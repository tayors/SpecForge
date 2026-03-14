---
name: "formal-check"
description: "Use when a repository exposes a root-level `formal.yaml` or when the user wants SpecForge-style TLA+-first formal checking, Apalache or TLC bounded checks, Z3Py companion-model runs, counterexample explanation, or regression-test scaffolding. Always shell through the `formal-check` CLI rather than re-implementing solver logic in-prompt."
---

# SpecForge Skill

Drive the SpecForge platform through the `formal-check` CLI. Do not re-implement solver orchestration in-prompt.
Treat `formal.yaml` as the contract of record and TLA+ as the source of truth for stateful behavior.

## Prerequisite check

1. Verify the CLI is available:

```bash
command -v formal-check >/dev/null 2>&1
```

If it is missing, pause and tell the user to install this repo in a virtualenv and expose the
`formal-check` command.

2. Run the health check in the target repo:

```bash
formal-check doctor --project-root /path/to/repo
```

If `formal.yaml` is missing, only use this skill if the user explicitly wants to scaffold formal assets.

## Default workflow

1. If the toolchain cache is missing, sync it:

```bash
formal-check toolchain sync
```

2. Run the right profile:

```bash
formal-check run --project-root /path/to/repo --profile pr
```

3. If a check fails and prints a `trace:` path, explain it:

```bash
formal-check explain /absolute/path/to/trace.json
```

4. Use the normalized summary to:
- name the failing invariant or proof obligation
- name the backend that found it
- map the failure to code and test targets
- produce a targeted fix prompt

5. If the user wants a regression scaffold, generate one:

```bash
formal-check test-generate /absolute/path/to/trace.json --language java
```

## Guardrails

- Always trust the CLI output over memory.
- Do not invent solver results when the CLI or toolchain has not run.
- Keep TLA+ as the behavioral source of truth; use Z3Py companion models only for explicit proof obligations.
- When the trace omits action labels, say so directly instead of guessing.

## References

Open only what you need:

- Modeling guidance: `references/modeling-patterns.md`
- Counterexample interpretation: `references/counterexamples.md`
