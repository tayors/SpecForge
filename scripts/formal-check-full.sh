#!/usr/bin/env bash
set -euo pipefail

formal-check toolchain sync
formal-check run --profile full "$@"
