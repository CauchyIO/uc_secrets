#!/usr/bin/env python3
"""Approve, or show, the private endpoint connection that Databricks created on the Key Vault for an NCC rule.

Terraform (ncc_private_endpoint_approval.tf) runs `approve` once per rule. Azure only lets the resource owner approve a private endpoint
connection, which is why this is not something the Databricks side can do for you.

    ./scripts/ncc_private_endpoint.py list    --vault-id <key vault resource id>
    ./scripts/ncc_private_endpoint.py approve --vault-id <key vault resource id> --endpoint-name <databricks-...-pe-...>

Runs the `az` found on PATH. On a machine where IPv6 stalls the Azure CLI, put an IPv4-only shim first on PATH.
The generic `az network private-endpoint-connection list` crashes on a vault that has no connections yet
(KeyError on the missing property), so the vault's own representation is read instead.
"""

import argparse
import json
import os
import time
import subprocess
import sys


def az(*args):
    cmd = ["az", *args, "-o", "json"]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=45)
    except subprocess.TimeoutExpired:
        raise SystemExit("Azure CLI timed out after 45s during endpoint discovery/approval") from None
    if proc.returncode != 0:
        raise SystemExit(f"Azure CLI failed during endpoint discovery/approval (exit {proc.returncode}); check Azure authentication and permissions.")
    return json.loads(proc.stdout) if proc.stdout.strip() else None


def subscription_of(resource_id):
    """The subscription segment of an ARM id; passed explicitly so az picks the right account even when its default
    account lives in another tenant."""
    parts = resource_id.split("/")
    try:
        return parts[parts.index("subscriptions") + 1]
    except (ValueError, IndexError):
        raise SystemExit(f"not an ARM resource id (no /subscriptions/<id>/ segment): {resource_id}")


def connections(vault_id):
    raw = az("resource", "show", "--ids", vault_id, "--subscription", subscription_of(vault_id),
             "--query", "properties.privateEndpointConnections")
    rows = []
    # ARM lists each connection as {id, properties: {privateEndpoint, privateLinkServiceConnectionState}}; the
    # connection has no name field, its name is the last segment of its id.
    for conn in raw or []:
        props = conn["properties"]
        rows.append(
            {
                "id": conn["id"],
                "name": conn["id"].rsplit("/", 1)[-1],
                "private_endpoint": props["privateEndpoint"]["id"].rsplit("/", 1)[-1],
                "status": props["privateLinkServiceConnectionState"]["status"],
                "description": props["privateLinkServiceConnectionState"].get("description"),
            }
        )
    return rows


def cmd_list(args):
    print(json.dumps(connections(args.vault_id), indent=2))
    return 0


def cmd_approve(args):
    # ARM may lag the Databricks rule. Match only the exact endpoint and never approve a sibling.
    for attempt in range(6):
        rows = connections(args.vault_id)
        mine = [r for r in rows if r["private_endpoint"] == args.endpoint_name]
        if mine or attempt == 5:
            break
        sys.stderr.write("NCC connection not visible in ARM yet; retrying in 5s.\n")
        time.sleep(5)
    if not mine:
        names = [r["private_endpoint"] for r in rows]
        raise SystemExit(
            f"no private endpoint connection named {args.endpoint_name} on {args.vault_id}; "
            f"the vault currently has {len(rows)} connection(s): {names}. Databricks may still be creating the "
            "endpoint; run terraform apply again once the rule reports PENDING."
        )
    if len(mine) > 1:
        raise SystemExit(f"{len(mine)} connections carry the endpoint name {args.endpoint_name}; refusing to guess: {mine}")
    conn = mine[0]
    if conn["status"] == "Approved":
        print(f"already approved: {conn['name']}")
        return 0
    if conn["status"] != "Pending":
        raise SystemExit(f"connection {conn['name']} is {conn['status']}, not Pending; nothing to approve")
    result = az(
        "keyvault", "private-endpoint-connection", "approve",
        "--id", conn["id"], "--subscription", subscription_of(conn["id"]),
        "--description", "Approved by Terraform (uc_secrets NCC)",
    )
    status = result["privateLinkServiceConnectionState"]["status"]
    print(f"approved {conn['name']}: status now {status}")
    return 0


def main(argv):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    p_list = sub.add_parser("list", help="show every private endpoint connection on the vault")
    p_list.add_argument("--vault-id", required=True)
    p_list.set_defaults(func=cmd_list)
    p_approve = sub.add_parser("approve", help="approve the pending connection whose private endpoint has this name")
    p_approve.add_argument("--vault-id", default=os.getenv("NCC_VAULT_ID"))
    p_approve.add_argument("--endpoint-name", default=os.getenv("NCC_ENDPOINT_NAME"))
    p_approve.set_defaults(func=cmd_approve)
    args = parser.parse_args(argv)
    if not args.vault_id:
        parser.error("provide --vault-id or NCC_VAULT_ID")
    if args.command == "approve" and not args.endpoint_name:
        parser.error("provide --endpoint-name or NCC_ENDPOINT_NAME")
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
