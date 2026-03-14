from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
import json

from importlib.resources import files

import jsonschema
import yaml


class ContractError(RuntimeError):
    """Raised when a formal.yaml contract is missing or invalid."""


@dataclass(frozen=True)
class Spec:
    id: str
    kind: str
    entry: str
    module: str | None
    cfg: str | None
    checker: str | None
    profiles: dict[str, dict[str, Any]]
    objective: str | None
    root: Path = field(repr=False)

    @property
    def entry_path(self) -> Path:
        return self.root / self.entry

    @property
    def cfg_path(self) -> Path | None:
        return self.root / self.cfg if self.cfg else None

    def checker_for(self, profile: str) -> str | None:
        profile_data = self.profiles.get(profile, {})
        if "checker" in profile_data:
            return str(profile_data["checker"])
        if self.checker:
            return self.checker
        if self.kind == "tla":
            return "apalache"
        return None

    def profile_length(self, profile: str) -> int:
        profile_data = self.profiles.get(profile, {})
        if "length" in profile_data:
            return int(profile_data["length"])
        return 8 if profile == "pr" else 20

    def profile_workers(self, profile: str) -> int | None:
        profile_data = self.profiles.get(profile, {})
        if "workers" not in profile_data:
            return None
        return int(profile_data["workers"])


@dataclass(frozen=True)
class Invariant:
    id: str
    spec: str
    expr: str
    kind: str
    severity: str
    code_paths: tuple[str, ...]
    test_paths: tuple[str, ...]


@dataclass(frozen=True)
class Action:
    id: str
    spec: str
    tla_action: str
    implemented_by: tuple[str, ...]


@dataclass(frozen=True)
class ProofObligation:
    id: str
    spec: str | None
    source_spec: str | None
    backend: str
    entry: str
    objective: str
    severity: str
    root: Path = field(repr=False)

    @property
    def entry_path(self) -> Path:
        return self.root / self.entry


@dataclass(frozen=True)
class Contract:
    root: Path
    version: int
    project: dict[str, Any]
    maturity: str
    toolchains: dict[str, Any]
    specs: dict[str, Spec]
    invariants: tuple[Invariant, ...]
    actions: tuple[Action, ...]
    proof_obligations: tuple[ProofObligation, ...]
    policy: dict[str, Any]
    raw: dict[str, Any] = field(repr=False)

    @property
    def output_dir(self) -> Path:
        return self.root / self.policy.get("output_dir", "output/formal")

    @property
    def project_name(self) -> str:
        return str(self.project["name"])

    def invariants_for_spec(self, spec_id: str) -> list[Invariant]:
        return [item for item in self.invariants if item.spec == spec_id]

    def actions_for_spec(self, spec_id: str) -> list[Action]:
        return [item for item in self.actions if item.spec == spec_id]

    def proof_obligations_for_spec(self, spec_id: str) -> list[ProofObligation]:
        matches: list[ProofObligation] = []
        for obligation in self.proof_obligations:
            if obligation.spec == spec_id or obligation.source_spec == spec_id:
                matches.append(obligation)
        return matches

    def should_block(self, severity: str) -> bool:
        if self.maturity != "enforced":
            return False
        block_on = {str(item) for item in self.policy.get("block_on", [])}
        return severity in block_on

    def impacted_spec_ids(self, changed_files: list[str] | None) -> list[str]:
        if not changed_files:
            return list(self.specs.keys())

        normalized_changes = {_normalize_relpath(self.root, path) for path in changed_files}
        impacted: list[str] = []
        for spec_id, spec in self.specs.items():
            candidate_paths = {spec.entry}
            if spec.cfg:
                candidate_paths.add(spec.cfg)

            for invariant in self.invariants_for_spec(spec_id):
                candidate_paths.update(invariant.code_paths)
                candidate_paths.update(invariant.test_paths)

            for action in self.actions_for_spec(spec_id):
                candidate_paths.update(action.implemented_by)

            for obligation in self.proof_obligations_for_spec(spec_id):
                candidate_paths.add(obligation.entry)

            if any(_paths_overlap(change, candidate) for change in normalized_changes for candidate in candidate_paths):
                impacted.append(spec_id)

        return impacted or list(self.specs.keys())


