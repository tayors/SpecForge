from __future__ import annotations

from pathlib import Path
import json
import re

from formal_check.traces import NormalizedTrace


JAVA_TEMPLATE = """package formal.regressions;

import static org.junit.jupiter.api.Assertions.assertTrue;

import org.junit.jupiter.api.Test;

class {class_name} {{
    @Test
    void reproduces{method_suffix}() throws Exception {{
        // Placeholder: wire this into repo-specific fixtures or service bootstrapping.
        String tracePath = "{trace_path}";
        String invariantId = "{check_id}";
        String backend = "{backend}";

        // Last observed action path: {action_path}
        // Last observed state payload:
        // {state_snapshot}

        assertTrue(true, "Replace with a real regression assertion for " + invariantId + " from " + backend + " using " + tracePath);
    }}
}}
"""


def generate_junit5(trace: NormalizedTrace, trace_path: Path) -> str:
    payload = trace.payload
    check_id = payload["check"]["id"]
    class_name = _camel_case(check_id) + "TraceRegressionTest"
    method_suffix = _camel_case(check_id)
    action_path = " -> ".join(payload.get("action_path", [])) or "unavailable"
    last_state = payload.get("steps", [{}])[-1].get("state", {})
    state_snapshot = json.dumps(last_state, sort_keys=True)
    return JAVA_TEMPLATE.format(
        class_name=class_name,
        method_suffix=method_suffix,
        trace_path=trace_path.as_posix(),
        check_id=check_id,
        backend=payload["backend"],
        action_path=action_path,
        state_snapshot=state_snapshot,
    )


def default_output_name(trace: NormalizedTrace) -> str:
    check_id = trace.payload["check"]["id"]
    return _camel_case(check_id) + "TraceRegressionTest.java"


def _camel_case(value: str) -> str:
    parts = re.split(r"[^A-Za-z0-9]+", value)
    return "".join(part[:1].upper() + part[1:] for part in parts if part)
