#!/usr/bin/env python3
"""Reproduce nine productivity charts using three archived adoption rankings.

Uses the independent BEA/CES/CPS productivity panel, including the October 2025
CPS midpoint treatment. No QILP series or new employment sources are introduced.
"""
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages
from matplotlib.ticker import MultipleLocator
import numpy as np
import pandas as pd

from analyze_independent_productivity import aggregate, BASE, COLORS
from independent_productivity_inputs import ROOT, OUT as PRODUCTIVITY_OUT
from btos_ai_employment_quintiles import adoption as btos_adoption, BTOS_URL
from rps_ai_employment_quantiles import adoption as rps_adoption, TRACKER_URL
from ramp_ai_employment_quantiles import read_adoption as ramp_adoption

OUT = ROOT / "outputs/ai_adoption_productivity_comparison_01a0a142"
GROUPS = {4: "quartiles", 5: "quintiles", 2: "halves"}
SOURCE_ORDER = ["btos", "rps", "ramp"]
INK, MUTED = "#18313F", "#50636D"


def load_sources():
    btos, timing = btos_adoption(ROOT/"data/btos_ai/Sector.xlsx", "202618", 4)
    rps, _, _, wave = rps_adoption(ROOT/"data/rps_ai", "2026-04-01")
    ramp, month = ramp_adoption(ROOT/"data/ramp_ai/chart_dataset.csv", "2026-04-01")
    return {
        "btos": {"name": "Census BTOS", "members": btos, "date": "Aug 10–23, 2026",
                 "measure": "Businesses reporting AI use in any business function during the preceding two weeks",
                 "snapshot": timing, "source_url": BTOS_URL,
                 "files": [ROOT/"data/btos_ai/Sector.xlsx"]},
        "rps": {"name": "RPS", "members": rps, "date": "May 2026",
                "measure": "Employed adults aged 18–64 reporting generative AI use for work",
                "snapshot": {"wave": wave, "fred_quarter_date": "2026-04-01"},
                "source_url": TRACKER_URL, "files": [ROOT/"data/rps_ai/fred_series.json"]},
        "ramp": {"name": "Ramp", "members": ramp, "date": "April 2026",
                 "measure": "Businesses with observed paid AI adoption in Ramp transaction data",
                 "snapshot": {"month": month.date().isoformat(), "coverage": "Complete 18-sector public chart download"},
                 "source_url": "https://datawrapper.dwcdn.net/wQR5S/23/dataset.csv",
                 "files": [ROOT/"data/ramp_ai/chart_dataset.csv"]},
    }


def group_label(group, count, short=False):
    if count == 2:
        return "Lower AI" if group == 1 else "Higher AI"
    if short:
        return f"Q{group}"
    return f"Q{group}" + (" (lowest AI)" if group == 1 else " (highest AI)" if group == count else "")


def plot_panel(ax, indexes, count, limits, compact=False):
    dates = indexes.index.to_timestamp()
    for i, group in enumerate(indexes):
        color = COLORS[count][i]
        label = group_label(group, count, short=compact)
        if compact:
            label += f"  {indexes[group].iloc[-1]:.1f}"
        ax.plot(dates, indexes[group], color=color, lw=2.4, label=label)
        ax.scatter(dates[-1], indexes[group].iloc[-1], s=20, color=color, zorder=4, clip_on=False)
    ax.axhline(100, color="#87949B", lw=.8, ls=(0, (3, 3)))
    ticks = pd.PeriodIndex([f"{year}Q1" for year in range(2023, indexes.index[-1].year+1)], freq="Q")
    ax.set_xticks(ticks.to_timestamp(), [f"{q.year} Q1" for q in ticks], fontsize=9 if compact else 11)
    ax.set_xlim(dates[0], dates[-1])
    ax.set_ylim(*limits)
    ax.yaxis.set_major_locator(MultipleLocator(4 if limits[1]-limits[0] > 20 else 2))
    ax.grid(axis="y", color="#E2E9ED", linewidth=.8)
    ax.set_axisbelow(True)
    for side in ["top", "right", "left"]:
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color("#C6D0D6")
    ax.tick_params(length=0, pad=8, colors=MUTED)
    ax.legend(loc="upper left", bbox_to_anchor=(-.025, -.15), ncol=3 if compact else count,
              frameon=False, fontsize=8.8 if compact else 10, handlelength=1.6,
              columnspacing=1.3, borderaxespad=0)
    if not compact:
        endpoint = indexes.iloc[-1].sort_values()
        ypos = endpoint.to_numpy().copy()
        for i in range(1, len(ypos)):
            ypos[i] = max(ypos[i], ypos[i-1]+1.35)
        ypos -= (ypos-endpoint.to_numpy()).mean()
        for (group, value), y in zip(endpoint.items(), ypos):
            color = COLORS[count][group-1]
            ax.annotate(f"{group_label(group, count, True)}  {value:.1f}\n{value-100:+.1f}% since 2023 Q1",
                        xy=(dates[-1], value), xytext=(dates[-1]+pd.Timedelta(days=30), y),
                        textcoords="data", color=color, fontsize=10.5, va="center",
                        annotation_clip=False, arrowprops={"arrowstyle": "-", "color": color, "lw": .7})


