#!/usr/bin/env python3
"""Crawl GitHub for SUSTech EE-related repositories and refresh sustech_ee_repos.csv.

Strategy:
  - broad queries ("sustech", "SUSTC", "南科大", "topic:sustech") catch anything
    mentioning SUSTech in name/description/README; waterfalls by star count to
    get past the 1000-result API cap, plus a zero-star tail pass.
  - bare course-code queries catch repos that never mention "sustech" anywhere
    (their course code only appears in the name).
  - each repo gets a SUSTech column: "yes" when SUSTech keywords appear in
    name/description/topics (or the broad query matched it), "?" when only the
    course code hints at it (could be another university's same-numbered course).

Uses the authenticated `gh` CLI (30 search requests/min), no token file needed.
Run from the repo root:  python3 crawler/hero.py
"""
import csv
import json
import re
import subprocess
import sys
import time
from urllib.parse import urlencode

CSV_PATH = "sustech_ee_repos.csv"
RAW_PATH = "crawler/sweep_raw.json"

SLEEP = 2.2  # keep below the authenticated search rate limit of 30 req/min

BROAD_QUERIES = [
    "sustech",
    "SUSTC",
    "南科大",
    "topic:sustech",
]

# Bare course codes: catch repos that never mention "sustech" anywhere.
CODES = (
    [f"EE{i}" for i in (102, 104, 105)]
    + [f"EE2{i:02d}" for i in range(1, 20)]  # EE201..EE219
    + [f"EE3{i:02d}" for i in range(1, 71)]  # EE301..EE370
    + [f"EE4{i:02d}" for i in range(1, 51)]  # EE401..EE450
    + ["EE490"]
    + ["EES101", "EES103", "EES203"]
    + ["SME201", "SME206", "SME306"]
    + ["SDM242", "SDM273", "SDM274", "SDM303", "SDM366", "SDM371"]
)

# Repos we know are SUSTech EE course repos even though they lack any
# SUSTech keyword in name/description/topics (verified by hand).
ALLOWLIST = {
    "hwy0507/ee201-17l_analog-circuits-laboratory",
    "hwy0507/ee202-17l_digital-circuits-laboratory",
    "hwy0507/ee206_communication-principles",
    "hwy0507/ee208_engineering-electromagnetics",
    "hwy0507/ee211_robotic-perception-and-intelligence",
    "hwy0507/ee315_data-communications-and-networking",
    "hwy0507/ee318_advanced-electronic-science-experiment-ii",
    "hwy0507/ee323_digital-signal-processing",
    "hwy0507/ee328_speech-signal-processing",
    "hwy0507/ee332_digital-system-design",
    "hwy0507/ee340_statistical-learning-for-data-science",
    "hwy0507/ee351_microprocessors-and-microsystems",
    "hwy0507/ee405_advanced-electronic-science-experiment-iii",
    "squarezhong/sustech-sdm273-assignments",
}

# A course code as a standalone token (EE205, SME206, ...) inside the repo NAME.
CODE_RE = re.compile(r"(?<![a-z0-9])(ee|ees|sme|sdm)[0-9]{3}(?![0-9])", re.I)
SUSTECH_KEYWORDS = ("sustech", "sustc", "南科大")

# Clearly unrelated repos that merely mention SUSTech in passing
# (political spam, other universities' course indexes, generic mega-repos).
DENYLIST = {
    "fighting41love/funnlp", "dujltqzv/some-many-books", "liyupi/ai-guide",
    "cirosantilli/x86-bare-metal-examples", "cirosantilli/china-dictatorship",
    "cirosantilli/china-dictatroship-7", "cirosantilli/cirosantilli",
    "mrfwq7lwnpzjavv5v6eo/cihna-dictattorshrip-8", "pxvr-official/1",
    "gege-circle/.github", "panbinibn/openpacketfix_", "zpc1314521/pcl2",
    "doublechaintech/his-biz-suite", "zhjcreator/fetch_lecture",
    "cgandgameenginelearner/hongjun", "shevonkuan/scut-thesis",
    "alexbybye/scut_cs", "suikaxhq/seu-bachelor-thesis-2022",
    "kylechandev/nuist-ke-cheng-she-ji", "feijianghan/csu-cs-review-materials",
    "njuptfreeexams/njupt-cst-free-exams", "njuhan/njuthesis-nju-thesis-template",
    "superkenvery/nju-judge-teaching", "ncuscc/cs4ncu",
    "jackeylea/njucs", "njuis-students/njuis-students.github.io",
    "njuis-students/resources", "crys-chen/ic-guide",
}


def gh_search(q, page=1, per_page=100):
    """One search API call via `gh`. Returns parsed JSON, or None after retries."""
    params = {"q": q, "per_page": per_page, "page": page,
              "sort": "stars", "order": "desc"}
    cmd = ["gh", "api", "search/repositories?" + urlencode(params)]
    for attempt in range(6):
        p = subprocess.run(cmd, capture_output=True, text=True)
        if p.returncode == 0:
            time.sleep(SLEEP)
            return json.loads(p.stdout)
        msg = (p.stderr or p.stdout or "").strip()
        wait = 65 if ("rate" in msg.lower() or "abuse" in msg.lower()) else 10 * (attempt + 1)
        print(f"  !! request failed ({msg[:120]}), retrying in {wait}s", flush=True)
        time.sleep(wait)
    print(f"  !! giving up on q={q!r} page={page}", flush=True)
    return None


