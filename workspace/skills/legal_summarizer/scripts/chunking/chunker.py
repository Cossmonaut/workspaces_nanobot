"""Legal runtime configuration adapter for the shared structural chunker."""
from lib.services.document_processing.chunking import chunker as _shared

globals().update({name: value for name, value in vars(_shared).items() if not name.startswith("__")})

def build_chunk_config_from_runtime(context_window_tokens=None):
    import llm.config as runtime_config
    return _shared.build_chunk_config_from_runtime(
        context_window_tokens, chunking_config=runtime_config.get_chunking_config(),
    )