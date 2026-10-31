#!/usr/bin/env bash
# Rows A1 and A2 of notebooks/TOPOLOGY.md: what ACCESS on the service credential grants on its own. Runs
# notebooks/credential_access_probe.py as a service principal that holds USE CATALOG, USE SCHEMA, REFERENCE SECRET on
# the secrets and EXECUTE on the provider service but no READ SECRET anywhere: first as a control, then with ACCESS on
# the credential. ACCESS is revoked again on every exit path. The principal needs workspace access and the right to
# run serverless jobs; the notebook itself only reports lengths and SHA-256 prefixes, never a value.
#
#   measurements/credential_access_probe.sh <service principal application id> [output dir]
# shellcheck source=measurements/lib.sh
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"
SP="${1:?usage: credential_access_probe.sh <service principal application id> [output dir]}"
[[ "$SP" =~ ^[[:xdigit:]]{8}-[[:xdigit:]]{4}-[[:xdigit:]]{4}-[[:xdigit:]]{4}-[[:xdigit:]]{12}$ ]] || { echo "Service principal application ID must be a GUID." >&2; exit 2; }
OUT="${2:-$MEASURE_DIR/out/credential_access}"
mkdir -p "$OUT"

grants() { db api get "/api/2.1/unity-catalog/permissions/credential/$CREDENTIAL?principal=$SP" | tr -d '\n '; }
change_access() {  # add | remove
  db api patch "/api/2.1/unity-catalog/permissions/credential/$CREDENTIAL" \
    --json "{\"changes\": [{\"principal\": \"$SP\", \"$1\": [\"ACCESS\"]}]}" > /dev/null
}
restore() {
  log "RESTORE: revoking ACCESS on $CREDENTIAL from $SP"
  change_access remove
  log "grants for the principal now: $(grants)"
}
submit_probe() {  # <tag> <run label>
  local tag="$1" label="$2" run
  python3 -I - "$OUT/$tag.json" "$CATALOG" "$label" "$SP" "$NOTEBOOK_DIR" "$KV" <<'PYJSON'
import json, pathlib, sys
path, catalog, label, principal, notebook_dir, vault = sys.argv[1:]
request = {
    "run_name": f"{catalog} credential ACCESS probe: {label}",
    "run_as": {"service_principal_name": principal},
    "tasks": [{"task_key": "credential_access_probe", "notebook_task": {
        "notebook_path": notebook_dir + "/credential_access_probe", "source": "WORKSPACE",
        "base_parameters": {"run_label": label, "vault_name": vault}}, "environment_key": "default"}],
    "environments": [{"environment_key": "default", "spec": {"environment_version": "6"}}],
}
pathlib.Path(path).write_text(json.dumps(request))
PYJSON
  run=$(submit_run "$OUT/$tag.json")
  log "$tag: submitted run $run"
  wait_run "$run"
  collect_run "$run" "$OUT"
}

log "pre-check: grants for the principal: $(grants)"
case "$(grants)" in *'"ACCESS"'*) log "the principal already holds ACCESS; refusing to start"; exit 1;; esac
trap restore EXIT
trap 'exit 1' INT TERM

submit_probe control "control: reference-only SP, no ACCESS on the credential"
log "granting ACCESS on $CREDENTIAL to $SP"
change_access add
log "grants for the principal now: $(grants)"
submit_probe access "reference-only SP, ACCESS on the credential"
log "done"
