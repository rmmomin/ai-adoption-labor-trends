#!/usr/bin/env python3
"""Rank industries by RPS work-related genAI adoption and plot CES employment.

Builds quartiles and quintiles by default; --groups 2 builds halves.
Reuses the BLS vintage of the Census/Ramp
charts. --offline reproduces the archived FRED/RPS source data without requests.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import html
import json
from pathlib import Path
import re

import numpy as np
import pandas as pd
import requests

from btos_ai_employment_quintiles import BASE, ROOT, SECTORS, employment, plot_index

TRACKER_URL = "https://www.genaiadoptiontracker.com/"
PAPER_URL = "https://doi.org/10.1287/mnsc.2025.02523"
PREFIX = "Generative Artificial Intelligence, Adoption Rate for Work: "
# Series identities are verified against the FRED titles before mapping to CES.
RPS_INDUSTRIES = {
    2: ("21", "Mining, Quarrying, and Oil and Gas Extraction"),
    3: ("23", "Construction"),
    4: ("31-33", "Manufacturing"),
    5: ("42", "Wholesale Trade"),
    6: ("44-45", "Retail Trade"),
    7: ("48-49", "Transportation and Warehousing"),
    8: ("22", "Utilities"),
    9: ("51", "Information"),
    10: ("52", "Finance and Insurance"),
    11: ("53", "Real Estate and Rental and Leasing"),
    12: ("54", "Professional, Scientific, and Technical Services"),
    13: ("55", "Management of Companies and Enterprises"),
    14: ("56", "Administrative and Support and Waste Management Services"),
    15: ("61", "Educational Services"),
    16: ("62", "Health Care and Social Assistance"),
    17: ("71", "Arts, Entertainment, and Recreation"),
    18: ("72", "Accommodation and Food Services"),
    19: ("81", "Other Services, Except Public Administration"),
}


def download(raw):
    raw.mkdir(parents=True, exist_ok=True)

    def get(i):
        sid = f"RPSGENAIUSAGESHAREIND{i}"
        url = "https://fred.stlouisfed.org/data/" + sid
        response = requests.get(url, timeout=45)
        response.raise_for_status()
        text = response.text
        (raw / f"{sid}.html").write_text(text)
        title = html.unescape(re.search(r"<title>(.*?)</title>", text, re.S).group(1))
        title = title.removeprefix("Table Data - ").removesuffix(" | FRED | St. Louis Fed")
        table = re.search(r'<table id="data-table-observations".*?</table>', text, re.S).group()
        rows = re.findall(r'<th[^>]*>\s*(\d{4}-\d{2}-\d{2})\s*</th>\s*<td[^>]*>\s*([^<]+)</td>', table, re.S)
        return {"series_id": sid, "title": title, "url": url,
                "observations": [{"date": d, "value": float(v.strip())} for d, v in rows]}

    with ThreadPoolExecutor(max_workers=5) as pool:
        series = list(pool.map(get, range(1, 21)))
    (raw / "fred_series.json").write_text(json.dumps(series, indent=2))


def adoption(raw, quarter):
    source = json.loads((raw / "fred_series.json").read_text())
    rows, catalog = [], []
    for series in source:
        i = int(series["series_id"].removeprefix("RPSGENAIUSAGESHAREIND"))
        if i not in RPS_INDUSTRIES:
            continue  # Agriculture and public administration excluded in all analyses.
        naics, expected_title = RPS_INDUSTRIES[i]
        assert series["title"] == PREFIX + expected_title, series["title"]
        catalog.append({"rps_series_id": series["series_id"], "naics": naics,
                        "rps_industry": expected_title, "source_url": series["url"]})
        for obs in series["observations"]:
            rows.append({"rps_series_id": series["series_id"], "rps_quarter_date": pd.Timestamp(obs["date"]),
                         "ai_adoption_pct": obs["value"]})
    panel = pd.DataFrame(rows)
    assert not panel.duplicated(["rps_series_id", "rps_quarter_date"]).any()
    assert panel.ai_adoption_pct.between(0, 100).all()
    last_dates = panel.groupby("rps_series_id").rps_quarter_date.max()
    assert len(last_dates) == 18 and last_dates.nunique() == 1, "RPS series do not have a common latest release."
    selected = pd.Timestamp(quarter) if quarter else last_dates.iloc[0]
    snapshot = panel.loc[panel.rps_quarter_date.eq(selected)]
    assert len(snapshot) == 18, "Ranking snapshot is incomplete."
    mapping = pd.DataFrame(SECTORS, columns=["btos_sector", "naics", "industry", "series_id"]).drop(columns="btos_sector")
    members = mapping.merge(pd.DataFrame(catalog), on="naics", validate="one_to_one")
    members = members.merge(snapshot, on="rps_series_id", validate="one_to_one")
    assert len(members) == 18 and members.ai_adoption_pct.notna().all()
    members = members.sort_values(["ai_adoption_pct", "naics"]).reset_index(drop=True)
    members["adoption_rank"] = np.arange(1, 19)
    # The tracker identifies Q2 2026 as the May 2026 wave. Other quarters retain
    # their FRED quarter label rather than guessing survey field dates.
    wave = "May 2026 (2026 Q2)" if selected == pd.Timestamp("2026-04-01") else f"{selected.year} Q{selected.quarter}"
    return members, panel, selected, wave


def report(out, members, monthly, meta, checks):
    name, wave = meta["group_name"], meta["survey_wave"]
    group_labels = {q: f"Q{q}" for q in range(1, meta["groups"] + 1)}
    if name == "half":
        group_labels = {1: "Lower-adoption half", 2: "Higher-adoption half"}
    first = monthly.loc[monthly.date.eq(BASE)].set_index(name)
    last = monthly.loc[monthly.date.eq(monthly.date.max())].set_index(name)
    summary = members.groupby(name).agg(industries=("industry", "size"),
        ai_min_pct=("ai_adoption_pct", "min"), ai_max_pct=("ai_adoption_pct", "max"))
    summary["jan_2023_employment_millions"] = first.employment_thousands / 1000
    summary["latest_employment_millions"] = last.employment_thousands / 1000
    summary["latest_index"] = last.employment_index
    summary["employment_change_pct"] = last.employment_index - 100
    summary["group_label"] = summary.index.map(group_labels)
    summary.to_csv(out / f"{name}_summary.csv", float_format="%.6f")
    lines = [f"# {meta['chart_title']}", "",
             f"RPS ranking wave: {wave}. Employment: January 2023–{monthly.date.max():%B %Y}, "
             "seasonally adjusted; January 2023 = 100. Latest employment estimates are preliminary.", "",
             "![Employment index](employment_index.png)", "",
             f"| {name.title()} | Sectors | Work-related genAI adoption | Jan 2023 jobs (m) | Latest jobs (m) | Latest index | Change |",
             "|---|---:|---:|---:|---:|---:|---:|"]
    for q, r in summary.iterrows():
        lines.append(f"| {group_labels[q]} | {r.industries:.0f} | {r.ai_min_pct:.2f}–{r.ai_max_pct:.2f}% | "
                     f"{r.jan_2023_employment_millions:.3f} | {r.latest_employment_millions:.3f} | "
                     f"{r.latest_index:.2f} | {r.employment_change_pct:+.2f}% |")
    sizes = ", ".join(map(str, meta["group_sizes"]))
    lines += ["", "## Measure and source", "",
              "The Real-Time Population Survey (RPS) is a survey of U.S. working-age adults. These series report the "
              "share of employed adults aged 18–64 in each industry who say they use generative AI for their job. "
              "They measure any reported work-related use, not only daily or last-week use. The series are not seasonally adjusted. "
              "The GenAI Adoption Tracker is associated with Alexander Bick, Adam Blandin, David Deming, and the Harvard "
              "Project on Workforce. FRED hosts the series at the Federal Reserve Bank of St. Louis; this is not a Chicago Fed business survey.", "",
              "FRED labels the latest observations 2026-04-01, meaning 2026 Q2. The tracker identifies the corresponding survey "
              "wave as May 2026. This is a quarterly period timestamp, not an April survey observation. "
              "The downloaded FRED tables show an August 4, 2026 update date.", "",
              "## Construction", "",
              f"Rank the same 18 broad nonfarm industries used in the Census and Ramp analyses using the {wave} point estimates. "
              f"Divide their ranks into {meta['groups']} approximately equal-count groups using pandas.qcut: {sizes} industries. "
              "Ties are ordered by NAICS code. Group membership stays fixed throughout the employment history. "
              "No earlier AI adoption values are imputed for January 2023.", "",
              "For each group and month, sum BLS CES seasonally adjusted all-employees employment, divide by the group's "
              "January 2023 employment, and multiply by 100. Industry growth is therefore weighted by January 2023 payroll jobs. "
              "Employment data and their revision vintage are identical to the prior Census and Ramp charts. The groups divide "
              "industries, not employees, into adoption groups. FRED and CES series IDs are recorded in industry_membership.csv.", "",
              "## Interpretation and coverage", "",
              "These are descriptive, retrospective groups rather than estimates of AI's causal effect on employment. "
              "RPS measures workers' self-reported genAI use; Census BTOS measures businesses' reported AI use; Ramp measures "
              "observed paid AI adoption among its business customers. Their definitions, populations, and ranking dates differ.", "",
              "The employment indexes exclude government and agriculture/forestry/fishing. Education and healthcare use private "
              "CES employment. RPS industry adoption estimates are not restricted to private payroll employees, while CES counts "
              "payroll jobs across ages. The two populations therefore do not match perfectly. Small-industry survey rankings "
              "may be noisy; FRED does not supply standard errors for these adoption series. No confidence bands are inferred.", "",
              f"Validation: all {checks['industries']} sectors are present for {checks['months']} consecutive employment months; "
              "every January 2023 index equals 100 and group totals equal the included industry totals. "
              f"Summed sectors plus excluded logging reconcile to published total private within "
              f"{checks['max_sector_plus_logging_reconciliation_difference_thousands']:.1f} thousand jobs.", "",
              "## Industry membership", "", f"| {name.title()} | NAICS | Industry | Work-related genAI adoption |", "|---|---|---|---:|"]
    for r in members.itertuples():
        lines.append(f"| {group_labels[getattr(r, name)]} | {r.naics} | {r.industry} | {r.ai_adoption_pct:.2f}% |")
    lines += ["", "## Sources and reproduction", "",
              f"- [GenAI Adoption Tracker]({TRACKER_URL}).",
              f"- Bick, A., Blandin, A., and Deming, D. (2026). [The Rapid Adoption of Generative AI]({PAPER_URL}). Management Science.",
              "- [FRED RPS series example](https://fred.stlouisfed.org/series/RPSGENAIUSAGESHAREIND5); "
              "all series URLs and raw HTML hashes are in source_metadata.json.",
              "- [BLS CES API](https://api.bls.gov/publicAPI/v2/timeseries/data/); the existing archived response is reused.", "",
              "```bash", f"python3 scripts/rps_ai_employment_quantiles.py --groups {meta['groups']} --offline --quarter {meta['rps_quarter_date']}", "```", ""]
    (out / "analysis.md").write_text("\n".join(lines))
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw-dir", type=Path, default=ROOT / "data/rps_ai")
    parser.add_argument("--bls-json", type=Path, default=ROOT / "data/btos_ai/bls_ces_response.json")
    parser.add_argument("--quarter", default="", help="FRED quarter-start date; default latest common quarter.")
    parser.add_argument("--offline", action="store_true")
    parser.add_argument("--groups", type=int, nargs="+", choices=[2, 4, 5], default=[4, 5],
                        help="Numbers of groups to build: 2 for halves, 4 for quartiles, 5 for quintiles.")
    args = parser.parse_args()
    if not args.offline:
        download(args.raw_dir)
    members, panel, quarter, wave = adoption(args.raw_dir, args.quarter)
    sources = []
    paths = [(args.raw_dir / f"{sid}.html", url) for sid, url in members[["rps_series_id", "source_url"]].itertuples(index=False, name=None)]
    paths += [(args.bls_json, "https://api.bls.gov/publicAPI/v2/timeseries/data/")]
    for path, url in paths:
        sources.append({"path": str(path.resolve()), "url": url,
            "retrieved_at_utc": datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat(),
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
    panel.to_csv(args.raw_dir / "rps_industry_adoption_quarterly.csv", index=False)
    summaries = []
    for groups in sorted(set(args.groups)):
        name = {2: "half", 4: "quartile", 5: "quintile"}[groups]
        plural = "halves" if groups == 2 else f"{name}s"
        out = ROOT / f"outputs/rps_ai_{plural}"
        out.mkdir(parents=True, exist_ok=True)
        grouped = members.copy()
        grouped[name] = pd.qcut(grouped.adoption_rank, groups, labels=False) + 1
        if groups == 2:
            grouped["group_label"] = grouped[name].map({1: "Lower-adoption half", 2: "Higher-adoption half"})
        industry, monthly, indexes, catalog, checks = employment(args.bls_json, grouped)
        meta = {"adoption_source": "RPS / GenAI Adoption Tracker via FRED", "survey_wave": wave,
                "rps_quarter_date": quarter.date().isoformat(), "groups": groups, "group_name": name,
                "group_sizes": grouped.groupby(name).size().tolist(),
                "chart_title": f"Employment by RPS genAI adoption {plural if groups == 2 else name}",
                "ranking_caption": f"Fixed groups ranked on workers' genAI use for work · {wave}",
                "source_caption": f"Sources: Bick, Blandin & Deming, RPS via FRED; BLS CES through {monthly.date.max():%B %Y} (latest preliminary)."}
        plot_index(indexes, meta, out / "employment_index")
        grouped.to_csv(out / "industry_membership.csv", index=False)
        industry.to_csv(out / "industry_monthly_employment.csv", index=False)
        monthly.to_csv(out / f"{name}_monthly_employment.csv", index=False, float_format="%.6f")
        index_labels = {1: "Lower_adoption_half", 2: "Higher_adoption_half"} if groups == 2 else {q: f"Q{q}" for q in range(1, groups + 1)}
        indexes.rename(columns=index_labels).to_csv(out / "employment_index.csv", float_format="%.6f")
        catalog.to_csv(out / "bls_series_catalog.csv", index=False)
        (out / "source_metadata.json").write_text(json.dumps({
            "built_at_utc": datetime.now(timezone.utc).isoformat(), "ranking": meta, "sources": sources}, indent=2))
        (out / "validation.json").write_text(json.dumps(checks, indent=2))
        summary = report(out, grouped, monthly, meta, checks)
        print(name, summary.round(3).to_string(), sep="\n")
        print(f"Artifacts: {out}")
        summaries.append(summary.reset_index().rename(columns={name: "group"}).assign(grouping=name))
    combined = ROOT / "outputs/rps_ai_quantiles"
    combined.mkdir(parents=True, exist_ok=True)
    summary_file = "summary.csv" if sorted(set(args.groups)) == [4, 5] else "summary_groups_" + "_".join(map(str, sorted(set(args.groups)))) + ".csv"
    pd.concat(summaries, ignore_index=True).to_csv(combined / summary_file, index=False, float_format="%.6f")


if __name__ == "__main__":
    main()
