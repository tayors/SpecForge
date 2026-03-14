from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any
import hashlib
import json
import platform
import shutil
import stat
import tarfile
import urllib.request
import zipfile

from importlib.resources import files


class ToolchainError(RuntimeError):
    """Raised when the toolchain cache is missing or inconsistent."""


@dataclass(frozen=True)
class ToolchainInstall:
    name: str
    version: str
    artifact: Path
    home: Path
    executable: Path | None = None
    python_path: Path | None = None


def default_cache_dir() -> Path:
    return Path.home() / ".cache" / "formal-check" / "toolchains"


def platform_key() -> str:
    system = platform.system().lower()
    machine = platform.machine().lower()
    aliases = {
        ("darwin", "arm64"): "darwin-arm64",
        ("darwin", "aarch64"): "darwin-arm64",
        ("darwin", "x86_64"): "darwin-x86_64",
        ("linux", "x86_64"): "linux-x86_64",
        ("linux", "amd64"): "linux-x86_64",
        ("linux", "aarch64"): "linux-arm64",
        ("linux", "arm64"): "linux-arm64",
        ("windows", "amd64"): "windows-x86_64",
        ("windows", "x86_64"): "windows-x86_64",
    }
    return aliases.get((system, machine), f"{system}-{machine}")


def load_manifest(manifest_path: str | Path | None = None) -> dict[str, Any]:
    if manifest_path:
        return json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    manifest_text = files("formal_check").joinpath("schema/toolchains.json").read_text(encoding="utf-8")
    return json.loads(manifest_text)


def doctor(project_root: Path, cache_dir: Path, manifest_path: str | Path | None = None) -> list[str]:
    lines = [
        f"Python: ok ({platform.python_version()})",
        f"Java: {'ok' if shutil.which('java') else 'missing'}",
        f"Platform: {platform_key()}",
    ]
    contract_path = project_root / "formal.yaml"
    lines.append(f"formal.yaml: {'present' if contract_path.exists() else 'missing'} ({contract_path})")

    manifest = load_manifest(manifest_path)
    lines.append(f"Toolchain manifest: ok (version {manifest['version']})")

    for name, details in manifest["toolchains"].items():
        version = details["version"]
        home = _toolchain_home(cache_dir, name, version)
        status = "present" if home.exists() else "missing"
        lines.append(f"{name}: {status} ({home})")

    return lines


def sync_toolchains(
    cache_dir: Path | None = None,
    manifest_path: str | Path | None = None,
    force: bool = False,
) -> dict[str, ToolchainInstall]:
    cache = cache_dir or default_cache_dir()
    cache.mkdir(parents=True, exist_ok=True)
    manifest = load_manifest(manifest_path)
    installs: dict[str, ToolchainInstall] = {}

    if not shutil.which("java"):
        raise ToolchainError("java is required to run Apalache and TLC")

    for name, details in manifest["toolchains"].items():
        installs[name] = _sync_one(cache, name, details, force=force)
    return installs


def resolve_installs(
    cache_dir: Path | None = None,
    manifest_path: str | Path | None = None,
) -> dict[str, ToolchainInstall]:
    cache = cache_dir or default_cache_dir()
    manifest = load_manifest(manifest_path)
    installs: dict[str, ToolchainInstall] = {}
    for name, details in manifest["toolchains"].items():
        home = _toolchain_home(cache, name, details["version"])
        if not home.exists():
            raise ToolchainError(f"toolchain {name} is missing from {home}; run `formal-check toolchain sync`")
        installs[name] = _install_from_home(name, details["version"], home, details)
    return installs


def _sync_one(cache: Path, name: str, details: dict[str, Any], force: bool) -> ToolchainInstall:
    home = _toolchain_home(cache, name, details["version"])
    artifact = _pick_artifact(details["artifacts"])
    artifact_dir = home / "downloads"
    artifact_dir.mkdir(parents=True, exist_ok=True)
    artifact_path = artifact_dir / artifact["filename"]
    marker_path = home / ".complete"

    if force and home.exists():
        shutil.rmtree(home)
        artifact_dir.mkdir(parents=True, exist_ok=True)

    if not artifact_path.exists() or force:
        _download(artifact["url"], artifact_path)
    _verify_sha256(artifact_path, artifact["sha256"])

    if not marker_path.exists() or force:
        _extract_artifact(artifact_path, home, artifact["format"])
        marker_path.write_text(json.dumps({"toolchain": name, "version": details["version"]}), encoding="utf-8")

    install = _install_from_home(name, details["version"], home, details)
    if install.executable:
        current_mode = install.executable.stat().st_mode
        install.executable.chmod(current_mode | stat.S_IXUSR)
    return install


def _pick_artifact(artifacts: list[dict[str, Any]]) -> dict[str, Any]:
    current_platform = platform_key()
    for artifact in artifacts:
        if artifact["platform"] == current_platform:
            return artifact
    for artifact in artifacts:
        if artifact["platform"] == "any":
            return artifact
    raise ToolchainError(f"no artifact published for platform {current_platform}")


def _download(url: str, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(destination.name + ".partial")
    temporary.unlink(missing_ok=True)
    try:
        request = urllib.request.Request(url, headers={"User-Agent": "formal-check/0.1.0"})
        with urllib.request.urlopen(request, timeout=120) as response, temporary.open("wb") as out:
            shutil.copyfileobj(response, out)
        temporary.replace(destination)
    except Exception as exc:
        temporary.unlink(missing_ok=True)
        raise ToolchainError(f"failed to download {url}: {exc}") from exc


def _verify_sha256(path: Path, expected: str) -> None:
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if digest != expected:
        raise ToolchainError(f"checksum mismatch for {path}: expected {expected}, got {digest}")


def _extract_artifact(artifact_path: Path, home: Path, format_name: str) -> None:
    home.mkdir(parents=True, exist_ok=True)
    if format_name == "file":
        shutil.copy2(artifact_path, home / artifact_path.name)
        return
    if format_name == "tgz":
        with tarfile.open(artifact_path, "r:gz") as archive:
            archive.extractall(home)
        return
    if format_name in {"zip", "wheel"}:
        with zipfile.ZipFile(artifact_path) as archive:
            archive.extractall(home)
        return
    raise ToolchainError(f"unsupported artifact format: {format_name}")


def _install_from_home(name: str, version: str, home: Path, details: dict[str, Any]) -> ToolchainInstall:
    if name == "apalache":
        executable = _find_first(home, details["binary_glob"])
        if executable is None:
            raise ToolchainError(f"apalache binary not found under {home}")
        return ToolchainInstall(name=name, version=version, artifact=home / "downloads", home=home, executable=executable)

    if name == "tlc":
        executable = _find_first(home, details["binary_glob"])
        if executable is None:
            raise ToolchainError(f"tla2tools.jar not found under {home}")
        return ToolchainInstall(name=name, version=version, artifact=home / "downloads", home=home, executable=executable)

    if name == "z3py":
        python_path = home
        if not (python_path / "z3").exists():
            raise ToolchainError(f"z3 python package not found under {home}")
        return ToolchainInstall(name=name, version=version, artifact=home / "downloads", home=home, python_path=python_path)

    raise ToolchainError(f"unsupported toolchain: {name}")


def _toolchain_home(cache_dir: Path, name: str, version: str) -> Path:
    return cache_dir / name / version


def _find_first(root: Path, pattern: str) -> Path | None:
    direct = root / pattern
    if direct.exists():
        return direct
    name = Path(pattern).name
    for candidate in root.rglob(name):
        return candidate
    return None
