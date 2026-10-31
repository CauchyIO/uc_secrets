# Databricks notebook source
# MAGIC %md
# MAGIC # `ACCESS` on the service credential: what it gives a principal that owns nothing
# MAGIC
# MAGIC The topology matrix (`TOPOLOGY.md`) showed that Key Vault admits the service credential's token from any network. Every one of those runs was
# MAGIC the owner of the credential. This notebook runs **as a principal that has no `READ SECRET` on any secret** (the reference-only service
# MAGIC principal from `RESULTS.md`) and measures what `ACCESS` on the credential alone gives it: once without that privilege, once with it.
# MAGIC
# MAGIC | Claim | Lane | Who decides |
# MAGIC | --- | --- | --- |
# MAGIC | A1 | UC read of the dummy secret, REST `include_value` | Unity Catalog, `READ SECRET` |
# MAGIC | A2 | credential metadata, `GET /credentials/{name}` | Unity Catalog |
# MAGIC | A3 | `POST /temporary-service-credentials`: an Entra token for the credential's managed identity | Unity Catalog, `ACCESS` |
# MAGIC | A4 | with that token, straight to Key Vault: list secrets, read the dummy, read the real secret | Key Vault, the identity's RBAC role; Unity Catalog is not involved |
# MAGIC | A5 | `dbutils.credentials.getServiceCredentialsProvider`: the same token from the compute's side | Unity Catalog, `ACCESS` |
# MAGIC
# MAGIC **Two secrets, two rules.** The dummy's value is read, but only its length and SHA-256 prefix are printed. The real secret is never printed and never
# MAGIC put in the exit value: only its length and SHA-256 prefix. Tokens are never printed, only their identity claims.
# MAGIC
# MAGIC Denials that are the expected answer are read from the HTTP answer or caught by their specific exception class, printed and recorded.
# MAGIC Anything else propagates and fails the run. The last cell exits with `results` as JSON.

# COMMAND ----------

# MAGIC %md
# MAGIC ## Parameters and helpers
# MAGIC
# MAGIC `vault_name` is a widget because a principal without privileges on the Unity Catalog connection cannot read the vault's name from it. It has
# MAGIC no default: `measurements/credential_access_probe.sh` passes the name from the Terraform state.
# MAGIC `run_label` is free text copied into the results (which grant was in place when the run was submitted).

# COMMAND ----------

import base64
import hashlib
import json

import requests
from databricks.sdk import WorkspaceClient

dbutils.widgets.text("catalog", "uc_secrets_demo")
dbutils.widgets.text("schema", "secrets")
dbutils.widgets.text("dummy_secret", "dummysecret")
dbutils.widgets.text("real_secret", "apimlanekey")
dbutils.widgets.text("credential", "uc_secrets_demo")
dbutils.widgets.text("vault_name", "")
dbutils.widgets.text("run_label", "")

CATALOG = dbutils.widgets.get("catalog")
SCHEMA = dbutils.widgets.get("schema")
DUMMY_SECRET = dbutils.widgets.get("dummy_secret")
REAL_SECRET = dbutils.widgets.get("real_secret")
CREDENTIAL = dbutils.widgets.get("credential")
VAULT_NAME = dbutils.widgets.get("vault_name")
if not VAULT_NAME:
    raise ValueError("vault_name is empty: pass the demo vault's name (terraform output key_vault_name)")
VAULT_HOST = f"{VAULT_NAME}.vault.azure.net"
RUN_LABEL = dbutils.widgets.get("run_label")
DUMMY_FULL = f"{CATALOG}.{SCHEMA}.{DUMMY_SECRET}"
if DUMMY_SECRET == REAL_SECRET:
    raise ValueError("dummy_secret is read directly from Key Vault by this compute; it must be a dummy, not real_secret")

# Azure public cloud: the OAuth scope of the Key Vault data plane, and a GA data-plane API version (list and get secrets have the
# same shape in every GA version).
KEY_VAULT_SCOPE = "https://vault.azure.net/.default"
KEY_VAULT_API_VERSION = "7.4"

w = WorkspaceClient()
HOST = w.config.host.rstrip("/")
# Plain `requests` calls use the HTTP timeout the Databricks SDK applies to its own REST calls: the configured value, else the SDK's
# built-in default (`http_timeout_seconds or 60` in _base_client.py of databricks-sdk 0.122.0, serverless environment 6).
HTTP_TIMEOUT_S = w.config.http_timeout_seconds or 60
NOTEBOOK_TOKEN = dbutils.notebook.entry_point.getDbutils().notebook().getContext().apiToken().get()  # the run's own token; never printed

