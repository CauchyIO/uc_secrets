#!/usr/bin/env python3
"""Beta Unity Catalog external Key Vault binding and metadata-only discovery.

read-binding/read-secret implement the Terraform external data-source protocol.
bind/unbind accept CLI flags or UC_STORAGE_* environment inputs. A missing or
empty profile uses Databricks unified authentication from the environment.
No response body, secret value, CLI payload or credential is written to stderr.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from urllib.parse import quote

API_ROOT = "/api/2.1/unity-catalog"
CLI_TIMEOUT_SECONDS = 45
RETRY_DELAYS = (1, 2, 4, 8)
MISSING_CODES = {"RESOURCE_DOES_NOT_EXIST", "NOT_FOUND", "SCHEMA_NOT_FOUND", "CATALOG_NOT_FOUND"}
RETRY_CODES = MISSING_CODES | {"PERMISSION_DENIED", "RESOURCE_EXHAUSTED", "TEMPORARILY_UNAVAILABLE", "INTERNAL_ERROR"}
KNOWN_CODES = RETRY_CODES | {"UNAUTHENTICATED", "INVALID_PARAMETER_VALUE", "BAD_REQUEST"}


class ApiError(RuntimeError):
    """Sanitized failure: never retain or display raw CLI output."""

    def __init__(self, method, *, status=None, code=None, exit_code=None):
        self.status, self.code = status, code
        super().__init__(f"Databricks API {method.upper()} failed "
                         f"(HTTP {status or 'unknown'}, code {code or 'unknown'}, exit {exit_code}). "
                         "Check workspace authentication, privileges and Key Vault connectivity/RBAC.")

    @property
    def missing(self):
        return self.status == 404 or self.code in MISSING_CODES

    @property
    def retryable(self):
        if self.status == 401 or self.code == "UNAUTHENTICATED":
            return False
        return self.missing or self.status in {403, 429, 500, 502, 503, 504} or self.code in RETRY_CODES


def error_details(raw):
    """Recognize CLI JSON and plain-text status codes without echoing their messages."""
    status, code = None, None
    try:
        body = json.loads(raw)
        if isinstance(body, dict):
            candidate = body.get("status_code", body.get("status"))
            if str(candidate).isdigit():
                status = int(candidate)
            candidate = body.get("error_code")
            if candidate in KNOWN_CODES:
                code = candidate
    except (ValueError, TypeError):
        pass
    if code is None:
        code = next((c for c in sorted(KNOWN_CODES) if re.search(rf"\b{c}\b", raw)), None)
    if status is None:
        match = re.search(r"\b(?:HTTP(?:/\d(?:\.\d)?)?\s+|status(?:_code| code)?[\s:=\"]+)([45]\d\d)\b", raw, re.I)
        if match:
            status = int(match[1])
        elif re.search(r"\b404\s+(?:Not Found|Client Error)\b", raw, re.I):
            status = 404
    # CLI v1.1.0 strips status/error_code from these SDK errors. Match only
    # explicit missing UC objects; never classify missing auth/profile files as 404.
    if status is None and code is None and re.search(
        r"(?im)^\s*(?:Error:\s*)?(?:Schema|Catalog|Secret)\s+['\"`][^\r\n]+['\"`]\s+does not exist\b", raw
    ):
        code = "RESOURCE_DOES_NOT_EXIST"
    return status, code


def run_databricks_api(method, path, profile=None, payload=None):
    cmd = ["databricks", "api", method, path]
    if profile and profile.strip():
        cmd.extend(["-p", profile])
    if payload is not None:
        cmd.extend(["--json", json.dumps(payload)])
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, check=False,
                              timeout=CLI_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"Databricks API {method.upper()} timed out after {CLI_TIMEOUT_SECONDS}s.") from None
    except OSError:
        raise RuntimeError("Cannot execute Databricks CLI; check installation and PATH.") from None
    if proc.returncode:
        status, code = error_details(proc.stderr + "\n" + proc.stdout)
        raise ApiError(method, status=status, code=code, exit_code=proc.returncode)
    try:
        result = json.loads(proc.stdout) if proc.stdout.strip() else {}
    except ValueError:
        raise RuntimeError("Databricks CLI returned invalid JSON; response omitted.") from None
    if not isinstance(result, dict):
        raise RuntimeError("Databricks CLI returned an unexpected JSON type; response omitted.")
    return result


def schema_path(schema):
    return f"{API_ROOT}/schemas/{quote(schema, safe='')}"


def cmd_read_binding():
    query = json.load(sys.stdin)
    try:
        resp = run_databricks_api("get", schema_path(query["schema"]) + "?include_secret_storage=true",
                                  profile=query.get("profile"))
    except ApiError as exc:
        if not exc.missing:
            raise
        resp = {}
    storage = resp.get("secret_storage") or {}
    json.dump({"storage_type": str(storage.get("storage_type") or ""),
               "connection_name": str(storage.get("connection_name") or "")}, sys.stdout)


def cmd_bind(args):
    run_databricks_api("patch", schema_path(args.schema), profile=args.profile,
                      payload={"secret_storage": {"connection_name": args.connection,
                                                  "storage_type": "STORAGE_TYPE_EXTERNAL"}})


def cmd_unbind(args):
    try:
        run_databricks_api("patch", schema_path(args.schema) + "?update_mask=secret_storage",
                          profile=args.profile, payload={"secret_storage": {}})
    except ApiError as exc:
        if not exc.missing:
            raise


def cmd_read_secret():
    query = json.load(sys.stdin)
    catalog, schema, secret = (query[k] for k in ("catalog", "schema", "secret"))
    list_path = f"{API_ROOT}/secrets?catalog_name={quote(catalog, safe='')}&schema_name={quote(schema, safe='')}"
    get_path = f"{API_ROOT}/secrets/{quote(f'{catalog}.{schema}.{secret}', safe='')}"
    fields = ("full_name", "securable_kind", "external_secret_id")
    for attempt in range(len(RETRY_DELAYS) + 1):
        try:
            # Listing triggers UC lazy import. Neither endpoint requests secret values.
            run_databricks_api("get", list_path, profile=query.get("profile"))
            meta = run_databricks_api("get", get_path, profile=query.get("profile"))
            if any(not isinstance(meta.get(f), str) or not meta[f] for f in fields):
                raise ApiError("get", code="NOT_FOUND")
            json.dump({field: meta[field] for field in fields}, sys.stdout)
            return
        except ApiError as exc:
            if not exc.retryable or attempt == len(RETRY_DELAYS):
                raise
            delay = RETRY_DELAYS[attempt]
            sys.stderr.write(f"Secret metadata not ready (attempt {attempt + 1}/5); retrying in {delay}s.\n")
            time.sleep(delay)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="subcommand", required=True)
    sub.add_parser("read-binding")
    sub.add_parser("read-secret")
    for action in ("bind", "unbind"):
        child = sub.add_parser(action)
        child.add_argument("--profile", default=os.getenv("UC_STORAGE_PROFILE"))
        child.add_argument("--schema", default=os.getenv("UC_STORAGE_SCHEMA"))
        if action == "bind":
            child.add_argument("--connection", default=os.getenv("UC_STORAGE_CONNECTION"))
    args = parser.parse_args()
    if args.subcommand in {"bind", "unbind"} and not args.schema:
        parser.error("provide --schema or UC_STORAGE_SCHEMA")
    if args.subcommand == "bind" and not args.connection:
        parser.error("provide --connection or UC_STORAGE_CONNECTION")
    try:
        if args.subcommand == "read-binding":
            cmd_read_binding()
        elif args.subcommand == "read-secret":
            cmd_read_secret()
        elif args.subcommand == "bind":
            cmd_bind(args)
        else:
            cmd_unbind(args)
    except (ApiError, RuntimeError) as exc:
        sys.stderr.write(f"{exc}\n")
        return 1
    except (KeyError, TypeError, ValueError):
        sys.stderr.write("Invalid bridge input or response structure; payload omitted.\n")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
