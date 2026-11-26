import pytest

from bahulam_poc.specs import ProjectSpecError, demo_project_spec, validate_project_spec


def test_demo_spec_is_valid():
    spec = validate_project_spec(demo_project_spec("Build a tiny task API"))
    assert "app.py" in spec["files"]
    assert "tests/test_app.py" in spec["files"]
    assert spec["entrypoint"] == "main.py"
    assert "fastapi" in spec["dependencies"]


def test_reject_path_traversal():
    spec = demo_project_spec("demo")
    spec["files"]["../outside.py"] = "print('bad')"
    with pytest.raises(ProjectSpecError):
        validate_project_spec(spec)


def test_reject_unapproved_package():
    spec = demo_project_spec("demo")
    spec["dependencies"].append("malicious-package")
    with pytest.raises(ProjectSpecError):
        validate_project_spec(spec)


def test_reject_non_python_entrypoint():
    spec = demo_project_spec("demo")
    spec["entrypoint"] = "README.md"
    with pytest.raises(ProjectSpecError):
        validate_project_spec(spec)


def test_demo_http_smoke_contract_is_valid():
    spec = validate_project_spec(demo_project_spec("Build an API"))
    assert spec["http_smoke"] == {"app_target": "app:app", "health_path": "/health"}


def test_reject_http_smoke_module_not_in_files():
    spec = demo_project_spec("demo")
    spec["http_smoke"] = {"app_target": "missing:app", "health_path": "/health"}
    with pytest.raises(ProjectSpecError):
        validate_project_spec(spec)
