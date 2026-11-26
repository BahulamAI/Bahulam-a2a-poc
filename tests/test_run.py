from __future__ import annotations

from pathlib import Path

import pytest

from bahulam_poc import run


def test_start_agents_skips_spawn_when_already_ready(monkeypatch, tmp_path):
    monkeypatch.setattr(run, "_is_agent_ready", lambda url: True)
    called = []
    monkeypatch.setattr(run.subprocess, "Popen", lambda *a, **kw: called.append(a))

    agents = run._start_agents(tmp_path)
    assert len(agents) == 2
    assert called == []
    assert all(a.process is None for a in agents)


def test_start_agents_spawns_and_stops_processes(monkeypatch, tmp_path):
    class FakeProc:
        def __init__(self):
            self.terminated = False
            self.waited = False

        def poll(self):
            return None

        def terminate(self):
            self.terminated = True

        def wait(self, timeout=None):
            self.waited = True
            return 0

    procs = []
    checks = {}

    def fake_popen(cmd, stdout=None, stderr=None, text=None):
        p = FakeProc()
        procs.append((cmd, p))
        return p

    def fake_ready(url):
        checks[url] = checks.get(url, 0) + 1
        # Not ready on initial check, ready on first poll
        return checks[url] >= 2

    monkeypatch.setattr(run, "_is_agent_ready", fake_ready)
    monkeypatch.setattr(run.subprocess, "Popen", fake_popen)

    agents = run._start_agents(tmp_path, startup_timeout=2.0)
    assert len(procs) == 2
    assert (tmp_path / "setup_agent.log").exists()
    assert (tmp_path / "builder_agent.log").exists()

    run._stop_agents(agents)
    assert all(p.terminated and p.waited for _, p in procs)


def test_start_agents_reports_early_exit(monkeypatch, tmp_path):
    class DeadProc:
        returncode = 1

        def poll(self):
            return 1

    monkeypatch.setattr(run, "_is_agent_ready", lambda url: False)
    monkeypatch.setattr(run.subprocess, "Popen", lambda *a, **kw: DeadProc())

    with pytest.raises(RuntimeError, match="exited early"):
        run._start_agents(tmp_path, startup_timeout=1.0)
