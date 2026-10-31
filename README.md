# Unity Catalog External Secrets & Unity Gateway (Terraform Reference)

End-to-end Terraform reference that binds an Azure Key Vault to a Unity Catalog schema (`STORAGE_TYPE_EXTERNAL`) and wires a Unity Gateway custom model provider (`secret_reference`) to an Azure API Management lane and LiteLLM. Callers invoke the model endpoint with `EXECUTE` on the gateway service and hold zero privileges on the underlying secret.

```text
Inference path:
  Workspace caller (EXECUTE only)
    -> Unity Gateway (databricks_ai_gateway_model_provider_service)
    -> Azure API Management static-key lane (/databricks/v1)
    -> Upstream LiteLLM container

Server-side secret resolution (on every request):
  Unity Gateway (secret_reference: secrets/<catalog>.<schema>.apimlanekey)
    -> Unity Catalog (STORAGE_TYPE_EXTERNAL schema binding)
    -> AZURE_KEY_VAULT connection + SERVICE credential
    -> Azure Databricks Access Connector + user-assigned managed identity
    -> Azure Key Vault (Azure RBAC: Key Vault Secrets User)
```

The APIM lane bearer secret is fetched ephemerally at plan/apply time via `ephemeral "azapi_resource_action"` (`namedValues/listValue`) and written into Azure Key Vault using Terraform 1.11+ write-only `value_wo` on `azurerm_key_vault_secret`. The production lane secret and optional `dummysecret` fixture never store plaintext in `terraform.tfstate` or plan files.

---

## Repository Layout

