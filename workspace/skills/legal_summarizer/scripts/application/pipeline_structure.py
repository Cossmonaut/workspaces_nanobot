"""Legal runtime adapter for the shared canonical document pipeline."""
from lib.services.document_processing.application import pipeline_structure as _shared

globals().update({name: value for name, value in vars(_shared).items() if not name.startswith("__")})

def run_canonical_pipeline(path, *, text=None, apply_repair=True,
                           include_retrieval_index=True, workspace_root=None,
                           session_key="default"):
    import llm.config as runtime_config
    return _shared.run_canonical_pipeline(
        path, text=text, apply_repair=apply_repair,
        include_retrieval_index=include_retrieval_index,
        workspace_root=workspace_root, session_key=session_key,
        chunking_config=runtime_config.get_chunking_config(),
    )