#!/usr/bin/env python3
"""Print a notebooks/TOPOLOGY.md raw-output section for one run: heading, run line, then every cell's heading and text
output from the run's CODE export (extract_cells.py), with the write-up's placeholders applied so that no identity, id,
private address or host name of the estate lands in the document.

    measurements/row_section.py "<row title>" <export json> <get-run json> [--replace real=placeholder ...]

What is derived, and from where:
- the Terraform state: the subscription and tenant (from the vault), the connector identity's object and application
  ids (from the user-assigned identity), the deploying user's object id (azurerm_client_config), the demo workspace id
  (from the workspace host, adb-<id>.<n>.azuredatabricks.net; it also covers the vault name kv-ucsec-<id>) and the
  vault's private-link alias;
- the workspace: the signed-in user, the metastore id and the model aliases the provider service targets;
- the run's own output: the classic driver's address and any private (RFC 1918) address the vault name resolved to
  (in this demo only the NCC private endpoint has one);
- patterns: Azure's DNS alias chain for a Key Vault, the regional control-plane host and the LiteLLM deployment id in a
  cooldown message.
Extra --replace pairs apply first. They are for what none of this covers: another workspace's id or metastore id, the
reference-only service principal's application id (rows A1 and A2, `<sp-application-id>`), and the laptop's address.
"""
import argparse
import datetime
import json
import pathlib
import re
import subprocess
import sys

MEASURE_DIR = pathlib.Path(__file__).resolve().parent
TF_DIR = MEASURE_DIR.parent

# Azure's alias chain behind <vault>.vault.azure.net, as the notebook's DNS lane prints it, the regional control-plane
# host a classic cluster's SDK points at, and LiteLLM's deployment id in its cooldown message (plain, and escaped once or
# twice inside JSON); the placeholders match the ones used in every existing row of notebooks/TOPOLOGY.md.
PATTERNS = [
    (r"\b[0-9]{4}-[0-9]{6}-[a-z0-9]+\b", "<cluster-id>"),
    (r"(?<![\w-])[0-9a-f]{12}(?![\w-])", "<sha256-prefix>"),
    (r"\b(?!00000000-0000-0000-0000-000000000000)[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}\b", "<request-or-resource-id>"),
    (r"(?<![\w.])[1-9][0-9]{11,}(?![\w.])", "<run-or-timestamp-id>"),
    (r"https://[a-z0-9]+-c\d\.azuredatabricks\.net", "<regional-control-plane-host>"),
    (r"[a-z]+\.tm\.prd\.r\.kv\.aadg\.trafficmanager\.net", "<kv-traffic-manager-canonical>"),
    (r"[a-z]+\.tm\.prd\.r\.kv\.aadg\.akadns\.net", "<kv-akadns-canonical>"),
    (r"data-prod-[a-z]+-region\.vaultcore\.azure\.net", "<kv-regional-alias-3>"),
    (r"data-prod-[a-z]+\.vaultcore\.azure\.net", "<kv-weu-alias-2>"),
    (r"[a-z]+\.prd\.r\.kv\.aadg\.msidentity\.com", "<kv-identity-alias-4>"),
    (r"(cooldown_list=\[\(\\*')[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", r"\1<litellm-deployment-id>"),
]
WORKSPACE_ID_IN_HOST = re.compile(r"adb-(\d+)\.\d+\.azuredatabricks\.net")
# The notebooks print every claim as "[claim] outcome  {json detail}".
CLAIM_LINE = re.compile(r"^\[(?P<claim>\w+)\] .*?  (?P<detail>\{.*\})$", re.M)


def databricks_json(profile, *args):
    return json.loads(subprocess.run(["databricks", *args] + (["-p", profile] if profile else []), capture_output=True, text=True, timeout=120, check=True).stdout)


