#!/usr/bin/env bash
# Shared by the measurement drivers in this directory. Source it; it changes into the Terraform root and reads every
# name it needs (vault, resource group, subscription, credential, schema, perimeter, NCC, workspace profile) from the
# applied state, and the provider service's model alias from the workspace, so no driver carries an estate-specific
# value. Run the drivers from a shell whose `az` and `databricks` are signed in to the tenant and workspace the
# Terraform was applied with.
#
# Environment knobs (all optional):
#   NOTEBOOK_DIR     workspace folder holding the uploaded notebooks (default: /Shared/<catalog name>)
#   WORKSPACE_LABEL  short name for the measured workspace inside run labels (default: ws-demo, its role label in
#                    notebooks/TOPOLOGY.md; a profile name can carry the workspace id, so it is not used)
#   CLASSIC_NODE     node type for the single-node classic cluster (default below)
#   CLASSIC_RUNTIME  Databricks Runtime for that cluster (default below)
set -euo pipefail
umask 077
MEASURE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TF_DIR="$(dirname "$MEASURE_DIR")"
cd "$TF_DIR" || exit 1
# The NCC private endpoint rule resource sits behind this provider feature flag; without it a plan proposes to drop it.
export DATABRICKS_TF_ENABLED_PF_RESOURCES=databricks_mws_ncc_private_endpoint_rule

log() { echo "[$(date -u +%H:%M:%S)] $*"; }

# Names from the applied state, read once. Perimeter and NCC values are empty when their add-on is not enabled.
TF_CONF="$(terraform show -json | python3 -I -c '
import json, shlex, sys
state = json.load(sys.stdin)["values"]
res = {r["address"]: r["values"] for r in state["root_module"]["resources"]}
outs = {k: v["value"] for k, v in state["outputs"].items()}
kv = res["azurerm_key_vault.demo"]
ncc = res.get("databricks_mws_network_connectivity_config.demo[0]", {})
conf = {
    "SUB": kv["id"].split("/")[2],
    "TENANT": kv["tenant_id"],
    "RG": kv["resource_group_name"],
    "KV": kv["name"],
    "DUMMY": (res.get("azurerm_key_vault_secret.dummy[0]") or res.get("azurerm_key_vault_secret.dummy") or {}).get("name", ""),
    "LANE": res["azurerm_key_vault_secret.lane"]["name"],
    "CREDENTIAL": res["databricks_credential.key_vault"]["name"],
    "CATALOG": res["databricks_catalog.demo"]["name"],
    "SCHEMA": res["databricks_schema.secrets"]["id"],
    "PROVIDER": outs["model_provider_service"],
    "PROFILE": outs.get("databricks_profile") or "",
    "NSP": res.get("azurerm_network_security_perimeter.demo[0]", {}).get("name", ""),
    "NSP_PROFILE": res.get("azurerm_network_security_perimeter_profile.vault[0]", {}).get("name", ""),
    "NCC_ID": ncc.get("network_connectivity_config_id", ""),
    "ACCOUNT_ID": ncc["id"].split("/")[0] if ncc else "",
}
print("\n".join(f"{k}={shlex.quote(str(v))}" for k, v in conf.items()))
')"
eval "$TF_CONF"
unset TF_CONF
db() {
  if [[ -n "$PROFILE" ]]; then command databricks "$@" -p "$PROFILE"; else command databricks "$@"; fi
}
# Optional account profile is separate from the workspace profile; otherwise use unified auth.
account_db() {
  if [[ -n "${DATABRICKS_ACCOUNT_PROFILE:-}" ]]; then
    command databricks "$@" -p "$DATABRICKS_ACCOUNT_PROFILE"
  else
    DATABRICKS_HOST=https://accounts.azuredatabricks.net DATABRICKS_ACCOUNT_ID="$ACCOUNT_ID" \
      ARM_TENANT_ID="$TENANT" DATABRICKS_AUTH_TYPE="${DATABRICKS_ACCOUNT_AUTH_TYPE:-${DATABRICKS_AUTH_TYPE:-azure-cli}}" command databricks "$@"
  fi
}
[[ -n "$DUMMY" ]] || { echo "Measurements require create_dummy_secret = true in a dedicated test deployment." >&2; exit 1; }
ME=$(db current-user me -o json | python3 -I -c 'import json, sys; print(json.load(sys.stdin)["userName"])')
# The model alias the topology notebook's gateway lane sends: the provider service's first target, as Unity Catalog reports it.
MODEL=$(db api get "/api/2.1/unity-catalog/model-provider-services/$PROVIDER" \
  | python3 -I -c 'import json, sys; print(json.load(sys.stdin)["config"]["targets"][0]["model"])')
