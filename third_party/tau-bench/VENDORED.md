# Vendored: τ-bench (Sierra), unmodified

- Source: https://github.com/sierra-research/tau-bench at commit `59a200c6d575d595120f1cb70fea53cef0632f6b`
- License: MIT (see `LICENSE`, copyright 2024 Sierra)
- Copied: `LICENSE`, `README.md`, `setup.py`, `tau_bench/`. Left out: `historical_trajectories/` (50 MB) and `few_shot_data/`, which the agent does not use.
- Integrity: `MANIFEST.sha256` lists the SHA-256 of every copied file. `tests/integration/test_tau_airline.py` checks all 103 files against it, so any edit here fails the test suite.

ConsentTrace tests the **airline agent** (`tau_bench.agents.tool_calling_agent.ToolCallingAgent` with the airline environment's policy wiki, tools and database) as a third-party agent under test. The adapter `targets/tau_airline/adapter.py` drives it without changing it:

- **User**: the trusted turns of a ConsentTrace case stand in for τ-bench's LLM user simulator, through the same user interface.
- **Tools**: `Env.tools_map` entries are wrapped to record each call, derive write receipts from the rows the call changed, and apply injections.
- **Model**: the agent's `litellm.completion` name is bound to ConsentTrace's model client, so calls can be recorded, replayed and metered.

The fixes ConsentTrace's report led to live outside this directory. `v1-gated` adds a confirmation gate in front of the write tools. `v1-fixed` also appends one paragraph to the policy the agent is given.
