"""Тесты CLI-обёртки ``scripts/cli.py``.

Тестируем через прямой вызов ``main(argv)`` — это позволяет
использовать моки для LLM и не дёргать subprocess.
"""

from __future__ import annotations

import io
import json
from contextlib import redirect_stdout
from pathlib import Path
from typing import Any

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _run_cli(
    *argv: str,
    monkeypatch: pytest.MonkeyPatch,
    llm_mock: Any,
    prepare_vnd_mock: Any | None = None,
) -> tuple[int, str]:
    """Запустить CLI с моками, вернуть (returncode, stdout)."""
    from workspace.skills.audit_formulation_strengthener.scripts import cli as cli_mod
    from workspace.skills.audit_formulation_strengthener.scripts.modes import (
        analyze,
        search,
        synthesize,
    )

    for mode_module in (analyze, search, synthesize):
        monkeypatch.setattr(mode_module, "call_llm_json", llm_mock)

    # Подменяем prepare_vnd в том же модуле, который использует search.
    if prepare_vnd_mock is not None:
        monkeypatch.setattr(search, "prepare_vnd", prepare_vnd_mock)

    # Перехватываем stdout.
    buf = io.StringIO()
    with redirect_stdout(buf):
        try:
            rc = cli_mod.main(list(argv))
        except SystemExit as exc:
            rc = exc.code if isinstance(exc.code, int) else 1
    return rc, buf.getvalue()


def _all_mock(system, user, operation):
    """Единый мок для всех трёх операций."""
    if operation == "analyze":
        return {
            "normalized": "В организации установлен срок хранения ПДн — 1 год.",
            "key_concepts": ["срок хранения", "ПДн"],
            "severity": "высокая",
            "suggested_vnd_sections": ["Сроки хранения ПДн"],
        }
    if operation == "search_map":
        return {
            "relation_type": "прямое_противоречие",
            "relevance_score": 0.9,
            "why_matches": "Прямое противоречие.",
        }
    if operation == "synthesize":
        result = {
            "title": "Анализ отклонения",
            "violation_summary": ["Нормализованный текст."],
            "established_facts": ["Установлено."],
            "deviation_analysis": ["Анализ."],
            "vnd_citations": [],
            "verdict": {"category": "высокая", "verdict_text": ["Итог."]},
            "recommended_formulation": ["Рекомендация."],
        }
        findings = json.loads(
            system.rsplit("## Релевантные фрагменты ВНД (от search-фазы)", 1)[1]
        )
        if findings:
            evidence = findings[0]
            result["vnd_citations"] = [{
                "evidence_id": evidence["evidence_id"],
                "excerpt": evidence["text_excerpt"],
                "relation_explanation": "Прямое противоречие.",
            }]
        return result
    raise RuntimeError(f"unexpected op: {operation}")


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_cli_analyze_mode(
    monkeypatch: pytest.MonkeyPatch, mock_prepare_vnd: Any
) -> None:
    """``--mode analyze`` → JSON-вывод с data.normalized."""
    # Подготовить моки: search_map НЕ должен вызываться.
    called = {"analyze": 0, "search": 0, "synth": 0}

    def counting(system, user, operation):
        if operation == "analyze":
            called["analyze"] += 1
        elif operation == "search_map":
            called["search"] += 1
        elif operation == "synthesize":
            called["synth"] += 1
        return _all_mock(system, user, operation)

    rc, out = _run_cli(
        "--mode", "analyze",
        "--violation", "Срок хранения ПДн — 1 год",
        monkeypatch=monkeypatch,
        llm_mock=counting,
        prepare_vnd_mock=mock_prepare_vnd,
    )

    assert rc == 0
    parsed = json.loads(out)
    assert parsed["status"] == "success"
    assert parsed["data"]["normalized"].startswith("В организации")
    assert called["analyze"] == 1
    assert called["search"] == 0
    assert called["synth"] == 0


def test_cli_estimate_only(
    monkeypatch: pytest.MonkeyPatch, mock_prepare_vnd: Any, tmp_vnd_files: list[str]
) -> None:
    """``--estimate-only`` → без LLM-вызовов."""
    called = {"any": 0}

    def counting(system, user, operation):
        called["any"] += 1
        return _all_mock(system, user, operation)

    rc, out = _run_cli(
        "--mode", "all",
        "--violation", "...",
        "--vnd", tmp_vnd_files[0],
        "--estimate-only",
        monkeypatch=monkeypatch,
        llm_mock=counting,
        prepare_vnd_mock=mock_prepare_vnd,
    )

    assert rc == 0
    assert called["any"] == 0  # нет LLM-вызовов при --estimate-only
    parsed = json.loads(out)
    assert parsed["status"] == "success"
    assert "llm_calls_planned" in parsed["data"] or "vnd_chunks_total" in parsed["data"]


def test_cli_no_vnd(monkeypatch: pytest.MonkeyPatch) -> None:
    """Без ``--vnd`` → ошибка exit-code 2."""
    called: list[str] = []

    def counting(system, user, operation):
        called.append(operation)
        return _all_mock(system, user, operation)

    rc, out = _run_cli(
        "--mode", "search",
        "--violation", "что-то",
        monkeypatch=monkeypatch,
        llm_mock=counting,
    )

    assert rc == 2
    assert out == ""
    assert called == []  # LLM не вызывался


def test_cli_empty_violation(
    monkeypatch: pytest.MonkeyPatch, mock_prepare_vnd: Any
) -> None:
    """Пустой ``--violation`` → ошибка ``empty_violation``."""
    called: list[str] = []

    def counting(system, user, operation):
        called.append(operation)
        return _all_mock(system, user, operation)

    rc, out = _run_cli(
        "--mode", "analyze",
        "--violation", "",
        monkeypatch=monkeypatch,
        llm_mock=counting,
        prepare_vnd_mock=mock_prepare_vnd,
    )

    assert rc == 2
    parsed = json.loads(out)
    assert parsed["data"]["error_type"] == "empty_violation"
    assert called == []


def test_cli_all_mode_saves_report(
    monkeypatch: pytest.MonkeyPatch,
    mock_prepare_vnd: Any,
    tmp_path: Path,
    tmp_vnd_files: list[str],
) -> None:
    """``--mode all --output <path>`` → сохраняет файл."""
    output_file = tmp_path / "report.md"

    rc, out = _run_cli(
        "--mode", "all",
        "--violation", "что-то",
        "--vnd", tmp_vnd_files[0],
        "--output", str(output_file),
        "--output-format", "md",
        monkeypatch=monkeypatch,
        llm_mock=_all_mock,
        prepare_vnd_mock=mock_prepare_vnd,
    )

    assert rc == 0
    parsed = json.loads(out)
    assert parsed["status"] == "success"
    assert parsed.get("saved_to") == str(output_file)
    assert output_file.exists()
    assert "Анализ отклонения" in output_file.read_text(encoding="utf-8")


def test_cli_default_mode_is_all(
    monkeypatch: pytest.MonkeyPatch, mock_prepare_vnd: Any, tmp_vnd_files: list[str]
) -> None:
    """Без ``--mode`` → ``all`` (по умолчанию)."""
    called = {"search_map": 0}

    def counting(system, user, operation):
        if operation == "search_map":
            called["search_map"] += 1
        return _all_mock(system, user, operation)

    rc, out = _run_cli(
        "--violation", "текст",
        "--vnd", tmp_vnd_files[0],
        "--output-format", "md",
        monkeypatch=monkeypatch,
        llm_mock=counting,
        prepare_vnd_mock=mock_prepare_vnd,
    )

    assert rc == 0
    assert called["search_map"] >= 1  # search был запущен
