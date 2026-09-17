"""Загрузка system-промптов для audit_formulation_strengthener.

Промпты хранятся рядом с этим файлом в директории prompts/.
Это единственное место, где определяются промпты.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from data import AnalyzeResult, Finding, SearchResult


# Директория с промптами — рядом с этим файлом
_PROMPTS_DIR = Path(__file__).parent / "prompts"


def _load_prompt(filename: str) -> str:
    """Загрузить промпт из файла."""
    path = _PROMPTS_DIR / filename
    if not path.exists():
        raise FileNotFoundError(f"Prompt not found: {path}")
    return path.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Промпты
# ---------------------------------------------------------------------------

def get_analyze_system_prompt() -> str:
    """System-промпт для analyze-фазы (нормализация отклонения)."""
    return _load_prompt("analyze.md")


def get_search_system_prompt() -> str:
    """System-промпт для search-фазы (оценка одного чанка)."""
    return _load_prompt("search_chunk.md")


def get_synthesize_system_prompt() -> str:
    """System-промпт для synthesize-фазы (финальный отчёт)."""
    return _load_prompt("synthesize.md")


# ---------------------------------------------------------------------------
# User messages
# ---------------------------------------------------------------------------

def build_analyze_user(violation: str) -> str:
    """Построить user message для analyze-фазы."""
    return f"""# ВХОДНАЯ ФОРМУЛИРОВКА ОТКЛОНЕНИЯ

{violation}"""


def build_search_user(
    violation: str,
    *,
    key_concepts: list[str],
    vnd_file: str,
    section_path: str,
    chunk_text: str,
) -> str:
    """Построить user message для search-фазы (оценка одного чанка)."""
    return f"""# ВХОДНЫЕ ДАННЫЕ ДЛЯ ОЦЕНКИ

## Формулировка отклонения

{violation}

## Ключевые концепты

{', '.join(key_concepts)}

## Фрагмент ВНД

**Файл:** {vnd_file}
**Раздел:** {section_path or 'без раздела'}

{chunk_text}"""


def build_synthesize_user(
    analyze: "AnalyzeResult",
    search: "SearchResult",
) -> str:
    """Построить user message для synthesize-фазы."""
    findings_json = json.dumps(
        [f.to_dict() for f in search.findings],
        ensure_ascii=False,
        indent=2,
    )
    concepts_json = json.dumps(analyze.key_concepts, ensure_ascii=False)

    return f"""# ВХОДНЫЕ ДАННЫЕ ДЛЯ СИНТЕЗА

## Нормализованная формулировка отклонения

{analyze.normalized}

## Категория тяжести (от analyze-фазы)

{analyze.severity}

## Ключевые концепты

{concepts_json}

## Релевантные фрагменты ВНД (от search-фазы)

{findings_json}"""
