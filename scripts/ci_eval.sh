#!/usr/bin/env bash
# CI gate for SHAIL retrieval evolution.
#
# Runs eval suite + unit tests. Fails non-zero on:
#   - golden snapshot drift
#   - any unit test failure
#   - any non-xfail eval test failure
#
# Use `make eval-refresh` locally before committing intentional snapshot changes.
set -euo pipefail

cd "$(dirname "$0")/.."

PY=${PY:-services_env/bin/python}

echo "[ci_eval] Unit tests…"
$PY -m pytest apps/shail/tests/ -q

echo "[ci_eval] Retrieval-precision eval suite…"
$PY -m pytest apps/shail/tests/retrieval_precision.py -v --tb=short

echo "[ci_eval] OK"
