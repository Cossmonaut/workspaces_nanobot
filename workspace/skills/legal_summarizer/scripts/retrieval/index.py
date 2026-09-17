"""Compatibility import; implementation lives in the shared document service."""
import sys
from importlib import import_module
sys.modules[__name__] = import_module("lib.services.document_processing.retrieval.index")
