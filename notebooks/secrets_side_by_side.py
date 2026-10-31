# Databricks notebook source
# MAGIC %md
# MAGIC # Legacy secret scopes vs Unity Catalog secrets, side by side
# MAGIC
# MAGIC Every claim below has its own cell, with this kind of explanation above it. Run the notebook once per persona:
# MAGIC
# MAGIC | Persona | How to run | What it has |
# MAGIC | --- | --- | --- |
# MAGIC | Admin (the workspace admin who owns the demo catalog) | job run as that user, `setup=true` the first time | owner of catalog, schema and secrets, so `READ SECRET` through ownership; `MANAGE` on the legacy scope |
# MAGIC | Reference-only (`uc-secrets-demo-reference-only`) | job with `run_as.service_principal_name`, `setup=false` | `USE CATALOG`, `USE SCHEMA`, `CREATE SERVICE` on the schema, `REFERENCE SECRET` on both secrets, `EXECUTE` on `litellm_via_apim`; `READ` on the legacy scope |
# MAGIC
# MAGIC Run it as a serverless job on environment version 6 (`environment_version: "6"`), which is what `databricks.secrets.get()` in session-scoped UDFs and the `SECRETS` clause of Unity Catalog Python UDFs need.
# MAGIC
# MAGIC **Two secrets, two rules.** `uc_secret` (default `dummysecret`, value `hello-from-key-vault`) and the legacy key (value `hello-from-legacy-scope`) are dummies and are printed on purpose.
# MAGIC `real_secret` (default `apimlanekey`) is a real credential: this notebook shows only its length and a SHA-256 prefix, never the value, and never puts it in the exit value.
# MAGIC
# MAGIC Failures that are the expected result (for example `PERMISSION_DENIED` for the reference-only persona) are caught by their specific exception class, printed, and recorded in `results`.
# MAGIC Any other failure propagates and fails the run. The last cell exits with `results` as JSON.

# COMMAND ----------

# MAGIC %md
# MAGIC ## Parameters, persona and helpers
# MAGIC
# MAGIC `setup=true` creates the demo fixtures (service principal, grants, legacy scope, probe schema) and is admin-only. The other widgets name the objects under test.

# COMMAND ----------

import hashlib
import json
import os
import re
import time

import requests
from databricks.sdk import WorkspaceClient
from databricks.sdk.errors import BadRequest, NotFound, PermissionDenied
from py4j.protocol import Py4JJavaError
from pyspark.errors.exceptions.connect import AnalysisException, SparkRuntimeException, UnknownException

dbutils.widgets.text("catalog", "uc_secrets_demo")
dbutils.widgets.text("schema", "secrets")
dbutils.widgets.text("uc_secret", "dummysecret")
dbutils.widgets.text("real_secret", "apimlanekey")
dbutils.widgets.text("legacy_scope", "uc_secrets_demo_legacy")
dbutils.widgets.text("legacy_key", "dummy")
dbutils.widgets.dropdown("setup", "false", ["false", "true"])
dbutils.widgets.text("reference_principal", "uc-secrets-demo-reference-only")
dbutils.widgets.text("provider_service", "litellm_via_apim")
dbutils.widgets.text("probe_schema", "probe")

CATALOG = dbutils.widgets.get("catalog")
SCHEMA = dbutils.widgets.get("schema")
UC_SECRET = dbutils.widgets.get("uc_secret")
REAL_SECRET = dbutils.widgets.get("real_secret")
LEGACY_SCOPE = dbutils.widgets.get("legacy_scope")
LEGACY_KEY = dbutils.widgets.get("legacy_key")
SETUP = dbutils.widgets.get("setup") == "true"
REFERENCE_PRINCIPAL = dbutils.widgets.get("reference_principal")
PROVIDER = f"{CATALOG}.{SCHEMA}.{dbutils.widgets.get('provider_service')}"
PROBE_SCHEMA = f"{CATALOG}.{dbutils.widgets.get('probe_schema')}"
UC_SECRET_FULL = f"{CATALOG}.{SCHEMA}.{UC_SECRET}"
REAL_SECRET_FULL = f"{CATALOG}.{SCHEMA}.{REAL_SECRET}"
REF_PROBE_SERVICE = f"{CATALOG}.{SCHEMA}.ref_probe"
REF_PROBE_UDF = f"{PROBE_SCHEMA}.dummy_secret_udf"
if UC_SECRET == REAL_SECRET:
    raise ValueError("uc_secret is printed and exited in the clear; it must be a dummy, not real_secret")

# Dummy values only. The legacy one is written by the setup cell; the UC one lives in Key Vault.
LEGACY_DUMMY_VALUE = "hello-from-legacy-scope"

