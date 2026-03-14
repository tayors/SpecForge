from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
import json
import os
import subprocess
import sys
import tempfile
import uuid

from formal_check.contract import Action, Contract, Invariant, ProofObligation, Spec
from formal_check.toolchains import ToolchainError, resolve_installs
from formal_check.traces import (
    NormalizedTrace,
    normalize_apalache_trace,
    normalize_tlc_trace,
    normalize_z3_result,
)


@dataclass(frozen=True)
class CheckResult:
    check_id: str
    spec_id: str
    backend: str
    status: str
    severity: str
    blocking: bool
    summary: str
    trace_path: Path | None
    report_path: Path | None


@dataclass(frozen=True)
class RunResult:
    project_root: Path
    profile: str
    checks: tuple[CheckResult, ...]
    warnings: tuple[str, ...]

    @property
    def failed_checks(self) -> list[CheckResult]:
        return [check for check in self.checks if check.status == "failed"]

    @property
    def blocking_failures(self) -> list[CheckResult]:
        return [check for check in self.failed_checks if check.blocking]

    @property
    def errors(self) -> list[CheckResult]:
        return [check for check in self.checks if check.status == "error"]

    @property
    def exit_code(self) -> int:
        if self.errors:
            return 1
        if self.blocking_failures:
            return 2
        return 0


def run_contract(
    contract: Contract,
    *,
    profile: str,
    changed_from: str | None = None,
    cache_dir: Path | None = None,
    manifest_path: str | Path | None = None,
) -> RunResult:
    warnings: list[str] = []
    changed_files = _changed_files(contract.root, changed_from, warnings)
    spec_ids = contract.impacted_spec_ids(changed_files)
    installs = resolve_installs(cache_dir=cache_dir, manifest_path=manifest_path)
    checks: list[CheckResult] = []

    for spec_id in spec_ids:
        spec = contract.specs[spec_id]
        if spec.kind == "tla":
            checker = spec.checker_for(profile) or "apalache"
            for invariant in contract.invariants_for_spec(spec_id):
                checks.append(
                    _run_tla_invariant(
                        contract=contract,
                        spec=spec,
                        invariant=invariant,
                        actions=contract.actions_for_spec(spec_id),
                        checker=checker,
                        profile=profile,
                        installs=installs,
                    )
                )
        elif spec.kind == "z3py":
            obligations = contract.proof_obligations_for_spec(spec_id)
            if not obligations:
                warnings.append(f"spec {spec_id} has no proof obligations")
            for obligation in obligations:
                checks.append(
                    _run_z3_obligation(
                        contract=contract,
                        spec=spec,
                        obligation=obligation,
                        installs=installs,
                    )
                )
        else:
            checks.append(
                CheckResult(
                    check_id=spec.id,
                    spec_id=spec.id,
                    backend="unknown",
                    status="error",
                    severity="critical",
                    blocking=True,
                    summary=f"unsupported spec kind: {spec.kind}",
                    trace_path=None,
                    report_path=None,
                )
            )

    return RunResult(project_root=contract.root, profile=profile, checks=tuple(checks), warnings=tuple(warnings))


