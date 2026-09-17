"""Режим ``search`` — поиск релевантных фрагментов ВНД.

Реализация этапа 5: чистый LLM map-reduce.

Алгоритм:
1. ``prepare_vnd`` — извлечь все чанки ВНД через общий document pipeline.
2. **Map-фаза:** для каждого чанка — 1 LLM-вызов с промптом
   ``prompts/search_chunk_system.md``. LLM возвращает
   ``{relation_type, relevance_score, why_matches}``.
3. **Filter:** отбрасываем чанки с ``relevance_score < MIN_RELEVANCE_SCORE``.
4. **Re-rank:** сортируем по ``relevance_score`` (убывание), берём top-K
   (``TOP_K_CANDIDATES``).
5. Возвращаем JSON со списком ``vnd_findings`` + метаданными.

Single-flight защита предоставляется общим LLM boundary из ``lib/services``.

Skill-specific параметры (не вынесены в ``project.json::skills.*`` —
не поддерживаются ``SkillSettings(extra="forbid")``):
* ``TOP_K_CANDIDATES`` — сколько top-кандидатов передавать в synthesize;
* ``MIN_RELEVANCE_SCORE`` — порог отсечения слаборелевантных кандидатов.
"""

from __future__ import annotations

import math
from typing import Any
from lib.services.document_processing.evaluation import map_chunks
from lib.services.document_processing.evidence import evidence_id
from workspace.skills.audit_formulation_strengthener.scripts.skill_config import get_execution_config

from workspace.skills.audit_formulation_strengthener.scripts.llm_client import JsonParseError, call_llm_json
from workspace.skills.audit_formulation_strengthener.scripts.prompts import load_prompt, render_prompt
from workspace.skills.audit_formulation_strengthener.scripts.vnd_io import VndInputError, prepare_vnd
from workspace.skills.audit_formulation_strengthener.scripts import output as _output


__all__ = ["run"]


# Skill-specific параметры (см. docstring).
TOP_K_CANDIDATES: int = 10
MIN_RELEVANCE_SCORE: float = 0.3

_ALLOWED_RELATION_TYPES = frozenset({
    "прямое_противоречие",
    "прямое_подтверждение",
    "косвенное_отношение",
    "контекст",
    "нерелевантно",
})


def run(
    *,
    violation: str,
    vnd_paths: list[str],
    analyze_result_path: str | None = None,
    analyze_result: dict[str, Any] | None = None,
    estimate_only: bool = False,
    confirm: bool = False,
    max_chunks: int | None = None,
    prepared_bundle: Any = None,
) -> tuple[dict[str, Any], str | None]:
    """Поиск релевантных фрагментов ВНД (map-reduce через LLM).

    Args:
        violation: текст отклонения.
        vnd_paths: список путей к файлам ВНД.
        analyze_result_path: путь к кэшированному JSON результата analyze
            (для улучшения формулировки violation перед map-фазой).
        analyze_result: готовый результат analyze (in-memory).
        estimate_only: только оценка без LLM-вызовов.
        confirm: подтверждение для длинных ВНД (пока не используется —
            estimate-only достаточно для UX).
        max_chunks: override safety net на число чанков.

    Returns:
        ``(json_result, report_text_or_None)``.
    """
    # Валидация ввода.
    if not vnd_paths:
        return _output.make_error(
            "Не указаны файлы ВНД", error_type="no_vnd"
        ), None

    # Если передан analyze_result_path — загрузить для нормализованной формулировки.
    normalized_violation = _resolve_violation_text(
        violation=violation,
        analyze_result=analyze_result,
        analyze_result_path=analyze_result_path,
    )
    if not normalized_violation or not normalized_violation.strip():
        normalized_violation = violation

    # Подготовка ВНД.
    try:
        bundle = prepared_bundle or prepare_vnd(
            vnd_paths=vnd_paths,
            violation=violation,
        )
    except VndInputError as exc:
        return _output.make_error(exc.message, error_type=exc.error_type), None
    limit = max_chunks if max_chunks is not None else get_execution_config().get("max_chunks_for_execution")
    if limit is not None and (isinstance(limit, bool) or not isinstance(limit, int) or limit <= 0):
        return _output.make_error("Лимит чанков должен быть положительным целым числом", error_type="invalid_limit"), None
    needs_confirmation = limit is not None and len(bundle.chunks) > limit and not confirm

    # Estimate-only — без LLM.
    if estimate_only:
        return (
            {
                "status": "success",
                "data": {
                    "vnd_files": len(vnd_paths),
                    "vnd_chunks_total": len(bundle.chunks),
                    "confirmation_required": needs_confirmation,
                    "cache_key": bundle.cache_key,
                    "size_estimate": bundle.size_estimate,
                    "top_k_candidates": TOP_K_CANDIDATES,
                    "min_relevance_score": MIN_RELEVANCE_SCORE,
                    "map_batches_planned": len(bundle.chunks),
                    "synthesis_llm_calls_planned": 1,
                },
            },
            None,
        )

    if needs_confirmation:
        return {"status": "confirmation_required", "data": {
            "vnd_chunks_total": len(bundle.chunks), "max_chunks_for_execution": limit,
            "message": "Для обработки всех фрагментов требуется --confirm. Текст не усечён.",
        }}, None

    # === Map-фаза: по одному LLM-вызову на чанк ===
    try:
        template = load_prompt("search_chunk_system")
    except FileNotFoundError as exc:
        return _output.make_error(
            f"Не удалось загрузить промпт: {exc}",
            error_type="prompt_missing",
        ), None

    def evaluate(vnd_chunk: Any) -> dict[str, Any] | None:
        system = render_prompt(
            template,
            {
                "VIOLATION_TEXT": normalized_violation,
                "VND_FILE": vnd_chunk.source_file,
                "VND_SECTION": vnd_chunk.section_title
                or vnd_chunk.section_path
                or "(без заголовка)",
                "CHUNK_TEXT": vnd_chunk.text,
            },
        )
        parsed = call_llm_json(system=system, user=f"Отклонение: {normalized_violation}", operation="search_map")
        return _normalize_finding(parsed, vnd_chunk=vnd_chunk)

    mapped = map_chunks(bundle.chunks, evaluate)
    if mapped.failures:
        error = _output.make_error(
            "Не все фрагменты ВНД обработаны. Синтез отчёта заблокирован.",
            error_type="incomplete_search",
        )
        error["data"].update(chunks_processed=mapped.processed,
                             chunks_failed=len(mapped.failures), failed_chunks=mapped.failures)
        return error, None
    findings = [
        finding for finding in mapped.values
        if finding["relevance_score"] >= MIN_RELEVANCE_SCORE
        and finding["relation_type"] != "нерелевантно"
    ]
    chunks_processed = mapped.processed
    chunks_failed = 0

    # === Re-rank: сортировка по score, top-K ===
    findings.sort(key=lambda f: f["relevance_score"], reverse=True)
    top_findings = findings[:TOP_K_CANDIDATES]

    return (
        {
            "status": "success",
            "data": {
                "vnd_findings": top_findings,
                "vnd_chunks_total": len(bundle.chunks),
                "chunks_processed": chunks_processed,
                "chunks_failed": chunks_failed,
                "chunks_relevant_total": len(findings),
                "top_k_candidates": TOP_K_CANDIDATES,
                "min_relevance_score": MIN_RELEVANCE_SCORE,
                "cache_key": bundle.cache_key,
                "normalized_violation_used": normalized_violation,
            },
        },
        None,
    )