def _collect(query):
    """Fetch every page of one query (up to the 1000-result API cap)."""
    batch, total = {}, None
    for page in range(1, 11):
        data = gh_search(query, page)
        if data is None or not data.get("items"):
            break
        total = data.get("total_count", 0)
        for it in data["items"]:
            batch[it["full_name"]] = it
        if len(batch) >= min(total, 1000):
            break
    return batch, total


def sweep_broad(q):
    """Fetch everything matching q, descending by stars, past the 1000-result cap."""
    repos, threshold = {}, None
    for _ in range(12):
        query = q if threshold is None else f"{q} stars:<{threshold}"
        batch, total = _collect(query)
        repos.update(batch)
        capped = total is not None and total > 1000 and len(batch) >= 1000
        print(f"    q={query!r}: +{len(batch)}  (total {len(repos)})", flush=True)
        if not batch or total is None or total <= 1000 or not capped:
            break
        new_threshold = min(it["stargazers_count"] for it in batch.values())
        if new_threshold <= 0 or (threshold is not None and new_threshold >= threshold):
            break
        threshold = new_threshold
    # Zero-star tail: the bands above only page through the starred repos.
    if capped := (threshold is not None and threshold > 0):
        batch, _ = _collect(f"{q} stars:0")
        repos.update(batch)
        print(f"    q={q!r} stars:0 (tail): +{len(batch)}  (total {len(repos)})", flush=True)
    return repos


def sweep_codes():
    """Search each course code; keep repos whose NAME contains that code."""
    repos = {}
    for code in CODES:
        data = gh_search(code)
        if data is None:
            continue
        kept = 0
        for it in data.get("items", []):
            name = it["name"]
            if CODE_RE.search(name) and code.lower() in name.lower():
                repos.setdefault(it["full_name"], it)
                kept += 1
        print(f"    {code}: +{kept} kept  (total {len(repos)})", flush=True)
    return repos


def keyword_in_fields(it):
    text = f"{it.get('name', '')} {it.get('description') or ''} {' '.join(it.get('topics') or [])}"
    return any(k in text.lower() for k in SUSTECH_KEYWORDS)


def norm_url(url):
    url = (url or "").strip().rstrip("/").lower()
    return url[:-4] if url.endswith(".git") else url


def main():
    existing = {}
    try:
        with open(CSV_PATH, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                existing[norm_url(row["Clone URL"])] = row
    except FileNotFoundError:
        pass
    print(f"Loaded {len(existing)} existing rows from {CSV_PATH}")

    if "--from-raw" in sys.argv:
        # Skip crawling: rebuild the CSV from a previous sweep (applying any
        # filter/denylist changes made since). Stored sustech flags are kept.
        with open(RAW_PATH, encoding="utf-8") as f:
            all_repos = {it["full_name"]: it for it in json.load(f)}
        broad_set = set()
    else:
        broad_all = {}
        for q in BROAD_QUERIES:
            print(f"[broad] {q}")
            for name, it in sweep_broad(q).items():
                broad_all.setdefault(name, it)
        broad_set = set(broad_all)

        print("[codes]")
        code_all = sweep_codes()

        # Broad results are kept only when SUSTech shows up in the fields we
        # can see (the query may have matched only a stray README mention).
        all_repos = {}
        for name, it in broad_all.items():
            if keyword_in_fields(it) or CODE_RE.search(it["name"]):
                all_repos[name] = it
        for name, it in code_all.items():
            all_repos.setdefault(name, it)
        print(f"Kept {len(all_repos)} of {len(broad_all) + len(code_all)} sweep results")

    # Merge with existing rows (carry over repos the sweep missed or that vanished).
    merged = {}
    for full_name, it in all_repos.items():
        if full_name.lower() in DENYLIST:
            continue
        if full_name.lower() in ALLOWLIST:
            it["sustech"] = "yes"  # hand-verified, override any stored flag
        it.setdefault("sustech",
                      "yes" if (keyword_in_fields(it) or full_name in broad_set) else "?")
        merged[norm_url(it["clone_url"])] = it
    for url, row in existing.items():
        if (row.get("Name") or "").lower() in DENYLIST:
            continue
        merged.setdefault(url, {
            "full_name": row["Name"], "clone_url": row["Clone URL"],
            "stargazers_count": int(row.get("Stars") or 0),
            "description": "", "topics": [], "sustech": "yes",
        })

    ordered = sorted(merged.values(), key=lambda it: -int(it.get("stargazers_count") or 0))
    with open(CSV_PATH, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["ID", "Name", "Clone URL", "Stars", "Description", "Topics", "SUSTech"])
        for i, it in enumerate(ordered, 1):
            desc = (it.get("description") or "").replace("\n", " ").strip()
            topics = ";".join(it.get("topics") or [])
            w.writerow([i, it.get("full_name"), it.get("clone_url"),
                        int(it.get("stargazers_count") or 0), desc, topics, it["sustech"]])

    with open(RAW_PATH, "w", encoding="utf-8") as f:
        json.dump(ordered, f, ensure_ascii=False, indent=1)

    verified = sum(1 for it in ordered if it["sustech"] == "yes")
    print(f"\nDone: {len(ordered)} repos in CSV (was {len(existing)}), "
          f"{verified} verified as SUSTech, raw data in {RAW_PATH}")


if __name__ == "__main__":
    main()