def _run_tla_invariant(
    *,
    contract: Contract,
    spec: Spec,
    invariant: Invariant,
    actions: list[Action],
    checker: str,
    profile: str,
    installs: dict[str, Any],
) -> CheckResult:
    run_id = _run_id(spec.id, invariant.id)
    bundle_dir = contract.output_dir / run_id
    raw_dir = bundle_dir / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    stdout_path = raw_dir / "stdout.txt"
    stderr_path = raw_dir / "stderr.txt"
    trace_path = None
    report_path = None

    try:
        if checker == "apalache":
            process = _execute_apalache(spec, invariant, raw_dir, installs["apalache"].executable, profile)
            stdout_path.write_text(process.stdout, encoding="utf-8")
            stderr_path.write_text(process.stderr, encoding="utf-8")
            if process.returncode == 0:
                return CheckResult(
                    check_id=invariant.id,
                    spec_id=spec.id,
                    backend="apalache",
                    status="passed",
                    severity=invariant.severity,
                    blocking=False,
                    summary=f"{invariant.id} holds under Apalache.",
                    trace_path=None,
                    report_path=None,
                )

            raw_trace = _find_apalache_trace(raw_dir)
            if raw_trace is None:
                return _runtime_error(invariant.id, spec.id, "apalache", invariant.severity, stdout_path, stderr_path)

            trace = normalize_apalache_trace(
                raw_trace,
                spec_id=spec.id,
                spec_kind=spec.kind,
                check_id=invariant.id,
                expr=invariant.expr,
                severity=invariant.severity,
                code_paths=list(invariant.code_paths),
                test_paths=list(invariant.test_paths),
            )
            trace_path, report_path = _write_trace_bundle(trace, bundle_dir)
            return CheckResult(
                check_id=invariant.id,
                spec_id=spec.id,
                backend="apalache",
                status="failed",
                severity=invariant.severity,
                blocking=contract.should_block(invariant.severity),
                summary=f"{invariant.id} failed under Apalache.",
                trace_path=trace_path,
                report_path=report_path,
            )

        if checker == "tlc":
            process, raw_trace = _execute_tlc(spec, invariant, raw_dir, installs["tlc"].executable)
            stdout_path.write_text(process.stdout, encoding="utf-8")
            stderr_path.write_text(process.stderr, encoding="utf-8")
            if process.returncode == 0:
                return CheckResult(
                    check_id=invariant.id,
                    spec_id=spec.id,
                    backend="tlc",
                    status="passed",
                    severity=invariant.severity,
                    blocking=False,
                    summary=f"{invariant.id} holds under TLC.",
                    trace_path=None,
                    report_path=None,
                )

            if raw_trace is None or not raw_trace.exists():
                return _runtime_error(invariant.id, spec.id, "tlc", invariant.severity, stdout_path, stderr_path)

            trace = normalize_tlc_trace(
                raw_trace,
                spec_id=spec.id,
                spec_kind=spec.kind,
                check_id=invariant.id,
                expr=invariant.expr,
                severity=invariant.severity,
                code_paths=list(invariant.code_paths),
                test_paths=list(invariant.test_paths),
            )
            trace_path, report_path = _write_trace_bundle(trace, bundle_dir)
            return CheckResult(
                check_id=invariant.id,
                spec_id=spec.id,
                backend="tlc",
                status="failed",
                severity=invariant.severity,
                blocking=contract.should_block(invariant.severity),
                summary=f"{invariant.id} failed under TLC.",
                trace_path=trace_path,
                report_path=report_path,
            )

        return CheckResult(
            check_id=invariant.id,
            spec_id=spec.id,
            backend=checker,
            status="error",
            severity=invariant.severity,
            blocking=True,
            summary=f"unsupported checker {checker}",
            trace_path=None,
            report_path=None,
        )
    except (ToolchainError, OSError, subprocess.SubprocessError) as exc:
        return CheckResult(
            check_id=invariant.id,
            spec_id=spec.id,
            backend=checker,
            status="error",
            severity=invariant.severity,
            blocking=True,
            summary=str(exc),
            trace_path=trace_path,
            report_path=report_path,
        )


