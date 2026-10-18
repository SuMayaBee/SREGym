import json
from subprocess import CompletedProcess

from clients.opensre.opensre_agent import OpenSREAgent


def test_investigate_passes_mcp_environment(monkeypatch, tmp_path):
    def fake_run(command, **kwargs):
        output = command[command.index("-o") + 1]
        with open(output, "w", encoding="utf-8") as stream:
            json.dump({"root_cause": "service selector mismatch"}, stream)
        assert kwargs["env"]["OPENCLAW_MCP_MODE"] == "sse"
        return CompletedProcess(command, 0, "", "")

    monkeypatch.setattr("clients.opensre.opensre_agent.subprocess.run", fake_run)
    agent = OpenSREAgent(tmp_path)

    result = agent.investigate("incident", extra_env={"OPENCLAW_MCP_MODE": "sse"})

    assert result["root_cause"] == "service selector mismatch"
    assert agent.last_return_code == 0


def test_investigate_does_not_reuse_stale_output(monkeypatch, tmp_path):
    agent = OpenSREAgent(tmp_path)
    agent.output_path.write_text('{"report": "old"}', encoding="utf-8")
    monkeypatch.setattr(
        "clients.opensre.opensre_agent.subprocess.run",
        lambda command, **kwargs: CompletedProcess(command, 1, "", "failed"),
    )

    assert agent.investigate("incident") == {}
    assert agent.last_return_code == 1
