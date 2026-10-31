"""Read-only unit tests and stubbed shell integration tests; never use live CLIs."""
import argparse
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("approval", ROOT / "scripts/ncc_private_endpoint.py")
approval = importlib.util.module_from_spec(spec)
spec.loader.exec_module(approval)


class ApprovalTests(unittest.TestCase):
    args = argparse.Namespace(vault_id="/subscriptions/test/resourceGroups/test/providers/Microsoft.KeyVault/vaults/test", endpoint_name="endpoint")

    def connection(self, status):
        return {"id": self.args.vault_id + "/privateEndpointConnections/generated-child", "name": "generated-child",
                "private_endpoint": "endpoint", "status": status}

    def test_approved_endpoint_is_never_written(self):
        with patch.object(approval, "connections", return_value=[self.connection("Approved")]), patch.object(approval, "az") as az, contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(approval.cmd_approve(self.args), 0)
        az.assert_not_called()

    def test_pending_endpoint_retries_discovery_and_matches_exact_child(self):
        conn = self.connection("Pending")
        with patch.object(approval, "connections", side_effect=[[], [conn]]), \
             patch.object(approval.time, "sleep") as sleep, \
             patch.object(approval, "az", return_value={"privateLinkServiceConnectionState": {"status": "Approved"}}) as az, \
             contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(approval.cmd_approve(self.args), 0)
        sleep.assert_called_once_with(5)
        self.assertIn(conn["id"], az.call_args.args)

    def test_ambiguous_or_rejected_connections_never_write(self):
        for rows in [[self.connection("Pending")] * 2, [self.connection("Rejected")], [self.connection("Disconnected")]]:
            with patch.object(approval, "connections", return_value=rows), patch.object(approval, "az") as az, self.assertRaises(SystemExit):
                approval.cmd_approve(self.args)
            az.assert_not_called()

    def test_approval_discovery_is_bounded(self):
        with patch.object(approval, "connections", return_value=[]) as discover, patch.object(approval.time, "sleep") as sleep, \
             contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            approval.cmd_approve(self.args)
        self.assertEqual(discover.call_count, 6)
        self.assertEqual(sleep.call_count, 5)


class SmokeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.dir = Path(self.temp.name)
        self.env = os.environ.copy()
        self.env.pop("DATABRICKS_PROFILE", None)
        self.env.update(PATH=str(self.dir) + os.pathsep + self.env["PATH"], FAKE_DIR=str(self.dir), FAKE_PROFILE="")
        self.stub("terraform", '''
import json, os, sys
values = {"databricks_profile":os.environ["FAKE_PROFILE"], "model_provider_service":"cat.schema.service", "unity_catalog_secret_for_lane":"cat.schema.lane", "key_vault_name":"test-vault", "workspace_host":"https://example.invalid", "apim_named_value_list_url":"https://example.invalid/listValue"}
if "-json" in sys.argv:
    print(json.dumps({k:{"value":v} for k,v in values.items()}))
else:
    print(values[sys.argv[-1]])
''')
        self.stub("databricks", '''
import json, os, sys
from pathlib import Path
with (Path(os.environ["FAKE_DIR"])/"db.jsonl").open("a") as f: f.write(json.dumps(sys.argv[1:])+"\\n")
if "token" in sys.argv: print(json.dumps({"access_token":"FAKE_ACCESS_TOKEN"}))
elif "include_value=true" in " ".join(sys.argv): print(json.dumps({"effective_value":"SECRET_TEST_VALUE"}))
else: print(json.dumps({"full_name":"cat.schema.lane"}))
''')
        self.stub("curl", '''
import json,os,sys
from pathlib import Path
(Path(os.environ["FAKE_DIR"])/"curl.json").write_text(json.dumps(sys.argv[1:]))
print("{}")
''')
        self.stub("az", '''
import json,os,sys
from pathlib import Path
with (Path(os.environ["FAKE_DIR"])/"az.jsonl").open("a") as f: f.write(json.dumps(sys.argv[1:])+"\\n")
if "rest" in sys.argv: sys.exit(1)
print("{}")
''')

    def stub(self, name, source):
        path = self.dir/name
        path.write_text("#!/usr/bin/env python3\n"+source)
        path.chmod(0o700)

    def smoke(self, *args):
        return subprocess.run(["bash", str(ROOT/"scripts/smoke_test.sh"), *args], env=self.env,
                              capture_output=True, text=True, timeout=20)

    def test_environment_auth_omits_profile_and_masks_secret(self):
        result = self.smoke("secret")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("SECRET_TEST_VALUE", result.stdout+result.stderr)
        for line in (self.dir/"db.jsonl").read_text().splitlines():
            self.assertNotIn("-p", json.loads(line))

    def test_profile_quotes_are_passed_literally(self):
        profile = "profile'; $(touch " + str(self.dir/"injected") + ")"
        self.env["FAKE_PROFILE"] = profile
        result = self.smoke("secret")
        self.assertEqual(result.returncode, 0, result.stderr)
        for line in (self.dir/"db.jsonl").read_text().splitlines():
            self.assertEqual(json.loads(line)[-2:], ["-p", profile])
        self.assertFalse((self.dir/"injected").exists())

    def test_gateway_payload_encodes_model_and_hides_token_from_argv(self):
        model = 'model" with \\ escapes'
        result = self.smoke("query", model)
        self.assertEqual(result.returncode, 0, result.stderr)
        args = json.loads((self.dir/"curl.json").read_text())
        self.assertEqual(json.loads(args[args.index("-d")+1])["model"], model)
        self.assertNotIn("FAKE_ACCESS_TOKEN", " ".join(args)+result.stdout+result.stderr)

    def test_locked_vault_preflight_never_mutates_on_exit(self):
        self.stub("terraform", '''
import json
resources = {
    "azurerm_key_vault.demo": {"id":"/subscriptions/test/vault", "tenant_id":"test", "name":"test-vault", "resource_group_name":"test-rg"},
    "azurerm_key_vault_secret.dummy[0]": {"name":"dummy"},
    "azurerm_key_vault_secret.lane": {"name":"lane"},
    "databricks_credential.key_vault": {"name":"credential"},
    "databricks_catalog.demo": {"name":"cat"},
    "databricks_schema.secrets": {"id":"cat.schema"},
}
print(json.dumps({"values":{"root_module":{"resources":[{"address":k,"values":v} for k,v in resources.items()]}, "outputs":{"model_provider_service":{"value":"cat.schema.service"}}}}))
''')
        self.stub("databricks", '''
import json,sys
print(json.dumps({"userName":"test-user"} if "current-user" in sys.argv else {"config":{"targets":[{"model":"test-model"}]}}))
''')
        self.stub("az", '''
import json,os,sys
from pathlib import Path
with (Path(os.environ["FAKE_DIR"])/"az.jsonl").open("a") as f: f.write(json.dumps(sys.argv[1:])+"\\n")
print(json.dumps({"public":"Disabled","deny":"Deny","bypass":"AzureServices"}))
''')
        result = subprocess.run(["bash", str(ROOT/"measurements/sealed_with_ncc.sh"), "test", str(self.dir/"out")],
                                env=self.env, capture_output=True, text=True, timeout=20)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("refusing to start", result.stdout)
        calls = [json.loads(line) for line in (self.dir/"az.jsonl").read_text().splitlines()]
        self.assertTrue(calls)
        self.assertTrue(all(call[:2] == ["keyvault", "show"] for call in calls))

    def test_reseed_read_failure_never_overwrites_secret(self):
        result = self.smoke("reseed")
        self.assertNotEqual(result.returncode, 0)
        calls = [json.loads(s) for s in (self.dir/"az.jsonl").read_text().splitlines()]
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][0], "rest")


if __name__ == "__main__":
    unittest.main()