# Unity Gateway client timeout. The upstream model behind the APIM lane is often down; when it is, APIM itself
# answers 500 once its backend times out. APIM's default forward-request timeout is 300 s, and the slowest
# upstream failure seen through Unity Gateway was about 240 s (README, 2026-10-28). The extra 60 s is my
# allowance for the Unity Gateway hop, whose own budget is undocumented. Each call prints how much of it it used.
GATEWAY_CLIENT_TIMEOUT_S = 300 + 60

w = WorkspaceClient()
HOST = w.config.host.rstrip("/")
# Plain `requests` calls use the same HTTP timeout the Databricks SDK applies to its own REST calls in this notebook:
# the configured value, else the SDK's built-in default (databricks-sdk 0.122.0, _base_client.py: `http_timeout_seconds or 60`).
SDK_HTTP_TIMEOUT_S = w.config.http_timeout_seconds or 60
ctx = dbutils.notebook.entry_point.getDbutils().notebook().getContext()
NOTEBOOK_TOKEN = ctx.apiToken().get()  # the run's own token; never printed

me = w.current_user.me()
IS_ADMIN = any(g.display == "admins" for g in (me.groups or []))
results = {
    "persona": {"user_name": me.user_name, "display_name": me.display_name, "workspace_admin": IS_ADMIN},
    "runtime": {
        "DATABRICKS_RUNTIME_VERSION": os.environ.get("DATABRICKS_RUNTIME_VERSION"),
        "DATABRICKS_ENV_VERSION": os.environ.get("DATABRICKS_ENV_VERSION"),
        "spark": spark.version,
    },
    "claims": {},
}

PERMISSION_MARKERS = ("PERMISSION_DENIED", "does not have", "READ_SECRET", "READ SECRET", "lacks access", "Forbidden", "not authorized")


def record(claim, outcome, **detail):
    results["claims"][claim] = {"outcome": outcome, **detail}
    print(f"[{claim}] {outcome}" + (f"  {json.dumps(detail)}" if detail else ""))


def expected_denial(claim, exc, markers=PERMISSION_MARKERS):
    """Record a failure that is the expected result. Anything that does not look like a permission failure re-raises."""
    text = str(exc)
    if not any(m in text for m in markers):
        raise exc
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    message = next((ln for ln in lines if any(m in ln for m in markers)), lines[0])
    cls = f"{type(exc).__module__}.{type(exc).__qualname__}"
    print(f"expected failure, caught {cls}:\n  {message}")
    record(claim, "denied", exception=cls, message=message)


def sha256_prefix(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:12]


def call_gateway(provider_full_name, model, quiet_not_found=False):
    """One chat completion through Unity Gateway with the run's own token, classified by the rules in the README."""
    t0 = time.monotonic()
    try:
        r = requests.post(
            f"{HOST}/ai-gateway/openai/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {NOTEBOOK_TOKEN}",
                "Databricks-Model-Provider-Service": provider_full_name,
                "Content-Type": "application/json",
            },
            json={"model": model, "messages": [{"role": "user", "content": "Reply with the single word: ok"}]},
            timeout=GATEWAY_CLIENT_TIMEOUT_S,
        )
    except requests.exceptions.Timeout as e:
        elapsed = time.monotonic() - t0
        print(f"client timeout after {elapsed:.1f} s (100% of the {GATEWAY_CLIENT_TIMEOUT_S} s budget): {e}")
        return {"verdict": "client timeout: no verdict", "elapsed_s": round(elapsed, 1)}
    elapsed = time.monotonic() - t0
    text = r.text
    try:
        body = r.json()
    except requests.exceptions.JSONDecodeError:
        body = {}
    error_code = body.get("error_code") if isinstance(body, dict) else None
    m = re.search(r'upstream_status\\?"?\s*[:=]\s*\\?"?(\d{3})', text)
    upstream = int(m.group(1)) if m else None
    if r.status_code == 404 and error_code == "NOT_FOUND":
        result = {"verdict": "provider service not known to the gateway (404 NOT_FOUND)", "http_status": 404,
                  "error_code": error_code, "message": body.get("message") or "", "elapsed_s": round(elapsed, 1)}
        if not quiet_not_found:
            print(f"HTTP 404 after {elapsed:.1f} s: {result['message']}")
        return result
    if r.status_code == 200:
        verdict = "completion returned: bearer accepted and the model answered"
    elif error_code == "CUSTOMER_UNAUTHORIZED" or upstream == 401:
        verdict = "bearer rejected upstream (401): the gateway resolved a secret and APIM refused it"
    elif error_code == "PERMISSION_DENIED" or r.status_code == 403:
        verdict = "denied by Databricks (no EXECUTE, or the secret could not be resolved)"
    elif upstream is not None and upstream >= 500:
        verdict = f"bearer accepted by APIM; the upstream model failed (upstream_status {upstream})"
    else:
        verdict = "unclassified"
    print(f"HTTP {r.status_code} after {elapsed:.1f} s ({100 * elapsed / GATEWAY_CLIENT_TIMEOUT_S:.0f}% of the {GATEWAY_CLIENT_TIMEOUT_S} s client timeout)")
    print(f"error_code={error_code} upstream_status={upstream}")
    if r.status_code == 200:
        print("answer:", body["choices"][0]["message"]["content"])
    else:
        print("message:", body.get("message") if isinstance(body, dict) and body.get("message") else text)
    print("verdict:", verdict)
    return {"verdict": verdict, "http_status": r.status_code, "error_code": error_code,
            "upstream_status": upstream, "elapsed_s": round(elapsed, 1)}


