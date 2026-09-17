"""Domain models для audit_formulation_strengthener.

Это единственное место, где определяются структуры данных.
Все остальные модули переиспользуют legal_summarizer напрямую.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

VALID_SEVERITIES = {"высокая", "средняя", "низкая"}
VALID_RELATION_TYPES = {
    "прямое_противоречие",
    "прямое_подтверждение",
    "косвенное_отношение",
    "контекст",
    "нерелевантно",
}
MIN_RELEVANCE_SCORE = 0.3
TOP_K = 10


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------

class AFSError(Exception):
    """Base exception для всех ошибок skill'а."""

    error_type: str = "internal_error"

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class JsonParseError(AFSError):
    error_type = "json_parse_failed"


class EmptyViolationError(AFSError):
    error_type = "empty_violation"


class NoVndFilesError(AFSError):
    error_type = "no_vnd"


class VndNotFoundError(AFSError):
    error_type = "vnd_not_found"


class LLMError(AFSError):
    error_type = "llm_error"


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class AnalyzeResult:
    """Результат фазы analyze — нормализация отклонения."""

    normalized: str
    key_concepts: list[str]
    severity: str
    suggested_vnd_sections: list[str]
    raw_violation: str

    @classmethod
    def from_llm_response(cls, raw_violation: str, data: dict) -> AnalyzeResult:
        """Создать из ответа LLM с валидацией."""
        if not data.get("normalized"):
            raise JsonParseError("Missing 'normalized' field in LLM response")

        severity = _normalize_severity(data.get("severity"))
        key_concepts = _to_string_list(data.get("key_concepts", []))
        sections = _to_string_list(data.get("suggested_vnd_sections", []))

        return cls(
            normalized=data["normalized"].strip(),
            key_concepts=key_concepts,
            severity=severity,
            suggested_vnd_sections=sections,
            raw_violation=raw_violation,
        )

    def to_dict(self) -> dict:
        return {
            "normalized": self.normalized,
            "key_concepts": self.key_concepts,
            "severity": self.severity,
            "suggested_vnd_sections": self.suggested_vnd_sections,
        }


@dataclass
class Finding:
    """Один релевантный фрагмент ВНД."""

    source_file: str
    chunk_index: int
    section_title: str
    section_path: str
    text_excerpt: str
    relation_type: str
    relevance_score: float
    why_matches: str

    @classmethod
    def from_llm_response(
        cls,
        data: dict,
        *,
        source_file: str,
        chunk_index: int,
        section_title: str,
        section_path: str,
        chunk_text: str,
    ) -> Finding:
        """Создать из ответа LLM map-фазы."""
        relation_type = _normalize_relation(data.get("relation_type", "контекст"))
        score = _clamp(float(data.get("relevance_score", 0.0)), 0.0, 1.0)

        # excerpt — до 2000 символов из text_excerpt или chunk_text
        excerpt = (data.get("text_excerpt") or chunk_text)[:2000]

        return cls(
            source_file=source_file,
            chunk_index=chunk_index,
            section_title=section_title or "",
            section_path=section_path or "",
            text_excerpt=excerpt,
            relation_type=relation_type,
            relevance_score=round(score, 3),
            why_matches=data.get("why_matches", "")[:500],
        )

    def to_dict(self) -> dict:
        return {
            "source_file": self.source_file,
            "chunk_index": self.chunk_index,
            "section_title": self.section_title,
            "section_path": self.section_path,
            "text_excerpt": self.text_excerpt,
            "relation_type": self.relation_type,
            "relevance_score": self.relevance_score,
            "why_matches": self.why_matches,
        }


@dataclass
class SearchResult:
    """Результат фазы search — найденные фрагменты ВНД."""

    findings: list[Finding]
    chunks_total: int = 0
    chunks_processed: int = 0
    chunks_failed: int = 0

    @property
    def relevant_total(self) -> int:
        return len(self.findings)


