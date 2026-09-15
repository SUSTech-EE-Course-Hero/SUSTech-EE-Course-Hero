#!/usr/bin/env python3
"""Compare the sweep results (crawler/sweep_raw.json) against readme.md.

Lists repos that are NOT yet linked in the README, grouped by course code,
so a human can pick which ones to add. Run from the repo root:

    python3 crawler/curate.py [--min-stars N] [--all-courses]
"""
import json
import re
import sys

RAW_PATH = "crawler/sweep_raw.json"
README_PATH = "readme.md"

CODE_RE = re.compile(r"(?<![a-z0-9])(ee|ees|sme|sdm)[0-9]{3}(?![0-9])", re.I)
GH_URL_RE = re.compile(r"github\.com/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+?)(?=[/\"'?#<>\s)]|$)", re.I)


def main():
    args = sys.argv[1:]
    min_stars = 1
    if "--min-stars" in args:
        min_stars = int(args[args.index("--min-stars") + 1])
    all_courses = "--all-courses" in args

    with open(RAW_PATH, encoding="utf-8") as f:
        repos = json.load(f)
    with open(README_PATH, encoding="utf-8") as f:
        readme = f.read()

    # Only verified-SUSTech repos unless --include-unverified is passed.
    if "--include-unverified" not in args:
        repos = [r for r in repos if r.get("sustech") == "yes"]

    linked = {f"{m.group(1).lower()}/{m.group(2).rstrip('.').lower()}"
              for m in GH_URL_RE.finditer(readme)}

    new = [r for r in repos if r["full_name"].lower() not in linked]
    print(f"total repos: {len(repos)}, already in README: {len(repos) - len(new)}, new: {len(new)}\n")

    groups = {}
    for r in new:
        code = None
        m = CODE_RE.search(r.get("name") or r.get("full_name", ""))
        if m:
            code = m.group(0).upper()
        groups.setdefault(code or "(no code in name)", []).append(r)

    for code in sorted(groups):
        rows = [r for r in groups[code] if int(r.get("stargazers_count") or 0) >= min_stars]
        if not rows:
            continue
        if code == "(no code in name)" and not all_courses:
            continue
        print(f"== {code} ({len(rows)} repos with >= {min_stars} star) ==")
        for r in sorted(rows, key=lambda x: -int(x.get("stargazers_count") or 0)):
            desc = (r.get("description") or "").replace("\n", " ")
            desc = desc if len(desc) <= 90 else desc[:87] + "..."
            print(f"  {int(r.get('stargazers_count') or 0):>4}*  {r['full_name']}  [{desc}]")
        print()


if __name__ == "__main__":
    main()