results = {"run_label": RUN_LABEL, "claims": {}}


def record(claim, outcome, **detail):
    results["claims"][claim] = {"outcome": outcome, **detail}
    print(f"[{claim}] {outcome}" + (f"  {json.dumps(detail)}" if detail else ""))


def sha256_prefix(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:12]


def jwt_identity(token):
    """The identity claims of an Entra access token (payload only, no signature check: it is only read to show WHO the token is for)."""
    payload = token.split(".")[1]
    claims = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
    return {k: claims[k] for k in ("oid", "appid", "idtyp", "xms_mirid") if k in claims}


def databricks_call(method, path, **kwargs):
    """One Databricks REST call with the run's own token. Returns (status, body); a non-200 answer without a Databricks error body is not a
    lane outcome, so it raises."""
    r = requests.request(method, f"{HOST}{path}", headers={"Authorization": f"Bearer {NOTEBOOK_TOKEN}"}, timeout=HTTP_TIMEOUT_S, **kwargs)
    body = r.json()
    if r.status_code != 200 and "error_code" not in body:
        raise RuntimeError(f"HTTP {r.status_code} without a Databricks error body: {r.text}")
    return r.status_code, body


def vault_get(token, path, params=None):
    """One Key Vault data-plane call. Returns (status, body); Key Vault always answers JSON, with an `error` object on failure."""
    r = requests.get(f"https://{VAULT_HOST}{path}", params={"api-version": KEY_VAULT_API_VERSION, **(params or {})},
                     headers={"Authorization": f"Bearer {token}"}, timeout=HTTP_TIMEOUT_S)
    return r.status_code, r.json()


def vault_error(body):
    err = body["error"]
    return {"error_code": err.get("code"), "inner_code": (err.get("innererror") or {}).get("code"), "message": err.get("message")}


# COMMAND ----------

# MAGIC %md
# MAGIC ## Who is running, and what the credential grants that principal

# COMMAND ----------

me = w.current_user.me()
status, body = databricks_call("GET", f"/api/2.1/unity-catalog/effective-permissions/credential/{CREDENTIAL}", params={"principal": me.user_name})
if status == 200:
    privileges = sorted({p["privilege"] for a in body.get("privilege_assignments", []) for p in a.get("privileges", [])})
    record("W_caller", me.user_name, workspace_id=w.get_workspace_id(), effective_privileges_on_credential=privileges)
else:
    record("W_caller", me.user_name, workspace_id=w.get_workspace_id(), effective_permissions_lookup=f"HTTP {status} {body['error_code']}",
           message=body.get("message"))

# COMMAND ----------

# MAGIC %md
# MAGIC ## A1. The governed lane: Unity Catalog read of the dummy secret
# MAGIC
# MAGIC Expected for this principal in both runs: refused, `READ SECRET` is missing. This is the lane the secret's own privileges govern.

# COMMAND ----------

status, body = databricks_call("GET", f"/api/2.1/unity-catalog/secrets/{DUMMY_FULL}", params={"include_value": "true"})
if status == 200:
    value = body.get("effective_value") or body.get("value")
    record("A1_uc_read_rest", "ok, value present", length=len(value), sha256_prefix=sha256_prefix(value))
else:
    record("A1_uc_read_rest", f"refused (HTTP {status} {body['error_code']})", message=body.get("message"))

# COMMAND ----------

# MAGIC %md
# MAGIC ## A2. Credential metadata

# COMMAND ----------

status, body = databricks_call("GET", f"/api/2.1/unity-catalog/credentials/{CREDENTIAL}")
if status == 200:
    record("A2_credential_metadata", "visible", owner=body.get("owner"), isolation_mode=body.get("isolation_mode"), purpose=body.get("purpose"))
else:
    record("A2_credential_metadata", f"refused (HTTP {status} {body['error_code']})", message=body.get("message"))

# COMMAND ----------

# MAGIC %md
# MAGIC ## A3. A token for the credential's identity, through the REST API
# MAGIC
# MAGIC `POST /api/2.1/unity-catalog/temporary-service-credentials` is the call a laptop makes (`TOPOLOGY.md`, laptop controls). `ACCESS` on the
# MAGIC credential is the documented requirement.

# COMMAND ----------

status, body = databricks_call("POST", "/api/2.1/unity-catalog/temporary-service-credentials",
                               json={"credential_name": CREDENTIAL, "azure_options": {"resources": [KEY_VAULT_SCOPE]}})
