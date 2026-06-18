from typing import Dict, List, Any, Optional, get_type_hints
from enum import Enum
import pytest

def test_langgraph_state_imports():
    """Assert structure and annotations of FAIRifierState and ProcessingStatus."""
    from fairifier.graph.state import FAIRifierState, ProcessingStatus

    assert issubclass(ProcessingStatus, Enum)
    assert ProcessingStatus.PENDING.value == "pending"
    assert ProcessingStatus.FAILED.value == "failed"

    # Assert some key fields of FAIRifierState and their annotations
    type_hints = get_type_hints(FAIRifierState)
    
    assert "document_path" in type_hints
    assert type_hints["document_path"] is str

    assert "document_content" in type_hints
    assert type_hints["document_content"] == Optional[str]

    assert "status" in type_hints
    assert type_hints["status"] is str

    assert "errors" in type_hints
    assert type_hints["errors"] == List[str]

    assert "plan_tasks" in type_hints
    assert type_hints["plan_tasks"] == List[Dict[str, Any]]