| Path | Purpose |
| :--- | :--- |
| [`azure.tf`](azure.tf) | Resource group, RBAC-enabled Azure Key Vault, user-assigned managed identity, Databricks Access Connector, `ephemeral "azapi_resource_action"` fetching the APIM named value, and write-only `azurerm_key_vault_secret` resources (`value_wo`). |
| [`databricks.tf`](databricks.tf) | Declarative Unity Catalog `SERVICE` credential, `AZURE_KEY_VAULT` connection, catalog and schema, Unity Gateway model provider service, and least-privilege caller grants. |
| [`uc_secret_storage_bridge.tf`](uc_secret_storage_bridge.tf) | The one always-wired Beta bridge: schema binding and metadata discovery, separate from native resources. |
| [`test_fixture.tf`](test_fixture.tf) & [`moved.tf`](moved.tf) | Optional dummy secret and state migrations for optional fixture/deployer-role creation. Existing `.demo` resource addresses and default names remain stable for compatibility. |
| [`modules/uc_schema_secret_storage/`](modules/uc_schema_secret_storage) | Reusable local module isolating the Beta Unity Catalog schema-binding REST API (`secret_storage` on `/api/2.1/unity-catalog/schemas`), with drift detection (`GET ?include_secret_storage=true`) and read-verified secret discovery (`data "external"`). |
| [`diagnostics.tf`](diagnostics.tf) | Optional Log Analytics workspace and `AuditEvent` diagnostic setting (`enable_diagnostics = true`) to inspect Databricks caller IPs and identity object IDs hitting Key Vault. |
| [`ncc.tf`](ncc.tf) | Optional NCC with a private endpoint rule from the serverless compute plane to the vault, bound to the workspace (`enable_ncc_private_endpoint = true`); the state-compatible approval adapter is isolated in [`ncc_private_endpoint_approval.tf`](ncc_private_endpoint_approval.tf). |
| [`nsp.tf`](nsp.tf) | Optional Network Security Perimeter around the vault (`enable_network_security_perimeter = true`): perimeter, profile, the vault's association (Learning mode unless `nsp_access_mode` says otherwise), an optional inbound rule for the connector's subscription, and the perimeter's access log into the diagnostics workspace. |
| [`variables.tf`](variables.tf) & [`terraform.tfvars.example`](terraform.tfvars.example) | Input variables (validated where the value has a known shape: GUIDs, region, workspace id, names) and template for tenant, subscription, workspace, APIM lane, storage root, model aliases, the optional names and the three optional add-ons. |
| [`versions.tf`](versions.tf), [`outputs.tf`](outputs.tf) & [`.terraform.lock.hcl`](.terraform.lock.hcl) | Terraform and provider version constraints with the workspace and Azure provider configurations; the core outputs the scripts read by name; the committed provider lock file. |
| [`scripts/`](scripts) | Operator helpers, run from this directory after `terraform apply`: [`smoke_test.sh`](scripts/smoke_test.sh) inspects the UC secret, queries Unity Gateway, rotates and reseeds Key Vault and queries the vault's caller log and the perimeter's access log; [`kv_network_probe.py`](scripts/kv_network_probe.py) tests Unity Catalog and Unity Gateway against five Key Vault firewall postures; [`ncc_private_endpoint.py`](scripts/ncc_private_endpoint.py) lists or approves the NCC endpoint on the vault. |
| [`notebooks/`](notebooks) | The notebooks uploaded to the workspace and the measured write-ups: [`secrets_side_by_side.py`](notebooks/secrets_side_by_side.py) with [`RESULTS.md`](notebooks/RESULTS.md) (legacy secret scopes against Unity Catalog secrets, `READ SECRET` vs. `REFERENCE SECRET` vs. `EXECUTE`); [`topology_matrix.py`](notebooks/topology_matrix.py) and [`credential_access_probe.py`](notebooks/credential_access_probe.py) with [`TOPOLOGY.md`](notebooks/TOPOLOGY.md) (which lanes to the secret work from each workspace, compute type, vault posture and perimeter state, and what `ACCESS` on the credential grants). Run by hand, `topology_matrix.py` needs its `model` widget (and `vault_name` on a metastore without the Unity Catalog connection) and `credential_access_probe.py` its `vault_name` widget; neither has a default, and the drivers in `measurements/` pass both. |
| [`measurements/`](measurements) | The drivers behind each phase of `TOPOLOGY.md`, every name read from the Terraform state and the model alias from the provider service ([`lib.sh`](measurements/lib.sh)): [`sealed_with_ncc.sh`](measurements/sealed_with_ncc.sh) (phases 3 and 4), [`nsp_perimeter.sh`](measurements/nsp_perimeter.sh) (phase 7: the perimeter in Learning, Enforced and Enforced with a rule), [`sql_lane.py`](measurements/sql_lane.py) (phase 6: the SQL warehouse), [`credential_access_probe.sh`](measurements/credential_access_probe.sh) (rows A1 and A2) and [`row_section.py`](measurements/row_section.py) (turns a run export into a raw-output section with the write-up's placeholders, through [`extract_cells.py`](measurements/extract_cells.py)). |

---

## Prerequisites

1. **Terraform `>= 1.11`:** Required for `ephemeral` resources (`azapi_resource_action`) and write-only secret arguments (`value_wo` on `azurerm_key_vault_secret`).
2. **Workspace Preview:** Turn on **External secrets for Unity Catalog** under **Settings > Previews** (`uc_external_secrets`).
3. **Azure authentication:** Locally, log in to the workspace's Entra tenant (`az login --tenant <tenant-id>`) and select the deployment subscription (`az account set --subscription <subscription-id>`). CI can use AzureRM/AzAPI `ARM_*` service-principal or OIDC settings. The caller needs APIM `listValue`, resource deployment rights, and role-assignment rights when `create_deployer_role_assignment` is true. If it is false, grant Key Vault Secrets Officer separately. The optional NCC approval helper also requires an authenticated Azure CLI session, including in CI.
4. **Databricks CLI:** Install the current CLI and authenticate for the workspace. Set `databricks_profile = "workspace"` for a local `~/.databrickscfg` profile, or leave it `null` for [unified authentication](https://learn.microsoft.com/en-us/azure/databricks/dev-tools/auth/unified-auth), including `DATABRICKS_HOST` plus the appropriate service-principal/OIDC settings. The provider and bridge must use the same workspace and principal. The bridge omits `-p` for null/empty profiles; operator scripts do the same. NCC uses a separate account provider with the configured tenant; `databricks_account_auth_type` can pin `azure-cli` locally or use environment authentication in CI.
5. **Python 3.10+:** `python3` on `PATH`. The schema-binding module runs its helper through it (`data "external"` reads during plan, provisioners during apply), and so does the NCC add-on's approval step.

---

## Quickstart

Copy the example variable file and fill in your tenant, subscription, workspace, APIM lane, model aliases (`litellm_models` has no default: list the aliases your lane's LiteLLM key may call), and catalog `storage_root`:

```bash
cp terraform.tfvars.example terraform.tfvars
```

`terraform.tfvars` is gitignored and loaded automatically by Terraform:

```bash
terraform init
terraform plan -out deployment.tfplan
terraform apply deployment.tfplan
```

The secure defaults are `public_network_access_enabled = false`, `network_acls = { default_action = "Deny", bypass = "AzureServices" }`, purge protection on, 90-day soft deletion, no purge on destroy, and catalog/schema `force_destroy = false`. The optional dummy secret is off. `tags` applies to every taggable Azure resource managed here. See [`terraform.tfvars.example`](terraform.tfvars.example) for all controls.

**Provision from a runner that can reach the vault's data plane.** The trusted-service exception used by Unity Catalog does not grant network access to an ordinary developer laptop or CI identity. Private endpoint routing and DNS for the runner must be provisioned separately; the optional Databricks NCC serves serverless compute and is not a private path for Terraform. IP/subnet firewall rules only help a runner when public network access is enabled. Keep the locked production posture as the target configuration.

**Upgrading an existing deployment:** explicitly preserve its network, retention, purge-protection, catalog/schema force-delete settings and catalog comment in your private tfvars before planning this change. Keep `create_dummy_secret = true` and `create_deployer_role_assignment = true` for objects already managed by this configuration. [`moved.tf`](moved.tf) maps both singleton addresses to `[0]`; the first plan records these address moves without replacing either object. Disabling either switch removes its managed object; it does not merely stop managing it. Purge protection is irreversible once enabled, and changing retention replaces the vault. Adopt the secure settings in a separate reviewed deployment change. The provider now protects resource groups containing unmanaged resources and retains deleted vaults by default.

To grant a non-admin caller access to the Unity Gateway endpoint without granting access to the secret, set `caller_principal = "<group-or-user>"` in `terraform.tfvars` (a one-off `-var` would be missing from the next plain `terraform plan`, which would then remove the grants). Terraform grants `USE_CATALOG`, `USE_SCHEMA`, and `EXECUTE` on the model provider service, and nothing on `apimlanekey`.

---

## Live Rotation & Audit Verification

**Run rotation and network/perimeter measurements only on a dedicated test deployment.** They write secrets, temporarily deny traffic, change permissions, or create billable compute. Enable `create_dummy_secret = true` for the notebooks and measurement drivers. The NCC measurement uses account CLI authentication (`DATABRICKS_ACCOUNT_PROFILE`, or `DATABRICKS_ACCOUNT_AUTH_TYPE`/standard auth environment; local fallback `azure-cli`). The topology drivers require an explicit open test baseline and refuse the locked production default before installing restore traps.

Use [`scripts/smoke_test.sh`](scripts/smoke_test.sh) to verify that Unity Gateway resolves the active Key Vault version at request time without caching:

```bash
./scripts/smoke_test.sh secret              # 1. Inspect UC secret metadata and the live Key Vault value (length and SHA-256 prefix only)
./scripts/smoke_test.sh rotate bogus-key    # 2. Write a bogus v2 in Key Vault (zero Databricks changes)
./scripts/smoke_test.sh query <model-alias> # 3. Call Unity Gateway; APIM rejects with HTTP 401 in ~2 s
./scripts/smoke_test.sh reseed              # 4. Restore the real APIM secret into Key Vault as v3
```

Every secret resolution is logged in Unity Catalog's audit table:

```sql
SELECT event_time, user_identity.email, action_name, request_params
FROM system.access.audit
WHERE service_name = 'unityCatalog'
  AND action_name LIKE '%Secret%'
ORDER BY event_time DESC;
```

---

## The Beta Schema-Binding Bridge (`modules/uc_schema_secret_storage`)

The `SERVICE` credential (`databricks_credential`) and `AZURE_KEY_VAULT` connection (`databricks_connection`) are native resources in the Databricks Terraform provider (`v1.140.0`), but binding a Unity Catalog schema to that connection is not yet exposed on `databricks_schema`.

[`uc_secret_storage_bridge.tf`](uc_secret_storage_bridge.tf) is the visible root entry point for [`modules/uc_schema_secret_storage/`](modules/uc_schema_secret_storage). The module encapsulates binding and discovery so [`databricks.tf`](databricks.tf) contains native provider resources:

| Operation | HTTP Method & Path | Payload |
| :--- | :--- | :--- |
| **Inspect binding state (drift check)** | `GET /api/2.1/unity-catalog/schemas/<catalog>.<schema>?include_secret_storage=true` | None (returns `STORAGE_TYPE_EXTERNAL` or `STORAGE_TYPE_MANAGED`) |
| **Bind schema to Key Vault** | `PATCH /api/2.1/unity-catalog/schemas/<catalog>.<schema>` | `{"secret_storage": {"connection_name": "<connection>", "storage_type": "STORAGE_TYPE_EXTERNAL"}}` |
| **Unbind schema (on destroy)** | `PATCH /api/2.1/unity-catalog/schemas/<catalog>.<schema>?update_mask=secret_storage` | `{"secret_storage": {}}` |

During `terraform plan`, `data.external.binding_state` checks whether `storage_type == "STORAGE_TYPE_EXTERNAL"` and `connection_name` matches the configured connection, triggering a re-bind if the schema drifted outside Terraform. While the schema does not exist yet (first deploy, or a schema replacement) the module's `schema_id` input is unknown, so Terraform makes that check during apply instead of failing the plan on a missing schema. Next, `data.external.secret` lists the bound schema (triggering Unity Catalog's lazy secret import from Key Vault) and returns each secret's `full_name`, `securable_kind`, and `external_secret_id` as module outputs.

A schema or catalog deleted out of band returns an empty binding on 404/`RESOURCE_DOES_NOT_EXIST`/`NOT_FOUND` (including the CLI’s plain missing-schema/catalog message), allowing Terraform to recreate it; unbinding an already absent schema succeeds. Authentication, server and other errors remain failures. Discovery retries transient missing metadata, RBAC propagation and service errors up to five attempts with 1/2/4/8-second backoff. Each CLI subprocess has a 45-second timeout. Paths/query values are URL-encoded, provisioners pass inputs through environment variables, and diagnostics never include response bodies or secret values.

**Removing the bridge later:** first verify native `databricks_schema.secret_storage` support in the pinned provider. Configure the equivalent native binding, replace metadata-output references, and retire the module with a Terraform `removed` block using `lifecycle { destroy = false }`. Review the state migration before applying. Simply deleting the module invokes its destroy provisioner and unbinds the live schema. Keep native and bridge writes from managing the same field at the same time.


---

## Private Key Vaults, Serverless Compute, and NCCs

When resolving an external secret, **nothing in the compute plane connects to Azure Key Vault.** The Unity Catalog control plane fetches the secret using the connection's service credential (`azurerm_databricks_access_connector` + managed identity) and returns it to the caller (or resolves `secret_reference` inside Unity Gateway). Network Connectivity Configuration (NCC) private endpoint rules apply only when serverless compute opens its own Azure SDK `SecretClient` directly to a private vault; [`notebooks/TOPOLOGY.md`](notebooks/TOPOLOGY.md) rows 13 and 14 measure exactly that split.

We tested five Key Vault firewall postures sequentially from a verified open baseline using [`scripts/kv_network_probe.py`](scripts/kv_network_probe.py):

| Vault posture (`publicNetworkAccess`, `defaultAction`, `bypass`) | Direct `az keyvault secret show` | Unity Catalog read | Unity Gateway |
| :--- | :--- | :--- | :--- |
| **Open baseline** (`Enabled`, no rules) | Succeeds | Succeeds | Reaches APIM |
| **`trusted`** (`Enabled`, `Deny`, `AzureServices`) | Denied (`Client address is not authorized...`) | **726 / 726 reads over 300 s** | Reaches APIM |
| **`closed`** (`Disabled`, no rules, default `AzureServices`) | Denied (`Public network access is disabled...`) | **727 / 727 reads over 300 s** | Reaches APIM |
| **`locked`** (`Disabled`, `Deny`, `AzureServices`) | Denied (`Public network access is disabled...`) | **1,028 / 1,028 reads over 420 s** | Reaches APIM |
| **`sealed`** (`Disabled`, `Deny`, `None`) | Denied (`bypass is not set to 'AzureServices'`) | **Fails on 1st read** (`access denied`) | HTTP 403 `PERMISSION_DENIED` |

### Key Takeaways

- **`bypass = "AzureServices"` is sufficient for locked-down vaults.** Azure Key Vault treats the Databricks Access Connector's managed identity as a trusted Microsoft service. You can disable public network access (`public_network_access_enabled = false`) with `default_action = "Deny"` and `bypass = "AzureServices"` with no NCC, private endpoint, or IP allowlist.
- **Unity Gateway does not cache resolved secrets.** With the vault `sealed` (`bypass = "None"`) and zero direct Unity Catalog reads in between, gateway calls at **5, 30, 60, 120, 240, and 420 s** all failed with HTTP 403 `PERMISSION_DENIED`. Reopening the vault restored resolution on the next request.

### The NCC Private Endpoint Add-on (`ncc.tf`)

`enable_ncc_private_endpoint = true` (with `databricks_account_id`) creates an NCC, a private endpoint rule to the vault (`group_id = "vault"`), binds the NCC to the workspace and approves the endpoint through the adapter in `ncc_private_endpoint_approval.tf`. Apply it with `DATABRICKS_TF_ENABLED_PF_RESOURCES=databricks_mws_ncc_private_endpoint_rule` so the rule waits for `PENDING` before the approval runs. The measured result is in [`notebooks/TOPOLOGY.md`](notebooks/TOPOLOGY.md) (phase 3): with the vault sealed (`bypass = "None"`) and the endpoint `ESTABLISHED`, the Unity Catalog read, Unity Gateway and classic compute were refused, exactly as without the endpoint. A re-check 22 minutes after approval showed serverless still resolving the vault to its public front end; 9 h 45 min after approval it resolved the vault to the private endpoint address, and a rerun of the sealed posture at that point (phase 4, rows 13 and 14) showed serverless reading the vault through the endpoint with the connector token while the Unity Catalog read and Unity Gateway from the same compute stayed refused, as did classic compute and the laptop. The private endpoint exists for serverless compute's own connections to the vault, never for Unity Catalog's secret fetch, so it is not a way to make a sealed vault work with external secrets.

Azure exposes [Key Vault private endpoint connection approval through ARM/AzAPI](https://learn.microsoft.com/en-us/azure/templates/microsoft.keyvault/vaults/privateendpointconnections). Declarative approval requires the vault's generated connection child ID; the NCC rule exposes only the endpoint name. The optional adapter matches that exact endpoint against ARM connections and retries delayed discovery. Its existing `terraform_data.approve_private_endpoint` address, input shape and rule-ID replacement trigger are preserved, so this upgrade does not replay approval or touch the live NCC endpoint. Already-approved connections are a no-op; ambiguous matches and rejected/disconnected connections fail. No destroy hook revokes approval. The live connection child name currently equals the endpoint name; the helper checks the relationship instead of assuming it for every rule. The pinned AzAPI 2.13.0 `azapi_update_resource` has no import implementation, so adopting it would plan a new approval operation. A future migration therefore needs an explicit ownership/state migration and verification of discovery for new rules; changing resource types is not a drop-in `moved` operation.

Lifecycle facts before enabling it:

- The provider cannot unbind an NCC from a workspace: destroying `databricks_mws_ncc_binding` only logs a warning, and Databricks only lets an account admin replace a workspace's NCC, not remove it. Before `terraform destroy`, rebind the workspace to another (empty) NCC through the account API, or the NCC delete fails.
- Private endpoint rules bill per hour from creation until deletion, whatever their state; Databricks may keep an `ESTABLISHED` endpoint on the vault for up to a day after the rule is deleted.
- A new binding and new rules take about ten minutes to reach serverless compute, and up to 24 hours to apply fully (measured here: not yet after 22 minutes, in place after 9 h 45 min). Running serverless resources must be restarted to use it.

### The Network Security Perimeter Add-on (`nsp.tf`)

`enable_network_security_perimeter = true` puts the vault inside an Azure Network Security Perimeter: a perimeter, a profile and the vault's association, in Learning mode unless `nsp_access_mode` says otherwise, plus the perimeter's access log into the diagnostics workspace when `enable_diagnostics` is on. The perimeter itself is free. Learning mode (the portal calls it Transition) leaves the vault's own firewall in charge and only logs what Enforced would deny. Enforced denies every public request that no inbound rule admits, trusted services included, and leaves private endpoint traffic alone. `nsp_admit_connector_subscription = true` adds an inbound rule for the subscription that holds the access connector's identity. [`measurements/nsp_perimeter.sh`](measurements/nsp_perimeter.sh) flips the association through Learning, Enforced and Enforced with that rule with the Azure CLI, measures each state on serverless and classic compute and from the laptop with the vault open throughout, and ends with the association back in Learning and a clean `terraform plan`. The measured result is in [`notebooks/TOPOLOGY.md`](notebooks/TOPOLOGY.md) (phase 7, rows 15 to 20):

- **Learning changed nothing** (rows 15 and 16): every lane as with no perimeter, and the perimeter's access log already attributes each request to its source: Unity Catalog's fetch arrives from a Databricks control-plane address and is attributed to the access connector resource, the laptop's calls to its public address, serverless's own call through the NCC endpoint as private traffic, the classic cluster's call as service-endpoint traffic.
- **Enforced with no rule blocks Unity Catalog's fetch while the vault's own firewall stays open** (rows 17 and 18): the Unity Catalog read and Unity Gateway were refused from serverless, classic and the laptop within a second of the switch (`ForbiddenByNsp`, "Request was not allowed by NSP rules"), the connector token was refused from the laptop and from classic compute, and only serverless reading the vault on its own connection through the NCC private endpoint still got `200`, because private endpoint traffic is exempt from the perimeter. This is the one posture in the whole matrix that keeps Unity Catalog out with `publicNetworkAccess` still `Enabled`. While the association was Enforced the vault's own `AuditEvent` log recorded no authenticated data-plane call at all, denied or admitted; the perimeter's access log is the only record of that window.
- **The subscription rule admits by identity, not by address** (rows 19 and 20): six seconds after the inbound rule for the connector's subscription, every lane worked again, from every network, the laptop included: the perimeter attributes a request carrying the connector's token to the access connector resource and admits it under the rule from the laptop's public address, while the user's own identity from the same laptop stays denied. So the rule gives back the same reach as the trusted-services bypass, scoped to one subscription's resources.

### Reproducing the Network Probe

```bash
./scripts/kv_network_probe.py trusted --watch-seconds 300 --gateway-model <model-alias>
./scripts/kv_network_probe.py closed  --watch-seconds 300 --gateway-model <model-alias>
./scripts/kv_network_probe.py locked  --watch-seconds 420 --gateway-model <model-alias>
./scripts/kv_network_probe.py sealed  --watch-seconds 420 --gateway-model <model-alias>

# Optional: deploy Log Analytics diagnostics and inspect Key Vault SecretGet caller IPs.
# Set enable_diagnostics = true in terraform.tfvars, review the plan, then apply that plan.
terraform plan -out diagnostics.tfplan
terraform apply diagnostics.tfplan
./scripts/smoke_test.sh secret
./scripts/smoke_test.sh callers

# The topology phases (notebooks/TOPOLOGY.md), after uploading the notebooks to /Shared/<catalog name>/
./measurements/sealed_with_ncc.sh "vault sealed + NCC live"      # needs enable_ncc_private_endpoint = true
./measurements/nsp_perimeter.sh                                     # needs enable_network_security_perimeter = true
./measurements/sql_lane.py --warehouse-id <id>
./measurements/credential_access_probe.sh <service principal application id>
```

---

## Topology Matrix: Workspaces, Compute, and Vault Posture

[`notebooks/topology_matrix.py`](notebooks/topology_matrix.py) measures five lanes to the secret from wherever it runs: UC read, compute DNS, a direct vault call without a token, a direct call with the service credential's token, and Unity Gateway. [`notebooks/TOPOLOGY.md`](notebooks/TOPOLOGY.md) records the runs across three workspaces, on serverless and classic compute, with the vault open, locked and sealed, with and without an NCC private endpoint and inside a Network Security Perimeter:

- Both tested workspaces on the secret's metastore (one VNet-injected, one managed VNet) read it through Unity Catalog and use it through Unity Gateway, on serverless (both) and classic compute (the VNet-injected one). A workspace on another metastore (another region) sees none of it.
- Locking the vault (`Disabled`, `Deny`, `AzureServices`) changed no Databricks lane. Neither the UC read nor the gateway lane needs a network path from compute to the vault.
- Key Vault's trusted-service admission follows the token, not the network. The credential's token (minted by `dbutils.credentials` on compute, or by `temporary-service-credentials` from a laptop, where it was valid about 24 h) read the locked vault from serverless, classic and a laptop outside Azure. The user's own identity was refused.
- So the vault firewall does not stop whoever can mint that token. The controls are `ACCESS` on the service credential, its workspace bindings, and the scope of the identity's Key Vault role.
- A SQL warehouse reaches the secret only through a Unity Catalog Python UDF with a `SECRETS` clause, which returned both secrets with the vault open and locked and failed sealed (`UDF_ERROR.INTERNAL_UNKNOWN`), like every notebook lane. `secret()` in SQL is the legacy-scope function and `ai_query` cannot address a model provider service on this workspace ("ai_query through UC Model Services is not enabled").
- A Network Security Perimeter in Enforced mode (rows 15 to 20) is the one network control that stops Unity Catalog's fetch while the vault's own firewall stays open: the Unity Catalog read, Unity Gateway and the connector token were refused everywhere except on serverless's own connection through the NCC private endpoint, which the perimeter exempts. An inbound rule for the connector's subscription re-admits the connector's token from every network, the laptop included, because the perimeter attributes requests to the identity's resource, not to the client address.
- `ACCESS` on the credential was then measured on its own (rows A1 and A2): a service principal with no `READ SECRET` on any secret, once granted `ACCESS`, minted the token and read both secrets straight from the vault, the real credential included, while its Unity Catalog read stayed refused. `ACCESS` on a service credential is therefore a grant of every secret its identity can reach; this repository grants it to nobody.

---

## Legacy Secret Scopes vs. Unity Catalog Secrets

[`notebooks/secrets_side_by_side.py`](notebooks/secrets_side_by_side.py) runs on Serverless compute (environment version 6) under both an admin persona and a least-privilege service principal (`uc-secrets-demo-reference-only`). Full cell-by-cell outputs are recorded in [`notebooks/RESULTS.md`](notebooks/RESULTS.md):

| Dimension | Legacy workspace secret scope | Unity Catalog external secret |
| :--- | :--- | :--- |
| **Key Vault auth model** | Requires legacy Vault access policies; incompatible with Azure RBAC (`rbac_authorization_enabled = true`). | Uses your `azurerm_databricks_access_connector` managed identity with standard Azure RBAC. |
| **Access levels** | `READ`, `WRITE`, `MANAGE` only (`REFERENCE` is rejected by the API). | `READ SECRET`, `REFERENCE SECRET`, or service-level `EXECUTE` via Unity Gateway. `ACCESS` on the service credential sits above all three: it mints the vault token and reads every secret directly ([TOPOLOGY.md](notebooks/TOPOLOGY.md), rows A1 and A2). |
| **Notebook redaction (`[REDACTED]`)** | Session-level literal string match on stdout; bypassed via `secret[1:]`, `" ".join(secret)`, or `secret[::-1]`. | Identical stdout string matching when a principal has `READ SECRET` and calls `dbutils.secrets.get()`. |
| **`REFERENCE SECRET` behavior** | Not supported. | Allows metadata discovery (`dbutils.secrets.list`); blocks `dbutils.secrets.get()`, REST `include_value=true`, UDFs, and creating new `secret_reference` services. |
| **Unity Gateway (`EXECUTE` only)** | Not supported. | Caller invokes the model endpoint with **zero privileges on the secret**; plaintext never enters notebook memory. |

---

## Operational Notes

- **Beta secret naming:** While External secrets for Unity Catalog is in Beta, use single lowercase words (`apimlanekey`, `dummysecret`) so Key Vault secret names and Unity Catalog identifiers match without normalization mismatches.
- **Azure RBAC propagation:** `azurerm_role_assignment.deployer_writes_secrets` can return in Terraform before the Key Vault data plane enforces `Key Vault Secrets Officer`. If the first `terraform apply` returns `403 Forbidden` when writing `apimlanekey`, re-run `terraform apply`.
- **Static-key vs. JWT APIM lanes:** Unity Gateway's custom provider sends a static `Authorization: Bearer <secret>` header; point `apim_lane_base_url` at a static-key APIM lane rather than an Entra JWT-validated lane.
- **macOS Azure CLI IPv6 timeouts:** If `az` commands hang for minutes while `terraform` and `databricks` respond immediately, check for broken IPv6 routes on `login.microsoftonline.com` or `*.vault.azure.net` (Python's `getaddrinfo` waits for the IPv6 connect timeout before falling back to IPv4).


## Offline checks and public release hygiene

```bash
terraform init -lockfile=readonly
terraform fmt -check -recursive
terraform validate
./scripts/test_offline.sh
python3 scripts/audit_public.py
```

The test runner copies only variable declarations, test fixtures and helpers into a temporary directory. `terraform test` uses the actual root declarations via a relative fixture symlink; Python tests mock all CLI/API operations. It never loads local tfvars/state or contacts Azure/Databricks. Terraform does not yet mock ephemeral resources, so the full APIM provisioning graph is verified by a separate authenticated, read-only plan. The provider lock includes hashes for `darwin_arm64`, `darwin_amd64`, `linux_amd64` and `linux_arm64`.

The public-file audit scans tracked files and untracked, nonignored additions without printing matched values. Recorded run/request/cluster IDs, raw IP addresses and secret fingerprints are anonymized; fractional timings and measured outcomes are retained. State, tfvars, saved plans and measurement exports remain gitignored. Before changing repository visibility, sanitize Git history or publish a clean-history repository: the release review found identifiers/workspace hosts in 15 of 16 locally reachable commits. Sanitizing the working tree does not remove those older contents. History has deliberately not been rewritten as part of this working-tree upgrade. Secret values, access tokens and unsanitized run exports must never be committed. Use a private remote backend with locking and restricted access for a shared production deployment.

Licensed under the [MIT License](LICENSE), Copyright (c) 2026 Cauchy.