if status == 200:
    rest_token = body["azure_aad"]["aad_token"]
    record("A3_rest_temporary_credential", "token issued", token_identity=jwt_identity(rest_token), expiration_time=body.get("expiration_time"))
else:
    rest_token = None
    record("A3_rest_temporary_credential", f"refused (HTTP {status} {body['error_code']})", message=body.get("message"))

# COMMAND ----------

# MAGIC %md
# MAGIC ## A4. With that token, straight to Key Vault
# MAGIC
# MAGIC Three data-plane calls with the token from A3: list the vault's secrets, read the dummy, read the real secret. Unity Catalog and its
# MAGIC `READ SECRET` privilege play no part here; Key Vault checks the identity's RBAC role (Key Vault Secrets User) and its own network rules.

# COMMAND ----------

if rest_token is None:
    record("A4_vault_list", "not attempted: no token")
    record("A4_vault_dummy", "not attempted: no token")
    record("A4_vault_real", "not attempted: no token")
else:
    status, body = vault_get(rest_token, "/secrets")
    if status == 200:
        names = sorted(item["id"].rsplit("/", 1)[-1] for item in body.get("value", []))
        record("A4_vault_list", f"HTTP 200: {len(names)} secret(s)", names=names)
    else:
        record("A4_vault_list", f"HTTP {status}", **vault_error(body))
    status, body = vault_get(rest_token, f"/secrets/{DUMMY_SECRET}")
    if status == 200:
        record("A4_vault_dummy", "HTTP 200: value ok", length=len(body["value"]), sha256_prefix=sha256_prefix(body["value"]))
    else:
        record("A4_vault_dummy", f"HTTP {status}", **vault_error(body))
    status, body = vault_get(rest_token, f"/secrets/{REAL_SECRET}")
    if status == 200:
        real_value = body.pop("value")
        record("A4_vault_real", "HTTP 200: value ok (never printed)", length=len(real_value), sha256_prefix=sha256_prefix(real_value))
        del real_value
    else:
        record("A4_vault_real", f"HTTP {status}", **vault_error(body))
    del rest_token

# COMMAND ----------

# MAGIC %md
# MAGIC ## A5. The same token from the compute's side
# MAGIC
# MAGIC `dbutils.credentials.getServiceCredentialsProvider(credential)` is how a notebook obtains the token (the topology matrix's lane 6).
# MAGIC Its provider raises a bare `Exception` with the Unity Catalog message in it (verified for a missing credential, ws-eastus run
# MAGIC <run-id>), so the class cannot be narrowed: the message is checked for a permission denial, which is recorded, and any other
# MAGIC failure is re-raised with its full text.

# COMMAND ----------

DENIED = ("PERMISSION_DENIED", "does not have", "not authorized")
try:
    provider = dbutils.credentials.getServiceCredentialsProvider(CREDENTIAL)
    compute_token = provider.get_token(KEY_VAULT_SCOPE).token
except Exception as e:  # noqa: BLE001  (bare Exception from the provider; see the cell's markdown)
    text = str(e)
    hit = next((m for m in DENIED if m in text), None)
    if hit is None:
        raise
    line = next(ln.strip() for ln in text.splitlines() if hit in ln)
    print(f"expected failure, caught {type(e).__module__}.{type(e).__qualname__}:\n  {line}")
    record("A5_compute_provider", "refused", exception=f"{type(e).__module__}.{type(e).__qualname__}", message=line)
else:
    identity = jwt_identity(compute_token)
    status, body = vault_get(compute_token, f"/secrets/{DUMMY_SECRET}")
    if status == 200:
        h = sha256_prefix(body["value"])
        record("A5_compute_provider", "token issued, HTTP 200: value ok", token_identity=identity, length=len(body["value"]), sha256_prefix=h,
               same_as_rest_lane=(h == results["claims"]["A4_vault_dummy"].get("sha256_prefix")))
    else:
        record("A5_compute_provider", f"token issued, HTTP {status}", token_identity=identity, **vault_error(body))
    del compute_token

# COMMAND ----------

# MAGIC %md
# MAGIC ## Summary

# COMMAND ----------

print(f"caller {results['claims']['W_caller']['outcome']} | run_label {RUN_LABEL or '(none)'}")
print(f"{'claim':30} outcome")
for claim, detail in results["claims"].items():
    print(f"{claim:30} {detail['outcome']}")

# COMMAND ----------

dbutils.notebook.exit(json.dumps(results))
