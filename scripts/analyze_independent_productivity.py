#!/usr/bin/env python3
"""Validate and chart the independent panel. QILP is used only for comparison here."""
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.ticker import MultipleLocator
import numpy as np
import pandas as pd

from independent_productivity_inputs import ROOT, OUT, RAW, BROAD, BEA_URL, BLS_URL, CPS_URL
from rps_ai_employment_quantiles import adoption, TRACKER_URL

BASE = pd.Period("2023Q1", freq="Q")
COLORS = {2: ["#356A8A", "#81559C"], 4: ["#356A8A", "#33958F", "#CC713A", "#81559C"],
          5: ["#356A8A", "#33958F", "#AE9029", "#CC713A", "#81559C"]}


def aggregate(frame):
    v = frame.pivot(index="quarter", columns="naics", values="real_value_added_quantity_index").sort_index()
    h = frame.pivot(index="quarter", columns="naics", values="annualized_hours").reindex_like(v)
    n = frame.pivot(index="quarter", columns="naics", values="nominal_value_added_dollars").reindex_like(v)
    assert v.notna().all().all() and h.notna().all().all() and n.notna().all().all()
    shares = n.div(n.sum(axis=1), axis=0)
    weights = (shares+shares.shift())/2
    dv = (weights*np.log(v).diff()).sum(axis=1, min_count=v.shape[1])
    outidx = 100*np.exp(dv.fillna(0).cumsum())
    # Hours are additive. Sum them directly rather than approximate their growth.
    hours = h.sum(axis=1)
    dh = np.log(hours).diff()
    lp = outidx/hours
    lp = 100*lp/lp.loc[BASE]
    result = pd.DataFrame({"productivity_index": lp, "real_output_index": 100*outidx/outidx.loc[BASE],
        "hours_index": 100*hours/hours.loc[BASE], "annualized_hours": hours,
        "output_growth_log_pct": 100*dv, "hours_growth_log_pct": 100*dh,
        "productivity_growth_log_pct": 100*(dv-dh),
        "productivity_growth_annualized_pct": 100*np.expm1(4*(dv-dh))})
    assert np.allclose(result.productivity_index, 100*result.real_output_index/result.hours_index)
    assert np.allclose(np.log(result.productivity_index).diff().dropna(), (dv-dh).dropna())
    contributions = []
    hshares = h.div(hours, axis=0)
    hweights = (hshares+hshares.shift())/2
    for industry in v:
        contributions.append(pd.DataFrame({"quarter": v.index, "naics": industry,
             "output_contribution_log_pp": 100*weights[industry]*np.log(v[industry]).diff(),
             "hours_contribution_tornqvist_log_pp": 100*hweights[industry]*np.log(h[industry]).diff(),
             "nominal_output_weight": weights[industry], "hours_weight": hweights[industry]}))
    return result, pd.concat(contributions, ignore_index=True)


