#!/usr/bin/env bash
# Phases 3 and 4: the vault SEALED (public access disabled, default Deny, bypass None) while the NCC private endpoint
# rule is ESTABLISHED and the NCC is bound to the workspace. Runs the topology notebook on serverless and classic
# compute with the laptop controls, after waiting out the ten minutes Databricks documents for a rule change to reach
# serverless compute, measured from the rule's last update (its approval). Phase 3 ran this ten minutes after the
# approval (the open-vault re-checks followed at 22 minutes and 9 h 45 min); phase 4 ran it again once serverless had
# started to resolve the vault to the endpoint address, 9 h 45 min after the approval. Reopens the vault on every exit path.
#
#   measurements/sealed_with_ncc.sh "<state label>" [output dir]     e.g. "vault sealed + NCC live"
# shellcheck source=measurements/lib.sh
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"
LABEL="${1:?usage: sealed_with_ncc.sh \"<state label>\" [output dir]}"
OUT="${2:-$MEASURE_DIR/out/sealed_with_ncc}"
mkdir -p "$OUT"
sealed_refusal() { own_identity_read | grep -q 'bypass is not set\|Public network access is disabled'; }

restore() {
  log "RESTORE: reopening the vault"
  reopen_vault
  log "UC read after restore: $(uc_read)"
}

log "pre-check posture: $(posture)"
[[ "$(posture)" == '{"public":"Enabled","deny":"Allow","bypass":"AzureServices"}' ]] || { log "requires the open test baseline (Enabled/Allow/AzureServices); refusing to start"; exit 1; }
[ -n "$NCC_ID" ] || { log "no NCC in the state; apply with enable_ncc_private_endpoint = true first"; exit 1; }
RULE=$(terraform output -no-color -json ncc_private_endpoint)
log "ncc rule: $RULE"
case "$RULE" in *ESTABLISHED*) ;; *) log "rule not ESTABLISHED; refusing to start"; exit 1;; esac

trap restore EXIT
trap 'exit 1' INT TERM

# Databricks documents ten minutes for a new binding and for rule changes to take effect; measured from the rule's
# last update (its approval) rather than guessed. Use account unified authentication instead
# of embedding a first-party application ID or manually transporting a bearer token.
UPDATED_MS=$(account_db account network-connectivity get-network-connectivity-configuration "$NCC_ID" -o json \
  | python3 -I -c 'import json, sys; rule_id = sys.argv[1]; rules = json.load(sys.stdin)["egress_config"]["target_rules"]["azure_private_endpoint_rules"]; print(next(r["updated_time"] for r in rules if r["rule_id"] == rule_id))' \
    "$(python3 -I -c 'import json,sys; print(json.loads(sys.argv[1])["rule_id"])' "$RULE")")
READY=$(( UPDATED_MS / 1000 + 600 ))
NOW=$(date +%s)
if [ "$NOW" -lt "$READY" ]; then log "waiting $(( READY - NOW )) s for the documented ten-minute propagation window"; sleep $(( READY - NOW )); fi

log "SEAL: public Disabled, default Deny, bypass None"
az keyvault update --subscription "$SUB" -n "$KV" --public-network-access Disabled --default-action Deny --bypass None -o none
log "sealed posture: $(posture)"
T0=$(date +%s)
wait_until "direct read with my identity refused (enforcement live)" sealed_refusal || { log "aborting: the runs must not land inside the enforcement lag"; exit 1; }
run_matrix "$LABEL" sealed "$OUT"
log "done; sealed for $(( $(date +%s) - T0 )) s"
