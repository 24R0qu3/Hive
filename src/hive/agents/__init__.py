"""Built-in agent definitions shipped with Hive."""

from hive.agent import AgentDefinition

SHELL_TASK_AGENT = AgentDefinition(
    name="shell-task",
    description="Execute multi-step shell operations to accomplish a stated goal.",
    system_prompt=(
        "You are a shell automation agent. You have access to the 'shell' tool.\n"
        "Execute the user's goal by running shell commands, observing the output, "
        "and adapting your approach based on what you see.\n"
        "Rules:\n"
        "- Always run a command and observe the actual output before proceeding.\n"
        "- Never guess or fabricate command output.\n"
        "- When the goal is fully accomplished, say TASK_COMPLETE followed by a "
        "brief summary of what was done.\n"
        "- If you encounter an unrecoverable error, say TASK_COMPLETE and explain "
        "what went wrong."
    ),
    tools=["shell"],
    max_steps=15,
    stop_phrase="TASK_COMPLETE",
)

BUILTIN_AGENTS: list[AgentDefinition] = [SHELL_TASK_AGENT]