def call_gateway_when_visible(provider_full_name, model):
    """A provider service created a moment ago can be unknown to the gateway for a while (404 NOT_FOUND, "Nodes do not exist").
    Call again while that is the answer, with no sleep: each 404 round trip takes a fraction of a second and never reaches APIM.
    Gives up after the same budget as one gateway call (GATEWAY_CLIENT_TIMEOUT_S) and reports the lag and the share of it used."""
    t0 = time.monotonic()
    attempts = 0
    while True:
        attempts += 1
        res = call_gateway(provider_full_name, model, quiet_not_found=True)
        waited = time.monotonic() - t0
        if attempts == 1 and res.get("http_status") == 404:
            print(f"first call: HTTP 404 {res['message']}")
        if res.get("http_status") != 404:
            print(f"gateway resolved the new provider on attempt {attempts}; this answer arrived {waited:.1f} s after the first call started "
                  f"({100 * waited / GATEWAY_CLIENT_TIMEOUT_S:.0f}% of the {GATEWAY_CLIENT_TIMEOUT_S} s budget)")
            res.update(attempts=attempts, visible_after_s=round(waited, 1))
            return res
        if waited >= GATEWAY_CLIENT_TIMEOUT_S:
            print(f"still 404 after {attempts} attempts and {waited:.1f} s (100% of the budget): {res['message']}")
            res.update(attempts=attempts, visible_after_s=None)
            return res


print(json.dumps(results["persona"]), json.dumps(results["runtime"]))
print("host:", HOST, "| SDK HTTP timeout:", SDK_HTTP_TIMEOUT_S, "s | gateway client timeout:", GATEWAY_CLIENT_TIMEOUT_S, "s")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Setup (admin only, `setup=true`)
# MAGIC
# MAGIC These cells create the demo fixtures and are idempotent. With `setup=false` they print that they were skipped.
# MAGIC With `setup=true` and a non-admin persona the first one fails on purpose.

# COMMAND ----------

# MAGIC %md
# MAGIC ### Setup 1: the reference-only service principal
# MAGIC
# MAGIC Created through the workspace SCIM API with only the `workspace-access` entitlement, if it does not exist yet.

# COMMAND ----------

from databricks.sdk.service import iam

sp_app_id = None
if SETUP:
    if not IS_ADMIN:
        raise PermissionError(f"setup=true needs a workspace admin; this run is {me.user_name}")
    found = list(w.service_principals.list(filter=f'displayName eq "{REFERENCE_PRINCIPAL}"'))
    if len(found) > 1:
        raise RuntimeError(f"{len(found)} service principals are named {REFERENCE_PRINCIPAL}; expected at most one")
    if found:
        sp = found[0]
        print("exists:", sp.display_name, sp.application_id, sp.id)
    else:
        sp = w.service_principals.create(
            display_name=REFERENCE_PRINCIPAL, active=True,
            entitlements=[iam.ComplexValue(value="workspace-access")],
        )
        print("created:", sp.display_name, sp.application_id, sp.id)
    sp_app_id = sp.application_id
    print("entitlements:", [e.value for e in (w.service_principals.get(sp.id).entitlements or [])])
elif me.display_name == REFERENCE_PRINCIPAL:
    sp_app_id = me.user_name
    print("this run IS the reference-only principal:", sp_app_id)
else:
    found = list(w.service_principals.list(filter=f'displayName eq "{REFERENCE_PRINCIPAL}"'))
    sp_app_id = found[0].application_id if found else None
    print("setup=false: skipped; reference principal application id:", sp_app_id)

# COMMAND ----------

# MAGIC %md
# MAGIC ### Setup 2: Unity Catalog grants for the reference-only principal
# MAGIC
# MAGIC The privilege names are what the permissions API accepts (the same names as the optional grants in `databricks.tf`).
# MAGIC There is no `CREATE MODEL PROVIDER SERVICE` privilege: the API rejects it, as this cell shows. Creating a model provider service needs
# MAGIC `CREATE SERVICE` and `USE SCHEMA` on the schema (Databricks SDK doc for `CreateModelProviderService`), so that is what is granted.
# MAGIC The cell ends by printing the principal's **effective** privileges on each secret, to show it has `REFERENCE SECRET` and nothing that reads.

