from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any
import json


@dataclass(frozen=True)
class NormalizedTrace:
    payload: dict[str, Any]

    def to_json(self) -> str:
        return json.dumps(self.payload, indent=2, sort_keys=True) + "\n"

    def to_markdown(self) -> str:
        check = self.payload["check"]
        spec = self.payload["spec"]
        mappings = self.payload.get("mappings", {})
        code_refs = ", ".join(mappings.get("code", [])) or "(none mapped)"
        test_refs = ", ".join(mappings.get("tests", [])) or "(none mapped)"
        action_path = " -> ".join(self.payload.get("action_path", [])) or "(action labels unavailable)"
        states = self.payload.get("steps", [])
        lines = [
            f"# {check['id']}",
            "",
            f"- Status: {self.payload['status']}",
            f"- Backend: {self.payload['backend']}",
            f"- Spec: {spec['id']} ({spec['kind']})",
            f"- Check: {check['kind']} `{check['expr']}`",
            f"- Severity: {check.get('severity', 'n/a')}",
            f"- Action path: {action_path}",
            f"- Code targets: {code_refs}",
            f"- Test targets: {test_refs}",
            "",
            "## Summary",
            "",
            self.payload.get("summary", "No summary provided."),
            "",
            "## States",
            "",
        ]
        for step in states:
            action = step.get("action") or "(unknown)"
            values = json.dumps(step.get("state", {}), sort_keys=True)
            lines.append(f"- Step {step['index']}: {action} {values}")
        return "\n".join(lines) + "\n"


def normalize_apalache_trace(
    trace_path: Path,
    *,
    spec_id: str,
    spec_kind: str,
    check_id: str,
    expr: str,
    severity: str,
    code_paths: list[str],
    test_paths: list[str],
) -> NormalizedTrace:
    data = json.loads(trace_path.read_text(encoding="utf-8"))
    states = data.get("states", [])
    normalized_steps: list[dict[str, Any]] = []
    action_path: list[str] = []
    for index, state in enumerate(states):
        if isinstance(state, dict):
            meta = state.get("#meta", {})
            action = meta.get("action") or meta.get("description")
            if action:
                action_path.append(str(action))
            cleaned = {key: value for key, value in state.items() if not key.startswith("#")}
        else:
            cleaned = {"raw": state}
            action = None
        normalized_steps.append({"index": index, "action": action, "state": cleaned})

    return NormalizedTrace(
        {
            "version": 1,
            "backend": "apalache",
            "status": "failed",
            "summary": f"Invariant {expr} failed in Apalache.",
            "spec": {"id": spec_id, "kind": spec_kind},
            "check": {"id": check_id, "kind": "invariant", "expr": expr, "severity": severity},
            "action_path": action_path,
            "steps": normalized_steps,
            "mappings": {"code": code_paths, "tests": test_paths},
            "raw_artifacts": {"trace": str(trace_path)},
        }
    )


def normalize_tlc_trace(
    trace_path: Path,
    *,
    spec_id: str,
    spec_kind: str,
    check_id: str,
    expr: str,
    severity: str,
    code_paths: list[str],
    test_paths: list[str],
) -> NormalizedTrace:
    data = json.loads(trace_path.read_text(encoding="utf-8"))
    raw_states = data["states"] if isinstance(data, dict) and "states" in data else data
    normalized_steps: list[dict[str, Any]] = []
    action_path: list[str] = []
    for index, state in enumerate(raw_states):
        if isinstance(state, dict):
            action = state.get("action")
            if action:
                action_path.append(str(action))
            cleaned = state.get("state", state)
        else:
            cleaned = {"raw": state}
            action = None
        normalized_steps.append({"index": index, "action": action, "state": cleaned})

    return NormalizedTrace(
        {
            "version": 1,
            "backend": "tlc",
            "status": "failed",
            "summary": f"Invariant {expr} failed in TLC.",
            "spec": {"id": spec_id, "kind": spec_kind},
            "check": {"id": check_id, "kind": "invariant", "expr": expr, "severity": severity},
            "action_path": action_path,
            "steps": normalized_steps,
            "mappings": {"code": code_paths, "tests": test_paths},
            "raw_artifacts": {"trace": str(trace_path)},
        }
    )


def normalize_z3_result(
    data: dict[str, Any],
    *,
    spec_id: str,
    check_id: str,
    expr: str,
    severity: str,
    objective: str,
    entry: str,
) -> NormalizedTrace:
    steps = []
    for state in data.get("states", []):
        steps.append({"index": state.get("index", len(steps)), "action": objective, "state": state.get("values", {})})

    return NormalizedTrace(
        {
            "version": 1,
            "backend": "z3",
            "status": "failed",
            "summary": data.get("summary", f"Proof obligation {expr} failed in Z3."),
            "spec": {"id": spec_id, "kind": "z3py"},
            "check": {"id": check_id, "kind": "proof_obligation", "expr": expr, "severity": severity, "objective": objective},
            "action_path": [],
            "steps": steps,
            "mappings": {"code": [entry], "tests": []},
            "raw_artifacts": {"entry": entry},
        }
    )


def load_trace(trace_path: Path) -> NormalizedTrace:
    return NormalizedTrace(json.loads(trace_path.read_text(encoding="utf-8")))
