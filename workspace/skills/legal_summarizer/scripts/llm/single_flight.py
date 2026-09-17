"""Compatibility import for the shared LLM boundary."""
import sys
from importlib import import_module
sys.modules[__name__] = import_module("lib.services.llm_single_flight")
