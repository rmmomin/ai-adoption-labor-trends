#!/usr/bin/env python3
"""Plot annual BLS detailed-industry productivity by fixed RPS adoption groups.

Use 2023 annual average = 100. Within each covered RPS sector, combine rebased
industry indexes with fixed 2023 hours weights; give sectors equal group weights.
The resulting composites describe covered industries, not official BLS aggregates.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.ticker import MultipleLocator
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
SOURCE_URL = "https://www.bls.gov/productivity/tables/labor-productivity-detailed-industries.xlsx"
TRACKER_URL = "https://www.genaiadoptiontracker.com/"
# FRED RPS industry numbers map to broad NAICS sectors. Agriculture and public
# administration are outside this analysis. Titles verify each source identity.
RPS_SECTORS = {
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
BASE = 2023
NAMES = {2: "halves", 4: "quartiles", 5: "quintiles"}
COLORS = {2: ["#356A8A", "#81559C"],
          4: ["#356A8A", "#33958F", "#CC713A", "#81559C"],
          5: ["#356A8A", "#33958F", "#AE9029", "#CC713A", "#81559C"]}


def load_rps(raw_dir, quarter):
    source = json.loads((raw_dir/"fred_series.json").read_text())
    rows = []
    for series in source:
        number = int(series["series_id"].removeprefix("RPSGENAIUSAGESHAREIND"))
        if number not in RPS_SECTORS:
            continue
        naics, title = RPS_SECTORS[number]
        if series["title"] != "Generative Artificial Intelligence, Adoption Rate for Work: " + title:
            raise ValueError(f"RPS source title mismatch: {series['series_id']}")
        for observation in series["observations"]:
            rows.append({"naics":naics,"industry":title,"rps_industry":title,
                         "rps_series_id":series["series_id"],"source_url":series["url"],
                         "rps_quarter_date":pd.Timestamp(observation["date"]),
                         "ai_adoption_pct":float(observation["value"])})
    panel = pd.DataFrame(rows)
    if panel.empty or panel.duplicated(["naics","rps_quarter_date"]).any():
        raise ValueError("Empty or duplicated RPS observations")
    if not panel.ai_adoption_pct.between(0,100).all():
        raise ValueError("RPS adoption must be between 0 and 100 percent")
    latest = panel.groupby("naics").rps_quarter_date.max()
    if len(latest) != len(RPS_SECTORS) or latest.nunique() != 1:
        raise ValueError("RPS sectors lack a complete common latest wave")
    selected = pd.Timestamp(quarter) if quarter else latest.iloc[0]
    members = panel.loc[panel.rps_quarter_date.eq(selected)].copy()
    if len(members) != len(RPS_SECTORS):
        raise ValueError("Selected RPS wave is incomplete")
    members = members.sort_values(["ai_adoption_pct","naics"]).reset_index(drop=True)
    members["adoption_rank"] = np.arange(1,len(members)+1)
    wave = "May 2026 (2026 Q2)" if selected == pd.Timestamp("2026-04-01") else f"{selected.year} Q{selected.quarter}"
    return members, selected, wave


def code_prefixes(code):
    """Expand BLS compact lists such as 44,45 and 722513,4,5."""
    parts = str(code).split(",")
    first = parts[0]
    if not all(part.isdigit() for part in parts):
        raise ValueError(f"Unsupported NAICS notation: {code}")
    return tuple(first[:len(first)-len(part)] + part for part in parts)


def sector_for(code):
    sectors = set()
    for prefix in code_prefixes(code):
        two = prefix[:2]
        sectors.add({"31": "31-33", "32": "31-33", "33": "31-33",
                     "44": "44-45", "45": "44-45", "48": "48-49", "49": "48-49"}.get(two, two))
    if len(sectors) != 1:
        raise ValueError(f"Cross-sector industry: {code}")
    return sectors.pop()


def select_nonoverlapping(candidates):
    selected, reasons = [], {}
    # Prefer the broadest complete published series. If its data are missing,
    # complete children can enter; the same set is used in all plotted years.
    for code in sorted(candidates, key=lambda c: (min(map(len, code_prefixes(c))), c)):
        prefixes = code_prefixes(code)
        parent = next((old for old in selected if all(
            any(p.startswith(q) for q in code_prefixes(old)) for p in prefixes)), None)
        if parent is not None:
            reasons[code] = f"Covered by selected parent {parent}"
            continue
        if any(p.startswith(q) or q.startswith(p) for p in prefixes
               for old in selected for q in code_prefixes(old)):
            raise ValueError(f"Partially overlapping NAICS groups at {code}")
        selected.append(code)
        reasons[code] = "Selected"
    return selected, reasons


def load_source(path, end_year):
    source = pd.read_excel(path, sheet_name="Annual", header=2, dtype={"NAICS": str})
    source.columns = source.columns.map(str)
    years = list(range(BASE, end_year+1))
    if not set(map(str, years)).issubset(source.columns):
        raise ValueError("Requested years are not in the BLS Annual sheet")
    lp = source[(source.Measure == "Labor productivity") &
                (source.Units == "Index (2017=100)") & (source.Basis == "All workers")].copy()
    lp["source_excel_row"] = lp.index + 4
    if lp.NAICS.duplicated().any():
        raise ValueError("Duplicate productivity rows for a NAICS code")
    lp = lp.set_index("NAICS")
    hours = source[(source.Measure == "Hours worked") & (source.Units == "Millions of hours") &
                   (source.Basis == "All workers")].set_index("NAICS")
    if hours.index.duplicated().any():
        raise ValueError("Duplicate hours-level rows")
    lp["base_hours_millions"] = pd.to_numeric(hours[str(BASE)], errors="coerce")
    for year in years:
        lp[str(year)] = pd.to_numeric(lp[str(year)], errors="coerce")
    fields = list(map(str, years)) + ["base_hours_millions"]
    eligible = lp[fields].notna().all(axis=1) & lp[fields].gt(0).all(axis=1)
    selected, reasons = select_nonoverlapping(lp.index[eligible].tolist())
    lp["selection_reason"] = [reasons.get(c, "Missing/nonpositive productivity in plotted years or base-year hours") for c in lp.index]
    lp["selected"] = lp.index.isin(selected)
    lp["rps_naics"] = [sector_for(code) for code in lp.index]
    details = lp.loc[selected].copy()
    levels = details[list(map(str, years))].T
    levels.index = pd.Index(years, name="year")
    normalized = 100 * levels.div(levels.loc[BASE], axis=1)
    details["sector_hours_weight"] = details.base_hours_millions / details.groupby("rps_naics").base_hours_millions.transform("sum")
    sectors = pd.DataFrame({sector: normalized[codes.index].mul(codes.sector_hours_weight, axis=1).sum(axis=1)
                            for sector, codes in details.groupby("rps_naics")})
    sectors.index.name = "year"
    # Compare index-implied annual growth against separately published BLS rates.
    change = source[(source.Measure == "Labor productivity") &
                    (source.Units == "% Change from previous year") & (source.Basis == "All workers")].set_index("NAICS")
    growth = 100 * levels.pct_change(fill_method=None)
    diffs = []
    for year in years[1:]:
        reported = pd.to_numeric(change.loc[selected, str(year)], errors="coerce")
        if reported.isna().any():
            raise ValueError("Missing published BLS growth-rate cross-check")
        # BLS publishes these rates to one decimal and the indexes to three.
        # Bound the effect of rounding both indexes before comparing the rate.
        prev, current = levels.loc[year-1], levels.loc[year]
        lower = 100 * ((current-.0005)/(prev+.0005)-1)
        upper = 100 * ((current+.0005)/(prev-.0005)-1)
        if ((reported+.05 < lower) | (reported-.05 > upper)).any():
            raise ValueError(f"Published growth is inconsistent with rounded indexes in {year}")
        diffs.extend((growth.loc[year]-reported).abs().tolist())
    max_growth_diff = max(diffs)
    assert np.allclose(normalized.loc[BASE], 100)
    assert np.allclose(sectors.loc[BASE], 100)
    assert np.allclose(details.groupby("rps_naics").sector_hours_weight.sum(), 1)
    return lp.reset_index(), details.reset_index(), normalized, sectors, max_growth_diff


def label(n, g):
    if n == 2:
        return "Lower AI" if g == 1 else "Higher AI"
    return f"Q{g}"


def plot_panel(ax, indexes, n, ylimits):
    years = indexes.index.to_numpy()
    for g in indexes:
        ax.plot(years, indexes[g], color=COLORS[n][g-1], lw=2.7, marker="o", ms=4.5)
    ax.axhline(100, color="#A4AFB5", lw=.8, linestyle=(0, (3, 3)))
    ax.set_xticks(years)
    ax.set_xlim(years[0]-.07, years[-1]+.90)
    ax.set_ylim(*ylimits)
    ax.yaxis.set_major_locator(MultipleLocator(2))
    ax.grid(axis="y", color="#E5EBEF", lw=.8)
    ax.set_axisbelow(True)
    ax.tick_params(length=0, pad=8, colors="#50636D", labelsize=10)
    for spine in ["top", "right", "left"]:
        ax.spines[spine].set_visible(False)
    ax.spines["bottom"].set_color("#CCD5DA")
    ordered = indexes.iloc[-1].sort_values()
    text_y = ordered.to_numpy().copy()
    gap = (ylimits[1]-ylimits[0])*.079
    for j in range(1, len(text_y)):
        text_y[j] = max(text_y[j], text_y[j-1]+gap)
    text_y -= np.mean(text_y-ordered.to_numpy())
    for (g, value), y in zip(ordered.items(), text_y):
        ax.annotate(f"{label(n,g)}  {value:.1f}", xy=(years[-1], value), xytext=(years[-1]+.16, y),
                    va="center", fontsize=10, color=COLORS[n][g-1],
                    arrowprops={"arrowstyle": "-", "color": COLORS[n][g-1], "lw": .65})
    ax.set_title(NAMES[n].title(), loc="left", fontsize=15, weight="bold", color="#18313F", pad=15)


def make_charts(results, out, wave, sectors_n, industries_n):
    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 11, "svg.fonttype": "none"})
    all_values = np.concatenate([r.to_numpy().ravel() for r in results.values()])
    limits = (min(98, np.floor(all_values.min()-1)), np.ceil(all_values.max()+1.2))
    fig, axes = plt.subplots(1, len(results), figsize=(16, 6.8), squeeze=False)
    fig.subplots_adjust(left=.055, right=.98, bottom=.255, top=.735, wspace=.23)
    fig.text(.055, .935, "Annual productivity by RPS AI adoption", fontsize=24, weight="bold", color="#18313F")
    fig.text(.055, .883, f"2023 annual average = 100  ·  {wave} adoption ranking  ·  fixed groups", fontsize=12, color="#50636D")
    fig.text(.055, .833, f"{sectors_n} covered RPS sectors; {industries_n} nonoverlapping BLS industry series with data for every plotted year", fontsize=11, color="#50636D")
    for ax, (n, indexes) in zip(axes[0], results.items()):
        plot_panel(ax, indexes, n, limits)
    axes[0, 0].set_ylabel("Productivity index", color="#50636D", labelpad=9)
    fig.text(.055, .175, "Q1 = lowest AI adoption; Q4/Q5 = highest. Quantiles split covered sectors by count, not workers.", fontsize=10, color="#50636D")
    fig.text(.055, .133, "Sectors have equal group weights. Within sectors, covered industries use fixed 2023 hours weights.", fontsize=10, color="#50636D")
    fig.text(.055, .091, "Partial industry coverage: these are descriptive composites, not official BLS aggregates or estimates of AI’s causal effect.", fontsize=10, color="#50636D")
    fig.text(.055, .049, "Sources: BLS annual detailed-industry workbook, August 26, 2026 release; RPS (Bick, Blandin & Deming) via FRED.", fontsize=10, color="#50636D")
    for ext in ["png", "svg", "pdf"]:
        fig.savefig(out/f"productivity_comparison.{ext}", dpi=200, facecolor="white")
    plt.close(fig)
    for n, indexes in results.items():
        fig, ax = plt.subplots(figsize=(10, 6.6))
        fig.subplots_adjust(left=.09, right=.96, bottom=.22, top=.72)
        fig.text(.09,.93,f"Annual productivity by AI adoption {NAMES[n]}",fontsize=20,weight="bold",color="#18313F")
        fig.text(.09,.875,f"2023 annual average = 100  ·  RPS {wave}",fontsize=11,color="#50636D")
        plot_panel(ax,indexes,n,limits)
        ax.set_title(f"{sectors_n} covered sectors; fixed membership",loc="left",fontsize=11,color="#50636D")
        fig.text(.09,.145,"Equal sector weights; covered industries within each sector use 2023 hours weights.",fontsize=10,color="#50636D")
        fig.text(.09,.102,"Q1 = lowest AI adoption. Partial coverage; descriptive composites, not official BLS aggregates.",fontsize=10,color="#50636D")
        fig.text(.09,.059,"Sources: BLS annual detailed industries (August 2026); RPS via FRED.",fontsize=10,color="#50636D")
        for ext in ["png","svg","pdf"]:
            fig.savefig(out/NAMES[n]/f"productivity_index.{ext}",dpi=200,facecolor="white")
        plt.close(fig)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bls-xlsx",type=Path,default=ROOT/"data/bls_annual_productivity/labor-productivity-detailed-industries.xlsx")
    parser.add_argument("--rps-raw-dir",type=Path,default=ROOT/"data/rps_ai")
    parser.add_argument("--rps-quarter",default="2026-04-01")
    parser.add_argument("--end-year",type=int,default=2025)
    parser.add_argument("--outdir",type=Path,default=ROOT/"outputs/rps_ai_bls_annual_productivity")
    args=parser.parse_args()
    if args.end_year <= BASE:
        parser.error("--end-year must be after 2023")
    args.outdir.mkdir(parents=True,exist_ok=True)
    raw,details,industry_indexes,sector_indexes,max_diff=load_source(args.bls_xlsx,args.end_year)
    rps,quarter,wave=load_rps(args.rps_raw_dir,args.rps_quarter)
    covered=rps[rps.naics.isin(sector_indexes.columns)].copy().reset_index(drop=True)
    if set(covered.naics) != set(sector_indexes.columns):
        raise ValueError("BLS sector has no RPS match")
    covered["covered_sector_rank"]=np.arange(1,len(covered)+1)
    coverage=rps.copy()
    counts=details.groupby("rps_naics").size()
    coverage["selected_bls_industries"]=coverage.naics.map(counts).fillna(0).astype(int)
    coverage["coverage"]="Selected industries only"
    complete=set(details.loc[details.NAICS.isin(["21","22","42","44,45"]),"rps_naics"])
    coverage.loc[coverage.naics.isin(complete),"coverage"]="Published whole-sector series"
    coverage.loc[coverage.selected_bls_industries.eq(0),"coverage"]="No productivity series in this workbook"
    results,summaries,memberships=[],[],[]
    charts={}
    for n in [4,5,2]:
        name=NAMES[n]
        out=args.outdir/name
        out.mkdir(exist_ok=True)
        members=covered.copy()
        members["group"]=pd.qcut(members.covered_sector_rank,n,labels=False)+1
        members["group_label"]=members.group.map(lambda g:label(n,g))
        members["sector_group_weight"]=1/members.groupby("group").naics.transform("size")
        indexes=pd.DataFrame({g:sector_indexes[gm.naics].mean(axis=1) for g,gm in members.groupby("group")})
        indexes.index.name="year"
        assert indexes.notna().all().all() and np.allclose(indexes.loc[BASE],100)
        sizes=members.groupby("group").size()
        assert sizes.sum()==len(covered) and sizes.max()-sizes.min()<=1
        weights=details.merge(members[["naics","group","sector_group_weight","ai_adoption_pct"]],left_on="rps_naics",right_on="naics",validate="many_to_one")
        weights["industry_group_weight"]=weights.sector_hours_weight*weights.sector_group_weight
        assert np.allclose(weights.groupby("group").industry_group_weight.sum(),1)
        for g,gw in weights.groupby("group"):
            direct=industry_indexes[gw.NAICS].mul(gw.set_index("NAICS").industry_group_weight,axis=1).sum(axis=1)
            assert np.allclose(direct,indexes[g])
        summary=members.groupby("group").agg(sectors=("naics","size"),adoption_min_pct=("ai_adoption_pct","min"),adoption_max_pct=("ai_adoption_pct","max"))
        summary["bls_industries"]=weights.groupby("group").size()
        summary["latest_year"]=args.end_year
        summary["latest_index"]=indexes.iloc[-1]
        summary["growth_since_2023_pct"]=summary.latest_index-100
        summary["group_label"]=[label(n,g) for g in summary.index]
        summary["split"]=name
        summaries.append(summary.reset_index())
        long=indexes.rename_axis(columns="group").stack().rename("productivity_index").reset_index()
        long["split"]=name
        long["growth_since_2023_pct"]=long.productivity_index-100
        results.append(long)
        members["split"]=name
        memberships.append(members)
        indexes.rename(columns={g:label(n,g) for g in indexes}).to_csv(out/"productivity_index.csv",float_format="%.10f")
        members.to_csv(out/"sector_membership.csv",index=False)
        weights.to_csv(out/"industry_membership_and_weights.csv",index=False,float_format="%.10f")
        summary.to_csv(out/"summary.csv",float_format="%.10f")
        charts[n]=indexes
    summary=pd.concat(summaries,ignore_index=True)
    summary.to_csv(args.outdir/"summary.csv",index=False,float_format="%.10f")
    pd.concat(results,ignore_index=True).to_csv(args.outdir/"annual_productivity.csv",index=False,float_format="%.10f")
    pd.concat(memberships,ignore_index=True).to_csv(args.outdir/"sector_membership.csv",index=False)
    raw.to_csv(args.outdir/"bls_row_selection_audit.csv",index=False)
    details.to_csv(args.outdir/"selected_bls_industries.csv",index=False)
    coverage.to_csv(args.outdir/"sector_coverage.csv",index=False)
    sector_indexes.to_csv(args.outdir/"sector_productivity_index.csv",float_format="%.10f")
    industry_indexes.to_csv(args.outdir/"industry_productivity_index.csv",float_format="%.10f")
    checks={"base_year":BASE,"end_year":args.end_year,"covered_rps_sectors":len(covered),
            "selected_nonoverlapping_bls_industries":len(details),"all_years_complete":True,
            "base_indexes_equal_100":True,"weights_sum_to_one":True,"direct_group_calculation_matches":True,
            "max_index_implied_vs_published_bls_growth_difference_pp":max_diff,
            "sector_counts_by_split":{NAMES[n]:pd.qcut(covered.covered_sector_rank,n).value_counts(sort=False).tolist() for n in charts}}
    (args.outdir/"validation.json").write_text(json.dumps(checks,indent=2))
    sources=[{"path":str(p.resolve()),"sha256":hashlib.sha256(p.read_bytes()).hexdigest(),"url":url}
             for p,url in [(args.bls_xlsx,SOURCE_URL),(args.rps_raw_dir/"fred_series.json",TRACKER_URL)]]
    (args.outdir/"source_metadata.json").write_text(json.dumps({"created_at_utc":datetime.now(timezone.utc).isoformat(),
        "bls_release_date":"2026-08-26","rps_quarter":str(quarter.date()),"rps_wave":wave,"sources":sources},indent=2))
    lines=["# Annual productivity by RPS AI adoption","",
        f"BLS annual detailed-industry data, {BASE}–{args.end_year}; 2023 annual average = 100. RPS ranking: {wave}.","",
        "![All three splits](productivity_comparison.png)","",
        "## Method","",
        "The source is the user-specified BLS **labor productivity by detailed industries** workbook, Annual sheet, "
        "released August 26, 2026. Select Labor productivity, All workers, Index (2017=100). "
        "There are no quarterly observations: the baseline is the 2023 annual average, not 2023Q1. "
        "Lines join observed annual points and do not supply quarterly estimates.","",
        "Keep a balanced panel with positive productivity in every plotted year and positive 2023 hours levels. "
        "Among eligible rows, select the broadest available nonoverlapping NAICS groups. A complete parent replaces "
        "its children; where a parent is incomplete, eligible children can enter. Membership is constant over time. "
        "The row-selection audit records every included and excluded productivity row and its reason.","",
        "Rebase each industry: I(i,t) = 100 × LP(i,t) / LP(i,2023). Map industries to their broad RPS sector. "
        "Within a sector, average industry indexes using fixed 2023 hours-worked shares (Millions of hours from the same workbook). "
        "Rank the covered RPS sectors by their adoption point estimates and divide ranks with pandas.qcut. "
        "Within each group, give each sector equal weight. All group and industry weights are exported.","",
        "This estimates average productivity growth among covered industries. It is a weighted mean of normalized "
        "indexes, not total group output divided by total group hours. It is not an official BLS sector aggregate. "
        "The sectoral-output concept also differs from QILP value-added productivity.","",
        "## Coverage and interpretation","",
        f"The balanced panel contains {len(details)} BLS series mapped to {len(covered)} RPS sectors. "
        "Construction (23), management of companies (55), and education (61) have no productivity rows in this workbook. "
        "Quantile boundaries are therefore recomputed among the 15 covered sectors and differ from the previous 18-sector charts.","",
        "Service-sector coverage is often narrow: finance is commercial banking, real estate/rental is truck/trailer/RV rental, "
        "professional services is engineering, administrative services is travel arrangement, and health care is medical/diagnostic laboratories. "
        "Their RPS rates measure the broader sectors. These covered-industry composites must not be treated as representative "
        "estimates for all activities in those sectors. Many discontinued or unavailable rows lack 2024/2025 observations and are excluded "
        "from all plotted years. Sector coverage and selected NAICS codes are supplied separately.","",
        "RPS measures self-reported work-related generative AI use by employed adults aged 18–64. "
        "The adoption wave postdates the productivity outcomes. These retrospective comparisons do not identify a causal effect of AI. "
        "No confidence intervals are inferred from the available point estimates.","",
        "## Results","","| Split | Group | RPS sectors | BLS industries | Latest index | Growth since 2023 |",
        "|---|---|---:|---:|---:|---:|"]
    for r in summary.itertuples():
        lines.append(f"| {r.split} | {r.group_label} | {r.sectors} | {r.bls_industries} | {r.latest_index:.2f} | {r.growth_since_2023_pct:+.2f}% |")
    lines += ["","## Checks and sources","",
        f"Checks passed: annual panel completeness, nonoverlapping NAICS coverage, normalization to 100, weights summing to one, "
        f"and direct industry-to-group calculation. The largest difference between index-implied growth and the workbook's separately "
        f"published annual growth rates is {max_diff:.5f} percentage points, consistent with rounding.","",
        f"- [BLS detailed-industry workbook]({SOURCE_URL})",f"- [BLS productivity tables](https://www.bls.gov/productivity/tables/)",
        f"- [RPS GenAI Adoption Tracker]({TRACKER_URL})","- Individual FRED source URLs are in sector_membership.csv.","",
        "```bash","python3 scripts/rps_ai_bls_annual_productivity.py","```",""]
    (args.outdir/"analysis.md").write_text("\n".join(lines))
    make_charts(charts,args.outdir,wave,len(covered),len(details))
    print(summary[["split","group_label","sectors","bls_industries","latest_index","growth_since_2023_pct"]].to_string(index=False))
    print(json.dumps(checks,indent=2))


if __name__ == "__main__":
    main()