def individual_chart(indexes, count, spec, sizes, limits):
    fig, ax = plt.subplots(figsize=(13, 8), facecolor="white")
    fig.subplots_adjust(left=.08, right=.79, top=.75, bottom=.28)
    fig.text(.08, .943, f"Productivity by {spec['name']} AI adoption {GROUPS[count]}",
             fontsize=21, fontweight="bold", color=INK)
    fig.text(.08, .892, "Independent industry output per hour · 2023 Q1 = 100", fontsize=13, color=MUTED)
    fig.text(.08, .846, f"Fixed {spec['date']} adoption ranking; {sizes} industries from lowest to highest AI use",
             fontsize=11, color=MUTED)
    plot_panel(ax, indexes, count, limits)
    fig.text(.08, .135, "Output uses adjacent-quarter nominal-value-added weights; hours are summed across industries.", fontsize=9.7, color=MUTED)
    fig.text(.08, .099, "Hours: independent CES + CPS construction, X-13 adjusted. October 2025 CPS inputs are interpolated.", fontsize=9.7, color=MUTED)
    adoption_caption = "Bick, Blandin & Deming, RPS via FRED" if spec["name"] == "RPS" else spec["name"]
    fig.text(.08, .063, f"Sources: BEA, BLS CES, Census CPS; adoption: {adoption_caption}. Same 18 sectors in all comparisons.", fontsize=9.7, color=MUTED)
    fig.text(.08, .027, "Retrospective industry comparisons; these rankings do not identify a causal effect of AI.", fontsize=9.7, color=MUTED)
    return fig


