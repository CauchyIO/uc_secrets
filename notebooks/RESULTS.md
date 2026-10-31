# Observed results: legacy secret scopes vs Unity Catalog secrets in a notebook

Measured on 2026-10-29 by running [`secrets_side_by_side.py`](secrets_side_by_side.py) as two personas on serverless job compute.
The notebook file that ran is the one in this directory (SHA-256 `a3cb8395195219d3e41067626011c5839005a5623fd0348324fb62b1db808caa`). It was uploaded to
`/Shared/uc_secrets_demo/secrets_side_by_side` and submitted with `databricks jobs submit`, `environment_version: "6"`.
Version 6 was accepted; the runs report `DATABRICKS_ENV_VERSION=6`, `DATABRICKS_RUNTIME_VERSION=client.6.5` and Spark 4.2.0.

Outputs below are copied verbatim from `databricks jobs export-run` (rendered cells) and `databricks jobs get-run-output` (exit value), with one exception:
deployment identifiers are replaced by placeholders: `<workspace-host>`, `<workspace-id>`, `<admin-user>`, `<admin-display-name>`,
`<sp-application-id>`, `<sp-scim-id>`, `<key-vault>`, `<key-vault-uri>`, `<apim-host>`.

## Answers

1. **Do legacy secret scopes have a reference-only permission?** No. The ACL vocabulary is exactly `MANAGE`, `READ`, `WRITE` (A1). An ACL with level
   `REFERENCE` is rejected by the API before any authorization check, for the admin and for a principal without `MANAGE` alike:
   `InvalidParameterValue: Missing required field: acl.permission` (A2). The lowest level, `READ`, hands the principal the value (A4), and the redaction
   bypasses then work (A6 to A8).
2. **How do Unity Catalog secrets appear in a notebook?** `dbutils.secrets.list(catalog=, schema=)` lists them by full name, and
   `dbutils.secrets.get(catalog=, schema=, key=)` returns the value into a Python string (B1, B4). Printing it shows `[REDACTED]`, as does `display()` of a DataFrame
   holding it (B5, B10). The REST API with `include_value=true` returns the plain value in `effective_value`. Printed before `dbutils` has read that secret in the session, it
   appears in the clear; printed after, it shows `[REDACTED]` (B3 vs B11). A session-scoped UDF using `databricks.secrets.get()` (C1) and a Unity Catalog
   Python UDF with a `SECRETS` clause (D2) both return the value into query results for a principal with `READ SECRET`.
3. **Can a principal with only `REFERENCE SECRET` see or propagate the value?** It can **see that the secret exists** (list and metadata: B1, B2). It **cannot get
   the value** by any path tested:
   - `dbutils` (B4) and REST `include_value` (B3) are refused with `PERMISSION_DENIED ... does not have READ SECRET`.
   - The session UDF fails (C1).
   It **cannot propagate the secret into a new object**:
   - A model provider service with a `secret_reference` is refused, `model provider service owner lacks access to the referenced secret` (D1).
   - A `SECRETS`-clause UDF is refused, `User does not have READ SECRET` (D2).

   Control runs that changed only `READ SECRET` show that **both need `READ SECRET`**. What it **can** do, with `EXECUTE` on an existing provider service and no
   privilege beyond `REFERENCE SECRET`, is **use** the secret through Unity Gateway. The gateway resolved `apimlanekey` and APIM accepted it as the bearer; the
   upstream model then failed with 500 (D3). The value never reaches the caller. The `EXECUTE` path does not even need `REFERENCE SECRET`: a control run with that
   grant removed, so the principal had no privilege at all on `apimlanekey`, got the same accepted-bearer result. The gateway reads the secret under the provider
   owner's access.
4. **Does a UC secret read with `dbutils` show the same `[REDACTED]`, and do the same bypasses work?** Yes, identically. `print(u)` → `[REDACTED]`; `u[1:]`,
   `" ".join(u)` and `u[::-1]` print in the clear (B5 to B8, same as A5 to A8). A string that merely *equals* the value, built from two literals, is also
   `[REDACTED]` (A9, B9). So redaction is string matching on output against the values `dbutils` has read **in this session**. It is not tracking where data came from:
   - In the reference-only run, which never read the UC value, the same literal printed in the clear (B9, reference-only column).
   - The notebook exit value is matched the same way. `get-run-output` shows the dummy values as `[REDACTED]` and their reversals in the clear.
   - B3's REST value, which printed in the clear, became `[REDACTED]` in the exit JSON because `dbutils` had read the secret by then.

## Runs

| Run | `run_id` / task `run_id` | Parameters | Result |
| --- | --- | --- | --- |
| **Admin persona** (owner of catalog, schema and secrets; `MANAGE` on the legacy scope) | <run-or-timestamp-id> / <run-or-timestamp-id> | `setup=true` (idempotent pass; the fixtures already existed) | SUCCESS |
| **Reference-only persona** (`uc-secrets-demo-reference-only`, `run_as.service_principal_name`) | <run-or-timestamp-id> / <run-or-timestamp-id> | `setup=false` | SUCCESS |
| First admin pass, created the fixtures (earlier notebook revision; cited for the `created:` lines and in the D1 lag tally) | <run-or-timestamp-id> / <run-or-timestamp-id> | `setup=true` | SUCCESS |
| Earlier admin passes cited for the gateway lag in D1 (earlier notebook revisions) | <run-or-timestamp-id>, <run-or-timestamp-id>, <run-or-timestamp-id> | `setup=true` | SUCCESS |
| Control: session UDF as the reference-only SP, `REFERENCE SECRET` only | <run-or-timestamp-id> / <run-or-timestamp-id> | throwaway notebook | SUCCESS |
| Control: same, with `READ SECRET` temporarily added on `dummysecret` | <run-or-timestamp-id> / <run-or-timestamp-id> | throwaway notebook | SUCCESS |
| Control: provider service + `SECRETS` UDF as the SP, `READ SECRET` temporarily added | <run-or-timestamp-id> / <run-or-timestamp-id> | throwaway notebook | SUCCESS |
| Control: gateway call as the SP with `REFERENCE SECRET` on `apimlanekey` temporarily removed (no privilege on it) | <run-or-timestamp-id> / <run-or-timestamp-id> | throwaway notebook | SUCCESS |

