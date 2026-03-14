#!/usr/bin/env python3
"""Example Z3Py companion model for formal-check."""

from __future__ import annotations

import argparse
import json
import sys


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--objective", required=True)
    parser.add_argument("--emit-json", action="store_true")
    args = parser.parse_args()

    if args.objective != "sat_counterexample":
        raise SystemExit(f"unsupported objective: {args.objective}")

    try:
        import z3
    except ImportError as exc:
        raise SystemExit(f"z3 import failed: {exc}") from exc

    quota = z3.Int("quota")
    spend = z3.Int("spend")
    next_quota = z3.Int("next_quota")

    solver = z3.Solver()
    solver.add(quota == 3)
    solver.add(spend == 5)
    solver.add(next_quota == quota - spend)
    solver.add(next_quota < 0)

    status = solver.check()
    result = {
        "status": str(status),
        "objective": args.objective,
        "variables": ["quota", "spend", "next_quota"],
        "states": [],
        "summary": "Counterexample where quota goes negative after a spend.",
    }
    if status == z3.sat:
        model = solver.model()
        result["states"] = [
            {
                "index": 0,
                "values": {
                    "quota": model[quota].as_long(),
                    "spend": model[spend].as_long(),
                    "next_quota": model[next_quota].as_long(),
                },
            }
        ]

    if args.emit_json:
        json.dump(result, sys.stdout, indent=2)
        sys.stdout.write("\n")
    else:
        print(result["summary"])

    return 1 if status == z3.sat else 0


if __name__ == "__main__":
    raise SystemExit(main())
