"""Orchestrator для audit_formulation_strengthener.

Единственный production Python файл с бизнес-логикой.
Всё остальное переиспользуется из legal_summarizer.

Pipeline:
    analyze (1 LLM) → search (N LLM, map-reduce) → synthesize (1 LLM)
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from data import AnalyzeResult, Report, SearchResult


# ---------------------------------------------------------------------------
# Setup: добавляем пути для импортов из legal_summarizer
# ---------------------------------------------------------------------------

_SKILL_ROOT = Path(__file__).parent
_REPO_ROOT = _SKILL_ROOT.parent.parent.parent  # workspaces_nanobot
_LEGAL_SUMMARIZER_SCRIPTS = str(
    _REPO_ROOT / "workspace" / "skills" / "legal_summarizer" / "scripts"
)

for _p in (_REPO_ROOT, _LEGAL_SUMMARIZER_SCRIPTS):
    if _p not in sys.path:
        sys.path.insert(0, _p)


# ---------------------------------------------------------------------------
# Lazy imports — импортируем внутри функций, чтобы тесты могли замокать
# ---------------------------------------------------------------------------

def _get_llm():
    """Lazy import для LLM."""
    from legal_summarizer.scripts.llm.calls import chat_locked
    return chat_locked


def _get_chunking():
    """Lazy import для chunking."""
    from legal_summarizer.scripts.chunking.chunks import Chunk
    from legal_summarizer.scripts.application import run_canonical_pipeline
    return Chunk, run_canonical_pipeline


# ---------------------------------------------------------------------------
# Imports из skill
# ---------------------------------------------------------------------------

from data import (
    AnalyzeResult,
    EmptyViolationError,
    Finding,
    JsonParseError,
    LLMError,
    NoVndFilesError,
    Report,
    SearchResult,
    TOP_K,
    MIN_RELEVANCE_SCORE,
)
from prompts_loader import (
    get_analyze_system_prompt,
    get_search_system_prompt,
    get_synthesize_system_prompt,
    build_analyze_user,
    build_search_user,
    build_synthesize_user,
)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MAX_RETRIES = 3


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

class AuditFormulationStrengthener:
    """Orchestrator для усиления формулировок отклонений."""

    def __init__(self, workspace_root: Path | str | None = None):
        """
        Args:
            workspace_root: корень workspace для кэширования документов.
        """
        self.workspace_root = Path(workspace_root) if workspace_root else None

    # -------------------------------------------------------------------------
    # Public API
    # -------------------------------------------------------------------------

    def analyze(self, violation: str) -> AnalyzeResult:
        """Фаза 1: нормализация отклонения.

        Args:
            violation: текст отклонения от аудитора.

        Returns:
            AnalyzeResult с нормализованной формулировкой.

        Raises:
            EmptyViolationError: violation пустой.
            JsonParseError: LLM вернул невалидный JSON.
            LLMError: ошибка при вызове LLM.
        """
        violation = (violation or "").strip()
        if not violation:
            raise EmptyViolationError("Violation text is empty")

        system = get_analyze_system_prompt()
        user = build_analyze_user(violation)

        response = self._call_llm_json(system, user)
        return AnalyzeResult.from_llm_response(violation, response)

    def search(
        self,
        violation: str,
        vnd_paths: list[str],
        analyze_result: AnalyzeResult | None = None,
    ) -> SearchResult:
        """Фаза 2: поиск релевантных фрагментов ВНД.

        Args:
            violation: текст отклонения.
            vnd_paths: список путей к файлам ВНД.
            analyze_result: результат analyze (для ключевых концептов).

        Returns:
            SearchResult со списком найденных фрагментов.

        Raises:
            NoVndFilesError: vnd_paths пуст.
            JsonParseError: LLM вернул невалидный JSON.
            LLMError: ошибка при вызове LLM.
        """
        if not vnd_paths:
            raise NoVndFilesError("No VND files provided")

        # Используем analyze_result или делаем analyze
        if analyze_result is None:
            analyze_result = self.analyze(violation)

        # Lazy imports
        Chunk, run_canonical_pipeline = _get_chunking()

        # Собираем все чанки из всех файлов
        all_chunks: list[tuple[str, Any]] = []
        for vnd_path in vnd_paths:
            path = Path(vnd_path)
            if not path.exists():
                raise FileNotFoundError(f"VND file not found: {vnd_path}")

            result = run_canonical_pipeline(
                str(path),
                include_retrieval_index=False,
                workspace_root=str(self.workspace_root) if self.workspace_root else None,
            )
            for chunk in result.chunks:
                all_chunks.append((str(path), chunk))

        chunks_total = len(all_chunks)

        # Map phase: оценка каждого чанка
        findings: list[Finding] = []
        chunks_processed = 0
        chunks_failed = 0

        system = get_search_system_prompt()

        for vnd_file, chunk in all_chunks:
            chunks_processed += 1

            user = build_search_user(
                violation,
                key_concepts=analyze_result.key_concepts,
                vnd_file=vnd_file,
                section_path=chunk.section_path or "",
                chunk_text=chunk.text,
            )

            try:
                response = self._call_llm_json(system, user)
                finding = Finding.from_llm_response(
                    response,
                    source_file=vnd_file,
                    chunk_index=chunk.index,
                    section_title=chunk.section_title or "",
                    section_path=chunk.section_path or "",
                    chunk_text=chunk.text,
                )

                # Включаем только если score >= MIN_RELEVANCE_SCORE
                if finding.relevance_score >= MIN_RELEVANCE_SCORE:
                    findings.append(finding)

            except (JsonParseError, LLMError):
                chunks_failed += 1
                continue

        # Reduce phase: top-K по relevance_score
        findings.sort(key=lambda f: f.relevance_score, reverse=True)
        findings = findings[:TOP_K]

        return SearchResult(
            findings=findings,
            chunks_total=chunks_total,
            chunks_processed=chunks_processed,
            chunks_failed=chunks_failed,
        )

    def synthesize(
        self,
        violation: str,
        analyze_result: AnalyzeResult,
        search_result: SearchResult,
    ) -> Report:
        """Фаза 3: финальный отчёт.

        Args:
            violation: текст отклонения (для отладки).
            analyze_result: результат analyze-фазы.
            search_result: результат search-фазы.

        Returns:
            Report с финальным отчётом.

        Raises:
            JsonParseError: LLM вернул невалидный JSON.
            LLMError: ошибка при вызове LLM.
        """
        system = get_synthesize_system_prompt()
        user = build_synthesize_user(analyze_result, search_result)

        response = self._call_llm_json(system, user)
        return Report.from_llm_response(
            response,
            normalized_violation=analyze_result.normalized,
            severity=analyze_result.severity,
            source_findings_count=len(search_result.findings),
        )

    def run_all(
        self,
        violation: str,
        vnd_paths: list[str],
    ) -> tuple[AnalyzeResult, SearchResult, Report]:
        """Полный pipeline: analyze → search → synthesize.

        Args:
            violation: текст отклонения.
            vnd_paths: список путей к файлам ВНД.

        Returns:
            tuple (analyze_result, search_result, report).
        """
        analyze_result = self.analyze(violation)
        search_result = self.search(violation, vnd_paths, analyze_result)
        report = self.synthesize(violation, analyze_result, search_result)
        return analyze_result, search_result, report

    # -------------------------------------------------------------------------
    # Internal
    # -------------------------------------------------------------------------

    def _call_llm_json(self, system: str, user: str) -> dict:
        """LLM-вызов с retry на JSON parse error.

        Args:
            system: system prompt.
            user: user message.

        Returns:
            parsed JSON dict.

        Raises:
            JsonParseError: после MAX_RETRIES попыток.
            LLMError: сетевая/системная ошибка.
        """
        # Lazy import для возможности мока в тестах
        chat_locked = _get_llm()

        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]

        for attempt in range(MAX_RETRIES):
            try:
                response = chat_locked(messages)
                return json.loads(response)
            except json.JSONDecodeError as e:
                if attempt == MAX_RETRIES - 1:
                    raise JsonParseError(f"Invalid JSON after {MAX_RETRIES} attempts: {e}")
                continue
            except Exception as e:
                raise LLMError(f"LLM call failed: {e}")


# ---------------------------------------------------------------------------
# Convenience functions
# ---------------------------------------------------------------------------

def analyze(violation: str) -> AnalyzeResult:
    """Analyze-only: нормализация отклонения."""
    orchestrator = AuditFormulationStrengthener()
    return orchestrator.analyze(violation)


def search(
    violation: str,
    vnd_paths: list[str],
    analyze_result: AnalyzeResult | None = None,
) -> SearchResult:
    """Search-only: поиск фрагментов ВНД."""
    orchestrator = AuditFormulationStrengthener()
    return orchestrator.search(violation, vnd_paths, analyze_result)


def synthesize(
    violation: str,
    analyze_result: AnalyzeResult,
    search_result: SearchResult,
) -> Report:
    """Synthesize-only: финальный отчёт."""
    orchestrator = AuditFormulationStrengthener()
    return orchestrator.synthesize(violation, analyze_result, search_result)


def run_all(
    violation: str,
    vnd_paths: list[str],
) -> tuple[AnalyzeResult, SearchResult, Report]:
    """Полный pipeline."""
    orchestrator = AuditFormulationStrengthener()
    return orchestrator.run_all(violation, vnd_paths)
