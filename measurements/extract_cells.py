#!/usr/bin/env python3
"""Print each cell's markdown heading and text output from a `databricks jobs export-run` JSON (CODE view)."""
import base64
import html
import json
import re
import sys
import urllib.parse

d = json.load(open(sys.argv[1]))
content = d["views"][0]["content"]
m = re.search(r"__DATABRICKS_NOTEBOOK_MODEL = '([^']+)'", content)
raw = base64.b64decode(m.group(1))
try:
    model = json.loads(raw)
except json.JSONDecodeError:
    model = json.loads(urllib.parse.unquote(raw.decode("utf-8")))
for cmd in model["commands"]:
    src = cmd.get("command") or ""
    if src.startswith("%md"):
        heading = next((ln.strip("# ").strip() for ln in src.splitlines() if ln.startswith("#")), None)
        if heading:
            print(f"\n**{heading}**\n")
        continue
    res = cmd.get("results") or {}
    data = res.get("data")
    text = ""
    if res.get("type") == "html" and isinstance(data, str):
        text = html.unescape(re.sub(r"<[^>]+>", "", data))
    elif isinstance(data, str):
        text = data
    elif isinstance(data, list):
        # ansi results are a list of {"type": "ansi", "data": "<stdout>"} chunks; keep only their text
        text = "".join(x.get("data", "") if isinstance(x, dict) else str(x) for x in data)
    text = text.strip()
    if text:
        print("```text\n" + text + "\n```")
