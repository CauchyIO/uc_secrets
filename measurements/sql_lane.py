#!/usr/bin/env python3
"""SQL warehouse lane (phase 6): can a SQL warehouse reach the Key Vault-backed secret, through which SQL surfaces, and
under which vault posture?

Runs every statement on a SQL warehouse of the demo workspace through the Statement Execution API as the signed-in
user, flips the vault posture with az (open -> locked -> sealed) around the UDF calls, and restores the vault and drops
the throwaway schema on every exit path. Values never leave the warehouse: every statement returns length and SHA-256
prefix only.

    measurements/sql_lane.py --warehouse-id <id> [--legacy-scope <scope> --legacy-key <key>] [--out <dir>]

`databricks warehouses list -p <profile>` shows the ids. The legacy pair, when given, measures the SQL `secret()`
function against a workspace secret scope next to the Unity Catalog lanes. Every other name comes from the applied
Terraform state, so the script runs from anywhere inside the repository.
"""

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

MEASURE_DIR = Path(__file__).resolve().parent
TF_DIR = MEASURE_DIR.parent
# The topology notebook's Unity Gateway budget (360 s, notebooks/topology_matrix.py) is the longest wait this demo
# justifies anywhere: it bounds every statement here and the wait for the vault's enforcement edge, as phases 3 to 5 did.
BUDGET_S = 360
POLL_S = 5  # statement polling; the API's own long-poll wait is 50 s, so this only matters after it returns RUNNING

results = {"statements": [], "postures": []}


def log(msg):
    print(f"[{time.strftime('%H:%M:%S', time.gmtime())}] {msg}", flush=True)


def run(cmd, check=True):
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if check and proc.returncode != 0:
        raise SystemExit(f"{' '.join(cmd)} failed with exit code {proc.returncode}:\n{proc.stderr.strip()}")
    return proc


def terraform_state():
    """Resource values and outputs of the applied root module."""
    state = json.loads(run(["terraform", "show", "-json"]).stdout)["values"]
    return ({r["address"]: r["values"] for r in state["root_module"]["resources"]},
            {k: v["value"] for k, v in state["outputs"].items()})


UDF_DDL = """CREATE OR REPLACE FUNCTION {name}() RETURNS STRING LANGUAGE PYTHON
SECRETS ({catalog}.{schema}.{key})
{environment}COMMENT 'Throwaway probe: length and SHA-256 prefix of a Unity Catalog secret, never its value. Dropped by the script that created it.'
AS $$
import hashlib
from databricks.secrets import get
v = get(catalog="{catalog}", schema="{schema}", key="{key}")
return f"{{len(v)}}:{{hashlib.sha256(v.encode()).hexdigest()[:12]}}"
$$"""


