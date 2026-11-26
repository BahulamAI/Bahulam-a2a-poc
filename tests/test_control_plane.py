from bahulam_poc.control_plane import ControlPlane


def test_control_plane_persists_run_and_events(tmp_path):
    control = ControlPlane(tmp_path / "control.sqlite3")
    control.create_run("a" * 32, "Build a tiny API")
    control.set_status("a" * 32, "planning")
    control.record_agent_task("a" * 32, "builder", "task-123", "completed")
    saved = control.get_run("a" * 32)
    assert saved["goal"] == "Build a tiny API"
    assert saved["status"] == "planning"
    assert saved["agent_tasks"][0]["a2a_task_id"] == "task-123"
    assert len(saved["events"]) >= 3