# COMMAND ----------


def grant(securable_type, full_name, privileges):
    return w.api_client.do(
        "PATCH", f"/api/2.1/unity-catalog/permissions/{securable_type}/{full_name}",
        body={"changes": [{"principal": sp_app_id, "add": privileges}]},
    )


if SETUP:
    try:
        grant("schema", f"{CATALOG}.{SCHEMA}", ["CREATE_MODEL_PROVIDER_SERVICE"])
        record("setup_privilege_create_model_provider_service", "exists and was granted")
    except BadRequest as e:
        print(f"{type(e).__qualname__}: {e}")
        record("setup_privilege_create_model_provider_service", "not a privilege", message=str(e))
    grant("catalog", CATALOG, ["USE_CATALOG"])
    grant("schema", f"{CATALOG}.{SCHEMA}", ["USE_SCHEMA", "CREATE_SERVICE"])
    grant("secret", UC_SECRET_FULL, ["REFERENCE_SECRET"])
    grant("secret", REAL_SECRET_FULL, ["REFERENCE_SECRET"])
    grant("model_provider_service", PROVIDER, ["EXECUTE"])
    for st, name in [("catalog", CATALOG), ("schema", f"{CATALOG}.{SCHEMA}"), ("secret", UC_SECRET_FULL),
                     ("secret", REAL_SECRET_FULL), ("model_provider_service", PROVIDER)]:
        eff = w.api_client.do("GET", f"/api/2.1/unity-catalog/effective-permissions/{st}/{name}",
                              query={"principal": sp_app_id})
        privs = sorted({(p["privilege"], p.get("inherited_from_name") or "direct")
                        for a in eff.get("privilege_assignments", []) for p in a.get("privileges", [])})
        print(f"{st:24} {name:45} effective for {REFERENCE_PRINCIPAL}: {privs}")
else:
    print("setup=false: skipped")

# COMMAND ----------

# MAGIC %md
# MAGIC ### Setup 3: the legacy (Databricks-backed) secret scope
# MAGIC
# MAGIC Creates `legacy_scope` if absent, writes the dummy key, and gives the reference-only principal `READ`, the **lowest** legacy level.
# MAGIC Legacy scopes have no level below `READ`, so this is the closest legacy equivalent of "may use the secret", and the cells below show what it allows.

# COMMAND ----------

from databricks.sdk.service.workspace import AclPermission

if SETUP:
    if LEGACY_SCOPE in {s.name for s in w.secrets.list_scopes()}:
        print("scope exists:", LEGACY_SCOPE)
    else:
        w.secrets.create_scope(scope=LEGACY_SCOPE)
        print("scope created:", LEGACY_SCOPE)
    w.secrets.put_secret(scope=LEGACY_SCOPE, key=LEGACY_KEY, string_value=LEGACY_DUMMY_VALUE)
    w.secrets.put_acl(scope=LEGACY_SCOPE, principal=sp_app_id, permission=AclPermission.READ)
    print("key written:", LEGACY_KEY, "; READ granted to", sp_app_id)
else:
    print("setup=false: skipped")

# COMMAND ----------

# MAGIC %md
# MAGIC ### Setup 4: throwaway probe schema for the UDF experiment
# MAGIC
# MAGIC `probe_schema` holds the Unity Catalog Python UDF attempts in experiment D2. The reference-only principal gets `USE SCHEMA` and `CREATE FUNCTION` here,
# MAGIC so the only thing it lacks is a privilege on the secret. Drop it after both persona runs:
# MAGIC `databricks schemas delete <catalog>.<probe_schema> --force`.

# COMMAND ----------

if SETUP:
    spark.sql(f"CREATE SCHEMA IF NOT EXISTS {PROBE_SCHEMA} COMMENT 'Throwaway: UDF SECRETS-clause probe. Safe to drop.'")
    grant("schema", PROBE_SCHEMA, ["USE_SCHEMA", "CREATE_FUNCTION"])
    print("probe schema ready:", PROBE_SCHEMA)
else:
    print("setup=false: skipped")

# COMMAND ----------

# MAGIC %md
# MAGIC ## A. Legacy secret scope
# MAGIC
# MAGIC ### A1: legacy scopes have exactly three ACL levels
# MAGIC
# MAGIC The SDK's `AclPermission` enum is the API's whole vocabulary. Listing the scope's ACLs needs `MANAGE` on the scope, so the reference-only persona is refused.

# COMMAND ----------

levels = [p.value for p in AclPermission]
print("AclPermission levels:", levels)
record("A1_acl_levels", "listed", levels=levels)
try:
    acls = [(a.principal, a.permission.value) for a in w.secrets.list_acls(scope=LEGACY_SCOPE)]
    for principal, permission in acls:
        print(f"  {permission:7} {principal}")
    record("A1_list_acls", "ok", acls=acls)