Effective privileges of the reference-only principal, printed by the admin run's setup cell (all direct grants, nothing inherited):
`USE_CATALOG` on the catalog; `USE_SCHEMA`, `CREATE_SERVICE` on `uc_secrets_demo.secrets`; `REFERENCE_SECRET` on `dummysecret` and on `apimlanekey`;
`EXECUTE` on `litellm_via_apim`; `READ` on the legacy scope. During the persona run it also had `USE_SCHEMA` and `CREATE_FUNCTION` on the probe schema,
which has been dropped since.
There is no `CREATE MODEL PROVIDER SERVICE` privilege: granting it fails with `Privilege CREATE MODEL PROVIDER SERVICE is not applicable to this entity
[uc_secrets_demo.secrets:SCHEMA/SCHEMA_STANDARD]`. `CREATE SERVICE` is the privilege the SDK documents for creating a model provider service.

## Results per persona

| Cell | What was tried | Admin | Reference-only |
| --- | --- | --- | --- |
| A1 | legacy ACL levels (`AclPermission`) | `MANAGE`, `READ`, `WRITE` | `MANAGE`, `READ`, `WRITE` |
| A1 | `w.secrets.list_acls(scope)` | ok: SP `READ`, admin `MANAGE` | `PermissionDenied`: no `secret-scopes.ruleSets/get` permission |
| A2 | ACL with permission `REFERENCE` (raw API) | rejected: `InvalidParameterValue: Missing required field: acl.permission` | same rejection |
| A3 | `dbutils.secrets.list(scope)` | `['dummy']` | `['dummy']` |
| A4 | `dbutils.secrets.get(scope=, key=)` | ok, 23 chars | ok, 23 chars (`READ` = the value) |
| A5 | `print(v)` | `[REDACTED]` | `[REDACTED]` |
| A6 | `print(v[1:])` | `ello-from-legacy-scope` | same |
| A7 | `print(" ".join(v))` | `h e l l o - f r o m - l e g a c y - s c o p e` | same |
| A8 | `print(v[::-1])` | `epocs-ycagel-morf-olleh` | same |
| A9 | `print("hello-from-" + "legacy-scope")` | `[REDACTED]` | `[REDACTED]` |
| A10 | `display(spark.createDataFrame([(v,)], ["v"]))` | table cell `[REDACTED]` | table cell `[REDACTED]` |
| B1 | `dbutils.secrets.list(catalog=, schema=)` | both secrets | both secrets |
| B2 | REST `GET .../secrets/{full}` (no value) | ok, `SECRET_EXTERNAL_AZURE_KEY_VAULT`, no value fields | same |
| B3 | REST `?include_value=true`, notebook token, before any `dbutils` read | 200, prints `hello-from-key-vault` in the clear | 403 `PERMISSION_DENIED`: does not have READ SECRET |
| B4 | `dbutils.secrets.get(catalog=, schema=, key=)` | ok, 20 chars | `Py4JJavaError`: `PERMISSION_DENIED` ... does not have READ SECRET |
| B5 | `print(u)` | `[REDACTED]` | no value |
| B6 | `print(u[1:])` | `ello-from-key-vault` | no value |
| B7 | `print(" ".join(u))` | `h e l l o - f r o m - k e y - v a u l t` | no value |
| B8 | `print(u[::-1])` | `tluav-yek-morf-olleh` | no value |
| B9 | `print("hello-from-" + "key-vault")` | `[REDACTED]` | `hello-from-key-vault` in the clear |
| B10 | `display()` of `u` | table cell `[REDACTED]` | no value |
| B11 | the B3 REST value printed again, after B4 | `[REDACTED]` | no value |
| B12 | real credential, length and SHA-256 prefix | 64, `<secret-sha256-prefix-1>` (expected) | `PERMISSION_DENIED`: does not have READ SECRET |
| C1 | session-scoped `@udf` with `databricks.secrets.get()` | value returned; printed `[REDACTED]`, reversal in the clear | `SparkRuntimeException [UDF_ERROR.INTERNAL_UNKNOWN]` (= missing `READ SECRET`, see controls) |
| D1 | create `ref_probe` provider service, `secret_reference` to `dummysecret`, same `base_url` | created (owner admin); calls 1 and 2 → 404 "Nodes do not exist", call 3 → 401 `CUSTOMER_UNAUTHORIZED`, `upstream_status` 401, 1.2 s after the first call; deleted | `PermissionDenied`: model provider service owner lacks access to the referenced secret |
| D2 | create UC Python UDF with `SECRETS (uc_secrets_demo.secrets.dummysecret)` | created; returned value printed `[REDACTED]`, reversal in the clear; dropped | `UnknownException`: `PERMISSION_DENIED` ... User does not have READ SECRET |
| D3 | Unity Gateway call through `litellm_via_apim` with the run's token | 502 `INTERNAL_ERROR`, `upstream_status` 500 after 231.3 s: bearer accepted, model down | 502 `INTERNAL_ERROR`, `upstream_status` 500 after 230.8 s: bearer accepted, model down |
| exit | `dbutils.notebook.exit(json.dumps(results))` | `legacy_value` and `uc_value` `[REDACTED]`; reversals in the clear; B3's value `[REDACTED]` | `legacy_value` `[REDACTED]`, reversal in the clear; `uc_value` null |

## What each result proves

- **A1, A2: legacy scopes cannot express "use but not see".** The API knows three levels, and rejects anything else while parsing, before authorization.
- **A4 to A10: legacy `READ` is full access to the value.** Redaction masks only an exact copy in output, so the value is one string operation away from the screen.
- **B1, B2: `REFERENCE SECRET` makes a UC secret discoverable,** both in `dbutils.secrets.list` and in REST metadata, without exposing a value field.
- **B3 vs B11: the REST value is not redacted at the source.** The same string prints in the clear before `dbutils` reads the secret and `[REDACTED]` afterwards.
  Only the redactor's knowledge changed.
