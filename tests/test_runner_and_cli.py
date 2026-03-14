from __future__ import annotations

from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock
import hashlib
import io
import json
import tarfile
import tempfile
import textwrap
import unittest
import zipfile

from formal_check.cli import main
from formal_check.contract import load_contract
from formal_check.runner import run_contract
from formal_check.traces import load_trace


FIXTURES = Path(__file__).parent / "fixtures" / "traces"


class RunnerAndCliTests(unittest.TestCase):
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