def _run_z3_obligation(
    *,
    contract: Contract,
    spec: Spec,
    obligation: ProofObligation,
    installs: dict[str, Any],
) -> CheckResult:
    run_id = _run_id(spec.id, obligation.id)
    bundle_dir = contract.output_dir / run_id
    raw_dir = bundle_dir / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    stdout_path = raw_dir / "stdout.txt"
    stderr_path = raw_dir / "stderr.txt"

    env = os.environ.copy()
    z3_python = installs["z3py"].python_path
    if z3_python is not None:
        existing = env.get("PYTHONPATH")
        env["PYTHONPATH"] = f"{z3_python}{os.pathsep}{existing}" if existing else str(z3_python)

    process = subprocess.run(
        [sys.executable, str(obligation.entry_path), "--objective", obligation.objective, "--emit-json"],
        cwd=contract.root,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    stdout_path.write_text(process.stdout, encoding="utf-8")
    stderr_path.write_text(process.stderr, encoding="utf-8")

    try:
        payload = json.loads(process.stdout or "{}")
    except json.JSONDecodeError:
        return _runtime_error(obligation.id, spec.id, "z3", obligation.severity, stdout_path, stderr_path)

    status = payload.get("status")
    if process.returncode == 0 and status == "unsat":
        return CheckResult(
            check_id=obligation.id,
            spec_id=spec.id,
            backend="z3",
            status="passed",
            severity=obligation.severity,
            blocking=False,
            summary=f"{obligation.id} holds under Z3.",
            trace_path=None,
            report_path=None,
        )

    if status != "sat":
        return _runtime_error(obligation.id, spec.id, "z3", obligation.severity, stdout_path, stderr_path)

    trace = normalize_z3_result(
        payload,
        spec_id=spec.id,
        check_id=obligation.id,
        expr=obligation.id,
        severity=obligation.severity,
        objective=obligation.objective,
        entry=obligation.entry,
    )
    trace_path, report_path = _write_trace_bundle(trace, bundle_dir)
    return CheckResult(
        check_id=obligation.id,
        spec_id=spec.id,
        backend="z3",
        status="failed",
        severity=obligation.severity,
        blocking=contract.should_block(obligation.severity),
        summary=f"{obligation.id} failed under Z3.",
        trace_path=trace_path,
        report_path=report_path,
    )


def _execute_apalache(spec: Spec, invariant: Invariant, raw_dir: Path, executable: Path | None, profile: str) -> subprocess.CompletedProcess[str]:
    if executable is None:
        raise ToolchainError("Apalache executable is unavailable")

    command = [
        str(executable),
        "check",
        f"--out-dir={raw_dir}",
        f"--run-dir={raw_dir / 'run'}",
        "--output-traces=true",
        "--max-error=1",
        f"--length={spec.profile_length(profile)}",
        f"--inv={invariant.expr}",
    ]
    if spec.cfg:
        command.append(f"--config={spec.cfg_path}")
    else:
        command.extend(["--init=Init", "--next=Next"])
    workers = spec.profile_workers(profile)
    if workers:
        command.append(f"--workers={workers}")
    command.append(str(spec.entry_path))

    return subprocess.run(command, cwd=spec.root, capture_output=True, text=True, check=False)


def _execute_tlc(
    spec: Spec,
    invariant: Invariant,
    raw_dir: Path,
    jar_path: Path | None,
) -> tuple[subprocess.CompletedProcess[str], Path]:
    if jar_path is None:
        raise ToolchainError("tla2tools.jar is unavailable")

    dump_path = raw_dir / "trace.json"
    config_path = raw_dir / "generated.cfg"
    config_path.write_text(_generated_tlc_config(spec, invariant), encoding="utf-8")
    command = [
        "java",
        "-cp",
        str(jar_path),
        "tlc2.TLC",
        "-config",
        str(config_path),
        "-dumpTrace",
        "json",
        str(dump_path),
        str(spec.entry_path),
    ]
    return subprocess.run(command, cwd=spec.root, capture_output=True, text=True, check=False), dump_path


def _generated_tlc_config(spec: Spec, invariant: Invariant) -> str:
    base = ""
    if spec.cfg_path and spec.cfg_path.exists():
        lines = spec.cfg_path.read_text(encoding="utf-8").splitlines()
        kept = [line for line in lines if not line.strip().startswith(("INVARIANT", "PROPERTY"))]
        base = "\n".join(kept).strip()
    if base:
        base += "\n\n"
    return base + f"INVARIANT {invariant.expr}\n"


def _find_apalache_trace(raw_dir: Path) -> Path | None:
    for pattern in ("*.itf.json", "**/*.itf.json", "counterexample*.json", "**/counterexample*.json"):
        matches = list(raw_dir.glob(pattern))
        if matches:
            return matches[0]
    return None


def _write_trace_bundle(trace: NormalizedTrace, bundle_dir: Path) -> tuple[Path, Path]:
    trace_path = bundle_dir / "trace.json"
    report_path = bundle_dir / "summary.md"
    trace_path.write_text(trace.to_json(), encoding="utf-8")
    report_path.write_text(trace.to_markdown(), encoding="utf-8")
    return trace_path, report_path


def _runtime_error(check_id: str, spec_id: str, backend: str, severity: str, stdout_path: Path, stderr_path: Path) -> CheckResult:
    summary = f"{backend} execution failed; inspect {stdout_path} and {stderr_path}"
    return CheckResult(
        check_id=check_id,
        spec_id=spec_id,
        backend=backend,
        status="error",
        severity=severity,
        blocking=True,
        summary=summary,
        trace_path=None,
        report_path=None,
    )


def _changed_files(project_root: Path, changed_from: str | None, warnings: list[str]) -> list[str] | None:
    if not changed_from:
        return None
    try:
        process = subprocess.run(
            ["git", "diff", "--name-only", changed_from, "HEAD"],
            cwd=project_root,
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError as exc:
        warnings.append(f"unable to collect changed files: {exc}")
        return None

    if process.returncode != 0:
        warnings.append("git diff failed; running all specs")
        return None

    files = [line.strip() for line in process.stdout.splitlines() if line.strip()]
    return files


def _run_id(spec_id: str, check_id: str) -> str:
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    suffix = uuid.uuid4().hex[:8]
    return f"{timestamp}-{spec_id}-{check_id}-{suffix}"
