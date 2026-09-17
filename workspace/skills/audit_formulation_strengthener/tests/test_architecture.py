"""Границы архитектуры skill-а audit_formulation_strengthener."""

from __future__ import annotations

from pathlib import Path


SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"


def test_skill_does_not_depend_on_legal_summarizer() -> None:
    """Skill использует общие сервисы, а не код другого skill-а."""
    references = [
        path
        for path in SCRIPTS_DIR.rglob("*.py")
        if "legal_summarizer" in path.read_text(encoding="utf-8")
    ]
    assert references == []


def test_only_direct_cli_bootstraps_package_imports() -> None:
    """Внутренние модули не изменяют import path процесса."""
    path_mutators = [
        path.relative_to(SCRIPTS_DIR)
        for path in SCRIPTS_DIR.rglob("*.py")
        if path.name != "cli.py" and "sys.path" in path.read_text(encoding="utf-8")
    ]
    assert path_mutators == []
