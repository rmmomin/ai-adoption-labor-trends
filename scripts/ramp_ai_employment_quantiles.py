#!/usr/bin/env python3
"""Build fixed Ramp AI-adoption quartiles and quintiles using archived BLS CES data.

The public full-sector Ramp chart is downloaded on a normal run. --offline reuses
the archived CSV. BLS data are the exact saved vintage used for the BTOS charts.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import requests

from btos_ai_employment_quintiles import BASE, ROOT, SECTORS, employment, plot_index
from reproduce_ces_monthly_employment_index import INDUSTRY_TO_CES, RAMP_SECTOR_MAP

RAMP_URL = "https://ramp.com/data/ai-index"
CHART_URL = "https://datawrapper.dwcdn.net/wQR5S/"
RAW = ROOT / "data/ramp_ai"


def download(raw):
    raw.mkdir(parents=True, exist_ok=True)
    response = requests.get(CHART_URL, timeout=45)
    response.raise_for_status()
    match = re.search(r"https://datawrapper\.dwcdn\.net/wQR5S/\d+/", response.text)
    if match is None:
        raise ValueError("Ramp chart version was not found; inspect the published chart.")
    version_url = match.group()
    chart = requests.get(version_url, timeout=45)
    chart.raise_for_status()
    if RAMP_URL not in chart.text or "naics_sector_" not in chart.text:
        raise ValueError("Unexpected chart source or sector schema.")
    dataset_url = version_url + "dataset.csv"
    response = requests.get(dataset_url, timeout=45)
    response.raise_for_status()
    csv_path = raw / "chart_dataset.csv"
    csv_path.write_bytes(response.content)
    (raw / "datawrapper.html").write_text(chart.text)
    (raw / "download_metadata.json").write_text(json.dumps({
        "ramp_url": RAMP_URL, "chart_url": version_url, "dataset_url": dataset_url,
        "retrieved_at_utc": datetime.now(timezone.utc).isoformat(),
        "sha256": hashlib.sha256(response.content).hexdigest(),
    }, indent=2))
    return csv_path


def read_adoption(csv_path, month):
    data = pd.read_csv(csv_path)
    data["Date"] = pd.to_datetime(data["Date"])
    assert not data.Date.duplicated().any()
    selected = pd.Timestamp(month) if month else data.Date.max()
    row = data.loc[data.Date.eq(selected)]
    if len(row) != 1:
        raise ValueError(f"Expected one Ramp observation for {selected:%Y-%m}.")
    records = []
    for column in data.columns:
        match = re.fullmatch(r"naics_sector_(.*)_ai_user_share", column)
        if not match:
            continue
        key = match.group(1)
        if key not in RAMP_SECTOR_MAP:
            raise ValueError(f"Unmapped Ramp sector: {key}")
        name = RAMP_SECTOR_MAP[key]
        if name not in INDUSTRY_TO_CES:
            continue  # Agriculture and public administration, as in the BTOS analysis.
        value = row.iloc[0][column]
        # The archived public CSV explicitly reports percentages, not proportions.
        if not isinstance(value, str) or not value.endswith("%"):
            raise ValueError(f"Expected a percentage for {key}, got {value!r}.")
        records.append({"series_id": INDUSTRY_TO_CES[name], "ramp_sector": key,
                        "ai_adoption_pct": float(value[:-1]), "ramp_month": selected.date().isoformat()})
    mapping = pd.DataFrame(SECTORS, columns=["btos_sector", "naics", "industry", "series_id"]).drop(columns="btos_sector")
    members = mapping.merge(pd.DataFrame(records), on="series_id", how="left", validate="one_to_one")
    assert len(members) == 18 and members.ai_adoption_pct.notna().all()
    assert members.ai_adoption_pct.between(0, 100).all()
    members = members.sort_values(["ai_adoption_pct", "naics"]).reset_index(drop=True)
    members["adoption_rank"] = np.arange(1, len(members) + 1)
    return members, selected


def make_report(out, members, monthly, meta, checks):
    name = meta["group_name"]
    month = pd.Timestamp(meta["ramp_month"])
    last_date = monthly.date.max()
    summary = members.groupby(name).agg(
        industries=("industry", "size"), ai_min_pct=("ai_adoption_pct", "min"),
        ai_max_pct=("ai_adoption_pct", "max"))
    first = monthly.loc[monthly.date.eq(BASE)].set_index(name)
    last = monthly.loc[monthly.date.eq(last_date)].set_index(name)
    summary["jan_2023_employment_millions"] = first.employment_thousands / 1000
    summary["latest_employment_millions"] = last.employment_thousands / 1000
    summary["latest_index"] = last.employment_index
    summary["employment_change_pct"] = last.change_since_jan_2023_pct
    summary.to_csv(out / f"{name}_summary.csv", float_format="%.6f")
    lines = [f"# Employment by Ramp AI adoption {name}", "",
             f"Ranking snapshot: {month:%B %Y}. Employment: January 2023–{last_date:%B %Y}. "
             "Seasonally adjusted payroll jobs; January 2023 = 100. Latest employment is preliminary.", "",
             "![Employment index](employment_index.png)", "",
             f"| {name.title()} | Sectors | Ramp AI adoption | Jan 2023 jobs (m) | Latest jobs (m) | Latest index | Change |",
             "|---|---:|---:|---:|---:|---:|---:|"]
    for q, r in summary.iterrows():
        lines.append(f"| Q{q} | {r.industries:.0f} | {r.ai_min_pct:.2f}–{r.ai_max_pct:.2f}% | "
                     f"{r.jan_2023_employment_millions:.3f} | {r.latest_employment_millions:.3f} | "
                     f"{r.latest_index:.2f} | {r.employment_change_pct:+.2f}% |")
    sizes = ", ".join(map(str, meta["group_sizes"]))
    lines += ["", "## Construction", "",
              f"Sort the same 18 broad nonfarm NAICS sectors used in the Census charts by Ramp's {month:%B %Y} AI adoption percentage. "
              f"Divide sector ranks into {meta['groups']} groups using pandas.qcut: {sizes} sectors from lowest to highest adoption. "
              "Ties are ordered by NAICS code. Group sizes refer to numbers of industries, not shares of jobs.", "",
              "Keep group membership fixed for the full history. For each month, sum the constituent sectors' "
              "BLS CES seasonally adjusted all-employees series, divide by the January 2023 group total, and multiply by 100. "
              "This weights industry growth by January 2023 employment. The exact BLS response used in the Census charts is reused. "
              "No data are filled or imputed. Government employment and agriculture/forestry/fishing are excluded; "
              "education and healthcare use private employment series.", "",
              "## Ramp data coverage and interpretation", "",
              f"The full-sector public Datawrapper download used here ends in {month:%B %Y}. "
              "When retrieved on September 14, 2026, Ramp's redesigned dashboard had newer August 2026 adoption data for only "
              "seven displayed sectors. We retain all 18 industries using the complete April snapshot rather than combining "
              "different ranking months or reducing the comparison universe. The source CSV includes some sectors hidden in "
              "the published chart; they are available in its downloadable data. Source URLs and hashes are archived.", "",
              "Ramp counts a business as an AI adopter when it observes a positive payment for an AI product or service in a month. "
              "The data reflect businesses using Ramp's payment platform and may omit free AI use or payments made through personal accounts. "
              "Sector assignments use Ramp's internal NAICS classification models. The percentages are not employment shares, "
              "and their population and definition differ from Census BTOS survey estimates. Standard errors are not supplied in this CSV.", "",
              "These are retrospective groupings based on recent adoption, not estimates of AI's causal impact on employment. "
              "The employment panel covers each whole private sector, not just the firms in Ramp's sample. "
              "Changing the adoption measure changes which industries enter each group and can change their employment paths.", "",
              f"Validation: all {checks['industries']} sectors have complete data for {checks['months']} consecutive months; "
              "all base indexes equal 100; group totals reconcile with the constituent CES series. "
              f"The largest difference between summed sectors plus logging and published total private employment is "
              f"{checks['max_sector_plus_logging_reconciliation_difference_thousands']:.1f} thousand jobs.", "",
              "## Industry membership", "", f"| {name.title()} | NAICS | Industry | Ramp AI adoption |", "|---|---|---|---:|"]
    for r in members.itertuples():
        lines.append(f"| Q{getattr(r, name)} | {r.naics} | {r.industry} | {r.ai_adoption_pct:.2f}% |")
    lines += ["", "## Sources and reproduction", "",
              f"- [Ramp AI Index and methodology]({RAMP_URL}).",
              f"- [Ramp sector chart]({meta['chart_url']}) and [full sector CSV]({meta['dataset_url']}).",
              "- [BLS public API](https://api.bls.gov/publicAPI/v2/timeseries/data/); "
              "archived response in data/btos_ai/bls_ces_response.json.", "",
              "```bash", f"python3 scripts/ramp_ai_employment_quantiles.py --offline --month {month:%Y-%m-%d}", "```", ""]
    (out / "analysis.md").write_text("\n".join(lines))
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw-dir", type=Path, default=RAW)
    parser.add_argument("--bls-json", type=Path, default=ROOT / "data/btos_ai/bls_ces_response.json")
    parser.add_argument("--month", default="", help="Ranking month; default last month in the full-sector CSV.")
    parser.add_argument("--offline", action="store_true")
    args = parser.parse_args()
    csv_path = args.raw_dir / "chart_dataset.csv" if args.offline else download(args.raw_dir)
    members, month = read_adoption(csv_path, args.month)
    chart_html = (args.raw_dir / "datawrapper.html").read_text()
    chart_match = re.search(r"https://datawrapper\.dwcdn\.net/wQR5S/\d+/", chart_html)
    if chart_match is None:
        raise ValueError("Cannot identify the archived Ramp chart version.")
    chart_url = chart_match.group()
    dataset_url = chart_url + "dataset.csv"
    if not args.bls_json.exists():
        raise FileNotFoundError("Run the BTOS analysis first to archive BLS employment data.")
    summaries = []
    for groups, name in [(4, "quartile"), (5, "quintile")]:
        out = ROOT / f"outputs/ramp_ai_{name}s"
        out.mkdir(parents=True, exist_ok=True)
        grouped = members.copy()
        grouped[name] = pd.qcut(grouped.adoption_rank, groups, labels=False) + 1
        assert grouped[name].nunique() == groups
        industry, monthly, indexes, catalog, checks = employment(args.bls_json, grouped)
        latest = monthly.date.max()
        meta = {"adoption_source": "Ramp", "ramp_month": month.date().isoformat(),
                "chart_url": chart_url, "dataset_url": dataset_url,
                "group_name": name, "groups": groups, "group_sizes": grouped.groupby(name).size().tolist(),
                "chart_title": f"Employment by Ramp AI adoption {name}",
                "ranking_caption": f"Fixed groups ranked on Ramp paid AI adoption, {month:%B %Y} · Full 18-sector download",
                "source_caption": f"Sources: Ramp AI Index, {month:%B %Y} sector snapshot; BLS CES through {latest:%B %Y} (latest preliminary)."}
        plot_index(indexes, meta, out / "employment_index")
        grouped.to_csv(out / "industry_membership.csv", index=False)
        industry.to_csv(out / "industry_monthly_employment.csv", index=False)
        monthly.to_csv(out / f"{name}_monthly_employment.csv", index=False, float_format="%.6f")
        indexes.rename(columns=lambda q: f"Q{q}").to_csv(out / "employment_index.csv", float_format="%.6f")
        catalog.to_csv(out / "bls_series_catalog.csv", index=False)
        (out / "validation.json").write_text(json.dumps(checks, indent=2))
        sources = []
        for path, url in [(csv_path, dataset_url),
                          (args.bls_json, "https://api.bls.gov/publicAPI/v2/timeseries/data/")]:
            sources.append({"path": str(path.resolve()), "url": url,
                            "retrieved_at_utc": datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat(),
                            "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
        (out / "source_metadata.json").write_text(json.dumps({
            "built_at_utc": datetime.now(timezone.utc).isoformat(), "ranking": meta, "sources": sources,
        }, indent=2))
        summary = make_report(out, grouped, monthly, meta, checks)
        print(name, summary.round(3).to_string(), sep="\n")
        print(f"Artifacts: {out}")
        summaries.append(summary.reset_index().rename(columns={name: "group"}).assign(grouping=name))
    combined = ROOT / "outputs/ramp_ai_quantiles"
    combined.mkdir(parents=True, exist_ok=True)
    pd.concat(summaries, ignore_index=True).to_csv(combined / "summary.csv", index=False, float_format="%.6f")


if __name__ == "__main__":
    main()
