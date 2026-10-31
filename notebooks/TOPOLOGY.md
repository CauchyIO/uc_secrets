# Topology matrix: which lanes to a Key Vault-backed Unity Catalog secret work, and from where

Measured on 2026-10-29 and 2026-10-30 by running [`topology_matrix.py`](topology_matrix.py) on every workspace and compute type we could reach, with the demo vault
first open, then locked, in phase 3 sealed (`bypass None`) with an NCC private endpoint from the serverless compute plane to it, and in phase 4 sealed
again once that endpoint had started carrying serverless traffic. Rows 1 to 12 ran the notebook at SHA-256
`6740919764bb8e276e3135ccce672896bb3c031a18200226bf2933e3b0e20287`; rows 13 and 14 ran the next revision (SHA-256
`e6dcdb268954cdc57d73aac35404fcbfe014aad73f7ffc599c7a81729a90f81d`), which differs only in classifying an IPv4-mapped IPv6 address (`::ffff:a.b.c.d`)
by the IPv4 inside it. The file now in this directory is that revision with the estate's names taken out: the `vault_name` and `model` widgets
have no defaults (the drivers in [`measurements/`](../measurements) pass both; an empty one that is needed raises) and one comment names a workspace
by its role label; no lane changed.
The notebook was imported to `/Shared/uc_secrets_demo/topology_matrix` on each workspace and
submitted as one-time jobs with `databricks jobs submit`, as `<user>` (owner of the catalog, the credential and the connection).
Phase 5 (rows A1 and A2) ran a second notebook, [`credential_access_probe.py`](credential_access_probe.py) (SHA-256 `244504c57a12b955bc76a74760a5542199a0cf9ffc5aa4961cd3df57fa587dd1`),
on serverless as the reference-only service principal from [`RESULTS.md`](RESULTS.md), once without and once with `ACCESS` on the service credential.
The file in this directory differs from that revision only in having no default for `vault_name` (an empty one raises), which
[`measurements/credential_access_probe.sh`](../measurements/credential_access_probe.sh) passes, and in naming a workspace by its role label.
Phase 6 drove a SQL warehouse through the Statement Execution API instead of a notebook (its own section below). Phase 7 (rows 15 to 20) put the vault
inside an Azure Network Security Perimeter and ran the topology notebook (the rows 13 and 14 file) on serverless and classic with the perimeter association
in Learning, Enforced, and Enforced with an inbound rule for the connector's subscription, the vault itself open throughout; `diagnostics.tf` was applied
for it, so the vault's `AuditEvent` log and the perimeter's access log cover those rows.

- **Serverless:** environment version 6 (`DATABRICKS_RUNTIME_VERSION=client.6.5`, Spark 4.2.0, databricks-sdk 0.122.0).
- **Classic:** a single-node job cluster in the demo workspace's own VNet, `data_security_mode: SINGLE_USER` for `<user>`, `spark_version` `18.x-scala2.13`
  (reported as `18.3`, Spark 4.1.0, databricks-sdk 0.67.0), node type `Standard_F4s_v2`. The version is the newest LTS at or above 17.3 that
  `databricks clusters spark-versions` lists ("18 LTS"), in its plain x86 build (the `aarch64` builds need Arm node types).
  The node type is the smallest that started. The smallest in `databricks clusters list-node-types`, `Standard_D2ads_v6` (2 cores, 8 GB, tied with
  `Standard_D2ds_v6`), never got a driver up: after 12 minutes the cluster logged `ADD_NODES_FAILED`, `DriverStartupTimeout: Driver failed to start
  within 300 seconds`, "This commonly occurs on instances with fewer than 4 CPU cores" (run <run-or-timestamp-id>, cancelled). So the classic rows use the
  smallest x86 type with 4 cores: `Standard_F4s_v2` (4 cores, 8 GB, tied in size with `Standard_F4` and `Standard_F4s`; the v2 is the current generation).

Cell outputs are copied from `databricks jobs export-run` (rendered cells, exit value included). Identifiers of the estate are replaced by placeholders:
the tenant, account, subscription, metastore, workspace, NCC and NCC rule ids (`<tenant-id>`, `<databricks-account-id>`, `<subscription-id>`,
`<metastore-id>` and `<metastore-id-eastus>`, `<workspace-id>` and its role variants, `<ncc-id>`, `<ncc-rule-id>`), the private endpoint's name suffix
(`<endpoint-suffix>`), the demo workspace's VNet and its resource group (`<workspace-vnet>`, `<workspace-vnet-rg>`), the private-link workspaces'
NCC (`<private-link-ncc>`), the connector identity's object and application ids
(`<connector-oid>`, `<connector-appid>`), the reference-only service principal's application id (`<sp-application-id>`, as in `RESULTS.md`),
private addresses in the estate's networks (`<classic-node-ip>`, `<ncc-private-endpoint-ip>`, `<serverless-private-ip-a>` and `-b`), the upstream
model alias (`<model-alias>`) and LiteLLM's deployment id, and the workspaces' own names by the role labels in "The estate". Resource names that
this repository's Terraform defines (`rg-uc-secrets-demo`, `dbac-uc-secrets-demo`, `id-uc-secrets-demo`, `kv-ucsec-<workspace-id>`,
`nsp-uc-secrets-demo`, `law-uc-secrets-demo`) are kept: anyone who applies it gets the same names. Addresses that belong to Azure or Databricks
rather than to the estate are anonymized too: Key Vault's West Europe front end, the Databricks control-plane address `<public-ip-1>` and the serverless
sandbox's own private range. Host names that belong to Azure's Key Vault front end are replaced by `<kv-...>` placeholders in the cell
outputs (including the phase 7 driver log), and the
user's e-mail by `<user>`, the laptop's public address by `<laptop-ip>` and the user's Entra object id by `<user-oid>`. The real credential `apimlanekey` appears only as length 64 and SHA-256 prefix `<secret-sha256-prefix-1>`; the dummy as length 20 and `<dummy-sha256-prefix>`.

## Answers

1. **A Unity Catalog secret is scoped to its metastore, not to a workspace, a VNet or a compute type.** Both westeurope workspaces, one VNet-injected and
   one on a managed VNet, read the secret through Unity Catalog and used it through Unity Gateway on serverless compute, and the VNet-injected one also on
   classic compute, in both vault postures. The eastus workspace sits on another metastore, so the catalog, the connection, the credential and the provider service all "do not exist"
   there. Serving another region means building the chain again on that region's metastore. Whether that second chain can point at the same vault is
   an inference, not measured.
2. **Locking the vault changed nothing for Databricks.** With public network access `Disabled`, `defaultAction: Deny` and `bypass: AzureServices`, every
   lane that worked open worked locked: UC reads, Unity Gateway, and direct reads with the connector's token. Only the user's own identity, calling from a
   laptop, was refused.
3. **Cell 6 answers the trust question: Key Vault's trusted-service admission is identity-based.** It follows the token, not the network origin. With the vault
   locked, a direct `GET /secrets/dummysecret` carrying the service credential's token was admitted:
   - from serverless compute in two workspaces;
   - from classic compute in the customer VNet;
   - from a laptop on the public internet, outside Azure and outside every Databricks network.

   On the same laptop, at the same minute, the user's own Entra identity was refused with `Forbidden`, "Public network access is disabled and request is
   not from a trusted service nor via an approved private link".

   What distinguishes the token: its `oid`/`appid` are the user-assigned identity `id-uc-secrets-demo`, but its `xms_mirid` claim names the access connector
   (`Microsoft.Databricks/accessConnectors/dbac-uc-secrets-demo`). Reading that claim as the reason Key Vault counts the caller as a trusted service is an
   inference; the admission itself is measured.
4. **So the network lock does not protect the vault from anyone who can mint the credential's token.** Such a caller reads every secret the identity
   may read, directly, from any network:
   - `dbutils.credentials.getServiceCredentialsProvider()` mints the token on compute. `POST /api/2.1/unity-catalog/temporary-service-credentials`
     mints the same token from a laptop.
   - The token minted on the laptop was valid for 86,700 s, about 24 hours.
   - The vault call never passes through Unity Catalog, so no grant on any UC secret is checked.
   - The credential is `ISOLATION_MODE_OPEN`. Minting worked from both westeurope workspaces we ran in; by that isolation mode it should work from
     every workspace on the metastore (an inference for the others).

   The controls that do bind are not network controls:
   - who holds `ACCESS` on the service credential. Rows A1 and A2 measured that privilege on its own: a principal with no privilege on any secret,
     once granted `ACCESS` on the credential, minted the token through the REST API and through `dbutils.credentials` and read both secrets
     straight from the vault, the real one included, while its Unity Catalog read of the dummy secret stayed refused for lack of `READ SECRET`;
   - the credential's workspace bindings;
   - the scope of the identity's Key Vault role assignment. A per-secret assignment instead of the vault-wide `Key Vault Secrets User` would limit
     what a minted token can read.
5. **The UC read and gateway lanes do not depend on the compute's network path to the vault.** Every compute resolved the vault to the same three public addresses of Key Vault's
   West Europe front end, even serverless in eastus. Every compute got an anonymous `401` challenge from the vault, open and locked alike: "public network
   access Disabled" does not hide the endpoint, it refuses after authentication.

   In phases 1 and 2 no private endpoint was in play anywhere: no RFC 1918 answer, no `privatelink` alias. Phase 3 added one (rows 9 and 10): the
   `privatelink` alias then appeared in every resolver's chain, still resolving to the public front end. By the next morning, 9 h 45 min after the
   endpoint's approval (row 12), serverless resolved the vault to a private address (`<ncc-private-endpoint-ip>`, with the vault's own name as the canonical name and
   no alias chain), and kept doing so in phase 4 (row 13); classic compute still resolved it publicly (row 14), because the endpoint lives in the
   serverless network, not in the workspace's VNet. The UC read and gateway lanes did not change with the path in any of those rows. The classic cluster's subnets carry `Microsoft.KeyVault` service
   endpoints, and phase 7's logs show its direct calls arriving that way: the perimeter log classifies them as service-endpoint traffic
   (`EvaluatedSEPolicy`) and the vault logs their caller address as `0.0.0.0`, while serverless's calls through the NCC endpoint are logged as private
   traffic with a private address of the serverless network (`<serverless-private-ip-a>`, `<serverless-private-ip-b>`), not the driver's own.
6. **The gateway lane needs the workspace's own URL, which classic notebooks do not hand you.** On a classic cluster the notebook context points the SDK at
   the regional control-plane URL (`<regional-control-plane-host>` in the outputs below). The REST APIs answer there, but Unity Gateway returns `404` with an empty body
   (run <run-or-timestamp-id>). The notebook takes the workspace URL from `spark.databricks.workspaceUrl` on classic.
7. **An NCC private endpoint to the vault does not make a sealed vault usable for external secrets (phases 3 and 4, rows 9, 10, 13 and 14).** With
   `bypass None` and the endpoint `ESTABLISHED`, the Unity Catalog read, Unity Gateway, classic compute and the laptop were all refused, exactly as
   without the endpoint. In phase 3 the endpoint was not yet carrying serverless traffic either (serverless still resolved the vault publicly and was
   refused as a public caller). Phase 4 is the clean version of the test: by then serverless resolved the vault to the private endpoint address and read
   it with the connector token over that path (`200`, row 13), while in the same minute the Unity Catalog read and Unity Gateway from that very compute
   were refused, and classic compute (row 14) and the laptop (L4) were refused on both lanes. The endpoint carries what serverless compute opens itself
   and nothing that the Unity Catalog service opens. The enterprise answer is therefore: keep `bypass: AzureServices` for Unity Catalog, and treat the
   NCC endpoint as a tool for serverless code that talks to the vault directly, not as a substitute for the trusted-services exception.
8. **A SQL warehouse reaches the secret through one surface only, a Unity Catalog Python UDF with a `SECRETS` clause, and that surface behaves exactly
   like the notebook lanes under every vault posture** (phase 6, below). The `secret()` SQL function is the legacy-scope function: it takes exactly two
   arguments and knows no catalog. `ai_query` cannot address a model provider service here ("ai_query through UC Model Services is not enabled"), so
   Unity Gateway has no SQL surface on this workspace today.
9. **A Network Security Perimeter in Enforced mode is the one network control that keeps Unity Catalog out while the vault's own firewall stays open,
   and its subscription rule admits by identity, from anywhere** (phase 7, rows 15 to 20). In Learning mode nothing changed (rows 15 and 16). Enforced with
   no inbound rule (rows 17, 18 and L5): with `publicNetworkAccess: Enabled` and no network rules on the vault, the Unity Catalog read, Unity Gateway and
   the connector token were refused from serverless, classic and the laptop within a second of the switch (`ForbiddenByNsp`, "Request was not allowed by
   NSP rules"); only serverless reading the vault on its own connection through the NCC private endpoint still got `200`, because the perimeter does not
   evaluate private endpoint traffic. The perimeter attributes every request carrying the connector's token to the access connector resource, whatever
   the client address, and `DefaultDenyAll` applied to all of them, the control plane's included: Microsoft's "even trusted services are blocked" is
   measured here. With an inbound rule for the subscription that holds the connector (rows 19, 20 and L6), every lane worked again six seconds later,
   from every network, the laptop outside Azure included, while the user's own identity from the same laptop stayed denied. The rule therefore gives
   back the reach of the trusted-services bypass, scoped to one subscription's resources, and leaves answer 4 as it is.

## The estate

All in Databricks account `<databricks-account-id>` (Entra tenant `<tenant-id>`), run as `<user>`. Workspaces go by role labels, not by their own names:

| Label | Role | Region | Network | Metastore | Workspace id |
| --- | --- | --- | --- | --- | --- |
| `ws-demo` | the demo workspace: Terraform applied here, CLI profile | westeurope | VNet-injected | westeurope, `<metastore-id>` | `<workspace-id>` |
| `ws-weu-managed` | a second workspace on the demo metastore | westeurope | managed VNet | westeurope, `<metastore-id>` | `<workspace-id-managed-vnet>` |
| `ws-eastus` | a workspace on another metastore | eastus | managed VNet | eastus, `<metastore-id-eastus>` | `<workspace-id-eastus>` |
| `ws-private-link-dev` | private-link-only workspace, development | westeurope | VNet-injected, private link only | westeurope, `<metastore-id>` | `<workspace-id-private-link-dev>` |
| `ws-private-link-prd` | private-link-only workspace, production | westeurope | VNet-injected, private link only | westeurope, `<metastore-id>` | `<workspace-id-private-link-prd>` |

| Workspace | Host | Region | Metastore | Network | NCC | Our access | Run here |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `ws-demo` (demo) | `adb-<workspace-id>.14.azuredatabricks.net` | westeurope | `<metastore-id>` `metastore_azure_westeurope` | VNet-injected (VNet `<workspace-vnet>`, RG `<workspace-vnet-rg>`), no public IP, public front end. Both cluster subnets carry `Microsoft.KeyVault` and `Microsoft.Storage` service endpoints; no NAT gateway | none | workspace admin; CLI profile | serverless and classic, both postures |
| `ws-weu-managed` | `adb-<workspace-id-managed-vnet>.19.azuredatabricks.net` | westeurope | same westeurope metastore | managed VNet | none | workspace admin; Entra token | serverless, both postures |
| `ws-eastus` | `adb-<workspace-id-eastus>.15.azuredatabricks.net` | eastus | `<metastore-id-eastus>` `metastore_azure_eastus` (a different metastore; `uc_secrets_demo` does not exist there) | managed VNet | none | member of `admins` (the notebook's `W4_caller` says `workspace_admin: true`); Entra token | serverless, open posture |
| `ws-private-link-dev` | `adb-<workspace-id-private-link-dev>.9.azuredatabricks.net` | westeurope | same westeurope metastore | VNet-injected, `NoAzureDatabricksRules`, front end `publicNetworkAccess: Disabled` (private link only) | `<private-link-ncc>` (storage private endpoint rules) | not a member; the host answers "Unauthorized network access" from outside | **not run** (see "Run it yourself from inside") |
| `ws-private-link-prd` | `adb-<workspace-id-private-link-prd>.14.azuredatabricks.net` | westeurope | same westeurope metastore | as dev | `<private-link-ncc>` | not a member | **not run** |

The secret chain under test (Terraform in this repo): Key Vault `kv-ucsec-<workspace-id>` (RG `rg-uc-secrets-demo`, Azure RBAC) ←
service credential `uc_secrets_demo` (access connector `dbac-uc-secrets-demo` with user-assigned identity `id-uc-secrets-demo`, principal
`<connector-oid>`, which holds `Key Vault Secrets User` on the vault) ← connection `uc_secrets_demo_key_vault` ← schema
`uc_secrets_demo.secrets` (catalog isolation `OPEN`, no workspace bindings; the credential is `ISOLATION_MODE_OPEN` too) ← model provider service `litellm_via_apim`.

## The matrix

One row per run (workspace × compute × vault posture). "Open": public network access `Enabled`, no network rules. "Locked": public network access
`Disabled`, `defaultAction: Deny`, `bypass: AzureServices`. "Perimeter ...": the vault open, inside a Network Security Perimeter whose association is in the
named mode (phase 7). The UC read column covers three reads: `dbutils` and REST `include_value` on the dummy (hash
`<dummy-sha256-prefix>`), and `dbutils` on the real credential (hash `<secret-sha256-prefix-1>`).

| # | Workspace | Compute | Vault | `run_id` | UC read | Compute DNS | Compute direct, no token | Compute direct, connector token | Unity Gateway |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | `ws-demo` (VNet-injected) | serverless | open | <run-or-timestamp-id> | value ok ×3 | public | `401` challenge | `200`, same hash as UC | `502`, `upstream_status` 500 after 230.3 s: bearer accepted |
| 2 | `ws-demo` | classic, driver `<classic-node-ip>` in `private-subnet` | open | <run-or-timestamp-id> | value ok ×3 | public | `401` challenge | `200`, same hash | `502`, upstream 500 after 230.8 s: bearer accepted |
| 3 | `ws-weu-managed` (managed VNet) | serverless | open | <run-or-timestamp-id> | value ok ×3 | public | `401` challenge | `200`, same hash | `502`, upstream 500 after 230.3 s: bearer accepted |
| 4 | `ws-eastus` (eastus, other metastore) | serverless | open | <run-or-timestamp-id> | catalog missing ×3 | public | `401` challenge | credential missing | `404 NOT_FOUND`: provider service does not exist |
| 5 | `ws-demo` | serverless | **locked** | <run-or-timestamp-id> | value ok ×3 | public | `401` challenge | **`200`**, same hash | `502`, upstream 500 after 136.6 s (LiteLLM "Connection error"): bearer accepted |
| 6 | `ws-demo` | classic, driver `<classic-node-ip>` | **locked** | <run-or-timestamp-id> | value ok ×3 | public | `401` challenge | **`200`**, same hash | `429 REQUEST_LIMIT_EXCEEDED`, upstream 429 after 1.0 s: the notebook says "unclassified" (see below) |
| 7 | `ws-demo` | classic, driver `<classic-node-ip>` | **locked** | <run-or-timestamp-id> | value ok ×3 | public | `401` challenge | **`200`**, same hash | `502`, upstream 500 after 230.7 s: bearer accepted |
| 8 | `ws-weu-managed` | serverless | **locked** | <run-or-timestamp-id> | value ok ×3 | public | `401` challenge | **`200`**, same hash | `502`, upstream 500 after 136.0 s (LiteLLM "Connection error"): bearer accepted |
| L1 | laptop on the public internet (control, outside Azure) | none | open | none (20:22:54 UTC) | n/a | public | `401` challenge | `200`, same hash | n/a |
| L2 | laptop (control) | none | **locked** | none (20:36:12, 20:36:33, 20:39:29, 20:43:05, 20:48:26 UTC) | n/a | public | `401` challenge | **`200`**, same hash; the user's own identity (20:35:55, 20:36:09, 20:36:33, 20:39:29, 20:48:26): `403 Forbidden` | n/a |
| P | `ws-private-link-dev`, `ws-private-link-prd` (private link only, NCC) | serverless, classic | either | **not run** | | | | | |
| 9 | `ws-demo` | serverless | **sealed + NCC** | <run-or-timestamp-id> | refused ×3: `PERMISSION_DENIED`, "the cloud provider returned access denied" | public; the `privatelink` alias is now in the chain but still resolves to the public front end | `401` challenge | **`403 ForbiddenByConnection`**: "Connection is not an approved private link and caller was ignored because bypass is not set to 'AzureServices'" | `403 PERMISSION_DENIED` after 0.9 s: the gateway could not resolve the secret |
| 10 | `ws-demo` | classic, driver `<classic-node-ip>` | **sealed + NCC** | <run-or-timestamp-id> | refused ×3 | public | `401` challenge | **`403 ForbiddenByConnection`** | `403 PERMISSION_DENIED` after 0.7 s |
| L3 | laptop (control) | none | **sealed + NCC** | none (21:10:49, 21:10:50, 21:21:31 UTC) | REST from the laptop refused: "the cloud provider returned access denied" | public | n/a | **`403 ForbiddenByConnection`** with the connector token; the user's own identity refused at 21:10:49 | n/a |
| 11 | `ws-demo` | serverless | open, NCC endpoint `ESTABLISHED` (re-check 22 min after approval) | <run-or-timestamp-id> | value ok | public; `privatelink` alias in the chain, public addresses | `401` challenge | `200`, same hash | `502`, upstream 500 after 230.8 s: bearer accepted |
| 12 | `ws-demo` | serverless | open, NCC endpoint `ESTABLISHED` (second re-check, 9 h 45 min after approval) | <run-or-timestamp-id> | value ok ×3 | **private endpoint address** `<ncc-private-endpoint-ip>`; the vault's own name is the canonical name, no alias chain | `401` challenge | `200`, same hash | `502`, upstream 500 after 231.6 s: bearer accepted |
| 13 | `ws-demo` | serverless | **sealed + NCC live** | <run-or-timestamp-id> | refused ×3: `PERMISSION_DENIED`, "the cloud provider returned access denied" | **private endpoint address** `<ncc-private-endpoint-ip>` | `401` challenge | **`200`**, same hash: the compute's own connection went through the endpoint | `403 PERMISSION_DENIED` after 1.1 s: the gateway could not resolve the secret |
| 14 | `ws-demo` | classic, driver `<classic-node-ip>` | **sealed + NCC live** | <run-or-timestamp-id> | refused ×3 | public; `privatelink` alias in the chain | `401` challenge | **`403 ForbiddenByConnection`** | `403 PERMISSION_DENIED` after 0.9 s |
| L4 | laptop (control) | none | **sealed + NCC live** | none (06:53:03, 07:02:22 UTC) | REST from the laptop refused: "the cloud provider returned access denied" | public | n/a | **`403 ForbiddenByConnection`** with the connector token; the user's own identity refused at 06:53:03 | n/a |
| 15 | `ws-demo` | serverless | open, **perimeter Learning** | <run-or-timestamp-id> | value ok ×3 | **private endpoint address** `<ncc-private-endpoint-ip>` | `401` challenge | `200`, same hash | `502`, upstream 500 after 231.3 s: bearer accepted |
| 16 | `ws-demo` | classic, driver `<classic-node-ip>` | open, **perimeter Learning** | <run-or-timestamp-id> | value ok ×3 | public; `privatelink` alias in the chain | `401` challenge | `200`, same hash (over the subnet's service endpoint, see the perimeter log) | `502`, upstream 500 after 230.9 s: bearer accepted |
| 17 | `ws-demo` | serverless | open, **perimeter Enforced, no rule** | <run-or-timestamp-id> | **refused ×3**: `PERMISSION_DENIED`, "the cloud provider returned access denied" | **private endpoint address** `<ncc-private-endpoint-ip>` | `401` challenge | **`200`**, same hash: private endpoint traffic is exempt from the perimeter | `403 PERMISSION_DENIED` after 1.3 s: the gateway could not resolve the secret |
| 18 | `ws-demo` | classic, driver `<classic-node-ip>` | open, **perimeter Enforced, no rule** | <run-or-timestamp-id> | **refused ×3** | public; `privatelink` alias in the chain | `401` challenge | **`403 ForbiddenByNsp`**: "Request was not allowed by NSP rules. Client address: 0.0.0.0 Caller: name=microsoft.databricks/accessconnectors" | `403 PERMISSION_DENIED` after 0.8 s |
| L5 | laptop (control) | none | open, **perimeter Enforced, no rule** | none (14:58:13, 15:02:18 UTC) | REST from the laptop refused: "the cloud provider returned access denied" | public | n/a | **`403 ForbiddenByNsp`** with the connector token: "Request was not allowed by NSP rules. Client address: `<laptop-ip>` Caller: name=microsoft.databricks/accessconnectors"; the user's own identity refused at 14:58:10, 14:58:14 and 15:02:18 with the same reason | n/a |
| 19 | `ws-demo` | serverless | open, **perimeter Enforced + subscription rule** | <run-or-timestamp-id> | value ok ×3 | **private endpoint address** `<ncc-private-endpoint-ip>` | `401` challenge | `200`, same hash | `502`, upstream 500 after 230.9 s: bearer accepted |
| 20 | `ws-demo` | classic, driver `<classic-node-ip>` | open, **perimeter Enforced + subscription rule** | <run-or-timestamp-id> | value ok ×3 | public; `privatelink` alias in the chain | `401` challenge | `200`, same hash: admitted by `admit-connector-subscription` | `502`, upstream 500 after 230.8 s: bearer accepted |
| L6 | laptop (control) | none | open, **perimeter Enforced + subscription rule** | none (15:02:34, 15:10:42 UTC) | REST from the laptop ok | public | n/a | **`200`**, same hash: the rule admitted the connector's token from the laptop's public address; the user's own identity still refused at 15:02:35 and 15:10:42 | n/a |

Row 12's raw output says `mixed` for the DNS lane: the notebook revision that ran it classified the IPv4-mapped form `::ffff:<ncc-private-endpoint-ip>` as public.
It is the same private address; rows 13 and 14 ran the corrected file and say `private endpoint address`.

Row 6's `429` body is LiteLLM's cooldown message ("No deployments available for selected model, Try again in 60 seconds. Passed model=<model-alias>"). Rows 5
and 8 had just failed against the same model, and LiteLLM had put the deployment on cooldown. LiteLLM sits behind APIM's bearer check, so the request had
passed APIM, but the notebook's classifier has no rule for `429` and labels it "unclassified". Row 7 is the same cell run again after the cooldown.

The serverless driver address is `<private-ip-2>` (with a second address observed once) in every workspace and region. It is the sandbox's own address, not an address in any customer network.

## Runs

Phase 1 (vault open, verified with `az keyvault show` before and after: `publicNetworkAccess: Enabled`, `networkAcls: null`): rows 1 to 4, submitted together
at 20:22 UTC. Phase 2 (locked): `az keyvault update ... --public-network-access Disabled --default-action Deny --bypass AzureServices` at 20:35:53 UTC. The
first direct read from the laptop with the user's own identity, at 20:35:55, was already refused, so enforcement was in place before rows 5, 6 and 8 were
submitted at 20:36:06 to 20:36:08. Restored at 20:48:30 UTC with `--public-network-access Enabled --default-action Allow --bypass AzureServices`; the vault
was locked for 12 min 37 s.

Phase 3 (sealed, with the NCC private endpoint): `ncc.tf` was applied at 20:58 to 21:00 UTC (NCC `ncc-uc-secrets-demo`, rule towards the vault's `vault`
sub-resource, binding to `ws-demo`, endpoint approved on the vault at 21:00:45; Databricks reported the rule `ESTABLISHED`). The orchestration
(`phase3.sh`, log below; in the repository as [`measurements/sealed_with_ncc.sh`](../measurements/sealed_with_ncc.sh)) waited until 21:10:45, ten minutes after the approval, which is the propagation time Databricks documents for a new binding and
for rule changes, then sealed the vault: `--public-network-access Disabled --default-action Deny --bypass None`. The first direct read with the user's
identity, one second later, was already refused. Rows 9 and 10 were submitted at 21:10:52; the vault was restored at 21:21:40 (sealed for 10 min 49 s)
and a Unity Catalog read succeeded at once afterwards.

Phase 3 re-checks (rows 11 and 12): the same serverless row again with the vault open. At 21:22:45, 22 minutes after the endpoint's approval and
24 minutes after the binding, serverless still resolved the vault to the public front end (a different canonical name this time, same addresses). At
06:45:28 the next morning, 9 h 45 min after the approval, it resolved the vault to `<ncc-private-endpoint-ip>`, a private address, with the vault's own name as the
canonical name and no alias chain: the endpoint was carrying serverless traffic by then. Nothing was measured between those two points, so the
propagation time is bounded, not known; Databricks documents up to 24 hours.

Phase 4 (sealed again, endpoint live): `phase4.sh`, the phase 3 orchestration with new labels (the label argument of `measurements/sealed_with_ncc.sh`), sealed the vault at 06:53:00 UTC on 2026-10-30
(`--public-network-access Disabled --default-action Deny --bypass None`); the first direct read with the user's identity was refused one second later.
Rows 13 and 14 were submitted at 06:53:06; the vault was restored at 07:02:29 (sealed for 9 min 29 s) and a Unity Catalog read succeeded at once
afterwards. The notebook file for rows 13 and 14 carries the classifier fix described at the top; nothing else changed.

Phase 5 (credential `ACCESS`, rows A1 and A2): `credential_access_probe.py` was imported to `/Shared/uc_secrets_demo/credential_access_probe` and
submitted twice on serverless with `run_as.service_principal_name` set to the reference-only service principal, the vault open. Row A1 ran with no
privilege on the credential. `ACCESS` was then added for that principal with `PATCH /api/2.1/unity-catalog/permissions/credential/uc_secrets_demo`
at 09:55:42 UTC, row A2 was submitted one second later, and the privilege was removed at 09:56:18, three seconds after the run ended. The credential's
grants are empty again (`GET .../permissions/credential/uc_secrets_demo` returns `{}`).

Phase 7 (Network Security Perimeter, rows 15 to 20): `nsp.tf` and `diagnostics.tf` were applied at about 14:38 UTC on 2026-10-30 (perimeter
`nsp-uc-secrets-demo`, profile `vault`, the vault's association in Learning mode; Log Analytics workspace `law-uc-secrets-demo` receiving the vault's
`AuditEvent` log and the perimeter's access log). The vault itself stayed open (`publicNetworkAccess: Enabled`, no network rules) throughout, verified
before the first run and after the restore. The orchestration ([`measurements/nsp_perimeter.sh`](../measurements/nsp_perimeter.sh), log below) submitted
rows 15 and 16 at 14:44:17 with the association in Learning; switched it to Enforced at 14:57:34 (the call returned at 14:58:09, and the first direct
read with the user's identity, one second later, was refused with "Request was not allowed by NSP rules"); submitted rows 17 and 18 at 14:58:12; created
the inbound rule `admit-connector-subscription` (subscription-based, naming the subscription that holds the access connector and its identity) at
15:02:23 (returned 15:02:25; the Unity Catalog read from the laptop was admitted six seconds later); submitted rows 19 and 20 at 15:02:34; and at
15:10:47 deleted the rule and set the association back to Learning (returned 15:11:23; the user's identity was admitted again one second later, the Unity
Catalog read succeeded, and `terraform plan` reported no changes). The association was Enforced for 13 min 14 s.

| Row | `run_id` / task `run_id` | `run_label` | Started (UTC) | Result |
| --- | --- | --- | --- | --- |
| 1 | <run-or-timestamp-id> / <run-or-timestamp-id> | vault open: ws-demo serverless | 20:22:38 | SUCCESS |
| 2 | <run-or-timestamp-id> / <run-or-timestamp-id> | vault open: ws-demo classic | 20:22:37 (cluster setup 472 s) | SUCCESS |
| 3 | <run-or-timestamp-id> / <run-or-timestamp-id> | vault open: ws-weu-managed serverless | 20:22:39 | SUCCESS |
| 4 | <run-or-timestamp-id> / <run-or-timestamp-id> | vault open: ws-eastus serverless | 20:22:40 | SUCCESS |
| 5 | <run-or-timestamp-id> / <run-or-timestamp-id> | vault locked: ws-demo serverless | 20:36:07 | SUCCESS |
| 6 | <run-or-timestamp-id> / <run-or-timestamp-id> | vault locked: ws-demo classic | 20:36:06 (cluster setup 162 s) | SUCCESS |
| 7 | <run-or-timestamp-id> / <run-or-timestamp-id> | vault locked: ws-demo classic (second run) | 20:40:31 (cluster setup 161 s) | SUCCESS |
| 8 | <run-or-timestamp-id> / <run-or-timestamp-id> | vault locked: ws-weu-managed serverless | 20:36:08 | SUCCESS |
| 9 | <run-or-timestamp-id> / <run-or-timestamp-id> | vault sealed + NCC: ws-demo serverless | 21:10:52 | SUCCESS |
| 10 | <run-or-timestamp-id> / <run-or-timestamp-id> | vault sealed + NCC: ws-demo classic | 21:10:52 (cluster setup to 21:21:31) | SUCCESS |
| 11 | <run-or-timestamp-id> | vault open + NCC propagation check: ws-demo serverless | 21:22:45 | SUCCESS |
| 12 | <run-or-timestamp-id> / <run-or-timestamp-id> | vault open + NCC propagation check: ws-demo serverless (second re-check) | 2026-10-30 06:45:28 | SUCCESS |
| 13 | <run-or-timestamp-id> / <run-or-timestamp-id> | vault sealed + NCC live: ws-demo serverless | 06:53:05 | SUCCESS |
| 14 | <run-or-timestamp-id> / <run-or-timestamp-id> | vault sealed + NCC live: ws-demo classic | 06:53:06 (cluster setup 472 s) | SUCCESS |
| A1 | <run-or-timestamp-id> / <run-or-timestamp-id> | control: reference-only SP, no ACCESS on the credential | 09:54:51 | SUCCESS |
| A2 | <run-or-timestamp-id> / <run-or-timestamp-id> | reference-only SP, ACCESS on the credential | 09:55:43 | SUCCESS |
| 15 | <run-or-timestamp-id> / <run-or-timestamp-id> | vault open + NSP Learning: ws-demo serverless | 14:44:15 | SUCCESS |
| 16 | <run-or-timestamp-id> / <run-or-timestamp-id> | vault open + NSP Learning: ws-demo classic | 14:44:17 (cluster setup 503 s) | SUCCESS |
| 17 | <run-or-timestamp-id> / <run-or-timestamp-id> | vault open + NSP Enforced, no rule: ws-demo serverless | 14:58:11 | SUCCESS |
| 18 | <run-or-timestamp-id> / <run-or-timestamp-id> | vault open + NSP Enforced, no rule: ws-demo classic | 14:58:12 (cluster setup 161 s) | SUCCESS |
| 19 | <run-or-timestamp-id> / <run-or-timestamp-id> | vault open + NSP Enforced + subscription rule: ws-demo serverless | 15:02:33 | SUCCESS |
| 20 | <run-or-timestamp-id> / <run-or-timestamp-id> | vault open + NSP Enforced + subscription rule: ws-demo classic | 15:02:34 (cluster setup 183 s) | SUCCESS |

Earlier runs on earlier revisions of the notebook, superseded by the rows above. Where they produced lane outcomes, those agree with the rows above; the
first three are cited for what went wrong:

- <run-or-timestamp-id> (ws-eastus): `get_token` on a credential the metastore does not have raises a bare `Exception`. The notebook now takes that answer from
  the typed credential lookup instead.
- <run-or-timestamp-id>: `Standard_D2ads_v6`, driver startup timeout, cancelled.
- <run-or-timestamp-id>: classic; the gateway call went to the regional host and got `404`, which led to the workspace-URL fix.
- <run-or-timestamp-id>, <run-or-timestamp-id>, <run-or-timestamp-id>, <run-or-timestamp-id> (serverless, same outcomes as rows 1, 3 and 4).
- <run-or-timestamp-id>, <run-or-timestamp-id>, <run-or-timestamp-id>, <run-or-timestamp-id> (a revision that differed only in comments; three cancelled, one completed).

## What each result proves

- **UC read lane (rows 1 to 3, 5 to 8): the metastore, not the workspace's network, decides.** The same three reads succeeded from a VNet-injected workspace
  with no public IP and from a managed-VNet workspace, on serverless and on classic, open and locked. The hashes match across all rows. The Unity Catalog
  service fetches the value with the credential's identity; the compute only talks to its own workspace's control plane.
- **Row 4: another metastore is another world.** `ws-eastus` sees no catalog, no connection, no credential and no provider service. The REST read answers
  `404 CATALOG_DOES_NOT_EXIST`. `dbutils` raises `ManagedCatalogServiceException: CATALOG_DOES_NOT_EXIST`. The gateway answers
  `404 NOT_FOUND 'uc_secrets_demo.secrets.litellm_via_apim' does not exist` in 0.2 s. The vault itself still answered that compute (`401`): the boundary
  is the metastore's object namespace, not the network.
- **Compute DNS (all rows): no private endpoint anywhere, and none needed.** The vault resolved to the same public front-end addresses from serverless in
  both regions and from the VNet-injected classic driver. The canonical name differed between resolvers (`<kv-traffic-manager-canonical-a>` and
  `-b`), and the aliases were the same West Europe front end.
- **Compute direct, no token (all rows, both postures): the vault's front end answers everyone.** `401` with a `Bearer` challenge
  (`AKV10000: Request is missing a Bearer, PoP, or MTLS_POP token.`), even with public network access `Disabled`. The network decision comes after
  authentication: it is a decision about the caller, not a closed port.
- **Compute direct, connector token (rows 1 to 3, 5 to 8, L1, L2): the credential's token is a key to the vault, valid from anywhere.** Open: expected,
  RBAC grants the identity `Key Vault Secrets User`. Locked: still `200` from serverless, classic and the laptop, while the user's identity is refused.
  Key Vault treats the access connector's token as a trusted service regardless of where it comes from. So `bypass: AzureServices` admits that
  identity from every network, not only the Databricks control plane. Compare the README's sealed posture (`bypass: None`): there the UC read lane itself
  fails. Phases 3 and 4 then looked for a posture that separates the two, and phase 4 found it: sealed with a live NCC endpoint, a minted token works
  from serverless over the endpoint while Unity Catalog stays out (see the next two bullets).
- **Phase 3, rows 9, 10 and L3: the NCC private endpoint changed nothing within its documented propagation window.** With the vault sealed and the
  endpoint `ESTABLISHED` and approved, the Unity Catalog read was refused from serverless, from classic and from the laptop's REST call, with the same
  "cloud provider returned access denied" text as in the README's sealed row; Unity Gateway answered `403 PERMISSION_DENIED` in under a second instead of
  reaching APIM; and the connector token was refused everywhere with Key Vault's own reason, `ForbiddenByConnection`: "Connection is not an approved
  private link and caller was ignored because bypass is not set to 'AzureServices'". Two things follow. First, `bypass None` is the one posture that keeps a
  minted token out from any network, and it keeps Unity Catalog out with it: the control-plane fetch does not travel through the workspace's NCC. Second,
  the serverless compute itself did not use the endpoint in this window: its DNS answer now carries the vault's `privatelink` alias (that alias appears in
  the public chain once a private endpoint exists on the vault; rows 1 to 8 had no such alias) but still resolves to the public front end, and its direct
  call was refused as a public caller. Databricks documents ten minutes for most propagation and up to 24 hours in full; row 12 found the endpoint
  live 9 h 45 min after approval, and phase 4 repeated the sealed test with it live.
- **Phase 4, rows 13, 14 and L4: with the endpoint live, serverless reaches the sealed vault on its own connection and nothing else does.** Row 13's
  serverless compute resolved the vault to the private endpoint address and read `dummysecret` with the connector token over it (`200`, same hash),
  while in the same run the Unity Catalog read was refused three times and Unity Gateway answered `403 PERMISSION_DENIED` in 1.1 s. Row 14's classic
  cluster, in the workspace's own VNet, still resolved the vault publicly and got `ForbiddenByConnection`; the laptop got the same. So the NCC endpoint
  is a path for connections that serverless compute opens itself. The Unity Catalog service's fetch, the one behind `dbutils.secrets.get` and Unity
  Gateway's `secret_reference`, does not use it, and no posture in this matrix admits that fetch without the trusted-services bypass.
- **Unity Gateway lane (rows 1 to 3, 5, 7, 8): any workspace on the metastore can use the provider service, and the vault posture is
  irrelevant to it.** The bearer was accepted by APIM in every westeurope run. The upstream model was down, either as APIM's 500 after about 231 s or as
  LiteLLM's "Connection error" after about 136 s; the model was not up for a full completion.
- **Phase 7, rows 17, 18 and L5: a perimeter in Enforced mode keeps Unity Catalog out with the vault's own firewall open.** With
  `publicNetworkAccess: Enabled` and no network rules on the vault, the Unity Catalog read was refused from serverless, from classic and from the
  laptop's REST call with the same "cloud provider returned access denied" text as the sealed posture, Unity Gateway answered `403 PERMISSION_DENIED`
  in about a second, and the connector token was refused from the laptop and from classic compute with Key Vault's reason for this case,
  `ForbiddenByNsp`: "Request was not allowed by NSP rules". The perimeter log shows why: it attributes every request carrying that token to the access
  connector resource, whatever the client address, and with no inbound rule its `DefaultDenyAll` applied to all public inbound traffic, the control
  plane's fetch included, which is Microsoft's "even trusted services are blocked" measured. Serverless's own call through the NCC endpoint still got
  `200` (row 17), logged as private inbound traffic that the perimeter does not evaluate. Enforced mode is therefore the first network control in this
  matrix that separates the vault's firewall from the token: it stops the token on every public path and leaves the private endpoint path open.
- **Phase 7, rows 19, 20 and L6: a subscription inbound rule re-admits the connector by identity, from anywhere.** Six seconds after the rule,
  Unity Catalog's fetch (from the control plane's public address), the classic cluster's call over its service endpoint and the laptop's call with the
  connector token were all admitted under `admit-connector-subscription`, while the user's own identity from the same laptop stayed under
  `DefaultDenyAll`. The rule's match key is the resource the request is attributed to (the access connector, in the admitted subscription), not the
  client address: the laptop outside Azure was admitted the moment it presented the connector's token. The perimeter thus reproduces the
  trusted-services bypass with a narrower scope, one subscription's resources instead of every trusted Microsoft service, and does not change answer 4.

## Laptop control: the same token from outside Azure

Cell 6 alone cannot tell "Key Vault trusts this token" from "Key Vault trusts any Databricks compute". The control repeats cell 6 from a laptop on the
public internet. The laptop is outside Azure and outside every Databricks network.

It mints the token with `POST /api/2.1/unity-catalog/temporary-service-credentials`, the endpoint `dbutils.credentials.getServiceCredentialsProvider()`
calls (visible in the traceback of run <run-or-timestamp-id>). Around each token call it reads the same secret with the user's own Entra identity (`az keyvault
secret show`), a principal that also holds a data role on the vault, `Key Vault Secrets Officer`. Neither token is printed. The request body needs
`azure_options.resources`, ending in `/.default`: `scopes` is rejected with `azure_options.resources must not be empty`, and a resource without `/.default`
with "The scope in the resource url must be '.default'".

```bash
TOKEN=$(databricks api post /api/2.1/unity-catalog/temporary-service-credentials -p <profile> \
  --json '{"credential_name": "uc_secrets_demo", "azure_options": {"resources": ["https://vault.azure.net/.default"]}}' \
  | python3 -c 'import json,sys; print(json.load(sys.stdin)["azure_aad"]["aad_token"])')
curl -4 -s -o /dev/null -w 'no token: %{http_code}\n' "https://<key-vault>.vault.azure.net/secrets?api-version=7.4"
curl -4 -s -H "Authorization: Bearer $TOKEN" "https://<key-vault>.vault.azure.net/secrets/dummysecret?api-version=7.4" \
  | python3 -c 'import hashlib,json,sys; d=json.load(sys.stdin); print("connector token:", "value sha256", hashlib.sha256(d["value"].encode()).hexdigest()[:12] if "value" in d else d)'
az keyvault secret show --vault-name <key-vault> -n dummysecret --query id -o tsv   # the user's own identity, for comparison
```

Outputs (the token's identity claims decoded from its payload; the issuer URL in the `az` error is shortened to `<entra-issuer>`):

```text
laptop control, vault open, 2026-10-29 20:22:54 UTC
token identity: {"oid": "<connector-oid>", "appid": "<connector-appid>", "idtyp": "app", "xms_mirid": "/subscriptions/<subscription-id>/resourceGroups/rg-uc-secrets-demo/providers/Microsoft.Databricks/accessConnectors/dbac-uc-secrets-demo"}
laptop, no token: 401 Unauthorized AKV10000: Request is missing a Bearer, PoP, or MTLS_POP token.
laptop, connector token: 200 sha256 prefix <dummy-sha256-prefix>
token lifetime (s): 86700

laptop control, vault locked, 2026-10-29 20:36:12 UTC
token identity: {"oid": "<connector-oid>", "appid": "<connector-appid>", "idtyp": "app", "xms_mirid": "/subscriptions/<subscription-id>/resourceGroups/rg-uc-secrets-demo/providers/Microsoft.Databricks/accessConnectors/dbac-uc-secrets-demo"}
laptop, no token: 401 Unauthorized AKV10000: Request is missing a Bearer, PoP, or MTLS_POP token.
laptop, connector token: 200 sha256 prefix <dummy-sha256-prefix>
token lifetime (s): 86700

== paired laptop check 2026-10-29 20:36:33 UTC
user identity (az): ERROR: (Forbidden) Public network access is disabled and request is not from a trusted service nor via an approved private link.
token identity: {"oid": "<connector-oid>", "appid": "<connector-appid>", "idtyp": "app", "xms_mirid": "/subscriptions/<subscription-id>/resourceGroups/rg-uc-secrets-demo/providers/Microsoft.Databricks/accessConnectors/dbac-uc-secrets-demo"}
laptop, no token: 401 Unauthorized AKV10000: Request is missing a Bearer, PoP, or MTLS_POP token.
laptop, connector token: 200 sha256 prefix <dummy-sha256-prefix>
user identity (az) again: ERROR: (Forbidden) Public network access is disabled and request is not from a trusted service nor via an approved private link.
== paired laptop check 2026-10-29 20:39:29 UTC
user identity (az): ERROR: (Forbidden) Public network access is disabled and request is not from a trusted service nor via an approved private link.
token identity: {"oid": "<connector-oid>", "appid": "<connector-appid>", "idtyp": "app", "xms_mirid": "/subscriptions/<subscription-id>/resourceGroups/rg-uc-secrets-demo/providers/Microsoft.Databricks/accessConnectors/dbac-uc-secrets-demo"}
laptop, no token: 401 Unauthorized AKV10000: Request is missing a Bearer, PoP, or MTLS_POP token.
laptop, connector token: 200 sha256 prefix <dummy-sha256-prefix>
user identity (az) again: ERROR: (Forbidden) Public network access is disabled and request is not from a trusted service nor via an approved private link.
== the bash commands above, 2026-10-29 20:43:05 UTC
no token: 401
connector token: value sha256 <dummy-sha256-prefix>
== paired laptop check 2026-10-29 20:48:26 UTC
user identity (az): ERROR: (Forbidden) Public network access is disabled and request is not from a trusted service nor via an approved private link.
token identity: {"oid": "<connector-oid>", "appid": "<connector-appid>", "idtyp": "app", "xms_mirid": "/subscriptions/<subscription-id>/resourceGroups/rg-uc-secrets-demo/providers/Microsoft.Databricks/accessConnectors/dbac-uc-secrets-demo"}
laptop, no token: 401 Unauthorized AKV10000: Request is missing a Bearer, PoP, or MTLS_POP token.
laptop, connector token: 200 sha256 prefix <dummy-sha256-prefix>
user identity (az) again: ERROR: (Forbidden) Public network access is disabled and request is not from a trusted service nor via an approved private link.

after restore:
== paired laptop check 2026-10-29 20:48:35 UTC
user identity (az): https://kv-ucsec-<workspace-id>.vault.azure.net/secrets/dummysecret/8a2075a9c1cb4f73a9b451a164241526
token identity: {"oid": "<connector-oid>", "appid": "<connector-appid>", "idtyp": "app", "xms_mirid": "/subscriptions/<subscription-id>/resourceGroups/rg-uc-secrets-demo/providers/Microsoft.Databricks/accessConnectors/dbac-uc-secrets-demo"}
laptop, no token: 401 Unauthorized AKV10000: Request is missing a Bearer, PoP, or MTLS_POP token.
laptop, connector token: 200 sha256 prefix <dummy-sha256-prefix>
user identity (az) again: https://kv-ucsec-<workspace-id>.vault.azure.net/secrets/dummysecret/8a2075a9c1cb4f73a9b451a164241526
```

## Credential `ACCESS` without `READ SECRET` (phase 5, rows A1 and A2)

Answer 4 rested on an inference: every token in rows 1 to 14 and in the laptop controls was minted by the owner of the credential. Phase 5 measured the
privilege itself. [`credential_access_probe.py`](credential_access_probe.py) ran twice on serverless as the reference-only service principal from
[`RESULTS.md`](RESULTS.md), which holds `USE CATALOG`, `USE SCHEMA`, `REFERENCE SECRET` on both secrets and `EXECUTE` on the provider service, and no
`READ SECRET` anywhere. Row A1 ran with no privilege on the credential; row A2 after `ACCESS` on `uc_secrets_demo` was granted to it (and removed again
right after the run). The vault was open throughout; its posture does not matter to a token holder (rows 5 to 8, L2).

| Claim | Lane | A1: no `ACCESS` | A2: `ACCESS` |
| --- | --- | --- | --- |
| A1 | UC read of the dummy secret, REST `include_value` | `403 PERMISSION_DENIED`: "does not have READ SECRET" | `403 PERMISSION_DENIED`: "does not have READ SECRET" |
| A2 | `GET /credentials/uc_secrets_demo` | `403 PERMISSION_DENIED`: "does not have any privileges on Credential" | visible: owner `<user>`, `ISOLATION_MODE_OPEN`, `SERVICE` |
| A3 | `POST /temporary-service-credentials` | `403 PERMISSION_DENIED`: "does not have ACCESS on Credential" | **token issued** for the connector identity (`xms_mirid` = the access connector), valid until 2026-10-31 09:54:22 UTC, about 24 h |
| A4 | with that token, Key Vault directly: list, read the dummy, read the real secret | not attempted (no token) | **`200` ×3**: both names listed; dummy length 20, `<dummy-sha256-prefix>`; real length 64, `<secret-sha256-prefix-1>` |
| A5 | `dbutils.credentials.getServiceCredentialsProvider` on the compute | refused, "does not have ACCESS on Credential" (a bare `Exception`) | **token issued, `200`** on the dummy, same hash as A4 |

What the two rows prove:

- **`ACCESS` on the service credential is the privilege that mints the token**, on compute and through the REST API alike. Without it both paths are
  refused with the same Unity Catalog message, and the credential's metadata is not even visible.
- **With it, the per-secret privileges are out of the loop.** The principal could not read the dummy secret through Unity Catalog in either row (no
  `READ SECRET`), yet in row A2 it read that secret and the real credential straight from the vault, with the identity Unity Catalog itself uses. From
  that point only Key Vault decides, through the identity's role assignment (`Key Vault Secrets User` on the whole vault).
- **So granting `ACCESS` on the credential grants every secret the identity can reach, in the clear, from any network** (rows 5 to 8 and L2 for the
  network part). It belongs with the credential's owner and its workspace bindings, not with the `READ SECRET` / `REFERENCE SECRET` model, and the
  Terraform in this repository grants it to nobody. A per-secret role assignment on the vault would be the one control that still applies to a token holder.

## SQL warehouse lane (phase 6)

The topology notebook cannot run on a SQL warehouse (no `dbutils`, no Python cell), so this lane was driven through the Statement Execution API
(`POST /api/2.0/sql/statements`) on the demo workspace's serverless SQL warehouse (`Serverless Starter Warehouse`, PRO, DBSQL `2026.42`, same
westeurope metastore), as `<user>`, on 2026-10-30 09:57 to 10:01 UTC. Every statement returns only lengths and SHA-256 prefixes; no value leaves the
warehouse. A throwaway schema `uc_secrets_demo.sql_lane` held the two functions and was dropped at the end. The vault was flipped with `az keyvault update`
exactly as in phases 2 and 3, and each posture was measured only after a direct read with the user's identity was refused.

| Statement | Vault | Result | Time |
| --- | --- | --- | --- |
| `SELECT length(secret('uc_secrets_demo_legacy', 'dummy')), left(sha2(secret(...), 256), 12)` | open | **works**: the legacy-scope SQL function; 23 chars, `<secret-sha256-prefix-2>` | 1.6 s |
| `secret('uc_secrets_demo.secrets.dummysecret')` | open | `WRONG_NUM_ARGS`: "`secret` requires 2 parameters but the actual number is 1" | 0.6 s |
| `secret('uc_secrets_demo', 'secrets', 'dummysecret')` | open | `WRONG_NUM_ARGS`: 3 given | 0.9 s |
| `secret('uc_secrets_demo.secrets', 'dummysecret')` | open | `INVALID_SECRET_LOOKUP`: "Secret does not exist with scope: uc_secrets_demo.secrets": the schema is not a scope | 0.7 s |
| `CREATE FUNCTION ... LANGUAGE PYTHON SECRETS (uc_secrets_demo.secrets.dummysecret) ENVIRONMENT (environment_version = '6')` | open | **created from the warehouse** (and the same for `apimlanekey`) | 17.6 s, 1.5 s |
| `SELECT dummy_secret_sha(), real_secret_sha()` (each returns `length:sha256_prefix`) | open | **`20:<dummy-sha256-prefix>`, `64:<secret-sha256-prefix-1>`**, the same hashes as every notebook lane | 26.9 s, then 10.9 s |
| same | **locked** (`Disabled`, `Deny`, `AzureServices`) | **same values** | 10.2 s, 9.7 s |
| same | **sealed** (`Disabled`, `Deny`, `None`) | **`UDF_ERROR.INTERNAL_UNKNOWN`**: "Execution of function ... failed due to an unknown error" | 16.3 s, 15.9 s |
| `SELECT ai_query('uc_secrets_demo.secrets.litellm_via_apim', ...)` | open | `AI_FUNCTION_COMPILATION_ERROR`: "ai_query through UC Model Services is not enabled" | 1.2 s |
| `SELECT ai_query('litellm_via_apim', ...)` | open | `AI_FUNCTION_COMPILATION_ERROR`: "'litellm_via_apim' does not exist or is not accessible" | 78.7 s |

What it proves:

- **The warehouse's lane is the Unity Catalog service's lane.** A `SECRETS`-clause UDF created and executed on the warehouse returned both secrets open and
  locked, and failed sealed, exactly as `dbutils.secrets.get` did on serverless and classic compute. The fetch is made by Unity Catalog with the access
  connector identity, not by the warehouse; the warehouse's own network is irrelevant to it, and the NCC endpoint bound to this workspace plays no part.
- **The sealed refusal reaches SQL as `UDF_ERROR.INTERNAL_UNKNOWN`,** the same opaque class the session-scoped UDF produced for a missing `READ SECRET`
  (`RESULTS.md`, C1). Nothing in the SQL error says "Key Vault refused the service credential"; the Unity Catalog REST read made at the same moment does.
- **There is no `secret()` for Unity Catalog secrets.** The function is the legacy-scope one, two arguments, and a schema name is not a scope.
- **`ai_query` knows about model provider services but the feature is gated here:** the full name is answered with "ai_query through UC Model Services is not
  enabled" (a capability that exists and is switched off on this workspace), the short name with "does not exist or is not accessible" after 78.7 s.

Driver log ([`measurements/sql_lane.py`](../measurements/sql_lane.py), the orchestration; statements and vault flips as above):

```text
[09:57:50] pre-check posture: {"bypass": null, "deny": null, "public": "Enabled"}
[09:58:02] S0_warehouse: SUCCEEDED in 10.4 s -> ['me', 'dbsql_version', 'metastore'] [['<user>', '2026.42', 'azure:westeurope:<metastore-id>']]
[09:58:04] S0_schema: SUCCEEDED in 1.7 s -> [] None
[09:58:06] S1_legacy_secret_fn: SUCCEEDED in 1.6 s -> ['len', 'sha256_prefix'] [['23', '<secret-sha256-prefix-2>']]
[09:58:06] S2a_secret_fn_3_part_name: FAILED in 0.6 s -> BAD_REQUEST: [WRONG_NUM_ARGS.WITHOUT_SUGGESTION] The `secret` requires 2 parameters but the actual number is 1. Please, refer to 'https://spark.apache.org/docs/latest/sql-ref-functions.html' for a fix. SQLSTATE: 42605; line 1 pos 17
[09:58:07] S2b_secret_fn_3_args: FAILED in 0.9 s -> BAD_REQUEST: [WRONG_NUM_ARGS.WITHOUT_SUGGESTION] The `secret` requires 2 parameters but the actual number is 3. Please, refer to 'https://spark.apache.org/docs/latest/sql-ref-functions.html' for a fix. SQLSTATE: 42605; line 1 pos 17
[09:58:08] S2c_secret_fn_schema_as_scope: FAILED in 0.7 s -> BAD_REQUEST: [INVALID_SECRET_LOOKUP.SECRET_FUNCTION_LOOKUP_FAILED] Invalid secret lookup: The SECRET function failed to find a secret with scope uc_secrets_demo.secrets and key dummysecret: java.lang.IllegalArgumentException: Secret does not exist with scope: uc_secrets_demo.secrets and key: dummysecret SQLSTATE
[09:58:26] S3_create_udf_dummysecret: SUCCEEDED in 17.6 s -> [] None
[09:58:27] S3_create_udf_apimlanekey: SUCCEEDED in 1.5 s -> [] None
[09:58:54] S4_udf_open: SUCCEEDED in 26.9 s -> ['dummy_len_sha', 'real_len_sha'] [['20:<dummy-sha256-prefix>', '64:<secret-sha256-prefix-1>']]
[09:59:05] S4_udf_open_again: SUCCEEDED in 10.9 s -> ['dummy_len_sha', 'real_len_sha'] [['20:<dummy-sha256-prefix>', '64:<secret-sha256-prefix-1>']]
[09:59:05] LOCKED: public Disabled, default Deny, bypass AzureServices
[09:59:12] posture now: {"bypass": "AzureServices", "deny": "Deny", "public": "Disabled"}
[09:59:12] direct read with my identity refused after 0.6 s: enforcement is live
[09:59:22] S5_udf_locked: SUCCEEDED in 10.2 s -> ['dummy_len_sha', 'real_len_sha'] [['20:<dummy-sha256-prefix>', '64:<secret-sha256-prefix-1>']]
[09:59:32] S5_udf_locked_again: SUCCEEDED in 9.7 s -> ['dummy_len_sha', 'real_len_sha'] [['20:<dummy-sha256-prefix>', '64:<secret-sha256-prefix-1>']]
[09:59:32] SEALED: public Disabled, default Deny, bypass None
[09:59:34] posture now: {"bypass": "None", "deny": "Deny", "public": "Disabled"}
[09:59:35] direct read with my identity refused after 0.4 s: enforcement is live
[09:59:51] S6_udf_sealed: FAILED in 16.3 s -> BAD_REQUEST: [UDF_ERROR.INTERNAL_UNKNOWN] Execution of function uc_secrets_demo.sql_lane.dummy_secret_sha failed  due to an unknown error. Please contact Databricks support. SQLSTATE: 39000
[10:00:07] S6_udf_sealed_again: FAILED in 15.9 s -> BAD_REQUEST: [UDF_ERROR.INTERNAL_UNKNOWN] Execution of function uc_secrets_demo.sql_lane.dummy_secret_sha failed  due to an unknown error. Please contact Databricks support. SQLSTATE: 39000
[10:00:07] RESTORE: reopening the vault
[10:00:10] restored posture: {"bypass": null, "deny": null, "public": "Enabled"}
[10:00:12] UC read after restore: ok, value present
[10:00:13] S7_ai_query_provider_service: FAILED in 1.2 s -> BAD_REQUEST: [AI_FUNCTION_COMPILATION_ERROR] An error occurred while compiling the AI function: INVALID_ARGUMENT: ai_query through UC Model Services is not enabled. SQLSTATE: 42883; line 1 pos 7
[10:01:32] S7_ai_query_short_name: FAILED in 78.7 s -> BAD_REQUEST: [AI_FUNCTION_COMPILATION_ERROR] An error occurred while compiling the AI function: INVALID_ARGUMENT: 'litellm_via_apim' does not exist or is not accessible. SQLSTATE: 42883; line 1 pos 7
[10:01:32] CLEANUP: dropping the throwaway functions and schema
[10:01:33] cleanup: SUCCEEDED in 1.0 s -> [] None
[10:01:34] cleanup: SUCCEEDED in 0.8 s -> [] None
[10:01:35] cleanup: SUCCEEDED in 1.7 s -> [] None
[10:01:35] done; results in <scratch>/sql_lane/results.json
exit 0
```

## Network Security Perimeter (phase 7, rows 15 to 20)

An Azure Network Security Perimeter (NSP) is a boundary drawn around PaaS resources. A resource associated with it gets its public inbound traffic
decided by the perimeter's rules instead of its own firewall once the association is in Enforced mode; in Learning mode (the portal calls it
Transition) the resource's own firewall keeps deciding and the perimeter only logs what Enforced would do. Microsoft's Key Vault documentation
says that in Enforced mode "even trusted services are blocked unless an explicit perimeter access rule admits them" and that "private endpoint
traffic isn't subject to Network Security Perimeter rules". Both sentences describe exactly the two lanes this matrix cares about: the trusted-service
admission that carries Unity Catalog's fetch, and the NCC private endpoint that carries serverless's own calls. `nsp.tf` creates the perimeter, a
profile and the vault's association in Learning mode; the driver switched the modes and created the rule with the Azure CLI, so Terraform never saw the
intermediate states, and its closing `terraform plan` reported no changes.

What each lane did in the three states, with the vault open (`publicNetworkAccess: Enabled`, no network rules) in all of them:

| Lane | Learning (rows 15, 16, laptop) | Enforced, no rule (rows 17, 18, L5) | Enforced + subscription rule (rows 19, 20, L6) |
| --- | --- | --- | --- |
| UC read (`dbutils`, REST, real credential) from serverless, classic and the laptop | value ok | **refused**: `PERMISSION_DENIED`, "the cloud provider returned access denied" | value ok |
| Unity Gateway | bearer accepted by APIM (upstream 500 after about 231 s) | **`403 PERMISSION_DENIED`** in 1.3 s (serverless) and 0.8 s (classic) | bearer accepted by APIM |
| Connector token, serverless (through the NCC private endpoint) | `200` | **`200`**: private endpoint traffic is not evaluated by the perimeter | `200` |
| Connector token, classic (over the subnet's service endpoint) | `200` | **`403 ForbiddenByNsp`**, "Client address: 0.0.0.0" | `200`, admitted by the rule |
| Connector token, laptop (public internet) | `200` | **`403 ForbiddenByNsp`**, "Client address: `<laptop-ip>`" | `200`, admitted by the rule |
| The user's own identity, laptop | ok | **`Forbidden`**, "Request was not allowed by NSP rules" | **still refused** |
| Compute direct, no token | `401` challenge | `401` challenge | `401` challenge |
| Compute DNS | serverless: private endpoint address; classic: public | unchanged | unchanged |

Timing: the switch to Enforced took effect within one second of the API call returning (the call itself took 35 s), the rule within six seconds, and
the restore within one second. The `403` from the vault names the perimeter as the reason (`innererror.code: ForbiddenByNsp`), the client address the
vault saw, and the caller it attributed the request to (`name=microsoft.databricks/accessconnectors;appid=...;oid=...` for the connector token).

### The perimeter's access log

The perimeter sends one row per decision to Log Analytics (`NSPAccessLogs`; `scripts/smoke_test.sh perimeter` queries it). Each row names the
source address, the traffic type, the decision, the rule that decided, and the resource the request is attributed to (`SourceResourceId`). Rows in
the three windows, grouped:

| State (UTC) | Source as logged | Attributed to | Rows | Decision, rule |
| --- | --- | --- | --- | --- |
| Learning, 14:44:11 to 14:57:34 | public, `<public-ip-1>` (a Databricks control-plane address: Unity Catalog's fetch and its listings) | the access connector | 12 | Allowed, `DefaultAllowAll` (`RuleType: Resource`, the vault's own rules) |
| | public, `<laptop-ip>`, connector token | the access connector | 2 | Allowed, `DefaultAllowAll` |
| | public, `<laptop-ip>`, the user's identity | nothing | 2 | Allowed, `DefaultAllowAll` |
| | private, no address (serverless through the NCC endpoint) | the access connector | 1 | Allowed, `NspPrivateInboundAllowed` |
| | public, no address (classic over the subnet's service endpoint) | the access connector | 1 | Allowed, `EvaluatedSEPolicy` |
| Enforced, no rule, 14:58:09 to 15:02:25 | public, `<public-ip-1>` | the access connector | 22 (`SecretGet`, `SecretList`, `SecretListVersions`: the service retried and tried other operations after the denial) | **Denied**, `DefaultDenyAll` (`RuleType: NSP`) |
| | public, `<laptop-ip>`, connector token | the access connector | 2 | **Denied**, `DefaultDenyAll` |
| | public, `<laptop-ip>`, the user's identity | nothing | 4 | **Denied**, `DefaultDenyAll` |
| | private (serverless, NCC endpoint) | the access connector | 1 | Allowed, `NspPrivateInboundAllowed` |
| | public, no address (classic, service endpoint) | the access connector | 1 | **Denied**, `DefaultDenyAll` |
| Enforced + rule, 15:02:25 to 15:11:23 | public, `<public-ip-1>` | the access connector | 16 | Allowed, `admit-connector-subscription` |
| | the same, at 15:02:25 and 15:02:26, before the rule was in force | the access connector | 2 | Denied, `DefaultDenyAll` |
| | public, `<laptop-ip>`, connector token | the access connector | 2 | Allowed, `admit-connector-subscription` |
| | public, `<laptop-ip>`, the user's identity | nothing | 2 | **Denied**, `DefaultDenyAll` |
| | private (serverless, NCC endpoint) | the access connector | 1 | Allowed, `NspPrivateInboundAllowed` |
| | public, no address (classic, service endpoint) | the access connector | 1 | Allowed, `admit-connector-subscription` |

Three things in that log settle questions the earlier phases could only infer. Unity Catalog's fetch arrives at the vault from a Databricks
control-plane address with the connector's identity (the vault's own audit log adds the client: `azsdk-java-azure-security-keyvault-secrets`, with the
identity's object id), so "the Unity Catalog service does the fetch" is now logged, not deduced. The perimeter attributes a request to a resource by the
identity on it: every call that carried the connector's token, from the control plane, from the laptop, through the private endpoint or over the
service endpoint, was attributed to the access connector, and the user's own calls to nothing. And the subscription rule matched on that attribution,
which is why the laptop was admitted with the token and refused without it.

### The vault's own audit log

With `diagnostics.tf` applied, the vault's `AuditEvent` log (`AzureDiagnostics`; `scripts/smoke_test.sh callers`) was read for the same windows at
15:19 UTC, eight minutes after the restore, when rows from after the restore had already arrived (`_TimeReceived` up to 15:15:22). In Learning mode it
shows every lane with its caller: Unity Catalog's ten `SecretGet` calls (plus a `SecretList` and a `SecretListDeleted`) from `<public-ip-1>` with client
`azsdk-java-azure-security-keyvault-secrets` and the identity's object id `<connector-oid>`; the laptop's two `curl` reads with the same identity and the
user's two `az` reads from `<laptop-ip>`; serverless's read through the NCC endpoint from `<serverless-private-ip-a>`, a private address of the serverless network
rather than the driver's; and the classic cluster's read with caller address `0.0.0.0`, the way the vault logs service-endpoint traffic. While the
association was Enforced, from 14:58:09 to 15:11:23, the same log recorded no authenticated data-plane call at all, neither the 29 requests the
perimeter denied in the no-rule window nor the 20 it admitted in the rule window: only five anonymous `Authentication` challenges and the perimeter's own
`PutNetworkSecurityPerimeterAssociationProxy` and `ListNetworkSecurityPerimeterConfiguration` operations from an Azure address. From 15:11:25 the log
fills again with the restore's Unity Catalog read and the `terraform plan` refresh. So while a perimeter enforces, its access log is the only record of
who reached the vault; the vault's own audit trail has a hole for the whole window. Whether that is by design or an ingestion artefact is not settled
here; the rows after the restore arriving within four minutes argue against a lag.

What it means for the enterprise question: a perimeter in Enforced mode with no inbound rule is the only posture in this matrix that stops Unity
Catalog's fetch while the vault's own firewall is open, and it stops the minted token on every public path at the same time, so it is a real control
over answer 4's "from any network", at the price of Unity Catalog not working at all. The moment an inbound rule admits the connector's subscription,
Unity Catalog works again and so does the token from anywhere. There is no perimeter rule in between that admits the Unity Catalog service and not a
laptop presenting the same identity, because the perimeter does not see a difference between them.

## Perimeter log (phase 7)

The orchestration's log (`measurements/nsp_perimeter.sh`), unedited apart from the placeholders. The connector token minted on the laptop is used in
one call and never printed; the exit JSON lines are the driver's own 220-character summaries of each run.

```text
[14:44:11] pre-check: vault {"bypass":null,"deny":null,"public":"Enabled"}, perimeter nsp-uc-secrets-demo mode Learning, rules []
[14:44:17] P1: submitted serverless run <run-or-timestamp-id> and classic run <run-or-timestamp-id>
[14:44:17] laptop control: UC REST read: ok, value present
[14:44:18] laptop control: laptop, connector token: 200 value sha256 <dummy-sha256-prefix>
[14:44:19] laptop control: own identity: https://kv-ucsec-<workspace-id>.vault.azure.net/secrets/dummysecret/8a2075a9c1cb4f73a9b451a164241526 
[14:48:53] run <run-or-timestamp-id>: TERMINATED SUCCESS
[14:57:28] run <run-or-timestamp-id>: TERMINATED SUCCESS
[14:57:29] laptop control: UC REST read: ok, value present
[14:57:29] laptop control: laptop, connector token: 200 value sha256 <dummy-sha256-prefix>
[14:57:29] laptop control: own identity: https://kv-ucsec-<workspace-id>.vault.azure.net/secrets/dummysecret/8a2075a9c1cb4f73a9b451a164241526 
[14:57:32] run <run-or-timestamp-id> task <run-or-timestamp-id> exit JSON:
  W1_workspace: workspace <workspace-id>  {"host": "https://adb-<workspace-id>.14.azuredatabricks.net", "sdk_host": "https://adb-<workspace-id>.14.azuredatabricks.net"}
  W2_metastore: metastore_azure_westeurope (westeurope)  {"metastore_id": "<metastore-id>", "cloud": "azure"}
  W3_compute: serverless  {"DATABRICKS_RUNTIME_VERSION": "client.6.5", "DATABRICKS_ENV_VERSION": "6", "spark": "4.2.0", "driver_ip": "<private-ip-2>", "driver_ip_rfc1918": true}
  W4_caller: <user>  {"workspace_admin": true}
  C1_catalog: visible, isolation OPEN  {"metastore_id": "<metastore-id>"}
  C2_catalog_bindings: 0 workspace binding(s)  {"bindings": []}
  C3_secret_listing: 2 secret(s)  {"secrets": ["uc_secrets_demo.secrets.apimlanekey", "uc_secrets_demo.secrets.dummysecret"]}
  C4_connection: AZURE_KEY_VAULT -> vault kv-ucsec-<workspace-id>  {"credential": "uc_secrets_demo"}
  C5_credential: SERVICE credential, isolation ISOLATION_MODE_OPEN  {"access_connector_id": "/subscriptions/<subscription-id>/resourceGroups/rg-uc-secrets-demo/providers/Microsoft.Databricks/accessConnectors/dbac-uc-secrets-demo", "managed_identity_id": "/subscriptions
  L1_uc_read_dbutils: value ok  {"length": 20, "sha256_prefix": "<dummy-sha256-prefix>"}
  L1_uc_read_rest: value ok  {"length": 20, "sha256_prefix": "<dummy-sha256-prefix>"}
  L1_uc_read_real_hash: value ok  {"length": 64, "sha256_prefix": "<secret-sha256-prefix-1>"}
  L2_compute_dns: private endpoint address  {"canonical": "kv-ucsec-<workspace-id>.vault.azure.net", "aliases": [], "addresses": {"<ncc-private-endpoint-ip>": "private (RFC 1918)", "::ffff:<ncc-private-endpoint-ip>": "private (RFC 1918)"}}
  L3_compute_unauth: HTTP 401 challenge: the vault answered this compute  {"http_status": 401, "www_authenticate_present": true, "www_authenticate_scheme": "Bearer", "error_code": "Unauthorized", "message": "AKV10000: Request is missing a Bearer, PoP, or MTLS_POP token."}
  L4_compute_connector_token: HTTP 200: value ok  {"token_identity": {"oid": "<connector-oid>", "appid": "<connector-appid>", "idtyp": "app", "xms_mirid": "/subscriptions/<subscription-id>/resourceGroups/rg-uc-s
  L5_gateway: bearer accepted by APIM; the upstream model failed (upstream_status 500)  {"http_status": 502, "error_code": "INTERNAL_ERROR", "upstream_status": 500, "elapsed_s": 231.3, "message": "Model Provider Service returned error with status code 500: Internal server error. The model provider returned 
[14:57:34] run <run-or-timestamp-id> task <run-or-timestamp-id> exit JSON:
  W1_workspace: workspace <workspace-id>  {"host": "https://adb-<workspace-id>.14.azuredatabricks.net", "sdk_host": "<regional-control-plane-host>"}
  W2_metastore: metastore_azure_westeurope (westeurope)  {"metastore_id": "<metastore-id>", "cloud": "azure"}
  W3_compute: classic  {"DATABRICKS_RUNTIME_VERSION": "18.3", "DATABRICKS_ENV_VERSION": null, "spark": "4.1.0", "cluster_id": "<cluster-id>", "node_type": "Standard_F4s_v2", "spark_version": "18.x-scala2.13", "driver_ip": "<classic-node-ip>",
  W4_caller: <user>  {"workspace_admin": true}
  C1_catalog: visible, isolation OPEN  {"metastore_id": "<metastore-id>"}
  C2_catalog_bindings: 0 workspace binding(s)  {"bindings": []}
  C3_secret_listing: 2 secret(s)  {"secrets": ["uc_secrets_demo.secrets.apimlanekey", "uc_secrets_demo.secrets.dummysecret"]}
  C4_connection: AZURE_KEY_VAULT -> vault kv-ucsec-<workspace-id>  {"credential": "uc_secrets_demo"}
  C5_credential: SERVICE credential, isolation ISOLATION_MODE_OPEN  {"access_connector_id": "/subscriptions/<subscription-id>/resourceGroups/rg-uc-secrets-demo/providers/Microsoft.Databricks/accessConnectors/dbac-uc-secrets-demo", "managed_identity_id": "/subscriptions
  L1_uc_read_dbutils: value ok  {"length": 20, "sha256_prefix": "<dummy-sha256-prefix>"}
  L1_uc_read_rest: value ok  {"length": 20, "sha256_prefix": "<dummy-sha256-prefix>"}
  L1_uc_read_real_hash: value ok  {"length": 64, "sha256_prefix": "<secret-sha256-prefix-1>"}
  L2_compute_dns: public address  {"canonical": "<kv-akadns-canonical>", "aliases": ["kv-ucsec-<workspace-id>.vault.azure.net", "kv-ucsec-<workspace-id>.privatelink.vaultcore.azure.net", "<kv-weu-alias-2>", "data-prod-weu-reg
  L3_compute_unauth: HTTP 401 challenge: the vault answered this compute  {"http_status": 401, "www_authenticate_present": true, "www_authenticate_scheme": "Bearer", "error_code": "Unauthorized", "message": "AKV10000: Request is missing a Bearer, PoP, or MTLS_POP token."}
  L4_compute_connector_token: HTTP 200: value ok  {"token_identity": {"oid": "<connector-oid>", "appid": "<connector-appid>", "idtyp": "app", "xms_mirid": "/subscriptions/<subscription-id>/resourceGroups/rg-uc-s
  L5_gateway: bearer accepted by APIM; the upstream model failed (upstream_status 500)  {"http_status": 502, "error_code": "INTERNAL_ERROR", "upstream_status": 500, "elapsed_s": 230.9, "message": "Model Provider Service returned error with status code 500: Internal server error. The model provider returned 
[14:57:34] P2: switching the association to Enforced
[14:58:09] mode now Enforced; vault still {"bypass":null,"deny":null,"public":"Enabled"}
[14:58:10] own identity read refused (enforcement live) after 1 s
[14:58:10] own identity read after Enforced: ERROR: (Forbidden) Request was not allowed by NSP rules. 
 Client address: <laptop-ip>
 Caller: appid=<request-or-resource-id>;oid=<user-oid>
 Vault: kv-ucsec-<workspace-id>;location=westeurope Code: Forbidden Message: Request was not allowed by NSP rules. 
[14:58:12] P2: submitted serverless run <run-or-timestamp-id> and classic run <run-or-timestamp-id>
[14:58:13] laptop control: UC REST read: Error: the cloud provider returned access denied, check the configuration of the service credential
[14:58:13] laptop control: laptop, connector token: {'error': {'code': 'Forbidden', 'message': 'Request was not allowed by NSP rules. \r\nClient address: <laptop-ip>\r\nCaller: name=microsoft.databricks/accessconnectors;appid=<connector-appid>;oid=<connector-oid>\r\nVault: kv-ucsec-<workspace-id>;location=westeurope', 'innererror': {'code': 'ForbiddenByNsp'}}}
[14:58:14] laptop control: own identity: ERROR: (Forbidden) Request was not allowed by NSP rules. 
 Client address: <laptop-ip>
 Caller: appid=<request-or-resource-id>;oid=<user-oid>
 Vault: kv-ucsec-
[14:58:44] run <run-or-timestamp-id>: TERMINATED SUCCESS
[15:02:17] run <run-or-timestamp-id>: TERMINATED SUCCESS
[15:02:17] laptop control: UC REST read: Error: the cloud provider returned access denied, check the configuration of the service credential
[15:02:18] laptop control: laptop, connector token: {'error': {'code': 'Forbidden', 'message': 'Request was not allowed by NSP rules. \r\nClient address: <laptop-ip>\r\nCaller: name=microsoft.databricks/accessconnectors;appid=<connector-appid>;oid=<connector-oid>\r\nVault: kv-ucsec-<workspace-id>;location=westeurope', 'innererror': {'code': 'ForbiddenByNsp'}}}
[15:02:18] laptop control: own identity: ERROR: (Forbidden) Request was not allowed by NSP rules. 
 Client address: <laptop-ip>
 Caller: appid=<request-or-resource-id>;oid=<user-oid>
 Vault: kv-ucsec-
[15:02:21] run <run-or-timestamp-id> task <run-or-timestamp-id> exit JSON:
  W1_workspace: workspace <workspace-id>  {"host": "https://adb-<workspace-id>.14.azuredatabricks.net", "sdk_host": "https://adb-<workspace-id>.14.azuredatabricks.net"}
  W2_metastore: metastore_azure_westeurope (westeurope)  {"metastore_id": "<metastore-id>", "cloud": "azure"}
  W3_compute: serverless  {"DATABRICKS_RUNTIME_VERSION": "client.6.5", "DATABRICKS_ENV_VERSION": "6", "spark": "4.2.0", "driver_ip": "<private-ip-2>", "driver_ip_rfc1918": true}
  W4_caller: <user>  {"workspace_admin": true}
  C1_catalog: visible, isolation OPEN  {"metastore_id": "<metastore-id>"}
  C2_catalog_bindings: 0 workspace binding(s)  {"bindings": []}
  C3_secret_listing: 2 secret(s)  {"secrets": ["uc_secrets_demo.secrets.apimlanekey", "uc_secrets_demo.secrets.dummysecret"]}
  C4_connection: AZURE_KEY_VAULT -> vault kv-ucsec-<workspace-id>  {"credential": "uc_secrets_demo"}
  C5_credential: SERVICE credential, isolation ISOLATION_MODE_OPEN  {"access_connector_id": "/subscriptions/<subscription-id>/resourceGroups/rg-uc-secrets-demo/providers/Microsoft.Databricks/accessConnectors/dbac-uc-secrets-demo", "managed_identity_id": "/subscriptions
  L1_uc_read_dbutils: Key Vault refused the service credential  {"exception": "py4j.protocol.Py4JJavaError", "message": ": com.databricks.backend.daemon.driver.repl.ManagedCatalogServiceException: PERMISSION_DENIED: the cloud provider returned access denied, check the configuration o
  L1_uc_read_rest: refused (HTTP 403 PERMISSION_DENIED)  {"http_status": 403, "error_code": "PERMISSION_DENIED", "message": "the cloud provider returned access denied, check the configuration of the service credential"}
  L1_uc_read_real_hash: Key Vault refused the service credential  {"exception": "py4j.protocol.Py4JJavaError", "message": ": com.databricks.backend.daemon.driver.repl.ManagedCatalogServiceException: PERMISSION_DENIED: the cloud provider returned access denied, check the configuration o
  L2_compute_dns: private endpoint address  {"canonical": "kv-ucsec-<workspace-id>.vault.azure.net", "aliases": [], "addresses": {"<ncc-private-endpoint-ip>": "private (RFC 1918)", "::ffff:<ncc-private-endpoint-ip>": "private (RFC 1918)"}}
  L3_compute_unauth: HTTP 401 challenge: the vault answered this compute  {"http_status": 401, "www_authenticate_present": true, "www_authenticate_scheme": "Bearer", "error_code": "Unauthorized", "message": "AKV10000: Request is missing a Bearer, PoP, or MTLS_POP token."}
  L4_compute_connector_token: HTTP 200: value ok  {"token_identity": {"oid": "<connector-oid>", "appid": "<connector-appid>", "idtyp": "app", "xms_mirid": "/subscriptions/<subscription-id>/resourceGroups/rg-uc-s
  L5_gateway: denied by Databricks (no EXECUTE, or the secret could not be resolved)  {"http_status": 403, "error_code": "PERMISSION_DENIED", "upstream_status": null, "elapsed_s": 1.3, "message": "the cloud provider returned access denied, check the configuration of the service credential"}
[15:02:23] run <run-or-timestamp-id> task <run-or-timestamp-id> exit JSON:
  W1_workspace: workspace <workspace-id>  {"host": "https://adb-<workspace-id>.14.azuredatabricks.net", "sdk_host": "<regional-control-plane-host>"}
  W2_metastore: metastore_azure_westeurope (westeurope)  {"metastore_id": "<metastore-id>", "cloud": "azure"}
  W3_compute: classic  {"DATABRICKS_RUNTIME_VERSION": "18.3", "DATABRICKS_ENV_VERSION": null, "spark": "4.1.0", "cluster_id": "<cluster-id>", "node_type": "Standard_F4s_v2", "spark_version": "18.x-scala2.13", "driver_ip": "<classic-node-ip>",
  W4_caller: <user>  {"workspace_admin": true}
  C1_catalog: visible, isolation OPEN  {"metastore_id": "<metastore-id>"}
  C2_catalog_bindings: 0 workspace binding(s)  {"bindings": []}
  C3_secret_listing: 2 secret(s)  {"secrets": ["uc_secrets_demo.secrets.apimlanekey", "uc_secrets_demo.secrets.dummysecret"]}
  C4_connection: AZURE_KEY_VAULT -> vault kv-ucsec-<workspace-id>  {"credential": "uc_secrets_demo"}
  C5_credential: SERVICE credential, isolation ISOLATION_MODE_OPEN  {"access_connector_id": "/subscriptions/<subscription-id>/resourceGroups/rg-uc-secrets-demo/providers/Microsoft.Databricks/accessConnectors/dbac-uc-secrets-demo", "managed_identity_id": "/subscriptions
  L1_uc_read_dbutils: Key Vault refused the service credential  {"exception": "py4j.protocol.Py4JJavaError", "message": ": com.databricks.sql.managedcatalog.acl.UnauthorizedAccessException: PERMISSION_DENIED: the cloud provider returned access denied, check the configuration of the s
  L1_uc_read_rest: refused (HTTP 403 PERMISSION_DENIED)  {"http_status": 403, "error_code": "PERMISSION_DENIED", "message": "the cloud provider returned access denied, check the configuration of the service credential"}
  L1_uc_read_real_hash: Key Vault refused the service credential  {"exception": "py4j.protocol.Py4JJavaError", "message": ": com.databricks.sql.managedcatalog.acl.UnauthorizedAccessException: PERMISSION_DENIED: the cloud provider returned access denied, check the configuration of the s
  L2_compute_dns: public address  {"canonical": "<kv-traffic-manager-canonical>", "aliases": ["kv-ucsec-<workspace-id>.vault.azure.net", "kv-ucsec-<workspace-id>.privatelink.vaultcore.azure.net", "<kv-weu-alias-2>", "data-prod
  L3_compute_unauth: HTTP 401 challenge: the vault answered this compute  {"http_status": 401, "www_authenticate_present": true, "www_authenticate_scheme": "Bearer", "error_code": "Unauthorized", "message": "AKV10000: Request is missing a Bearer, PoP, or MTLS_POP token."}
  L4_compute_connector_token: HTTP 403 Forbidden  {"token_identity": {"oid": "<connector-oid>", "appid": "<connector-appid>", "idtyp": "app", "xms_mirid": "/subscriptions/<subscription-id>/resourceGroups/rg-uc-s
  L5_gateway: denied by Databricks (no EXECUTE, or the secret could not be resolved)  {"http_status": 403, "error_code": "PERMISSION_DENIED", "upstream_status": null, "elapsed_s": 0.8, "message": "the cloud provider returned access denied, check the configuration of the service credential"}
[15:02:23] P3: adding the inbound subscription rule for the connector identity's subscription
[15:02:25] rules now ["admit-connector-subscription"]
[15:02:31] UC read admitted by the rule after 6 s
[15:02:31] UC read after the rule: ok, value present
[15:02:34] P3: submitted serverless run <run-or-timestamp-id> and classic run <run-or-timestamp-id>
[15:02:34] laptop control: UC REST read: ok, value present
[15:02:35] laptop control: laptop, connector token: 200 value sha256 <dummy-sha256-prefix>
[15:02:35] laptop control: own identity: ERROR: (Forbidden) Request was not allowed by NSP rules. 
 Client address: <laptop-ip>
 Caller: appid=<request-or-resource-id>;oid=<user-oid>
 Vault: kv-ucsec-
[15:07:08] run <run-or-timestamp-id>: TERMINATED SUCCESS
[15:10:41] run <run-or-timestamp-id>: TERMINATED SUCCESS
[15:10:41] laptop control: UC REST read: ok, value present
[15:10:42] laptop control: laptop, connector token: 200 value sha256 <dummy-sha256-prefix>
[15:10:42] laptop control: own identity: ERROR: (Forbidden) Request was not allowed by NSP rules. 
 Client address: <laptop-ip>
 Caller: appid=<request-or-resource-id>;oid=<user-oid>
 Vault: kv-ucsec-
[15:10:45] run <run-or-timestamp-id> task <run-or-timestamp-id> exit JSON:
  W1_workspace: workspace <workspace-id>  {"host": "https://adb-<workspace-id>.14.azuredatabricks.net", "sdk_host": "https://adb-<workspace-id>.14.azuredatabricks.net"}
  W2_metastore: metastore_azure_westeurope (westeurope)  {"metastore_id": "<metastore-id>", "cloud": "azure"}
  W3_compute: serverless  {"DATABRICKS_RUNTIME_VERSION": "client.6.5", "DATABRICKS_ENV_VERSION": "6", "spark": "4.2.0", "driver_ip": "<private-ip-2>", "driver_ip_rfc1918": true}
  W4_caller: <user>  {"workspace_admin": true}
  C1_catalog: visible, isolation OPEN  {"metastore_id": "<metastore-id>"}
  C2_catalog_bindings: 0 workspace binding(s)  {"bindings": []}
  C3_secret_listing: 2 secret(s)  {"secrets": ["uc_secrets_demo.secrets.apimlanekey", "uc_secrets_demo.secrets.dummysecret"]}
  C4_connection: AZURE_KEY_VAULT -> vault kv-ucsec-<workspace-id>  {"credential": "uc_secrets_demo"}
  C5_credential: SERVICE credential, isolation ISOLATION_MODE_OPEN  {"access_connector_id": "/subscriptions/<subscription-id>/resourceGroups/rg-uc-secrets-demo/providers/Microsoft.Databricks/accessConnectors/dbac-uc-secrets-demo", "managed_identity_id": "/subscriptions
  L1_uc_read_dbutils: value ok  {"length": 20, "sha256_prefix": "<dummy-sha256-prefix>"}
  L1_uc_read_rest: value ok  {"length": 20, "sha256_prefix": "<dummy-sha256-prefix>"}
  L1_uc_read_real_hash: value ok  {"length": 64, "sha256_prefix": "<secret-sha256-prefix-1>"}
  L2_compute_dns: private endpoint address  {"canonical": "kv-ucsec-<workspace-id>.vault.azure.net", "aliases": [], "addresses": {"<ncc-private-endpoint-ip>": "private (RFC 1918)", "::ffff:<ncc-private-endpoint-ip>": "private (RFC 1918)"}}
  L3_compute_unauth: HTTP 401 challenge: the vault answered this compute  {"http_status": 401, "www_authenticate_present": true, "www_authenticate_scheme": "Bearer", "error_code": "Unauthorized", "message": "AKV10000: Request is missing a Bearer, PoP, or MTLS_POP token."}
  L4_compute_connector_token: HTTP 200: value ok  {"token_identity": {"oid": "<connector-oid>", "appid": "<connector-appid>", "idtyp": "app", "xms_mirid": "/subscriptions/<subscription-id>/resourceGroups/rg-uc-s
  L5_gateway: bearer accepted by APIM; the upstream model failed (upstream_status 500)  {"http_status": 502, "error_code": "INTERNAL_ERROR", "upstream_status": 500, "elapsed_s": 230.9, "message": "Model Provider Service returned error with status code 500: Internal server error. The model provider returned 
[15:10:47] run <run-or-timestamp-id> task <run-or-timestamp-id> exit JSON:
  W1_workspace: workspace <workspace-id>  {"host": "https://adb-<workspace-id>.14.azuredatabricks.net", "sdk_host": "<regional-control-plane-host>"}
  W2_metastore: metastore_azure_westeurope (westeurope)  {"metastore_id": "<metastore-id>", "cloud": "azure"}
  W3_compute: classic  {"DATABRICKS_RUNTIME_VERSION": "18.3", "DATABRICKS_ENV_VERSION": null, "spark": "4.1.0", "cluster_id": "<cluster-id>", "node_type": "Standard_F4s_v2", "spark_version": "18.x-scala2.13", "driver_ip": "<classic-node-ip>",
  W4_caller: <user>  {"workspace_admin": true}
  C1_catalog: visible, isolation OPEN  {"metastore_id": "<metastore-id>"}
  C2_catalog_bindings: 0 workspace binding(s)  {"bindings": []}
  C3_secret_listing: 2 secret(s)  {"secrets": ["uc_secrets_demo.secrets.apimlanekey", "uc_secrets_demo.secrets.dummysecret"]}
  C4_connection: AZURE_KEY_VAULT -> vault kv-ucsec-<workspace-id>  {"credential": "uc_secrets_demo"}
  C5_credential: SERVICE credential, isolation ISOLATION_MODE_OPEN  {"access_connector_id": "/subscriptions/<subscription-id>/resourceGroups/rg-uc-secrets-demo/providers/Microsoft.Databricks/accessConnectors/dbac-uc-secrets-demo", "managed_identity_id": "/subscriptions
  L1_uc_read_dbutils: value ok  {"length": 20, "sha256_prefix": "<dummy-sha256-prefix>"}
  L1_uc_read_rest: value ok  {"length": 20, "sha256_prefix": "<dummy-sha256-prefix>"}
  L1_uc_read_real_hash: value ok  {"length": 64, "sha256_prefix": "<secret-sha256-prefix-1>"}
  L2_compute_dns: public address  {"canonical": "<kv-akadns-canonical>", "aliases": ["kv-ucsec-<workspace-id>.vault.azure.net", "kv-ucsec-<workspace-id>.privatelink.vaultcore.azure.net", "<kv-weu-alias-2>", "data-prod-weu-reg
  L3_compute_unauth: HTTP 401 challenge: the vault answered this compute  {"http_status": 401, "www_authenticate_present": true, "www_authenticate_scheme": "Bearer", "error_code": "Unauthorized", "message": "AKV10000: Request is missing a Bearer, PoP, or MTLS_POP token."}
  L4_compute_connector_token: HTTP 200: value ok  {"token_identity": {"oid": "<connector-oid>", "appid": "<connector-appid>", "idtyp": "app", "xms_mirid": "/subscriptions/<subscription-id>/resourceGroups/rg-uc-s
  L5_gateway: bearer accepted by APIM; the upstream model failed (upstream_status 500)  {"http_status": 502, "error_code": "INTERNAL_ERROR", "upstream_status": 500, "elapsed_s": 230.8, "message": "Model Provider Service returned error with status code 500: Internal server error. The model provider returned 
[15:10:47] phase 5 measurements done
[15:10:47] RESTORE: perimeter back to Learning, rule removed
[15:11:23] restored: mode Learning, rules [], vault {"bypass":null,"deny":null,"public":"Enabled"}
[15:11:24] own identity read admitted again after 1 s
[15:11:24] own identity read after restore: https://kv-ucsec-<workspace-id>.vault.azure.net/secrets/dummysecret/8a2075a9c1cb4f73a9b451a164241526 
[15:11:25] UC read after restore: ok, value present
[15:11:25] terraform plan after restore (expect no changes):
No changes. Your infrastructure matches the configuration.
```

## Vault posture log (phase 2)

Lock, enforcement check and the full text of the refusal the user's identity got (`phase2_lock`), then the restore and its verification:

```text
lock start 20:35:53
{
  "acls": {
    "bypass": "AzureServices",
    "defaultAction": "Deny",
    "ipRules": [],
    "virtualNetworkRules": []
  },
  "public": "Disabled"
}
lock applied 20:35:55
enforced after 0 s, attempt 1, 20:35:55 (first direct read with the user's identity refused)
laptop az (user identity), 2026-10-29 20:36:09 UTC
ERROR: (Forbidden) Public network access is disabled and request is not from a trusted service nor via an approved private link.
Caller: appid=<request-or-resource-id>;oid=<user-oid>;iss=<entra-issuer>
Vault: kv-ucsec-<workspace-id>;location=westeurope
Code: Forbidden
Message: Public network access is disabled and request is not from a trusted service nor via an approved private link.
```

```text
restore start 20:48:29
{
  "acls": null,
  "public": "Enabled"
}
restore applied 20:48:30
{
  "acls": null,
  "pe": null,
  "public": "Enabled"
}
```

`az keyvault show` after the restore: `publicNetworkAccess: Enabled`, `networkAcls: null`, no private endpoint connections. That is the open posture phase 1 started from.

## Vault posture log (phase 3)

The orchestration's log, unedited apart from the placeholders. The connector token minted on the laptop is used in one call and never printed.

```text
[21:02:58] pre-check posture: {"bypass":null,"deny":null,"public":"Enabled"}
[21:02:59] ncc rule: {"connection_state":"ESTABLISHED","endpoint_name":"databricks-<ncc-id>-pe-<endpoint-suffix>","network_connectivity_config_id":"<ncc-id>","rule_id":"<ncc-rule-id>"}
[21:03:00] waiting 465 s for the documented ten-minute propagation window
[21:10:45] SEAL: public Disabled, default Deny, bypass None
[21:10:48] sealed posture: {"bypass":"None","deny":"Deny","public":"Disabled"}
[21:10:49] direct read with my identity refused after 1 s: enforcement is live
[21:10:49] UC read from the laptop (control plane fetch) while sealed:
Error: the cloud provider returned access denied, check the configuration of the service credential

[21:10:50] connector token from the laptop while sealed (bypass None, no private link from here):
laptop, connector token: {'error': {'code': 'Forbidden', 'message': "Connection is not an approved private link and caller was ignored because bypass is not set to 'AzureServices' and PublicNetworkAccess is set to 'Disabled'. \r\nVault: kv-ucsec-<workspace-id>;location=westeurope", 'innererror': {'code': 'ForbiddenByConnection'}}}
[21:10:52] submitted serverless run <run-or-timestamp-id> and classic run <run-or-timestamp-id>
[21:11:23] run <run-or-timestamp-id>: TERMINATED SUCCESS
[21:21:31] run <run-or-timestamp-id>: TERMINATED SUCCESS
[21:21:31] UC read from the laptop again, still sealed:
Error: the cloud provider returned access denied, check the configuration of the service credential

[21:21:34] run <run-or-timestamp-id> task <run-or-timestamp-id> exit JSON:
  W1_workspace: workspace <workspace-id>  {"host": "https://adb-<workspace-id>.14.azuredatabricks.net", "sdk_host": "https://adb-<workspace-id>.14.azuredatabricks.net"}
  W2_metastore: metastore_azure_westeurope (westeurope)  {"metastore_id": "<metastore-id>", "cloud": "azure"}
  W3_compute: serverless  {"DATABRICKS_RUNTIME_VERSION": "client.6.5", "DATABRICKS_ENV_VERSION": "6", "spark": "4.2.0", "driver_ip": "<private-ip-2>", "driver_ip_rfc1918": true}
  W4_caller: <user>  {"workspace_admin": true}
  C1_catalog: visible, isolation OPEN  {"metastore_id": "<metastore-id>"}
  C2_catalog_bindings: 0 workspace binding(s)  {"bindings": []}
  C3_secret_listing: 2 secret(s)  {"secrets": ["uc_secrets_demo.secrets.apimlanekey", "uc_secrets_demo.secrets.dummysecret"]}
  C4_connection: AZURE_KEY_VAULT -> vault kv-ucsec-<workspace-id>  {"credential": "uc_secrets_demo"}
  C5_credential: SERVICE credential, isolation ISOLATION_MODE_OPEN  {"access_connector_id": "/subscriptions/<subscription-id>/resourceGroups/rg-uc-secrets-demo/providers/Microsoft.Databricks/accessConnectors/dbac-uc-secrets-demo", "managed_identity_id": "/subscriptions
  L1_uc_read_dbutils: Key Vault refused the service credential  {"exception": "py4j.protocol.Py4JJavaError", "message": ": com.databricks.backend.daemon.driver.repl.ManagedCatalogServiceException: PERMISSION_DENIED: the cloud provider returned access denied, check the configuration o
  L1_uc_read_rest: refused (HTTP 403 PERMISSION_DENIED)  {"http_status": 403, "error_code": "PERMISSION_DENIED", "message": "the cloud provider returned access denied, check the configuration of the service credential"}
  L1_uc_read_real_hash: Key Vault refused the service credential  {"exception": "py4j.protocol.Py4JJavaError", "message": ": com.databricks.backend.daemon.driver.repl.ManagedCatalogServiceException: PERMISSION_DENIED: the cloud provider returned access denied, check the configuration o
  L2_compute_dns: public address  {"canonical": "<kv-traffic-manager-canonical>", "aliases": ["kv-ucsec-<workspace-id>.vault.azure.net", "<kv-privatelink-alias>", "<kv-weu-alias-2>", "<kv-weu-alias-2>
  L3_compute_unauth: HTTP 401 challenge: the vault answered this compute  {"http_status": 401, "www_authenticate_present": true, "www_authenticate_scheme": "Bearer", "error_code": "Unauthorized", "message": "AKV10000: Request is missing a Bearer, PoP, or MTLS_POP token."}
  L4_compute_connector_token: HTTP 403 Forbidden  {"token_identity": {"oid": "<connector-oid>", "appid": "<connector-appid>", "idtyp": "app", "xms_mirid": "/subscriptions/<subscription-id>/resourceGroups/rg-uc-s
  L5_gateway: denied by Databricks (no EXECUTE, or the secret could not be resolved)  {"http_status": 403, "error_code": "PERMISSION_DENIED", "upstream_status": null, "elapsed_s": 0.9, "message": "the cloud provider returned access denied, check the configuration of the service credential"}
[21:21:37] run <run-or-timestamp-id> task <run-or-timestamp-id> exit JSON:
  W1_workspace: workspace <workspace-id>  {"host": "https://adb-<workspace-id>.14.azuredatabricks.net", "sdk_host": "<regional-control-plane-host>"}
  W2_metastore: metastore_azure_westeurope (westeurope)  {"metastore_id": "<metastore-id>", "cloud": "azure"}
  W3_compute: classic  {"DATABRICKS_RUNTIME_VERSION": "18.3", "DATABRICKS_ENV_VERSION": null, "spark": "4.1.0", "cluster_id": "<cluster-id>", "node_type": "Standard_F4s_v2", "spark_version": "18.x-scala2.13", "driver_ip": "<classic-node-ip>",
  W4_caller: <user>  {"workspace_admin": true}
  C1_catalog: visible, isolation OPEN  {"metastore_id": "<metastore-id>"}
  C2_catalog_bindings: 0 workspace binding(s)  {"bindings": []}
  C3_secret_listing: 2 secret(s)  {"secrets": ["uc_secrets_demo.secrets.apimlanekey", "uc_secrets_demo.secrets.dummysecret"]}
  C4_connection: AZURE_KEY_VAULT -> vault kv-ucsec-<workspace-id>  {"credential": "uc_secrets_demo"}
  C5_credential: SERVICE credential, isolation ISOLATION_MODE_OPEN  {"access_connector_id": "/subscriptions/<subscription-id>/resourceGroups/rg-uc-secrets-demo/providers/Microsoft.Databricks/accessConnectors/dbac-uc-secrets-demo", "managed_identity_id": "/subscriptions
  L1_uc_read_dbutils: Key Vault refused the service credential  {"exception": "py4j.protocol.Py4JJavaError", "message": ": com.databricks.sql.managedcatalog.acl.UnauthorizedAccessException: PERMISSION_DENIED: the cloud provider returned access denied, check the configuration of the s
  L1_uc_read_rest: refused (HTTP 403 PERMISSION_DENIED)  {"http_status": 403, "error_code": "PERMISSION_DENIED", "message": "the cloud provider returned access denied, check the configuration of the service credential"}
  L1_uc_read_real_hash: Key Vault refused the service credential  {"exception": "py4j.protocol.Py4JJavaError", "message": ": com.databricks.sql.managedcatalog.acl.UnauthorizedAccessException: PERMISSION_DENIED: the cloud provider returned access denied, check the configuration of the s
  L2_compute_dns: public address  {"canonical": "<kv-traffic-manager-canonical>", "aliases": ["kv-ucsec-<workspace-id>.vault.azure.net", "<kv-privatelink-alias>", "<kv-weu-alias-2>", "<kv-weu-alias-2>
  L3_compute_unauth: HTTP 401 challenge: the vault answered this compute  {"http_status": 401, "www_authenticate_present": true, "www_authenticate_scheme": "Bearer", "error_code": "Unauthorized", "message": "AKV10000: Request is missing a Bearer, PoP, or MTLS_POP token."}
  L4_compute_connector_token: HTTP 403 Forbidden  {"token_identity": {"oid": "<connector-oid>", "appid": "<connector-appid>", "idtyp": "app", "xms_mirid": "/subscriptions/<subscription-id>/resourceGroups/rg-uc-s
  L5_gateway: denied by Databricks (no EXECUTE, or the secret could not be resolved)  {"http_status": 403, "error_code": "PERMISSION_DENIED", "upstream_status": null, "elapsed_s": 0.7, "message": "the cloud provider returned access denied, check the configuration of the service credential"}
[21:21:37] phase 3 done; sealed for 649 s
[21:21:37] RESTORE: reopening the vault
[21:21:40] restored posture: {"bypass":null,"deny":null,"public":"Enabled"}
[21:21:41] UC read after restore: ok, value present
```

## Vault posture log (phase 4)

The orchestration's log (`phase4.sh`, the phase 3 script with new labels and output paths; its last line therefore still says "phase 3 done"), unedited
apart from the placeholders. The connector token minted on the laptop is used in one call and never printed.

```text
[06:52:58] pre-check posture: {"bypass":null,"deny":null,"public":"Enabled"}
[06:52:59] ncc rule: {"connection_state":"ESTABLISHED","endpoint_name":"databricks-<ncc-id>-pe-<endpoint-suffix>","network_connectivity_config_id":"<ncc-id>","rule_id":"<ncc-rule-id>"}
[06:53:00] SEAL: public Disabled, default Deny, bypass None
[06:53:02] sealed posture: {"bypass":"None","deny":"Deny","public":"Disabled"}
[06:53:03] direct read with my identity refused after 1 s: enforcement is live
[06:53:03] UC read from the laptop (control plane fetch) while sealed:
Error: the cloud provider returned access denied, check the configuration of the service credential

[06:53:03] connector token from the laptop while sealed (bypass None, no private link from here):
laptop, connector token: {'error': {'code': 'Forbidden', 'message': "Connection is not an approved private link and caller was ignored because bypass is not set to 'AzureServices' and PublicNetworkAccess is set to 'Disabled'. \r\nVault: kv-ucsec-<workspace-id>;location=westeurope", 'innererror': {'code': 'ForbiddenByConnection'}}}
[06:53:06] submitted serverless run <run-or-timestamp-id> and classic run <run-or-timestamp-id>
[06:54:07] run <run-or-timestamp-id>: TERMINATED SUCCESS
[07:02:22] run <run-or-timestamp-id>: TERMINATED SUCCESS
[07:02:22] UC read from the laptop again, still sealed:
Error: the cloud provider returned access denied, check the configuration of the service credential

[07:02:25] run <run-or-timestamp-id> task <run-or-timestamp-id> exit JSON:
  W1_workspace: workspace <workspace-id>  {"host": "https://adb-<workspace-id>.14.azuredatabricks.net", "sdk_host": "https://adb-<workspace-id>.14.azuredatabricks.net"}
  W2_metastore: metastore_azure_westeurope (westeurope)  {"metastore_id": "<metastore-id>", "cloud": "azure"}
  W3_compute: serverless  {"DATABRICKS_RUNTIME_VERSION": "client.6.5", "DATABRICKS_ENV_VERSION": "6", "spark": "4.2.0", "driver_ip": "<private-ip-3>", "driver_ip_rfc1918": true}
  W4_caller: <user>  {"workspace_admin": true}
  C1_catalog: visible, isolation OPEN  {"metastore_id": "<metastore-id>"}
  C2_catalog_bindings: 0 workspace binding(s)  {"bindings": []}
  C3_secret_listing: 2 secret(s)  {"secrets": ["uc_secrets_demo.secrets.apimlanekey", "uc_secrets_demo.secrets.dummysecret"]}
  C4_connection: AZURE_KEY_VAULT -> vault kv-ucsec-<workspace-id>  {"credential": "uc_secrets_demo"}
  C5_credential: SERVICE credential, isolation ISOLATION_MODE_OPEN  {"access_connector_id": "/subscriptions/<subscription-id>/resourceGroups/rg-uc-secrets-demo/providers/Microsoft.Databricks/accessConnectors/dbac-uc-secrets-demo", "managed_identity_id": "/subscriptions
  L1_uc_read_dbutils: Key Vault refused the service credential  {"exception": "py4j.protocol.Py4JJavaError", "message": ": com.databricks.backend.daemon.driver.repl.ManagedCatalogServiceException: PERMISSION_DENIED: the cloud provider returned access denied, check the configuration o
  L1_uc_read_rest: refused (HTTP 403 PERMISSION_DENIED)  {"http_status": 403, "error_code": "PERMISSION_DENIED", "message": "the cloud provider returned access denied, check the configuration of the service credential"}
  L1_uc_read_real_hash: Key Vault refused the service credential  {"exception": "py4j.protocol.Py4JJavaError", "message": ": com.databricks.backend.daemon.driver.repl.ManagedCatalogServiceException: PERMISSION_DENIED: the cloud provider returned access denied, check the configuration o
  L2_compute_dns: private endpoint address  {"canonical": "kv-ucsec-<workspace-id>.vault.azure.net", "aliases": [], "addresses": {"<ncc-private-endpoint-ip>": "private (RFC 1918)", "::ffff:<ncc-private-endpoint-ip>": "private (RFC 1918)"}}
  L3_compute_unauth: HTTP 401 challenge: the vault answered this compute  {"http_status": 401, "www_authenticate_present": true, "www_authenticate_scheme": "Bearer", "error_code": "Unauthorized", "message": "AKV10000: Request is missing a Bearer, PoP, or MTLS_POP token."}
  L4_compute_connector_token: HTTP 200: value ok  {"token_identity": {"oid": "<connector-oid>", "appid": "<connector-appid>", "idtyp": "app", "xms_mirid": "/subscriptions/<subscription-id>/resourceGroups/rg-uc-s
  L5_gateway: denied by Databricks (no EXECUTE, or the secret could not be resolved)  {"http_status": 403, "error_code": "PERMISSION_DENIED", "upstream_status": null, "elapsed_s": 1.1, "message": "the cloud provider returned access denied, check the configuration of the service credential"}
[07:02:27] run <run-or-timestamp-id> task <run-or-timestamp-id> exit JSON:
  W1_workspace: workspace <workspace-id>  {"host": "https://adb-<workspace-id>.14.azuredatabricks.net", "sdk_host": "<regional-control-plane-host>"}
  W2_metastore: metastore_azure_westeurope (westeurope)  {"metastore_id": "<metastore-id>", "cloud": "azure"}
  W3_compute: classic  {"DATABRICKS_RUNTIME_VERSION": "18.3", "DATABRICKS_ENV_VERSION": null, "spark": "4.1.0", "cluster_id": "<cluster-id>", "node_type": "Standard_F4s_v2", "spark_version": "18.x-scala2.13", "driver_ip": "<classic-node-ip>",
  W4_caller: <user>  {"workspace_admin": true}
  C1_catalog: visible, isolation OPEN  {"metastore_id": "<metastore-id>"}
  C2_catalog_bindings: 0 workspace binding(s)  {"bindings": []}
  C3_secret_listing: 2 secret(s)  {"secrets": ["uc_secrets_demo.secrets.apimlanekey", "uc_secrets_demo.secrets.dummysecret"]}
  C4_connection: AZURE_KEY_VAULT -> vault kv-ucsec-<workspace-id>  {"credential": "uc_secrets_demo"}
  C5_credential: SERVICE credential, isolation ISOLATION_MODE_OPEN  {"access_connector_id": "/subscriptions/<subscription-id>/resourceGroups/rg-uc-secrets-demo/providers/Microsoft.Databricks/accessConnectors/dbac-uc-secrets-demo", "managed_identity_id": "/subscriptions
  L1_uc_read_dbutils: Key Vault refused the service credential  {"exception": "py4j.protocol.Py4JJavaError", "message": ": com.databricks.sql.managedcatalog.acl.UnauthorizedAccessException: PERMISSION_DENIED: the cloud provider returned access denied, check the configuration of the s
  L1_uc_read_rest: refused (HTTP 403 PERMISSION_DENIED)  {"http_status": 403, "error_code": "PERMISSION_DENIED", "message": "the cloud provider returned access denied, check the configuration of the service credential"}
  L1_uc_read_real_hash: Key Vault refused the service credential  {"exception": "py4j.protocol.Py4JJavaError", "message": ": com.databricks.sql.managedcatalog.acl.UnauthorizedAccessException: PERMISSION_DENIED: the cloud provider returned access denied, check the configuration of the s
  L2_compute_dns: public address  {"canonical": "<kv-akadns-canonical>", "aliases": ["kv-ucsec-<workspace-id>.vault.azure.net", "<kv-privatelink-alias>", "<kv-weu-alias-2>", "<kv-regional-alias-3>
  L3_compute_unauth: HTTP 401 challenge: the vault answered this compute  {"http_status": 401, "www_authenticate_present": true, "www_authenticate_scheme": "Bearer", "error_code": "Unauthorized", "message": "AKV10000: Request is missing a Bearer, PoP, or MTLS_POP token."}
  L4_compute_connector_token: HTTP 403 Forbidden  {"token_identity": {"oid": "<connector-oid>", "appid": "<connector-appid>", "idtyp": "app", "xms_mirid": "/subscriptions/<subscription-id>/resourceGroups/rg-uc-s
  L5_gateway: denied by Databricks (no EXECUTE, or the secret could not be resolved)  {"http_status": 403, "error_code": "PERMISSION_DENIED", "upstream_status": null, "elapsed_s": 0.9, "message": "the cloud provider returned access denied, check the configuration of the service credential"}
[07:02:27] phase 3 done; sealed for 565 s
[07:02:27] RESTORE: reopening the vault
[07:02:29] restored posture: {"bypass":null,"deny":null,"public":"Enabled"}
[07:02:29] UC read after restore: ok, value present
```

## Not tested, and why

- **The two private-link workspaces (`ws-private-link-dev`, `ws-private-link-prd`).** Their front ends accept private link only
  (`publicNetworkAccess: Disabled`); from outside, the dev host answers "Unauthorized network access", and `<user>` is not a member. Adding a member or a
  network path was out of scope. They sit on the **same westeurope metastore**, so the catalog is `OPEN` to them. See "Run it yourself from inside" below.
- **The warehouse's other lanes.** The SQL warehouse lane (phase 6) covers the `SECRETS`-clause UDF and `ai_query`; a SQL warehouse has no `dbutils`,
  no DNS lane and no direct-call lane, so those columns of the matrix do not exist for it.
- **When exactly the NCC endpoint went live.** Serverless still resolved the vault publicly 22 minutes after the endpoint's approval (row 11) and
  privately 9 h 45 min after it (row 12). Nothing was measured in between, so the propagation time is only bounded by those two points. Databricks
  documents ten minutes for most changes and up to 24 hours in full.
- **Audit and diagnostic logs for phases 1 to 6.** `diagnostics.tf` was applied only before phase 7, so the caller addresses of the earlier phases were
  never logged; phase 7's logs cover the same lanes and compute types, which is where the service-endpoint and private-endpoint attributions above
  come from. The Databricks audit rows for the token issuance were not inspected.
- **A completed chat answer.** The upstream model behind the APIM lane was down in every run, so the gateway lane proves "bearer accepted by APIM", not a completion.

## Run it yourself from inside: the private-link workspaces

`ws-private-link-dev` and `ws-private-link-prd` are on the same westeurope metastore, so this notebook can produce their rows unchanged. Run it
from a machine that can reach their private front ends, as a member of the workspace:

1. Import `notebooks/topology_matrix.py` to `/Shared/uc_secrets_demo/topology_matrix` (see "Re-running").
2. Submit one serverless and one classic run with `run_label` `vault open: <workspace> serverless` and `... classic`. The classic cluster uses the
   workspace's own VNet-injected subnets.
3. Compare with rows 1 to 3. What these rows predict, untested on those workspaces:
   - UC read and Unity Gateway as in rows 1 and 3, because neither depends on the workspace's network.
   - Compute DNS public, unless the VNet or `<private-link-ncc>` has a Key Vault private endpoint (the NCC's rules today are for storage).
   - Compute direct with the connector token `200` if the compute has any route to the vault's front end.
   A difference in any column is the finding.

## Re-running

Upload the notebook to each workspace you want a row for (the CLI profile for the demo workspace; an Entra token for the others):

```bash
databricks workspace import /Shared/uc_secrets_demo/topology_matrix --file notebooks/topology_matrix.py \
  --format SOURCE --language PYTHON --overwrite -p <profile>

# a workspace without a CLI profile: an Entra token for the Azure Databricks resource. DATABRICKS_AUTH_TYPE=pat stops the CLI from
# merging in the auth type of a DEFAULT profile in ~/.databrickscfg (without it the CLI tried that profile's cached login instead)
TOK=$(az account get-access-token --resource <request-or-resource-id> --query accessToken -o tsv)
export DATABRICKS_AUTH_TYPE=pat DATABRICKS_HOST=https://<workspace-host> DATABRICKS_TOKEN=$TOK
databricks workspace mkdirs /Shared/uc_secrets_demo
databricks workspace import /Shared/uc_secrets_demo/topology_matrix --file notebooks/topology_matrix.py --format SOURCE --language PYTHON --overwrite
```

Serverless row (`serverless.json`), submitted with `databricks jobs submit --json @serverless.json`:

```json
{
  "run_name": "uc_secrets_demo topology matrix: vault open: ws-demo serverless",
  "tasks": [{
    "task_key": "topology_matrix",
    "notebook_task": {"notebook_path": "/Shared/uc_secrets_demo/topology_matrix", "source": "WORKSPACE",
                      "base_parameters": {"run_label": "vault open: ws-demo serverless", "vault_name": "<key-vault>", "model": "<model-alias>"}},
    "environment_key": "default"
  }],
  "environments": [{"environment_key": "default", "spec": {"environment_version": "6"}}]
}
```

Classic row (`classic.json`): the same task with a single-node job cluster instead of `environment_key` and `environments`:

```json
{
  "run_name": "uc_secrets_demo topology matrix: vault open: ws-demo classic",
  "tasks": [{
    "task_key": "topology_matrix",
    "notebook_task": {"notebook_path": "/Shared/uc_secrets_demo/topology_matrix", "source": "WORKSPACE",
                      "base_parameters": {"run_label": "vault open: ws-demo classic", "vault_name": "<key-vault>", "model": "<model-alias>"}},
    "new_cluster": {
      "spark_version": "18.x-scala2.13", "node_type_id": "Standard_F4s_v2", "num_workers": 0,
      "data_security_mode": "SINGLE_USER", "single_user_name": "<user>",
      "spark_conf": {"spark.databricks.cluster.profile": "singleNode", "spark.master": "local[*]"},
      "custom_tags": {"ResourceClass": "SingleNode"}
    }
  }]
}
```

Locked posture (run the rows, then restore; nothing else may change the vault in between):

```bash
az keyvault update --subscription <subscription> -n <key-vault> --public-network-access Disabled --default-action Deny --bypass AzureServices
# wait until a direct read from outside is refused, so the runs do not land inside the enforcement lag:
until az keyvault secret show --subscription <subscription> --vault-name <key-vault> -n dummysecret --query id -o tsv 2>&1 \
  | grep -q "Public network access is disabled"; do :; done
databricks jobs submit --json @serverless.json -p <profile>   # run_label "vault locked: ..."
az keyvault update --subscription <subscription> -n <key-vault> --public-network-access Enabled --default-action Allow --bypass AzureServices
az keyvault show --subscription <subscription> -n <key-vault> --query '{public:properties.publicNetworkAccess, acls:properties.networkAcls}'
```

Read the results with `databricks jobs get-run-output <task run_id>` (exit value) and `databricks jobs export-run <task run_id> --views-to-export CODE`
(rendered cells).

The drivers that produced phases 3 to 7 (phase 5 is rows A1 and A2) are in [`measurements/`](../measurements): they read every name from the Terraform
state (the model alias from the workspace), submit the topology rows as exactly the two requests above (`run_matrix` in `lib.sh`), poll the runs, keep
the laptop controls, save each run's output and CODE export under
`measurements/out/` (gitignored), and restore the vault or the perimeter on every exit path. [`row_section.py`](../measurements/row_section.py) turns a saved
export into one of the raw-output sections below with the placeholders of this document applied; values it cannot derive from the
state or the workspace (another workspace's id, the reference-only principal's application id) go in as `--replace` pairs.

## Raw cell outputs per run

Sections 1 to 8 as rendered by the run, then the exit value.

### Row 1: ws-demo, serverless, vault open

`run_id` <run-or-timestamp-id> / task `run_id` <run-or-timestamp-id>, SUCCESS, started 2026-10-29 20:22:38 UTC.

**Parameters and helpers**

```text
run_label: vault open: ws-demo serverless
workspace host: https://adb-<workspace-id>.14.azuredatabricks.net | SDK host: https://adb-<workspace-id>.14.azuredatabricks.net | databricks-sdk 0.122.0 | SDK HTTP timeout: 60 s | gateway client timeout: 360 s
```

**1. Where am I**

```text
[W1_workspace] workspace <workspace-id>  {"host": "https://adb-<workspace-id>.14.azuredatabricks.net", "sdk_host": "https://adb-<workspace-id>.14.azuredatabricks.net"}
[W2_metastore] metastore_azure_westeurope (westeurope)  {"metastore_id": "<metastore-id>", "cloud": "azure"}
[W3_compute] serverless  {"DATABRICKS_RUNTIME_VERSION": "client.6.5", "DATABRICKS_ENV_VERSION": "6", "spark": "4.2.0", "driver_ip": "<private-ip-2>", "driver_ip_rfc1918": true}
[W4_caller] <user>  {"workspace_admin": true}
```

**2. Catalog visibility, binding and the secret chain**

```text
[C1_catalog] visible, isolation OPEN  {"metastore_id": "<metastore-id>"}
[C2_catalog_bindings] 0 workspace binding(s)  {"bindings": []}
[C3_secret_listing] 2 secret(s)  {"secrets": ["uc_secrets_demo.secrets.apimlanekey", "uc_secrets_demo.secrets.dummysecret"]}
[C4_connection] AZURE_KEY_VAULT -> vault kv-ucsec-<workspace-id>  {"credential": "uc_secrets_demo"}
[C5_credential] SERVICE credential, isolation ISOLATION_MODE_OPEN  {"access_connector_id": "/subscriptions/<subscription-id>/resourceGroups/rg-uc-secrets-demo/providers/Microsoft.Databricks/accessConnectors/dbac-uc-secrets-demo", "managed_identity_id": "/subscriptions/<subscription-id>/resourceGroups/rg-uc-secrets-demo/providers/Microsoft.ManagedIdentity/userAssignedIdentities/id-uc-secrets-demo"}
vault under test: kv-ucsec-<workspace-id>.vault.azure.net
```

**3. UC read lane**

```text
[L1_uc_read_dbutils] value ok  {"length": 20, "sha256_prefix": "<dummy-sha256-prefix>"}
[L1_uc_read_rest] value ok  {"length": 20, "sha256_prefix": "<dummy-sha256-prefix>"}
[L1_uc_read_real_hash] value ok  {"length": 64, "sha256_prefix": "<secret-sha256-prefix-1>"}
```

**4. Compute DNS lane**

```text
[L2_compute_dns] public address  {"canonical": "<kv-traffic-manager-canonical-b>", "aliases": ["kv-ucsec-<workspace-id>.vault.azure.net", "<kv-weu-alias-1>", "<kv-weu-alias-2>", "<kv-regional-alias-3>"], "addresses": {"<public-ip-4>": "public", "<public-ip-5>": "public", "<public-ip-6>": "public"}}
```

**5. Compute direct, no token**

```text
[L3_compute_unauth] HTTP 401 challenge: the vault answered this compute  {"http_status": 401, "www_authenticate_present": true, "www_authenticate_scheme": "Bearer", "error_code": "Unauthorized", "message": "AKV10000: Request is missing a Bearer, PoP, or MTLS_POP token."}
```

**6. Compute direct, with the identity Unity Catalog uses**

```text
token identity: {"oid": "<connector-oid>", "appid": "<connector-appid>", "idtyp": "app", "xms_mirid": "/subscriptions/<subscription-id>/resourceGroups/rg-uc-secrets-demo/providers/Microsoft.Databricks/accessConnectors/dbac-uc-secrets-demo"}
[L4_compute_connector_token] HTTP 200: value ok  {"token_identity": {"oid": "<connector-oid>", "appid": "<connector-appid>", "idtyp": "app", "xms_mirid": "/subscriptions/<subscription-id>/resourceGroups/rg-uc-secrets-demo/providers/Microsoft.Databricks/accessConnectors/dbac-uc-secrets-demo"}, "sha256_prefix": "<dummy-sha256-prefix>", "same_as_uc_read": true}
```

**7. Unity Gateway lane**

```text
HTTP 502 after 230.3 s (64% of the 360 s client timeout)
error_code=INTERNAL_ERROR upstream_status=500
message: Model Provider Service returned error with status code 500: Internal server error. The model provider returned a server error — this is usually transient, so retry with backoff; if it persists, check the provider's status page.
verdict: bearer accepted by APIM; the upstream model failed (upstream_status 500)
[L5_gateway] bearer accepted by APIM; the upstream model failed (upstream_status 500)  {"http_status": 502, "error_code": "INTERNAL_ERROR", "upstream_status": 500, "elapsed_s": 230.3, "message": "Model Provider Service returned error with status code 500: Internal server error. The model provider returned a server error \u2014 this is usually transient, so retry with backoff; if it persists, check the provider's status page."}
```

**8. Summary**

```text
workspace <workspace-id> | metastore_azure_westeurope (westeurope) | serverless | driver <private-ip-2> | run_label vault open: ws-demo serverless
vault kv-ucsec-<workspace-id>.vault.azure.net | catalog visible, isolation OPEN | credential SERVICE credential, isolation ISOLATION_MODE_OPEN
lane                                     outcome
UC read, dbutils (dummy)                 value ok
UC read, REST include_value (dummy)      value ok
UC read, dbutils (real, hash only)       value ok
compute DNS                              public address
compute direct, no token                 HTTP 401 challenge: the vault answered this compute
compute direct, connector token          HTTP 200: value ok
Unity Gateway                            bearer accepted by APIM; the upstream model failed (upstream_status 500)
```

<details><summary>Exit value (<code>dbutils.notebook.exit</code>)</summary>

```json
{"run_label": "vault open: ws-demo serverless", "claims": {"W1_workspace": {"outcome": "workspace <workspace-id>", "host": "https://adb-<workspace-id>.14.azuredatabricks.net", "sdk_host": "https://adb-<workspace-id>.14.azuredatabricks.net"}, "W2_metastore": {"outcome": "metastore_azure_westeurope (westeurope)", "metastore_id": "<metastore-id>", "cloud": "azure"}, "W3_compute": {"outcome": "serverless", "DATABRICKS_RUNTIME_VERSION": "client.6.5", "DATABRICKS_ENV_VERSION": "6", "spark": "4.2.0", "driver_ip": "<private-ip-2>", "driver_ip_rfc1918": true}, "W4_caller": {"outcome": "<user>", "workspace_admin": true}, "C1_catalog": {"outcome": "visible, isolation OPEN", "metastore_id": "<metastore-id>"}, "C2_catalog_bindings": {"outcome": "0 workspace binding(s)", "bindings": []}, "C3_secret_listing": {"outcome": "2 secret(s)", "secrets": ["uc_secrets_demo.secrets.apimlanekey", "uc_secrets_demo.secrets.dummysecret"]}, "C4_connection": {"outcome": "AZURE_KEY_VAULT -> vault kv-ucsec-<workspace-id>", "credential": "uc_secrets_demo"}, "C5_credential": {"outcome": "SERVICE credential, isolation ISOLATION_MODE_OPEN", "access_connector_id": "/subscriptions/<subscription-id>/resourceGroups/rg-uc-secrets-demo/providers/Microsoft.Databricks/accessConnectors/dbac-uc-secrets-demo", "managed_identity_id": "/subscriptions/<subscription-id>/resourceGroups/rg-uc-secrets-demo/providers/Microsoft.ManagedIdentity/userAssignedIdentities/id-uc-secrets-demo"}, "L1_uc_read_dbutils": {"outcome": "value ok", "length": 20, "sha256_prefix": "<dummy-sha256-prefix>"}, "L1_uc_read_rest": {"outcome": "value ok", "length": 20, "sha256_prefix": "<dummy-sha256-prefix>"}, "L1_uc_read_real_hash": {"outcome": "value ok", "length": 64, "sha256_prefix": "<secret-sha256-prefix-1>"}, "L2_compute_dns": {"outcome": "public address", "canonical": "<kv-traffic-manager-canonical-b>", "aliases": ["kv-ucsec-<workspace-id>.vault.azure.net", "<kv-weu-alias-1>", "<kv-weu-alias-2>", "<kv-regional-alias-3>"], "addresses": {"<public-ip-4>": "public", "<public-ip-5>": "public", "<public-ip-6>": "public"}}, "L3_compute_unauth": {"outcome": "HTTP 401 challenge: the vault answered this compute", "http_status": 401, "www_authenticate_present": true, "www_authenticate_scheme": "Bearer", "error_code": "Unauthorized", "message": "AKV10000: Request is missing a Bearer, PoP, or MTLS_POP token."}, "L4_compute_connector_token": {"outcome": "HTTP 200: value ok", "token_identity": {"oid": "<connector-oid>", "appid": "<connector-appid>", "idtyp": "app", "xms_mirid": "/subscriptions/<subscription-id>/resourceGroups/rg-uc-secrets-demo/providers/Microsoft.Databricks/accessConnectors/dbac-uc-secrets-demo"}, "sha256_prefix": "<dummy-sha256-prefix>", "same_as_uc_read": true}, "L5_gateway": {"outcome": "bearer accepted by APIM; the upstream model failed (upstream_status 500)", "http_status": 502, "error_code": "INTERNAL_ERROR", "upstream_status": 500, "elapsed_s": 230.3, "message": "Model Provider Service returned error with status code 500: Internal server error. The model provider returned a server error — this is usually transient, so retry with backoff; if it persists, check the provider's status page."}}}
```

</details>

### Row 2: ws-demo, classic, vault open

`run_id` <run-or-timestamp-id> / task `run_id` <run-or-timestamp-id>, SUCCESS, started 2026-10-29 20:22:37 UTC.

**Parameters and helpers**

```text
run_label: vault open: ws-demo classic
workspace host: https://adb-<workspace-id>.14.azuredatabricks.net | SDK host: https://<regional-control-plane-host> | databricks-sdk 0.67.0 | SDK HTTP timeout: 60 s | gateway client timeout: 360 s
```

**1. Where am I**

```text
[W1_workspace] workspace <workspace-id>  {"host": "https://adb-<workspace-id>.14.azuredatabricks.net", "sdk_host": "https://<regional-control-plane-host>"}
[W2_metastore] metastore_azure_westeurope (westeurope)  {"metastore_id": "<metastore-id>", "cloud": "azure"}
[W3_compute] classic  {"DATABRICKS_RUNTIME_VERSION": "18.3", "DATABRICKS_ENV_VERSION": null, "spark": "4.1.0", "cluster_id": "<cluster-id>", "node_type": "Standard_F4s_v2", "spark_version": "18.x-scala2.13", "driver_ip": "<classic-node-ip>", "driver_ip_rfc1918": true}
[W4_caller] <user>  {"workspace_admin": true}
```

**2. Catalog visibility, binding and the secret chain**

```text
[C1_catalog] visible, isolation OPEN  {"metastore_id": "<metastore-id>"}
[C2_catalog_bindings] 0 workspace binding(s)  {"bindings": []}
[C3_secret_listing] 2 secret(s)  {"secrets": ["uc_secrets_demo.secrets.apimlanekey", "uc_secrets_demo.secrets.dummysecret"]}
[C4_connection] AZURE_KEY_VAULT -> vault kv-ucsec-<workspace-id>  {"credential": "uc_secrets_demo"}
[C5_credential] SERVICE credential, isolation ISOLATION_MODE_OPEN  {"access_connector_id": "/subscriptions/<subscription-id>/resourceGroups/rg-uc-secrets-demo/providers/Microsoft.Databricks/accessConnectors/dbac-uc-secrets-demo", "managed_identity_id": "/subscriptions/<subscription-id>/resourceGroups/rg-uc-secrets-demo/providers/Microsoft.ManagedIdentity/userAssignedIdentities/id-uc-secrets-demo"}
vault under test: kv-ucsec-<workspace-id>.vault.azure.net
```

**3. UC read lane**

```text
[L1_uc_read_dbutils] value ok  {"length": 20, "sha256_prefix": "<dummy-sha256-prefix>"}
[L1_uc_read_rest] value ok  {"length": 20, "sha256_prefix": "<dummy-sha256-prefix>"}
[L1_uc_read_real_hash] value ok  {"length": 64, "sha256_prefix": "<secret-sha256-prefix-1>"}
```

**4. Compute DNS lane**

```text
[L2_compute_dns] public address  {"canonical": "<kv-traffic-manager-canonical-a>", "aliases": ["kv-ucsec-<workspace-id>.vault.azure.net", "<kv-weu-alias-1>", "<kv-weu-alias-2>", "<kv-regional-alias-3>"], "addresses": {"<public-ip-4>": "public", "<public-ip-5>": "public", "<public-ip-6>": "public"}}
```

**5. Compute direct, no token**

```text
[L3_compute_unauth] HTTP 401 challenge: the vault answered this compute  {"http_status": 401, "www_authenticate_present": true, "www_authenticate_scheme": "Bearer", "error_code": "Unauthorized", "message": "AKV10000: Request is missing a Bearer, PoP, or MTLS_POP token."}
```

**6. Compute direct, with the identity Unity Catalog uses**

```text
token identity: {"oid": "<connector-oid>", "appid": "<connector-appid>", "idtyp": "app", "xms_mirid": "/subscriptions/<subscription-id>/resourceGroups/rg-uc-secrets-demo/providers/Microsoft.Databricks/accessConnectors/dbac-uc-secrets-demo"}
[L4_compute_connector_token] HTTP 200: value ok  {"token_identity": {"oid": "<connector-oid>", "appid": "<connector-appid>", "idtyp": "app", "xms_mirid": "/subscriptions/<subscription-id>/resourceGroups/rg-uc-secrets-demo/providers/Microsoft.Databricks/accessConnectors/dbac-uc-secrets-demo"}, "sha256_prefix": "<dummy-sha256-prefix>", "same_as_uc_read": true}
```

**7. Unity Gateway lane**

```text
HTTP 502 after 230.8 s (64% of the 360 s client timeout)
error_code=INTERNAL_ERROR upstream_status=500
message: Model Provider Service returned error with status code 500: Internal server error. The model provider returned a server error — this is usually transient, so retry with backoff; if it persists, check the provider's status page.
verdict: bearer accepted by APIM; the upstream model failed (upstream_status 500)
[L5_gateway] bearer accepted by APIM; the upstream model failed (upstream_status 500)  {"http_status": 502, "error_code": "INTERNAL_ERROR", "upstream_status": 500, "elapsed_s": 230.8, "message": "Model Provider Service returned error with status code 500: Internal server error. The model provider returned a server error \u2014 this is usually transient, so retry with backoff; if it persists, check the provider's status page."}
```

**8. Summary**

```text
workspace <workspace-id> | metastore_azure_westeurope (westeurope) | classic | driver <classic-node-ip> | run_label vault open: ws-demo classic
vault kv-ucsec-<workspace-id>.vault.azure.net | catalog visible, isolation OPEN | credential SERVICE credential, isolation ISOLATION_MODE_OPEN
lane                                     outcome
UC read, dbutils (dummy)                 value ok
UC read, REST include_value (dummy)      value ok
UC read, dbutils (real, hash only)       value ok
compute DNS                              public address
compute direct, no token                 HTTP 401 challenge: the vault answered this compute
compute direct, connector token          HTTP 200: value ok
Unity Gateway                            bearer accepted by APIM; the upstream model failed (upstream_status 500)
```

<details><summary>Exit value (<code>dbutils.notebook.exit</code>)</summary>

```json
{"run_label": "vault open: ws-demo classic", "claims": {"W1_workspace": {"outcome": "workspace <workspace-id>", "host": "https://adb-<workspace-id>.14.azuredatabricks.net", "sdk_host": "https://<regional-control-plane-host>"}, "W2_metastore": {"outcome": "metastore_azure_westeurope (westeurope)", "metastore_id": "<metastore-id>", "cloud": "azure"}, "W3_compute": {"outcome": "classic", "DATABRICKS_RUNTIME_VERSION": "18.3", "DATABRICKS_ENV_VERSION": null, "spark": "4.1.0", "cluster_id": "<cluster-id>", "node_type": "Standard_F4s_v2", "spark_version": "18.x-scala2.13", "driver_ip": "<classic-node-ip>", "driver_ip_rfc1918": true}, "W4_caller": {"outcome": "<user>", "workspace_admin": true}, "C1_catalog": {"outcome": "visible, isolation OPEN", "metastore_id": "<metastore-id>"}, "C2_catalog_bindings": {"outcome": "0 workspace binding(s)", "bindings": []}, "C3_secret_listing": {"outcome": "2 secret(s)", "secrets": ["uc_secrets_demo.secrets.apimlanekey", "uc_secrets_demo.secrets.dummysecret"]}, "C4_connection": {"outcome": "AZURE_KEY_VAULT -> vault kv-ucsec-<workspace-id>", "credential": "uc_secrets_demo"}, "C5_credential": {"outcome": "SERVICE credential, isolation ISOLATION_MODE_OPEN", "access_connector_id": "/subscriptions/<subscription-id>/resourceGroups/rg-uc-secrets-demo/providers/Microsoft.Databricks/accessConnectors/dbac-uc-secrets-demo", "managed_identity_id": "/subscriptions/<subscription-id>/resourceGroups/rg-uc-secrets-demo/providers/Microsoft.ManagedIdentity/userAssignedIdentities/id-uc-secrets-demo"}, "L1_uc_read_dbutils": {"outcome": "value ok", "length": 20, "sha256_prefix": "<dummy-sha256-prefix>"}, "L1_uc_read_rest": {"outcome": "value ok", "length": 20, "sha256_prefix": "<dummy-sha256-prefix>"}, "L1_uc_read_real_hash": {"outcome": "value ok", "length": 64, "sha256_prefix": "<secret-sha256-prefix-1>"}, "L2_compute_dns": {"outcome": "public address", "canonical": "<kv-traffic-manager-canonical-a>", "aliases": ["kv-ucsec-<workspace-id>.vault.azure.net", "<kv-weu-alias-1>", "<kv-weu-alias-2>", "<kv-regional-alias-3>"], "addresses": {"<public-ip-4>": "public", "<public-ip-5>": "public", "<public-ip-6>": "public"}}, "L3_compute_unauth": {"outcome": "HTTP 401 challenge: the vault answered this compute", "http_status": 401, "www_authenticate_present": true, "www_authenticate_scheme": "Bearer", "error_code": "Unauthorized", "message": "AKV10000: Request is missing a Bearer, PoP, or MTLS_POP token."}, "L4_compute_connector_token": {"outcome": "HTTP 200: value ok", "token_identity": {"oid": "<connector-oid>", "appid": "<connector-appid>", "idtyp": "app", "xms_mirid": "/subscriptions/<subscription-id>/resourceGroups/rg-uc-secrets-demo/providers/Microsoft.Databricks/accessConnectors/dbac-uc-secrets-demo"}, "sha256_prefix": "<dummy-sha256-prefix>", "same_as_uc_read": true}, "L5_gateway": {"outcome": "bearer accepted by APIM; the upstream model failed (upstream_status 500)", "http_status": 502, "error_code": "INTERNAL_ERROR", "upstream_status": 500, "elapsed_s": 230.8, "message": "Model Provider Service returned error with status code 500: Internal server error. The model provider returned a server error — this is usually transient, so retry with backoff; if it persists, check the provider's status page."}}}
```

</details>

### Row 3: ws-weu-managed, serverless, vault open

`run_id` <run-or-timestamp-id> / task `run_id` <run-or-timestamp-id>, SUCCESS, started 2026-10-29 20:22:39 UTC.

**Parameters and helpers**

```text
run_label: vault open: ws-weu-managed serverless
workspace host: https://adb-<workspace-id-managed-vnet>.19.azuredatabricks.net | SDK host: https://adb-<workspace-id-managed-vnet>.19.azuredatabricks.net | databricks-sdk 0.122.0 | SDK HTTP timeout: 60 s | gateway client timeout: 360 s
```

**1. Where am I**

```text
[W1_workspace] workspace <workspace-id-managed-vnet>  {"host": "https://adb-<workspace-id-managed-vnet>.19.azuredatabricks.net", "sdk_host": "https://adb-<workspace-id-managed-vnet>.19.azuredatabricks.net"}
[W2_metastore] metastore_azure_westeurope (westeurope)  {"metastore_id": "<metastore-id>", "cloud": "azure"}
[W3_compute] serverless  {"DATABRICKS_RUNTIME_VERSION": "client.6.5", "DATABRICKS_ENV_VERSION": "6", "spark": "4.2.0", "driver_ip": "<private-ip-2>", "driver_ip_rfc1918": true}
[W4_caller] <user>  {"workspace_admin": true}
```

**2. Catalog visibility, binding and the secret chain**

```text
[C1_catalog] visible, isolation OPEN  {"metastore_id": "<metastore-id>"}
[C2_catalog_bindings] 0 workspace binding(s)  {"bindings": []}
[C3_secret_listing] 2 secret(s)  {"secrets": ["uc_secrets_demo.secrets.apimlanekey", "uc_secrets_demo.secrets.dummysecret"]}
[C4_connection] AZURE_KEY_VAULT -> vault kv-ucsec-<workspace-id>  {"credential": "uc_secrets_demo"}
[C5_credential] SERVICE credential, isolation ISOLATION_MODE_OPEN  {"access_connector_id": "/subscriptions/<subscription-id>/resourceGroups/rg-uc-secrets-demo/providers/Microsoft.Databricks/accessConnectors/dbac-uc-secrets-demo", "managed_identity_id": "/subscriptions/<subscription-id>/resourceGroups/rg-uc-secrets-demo/providers/Microsoft.ManagedIdentity/userAssignedIdentities/id-uc-secrets-demo"}
vault under test: kv-ucsec-<workspace-id>.vault.azure.net
```

**3. UC read lane**

```text
[L1_uc_read_dbutils] value ok  {"length": 20, "sha256_prefix": "<dummy-sha256-prefix>"}
[L1_uc_read_rest] value ok  {"length": 20, "sha256_prefix": "<dummy-sha256-prefix>"}
[L1_uc_read_real_hash] value ok  {"length": 64, "sha256_prefix": "<secret-sha256-prefix-1>"}
```

**4. Compute DNS lane**

```text
[L2_compute_dns] public address  {"canonical": "<kv-traffic-manager-canonical-a>", "aliases": ["kv-ucsec-<workspace-id>.vault.azure.net", "<kv-weu-alias-1>", "<kv-weu-alias-2>", "<kv-regional-alias-3>"], "addresses": {"<public-ip-4>": "public", "<public-ip-5>": "public", "<public-ip-6>": "public"}}
```

**5. Compute direct, no token**

```text
[L3_compute_unauth] HTTP 401 challenge: the vault answered this compute  {"http_status": 401, "www_authenticate_present": true, "www_authenticate_scheme": "Bearer", "error_code": "Unauthorized", "message": "AKV10000: Request is missing a Bearer, PoP, or MTLS_POP token."}
```

**6. Compute direct, with the identity Unity Catalog uses**

```text
token identity: {"oid": "<connector-oid>", "appid": "<connector-appid>", "idtyp": "app", "xms_mirid": "/subscriptions/<subscription-id>/resourceGroups/rg-uc-secrets-demo/providers/Microsoft.Databricks/accessConnectors/dbac-uc-secrets-demo"}
[L4_compute_connector_token] HTTP 200: value ok  {"token_identity": {"oid": "<connector-oid>", "appid": "<connector-appid>", "idtyp": "app", "xms_mirid": "/subscriptions/<subscription-id>/resourceGroups/rg-uc-secrets-demo/providers/Microsoft.Databricks/accessConnectors/dbac-uc-secrets-demo"}, "sha256_prefix": "<dummy-sha256-prefix>", "same_as_uc_read": true}
```

**7. Unity Gateway lane**

```text
HTTP 502 after 230.3 s (64% of the 360 s client timeout)
error_code=INTERNAL_ERROR upstream_status=500
message: Model Provider Service returned error with status code 500: Internal server error. The model provider returned a server error — this is usually transient, so retry with backoff; if it persists, check the provider's status page.
verdict: bearer accepted by APIM; the upstream model failed (upstream_status 500)
[L5_gateway] bearer accepted by APIM; the upstream model failed (upstream_status 500)  {"http_status": 502, "error_code": "INTERNAL_ERROR", "upstream_status": 500, "elapsed_s": 230.3, "message": "Model Provider Service returned error with status code 500: Internal server error. The model provider returned a server error \u2014 this is usually transient, so retry with backoff; if it persists, check the provider's status page."}
```

**8. Summary**

```text
workspace <workspace-id-managed-vnet> | metastore_azure_westeurope (westeurope) | serverless | driver <private-ip-2> | run_label vault open: ws-weu-managed serverless
vault kv-ucsec-<workspace-id>.vault.azure.net | catalog visible, isolation OPEN | credential SERVICE credential, isolation ISOLATION_MODE_OPEN
lane                                     outcome
UC read, dbutils (dummy)                 value ok
UC read, REST include_value (dummy)      value ok
UC read, dbutils (real, hash only)       value ok
compute DNS                              public address
compute direct, no token                 HTTP 401 challenge: the vault answered this compute
compute direct, connector token          HTTP 200: value ok
Unity Gateway                            bearer accepted by APIM; the upstream model failed (upstream_status 500)
```

<details><summary>Exit value (<code>dbutils.notebook.exit</code>)</summary>

```json
{"run_label": "vault open: ws-weu-managed serverless", "claims": {"W1_workspace": {"outcome": "workspace <workspace-id-managed-vnet>", "host": "https://adb-<workspace-id-managed-vnet>.19.azuredatabricks.net", "sdk_host": "https://adb-<workspace-id-managed-vnet>.19.azuredatabricks.net"}, "W2_metastore": {"outcome": "metastore_azure_westeurope (westeurope)", "metastore_id": "<metastore-id>", "cloud": "azure"}, "W3_compute": {"outcome": "serverless", "DATABRICKS_RUNTIME_VERSION": "client.6.5", "DATABRICKS_ENV_VERSION": "6", "spark": "4.2.0", "driver_ip": "<private-ip-2>", "driver_ip_rfc1918": true}, "W4_caller": {"outcome": "<user>", "workspace_admin": true}, "C1_catalog": {"outcome": "visible, isolation OPEN", "metastore_id": "<metastore-id>"}, "C2_catalog_bindings": {"outcome": "0 workspace binding(s)", "bindings": []}, "C3_secret_listing": {"outcome": "2 secret(s)", "secrets": ["uc_secrets_demo.secrets.apimlanekey", "uc_secrets_demo.secrets.dummysecret"]}, "C4_connection": {"outcome": "AZURE_KEY_VAULT -> vault kv-ucsec-<workspace-id>", "credential": "uc_secrets_demo"}, "C5_credential": {"outcome": "SERVICE credential, isolation ISOLATION_MODE_OPEN", "access_connector_id": "/subscriptions/<subscription-id>/resourceGroups/rg-uc-secrets-demo/providers/Microsoft.Databricks/accessConnectors/dbac-uc-secrets-demo", "managed_identity_id": "/subscriptions/<subscription-id>/resourceGroups/rg-uc-secrets-demo/providers/Microsoft.ManagedIdentity/userAssignedIdentities/id-uc-secrets-demo"}, "L1_uc_read_dbutils": {"outcome": "value ok", "length": 20, "sha256_prefix": "<dummy-sha256-prefix>"}, "L1_uc_read_rest": {"outcome": "value ok", "length": 20, "sha256_prefix": "<dummy-sha256-prefix>"}, "L1_uc_read_real_hash": {"outcome": "value ok", "length": 64, "sha256_prefix": "<secret-sha256-prefix-1>"}, "L2_compute_dns": {"outcome": "public address", "canonical": "<kv-traffic-manager-canonical-a>", "aliases": ["kv-ucsec-<workspace-id>.vault.azure.net", "<kv-weu-alias-1>", "<kv-weu-alias-2>", "<kv-regional-alias-3>"], "addresses": {"<public-ip-4>": "public", "<public-ip-5>": "public", "<public-ip-6>": "public"}}, "L3_compute_unauth": {"outcome": "HTTP 401 challenge: the vault answered this compute", "http_status": 401, "www_authenticate_present": true, "www_authenticate_scheme": "Bearer", "error_code": "Unauthorized", "message": "AKV10000: Request is missing a Bearer, PoP, or MTLS_POP token."}, "L4_compute_connector_token": {"outcome": "HTTP 200: value ok", "token_identity": {"oid": "<connector-oid>", "appid": "<connector-appid>", "idtyp": "app", "xms_mirid": "/subscriptions/<subscription-id>/resourceGroups/rg-uc-secrets-demo/providers/Microsoft.Databricks/accessConnectors/dbac-uc-secrets-demo"}, "sha256_prefix": "<dummy-sha256-prefix>", "same_as_uc_read": true}, "L5_gateway": {"outcome": "bearer accepted by APIM; the upstream model failed (upstream_status 500)", "http_status": 502, "error_code": "INTERNAL_ERROR", "upstream_status": 500, "elapsed_s": 230.3, "message": "Model Provider Service returned error with status code 500: Internal server error. The model provider returned a server error — this is usually transient, so retry with backoff; if it persists, check the provider's status page."}}}
```

</details>

### Row 4: ws-eastus, serverless, vault open

`run_id` <run-or-timestamp-id> / task `run_id` <run-or-timestamp-id>, SUCCESS, started 2026-10-29 20:22:40 UTC.

**Parameters and helpers**

```text
run_label: vault open: ws-eastus serverless
workspace host: https://adb-<workspace-id-eastus>.15.azuredatabricks.net | SDK host: https://adb-<workspace-id-eastus>.15.azuredatabricks.net | databricks-sdk 0.122.0 | SDK HTTP timeout: 60 s | gateway client timeout: 360 s
```

**1. Where am I**

```text
[W1_workspace] workspace <workspace-id-eastus>  {"host": "https://adb-<workspace-id-eastus>.15.azuredatabricks.net", "sdk_host": "https://adb-<workspace-id-eastus>.15.azuredatabricks.net"}
[W2_metastore] metastore_azure_eastus (eastus)  {"metastore_id": "<metastore-id-eastus>", "cloud": "azure"}
[W3_compute] serverless  {"DATABRICKS_RUNTIME_VERSION": "client.6.5", "DATABRICKS_ENV_VERSION": "6", "spark": "4.2.0", "driver_ip": "<private-ip-3>", "driver_ip_rfc1918": true}
[W4_caller] <user>  {"workspace_admin": true}
```

**2. Catalog visibility, binding and the secret chain**

```text
[C1_catalog] catalog missing  {"exception": "NotFound", "message": "Catalog 'uc_secrets_demo' does not exist."}
[C2_catalog_bindings] catalog missing  {"exception": "NotFound", "message": "Catalog 'uc_secrets_demo' does not exist."}
[C3_secret_listing] catalog missing  {"exception": "NotFound", "message": "Catalog 'uc_secrets_demo' does not exist."}
[C4_connection] connection missing; vault name from the widget  {"vault_name": "kv-ucsec-<workspace-id>", "message": "Connection 'uc_secrets_demo_key_vault' does not exist."}
[C5_credential] credential missing  {"exception": "NotFound", "message": "Credential 'uc_secrets_demo' does not exist."}
vault under test: kv-ucsec-<workspace-id>.vault.azure.net
```

**3. UC read lane**

```text
expected failure, caught py4j.protocol.Py4JJavaError:
  : com.databricks.backend.daemon.driver.repl.ManagedCatalogServiceException: CATALOG_DOES_NOT_EXIST: Catalog 'uc_secrets_demo' does not exist.
[L1_uc_read_dbutils] catalog missing  {"exception": "py4j.protocol.Py4JJavaError", "message": ": com.databricks.backend.daemon.driver.repl.ManagedCatalogServiceException: CATALOG_DOES_NOT_EXIST: Catalog 'uc_secrets_demo' does not exist."}
[L1_uc_read_rest] catalog missing  {"http_status": 404, "error_code": "CATALOG_DOES_NOT_EXIST", "message": "Catalog 'uc_secrets_demo' does not exist."}
expected failure, caught py4j.protocol.Py4JJavaError:
  : com.databricks.backend.daemon.driver.repl.ManagedCatalogServiceException: CATALOG_DOES_NOT_EXIST: Catalog 'uc_secrets_demo' does not exist.
[L1_uc_read_real_hash] catalog missing  {"exception": "py4j.protocol.Py4JJavaError", "message": ": com.databricks.backend.daemon.driver.repl.ManagedCatalogServiceException: CATALOG_DOES_NOT_EXIST: Catalog 'uc_secrets_demo' does not exist."}
```

**4. Compute DNS lane**

```text
[L2_compute_dns] public address  {"canonical": "<kv-traffic-manager-canonical-a>", "aliases": ["kv-ucsec-<workspace-id>.vault.azure.net", "<kv-weu-alias-1>", "<kv-weu-alias-2>", "<kv-regional-alias-3>"], "addresses": {"<public-ip-4>": "public", "<public-ip-5>": "public", "<public-ip-6>": "public"}}
```

**5. Compute direct, no token**

```text
[L3_compute_unauth] HTTP 401 challenge: the vault answered this compute  {"http_status": 401, "www_authenticate_present": true, "www_authenticate_scheme": "Bearer", "error_code": "Unauthorized", "message": "AKV10000: Request is missing a Bearer, PoP, or MTLS_POP token."}
```

**6. Compute direct, with the identity Unity Catalog uses**

```text
[L4_compute_connector_token] credential missing  {"exception": "NotFound", "message": "Credential 'uc_secrets_demo' does not exist."}
```

**7. Unity Gateway lane**

```text
HTTP 404 after 0.2 s (0% of the 360 s client timeout)
error_code=NOT_FOUND upstream_status=None
message: 'uc_secrets_demo.secrets.litellm_via_apim' does not exist.
verdict: provider service not known to this workspace's gateway (404 NOT_FOUND)
[L5_gateway] provider service not known to this workspace's gateway (404 NOT_FOUND)  {"http_status": 404, "error_code": "NOT_FOUND", "upstream_status": null, "elapsed_s": 0.2, "message": "'uc_secrets_demo.secrets.litellm_via_apim' does not exist."}
```

**8. Summary**

```text
workspace <workspace-id-eastus> | metastore_azure_eastus (eastus) | serverless | driver <private-ip-3> | run_label vault open: ws-eastus serverless
vault kv-ucsec-<workspace-id>.vault.azure.net | catalog catalog missing | credential credential missing
lane                                     outcome
UC read, dbutils (dummy)                 catalog missing
UC read, REST include_value (dummy)      catalog missing
UC read, dbutils (real, hash only)       catalog missing
compute DNS                              public address
compute direct, no token                 HTTP 401 challenge: the vault answered this compute
compute direct, connector token          credential missing
Unity Gateway                            provider service not known to this workspace's gateway (404 NOT_FOUND)
```

<details><summary>Exit value (<code>dbutils.notebook.exit</code>)</summary>

```json
{"run_label": "vault open: ws-eastus serverless", "claims": {"W1_workspace": {"outcome": "workspace <workspace-id-eastus>", "host": "https://adb-<workspace-id-eastus>.15.azuredatabricks.net", "sdk_host": "https://adb-<workspace-id-eastus>.15.azuredatabricks.net"}, "W2_metastore": {"outcome": "metastore_azure_eastus (eastus)", "metastore_id": "<metastore-id-eastus>", "cloud": "azure"}, "W3_compute": {"outcome": "serverless", "DATABRICKS_RUNTIME_VERSION": "client.6.5", "DATABRICKS_ENV_VERSION": "6", "spark": "4.2.0", "driver_ip": "<private-ip-3>", "driver_ip_rfc1918": true}, "W4_caller": {"outcome": "<user>", "workspace_admin": true}, "C1_catalog": {"outcome": "catalog missing", "exception": "NotFound", "message": "Catalog 'uc_secrets_demo' does not exist."}, "C2_catalog_bindings": {"outcome": "catalog missing", "exception": "NotFound", "message": "Catalog 'uc_secrets_demo' does not exist."}, "C3_secret_listing": {"outcome": "catalog missing", "exception": "NotFound", "message": "Catalog 'uc_secrets_demo' does not exist."}, "C4_connection": {"outcome": "connection missing; vault name from the widget", "vault_name": "kv-ucsec-<workspace-id>", "message": "Connection 'uc_secrets_demo_key_vault' does not exist."}, "C5_credential": {"outcome": "credential missing", "exception": "NotFound", "message": "Credential 'uc_secrets_demo' does not exist."}, "L1_uc_read_dbutils": {"outcome": "catalog missing", "exception": "py4j.protocol.Py4JJavaError", "message": ": com.databricks.backend.daemon.driver.repl.ManagedCatalogServiceException: CATALOG_DOES_NOT_EXIST: Catalog 'uc_secrets_demo' does not exist."}, "L1_uc_read_rest": {"outcome": "catalog missing", "http_status": 404, "error_code": "CATALOG_DOES_NOT_EXIST", "message": "Catalog 'uc_secrets_demo' does not exist."}, "L1_uc_read_real_hash": {"outcome": "catalog missing", "exception": "py4j.protocol.Py4JJavaError", "message": ": com.databricks.backend.daemon.driver.repl.ManagedCatalogServiceException: CATALOG_DOES_NOT_EXIST: Catalog 'uc_secrets_demo' does not exist."}, "L2_compute_dns": {"outcome": "public address", "canonical": "<kv-traffic-manager-canonical-a>", "aliases": ["kv-ucsec-<workspace-id>.vault.azure.net", "<kv-weu-alias-1>", "<kv-weu-alias-2>", "<kv-regional-alias-3>"], "addresses": {"<public-ip-4>": "public", "<public-ip-5>": "public", "<public-ip-6>": "public"}}, "L3_compute_unauth": {"outcome": "HTTP 401 challenge: the vault answered this compute", "http_status": 401, "www_authenticate_present": true, "www_authenticate_scheme": "Bearer", "error_code": "Unauthorized", "message": "AKV10000: Request is missing a Bearer, PoP, or MTLS_POP token."}, "L4_compute_connector_token": {"outcome": "credential missing", "exception": "NotFound", "message": "Credential 'uc_secrets_demo' does not exist."}, "L5_gateway": {"outcome": "provider service not known to this workspace's gateway (404 NOT_FOUND)", "http_status": 404, "error_code": "NOT_FOUND", "upstream_status": null, "elapsed_s": 0.2, "message": "'uc_secrets_demo.secrets.litellm_via_apim' does not exist."}}}
```

</details>

### Row 5: ws-demo, serverless, vault locked

`run_id` <run-or-timestamp-id> / task `run_id` <run-or-timestamp-id>, SUCCESS, started 2026-10-29 20:36:07 UTC.

**Parameters and helpers**

```text
run_label: vault locked: ws-demo serverless
workspace host: https://adb-<workspace-id>.14.azuredatabricks.net | SDK host: https://adb-<workspace-id>.14.azuredatabricks.net | databricks-sdk 0.122.0 | SDK HTTP timeout: 60 s | gateway client timeout: 360 s
```

**1. Where am I**

```text
[W1_workspace] workspace <workspace-id>  {"host": "https://adb-<workspace-id>.14.azuredatabricks.net", "sdk_host": "https://adb-<workspace-id>.14.azuredatabricks.net"}
[W2_metastore] metastore_azure_westeurope (westeurope)  {"metastore_id": "<metastore-id>", "cloud": "azure"}
[W3_compute] serverless  {"DATABRICKS_RUNTIME_VERSION": "client.6.5", "DATABRICKS_ENV_VERSION": "6", "spark": "4.2.0", "driver_ip": "<private-ip-2>", "driver_ip_rfc1918": true}
[W4_caller] <user>  {"workspace_admin": true}
```

**2. Catalog visibility, binding and the secret chain**

```text
[C1_catalog] visible, isolation OPEN  {"metastore_id": "<metastore-id>"}
[C2_catalog_bindings] 0 workspace binding(s)  {"bindings": []}
[C3_secret_listing] 2 secret(s)  {"secrets": ["uc_secrets_demo.secrets.apimlanekey", "uc_secrets_demo.secrets.dummysecret"]}
[C4_connection] AZURE_KEY_VAULT -> vault kv-ucsec-<workspace-id>  {"credential": "uc_secrets_demo"}
[C5_credential] SERVICE credential, isolation ISOLATION_MODE_OPEN  {"access_connector_id": "/subscriptions/<subscription-id>/resourceGroups/rg-uc-secrets-demo/providers/Microsoft.Databricks/accessConnectors/dbac-uc-secrets-demo", "managed_identity_id": "/subscriptions/<subscription-id>/resourceGroups/rg-uc-secrets-demo/providers/Microsoft.ManagedIdentity/userAssignedIdentities/id-uc-secrets-demo"}
vault under test: kv-ucsec-<workspace-id>.vault.azure.net
```

**3. UC read lane**

```text
[L1_uc_read_dbutils] value ok  {"length": 20, "sha256_prefix": "<dummy-sha256-prefix>"}
[L1_uc_read_rest] value ok  {"length": 20, "sha256_prefix": "<dummy-sha256-prefix>"}
[L1_uc_read_real_hash] value ok  {"length": 64, "sha256_prefix": "<secret-sha256-prefix-1>"}
```

**4. Compute DNS lane**

```text
[L2_compute_dns] public address  {"canonical": "<kv-traffic-manager-canonical-b>", "aliases": ["kv-ucsec-<workspace-id>.vault.azure.net", "<kv-weu-alias-1>", "<kv-weu-alias-2>", "<kv-regional-alias-3>"], "addresses": {"<public-ip-4>": "public", "<public-ip-5>": "public", "<public-ip-6>": "public"}}
```

**5. Compute direct, no token**

```text
[L3_compute_unauth] HTTP 401 challenge: the vault answered this compute  {"http_status": 401, "www_authenticate_present": true, "www_authenticate_scheme": "Bearer", "error_code": "Unauthorized", "message": "AKV10000: Request is missing a Bearer, PoP, or MTLS_POP token."}
```

**6. Compute direct, with the identity Unity Catalog uses**

```text
token identity: {"oid": "<connector-oid>", "appid": "<connector-appid>", "idtyp": "app", "xms_mirid": "/subscriptions/<subscription-id>/resourceGroups/rg-uc-secrets-demo/providers/Microsoft.Databricks/accessConnectors/dbac-uc-secrets-demo"}
[L4_compute_connector_token] HTTP 200: value ok  {"token_identity": {"oid": "<connector-oid>", "appid": "<connector-appid>", "idtyp": "app", "xms_mirid": "/subscriptions/<subscription-id>/resourceGroups/rg-uc-secrets-demo/providers/Microsoft.Databricks/accessConnectors/dbac-uc-secrets-demo"}, "sha256_prefix": "<dummy-sha256-prefix>", "same_as_uc_read": true}
```

**7. Unity Gateway lane**

```text
HTTP 502 after 136.6 s (38% of the 360 s client timeout)
error_code=INTERNAL_ERROR upstream_status=500
message: Model Provider Service returned error with status code 500: litellm.APIError: APIError: OpenAIException - Connection error.. Received Model Group=<model-alias>
Available Model Group Fallbacks=None. The model provider returned a server error — this is usually transient, so retry with backoff; if it persists, check the provider's status page.
verdict: bearer accepted by APIM; the upstream model failed (upstream_status 500)
[L5_gateway] bearer accepted by APIM; the upstream model failed (upstream_status 500)  {"http_status": 502, "error_code": "INTERNAL_ERROR", "upstream_status": 500, "elapsed_s": 136.6, "message": "Model Provider Service returned error with status code 500: litellm.APIError: APIError: OpenAIException - Connection error.. Received Model Group=<model-alias>\nAvailable Model Group Fallbacks=None. The model provider returned a server error \u2014 this is usually transient, so retry with backoff; if it persists, check the provider's status page."}
```

**8. Summary**

```text
workspace <workspace-id> | metastore_azure_westeurope (westeurope) | serverless | driver <private-ip-2> | run_label vault locked: ws-demo serverless
vault kv-ucsec-<workspace-id>.vault.azure.net | catalog visible, isolation OPEN | credential SERVICE credential, isolation ISOLATION_MODE_OPEN
lane                                     outcome
UC read, dbutils (dummy)                 value ok
UC read, REST include_value (dummy)      value ok
UC read, dbutils (real, hash only)       value ok
compute DNS                              public address
compute direct, no token                 HTTP 401 challenge: the vault answered this compute
compute direct, connector token          HTTP 200: value ok
Unity Gateway                            bearer accepted by APIM; the upstream model failed (upstream_status 500)
```

<details><summary>Exit value (<code>dbutils.notebook.exit</code>)</summary>

```json
{"run_label": "vault locked: ws-demo serverless", "claims": {"W1_workspace": {"outcome": "workspace <workspace-id>", "host": "https://adb-<workspace-id>.14.azuredatabricks.net", "sdk_host": "https://adb-<workspace-id>.14.azuredatabricks.net"}, "W2_metastore": {"outcome": "metastore_azure_westeurope (westeurope)", "metastore_id": "<metastore-id>", "cloud": "azure"}, "W3_compute": {"outcome": "serverless", "DATABRICKS_RUNTIME_VERSION": "client.6.5", "DATABRICKS_ENV_VERSION": "6", "spark": "4.2.0", "driver_ip": "<private-ip-2>", "driver_ip_rfc1918": true}, "W4_caller": {"outcome": "<user>", "workspace_admin": true}, "C1_catalog": {"outcome": "visible, isolation OPEN", "metastore_id": "<metastore-id>"}, "C2_catalog_bindings": {"outcome": "0 workspace binding(s)", "bindings": []}, "C3_secret_listing": {"outcome": "2 secret(s)", "secrets": ["uc_secrets_demo.secrets.apimlanekey", "uc_secrets_demo.secrets.dummysecret"]}, "C4_connection": {"outcome": "AZURE_KEY_VAULT -> vault kv-ucsec-<workspace-id>", "credential": "uc_secrets_demo"}, "C5_credential": {"outcome": "SERVICE credential, isolation ISOLATION_MODE_OPEN", "access_connector_id": "/subscriptions/<subscription-id>/resourceGroups/rg-uc-secrets-demo/providers/Microsoft.Databricks/accessConnectors/dbac-uc-secrets-demo", "managed_identity_id": "/subscriptions/<subscription-id>/resourceGroups/rg-uc-secrets-demo/providers/Microsoft.ManagedIdentity/userAssignedIdentities/id-uc-secrets-demo"}, "L1_uc_read_dbutils": {"outcome": "value ok", "length": 20, "sha256_prefix": "<dummy-sha256-prefix>"}, "L1_uc_read_rest": {"outcome": "value ok", "length": 20, "sha256_prefix": "<dummy-sha256-prefix>"}, "L1_uc_read_real_hash": {"outcome": "value ok", "length": 64, "sha256_prefix": "<secret-sha256-prefix-1>"}, "L2_compute_dns": {"outcome": "public address", "canonical": "<kv-traffic-manager-canonical-b>", "aliases": ["kv-ucsec-<workspace-id>.vault.azure.net", "<kv-weu-alias-1>", "<kv-weu-alias-2>", "<kv-regional-alias-3>"], "addresses": {"<public-ip-4>": "public", "<public-ip-5>": "public", "<public-ip-6>": "public"}}, "L3_compute_unauth": {"outcome": "HTTP 401 challenge: the vault answered this compute", "http_status": 401, "www_authenticate_present": true, "www_authenticate_scheme": "Bearer", "error_code": "Unauthorized", "message": "AKV10000: Request is missing a Bearer, PoP, or MTLS_POP token."}, "L4_compute_connector_token": {"outcome": "HTTP 200: value ok", "token_identity": {"oid": "<connector-oid>", "appid": "<connector-appid>", "idtyp": "app", "xms_mirid": "/subscriptions/<subscription-id>/resourceGroups/rg-uc-secrets-demo/providers/Microsoft.Databricks/accessConnectors/dbac-uc-secrets-demo"}, "sha256_prefix": "<dummy-sha256-prefix>", "same_as_uc_read": true}, "L5_gateway": {"outcome": "bearer accepted by APIM; the upstream model failed (upstream_status 500)", "http_status": 502, "error_code": "INTERNAL_ERROR", "upstream_status": 500, "elapsed_s": 136.6, "message": "Model Provider Service returned error with status code 500: litellm.APIError: APIError: OpenAIException - Connection error.. Received Model Group=<model-alias>\nAvailable Model Group Fallbacks=None. The model provider returned a server error — this is usually transient, so retry with backoff; if it persists, check the provider's status page."}}}
```

</details>

### Row 6: ws-demo, classic, vault locked

`run_id` <run-or-timestamp-id> / task `run_id` <run-or-timestamp-id>, SUCCESS, started 2026-10-29 20:36:06 UTC.

**Parameters and helpers**

```text
run_label: vault locked: ws-demo classic
workspace host: https://adb-<workspace-id>.14.azuredatabricks.net | SDK host: https://<regional-control-plane-host> | databricks-sdk 0.67.0 | SDK HTTP timeout: 60 s | gateway client timeout: 360 s
```

**1. Where am I**

```text
[W1_workspace] workspace <workspace-id>  {"host": "https://adb-<workspace-id>.14.azuredatabricks.net", "sdk_host": "https://<regional-control-plane-host>"}
[W2_metastore] metastore_azure_westeurope (westeurope)  {"metastore_id": "<metastore-id>", "cloud": "azure"}
[W3_compute] classic  {"DATABRICKS_RUNTIME_VERSION": "18.3", "DATABRICKS_ENV_VERSION": null, "spark": "4.1.0", "cluster_id": "<cluster-id>", "node_type": "Standard_F4s_v2", "spark_version": "18.x-scala2.13", "driver_ip": "<classic-node-ip>", "driver_ip_rfc1918": true}
[W4_caller] <user>  {"workspace_admin": true}
```

**2. Catalog visibility, binding and the secret chain**

```text
[C1_catalog] visible, isolation OPEN  {"metastore_id": "<metastore-id>"}
[C2_catalog_bindings] 0 workspace binding(s)  {"bindings": []}
[C3_secret_listing] 2 secret(s)  {"secrets": ["uc_secrets_demo.secrets.apimlanekey", "uc_secrets_demo.secrets.dummysecret"]}
[C4_connection] AZURE_KEY_VAULT -> vault kv-ucsec-<workspace-id>  {"credential": "uc_secrets_demo"}
[C5_credential] SERVICE credential, isolation ISOLATION_MODE_OPEN  {"access_connector_id": "/subscriptions/<subscription-id>/resourceGroups/rg-uc-secrets-demo/providers/Microsoft.Databricks/accessConnectors/dbac-uc-secrets-demo", "managed_identity_id": "/subscriptions/<subscription-id>/resourceGroups/rg-uc-secrets-demo/providers/Microsoft.ManagedIdentity/userAssignedIdentities/id-uc-secrets-demo"}
vault under test: kv-ucsec-<workspace-id>.vault.azure.net
```

**3. UC read lane**

```text
[L1_uc_read_dbutils] value ok  {"length": 20, "sha256_prefix": "<dummy-sha256-prefix>"}
[L1_uc_read_rest] value ok  {"length": 20, "sha256_prefix": "<dummy-sha256-prefix>"}
[L1_uc_read_real_hash] value ok  {"length": 64, "sha256_prefix": "<secret-sha256-prefix-1>"}
```

**4. Compute DNS lane**

```text
[L2_compute_dns] public address  {"canonical": "<kv-traffic-manager-canonical-b>", "aliases": ["kv-ucsec-<workspace-id>.vault.azure.net", "<kv-weu-alias-1>", "<kv-weu-alias-2>", "<kv-regional-alias-3>"], "addresses": {"<public-ip-4>": "public", "<public-ip-5>": "public", "<public-ip-6>": "public"}}
```

**5. Compute direct, no token**

```text
[L3_compute_unauth] HTTP 401 challenge: the vault answered this compute  {"http_status": 401, "www_authenticate_present": true, "www_authenticate_scheme": "Bearer", "error_code": "Unauthorized", "message": "AKV10000: Request is missing a Bearer, PoP, or MTLS_POP token."}
```

**6. Compute direct, with the identity Unity Catalog uses**

```text
token identity: {"oid": "<connector-oid>", "appid": "<connector-appid>", "idtyp": "app", "xms_mirid": "/subscriptions/<subscription-id>/resourceGroups/rg-uc-secrets-demo/providers/Microsoft.Databricks/accessConnectors/dbac-uc-secrets-demo"}
[L4_compute_connector_token] HTTP 200: value ok  {"token_identity": {"oid": "<connector-oid>", "appid": "<connector-appid>", "idtyp": "app", "xms_mirid": "/subscriptions/<subscription-id>/resourceGroups/rg-uc-secrets-demo/providers/Microsoft.Databricks/accessConnectors/dbac-uc-secrets-demo"}, "sha256_prefix": "<dummy-sha256-prefix>", "same_as_uc_read": true}
```

**7. Unity Gateway lane**

```text
HTTP 429 after 1.0 s (0% of the 360 s client timeout)
error_code=REQUEST_LIMIT_EXCEEDED upstream_status=429
message: Model Provider Service returned error with status code 429: No deployments available for selected model, Try again in 60 seconds. Passed model=<model-alias>. pre-call-checks=False, cooldown_list=[('<litellm-deployment-id>', {'exception_received': 'No deployments available for selected model, Try again in 60 seconds. Passed model=<model-alias>. pre-call-checks=False, cooldown_list=[(\'<litellm-deployment-id>\', {\'exception_received\': "No deployments available for selected model, Try again in 60 seconds. Passed model=<model-alias>.…. The model provider rate-limited the request — retry with backoff or check the provider-side quota for this model.
verdict: unclassified
[L5_gateway] unclassified  {"http_status": 429, "error_code": "REQUEST_LIMIT_EXCEEDED", "upstream_status": 429, "elapsed_s": 1.0, "message": "Model Provider Service returned error with status code 429: No deployments available for selected model, Try again in 60 seconds. Passed model=<model-alias>. pre-call-checks=False, cooldown_list=[('<litellm-deployment-id>', {'exception_received': 'No deployments available for selected model, Try again in 60 seconds. Passed model=<model-alias>. pre-call-checks=False, cooldown_list=[(\\'<litellm-deployment-id>\\', {\\'exception_received\\': \"No deployments available for selected model, Try again in 60 seconds. Passed model=<model-alias>.\u2026. The model provider rate-limited the request \u2014 retry with backoff or check the provider-side quota for this model."}
```

**8. Summary**

```text
workspace <workspace-id> | metastore_azure_westeurope (westeurope) | classic | driver <classic-node-ip> | run_label vault locked: ws-demo classic
vault kv-ucsec-<workspace-id>.vault.azure.net | catalog visible, isolation OPEN | credential SERVICE credential, isolation ISOLATION_MODE_OPEN
lane                                     outcome
UC read, dbutils (dummy)                 value ok
UC read, REST include_value (dummy)      value ok
UC read, dbutils (real, hash only)       value ok
compute DNS                              public address
compute direct, no token                 HTTP 401 challenge: the vault answered this compute
compute direct, connector token          HTTP 200: value ok
Unity Gateway                            unclassified
```

<details><summary>Exit value (<code>dbutils.notebook.exit</code>)</summary>

```json
{"run_label": "vault locked: ws-demo classic", "claims": {"W1_workspace": {"outcome": "workspace <workspace-id>", "host": "https://adb-<workspace-id>.14.azuredatabricks.net", "sdk_host": "https://<regional-control-plane-host>"}, "W2_metastore": {"outcome": "metastore_azure_westeurope (westeurope)", "metastore_id": "<metastore-id>", "cloud": "azure"}, "W3_compute": {"outcome": "classic", "DATABRICKS_RUNTIME_VERSION": "18.3", "DATABRICKS_ENV_VERSION": null, "spark": "4.1.0", "cluster_id": "<cluster-id>", "node_type": "Standard_F4s_v2", "spark_version": "18.x-scala2.13", "driver_ip": "<classic-node-ip>", "driver_ip_rfc1918": true}, "W4_caller": {"outcome": "<user>", "workspace_admin": true}, "C1_catalog": {"outcome": "visible, isolation OPEN", "metastore_id": "<metastore-id>"}, "C2_catalog_bindings": {"outcome": "0 workspace binding(s)", "bindings": []}, "C3_secret_listing": {"outcome": "2 secret(s)", "secrets": ["uc_secrets_demo.secrets.apimlanekey", "uc_secrets_demo.secrets.dummysecret"]}, "C4_connection": {"outcome": "AZURE_KEY_VAULT -> vault kv-ucsec-<workspace-id>", "credential": "uc_secrets_demo"}, "C5_credential": {"outcome": "SERVICE credential, isolation ISOLATION_MODE_OPEN", "access_connector_id": "/subscriptions/<subscription-id>/resourceGroups/rg-uc-secrets-demo/providers/Microsoft.Databricks/accessConnectors/dbac-uc-secrets-demo", "managed_identity_id": "/subscriptions/<subscription-id>/resourceGroups/rg-uc-secrets-demo/providers/Microsoft.ManagedIdentity/userAssignedIdentities/id-uc-secrets-demo"}, "L1_uc_read_dbutils": {"outcome": "value ok", "length": 20, "sha256_prefix": "<dummy-sha256-prefix>"}, "L1_uc_read_rest": {"outcome": "value ok", "length": 20, "sha256_prefix": "<dummy-sha256-prefix>"}, "L1_uc_read_real_hash": {"outcome": "value ok", "length": 64, "sha256_prefix": "<secret-sha256-prefix-1>"}, "L2_compute_dns": {"outcome": "public address", "canonical": "<kv-traffic-manager-canonical-b>", "aliases": ["kv-ucsec-<workspace-id>.vault.azure.net", "<kv-weu-alias-1>", "<kv-weu-alias-2>", "<kv-regional-alias-3>"], "addresses": {"<public-ip-4>": "public", "<public-ip-5>": "public", "<public-ip-6>": "public"}}, "L3_compute_unauth": {"outcome": "HTTP 401 challenge: the vault answered this compute", "http_status": 401, "www_authenticate_present": true, "www_authenticate_scheme": "Bearer", "error_code": "Unauthorized", "message": "AKV10000: Request is missing a Bearer, PoP, or MTLS_POP token."}, "L4_compute_connector_token": {"outcome": "HTTP 200: value ok", "token_identity": {"oid": "<connector-oid>", "appid": "<connector-appid>", "idtyp": "app", "xms_mirid": "/subscriptions/<subscription-id>/resourceGroups/rg-uc-secrets-demo/providers/Microsoft.Databricks/accessConnectors/dbac-uc-secrets-demo"}, "sha256_prefix": "<dummy-sha256-prefix>", "same_as_uc_read": true}, "L5_gateway": {"outcome": "unclassified", "http_status": 429, "error_code": "REQUEST_LIMIT_EXCEEDED", "upstream_status": 429, "elapsed_s": 1.0, "message": "Model Provider Service returned error with status code 429: No deployments available for selected model, Try again in 60 seconds. Passed model=<model-alias>. pre-call-checks=False, cooldown_list=[('<litellm-deployment-id>', {'exception_received': 'No deployments available for selected model, Try again in 60 seconds. Passed model=<model-alias>. pre-call-checks=False, cooldown_list=[(\\'<litellm-deployment-id>\\', {\\'exception_received\\': \"No deployments available for selected model, Try again in 60 seconds. Passed model=<model-alias>.…. The model provider rate-limited the request — retry with backoff or check the provider-side quota for this model."}}}
```

</details>

### Row 7: ws-demo, classic, vault locked (second run)

`run_id` <run-or-timestamp-id> / task `run_id` <run-or-timestamp-id>, SUCCESS, started 2026-10-29 20:40:31 UTC.

**Parameters and helpers**

```text
run_label: vault locked: ws-demo classic (second run)
workspace host: https://adb-<workspace-id>.14.azuredatabricks.net | SDK host: https://<regional-control-plane-host> | databricks-sdk 0.67.0 | SDK HTTP timeout: 60 s | gateway client timeout: 360 s
```

**1. Where am I**

```text
[W1_workspace] workspace <workspace-id>  {"host": "https://adb-<workspace-id>.14.azuredatabricks.net", "sdk_host": "https://<regional-control-plane-host>"}
[W2_metastore] metastore_azure_westeurope (westeurope)  {"metastore_id": "<metastore-id>", "cloud": "azure"}
[W3_compute] classic  {"DATABRICKS_RUNTIME_VERSION": "18.3", "DATABRICKS_ENV_VERSION": null, "spark": "4.1.0", "cluster_id": "<cluster-id>", "node_type": "Standard_F4s_v2", "spark_version": "18.x-scala2.13", "driver_ip": "<classic-node-ip>", "driver_ip_rfc1918": true}
[W4_caller] <user>  {"workspace_admin": true}
```

**2. Catalog visibility, binding and the secret chain**

```text
[C1_catalog] visible, isolation OPEN  {"metastore_id": "<metastore-id>"}
[C2_catalog_bindings] 0 workspace binding(s)  {"bindings": []}
[C3_secret_listing] 2 secret(s)  {"secrets": ["uc_secrets_demo.secrets.apimlanekey", "uc_secrets_demo.secrets.dummysecret"]}
[C4_connection] AZURE_KEY_VAULT -> vault kv-ucsec-<workspace-id>  {"credential": "uc_secrets_demo"}
[C5_credential] SERVICE credential, isolation ISOLATION_MODE_OPEN  {"access_connector_id": "/subscriptions/<subscription-id>/resourceGroups/rg-uc-secrets-demo/providers/Microsoft.Databricks/accessConnectors/dbac-uc-secrets-demo", "managed_identity_id": "/subscriptions/<subscription-id>/resourceGroups/rg-uc-secrets-demo/providers/Microsoft.ManagedIdentity/userAssignedIdentities/id-uc-secrets-demo"}
vault under test: kv-ucsec-<workspace-id>.vault.azure.net
```

**3. UC read lane**

```text
[L1_uc_read_dbutils] value ok  {"length": 20, "sha256_prefix": "<dummy-sha256-prefix>"}
[L1_uc_read_rest] value ok  {"length": 20, "sha256_prefix": "<dummy-sha256-prefix>"}
[L1_uc_read_real_hash] value ok  {"length": 64, "sha256_prefix": "<secret-sha256-prefix-1>"}
```

**4. Compute DNS lane**

```text
[L2_compute_dns] public address  {"canonical": "<kv-traffic-manager-canonical-a>", "aliases": ["kv-ucsec-<workspace-id>.vault.azure.net", "<kv-weu-alias-1>", "<kv-weu-alias-2>", "<kv-regional-alias-3>"], "addresses": {"<public-ip-4>": "public", "<public-ip-5>": "public", "<public-ip-6>": "public"}}
```

**5. Compute direct, no token**

```text
[L3_compute_unauth] HTTP 401 challenge: the vault answered this compute  {"http_status": 401, "www_authenticate_present": true, "www_authenticate_scheme": "Bearer", "error_code": "Unauthorized", "message": "AKV10000: Request is missing a Bearer, PoP, or MTLS_POP token."}
```

**6. Compute direct, with the identity Unity Catalog uses**

```text
token identity: {"oid": "<connector-oid>", "appid": "<connector-appid>", "idtyp": "app", "xms_mirid": "/subscriptions/<subscription-id>/resourceGroups/rg-uc-secrets-demo/providers/Microsoft.Databricks/accessConnectors/dbac-uc-secrets-demo"}
[L4_compute_connector_token] HTTP 200: value ok  {"token_identity": {"oid": "<connector-oid>", "appid": "<connector-appid>", "idtyp": "app", "xms_mirid": "/subscriptions/<subscription-id>/resourceGroups/rg-uc-secrets-demo/providers/Microsoft.Databricks/accessConnectors/dbac-uc-secrets-demo"}, "sha256_prefix": "<dummy-sha256-prefix>", "same_as_uc_read": true}
```

**7. Unity Gateway lane**

```text
HTTP 502 after 230.7 s (64% of the 360 s client timeout)
error_code=INTERNAL_ERROR upstream_status=500
message: Model Provider Service returned error with status code 500: Internal server error. The model provider returned a server error — this is usually transient, so retry with backoff; if it persists, check the provider's status page.
verdict: bearer accepted by APIM; the upstream model failed (upstream_status 500)
[L5_gateway] bearer accepted by APIM; the upstream model failed (upstream_status 500)  {"http_status": 502, "error_code": "INTERNAL_ERROR", "upstream_status": 500, "elapsed_s": 230.7, "message": "Model Provider Service returned error with status code 500: Internal server error. The model provider returned a server error \u2014 this is usually transient, so retry with backoff; if it persists, check the provider's status page."}
```

**8. Summary**

```text
workspace <workspace-id> | metastore_azure_westeurope (westeurope) | classic | driver <classic-node-ip> | run_label vault locked: ws-demo classic (second run)
vault kv-ucsec-<workspace-id>.vault.azure.net | catalog visible, isolation OPEN | credential SERVICE credential, isolation ISOLATION_MODE_OPEN
lane                                     outcome
UC read, dbutils (dummy)                 value ok
UC read, REST include_value (dummy)      value ok
UC read, dbutils (real, hash only)       value ok
compute DNS                              public address
compute direct, no token                 HTTP 401 challenge: the vault answered this compute
compute direct, connector token          HTTP 200: value ok
Unity Gateway                            bearer accepted by APIM; the upstream model failed (upstream_status 500)
```

<details><summary>Exit value (<code>dbutils.notebook.exit</code>)</summary>

```json
{"run_label": "vault locked: ws-demo classic (second run)", "claims": {"W1_workspace": {"outcome": "workspace <workspace-id>", "host": "https://adb-<workspace-id>.14.azuredatabricks.net", "sdk_host": "https://<regional-control-plane-host>"}, "W2_metastore": {"outcome": "metastore_azure_westeurope (westeurope)", "metastore_id": "<metastore-id>", "cloud": "azure"}, "W3_compute": {"outcome": "classic", "DATABRICKS_RUNTIME_VERSION": "18.3", "DATABRICKS_ENV_VERSION": null, "spark": "4.1.0", "cluster_id": "<cluster-id>", "node_type": "Standard_F4s_v2", "spark_version": "18.x-scala2.13", "driver_ip": "<classic-node-ip>", "driver_ip_rfc1918": true}, "W4_caller": {"outcome": "<user>", "workspace_admin": true}, "C1_catalog": {"outcome": "visible, isolation OPEN", "metastore_id": "<metastore-id>"}, "C2_catalog_bindings": {"outcome": "0 workspace binding(s)", "bindings": []}, "C3_secret_listing": {"outcome": "2 secret(s)", "secrets": ["uc_secrets_demo.secrets.apimlanekey", "uc_secrets_demo.secrets.dummysecret"]}, "C4_connection": {"outcome": "AZURE_KEY_VAULT -> vault kv-ucsec-<workspace-id>", "credential": "uc_secrets_demo"}, "C5_credential": {"outcome": "SERVICE credential, isolation ISOLATION_MODE_OPEN", "access_connector_id": "/subscriptions/<subscription-id>/resourceGroups/rg-uc-secrets-demo/providers/Microsoft.Databricks/accessConnectors/dbac-uc-secrets-demo", "managed_identity_id": "/subscriptions/<subscription-id>/resourceGroups/rg-uc-secrets-demo/providers/Microsoft.ManagedIdentity/userAssignedIdentities/id-uc-secrets-demo"}, "L1_uc_read_dbutils": {"outcome": "value ok", "length": 20, "sha256_prefix": "<dummy-sha256-prefix>"}, "L1_uc_read_rest": {"outcome": "value ok", "length": 20, "sha256_prefix": "<dummy-sha256-prefix>"}, "L1_uc_read_real_hash": {"outcome": "value ok", "length": 64, "sha256_prefix": "<secret-sha256-prefix-1>"}, "L2_compute_dns": {"outcome": "public address", "canonical": "<kv-traffic-manager-canonical-a>", "aliases": ["kv-ucsec-<workspace-id>.vault.azure.net", "<kv-weu-alias-1>", "<kv-weu-alias-2>", "<kv-regional-alias-3>"], "addresses": {"<public-ip-4>": "public", "<public-ip-5>": "public", "<public-ip-6>": "public"}}, "L3_compute_unauth": {"outcome": "HTTP 401 challenge: the vault answered this compute", "http_status": 401, "www_authenticate_present": true, "www_authenticate_scheme": "Bearer", "error_code": "Unauthorized", "message": "AKV10000: Request is missing a Bearer, PoP, or MTLS_POP token."}, "L4_compute_connector_token": {"outcome": "HTTP 200: value ok", "token_identity": {"oid": "<connector-oid>", "appid": "<connector-appid>", "idtyp": "app", "xms_mirid": "/subscriptions/<subscription-id>/resourceGroups/rg-uc-secrets-demo/providers/Microsoft.Databricks/accessConnectors/dbac-uc-secrets-demo"}, "sha256_prefix": "<dummy-sha256-prefix>", "same_as_uc_read": true}, "L5_gateway": {"outcome": "bearer accepted by APIM; the upstream model failed (upstream_status 500)", "http_status": 502, "error_code": "INTERNAL_ERROR", "upstream_status": 500, "elapsed_s": 230.7, "message": "Model Provider Service returned error with status code 500: Internal server error. The model provider returned a server error — this is usually transient, so retry with backoff; if it persists, check the provider's status page."}}}
```

</details>

### Row 8: ws-weu-managed, serverless, vault locked

`run_id` <run-or-timestamp-id> / task `run_id` <run-or-timestamp-id>, SUCCESS, started 2026-10-29 20:36:08 UTC.

**Parameters and helpers**

```text
run_label: vault locked: ws-weu-managed serverless
workspace host: https://adb-<workspace-id-managed-vnet>.19.azuredatabricks.net | SDK host: https://adb-<workspace-id-managed-vnet>.19.azuredatabricks.net | databricks-sdk 0.122.0 | SDK HTTP timeout: 60 s | gateway client timeout: 360 s
```

**1. Where am I**

```text
[W1_workspace] workspace <workspace-id-managed-vnet>  {"host": "https://adb-<workspace-id-managed-vnet>.19.azuredatabricks.net", "sdk_host": "https://adb-<workspace-id-managed-vnet>.19.azuredatabricks.net"}
[W2_metastore] metastore_azure_westeurope (westeurope)  {"metastore_id": "<metastore-id>", "cloud": "azure"}
[W3_compute] serverless  {"DATABRICKS_RUNTIME_VERSION": "client.6.5", "DATABRICKS_ENV_VERSION": "6", "spark": "4.2.0", "driver_ip": "<private-ip-2>", "driver_ip_rfc1918": true}
[W4_caller] <user>  {"workspace_admin": true}
```

**2. Catalog visibility, binding and the secret chain**

```text
[C1_catalog] visible, isolation OPEN  {"metastore_id": "<metastore-id>"}
[C2_catalog_bindings] 0 workspace binding(s)  {"bindings": []}
[C3_secret_listing] 2 secret(s)  {"secrets": ["uc_secrets_demo.secrets.apimlanekey", "uc_secrets_demo.secrets.dummysecret"]}
[C4_connection] AZURE_KEY_VAULT -> vault kv-ucsec-<workspace-id>  {"credential": "uc_secrets_demo"}
[C5_credential] SERVICE credential, isolation ISOLATION_MODE_OPEN  {"access_connector_id": "/subscriptions/<subscription-id>/resourceGroups/rg-uc-secrets-demo/providers/Microsoft.Databricks/accessConnectors/dbac-uc-secrets-demo", "managed_identity_id": "/subscriptions/<subscription-id>/resourceGroups/rg-uc-secrets-demo/providers/Microsoft.ManagedIdentity/userAssignedIdentities/id-uc-secrets-demo"}
vault under test: kv-ucsec-<workspace-id>.vault.azure.net
```

**3. UC read lane**

```text
[L1_uc_read_dbutils] value ok  {"length": 20, "sha256_prefix": "<dummy-sha256-prefix>"}
[L1_uc_read_rest] value ok  {"length": 20, "sha256_prefix": "<dummy-sha256-prefix>"}
[L1_uc_read_real_hash] value ok  {"length": 64, "sha256_prefix": "<secret-sha256-prefix-1>"}
```

**4. Compute DNS lane**

```text
[L2_compute_dns] public address  {"canonical": "<kv-traffic-manager-canonical-b>", "aliases": ["kv-ucsec-<workspace-id>.vault.azure.net", "<kv-weu-alias-1>", "<kv-weu-alias-2>", "<kv-regional-alias-3>"], "addresses": {"<public-ip-4>": "public", "<public-ip-5>": "public", "<public-ip-6>": "public"}}
```

**5. Compute direct, no token**

```text
[L3_compute_unauth] HTTP 401 challenge: the vault answered this compute  {"http_status": 401, "www_authenticate_present": true, "www_authenticate_scheme": "Bearer", "error_code": "Unauthorized", "message": "AKV10000: Request is missing a Bearer, PoP, or MTLS_POP token."}
```

**6. Compute direct, with the identity Unity Catalog uses**

```text
token identity: {"oid": "<connector-oid>", "appid": "<connector-appid>", "idtyp": "app", "xms_mirid": "/subscriptions/<subscription-id>/resourceGroups/rg-uc-secrets-demo/providers/Microsoft.Databricks/accessConnectors/dbac-uc-secrets-demo"}
[L4_compute_connector_token] HTTP 200: value ok  {"token_identity": {"oid": "<connector-oid>", "appid": "<connector-appid>", "idtyp": "app", "xms_mirid": "/subscriptions/<subscription-id>/resourceGroups/rg-uc-secrets-demo/providers/Microsoft.Databricks/accessConnectors/dbac-uc-secrets-demo"}, "sha256_prefix": "<dummy-sha256-prefix>", "same_as_uc_read": true}
```

**7. Unity Gateway lane**

```text
HTTP 502 after 136.0 s (38% of the 360 s client timeout)
error_code=INTERNAL_ERROR upstream_status=500
message: Model Provider Service returned error with status code 500: litellm.APIError: APIError: OpenAIException - Connection error.. Received Model Group=<model-alias>
Available Model Group Fallbacks=None. The model provider returned a server error — this is usually transient, so retry with backoff; if it persists, check the provider's status page.
verdict: bearer accepted by APIM; the upstream model failed (upstream_status 500)
[L5_gateway] bearer accepted by APIM; the upstream model failed (upstream_status 500)  {"http_status": 502, "error_code": "INTERNAL_ERROR", "upstream_status": 500, "elapsed_s": 136.0, "message": "Model Provider Service returned error with status code 500: litellm.APIError: APIError: OpenAIException - Connection error.. Received Model Group=<model-alias>\nAvailable Model Group Fallbacks=None. The model provider returned a server error \u2014 this is usually transient, so retry with backoff; if it persists, check the provider's status page."}
```

**8. Summary**

```text
workspace <workspace-id-managed-vnet> | metastore_azure_westeurope (westeurope) | serverless | driver <private-ip-2> | run_label vault locked: ws-weu-managed serverless
vault kv-ucsec-<workspace-id>.vault.azure.net | catalog visible, isolation OPEN | credential SERVICE credential, isolation ISOLATION_MODE_OPEN
lane                                     outcome
UC read, dbutils (dummy)                 value ok
UC read, REST include_value (dummy)      value ok
UC read, dbutils (real, hash only)       value ok
compute DNS                              public address
compute direct, no token                 HTTP 401 challenge: the vault answered this compute
compute direct, connector token          HTTP 200: value ok
Unity Gateway                            bearer accepted by APIM; the upstream model failed (upstream_status 500)
```

<details><summary>Exit value (<code>dbutils.notebook.exit</code>)</summary>

```json
{"run_label": "vault locked: ws-weu-managed serverless", "claims": {"W1_workspace": {"outcome": "workspace <workspace-id-managed-vnet>", "host": "https://adb-<workspace-id-managed-vnet>.19.azuredatabricks.net", "sdk_host": "https://adb-<workspace-id-managed-vnet>.19.azuredatabricks.net"}, "W2_metastore": {"outcome": "metastore_azure_westeurope (westeurope)", "metastore_id": "<metastore-id>", "cloud": "azure"}, "W3_compute": {"outcome": "serverless", "DATABRICKS_RUNTIME_VERSION": "client.6.5", "DATABRICKS_ENV_VERSION": "6", "spark": "4.2.0", "driver_ip": "<private-ip-2>", "driver_ip_rfc1918": true}, "W4_caller": {"outcome": "<user>", "workspace_admin": true}, "C1_catalog": {"outcome": "visible, isolation OPEN", "metastore_id": "<metastore-id>"}, "C2_catalog_bindings": {"outcome": "0 workspace binding(s)", "bindings": []}, "C3_secret_listing": {"outcome": "2 secret(s)", "secrets": ["uc_secrets_demo.secrets.apimlanekey", "uc_secrets_demo.secrets.dummysecret"]}, "C4_connection": {"outcome": "AZURE_KEY_VAULT -> vault kv-ucsec-<workspace-id>", "credential": "uc_secrets_demo"}, "C5_credential": {"outcome": "SERVICE credential, isolation ISOLATION_MODE_OPEN", "access_connector_id": "/subscriptions/<subscription-id>/resourceGroups/rg-uc-secrets-demo/providers/Microsoft.Databricks/accessConnectors/dbac-uc-secrets-demo", "managed_identity_id": "/subscriptions/<subscription-id>/resourceGroups/rg-uc-secrets-demo/providers/Microsoft.ManagedIdentity/userAssignedIdentities/id-uc-secrets-demo"}, "L1_uc_read_dbutils": {"outcome": "value ok", "length": 20, "sha256_prefix": "<dummy-sha256-prefix>"}, "L1_uc_read_rest": {"outcome": "value ok", "length": 20, "sha256_prefix": "<dummy-sha256-prefix>"}, "L1_uc_read_real_hash": {"outcome": "value ok", "length": 64, "sha256_prefix": "<secret-sha256-prefix-1>"}, "L2_compute_dns": {"outcome": "public address", "canonical": "<kv-traffic-manager-canonical-b>", "aliases": ["kv-ucsec-<workspace-id>.vault.azure.net", "<kv-weu-alias-1>", "<kv-weu-alias-2>", "<kv-regional-alias-3>"], "addresses": {"<public-ip-4>": "public", "<public-ip-5>": "public", "<public-ip-6>": "public"}}, "L3_compute_unauth": {"outcome": "HTTP 401 challenge: the vault answered this compute", "http_status": 401, "www_authenticate_present": true, "www_authenticate_scheme": "Bearer", "error_code": "Unauthorized", "message": "AKV10000: Request is missing a Bearer, PoP, or MTLS_POP token."}, "L4_compute_connector_token": {"outcome": "HTTP 200: value ok", "token_identity": {"oid": "<connector-oid>", "appid": "<connector-appid>", "idtyp": "app", "xms_mirid": "/subscriptions/<subscription-id>/resourceGroups/rg-uc-secrets-demo/providers/Microsoft.Databricks/accessConnectors/dbac-uc-secrets-demo"}, "sha256_prefix": "<dummy-sha256-prefix>", "same_as_uc_read": true}, "L5_gateway": {"outcome": "bearer accepted by APIM; the upstream model failed (upstream_status 500)", "http_status": 502, "error_code": "INTERNAL_ERROR", "upstream_status": 500, "elapsed_s": 136.0, "message": "Model Provider Service returned error with status code 500: litellm.APIError: APIError: OpenAIException - Connection error.. Received Model Group=<model-alias>\nAvailable Model Group Fallbacks=None. The model provider returned a server error — this is usually transient, so retry with backoff; if it persists, check the provider's status page."}}}
```

</details>

### Row 9: ws-demo, serverless, vault sealed + NCC

`run_id` <run-or-timestamp-id> / task `run_id` <run-or-timestamp-id>, SUCCESS, submitted 2026-10-29 21:10:52 UTC, ended 21:11:23: every lane failed fast, so no gateway wait.

**Parameters and helpers**

```text
run_label: vault sealed + NCC: ws-demo serverless
workspace host: https://adb-<workspace-id>.14.azuredatabricks.net | SDK host: https://adb-<workspace-id>.14.azuredatabricks.net | databricks-sdk 0.122.0 | SDK HTTP timeout: 60 s | gateway client timeout: 360 s
```

**1. Where am I**

```text
[W1_workspace] workspace <workspace-id>  {"host": "https://adb-<workspace-id>.14.azuredatabricks.net", "sdk_host": "https://adb-<workspace-id>.14.azuredatabricks.net"}
[W2_metastore] metastore_azure_westeurope (westeurope)  {"metastore_id": "<metastore-id>", "cloud": "azure"}
[W3_compute] serverless  {"DATABRICKS_RUNTIME_VERSION": "client.6.5", "DATABRICKS_ENV_VERSION": "6", "spark": "4.2.0", "driver_ip": "<private-ip-2>", "driver_ip_rfc1918": true}
[W4_caller] <user>  {"workspace_admin": true}
```

**2. Catalog visibility, binding and the secret chain**

```text
[C1_catalog] visible, isolation OPEN  {"metastore_id": "<metastore-id>"}
[C2_catalog_bindings] 0 workspace binding(s)  {"bindings": []}
[C3_secret_listing] 2 secret(s)  {"secrets": ["uc_secrets_demo.secrets.apimlanekey", "uc_secrets_demo.secrets.dummysecret"]}
[C4_connection] AZURE_KEY_VAULT -> vault kv-ucsec-<workspace-id>  {"credential": "uc_secrets_demo"}
[C5_credential] SERVICE credential, isolation ISOLATION_MODE_OPEN  {"access_connector_id": "/subscriptions/<subscription-id>/resourceGroups/rg-uc-secrets-demo/providers/Microsoft.Databricks/accessConnectors/dbac-uc-secrets-demo", "managed_identity_id": "/subscriptions/<subscription-id>/resourceGroups/rg-uc-secrets-demo/providers/Microsoft.ManagedIdentity/userAssignedIdentities/id-uc-secrets-demo"}
vault under test: kv-ucsec-<workspace-id>.vault.azure.net
```

**3. UC read lane**

```text
expected failure, caught py4j.protocol.Py4JJavaError:
  : com.databricks.backend.daemon.driver.repl.ManagedCatalogServiceException: PERMISSION_DENIED: the cloud provider returned access denied, check the configuration of the service credential
[L1_uc_read_dbutils] Key Vault refused the service credential  {"exception": "py4j.protocol.Py4JJavaError", "message": ": com.databricks.backend.daemon.driver.repl.ManagedCatalogServiceException: PERMISSION_DENIED: the cloud provider returned access denied, check the configuration of the service credential"}
[L1_uc_read_rest] refused (HTTP 403 PERMISSION_DENIED)  {"http_status": 403, "error_code": "PERMISSION_DENIED", "message": "the cloud provider returned access denied, check the configuration of the service credential"}
expected failure, caught py4j.protocol.Py4JJavaError:
  : com.databricks.backend.daemon.driver.repl.ManagedCatalogServiceException: PERMISSION_DENIED: the cloud provider returned access denied, check the configuration of the service credential
[L1_uc_read_real_hash] Key Vault refused the service credential  {"exception": "py4j.protocol.Py4JJavaError", "message": ": com.databricks.backend.daemon.driver.repl.ManagedCatalogServiceException: PERMISSION_DENIED: the cloud provider returned access denied, check the configuration of the service credential"}
```

**4. Compute DNS lane**

```text
[L2_compute_dns] public address  {"canonical": "<kv-traffic-manager-canonical>", "aliases": ["kv-ucsec-<workspace-id>.vault.azure.net", "<kv-privatelink-alias>", "<kv-weu-alias-2>", "<kv-regional-alias-3>", "<kv-identity-alias-4>"], "addresses": {"<public-ip-4>": "public", "<public-ip-5>": "public", "<public-ip-6>": "public"}}
```

**5. Compute direct, no token**

```text
[L3_compute_unauth] HTTP 401 challenge: the vault answered this compute  {"http_status": 401, "www_authenticate_present": true, "www_authenticate_scheme": "Bearer", "error_code": "Unauthorized", "message": "AKV10000: Request is missing a Bearer, PoP, or MTLS_POP token."}
```

**6. Compute direct, with the identity Unity Catalog uses**

```text
token identity: {"oid": "<connector-oid>", "appid": "<connector-appid>", "idtyp": "app", "xms_mirid": "/subscriptions/<subscription-id>/resourceGroups/rg-uc-secrets-demo/providers/Microsoft.Databricks/accessConnectors/dbac-uc-secrets-demo"}
[L4_compute_connector_token] HTTP 403 Forbidden  {"token_identity": {"oid": "<connector-oid>", "appid": "<connector-appid>", "idtyp": "app", "xms_mirid": "/subscriptions/<subscription-id>/resourceGroups/rg-uc-secrets-demo/providers/Microsoft.Databricks/accessConnectors/dbac-uc-secrets-demo"}, "message": "Connection is not an approved private link and caller was ignored because bypass is not set to 'AzureServices' and PublicNetworkAccess is set to 'Disabled'. \r\nVault: kv-ucsec-<workspace-id>;location=westeurope", "inner_code": "ForbiddenByConnection"}
```

**7. Unity Gateway lane**

```text
HTTP 403 after 0.9 s (0% of the 360 s client timeout)
error_code=PERMISSION_DENIED upstream_status=None
message: the cloud provider returned access denied, check the configuration of the service credential
verdict: denied by Databricks (no EXECUTE, or the secret could not be resolved)
[L5_gateway] denied by Databricks (no EXECUTE, or the secret could not be resolved)  {"http_status": 403, "error_code": "PERMISSION_DENIED", "upstream_status": null, "elapsed_s": 0.9, "message": "the cloud provider returned access denied, check the configuration of the service credential"}
```

**8. Summary**

```text
workspace <workspace-id> | metastore_azure_westeurope (westeurope) | serverless | driver <private-ip-2> | run_label vault sealed + NCC: ws-demo serverless
vault kv-ucsec-<workspace-id>.vault.azure.net | catalog visible, isolation OPEN | credential SERVICE credential, isolation ISOLATION_MODE_OPEN
lane                                     outcome
UC read, dbutils (dummy)                 Key Vault refused the service credential
UC read, REST include_value (dummy)      refused (HTTP 403 PERMISSION_DENIED)
UC read, dbutils (real, hash only)       Key Vault refused the service credential
compute DNS                              public address
compute direct, no token                 HTTP 401 challenge: the vault answered this compute
compute direct, connector token          HTTP 403 Forbidden
Unity Gateway                            denied by Databricks (no EXECUTE, or the secret could not be resolved)
```
```text
{"run_label": "vault sealed + NCC: ws-demo serverless", "claims": {"W1_workspace": {"outcome": "workspace <workspace-id>", "host": "https://adb-<workspace-id>.14.azuredatabricks.net", "sdk_host": "https://adb-<workspace-id>.14.azuredatabricks.net"}, "W2_metastore": {"outcome": "metastore_azure_westeurope (westeurope)", "metastore_id": "<metastore-id>", "cloud": "azure"}, "W3_compute": {"outcome": "serverless", "DATABRICKS_RUNTIME_VERSION": "client.6.5", "DATABRICKS_ENV_VERSION": "6", "spark": "4.2.0", "driver_ip": "<private-ip-2>", "driver_ip_rfc1918": true}, "W4_caller": {"outcome": "<user>", "workspace_admin": true}, "C1_catalog": {"outcome": "visible, isolation OPEN", "metastore_id": "<metastore-id>"}, "C2_catalog_bindings": {"outcome": "0 workspace binding(s)", "bindings": []}, "C3_secret_listing": {"outcome": "2 secret(s)", "secrets": ["uc_secrets_demo.secrets.apimlanekey", "uc_secrets_demo.secrets.dummysecret"]}, "C4_connection": {"outcome": "AZURE_KEY_VAULT -> vault kv-ucsec-<workspace-id>", "credential": "uc_secrets_demo"}, "C5_credential": {"outcome": "SERVICE credential, isolation ISOLATION_MODE_OPEN", "access_connector_id": "/subscriptions/<subscription-id>/resourceGroups/rg-uc-secrets-demo/providers/Microsoft.Databricks/accessConnectors/dbac-uc-secrets-demo", "managed_identity_id": "/subscriptions/<subscription-id>/resourceGroups/rg-uc-secrets-demo/providers/Microsoft.ManagedIdentity/userAssignedIdentities/id-uc-secrets-demo"}, "L1_uc_read_dbutils": {"outcome": "Key Vault refused the service credential", "exception": "py4j.protocol.Py4JJavaError", "message": ": com.databricks.backend.daemon.driver.repl.ManagedCatalogServiceException: PERMISSION_DENIED: the cloud provider returned access denied, check the configuration of the service credential"}, "L1_uc_read_rest": {"outcome": "refused (HTTP 403 PERMISSION_DENIED)", "http_status": 403, "error_code": "PERMISSION_DENIED", "message": "the cloud provider returned access denied, check the configuration of the service credential"}, "L1_uc_read_real_hash": {"outcome": "Key Vault refused the service credential", "exception": "py4j.protocol.Py4JJavaError", "message": ": com.databricks.backend.daemon.driver.repl.ManagedCatalogServiceException: PERMISSION_DENIED: the cloud provider returned access denied, check the configuration of the service credential"}, "L2_compute_dns": {"outcome": "public address", "canonical": "<kv-traffic-manager-canonical>", "aliases": ["kv-ucsec-<workspace-id>.vault.azure.net", "<kv-privatelink-alias>", "<kv-weu-alias-2>", "<kv-regional-alias-3>", "<kv-identity-alias-4>"], "addresses": {"<public-ip-4>": "public", "<public-ip-5>": "public", "<public-ip-6>": "public"}}, "L3_compute_unauth": {"outcome": "HTTP 401 challenge: the vault answered this compute", "http_status": 401, "www_authenticate_present": true, "www_authenticate_scheme": "Bearer", "error_code": "Unauthorized", "message": "AKV10000: Request is missing a Bearer, PoP, or MTLS_POP token."}, "L4_compute_connector_token": {"outcome": "HTTP 403 Forbidden", "token_identity": {"oid": "<connector-oid>", "appid": "<connector-appid>", "idtyp": "app", "xms_mirid": "/subscriptions/<subscription-id>/resourceGroups/rg-uc-secrets-demo/providers/Microsoft.Databricks/accessConnectors/dbac-uc-secrets-demo"}, "message": "Connection is not an approved private link and caller was ignored because bypass is not set to 'AzureServices' and PublicNetworkAccess is set to 'Disabled'. \r\nVault: kv-ucsec-<workspace-id>;location=westeurope", "inner_code": "ForbiddenByConnection"}, "L5_gateway": {"outcome": "denied by Databricks (no EXECUTE, or the secret could not be resolved)", "http_status": 403, "error_code": "PERMISSION_DENIED", "upstream_status": null, "elapsed_s": 0.9, "message": "the cloud provider returned access denied, check the configuration of the service credential"}}}
```


### Row 10: ws-demo, classic, vault sealed + NCC

`run_id` <run-or-timestamp-id> / task `run_id` <run-or-timestamp-id>, SUCCESS, submitted 2026-10-29 21:10:52 UTC, ended 21:21:31 (cluster setup included).

**Parameters and helpers**

```text
run_label: vault sealed + NCC: ws-demo classic
workspace host: https://adb-<workspace-id>.14.azuredatabricks.net | SDK host: <regional-control-plane-host> | databricks-sdk 0.67.0 | SDK HTTP timeout: 60 s | gateway client timeout: 360 s
```

**1. Where am I**

```text
[W1_workspace] workspace <workspace-id>  {"host": "https://adb-<workspace-id>.14.azuredatabricks.net", "sdk_host": "<regional-control-plane-host>"}
[W2_metastore] metastore_azure_westeurope (westeurope)  {"metastore_id": "<metastore-id>", "cloud": "azure"}
[W3_compute] classic  {"DATABRICKS_RUNTIME_VERSION": "18.3", "DATABRICKS_ENV_VERSION": null, "spark": "4.1.0", "cluster_id": "<cluster-id>", "node_type": "Standard_F4s_v2", "spark_version": "18.x-scala2.13", "driver_ip": "<classic-node-ip>", "driver_ip_rfc1918": true}
[W4_caller] <user>  {"workspace_admin": true}
```

**2. Catalog visibility, binding and the secret chain**

```text
[C1_catalog] visible, isolation OPEN  {"metastore_id": "<metastore-id>"}
[C2_catalog_bindings] 0 workspace binding(s)  {"bindings": []}
[C3_secret_listing] 2 secret(s)  {"secrets": ["uc_secrets_demo.secrets.apimlanekey", "uc_secrets_demo.secrets.dummysecret"]}
[C4_connection] AZURE_KEY_VAULT -> vault kv-ucsec-<workspace-id>  {"credential": "uc_secrets_demo"}
[C5_credential] SERVICE credential, isolation ISOLATION_MODE_OPEN  {"access_connector_id": "/subscriptions/<subscription-id>/resourceGroups/rg-uc-secrets-demo/providers/Microsoft.Databricks/accessConnectors/dbac-uc-secrets-demo", "managed_identity_id": "/subscriptions/<subscription-id>/resourceGroups/rg-uc-secrets-demo/providers/Microsoft.ManagedIdentity/userAssignedIdentities/id-uc-secrets-demo"}
vault under test: kv-ucsec-<workspace-id>.vault.azure.net
```

**3. UC read lane**

```text
expected failure, caught py4j.protocol.Py4JJavaError:
  : com.databricks.sql.managedcatalog.acl.UnauthorizedAccessException: PERMISSION_DENIED: the cloud provider returned access denied, check the configuration of the service credential
[L1_uc_read_dbutils] Key Vault refused the service credential  {"exception": "py4j.protocol.Py4JJavaError", "message": ": com.databricks.sql.managedcatalog.acl.UnauthorizedAccessException: PERMISSION_DENIED: the cloud provider returned access denied, check the configuration of the service credential"}
[L1_uc_read_rest] refused (HTTP 403 PERMISSION_DENIED)  {"http_status": 403, "error_code": "PERMISSION_DENIED", "message": "the cloud provider returned access denied, check the configuration of the service credential"}
expected failure, caught py4j.protocol.Py4JJavaError:
  : com.databricks.sql.managedcatalog.acl.UnauthorizedAccessException: PERMISSION_DENIED: the cloud provider returned access denied, check the configuration of the service credential
[L1_uc_read_real_hash] Key Vault refused the service credential  {"exception": "py4j.protocol.Py4JJavaError", "message": ": com.databricks.sql.managedcatalog.acl.UnauthorizedAccessException: PERMISSION_DENIED: the cloud provider returned access denied, check the configuration of the service credential"}
```

**4. Compute DNS lane**

```text
[L2_compute_dns] public address  {"canonical": "<kv-traffic-manager-canonical>", "aliases": ["kv-ucsec-<workspace-id>.vault.azure.net", "<kv-privatelink-alias>", "<kv-weu-alias-2>", "<kv-regional-alias-3>", "<kv-identity-alias-4>"], "addresses": {"<public-ip-4>": "public", "<public-ip-5>": "public", "<public-ip-6>": "public"}}
```

**5. Compute direct, no token**

```text
[L3_compute_unauth] HTTP 401 challenge: the vault answered this compute  {"http_status": 401, "www_authenticate_present": true, "www_authenticate_scheme": "Bearer", "error_code": "Unauthorized", "message": "AKV10000: Request is missing a Bearer, PoP, or MTLS_POP token."}
```

**6. Compute direct, with the identity Unity Catalog uses**

```text
token identity: {"oid": "<connector-oid>", "appid": "<connector-appid>", "idtyp": "app", "xms_mirid": "/subscriptions/<subscription-id>/resourceGroups/rg-uc-secrets-demo/providers/Microsoft.Databricks/accessConnectors/dbac-uc-secrets-demo"}
[L4_compute_connector_token] HTTP 403 Forbidden  {"token_identity": {"oid": "<connector-oid>", "appid": "<connector-appid>", "idtyp": "app", "xms_mirid": "/subscriptions/<subscription-id>/resourceGroups/rg-uc-secrets-demo/providers/Microsoft.Databricks/accessConnectors/dbac-uc-secrets-demo"}, "message": "Connection is not an approved private link and caller was ignored because bypass is not set to 'AzureServices' and PublicNetworkAccess is set to 'Disabled'. \r\nVault: kv-ucsec-<workspace-id>;location=westeurope", "inner_code": "ForbiddenByConnection"}
```

**7. Unity Gateway lane**

```text
HTTP 403 after 0.7 s (0% of the 360 s client timeout)
error_code=PERMISSION_DENIED upstream_status=None
message: the cloud provider returned access denied, check the configuration of the service credential
verdict: denied by Databricks (no EXECUTE, or the secret could not be resolved)
[L5_gateway] denied by Databricks (no EXECUTE, or the secret could not be resolved)  {"http_status": 403, "error_code": "PERMISSION_DENIED", "upstream_status": null, "elapsed_s": 0.7, "message": "the cloud provider returned access denied, check the configuration of the service credential"}
```

**8. Summary**

```text
workspace <workspace-id> | metastore_azure_westeurope (westeurope) | classic | driver <classic-node-ip> | run_label vault sealed + NCC: ws-demo classic
vault kv-ucsec-<workspace-id>.vault.azure.net | catalog visible, isolation OPEN | credential SERVICE credential, isolation ISOLATION_MODE_OPEN
lane                                     outcome
UC read, dbutils (dummy)                 Key Vault refused the service credential
UC read, REST include_value (dummy)      refused (HTTP 403 PERMISSION_DENIED)
UC read, dbutils (real, hash only)       Key Vault refused the service credential
compute DNS                              public address
compute direct, no token                 HTTP 401 challenge: the vault answered this compute
compute direct, connector token          HTTP 403 Forbidden
Unity Gateway                            denied by Databricks (no EXECUTE, or the secret could not be resolved)
```
```text
{"run_label": "vault sealed + NCC: ws-demo classic", "claims": {"W1_workspace": {"outcome": "workspace <workspace-id>", "host": "https://adb-<workspace-id>.14.azuredatabricks.net", "sdk_host": "<regional-control-plane-host>"}, "W2_metastore": {"outcome": "metastore_azure_westeurope (westeurope)", "metastore_id": "<metastore-id>", "cloud": "azure"}, "W3_compute": {"outcome": "classic", "DATABRICKS_RUNTIME_VERSION": "18.3", "DATABRICKS_ENV_VERSION": null, "spark": "4.1.0", "cluster_id": "<cluster-id>", "node_type": "Standard_F4s_v2", "spark_version": "18.x-scala2.13", "driver_ip": "<classic-node-ip>", "driver_ip_rfc1918": true}, "W4_caller": {"outcome": "<user>", "workspace_admin": true}, "C1_catalog": {"outcome": "visible, isolation OPEN", "metastore_id": "<metastore-id>"}, "C2_catalog_bindings": {"outcome": "0 workspace binding(s)", "bindings": []}, "C3_secret_listing": {"outcome": "2 secret(s)", "secrets": ["uc_secrets_demo.secrets.apimlanekey", "uc_secrets_demo.secrets.dummysecret"]}, "C4_connection": {"outcome": "AZURE_KEY_VAULT -> vault kv-ucsec-<workspace-id>", "credential": "uc_secrets_demo"}, "C5_credential": {"outcome": "SERVICE credential, isolation ISOLATION_MODE_OPEN", "access_connector_id": "/subscriptions/<subscription-id>/resourceGroups/rg-uc-secrets-demo/providers/Microsoft.Databricks/accessConnectors/dbac-uc-secrets-demo", "managed_identity_id": "/subscriptions/<subscription-id>/resourceGroups/rg-uc-secrets-demo/providers/Microsoft.ManagedIdentity/userAssignedIdentities/id-uc-secrets-demo"}, "L1_uc_read_dbutils": {"outcome": "Key Vault refused the service credential", "exception": "py4j.protocol.Py4JJavaError", "message": ": com.databricks.sql.managedcatalog.acl.UnauthorizedAccessException: PERMISSION_DENIED: the cloud provider returned access denied, check the configuration of the service credential"}, "L1_uc_read_rest": {"outcome": "refused (HTTP 403 PERMISSION_DENIED)", "http_status": 403, "error_code": "PERMISSION_DENIED", "message": "the cloud provider returned access denied, check the configuration of the service credential"}, "L1_uc_read_real_hash": {"outcome": "Key Vault refused the service credential", "exception": "py4j.protocol.Py4JJavaError", "message": ": com.databricks.sql.managedcatalog.acl.UnauthorizedAccessException: PERMISSION_DENIED: the cloud provider returned access denied, check the configuration of the service credential"}, "L2_compute_dns": {"outcome": "public address", "canonical": "<kv-traffic-manager-canonical>", "aliases": ["kv-ucsec-<workspace-id>.vault.azure.net", "<kv-privatelink-alias>", "<kv-weu-alias-2>", "<kv-regional-alias-3>", "<kv-identity-alias-4>"], "addresses": {"<public-ip-4>": "public", "<public-ip-5>": "public", "<public-ip-6>": "public"}}, "L3_compute_unauth": {"outcome": "HTTP 401 challenge: the vault answered this compute", "http_status": 401, "www_authenticate_present": true, "www_authenticate_scheme": "Bearer", "error_code": "Unauthorized", "message": "AKV10000: Request is missing a Bearer, PoP, or MTLS_POP token."}, "L4_compute_connector_token": {"outcome": "HTTP 403 Forbidden", "token_identity": {"oid": "<connector-oid>", "appid": "<connector-appid>", "idtyp": "app", "xms_mirid": "/subscriptions/<subscription-id>/resourceGroups/rg-uc-secrets-demo/providers/Microsoft.Databricks/accessConnectors/dbac-uc-secrets-demo"}, "message": "Connection is not an approved private link and caller was ignored because bypass is not set to 'AzureServices' and PublicNetworkAccess is set to 'Disabled'. \r\nVault: kv-ucsec-<workspace-id>;location=westeurope", "inner_code": "ForbiddenByConnection"}, "L5_gateway": {"outcome": "denied by Databricks (no EXECUTE, or the secret could not be resolved)", "http_status": 403, "error_code": "PERMISSION_DENIED", "upstream_status": null, "elapsed_s": 0.7, "message": "the cloud provider returned access denied, check the configuration of the service credential"}}}
```

### Row 11: ws-demo, serverless, vault open, NCC endpoint ESTABLISHED (re-check)

`run_id` <run-or-timestamp-id> / task `run_id` <run-or-timestamp-id>, SUCCESS, submitted 2026-10-29 21:22:45 UTC, ended 21:27:19.

**Parameters and helpers**

```text
run_label: vault open + NCC propagation check: ws-demo serverless
workspace host: https://adb-<workspace-id>.14.azuredatabricks.net | SDK host: https://adb-<workspace-id>.14.azuredatabricks.net | databricks-sdk 0.122.0 | SDK HTTP timeout: 60 s | gateway client timeout: 360 s
```

**1. Where am I**

```text
[W1_workspace] workspace <workspace-id>  {"host": "https://adb-<workspace-id>.14.azuredatabricks.net", "sdk_host": "https://adb-<workspace-id>.14.azuredatabricks.net"}
[W2_metastore] metastore_azure_westeurope (westeurope)  {"metastore_id": "<metastore-id>", "cloud": "azure"}
[W3_compute] serverless  {"DATABRICKS_RUNTIME_VERSION": "client.6.5", "DATABRICKS_ENV_VERSION": "6", "spark": "4.2.0", "driver_ip": "<private-ip-2>", "driver_ip_rfc1918": true}
[W4_caller] <user>  {"workspace_admin": true}
```

**2. Catalog visibility, binding and the secret chain**

```text
[C1_catalog] visible, isolation OPEN  {"metastore_id": "<metastore-id>"}
[C2_catalog_bindings] 0 workspace binding(s)  {"bindings": []}
[C3_secret_listing] 2 secret(s)  {"secrets": ["uc_secrets_demo.secrets.apimlanekey", "uc_secrets_demo.secrets.dummysecret"]}
[C4_connection] AZURE_KEY_VAULT -> vault kv-ucsec-<workspace-id>  {"credential": "uc_secrets_demo"}
[C5_credential] SERVICE credential, isolation ISOLATION_MODE_OPEN  {"access_connector_id": "/subscriptions/<subscription-id>/resourceGroups/rg-uc-secrets-demo/providers/Microsoft.Databricks/accessConnectors/dbac-uc-secrets-demo", "managed_identity_id": "/subscriptions/<subscription-id>/resourceGroups/rg-uc-secrets-demo/providers/Microsoft.ManagedIdentity/userAssignedIdentities/id-uc-secrets-demo"}
vault under test: kv-ucsec-<workspace-id>.vault.azure.net
```

**3. UC read lane**

```text
[L1_uc_read_dbutils] value ok  {"length": 20, "sha256_prefix": "<dummy-sha256-prefix>"}
[L1_uc_read_rest] value ok  {"length": 20, "sha256_prefix": "<dummy-sha256-prefix>"}
[L1_uc_read_real_hash] value ok  {"length": 64, "sha256_prefix": "<secret-sha256-prefix-1>"}
```

**4. Compute DNS lane**

```text
[L2_compute_dns] public address  {"canonical": "<kv-akadns-canonical>", "aliases": ["kv-ucsec-<workspace-id>.vault.azure.net", "<kv-privatelink-alias>", "<kv-weu-alias-2>", "<kv-regional-alias-3>", "<kv-identity-alias-4>"], "addresses": {"<public-ip-4>": "public", "<public-ip-5>": "public", "<public-ip-6>": "public"}}
```

**5. Compute direct, no token**

```text
[L3_compute_unauth] HTTP 401 challenge: the vault answered this compute  {"http_status": 401, "www_authenticate_present": true, "www_authenticate_scheme": "Bearer", "error_code": "Unauthorized", "message": "AKV10000: Request is missing a Bearer, PoP, or MTLS_POP token."}
```

**6. Compute direct, with the identity Unity Catalog uses**

```text
token identity: {"oid": "<connector-oid>", "appid": "<connector-appid>", "idtyp": "app", "xms_mirid": "/subscriptions/<subscription-id>/resourceGroups/rg-uc-secrets-demo/providers/Microsoft.Databricks/accessConnectors/dbac-uc-secrets-demo"}
[L4_compute_connector_token] HTTP 200: value ok  {"token_identity": {"oid": "<connector-oid>", "appid": "<connector-appid>", "idtyp": "app", "xms_mirid": "/subscriptions/<subscription-id>/resourceGroups/rg-uc-secrets-demo/providers/Microsoft.Databricks/accessConnectors/dbac-uc-secrets-demo"}, "sha256_prefix": "<dummy-sha256-prefix>", "same_as_uc_read": true}
```

**7. Unity Gateway lane**

```text
HTTP 502 after 230.8 s (64% of the 360 s client timeout)
error_code=INTERNAL_ERROR upstream_status=500
message: Model Provider Service returned error with status code 500: Internal server error. The model provider returned a server error — this is usually transient, so retry with backoff; if it persists, check the provider's status page.
verdict: bearer accepted by APIM; the upstream model failed (upstream_status 500)
[L5_gateway] bearer accepted by APIM; the upstream model failed (upstream_status 500)  {"http_status": 502, "error_code": "INTERNAL_ERROR", "upstream_status": 500, "elapsed_s": 230.8, "message": "Model Provider Service returned error with status code 500: Internal server error. The model provider returned a server error \u2014 this is usually transient, so retry with backoff; if it persists, check the provider's status page."}
```

**8. Summary**

```text
workspace <workspace-id> | metastore_azure_westeurope (westeurope) | serverless | driver <private-ip-2> | run_label vault open + NCC propagation check: ws-demo serverless
vault kv-ucsec-<workspace-id>.vault.azure.net | catalog visible, isolation OPEN | credential SERVICE credential, isolation ISOLATION_MODE_OPEN
lane                                     outcome
UC read, dbutils (dummy)                 value ok
UC read, REST include_value (dummy)      value ok
UC read, dbutils (real, hash only)       value ok
compute DNS                              public address
compute direct, no token                 HTTP 401 challenge: the vault answered this compute
compute direct, connector token          HTTP 200: value ok
Unity Gateway                            bearer accepted by APIM; the upstream model failed (upstream_status 500)
```
```text
{"run_label": "vault open + NCC propagation check: ws-demo serverless", "claims": {"W1_workspace": {"outcome": "workspace <workspace-id>", "host": "https://adb-<workspace-id>.14.azuredatabricks.net", "sdk_host": "https://adb-<workspace-id>.14.azuredatabricks.net"}, "W2_metastore": {"outcome": "metastore_azure_westeurope (westeurope)", "metastore_id": "<metastore-id>", "cloud": "azure"}, "W3_compute": {"outcome": "serverless", "DATABRICKS_RUNTIME_VERSION": "client.6.5", "DATABRICKS_ENV_VERSION": "6", "spark": "4.2.0", "driver_ip": "<private-ip-2>", "driver_ip_rfc1918": true}, "W4_caller": {"outcome": "<user>", "workspace_admin": true}, "C1_catalog": {"outcome": "visible, isolation OPEN", "metastore_id": "<metastore-id>"}, "C2_catalog_bindings": {"outcome": "0 workspace binding(s)", "bindings": []}, "C3_secret_listing": {"outcome": "2 secret(s)", "secrets": ["uc_secrets_demo.secrets.apimlanekey", "uc_secrets_demo.secrets.dummysecret"]}, "C4_connection": {"outcome": "AZURE_KEY_VAULT -> vault kv-ucsec-<workspace-id>", "credential": "uc_secrets_demo"}, "C5_credential": {"outcome": "SERVICE credential, isolation ISOLATION_MODE_OPEN", "access_connector_id": "/subscriptions/<subscription-id>/resourceGroups/rg-uc-secrets-demo/providers/Microsoft.Databricks/accessConnectors/dbac-uc-secrets-demo", "managed_identity_id": "/subscriptions/<subscription-id>/resourceGroups/rg-uc-secrets-demo/providers/Microsoft.ManagedIdentity/userAssignedIdentities/id-uc-secrets-demo"}, "L1_uc_read_dbutils": {"outcome": "value ok", "length": 20, "sha256_prefix": "<dummy-sha256-prefix>"}, "L1_uc_read_rest": {"outcome": "value ok", "length": 20, "sha256_prefix": "<dummy-sha256-prefix>"}, "L1_uc_read_real_hash": {"outcome": "value ok", "length": 64, "sha256_prefix": "<secret-sha256-prefix-1>"}, "L2_compute_dns": {"outcome": "public address", "canonical": "<kv-akadns-canonical>", "aliases": ["kv-ucsec-<workspace-id>.vault.azure.net", "<kv-privatelink-alias>", "<kv-weu-alias-2>", "<kv-regional-alias-3>", "<kv-identity-alias-4>"], "addresses": {"<public-ip-4>": "public", "<public-ip-5>": "public", "<public-ip-6>": "public"}}, "L3_compute_unauth": {"outcome": "HTTP 401 challenge: the vault answered this compute", "http_status": 401, "www_authenticate_present": true, "www_authenticate_scheme": "Bearer", "error_code": "Unauthorized", "message": "AKV10000: Request is missing a Bearer, PoP, or MTLS_POP token."}, "L4_compute_connector_token": {"outcome": "HTTP 200: value ok", "token_identity": {"oid": "<connector-oid>", "appid": "<connector-appid>", "idtyp": "app", "xms_mirid": "/subscriptions/<subscription-id>/resourceGroups/rg-uc-secrets-demo/providers/Microsoft.Databricks/accessConnectors/dbac-uc-secrets-demo"}, "sha256_prefix": "<dummy-sha256-prefix>", "same_as_uc_read": true}, "L5_gateway": {"outcome": "bearer accepted by APIM; the upstream model failed (upstream_status 500)", "http_status": 502, "error_code": "INTERNAL_ERROR", "upstream_status": 500, "elapsed_s": 230.8, "message": "Model Provider Service returned error with status code 500: Internal server error. The model provider returned a server error \u2014 this is usually transient, so retry with backoff; if it persists, check the provider's status page."}}}
```

### Row 12: ws-demo, serverless, vault open, NCC endpoint ESTABLISHED (second re-check, 9 h 45 min after approval)

`run_id` <run-or-timestamp-id> / task `run_id` <run-or-timestamp-id>, SUCCESS, submitted 2026-10-30 06:45:28 UTC, ended 06:49:57.

**Topology matrix: from this workspace and this compute, which lanes to the Key Vault-backed secret work?**


**Parameters and helpers**

```text
run_label: vault open + NCC propagation check: ws-demo serverless
workspace host: https://adb-<workspace-id>.14.azuredatabricks.net | SDK host: https://adb-<workspace-id>.14.azuredatabricks.net | databricks-sdk 0.122.0 | SDK HTTP timeout: 60 s | gateway client timeout: 360 s
```

**1. Where am I**

```text
[W1_workspace] workspace <workspace-id>  {"host": "https://adb-<workspace-id>.14.azuredatabricks.net", "sdk_host": "https://adb-<workspace-id>.14.azuredatabricks.net"}
[W2_metastore] metastore_azure_westeurope (westeurope)  {"metastore_id": "<metastore-id>", "cloud": "azure"}
[W3_compute] serverless  {"DATABRICKS_RUNTIME_VERSION": "client.6.5", "DATABRICKS_ENV_VERSION": "6", "spark": "4.2.0", "driver_ip": "<private-ip-3>", "driver_ip_rfc1918": true}
[W4_caller] <user>  {"workspace_admin": true}
```

**2. Catalog visibility, binding and the secret chain**

```text
[C1_catalog] visible, isolation OPEN  {"metastore_id": "<metastore-id>"}
[C2_catalog_bindings] 0 workspace binding(s)  {"bindings": []}
[C3_secret_listing] 2 secret(s)  {"secrets": ["uc_secrets_demo.secrets.apimlanekey", "uc_secrets_demo.secrets.dummysecret"]}
[C4_connection] AZURE_KEY_VAULT -> vault kv-ucsec-<workspace-id>  {"credential": "uc_secrets_demo"}
[C5_credential] SERVICE credential, isolation ISOLATION_MODE_OPEN  {"access_connector_id": "/subscriptions/<subscription-id>/resourceGroups/rg-uc-secrets-demo/providers/Microsoft.Databricks/accessConnectors/dbac-uc-secrets-demo", "managed_identity_id": "/subscriptions/<subscription-id>/resourceGroups/rg-uc-secrets-demo/providers/Microsoft.ManagedIdentity/userAssignedIdentities/id-uc-secrets-demo"}
vault under test: kv-ucsec-<workspace-id>.vault.azure.net
```

**3. UC read lane**

```text
[L1_uc_read_dbutils] value ok  {"length": 20, "sha256_prefix": "<dummy-sha256-prefix>"}
[L1_uc_read_rest] value ok  {"length": 20, "sha256_prefix": "<dummy-sha256-prefix>"}
[L1_uc_read_real_hash] value ok  {"length": 64, "sha256_prefix": "<secret-sha256-prefix-1>"}
```

**4. Compute DNS lane**

```text
[L2_compute_dns] mixed  {"canonical": "kv-ucsec-<workspace-id>.vault.azure.net", "aliases": [], "addresses": {"<ncc-private-endpoint-ip>": "private (RFC 1918)", "::ffff:<ncc-private-endpoint-ip>": "public"}}
```

**5. Compute direct, no token**

```text
[L3_compute_unauth] HTTP 401 challenge: the vault answered this compute  {"http_status": 401, "www_authenticate_present": true, "www_authenticate_scheme": "Bearer", "error_code": "Unauthorized", "message": "AKV10000: Request is missing a Bearer, PoP, or MTLS_POP token."}
```

**6. Compute direct, with the identity Unity Catalog uses**

```text
token identity: {"oid": "<connector-oid>", "appid": "<connector-appid>", "idtyp": "app", "xms_mirid": "/subscriptions/<subscription-id>/resourceGroups/rg-uc-secrets-demo/providers/Microsoft.Databricks/accessConnectors/dbac-uc-secrets-demo"}
[L4_compute_connector_token] HTTP 200: value ok  {"token_identity": {"oid": "<connector-oid>", "appid": "<connector-appid>", "idtyp": "app", "xms_mirid": "/subscriptions/<subscription-id>/resourceGroups/rg-uc-secrets-demo/providers/Microsoft.Databricks/accessConnectors/dbac-uc-secrets-demo"}, "sha256_prefix": "<dummy-sha256-prefix>", "same_as_uc_read": true}
```

**7. Unity Gateway lane**

```text
HTTP 502 after 231.6 s (64% of the 360 s client timeout)
error_code=INTERNAL_ERROR upstream_status=500
message: Model Provider Service returned error with status code 500: Internal server error. The model provider returned a server error — this is usually transient, so retry with backoff; if it persists, check the provider's status page.
verdict: bearer accepted by APIM; the upstream model failed (upstream_status 500)
[L5_gateway] bearer accepted by APIM; the upstream model failed (upstream_status 500)  {"http_status": 502, "error_code": "INTERNAL_ERROR", "upstream_status": 500, "elapsed_s": 231.6, "message": "Model Provider Service returned error with status code 500: Internal server error. The model provider returned a server error \u2014 this is usually transient, so retry with backoff; if it persists, check the provider's status page."}
```

**8. Summary**

```text
workspace <workspace-id> | metastore_azure_westeurope (westeurope) | serverless | driver <private-ip-3> | run_label vault open + NCC propagation check: ws-demo serverless
vault kv-ucsec-<workspace-id>.vault.azure.net | catalog visible, isolation OPEN | credential SERVICE credential, isolation ISOLATION_MODE_OPEN
lane                                     outcome
UC read, dbutils (dummy)                 value ok
UC read, REST include_value (dummy)      value ok
UC read, dbutils (real, hash only)       value ok
compute DNS                              mixed
compute direct, no token                 HTTP 401 challenge: the vault answered this compute
compute direct, connector token          HTTP 200: value ok
Unity Gateway                            bearer accepted by APIM; the upstream model failed (upstream_status 500)
```
```text
{"run_label": "vault open + NCC propagation check: ws-demo serverless", "claims": {"W1_workspace": {"outcome": "workspace <workspace-id>", "host": "https://adb-<workspace-id>.14.azuredatabricks.net", "sdk_host": "https://adb-<workspace-id>.14.azuredatabricks.net"}, "W2_metastore": {"outcome": "metastore_azure_westeurope (westeurope)", "metastore_id": "<metastore-id>", "cloud": "azure"}, "W3_compute": {"outcome": "serverless", "DATABRICKS_RUNTIME_VERSION": "client.6.5", "DATABRICKS_ENV_VERSION": "6", "spark": "4.2.0", "driver_ip": "<private-ip-3>", "driver_ip_rfc1918": true}, "W4_caller": {"outcome": "<user>", "workspace_admin": true}, "C1_catalog": {"outcome": "visible, isolation OPEN", "metastore_id": "<metastore-id>"}, "C2_catalog_bindings": {"outcome": "0 workspace binding(s)", "bindings": []}, "C3_secret_listing": {"outcome": "2 secret(s)", "secrets": ["uc_secrets_demo.secrets.apimlanekey", "uc_secrets_demo.secrets.dummysecret"]}, "C4_connection": {"outcome": "AZURE_KEY_VAULT -> vault kv-ucsec-<workspace-id>", "credential": "uc_secrets_demo"}, "C5_credential": {"outcome": "SERVICE credential, isolation ISOLATION_MODE_OPEN", "access_connector_id": "/subscriptions/<subscription-id>/resourceGroups/rg-uc-secrets-demo/providers/Microsoft.Databricks/accessConnectors/dbac-uc-secrets-demo", "managed_identity_id": "/subscriptions/<subscription-id>/resourceGroups/rg-uc-secrets-demo/providers/Microsoft.ManagedIdentity/userAssignedIdentities/id-uc-secrets-demo"}, "L1_uc_read_dbutils": {"outcome": "value ok", "length": 20, "sha256_prefix": "<dummy-sha256-prefix>"}, "L1_uc_read_rest": {"outcome": "value ok", "length": 20, "sha256_prefix": "<dummy-sha256-prefix>"}, "L1_uc_read_real_hash": {"outcome": "value ok", "length": 64, "sha256_prefix": "<secret-sha256-prefix-1>"}, "L2_compute_dns": {"outcome": "mixed", "canonical": "kv-ucsec-<workspace-id>.vault.azure.net", "aliases": [], "addresses": {"<ncc-private-endpoint-ip>": "private (RFC 1918)", "::ffff:<ncc-private-endpoint-ip>": "public"}}, "L3_compute_unauth": {"outcome": "HTTP 401 challenge: the vault answered this compute", "http_status": 401, "www_authenticate_present": true, "www_authenticate_scheme": "Bearer", "error_code": "Unauthorized", "message": "AKV10000: Request is missing a Bearer, PoP, or MTLS_POP token."}, "L4_compute_connector_token": {"outcome": "HTTP 200: value ok", "token_identity": {"oid": "<connector-oid>", "appid": "<connector-appid>", "idtyp": "app", "xms_mirid": "/subscriptions/<subscription-id>/resourceGroups/rg-uc-secrets-demo/providers/Microsoft.Databricks/accessConnectors/dbac-uc-secrets-demo"}, "sha256_prefix": "<dummy-sha256-prefix>", "same_as_uc_read": true}, "L5_gateway": {"outcome": "bearer accepted by APIM; the upstream model failed (upstream_status 500)", "http_status": 502, "error_code": "INTERNAL_ERROR", "upstream_status": 500, "elapsed_s": 231.6, "message": "Model Provider Service returned error with status code 500: Internal server error. The model provider returned a server error \u2014 this is usually transient, so retry with backoff; if it persists, check the provider's status page."}}}
```

### Row 13: ws-demo, serverless, vault sealed + NCC live

`run_id` <run-or-timestamp-id> / task `run_id` <run-or-timestamp-id>, SUCCESS, submitted 2026-10-30 06:53:05 UTC, ended 06:53:44.

**Topology matrix: from this workspace and this compute, which lanes to the Key Vault-backed secret work?**


**Parameters and helpers**

```text
run_label: vault sealed + NCC live: ws-demo serverless
workspace host: https://adb-<workspace-id>.14.azuredatabricks.net | SDK host: https://adb-<workspace-id>.14.azuredatabricks.net | databricks-sdk 0.122.0 | SDK HTTP timeout: 60 s | gateway client timeout: 360 s
```

**1. Where am I**

```text
[W1_workspace] workspace <workspace-id>  {"host": "https://adb-<workspace-id>.14.azuredatabricks.net", "sdk_host": "https://adb-<workspace-id>.14.azuredatabricks.net"}
[W2_metastore] metastore_azure_westeurope (westeurope)  {"metastore_id": "<metastore-id>", "cloud": "azure"}
[W3_compute] serverless  {"DATABRICKS_RUNTIME_VERSION": "client.6.5", "DATABRICKS_ENV_VERSION": "6", "spark": "4.2.0", "driver_ip": "<private-ip-3>", "driver_ip_rfc1918": true}
[W4_caller] <user>  {"workspace_admin": true}
```

**2. Catalog visibility, binding and the secret chain**

```text
[C1_catalog] visible, isolation OPEN  {"metastore_id": "<metastore-id>"}
[C2_catalog_bindings] 0 workspace binding(s)  {"bindings": []}
[C3_secret_listing] 2 secret(s)  {"secrets": ["uc_secrets_demo.secrets.apimlanekey", "uc_secrets_demo.secrets.dummysecret"]}
[C4_connection] AZURE_KEY_VAULT -> vault kv-ucsec-<workspace-id>  {"credential": "uc_secrets_demo"}
[C5_credential] SERVICE credential, isolation ISOLATION_MODE_OPEN  {"access_connector_id": "/subscriptions/<subscription-id>/resourceGroups/rg-uc-secrets-demo/providers/Microsoft.Databricks/accessConnectors/dbac-uc-secrets-demo", "managed_identity_id": "/subscriptions/<subscription-id>/resourceGroups/rg-uc-secrets-demo/providers/Microsoft.ManagedIdentity/userAssignedIdentities/id-uc-secrets-demo"}
vault under test: kv-ucsec-<workspace-id>.vault.azure.net
```

**3. UC read lane**

```text
expected failure, caught py4j.protocol.Py4JJavaError:
  : com.databricks.backend.daemon.driver.repl.ManagedCatalogServiceException: PERMISSION_DENIED: the cloud provider returned access denied, check the configuration of the service credential
[L1_uc_read_dbutils] Key Vault refused the service credential  {"exception": "py4j.protocol.Py4JJavaError", "message": ": com.databricks.backend.daemon.driver.repl.ManagedCatalogServiceException: PERMISSION_DENIED: the cloud provider returned access denied, check the configuration of the service credential"}
[L1_uc_read_rest] refused (HTTP 403 PERMISSION_DENIED)  {"http_status": 403, "error_code": "PERMISSION_DENIED", "message": "the cloud provider returned access denied, check the configuration of the service credential"}
expected failure, caught py4j.protocol.Py4JJavaError:
  : com.databricks.backend.daemon.driver.repl.ManagedCatalogServiceException: PERMISSION_DENIED: the cloud provider returned access denied, check the configuration of the service credential
[L1_uc_read_real_hash] Key Vault refused the service credential  {"exception": "py4j.protocol.Py4JJavaError", "message": ": com.databricks.backend.daemon.driver.repl.ManagedCatalogServiceException: PERMISSION_DENIED: the cloud provider returned access denied, check the configuration of the service credential"}
```

**4. Compute DNS lane**

```text
[L2_compute_dns] private endpoint address  {"canonical": "kv-ucsec-<workspace-id>.vault.azure.net", "aliases": [], "addresses": {"<ncc-private-endpoint-ip>": "private (RFC 1918)", "::ffff:<ncc-private-endpoint-ip>": "private (RFC 1918)"}}
```

**5. Compute direct, no token**

```text
[L3_compute_unauth] HTTP 401 challenge: the vault answered this compute  {"http_status": 401, "www_authenticate_present": true, "www_authenticate_scheme": "Bearer", "error_code": "Unauthorized", "message": "AKV10000: Request is missing a Bearer, PoP, or MTLS_POP token."}
```

**6. Compute direct, with the identity Unity Catalog uses**

```text
token identity: {"oid": "<connector-oid>", "appid": "<connector-appid>", "idtyp": "app", "xms_mirid": "/subscriptions/<subscription-id>/resourceGroups/rg-uc-secrets-demo/providers/Microsoft.Databricks/accessConnectors/dbac-uc-secrets-demo"}
[L4_compute_connector_token] HTTP 200: value ok  {"token_identity": {"oid": "<connector-oid>", "appid": "<connector-appid>", "idtyp": "app", "xms_mirid": "/subscriptions/<subscription-id>/resourceGroups/rg-uc-secrets-demo/providers/Microsoft.Databricks/accessConnectors/dbac-uc-secrets-demo"}, "sha256_prefix": "<dummy-sha256-prefix>", "same_as_uc_read": null}
```

**7. Unity Gateway lane**

```text
HTTP 403 after 1.1 s (0% of the 360 s client timeout)
error_code=PERMISSION_DENIED upstream_status=None
message: the cloud provider returned access denied, check the configuration of the service credential
verdict: denied by Databricks (no EXECUTE, or the secret could not be resolved)
[L5_gateway] denied by Databricks (no EXECUTE, or the secret could not be resolved)  {"http_status": 403, "error_code": "PERMISSION_DENIED", "upstream_status": null, "elapsed_s": 1.1, "message": "the cloud provider returned access denied, check the configuration of the service credential"}
```

**8. Summary**

```text
workspace <workspace-id> | metastore_azure_westeurope (westeurope) | serverless | driver <private-ip-3> | run_label vault sealed + NCC live: ws-demo serverless
vault kv-ucsec-<workspace-id>.vault.azure.net | catalog visible, isolation OPEN | credential SERVICE credential, isolation ISOLATION_MODE_OPEN
lane                                     outcome
UC read, dbutils (dummy)                 Key Vault refused the service credential
UC read, REST include_value (dummy)      refused (HTTP 403 PERMISSION_DENIED)
UC read, dbutils (real, hash only)       Key Vault refused the service credential
compute DNS                              private endpoint address
compute direct, no token                 HTTP 401 challenge: the vault answered this compute
compute direct, connector token          HTTP 200: value ok
Unity Gateway                            denied by Databricks (no EXECUTE, or the secret could not be resolved)
```
```text
{"run_label": "vault sealed + NCC live: ws-demo serverless", "claims": {"W1_workspace": {"outcome": "workspace <workspace-id>", "host": "https://adb-<workspace-id>.14.azuredatabricks.net", "sdk_host": "https://adb-<workspace-id>.14.azuredatabricks.net"}, "W2_metastore": {"outcome": "metastore_azure_westeurope (westeurope)", "metastore_id": "<metastore-id>", "cloud": "azure"}, "W3_compute": {"outcome": "serverless", "DATABRICKS_RUNTIME_VERSION": "client.6.5", "DATABRICKS_ENV_VERSION": "6", "spark": "4.2.0", "driver_ip": "<private-ip-3>", "driver_ip_rfc1918": true}, "W4_caller": {"outcome": "<user>", "workspace_admin": true}, "C1_catalog": {"outcome": "visible, isolation OPEN", "metastore_id": "<metastore-id>"}, "C2_catalog_bindings": {"outcome": "0 workspace binding(s)", "bindings": []}, "C3_secret_listing": {"outcome": "2 secret(s)", "secrets": ["uc_secrets_demo.secrets.apimlanekey", "uc_secrets_demo.secrets.dummysecret"]}, "C4_connection": {"outcome": "AZURE_KEY_VAULT -> vault kv-ucsec-<workspace-id>", "credential": "uc_secrets_demo"}, "C5_credential": {"outcome": "SERVICE credential, isolation ISOLATION_MODE_OPEN", "access_connector_id": "/subscriptions/<subscription-id>/resourceGroups/rg-uc-secrets-demo/providers/Microsoft.Databricks/accessConnectors/dbac-uc-secrets-demo", "managed_identity_id": "/subscriptions/<subscription-id>/resourceGroups/rg-uc-secrets-demo/providers/Microsoft.ManagedIdentity/userAssignedIdentities/id-uc-secrets-demo"}, "L1_uc_read_dbutils": {"outcome": "Key Vault refused the service credential", "exception": "py4j.protocol.Py4JJavaError", "message": ": com.databricks.backend.daemon.driver.repl.ManagedCatalogServiceException: PERMISSION_DENIED: the cloud provider returned access denied, check the configuration of the service credential"}, "L1_uc_read_rest": {"outcome": "refused (HTTP 403 PERMISSION_DENIED)", "http_status": 403, "error_code": "PERMISSION_DENIED", "message": "the cloud provider returned access denied, check the configuration of the service credential"}, "L1_uc_read_real_hash": {"outcome": "Key Vault refused the service credential", "exception": "py4j.protocol.Py4JJavaError", "message": ": com.databricks.backend.daemon.driver.repl.ManagedCatalogServiceException: PERMISSION_DENIED: the cloud provider returned access denied, check the configuration of the service credential"}, "L2_compute_dns": {"outcome": "private endpoint address", "canonical": "kv-ucsec-<workspace-id>.vault.azure.net", "aliases": [], "addresses": {"<ncc-private-endpoint-ip>": "private (RFC 1918)", "::ffff:<ncc-private-endpoint-ip>": "private (RFC 1918)"}}, "L3_compute_unauth": {"outcome": "HTTP 401 challenge: the vault answered this compute", "http_status": 401, "www_authenticate_present": true, "www_authenticate_scheme": "Bearer", "error_code": "Unauthorized", "message": "AKV10000: Request is missing a Bearer, PoP, or MTLS_POP token."}, "L4_compute_connector_token": {"outcome": "HTTP 200: value ok", "token_identity": {"oid": "<connector-oid>", "appid": "<connector-appid>", "idtyp": "app", "xms_mirid": "/subscriptions/<subscription-id>/resourceGroups/rg-uc-secrets-demo/providers/Microsoft.Databricks/accessConnectors/dbac-uc-secrets-demo"}, "sha256_prefix": "<dummy-sha256-prefix>", "same_as_uc_read": null}, "L5_gateway": {"outcome": "denied by Databricks (no EXECUTE, or the secret could not be resolved)", "http_status": 403, "error_code": "PERMISSION_DENIED", "upstream_status": null, "elapsed_s": 1.1, "message": "the cloud provider returned access denied, check the configuration of the service credential"}}}
```

### Row 14: ws-demo, classic, vault sealed + NCC live

`run_id` <run-or-timestamp-id> / task `run_id` <run-or-timestamp-id>, SUCCESS, submitted 2026-10-30 06:53:06 UTC, ended 07:01:53.

**Topology matrix: from this workspace and this compute, which lanes to the Key Vault-backed secret work?**


**Parameters and helpers**

```text
run_label: vault sealed + NCC live: ws-demo classic
workspace host: https://adb-<workspace-id>.14.azuredatabricks.net | SDK host: <regional-control-plane-host> | databricks-sdk 0.67.0 | SDK HTTP timeout: 60 s | gateway client timeout: 360 s
```

**1. Where am I**

```text
[W1_workspace] workspace <workspace-id>  {"host": "https://adb-<workspace-id>.14.azuredatabricks.net", "sdk_host": "<regional-control-plane-host>"}
[W2_metastore] metastore_azure_westeurope (westeurope)  {"metastore_id": "<metastore-id>", "cloud": "azure"}
[W3_compute] classic  {"DATABRICKS_RUNTIME_VERSION": "18.3", "DATABRICKS_ENV_VERSION": null, "spark": "4.1.0", "cluster_id": "<cluster-id>", "node_type": "Standard_F4s_v2", "spark_version": "18.x-scala2.13", "driver_ip": "<classic-node-ip>", "driver_ip_rfc1918": true}
[W4_caller] <user>  {"workspace_admin": true}
```

**2. Catalog visibility, binding and the secret chain**

```text
[C1_catalog] visible, isolation OPEN  {"metastore_id": "<metastore-id>"}
[C2_catalog_bindings] 0 workspace binding(s)  {"bindings": []}
[C3_secret_listing] 2 secret(s)  {"secrets": ["uc_secrets_demo.secrets.apimlanekey", "uc_secrets_demo.secrets.dummysecret"]}
[C4_connection] AZURE_KEY_VAULT -> vault kv-ucsec-<workspace-id>  {"credential": "uc_secrets_demo"}
[C5_credential] SERVICE credential, isolation ISOLATION_MODE_OPEN  {"access_connector_id": "/subscriptions/<subscription-id>/resourceGroups/rg-uc-secrets-demo/providers/Microsoft.Databricks/accessConnectors/dbac-uc-secrets-demo", "managed_identity_id": "/subscriptions/<subscription-id>/resourceGroups/rg-uc-secrets-demo/providers/Microsoft.ManagedIdentity/userAssignedIdentities/id-uc-secrets-demo"}
vault under test: kv-ucsec-<workspace-id>.vault.azure.net
```

**3. UC read lane**

```text
expected failure, caught py4j.protocol.Py4JJavaError:
  : com.databricks.sql.managedcatalog.acl.UnauthorizedAccessException: PERMISSION_DENIED: the cloud provider returned access denied, check the configuration of the service credential
[L1_uc_read_dbutils] Key Vault refused the service credential  {"exception": "py4j.protocol.Py4JJavaError", "message": ": com.databricks.sql.managedcatalog.acl.UnauthorizedAccessException: PERMISSION_DENIED: the cloud provider returned access denied, check the configuration of the service credential"}
[L1_uc_read_rest] refused (HTTP 403 PERMISSION_DENIED)  {"http_status": 403, "error_code": "PERMISSION_DENIED", "message": "the cloud provider returned access denied, check the configuration of the service credential"}
expected failure, caught py4j.protocol.Py4JJavaError:
  : com.databricks.sql.managedcatalog.acl.UnauthorizedAccessException: PERMISSION_DENIED: the cloud provider returned access denied, check the configuration of the service credential
[L1_uc_read_real_hash] Key Vault refused the service credential  {"exception": "py4j.protocol.Py4JJavaError", "message": ": com.databricks.sql.managedcatalog.acl.UnauthorizedAccessException: PERMISSION_DENIED: the cloud provider returned access denied, check the configuration of the service credential"}
```

**4. Compute DNS lane**

```text
[L2_compute_dns] public address  {"canonical": "<kv-akadns-canonical>", "aliases": ["kv-ucsec-<workspace-id>.vault.azure.net", "<kv-privatelink-alias>", "<kv-weu-alias-2>", "<kv-regional-alias-3>", "<kv-identity-alias-4>"], "addresses": {"<public-ip-4>": "public", "<public-ip-5>": "public", "<public-ip-6>": "public"}}
```

**5. Compute direct, no token**

```text
[L3_compute_unauth] HTTP 401 challenge: the vault answered this compute  {"http_status": 401, "www_authenticate_present": true, "www_authenticate_scheme": "Bearer", "error_code": "Unauthorized", "message": "AKV10000: Request is missing a Bearer, PoP, or MTLS_POP token."}
```

**6. Compute direct, with the identity Unity Catalog uses**

```text
token identity: {"oid": "<connector-oid>", "appid": "<connector-appid>", "idtyp": "app", "xms_mirid": "/subscriptions/<subscription-id>/resourceGroups/rg-uc-secrets-demo/providers/Microsoft.Databricks/accessConnectors/dbac-uc-secrets-demo"}
[L4_compute_connector_token] HTTP 403 Forbidden  {"token_identity": {"oid": "<connector-oid>", "appid": "<connector-appid>", "idtyp": "app", "xms_mirid": "/subscriptions/<subscription-id>/resourceGroups/rg-uc-secrets-demo/providers/Microsoft.Databricks/accessConnectors/dbac-uc-secrets-demo"}, "message": "Connection is not an approved private link and caller was ignored because bypass is not set to 'AzureServices' and PublicNetworkAccess is set to 'Disabled'. \r\nVault: kv-ucsec-<workspace-id>;location=westeurope", "inner_code": "ForbiddenByConnection"}
```

**7. Unity Gateway lane**

```text
HTTP 403 after 0.9 s (0% of the 360 s client timeout)
error_code=PERMISSION_DENIED upstream_status=None
message: the cloud provider returned access denied, check the configuration of the service credential
verdict: denied by Databricks (no EXECUTE, or the secret could not be resolved)
[L5_gateway] denied by Databricks (no EXECUTE, or the secret could not be resolved)  {"http_status": 403, "error_code": "PERMISSION_DENIED", "upstream_status": null, "elapsed_s": 0.9, "message": "the cloud provider returned access denied, check the configuration of the service credential"}
```

**8. Summary**

```text
workspace <workspace-id> | metastore_azure_westeurope (westeurope) | classic | driver <classic-node-ip> | run_label vault sealed + NCC live: ws-demo classic
vault kv-ucsec-<workspace-id>.vault.azure.net | catalog visible, isolation OPEN | credential SERVICE credential, isolation ISOLATION_MODE_OPEN
lane                                     outcome
UC read, dbutils (dummy)                 Key Vault refused the service credential
UC read, REST include_value (dummy)      refused (HTTP 403 PERMISSION_DENIED)
UC read, dbutils (real, hash only)       Key Vault refused the service credential
compute DNS                              public address
compute direct, no token                 HTTP 401 challenge: the vault answered this compute
compute direct, connector token          HTTP 403 Forbidden
Unity Gateway                            denied by Databricks (no EXECUTE, or the secret could not be resolved)
```
```text
{"run_label": "vault sealed + NCC live: ws-demo classic", "claims": {"W1_workspace": {"outcome": "workspace <workspace-id>", "host": "https://adb-<workspace-id>.14.azuredatabricks.net", "sdk_host": "<regional-control-plane-host>"}, "W2_metastore": {"outcome": "metastore_azure_westeurope (westeurope)", "metastore_id": "<metastore-id>", "cloud": "azure"}, "W3_compute": {"outcome": "classic", "DATABRICKS_RUNTIME_VERSION": "18.3", "DATABRICKS_ENV_VERSION": null, "spark": "4.1.0", "cluster_id": "<cluster-id>", "node_type": "Standard_F4s_v2", "spark_version": "18.x-scala2.13", "driver_ip": "<classic-node-ip>", "driver_ip_rfc1918": true}, "W4_caller": {"outcome": "<user>", "workspace_admin": true}, "C1_catalog": {"outcome": "visible, isolation OPEN", "metastore_id": "<metastore-id>"}, "C2_catalog_bindings": {"outcome": "0 workspace binding(s)", "bindings": []}, "C3_secret_listing": {"outcome": "2 secret(s)", "secrets": ["uc_secrets_demo.secrets.apimlanekey", "uc_secrets_demo.secrets.dummysecret"]}, "C4_connection": {"outcome": "AZURE_KEY_VAULT -> vault kv-ucsec-<workspace-id>", "credential": "uc_secrets_demo"}, "C5_credential": {"outcome": "SERVICE credential, isolation ISOLATION_MODE_OPEN", "access_connector_id": "/subscriptions/<subscription-id>/resourceGroups/rg-uc-secrets-demo/providers/Microsoft.Databricks/accessConnectors/dbac-uc-secrets-demo", "managed_identity_id": "/subscriptions/<subscription-id>/resourceGroups/rg-uc-secrets-demo/providers/Microsoft.ManagedIdentity/userAssignedIdentities/id-uc-secrets-demo"}, "L1_uc_read_dbutils": {"outcome": "Key Vault refused the service credential", "exception": "py4j.protocol.Py4JJavaError", "message": ": com.databricks.sql.managedcatalog.acl.UnauthorizedAccessException: PERMISSION_DENIED: the cloud provider returned access denied, check the configuration of the service credential"}, "L1_uc_read_rest": {"outcome": "refused (HTTP 403 PERMISSION_DENIED)", "http_status": 403, "error_code": "PERMISSION_DENIED", "message": "the cloud provider returned access denied, check the configuration of the service credential"}, "L1_uc_read_real_hash": {"outcome": "Key Vault refused the service credential", "exception": "py4j.protocol.Py4JJavaError", "message": ": com.databricks.sql.managedcatalog.acl.UnauthorizedAccessException: PERMISSION_DENIED: the cloud provider returned access denied, check the configuration of the service credential"}, "L2_compute_dns": {"outcome": "public address", "canonical": "<kv-akadns-canonical>", "aliases": ["kv-ucsec-<workspace-id>.vault.azure.net", "<kv-privatelink-alias>", "<kv-weu-alias-2>", "<kv-regional-alias-3>", "<kv-identity-alias-4>"], "addresses": {"<public-ip-4>": "public", "<public-ip-5>": "public", "<public-ip-6>": "public"}}, "L3_compute_unauth": {"outcome": "HTTP 401 challenge: the vault answered this compute", "http_status": 401, "www_authenticate_present": true, "www_authenticate_scheme": "Bearer", "error_code": "Unauthorized", "message": "AKV10000: Request is missing a Bearer, PoP, or MTLS_POP token."}, "L4_compute_connector_token": {"outcome": "HTTP 403 Forbidden", "token_identity": {"oid": "<connector-oid>", "appid": "<connector-appid>", "idtyp": "app", "xms_mirid": "/subscriptions/<subscription-id>/resourceGroups/rg-uc-secrets-demo/providers/Microsoft.Databricks/accessConnectors/dbac-uc-secrets-demo"}, "message": "Connection is not an approved private link and caller was ignored because bypass is not set to 'AzureServices' and PublicNetworkAccess is set to 'Disabled'. \r\nVault: kv-ucsec-<workspace-id>;location=westeurope", "inner_code": "ForbiddenByConnection"}, "L5_gateway": {"outcome": "denied by Databricks (no EXECUTE, or the secret could not be resolved)", "http_status": 403, "error_code": "PERMISSION_DENIED", "upstream_status": null, "elapsed_s": 0.9, "message": "the cloud provider returned access denied, check the configuration of the service credential"}}}
```

### Row A1: ws-demo, serverless, reference-only service principal, no ACCESS on the credential (control)

`run_id` <run-or-timestamp-id> / task `run_id` <run-or-timestamp-id>, SUCCESS, submitted 2026-10-30 09:54:51 UTC, ended 09:55:16.

**`ACCESS` on the service credential: what it gives a principal that owns nothing**


**Parameters and helpers**


**Who is running, and what the credential grants that principal**

```text
[W_caller] <sp-application-id>  {"workspace_id": <workspace-id>, "effective_permissions_lookup": "HTTP 403 PERMISSION_DENIED", "message": "Principal 'uc-secrets-demo-reference-only' does not have any privileges on Credential 'uc_secrets_demo'."}
```

**A1. The governed lane: Unity Catalog read of the dummy secret**

```text
[A1_uc_read_rest] refused (HTTP 403 PERMISSION_DENIED)  {"message": "Principal 'uc-secrets-demo-reference-only' does not have READ SECRET on Secret 'uc_secrets_demo.secrets.dummysecret'."}
```

**A2. Credential metadata**

```text
[A2_credential_metadata] refused (HTTP 403 PERMISSION_DENIED)  {"message": "Principal 'uc-secrets-demo-reference-only' does not have any privileges on Credential 'uc_secrets_demo'."}
```

**A3. A token for the credential's identity, through the REST API**

```text
[A3_rest_temporary_credential] refused (HTTP 403 PERMISSION_DENIED)  {"message": "Principal 'uc-secrets-demo-reference-only' does not have ACCESS on Credential 'uc_secrets_demo'."}
```

**A4. With that token, straight to Key Vault**

```text
[A4_vault_list] not attempted: no token
[A4_vault_dummy] not attempted: no token
[A4_vault_real] not attempted: no token
```

**A5. The same token from the compute's side**

```text
expected failure, caught builtins.Exception:
  Error while retrieving temporary credentials: Principal 'uc-secrets-demo-reference-only' does not have ACCESS on Credential 'uc_secrets_demo'.
[A5_compute_provider] refused  {"exception": "builtins.Exception", "message": "Error while retrieving temporary credentials: Principal 'uc-secrets-demo-reference-only' does not have ACCESS on Credential 'uc_secrets_demo'."}
```

**Summary**

```text
caller <sp-application-id> | run_label control: reference-only SP, no ACCESS on the credential
claim                          outcome
W_caller                       <sp-application-id>
A1_uc_read_rest                refused (HTTP 403 PERMISSION_DENIED)
A2_credential_metadata         refused (HTTP 403 PERMISSION_DENIED)
A3_rest_temporary_credential   refused (HTTP 403 PERMISSION_DENIED)
A4_vault_list                  not attempted: no token
A4_vault_dummy                 not attempted: no token
A4_vault_real                  not attempted: no token
A5_compute_provider            refused
```
```text
{"run_label": "control: reference-only SP, no ACCESS on the credential", "claims": {"W_caller": {"outcome": "<sp-application-id>", "workspace_id": <workspace-id>, "effective_permissions_lookup": "HTTP 403 PERMISSION_DENIED", "message": "Principal 'uc-secrets-demo-reference-only' does not have any privileges on Credential 'uc_secrets_demo'."}, "A1_uc_read_rest": {"outcome": "refused (HTTP 403 PERMISSION_DENIED)", "message": "Principal 'uc-secrets-demo-reference-only' does not have READ SECRET on Secret 'uc_secrets_demo.secrets.dummysecret'."}, "A2_credential_metadata": {"outcome": "refused (HTTP 403 PERMISSION_DENIED)", "message": "Principal 'uc-secrets-demo-reference-only' does not have any privileges on Credential 'uc_secrets_demo'."}, "A3_rest_temporary_credential": {"outcome": "refused (HTTP 403 PERMISSION_DENIED)", "message": "Principal 'uc-secrets-demo-reference-only' does not have ACCESS on Credential 'uc_secrets_demo'."}, "A4_vault_list": {"outcome": "not attempted: no token"}, "A4_vault_dummy": {"outcome": "not attempted: no token"}, "A4_vault_real": {"outcome": "not attempted: no token"}, "A5_compute_provider": {"outcome": "refused", "exception": "builtins.Exception", "message": "Error while retrieving temporary credentials: Principal 'uc-secrets-demo-reference-only' does not have ACCESS on Credential 'uc_secrets_demo'."}}}
```

### Row A2: ws-demo, serverless, reference-only service principal, ACCESS on the credential

`run_id` <run-or-timestamp-id> / task `run_id` <run-or-timestamp-id>, SUCCESS, submitted 2026-10-30 09:55:43 UTC, ended 09:56:08.

**`ACCESS` on the service credential: what it gives a principal that owns nothing**


**Parameters and helpers**


**Who is running, and what the credential grants that principal**

```text
[W_caller] <sp-application-id>  {"workspace_id": <workspace-id>, "effective_privileges_on_credential": ["ACCESS"]}
```

**A1. The governed lane: Unity Catalog read of the dummy secret**

```text
[A1_uc_read_rest] refused (HTTP 403 PERMISSION_DENIED)  {"message": "Principal 'uc-secrets-demo-reference-only' does not have READ SECRET on Secret 'uc_secrets_demo.secrets.dummysecret'."}
```

**A2. Credential metadata**

```text
[A2_credential_metadata] visible  {"owner": "<user>", "isolation_mode": "ISOLATION_MODE_OPEN", "purpose": "SERVICE"}
```

**A3. A token for the credential's identity, through the REST API**

```text
[A3_rest_temporary_credential] token issued  {"token_identity": {"oid": "<connector-oid>", "appid": "<connector-appid>", "idtyp": "app", "xms_mirid": "/subscriptions/<subscription-id>/resourceGroups/rg-uc-secrets-demo/providers/Microsoft.Databricks/accessConnectors/dbac-uc-secrets-demo"}, "expiration_time": <run-or-timestamp-id>}
```

**A4. With that token, straight to Key Vault**

```text
[A4_vault_list] HTTP 200: 2 secret(s)  {"names": ["apimlanekey", "dummysecret"]}
[A4_vault_dummy] HTTP 200: value ok  {"length": 20, "sha256_prefix": "<dummy-sha256-prefix>"}
[A4_vault_real] HTTP 200: value ok (never printed)  {"length": 64, "sha256_prefix": "<secret-sha256-prefix-1>"}
```

**A5. The same token from the compute's side**

```text
[A5_compute_provider] token issued, HTTP 200: value ok  {"token_identity": {"oid": "<connector-oid>", "appid": "<connector-appid>", "idtyp": "app", "xms_mirid": "/subscriptions/<subscription-id>/resourceGroups/rg-uc-secrets-demo/providers/Microsoft.Databricks/accessConnectors/dbac-uc-secrets-demo"}, "length": 20, "sha256_prefix": "<dummy-sha256-prefix>", "same_as_rest_lane": true}
```

**Summary**

```text
caller <sp-application-id> | run_label reference-only SP, ACCESS on the credential
claim                          outcome
W_caller                       <sp-application-id>
A1_uc_read_rest                refused (HTTP 403 PERMISSION_DENIED)
A2_credential_metadata         visible
A3_rest_temporary_credential   token issued
A4_vault_list                  HTTP 200: 2 secret(s)
A4_vault_dummy                 HTTP 200: value ok
A4_vault_real                  HTTP 200: value ok (never printed)
A5_compute_provider            token issued, HTTP 200: value ok
```
```text
{"run_label": "reference-only SP, ACCESS on the credential", "claims": {"W_caller": {"outcome": "<sp-application-id>", "workspace_id": <workspace-id>, "effective_privileges_on_credential": ["ACCESS"]}, "A1_uc_read_rest": {"outcome": "refused (HTTP 403 PERMISSION_DENIED)", "message": "Principal 'uc-secrets-demo-reference-only' does not have READ SECRET on Secret 'uc_secrets_demo.secrets.dummysecret'."}, "A2_credential_metadata": {"outcome": "visible", "owner": "<user>", "isolation_mode": "ISOLATION_MODE_OPEN", "purpose": "SERVICE"}, "A3_rest_temporary_credential": {"outcome": "token issued", "token_identity": {"oid": "<connector-oid>", "appid": "<connector-appid>", "idtyp": "app", "xms_mirid": "/subscriptions/<subscription-id>/resourceGroups/rg-uc-secrets-demo/providers/Microsoft.Databricks/accessConnectors/dbac-uc-secrets-demo"}, "expiration_time": <run-or-timestamp-id>}, "A4_vault_list": {"outcome": "HTTP 200: 2 secret(s)", "names": ["apimlanekey", "dummysecret"]}, "A4_vault_dummy": {"outcome": "HTTP 200: value ok", "length": 20, "sha256_prefix": "<dummy-sha256-prefix>"}, "A4_vault_real": {"outcome": "HTTP 200: value ok (never printed)", "length": 64, "sha256_prefix": "<secret-sha256-prefix-1>"}, "A5_compute_provider": {"outcome": "token issued, HTTP 200: value ok", "token_identity": {"oid": "<connector-oid>", "appid": "<connector-appid>", "idtyp": "app", "xms_mirid": "/subscriptions/<subscription-id>/resourceGroups/rg-uc-secrets-demo/providers/Microsoft.Databricks/accessConnectors/dbac-uc-secrets-demo"}, "length": 20, "sha256_prefix": "<dummy-sha256-prefix>", "same_as_rest_lane": true}}}
```

### Row 15: ws-demo, serverless, vault open, perimeter Learning

`run_id` <run-or-timestamp-id> / task `run_id` <run-or-timestamp-id>, SUCCESS, submitted 2026-10-30 14:44:15 UTC, ended 14:48:40.

**Topology matrix: from this workspace and this compute, which lanes to the Key Vault-backed secret work?**


**Parameters and helpers**

```text
run_label: vault open + NSP Learning: ws-demo serverless
workspace host: https://adb-<workspace-id>.14.azuredatabricks.net | SDK host: https://adb-<workspace-id>.14.azuredatabricks.net | databricks-sdk 0.122.0 | SDK HTTP timeout: 60 s | gateway client timeout: 360 s
```

**1. Where am I**

```text
[W1_workspace] workspace <workspace-id>  {"host": "https://adb-<workspace-id>.14.azuredatabricks.net", "sdk_host": "https://adb-<workspace-id>.14.azuredatabricks.net"}
[W2_metastore] metastore_azure_westeurope (westeurope)  {"metastore_id": "<metastore-id>", "cloud": "azure"}
[W3_compute] serverless  {"DATABRICKS_RUNTIME_VERSION": "client.6.5", "DATABRICKS_ENV_VERSION": "6", "spark": "4.2.0", "driver_ip": "<private-ip-2>", "driver_ip_rfc1918": true}
[W4_caller] <user>  {"workspace_admin": true}
```

**2. Catalog visibility, binding and the secret chain**

```text
[C1_catalog] visible, isolation OPEN  {"metastore_id": "<metastore-id>"}
[C2_catalog_bindings] 0 workspace binding(s)  {"bindings": []}
[C3_secret_listing] 2 secret(s)  {"secrets": ["uc_secrets_demo.secrets.apimlanekey", "uc_secrets_demo.secrets.dummysecret"]}
[C4_connection] AZURE_KEY_VAULT -> vault kv-ucsec-<workspace-id>  {"credential": "uc_secrets_demo"}
[C5_credential] SERVICE credential, isolation ISOLATION_MODE_OPEN  {"access_connector_id": "/subscriptions/<subscription-id>/resourceGroups/rg-uc-secrets-demo/providers/Microsoft.Databricks/accessConnectors/dbac-uc-secrets-demo", "managed_identity_id": "/subscriptions/<subscription-id>/resourceGroups/rg-uc-secrets-demo/providers/Microsoft.ManagedIdentity/userAssignedIdentities/id-uc-secrets-demo"}
vault under test: kv-ucsec-<workspace-id>.vault.azure.net
```

**3. UC read lane**

```text
[L1_uc_read_dbutils] value ok  {"length": 20, "sha256_prefix": "<dummy-sha256-prefix>"}
[L1_uc_read_rest] value ok  {"length": 20, "sha256_prefix": "<dummy-sha256-prefix>"}
[L1_uc_read_real_hash] value ok  {"length": 64, "sha256_prefix": "<secret-sha256-prefix-1>"}
```

**4. Compute DNS lane**

```text
[L2_compute_dns] private endpoint address  {"canonical": "kv-ucsec-<workspace-id>.vault.azure.net", "aliases": [], "addresses": {"<ncc-private-endpoint-ip>": "private (RFC 1918)", "::ffff:<ncc-private-endpoint-ip>": "private (RFC 1918)"}}
```

**5. Compute direct, no token**

```text
[L3_compute_unauth] HTTP 401 challenge: the vault answered this compute  {"http_status": 401, "www_authenticate_present": true, "www_authenticate_scheme": "Bearer", "error_code": "Unauthorized", "message": "AKV10000: Request is missing a Bearer, PoP, or MTLS_POP token."}
```

**6. Compute direct, with the identity Unity Catalog uses**

```text
token identity: {"oid": "<connector-oid>", "appid": "<connector-appid>", "idtyp": "app", "xms_mirid": "/subscriptions/<subscription-id>/resourceGroups/rg-uc-secrets-demo/providers/Microsoft.Databricks/accessConnectors/dbac-uc-secrets-demo"}
[L4_compute_connector_token] HTTP 200: value ok  {"token_identity": {"oid": "<connector-oid>", "appid": "<connector-appid>", "idtyp": "app", "xms_mirid": "/subscriptions/<subscription-id>/resourceGroups/rg-uc-secrets-demo/providers/Microsoft.Databricks/accessConnectors/dbac-uc-secrets-demo"}, "sha256_prefix": "<dummy-sha256-prefix>", "same_as_uc_read": true}
```

**7. Unity Gateway lane**

```text
HTTP 502 after 231.3 s (64% of the 360 s client timeout)
error_code=INTERNAL_ERROR upstream_status=500
message: Model Provider Service returned error with status code 500: Internal server error. The model provider returned a server error — this is usually transient, so retry with backoff; if it persists, check the provider's status page.
verdict: bearer accepted by APIM; the upstream model failed (upstream_status 500)
[L5_gateway] bearer accepted by APIM; the upstream model failed (upstream_status 500)  {"http_status": 502, "error_code": "INTERNAL_ERROR", "upstream_status": 500, "elapsed_s": 231.3, "message": "Model Provider Service returned error with status code 500: Internal server error. The model provider returned a server error \u2014 this is usually transient, so retry with backoff; if it persists, check the provider's status page."}
```

**8. Summary**

```text
workspace <workspace-id> | metastore_azure_westeurope (westeurope) | serverless | driver <private-ip-2> | run_label vault open + NSP Learning: ws-demo serverless
vault kv-ucsec-<workspace-id>.vault.azure.net | catalog visible, isolation OPEN | credential SERVICE credential, isolation ISOLATION_MODE_OPEN
lane                                     outcome
UC read, dbutils (dummy)                 value ok
UC read, REST include_value (dummy)      value ok
UC read, dbutils (real, hash only)       value ok
compute DNS                              private endpoint address
compute direct, no token                 HTTP 401 challenge: the vault answered this compute
compute direct, connector token          HTTP 200: value ok
Unity Gateway                            bearer accepted by APIM; the upstream model failed (upstream_status 500)
```
```text
{"run_label": "vault open + NSP Learning: ws-demo serverless", "claims": {"W1_workspace": {"outcome": "workspace <workspace-id>", "host": "https://adb-<workspace-id>.14.azuredatabricks.net", "sdk_host": "https://adb-<workspace-id>.14.azuredatabricks.net"}, "W2_metastore": {"outcome": "metastore_azure_westeurope (westeurope)", "metastore_id": "<metastore-id>", "cloud": "azure"}, "W3_compute": {"outcome": "serverless", "DATABRICKS_RUNTIME_VERSION": "client.6.5", "DATABRICKS_ENV_VERSION": "6", "spark": "4.2.0", "driver_ip": "<private-ip-2>", "driver_ip_rfc1918": true}, "W4_caller": {"outcome": "<user>", "workspace_admin": true}, "C1_catalog": {"outcome": "visible, isolation OPEN", "metastore_id": "<metastore-id>"}, "C2_catalog_bindings": {"outcome": "0 workspace binding(s)", "bindings": []}, "C3_secret_listing": {"outcome": "2 secret(s)", "secrets": ["uc_secrets_demo.secrets.apimlanekey", "uc_secrets_demo.secrets.dummysecret"]}, "C4_connection": {"outcome": "AZURE_KEY_VAULT -> vault kv-ucsec-<workspace-id>", "credential": "uc_secrets_demo"}, "C5_credential": {"outcome": "SERVICE credential, isolation ISOLATION_MODE_OPEN", "access_connector_id": "/subscriptions/<subscription-id>/resourceGroups/rg-uc-secrets-demo/providers/Microsoft.Databricks/accessConnectors/dbac-uc-secrets-demo", "managed_identity_id": "/subscriptions/<subscription-id>/resourceGroups/rg-uc-secrets-demo/providers/Microsoft.ManagedIdentity/userAssignedIdentities/id-uc-secrets-demo"}, "L1_uc_read_dbutils": {"outcome": "value ok", "length": 20, "sha256_prefix": "<dummy-sha256-prefix>"}, "L1_uc_read_rest": {"outcome": "value ok", "length": 20, "sha256_prefix": "<dummy-sha256-prefix>"}, "L1_uc_read_real_hash": {"outcome": "value ok", "length": 64, "sha256_prefix": "<secret-sha256-prefix-1>"}, "L2_compute_dns": {"outcome": "private endpoint address", "canonical": "kv-ucsec-<workspace-id>.vault.azure.net", "aliases": [], "addresses": {"<ncc-private-endpoint-ip>": "private (RFC 1918)", "::ffff:<ncc-private-endpoint-ip>": "private (RFC 1918)"}}, "L3_compute_unauth": {"outcome": "HTTP 401 challenge: the vault answered this compute", "http_status": 401, "www_authenticate_present": true, "www_authenticate_scheme": "Bearer", "error_code": "Unauthorized", "message": "AKV10000: Request is missing a Bearer, PoP, or MTLS_POP token."}, "L4_compute_connector_token": {"outcome": "HTTP 200: value ok", "token_identity": {"oid": "<connector-oid>", "appid": "<connector-appid>", "idtyp": "app", "xms_mirid": "/subscriptions/<subscription-id>/resourceGroups/rg-uc-secrets-demo/providers/Microsoft.Databricks/accessConnectors/dbac-uc-secrets-demo"}, "sha256_prefix": "<dummy-sha256-prefix>", "same_as_uc_read": true}, "L5_gateway": {"outcome": "bearer accepted by APIM; the upstream model failed (upstream_status 500)", "http_status": 502, "error_code": "INTERNAL_ERROR", "upstream_status": 500, "elapsed_s": 231.3, "message": "Model Provider Service returned error with status code 500: Internal server error. The model provider returned a server error \u2014 this is usually transient, so retry with backoff; if it persists, check the provider's status page."}}}
```

### Row 16: ws-demo, classic, vault open, perimeter Learning

`run_id` <run-or-timestamp-id> / task `run_id` <run-or-timestamp-id>, SUCCESS, submitted 2026-10-30 14:44:17 UTC, ended 14:57:21.

**Topology matrix: from this workspace and this compute, which lanes to the Key Vault-backed secret work?**


**Parameters and helpers**

```text
run_label: vault open + NSP Learning: ws-demo classic
workspace host: https://adb-<workspace-id>.14.azuredatabricks.net | SDK host: <regional-control-plane-host> | databricks-sdk 0.67.0 | SDK HTTP timeout: 60 s | gateway client timeout: 360 s
```

**1. Where am I**

```text
[W1_workspace] workspace <workspace-id>  {"host": "https://adb-<workspace-id>.14.azuredatabricks.net", "sdk_host": "<regional-control-plane-host>"}
[W2_metastore] metastore_azure_westeurope (westeurope)  {"metastore_id": "<metastore-id>", "cloud": "azure"}
[W3_compute] classic  {"DATABRICKS_RUNTIME_VERSION": "18.3", "DATABRICKS_ENV_VERSION": null, "spark": "4.1.0", "cluster_id": "<cluster-id>", "node_type": "Standard_F4s_v2", "spark_version": "18.x-scala2.13", "driver_ip": "<classic-node-ip>", "driver_ip_rfc1918": true}
[W4_caller] <user>  {"workspace_admin": true}
```

**2. Catalog visibility, binding and the secret chain**

```text
[C1_catalog] visible, isolation OPEN  {"metastore_id": "<metastore-id>"}
[C2_catalog_bindings] 0 workspace binding(s)  {"bindings": []}
[C3_secret_listing] 2 secret(s)  {"secrets": ["uc_secrets_demo.secrets.apimlanekey", "uc_secrets_demo.secrets.dummysecret"]}
[C4_connection] AZURE_KEY_VAULT -> vault kv-ucsec-<workspace-id>  {"credential": "uc_secrets_demo"}
[C5_credential] SERVICE credential, isolation ISOLATION_MODE_OPEN  {"access_connector_id": "/subscriptions/<subscription-id>/resourceGroups/rg-uc-secrets-demo/providers/Microsoft.Databricks/accessConnectors/dbac-uc-secrets-demo", "managed_identity_id": "/subscriptions/<subscription-id>/resourceGroups/rg-uc-secrets-demo/providers/Microsoft.ManagedIdentity/userAssignedIdentities/id-uc-secrets-demo"}
vault under test: kv-ucsec-<workspace-id>.vault.azure.net
```

**3. UC read lane**

```text
[L1_uc_read_dbutils] value ok  {"length": 20, "sha256_prefix": "<dummy-sha256-prefix>"}
[L1_uc_read_rest] value ok  {"length": 20, "sha256_prefix": "<dummy-sha256-prefix>"}
[L1_uc_read_real_hash] value ok  {"length": 64, "sha256_prefix": "<secret-sha256-prefix-1>"}
```

**4. Compute DNS lane**

```text
[L2_compute_dns] public address  {"canonical": "<kv-akadns-canonical>", "aliases": ["kv-ucsec-<workspace-id>.vault.azure.net", "<kv-privatelink-alias>", "<kv-weu-alias-2>", "<kv-regional-alias-3>", "<kv-identity-alias-4>"], "addresses": {"<public-ip-4>": "public", "<public-ip-5>": "public", "<public-ip-6>": "public"}}
```

**5. Compute direct, no token**

```text
[L3_compute_unauth] HTTP 401 challenge: the vault answered this compute  {"http_status": 401, "www_authenticate_present": true, "www_authenticate_scheme": "Bearer", "error_code": "Unauthorized", "message": "AKV10000: Request is missing a Bearer, PoP, or MTLS_POP token."}
```

**6. Compute direct, with the identity Unity Catalog uses**

```text
token identity: {"oid": "<connector-oid>", "appid": "<connector-appid>", "idtyp": "app", "xms_mirid": "/subscriptions/<subscription-id>/resourceGroups/rg-uc-secrets-demo/providers/Microsoft.Databricks/accessConnectors/dbac-uc-secrets-demo"}
[L4_compute_connector_token] HTTP 200: value ok  {"token_identity": {"oid": "<connector-oid>", "appid": "<connector-appid>", "idtyp": "app", "xms_mirid": "/subscriptions/<subscription-id>/resourceGroups/rg-uc-secrets-demo/providers/Microsoft.Databricks/accessConnectors/dbac-uc-secrets-demo"}, "sha256_prefix": "<dummy-sha256-prefix>", "same_as_uc_read": true}
```

**7. Unity Gateway lane**

```text
HTTP 502 after 230.9 s (64% of the 360 s client timeout)
error_code=INTERNAL_ERROR upstream_status=500
message: Model Provider Service returned error with status code 500: Internal server error. The model provider returned a server error — this is usually transient, so retry with backoff; if it persists, check the provider's status page.
verdict: bearer accepted by APIM; the upstream model failed (upstream_status 500)
[L5_gateway] bearer accepted by APIM; the upstream model failed (upstream_status 500)  {"http_status": 502, "error_code": "INTERNAL_ERROR", "upstream_status": 500, "elapsed_s": 230.9, "message": "Model Provider Service returned error with status code 500: Internal server error. The model provider returned a server error \u2014 this is usually transient, so retry with backoff; if it persists, check the provider's status page."}
```

**8. Summary**

```text
workspace <workspace-id> | metastore_azure_westeurope (westeurope) | classic | driver <classic-node-ip> | run_label vault open + NSP Learning: ws-demo classic
vault kv-ucsec-<workspace-id>.vault.azure.net | catalog visible, isolation OPEN | credential SERVICE credential, isolation ISOLATION_MODE_OPEN
lane                                     outcome
UC read, dbutils (dummy)                 value ok
UC read, REST include_value (dummy)      value ok
UC read, dbutils (real, hash only)       value ok
compute DNS                              public address
compute direct, no token                 HTTP 401 challenge: the vault answered this compute
compute direct, connector token          HTTP 200: value ok
Unity Gateway                            bearer accepted by APIM; the upstream model failed (upstream_status 500)
```
```text
{"run_label": "vault open + NSP Learning: ws-demo classic", "claims": {"W1_workspace": {"outcome": "workspace <workspace-id>", "host": "https://adb-<workspace-id>.14.azuredatabricks.net", "sdk_host": "<regional-control-plane-host>"}, "W2_metastore": {"outcome": "metastore_azure_westeurope (westeurope)", "metastore_id": "<metastore-id>", "cloud": "azure"}, "W3_compute": {"outcome": "classic", "DATABRICKS_RUNTIME_VERSION": "18.3", "DATABRICKS_ENV_VERSION": null, "spark": "4.1.0", "cluster_id": "<cluster-id>", "node_type": "Standard_F4s_v2", "spark_version": "18.x-scala2.13", "driver_ip": "<classic-node-ip>", "driver_ip_rfc1918": true}, "W4_caller": {"outcome": "<user>", "workspace_admin": true}, "C1_catalog": {"outcome": "visible, isolation OPEN", "metastore_id": "<metastore-id>"}, "C2_catalog_bindings": {"outcome": "0 workspace binding(s)", "bindings": []}, "C3_secret_listing": {"outcome": "2 secret(s)", "secrets": ["uc_secrets_demo.secrets.apimlanekey", "uc_secrets_demo.secrets.dummysecret"]}, "C4_connection": {"outcome": "AZURE_KEY_VAULT -> vault kv-ucsec-<workspace-id>", "credential": "uc_secrets_demo"}, "C5_credential": {"outcome": "SERVICE credential, isolation ISOLATION_MODE_OPEN", "access_connector_id": "/subscriptions/<subscription-id>/resourceGroups/rg-uc-secrets-demo/providers/Microsoft.Databricks/accessConnectors/dbac-uc-secrets-demo", "managed_identity_id": "/subscriptions/<subscription-id>/resourceGroups/rg-uc-secrets-demo/providers/Microsoft.ManagedIdentity/userAssignedIdentities/id-uc-secrets-demo"}, "L1_uc_read_dbutils": {"outcome": "value ok", "length": 20, "sha256_prefix": "<dummy-sha256-prefix>"}, "L1_uc_read_rest": {"outcome": "value ok", "length": 20, "sha256_prefix": "<dummy-sha256-prefix>"}, "L1_uc_read_real_hash": {"outcome": "value ok", "length": 64, "sha256_prefix": "<secret-sha256-prefix-1>"}, "L2_compute_dns": {"outcome": "public address", "canonical": "<kv-akadns-canonical>", "aliases": ["kv-ucsec-<workspace-id>.vault.azure.net", "<kv-privatelink-alias>", "<kv-weu-alias-2>", "<kv-regional-alias-3>", "<kv-identity-alias-4>"], "addresses": {"<public-ip-4>": "public", "<public-ip-5>": "public", "<public-ip-6>": "public"}}, "L3_compute_unauth": {"outcome": "HTTP 401 challenge: the vault answered this compute", "http_status": 401, "www_authenticate_present": true, "www_authenticate_scheme": "Bearer", "error_code": "Unauthorized", "message": "AKV10000: Request is missing a Bearer, PoP, or MTLS_POP token."}, "L4_compute_connector_token": {"outcome": "HTTP 200: value ok", "token_identity": {"oid": "<connector-oid>", "appid": "<connector-appid>", "idtyp": "app", "xms_mirid": "/subscriptions/<subscription-id>/resourceGroups/rg-uc-secrets-demo/providers/Microsoft.Databricks/accessConnectors/dbac-uc-secrets-demo"}, "sha256_prefix": "<dummy-sha256-prefix>", "same_as_uc_read": true}, "L5_gateway": {"outcome": "bearer accepted by APIM; the upstream model failed (upstream_status 500)", "http_status": 502, "error_code": "INTERNAL_ERROR", "upstream_status": 500, "elapsed_s": 230.9, "message": "Model Provider Service returned error with status code 500: Internal server error. The model provider returned a server error \u2014 this is usually transient, so retry with backoff; if it persists, check the provider's status page."}}}
```

### Row 17: ws-demo, serverless, vault open, perimeter Enforced, no rule

`run_id` <run-or-timestamp-id> / task `run_id` <run-or-timestamp-id>, SUCCESS, submitted 2026-10-30 14:58:11 UTC, ended 14:58:41.

**Topology matrix: from this workspace and this compute, which lanes to the Key Vault-backed secret work?**


**Parameters and helpers**

```text
run_label: vault open + NSP Enforced, no rule: ws-demo serverless
workspace host: https://adb-<workspace-id>.14.azuredatabricks.net | SDK host: https://adb-<workspace-id>.14.azuredatabricks.net | databricks-sdk 0.122.0 | SDK HTTP timeout: 60 s | gateway client timeout: 360 s
```

**1. Where am I**

```text
[W1_workspace] workspace <workspace-id>  {"host": "https://adb-<workspace-id>.14.azuredatabricks.net", "sdk_host": "https://adb-<workspace-id>.14.azuredatabricks.net"}
[W2_metastore] metastore_azure_westeurope (westeurope)  {"metastore_id": "<metastore-id>", "cloud": "azure"}
[W3_compute] serverless  {"DATABRICKS_RUNTIME_VERSION": "client.6.5", "DATABRICKS_ENV_VERSION": "6", "spark": "4.2.0", "driver_ip": "<private-ip-2>", "driver_ip_rfc1918": true}
[W4_caller] <user>  {"workspace_admin": true}
```

**2. Catalog visibility, binding and the secret chain**

```text
[C1_catalog] visible, isolation OPEN  {"metastore_id": "<metastore-id>"}
[C2_catalog_bindings] 0 workspace binding(s)  {"bindings": []}
[C3_secret_listing] 2 secret(s)  {"secrets": ["uc_secrets_demo.secrets.apimlanekey", "uc_secrets_demo.secrets.dummysecret"]}
[C4_connection] AZURE_KEY_VAULT -> vault kv-ucsec-<workspace-id>  {"credential": "uc_secrets_demo"}
[C5_credential] SERVICE credential, isolation ISOLATION_MODE_OPEN  {"access_connector_id": "/subscriptions/<subscription-id>/resourceGroups/rg-uc-secrets-demo/providers/Microsoft.Databricks/accessConnectors/dbac-uc-secrets-demo", "managed_identity_id": "/subscriptions/<subscription-id>/resourceGroups/rg-uc-secrets-demo/providers/Microsoft.ManagedIdentity/userAssignedIdentities/id-uc-secrets-demo"}
vault under test: kv-ucsec-<workspace-id>.vault.azure.net
```

**3. UC read lane**

```text
expected failure, caught py4j.protocol.Py4JJavaError:
  : com.databricks.backend.daemon.driver.repl.ManagedCatalogServiceException: PERMISSION_DENIED: the cloud provider returned access denied, check the configuration of the service credential
[L1_uc_read_dbutils] Key Vault refused the service credential  {"exception": "py4j.protocol.Py4JJavaError", "message": ": com.databricks.backend.daemon.driver.repl.ManagedCatalogServiceException: PERMISSION_DENIED: the cloud provider returned access denied, check the configuration of the service credential"}
[L1_uc_read_rest] refused (HTTP 403 PERMISSION_DENIED)  {"http_status": 403, "error_code": "PERMISSION_DENIED", "message": "the cloud provider returned access denied, check the configuration of the service credential"}
expected failure, caught py4j.protocol.Py4JJavaError:
  : com.databricks.backend.daemon.driver.repl.ManagedCatalogServiceException: PERMISSION_DENIED: the cloud provider returned access denied, check the configuration of the service credential
[L1_uc_read_real_hash] Key Vault refused the service credential  {"exception": "py4j.protocol.Py4JJavaError", "message": ": com.databricks.backend.daemon.driver.repl.ManagedCatalogServiceException: PERMISSION_DENIED: the cloud provider returned access denied, check the configuration of the service credential"}
```

**4. Compute DNS lane**

```text
[L2_compute_dns] private endpoint address  {"canonical": "kv-ucsec-<workspace-id>.vault.azure.net", "aliases": [], "addresses": {"<ncc-private-endpoint-ip>": "private (RFC 1918)", "::ffff:<ncc-private-endpoint-ip>": "private (RFC 1918)"}}
```

**5. Compute direct, no token**

```text
[L3_compute_unauth] HTTP 401 challenge: the vault answered this compute  {"http_status": 401, "www_authenticate_present": true, "www_authenticate_scheme": "Bearer", "error_code": "Unauthorized", "message": "AKV10000: Request is missing a Bearer, PoP, or MTLS_POP token."}
```

**6. Compute direct, with the identity Unity Catalog uses**

```text
token identity: {"oid": "<connector-oid>", "appid": "<connector-appid>", "idtyp": "app", "xms_mirid": "/subscriptions/<subscription-id>/resourceGroups/rg-uc-secrets-demo/providers/Microsoft.Databricks/accessConnectors/dbac-uc-secrets-demo"}
[L4_compute_connector_token] HTTP 200: value ok  {"token_identity": {"oid": "<connector-oid>", "appid": "<connector-appid>", "idtyp": "app", "xms_mirid": "/subscriptions/<subscription-id>/resourceGroups/rg-uc-secrets-demo/providers/Microsoft.Databricks/accessConnectors/dbac-uc-secrets-demo"}, "sha256_prefix": "<dummy-sha256-prefix>", "same_as_uc_read": null}
```

**7. Unity Gateway lane**

```text
HTTP 403 after 1.3 s (0% of the 360 s client timeout)
error_code=PERMISSION_DENIED upstream_status=None
message: the cloud provider returned access denied, check the configuration of the service credential
verdict: denied by Databricks (no EXECUTE, or the secret could not be resolved)
[L5_gateway] denied by Databricks (no EXECUTE, or the secret could not be resolved)  {"http_status": 403, "error_code": "PERMISSION_DENIED", "upstream_status": null, "elapsed_s": 1.3, "message": "the cloud provider returned access denied, check the configuration of the service credential"}
```

**8. Summary**

```text
workspace <workspace-id> | metastore_azure_westeurope (westeurope) | serverless | driver <private-ip-2> | run_label vault open + NSP Enforced, no rule: ws-demo serverless
vault kv-ucsec-<workspace-id>.vault.azure.net | catalog visible, isolation OPEN | credential SERVICE credential, isolation ISOLATION_MODE_OPEN
lane                                     outcome
UC read, dbutils (dummy)                 Key Vault refused the service credential
UC read, REST include_value (dummy)      refused (HTTP 403 PERMISSION_DENIED)
UC read, dbutils (real, hash only)       Key Vault refused the service credential
compute DNS                              private endpoint address
compute direct, no token                 HTTP 401 challenge: the vault answered this compute
compute direct, connector token          HTTP 200: value ok
Unity Gateway                            denied by Databricks (no EXECUTE, or the secret could not be resolved)
```
```text
{"run_label": "vault open + NSP Enforced, no rule: ws-demo serverless", "claims": {"W1_workspace": {"outcome": "workspace <workspace-id>", "host": "https://adb-<workspace-id>.14.azuredatabricks.net", "sdk_host": "https://adb-<workspace-id>.14.azuredatabricks.net"}, "W2_metastore": {"outcome": "metastore_azure_westeurope (westeurope)", "metastore_id": "<metastore-id>", "cloud": "azure"}, "W3_compute": {"outcome": "serverless", "DATABRICKS_RUNTIME_VERSION": "client.6.5", "DATABRICKS_ENV_VERSION": "6", "spark": "4.2.0", "driver_ip": "<private-ip-2>", "driver_ip_rfc1918": true}, "W4_caller": {"outcome": "<user>", "workspace_admin": true}, "C1_catalog": {"outcome": "visible, isolation OPEN", "metastore_id": "<metastore-id>"}, "C2_catalog_bindings": {"outcome": "0 workspace binding(s)", "bindings": []}, "C3_secret_listing": {"outcome": "2 secret(s)", "secrets": ["uc_secrets_demo.secrets.apimlanekey", "uc_secrets_demo.secrets.dummysecret"]}, "C4_connection": {"outcome": "AZURE_KEY_VAULT -> vault kv-ucsec-<workspace-id>", "credential": "uc_secrets_demo"}, "C5_credential": {"outcome": "SERVICE credential, isolation ISOLATION_MODE_OPEN", "access_connector_id": "/subscriptions/<subscription-id>/resourceGroups/rg-uc-secrets-demo/providers/Microsoft.Databricks/accessConnectors/dbac-uc-secrets-demo", "managed_identity_id": "/subscriptions/<subscription-id>/resourceGroups/rg-uc-secrets-demo/providers/Microsoft.ManagedIdentity/userAssignedIdentities/id-uc-secrets-demo"}, "L1_uc_read_dbutils": {"outcome": "Key Vault refused the service credential", "exception": "py4j.protocol.Py4JJavaError", "message": ": com.databricks.backend.daemon.driver.repl.ManagedCatalogServiceException: PERMISSION_DENIED: the cloud provider returned access denied, check the configuration of the service credential"}, "L1_uc_read_rest": {"outcome": "refused (HTTP 403 PERMISSION_DENIED)", "http_status": 403, "error_code": "PERMISSION_DENIED", "message": "the cloud provider returned access denied, check the configuration of the service credential"}, "L1_uc_read_real_hash": {"outcome": "Key Vault refused the service credential", "exception": "py4j.protocol.Py4JJavaError", "message": ": com.databricks.backend.daemon.driver.repl.ManagedCatalogServiceException: PERMISSION_DENIED: the cloud provider returned access denied, check the configuration of the service credential"}, "L2_compute_dns": {"outcome": "private endpoint address", "canonical": "kv-ucsec-<workspace-id>.vault.azure.net", "aliases": [], "addresses": {"<ncc-private-endpoint-ip>": "private (RFC 1918)", "::ffff:<ncc-private-endpoint-ip>": "private (RFC 1918)"}}, "L3_compute_unauth": {"outcome": "HTTP 401 challenge: the vault answered this compute", "http_status": 401, "www_authenticate_present": true, "www_authenticate_scheme": "Bearer", "error_code": "Unauthorized", "message": "AKV10000: Request is missing a Bearer, PoP, or MTLS_POP token."}, "L4_compute_connector_token": {"outcome": "HTTP 200: value ok", "token_identity": {"oid": "<connector-oid>", "appid": "<connector-appid>", "idtyp": "app", "xms_mirid": "/subscriptions/<subscription-id>/resourceGroups/rg-uc-secrets-demo/providers/Microsoft.Databricks/accessConnectors/dbac-uc-secrets-demo"}, "sha256_prefix": "<dummy-sha256-prefix>", "same_as_uc_read": null}, "L5_gateway": {"outcome": "denied by Databricks (no EXECUTE, or the secret could not be resolved)", "http_status": 403, "error_code": "PERMISSION_DENIED", "upstream_status": null, "elapsed_s": 1.3, "message": "the cloud provider returned access denied, check the configuration of the service credential"}}}
```

### Row 18: ws-demo, classic, vault open, perimeter Enforced, no rule

`run_id` <run-or-timestamp-id> / task `run_id` <run-or-timestamp-id>, SUCCESS, submitted 2026-10-30 14:58:12 UTC, ended 15:01:53.

**Topology matrix: from this workspace and this compute, which lanes to the Key Vault-backed secret work?**


**Parameters and helpers**

```text
run_label: vault open + NSP Enforced, no rule: ws-demo classic
workspace host: https://adb-<workspace-id>.14.azuredatabricks.net | SDK host: <regional-control-plane-host> | databricks-sdk 0.67.0 | SDK HTTP timeout: 60 s | gateway client timeout: 360 s
```

**1. Where am I**

```text
[W1_workspace] workspace <workspace-id>  {"host": "https://adb-<workspace-id>.14.azuredatabricks.net", "sdk_host": "<regional-control-plane-host>"}
[W2_metastore] metastore_azure_westeurope (westeurope)  {"metastore_id": "<metastore-id>", "cloud": "azure"}
[W3_compute] classic  {"DATABRICKS_RUNTIME_VERSION": "18.3", "DATABRICKS_ENV_VERSION": null, "spark": "4.1.0", "cluster_id": "<cluster-id>", "node_type": "Standard_F4s_v2", "spark_version": "18.x-scala2.13", "driver_ip": "<classic-node-ip>", "driver_ip_rfc1918": true}
[W4_caller] <user>  {"workspace_admin": true}
```

**2. Catalog visibility, binding and the secret chain**

```text
[C1_catalog] visible, isolation OPEN  {"metastore_id": "<metastore-id>"}
[C2_catalog_bindings] 0 workspace binding(s)  {"bindings": []}
[C3_secret_listing] 2 secret(s)  {"secrets": ["uc_secrets_demo.secrets.apimlanekey", "uc_secrets_demo.secrets.dummysecret"]}
[C4_connection] AZURE_KEY_VAULT -> vault kv-ucsec-<workspace-id>  {"credential": "uc_secrets_demo"}
[C5_credential] SERVICE credential, isolation ISOLATION_MODE_OPEN  {"access_connector_id": "/subscriptions/<subscription-id>/resourceGroups/rg-uc-secrets-demo/providers/Microsoft.Databricks/accessConnectors/dbac-uc-secrets-demo", "managed_identity_id": "/subscriptions/<subscription-id>/resourceGroups/rg-uc-secrets-demo/providers/Microsoft.ManagedIdentity/userAssignedIdentities/id-uc-secrets-demo"}
vault under test: kv-ucsec-<workspace-id>.vault.azure.net
```

**3. UC read lane**

```text
expected failure, caught py4j.protocol.Py4JJavaError:
  : com.databricks.sql.managedcatalog.acl.UnauthorizedAccessException: PERMISSION_DENIED: the cloud provider returned access denied, check the configuration of the service credential
[L1_uc_read_dbutils] Key Vault refused the service credential  {"exception": "py4j.protocol.Py4JJavaError", "message": ": com.databricks.sql.managedcatalog.acl.UnauthorizedAccessException: PERMISSION_DENIED: the cloud provider returned access denied, check the configuration of the service credential"}
[L1_uc_read_rest] refused (HTTP 403 PERMISSION_DENIED)  {"http_status": 403, "error_code": "PERMISSION_DENIED", "message": "the cloud provider returned access denied, check the configuration of the service credential"}
expected failure, caught py4j.protocol.Py4JJavaError:
  : com.databricks.sql.managedcatalog.acl.UnauthorizedAccessException: PERMISSION_DENIED: the cloud provider returned access denied, check the configuration of the service credential
[L1_uc_read_real_hash] Key Vault refused the service credential  {"exception": "py4j.protocol.Py4JJavaError", "message": ": com.databricks.sql.managedcatalog.acl.UnauthorizedAccessException: PERMISSION_DENIED: the cloud provider returned access denied, check the configuration of the service credential"}
```

**4. Compute DNS lane**

```text
[L2_compute_dns] public address  {"canonical": "<kv-traffic-manager-canonical>", "aliases": ["kv-ucsec-<workspace-id>.vault.azure.net", "<kv-privatelink-alias>", "<kv-weu-alias-2>", "<kv-regional-alias-3>", "<kv-identity-alias-4>"], "addresses": {"<public-ip-4>": "public", "<public-ip-5>": "public", "<public-ip-6>": "public"}}
```

**5. Compute direct, no token**

```text
[L3_compute_unauth] HTTP 401 challenge: the vault answered this compute  {"http_status": 401, "www_authenticate_present": true, "www_authenticate_scheme": "Bearer", "error_code": "Unauthorized", "message": "AKV10000: Request is missing a Bearer, PoP, or MTLS_POP token."}
```

**6. Compute direct, with the identity Unity Catalog uses**

```text
token identity: {"oid": "<connector-oid>", "appid": "<connector-appid>", "idtyp": "app", "xms_mirid": "/subscriptions/<subscription-id>/resourceGroups/rg-uc-secrets-demo/providers/Microsoft.Databricks/accessConnectors/dbac-uc-secrets-demo"}
[L4_compute_connector_token] HTTP 403 Forbidden  {"token_identity": {"oid": "<connector-oid>", "appid": "<connector-appid>", "idtyp": "app", "xms_mirid": "/subscriptions/<subscription-id>/resourceGroups/rg-uc-secrets-demo/providers/Microsoft.Databricks/accessConnectors/dbac-uc-secrets-demo"}, "message": "Request was not allowed by NSP rules. \r\nClient address: 0.0.0.0\r\nCaller: name=microsoft.databricks/accessconnectors;appid=<connector-appid>;oid=<connector-oid>\r\nVault: kv-ucsec-<workspace-id>;location=westeurope", "inner_code": "ForbiddenByNsp"}
```

**7. Unity Gateway lane**

```text
HTTP 403 after 0.8 s (0% of the 360 s client timeout)
error_code=PERMISSION_DENIED upstream_status=None
message: the cloud provider returned access denied, check the configuration of the service credential
verdict: denied by Databricks (no EXECUTE, or the secret could not be resolved)
[L5_gateway] denied by Databricks (no EXECUTE, or the secret could not be resolved)  {"http_status": 403, "error_code": "PERMISSION_DENIED", "upstream_status": null, "elapsed_s": 0.8, "message": "the cloud provider returned access denied, check the configuration of the service credential"}
```

**8. Summary**

```text
workspace <workspace-id> | metastore_azure_westeurope (westeurope) | classic | driver <classic-node-ip> | run_label vault open + NSP Enforced, no rule: ws-demo classic
vault kv-ucsec-<workspace-id>.vault.azure.net | catalog visible, isolation OPEN | credential SERVICE credential, isolation ISOLATION_MODE_OPEN
lane                                     outcome
UC read, dbutils (dummy)                 Key Vault refused the service credential
UC read, REST include_value (dummy)      refused (HTTP 403 PERMISSION_DENIED)
UC read, dbutils (real, hash only)       Key Vault refused the service credential
compute DNS                              public address
compute direct, no token                 HTTP 401 challenge: the vault answered this compute
compute direct, connector token          HTTP 403 Forbidden
Unity Gateway                            denied by Databricks (no EXECUTE, or the secret could not be resolved)
```
```text
{"run_label": "vault open + NSP Enforced, no rule: ws-demo classic", "claims": {"W1_workspace": {"outcome": "workspace <workspace-id>", "host": "https://adb-<workspace-id>.14.azuredatabricks.net", "sdk_host": "<regional-control-plane-host>"}, "W2_metastore": {"outcome": "metastore_azure_westeurope (westeurope)", "metastore_id": "<metastore-id>", "cloud": "azure"}, "W3_compute": {"outcome": "classic", "DATABRICKS_RUNTIME_VERSION": "18.3", "DATABRICKS_ENV_VERSION": null, "spark": "4.1.0", "cluster_id": "<cluster-id>", "node_type": "Standard_F4s_v2", "spark_version": "18.x-scala2.13", "driver_ip": "<classic-node-ip>", "driver_ip_rfc1918": true}, "W4_caller": {"outcome": "<user>", "workspace_admin": true}, "C1_catalog": {"outcome": "visible, isolation OPEN", "metastore_id": "<metastore-id>"}, "C2_catalog_bindings": {"outcome": "0 workspace binding(s)", "bindings": []}, "C3_secret_listing": {"outcome": "2 secret(s)", "secrets": ["uc_secrets_demo.secrets.apimlanekey", "uc_secrets_demo.secrets.dummysecret"]}, "C4_connection": {"outcome": "AZURE_KEY_VAULT -> vault kv-ucsec-<workspace-id>", "credential": "uc_secrets_demo"}, "C5_credential": {"outcome": "SERVICE credential, isolation ISOLATION_MODE_OPEN", "access_connector_id": "/subscriptions/<subscription-id>/resourceGroups/rg-uc-secrets-demo/providers/Microsoft.Databricks/accessConnectors/dbac-uc-secrets-demo", "managed_identity_id": "/subscriptions/<subscription-id>/resourceGroups/rg-uc-secrets-demo/providers/Microsoft.ManagedIdentity/userAssignedIdentities/id-uc-secrets-demo"}, "L1_uc_read_dbutils": {"outcome": "Key Vault refused the service credential", "exception": "py4j.protocol.Py4JJavaError", "message": ": com.databricks.sql.managedcatalog.acl.UnauthorizedAccessException: PERMISSION_DENIED: the cloud provider returned access denied, check the configuration of the service credential"}, "L1_uc_read_rest": {"outcome": "refused (HTTP 403 PERMISSION_DENIED)", "http_status": 403, "error_code": "PERMISSION_DENIED", "message": "the cloud provider returned access denied, check the configuration of the service credential"}, "L1_uc_read_real_hash": {"outcome": "Key Vault refused the service credential", "exception": "py4j.protocol.Py4JJavaError", "message": ": com.databricks.sql.managedcatalog.acl.UnauthorizedAccessException: PERMISSION_DENIED: the cloud provider returned access denied, check the configuration of the service credential"}, "L2_compute_dns": {"outcome": "public address", "canonical": "<kv-traffic-manager-canonical>", "aliases": ["kv-ucsec-<workspace-id>.vault.azure.net", "<kv-privatelink-alias>", "<kv-weu-alias-2>", "<kv-regional-alias-3>", "<kv-identity-alias-4>"], "addresses": {"<public-ip-4>": "public", "<public-ip-5>": "public", "<public-ip-6>": "public"}}, "L3_compute_unauth": {"outcome": "HTTP 401 challenge: the vault answered this compute", "http_status": 401, "www_authenticate_present": true, "www_authenticate_scheme": "Bearer", "error_code": "Unauthorized", "message": "AKV10000: Request is missing a Bearer, PoP, or MTLS_POP token."}, "L4_compute_connector_token": {"outcome": "HTTP 403 Forbidden", "token_identity": {"oid": "<connector-oid>", "appid": "<connector-appid>", "idtyp": "app", "xms_mirid": "/subscriptions/<subscription-id>/resourceGroups/rg-uc-secrets-demo/providers/Microsoft.Databricks/accessConnectors/dbac-uc-secrets-demo"}, "message": "Request was not allowed by NSP rules. \r\nClient address: 0.0.0.0\r\nCaller: name=microsoft.databricks/accessconnectors;appid=<connector-appid>;oid=<connector-oid>\r\nVault: kv-ucsec-<workspace-id>;location=westeurope", "inner_code": "ForbiddenByNsp"}, "L5_gateway": {"outcome": "denied by Databricks (no EXECUTE, or the secret could not be resolved)", "http_status": 403, "error_code": "PERMISSION_DENIED", "upstream_status": null, "elapsed_s": 0.8, "message": "the cloud provider returned access denied, check the configuration of the service credential"}}}
```

### Row 19: ws-demo, serverless, vault open, perimeter Enforced + subscription rule

`run_id` <run-or-timestamp-id> / task `run_id` <run-or-timestamp-id>, SUCCESS, submitted 2026-10-30 15:02:33 UTC, ended 15:06:54.

**Topology matrix: from this workspace and this compute, which lanes to the Key Vault-backed secret work?**


**Parameters and helpers**

```text
run_label: vault open + NSP Enforced + subscription rule: ws-demo serverless
workspace host: https://adb-<workspace-id>.14.azuredatabricks.net | SDK host: https://adb-<workspace-id>.14.azuredatabricks.net | databricks-sdk 0.122.0 | SDK HTTP timeout: 60 s | gateway client timeout: 360 s
```

**1. Where am I**

```text
[W1_workspace] workspace <workspace-id>  {"host": "https://adb-<workspace-id>.14.azuredatabricks.net", "sdk_host": "https://adb-<workspace-id>.14.azuredatabricks.net"}
[W2_metastore] metastore_azure_westeurope (westeurope)  {"metastore_id": "<metastore-id>", "cloud": "azure"}
[W3_compute] serverless  {"DATABRICKS_RUNTIME_VERSION": "client.6.5", "DATABRICKS_ENV_VERSION": "6", "spark": "4.2.0", "driver_ip": "<private-ip-2>", "driver_ip_rfc1918": true}
[W4_caller] <user>  {"workspace_admin": true}
```

**2. Catalog visibility, binding and the secret chain**

```text
[C1_catalog] visible, isolation OPEN  {"metastore_id": "<metastore-id>"}
[C2_catalog_bindings] 0 workspace binding(s)  {"bindings": []}
[C3_secret_listing] 2 secret(s)  {"secrets": ["uc_secrets_demo.secrets.apimlanekey", "uc_secrets_demo.secrets.dummysecret"]}
[C4_connection] AZURE_KEY_VAULT -> vault kv-ucsec-<workspace-id>  {"credential": "uc_secrets_demo"}
[C5_credential] SERVICE credential, isolation ISOLATION_MODE_OPEN  {"access_connector_id": "/subscriptions/<subscription-id>/resourceGroups/rg-uc-secrets-demo/providers/Microsoft.Databricks/accessConnectors/dbac-uc-secrets-demo", "managed_identity_id": "/subscriptions/<subscription-id>/resourceGroups/rg-uc-secrets-demo/providers/Microsoft.ManagedIdentity/userAssignedIdentities/id-uc-secrets-demo"}
vault under test: kv-ucsec-<workspace-id>.vault.azure.net
```

**3. UC read lane**

```text
[L1_uc_read_dbutils] value ok  {"length": 20, "sha256_prefix": "<dummy-sha256-prefix>"}
[L1_uc_read_rest] value ok  {"length": 20, "sha256_prefix": "<dummy-sha256-prefix>"}
[L1_uc_read_real_hash] value ok  {"length": 64, "sha256_prefix": "<secret-sha256-prefix-1>"}
```

**4. Compute DNS lane**

```text
[L2_compute_dns] private endpoint address  {"canonical": "kv-ucsec-<workspace-id>.vault.azure.net", "aliases": [], "addresses": {"<ncc-private-endpoint-ip>": "private (RFC 1918)", "::ffff:<ncc-private-endpoint-ip>": "private (RFC 1918)"}}
```

**5. Compute direct, no token**

```text
[L3_compute_unauth] HTTP 401 challenge: the vault answered this compute  {"http_status": 401, "www_authenticate_present": true, "www_authenticate_scheme": "Bearer", "error_code": "Unauthorized", "message": "AKV10000: Request is missing a Bearer, PoP, or MTLS_POP token."}
```

**6. Compute direct, with the identity Unity Catalog uses**

```text
token identity: {"oid": "<connector-oid>", "appid": "<connector-appid>", "idtyp": "app", "xms_mirid": "/subscriptions/<subscription-id>/resourceGroups/rg-uc-secrets-demo/providers/Microsoft.Databricks/accessConnectors/dbac-uc-secrets-demo"}
[L4_compute_connector_token] HTTP 200: value ok  {"token_identity": {"oid": "<connector-oid>", "appid": "<connector-appid>", "idtyp": "app", "xms_mirid": "/subscriptions/<subscription-id>/resourceGroups/rg-uc-secrets-demo/providers/Microsoft.Databricks/accessConnectors/dbac-uc-secrets-demo"}, "sha256_prefix": "<dummy-sha256-prefix>", "same_as_uc_read": true}
```

**7. Unity Gateway lane**

```text
HTTP 502 after 230.9 s (64% of the 360 s client timeout)
error_code=INTERNAL_ERROR upstream_status=500
message: Model Provider Service returned error with status code 500: Internal server error. The model provider returned a server error — this is usually transient, so retry with backoff; if it persists, check the provider's status page.
verdict: bearer accepted by APIM; the upstream model failed (upstream_status 500)
[L5_gateway] bearer accepted by APIM; the upstream model failed (upstream_status 500)  {"http_status": 502, "error_code": "INTERNAL_ERROR", "upstream_status": 500, "elapsed_s": 230.9, "message": "Model Provider Service returned error with status code 500: Internal server error. The model provider returned a server error \u2014 this is usually transient, so retry with backoff; if it persists, check the provider's status page."}
```

**8. Summary**

```text
workspace <workspace-id> | metastore_azure_westeurope (westeurope) | serverless | driver <private-ip-2> | run_label vault open + NSP Enforced + subscription rule: ws-demo serverless
vault kv-ucsec-<workspace-id>.vault.azure.net | catalog visible, isolation OPEN | credential SERVICE credential, isolation ISOLATION_MODE_OPEN
lane                                     outcome
UC read, dbutils (dummy)                 value ok
UC read, REST include_value (dummy)      value ok
UC read, dbutils (real, hash only)       value ok
compute DNS                              private endpoint address
compute direct, no token                 HTTP 401 challenge: the vault answered this compute
compute direct, connector token          HTTP 200: value ok
Unity Gateway                            bearer accepted by APIM; the upstream model failed (upstream_status 500)
```
```text
{"run_label": "vault open + NSP Enforced + subscription rule: ws-demo serverless", "claims": {"W1_workspace": {"outcome": "workspace <workspace-id>", "host": "https://adb-<workspace-id>.14.azuredatabricks.net", "sdk_host": "https://adb-<workspace-id>.14.azuredatabricks.net"}, "W2_metastore": {"outcome": "metastore_azure_westeurope (westeurope)", "metastore_id": "<metastore-id>", "cloud": "azure"}, "W3_compute": {"outcome": "serverless", "DATABRICKS_RUNTIME_VERSION": "client.6.5", "DATABRICKS_ENV_VERSION": "6", "spark": "4.2.0", "driver_ip": "<private-ip-2>", "driver_ip_rfc1918": true}, "W4_caller": {"outcome": "<user>", "workspace_admin": true}, "C1_catalog": {"outcome": "visible, isolation OPEN", "metastore_id": "<metastore-id>"}, "C2_catalog_bindings": {"outcome": "0 workspace binding(s)", "bindings": []}, "C3_secret_listing": {"outcome": "2 secret(s)", "secrets": ["uc_secrets_demo.secrets.apimlanekey", "uc_secrets_demo.secrets.dummysecret"]}, "C4_connection": {"outcome": "AZURE_KEY_VAULT -> vault kv-ucsec-<workspace-id>", "credential": "uc_secrets_demo"}, "C5_credential": {"outcome": "SERVICE credential, isolation ISOLATION_MODE_OPEN", "access_connector_id": "/subscriptions/<subscription-id>/resourceGroups/rg-uc-secrets-demo/providers/Microsoft.Databricks/accessConnectors/dbac-uc-secrets-demo", "managed_identity_id": "/subscriptions/<subscription-id>/resourceGroups/rg-uc-secrets-demo/providers/Microsoft.ManagedIdentity/userAssignedIdentities/id-uc-secrets-demo"}, "L1_uc_read_dbutils": {"outcome": "value ok", "length": 20, "sha256_prefix": "<dummy-sha256-prefix>"}, "L1_uc_read_rest": {"outcome": "value ok", "length": 20, "sha256_prefix": "<dummy-sha256-prefix>"}, "L1_uc_read_real_hash": {"outcome": "value ok", "length": 64, "sha256_prefix": "<secret-sha256-prefix-1>"}, "L2_compute_dns": {"outcome": "private endpoint address", "canonical": "kv-ucsec-<workspace-id>.vault.azure.net", "aliases": [], "addresses": {"<ncc-private-endpoint-ip>": "private (RFC 1918)", "::ffff:<ncc-private-endpoint-ip>": "private (RFC 1918)"}}, "L3_compute_unauth": {"outcome": "HTTP 401 challenge: the vault answered this compute", "http_status": 401, "www_authenticate_present": true, "www_authenticate_scheme": "Bearer", "error_code": "Unauthorized", "message": "AKV10000: Request is missing a Bearer, PoP, or MTLS_POP token."}, "L4_compute_connector_token": {"outcome": "HTTP 200: value ok", "token_identity": {"oid": "<connector-oid>", "appid": "<connector-appid>", "idtyp": "app", "xms_mirid": "/subscriptions/<subscription-id>/resourceGroups/rg-uc-secrets-demo/providers/Microsoft.Databricks/accessConnectors/dbac-uc-secrets-demo"}, "sha256_prefix": "<dummy-sha256-prefix>", "same_as_uc_read": true}, "L5_gateway": {"outcome": "bearer accepted by APIM; the upstream model failed (upstream_status 500)", "http_status": 502, "error_code": "INTERNAL_ERROR", "upstream_status": 500, "elapsed_s": 230.9, "message": "Model Provider Service returned error with status code 500: Internal server error. The model provider returned a server error \u2014 this is usually transient, so retry with backoff; if it persists, check the provider's status page."}}}
```

### Row 20: ws-demo, classic, vault open, perimeter Enforced + subscription rule

`run_id` <run-or-timestamp-id> / task `run_id` <run-or-timestamp-id>, SUCCESS, submitted 2026-10-30 15:02:34 UTC, ended 15:10:15.

**Topology matrix: from this workspace and this compute, which lanes to the Key Vault-backed secret work?**


**Parameters and helpers**

```text
run_label: vault open + NSP Enforced + subscription rule: ws-demo classic
workspace host: https://adb-<workspace-id>.14.azuredatabricks.net | SDK host: <regional-control-plane-host> | databricks-sdk 0.67.0 | SDK HTTP timeout: 60 s | gateway client timeout: 360 s
```

**1. Where am I**

```text
[W1_workspace] workspace <workspace-id>  {"host": "https://adb-<workspace-id>.14.azuredatabricks.net", "sdk_host": "<regional-control-plane-host>"}
[W2_metastore] metastore_azure_westeurope (westeurope)  {"metastore_id": "<metastore-id>", "cloud": "azure"}
[W3_compute] classic  {"DATABRICKS_RUNTIME_VERSION": "18.3", "DATABRICKS_ENV_VERSION": null, "spark": "4.1.0", "cluster_id": "<cluster-id>", "node_type": "Standard_F4s_v2", "spark_version": "18.x-scala2.13", "driver_ip": "<classic-node-ip>", "driver_ip_rfc1918": true}
[W4_caller] <user>  {"workspace_admin": true}
```

**2. Catalog visibility, binding and the secret chain**

```text
[C1_catalog] visible, isolation OPEN  {"metastore_id": "<metastore-id>"}
[C2_catalog_bindings] 0 workspace binding(s)  {"bindings": []}
[C3_secret_listing] 2 secret(s)  {"secrets": ["uc_secrets_demo.secrets.apimlanekey", "uc_secrets_demo.secrets.dummysecret"]}
[C4_connection] AZURE_KEY_VAULT -> vault kv-ucsec-<workspace-id>  {"credential": "uc_secrets_demo"}
[C5_credential] SERVICE credential, isolation ISOLATION_MODE_OPEN  {"access_connector_id": "/subscriptions/<subscription-id>/resourceGroups/rg-uc-secrets-demo/providers/Microsoft.Databricks/accessConnectors/dbac-uc-secrets-demo", "managed_identity_id": "/subscriptions/<subscription-id>/resourceGroups/rg-uc-secrets-demo/providers/Microsoft.ManagedIdentity/userAssignedIdentities/id-uc-secrets-demo"}
vault under test: kv-ucsec-<workspace-id>.vault.azure.net
```

**3. UC read lane**

```text
[L1_uc_read_dbutils] value ok  {"length": 20, "sha256_prefix": "<dummy-sha256-prefix>"}
[L1_uc_read_rest] value ok  {"length": 20, "sha256_prefix": "<dummy-sha256-prefix>"}
[L1_uc_read_real_hash] value ok  {"length": 64, "sha256_prefix": "<secret-sha256-prefix-1>"}
```

**4. Compute DNS lane**

```text
[L2_compute_dns] public address  {"canonical": "<kv-akadns-canonical>", "aliases": ["kv-ucsec-<workspace-id>.vault.azure.net", "<kv-privatelink-alias>", "<kv-weu-alias-2>", "<kv-regional-alias-3>", "<kv-identity-alias-4>"], "addresses": {"<public-ip-4>": "public", "<public-ip-5>": "public", "<public-ip-6>": "public"}}
```

**5. Compute direct, no token**

```text
[L3_compute_unauth] HTTP 401 challenge: the vault answered this compute  {"http_status": 401, "www_authenticate_present": true, "www_authenticate_scheme": "Bearer", "error_code": "Unauthorized", "message": "AKV10000: Request is missing a Bearer, PoP, or MTLS_POP token."}
```

**6. Compute direct, with the identity Unity Catalog uses**

```text
token identity: {"oid": "<connector-oid>", "appid": "<connector-appid>", "idtyp": "app", "xms_mirid": "/subscriptions/<subscription-id>/resourceGroups/rg-uc-secrets-demo/providers/Microsoft.Databricks/accessConnectors/dbac-uc-secrets-demo"}
[L4_compute_connector_token] HTTP 200: value ok  {"token_identity": {"oid": "<connector-oid>", "appid": "<connector-appid>", "idtyp": "app", "xms_mirid": "/subscriptions/<subscription-id>/resourceGroups/rg-uc-secrets-demo/providers/Microsoft.Databricks/accessConnectors/dbac-uc-secrets-demo"}, "sha256_prefix": "<dummy-sha256-prefix>", "same_as_uc_read": true}
```

**7. Unity Gateway lane**

```text
HTTP 502 after 230.8 s (64% of the 360 s client timeout)
error_code=INTERNAL_ERROR upstream_status=500
message: Model Provider Service returned error with status code 500: Internal server error. The model provider returned a server error — this is usually transient, so retry with backoff; if it persists, check the provider's status page.
verdict: bearer accepted by APIM; the upstream model failed (upstream_status 500)
[L5_gateway] bearer accepted by APIM; the upstream model failed (upstream_status 500)  {"http_status": 502, "error_code": "INTERNAL_ERROR", "upstream_status": 500, "elapsed_s": 230.8, "message": "Model Provider Service returned error with status code 500: Internal server error. The model provider returned a server error \u2014 this is usually transient, so retry with backoff; if it persists, check the provider's status page."}
```

**8. Summary**

```text
workspace <workspace-id> | metastore_azure_westeurope (westeurope) | classic | driver <classic-node-ip> | run_label vault open + NSP Enforced + subscription rule: ws-demo classic
vault kv-ucsec-<workspace-id>.vault.azure.net | catalog visible, isolation OPEN | credential SERVICE credential, isolation ISOLATION_MODE_OPEN
lane                                     outcome
UC read, dbutils (dummy)                 value ok
UC read, REST include_value (dummy)      value ok
UC read, dbutils (real, hash only)       value ok
compute DNS                              public address
compute direct, no token                 HTTP 401 challenge: the vault answered this compute
compute direct, connector token          HTTP 200: value ok
Unity Gateway                            bearer accepted by APIM; the upstream model failed (upstream_status 500)
```
```text
{"run_label": "vault open + NSP Enforced + subscription rule: ws-demo classic", "claims": {"W1_workspace": {"outcome": "workspace <workspace-id>", "host": "https://adb-<workspace-id>.14.azuredatabricks.net", "sdk_host": "<regional-control-plane-host>"}, "W2_metastore": {"outcome": "metastore_azure_westeurope (westeurope)", "metastore_id": "<metastore-id>", "cloud": "azure"}, "W3_compute": {"outcome": "classic", "DATABRICKS_RUNTIME_VERSION": "18.3", "DATABRICKS_ENV_VERSION": null, "spark": "4.1.0", "cluster_id": "<cluster-id>", "node_type": "Standard_F4s_v2", "spark_version": "18.x-scala2.13", "driver_ip": "<classic-node-ip>", "driver_ip_rfc1918": true}, "W4_caller": {"outcome": "<user>", "workspace_admin": true}, "C1_catalog": {"outcome": "visible, isolation OPEN", "metastore_id": "<metastore-id>"}, "C2_catalog_bindings": {"outcome": "0 workspace binding(s)", "bindings": []}, "C3_secret_listing": {"outcome": "2 secret(s)", "secrets": ["uc_secrets_demo.secrets.apimlanekey", "uc_secrets_demo.secrets.dummysecret"]}, "C4_connection": {"outcome": "AZURE_KEY_VAULT -> vault kv-ucsec-<workspace-id>", "credential": "uc_secrets_demo"}, "C5_credential": {"outcome": "SERVICE credential, isolation ISOLATION_MODE_OPEN", "access_connector_id": "/subscriptions/<subscription-id>/resourceGroups/rg-uc-secrets-demo/providers/Microsoft.Databricks/accessConnectors/dbac-uc-secrets-demo", "managed_identity_id": "/subscriptions/<subscription-id>/resourceGroups/rg-uc-secrets-demo/providers/Microsoft.ManagedIdentity/userAssignedIdentities/id-uc-secrets-demo"}, "L1_uc_read_dbutils": {"outcome": "value ok", "length": 20, "sha256_prefix": "<dummy-sha256-prefix>"}, "L1_uc_read_rest": {"outcome": "value ok", "length": 20, "sha256_prefix": "<dummy-sha256-prefix>"}, "L1_uc_read_real_hash": {"outcome": "value ok", "length": 64, "sha256_prefix": "<secret-sha256-prefix-1>"}, "L2_compute_dns": {"outcome": "public address", "canonical": "<kv-akadns-canonical>", "aliases": ["kv-ucsec-<workspace-id>.vault.azure.net", "<kv-privatelink-alias>", "<kv-weu-alias-2>", "<kv-regional-alias-3>", "<kv-identity-alias-4>"], "addresses": {"<public-ip-4>": "public", "<public-ip-5>": "public", "<public-ip-6>": "public"}}, "L3_compute_unauth": {"outcome": "HTTP 401 challenge: the vault answered this compute", "http_status": 401, "www_authenticate_present": true, "www_authenticate_scheme": "Bearer", "error_code": "Unauthorized", "message": "AKV10000: Request is missing a Bearer, PoP, or MTLS_POP token."}, "L4_compute_connector_token": {"outcome": "HTTP 200: value ok", "token_identity": {"oid": "<connector-oid>", "appid": "<connector-appid>", "idtyp": "app", "xms_mirid": "/subscriptions/<subscription-id>/resourceGroups/rg-uc-secrets-demo/providers/Microsoft.Databricks/accessConnectors/dbac-uc-secrets-demo"}, "sha256_prefix": "<dummy-sha256-prefix>", "same_as_uc_read": true}, "L5_gateway": {"outcome": "bearer accepted by APIM; the upstream model failed (upstream_status 500)", "http_status": 502, "error_code": "INTERNAL_ERROR", "upstream_status": 500, "elapsed_s": 230.8, "message": "Model Provider Service returned error with status code 500: Internal server error. The model provider returned a server error \u2014 this is usually transient, so retry with backoff; if it persists, check the provider's status page."}}}
```