except PermissionDenied as e:
    expected_denial("A1_list_acls", e)

# COMMAND ----------

# MAGIC %md
# MAGIC ### A2: there is no reference-only level to grant
# MAGIC
# MAGIC Asks the raw API for an ACL with permission `REFERENCE` on the scope. The admin persona has `MANAGE`, so a refusal can only be about the level itself.
# MAGIC If the API ever accepted it, the cell records that and deletes the ACL again.

# COMMAND ----------

if sp_app_id is None:
    raise RuntimeError(f"no service principal named {REFERENCE_PRINCIPAL}; run once with setup=true")
try:
    w.api_client.do("POST", "/api/2.0/secrets/acls/put",
                    body={"scope": LEGACY_SCOPE, "principal": sp_app_id, "permission": "REFERENCE"})
    record("A2_put_reference_acl", "ACCEPTED (unexpected)")
    w.api_client.do("POST", "/api/2.0/secrets/acls/delete", body={"scope": LEGACY_SCOPE, "principal": sp_app_id})
    w.secrets.put_acl(scope=LEGACY_SCOPE, principal=sp_app_id, permission=AclPermission.READ)
except BadRequest as e:
    print(f"rejected, caught {type(e).__module__}.{type(e).__qualname__}: {e}")
    record("A2_put_reference_acl", "rejected", exception=type(e).__qualname__, message=str(e))
except PermissionDenied as e:
    expected_denial("A2_put_reference_acl", e)

# COMMAND ----------

# MAGIC %md
# MAGIC ### A3: list the keys in the scope

# COMMAND ----------

keys = [s.key for s in dbutils.secrets.list(LEGACY_SCOPE)]
print(keys)
record("A3_dbutils_list", "ok", keys=keys)

# COMMAND ----------

# MAGIC %md
# MAGIC ### A4: read the value with `dbutils.secrets.get(scope=, key=)`
# MAGIC
# MAGIC `READ` on the scope is enough to get the value into a Python variable. There is nothing between "can use" and "can read".

# COMMAND ----------

try:
    v = dbutils.secrets.get(scope=LEGACY_SCOPE, key=LEGACY_KEY)
    record("A4_dbutils_get", "ok", length=len(v))
except Py4JJavaError as e:
    v = None
    expected_denial("A4_dbutils_get", e)

# COMMAND ----------

# MAGIC %md
# MAGIC ### A5: `print(v)` is redacted
# MAGIC
# MAGIC Look at the cell output: it should read `[REDACTED]`.

# COMMAND ----------

if v is None:
    print("skipped: A4 did not return a value")
else:
    print(v)

# COMMAND ----------

# MAGIC %md
# MAGIC ### A6: a slice is not redacted
# MAGIC
# MAGIC Redaction matches the literal value in output. `v[1:]` is a different string.

# COMMAND ----------

if v is None:
    print("skipped: A4 did not return a value")
else:
    print(v[1:])
    record("A6_slice", "printed", value=v[1:])

# COMMAND ----------

# MAGIC %md
# MAGIC ### A7: characters joined by spaces are not redacted

# COMMAND ----------

if v is None:
    print("skipped: A4 did not return a value")
else:
    print(" ".join(v))
    record("A7_join", "printed", value=" ".join(v))

# COMMAND ----------

# MAGIC %md
# MAGIC ### A8: the reversed string is not redacted

# COMMAND ----------

if v is None:
    print("skipped: A4 did not return a value")
else:
    print(v[::-1])
    record("A8_reverse", "printed", value=v[::-1])

# COMMAND ----------

# MAGIC %md
# MAGIC ### A9: a string that merely equals the secret is redacted too
# MAGIC
# MAGIC Built from two literals, without touching `v`. If this prints `[REDACTED]`, redaction is plain string matching on output against values read in this session, not tracking of where data came from.

# COMMAND ----------

print("hello-from-" + "legacy-scope")

# COMMAND ----------

# MAGIC %md
# MAGIC ### A10: `display()` of a DataFrame holding the value
# MAGIC
# MAGIC Does the table output get the same treatment as `print`?

# COMMAND ----------

if v is None:
    print("skipped: A4 did not return a value")
else:
    display(spark.createDataFrame([(v,)], ["v"]))

# COMMAND ----------

# MAGIC %md
# MAGIC ## B. Unity Catalog secret read in the notebook
# MAGIC
# MAGIC ### B1: list the secrets in the schema with `dbutils.secrets.list(catalog=, schema=)`
# MAGIC
# MAGIC `REFERENCE SECRET` makes a secret discoverable; `BROWSE` does not apply to secrets.

# COMMAND ----------

try:
    listed = [s.key for s in dbutils.secrets.list(catalog=CATALOG, schema=SCHEMA)]
    print(listed)
    record("B1_dbutils_list", "ok", keys=listed)
