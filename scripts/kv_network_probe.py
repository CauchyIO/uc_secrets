#!/usr/bin/env python3
"""Where do Unity Catalog's Key Vault reads come from? Make the demo vault's firewall answer.

  ./scripts/kv_network_probe.py closed  --watch-seconds N [--gateway-model ALIAS]
      Public network access Disabled: the private-endpoint-only posture.
  ./scripts/kv_network_probe.py trusted --watch-seconds N [--gateway-model ALIAS]
      Public endpoint open, firewall default action Deny, "Allow trusted Microsoft services" switched on.
  ./scripts/kv_network_probe.py locked  --watch-seconds N [--gateway-model ALIAS]
      Public network access Disabled AND default action Deny AND "Allow trusted Microsoft services" on: the
      posture a Terraform `public_network_access_enabled = false` + `network_acls { default_action = "Deny",
      bypass = "AzureServices" }` produces.
  ./scripts/kv_network_probe.py sealed  --watch-seconds N [--gateway-model ALIAS]
      Public network access Disabled, default action Deny, bypass None: no exception for trusted services.

Alongside the Unity Catalog read the probe also reads a secret directly with `az keyvault secret show`, so the
output shows how quickly the vault enforces the change for a fresh caller versus the Unity Catalog service.

The probe changes the vault's network settings, reads the Unity Catalog secret in a loop until the read fails or
the watch window ends, optionally sends one chat completion through Unity Gateway while the vault is closed, and
then restores the Terraform-managed settings (public access enabled, no rules) and waits until reads work again.
Key Vault enforces network changes on its data plane with a lag of seconds to minutes, which is why a watch window
is required; the probe prints how much of it was used. Run from the Terraform directory after `terraform apply`.
"""
import argparse
import json
import subprocess
import sys
import time


def state_resource(address):
    state = json.loads(subprocess.run(["terraform", "show", "-json"], capture_output=True, text=True, timeout=120, check=True).stdout)
    for resource in state["values"]["root_module"]["resources"]:
        if resource["address"] in {address, address + "[0]"}:
            return resource["values"]
    sys.exit(f"{address} is not in the Terraform state; apply first")


