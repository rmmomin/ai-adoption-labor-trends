#!/usr/bin/env python3
"""Download Census BTOS AI adoption and BLS CES employment; plot fixed quantiles.

Run from any directory. Use --offline to reproduce the saved source vintage.
Groups contain approximately equal numbers of broad NAICS sectors, not jobs.
Employment is summed within each fixed group before rebasing to January 2023.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import requests

from bls_api import BLS_V2_TIMESERIES_URL, resolve_bls_api_key

ROOT = Path(__file__).resolve().parents[1]
BTOS_URL = "https://www.census.gov/hfp/btos/downloads/Sector.xlsx"
BTOS_DOCS = "https://www.census.gov/hfp/btos/data_downloads"
WORDING_URL = "https://www.census.gov/hfp/btos/downloads/AI%20Question%20Wording%20Updates.pdf"
BASE = pd.Timestamp("2023-01-01")
# BTOS uses 31, 44, and 48 for the combined NAICS sectors 31-33, 44-45, 48-49.
# Each entry is a distinct, non-overlapping private CES all-employees SA series.
SECTORS = [
    ("21", "21", "Mining, quarrying, and oil and gas extraction", "CES1021000001"),
    ("22", "22", "Utilities", "CES4422000001"),
    ("23", "23", "Construction", "CES2000000001"),
    ("31", "31-33", "Manufacturing", "CES3000000001"),
    ("42", "42", "Wholesale trade", "CES4142000001"),
    ("44", "44-45", "Retail trade", "CES4200000001"),
    ("48", "48-49", "Transportation and warehousing", "CES4300000001"),
    ("51", "51", "Information", "CES5000000001"),
    ("52", "52", "Finance and insurance", "CES5552000001"),
    ("53", "53", "Real estate and rental and leasing", "CES5553000001"),
    ("54", "54", "Professional, scientific, and technical services", "CES6054000001"),
    ("55", "55", "Management of companies and enterprises", "CES6055000001"),
    ("56", "56", "Administrative, support, and waste services", "CES6056000001"),
    ("61", "61", "Private educational services", "CES6561000001"),
    ("62", "62", "Health care and social assistance", "CES6562000001"),
    ("71", "71", "Arts, entertainment, and recreation", "CES7071000001"),
    ("72", "72", "Accommodation and food services", "CES7072000001"),
    ("81", "81", "Other services, except government", "CES8000000001"),
]
COLORS = {1: "#3B728F", 2: "#48A49C", 3: "#B39736", 4: "#D56B3D", 5: "#834C98"}


def percent(series):
    """Published percentages become percentage points; suppression is missing."""
    return pd.to_numeric(series.astype(str).str.rstrip("%"), errors="coerce")


def sources(raw, offline):
    raw.mkdir(parents=True, exist_ok=True)
    workbook = raw / "Sector.xlsx"
    response_file = raw / "bls_ces_response.json"
    if not offline:
        response = requests.get(BTOS_URL, timeout=60)
        response.raise_for_status()
        workbook.write_bytes(response.content)
        ids = [row[3] for row in SECTORS] + ["CES0500000001", "CES1011330001"]
        response = requests.post(BLS_V2_TIMESERIES_URL, json={
            "seriesid": sorted(ids), "startyear": "2023",
            "endyear": str(datetime.now().year), "catalog": True,
            "registrationkey": resolve_bls_api_key(),
        }, timeout=60)
        response.raise_for_status()
        body = response.json()
        if body.get("status") != "REQUEST_SUCCEEDED" or body.get("message"):
            raise RuntimeError(f"BLS request needs review: {body.get('message')}")
        response_file.write_text(json.dumps(body, indent=2))
    if not workbook.exists() or not response_file.exists():
        raise FileNotFoundError("Missing source files. Run without --offline first.")
    return workbook, response_file


def adoption(workbook, period, groups=5):
    estimates = pd.read_excel(workbook, sheet_name="Response Estimates")
    errors = pd.read_excel(workbook, sheet_name="Response Standard Errors")
    dates = pd.read_excel(workbook, sheet_name="Collection and Reference Dates")
    dates = dates.loc[dates["Smpdt"].notna()].copy()
    dates["Smpdt"] = dates["Smpdt"].astype(int)
    dates["Publication Date"] = pd.to_datetime(dates["Publication Date"])
    available = dates.loc[dates["Publication Date"] <= pd.Timestamp.now().normalize()]
    selected = int(period) if period else int(available["Smpdt"].max())
    timing = available.loc[available["Smpdt"].eq(selected)].iloc[0]
    col = str(selected)
    query = estimates["Question"].str.contains("In the last two weeks", na=False)
    query &= estimates["Question"].str.contains("Artificial Intelligence", na=False)
    query &= estimates["Question"].str.contains("any of its business functions", na=False)
    query &= estimates["Answer"].eq("Yes")
    selected_rows = estimates.loc[query].copy()
    selected_rows["Sector"] = selected_rows["Sector"].astype(str)
    assert selected_rows["Question ID"].nunique() == 1
    qid = selected_rows["Question ID"].iloc[0]
    selected_errors = errors.loc[errors["Question ID"].eq(qid) & errors["Answer"].eq("Yes")].copy()
    selected_errors["Sector"] = selected_errors["Sector"].astype(str)
    selected_rows["ai_adoption_pct"] = percent(selected_rows[col])
    selected_errors["ai_standard_error_pp"] = percent(selected_errors[col])
    membership = pd.DataFrame(SECTORS, columns=["btos_sector", "naics", "industry", "series_id"])
    membership = membership.merge(
        selected_rows[["Sector", "ai_adoption_pct"]], left_on="btos_sector", right_on="Sector",
        how="left", validate="one_to_one",
    ).drop(columns="Sector")
    membership = membership.merge(
        selected_errors[["Sector", "ai_standard_error_pp"]], left_on="btos_sector", right_on="Sector",
        how="left", validate="one_to_one",
    ).drop(columns="Sector")
    if membership.ai_adoption_pct.isna().any():
        missing = membership.loc[membership.ai_adoption_pct.isna(), "naics"].tolist()
        raise ValueError(f"AI adoption missing/suppressed for {missing} in {col}; select another --period.")
    membership = membership.sort_values(["ai_adoption_pct", "naics"]).reset_index(drop=True)
    membership["adoption_rank"] = np.arange(1, len(membership) + 1)
    group_name = "quartile" if groups == 4 else "quintile"
    membership[group_name] = pd.qcut(membership["adoption_rank"], groups, labels=False) + 1
    membership["btos_period"] = selected
    for key in ["Reference Period Start", "Ref End", "Collection Start", "Col End", "Publication Date"]:
        membership[key.lower().replace(" ", "_")] = pd.Timestamp(timing[key]).date().isoformat()
    metadata = {"period": selected, "question": selected_rows["Question"].iloc[0],
                "group_name": group_name, "groups": groups,
                "group_sizes": membership.groupby(group_name).size().tolist()}
    metadata.update({k: pd.Timestamp(timing[k]).date().isoformat() for k in [
        "Reference Period Start", "Ref End", "Collection Start", "Col End", "Publication Date"]})
    return membership, metadata


def employment(response_file, membership):
    group_columns = [name for name in ("half", "quartile", "quintile") if name in membership.columns]
    if len(group_columns) != 1:
        raise ValueError("Membership must contain exactly one grouping column.")
    group_name = group_columns[0]
    body = json.loads(response_file.read_text())
    assert body["status"] == "REQUEST_SUCCEEDED"
    rows, catalog = [], []
    for series in body["Results"]["series"]:
        sid = series["seriesID"]
        title = series.get("catalog", {}).get("series_title", "")
        assert title.startswith("All employees, thousands,") and title.endswith("seasonally adjusted"), (sid, title)
        catalog.append({"series_id": sid, **series.get("catalog", {})})
        for obs in series["data"]:
            if obs["period"] == "M13" or not obs["period"].startswith("M"):
                continue
            date = pd.Timestamp(int(obs["year"]), int(obs["period"][1:]), 1)
            if BASE <= date <= pd.Timestamp.now().normalize():
                rows.append({"date": date, "series_id": sid, "employment_thousands": float(obs["value"]),
                             "preliminary": any(f.get("code") == "P" for f in obs.get("footnotes", []))})
    data = pd.DataFrame(rows)
    assert not data.duplicated(["date", "series_id"]).any()
    required = set(membership.series_id) | {"CES0500000001", "CES1011330001"}
    assert required == set(data.series_id)
    wide = data.pivot(index="date", columns="series_id", values="employment_thousands").sort_index()
    assert not wide.isna().any().any(), "Missing monthly data; do not change group composition."
    assert wide.index.equals(pd.date_range(BASE, wide.index.max(), freq="MS")), "Missing months."
    assert (wide > 0).all().all()
    industry = data.merge(membership, on="series_id", how="inner", validate="many_to_one")
    group = industry.groupby(["date", group_name], as_index=False).agg(
        employment_thousands=("employment_thousands", "sum"), preliminary=("preliminary", "any"),
        industry_count=("series_id", "nunique"))
    levels = group.pivot(index="date", columns=group_name, values="employment_thousands")
    indexes = levels.div(levels.loc[BASE]).mul(100)
    assert np.allclose(indexes.loc[BASE], 100)
    assert np.allclose(levels.sum(axis=1), wide[membership.series_id].sum(axis=1))
    # Sector totals plus excluded logging should reconcile with published total private,
    # allowing published rounding and independent seasonal adjustment of aggregates.
    difference = levels.sum(axis=1) + wide["CES1011330001"] - wide["CES0500000001"]
    assert (difference.abs() / wide["CES0500000001"]).max() < 0.001
    index_long = indexes.rename_axis(columns=group_name).stack().rename("employment_index").reset_index()
    group = group.merge(index_long, on=["date", group_name], validate="one_to_one")
    group["change_since_jan_2023_pct"] = group.employment_index - 100
    checks = {"passed": True, "months": len(wide), "industries": len(membership),
              "group_name": group_name, "group_sizes": membership.groupby(group_name).size().tolist(),
              "latest_employment_month": wide.index.max().date().isoformat(),
              "max_sector_plus_logging_reconciliation_difference_thousands": float(difference.abs().max()),
              "latest_share_of_total_private_employment_pct": float(levels.iloc[-1].sum() / wide["CES0500000001"].iloc[-1] * 100)}
    return industry, group, indexes, pd.DataFrame(catalog), checks


def plot_index(indexes, meta, path):
    group_name, groups = meta["group_name"], meta["groups"]
    colors = COLORS if groups == 5 else {1: COLORS[1], 2: COLORS[2], 3: COLORS[4], 4: COLORS[5]}
    labels = {q: f"Q{q}" for q in range(1, groups + 1)}
    labels.update({1: "Q1 · Lowest AI", groups: f"Q{groups} · Highest AI"})
    endpoint_labels = {q: f"Q{q}" for q in range(1, groups + 1)}
    if groups == 2:
        colors = {1: COLORS[1], 2: COLORS[5]}
        labels = {1: "Lower-adoption half", 2: "Higher-adoption half"}
        endpoint_labels = {1: "Lower half", 2: "Higher half"}
    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 11, "svg.fonttype": "none"})
    fig, ax = plt.subplots(figsize=(13, 7.8), facecolor="white")
    fig.subplots_adjust(left=.075, right=.79, bottom=.21, top=.75)
    title = meta.get("chart_title", f"Employment by industry AI adoption {group_name}")
    fig.text(.075, .935, title, fontsize=22, weight="bold", color="#18313F")
    fig.text(.075, .89, "Seasonally adjusted payroll employment · January 2023 = 100", fontsize=13, color="#50636D")
    ranking_caption = meta.get("ranking_caption")
    if ranking_caption is None:
        start = pd.Timestamp(meta["Reference Period Start"])
        end = pd.Timestamp(meta["Ref End"])
        ranking_caption = f"Fixed groups ranked on BTOS AI use, {start:%b %d}–{end:%b %d, %Y}"
    fig.text(.075, .853, ranking_caption, fontsize=11, color="#50636D")
    for q in range(1, groups + 1):
        ax.plot(indexes.index, indexes[q], color=colors[q], lw=2.7, label=labels[q])
    ax.axhline(100, color="#87949B", lw=1, linestyle=(0, (3, 3)), zorder=0)
    ax.grid(axis="y", color="#E6EBEE", lw=.8)
    ax.set_axisbelow(True)
    for name in ["top", "right", "left"]:
        ax.spines[name].set_visible(False)
    ax.spines["bottom"].set_color("#C6D0D6")
    ax.tick_params(axis="both", length=0, pad=10, colors="#50636D")
    latest = indexes.index.max()
    ticks = list(pd.date_range(BASE, latest, freq="YS"))
    if latest.month != 1:
        ticks.append(latest)
    ax.set_xticks(ticks)
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%b\n%Y"))
    ax.set_xlim(BASE, latest)
    low, high = float(indexes.min().min()), float(indexes.max().max())
    ax.set_ylim(min(98, low - .7), high + 1)
    values = indexes.iloc[-1].sort_values()
    label_y = values.to_numpy().copy()
    spacing = max(.7, (high - low) * .065)
    for i in range(1, len(label_y)):
        label_y[i] = max(label_y[i], label_y[i-1] + spacing)
    label_y -= (label_y - values.to_numpy()).mean()
    for (q, value), y in zip(values.items(), label_y):
        ax.scatter([latest], [value], color=colors[q], s=26, zorder=4, clip_on=False)
        ax.annotate(f"{endpoint_labels[q]}  {value:.1f}", xy=(latest, value), xytext=(mdates.date2num(latest) + 45, y),
                    textcoords="data", fontsize=12, weight="bold", color=colors[q], va="center",
                    annotation_clip=False, arrowprops={"arrowstyle": "-", "color": colors[q], "lw": .8})
    fig.legend(*ax.get_legend_handles_labels(), loc="upper left", bbox_to_anchor=(.066, .823),
               frameon=False, ncol=groups, columnspacing=2.0, handlelength=2.1)
    sizes = " / ".join(map(str, meta["group_sizes"]))
    group_plural = "halves" if group_name == "half" else f"{group_name}s"
    fig.text(.075, .105, f"18 broad NAICS sectors; {group_plural} contain {sizes} sectors from lowest to highest AI use.",
             fontsize=10, color="#50636D")
    fig.text(.075, .075, "Each index = total group employment / January 2023 group employment × 100. Membership stays fixed.",
             fontsize=10, color="#50636D")
    source_caption = meta.get("source_caption")
    if source_caption is None:
        source_caption = f"Sources: Census BTOS (released {meta['Publication Date']}); BLS CES through {latest:%B %Y} (latest preliminary)."
    fig.text(.075, .04, source_caption,
             fontsize=9, color="#70818A")
    for suffix in ["png", "svg"]:
        fig.savefig(path.with_suffix("." + suffix), dpi=180, facecolor="white")
    plt.close(fig)


def report(out, membership, group, meta, checks, source_meta):
    group_name, groups = meta["group_name"], meta["groups"]
    sizes = ", ".join(map(str, meta["group_sizes"]))
    group_option = f" --groups {groups}" if groups != 5 else ""
    latest = group.date.max()
    summary = membership.groupby(group_name).agg(
        industries=("industry", "size"), ai_min_pct=("ai_adoption_pct", "min"),
        ai_max_pct=("ai_adoption_pct", "max"))
    first = group.loc[group.date.eq(BASE)].set_index(group_name)
    last = group.loc[group.date.eq(latest)].set_index(group_name)
    summary["jan_2023_employment_millions"] = first.employment_thousands / 1000
    summary["latest_employment_millions"] = last.employment_thousands / 1000
    summary["latest_index"] = last.employment_index
    summary["employment_change_pct"] = last.change_since_jan_2023_pct
    summary.to_csv(out / f"{group_name}_summary.csv", float_format="%.6f")
    lines = [f"# Employment by Census BTOS AI adoption {group_name}", "",
             f"Employment: January 2023–{latest:%B %Y}. January 2023 = 100. Latest employment estimates are preliminary.", "",
             f"AI ranking: BTOS period {meta['period']}, reference {meta['Reference Period Start']}–{meta['Ref End']}; "
             f"collection {meta['Collection Start']}–{meta['Col End']}; published {meta['Publication Date']}.", "",
             "![Employment index](employment_index.png)", "",
             f"| {group_name.title()} | Sectors | AI adoption range | Jan 2023 jobs (m) | Latest jobs (m) | Latest index | Change |",
             "|---|---:|---:|---:|---:|---:|---:|"]
    for q, r in summary.iterrows():
        lines.append(f"| Q{q} | {r.industries:.0f} | {r.ai_min_pct:.1f}–{r.ai_max_pct:.1f}% | "
                     f"{r.jan_2023_employment_millions:.3f} | {r.latest_employment_millions:.3f} | "
                     f"{r.latest_index:.2f} | {r.employment_change_pct:+.2f}% |")
    lines += ["", "## Method", "",
              "Rank 18 broad nonfarm NAICS sectors by the published percentage of businesses answering yes to current AI use in any business function. "
              f"Use the selected published period, not expected future use. Divide ordered sector ranks into {groups} bins using pandas.qcut: {sizes} sectors. "
              f"These are {group_name}s of sectors, not {group_name}s of employment. Ties are ordered by NAICS code.", "",
              f"Match each sector to its BLS CES seasonally adjusted all-employees series. Sum employment within each fixed {group_name} each month, "
              "then divide by the group's January 2023 sum and multiply by 100. This weights sector growth by January 2023 employment. "
              "No missing values are filled and no industries enter or leave the groups over time. Series IDs and AI standard errors are in industry_membership.csv.", "",
              "## Interpretation and coverage", "",
              "This is a retrospective, descriptive grouping based on 2026 AI adoption. It does not measure the causal effect of AI on jobs, "
              f"and it does not assert these {group_name}s were known in January 2023. BTOS did not measure this AI question in January 2023; "
              "only employment is indexed to that month. Census broadened its AI wording in November 2025, so the ranking does not splice old and new AI definitions.", "",
              "BTOS adoption is a survey estimate for businesses, not a worker adoption rate. CES measures payroll jobs at establishments, not unique workers. "
              "Government employment, NAICS 11 (agriculture/forestry/fishing), and the unassignable BTOS multi-sector category XX are excluded. "
              "The CES education and health series cover private employment. BTOS places businesses spanning multiple sectors in XX; "
              "their establishment jobs can still appear in CES sector totals. The universes therefore do not align perfectly.", "",
              f"Sector point estimates have sampling error; {group_name} boundaries are not statistically sharp. In particular, management of companies "
              "has a large AI adoption standard error in this release; inspect the membership file before interpreting small rank differences. "
              "Broad sectors provide complete current estimates; many detailed subsector estimates are suppressed. The plot has no confidence bands "
              "because published sector summaries do not provide the joint uncertainty needed for these constructed indexes.", "",
              f"Validation: {checks['industries']} distinct sectors × {checks['months']} consecutive months, complete data, {groups} fixed groups, "
              "all base indexes equal 100. Group sums equal the included industry sums. "
              f"Sectors plus excluded logging reconcile to total private within {checks['max_sector_plus_logging_reconciliation_difference_thousands']:.1f} thousand jobs "
              f"across all months; latest coverage is {checks['latest_share_of_total_private_employment_pct']:.2f}% of total private payrolls.", "",
              "## Industry membership", "", f"| {group_name.title()} | NAICS | Industry | AI adoption | SE (pp) |", "|---|---|---|---:|---:|"]
    for r in membership.itertuples():
        lines.append(f"| Q{getattr(r, group_name)} | {r.naics} | {r.industry} | {r.ai_adoption_pct:.1f}% | {r.ai_standard_error_pp:.2f} |")
    lines += ["", "## Sources and reproduction", "",
              f"- [Census BTOS downloads]({BTOS_DOCS}); [sector workbook]({BTOS_URL}).",
              f"- [Census AI question wording change]({WORDING_URL}).",
              f"- [BLS public API]({BLS_V2_TIMESERIES_URL}); response and catalog archived locally.",
              f"- Raw source hashes, retrieval times, dates, and validation results: source_metadata.json and validation.json.", "",
              "```bash", f"python3 scripts/btos_ai_employment_quintiles.py{group_option}", "# Reproduce this downloaded vintage:",
              f"python3 scripts/btos_ai_employment_quintiles.py{group_option} --period {meta['period']} --offline", "```", ""]
    (out / "analysis.md").write_text("\n".join(lines))
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw-dir", type=Path, default=ROOT / "data/btos_ai")
    parser.add_argument("--outdir", type=Path, default=None)
    parser.add_argument("--groups", type=int, choices=[4, 5], default=5, help="4 for quartiles; 5 for quintiles (default).")
    parser.add_argument("--period", default="", help="BTOS period, e.g. 202618; default latest published.")
    parser.add_argument("--offline", action="store_true", help="Reuse the archived workbook and BLS JSON without network calls.")
    args = parser.parse_args()
    group_name = "quartile" if args.groups == 4 else "quintile"
    if args.outdir is None:
        args.outdir = ROOT / f"outputs/btos_ai_{group_name}s"
    args.outdir.mkdir(parents=True, exist_ok=True)
    workbook, response_file = sources(args.raw_dir, args.offline)
    members, meta = adoption(workbook, args.period, args.groups)
    industry, group, indexes, catalog, checks = employment(response_file, members)
    members.to_csv(args.outdir / "industry_membership.csv", index=False)
    industry.to_csv(args.outdir / "industry_monthly_employment.csv", index=False)
    group.to_csv(args.outdir / f"{group_name}_monthly_employment.csv", index=False, float_format="%.6f")
    indexes.rename(columns=lambda q: f"Q{q}").to_csv(args.outdir / "employment_index.csv", float_format="%.6f")
    catalog.to_csv(args.outdir / "bls_series_catalog.csv", index=False)
    (args.outdir / "validation.json").write_text(json.dumps(checks, indent=2))
    source_meta = {"built_at_utc": datetime.now(timezone.utc).isoformat(), "btos": meta, "sources": []}
    for path, url in [(workbook, BTOS_URL), (response_file, BLS_V2_TIMESERIES_URL)]:
        source_meta["sources"].append({"path": str(path.resolve()), "url": url,
            "retrieved_at_utc": datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat(),
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
    (args.outdir / "source_metadata.json").write_text(json.dumps(source_meta, indent=2))
    plot_index(indexes, meta, args.outdir / "employment_index")
    summary = report(args.outdir, members, group, meta, checks, source_meta)
    print(summary.round(3).to_string())
    print(json.dumps(checks, indent=2))
    print(f"Artifacts: {args.outdir.resolve()}")


if __name__ == "__main__":
    main()
