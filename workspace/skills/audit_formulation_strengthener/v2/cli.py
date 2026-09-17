#!/usr/bin/env python3
"""CLI для audit_formulation_strengthener.

Usage:
    python cli.py --violation "текст отклонения" --vnd path/to/vnd.pdf

    # Полный pipeline
    python cli.py --violation "..." --vnd vnd.pdf --output report.md

    # Только analyze
    python cli.py --mode analyze --violation "..."

    # Resume из кэшированных результатов
    python cli.py --mode synthesize --analyze-result a.json --search-result s.json
"""

from __future__ import annotations

import argparse
import json
import sys
import traceback
from pathlib import Path
from typing import Any

# Добавляем пути для импорта orchestrator
_SKILL_ROOT = Path(__file__).parent
_REPO_ROOT = _SKILL_ROOT.parent.parent.parent
_SKILL_V2 = str(_SKILL_ROOT / "v2")

for _p in (_REPO_ROOT, _SKILL_V2):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from data import (
    AnalyzeResult,
    Finding,
    Report,
    SearchResult,
)
from orchestrator import AuditFormulationStrengthener


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

MODES = ("analyze", "search", "synthesize", "all")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="audit_formulation_strengthener",
        description="Усиление формулировки отклонения по ВНД.",
    )
    parser.add_argument(
        "--violation",
        required=True,
        help="Текст отклонения",
    )
    parser.add_argument(
        "--vnd",
        action="append",
        dest="vnd_paths",
        help="Путь к файлу ВНД (.pdf/.docx/.txt)",
    )
    parser.add_argument(
        "--mode",
        choices=MODES,
        default="all",
        help="Режим работы",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Путь к файлу отчёта",
    )
    parser.add_argument(
        "--internal-format",
        choices=("json", "report"),
        default="report",
        help="Формат вывода",
    )
    parser.add_argument(
        "--analyze-result",
        help="Путь к кэшированному результату analyze (JSON)",
    )
    parser.add_argument(
        "--search-result",
        help="Путь к кэшированному результату search (JSON)",
    )
    return parser


def _load_analyze_result(path: str | None) -> AnalyzeResult | None:
    if path is None:
        return None
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return AnalyzeResult.from_llm_response(
        data["raw_violation"] if "raw_violation" in data else "",
        data,
    )


def _load_search_result(path: str | None) -> SearchResult | None:
    if path is None:
        return None
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    findings = [
        Finding(**f) for f in data.get("findings", [])
    ]
    return SearchResult(
        findings=findings,
        chunks_total=data.get("chunks_total", 0),
        chunks_processed=data.get("chunks_processed", 0),
        chunks_failed=data.get("chunks_failed", 0),
    )


def _save_json(data: dict, path: str) -> None:
    Path(path).write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    orchestrator = AuditFormulationStrengthener()

    try:
        if args.mode == "analyze":
            result = orchestrator.analyze(args.violation)
            output = result.to_dict()
            if args.output:
                _save_json(output, args.output)
            else:
                print(json.dumps(output, ensure_ascii=False, indent=2))

        elif args.mode == "search":
            if not args.vnd_paths:
                print("Error: --vnd required for search mode", file=sys.stderr)
                return 2
            analyze_result = _load_analyze_result(args.analyze_result)
            result = orchestrator.search(args.violation, args.vnd_paths, analyze_result)
            output = {
                "findings": [f.to_dict() for f in result.findings],
                "chunks_total": result.chunks_total,
                "chunks_processed": result.chunks_processed,
                "chunks_failed": result.chunks_failed,
            }
            if args.output:
                _save_json(output, args.output)
            else:
                print(json.dumps(output, ensure_ascii=False, indent=2))

        elif args.mode == "synthesize":
            analyze_result = _load_analyze_result(args.analyze_result)
            search_result = _load_search_result(args.search_result)
            if analyze_result is None or search_result is None:
                print("Error: --analyze-result and --search-result required for synthesize", 
                      file=sys.stderr)
                return 2
            result = orchestrator.synthesize(
                args.violation, analyze_result, search_result
            )
            output = result.to_dict()
            if args.output:
                _save_json(output, args.output)
            else:
                print(json.dumps(output, ensure_ascii=False, indent=2))

        elif args.mode == "all":
            if not args.vnd_paths:
                print("Error: --vnd required for all mode", file=sys.stderr)
                return 2
            analyze_result, search_result, report = orchestrator.run_all(
                args.violation, args.vnd_paths
            )

            if args.internal_format == "json":
                output = report.to_dict()
                if args.output:
                    _save_json(output, args.output)
                else:
                    print(json.dumps(output, ensure_ascii=False, indent=2))
            else:
                markdown = report.to_markdown()
                if args.output:
                    Path(args.output).write_text(markdown, encoding="utf-8")
                else:
                    print(markdown)

        return 0

    except Exception as exc:
        tb = traceback.format_exc()
        error_output = {
            "status": "error",
            "error_type": getattr(exc, "error_type", "internal_error"),
            "message": f"{exc!r}\n{tb}",
        }
        print(json.dumps(error_output, ensure_ascii=False, indent=2), 
              file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
