# Databricks notebook source
# MAGIC %md
# MAGIC # Topology matrix: from this workspace and this compute, which lanes to the Key Vault-backed secret work?
# MAGIC
# MAGIC Run it once per workspace and compute type (serverless, classic). Each run answers for **where it runs**:
# MAGIC
# MAGIC | Lane | Who talks to Key Vault | What a success proves |
# MAGIC | --- | --- | --- |
# MAGIC | UC read (`dbutils.secrets.get`, REST `include_value`) | the Unity Catalog service, with the service credential's access connector identity | this workspace sees the catalog, and the metastore can fetch the secret |
# MAGIC | Compute DNS | nobody: name resolution on this compute only | whether the vault name resolves to a private endpoint (RFC 1918) or a public address here |
# MAGIC | Compute direct, no token | this compute, anonymously | whether the vault's network layer answers this compute at all |
# MAGIC | Compute direct, connector token | this compute, holding a token for the **same** managed identity Unity Catalog uses | whether Key Vault's trusted-service admission follows the identity (admitted) or the network origin (denied) when the vault is locked |
# MAGIC | Unity Gateway | Unity Gateway, resolving the provider service's `secret_reference` | the gateway behind this workspace's host can use the secret, which the caller never sees |
# MAGIC
# MAGIC **Two secrets, two rules.** `dummy_secret` (default `dummysecret`) is a dummy: its value is read, but only its length and a SHA-256 prefix are printed, so the lanes can be compared.
# MAGIC `real_secret` (default `apimlanekey`) is a real credential: only its length and SHA-256 prefix are ever shown, and the value is never put in the exit value.
# MAGIC
# MAGIC Outcomes that are a valid answer for a lane (catalog missing on another metastore, a denial, no network path, a Key Vault error body) are caught by their
# MAGIC specific exception class or read from the HTTP answer, printed and recorded. Anything else propagates and fails the run. The last cell exits with `results` as JSON.

# COMMAND ----------

# MAGIC %md
# MAGIC ## Parameters and helpers
# MAGIC
# MAGIC `run_label` is free text copied into the results (for example the vault posture the operator set before the run); the notebook cannot read the vault's configuration.
# MAGIC `model` is a model alias the provider service targets, and `vault_name` is read only when the Unity Catalog connection does not exist on this metastore.
# MAGIC Neither has a default: the drivers in `measurements/` pass both from the Terraform state and the workspace.

# COMMAND ----------

import base64
import hashlib
import ipaddress
import json
import os
import re
import socket
import time

import requests
from databricks.sdk import WorkspaceClient
from databricks.sdk.errors import NotFound, PermissionDenied
from databricks.sdk.version import __version__ as SDK_VERSION
from py4j.protocol import Py4JJavaError

dbutils.widgets.text("catalog", "uc_secrets_demo")
dbutils.widgets.text("schema", "secrets")
dbutils.widgets.text("dummy_secret", "dummysecret")
dbutils.widgets.text("real_secret", "apimlanekey")
dbutils.widgets.text("credential", "uc_secrets_demo")
dbutils.widgets.text("connection", "uc_secrets_demo_key_vault")
dbutils.widgets.text("vault_name", "")
dbutils.widgets.text("provider_service", "litellm_via_apim")
dbutils.widgets.text("model", "")
dbutils.widgets.text("run_label", "")

CATALOG = dbutils.widgets.get("catalog")
SCHEMA = dbutils.widgets.get("schema")
DUMMY_SECRET = dbutils.widgets.get("dummy_secret")
REAL_SECRET = dbutils.widgets.get("real_secret")
CREDENTIAL = dbutils.widgets.get("credential")
CONNECTION = dbutils.widgets.get("connection")
VAULT_NAME_WIDGET = dbutils.widgets.get("vault_name")
PROVIDER = f"{CATALOG}.{SCHEMA}.{dbutils.widgets.get('provider_service')}"
MODEL = dbutils.widgets.get("model")
RUN_LABEL = dbutils.widgets.get("run_label")
DUMMY_FULL = f"{CATALOG}.{SCHEMA}.{DUMMY_SECRET}"
if DUMMY_SECRET == REAL_SECRET:
    raise ValueError("dummy_secret is read directly from Key Vault by this compute; it must be a dummy, not real_secret")
if not MODEL:
    raise ValueError("model is empty: pass a model alias the provider service targets (litellm_models in terraform.tfvars)")

