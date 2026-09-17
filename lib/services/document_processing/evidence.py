"""Stable evidence identifiers and exact quote resolution."""
import hashlib
import json
from typing import Any


def evidence_id(source_file: str, chunk_index: int, text: str) -> str:
    payload = json.dumps([source_file, chunk_index, text], ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def resolve_citations(citations: Any, findings: list[dict]) -> list[dict]:
    if not isinstance(citations, list):
        raise ValueError("Citations must be a list")
    registry = {f["evidence_id"]: f for f in findings}
    result = []
    for citation in citations:
        if not isinstance(citation, dict):
            raise ValueError("Citation must be an object")
        finding = registry.get(citation.get("evidence_id"))
        if finding is None:
            raise ValueError("Unknown evidence identifier")
        excerpt = citation.get("excerpt")
        if not isinstance(excerpt, str) or not excerpt.strip() or excerpt not in finding["text_excerpt"]:
            raise ValueError("Quote is not an exact substring of the source evidence")
        explanation = citation.get("relation_explanation", "")
        if not isinstance(explanation, str):
            raise ValueError("Citation explanation must be a string")
        result.append({
            "evidence_id": finding["evidence_id"],
            "source_file": finding["source_file"],
            "chunk_index": finding.get("chunk_index", 0),
            "section_title": finding.get("section_title", ""),
            "section_path": finding.get("section_path", ""),
            "provenance": finding.get("provenance", {}),
            "excerpt": excerpt,
            "relation_type": finding["relation_type"],
            "relation_explanation": explanation,
        })
    return result
