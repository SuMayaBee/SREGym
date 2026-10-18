"""Run OpenSRE against a SREGym Kubernetes incident."""

from __future__ import annotations

import argparse
import json
import logging
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import requests

from clients.harness.problem_id import resolve_problem_id
from clients.opensre.opensre_agent import OpenSREAgent
from logger import init_logger

init_logger()
logger = logging.getLogger("all.opensre.driver")
HTTP_TIMEOUT = 30


def run_preflight() -> None:
    """Check that the CLI is installed and can start."""
    binary = shutil.which("opensre") or "/opt/agent-tools/bin/opensre"
    result = subprocess.run([binary, "investigate", "--help"], capture_output=True, text=True, timeout=30)
    if result.returncode:
        print(result.stdout or result.stderr)
    raise SystemExit(result.returncode)


def get_api_base_url() -> str:
    return f"http://{os.getenv('API_HOSTNAME', 'localhost')}:{os.getenv('API_PORT', '8000')}"


def get_app_info() -> dict[str, Any]:
    response = requests.get(f"{get_api_base_url()}/get_app", timeout=HTTP_TIMEOUT)
    response.raise_for_status()
    return response.json()


def get_stage() -> str | None:
    try:
        response = requests.get(f"{get_api_base_url()}/status", timeout=HTTP_TIMEOUT)
        response.raise_for_status()
        return response.json().get("stage")
    except requests.RequestException as exc:
        logger.debug("Status check failed: %s", exc)
        return None


def wait_for_stage(target: str, timeout: int = 600) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        stage = get_stage()
        if stage == target:
            return
        if stage == "done":
            raise RuntimeError(f"Conductor reached 'done' before '{target}'")
        time.sleep(2)
    raise TimeoutError(f"Conductor did not reach '{target}' within {timeout}s")


def submit(solution: str) -> None:
    response = requests.post(f"{get_api_base_url()}/submit", json={"solution": solution}, timeout=HTTP_TIMEOUT)
    response.raise_for_status()


def build_llm_env(model: str) -> dict[str, str]:
    """Translate SREGym's model selection into OpenSRE's provider settings."""
    if os.getenv("AGENT_API_BASE"):
        selected = model.partition("/")[2] or model
        return {
            "LLM_PROVIDER": "custom-openai",
            "CUSTOM_OPENAI_API_KEY": os.getenv("AGENT_API_KEY", ""),
            "CUSTOM_OPENAI_BASE_URL": os.environ["AGENT_API_BASE"],
            "CUSTOM_OPENAI_MODEL": selected,
        }

    prefix, separator, selected = model.partition("/")
    aliases = {"vertex_ai": "vertex-ai", "google": "gemini"}
    if separator:
        provider = aliases.get(prefix, prefix)
    elif model.startswith("claude"):
        provider, selected = "anthropic", model
    elif model.startswith("gemini"):
        provider, selected = "gemini", model
    else:
        provider, selected = "openai", model
    variable_prefix = provider.upper().replace("-", "_")
    return {
        "LLM_PROVIDER": provider,
        f"{variable_prefix}_REASONING_MODEL": selected,
        f"{variable_prefix}_TOOLCALL_MODEL": selected,
    }


def _namespaces(app_info: dict[str, Any]) -> list[str]:
    return app_info.get("namespaces") or [app_info.get("namespace", "default")]


def _scope(app_info: dict[str, Any]) -> str:
    namespaces = _namespaces(app_info)
    suffix = " (the scenario spans all of them)" if len(namespaces) > 1 else ""
    return f"namespace(s) {', '.join(namespaces)}{suffix}"


def build_incident(app_info: dict[str, Any]) -> str:
    namespaces = _namespaces(app_info)
    return f"""A fault has been injected into the Kubernetes application '{app_info.get("app_name", "unknown")}' in {_scope(app_info)}.

Investigate the live cluster with OpenSRE's Kubernetes tools and identify the faulty Kubernetes object and root cause. Start by checking workloads, services, events, and logs in {", ".join(namespaces)}; follow the evidence until the cause is specific. Do not ask the operator to run commands.

Scenario context:
{app_info.get("descriptions", "")}"""


def run_mitigation_executor(model: str, logs_dir: Path, diagnosis: str | None) -> int:
    """Run SREGym's native execution loop for the current mitigation stage."""
    environment = os.environ.copy()
    environment["AGENT_MODEL_ID"] = model
    environment["AGENT_LOGS_DIR"] = str(logs_dir / "mitigation")
    if diagnosis:
        environment["OPENSRE_DIAGNOSIS_CONTEXT"] = diagnosis
    result = subprocess.run(
        [sys.executable, "-m", "clients.mini_sre.driver"],
        env=environment,
        timeout=int(os.getenv("OPENSRE_MITIGATION_TIMEOUT", "1800")),
    )
    return result.returncode


def save_results(logs_dir: Path, problem_id: str, return_code: int, usage_metrics: dict[str, int]) -> None:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = logs_dir / f"opensre_results_{problem_id}_{timestamp}.json"
    path.write_text(
        json.dumps(
            {
                "problem_id": problem_id,
                "timestamp": timestamp,
                "return_code": return_code,
                "success": return_code == 0,
                "usage_metrics": usage_metrics,
            },
            indent=2,
        ),
        encoding="utf-8",
    )


def run(logs_dir: Path, model: str, problem_id: str) -> int:
    OpenSREAgent.ensure_installed()
    app_info = get_app_info()
    stages = app_info.get("stages") or ["diagnosis", "mitigation"]
    agent_env = build_llm_env(model)
    diagnosis: str | None = None
    usage = {"input_tokens": 0, "cached_input_tokens": 0, "output_tokens": 0}
    return_code = 0

    if "diagnosis" in stages:
        wait_for_stage("diagnosis")
        agent = OpenSREAgent(logs_dir / "diagnosis", model)
        result = agent.investigate(build_incident(app_info), "SREGym diagnosis", agent_env)
        if not result or agent.last_return_code:
            raise RuntimeError(f"OpenSRE diagnosis failed with exit code {agent.last_return_code}")
        diagnosis = agent.diagnosis_text(result)
        return_code = max(return_code, agent.last_return_code)
        usage = agent.get_usage_metrics()
        submit(diagnosis)

    if "mitigation" in stages:
        wait_for_stage("mitigation")
        return_code = max(return_code, run_mitigation_executor(model, logs_dir, diagnosis))

    save_results(logs_dir, problem_id, return_code, usage)
    return return_code


def main() -> None:
    parser = argparse.ArgumentParser(description="Run OpenSRE on a SREGym task")
    parser.add_argument("--model", default=os.getenv("AGENT_MODEL_ID", "claude-sonnet-4-5"))
    parser.add_argument("--logs-dir", default=os.getenv("AGENT_LOGS_DIR", "./logs/opensre"))
    parser.add_argument("--problem-id")
    args = parser.parse_args()
    logs_dir = Path(args.logs_dir)
    logs_dir.mkdir(parents=True, exist_ok=True)
    code = run(logs_dir, args.model, resolve_problem_id(cli_problem_id=args.problem_id))
    if code:
        sys.exit(code)


if __name__ == "__main__":
    main()
