from bahulam_poc.a2a_server import JsonAgentExecutor, build_a2a_app, serve
from bahulam_poc.agents.setup_agent import WorkspaceSetupAgent
from bahulam_poc.settings import settings


def main() -> None:
    agent = WorkspaceSetupAgent()
    app = build_a2a_app(
        name="Bahulam Workspace Setup Agent",
        description="Creates project workspaces and virtual environments, validates and installs allowlisted Python dependencies.",
        version="0.1.0",
        host=settings.setup_agent_host,
        port=settings.setup_agent_port,
        public_url=settings.setup_agent_url,
        skill_id="workspace_setup",
        skill_name="Workspace and dependency setup",
        skill_description="Prepare a workspace, create a virtual environment, and install approved packages.",
        examples=["Prepare a Python project workspace", "Install fastapi and pytest in a project environment"],
        executor=JsonAgentExecutor(agent.handle, "Workspace Setup Agent"),
    )
    serve(app, settings.setup_agent_host, settings.setup_agent_port)


if __name__ == "__main__":
    main()
