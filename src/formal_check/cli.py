from __future__ import annotations

from pathlib import Path
import argparse
import sys

from formal_check.contract import ContractError, load_contract
from formal_check.junit import default_output_name, generate_junit5
from formal_check.runner import run_contract
from formal_check.scaffold import InitError, scaffold_template
from formal_check.toolchains import ToolchainError, default_cache_dir, doctor, sync_toolchains
from formal_check.traces import load_trace


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    try:
        return args.handler(args)
    except (ContractError, InitError, ToolchainError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="formal-check")
    subparsers = parser.add_subparsers(dest="command", required=True)

    doctor_parser = subparsers.add_parser("doctor", help="check host prerequisites and cache state")
    doctor_parser.add_argument("--project-root", default=".", help="repository root containing formal.yaml")
    doctor_parser.add_argument("--cache-dir", default=None, help="toolchain cache directory")
    doctor_parser.add_argument("--manifest-path", default=None, help="override the toolchain manifest path")
    doctor_parser.set_defaults(handler=_handle_doctor)

    toolchain_parser = subparsers.add_parser("toolchain", help="manage pinned solver toolchains")
    toolchain_subparsers = toolchain_parser.add_subparsers(dest="toolchain_command", required=True)
    sync_parser = toolchain_subparsers.add_parser("sync", help="download pinned toolchain artifacts")
    sync_parser.add_argument("--cache-dir", default=None, help="toolchain cache directory")
    sync_parser.add_argument("--manifest-path", default=None, help="override the toolchain manifest path")
    sync_parser.add_argument("--force", action="store_true", help="re-download and re-extract every toolchain")
    sync_parser.set_defaults(handler=_handle_toolchain_sync)

    init_parser = subparsers.add_parser("init", help="scaffold formal assets into a target repository")
    init_parser.add_argument("--template", required=True, choices=["workflow", "arithmetic"])
    init_parser.add_argument("--dest", default=".", help="destination directory")
    init_parser.add_argument("--force", action="store_true", help="overwrite files that already exist")
    init_parser.set_defaults(handler=_handle_init)

    run_parser = subparsers.add_parser("run", help="run formal checks for a repository")
    run_parser.add_argument("--project-root", default=".", help="repository root containing formal.yaml")
    run_parser.add_argument("--profile", default="pr", choices=["pr", "full"])
    run_parser.add_argument("--changed-from", default=None, help="git ref used to scope checks to changed mappings")
    run_parser.add_argument("--cache-dir", default=None, help="toolchain cache directory")
    run_parser.add_argument("--manifest-path", default=None, help="override the toolchain manifest path")
    run_parser.set_defaults(handler=_handle_run)

    explain_parser = subparsers.add_parser("explain", help="render a normalized trace as markdown")
    explain_parser.add_argument("trace_json", help="path to a normalized trace.json")
    explain_parser.set_defaults(handler=_handle_explain)

    test_parser = subparsers.add_parser("test-generate", help="generate a regression scaffold from a trace")
    test_parser.add_argument("trace_json", help="path to a normalized trace.json")
    test_parser.add_argument("--language", required=True, choices=["java"])
    test_parser.add_argument("--output", default=None, help="output path for the generated scaffold")
    test_parser.set_defaults(handler=_handle_test_generate)

    return parser


def _handle_doctor(args: argparse.Namespace) -> int:
    project_root = Path(args.project_root).resolve()
    cache_dir = Path(args.cache_dir).resolve() if args.cache_dir else default_cache_dir()
    for line in doctor(project_root, cache_dir, manifest_path=args.manifest_path):
        print(line)
    return 0


def _handle_toolchain_sync(args: argparse.Namespace) -> int:
    cache_dir = Path(args.cache_dir).resolve() if args.cache_dir else default_cache_dir()
    installs = sync_toolchains(cache_dir=cache_dir, manifest_path=args.manifest_path, force=args.force)
    for name, install in installs.items():
        target = install.executable or install.python_path or install.home
        print(f"{name}: synced {install.version} -> {target}")
    return 0


def _handle_init(args: argparse.Namespace) -> int:
    destination = Path(args.dest).resolve()
    created = scaffold_template(args.template, destination, force=args.force)
    print(f"scaffolded {args.template} template into {destination}")
    for path in created:
        print(path)
    return 0


def _handle_run(args: argparse.Namespace) -> int:
    project_root = Path(args.project_root).resolve()
    cache_dir = Path(args.cache_dir).resolve() if args.cache_dir else default_cache_dir()
    contract = load_contract(project_root)
    result = run_contract(
        contract,
        profile=args.profile,
        changed_from=args.changed_from,
        cache_dir=cache_dir,
        manifest_path=args.manifest_path,
    )
    print(f"project: {contract.project_name}")
    print(f"profile: {args.profile}")
    if result.warnings:
        print("warnings:")
        for warning in result.warnings:
            print(f"  - {warning}")
    if not result.checks:
        print("no checks were selected")
        return 0
    for check in result.checks:
        print(f"{check.status}: {check.spec_id}/{check.check_id} via {check.backend} ({check.summary})")
        if check.trace_path:
            print(f"  trace: {check.trace_path}")
        if check.report_path:
            print(f"  report: {check.report_path}")
    return result.exit_code


def _handle_explain(args: argparse.Namespace) -> int:
    trace = load_trace(Path(args.trace_json).resolve())
    print(trace.to_markdown(), end="")
    return 0


def _handle_test_generate(args: argparse.Namespace) -> int:
    trace_path = Path(args.trace_json).resolve()
    trace = load_trace(trace_path)
    if args.language != "java":
        raise ToolchainError(f"unsupported language: {args.language}")
    rendered = generate_junit5(trace, trace_path)
    if args.output:
        destination = Path(args.output).resolve()
    else:
        destination = Path.cwd() / default_output_name(trace)
    destination.write_text(rendered, encoding="utf-8")
    print(destination)
    return 0