- **B4 to B10: UC secrets read with `dbutils` get exactly the legacy redaction behaviour,** with the same three bypasses.
- **A9, B9 and the exit values: redaction is literal string matching against values read in the session.** It also masks strings that never touched the
  secret, and it does nothing in a session that never read the value (reference-only B9).
- **C1, D2 (admin): code that may read a secret can return it as data.** Redaction then only covers the exact string in notebook output; the reversed value comes back
  in the clear from both UDF kinds.
- **B3, B4, B12, C1 (reference-only): `REFERENCE SECRET` gives no read path.** dbutils, REST and session UDFs are all refused, the last with a misleading error.
- **D1 (both personas): a `secret_reference` in a model provider service requires `READ SECRET`.** The reference-only principal is refused; the admin is allowed. Once
  created, the gateway sends the referenced value to whatever `base_url` the creator configured: the dummy value reached APIM and was refused there with 401.
  `READ SECRET` plus `CREATE SERVICE` is therefore enough to forward a secret to an endpoint of the creator's choosing. Only the same APIM lane was tested.
- **D2 (both personas): a `SECRETS` clause requires `READ SECRET`,** exactly as documented. The refusal for a principal without it arrives as `UnknownException`.
- **D3 (both personas, plus a control): `EXECUTE` on an existing provider service is enough to use the secret,** with no privilege on the secret at all. The control
  removed even `REFERENCE SECRET`. APIM's bearer check passed every time; a wrong bearer gives 401 in about a second, as D1 shows. The 500 after about 231 s is
  the laptop-hosted model, the same failure the README records for direct calls to the lane.

### Read-after-create lag in Unity Gateway (D1)

In five admin runs, the first gateway call made right after creating `ref_probe` got:

- HTTP 401 `CUSTOMER_UNAUTHORIZED` twice (<run-or-timestamp-id> and <run-or-timestamp-id>);
- HTTP 404 `NOT_FOUND` three times (<run-or-timestamp-id>, <run-or-timestamp-id> and the final run <run-or-timestamp-id>), with the message
  `Nodes do not exist. Node IDs (truncated): MODEL_PROVIDER_SERVICE/<id>`.

A provider service can therefore be unknown to the gateway for a moment after `POST` returns. The committed notebook repeats the call while the answer is that 404,
within the 360 s gateway budget, and prints the lag. In the final run, calls 1 and 2 got the 404 and call 3 resolved, 1.2 s after the first call started.

## Raw cell outputs: admin persona (run <run-or-timestamp-id>)

Setup and listing cells:

**Setup 1** (output only)

```text
exists: uc-secrets-demo-reference-only <sp-application-id> <sp-scim-id>
entitlements: ['workspace-access']
```

**Setup 2** (output only)

```text
InvalidParameterValue: Privilege CREATE MODEL PROVIDER SERVICE is not applicable to this entity [uc_secrets_demo.secrets:SCHEMA/SCHEMA_STANDARD]. If this seems unexpected, please check the privilege version of the metastore in use [1.0].
[setup_privilege_create_model_provider_service] not a privilege  {"message": "Privilege CREATE MODEL PROVIDER SERVICE is not applicable to this entity [uc_secrets_demo.secrets:SCHEMA/SCHEMA_STANDARD]. If this seems unexpected, please check the privilege version of the metastore in use [1.0]."}
catalog                  uc_secrets_demo                               effective for uc-secrets-demo-reference-only: [('USE_CATALOG', 'direct')]
schema                   uc_secrets_demo.secrets                       effective for uc-secrets-demo-reference-only: [('CREATE_SERVICE', 'direct'), ('USE_SCHEMA', 'direct')]
secret                   uc_secrets_demo.secrets.dummysecret           effective for uc-secrets-demo-reference-only: [('REFERENCE_SECRET', 'direct')]
secret                   uc_secrets_demo.secrets.apimlanekey           effective for uc-secrets-demo-reference-only: [('REFERENCE_SECRET', 'direct')]
model_provider_service   uc_secrets_demo.secrets.litellm_via_apim      effective for uc-secrets-demo-reference-only: [('EXECUTE', 'direct')]
```

**Setup 3** (output only)

```text
scope exists: uc_secrets_demo_legacy
key written: dummy ; READ granted to <sp-application-id>
```

**Setup 4** (output only)

```text
probe schema ready: uc_secrets_demo.probe
```

**A1** (output only)

```text
AclPermission levels: ['MANAGE', 'READ', 'WRITE']
[A1_acl_levels] listed  {"levels": ["MANAGE", "READ", "WRITE"]}
  READ    <sp-application-id>
  MANAGE  <admin-user>
[A1_list_acls] ok  {"acls": [["<sp-application-id>", "READ"], ["<admin-user>", "MANAGE"]]}
```

**A2** (output only)

```text
rejected, caught databricks.sdk.errors.platform.InvalidParameterValue: Missing required field: acl.permission
[A2_put_reference_acl] rejected  {"exception": "InvalidParameterValue", "message": "Missing required field: acl.permission"}
```

**B1** (output only)

```text
['uc_secrets_demo.secrets.apimlanekey', 'uc_secrets_demo.secrets.dummysecret']
[B1_dbutils_list] ok  {"keys": ["uc_secrets_demo.secrets.apimlanekey", "uc_secrets_demo.secrets.dummysecret"]}
```

**B2** (output only)

```text
{
 "full_name": "uc_secrets_demo.secrets.dummysecret",
 "securable_kind": "SECRET_EXTERNAL_AZURE_KEY_VAULT",
 "effective_owner": "<admin-user>",
 "external_secret_id": "<key-vault-uri>/secrets/dummysecret"
}
value fields present: []
[B2_rest_metadata] ok  {"securable_kind": "SECRET_EXTERNAL_AZURE_KEY_VAULT"}
```


Redaction and propagation cells:

**A5 print(v)**

```python
if v is None:
    print("skipped: A4 did not return a value")
else:
    print(v)
```

```text
[REDACTED]
```

**A6 v[1:]**

```python
if v is None:
    print("skipped: A4 did not return a value")
else:
    print(v[1:])
    record("A6_slice", "printed", value=v[1:])
```

