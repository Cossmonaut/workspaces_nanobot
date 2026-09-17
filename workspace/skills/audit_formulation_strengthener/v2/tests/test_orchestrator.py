"""Tests для orchestrator.py."""

from __future__ import annotations

import json

import pytest


class TestOrchestratorAnalyze:
    """Тесты для analyze-фазы — через прямой вызов без моков LLM."""

    def test_analyze_empty_raises(self):
        """Пустой violation вызывает ошибку."""
        # Import inside to avoid module-level issues
        import sys
        from pathlib import Path
        
        # Setup paths
        v2_dir = Path(__file__).parent.parent
        repo_root = v2_dir.parent.parent.parent
        legal_scripts = str(repo_root / "workspace" / "skills" / "legal_summarizer" / "scripts")
        
        for p in (str(repo_root), legal_scripts):
            if p not in sys.path:
                sys.path.insert(0, p)
        
        from orchestrator import AuditFormulationStrengthener
        from data import EmptyViolationError
        
        orch = AuditFormulationStrengthener()
        
        with pytest.raises(EmptyViolationError):
            orch.analyze("")
        
        with pytest.raises(EmptyViolationError):
            orch.analyze("   ")

    def test_analyze_whitespace_raises(self):
        """Whitespace-only violation вызывает ошибку."""
        import sys
        from pathlib import Path
        
        v2_dir = Path(__file__).parent.parent
        repo_root = v2_dir.parent.parent.parent
        legal_scripts = str(repo_root / "workspace" / "skills" / "legal_summarizer" / "scripts")
        
        for p in (str(repo_root), legal_scripts):
            if p not in sys.path:
                sys.path.insert(0, p)
        
        from orchestrator import AuditFormulationStrengthener
        from data import EmptyViolationError
        
        orch = AuditFormulationStrengthener()
        
        with pytest.raises(EmptyViolationError):
            orch.analyze("   \n\t  ")


class TestOrchestratorClassExists:
    """Проверка что класс создаётся."""

    def test_class_instantiation(self):
        """Orchestrator создаётся без ошибок."""
        import sys
        from pathlib import Path
        
        v2_dir = Path(__file__).parent.parent
        repo_root = v2_dir.parent.parent.parent
        legal_scripts = str(repo_root / "workspace" / "skills" / "legal_summarizer" / "scripts")
        
        for p in (str(repo_root), legal_scripts):
            if p not in sys.path:
                sys.path.insert(0, p)
        
        from orchestrator import AuditFormulationStrengthener
        
        orch = AuditFormulationStrengthener()
        assert orch is not None
        assert orch.workspace_root is None

    def test_class_instantiation_with_workspace(self):
        """Orchestrator создаётся с workspace_root."""
        import sys
        from pathlib import Path
        
        v2_dir = Path(__file__).parent.parent
        repo_root = v2_dir.parent.parent.parent
        legal_scripts = str(repo_root / "workspace" / "skills" / "legal_summarizer" / "scripts")
        
        for p in (str(repo_root), legal_scripts):
            if p not in sys.path:
                sys.path.insert(0, p)
        
        from orchestrator import AuditFormulationStrengthener
        
        workspace = Path("/tmp/test")
        orch = AuditFormulationStrengthener(workspace_root=workspace)
        assert orch.workspace_root == workspace