def tf_output(name):
    outputs = json.loads(subprocess.run(["terraform", "output", "-json"], capture_output=True, text=True, timeout=120, check=True).stdout)
    return outputs.get(name, {}).get("value") or ""


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("mode", choices=["closed", "trusted", "locked", "sealed"])
    parser.add_argument("--watch-seconds", type=float, required=True,
                        help="how long to keep reading before concluding that the vault never blocked Unity Catalog")
    parser.add_argument("--gateway-model", help="also send one chat completion through Unity Gateway while the vault is closed")
    args = parser.parse_args()
    if args.watch_seconds <= 0:
        parser.error("--watch-seconds must be positive")

    vault = state_resource("azurerm_key_vault.demo")
    kv_name, subscription = vault["name"], vault["id"].split("/")[2]
    dummy_secret = state_resource("azurerm_key_vault_secret.dummy")["name"]
    profile, secret = tf_output("databricks_profile"), tf_output("unity_catalog_secret_for_lane")
    t0 = time.time()

    def stamp():
        return f"[{time.time() - t0:6.1f}s]"

    def az(*argv):
        r = subprocess.run(["az", "keyvault", *argv, "--name", kv_name, "--subscription", subscription], capture_output=True, text=True, timeout=120)
        if r.returncode != 0:
            sys.exit(f"az keyvault {argv[0]} failed: {r.stderr.strip()}")
        return r.stdout

    def network_state():
        return json.loads(az("show", "--query", "{public:properties.publicNetworkAccess, acls:properties.networkAcls}", "-o", "json"))

    def uc_read():
        r = subprocess.run(["databricks", "api", "get", f"/api/2.1/unity-catalog/secrets/{secret}?include_value=true", ] + (["-p", profile] if profile else []),
                           capture_output=True, text=True, timeout=120)
        return r.returncode == 0, "read succeeded" if r.returncode == 0 else "UC read failed; response omitted"

    def external_read():
        r = subprocess.run(["az", "keyvault", "secret", "show", "--vault-name", kv_name, "--name", dummy_secret, "--subscription", subscription,
                            "--query", "name", "-o", "tsv"], capture_output=True, text=True, timeout=120)
        return "ok" if r.returncode == 0 else "denied: " + r.stderr.strip().splitlines()[0][:160]

    def watch(label, until_ok, seconds):
        """Read until the outcome flips to the wanted one or the window ends; print only the transition."""
        start, reads, ok, out = time.time(), 0, None, ""
        while time.time() - start < seconds:
            reads += 1
            ok, out = uc_read()
            if ok == until_ok:
                detail = "(value redacted)" if ok else out[:400]
                print(f"{stamp()} {label}: {'reads succeed' if ok else 'read FAILED'} after {reads} reads, "
                      f"{100 * (time.time() - start) / seconds:.0f}% of the {seconds:.0f}s window: {detail}")
                return True
        last = "succeeded" if ok else f"failed: {out[:400]}"
        print(f"{stamp()} {label}: outcome never changed in {reads} reads over the full {seconds:.0f}s window; last read {last}")
        return False

    baseline = network_state()
    print("baseline:", json.dumps(baseline))
    acls = baseline["acls"] or {}
    if baseline["public"] != "Enabled" or acls.get("defaultAction", "Allow") != "Allow" or acls.get("bypass") != "AzureServices":
        sys.exit("the vault is not in the open Terraform-managed posture; restore it before probing so runs do not inherit state")
    ok, out = uc_read()
    if not ok:
        sys.exit(f"the baseline Unity Catalog read already fails, fix that before probing the network: {out[:400]}")

    change = {
        "closed": ["update", "--public-network-access", "Disabled"],
        "trusted": ["update", "--public-network-access", "Enabled", "--default-action", "Deny", "--bypass", "AzureServices"],
        "locked": ["update", "--public-network-access", "Disabled", "--default-action", "Deny", "--bypass", "AzureServices"],
        "sealed": ["update", "--public-network-access", "Disabled", "--default-action", "Deny", "--bypass", "None"],
    }[args.mode]
    verdicts = {
        ("closed", True): "Unity Catalog reaches Key Vault over the vault's PUBLIC endpoint; a private-endpoint-only vault blocks it.",
        ("closed", False): "Unity Catalog kept reading with public access disabled; this alone does not distinguish a trusted-services bypass from a private path.",
        ("trusted", True): "The 'Allow trusted Microsoft services' exception does NOT admit Unity Catalog's reads.",
        ("trusted", False): "The 'Allow trusted Microsoft services' exception admits Unity Catalog's reads.",
        ("locked", True): "Public access off + Deny + trusted-services exception blocks Unity Catalog once the vault enforces it.",
        ("locked", False): "Public access off + Deny + trusted-services exception still lets Unity Catalog read.",
        ("sealed", True): "With no trusted-services exception the vault blocks Unity Catalog.",
        ("sealed", False): "Unity Catalog still read with public access off, Deny and no trusted-services exception.",
    }
    try:
        az(*change, "-o", "none")
        print(f"{stamp()} applied {args.mode}:", json.dumps(network_state()))
        print(f"{stamp()} direct az read right after the change:", external_read())
        blocked = watch(f"UC read with the vault {args.mode}", until_ok=False, seconds=args.watch_seconds)
        print(f"{stamp()} direct az read now:", external_read())
        if args.gateway_model:
            print(f"{stamp()} Unity Gateway query while the vault is {args.mode}:")
            r = subprocess.run(["./scripts/smoke_test.sh", "query", args.gateway_model], capture_output=True, text=True, timeout=120)
            print((r.stdout + r.stderr).strip()[:1500])
        print("RESULT:", verdicts[(args.mode, blocked)])
    finally:
        az("update", "--public-network-access", "Enabled", "--default-action", "Allow", "--bypass", "AzureServices", "-o", "none")
        print(f"{stamp()} restored:", json.dumps(network_state()))
        watch("UC read after the restore", until_ok=True, seconds=args.watch_seconds)
        print(f"{stamp()} direct az read after the restore:", external_read())


if __name__ == "__main__":
    main()
