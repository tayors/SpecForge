from __future__ import annotations

from pathlib import Path
import shutil

from importlib.resources import as_file, files


class InitError(RuntimeError):
    """Raised when template scaffolding fails."""


def scaffold_template(template: str, destination: Path, force: bool = False) -> list[Path]:
    template_resource = files("formal_check").joinpath("templates", template)
    if not template_resource.is_dir():
        raise InitError(f"unknown template: {template}")

    destination = destination.resolve()
    created: list[Path] = []

    with as_file(template_resource) as template_root:
        for resource in Path(template_root).rglob("*"):
            relative = resource.relative_to(template_root)
            target = destination / relative
            if resource.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            if target.exists() and not force:
                raise InitError(f"{target} already exists; rerun with --force to overwrite")
            target.parent.mkdir(parents=True, exist_ok=True)
            with resource.open("rb") as src, target.open("wb") as dest:
                shutil.copyfileobj(src, dest)
            created.append(target)

    return created
