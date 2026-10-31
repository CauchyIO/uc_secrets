#!/usr/bin/env bash
# Phase 7 (notebooks/TOPOLOGY.md rows 15 to 20): the demo vault inside a Network Security Perimeter (nsp.tf applied in its default Learning mode).
#
# The vault stays OPEN (public access enabled, no network rules) throughout. Microsoft documents that an association
# in Enforced mode overrides the vault's own publicNetworkAccess, blocks trusted services unless an inbound rule
# admits them, and exempts private endpoint traffic. Three perimeter states, each measured with the topology notebook
# on serverless and classic compute plus the laptop controls:
#   P1  Learning, no rule     the Terraform-declared state
#   P2  Enforced, no rule
#   P3  Enforced + inbound rule admitting resources of the connector identity's subscription
# The perimeter is flipped with the Azure CLI, not Terraform, so the state file never sees the intermediate modes.
# On every exit path the association goes back to Learning, the rule is deleted, and `terraform plan` proves the
# estate matches the declared configuration again.
#
#   measurements/nsp_perimeter.sh [output dir]     default output dir: measurements/out/nsp_perimeter (gitignored)
# shellcheck source=measurements/lib.sh
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"
OUT="${1:-$MEASURE_DIR/out/nsp_perimeter}"
mkdir -p "$OUT"
RULE=admit-connector-subscription

mode() { az network perimeter association show --subscription "$SUB" -g "$RG" --perimeter-name "$NSP" -n "$KV" --query accessMode -o tsv; }
rules() { az network perimeter profile access-rule list --subscription "$SUB" -g "$RG" --perimeter-name "$NSP" --profile-name "$NSP_PROFILE" --query '[].name' -o json | tr -d '\n '; }
own_identity_refused() { own_identity_read | grep -q -i "forbidden"; }
own_identity_ok() { own_identity_read | grep -q "https://"; }
uc_read_ok() { uc_read | grep -q "ok, value present"; }

restore() {
  log "RESTORE: perimeter back to Learning, rule removed"
  az network perimeter profile access-rule delete --subscription "$SUB" -g "$RG" --perimeter-name "$NSP" --profile-name "$NSP_PROFILE" -n "$RULE" -y -o none 2>&1 | grep -v -i "not found" || true
  az network perimeter association update --subscription "$SUB" -g "$RG" --perimeter-name "$NSP" -n "$KV" --access-mode Learning -o none
  log "restored: mode $(mode), rules $(rules), vault $(posture)"
  wait_until "own identity read admitted again" own_identity_ok
  log "own identity read after restore: $(own_identity_read | head -c 120 | tr '\n' ' ')"
  log "UC read after restore: $(uc_read)"
  log "terraform plan after restore (expect no changes):"
  terraform plan -no-color -input=false -detailed-exitcode 2>&1 | grep -E '^(No changes|Plan:|Error)' || log "plan output had no summary line"
}

[ -n "$NSP" ] || { log "no perimeter in the state; apply with enable_network_security_perimeter = true first"; exit 1; }
log "pre-check: vault $(posture), perimeter $NSP mode $(mode), rules $(rules)"
[[ "$(posture)" == '{"public":"Enabled","deny":"Allow","bypass":"AzureServices"}' ]] || { log "requires the open test baseline (Enabled/Allow/AzureServices); refusing to start"; exit 1; }
[ "$(mode)" = "Learning" ] || { log "perimeter is not in Learning mode; refusing to start"; exit 1; }
[ "$(rules)" = "[]" ] || { log "profile already has rules; refusing to start"; exit 1; }

trap restore EXIT
trap 'exit 1' INT TERM

# P1: Learning, as applied.
run_matrix "vault open + NSP Learning" P1 "$OUT"

# P2: Enforced, no rule.
log "P2: switching the association to Enforced"
az network perimeter association update --subscription "$SUB" -g "$RG" --perimeter-name "$NSP" -n "$KV" --access-mode Enforced -o none
log "mode now $(mode); vault still $(posture)"
wait_until "own identity read refused (enforcement live)" own_identity_refused
log "own identity read after Enforced: $(own_identity_read | head -c 300 | tr '\n' ' ')"
run_matrix "vault open + NSP Enforced, no rule" P2 "$OUT"

# P3: Enforced + inbound subscription rule.
log "P3: adding the inbound subscription rule for the connector identity's subscription"
az network perimeter profile access-rule create --subscription "$SUB" -g "$RG" --perimeter-name "$NSP" --profile-name "$NSP_PROFILE" -n "$RULE" \
  --direction Inbound --subscriptions "[0].id=/subscriptions/$SUB" -o none
log "rules now $(rules)"
wait_until "UC read admitted by the rule" uc_read_ok
log "UC read after the rule: $(uc_read)"
run_matrix "vault open + NSP Enforced + subscription rule" P3 "$OUT"
log "perimeter measurements done"