# Azure public cloud: the Key Vault data-plane DNS suffix and the OAuth scope of that data plane. The vault name itself comes from
# the Unity Catalog connection (or the widget when the connection does not exist on this metastore).
KEY_VAULT_DNS_SUFFIX = "vault.azure.net"
KEY_VAULT_SCOPE = f"https://{KEY_VAULT_DNS_SUFFIX}/.default"
# Key Vault data-plane API version. 7.4 is a GA version; the two calls used here (list secrets, get secret) have the same shape in every GA version.
KEY_VAULT_API_VERSION = "7.4"
RFC1918 = [ipaddress.ip_network(n) for n in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16")]

# Unity Gateway client timeout. The upstream model behind the APIM lane is often down; when it is, APIM itself
# answers 500 once its backend times out. APIM's default forward-request timeout is 300 s, and the slowest
# upstream failure seen through Unity Gateway was about 240 s (README, 2026-10-28). The extra 60 s is my
# allowance for the Unity Gateway hop, whose own budget is undocumented. Each call prints how much of it it used.
GATEWAY_CLIENT_TIMEOUT_S = 300 + 60

w = WorkspaceClient()
API_HOST = w.config.host.rstrip("/")
# Serverless notebooks report a `client.<env>.<n>` runtime version (`RESULTS.md`: `client.6.5`); classic clusters report the DBR version.
RUNTIME = os.environ.get("DATABRICKS_RUNTIME_VERSION", "")
IS_SERVERLESS = RUNTIME.startswith("client.")
# On a classic cluster the notebook context points the SDK at the regional control-plane URL, not at this workspace's own URL. The REST
# APIs answer there, Unity Gateway does not (HTTP 404 with an empty body, classic run <run-id>). The workspace's own URL is in the
# cluster's Spark conf; on serverless the SDK host already is that URL. Every plain `requests` call below goes to the workspace's own URL.
HOST = API_HOST if IS_SERVERLESS else f"https://{spark.conf.get('spark.databricks.workspaceUrl')}"
# Plain `requests` calls (to Databricks and to Key Vault) use the same HTTP timeout the Databricks SDK applies to its own REST calls in
# this notebook: the configured value, else the SDK's built-in default (`http_timeout_seconds or 60` in _base_client.py of both
# databricks-sdk 0.122.0, serverless environment 6, and 0.67.0, DBR 18.3 LTS).
SDK_HTTP_TIMEOUT_S = w.config.http_timeout_seconds or 60
ctx = dbutils.notebook.entry_point.getDbutils().notebook().getContext()
NOTEBOOK_TOKEN = ctx.apiToken().get()  # the run's own token; never printed

results = {"run_label": RUN_LABEL, "claims": {}}

DENIED = ("PERMISSION_DENIED", "does not have", "lacks access", "Forbidden", "not authorized")
# The Unity Catalog service's wording when Key Vault refuses the service credential (README, sealed posture).
KEY_VAULT_REFUSED = ("cloud provider returned access denied",)
CATALOG_MISSING = ("CATALOG_DOES_NOT_EXIST", f"Catalog '{CATALOG}' does not exist")


def record(claim, outcome, **detail):
    results["claims"][claim] = {"outcome": outcome, **detail}
    print(f"[{claim}] {outcome}" + (f"  {json.dumps(detail)}" if detail else ""))


def expected_failure(claim, exc, outcomes):
    """Record a failure whose text matches one of `outcomes` ({label: markers}, first match wins). Anything else re-raises."""
    text = str(exc)
    for outcome, markers in outcomes.items():
        hit = next((m for m in markers if m in text), None)
        if hit is None:
            continue
        lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
        message = next(ln for ln in lines if hit in ln)
        cls = f"{type(exc).__module__}.{type(exc).__qualname__}"
        print(f"expected failure, caught {cls}:\n  {message}")
        record(claim, outcome, exception=cls, message=message)
        return outcome
    raise exc


def sha256_prefix(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:12]


def is_rfc1918(address):
    ip = ipaddress.ip_address(address)
    # getaddrinfo on a dual-stack host also reports every A record as an IPv4-mapped IPv6 address (::ffff:a.b.c.d);
    # that is the same address, so classify the IPv4 inside it.
    if ip.version == 6 and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    return any(ip in net for net in RFC1918)


def jwt_identity(token):
    """The identity claims of an Entra access token (payload only, no signature check: it is only read to show WHO the token is for)."""
    payload = token.split(".")[1]
    claims = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
    return {k: claims[k] for k in ("oid", "appid", "idtyp", "xms_mirid") if k in claims}


def databricks_error(r):
    """A Databricks REST error answer as a dict. A body that is not a Databricks error is not a lane outcome, so it raises."""
    body = r.json()
    if "error_code" not in body:
        raise RuntimeError(f"HTTP {r.status_code} without a Databricks error body: {r.text}")
    return {"http_status": r.status_code, "error_code": body["error_code"], "message": body.get("message")}


def call_gateway(provider_full_name, model):
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
    message = body.get("message") if isinstance(body, dict) and body.get("message") else text
    m = re.search(r'upstream_status\\?"?\s*[:=]\s*\\?"?(\d{3})', text)
    upstream = int(m.group(1)) if m else None
    if r.status_code == 200:
        verdict = "completion returned: bearer accepted and the model answered"
    elif r.status_code == 404:
        verdict = f"provider service not known to this workspace's gateway (404 {error_code})"
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
        print("message:", message)
    print("verdict:", verdict)
    return {"verdict": verdict, "http_status": r.status_code, "error_code": error_code, "upstream_status": upstream,
            "elapsed_s": round(elapsed, 1), "message": None if r.status_code == 200 else message}


print("run_label:", RUN_LABEL or "(none)")
print("workspace host:", HOST, "| SDK host:", API_HOST, "| databricks-sdk", SDK_VERSION, "| SDK HTTP timeout:", SDK_HTTP_TIMEOUT_S, "s | gateway client timeout:", GATEWAY_CLIENT_TIMEOUT_S, "s")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 1. Where am I
# MAGIC
# MAGIC Workspace, metastore (id, name, region), compute type and the driver's private address, and who runs this.
# MAGIC Serverless or classic is decided from the runtime version (parameters cell); classic clusters also carry cluster usage tags.
# MAGIC The driver address is the source address the kernel would use towards the workspace host (a UDP `connect` sends no packet).

# COMMAND ----------

me = w.current_user.me()
IS_ADMIN = any(g.display == "admins" for g in (me.groups or []))
WORKSPACE_ID = w.get_workspace_id()
record("W1_workspace", f"workspace {WORKSPACE_ID}", host=HOST, sdk_host=API_HOST)

ms = w.api_client.do("GET", "/api/2.1/unity-catalog/metastore_summary")
METASTORE_ID = ms["metastore_id"]
record("W2_metastore", f"{ms.get('name')} ({ms.get('region')})", metastore_id=METASTORE_ID, cloud=ms.get("cloud"))

compute = {"DATABRICKS_RUNTIME_VERSION": RUNTIME, "DATABRICKS_ENV_VERSION": os.environ.get("DATABRICKS_ENV_VERSION"), "spark": spark.version}
if not IS_SERVERLESS:
    # Classic clusters always carry these tags; a classic run without them would be mislabelled, so a missing tag raises.
    compute["cluster_id"] = spark.conf.get("spark.databricks.clusterUsageTags.clusterId")
    compute["node_type"] = spark.conf.get("spark.databricks.clusterUsageTags.clusterNodeType")
    compute["spark_version"] = spark.conf.get("spark.databricks.clusterUsageTags.sparkVersion")
with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
    s.connect((HOST.split("://", 1)[1], 443))
    compute["driver_ip"] = s.getsockname()[0]
compute["driver_ip_rfc1918"] = is_rfc1918(compute["driver_ip"])
record("W3_compute", "serverless" if IS_SERVERLESS else "classic", **compute)

record("W4_caller", me.user_name, workspace_admin=IS_ADMIN)

# COMMAND ----------

# MAGIC %md
# MAGIC ## 2. Catalog visibility, binding and the secret chain
# MAGIC
# MAGIC A catalog lives in one metastore; a workspace on another metastore cannot see it at all. Inside the metastore, `isolation_mode` and the catalog's workspace bindings
# MAGIC decide which workspaces may use it (`OPEN` = every workspace on the metastore). The connection gives the vault name; the credential names the access connector
# MAGIC and managed identity that Unity Catalog uses towards Key Vault. The secret listing's `external_secret_id` must point at the same vault as the connection, or the
# MAGIC compute lanes below would probe a different vault than Unity Catalog reads.

# COMMAND ----------

try:
    cat = w.api_client.do("GET", f"/api/2.1/unity-catalog/catalogs/{CATALOG}")
    record("C1_catalog", f"visible, isolation {cat.get('isolation_mode')}", metastore_id=cat.get("metastore_id"))
except NotFound as e:
    record("C1_catalog", "catalog missing", exception=type(e).__qualname__, message=str(e))

try:
    b = w.api_client.do("GET", f"/api/2.1/unity-catalog/bindings/catalog/{CATALOG}")
    record("C2_catalog_bindings", f"{len(b.get('bindings', []))} workspace binding(s)", bindings=b.get("bindings", []))
except NotFound as e:
    record("C2_catalog_bindings", "catalog missing", exception=type(e).__qualname__, message=str(e))
except PermissionDenied as e:
    record("C2_catalog_bindings", "denied", exception=type(e).__qualname__, message=str(e))

external_ids = {}
try:
    listed = w.api_client.do("GET", "/api/2.1/unity-catalog/secrets", query={"catalog_name": CATALOG, "schema_name": SCHEMA})
    external_ids = {s["full_name"]: s.get("external_secret_id") for s in listed.get("secrets", [])}
    record("C3_secret_listing", f"{len(external_ids)} secret(s)", secrets=sorted(external_ids))
except NotFound as e:
    record("C3_secret_listing", "catalog missing", exception=type(e).__qualname__, message=str(e))
except PermissionDenied as e:
    record("C3_secret_listing", "denied", exception=type(e).__qualname__, message=str(e))

try:
    conn = w.api_client.do("GET", f"/api/2.1/unity-catalog/connections/{CONNECTION}")
    VAULT_NAME = conn["options"]["vault_name"]
    record("C4_connection", f"{conn.get('connection_type')} -> vault {VAULT_NAME}", credential=conn["options"].get("credential"))
except NotFound as e:
    if not VAULT_NAME_WIDGET:
        raise ValueError(f"connection {CONNECTION} does not exist on this metastore and the vault_name widget is empty: "
                         "pass the demo vault's name (terraform output key_vault_name)") from e
    VAULT_NAME = VAULT_NAME_WIDGET
    record("C4_connection", "connection missing; vault name from the widget", vault_name=VAULT_NAME, message=str(e))

try:
    cred = w.api_client.do("GET", f"/api/2.1/unity-catalog/credentials/{CREDENTIAL}")
    mi = cred.get("azure_managed_identity", {})
    CREDENTIAL_MISSING = None
    record("C5_credential", f"{cred.get('purpose')} credential, isolation {cred.get('isolation_mode')}",
           access_connector_id=mi.get("access_connector_id"), managed_identity_id=mi.get("managed_identity_id"))
except NotFound as e:
    CREDENTIAL_MISSING = e
    record("C5_credential", "credential missing", exception=type(e).__qualname__, message=str(e))

VAULT_HOST = f"{VAULT_NAME}.{KEY_VAULT_DNS_SUFFIX}"
dummy_external_id = external_ids.get(DUMMY_FULL)
if dummy_external_id is not None and dummy_external_id.split("/")[2] != VAULT_HOST:
    raise ValueError(f"{DUMMY_FULL} lives in {dummy_external_id.split('/')[2]}, but the compute lanes would probe {VAULT_HOST}")
print("vault under test:", VAULT_HOST)

# COMMAND ----------

# MAGIC %md
# MAGIC ## 3. UC read lane
# MAGIC
# MAGIC The Unity Catalog service fetches the value from Key Vault with the service credential's identity and hands it to this notebook; this compute does not contact the vault.
# MAGIC Three reads: the dummy with `dbutils`, the dummy over REST (`include_value=true`, the run's own token), and the real credential with `dbutils` as length and hash only.

# COMMAND ----------

UC_READ_FAILURES = {"catalog missing": CATALOG_MISSING, "Key Vault refused the service credential": KEY_VAULT_REFUSED, "denied": DENIED}

try:
    _dummy = dbutils.secrets.get(catalog=CATALOG, schema=SCHEMA, key=DUMMY_SECRET)
    UC_DUMMY_HASH = sha256_prefix(_dummy)
    record("L1_uc_read_dbutils", "value ok", length=len(_dummy), sha256_prefix=UC_DUMMY_HASH)
    del _dummy
except Py4JJavaError as e:
    UC_DUMMY_HASH = None
    expected_failure("L1_uc_read_dbutils", e, UC_READ_FAILURES)

r = requests.get(f"{HOST}/api/2.1/unity-catalog/secrets/{DUMMY_FULL}", params={"include_value": "true"},
                 headers={"Authorization": f"Bearer {NOTEBOOK_TOKEN}"}, timeout=SDK_HTTP_TIMEOUT_S)
if r.status_code == 200:
    _rest = r.json()["effective_value"]
    record("L1_uc_read_rest", "value ok", length=len(_rest), sha256_prefix=sha256_prefix(_rest))
    del _rest
else:
    err = databricks_error(r)
    outcome = "catalog missing" if err["error_code"] == "CATALOG_DOES_NOT_EXIST" else f"refused (HTTP {err['http_status']} {err['error_code']})"
    record("L1_uc_read_rest", outcome, **err)

try:
    _real = dbutils.secrets.get(catalog=CATALOG, schema=SCHEMA, key=REAL_SECRET)
    record("L1_uc_read_real_hash", "value ok", length=len(_real), sha256_prefix=sha256_prefix(_real))
    del _real
except Py4JJavaError as e:
    expected_failure("L1_uc_read_real_hash", e, UC_READ_FAILURES)

# COMMAND ----------

# MAGIC %md
# MAGIC ## 4. Compute DNS lane
# MAGIC
# MAGIC What the vault name resolves to **on this compute**. A private endpoint shows up as an RFC 1918 address (and a `privatelink` alias);
# MAGIC a public address means any direct call from here leaves through this compute's internet egress.

# COMMAND ----------

try:
    canonical, aliases, _ = socket.gethostbyname_ex(VAULT_HOST)
    infos = socket.getaddrinfo(VAULT_HOST, 443, proto=socket.IPPROTO_TCP)
    addresses = {a: ("private (RFC 1918)" if is_rfc1918(a) else "public") for a in sorted({i[4][0] for i in infos})}
    kinds = set(addresses.values())
    outcome = "private endpoint address" if kinds == {"private (RFC 1918)"} else "public address" if kinds == {"public"} else "mixed"
    record("L2_compute_dns", outcome, canonical=canonical, aliases=aliases, addresses=addresses)
except socket.gaierror as e:
    record("L2_compute_dns", "no DNS answer", errno=e.errno, message=str(e))

# COMMAND ----------

# MAGIC %md
# MAGIC ## 5. Compute direct, no token
# MAGIC
# MAGIC An anonymous `GET /secrets` from this compute. A `401` with a `WWW-Authenticate` challenge means the vault's front end answered this compute;
# MAGIC no answer at all (connection error or timeout) means there is no network path from here. The challenge's value is not recorded, only its scheme.

# COMMAND ----------

try:
    r = requests.get(f"https://{VAULT_HOST}/secrets", params={"api-version": KEY_VAULT_API_VERSION}, timeout=SDK_HTTP_TIMEOUT_S)
    challenge = r.headers.get("WWW-Authenticate")
    kv_error = r.json().get("error", {}) if r.content else {}
    outcome = f"HTTP {r.status_code}" + (" challenge: the vault answered this compute" if r.status_code == 401 and challenge else "")
    record("L3_compute_unauth", outcome, http_status=r.status_code, www_authenticate_present=challenge is not None,
           www_authenticate_scheme=challenge.split(" ", 1)[0] if challenge else None,
           error_code=kv_error.get("code"), message=kv_error.get("message"))
except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as e:
    record("L3_compute_unauth", "no network path", exception=f"{type(e).__module__}.{type(e).__qualname__}", message=str(e))

# COMMAND ----------

# MAGIC %md
# MAGIC ## 6. Compute direct, with the identity Unity Catalog uses
# MAGIC
# MAGIC `dbutils.credentials.getServiceCredentialsProvider(credential)` hands this compute an Azure token for the service credential's managed identity: the identity the
# MAGIC Unity Catalog service uses for the UC read lane. This cell asks Key Vault for the dummy secret with that token, **from this compute's network position**.
# MAGIC
# MAGIC With the vault locked (public access `Disabled`, `Deny`, bypass `AzureServices`) this decides how Key Vault's trusted-service admission works:
# MAGIC a `200` here means admission follows the token, not where the request comes from; a `403` while the UC read lane still works means it follows the
# MAGIC network origin (the Databricks control plane). To tell "the token" from "any Databricks compute", repeat the call from outside Azure with the same
# MAGIC token (`TOPOLOGY.md`, laptop control).
# MAGIC Only the token's identity claims are printed, never the token; for the value only the SHA-256 prefix, compared with the UC read lane's.

# COMMAND ----------

# For a credential this metastore does not have, the provider's get_token raises a bare `Exception` ("Error while retrieving temporary
# credentials: Credential '<name>' does not exist", ws-eastus run <run-id>), which no handler can tell apart from any other
# failure by class. The typed NotFound from the credential lookup in section 2 is the same answer, so that is what is recorded here,
# and every provider failure on an existing credential propagates.
if CREDENTIAL_MISSING is not None:
    record("L4_compute_connector_token", "credential missing", exception=type(CREDENTIAL_MISSING).__qualname__, message=str(CREDENTIAL_MISSING))
else:
    provider = dbutils.credentials.getServiceCredentialsProvider(CREDENTIAL)
    kv_token = provider.get_token(KEY_VAULT_SCOPE).token
    identity = jwt_identity(kv_token)
    print("token identity:", json.dumps(identity))
    try:
        r = requests.get(f"https://{VAULT_HOST}/secrets/{DUMMY_SECRET}", params={"api-version": KEY_VAULT_API_VERSION},
                         headers={"Authorization": f"Bearer {kv_token}"}, timeout=SDK_HTTP_TIMEOUT_S)
    except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as e:
        record("L4_compute_connector_token", "no network path", token_identity=identity,
               exception=f"{type(e).__module__}.{type(e).__qualname__}", message=str(e))
    else:
        if r.status_code == 200:
            h = sha256_prefix(r.json()["value"])
            record("L4_compute_connector_token", "HTTP 200: value ok", token_identity=identity, sha256_prefix=h,
                   same_as_uc_read=(h == UC_DUMMY_HASH) if UC_DUMMY_HASH else None)
        else:
            kv_error = r.json()["error"]
            record("L4_compute_connector_token", f"HTTP {r.status_code} {kv_error.get('code')}", token_identity=identity,
                   message=kv_error.get("message"), inner_code=(kv_error.get("innererror") or {}).get("code"))
    del kv_token

# COMMAND ----------

# MAGIC %md
# MAGIC ## 7. Unity Gateway lane
# MAGIC
# MAGIC One chat completion through **this workspace's** gateway with the run's own token. The gateway resolves the provider service's `secret_reference`
# MAGIC (`apimlanekey`) through Unity Catalog on every request. Classification: `upstream_status` 500 after a long wait = bearer accepted by APIM, model down;
# MAGIC 401 `CUSTOMER_UNAUTHORIZED` = wrong bearer; 403 `PERMISSION_DENIED` = no `EXECUTE` or the secret could not be resolved; 404 = the provider service is not known here.

# COMMAND ----------

gw = call_gateway(PROVIDER, MODEL)
record("L5_gateway", gw.pop("verdict"), **gw)

# COMMAND ----------

# MAGIC %md
# MAGIC ## 8. Summary
# MAGIC
# MAGIC One line per lane for this workspace and compute. The next cell exits with all claims as JSON (hashes and lengths only, no secret values).

# COMMAND ----------

LANES = [
    ("UC read, dbutils (dummy)", "L1_uc_read_dbutils"),
    ("UC read, REST include_value (dummy)", "L1_uc_read_rest"),
    ("UC read, dbutils (real, hash only)", "L1_uc_read_real_hash"),
    ("compute DNS", "L2_compute_dns"),
    ("compute direct, no token", "L3_compute_unauth"),
    ("compute direct, connector token", "L4_compute_connector_token"),
    ("Unity Gateway", "L5_gateway"),
]
c = results["claims"]
print(f"workspace {WORKSPACE_ID} | {c['W2_metastore']['outcome']} | {c['W3_compute']['outcome']} | driver {compute['driver_ip']} | run_label {RUN_LABEL or '(none)'}")
print(f"vault {VAULT_HOST} | catalog {c['C1_catalog']['outcome']} | credential {c['C5_credential']['outcome']}")
print(f"{'lane':40} outcome")
for label, claim in LANES:
    print(f"{label:40} {c[claim]['outcome']}")

# COMMAND ----------

dbutils.notebook.exit(json.dumps(results))
