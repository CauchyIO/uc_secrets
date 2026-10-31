#!/usr/bin/env python3
"""Scan public files for identifiers and common credentials; report locations, never values.

Includes git ls-files plus untracked, nonignored additions. This is a release
check for the working tree, not a substitute for reviewing Git history or prose.
"""
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ZERO_GUID = "00000000-0000-0000-0000-000000000000"
PATTERNS = {
    "recorded secret fingerprint": re.compile(r"(?<![\w-])[0-9a-f]{12}(?![\w-])"),
    "cluster identifier": re.compile(r"\b[0-9]{4}-[0-9]{6}-[a-z0-9]+\b"),
    "non-placeholder GUID": re.compile(r"\b[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}\b"),
    "opaque numeric identifier": re.compile(r"(?<![\w.])[0-9]{12,}(?![\w.])"),
    "workspace hostname": re.compile(r"\badb-[0-9]+\.[0-9]+\.azuredatabricks\.net\b"),
    "email": re.compile(r"\b[\w.+-]+@[\w-]+(?:\.[\w-]+)+\b"),
    "private hostname": re.compile(r"\b(?:[\w-]+\.)+(?:internal|local|corp)\b", re.I),
    "credential-like token": re.compile(r"\b(?:dapi[a-f0-9]{20,}|sk-[A-Za-z0-9_-]{20,}|eyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+)\b"),
}


def findings(path, text):
    for number, line in enumerate(text.splitlines(), 1):
        for kind, pattern in PATTERNS.items():
            for match in pattern.finditer(line):
                value = match.group()
                if value == ZERO_GUID:
                    continue
                if kind in {"opaque numeric identifier", "recorded secret fingerprint"} and (set(value) == {"0"} or re.fullmatch(r"10+", value)):
                    continue  # placeholder IDs and timestamp-unit conversion constants
                if kind == "email" and (value.endswith(("@example.com", "@example.invalid", "@example.dfs.core.windows.net"))):
                    continue
                yield f"{path}:{number}: {kind}"


def main():
    raw = subprocess.check_output(["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"], cwd=ROOT)
    paths = sorted(set(filter(None, raw.decode().split("\0"))))
    hits = []
    for name in paths:
        path = ROOT / name
        if path.is_file():
            try:
                text = path.read_text()
            except UnicodeDecodeError:
                hits.append(f"{name}: binary file requires manual review")
                continue
            hits.extend(findings(name, text))
    for hit in hits:
        print(hit)
    print(f"Public-file audit: {len(paths)} files, {len(hits)} findings (matched values suppressed).")
    return bool(hits)


if __name__ == "__main__":
    sys.exit(main())