```text
ello-from-legacy-scope
[A6_slice] printed  {"value": "ello-from-legacy-scope"}
```

**A7 join**

```python
if v is None:
    print("skipped: A4 did not return a value")
else:
    print(" ".join(v))
    record("A7_join", "printed", value=" ".join(v))
```

```text
h e l l o - f r o m - l e g a c y - s c o p e
[A7_join] printed  {"value": "h e l l o - f r o m - l e g a c y - s c o p e"}
```

**A8 reverse**

```python
if v is None:
    print("skipped: A4 did not return a value")
else:
    print(v[::-1])
    record("A8_reverse", "printed", value=v[::-1])
```

```text
epocs-ycagel-morf-olleh
[A8_reverse] printed  {"value": "epocs-ycagel-morf-olleh"}
```

**A9 equal literal**

```python
print("hello-from-" + "legacy-scope")
```

```text
[REDACTED]
```

**A10 display**

```python
if v is None:
    print("skipped: A4 did not return a value")
else:
    display(spark.createDataFrame([(v,)], ["v"]))
```

```text
TABLE ["v"]
  ["[REDACTED]"]
```

**B3 REST include_value, before dbutils**

```python
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
```

```text
hello-from-key-vault
[B3_rest_include_value] ok  {"value": "hello-from-key-vault"}
```

**B5 print(u)**

```python
if u is None:
    print("skipped: B4 did not return a value")
else:
    print(u)
```

```text
[REDACTED]
```

**B6 u[1:]**

```python
if u is None:
    print("skipped: B4 did not return a value")
else:
    print(u[1:])
    record("B6_slice", "printed", value=u[1:])
```

```text
ello-from-key-vault
[B6_slice] printed  {"value": "ello-from-key-vault"}
```

**B7 join**

```python
if u is None:
    print("skipped: B4 did not return a value")
else:
    print(" ".join(u))
    record("B7_join", "printed", value=" ".join(u))
```

```text
h e l l o - f r o m - k e y - v a u l t
[B7_join] printed  {"value": "h e l l o - f r o m - k e y - v a u l t"}
```

**B8 reverse**

```python
if u is None:
    print("skipped: B4 did not return a value")
else:
    print(u[::-1])
    record("B8_reverse", "printed", value=u[::-1])
```

```text
tluav-yek-morf-olleh
[B8_reverse] printed  {"value": "tluav-yek-morf-olleh"}
```

**B9 equal literal**

```python
print("hello-from-" + "key-vault")
```

```text
[REDACTED]
```

**B10 display**

```python
if u is None:
    print("skipped: B4 did not return a value")
else:
    display(spark.createDataFrame([(u,)], ["u"]))
```

```text
TABLE ["u"]
  ["[REDACTED]"]
```

**B11 REST value again, after dbutils**

```python
if rest_value is None:
    print("skipped: B3 did not return a value")
else:
    print(rest_value)
```

```text
[REDACTED]
```

**B12 real credential**

```python
try:
    _real = dbutils.secrets.get(catalog=CATALOG, schema=SCHEMA, key=REAL_SECRET)
    print("length:", len(_real), " sha256 prefix:", sha256_prefix(_real))
    record("B12_real_secret_hash", "ok", length=len(_real), sha256_prefix=sha256_prefix(_real))
    del _real
except Py4JJavaError as e:
    expected_denial("B12_real_secret_hash", e)
```

```text
length: 64  sha256 prefix: <secret-sha256-prefix-1>
[B12_real_secret_hash] ok  {"length": 64, "sha256_prefix": "<secret-sha256-prefix-1>"}
```

**C1 session UDF** (output only)

```text
UDF returned: [REDACTED]
UDF returned, reversed: tluav-yek-morf-olleh
[C1_session_udf] ok  {"length": 20, "reversed": "tluav-yek-morf-olleh"}
```

**D1 provider with secret_reference** (output only)

```text
existing provider: model-provider-services/uc_secrets_demo.secrets.litellm_via_apim base_url: <apim-host>/databricks/v1 secret_reference: secrets/uc_secrets_demo.secrets.apimlanekey
created: model-provider-services/uc_secrets_demo.secrets.ref_probe owner: <admin-user>
[D1_create_provider_with_secret_reference] created  {"owner": "<admin-user>"}
first call: HTTP 404 Nodes do not exist. Node IDs (truncated): MODEL_PROVIDER_SERVICE/d4c36e7222de4b3ba20adc4a86609555
HTTP 401 after 0.7 s (0% of the 360 s client timeout)
error_code=CUSTOMER_UNAUTHORIZED upstream_status=401
message: Model Provider Service returned error with status code 401: Unauthorized. Authentication with the model provider failed — verify the credentials configured on this route are valid and not expired.
verdict: bearer rejected upstream (401): the gateway resolved a secret and APIM refused it
gateway resolved the new provider on attempt 3; this answer arrived 1.2 s after the first call started (0% of the 360 s budget)
deleted: uc_secrets_demo.secrets.ref_probe
```

**D2 SECRETS-clause UDF** (output only)

```text
[D2_create_udf_with_secrets_clause] created
UDF returned: [REDACTED]
UDF returned, reversed: tluav-yek-morf-olleh
dropped: uc_secrets_demo.probe.dummy_secret_udf
```

**D3 gateway with EXECUTE** (output only)

```text
HTTP 502 after 231.3 s (64% of the 360 s client timeout)
error_code=INTERNAL_ERROR upstream_status=500
message: Model Provider Service returned error with status code 500: Internal server error. The model provider returned a server error — this is usually transient, so retry with backoff; if it persists, check the provider's status page.
verdict: bearer accepted by APIM; the upstream model failed (upstream_status 500)
```


Exit value (`get-run-output`):

