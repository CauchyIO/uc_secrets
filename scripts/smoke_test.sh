#!/usr/bin/env bash
# End-to-end proof against the real workspace and the real Key Vault. No mocks.
#
#   ./scripts/smoke_test.sh secret                 show the Unity Catalog secret and its live value from Key Vault (masked)
#   ./scripts/smoke_test.sh query <model-alias>    chat completion through Unity Gateway; the gateway fetches the key itself
#   ./scripts/smoke_test.sh rotate <new-value>     write a new value into Key Vault, then re-read it through Unity Catalog
#   ./scripts/smoke_test.sh reseed                 copy the real lane secret from APIM back into Key Vault (undo a rotate)
#   ./scripts/smoke_test.sh callers                Key Vault audit rows: who read the secrets, from which IP (diagnostics add-on)
#   ./scripts/smoke_test.sh perimeter              Network Security Perimeter access rows: each request's source, traffic type and the rule that decided it (nsp.tf + diagnostics)
#
# Run from the Terraform directory after `terraform apply`.
set -euo pipefail

TF_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$TF_DIR"
PROFILE="${DATABRICKS_PROFILE:-$(terraform output -json | python3 -I -c 'import json,sys; print(json.load(sys.stdin).get("databricks_profile", {}).get("value") or "")')}"
db() {
  if [[ -n "$PROFILE" ]]; then command databricks "$@" -p "$PROFILE"; else command databricks "$@"; fi
}
PROVIDER="$(terraform output -raw model_provider_service)"
SECRET_FULL_NAME="$(terraform output -raw unity_catalog_secret_for_lane)"
KEY_VAULT="$(terraform output -raw key_vault_name)"
SECRET_NAME="${SECRET_FULL_NAME##*.}"

host() { terraform output -raw workspace_host; }
token() { db auth token | python3 -I -c 'import json,sys; print(json.load(sys.stdin)["access_token"])'; }
# The repo rule: no part of a secret value is ever printed, only its length and the first 12 hex digits of its SHA-256.
mask() { python3 -I -c 'import hashlib,sys; v=sys.stdin.read().strip(); print(f"len={len(v)} sha256={hashlib.sha256(v.encode()).hexdigest()[:12]}")'; }

cmd_secret() {
  echo "# Unity Catalog view of the secret (no value):"
  db api get "/api/2.1/unity-catalog/secrets/${SECRET_FULL_NAME}"
  echo
  echo "# Live read of the value through Unity Catalog (fetched from Key Vault on demand, masked here):"
  db api get "/api/2.1/unity-catalog/secrets/${SECRET_FULL_NAME}?include_value=true" \
    | python3 -I -c 'import json,sys; print(json.load(sys.stdin)["effective_value"])' | mask
}

cmd_query() {
  local model="${1:?usage: scripts/smoke_test.sh query <model-alias>}"
  echo "# POST $(host)/ai-gateway/openai/v1/chat/completions  (Databricks-Model-Provider-Service: ${PROVIDER})"
  local access_token
  access_token="$(token)" || return
  curl --connect-timeout 10 --max-time 120 -sS --fail-with-body "$(host)/ai-gateway/openai/v1/chat/completions" \
    -H @<(printf 'Authorization: Bearer %s\n' "$access_token") \
    -H "Databricks-Model-Provider-Service: ${PROVIDER}" \
    -H "Content-Type: application/json" \
    -d "$(python3 -I -c 'import json,sys; print(json.dumps({"model":sys.argv[1],"messages":[{"role":"user","content":"Reply with the single word: ok"}]}))' "$model")"
  echo
}

cmd_rotate() {
  local value="${1:?usage: scripts/smoke_test.sh rotate <new-value>}"
  echo "# Writing a new version of ${SECRET_NAME} into ${KEY_VAULT} (Key Vault is the only writable side):"
  printf %s "$value" | az keyvault secret set --vault-name "$KEY_VAULT" --name "$SECRET_NAME" --file /dev/stdin --query '{name:name,version:id}' -o json
  echo "# Reading it back through Unity Catalog, no Databricks-side change was made:"
  db api get "/api/2.1/unity-catalog/secrets/${SECRET_FULL_NAME}?include_value=true" \
    | python3 -I -c 'import json,sys; print(json.load(sys.stdin)["effective_value"])' | mask
}

cmd_reseed() {
  echo "# Copying the Databricks-lane shared secret from APIM into ${KEY_VAULT}/${SECRET_NAME} through a pipe:"
  local value
  value="$(az rest --method post --url "$(terraform output -raw apim_named_value_list_url)" --query value -o tsv)" || return
  [[ -n "$value" ]] || { echo "APIM returned no value; refusing to overwrite the secret." >&2; return 1; }
  printf %s "$value" | az keyvault secret set --vault-name "$KEY_VAULT" --name "$SECRET_NAME" --file /dev/stdin --query '{name:name,version:id}' -o json
}

cmd_callers() {
  local ws
  if ! ws="$(terraform output -raw log_analytics_workspace_customer_id 2>/dev/null)" || [[ -z "$ws" ]]; then
    echo "Set enable_diagnostics = true in terraform.tfvars and run terraform apply before querying audit logs." >&2
    return 1
  fi
  echo "# Key Vault AuditEvent rows for ${KEY_VAULT}. Log Analytics ingestion lags the call by minutes."
  echo "# The service-credential identity has object id $(terraform output -raw key_vault_reader_principal_id)."
  az monitor log-analytics query -w "$ws" -o table --analytics-query "AzureDiagnostics
    | where ResourceProvider == 'MICROSOFT.KEYVAULT' and Resource == toupper('${KEY_VAULT}')
    | project TimeGenerated, OperationName, ResultType, CallerIPAddress, identity_claim_oid_g, clientInfo_s
    | order by TimeGenerated desc"
}

cmd_perimeter() {
  local ws
  if ! ws="$(terraform output -raw log_analytics_workspace_customer_id 2>/dev/null)" || [[ -z "$ws" ]]; then
    echo "Set enable_diagnostics = true and enable_network_security_perimeter = true in terraform.tfvars and run terraform apply before querying perimeter logs." >&2
    return 1
  fi
  echo "# Perimeter access rows for the vault's profile. Public rows carry the caller's address; Private rows came through a private endpoint."
  echo "# In Learning mode every row is logged as allowed with the rule that decided it; in Enforced mode denied rows name no rule."
  az monitor log-analytics query -w "$ws" -o table --analytics-query "NSPAccessLogs
    | project TimeGenerated, Category, ResultAction, TrafficType, SourceIpAddress, OperationName, MatchedRule, Profile
    | order by TimeGenerated desc"
}

case "${1:-}" in
  secret) cmd_secret ;;
  query)  shift; cmd_query "$@" ;;
  rotate) shift; cmd_rotate "$@" ;;
  reseed) cmd_reseed ;;
  callers) cmd_callers ;;
  perimeter) cmd_perimeter ;;
  *) sed -n '2,11p' "$0"; exit 2 ;;
esac
