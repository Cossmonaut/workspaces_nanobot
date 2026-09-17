"""Thin audit adapter for the project's shared LLM and single-flight services."""
from __future__ import annotations
from typing import Any

from lib.services.llm_client import call_llm, call_llm_json_strict
from lib.services.llm_single_flight import guarded_chat
from workspace.skills.audit_formulation_strengthener.scripts.skill_config import get_llm_config, get_max_retries


class JsonParseError(Exception):
    def __init__(self, message: str, raw_text: str = "", attempt: int = 1):
        super().__init__(message)
        self.raw_text = raw_text
        self.attempt = attempt


def _options() -> dict[str, Any]:
    cfg = get_llm_config()
    return {
        "max_tokens": int(cfg.get("max_tokens", 4096)),
        "temperature": float(cfg.get("temperature", 0.1)),
        "max_retries": get_max_retries(),
    }


def _messages(system: str, user: str) -> list[dict[str, str]]:
    messages = [{"role": "system", "content": system}] if system else []
    return messages + [{"role": "user", "content": user}]


def call_llm_text(*, system: str, user: str, operation: str = "afs") -> str:
    return guarded_chat(call_llm, _messages(system, user), **_options())


def call_llm_json(*, system: str, user: str, operation: str = "afs") -> dict[str, Any]:
    try:
        return guarded_chat(call_llm_json_strict, _messages(system, user), **_options())
    except ValueError as exc:
        raise JsonParseError(str(exc)) from exc