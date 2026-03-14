# SpecForge

SpecForge is a TLA+-first formal verification platform for multi-repo Codex use.

It ships three surfaces:

- a Python CLI named `formal-check`
- an installable Codex skill in `skill/formal-check/`
- provider-neutral CI entrypoints in `scripts/`

The platform expects each participating repository to expose a root-level `formal.yaml`.
TLA+ is the source of truth for stateful behavior. `Apalache` is the default bounded checker,
`TLC` is the explicit-state checker, and `Z3Py` companion models handle arithmetic-heavy proof
obligations.

## Quick start

```bash
cd /Users/brahm/formal-check
python3 -m venv .venv
. .venv/bin/activate
pip install -e .
formal-check doctor --project-root examples/workflow
formal-check toolchain sync
formal-check run --project-root examples/workflow --profile pr
formal-check run --project-root examples/arithmetic --profile pr
```

## How to use it

### 1. Use the built-in examples

Check the host and contract:

```bash
formal-check doctor --project-root examples/workflow
```

Run a bounded workflow check:

```bash
formal-check run --project-root examples/workflow --profile pr
```

Run the arithmetic companion-model example:

```bash
formal-check run --project-root examples/arithmetic --profile pr
```

If a run emits a trace path, render it as a readable summary:

```bash
formal-check explain /absolute/path/to/trace.json
```

Generate a Java regression scaffold from the trace:

```bash
formal-check test-generate /absolute/path/to/trace.json --language java
```

### 2. Add it to another repo

Scaffold a starting contract and formal assets into a target repo:

```bash
formal-check init --template workflow --dest /path/to/other-repo
```

or:

```bash
formal-check init --template arithmetic --dest /path/to/other-repo
```

This creates a root-level `formal.yaml` plus starter assets under `formal/`.

Then run the checks in that repo:

```bash
formal-check doctor --project-root /path/to/other-repo
formal-check run --project-root /path/to/other-repo --profile pr
```

### 3. Use it from Codex

Expose the skill to Codex by linking or copying `skill/formal-check/` into your skills directory:

```bash
mkdir -p "${CODEX_HOME:-$HOME/.codex}/skills"
ln -s /Users/brahm/formal-check/skill/formal-check "${CODEX_HOME:-$HOME/.codex}/skills/formal-check"
```

Once installed, Codex can use `$formal-check` in repos that expose `formal.yaml`.

### 4. Use it in CI

For a PR-style run:

```bash
scripts/formal-check-ci.sh --project-root /path/to/repo
```

For a deeper run:

```bash
scripts/formal-check-full.sh --project-root /path/to/repo
```

Both wrappers sync the pinned toolchains before running checks.

## How other people use it

Publish this directory as a shared git repo, then teammates can:

```bash
git clone <formal-check-repo-url>
cd formal-check
python3 -m venv .venv
. .venv/bin/activate
pip install -e .
formal-check toolchain sync
```

Each adopting application repo then adds:

- a root `formal.yaml`
- formal assets under `formal/`
- optional CI calls to `formal-check`
- optional Codex skill installation from `skill/formal-check/`

## Layout

- `src/formal_check/`: CLI and platform runtime
- `schema/`: checked-in JSON Schema for `formal.yaml`
- `examples/`: workflow and arithmetic reference packages
- `skill/formal-check/`: Codex skill that shells through the CLI
- `adapters/java/junit5/`: JUnit 5 regression scaffold template
- `scripts/`: CI-friendly entrypoints

## Contract

Every adopting repo must declare:

- `version`
- `project`
- `maturity`
- `toolchains`
- `specs`
- `invariants`
- `actions`
- `proof_obligations`
- `policy`

See `schema/formal.schema.json` and the example `formal.yaml` files under `examples/`.