```json
{
 "persona": {
  "user_name": "<admin-user>",
  "display_name": "<admin-display-name>",
  "workspace_admin": true
 },
 "runtime": {
  "DATABRICKS_RUNTIME_VERSION": "client.6.5",
  "DATABRICKS_ENV_VERSION": "6",
  "spark": "4.2.0"
 },
 "claims": {
  "setup_privilege_create_model_provider_service": {
   "outcome": "not a privilege",
   "message": "Privilege CREATE MODEL PROVIDER SERVICE is not applicable to this entity [uc_secrets_demo.secrets:SCHEMA/SCHEMA_STANDARD]. If this seems unexpected, please check the privilege version of the metastore in use [1.0]."
  },
  "A1_acl_levels": {
   "outcome": "listed",
   "levels": [
    "MANAGE",
    "READ",
    "WRITE"
   ]
  },
  "A1_list_acls": {
   "outcome": "ok",
   "acls": [
    [
     "<sp-application-id>",
     "READ"
    ],
    [
     "<admin-user>",
     "MANAGE"
    ]
   ]
  },
  "A2_put_reference_acl": {
   "outcome": "rejected",
   "exception": "InvalidParameterValue",
   "message": "Missing required field: acl.permission"
  },
  "A3_dbutils_list": {
   "outcome": "ok",
   "keys": [
    "dummy"
   ]
  },
  "A4_dbutils_get": {
   "outcome": "ok",
   "length": 23
  },
  "A6_slice": {
   "outcome": "printed",
   "value": "ello-from-legacy-scope"
  },
  "A7_join": {
   "outcome": "printed",
   "value": "h e l l o - f r o m - l e g a c y - s c o p e"
  },
  "A8_reverse": {
   "outcome": "printed",
   "value": "epocs-ycagel-morf-olleh"
  },
  "B1_dbutils_list": {
   "outcome": "ok",
   "keys": [
    "uc_secrets_demo.secrets.apimlanekey",
    "uc_secrets_demo.secrets.dummysecret"
   ]
  },
  "B2_rest_metadata": {
   "outcome": "ok",
   "securable_kind": "SECRET_EXTERNAL_AZURE_KEY_VAULT"
  },
  "B3_rest_include_value": {
   "outcome": "ok",
   "value": "[REDACTED]"
  },
  "B4_dbutils_get": {
   "outcome": "ok",
   "length": 20
  },
  "B6_slice": {
   "outcome": "printed",
   "value": "ello-from-key-vault"
  },
  "B7_join": {
   "outcome": "printed",
   "value": "h e l l o - f r o m - k e y - v a u l t"
  },
  "B8_reverse": {
   "outcome": "printed",
   "value": "tluav-yek-morf-olleh"
  },
  "B12_real_secret_hash": {
   "outcome": "ok",
   "length": 64,
   "sha256_prefix": "<secret-sha256-prefix-1>"
  },
  "C1_session_udf": {
   "outcome": "ok",
   "length": 20,
   "reversed": "tluav-yek-morf-olleh"
  },
  "D1_create_provider_with_secret_reference": {
   "outcome": "created",
   "owner": "<admin-user>",
   "invoke": {
    "verdict": "bearer rejected upstream (401): the gateway resolved a secret and APIM refused it",
    "http_status": 401,
    "error_code": "CUSTOMER_UNAUTHORIZED",
    "upstream_status": 401,
    "elapsed_s": 0.7,
    "attempts": 3,
    "visible_after_s": 1.2
   }
  },
  "D2_create_udf_with_secrets_clause": {
   "outcome": "created",
   "length": 20,
   "reversed": "tluav-yek-morf-olleh"
  },
  "D3_gateway_execute_only": {
   "verdict": "bearer accepted by APIM; the upstream model failed (upstream_status 500)",
   "http_status": 502,
   "error_code": "INTERNAL_ERROR",
   "upstream_status": 500,
   "elapsed_s": 231.3
  }
 },
 "exit_probe": {
  "legacy_value": "[REDACTED]",
  "legacy_value_reversed": "epocs-ycagel-morf-olleh",
  "uc_value": "[REDACTED]",
  "uc_value_reversed": "tluav-yek-morf-olleh"
 }
}
```

## Raw cell outputs: reference-only persona (run <run-or-timestamp-id>)

**A1 list ACLs** (output only)

```text
AclPermission levels: ['MANAGE', 'READ', 'WRITE']
[A1_acl_levels] listed  {"levels": ["MANAGE", "READ", "WRITE"]}
expected failure, caught databricks.sdk.errors.platform.PermissionDenied:
  User <sp-application-id> does not have secret-scopes.ruleSets/get permission on scope uc_secrets_demo_legacy to perform this action. Config: host=<workspace-host>, auth_type=runtime
[A1_list_acls] denied  {"exception": "databricks.sdk.errors.platform.PermissionDenied", "message": "User <sp-application-id> does not have secret-scopes.ruleSets/get permission on scope uc_secrets_demo_legacy to perform this action. Config: host=<workspace-host>, auth_type=runtime"}
```

**A2 REFERENCE ACL** (output only)

```text
rejected, caught databricks.sdk.errors.platform.InvalidParameterValue: Missing required field: acl.permission
[A2_put_reference_acl] rejected  {"exception": "InvalidParameterValue", "message": "Missing required field: acl.permission"}
```

**A5 print(v)** (output only)

```text
[REDACTED]
```

**A6 v[1:]** (output only)

```text
ello-from-legacy-scope
[A6_slice] printed  {"value": "ello-from-legacy-scope"}
```

**A7 join** (output only)

```text
h e l l o - f r o m - l e g a c y - s c o p e
[A7_join] printed  {"value": "h e l l o - f r o m - l e g a c y - s c o p e"}
```

**A8 reverse** (output only)

```text
epocs-ycagel-morf-olleh
[A8_reverse] printed  {"value": "epocs-ycagel-morf-olleh"}
```

**A9 equal literal** (output only)

```text
[REDACTED]
```

**A10 display** (output only)

```text
TABLE ["v"]
  ["[REDACTED]"]
```

**B1 list** (output only)

```text
['uc_secrets_demo.secrets.apimlanekey', 'uc_secrets_demo.secrets.dummysecret']
[B1_dbutils_list] ok  {"keys": ["uc_secrets_demo.secrets.apimlanekey", "uc_secrets_demo.secrets.dummysecret"]}
```

**B3 REST include_value** (output only)