except Py4JJavaError as e:
    expected_denial("B1_dbutils_list", e)

# COMMAND ----------

# MAGIC %md
# MAGIC ### B2: secret metadata over REST (no value)
# MAGIC
# MAGIC `GET /api/2.1/unity-catalog/secrets/{full_name}` without `include_value` returns the object only.

# COMMAND ----------

try:
    meta = w.api_client.do("GET", f"/api/2.1/unity-catalog/secrets/{UC_SECRET_FULL}")
    shown = {k: meta.get(k) for k in ("full_name", "securable_kind", "effective_owner", "external_secret_id")}
    print(json.dumps(shown, indent=1))
    print("value fields present:", sorted(k for k in meta if "value" in k))
    record("B2_rest_metadata", "ok", securable_kind=meta.get("securable_kind"))
except PermissionDenied as e:
    expected_denial("B2_rest_metadata", e)

# COMMAND ----------

# MAGIC %md
# MAGIC ### B3: the REST value is not redacted (read before any `dbutils` call for this secret)
# MAGIC
# MAGIC `GET ...?include_value=true` with the notebook's own API token, then `print(effective_value)`. The HTTP timeout is the one the SDK uses for every other REST call here (`SDK_HTTP_TIMEOUT_S`).
# MAGIC This runs **before** `dbutils.secrets.get` has seen this secret in the session, so the redactor does not know the value yet.

# COMMAND ----------

r = requests.get(f"{HOST}/api/2.1/unity-catalog/secrets/{UC_SECRET_FULL}", params={"include_value": "true"},
                 headers={"Authorization": f"Bearer {NOTEBOOK_TOKEN}"}, timeout=SDK_HTTP_TIMEOUT_S)
if r.status_code == 200:
    rest_value = r.json()["effective_value"]
    print(rest_value)
    record("B3_rest_include_value", "ok", value=rest_value)
elif r.status_code == 403:
    rest_value = None
    err = r.json()
    print(f"HTTP 403 {err.get('error_code')}: {err.get('message')}")
    record("B3_rest_include_value", "denied", http_status=403, error_code=err.get("error_code"), message=err.get("message"))
else:
    r.raise_for_status()
    raise RuntimeError(f"unexpected HTTP {r.status_code}: {r.text}")

# COMMAND ----------

# MAGIC %md
# MAGIC ### B4: read the value with `dbutils.secrets.get(catalog=, schema=, key=)`
# MAGIC
# MAGIC Needs `READ SECRET` on the secret or a parent. `REFERENCE SECRET` alone is expected to fail here.

# COMMAND ----------

try:
    u = dbutils.secrets.get(catalog=CATALOG, schema=SCHEMA, key=UC_SECRET)
    record("B4_dbutils_get", "ok", length=len(u))
except Py4JJavaError as e:
    u = None
    expected_denial("B4_dbutils_get", e)

# COMMAND ----------

# MAGIC %md
# MAGIC ### B5: `print(u)` is redacted

# COMMAND ----------

if u is None:
    print("skipped: B4 did not return a value")
else:
    print(u)

# COMMAND ----------

# MAGIC %md
# MAGIC ### B6: a slice is not redacted

# COMMAND ----------

if u is None:
    print("skipped: B4 did not return a value")
else:
    print(u[1:])
    record("B6_slice", "printed", value=u[1:])

# COMMAND ----------

# MAGIC %md
# MAGIC ### B7: characters joined by spaces are not redacted

# COMMAND ----------

if u is None:
    print("skipped: B4 did not return a value")
else:
    print(" ".join(u))
    record("B7_join", "printed", value=" ".join(u))

# COMMAND ----------

# MAGIC %md
# MAGIC ### B8: the reversed string is not redacted

# COMMAND ----------

if u is None:
    print("skipped: B4 did not return a value")
else:
    print(u[::-1])
    record("B8_reverse", "printed", value=u[::-1])

# COMMAND ----------

# MAGIC %md
# MAGIC ### B9: a string that merely equals the secret is redacted too

# COMMAND ----------

print("hello-from-" + "key-vault")

# COMMAND ----------

# MAGIC %md
# MAGIC ### B10: `display()` of a DataFrame holding the value

# COMMAND ----------

if u is None:
    print("skipped: B4 did not return a value")
else:
    display(spark.createDataFrame([(u,)], ["u"]))

# COMMAND ----------

# MAGIC %md
# MAGIC ### B11: the same REST value printed again, after `dbutils.secrets.get`
# MAGIC
# MAGIC Same string as B3. If B3 was in the clear and this one is `[REDACTED]`, the difference is only that `dbutils` has now registered the literal with the redactor.

# COMMAND ----------

if rest_value is None:
    print("skipped: B3 did not return a value")
else:
    print(rest_value)

# COMMAND ----------

