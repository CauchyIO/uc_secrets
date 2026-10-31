"""Offline regressions for the Beta bridge; no real CLI, cloud API or Terraform state."""
import argparse
import contextlib
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location(
    "bridge", Path(__file__).resolve().parents[1] / "modules/uc_schema_secret_storage/uc_secret_storage.py")
bridge = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(bridge)


class BridgeTests(unittest.TestCase):
    def command(self, function, query, side_effect):
        stdout, stderr = io.StringIO(), io.StringIO()
        with patch.object(bridge.sys, "stdin", io.StringIO(json.dumps(query))), \
             contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr), \
             patch.object(bridge, "run_databricks_api", side_effect=side_effect) as api:
            function()
        return stdout.getvalue(), stderr.getvalue(), api

    def test_missing_schema_is_empty_binding(self):
        for error in [bridge.ApiError("get", status=404),
                      bridge.ApiError("get", code="RESOURCE_DOES_NOT_EXIST"),
                      bridge.ApiError("get", code="NOT_FOUND")]:
            with self.subTest(error=error):
                out, _, _ = self.command(bridge.cmd_read_binding, {"schema": "catalog.schema"}, [error])
                self.assertEqual(json.loads(out), {"storage_type": "", "connection_name": ""})

    def test_read_binding_fails_on_auth_or_server_error(self):
        for status in [401, 403, 500]:
            with self.subTest(status=status), self.assertRaises(bridge.ApiError):
                self.command(bridge.cmd_read_binding, {"schema": "catalog.schema"}, [bridge.ApiError("get", status=status)])

    def test_existing_binding(self):
        out, _, _ = self.command(bridge.cmd_read_binding, {"schema": "cat.schema"},
                                [{"secret_storage": {"storage_type": "STORAGE_TYPE_EXTERNAL", "connection_name": "vault"}}])
        self.assertEqual(json.loads(out)["connection_name"], "vault")

    def test_unbind_missing_catalog_or_schema_is_idempotent(self):
        args = argparse.Namespace(schema="cat.schema", profile=None)
        for error in [bridge.ApiError("patch", status=404), bridge.ApiError("patch", code="NOT_FOUND"),
                      bridge.ApiError("patch", code="RESOURCE_DOES_NOT_EXIST")]:
            with patch.object(bridge, "run_databricks_api", side_effect=error):
                bridge.cmd_unbind(args)
        with patch.object(bridge, "run_databricks_api", side_effect=bridge.ApiError("patch", status=403)), self.assertRaises(bridge.ApiError):
            bridge.cmd_unbind(args)

    def test_optional_profile_and_quoted_profile_remain_argv(self):
        for profile in [None, "", " ", "team's profile; $(touch /tmp/should-not-exist)"]:
            with self.subTest(profile=profile), patch.object(bridge.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, "{}", "")) as run:
                bridge.run_databricks_api("get", "/metadata", profile)
                cmd = run.call_args.args[0]
                if profile and profile.strip():
                    self.assertEqual(cmd[-2:], ["-p", profile])
                else:
                    self.assertNotIn("-p", cmd)
                self.assertEqual(run.call_args.kwargs["timeout"], 45)
                self.assertNotIn("shell", run.call_args.kwargs)

    def test_errors_never_echo_response_or_values(self):
        raw = '{"error_code":"PERMISSION_DENIED","message":"SECRET_SENTINEL","status_code":403}'
        with patch.object(bridge.subprocess, "run", return_value=subprocess.CompletedProcess([], 1, raw, "")):
            with self.assertRaises(bridge.ApiError) as caught:
                bridge.run_databricks_api("get", "/metadata")
        self.assertNotIn("SECRET_SENTINEL", str(caught.exception))
        self.assertEqual(caught.exception.status, 403)
        self.assertEqual(caught.exception.code, "PERMISSION_DENIED")

    def test_http_and_cli_missing_error_formats(self):
        for raw in ['HTTP 404', 'HTTP/1.1 404 Not Found', 'Error: RESOURCE_DOES_NOT_EXIST: schema missing',
                    'Error: NOT_FOUND: catalog missing', '404 Client Error: Not Found', "Error: Schema 'catalog.missing' does not exist.",
                    "Error: Catalog 'missing' does not exist.", "Error: SCHEMA_NOT_FOUND"]:
            status, code = bridge.error_details(raw)
            self.assertTrue(bridge.ApiError("get", status=status, code=code).missing, raw)
        self.assertEqual(bridge.error_details("Error: Profile 'missing' does not exist."), (None, None))
        self.assertFalse(bridge.ApiError("get", **dict(zip(["status", "code"], bridge.error_details("UNAUTHENTICATED: not found in config")))).missing)

    def test_timeout_is_sanitized(self):
        with patch.object(bridge.subprocess, "run", side_effect=subprocess.TimeoutExpired("SECRET_SENTINEL", 45)), self.assertRaises(RuntimeError) as caught:
            bridge.run_databricks_api("get", "/metadata")
        self.assertIn("timed out", str(caught.exception))
        self.assertNotIn("SECRET_SENTINEL", str(caught.exception))

    def test_invalid_cli_json_is_sanitized(self):
        for raw in ["SECRET_SENTINEL", "[]"]:
            with patch.object(bridge.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, raw, "")), self.assertRaises(RuntimeError) as caught:
                bridge.run_databricks_api("get", "/metadata")
            self.assertNotIn("SECRET_SENTINEL", str(caught.exception))

    def test_paths_and_queries_are_encoded(self):
        meta = {"full_name": "cat.schema.key", "securable_kind": "SECRET", "external_secret_id": "metadata-id"}
        out, _, api = self.command(bridge.cmd_read_secret, {"catalog": "cat &/", "schema": "sc?=", "secret": "key/#"}, [{}, meta])
        self.assertIn("catalog_name=cat%20%26%2F&schema_name=sc%3F%3D", api.call_args_list[0].args[1])
        self.assertTrue(api.call_args_list[1].args[1].endswith("cat%20%26%2F.sc%3F%3D.key%2F%23"))
        self.assertEqual(bridge.schema_path("a/b.c?d"), bridge.API_ROOT + "/schemas/a%2Fb.c%3Fd")
        self.assertEqual(json.loads(out), meta)

    def test_secret_discovery_retries_rbac_and_lazy_import(self):
        meta = {"full_name": "cat.schema.key", "securable_kind": "SECRET", "external_secret_id": "id", "value": "SECRET_SENTINEL"}
        with patch.object(bridge.time, "sleep") as sleep:
            out, stderr, api = self.command(bridge.cmd_read_secret, {"catalog": "cat", "schema": "schema", "secret": "key"},
                                          [bridge.ApiError("get", status=403), {}, bridge.ApiError("get", status=404), {}, meta])
        self.assertEqual(api.call_count, 5)
        self.assertEqual([c.args[0] for c in sleep.call_args_list], [1, 2])
        self.assertNotIn("SECRET_SENTINEL", out + stderr)
        self.assertNotIn("value", json.loads(out))

    def test_retry_budget_is_bounded(self):
        with patch.object(bridge.time, "sleep") as sleep, self.assertRaises(bridge.ApiError):
            self.command(bridge.cmd_read_secret, {"catalog": "cat", "schema": "schema", "secret": "key"},
                         [bridge.ApiError("get", status=404)] * 5)
        self.assertEqual([c.args[0] for c in sleep.call_args_list], [1, 2, 4, 8])

    def test_secret_auth_failure_is_not_retried(self):
        with patch.object(bridge.time, "sleep") as sleep, self.assertRaises(bridge.ApiError):
            self.command(bridge.cmd_read_secret, {"catalog": "cat", "schema": "schema", "secret": "key"},
                         [bridge.ApiError("get", status=401)])
        sleep.assert_not_called()

    def test_metadata_missing_fields_is_retried(self):
        meta = {"full_name": "cat.schema.key", "securable_kind": "SECRET", "external_secret_id": "id"}
        with patch.object(bridge.time, "sleep") as sleep:
            out, _, _ = self.command(bridge.cmd_read_secret, {"catalog": "cat", "schema": "schema", "secret": "key"}, [{}, {}, {}, meta])
        sleep.assert_called_once_with(1)
        self.assertEqual(json.loads(out), meta)

    def test_environment_inputs_bind_without_shell_parsing(self):
        env = {"UC_STORAGE_SCHEMA": "cat.schema", "UC_STORAGE_CONNECTION": "vault", "UC_STORAGE_PROFILE": "name' with quotes"}
        with patch.dict(bridge.os.environ, env), patch.object(bridge.sys, "argv", ["bridge", "bind"]), patch.object(bridge, "run_databricks_api") as api:
            self.assertEqual(bridge.main(), 0)
        self.assertEqual(api.call_args.kwargs["profile"], env["UC_STORAGE_PROFILE"])
        self.assertEqual(api.call_args.kwargs["payload"]["secret_storage"]["connection_name"], "vault")


if __name__ == "__main__":
    unittest.main()