def draw(indexes, groups, wave, path):
    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 11, "svg.fonttype": "none"})
    plural = {2: "halves", 4: "quartiles", 5: "quintiles"}[groups]
    fig, ax = plt.subplots(figsize=(13, 8), facecolor="white")
    fig.subplots_adjust(left=.075, right=.79, top=.735, bottom=.24)
    fig.text(.075, .94, f"Independent productivity by AI adoption {plural}", size=21, weight="bold", color="#18313F")
    fig.text(.075, .892, "Industry output per hour, 2023 Q1 = 100", size=13, color="#50636D")
    fig.text(.075, .853, f"18 sectors ranked by the {wave} RPS wave; fixed group membership", size=10.5, color="#50636D")
    dates = indexes.index.to_timestamp()
    for i, g in enumerate(indexes):
        label = ("Lower-adoption half" if g == 1 else "Higher-adoption half") if groups == 2 else f"Q{g}"+("  Lowest AI" if g == 1 else "  Highest AI" if g == groups else "")
        ax.plot(dates, indexes[g], color=COLORS[groups][i], lw=2.6, label=label)
        ax.scatter(dates[-1], indexes[g].iloc[-1], color=COLORS[groups][i], s=26, zorder=4)
    end = indexes.iloc[-1].sort_values()
    label_y = end.to_numpy().copy()
    ymin, ymax = min(98, np.floor(indexes.min().min()-1)), np.ceil(indexes.max().max()+2)
    for i in range(1, len(label_y)):
        label_y[i] = max(label_y[i], label_y[i-1]+max(1.2, (ymax-ymin)*.09))
    label_y -= (label_y-end.to_numpy()).mean()
    for (g, value), y in zip(end.items(), label_y):
        label = ("Lower AI" if g == 1 else "Higher AI") if groups == 2 else f"Q{g}"
        ax.annotate(f"{label}  {value:.1f}\n{value-100:+.1f}% since 2023 Q1", xy=(dates[-1], value),
            xytext=(dates[-1]+pd.Timedelta(days=28), y), textcoords="data", color=COLORS[groups][g-1],
            fontsize=10.5, va="center", annotation_clip=False,
            arrowprops={"arrowstyle": "-", "color": COLORS[groups][g-1], "lw": .7})
    ax.axhline(100, color="#87949B", lw=.9, ls=(0, (3, 3)))
    ax.axvline(pd.Timestamp("2025-01-01"), color="#AFB9BE", lw=.8, ls=(0, (2, 4)), zorder=0)
    ax.set_xlim(dates[0], dates[-1])
    ax.set_ylim(ymin, ymax)
    ticks = indexes.index[::2]
    if ticks[-1] != indexes.index[-1]:
        ticks = ticks.append(indexes.index[-1:])
    ax.set_xticks(ticks.to_timestamp(), [f"{q.year}\nQ{q.quarter}" for q in ticks])
    ax.yaxis.set_major_locator(MultipleLocator(2))
    ax.grid(axis="y", color="#E5EBEF", lw=.8)
    ax.set_axisbelow(True)
    for s in ["top", "right", "left"]:
        ax.spines[s].set_visible(False)
    ax.spines["bottom"].set_color("#C6D0D6")
    ax.tick_params(length=0, pad=9, colors="#50636D")
    fig.legend(*ax.get_legend_handles_labels(), loc="upper left", bbox_to_anchor=(.066, .811),
               frameon=False, ncol=groups, fontsize=10.5, handlelength=2.1)
    fig.text(.075, .148, "Hours: CES payroll plus CPS self-employed, unpaid family and private-household workers; X-13 adjusted.", size=9.5, color="#50636D")
    fig.text(.075, .111, "Group output uses Törnqvist weights; group hours are summed. October 2025 CPS inputs are interpolated.", size=9.5, color="#50636D")
    fig.text(.075, .074, "Sources: BEA GDP by Industry, BLS CES, Census CPS; RPS via FRED. Entire series independently calculated.", size=9.5, color="#50636D")
    fig.text(.075, .037, "Research estimates of value added per labor-hour proxy. Retrospective AI rankings do not establish causality.", size=9.5, color="#6D7D85")
    for ext in ["png", "svg", "pdf"]:
        fig.savefig(path.with_suffix("."+ext), dpi=200, facecolor="white")
    plt.close(fig)


