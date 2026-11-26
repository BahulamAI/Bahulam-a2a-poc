from bahulam_poc.a2a_server import JsonAgentExecutor, build_a2a_app, serve
from bahulam_poc.agents.builder_agent import CodeBuilderAgent
from bahulam_poc.settings import settings


def main() -> None:
    agent = CodeBuilderAgent()
    app = build_a2a_app(
        name="Bahulam Code Builder Agent",
        description="Delegates environment setup to the Workspace Setup Agent over A2A, generates project files, runs checks, and returns artifacts.",
        version="0.1.0",
        host=settings.builder_agent_host,
        port=settings.builder_agent_port,
        public_url=settings.builder_agent_url,
        skill_id="code_generation_and_execution",
        skill_name="Generate, write and verify code",
        skill_description="Create a bounded project specification, coordinate setup over A2A, write files, run compile/tests and return an artifact manifest.",
        examples=["Create a small FastAPI service", "Build and test a Python utility"],
        executor=JsonAgentExecutor(agent.handle, "Code Builder Agent"),
    )
    serve(app, settings.builder_agent_host, settings.builder_agent_port)


if __name__ == "__main__":
    main()
