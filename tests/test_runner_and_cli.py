from __future__ import annotations

from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock
import hashlib
import io
import json
import subprocess
import tarfile
import tempfile
import textwrap
import unittest
import zipfile

from formal_check.cli import main
from formal_check.contract import Invariant, Spec, load_contract
from formal_check.runner import _execute_tlc, run_contract
from formal_check.traces import load_trace


FIXTURES = Path(__file__).parent / "fixtures" / "traces"


class RunnerAndCliTests(unittest.TestCase):
    def test_execute_tlc_uses_supported_tlc_cli_shape(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            raw_dir = root / "raw"
            raw_dir.mkdir()
            spec_dir = root / "formal"
            spec_dir.mkdir()
            spec_path = spec_dir / "RetryLease.tla"
            cfg_path = spec_dir / "RetryLease.cfg"
            spec_path.write_text("---- MODULE RetryLease ----\n====\n", encoding="utf-8")
            cfg_path.write_text("INIT Init\nNEXT Next\n", encoding="utf-8")
            spec = Spec(
                id="retry-lease",
                kind="tla",
                entry="formal/RetryLease.tla",
                module="RetryLease",
                cfg="formal/RetryLease.cfg",
                checker=None,
                profiles={},
                objective=None,
                root=root,
            )
            invariant = Invariant(
                id="at-most-one-holder",
                spec="retry-lease",
                expr="AtMostOneHolder",
                kind="safety",
                severity="critical",
                code_paths=(),
                test_paths=(),
            )

            with mock.patch("formal_check.runner.subprocess.run") as run_mock:
                run_mock.return_value = subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")
                _execute_tlc(spec, invariant, raw_dir, Path("/tmp/tla2tools.jar"))

            command = run_mock.call_args.args[0]
            self.assertNotIn("-dumpTrace", command)
            config_path = Path(command[command.index("-config") + 1])
            self.assertTrue(config_path.is_relative_to(raw_dir))
            self.assertNotEqual(config_path.parent, spec_dir)
            self.assertIn("-metadir", command)
            self.assertEqual(command[command.index("-metadir") + 1], str(raw_dir / "states"))
            self.assertTrue(Path(command[-1]).is_relative_to(raw_dir))
            self.assertFalse(any(spec_dir.glob(".formal-check-*.cfg")))

    def test_cli_init_scaffolds_template(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            rc = main(["init", "--template", "workflow", "--dest", tmp_dir])
            self.assertEqual(rc, 0)
            self.assertTrue((Path(tmp_dir) / "formal.yaml").exists())
            self.assertTrue((Path(tmp_dir) / "formal" / "RetryLease.tla").exists())

    def test_cli_test_generate_emits_java_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            output = Path(tmp_dir) / "QuotaTraceRegressionTest.java"
            rc = main(
                [
                    "test-generate",
                    str(FIXTURES / "z3.json"),
                    "--language",
                    "java",
                    "--output",
                    str(output),
                ]
            )
            self.assertEqual(rc, 0)
            self.assertIn("class QuotaNeverNegativeTraceRegressionTest", output.read_text(encoding="utf-8"))

    def test_cli_explain_renders_summary(self) -> None:
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            rc = main(["explain", str(FIXTURES / "z3.json")])
        self.assertEqual(rc, 0)
        self.assertIn("quota-never-negative", buffer.getvalue())

    def test_run_contract_blocks_in_enforced_mode(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            project_root = Path(tmp_dir) / "project"
            project_root.mkdir()
            self._write_project(project_root, maturity="enforced")
            manifest_path = self._write_manifest(Path(tmp_dir))
            cache_dir = Path(tmp_dir) / "cache"
            with mock.patch("formal_check.toolchains.shutil.which", return_value="/usr/bin/java"):
                main(["toolchain", "sync", "--cache-dir", str(cache_dir), "--manifest-path", str(manifest_path)])
            contract = load_contract(project_root)
            result = run_contract(contract, profile="pr", cache_dir=cache_dir, manifest_path=manifest_path)
            self.assertEqual(result.exit_code, 2)
            self.assertEqual(len(result.failed_checks), 1)

    def test_run_contract_is_advisory_when_not_enforced(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            project_root = Path(tmp_dir) / "project"
            project_root.mkdir()
            self._write_project(project_root, maturity="advisory")
            manifest_path = self._write_manifest(Path(tmp_dir))
            cache_dir = Path(tmp_dir) / "cache"
            with mock.patch("formal_check.toolchains.shutil.which", return_value="/usr/bin/java"):
                main(["toolchain", "sync", "--cache-dir", str(cache_dir), "--manifest-path", str(manifest_path)])
            contract = load_contract(project_root)
            result = run_contract(contract, profile="pr", cache_dir=cache_dir, manifest_path=manifest_path)
            self.assertEqual(result.exit_code, 0)
            self.assertEqual(len(result.failed_checks), 1)

    def test_run_contract_marks_tlc_invariant_violations_as_failed_without_trace_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            project_root = Path(tmp_dir) / "project"
            (project_root / "formal").mkdir(parents=True)
            (project_root / "formal" / "RetryLease.tla").write_text("---- MODULE RetryLease ----\n====\n", encoding="utf-8")
            (project_root / "formal" / "RetryLease.cfg").write_text("INIT Init\nNEXT Next\n", encoding="utf-8")
            (project_root / "formal.yaml").write_text(
                textwrap.dedent(
                    """\
                    version: 1
                    project:
                      name: tlc-runner-test
                    maturity: enforced
                    toolchains:
                      pinset: default
                    specs:
                      - id: retry-lease
                        kind: tla
                        entry: formal/RetryLease.tla
                        module: RetryLease
                        cfg: formal/RetryLease.cfg
                        checker: tlc
                    invariants:
                      - id: at-most-one-holder
                        spec: retry-lease
                        expr: AtMostOneHolder
                        kind: safety
                        severity: critical
                        maps_to:
                          code:
                            - src/main/java/example/LeaseService.java
                          tests:
                            - src/test/java/example/LeaseServiceTest.java
                    actions: []
                    proof_obligations: []
                    policy:
                      block_on:
                        - critical
                    """
                ),
                encoding="utf-8",
            )
            contract = load_contract(project_root)
            stdout = textwrap.dedent(
                """\
                TLC2 Version 2.19 of 08 August 2024 (rev: 5a47802)
                Error: Invariant AtMostOneHolder is violated.
                Error: The behavior up to this point is:
                State 1: <Initial predicate>
                holder = 0
                """
            )
            installs = {
                "apalache": mock.Mock(executable=Path("/tmp/apalache")),
                "tlc": mock.Mock(executable=Path("/tmp/tla2tools.jar")),
                "z3py": mock.Mock(python_path=None),
            }
            with mock.patch("formal_check.runner.resolve_installs", return_value=installs):
                with mock.patch("formal_check.runner.subprocess.run") as run_mock:
                    run_mock.return_value = subprocess.CompletedProcess(args=[], returncode=12, stdout=stdout, stderr="")
                    result = run_contract(contract, profile="full")

            self.assertEqual(result.exit_code, 2)
            self.assertEqual(len(result.failed_checks), 1)
            self.assertEqual(result.errors, [])
            self.assertEqual(result.failed_checks[0].backend, "tlc")
            self.assertIsNotNone(result.failed_checks[0].trace_path)
            self.assertIsNotNone(result.failed_checks[0].report_path)
            trace = load_trace(result.failed_checks[0].trace_path)
            self.assertEqual(trace.payload["steps"][0]["action"], "<Initial predicate>")
            self.assertEqual(trace.payload["steps"][0]["state"]["holder"], 0)

    def _write_project(self, project_root: Path, maturity: str) -> None:
        (project_root / "formal").mkdir()
        (project_root / "formal" / "proof.py").write_text(
            textwrap.dedent(
                """\
                #!/usr/bin/env python3
                import json
                import sys

                json.dump(
                    {
                        "status": "sat",
                        "summary": "Synthetic counterexample from the test harness.",
                        "states": [{"index": 0, "values": {"value": 1}}],
                    },
                    sys.stdout,
                )
                sys.stdout.write("\\n")
                raise SystemExit(1)
                """
            ),
            encoding="utf-8",
        )
        (project_root / "formal.yaml").write_text(
            textwrap.dedent(
                f"""\
                version: 1
                project:
                  name: runner-test
                maturity: {maturity}
                toolchains:
                  pinset: default
                specs:
                  - id: quota
                    kind: z3py
                    entry: formal/proof.py
                invariants: []
                actions: []
                proof_obligations:
                  - id: quota-never-negative
                    spec: quota
                    backend: z3
                    entry: formal/proof.py
                    objective: sat_counterexample
                    severity: critical
                policy:
                  block_on:
                    - critical
                """
            ),
            encoding="utf-8",
        )

    def _write_manifest(self, root: Path) -> Path:
        apalache_archive = root / "apalache.tgz"
        with tarfile.open(apalache_archive, "w:gz") as archive:
            payload = root / "apalache-mc"
            payload.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
            archive.add(payload, arcname="bin/apalache-mc")

        tlc_jar = root / "tla2tools.jar"
        tlc_jar.write_text("fake jar", encoding="utf-8")

        z3_wheel = root / "z3_solver.whl"
        with zipfile.ZipFile(z3_wheel, "w") as archive:
            archive.writestr("z3/__init__.py", "__all__ = []\n")

        def digest(path: Path) -> str:
            return hashlib.sha256(path.read_bytes()).hexdigest()

        manifest = {
            "version": 1,
            "toolchains": {
                "apalache": {
                    "version": "test",
                    "artifacts": [{"platform": "any", "filename": apalache_archive.name, "url": apalache_archive.as_uri(), "sha256": digest(apalache_archive), "format": "tgz"}],
                    "binary_glob": "bin/apalache-mc",
                },
                "tlc": {
                    "version": "test",
                    "artifacts": [{"platform": "any", "filename": tlc_jar.name, "url": tlc_jar.as_uri(), "sha256": digest(tlc_jar), "format": "file"}],
                    "binary_glob": "tla2tools.jar",
                },
                "z3py": {
                    "version": "test",
                    "artifacts": [{"platform": "any", "filename": z3_wheel.name, "url": z3_wheel.as_uri(), "sha256": digest(z3_wheel), "format": "wheel"}],
                    "python_path_glob": "z3",
                },
            },
        }
        manifest_path = root / "toolchains.json"
        manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        return manifest_path


if __name__ == "__main__":
    unittest.main()
