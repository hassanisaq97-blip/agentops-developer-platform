from agentops.security.secrets import redact_mapping, redact_text


def test_redacts_openai_style_key():
    text = "The key is sk-abcdefghijklmnopqrstuvwxyz123456"
    assert "sk-abcdefghijklmnopqrstuvwxyz123456" not in redact_text(text)


def test_redacts_github_token():
    text = "token: ghp_" + "a" * 36
    assert "ghp_" + "a" * 36 not in redact_text(text)


def test_leaves_normal_text_untouched():
    text = "This is a normal sentence about code review."
    assert redact_text(text) == text


def test_redact_mapping_hides_secret_keys():
    data = {"api_key": "supersecret", "path": "src/app.py"}
    result = redact_mapping(data)
    assert result["api_key"] == "***REDACTED***"
    assert result["path"] == "src/app.py"


def test_redact_mapping_recurses_into_nested_dicts():
    data = {"config": {"password": "hunter2"}, "count": 3}
    result = redact_mapping(data)
    assert result["config"]["password"] == "***REDACTED***"
    assert result["count"] == 3
