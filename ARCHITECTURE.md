# Architecture notes

![Bahulam Two-Agent IDE POC — A2A Architecture & Task Flow](docs/architecture.jpg)

## A2A handoff sequence

```mermaid
sequenceDiagram
    autonumber
    participant CLI as Control Plane / CLI<br/>(run.py + cli.py)
    participant Builder as Code Builder Agent<br/>(127.0.0.1:9102)
    participant Setup as Workspace Setup Agent<br/>(127.0.0.1:9101)
    participant Gemini as Gemini API<br/>(gemini-2.5-flash)
    participant WS as Workspace<br/>(workspaces/<run_id>/)

    CLI->>Builder: A2A Card Discovery + prepare_and_plan
    Builder->>Setup: A2A Card Discovery + prepare_workspace
    Setup->>WS: Create .venv
    Setup-->>Builder: Artifact: venv_ready
    Builder->>Gemini: Generate JSON project_spec (llm.py)
    Gemini-->>Builder: files, dependencies, entrypoint
    Builder->>Setup: A2A install_dependencies
    Setup->>WS: Allowlist check + pip install + requirements.lock.txt
    Setup-->>Builder: Artifact: installed_dependencies
    Builder-->>CLI: Artifact: plan + files_to_create
    Note over CLI: Human Execution Approval Gate [y/N]
    CLI->>Builder: A2A write_and_run (execution_approved: true)
    Builder->>WS: Write files + compileall + pytest + smoke + HTTP /health
    Builder-->>CLI: Artifact: SHA-256 manifest + check results
```

## Run contract

A `run_id` is a 32-character UUID hex string. In the POC it is also the `workspace_id`. The Control Plane creates the run and passes this identifier to the Builder Agent. The identifier is validated before it is used as a workspace path.

## A2A handoff contract

Every A2A message carries JSON text with an `action` field. Every agent returns a JSON object as an A2A Artifact with media type `application/json`.

### Builder -> Setup: prepare workspace

```json
{
  "action": "prepare_workspace",
  "workspace_id": "<uuid-hex>",
  "requested_by": "code_builder_agent"
}
```

### Builder -> Setup: install dependencies

```json
{
  "action": "install_dependencies",
  "workspace_id": "<uuid-hex>",
  "dependencies": ["fastapi", "uvicorn", "httpx", "pytest"]
}
```

### Control Plane -> Builder: generate plan

```json
{
  "action": "prepare_and_plan",
  "run_id": "<uuid-hex>",
  "goal": "Build a small task tracker API"
}
```

### Control Plane -> Builder: write and run after approval

```json
{
  "action": "write_and_run",
  "run_id": "<uuid-hex>",
  "execution_approved": true,
  "project_spec": {
    "summary": "...",
    "dependencies": ["fastapi", "pytest"],
    "entrypoint": "main.py",
    "files": {"main.py": "...", "tests/test_main.py": "..."}
  }
}
```

## Ownership boundaries

- Setup Agent owns venv creation and package installation.
- Builder Agent owns project-spec generation, safe file writing, compile/tests/smoke execution and result packaging.
- Control Plane owns the run lifecycle, approval, task ID association and persistent run history.
- A2A carries messages and Task Artifacts; it is not the durable Work Graph, authorization system or sandbox.