# MAGIC %md
# MAGIC ### B12: the real credential, as length and SHA-256 prefix only
# MAGIC
# MAGIC The value stays in a local variable that is deleted at the end of the cell. Expected for the admin: length 64, prefix `<secret-sha256-prefix-1>`.

# COMMAND ----------

try:
    _real = dbutils.secrets.get(catalog=CATALOG, schema=SCHEMA, key=REAL_SECRET)
    print("length:", len(_real), " sha256 prefix:", sha256_prefix(_real))
    record("B12_real_secret_hash", "ok", length=len(_real), sha256_prefix=sha256_prefix(_real))
    del _real
except Py4JJavaError as e:
    expected_denial("B12_real_secret_hash", e)

# COMMAND ----------

# MAGIC %md
# MAGIC ## C. Session-scoped UDF with `databricks.secrets.get()`
# MAGIC
# MAGIC A PySpark `@udf` registered in this session reads the secret with the **caller's** permissions (serverless environment version 6+).
# MAGIC The UDF returns the dummy value itself, so the cell shows whether a value coming back from Spark is redacted, and the reversed value shows the bypass.
# MAGIC
# MAGIC Without `READ SECRET` the refusal does **not** arrive as `PERMISSION_DENIED`: it surfaces as `[UDF_ERROR.INTERNAL_UNKNOWN] ... due to an unknown error`.
# MAGIC A control run as the reference-only principal (2026-10-29, see `RESULTS.md`) changed only that one privilege: with `READ SECRET` added the same UDF read the secret,
# MAGIC without it the error came back, while a nonexistent secret gave the structured `SECRET_NOT_FOUND`. So this cell accepts `INTERNAL_UNKNOWN` as the expected denial,
# MAGIC but only when B4 has already shown that this principal cannot read the secret; anywhere else it propagates.

# COMMAND ----------

from pyspark.sql.functions import udf

env_version = os.environ.get("DATABRICKS_ENV_VERSION")
if env_version is None or not env_version.isdigit() or int(env_version) < 6:
    print(f"skipped: session-scoped UDF secrets need serverless environment version 6+, this run has {env_version!r}")
    record("C1_session_udf", "skipped", reason=f"environment version {env_version!r}")
else:
    _c, _s, _k = CATALOG, SCHEMA, UC_SECRET

    @udf("string")
    def session_secret_udf(_):
        from databricks.secrets import get
        return get(catalog=_c, schema=_s, key=_k)

    try:
        got = spark.range(1).select(session_secret_udf("id").alias("value")).collect()[0]["value"]
        print("UDF returned:", got)
        print("UDF returned, reversed:", got[::-1])
        record("C1_session_udf", "ok", length=len(got), reversed=got[::-1])
    except SparkRuntimeException as e:
        if u is None and "UDF_ERROR.INTERNAL_UNKNOWN" in str(e):
            expected_denial("C1_session_udf", e, markers=("UDF_ERROR.INTERNAL_UNKNOWN",))
            results["claims"]["C1_session_udf"]["note"] = "missing READ SECRET surfaces as UDF_ERROR.INTERNAL_UNKNOWN (control run in RESULTS.md)"
        else:
            expected_denial("C1_session_udf", e)

# COMMAND ----------

# MAGIC %md
# MAGIC ## D. Can a principal with only `REFERENCE SECRET` use or propagate the secret?
# MAGIC
# MAGIC ### D1: create a model provider service whose `api_key` is a `secret_reference` to the dummy secret
# MAGIC
# MAGIC Which privilege a `secret_reference` needs is not documented. The SDK says the referenced secret "is read at invoke time under the model provider service owner's access",
# MAGIC so whoever creates the service decides where the value is sent. The probe points at the **same** `base_url` as `litellm_via_apim` (read from it),
# MAGIC so nothing leaves the demo lane. If it is created, it is called (the dummy bearer should make APIM answer 401, which proves the gateway resolved
# MAGIC the secret and sent it to the creator's `base_url`) and then deleted. Right after creation the gateway can still answer 404 "Nodes do not exist"
# MAGIC for the new service; the call is repeated while that is the answer, and the cell prints how long the service took to become visible.
# MAGIC
# MAGIC Without `READ SECRET` the API answers 403 "model provider service owner lacks access to the referenced secret", without naming the privilege.
# MAGIC A control run as the reference-only principal with `READ SECRET` temporarily added on the dummy secret (2026-10-29, see `RESULTS.md`) created the service,
# MAGIC so the privilege a `secret_reference` demands is `READ SECRET`; `REFERENCE SECRET` is not enough.

# COMMAND ----------