@dataclass
class Report:
    """Финальный отчёт — результат synthesize-фазы."""

    title: str
    violation_summary: list[str]
    established_facts: list[str]
    deviation_analysis: list[str]
    vnd_citations: list[dict]
    verdict: dict
    recommended_formulation: list[str]
    date_iso: str
    normalized_violation: str
    severity: str
    source_findings_count: int

    @classmethod
    def from_llm_response(
        cls,
        data: dict,
        *,
        normalized_violation: str,
        severity: str,
        source_findings_count: int,
    ) -> Report:
        """Создать из ответа LLM."""
        # Валидация verdict.category
        verdict = data.get("verdict", {})
        category = _normalize_severity(verdict.get("category", severity))

        # Цитаты — только из переданных данных
        citations = []
        for c in data.get("vnd_citations", []):
            if isinstance(c, dict):
                citations.append({
                    "source_file": c.get("source_file", ""),
                    "section_title": c.get("section_title", ""),
                    "section_path": c.get("section_path", ""),
                    "excerpt": c.get("excerpt", "")[:500],
                    "relation_type": _normalize_relation(c.get("relation_type", "контекст")),
                    "relation_explanation": c.get("relation_explanation", "")[:300],
                })

        return cls(
            title=data.get("title", "Анализ отклонения")[:80],
            violation_summary=_to_string_list(data.get("violation_summary", [])),
            established_facts=_to_string_list(data.get("established_facts", [])),
            deviation_analysis=_to_string_list(data.get("deviation_analysis", [])),
            vnd_citations=citations,
            verdict={
                "category": category,
                "verdict_text": _to_string_list(verdict.get("verdict_text", [])),
            },
            recommended_formulation=_to_string_list(
                data.get("recommended_formulation", [])
            ),
            date_iso=datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            normalized_violation=normalized_violation,
            severity=severity,
            source_findings_count=source_findings_count,
        )

    def to_dict(self) -> dict:
        return {
            "title": self.title,
            "violation_summary": self.violation_summary,
            "established_facts": self.established_facts,
            "deviation_analysis": self.deviation_analysis,
            "vnd_citations": self.vnd_citations,
            "verdict": self.verdict,
            "recommended_formulation": self.recommended_formulation,
            "date_iso": self.date_iso,
            "normalized_violation": self.normalized_violation,
            "severity": self.severity,
            "source_findings_count": self.source_findings_count,
        }

    def to_markdown(self) -> str:
        """Рендер в markdown для пользователя."""
        lines = [
            f"# {self.title}",
            "",
            f"**Дата:** {self.date_iso}  **Категория тяжести:** {self.verdict['category']}",
            "",
            "## 1. Краткое изложение отклонения",
        ]
        for para in self.violation_summary:
            lines.append(f"\n{para}")

        lines.extend(["", "## 2. Установленные факты (по ВНД)"])
        for para in self.established_facts:
            lines.append(f"\n{para}")

        lines.extend(["", "## 3. Анализ отклонения"])
        for para in self.deviation_analysis:
            lines.append(f"\n{para}")

        lines.extend(["", "## 4. Релевантные фрагменты ВНД"])
        if self.vnd_citations:
            for i, c in enumerate(self.vnd_citations, 1):
                lines.extend([
                    f"### {i}. {c['section_title'] or 'Без названия раздела'}",
                    f"**Источник:** {c['source_file']}  **Тип соотнесения:** {c['relation_type']}",
                    f"> {c['excerpt']}",
                    f"\n{c['relation_explanation']}",
                    "",
                ])
        else:
            lines.append("\n_Релевантные фрагменты не найдены._")

        lines.extend([
            "",
            "## 5. Итоговая классификация",
        ])
        verdict_text = self.verdict.get("verdict_text", [])
        if verdict_text:
            for para in verdict_text:
                lines.append(f"\n{para}")
        else:
            lines.append(f"\n_Категория: {self.verdict['category']}_")

        lines.extend([
            "",
            "## 6. Рекомендуемая усиленная формулировка",
        ])
        for para in self.recommended_formulation:
            lines.append(f"\n{para}")

        lines.extend([
            "",
            "---",
            "_Отчёт сгенерирован skill'ом audit_formulation_strengthener._",
        ])

        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _normalize_severity(value: Any) -> str:
    """Привести severity к whitelist."""
    if isinstance(value, str) and value.lower() in VALID_SEVERITIES:
        return value.lower()
    return "средняя"


def _normalize_relation(value: Any) -> str:
    """Привести relation_type к whitelist."""
    if isinstance(value, str) and value in VALID_RELATION_TYPES:
        return value
    return "контекст"


def _clamp(value: float, min_val: float, max_val: float) -> float:
    """Ограничить значение диапазоном."""
    return max(min_val, min(max_val, value))


def _to_string_list(value: Any) -> list[str]:
    """Преобразовать в список строк, отфильтровав пустые."""
    if isinstance(value, list):
        return [str(v).strip() for v in value if str(v).strip()]
    return [str(value).strip()] if value else []