[ -n "$MODEL" ] || { log "no model alias from the provider service $PROVIDER; refusing to start"; exit 1; }
NOTEBOOK_DIR="${NOTEBOOK_DIR:-/Shared/$CATALOG}"
WORKSPACE_LABEL="${WORKSPACE_LABEL:-ws-demo}"
# The same single-node shape every classic row in notebooks/TOPOLOGY.md was measured on.
CLASSIC_NODE="${CLASSIC_NODE:-Standard_F4s_v2}"
CLASSIC_RUNTIME="${CLASSIC_RUNTIME:-18.x-scala2.13}"
# The topology notebook's Unity Gateway budget (360 s, notebooks/topology_matrix.py) is the longest wait this demo
# justifies anywhere; every wait for a vault or perimeter enforcement edge uses it and reports how much was used.
BUDGET=360

posture() {
  az keyvault show --subscription "$SUB" -n "$KV" \
    --query '{public:properties.publicNetworkAccess, deny:properties.networkAcls.defaultAction, bypass:properties.networkAcls.bypass}' -o json | tr -d '\n '
}
own_identity_read() { az keyvault secret show --subscription "$SUB" --vault-name "$KV" -n "$DUMMY" --query id -o tsv 2>&1 || true; }
uc_read() {
  db api get "/api/2.1/unity-catalog/secrets/$SCHEMA.$DUMMY?include_value=true" 2>&1 | python3 -I -c 'import json, sys
raw = sys.stdin.read()
try:
    d = json.loads(raw)
    print("ok, value present" if d.get("effective_value") or d.get("value") else "no secret value returned")
except json.JSONDecodeError:
    print("UC read failed; response omitted")'
}
# The connector token from the laptop: Unity Catalog mints it, the vault decides by the laptop's network position.
laptop_token_read() {
  local token
  token=$(db api post /api/2.1/unity-catalog/temporary-service-credentials \
    --json "{\"credential_name\": \"$CREDENTIAL\", \"azure_options\": {\"resources\": [\"https://vault.azure.net/.default\"]}}" \
    | python3 -I -c 'import json, sys; print(json.load(sys.stdin)["azure_aad"]["aad_token"])')
  curl -4 -s -m 30 -H @<(printf 'Authorization: Bearer %s\n' "$token") "https://$KV.vault.azure.net/secrets/$DUMMY?api-version=7.4" \
    | python3 -I -c 'import hashlib, json, sys
d = json.load(sys.stdin)
print("laptop, connector token:", "200 value sha256 " + hashlib.sha256(d["value"].encode()).hexdigest()[:12] if "value" in d else "no secret value returned")'
}
laptop_controls() {
  log "laptop control: UC REST read: $(uc_read)"
  log "laptop control: $(laptop_token_read)"
  log "laptop control: own identity: $(own_identity_read | head -c 200 | tr '\n' ' ')"
}
# Restore the open test baseline; callers must check it before installing an EXIT trap.
reopen_vault() {
  az keyvault update --subscription "$SUB" -n "$KV" --public-network-access Enabled --default-action Allow --bypass AzureServices -o none
  log "restored posture: $(posture)"
}
# wait_until <description> <command...>: poll every 5 s until the command succeeds or the budget is spent.
wait_until() {
  local what="$1" t0; shift
  t0=$(date +%s)
  until "$@"; do
    if [ $(( $(date +%s) - t0 )) -ge "$BUDGET" ]; then log "$what: not reached within $BUDGET s (100% of the budget); carrying on"; return 1; fi
    sleep 5
  done
  log "$what after $(( $(date +%s) - t0 )) s"
}
submit_run() {  # <request json file>: submit a one-time run, print its run id
  db jobs submit --json @"$1" --no-wait -o json | python3 -I -c 'import json, sys; print(json.load(sys.stdin)["run_id"])'
}
wait_run() {  # <run id>: poll every 30 s; the notebook's gateway cell alone takes over two minutes, so that wastes at most that much
  local r="$1" state t0
  t0=$(date +%s)
  while true; do
    [[ $(( $(date +%s) - t0 )) -lt "${RUN_TIMEOUT_SECONDS:-3600}" ]] || { log "run timed out; inspect/cancel it in Databricks"; return 1; }
    state=$(db jobs get-run "$r" -o json | python3 -I -c 'import json, sys; s = json.load(sys.stdin)["state"]; print(s["life_cycle_state"], s.get("result_state", ""))')
    case "$state" in TERMINATED*|INTERNAL_ERROR*|SKIPPED*) log "run $r: $state"; [[ "$state" == "TERMINATED SUCCESS" ]]; return;; esac
    sleep 30
  done
}
collect_run() {  # <run id> <output dir>: save the run, its output and its CODE export for the write-up; print the exit claims
  local r="$1" out="$2" task
  db jobs get-run "$r" -o json > "$out/run_${r}_run.json"
  task=$(python3 -I -c 'import json, sys; print(json.load(open(sys.argv[1]))["tasks"][0]["run_id"])' "$out/run_${r}_run.json")
  db jobs get-run-output "$task" -o json > "$out/run_${r}_output.json"
  db jobs export-run "$task" --views-to-export CODE -o json > "$out/run_${r}_export.json"
  log "run $r task $task exit JSON:"
  python3 -I - "$out/run_${r}_output.json" <<'PY'
import json, sys
d = json.load(open(sys.argv[1]))
res = (d.get("notebook_output") or {}).get("result")
err = d.get("error")
if err:
    print("ERROR:", err[:400])
if not res:
    print("no exit value"); sys.exit(0)
for k, v in json.loads(res).get("claims", {}).items():
    print(f"  {k}: {v.get('outcome')}  {json.dumps({kk: vv for kk, vv in v.items() if kk != 'outcome'})[:220]}")
PY
}
# run_matrix <state label> <file tag> <output dir>: the topology notebook on serverless and on a single-node classic
# cluster, with the laptop controls before and after.
run_matrix() {
  local label="$1" tag="$2" out="$3" run_s run_c r
  mkdir -p "$out"
  python3 -I - "$out" "$tag" "$CATALOG" "$label" "$WORKSPACE_LABEL" "$NOTEBOOK_DIR" "$KV" "$MODEL" "$CLASSIC_RUNTIME" "$CLASSIC_NODE" "$ME" <<'PYJSON'
import json, pathlib, sys
out, tag, catalog, label, workspace, notebook_dir, vault, model, runtime, node, user = sys.argv[1:]
for mode in ("serverless", "classic"):
    task = {"task_key": "topology_matrix", "notebook_task": {
        "notebook_path": notebook_dir + "/topology_matrix", "source": "WORKSPACE",
        "base_parameters": {"run_label": f"{label}: {workspace} {mode}", "vault_name": vault, "model": model}}}
    request = {"run_name": f"{catalog} topology matrix: {label}: {workspace} {mode}", "tasks": [task]}
    if mode == "serverless":
        task["environment_key"] = "default"
        request["environments"] = [{"environment_key": "default", "spec": {"environment_version": "6"}}]
    else:
        task["new_cluster"] = {"spark_version": runtime, "node_type_id": node, "num_workers": 0,
                               "data_security_mode": "SINGLE_USER", "single_user_name": user,
                               "spark_conf": {"spark.databricks.cluster.profile": "singleNode", "spark.master": "local[*]"},
                               "custom_tags": {"ResourceClass": "SingleNode"}}
    (pathlib.Path(out) / f"{tag}_{mode}.json").write_text(json.dumps(request))
PYJSON
  run_s=$(submit_run "$out/${tag}_serverless.json")
  run_c=$(submit_run "$out/${tag}_classic.json")
  log "$tag: submitted serverless run $run_s and classic run $run_c"
  laptop_controls
  for r in $run_s $run_c; do wait_run "$r"; done
  laptop_controls
  for r in $run_s $run_c; do collect_run "$r" "$out"; done
}