```text
HTTP 403 PERMISSION_DENIED: Principal 'uc-secrets-demo-reference-only' does not have READ SECRET on Secret 'uc_secrets_demo.secrets.dummysecret'.
[B3_rest_include_value] denied  {"http_status": 403, "error_code": "PERMISSION_DENIED", "message": "Principal 'uc-secrets-demo-reference-only' does not have READ SECRET on Secret 'uc_secrets_demo.secrets.dummysecret'."}
```

**B4 dbutils get** (output only)

```text
expected failure, caught py4j.protocol.Py4JJavaError:
  : com.databricks.backend.daemon.driver.repl.ManagedCatalogServiceException: PERMISSION_DENIED: Principal 'uc-secrets-demo-reference-only' does not have READ SECRET on Secret 'uc_secrets_demo.secrets.dummysecret'.
[B4_dbutils_get] denied  {"exception": "py4j.protocol.Py4JJavaError", "message": ": com.databricks.backend.daemon.driver.repl.ManagedCatalogServiceException: PERMISSION_DENIED: Principal 'uc-secrets-demo-reference-only' does not have READ SECRET on Secret 'uc_secrets_demo.secrets.dummysecret'."}
```

**B9 equal literal** (output only)

```text
hello-from-key-vault
```

**B12 real credential** (output only)

```text
expected failure, caught py4j.protocol.Py4JJavaError:
  : com.databricks.backend.daemon.driver.repl.ManagedCatalogServiceException: PERMISSION_DENIED: Principal 'uc-secrets-demo-reference-only' does not have READ SECRET on Secret 'uc_secrets_demo.secrets.apimlanekey'.
[B12_real_secret_hash] denied  {"exception": "py4j.protocol.Py4JJavaError", "message": ": com.databricks.backend.daemon.driver.repl.ManagedCatalogServiceException: PERMISSION_DENIED: Principal 'uc-secrets-demo-reference-only' does not have READ SECRET on Secret 'uc_secrets_demo.secrets.apimlanekey'."}
```

**C1 session UDF** (output only)

```text
expected failure, caught pyspark.errors.exceptions.connect.SparkRuntimeException:
  [UDF_ERROR.INTERNAL_UNKNOWN] Execution of function  failed  due to an unknown error. Please contact Databricks support. SQLSTATE: 39000
[C1_session_udf] denied  {"exception": "pyspark.errors.exceptions.connect.SparkRuntimeException", "message": "[UDF_ERROR.INTERNAL_UNKNOWN] Execution of function  failed  due to an unknown error. Please contact Databricks support. SQLSTATE: 39000"}
```

**D1 provider with secret_reference** (output only)

```text
existing provider: model-provider-services/uc_secrets_demo.secrets.litellm_via_apim base_url: <apim-host>/databricks/v1 secret_reference: secrets/uc_secrets_demo.secrets.apimlanekey
expected failure, caught databricks.sdk.errors.platform.PermissionDenied:
  model provider service owner lacks access to the referenced secret. Config: host=<workspace-host>, auth_type=runtime
[D1_create_provider_with_secret_reference] denied  {"exception": "databricks.sdk.errors.platform.PermissionDenied", "message": "model provider service owner lacks access to the referenced secret. Config: host=<workspace-host>, auth_type=runtime"}
```

**D2 SECRETS-clause UDF** (output only)

```text
expected failure, caught pyspark.errors.exceptions.connect.UnknownException:
  (com.databricks.sql.managedcatalog.acl.UnauthorizedAccessException) PERMISSION_DENIED: Routine or Model 'uc_secrets_demo.probe.dummy_secret_udf' does not have sufficient privilege to execute because the owner of one of the underlying resources failed an authorization check. User does not have READ SECRET on Secret 'uc_secrets_demo.secrets.dummysecret'.
[D2_create_udf_with_secrets_clause] denied  {"exception": "pyspark.errors.exceptions.connect.UnknownException", "message": "(com.databricks.sql.managedcatalog.acl.UnauthorizedAccessException) PERMISSION_DENIED: Routine or Model 'uc_secrets_demo.probe.dummy_secret_udf' does not have sufficient privilege to execute because the owner of one of the underlying resources failed an authorization check. User does not have READ SECRET on Secret 'uc_secrets_demo.secrets.dummysecret'."}
```

**D3 gateway with EXECUTE** (output only)

```text
HTTP 502 after 230.8 s (64% of the 360 s client timeout)
error_code=INTERNAL_ERROR upstream_status=500
message: Model Provider Service returned error with status code 500: Internal server error. The model provider returned a server error — this is usually transient, so retry with backoff; if it persists, check the provider's status page.
verdict: bearer accepted by APIM; the upstream model failed (upstream_status 500)
```


Exit value (`get-run-output`):

