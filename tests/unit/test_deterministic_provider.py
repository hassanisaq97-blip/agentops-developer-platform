import json

from agentops.gateway.providers.test_provider import DeterministicTestProvider
from agentops.gateway.schemas import (
    ChatRole,
    CompletionRequest,
    Message,
    StopReason,
    ToolDefinition,
)

TOOLS = [
    ToolDefinition(name=n, description=n)
    for n in ["get_repository_status", "run_tests", "search_code", "read_file", "apply_patch"]
]


def _tool_result(name: str, call_id: str, payload: dict | str) -> Message:
    content = payload if isinstance(payload, str) else json.dumps(payload)
    return Message(role=ChatRole.TOOL, name=name, tool_call_id=call_id, content=content)


def test_first_call_checks_repository_status():
    provider = DeterministicTestProvider()
    request = CompletionRequest(
        messages=[Message(role=ChatRole.USER, content="Fix the failing test")], tools=TOOLS
    )
    result = provider.complete(request, model="deterministic-v1")
    assert result.stop_reason == StopReason.TOOL_USE
    assert result.message.tool_calls[0].name == "get_repository_status"
    assert result.provider == "test"
    assert result.model == "deterministic-v1"


def test_full_playbook_finds_and_fixes_the_bug():
    provider = DeterministicTestProvider()
    messages = [Message(role=ChatRole.USER, content="Fix the failing test")]

    # Step 1: repository status
    result = provider.complete(
        CompletionRequest(messages=messages, tools=TOOLS), model="deterministic-v1"
    )
    assert result.message.tool_calls[0].name == "get_repository_status"
    messages.append(result.message)
    messages.append(
        _tool_result(
            "get_repository_status", result.message.tool_calls[0].id, {"head_commit": "init"}
        )
    )

    # Step 2: run_tests (fails)
    result = provider.complete(
        CompletionRequest(messages=messages, tools=TOOLS), model="deterministic-v1"
    )
    assert result.message.tool_calls[0].name == "run_tests"
    messages.append(result.message)
    messages.append(
        _tool_result(
            "run_tests",
            result.message.tool_calls[0].id,
            {
                "returncode": 1,
                "passed": 0,
                "failed": 1,
                "stdout": "FAILED tests/test_calculator.py::test_add",
            },
        )
    )

    # Step 3: search_code
    result = provider.complete(
        CompletionRequest(messages=messages, tools=TOOLS), model="deterministic-v1"
    )
    assert result.message.tool_calls[0].name == "search_code"
    assert result.message.tool_calls[0].arguments["query"] == "def add"
    messages.append(result.message)
    messages.append(
        _tool_result(
            "search_code",
            result.message.tool_calls[0].id,
            [{"path": "src/calculator.py", "line_number": 2, "line": "return a - b"}],
        )
    )

    # Step 4: read_file
    result = provider.complete(
        CompletionRequest(messages=messages, tools=TOOLS), model="deterministic-v1"
    )
    assert result.message.tool_calls[0].name == "read_file"
    assert result.message.tool_calls[0].arguments["path"] == "src/calculator.py"
    messages.append(result.message)
    file_content = "def add(a, b):\n    return a - b\n"
    messages.append(_tool_result("read_file", result.message.tool_calls[0].id, file_content))

    # Step 5: apply_patch
    result = provider.complete(
        CompletionRequest(messages=messages, tools=TOOLS), model="deterministic-v1"
    )
    assert result.message.tool_calls[0].name == "apply_patch"
    assert "return a + b" in result.message.tool_calls[0].arguments["diff_text"]
    messages.append(result.message)
    messages.append(_tool_result("apply_patch", result.message.tool_calls[0].id, {"applied": True}))

    # Step 6: run_tests again (passes)
    result = provider.complete(
        CompletionRequest(messages=messages, tools=TOOLS), model="deterministic-v1"
    )
    assert result.message.tool_calls[0].name == "run_tests"
    messages.append(result.message)
    messages.append(
        _tool_result(
            "run_tests",
            result.message.tool_calls[0].id,
            {"returncode": 0, "passed": 5, "failed": 0},
        )
    )

    # Step 7: final answer
    result = provider.complete(
        CompletionRequest(messages=messages, tools=TOOLS), model="deterministic-v1"
    )
    assert result.stop_reason == StopReason.END_TURN
    assert "rettet" in result.message.content.lower()


def test_already_passing_tests_short_circuits():
    provider = DeterministicTestProvider()
    messages = [Message(role=ChatRole.USER, content="Fix the failing test")]
    result = provider.complete(
        CompletionRequest(messages=messages, tools=TOOLS), model="deterministic-v1"
    )
    messages.append(result.message)
    messages.append(_tool_result("get_repository_status", result.message.tool_calls[0].id, {}))

    result = provider.complete(
        CompletionRequest(messages=messages, tools=TOOLS), model="deterministic-v1"
    )
    messages.append(result.message)
    messages.append(
        _tool_result(
            "run_tests",
            result.message.tool_calls[0].id,
            {"returncode": 0, "passed": 5, "failed": 0},
        )
    )

    result = provider.complete(
        CompletionRequest(messages=messages, tools=TOOLS), model="deterministic-v1"
    )
    assert result.stop_reason == StopReason.END_TURN
    assert "består allerede" in result.message.content