def overview(charts, sources, limits):
    fig, axes = plt.subplots(3, 3, figsize=(20, 15), facecolor="white")
    fig.subplots_adjust(left=.055, right=.973, top=.835, bottom=.143, hspace=.62, wspace=.16)
    fig.text(.055, .966, "Productivity since 2023 Q1, across three AI adoption measures", fontsize=25, weight="bold", color=INK)
    fig.text(.055, .931, "Independent industry output per hour · 2023 Q1 = 100 · through 2026 Q1", fontsize=15, color=MUTED)
    fig.text(.055, .899, "Same 18 industries and productivity data; fixed adoption rankings and a common vertical scale.", fontsize=12, color=MUTED)
    for row, source in enumerate(SOURCE_ORDER):
        spec = sources[source]
        for col, count in enumerate(GROUPS):
            ax = axes[row, col]
            indexes, sizes = charts[(source, count)]
            ax.set_title(f"{spec['name']} · {GROUPS[count].title()}", fontsize=14, color=INK, loc="left", pad=27, weight="bold")
            ax.text(0, 1.032, f"{spec['date']} ranking · {sizes} industries", transform=ax.transAxes, fontsize=10, color=MUTED)
            plot_panel(ax, indexes, count, limits, compact=True)
    fig.text(.055, .078, "Q1 = lowest adoption; Q4 or Q5 = highest. Legend values are productivity indexes in 2026 Q1.", fontsize=11.5, color=MUTED)
    fig.text(.055, .053, "BEA output; independently constructed CES + CPS hours, X-13 adjusted. October 2025 CPS inputs use September–November midpoints.", fontsize=10.5, color=MUTED)
    fig.text(.055, .028, "Adoption: Census BTOS; Bick–Blandin–Deming RPS via FRED; Ramp. Definitions and ranking dates differ. Comparisons are descriptive.", fontsize=10.5, color=MUTED)
    return fig


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 10, "svg.fonttype": "none"})
    sources = load_sources()
    input_path = PRODUCTIVITY_OUT/"quarterly_industry_productivity.csv"
    panel = pd.read_csv(input_path, dtype={"naics": str})
    panel["quarter"] = pd.PeriodIndex(panel.quarter, freq="Q")
    assert set(panel.variant) == {"all_workers"}
    assert panel.naics.nunique() == 18
    latest = panel.quarter.max()
    assert str(latest) == "2026Q1", "Review date captions when refreshing productivity"
    quarters = pd.period_range(BASE, latest, freq="Q")
    charts, all_groups, memberships, summary = {}, [], [], []
    for source, spec in sources.items():
        members = spec["members"].sort_values(["ai_adoption_pct", "naics"]).reset_index(drop=True)
        assert set(members.naics) == set(panel.naics)
        assert members.ai_adoption_pct.notna().all() and members.ai_adoption_pct.between(0, 100).all()
        for count in GROUPS:
            dest = OUT/source/GROUPS[count]
            dest.mkdir(parents=True, exist_ok=True)
            m = members[["naics", "industry", "ai_adoption_pct", "adoption_rank"]].copy()
            m["group"] = pd.qcut(m.adoption_rank, count, labels=False)+1
            m["source"], m["groups"], m["ranking_date"] = source, count, spec["date"]
            m["adoption_source_url"] = spec["source_url"]
            sizes = m.groupby("group").size()
            assert sizes.sum() == 18 and sizes.max()-sizes.min() <= 1
            m.to_csv(dest/"industry_membership.csv", index=False)
            memberships.append(m)
            local = []
            for group, subset in m.groupby("group"):
                result, _ = aggregate(panel[panel.naics.isin(subset.naics)])
                result = result.loc[BASE:].copy()
                assert result.index.equals(quarters) and result.notna().all().all()
                result["source"], result["groups"], result["group"] = source, count, group
                result["industry_count"] = len(subset)
                result["ranking_date"] = spec["date"]
                result["growth_since_2023q1_pct"] = result.productivity_index-100
                result["quarter_contains_imputed_cps_month"] = result.index == pd.Period("2025Q4")
                result["adoption_source_url"] = spec["source_url"]
                local.append(result.reset_index())
                summary.append({"source": source, "groups": count, "group": group,
                    "label": group_label(group, count), "industry_count": len(subset),
                    "ai_min_pct": subset.ai_adoption_pct.min(), "ai_max_pct": subset.ai_adoption_pct.max(),
                    "ranking_date": spec["date"], "latest_quarter": str(latest),
                    "latest_productivity_index": result.productivity_index.iloc[-1],
                    "growth_since_2023q1_pct": result.productivity_index.iloc[-1]-100})
            local = pd.concat(local, ignore_index=True)
            indexes = local.pivot(index="quarter", columns="group", values="productivity_index")
            assert np.allclose(indexes.loc[BASE], 100)
            local.to_csv(dest/"quarterly_productivity.csv", index=False, float_format="%.10f")
            indexes.rename(columns={g: group_label(g, count) for g in indexes}).to_csv(dest/"productivity_index.csv", float_format="%.10f")
            charts[(source, count)] = indexes, "/".join(map(str, sizes))
            all_groups.append(local)
    combined = pd.concat(all_groups, ignore_index=True)
    combined.to_csv(OUT/"all_chart_data.csv", index=False, float_format="%.10f")
    pd.concat(memberships, ignore_index=True).to_csv(OUT/"all_industry_memberships.csv", index=False)
    totals = pd.DataFrame(summary)
    totals.to_csv(OUT/"endpoint_summary.csv", index=False, float_format="%.6f")
    assert len(combined) == len(quarters)*3*sum(GROUPS)
    lower = min(98, 2*np.floor(combined.productivity_index.min()/2))
    upper = 2*np.ceil(combined.productivity_index.max()/2)+2
    limits = lower, upper
    board = overview(charts, sources, limits)
    for ext in ["png", "svg", "pdf"]:
        board.savefig(OUT/f"comparison_overview.{ext}", dpi=180, facecolor="white")
    with PdfPages(OUT/"all_nine_charts.pdf") as pdf:
        pdf.savefig(board)
        plt.close(board)
        for source in SOURCE_ORDER:
            for count in GROUPS:
                indexes, sizes = charts[(source, count)]
                fig = individual_chart(indexes, count, sources[source], sizes, limits)
                for ext in ["png", "svg", "pdf"]:
                    fig.savefig(OUT/source/GROUPS[count]/f"productivity_index.{ext}", dpi=180, facecolor="white")
                pdf.savefig(fig)
                plt.close(fig)
    # Reproducing RPS on the new chart layout must not change its existing series.
    max_difference = 0.0
    for count in GROUPS:
        old = pd.read_csv(PRODUCTIVITY_OUT/GROUPS[count]/"productivity_index.csv", index_col=0)
        new = charts[("rps", count)][0]
        assert list(old.index) == list(new.index.astype(str))
        max_difference = max(max_difference, float(np.abs(old.to_numpy()-new.to_numpy()).max()))
    assert max_difference < 1e-7
    checks = {"charts": 9, "adoption_sources": 3, "industries_per_chart": 18,
              "quarters_per_series": len(quarters), "first_quarter": str(BASE), "last_quarter": str(latest),
              "series": 33, "data_rows": len(combined), "missing_chart_values": 0,
              "base_indexes_equal_100": True, "identical_industry_universe": True,
              "common_y_axis": list(limits), "october_2025_cps_interpolation_retained": True,
              "max_rps_difference_vs_existing_charts": max_difference}
    checks["group_sizes"] = {GROUPS[n]: [int(x) for x in pd.Series(pd.qcut(range(18), n, labels=False)).value_counts().sort_index()] for n in GROUPS}
    (OUT/"validation.json").write_text(json.dumps(checks, indent=2))
    metadata = {"created_at_utc": datetime.now(timezone.utc).isoformat(), "productivity_source": str(input_path.relative_to(ROOT)),
                "productivity_sha256": hashlib.sha256(input_path.read_bytes()).hexdigest(),
                "adoption": {key: {k: v for k, v in spec.items() if k not in ["members", "files"]} for key, spec in sources.items()},
                "files": [{"path": str(f.relative_to(ROOT)), "sha256": hashlib.sha256(f.read_bytes()).hexdigest()} for spec in sources.values() for f in spec["files"]]}
    (OUT/"source_metadata.json").write_text(json.dumps(metadata, indent=2))
    write_report(totals, sources, checks)
    with ZipFile(OUT/"charts_and_data.zip", "w", ZIP_DEFLATED) as archive:
        for path in sorted(OUT.rglob("*")):
            if path.is_file() and path.suffix != ".zip":
                archive.write(path, path.relative_to(OUT))
    print(totals[totals.groups.eq(2)][["source", "label", "latest_productivity_index", "growth_since_2023q1_pct"]].round(3).to_string(index=False))
    print(json.dumps(checks, indent=2))


