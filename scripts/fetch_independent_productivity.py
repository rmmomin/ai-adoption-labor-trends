#!/usr/bin/env python3
"""Archive primary BEA, BLS and Census inputs for an independent productivity panel."""
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
RAW = Path(os.environ.get("PRODUCTIVITY_RAW_DIR", ROOT / "data/independent_productivity")).resolve()
HEADERS = {"User-Agent": "Mozilla/5.0 (reproducible economic research)"}


def fetch(url, path):
    path.parent.mkdir(parents=True, exist_ok=True)
    metadata = path.with_name(path.name + ".source.json")
    if path.exists() and metadata.exists():
        return json.loads(metadata.read_text())
    for attempt in range(4):
        try:
            req = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=60) as response:
                blob = response.read()
                headers = dict(response.headers)
            break
        except Exception:
            if attempt == 3:
                raise
            time.sleep(1 + attempt)
    temp = path.with_name(path.name + ".partial")
    temp.write_bytes(blob)
    temp.replace(path)
    record = {"url": url, "file": str(path.relative_to(RAW)), "bytes": len(blob),
              "sha256": hashlib.sha256(blob).hexdigest(),
              "retrieved_at_utc": datetime.now(timezone.utc).isoformat(),
              "last_modified": headers.get("Last-Modified", headers.get("last-modified"))}
    metadata.write_text(json.dumps(record, indent=2))
    return record


def hrefs(blob):
    return ["https:" + u if u.startswith("//") else u
            for u in re.findall(r'href="([^"]+)"', blob, flags=re.I)]


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--start-year", type=int, default=2006)
    p.add_argument("--end-year", type=int, default=2026)
    p.add_argument("--workers", type=int, default=4)
    args = p.parse_args()
    RAW.mkdir(parents=True, exist_ok=True)
    jobs = {}
    # BLS's downloadt host serves the same public bulk-file schema and is
    # accessible where the download host rejects programmatic requests.
    # Source modification times are retained, and recent CES is refreshed by API.
    index_url = "https://downloadt.bls.gov/pub/time.series/ce/"
    fetch(index_url, RAW / "ces_index_current.html")
    index = (RAW / "ces_index_current.html").read_text()
    for u in hrefs(index):
        filename = u.rsplit("/", 1)[-1]
        if filename in ["ce.series", "ce.industry", "ce.datatype"] or re.match(r"ce\.data\.(05|10|20|30|31|32|41|42|43|50|55|60|65|70|80)[ab]\.", filename):
            jobs[RAW / "bls" / filename] = "https://downloadt.bls.gov" + u
    jobs[RAW / "bea" / "ValueAdded.xlsx"] = "https://apps.bea.gov/industry/Release/XLS/GDPxInd/ValueAdded.xlsx"
    for y in range(args.start_year, args.end_year + 1):
        index_path = RAW / f"cps_index_{y}.html"
        # Previously inspected index pages are public discovery documents, not observations.
        if not index_path.exists():
            fetch(f"https://www.census.gov/data/datasets/{y}/demo/cps/cps-basic-{y}.html", index_path)
        for u in hrefs(index_path.read_text()):
            if "www2.census.gov" not in u:
                continue
            filename = u.rsplit("/", 1)[-1]
            if re.fullmatch(r"[a-z]{3}\d{2}pub\.dat\.gz", filename):
                jobs[RAW / "cps" / str(y) / filename] = u
            elif filename.endswith(".txt") and not "revwgts" in filename:
                jobs[RAW / "cps_dict" / filename] = u
        print(f"Discovered Census {y}", flush=True)
    # Industry list is a separate structured file in the newest release.
    jobs[RAW / "cps_dict/cps_industry_codes_2026.csv"] = "https://www2.census.gov/programs-surveys/cps/datasets/2026/basic/cps_industry_codes.csv"
    failures = []
    records = []
    with ThreadPoolExecutor(args.workers) as pool:
        pending = {pool.submit(fetch, u, path): path for path, u in jobs.items()}
        for i, future in enumerate(as_completed(pending), 1):
            path = pending[future]
            try:
                records.append(future.result())
            except Exception as exc:
                failures.append({"file": str(path), "error": str(exc)})
                print(f"Failed {path.name}: {exc}", flush=True)
            if i % 12 == 0 or i == len(jobs):
                print(f"Archived {i}/{len(jobs)} sources; {len(failures)} failures", flush=True)
    (RAW / "manifest.json").write_text(json.dumps(sorted(records, key=lambda r: r["file"]), indent=2))
    (RAW / "fetch_failures.json").write_text(json.dumps(failures, indent=2))
    if failures:
        raise RuntimeError(f"{len(failures)} sources failed; see fetch_failures.json")


if __name__ == "__main__":
    main()