def main():
    panel = pd.read_csv(OUT/"quarterly_productivity_all_variants.csv", dtype={"naics": str})
    panel["quarter"] = pd.PeriodIndex(panel.quarter, freq="Q")
    members, _, _, wave = adoption(ROOT/"data/rps_ai", "")
    groups_out, contributions = [], []
    for variant, vf in panel.groupby("variant"):
        aggregate_all, weights_all = aggregate(vf)
        aggregate_all["variant"], aggregate_all["groups"], aggregate_all["group"] = variant, 1, 1
        groups_out.append(aggregate_all.reset_index())
        for groups in [2, 4, 5]:
            membership = members.copy()
            membership["group"] = pd.qcut(membership.adoption_rank, groups, labels=False)+1
            membership["groups"] = groups
            for group, subset in membership.groupby("group"):
                values, weights = aggregate(vf[vf.naics.isin(subset.naics)])
                values["variant"], values["groups"], values["group"] = variant, groups, group
                groups_out.append(values.reset_index())
                weights["variant"], weights["groups"], weights["group"] = variant, groups, group
                contributions.append(weights)
            name = {2:"halves",4:"quartiles",5:"quintiles"}[groups]
            if variant == "all_workers":
                dest = OUT/name
                dest.mkdir(exist_ok=True)
                membership.to_csv(dest/"industry_membership.csv", index=False)
    groups_data = pd.concat(groups_out, ignore_index=True)
    groups_data.to_csv(OUT/"group_productivity_all_variants.csv", index=False, float_format="%.10f")
    pd.concat(contributions).to_csv(OUT/"group_growth_contributions.csv", index=False, float_format="%.10f")
    summaries = []
    for groups in [2, 4, 5]:
        name = {2:"halves",4:"quartiles",5:"quintiles"}[groups]
        main = groups_data[groups_data.variant.eq("all_workers") & groups_data.groups.eq(groups) & groups_data.quarter.ge(BASE)]
        indexes = main.pivot(index="quarter", columns="group", values="productivity_index")
        indexes.to_csv(OUT/name/"productivity_index.csv", float_format="%.10f")
        main.to_csv(OUT/name/"quarterly_productivity.csv", index=False, float_format="%.10f")
        draw(indexes, groups, wave, OUT/name/"productivity_index")
        latest = main[main.quarter.eq(main.quarter.max())].copy()
        latest["growth_since_2023q1_pct"] = latest.productivity_index-100
        summaries.append(latest)
    summary = pd.concat(summaries, ignore_index=True)
    summary.to_csv(OUT/"ai_group_summary.csv", index=False, float_format="%.10f")
    audit = groups_data[groups_data.quarter.between(pd.Period("2024Q4"), pd.Period("2025Q2")) & groups_data.groups.isin([1,2])]
    audit.to_csv(OUT/"2025q1_group_diagnostic.csv", index=False, float_format="%.10f")
    industry_audit = panel[panel.quarter.eq(pd.Period("2025Q1"))][["naics", "industry", "variant", "real_output_growth_log_pct", "hours_growth_log_pct", "productivity_growth_log_pct", "productivity_growth_annualized_pct"]]
    industry_audit.to_csv(OUT/"2025q1_industry_diagnostic.csv", index=False, float_format="%.10f")
    # Comparison is deliberately downstream: QILP cannot feed the independent construction.
    old_path = ROOT/"outputs/rps_ai_productivity/halves/quarterly_productivity.csv"
    if old_path.exists():
        old = pd.read_csv(old_path)
        old = old[old.quarter.eq("2025Q1")]
        q1 = audit[audit.quarter.eq(pd.Period("2025Q1")) & audit.groups.eq(2)].copy()
        q1["old_qilp_growth_annualized_log_pct"] = q1["group"].map(old.set_index("half").productivity_growth_annualized_log_pct)
        q1["independent_growth_annualized_log_pct"] = 4*q1.productivity_growth_log_pct
        q1.to_csv(OUT/"2025q1_comparison_with_previous_chart.csv", index=False, float_format="%.10f")
    print(summary[["groups", "group", "quarter", "productivity_index", "growth_since_2023q1_pct"]].round(3).to_string(index=False))
    print("2025 Q1", audit[audit.quarter.eq(pd.Period("2025Q1"))][["variant", "groups", "group", "output_growth_log_pct", "hours_growth_log_pct", "productivity_growth_annualized_pct"]].round(3).to_string(index=False))


if __name__ == "__main__":
    main()