existing = w.api_client.do("GET", f"/api/2.1/unity-catalog/model-provider-services/{PROVIDER}")
direct = existing["config"]["custom"]["direct"]
base_url = direct["base_url"]
targets = existing["config"]["targets"]
print("existing provider:", existing["name"], "base_url:", base_url, "secret_reference:", direct["api_key"]["secret_reference"]["name"])
probe_body = {
    "comment": "Throwaway probe: secret_reference to a dummy secret. Deleted by the notebook that created it.",
    "config": {
        "provider_type": existing["config"]["provider_type"],
        "targets": targets,
        "custom": {"direct": {"base_url": base_url, "api_key": {"secret_reference": {"name": f"secrets/{UC_SECRET_FULL}"}}}},
    },
}
try:
    created = w.api_client.do(
        "POST", "/api/2.1/unity-catalog/model-provider-services",
        query={"parent": f"schemas/{CATALOG}.{SCHEMA}", "model_provider_service_id": REF_PROBE_SERVICE.split(".")[-1]},
        body=probe_body,
    )
except PermissionDenied as e:
    expected_denial("D1_create_provider_with_secret_reference", e)
else:
    print("created:", created["name"], "owner:", created.get("effective_owner"))
    record("D1_create_provider_with_secret_reference", "created", owner=created.get("effective_owner"))
    try:
        results["claims"]["D1_create_provider_with_secret_reference"]["invoke"] = call_gateway_when_visible(REF_PROBE_SERVICE, targets[0]["model"])
    finally:
        w.api_client.do("DELETE", f"/api/2.1/unity-catalog/model-provider-services/{REF_PROBE_SERVICE}")
        print("deleted:", REF_PROBE_SERVICE)

# COMMAND ----------

# MAGIC %md
# MAGIC ### D2: create a Unity Catalog Python UDF with a `SECRETS` clause on the dummy secret
# MAGIC
# MAGIC Documented: creating a UDF that declares a secret needs `READ SECRET`, and at runtime the UDF uses the **owner's** permissions.
# MAGIC The function returns the dummy value. If it is created, it is called once and dropped.
# MAGIC
# MAGIC The refusal for a principal without `READ SECRET` arrives as `UnknownException` (`[UNAUTHORIZED_ACCESS] ... User does not have READ SECRET`), not as `AnalysisException`,
# MAGIC which is what a missing secret raises; both are caught here, and only a permission message counts as the expected result.

# COMMAND ----------

try:
    spark.sql(f"""
CREATE FUNCTION {REF_PROBE_UDF}() RETURNS STRING LANGUAGE PYTHON
SECRETS ({UC_SECRET_FULL})
ENVIRONMENT (environment_version = '6')
COMMENT 'Throwaway probe. Dropped by the notebook that created it.'
AS $$
from databricks.secrets import get
return get(catalog="{CATALOG}", schema="{SCHEMA}", key="{UC_SECRET}")
$$""")
except (AnalysisException, UnknownException) as e:
    expected_denial("D2_create_udf_with_secrets_clause", e)
else:
    record("D2_create_udf_with_secrets_clause", "created")
    try:
        got = spark.sql(f"SELECT {REF_PROBE_UDF}() AS value").collect()[0]["value"]
        print("UDF returned:", got)
        print("UDF returned, reversed:", got[::-1])
        results["claims"]["D2_create_udf_with_secrets_clause"].update(length=len(got), reversed=got[::-1])
    finally:
        spark.sql(f"DROP FUNCTION {REF_PROBE_UDF}")
        print("dropped:", REF_PROBE_UDF)

# COMMAND ----------

# MAGIC %md
# MAGIC ### D3: use the real secret through Unity Gateway with only `EXECUTE` on the provider
# MAGIC
# MAGIC `litellm_via_apim` references `apimlanekey`; the gateway reads it under the provider owner's access. The run's own token is the only credential sent.
# MAGIC Classification: upstream status 500 after a long wait = bearer accepted, model down; 401 `CUSTOMER_UNAUTHORIZED` = bad bearer; 403 `PERMISSION_DENIED` = no `EXECUTE`.

# COMMAND ----------

results["claims"]["D3_gateway_execute_only"] = call_gateway(PROVIDER, targets[0]["model"])

# COMMAND ----------

# MAGIC %md
# MAGIC ## E. Summary
# MAGIC
# MAGIC One line per claim for this persona. The next cell exits with the same data as JSON. It holds outcomes and dummy values only;
# MAGIC for the real credential it holds length and hash prefix. The dummy values are included on purpose (`exit_probe`), to see whether a notebook exit value is redacted.

# COMMAND ----------

results["exit_probe"] = {"legacy_value": v, "legacy_value_reversed": v[::-1] if v else None,
                         "uc_value": u, "uc_value_reversed": u[::-1] if u else None}
print(f"persona: {results['persona']['user_name']} ({results['persona']['display_name']})")
for claim, data in results["claims"].items():
    print(f"{claim:45} {data.get('outcome', data.get('verdict'))}")

# COMMAND ----------

dbutils.notebook.exit(json.dumps(results))
