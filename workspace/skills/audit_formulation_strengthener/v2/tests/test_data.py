"""Tests для data.py."""

from __future__ import annotations

import pytest

from data import (
    AnalyzeResult,
    EmptyViolationError,
    Finding,
    JsonParseError,
    Report,
    SearchResult,
    _normalize_relation,
    _normalize_severity,
    _clamp,
)


class TestNormalizeSeverity:
    def test_valid_severity(self):
        assert _normalize_severity("высокая") == "высокая"
        assert _normalize_severity("средняя") == "средняя"
        assert _normalize_severity("низкая") == "низкая"

    def test_invalid_severity_defaults_to_medium(self):
        assert _normalize_severity("высшая") == "средняя"
        assert _normalize_severity("") == "средняя"
        assert _normalize_severity(None) == "средняя"
        assert _normalize_severity(123) == "средняя"


class TestNormalizeRelation:
    def test_valid_relation(self):
        assert _normalize_relation("прямое_противоречие") == "прямое_противоречие"
        assert _normalize_relation("контекст") == "контекст"

    def test_invalid_relation_defaults_to_context(self):
        assert _normalize_relation("неверный") == "контекст"
        assert _normalize_relation("") == "контекст"


class TestClamp:
    def test_within_bounds(self):
        assert _clamp(0.5, 0.0, 1.0) == 0.5

    def test_above_max(self):
        assert _clamp(1.5, 0.0, 1.0) == 1.0

    def test_below_min(self):
        assert _clamp(-0.5, 0.0, 1.0) == 0.0


class TestAnalyzeResult:
    def test_from_llm_response(self, sample_analyze_response, sample_violation):
        result = AnalyzeResult.from_llm_response(
            sample_violation, sample_analyze_response
        )
        assert result.normalized == sample_analyze_response["normalized"]
        assert result.key_concepts == sample_analyze_response["key_concepts"]
        assert result.severity == "высокая"
        assert result.raw_violation == sample_violation

    def test_from_llm_response_missing_normalized_raises(self, sample_violation):
        with pytest.raises(JsonParseError):
            AnalyzeResult.from_llm_response(sample_violation, {})

    def test_to_dict(self, sample_analyze_response, sample_violation):
        result = AnalyzeResult.from_llm_response(
            sample_violation, sample_analyze_response
        )
        d = result.to_dict()
        assert d["normalized"] == sample_analyze_response["normalized"]
        assert "severity" in d


class TestFinding:
    def test_from_llm_response(self, sample_search_response, sample_chunk):
        finding = Finding.from_llm_response(
            sample_search_response,
            source_file="vnd1.txt",
            chunk_index=0,
            section_title="5.4",
            section_path="5 / 5.4",
            chunk_text=sample_chunk.text,
        )
        assert finding.source_file == "vnd1.txt"
        assert finding.relation_type == "прямое_противоречие"
        assert finding.relevance_score == 0.85

    def test_to_dict(self, sample_search_response, sample_chunk):
        finding = Finding.from_llm_response(
            sample_search_response,
            source_file="vnd1.txt",
            chunk_index=0,
            section_title="5.4",
            section_path="5 / 5.4",
            chunk_text=sample_chunk.text,
        )
        d = finding.to_dict()
        assert d["source_file"] == "vnd1.txt"
        assert "relevance_score" in d


class TestSearchResult:
    def test_relevant_total(self, sample_search_response, sample_chunk):
        finding = Finding.from_llm_response(
            sample_search_response,
            source_file="vnd1.txt",
            chunk_index=0,
            section_title="5.4",
            section_path="5 / 5.4",
            chunk_text=sample_chunk.text,
        )
        result = SearchResult(
            findings=[finding],
            chunks_total=1,
            chunks_processed=1,
            chunks_failed=0,
        )
        assert result.relevant_total == 1


class TestReport:
    def test_from_llm_response(
        self, sample_synthesize_response, sample_analyze_response, sample_violation
    ):
        analyze = AnalyzeResult.from_llm_response(
            sample_violation, sample_analyze_response
        )
        report = Report.from_llm_response(
            sample_synthesize_response,
            normalized_violation=analyze.normalized,
            severity=analyze.severity,
            source_findings_count=1,
        )
        assert report.title == sample_synthesize_response["title"]
        assert len(report.violation_summary) == 2
        assert len(report.vnd_citations) == 1

    def test_to_markdown(self, sample_synthesize_response, sample_analyze_response, sample_violation):
        analyze = AnalyzeResult.from_llm_response(
            sample_violation, sample_analyze_response
        )
        report = Report.from_llm_response(
            sample_synthesize_response,
            normalized_violation=analyze.normalized,
            severity=analyze.severity,
            source_findings_count=1,
        )
        md = report.to_markdown()
        assert "#" in md
        assert "Срок хранения" in md
        assert "5.4 Сроки хранения" in md
