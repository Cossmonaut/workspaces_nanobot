"""Test fixtures для v2."""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


# ---------------------------------------------------------------------------
# Setup: добавляем пути для импортов
# ---------------------------------------------------------------------------

def _ensure_paths() -> None:
    """Добавить пути для импортов."""
    # v2/ directory
    v2_dir = Path(__file__).parent.parent
    # skill root
    skill_root = v2_dir.parent
    # workspace/
    workspace = skill_root.parent
    # workspaces_nanobot/
    repo_root = workspace.parent.parent
    
    legal_summarizer_scripts = str(
        repo_root / "workspace" / "skills" / "legal_summarizer" / "scripts"
    )
    repo_root_str = str(repo_root)
    v2_dir_str = str(v2_dir)
    workspace_str = str(workspace)

    for p in (repo_root_str, legal_summarizer_scripts, v2_dir_str, workspace_str):
        if p not in sys.path:
            sys.path.insert(0, p)


_ensure_paths()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def sample_violation() -> str:
    return "Срок хранения персональных данных установлен 1 год"


@pytest.fixture
def sample_analyze_response() -> dict:
    return {
        "normalized": "В организации установлен срок хранения персональных данных, составляющий один год.",
        "key_concepts": ["срок хранения", "персональные данные", "1 год"],
        "severity": "высокая",
        "suggested_vnd_sections": ["Сроки хранения ПДн"],
    }


@pytest.fixture
def sample_search_response() -> dict:
    return {
        "relation_type": "прямое_противоречие",
        "relevance_score": 0.85,
        "why_matches": "ВНД требует срок хранения 5 лет, отклонение фиксирует 1 год.",
        "text_excerpt": "Срок хранения персональных данных должен составлять не менее пяти лет.",
    }


@pytest.fixture
def sample_synthesize_response() -> dict:
    return {
        "title": "Анализ отклонения: срок хранения персональных данных",
        "violation_summary": [
            "В организации установлен срок хранения персональных данных, составляющий один год.",
            "Нарушение классифицировано как высокой степени тяжести.",
        ],
        "established_facts": [
            "Согласно п. 5.4 ВНД, срок хранения персональных данных должен составлять не менее пяти лет.",
        ],
        "deviation_analysis": [
            "Установленный срок хранения (1 год) не соответствует требованиям ВНД (5 лет).",
        ],
        "vnd_citations": [
            {
                "source_file": "vnd1.txt",
                "section_title": "5.4 Сроки хранения",
                "section_path": "5 / 5.4",
                "excerpt": "Срок хранения персональных данных должен составлять не менее пяти лет.",
                "relation_type": "прямое_противоречие",
                "relation_explanation": "Отклонение фиксирует срок 1 год, что противоречит требованию 5 лет.",
            }
        ],
        "verdict": {
            "category": "высокая",
            "verdict_text": [
                "Выявлено несоответствие между фактическим сроком хранения и требованиями ВНД.",
            ],
        },
        "recommended_formulation": [
            "В ходе проверки установлено, что срок хранения персональных данных составляет один год, "
            "что не соответствует требованиям п. 5.4 ВНД, согласно которому срок хранения должен "
            "составлять не менее пяти лет.",
        ],
    }


@pytest.fixture
def sample_chunk() -> SimpleNamespace:
    """Mock Chunk object."""
    return SimpleNamespace(
        index=0,
        text="Срок хранения персональных данных должен составлять не менее пяти лет. (п. 5.4)",
        section_title="5.4 Сроки хранения",
        section_path="5 / 5.4 Сроки хранения",
        token_estimate=50,
    )
