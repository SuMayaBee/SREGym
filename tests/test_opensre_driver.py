from pathlib import Path
from unittest.mock import Mock, call

import pytest

from clients.opensre import driver


@pytest.mark.parametrize(
    ("model", "provider", "variable"),
    [
        ("anthropic/claude-sonnet-4-5", "anthropic", "ANTHROPIC_REASONING_MODEL"),
        ("openai/gpt-5", "openai", "OPENAI_REASONING_MODEL"),
        ("google/gemini-2.5-pro", "gemini", "GEMINI_REASONING_MODEL"),
    ],
)
def test_llm_model_is_forwarded(monkeypatch, model, provider, variable):
    monkeypatch.delenv("AGENT_API_BASE", raising=False)

    environment = driver.build_llm_env(model)

    assert environment["LLM_PROVIDER"] == provider
    assert environment[variable] == model.partition("/")[2]


def test_mitigation_only_runs_executor_directly(monkeypatch, tmp_path):
    agent_type = Mock()
    agent_type.ensure_installed = Mock()
    monkeypatch.setattr(driver, "OpenSREAgent", agent_type)
    monkeypatch.setattr(driver, "get_app_info", lambda: {"stages": ["mitigation"], "namespace": "demo"})
    wait = Mock()
    executor = Mock(return_value=0)
    monkeypatch.setattr(driver, "wait_for_stage", wait)
    monkeypatch.setattr(driver, "run_mitigation_executor", executor)
    monkeypatch.setattr(driver, "save_results", Mock())

    assert driver.run(Path(tmp_path), "openai/gpt-5", "problem") == 0
    wait.assert_called_once_with("mitigation")
    executor.assert_called_once_with("openai/gpt-5", Path(tmp_path), None)
    agent_type.assert_not_called()


def test_full_workflow_submits_diagnosis_before_mitigation(monkeypatch, tmp_path):
    diagnosis_agent = Mock(last_return_code=0)
    diagnosis_agent.investigate.return_value = {"root_cause": "bad selector"}
    diagnosis_agent.diagnosis_text.return_value = "bad selector"
    diagnosis_agent.get_usage_metrics.return_value = {
        "input_tokens": 1,
        "cached_input_tokens": 0,
        "output_tokens": 1,
    }
    monkeypatch.setattr(driver.OpenSREAgent, "ensure_installed", Mock())
    monkeypatch.setattr(driver, "OpenSREAgent", Mock(return_value=diagnosis_agent))
    monkeypatch.setattr(driver, "get_app_info", lambda: {"namespace": "demo"})
    wait = Mock()
    submit = Mock()
    executor = Mock(return_value=0)
    monkeypatch.setattr(driver, "wait_for_stage", wait)
    monkeypatch.setattr(driver, "submit", submit)
    monkeypatch.setattr(driver, "run_mitigation_executor", executor)
    monkeypatch.setattr(driver, "save_results", Mock())

    driver.run(Path(tmp_path), "openai/gpt-5", "problem")

    assert wait.call_args_list == [call("diagnosis"), call("mitigation")]
    submit.assert_called_once_with("bad selector")
    executor.assert_called_once_with("openai/gpt-5", Path(tmp_path), "bad selector")


def test_executor_receives_upstream_diagnosis(monkeypatch, tmp_path):
    completed = Mock(returncode=0)
    run = Mock(return_value=completed)
    monkeypatch.setattr(driver.subprocess, "run", run)

    assert driver.run_mitigation_executor("openai/gpt-5", Path(tmp_path), "bad selector") == 0

    environment = run.call_args.kwargs["env"]
    assert environment["AGENT_MODEL_ID"] == "openai/gpt-5"
    assert environment["OPENSRE_DIAGNOSIS_CONTEXT"] == "bad selector"