```json
{
 "persona": {
  "user_name": "<sp-application-id>",
  "display_name": "uc-secrets-demo-reference-only",
  "workspace_admin": false
 },
 "runtime": {
  "DATABRICKS_RUNTIME_VERSION": "client.6.5",
  "DATABRICKS_ENV_VERSION": "6",
  "spark": "4.2.0"
 },
 "claims": {
  "A1_acl_levels": {
   "outcome": "listed",
   "levels": [
    "MANAGE",
    "READ",
    "WRITE"
   ]
  },
  "A1_list_acls": {
   "outcome": "denied",
   "exception": "databricks.sdk.errors.platform.PermissionDenied",
   "message": "User <sp-application-id> does not have secret-scopes.ruleSets/get permission on scope uc_secrets_demo_legacy to perform this action. Config: host=<workspace-host>, auth_type=runtime"
  },
  "A2_put_reference_acl": {
   "outcome": "rejected",
   "exception": "InvalidParameterValue",
   "message": "Missing required field: acl.permission"
  },
  "A3_dbutils_list": {
   "outcome": "ok",
   "keys": [
    "dummy"
   ]
  },
  "A4_dbutils_get": {
   "outcome": "ok",
   "length": 23
  },
  "A6_slice": {
   "outcome": "printed",
   "value": "ello-from-legacy-scope"
  },
  "A7_join": {
   "outcome": "printed",
   "value": "h e l l o - f r o m - l e g a c y - s c o p e"
  },
  "A8_reverse": {
   "outcome": "printed",
   "value": "epocs-ycagel-morf-olleh"
  },
  "B1_dbutils_list": {
   "outcome": "ok",
   "keys": [
    "uc_secrets_demo.secrets.apimlanekey",
    "uc_secrets_demo.secrets.dummysecret"
   ]
  },
  "B2_rest_metadata": {
   "outcome": "ok",
   "securable_kind": "SECRET_EXTERNAL_AZURE_KEY_VAULT"
  },
  "B3_rest_include_value": {
   "outcome": "denied",
   "http_status": 403,
   "error_code": "PERMISSION_DENIED",
   "message": "Principal 'uc-secrets-demo-reference-only' does not have READ SECRET on Secret 'uc_secrets_demo.secrets.dummysecret'."
  },
  "B4_dbutils_get": {
   "outcome": "denied",
   "exception": "py4j.protocol.Py4JJavaError",
   "message": ": com.databricks.backend.daemon.driver.repl.ManagedCatalogServiceException: PERMISSION_DENIED: Principal 'uc-secrets-demo-reference-only' does not have READ SECRET on Secret 'uc_secrets_demo.secrets.dummysecret'."
  },
  "B12_real_secret_hash": {
   "outcome": "denied",
   "exception": "py4j.protocol.Py4JJavaError",
   "message": ": com.databricks.backend.daemon.driver.repl.ManagedCatalogServiceException: PERMISSION_DENIED: Principal 'uc-secrets-demo-reference-only' does not have READ SECRET on Secret 'uc_secrets_demo.secrets.apimlanekey'."
  },
  "C1_session_udf": {
   "outcome": "denied",
   "exception": "pyspark.errors.exceptions.connect.SparkRuntimeException",
   "message": "[UDF_ERROR.INTERNAL_UNKNOWN] Execution of function  failed  due to an unknown error. Please contact Databricks support. SQLSTATE: 39000",
   "note": "missing READ SECRET surfaces as UDF_ERROR.INTERNAL_UNKNOWN (control run in RESULTS.md)"
  },
  "D1_create_provider_with_secret_reference": {
   "outcome": "denied",
   "exception": "databricks.sdk.errors.platform.PermissionDenied",
   "message": "model provider service owner lacks access to the referenced secret. Config: host=<workspace-host>, auth_type=runtime"
  },
  "D2_create_udf_with_secrets_clause": {
   "outcome": "denied",
   "exception": "pyspark.errors.exceptions.connect.UnknownException",
   "message": "(com.databricks.sql.managedcatalog.acl.UnauthorizedAccessException) PERMISSION_DENIED: Routine or Model 'uc_secrets_demo.probe.dummy_secret_udf' does not have sufficient privilege to execute because the owner of one of the underlying resources failed an authorization check. User does not have READ SECRET on Secret 'uc_secrets_demo.secrets.dummysecret'."
  },
  "D3_gateway_execute_only": {
   "verdict": "bearer accepted by APIM; the upstream model failed (upstream_status 500)",
   "http_status": 502,
   "error_code": "INTERNAL_ERROR",
   "upstream_status": 500,
   "elapsed_s": 230.8
  }
 },
 "exit_probe": {
  "legacy_value": "[REDACTED]",
  "legacy_value_reversed": "epocs-ycagel-morf-olleh",
  "uc_value": null,
  "uc_value_reversed": null
 }
}
```

## Control runs: what the opaque refusals mean

The reference-only principal's refusals in C1 and D1 do not name the missing privilege. Two throwaway notebooks were run as the same service principal with
nothing changed except `READ SECRET` on `dummysecret`. It was granted just before phase 2 and revoked right after. Effective privileges were printed before and
after: `['REFERENCE_SECRET']` → `['READ_SECRET', 'REFERENCE_SECRET']` → `['REFERENCE_SECRET']`.

Session UDF control (core of the notebook):

```python
@udf("int")
def dummy_len(_):
    from databricks.secrets import get
    return len(get(catalog="uc_secrets_demo", schema="secrets", key="dummysecret"))
# plus a UDF with no secret, and one that reads a nonexistent secret
```

```text
phase 1, REFERENCE SECRET only (<run-or-timestamp-id>):
 "no_secret": "ok: plain-udf-ok",
 "dummysecret_len": "SparkRuntimeException: [UDF_ERROR.INTERNAL_UNKNOWN] Execution of function  failed  due to an unknown error. Please contact Databricks support. SQLSTATE: 39000",
 "missing_secret_len": "SparkRuntimeException: [UDF_USER_CODE_ERROR.SECRET_NOT_FOUND] Execution of function  failed. The requested secret was not found. [UC_SECRET_NOT_FOUND] Secret `uc_secrets_demo`.`secrets`.`doesnotexistprobe` does not exist. Use 'SHOW SECRETS' to list available secrets. SQLSTATE: 42704"

phase 2, READ SECRET added (<run-or-timestamp-id>):
 "no_secret": "ok: plain-udf-ok",
 "dummysecret_len": "ok: 20",
 "missing_secret_len": "SparkRuntimeException: [UDF_USER_CODE_ERROR.SECRET_NOT_FOUND] ... (same as phase 1)"
```

So `UDF_ERROR.INTERNAL_UNKNOWN` in C1 is the missing `READ SECRET`, reported as an unknown internal error. That is worth raising with Databricks.
The notebook accepts it as the expected denial only when B4 has already shown that the principal cannot read the secret.

Propagation control, phase 2 with `READ SECRET` added (<run-or-timestamp-id>). Same `ref_probe` body and `SECRETS` UDF as D1 and D2:

```text
principal: <sp-application-id>
D1 create provider: created, owner <sp-application-id>
deleted ref_probe
D2 create udf: created; returns length 20
dropped dummy_secret_udf
```

The `REFERENCE SECRET`-only side of this comparison is the reference-only persona run itself (D1 and D2 above, same request bodies). So the privilege a
model provider service's `secret_reference` demands is `READ SECRET`; that is not in the documentation. Its refusal message, "model provider service owner
lacks access to the referenced secret", matches the SDK note that a `secret_reference` "is read at invoke time under the model provider service owner's access".

