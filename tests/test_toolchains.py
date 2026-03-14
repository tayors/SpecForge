from __future__ import annotations

from pathlib import Path
from unittest import mock
import hashlib
import json
import tarfile
import tempfile
import unittest
import zipfile

from formal_check.toolchains import ToolchainError, load_manifest, sync_toolchains


class ToolchainTests(unittest.TestCase):
    def test_syncs_local_fixture_toolchains(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp = Path(tmp_dir)
            manifest_path = self._write_manifest(tmp)
            cache_dir = tmp / "cache"
            with mock.patch("formal_check.toolchains.shutil.which", return_value="/usr/bin/java"):
                installs = sync_toolchains(cache_dir=cache_dir, manifest_path=manifest_path)

            self.assertTrue(installs["apalache"].executable and installs["apalache"].executable.exists())
            self.assertTrue(installs["tlc"].executable and installs["tlc"].executable.exists())
            self.assertTrue(installs["z3py"].python_path and (installs["z3py"].python_path / "z3").exists())

    def test_rejects_bad_checksum(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp = Path(tmp_dir)
            manifest_path = self._write_manifest(tmp, corrupt_checksum=True)
            cache_dir = tmp / "cache"
            with mock.patch("formal_check.toolchains.shutil.which", return_value="/usr/bin/java"):
                with self.assertRaises(ToolchainError):
                    sync_toolchains(cache_dir=cache_dir, manifest_path=manifest_path)

    def _write_manifest(self, root: Path, corrupt_checksum: bool = False) -> Path:
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
            value = hashlib.sha256(path.read_bytes()).hexdigest()
            return "0" * 64 if corrupt_checksum else value

        manifest = {
            "version": 1,
            "toolchains": {
                "apalache": {
                    "version": "test",
                    "artifacts": [
                        {
                            "platform": "any",
                            "filename": apalache_archive.name,
                            "url": apalache_archive.as_uri(),
                            "sha256": digest(apalache_archive),
                            "format": "tgz",
                        }
                    ],
                    "binary_glob": "bin/apalache-mc",
                },
                "tlc": {
                    "version": "test",
                    "artifacts": [
                        {
                            "platform": "any",
                            "filename": tlc_jar.name,
                            "url": tlc_jar.as_uri(),
                            "sha256": digest(tlc_jar),
                            "format": "file",
                        }
                    ],
                    "binary_glob": "tla2tools.jar",
                },
                "z3py": {
                    "version": "test",
                    "artifacts": [
                        {
                            "platform": "any",
                            "filename": z3_wheel.name,
                            "url": z3_wheel.as_uri(),
                            "sha256": digest(z3_wheel),
                            "format": "wheel",
                        }
                    ],
                    "python_path_glob": "z3",
                },
            },
        }
        manifest_path = root / "toolchains.json"
        manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        return manifest_path


if __name__ == "__main__":
    unittest.main()