class Lane:
    def __init__(self, args):
        res, outs = terraform_state()
        kv = res["azurerm_key_vault.demo"]
        self.sub, self.kv = kv["id"].split("/")[2], kv["name"]
        self.catalog = res["databricks_catalog.demo"]["name"]
        self.schema = res["databricks_schema.secrets"]["name"]
        fixture = res.get("azurerm_key_vault_secret.dummy[0]") or res.get("azurerm_key_vault_secret.dummy")
        if not fixture:
            raise SystemExit("SQL measurements require create_dummy_secret = true in a test deployment")
        self.dummy = fixture["name"]
        self.lane = res["azurerm_key_vault_secret.lane"]["name"]
        self.provider = outs["model_provider_service"]
        self.profile = outs.get("databricks_profile") or ""
        self.warehouse = args.warehouse_id
        self.legacy = (args.legacy_scope, args.legacy_key) if args.legacy_scope else None
        self.probe_schema = f"{self.catalog}.sql_lane"
        self.dummy_udf = f"{self.probe_schema}.dummy_secret_sha"
        self.real_udf = f"{self.probe_schema}.real_secret_sha"
        self.out = Path(args.out)
        self.out.mkdir(parents=True, exist_ok=True)

    def api(self, method, path, body=None):
        cmd = ["databricks", "api", method, path] + (["-p", self.profile] if self.profile else [])
        if body is not None:
            cmd += ["--json", json.dumps(body)]
        proc = run(cmd, check=False)
        if proc.returncode != 0:
            raise RuntimeError(f"databricks api {method} {path} failed with exit code {proc.returncode}: {proc.stderr.strip()[:500]}")
        return json.loads(proc.stdout) if proc.stdout.strip() else {}

    def statement(self, label, sql, posture=None):
        """Execute one statement, wait for its terminal state within the budget, and record what came back."""
        t0 = time.monotonic()
        d = self.api("post", "/api/2.0/sql/statements",
                     {"warehouse_id": self.warehouse, "statement": sql, "wait_timeout": "50s", "on_wait_timeout": "CONTINUE"})
        sid = d["statement_id"]
        while d["status"]["state"] in ("PENDING", "RUNNING"):
            if time.monotonic() - t0 >= BUDGET_S:
                self.api("post", f"/api/2.0/sql/statements/{sid}/cancel")
                log(f"{label}: cancelled after {BUDGET_S} s (100% of the budget)")
                break
            time.sleep(POLL_S)
            d = self.api("get", f"/api/2.0/sql/statements/{sid}")
        elapsed = round(time.monotonic() - t0, 1)
        state = d["status"]["state"]
        rec = {"label": label, "posture": posture, "sql": sql, "statement_id": sid, "state": state, "elapsed_s": elapsed}
        if state == "SUCCEEDED":
            rec["rows"] = d.get("result", {}).get("data_array")
            rec["columns"] = [c["name"] for c in d.get("manifest", {}).get("schema", {}).get("columns", [])]
            log(f"{label}: SUCCEEDED in {elapsed} s -> {rec['columns']} {rec['rows']}")
        else:
            err = d["status"].get("error") or {}
            rec["error_code"] = err.get("error_code")
            rec["message"] = (err.get("message") or "")[:600]
            log(f"{label}: {state} in {elapsed} s -> {rec['error_code']}: {rec['message'][:300]}")
        results["statements"].append(rec)
        return rec

    def posture(self):
        proc = run(["az", "keyvault", "show", "--subscription", self.sub, "-n", self.kv, "--query",
                    "{public:properties.publicNetworkAccess, deny:properties.networkAcls.defaultAction, bypass:properties.networkAcls.bypass}", "-o", "json"])
        return json.loads(proc.stdout)

    def set_posture(self, name, public, deny, bypass, refusal_markers):
        log(f"{name.upper()}: public {public}, default {deny}, bypass {bypass}")
        run(["az", "keyvault", "update", "--subscription", self.sub, "-n", self.kv, "--public-network-access", public,
             "--default-action", deny, "--bypass", bypass, "-o", "none"])
        log(f"posture now: {json.dumps(self.posture())}")
        t0 = time.monotonic()
        while True:
            proc = run(["az", "keyvault", "secret", "show", "--subscription", self.sub, "--vault-name", self.kv, "-n", self.dummy,
                        "--query", "id", "-o", "tsv"], check=False)
            text = proc.stdout + proc.stderr
            if any(m in text for m in refusal_markers):
                waited = round(time.monotonic() - t0, 1)
                log(f"direct read with my identity refused after {waited} s: enforcement is live")
                results["postures"].append({"posture": name, "public": public, "deny": deny, "bypass": bypass, "enforced_after_s": waited})
                return
            if time.monotonic() - t0 >= BUDGET_S:
                raise SystemExit(f"enforcement never showed up within {BUDGET_S} s (100% of the budget); aborting")
            time.sleep(POLL_S)

    def restore(self):
        log("RESTORE: reopening the vault")
        run(["az", "keyvault", "update", "--subscription", self.sub, "-n", self.kv, "--public-network-access", "Enabled",
             "--default-action", "Allow", "--bypass", "AzureServices", "-o", "none"])
        log(f"restored posture: {json.dumps(self.posture())}")
        proc = run(["databricks", "api", "get", f"/api/2.1/unity-catalog/secrets/{self.catalog}.{self.schema}.{self.dummy}?include_value=true",
                    ] + (["-p", self.profile] if self.profile else []), check=False)
        ok = proc.returncode == 0 and ("effective_value" in proc.stdout or '"value"' in proc.stdout)
        log(f"UC read after restore: {'ok, value present' if ok else 'read failed; response omitted'}")

    def cleanup(self):
        log("CLEANUP: dropping the throwaway functions and schema")
        for sql in (f"DROP FUNCTION IF EXISTS {self.dummy_udf}", f"DROP FUNCTION IF EXISTS {self.real_udf}",
                    f"DROP SCHEMA IF EXISTS {self.probe_schema}"):
            self.statement("cleanup", sql)

    def measure(self):
        log(f"pre-check posture: {json.dumps(self.posture())}")
        if self.posture() != {"public": "Enabled", "deny": "Allow", "bypass": "AzureServices"}:
            raise SystemExit("vault is not open; refusing to start")
        try:
            self.statement("S0_warehouse", "SELECT current_user() AS me, current_version().dbsql_version AS dbsql_version, current_metastore() AS metastore")
            self.statement("S0_schema", f"CREATE SCHEMA IF NOT EXISTS {self.probe_schema} COMMENT 'Throwaway: SQL warehouse lane probe. Safe to drop.'")

            # S1/S2: the legacy scope has a SQL function; what about Unity Catalog secrets?
            if self.legacy:
                scope, key = self.legacy
                self.statement("S1_legacy_secret_fn", f"SELECT length(secret('{scope}', '{key}')) AS len, left(sha2(secret('{scope}', '{key}'), 256), 12) AS sha256_prefix")
            self.statement("S2a_secret_fn_3_part_name", f"SELECT left(sha2(secret('{self.catalog}.{self.schema}.{self.dummy}'), 256), 12) AS sha256_prefix")
            self.statement("S2b_secret_fn_3_args", f"SELECT left(sha2(secret('{self.catalog}', '{self.schema}', '{self.dummy}'), 256), 12) AS sha256_prefix")
            self.statement("S2c_secret_fn_schema_as_scope", f"SELECT left(sha2(secret('{self.catalog}.{self.schema}', '{self.dummy}'), 256), 12) AS sha256_prefix")

            # S3: the documented SQL surface, a Unity Catalog Python UDF with a SECRETS clause, created from the warehouse.
            for name, key in ((self.dummy_udf, self.dummy), (self.real_udf, self.lane)):
                rec = self.statement(f"S3_create_udf_{key}", UDF_DDL.format(name=name, catalog=self.catalog, schema=self.schema, key=key,
                                                                             environment="ENVIRONMENT (environment_version = '6')\n"))
                if rec["state"] != "SUCCEEDED" and "ENVIRONMENT" in (rec.get("message") or "").upper():
                    self.statement(f"S3_create_udf_{key}_no_environment", UDF_DDL.format(name=name, catalog=self.catalog, schema=self.schema, key=key, environment=""))
            call = f"SELECT {self.dummy_udf}() AS dummy_len_sha, {self.real_udf}() AS real_len_sha"
            self.statement("S4_udf_open", call, posture="open")
            self.statement("S4_udf_open_again", call, posture="open")

            # S5/S6: the same call with the vault locked (trusted services on) and sealed (trusted services off).
            self.set_posture("locked", "Disabled", "Deny", "AzureServices", ("Public network access is disabled",))
            self.statement("S5_udf_locked", call, posture="locked")
            self.statement("S5_udf_locked_again", call, posture="locked")
            self.set_posture("sealed", "Disabled", "Deny", "None", ("bypass is not set", "Public network access is disabled"))
            self.statement("S6_udf_sealed", call, posture="sealed")
            self.statement("S6_udf_sealed_again", call, posture="sealed")
        finally:
            self.restore()
        try:
            # S7: Unity Gateway from SQL. ai_query addresses model serving endpoints; whether it knows a model provider service is the question.
            self.statement("S7_ai_query_provider_service", f"SELECT ai_query('{self.provider}', 'Reply with the single word: ok') AS answer", posture="open")
            self.statement("S7_ai_query_short_name", f"SELECT ai_query('{self.provider.split('.')[-1]}', 'Reply with the single word: ok') AS answer", posture="open")
        finally:
            self.cleanup()


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--warehouse-id", required=True, help="SQL warehouse to run on (databricks warehouses list)")
    parser.add_argument("--legacy-scope", help="workspace secret scope for the SQL secret() comparison")
    parser.add_argument("--legacy-key", help="key in that scope")
    parser.add_argument("--out", default=str(MEASURE_DIR / "out" / "sql_lane"), help="where results.json goes")
    args = parser.parse_args()
    if bool(args.legacy_scope) != bool(args.legacy_key):
        parser.error("--legacy-scope and --legacy-key go together")
    os.chdir(TF_DIR)
    lane = Lane(args)
    try:
        lane.measure()
    finally:
        (lane.out / "results.json").write_text(json.dumps(results, indent=2))
        log(f"results in {lane.out / 'results.json'}")


if __name__ == "__main__":
    main()
