"""VND adapter for the shared canonical document pipeline."""
from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from lib.services.document_processing.application.pipeline_structure import run_canonical_pipeline
from lib.services.document_processing.chunking.chunks import Chunk
from lib.services.document_processing.retrieval.provenance import build_provenance_chain
from workspace.skills.audit_formulation_strengthener.scripts.skill_config import get_chunking_config


@dataclass(frozen=True)
class VndChunk:
    source_file: str
    index: int
    text: str
    section_title: str
    section_path: str
    token_estimate: int
    document_id: str = ""
    chunk_id: str = ""
    provenance: dict[str, Any] = field(default_factory=dict)


def extract_vnd_chunks(vnd_paths: list[str], *, max_chunks_per_file: int | None = None) -> list[VndChunk]:
    if max_chunks_per_file is not None and max_chunks_per_file <= 0:
        raise RuntimeError("Лимит чанков должен быть положительным")
    out = []
    for path_str in vnd_paths:
        path = Path(path_str)
        if not path.is_file():
            raise FileNotFoundError(f"Файл ВНД не найден: {path}")
        try:
            result = run_canonical_pipeline(path, include_retrieval_index=False,
                                            chunking_config=get_chunking_config())
        except Exception as exc:
            raise RuntimeError(f"Не удалось обработать ВНД '{path}': {exc}") from exc
        if not result.chunks:
            raise RuntimeError(f"ВНД '{path}' не содержит извлекаемого текста")
        if max_chunks_per_file is not None and len(result.chunks) > max_chunks_per_file:
            raise RuntimeError(
                f"ВНД '{path}' содержит {len(result.chunks)} чанков при лимите "
                f"{max_chunks_per_file}. Текст не был усечён; увеличьте лимит."
            )
        for ch in result.chunks:
            chain = build_provenance_chain(
                ch, doc=result.analysis.physical, struct=result.analysis.structure,
                document_id=result.analysis.identity.document_id,
            )
            if chain is None:
                raise RuntimeError(f"Не удалось установить источник чанка {ch.chunk_id}")
            out.append(VndChunk(
                source_file=str(path), index=ch.index, text=ch.text,
                section_title=chain.section_title, section_path=chain.section_path,
                token_estimate=ch.token_estimate,
                document_id=chain.document_id, chunk_id=ch.chunk_id,
                provenance=chain.to_dict(),
            ))
    return out


def estimate_vnd_size(vnd_paths: list[str]) -> dict[str, Any]:
    return estimate_chunks(extract_vnd_chunks(vnd_paths), len(vnd_paths))


def estimate_chunks(chunks: list[VndChunk], file_count: int) -> dict[str, Any]:
    total_chars = sum(len(ch.text) for ch in chunks)
    return {
        "vnd_files": file_count, "total_chars": total_chars,
        "total_pages_estimated": max(1, (total_chars + 2999) // 3000),
        "chunks_estimated": len(chunks), "map_batches_planned": len(chunks),
    }