def _resolve_violation_text(
    *,
    violation: str,
    analyze_result: dict[str, Any] | None,
    analyze_result_path: str | None,
) -> str:
    """Получить нормализованную формулировку из analyze_result (если есть).

    Приоритет:
    1. ``analyze_result`` (in-memory, передан из `_run_all`).
    2. ``analyze_result_path`` (загрузить из файла).
    3. Исходный ``violation`` (fallback).
    """
    candidate: dict[str, Any] | None = analyze_result
    if candidate is None and analyze_result_path:
        try:
            import json as _json

            candidate = _json.loads(
                Path(analyze_result_path).read_text(encoding="utf-8")
            )
        except (OSError, ValueError):
            candidate = None

    if isinstance(candidate, dict):
        data = candidate.get("data") or {}
        normalized = data.get("normalized")
        if isinstance(normalized, str) and normalized.strip():
            return normalized
    return violation


def _normalize_finding(
    parsed: dict[str, Any],
    *,
    vnd_chunk: Any,
) -> dict[str, Any] | None:
    """Привести ответ LLM по одному чанку к финальному формату."""
    if not isinstance(parsed, dict):
        return None

    relation_type = str(parsed.get("relation_type") or "").strip()
    if relation_type not in _ALLOWED_RELATION_TYPES:
        # Не валидный тип — попробуем угадать по score.
        relation_type = "контекст"

    try:
        score = float(parsed.get("relevance_score"))
    except (TypeError, ValueError):
        return None
    if not math.isfinite(score) or not 0 <= score <= 1:
        return None
    # clamp 0..1
    score = max(0.0, min(1.0, score))

    why = parsed.get("why_matches") or ""
    if not isinstance(why, str):
        why = str(why)

    return {
        "evidence_id": evidence_id(vnd_chunk.source_file, vnd_chunk.index, vnd_chunk.text),
        "source_file": vnd_chunk.source_file,
        "chunk_index": vnd_chunk.index,
        "section_title": vnd_chunk.section_title,
        "section_path": vnd_chunk.section_path,
        "text_excerpt": vnd_chunk.text,
        "provenance": getattr(vnd_chunk, "provenance", {}),
        "relation_type": relation_type,
        "relevance_score": round(score, 3),
        "why_matches": why.strip(),
    }


def _truncate(text: str, *, max_chars: int) -> str:
    """Обрезать текст с маркером ``[TRUNCATED]``, если он длиннее ``max_chars``."""
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + "\n\n[TRUNCATED]"
