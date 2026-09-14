#!/usr/bin/env python3
"""Chart CES payroll employment by BTOS, RPS and Ramp adoption groups.

Reproduce the archived adoption/employment vintage without network requests.
Quarterly charts use complete three-month averages and 2023 Q1 = 100.
A monthly companion retains observations in the incomplete final quarter.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages
from matplotlib.ticker import MultipleLocator
import numpy as np
import pandas as pd

from btos_ai_employment_quintiles import ROOT, BTOS_URL, adoption as btos_adoption, employment
from rps_ai_employment_quantiles import TRACKER_URL, adoption as rps_adoption
from ramp_ai_employment_quantiles import read_adoption as ramp_adoption

BASE = pd.Period("2023Q1", freq="Q")
GROUPS = {4: "quartiles", 5: "quintiles", 2: "halves"}
COLORS = {2: ["#356A8A", "#81559C"],
          4: ["#356A8A", "#33958F", "#CC713A", "#81559C"],
          5: ["#356A8A", "#33958F", "#AE9029", "#CC713A", "#81559C"]}
INK, MUTED = "#18313F", "#50636D"


def load_sources():
    btos, timing = btos_adoption(ROOT / "data/btos_ai/Sector.xlsx", "202618", 4)
    rps, _, _, wave = rps_adoption(ROOT / "data/rps_ai", "2026-04-01")
    ramp, month = ramp_adoption(ROOT / "data/ramp_ai/chart_dataset.csv", "2026-04-01")
    return {
        "btos": {"name": "Census BTOS", "members": btos, "date": "Aug 10–23, 2026",
                 "measure": "Businesses reporting AI use in any business function in the preceding two weeks",
                 "snapshot": timing, "source_url": BTOS_URL,
                 "file": ROOT / "data/btos_ai/Sector.xlsx"},
        "rps": {"name": "RPS", "members": rps, "date": "May 2026",
                "measure": "Employed adults aged 18–64 reporting generative AI use for their job",
                "snapshot": {"wave": wave, "fred_quarter_date": "2026-04-01"},
                "source_url": TRACKER_URL, "file": ROOT / "data/rps_ai/fred_series.json"},
        "ramp": {"name": "Ramp", "members": ramp, "date": "April 2026",
                 "measure": "Businesses with paid AI adoption observed in Ramp transactions",
                 "snapshot": {"month": month.date().isoformat(), "coverage": "Complete 18-sector download"},
                 "source_url": "https://datawrapper.dwcdn.net/wQR5S/23/dataset.csv",
                 "file": ROOT / "data/ramp_ai/chart_dataset.csv"},
    }


def label(group, count, compact=False):
    if count == 2:
        return "Lower half" if group == 1 else "Higher half"
    return f"Q{group}" + ("" if compact else " · Lowest AI" if group == 1 else " · Highest AI" if group == count else "")


def period_label(period):
    return f"{period.year} Q{period.quarter}"


def plot_panel(ax, indexes, count, limits, compact=False, monthly=False):
    dates = indexes.index if monthly else indexes.index.to_timestamp()
    for group in indexes:
        color = COLORS[count][group - 1]
        legend = label(group, count, compact)
        if compact:
            legend += f"  {indexes[group].iloc[-1]:.1f}"
        ax.plot(dates, indexes[group], color=color, lw=2.4, label=legend)
        ax.scatter(dates[-1], indexes[group].iloc[-1], s=20, color=color, zorder=4, clip_on=False)
    ax.axhline(100, color="#87949B", lw=.8, ls=(0, (3, 3)))
    ticks = [pd.Timestamp(year, 1, 1) for year in range(2023, dates[-1].year + 1)]
    ax.set_xticks(ticks, [f"{t.year}" if monthly else f"{t.year} Q1" for t in ticks], fontsize=9 if compact else 11)
    ax.set_xlim(dates[0], dates[-1])
    ax.set_ylim(*limits)
    ax.yaxis.set_major_locator(MultipleLocator(2))
    ax.grid(axis="y", color="#E2E9ED", linewidth=.8)
    ax.set_axisbelow(True)
    for side in ["top", "right", "left"]:
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color("#C6D0D6")
    ax.tick_params(length=0, pad=8, colors=MUTED)
    ax.legend(loc="upper left", bbox_to_anchor=(-.025, -.15), ncol=count,
              frameon=False, fontsize=8.8 if compact else 10, handlelength=1.6,
              columnspacing=1.3, borderaxespad=0)
    if not compact:
        endpoints = indexes.iloc[-1].sort_values()
        positions = endpoints.to_numpy().copy()
        # Reserve enough vertical space for each two-line endpoint annotation.
        axis_height_points = ax.figure.get_figheight() * 72 * ax.get_position().height
        gap = (limits[1] - limits[0]) * 30 / axis_height_points
        for i in range(1, len(positions)):
            positions[i] = max(positions[i], positions[i - 1] + gap)
        positions -= (positions - endpoints.to_numpy()).mean()
        positions += max(0, limits[0] + .5 - positions.min())
        positions -= max(0, positions.max() - limits[1] + .5)
        for (group, value), y in zip(endpoints.items(), positions):
            color = COLORS[count][group - 1]
            ax.annotate(f"{label(group, count, True)}  {value:.1f}\n{value - 100:+.1f}% since 2023 Q1",
                        xy=(dates[-1], value), xytext=(dates[-1] + pd.Timedelta(days=35), y),
                        textcoords="data", color=color, fontsize=10.5, va="center",
                        annotation_clip=False, arrowprops={"arrowstyle": "-", "color": color, "lw": .7})


def overview(charts, sources, limits, monthly=False):
    fig, axes = plt.subplots(3, 3, figsize=(20, 15), facecolor="white")
    fig.subplots_adjust(left=.055, right=.973, top=.835, bottom=.143, hspace=.62, wspace=.16)
    last = next(iter(charts.values()))[0].index[-1]
    endpoint = last.strftime("%B %Y") if monthly else period_label(last)
    fig.text(.055, .966, "Payroll employment since 2023 Q1, by AI adoption", fontsize=25, weight="bold", color=INK)
    frequency = "Monthly levels" if monthly else "Quarterly averages"
    fig.text(.055, .931, f"{frequency} · Seasonally adjusted · 2023 Q1 average = 100 · through {endpoint}", fontsize=15, color=MUTED)
    fig.text(.055, .899, "Same 18 private industries and BLS CES data; fixed adoption rankings and a common vertical scale.", fontsize=12, color=MUTED)
    for row, (source, spec) in enumerate(sources.items()):
        for col, count in enumerate(GROUPS):
            ax = axes[row, col]
            indexes, sizes = charts[(source, count)]
            ax.set_title(f"{spec['name']} · {GROUPS[count].title()}", fontsize=14, color=INK, loc="left", pad=27, weight="bold")
            ax.text(0, 1.032, f"{spec['date']} ranking · {sizes} industries", transform=ax.transAxes, fontsize=10, color=MUTED)
            plot_panel(ax, indexes, count, limits, compact=True, monthly=monthly)
    fig.text(.055, .078, f"Q1 = lowest adoption; Q4 or Q5 = highest. Legend values are employment indexes in {endpoint}.", fontsize=11.5, color=MUTED)
    note = "Monthly companion includes the incomplete final quarter; latest payroll observations are preliminary." if monthly else "Each observation averages three months of summed payroll jobs. Incomplete quarters are excluded; no employment values are imputed."
    fig.text(.055, .053, note, fontsize=10.5, color=MUTED)
    fig.text(.055, .028, "Adoption: Census BTOS; Bick–Blandin–Deming RPS via St. Louis Fed/FRED; Ramp. Different measures and dates; descriptive comparisons.", fontsize=10.5, color=MUTED)
    return fig


def individual_chart(indexes, count, spec, sizes, limits):
    fig, ax = plt.subplots(figsize=(13, 8), facecolor="white")
    fig.subplots_adjust(left=.08, right=.79, top=.75, bottom=.28)
    fig.text(.08, .943, f"Payroll employment by {spec['name']} AI adoption {GROUPS[count]}", fontsize=20, fontweight="bold", color=INK)
    fig.text(.08, .892, f"Seasonally adjusted quarterly averages · 2023 Q1 = 100 · through {period_label(indexes.index[-1])}", fontsize=12.5, color=MUTED)
    fig.text(.08, .846, f"Fixed {spec['date']} adoption ranking; {sizes} industries from lowest to highest AI use", fontsize=11, color=MUTED)
    plot_panel(ax, indexes, count, limits)
    fig.text(.08, .135, "Sum payroll jobs within each fixed group; average the three months; divide by the 2023 Q1 group average.", fontsize=9.7, color=MUTED)
    fig.text(.08, .099, "Same 18 private nonfarm sectors in every chart. Groups divide industry counts, not numbers of jobs.", fontsize=9.7, color=MUTED)
    adoption_caption = "Bick, Blandin & Deming, RPS via St. Louis Fed/FRED" if spec["name"] == "RPS" else spec["name"]
    fig.text(.08, .063, f"Sources: BLS CES; adoption: {adoption_caption}. Complete quarters only; no imputation.", fontsize=9.7, color=MUTED)
    fig.text(.08, .027, "Recent adoption rankings are applied retrospectively; these comparisons do not identify a causal effect of AI.", fontsize=9.7, color=MUTED)
    return fig


def write_report(out, sources, summary, checks):
    lines = ["# Payroll employment by three AI adoption measures", "",
             "Nine charts compare quartiles, quintiles and halves for all three sources, following the earlier productivity comparison in this repository.", "",
             f"The main chart runs from 2023 Q1 through {period_label(pd.Period(checks['last_quarter']))}. All indexes equal 100 in 2023 Q1. The monthly companion runs through {checks['latest_month']} and uses the same quarterly-average denominator.", "",
             "![Quarterly comparison](comparison_overview.png)", "", "## Adoption snapshots", "",
             "| Source | Fixed ranking snapshot | Measure |", "|---|---|---|"]
    for spec in sources.values():
        lines.append(f"| [{spec['name']}]({spec['source_url']}) | {spec['date']} | {spec['measure']} |")
    lines += ["", "RPS is the Bick–Blandin–Deming Real-Time Population Survey, distributed through the GenAI Adoption Tracker and St. Louis Fed/FRED. It is not a Chicago Fed survey. Chicago Fed QILP is not an input to these payroll employment charts.", "",
              "BTOS uses period 202618, released September 10, 2026. It asks about AI use in any business function. RPS uses the May 2026 wave, represented by FRED's 2026 Q2 timestamp (April 1). Ramp uses the archived version-23 full-sector download for April 2026, retaining the same 18 sectors. These are fixed archived ranking snapshots, not synchronized survey dates.", "",
              "## Employment and aggregation", "",
              "Employment comes directly from the archived [BLS CES API](https://api.bls.gov/publicAPI/v2/timeseries/data/) response. The 18 sector series count seasonally adjusted private payroll jobs in thousands. They exclude agriculture/forestry/fishing, logging, and government. Education and healthcare use private employment. Self-employment is outside this payroll measure. The complete sector-to-CES mapping is in `industry_monthly_employment.csv` and the BLS titles are in `bls_series_catalog.csv`.", "",
              "Within each source, sort sectors by adoption percentage, breaking ties by NAICS code, and apply pandas.qcut to ordinal ranks. Quartiles contain 5/4/4/5 industries, quintiles 4/3/4/3/4, and halves 9/9. These are approximately equal numbers of industries, not equal numbers of jobs or businesses. Membership remains fixed throughout each employment series.", "",
              "For group g, let E[g,m] be the sum of its constituent CES sector employment levels in month m. Quarterly employment E[g,q] is the arithmetic mean of E[g,m] over the three months of q. The quarterly index is 100 × E[g,q] / E[g,2023Q1]. This is equivalent to weighting sector employment indexes by their 2023 Q1 employment shares; it is not an equal-weight average of industry growth rates. Quarterly levels are averages, not the sum of three monthly job counts.", "",
              f"The source panel contains {checks['months']} complete months from January 2023 through {checks['latest_month']}. Only quarters with all three months are plotted in the main chart. The excluded partial quarters are {checks['excluded_partial_quarters']}. No employment observations are filled, interpolated or forecast. In particular, this CES pipeline does not use the CPS interpolation from the productivity analysis. Preliminary flags from the source are retained in the data files.", "",
              "The monthly companion uses 100 × E[g,m] / E[g,2023Q1]. Individual January–March 2023 monthly values need not equal 100; their mean equals 100. Existing monthly charts in the repository instead use January 2023 = 100. The underlying group employment levels and memberships are unchanged.", "",
              "## Interpretation", "",
              "BTOS measures business AI use, RPS measures workers' self-reported generative AI use, and Ramp measures paid adoption among its customers. Their dates and populations differ. Employment covers whole private sectors, not only respondents or adopting firms. RPS industry adoption can include government workers while the employment series here are private. Later rankings are applied retrospectively. Differences between lines reflect industry composition and other factors as well as possible AI effects; they do not establish causality. Adoption sampling uncertainty is not converted into confidence bands.", "",
              "## Latest complete quarter", "", "| Source | Split | Group | Industries | Payroll jobs (millions) | Index | Growth since 2023 Q1 |", "|---|---|---|---:|---:|---:|---:|"]
    for r in summary.itertuples():
        lines.append(f"| {sources[r.source]['name']} | {GROUPS[r.groups]} | {r.label} | {r.industry_count} | {r.latest_employment_thousands / 1000:.3f} | {r.latest_employment_index:.2f} | {r.growth_since_2023q1_pct:+.2f}% |")
    lines += ["", "## Validation and reproduction", "",
              "Validation checks complete industry/month/quarter coverage, fixed membership, base normalization, equality between group sums and constituent sector totals, agreement with the employment-weighted sector index formula, and exact reproduction of existing monthly group levels where available. Sector totals plus excluded logging reconcile to published total private within " + f"{checks['source_employment_checks']['max_sector_plus_logging_reconciliation_difference_thousands']:.1f} thousand jobs (published rounding).", "",
              "Input files and SHA-256 hashes are recorded in `source_metadata.json`. All results use the saved source vintage without downloads. Reproduce from the repository root:", "", "```bash", "python3 scripts/compare_ai_adoption_employment.py", "```", "",
              "The output includes a nine-panel overview, nine individual charts (PNG/SVG/PDF), a combined PDF, a monthly overview, quarterly and monthly chart data, industry assignments, baseline employment weights, source metadata, validation results, and a ZIP of all artifacts.", ""]
    (out / "analysis.md").write_text("\n".join(lines))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--outdir", type=Path, default=ROOT / "outputs/ai_adoption_employment_comparison")
    args = parser.parse_args()
    out = args.outdir.resolve()
    out.mkdir(parents=True, exist_ok=True)
    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 10, "svg.fonttype": "none"})
    sources = load_sources()
    bls_path = ROOT / "data/btos_ai/bls_ces_response.json"
    seed = sources["btos"]["members"][["naics", "industry", "series_id", "quartile"]]
    industry, _, _, catalog, source_checks = employment(bls_path, seed)
    industry = industry.drop(columns="quartile").sort_values(["date", "naics"])
    industry["quarter"] = industry.date.dt.to_period("Q")
    industry.to_csv(out / "industry_monthly_employment.csv", index=False)
    catalog.to_csv(out / "bls_series_catalog.csv", index=False)
    month_counts = industry.groupby("quarter").date.nunique()
    complete = month_counts.index[month_counts.eq(3)]
    quarters = pd.period_range(BASE, complete.max(), freq="Q")
    assert complete.equals(quarters), "Missing complete quarters"
    assert (month_counts.loc[~month_counts.eq(3)].index > quarters[-1]).all()
    sector_q = industry[industry.quarter.isin(quarters)].groupby(["quarter", "naics"]).employment_thousands.mean().unstack()
    sector_base = sector_q.loc[BASE]
    sector_indexes = 100 * sector_q / sector_base
    charts, monthly_charts, quarterly_rows, monthly_rows, memberships, summaries = {}, {}, [], [], [], []
    max_weight_error, max_existing_error = 0., 0.
    existing_comparisons = 0
    for source, spec in sources.items():
        members = spec["members"].drop(columns=["half", "quartile", "quintile"], errors="ignore")
        members = members.sort_values(["ai_adoption_pct", "naics"]).reset_index(drop=True)
        assert len(members) == 18 and set(members.naics) == set(industry.naics)
        assert members.ai_adoption_pct.between(0, 100).all()
        assert members.series_id.is_unique and members.naics.is_unique
        assert np.array_equal(members.adoption_rank, np.arange(1, 19))
        for count, plural in GROUPS.items():
            dest = out / source / plural
            dest.mkdir(parents=True, exist_ok=True)
            m = members.copy()
            m["group"] = pd.qcut(m.adoption_rank, count, labels=False) + 1
            m["source"], m["groups"], m["ranking_date"] = source, count, spec["date"]
            m["label"] = m.group.map(lambda g: label(g, count))
            m["base_employment_thousands"] = m.naics.map(sector_base)
            m["base_employment_weight"] = m.base_employment_thousands / m.groupby("group").base_employment_thousands.transform("sum")
            sizes = m.groupby("group").size()
            assert sizes.sum() == 18 and sizes.max() - sizes.min() <= 1
            assert np.allclose(m.groupby("group").base_employment_weight.sum(), 1)
            m.to_csv(dest / "industry_membership.csv", index=False)
            memberships.append(m)
            joined = industry.merge(m[["naics", "group"]], on="naics", validate="many_to_one")
            monthly = joined.groupby(["date", "group"], as_index=False).agg(
                employment_thousands=("employment_thousands", "sum"), preliminary=("preliminary", "any"),
                industry_count=("naics", "nunique"))
            monthly["quarter"] = monthly.date.dt.to_period("Q")
            quarterly = monthly[monthly.quarter.isin(quarters)].groupby(["quarter", "group"], as_index=False).agg(
                employment_thousands=("employment_thousands", "mean"), preliminary=("preliminary", "any"),
                industry_count=("industry_count", "first"), observed_months=("date", "nunique"))
            assert quarterly.observed_months.eq(3).all()
            levels = quarterly.pivot(index="quarter", columns="group", values="employment_thousands")
            assert levels.index.equals(quarters) and levels.notna().all().all()
            assert np.allclose(levels.sum(axis=1), sector_q.sum(axis=1), atol=1e-8, rtol=0)
            assert np.allclose(monthly.groupby("date").employment_thousands.sum(), industry.groupby("date").employment_thousands.sum(), atol=1e-8, rtol=0)
            base = levels.loc[BASE]
            for frame in [quarterly, monthly]:
                assert (frame.industry_count == frame.group.map(sizes)).all()
                frame["base_employment_thousands"] = frame.group.map(base)
                frame["employment_index"] = 100 * frame.employment_thousands / frame.base_employment_thousands
                frame["growth_since_2023q1_pct"] = frame.employment_index - 100
                frame["source"], frame["groups"], frame["ranking_date"] = source, count, spec["date"]
                frame["label"] = frame.group.map(lambda g: label(g, count))
            indexes = 100 * levels / base
            assert np.allclose(indexes.loc[BASE], 100)
            assert np.allclose(monthly[monthly.quarter.eq(BASE)].groupby("group").employment_index.mean(), 100)
            for group, subset in m.groupby("group"):
                weighted = sector_indexes[subset.naics].mul(subset.set_index("naics").base_employment_weight, axis=1).sum(axis=1)
                max_weight_error = max(max_weight_error, float((weighted - indexes[group]).abs().max()))
                summaries.append({"source": source, "groups": count, "group": int(group), "label": label(group, count),
                    "industry_count": len(subset), "ai_min_pct": subset.ai_adoption_pct.min(), "ai_max_pct": subset.ai_adoption_pct.max(),
                    "ranking_date": spec["date"], "latest_quarter": str(quarters[-1]), "base_employment_thousands": base[group],
                    "latest_employment_thousands": levels[group].iloc[-1], "latest_employment_index": indexes[group].iloc[-1],
                    "growth_since_2023q1_pct": indexes[group].iloc[-1] - 100})
            group_name = {2: "half", 4: "quartile", 5: "quintile"}[count]
            old_path = ROOT / f"outputs/{source}_ai_{plural}/{group_name}_monthly_employment.csv"
            if old_path.exists():
                old = pd.read_csv(old_path, parse_dates=["date"]).rename(columns={group_name: "group"})
                check = old.merge(monthly, on=["date", "group"], validate="one_to_one", suffixes=("_old", "_new"))
                assert len(check) == len(old) == len(monthly)
                max_existing_error = max(max_existing_error, float((check.employment_thousands_old - check.employment_thousands_new).abs().max()))
                existing_comparisons += 1
            quarterly.to_csv(dest / "quarterly_employment.csv", index=False, float_format="%.10f")
            indexes.rename(columns=lambda g: label(g, count)).to_csv(dest / "employment_index.csv", float_format="%.10f")
            charts[(source, count)] = indexes, "/".join(map(str, sizes))
            monthly_charts[(source, count)] = monthly.pivot(index="date", columns="group", values="employment_index"), charts[(source, count)][1]
            quarterly_rows.append(quarterly)
            monthly_rows.append(monthly)
    combined = pd.concat(quarterly_rows, ignore_index=True)
    combined_monthly = pd.concat(monthly_rows, ignore_index=True)
    assert len(combined) == len(quarters) * 3 * sum(GROUPS)
    assert len(combined_monthly) == source_checks["months"] * 3 * sum(GROUPS)
    assert combined.employment_index.notna().all() and combined_monthly.employment_index.notna().all()
    assert max_weight_error < 1e-9 and max_existing_error < 1e-6
    combined.to_csv(out / "all_chart_data.csv", index=False, float_format="%.10f")
    combined_monthly.to_csv(out / "monthly_chart_data.csv", index=False, float_format="%.10f")
    pd.concat(memberships, ignore_index=True).to_csv(out / "all_industry_memberships.csv", index=False)
    summary = pd.DataFrame(summaries)
    summary.to_csv(out / "endpoint_summary.csv", index=False, float_format="%.6f")
    limits = [min(98, 2 * np.floor(combined_monthly.employment_index.min() / 2)),
              2 * np.ceil(combined_monthly.employment_index.max() / 2) + 2]
    with PdfPages(out / "all_nine_charts.pdf") as pdf:
        board = overview(charts, sources, limits)
        for ext in ["png", "svg", "pdf"]:
            board.savefig(out / f"comparison_overview.{ext}", dpi=180, facecolor="white")
        pdf.savefig(board)
        plt.close(board)
        for (source, count), (indexes, sizes) in charts.items():
            fig = individual_chart(indexes, count, sources[source], sizes, limits)
            for ext in ["png", "svg", "pdf"]:
                fig.savefig(out / source / GROUPS[count] / f"employment_index.{ext}", dpi=180, facecolor="white")
            pdf.savefig(fig)
            plt.close(fig)
    monthly_board = overview(monthly_charts, sources, limits, monthly=True)
    for ext in ["png", "svg", "pdf"]:
        monthly_board.savefig(out / f"monthly_comparison_overview.{ext}", dpi=180, facecolor="white")
    plt.close(monthly_board)
    checks = {"passed": True, "charts": 9, "series": 33, "industries_per_chart": 18,
              "first_quarter": str(BASE), "last_quarter": str(quarters[-1]), "quarters_per_series": len(quarters),
              "data_rows": len(combined), "months": source_checks["months"], "latest_month": str(industry.date.max().date()),
              "excluded_partial_quarters": {str(q): int(n) for q, n in month_counts.items() if n < 3},
              "missing_chart_values": 0, "employment_values_imputed": 0, "base_indexes_equal_100": True,
              "common_y_axis": limits, "max_employment_weighted_formula_error": max_weight_error,
              "existing_monthly_groupings_compared": existing_comparisons, "max_existing_monthly_level_difference_thousands": max_existing_error,
              "group_sizes": {name: pd.Series(pd.qcut(range(18), n, labels=False)).value_counts().sort_index().tolist() for n, name in GROUPS.items()},
              "source_employment_checks": source_checks}
    (out / "validation.json").write_text(json.dumps(checks, indent=2))
    files = [bls_path, Path(__file__)] + [spec["file"] for spec in sources.values()]
    files += [Path(__file__).with_name(name) for name in ["btos_ai_employment_quintiles.py", "rps_ai_employment_quantiles.py", "ramp_ai_employment_quantiles.py", "reproduce_ces_monthly_employment_index.py", "bls_api.py"]]
    metadata = {"built_at_utc": datetime.now(timezone.utc).isoformat(), "employment_source_url": "https://api.bls.gov/publicAPI/v2/timeseries/data/",
                "base": "2023 Q1 average = 100", "frequency": "Complete-quarter average; monthly companion uses the same denominator",
                "adoption": {key: {k: v for k, v in spec.items() if k not in ["members", "file"]} for key, spec in sources.items()},
                "files": [{"path": str(f.relative_to(ROOT)), "sha256": hashlib.sha256(f.read_bytes()).hexdigest()} for f in files]}
    (out / "source_metadata.json").write_text(json.dumps(metadata, indent=2))
    write_report(out, sources, summary, checks)
    with ZipFile(out / "charts_and_data.zip", "w", ZIP_DEFLATED) as archive:
        for path in sorted(out.rglob("*")):
            if path.is_file() and path.suffix != ".zip":
                archive.write(path, path.relative_to(out))
    print(summary[summary.groups.eq(2)][["source", "label", "latest_employment_index", "growth_since_2023q1_pct"]].round(3).to_string(index=False))
    print(json.dumps(checks, indent=2))
    print(f"Artifacts: {out}")


if __name__ == "__main__":
    main()