EXECUTE-only gateway control (<run-or-timestamp-id>). `REFERENCE_SECRET` on `apimlanekey` was removed from the SP just before the run and restored right after;
effective privileges were `['REFERENCE_SECRET']` → `[]` → `['REFERENCE_SECRET']`. One `POST /ai-gateway/openai/v1/chat/completions` with
`Databricks-Model-Provider-Service: uc_secrets_demo.secrets.litellm_via_apim` and the run's own token:

```text
{
 "http_status": 502,
 "error_code": "INTERNAL_ERROR",
 "upstream_status": 500,
 "elapsed_s": 231.5,
 "message": "Model Provider Service returned error with status code 500: Internal server error. The model provider returned a server error \u2014 this is usually transient, so retry with backoff; if it persists, check the provider's status page."
}
```

## Not tested, and why

- **Spark conf secret references (`{{secrets/<scope>/<key>}}`)**, which the docs say redaction also covers. They need a classic cluster; only serverless compute was
  used, as asked.
- **Azure Key Vault-backed legacy scopes.** Only a Databricks-backed scope was created. The ACL model (A1, A2) is the same API; the scope backend was not varied.
- **Legacy `WRITE`/`MANAGE` and UC `WRITE SECRET`/`CREATE SECRET`.** Out of scope; the personas only cover reading and referencing.
- **A provider service pointed at a different `base_url`.** Deliberately not done. D1 shows the gateway sends the referenced value to the creator's `base_url`, so
  pointing elsewhere would only change the destination. That is an inference, not a measurement.
- **Other consumers of `REFERENCE SECRET`**, such as Unity Catalog connections. The docs say a connection needs `READ SECRET`; not tested. No consumer was found for
  which `REFERENCE SECRET` alone was enough to use a secret in a new object. Its observed effect is discoverability (B1, B2).
- **A reference-only principal executing a `SECRETS` UDF owned by someone with `READ SECRET`.** Per the docs that runs with the owner's rights, like D3's provider path.
  It was not set up, because it needs an `EXECUTE` grant on such a function.
- **A completed chat answer through the gateway.** The upstream model behind the APIM lane failed with 500 after about 231 s in every run, so D3 proves the bearer
  was accepted, not a full completion.
- **Classic compute (DBR 17.3+ / 19) and SQL warehouses**, driver logs, the Spark UI, and audit rows in `system.access.audit`. Not inspected.

## Demo fixtures left in place, and how to remove them

| Fixture | Created by | Remove with |
| --- | --- | --- |
| Service principal `uc-secrets-demo-reference-only` (`workspace-access` only), SCIM id `<sp-scim-id>`, application id `<sp-application-id>` | setup cell 1 | `databricks service-principals delete <sp-scim-id> -p <profile>`; if the workspace is identity-federated, check the account console as well |
| `roles/servicePrincipal.user` for the admin on that SP. The creator only gets `servicePrincipal.manager`, and `run_as` needs the user role | `PUT /api/2.0/preview/accounts/access-control/rule-sets` (CLI, once) | removed with the SP, or `PUT` the rule set back to the manager rule alone |
| UC grants to the SP: `USE_CATALOG` on `uc_secrets_demo`; `USE_SCHEMA`, `CREATE_SERVICE` on `uc_secrets_demo.secrets`; `REFERENCE_SECRET` on both secrets; `EXECUTE` on `litellm_via_apim` | setup cell 2 | `databricks api patch /api/2.1/unity-catalog/permissions/<type>/<name> -p <profile> --json '{"changes":[{"principal":"<sp-application-id>","remove":[<privileges>]}]}'` per securable (`catalog`, `schema`, `secret`, `model_provider_service`). `terraform destroy` drops the catalog and all of them |
| Legacy scope `uc_secrets_demo_legacy`, key `dummy` = `hello-from-legacy-scope`, ACLs admin `MANAGE`, SP `READ` | setup cell 3 | `databricks secrets delete-scope uc_secrets_demo_legacy -p <profile>` |
| Workspace notebook `/Shared/uc_secrets_demo/secrets_side_by_side` | `databricks workspace import` | `databricks workspace delete --recursive /Shared/uc_secrets_demo -p <profile>` |
| The job runs listed under **Runs** (evidence) | `databricks jobs submit` | `databricks jobs delete-run <run_id> -p <profile>`; runs also expire after 60 days |

None of these are in the Terraform state, so `terraform plan` is unaffected. The UC grants live inside the Terraform-managed catalog and disappear with it.

Already removed after the runs:
- the probe schema `uc_secrets_demo.probe`, together with the SP's `USE_SCHEMA`/`CREATE_FUNCTION` there;
- every `ref_probe` provider service and `dummy_secret_udf` function (each run deletes what it creates);
- the throwaway discovery and control notebooks, the superseded runs, and a sandbox schema used once to test privilege names.

## Re-running

```bash
databricks workspace import /Shared/uc_secrets_demo/secrets_side_by_side --file notebooks/secrets_side_by_side.py \
  --format SOURCE --language PYTHON --overwrite -p <profile>
databricks jobs submit --json @admin.json -p <profile>   # first: creates the fixtures and the probe schema
databricks jobs submit --json @sp.json -p <profile>      # then: the reference-only persona
databricks schemas delete uc_secrets_demo.probe --force -p <profile>   # afterwards
```

`admin.json` (for `sp.json`, add `"run_as": {"service_principal_name": "<sp-application-id>"}` and set `setup` to `"false"`):

```json
{
  "run_name": "uc_secrets_demo side-by-side: admin persona (setup=true)",
  "tasks": [{
    "task_key": "side_by_side",
    "notebook_task": {"notebook_path": "/Shared/uc_secrets_demo/secrets_side_by_side", "source": "WORKSPACE",
                      "base_parameters": {"setup": "true"}},
    "environment_key": "default"
  }],
  "environments": [{"environment_key": "default", "spec": {"environment_version": "6"}}]
}
```

Run the two personas one after the other, not in parallel: both create and delete the same `ref_probe` and `dummy_secret_udf` names.
The reference-only run needs the probe schema, so run the admin pass first.
