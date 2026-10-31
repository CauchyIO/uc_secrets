#!/usr/bin/env bash
# Isolate variable validation and helper tests from live tfvars/state and cloud providers.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
umask 077
TEST_DIR="$(mktemp -d "${TMPDIR:-/tmp}/uc-secrets-tests.XXXXXX")"
trap 'rm -rf "$TEST_DIR"' EXIT
# Only the root variable declarations, their fixture and Python helper are copied.
# The root APIM ephemeral resource cannot be mocked by Terraform, so it is excluded.
cp "$ROOT/variables.tf" "$TEST_DIR/"
cp -R "$ROOT/tests" "$TEST_DIR/"
mkdir -p "$TEST_DIR/modules/uc_schema_secret_storage" "$TEST_DIR/scripts" "$TEST_DIR/measurements"
cp "$ROOT/modules/uc_schema_secret_storage/"*.py "$TEST_DIR/modules/uc_schema_secret_storage/"
cp "$ROOT/scripts/"*.py "$ROOT/scripts/"*.sh "$TEST_DIR/scripts/"
cp "$ROOT/measurements/"*.py "$ROOT/measurements/"*.sh "$TEST_DIR/measurements/"
# TF_VAR/TF_CLI_ARGS can silently replace the test inputs; remove them in this subshell.
while IFS= read -r key; do unset "$key"; done < <(env | sed -n 's/^\(TF_VAR_[^=]*\|TF_CLI_ARGS[^=]*\|TF_DATA_DIR\)=.*/\1/p')
cd "$TEST_DIR"
terraform init -backend=false -input=false -no-color >/dev/null
terraform test -no-color
python3 -m unittest discover -s tests -p 'test_*.py' -v
