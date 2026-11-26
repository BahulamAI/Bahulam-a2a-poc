from __future__ import annotations

import argparse
import asyncio
import json
import sys
import uuid
from typing import Any

from bahulam_poc.a2a_client import invoke_a2a_agent
from bahulam_poc.control_plane import ControlPlane
from bahulam_poc.settings import settings


def print_json(value: Any) -> None:
    print(json.dumps(value, indent=2, ensure_ascii=False))


async def run_build(goal: str, approve_execution: bool) -> int:
    run_id = uuid.uuid4().hex
    control = ControlPlane()
    control.create_run(run_id, goal)
    control.set_status(run_id, "planning")
    print(f"\n[Bahulam Control Plane] Run ID: {run_id}")
    print("[A2A] Discovering Code Builder Agent and submitting prepare_and_plan task...")

    try:
        plan_result = await invoke_a2a_agent(
            settings.builder_agent_url,
            {"action": "prepare_and_plan", "run_id": run_id, "goal": goal},
            timeout=900.0,
        )
        control.record_agent_task(run_id, "code_builder_agent", plan_result.task_id, plan_result.state)
        try:
            plan = json.loads(plan_result.artifact_text)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"Builder Agent returned invalid plan artifact: {exc}\n{plan_result.artifact_text}") from exc
        if not isinstance(plan, dict):
            raise RuntimeError("Builder Agent returned a non-object plan artifact.")
        if plan.get("status") != "planned_and_environment_ready":
            raise RuntimeError(f"Builder Agent did not prepare a usable project plan: {plan}")

        workspace_id = plan["workspace_id"]
        control.set_workspace(run_id, workspace_id)
        for task in plan.get("setup_agent_tasks", []):
            control.record_agent_task(run_id, "workspace_setup_agent", task.get("task_id"), task.get("state"))
        control.add_event(run_id, "code_builder_agent", "project.plan_created", {
            "summary": plan.get("summary"),
            "dependencies": plan.get("dependencies"),
            "files_to_create": plan.get("files_to_create"),
        })
        control.set_status(run_id, "awaiting_execution_approval")

        print("\n[Code Builder Agent] Project plan is ready.")
        print(f"Summary: {plan.get('summary')}")
        print(f"Workspace: {workspace_id}")
        print(f"Dependencies installed by Setup Agent: {', '.join(plan.get('installed_dependencies', []))}")
        print("Files to create:")
        for file_name in plan.get("files_to_create", []):
            print(f"  - {file_name}")
        print("\n[Control Plane] The generated project will now be written and executed only after approval.")

        approved = approve_execution
        if not approved and sys.stdin.isatty():
            answer = input("Approve writing and running the generated code in this local workspace? [y/N]: ").strip().lower()
            approved = answer in {"y", "yes"}
        if not approved:
            control.set_status(run_id, "approval_required")
            print("\nExecution was not approved. The workspace and dependency environment are prepared, but generated files were not written or run.")
            print(f"Run record: {settings.control_plane_db}")
            return 2

        control.add_event(run_id, "human", "execution.approved", {"approved": True})
        control.set_status(run_id, "executing")
        print("\n[A2A] Sending write_and_run task to Code Builder Agent...")
        execute_result = await invoke_a2a_agent(
            settings.builder_agent_url,
            {
                "action": "write_and_run",
                "run_id": run_id,
                "project_spec": plan["project_spec"],
                "execution_approved": True,
            },
            timeout=300.0,
        )
        control.record_agent_task(run_id, "code_builder_agent", execute_result.task_id, execute_result.state)
        try:
            report = json.loads(execute_result.artifact_text)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"Builder Agent returned invalid execution artifact: {exc}\n{execute_result.artifact_text}") from exc
        control.save_result(run_id, report.get("status", "unknown"), report)

        print("\n========== BAHULAM BUILD RESULT ==========")
        print(f"Status: {report.get('status')}")
        print(f"Workspace: {report.get('project_directory')}")
        print(f"Files created: {len(report.get('files', []))}")
        print(f"Compile check: {'PASS' if report.get('compile_check', {}).get('passed') else 'FAIL'}")
        test_result = report.get("test_result")
        print(f"Tests: {('PASS' if test_result.get('passed') else 'FAIL') if test_result else 'NOT RUN'}")
        entry_result = report.get("entrypoint_result")
        print(f"Smoke run: {('PASS' if entry_result.get('passed') else 'FAIL') if entry_result else 'NOT RUN'}")
        http_smoke = report.get("http_smoke_result")
        print(f"HTTP smoke: {('PASS' if http_smoke.get('passed') else 'FAIL') if http_smoke else 'NOT APPLICABLE'}")
        if test_result:
            print("\n--- Test output ---")
            print(test_result.get("stdout", "") or test_result.get("stderr", ""))
        if entry_result:
            print("\n--- Program output ---")
            print(entry_result.get("stdout", "") or entry_result.get("stderr", ""))
        print("\n--- Artifact manifest ---")
        print_json(report.get("files", []))
        print(f"\nRun record: {settings.control_plane_db}")
        print("=========================================\n")
        return 0 if report.get("all_checks_passed") else 1

    except Exception as exc:
        control.set_status(run_id, "failed")
        control.add_event(run_id, "control_plane", "run.error", {"error": f"{type(exc).__name__}: {exc}"})
        print(f"\n[ERROR] {type(exc).__name__}: {exc}", file=sys.stderr)
        print("Check that both A2A agent servers are running and inspect their terminal logs.", file=sys.stderr)
        return 1


def show_run(run_id: str) -> int:
    control = ControlPlane()
    run = control.get_run(run_id)
    if not run:
        print(f"Run not found: {run_id}", file=sys.stderr)
        return 1
    print_json(run)
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Bahulam two-agent A2A coding POC")
    parser.add_argument("goal", nargs="?", help="What project should the agents create?")
    parser.add_argument("--approve-execution", action="store_true", help="Approve writing and running generated code without an interactive prompt.")
    parser.add_argument("--show-run", help="Print a saved Control Plane run by run ID.")
    args = parser.parse_args()
    if args.show_run:
        raise SystemExit(show_run(args.show_run))
    if not args.goal:
        parser.error("Provide a project goal, for example: Build a simple task tracker API.")
    raise SystemExit(asyncio.run(run_build(args.goal, args.approve_execution)))


if __name__ == "__main__":
    main()
