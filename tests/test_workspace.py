import pytest

from bahulam_poc.workspaces import WorkspaceError, WorkspaceManager


def test_workspace_id_is_validated(tmp_path):
    manager = WorkspaceManager(tmp_path)
    with pytest.raises(WorkspaceError):
        manager.prepare("../../outside")


def test_dependencies_are_allowlisted(tmp_path):
    manager = WorkspaceManager(tmp_path)
    assert manager.validate_packages(["FastAPI", "pytest"]) == ["fastapi", "pytest"]
    with pytest.raises(WorkspaceError):
        manager.validate_packages(["https://example.com/evil.whl"])