def write_report(summary, sources, checks):
    lines = ["# Productivity by three AI adoption measures", "",
        "Nine charts show quartiles, quintiles and halves for Census BTOS, RPS and Ramp. The repeated word 'quartiles' in the request is interpreted as quartiles and quintiles, matching the earlier analyses.", "",
        "The independent productivity panel covers the same 18 broad private nonfarm sectors in every chart. Charts run from 2023 Q1 to 2026 Q1, with 2023 Q1 = 100 and a common vertical scale. Each group has all 13 quarterly observations. October 2025 CPS employment and actual hours use the September-November midpoint treatment; 2025 Q4 contains all three months.", "",
        "## Adoption snapshots", "", "| Measure | Fixed ranking snapshot | Definition |", "|---|---|---|"]
    for key in SOURCE_ORDER:
        spec = sources[key]
        lines.append(f"| [{spec['name']}]({spec['source_url']}) | {spec['date']} | {spec['measure']} |")
    lines += ["", "RPS refers to the Bick–Blandin–Deming Real-Time Population Survey, distributed through the GenAI Adoption Tracker and St. Louis Fed FRED. It is not a Chicago Fed survey. Chicago Fed QILP inspired the earlier productivity methodology; its observations are not used in these charts.", "",
        "Ranking snapshots reproduce the saved adoption analyses. BTOS period 202618 was released September 10, 2026. RPS is the May wave, represented by FRED's 2026 Q2 timestamp. Ramp uses the complete April 2026 sector snapshot in version 23 of the public download, which was checked again on September 14, 2026 and remained unchanged. April is the snapshot used here, not a claim that Ramp has no later headline releases.", "",
        "## Group construction", "",
        "Rank the 18 sectors by adoption within each source. Break ties by NAICS code. Apply pandas.qcut to those fixed ordinal ranks. Quartiles contain 5/4/4/5 industries; quintiles 4/3/4/3/4; halves 9/9. These divide industries into approximately equal counts, not workers, firms, or output. No adoption observations are interpolated.", "",
        "Group real output is a Törnqvist chain index using adjacent-quarter average nominal-value-added shares and BEA industry real-output growth. Group hours are the sum of independently constructed industry hours. Divide the group output index by the group hours index and normalize to 2023 Q1 = 100. Industry productivity indexes are not simply averaged. All three adoption sources use identical BEA/CES/CPS inputs and the same aggregation method.", "",
        "The main denominator combines observed CES payroll employment and workweeks with CPS nonpayroll and private-household employment at the sector CES workweek. The entire monthly hours series is seasonally adjusted with X-13. It is a research labor-hours proxy, including paid-versus-worked-hours limitations described in the underlying dataset's methodology.", "",
        "The sources measure different populations and concepts. RPS adoption can include government employees within an industry, while this productivity panel covers private sectors. Ramp observes paid adoption among its customers; BTOS reports business AI use, including uses that need not produce a Ramp transaction. Later adoption rankings are applied retrospectively; these descriptive comparisons do not identify an AI treatment effect or correct for other industry differences. Grouping and composition affect the result.", "",
        "## Growth since 2023 Q1", "", "| Source | Grouping | Group | Industries | 2026 Q1 index | Cumulative growth |", "|---|---|---|---:|---:|---:|"]
    for row in summary.itertuples():
        lines.append(f"| {sources[row.source]['name']} | {GROUPS[row.groups]} | {row.label} | {row.industry_count} | {row.latest_productivity_index:.2f} | {row.growth_since_2023q1_pct:+.2f}% |")
    lines += ["", "## Files and reproduction", "",
        "`comparison_overview.png`, `.svg`, and `.pdf` contain the nine-panel comparison. `all_nine_charts.pdf` includes that overview plus nine full-size charts. Each source/grouping directory contains PNG, SVG and PDF charts, indexed chart data, group output/hours data and industry membership. `all_chart_data.csv` and `all_industry_memberships.csv` combine the panels. `source_metadata.json` records input hashes and ranking dates.", "",
        "Run `python3 scripts/compare_ai_adoption_productivity.py` from the repository using the archived inputs. Rebuild the independent productivity panel first only when its input vintage or treatment changes. This chart builder makes no network requests and does not overwrite the source productivity workbook.", "",
        f"Validation: nine charts, 33 complete index series, {checks['data_rows']} chart-data rows, all baselines 100, matching industry universes, and exact output/hours accounting identities. The RPS series reproduce the existing RPS productivity charts to numerical precision.", "",
        "Primary productivity sources: [BEA GDP by Industry](https://www.bea.gov/itable/gdp-by-industry), [BLS CES](https://www.bls.gov/ces/data/), and [Census CPS](https://www.census.gov/programs-surveys/cps/data/datasets.html). [BLS documents the October 2025 collection gap](https://www.bls.gov/cps/methods/2025-federal-government-shutdown-impact-cps.htm).", ""]
    (OUT/"methodology.md").write_text("\n".join(lines))


if __name__ == "__main__":
    main()
