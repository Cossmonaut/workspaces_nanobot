"""Reusable sequential map execution with explicit completeness accounting."""
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable


@dataclass
class MapResult:
    values: list[Any] = field(default_factory=list)
    failures: list[dict[str, Any]] = field(default_factory=list)
    processed: int = 0


def map_chunks(chunks: Iterable[Any], evaluate: Callable[[Any], Any]) -> MapResult:
    result = MapResult()
    for chunk in chunks:
        result.processed += 1
        try:
            value = evaluate(chunk)
            if value is None:
                raise ValueError("Response does not match the expected schema")
            result.values.append(value)
        except Exception as exc:
            result.failures.append({
                "source_file": chunk.source_file,
                "chunk_index": chunk.index,
                "error_type": type(exc).__name__,
            })
    return result