def state_pairs():
    """(real value, placeholder) pairs from the applied state and the workspace."""
    state = json.loads(subprocess.run(["terraform", "show", "-json"], cwd=TF_DIR, capture_output=True, text=True, timeout=120, check=True).stdout)["values"]
    res = {r["address"]: r["values"] for r in state["root_module"]["resources"]}
    outs = {k: v["value"] for k, v in state["outputs"].items()}
    profile = outs.get("databricks_profile") or ""
    kv = res["azurerm_key_vault.demo"]
    identity = res["azurerm_user_assigned_identity.key_vault_reader"]
    host = outs["workspace_host"]
    m = WORKSPACE_ID_IN_HOST.search(host)
    if m is None:
        raise SystemExit(f"workspace_host {host!r} is not an adb-<workspace id>.<n>.azuredatabricks.net host; "
                         "pass the workspace id as --replace <id>=<workspace-id>")
    pairs = [
        (databricks_json(profile, "current-user", "me", "-o", "json")["userName"], "<user>"),
        (f"{kv['name']}.privatelink.vaultcore.azure.net", "<kv-privatelink-alias>"),
        (m.group(1), "<workspace-id>"),
        (kv["id"].split("/")[2], "<subscription-id>"),
        (kv["tenant_id"], "<tenant-id>"),
        (identity["principal_id"], "<connector-oid>"),
        (identity["client_id"], "<connector-appid>"),
        (res["data.azurerm_client_config.current"]["object_id"], "<user-oid>"),
        (databricks_json(profile, "api", "get", "/api/2.1/unity-catalog/metastore_summary")["metastore_id"], "<metastore-id>"),
    ]
    provider = databricks_json(profile, "api", "get", f"/api/2.1/unity-catalog/model-provider-services/{outs['model_provider_service']}")
    return pairs + [(t["model"], "<model-alias>") for t in provider["config"]["targets"]]


def output_pairs(body):
    """(real value, placeholder) pairs from the run's own output, `body` as extracted (before any replacement, so the claims'
    JSON still parses)."""
    pairs = []
    for claim in CLAIM_LINE.finditer(body):
        if claim["claim"] == "W3_compute":
            detail = json.loads(claim["detail"])
            if "cluster_id" in detail:  # classic: the driver sits in the workspace's own VNet
                pairs.append((detail["driver_ip"], "<classic-node-ip>"))
        elif claim["claim"] == "L2_compute_dns":
            pairs += [(a.removeprefix("::ffff:"), "<ncc-private-endpoint-ip>")
                      for a, kind in json.loads(claim["detail"]).get("addresses", {}).items() if kind.startswith("private")]
    return pairs


def scrub(body, replace, derived):
    """--replace pairs first, then the derived pairs, then the patterns."""
    for real, placeholder in replace:
        body = body.replace(real, placeholder)
    # Longest value first, so the vault's private-link alias is replaced before the workspace id inside it. A value
    # only counts where it is not part of a longer word, number or dotted address (a workspace id inside a run id, say).
    for real, placeholder in sorted(set(derived), key=lambda p: -len(p[0])):
        if real:
            body = re.sub(rf"(?<![\w.]){re.escape(real)}(?!\w)", placeholder, body)
    for pattern, placeholder in PATTERNS:
        body = re.sub(pattern, placeholder, body)
    return body


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("title")
    parser.add_argument("export_json")
    parser.add_argument("run_json")
    parser.add_argument("--replace", action="append", default=[], metavar="REAL=PLACEHOLDER")
    args = parser.parse_args()

    run = json.load(open(args.run_json))
    stamp = lambda ms: datetime.datetime.fromtimestamp(ms / 1000, datetime.timezone.utc)
    start, end = stamp(run["start_time"]), stamp(run["end_time"])
    body = subprocess.run([sys.executable, "-I", str(MEASURE_DIR / "extract_cells.py"), args.export_json],
                          capture_output=True, text=True, timeout=120, check=True).stdout
    body = scrub(body, [pair.split("=", 1) for pair in args.replace], state_pairs() + output_pairs(body))
    print(f"### {args.title}\n")
    print(f"`run_id` <run-id> / task `run_id` <task-run-id>, {run['state']['result_state']}, submitted {start:%Y-%m-%d %H:%M:%S} UTC, ended {end:%H:%M:%S}.")
    print(body.rstrip())


if __name__ == "__main__":
    main()
