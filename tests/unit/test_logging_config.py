import json
import logging

from agentops.observability.logging_config import configure_logging, get_logger


def test_configure_logging_emits_json_and_redacts_secrets(capsys):
    configure_logging("INFO")
    logger = get_logger("test.logger")
    logger.info("provider_call", api_key="sk-should-not-appear", path="src/app.py")

    captured = capsys.readouterr()
    line = next(line for line in captured.out.splitlines() if line.strip())
    payload = json.loads(line)

    assert payload["event"] == "provider_call"
    assert payload["api_key"] == "***REDACTED***"
    assert payload["path"] == "src/app.py"


def test_stdlib_logging_also_flows_through_json_formatter(capsys):
    configure_logging("INFO")
    logging.getLogger("stdlib.test").warning("something happened")

    captured = capsys.readouterr()
    line = next(line for line in captured.out.splitlines() if line.strip())
    payload = json.loads(line)
    assert payload["event"] == "something happened"
    assert payload["level"] == "warning"