def load_contract(project_root: str | Path) -> Contract:
    root = Path(project_root).resolve()
    contract_path = root / "formal.yaml"
    if not contract_path.exists():
        raise ContractError(f"missing formal.yaml at {contract_path}")

    try:
        data = yaml.safe_load(contract_path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ContractError(f"failed to parse {contract_path}: {exc}") from exc

    if not isinstance(data, dict):
        raise ContractError("formal.yaml must contain a YAML object at the top level")

    _validate_schema(data)

    specs = {
        item["id"]: Spec(
            id=item["id"],
            kind=item["kind"],
            entry=item["entry"],
            module=item.get("module"),
            cfg=item.get("cfg"),
            checker=item.get("checker"),
            profiles=item.get("profiles", {}),
            objective=item.get("objective"),
            root=root,
        )
        for item in data["specs"]
    }
    invariants = tuple(
        Invariant(
            id=item["id"],
            spec=item["spec"],
            expr=item["expr"],
            kind=item["kind"],
            severity=item["severity"],
            code_paths=tuple(item["maps_to"]["code"]),
            test_paths=tuple(item["maps_to"]["tests"]),
        )
        for item in data["invariants"]
    )
    actions = tuple(
        Action(
            id=item["id"],
            spec=item["spec"],
            tla_action=item["tla_action"],
            implemented_by=tuple(item["implemented_by"]),
        )
        for item in data["actions"]
    )
    obligations = tuple(
        ProofObligation(
            id=item["id"],
            spec=item.get("spec"),
            source_spec=item.get("source_spec"),
            backend=item["backend"],
            entry=item["entry"],
            objective=item["objective"],
            severity=item.get("severity", "high"),
            root=root,
        )
        for item in data["proof_obligations"]
    )

    _validate_cross_references(specs, invariants, actions, obligations)

    return Contract(
        root=root,
        version=int(data["version"]),
        project=data["project"],
        maturity=data["maturity"],
        toolchains=data["toolchains"],
        specs=specs,
        invariants=invariants,
        actions=actions,
        proof_obligations=obligations,
        policy=data["policy"],
        raw=data,
    )


def schema_dict() -> dict[str, Any]:
    schema_text = files("formal_check").joinpath("schema/formal.schema.json").read_text(encoding="utf-8")
    return json.loads(schema_text)


def _validate_schema(data: dict[str, Any]) -> None:
    validator = jsonschema.Draft202012Validator(schema_dict())
    errors = sorted(validator.iter_errors(data), key=lambda item: list(item.path))
    if not errors:
        return
    details = "; ".join(f"{'/'.join(str(part) for part in error.path) or '<root>'}: {error.message}" for error in errors)
    raise ContractError(f"formal.yaml schema validation failed: {details}")


def _validate_cross_references(
    specs: dict[str, Spec],
    invariants: tuple[Invariant, ...],
    actions: tuple[Action, ...],
    obligations: tuple[ProofObligation, ...],
) -> None:
    errors: list[str] = []
    spec_ids = set(specs)

    for invariant in invariants:
        if invariant.spec not in spec_ids:
            errors.append(f"invariant {invariant.id} references unknown spec {invariant.spec}")

    for action in actions:
        if action.spec not in spec_ids:
            errors.append(f"action {action.id} references unknown spec {action.spec}")

    for obligation in obligations:
        target = obligation.spec or obligation.source_spec
        if target not in spec_ids:
            errors.append(f"proof obligation {obligation.id} references unknown spec {target}")

    if errors:
        raise ContractError("formal.yaml cross-reference validation failed: " + "; ".join(errors))


def _normalize_relpath(root: Path, path_value: str) -> str:
    path = Path(path_value)
    if path.is_absolute():
        try:
            path = path.relative_to(root)
        except ValueError:
            return path.as_posix()
    return path.as_posix()


def _paths_overlap(left: str, right: str) -> bool:
    if left == right:
        return True
    left_prefix = left.rstrip("/") + "/"
    right_prefix = right.rstrip("/") + "/"
    return left.startswith(right_prefix) or right.startswith(left_prefix)
