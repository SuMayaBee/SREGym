# OpenSRE client

This client integrates OpenSRE's supported Kubernetes investigation workflow
with SREGym. For a normal two-stage problem:

1. OpenSRE uses its native Kubernetes integration to investigate the cluster.
2. The driver submits OpenSRE's root-cause report for diagnosis scoring.
3. SREGym's built-in MiniSRE execution loop validates that report, applies the
   fix, and submits to the live mitigation oracle.

Mitigation-only problems skip OpenSRE diagnosis and start the execution loop
directly. This split is intentional: current OpenSRE Kubernetes tools are
read-only, while its old generic MCP bridge was only available on the chat
surface—not the non-interactive `investigate` command used by benchmarks.

OpenSRE is installed in the isolated agent container by
`install-opensre.sh`. The registry pins `v0.1.2026.9.2`, the newest release
that retains OpenSRE's non-interactive investigation interface, so runs are
reproducible. SREGym already mounts the filtered kubeconfig into that container,
which OpenSRE discovers through `KUBECONFIG`; no host-side OpenSRE setup is
needed.

## Run

Set the API key for the selected model provider, then run the benchmark like
another registered agent:

```bash
export ANTHROPIC_API_KEY=...
uv run python main.py --agent opensre --model anthropic/claude-sonnet-4-5
```

`AGENT_MODEL_ID` is translated to OpenSRE's provider and reasoning/tool-call
model settings. `AGENT_API_BASE` and `AGENT_API_KEY` select a custom
OpenAI-compatible endpoint.

The OpenSRE alert, raw report, and combined result are written below
`AGENT_LOGS_DIR`. The mitigation transcript and its own result are stored in
the `mitigation` subdirectory. `OPENSRE_MITIGATION_TIMEOUT` controls the
executor timeout (default: 1800 seconds).
