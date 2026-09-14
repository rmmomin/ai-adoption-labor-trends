#!/usr/bin/env python3
"""Chart quarterly productivity by fixed RPS AI adoption halves, quartiles or quintiles.

Uses the archived RPS wave and QILP research extension from this project.
Group productivity is a chained Tornqvist output index divided by a chained
Tornqvist hours index, rebased to 2023 Q1 = 100.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
from matplotlib.ticker import MultipleLocator
import numpy as np
import pandas as pd

from rps_ai_employment_quantiles import adoption, TRACKER_URL, PAPER_URL

ROOT = Path(__file__).resolve().parents[1]
BASE = pd.Period("2023Q1", freq="Q")
QILP_PAPER = "https://www.chicagofed.org/publications/economic-perspectives/2025/1"
QILP_MAP = {
    "21": (4, "Mining"), "22": (8, "Utilities"), "23": (9, "Construction"),
    "31-33": (10, "Manufacturing"), "42": (32, "Wholesale trade"),
    "44-45": (33, "Retail trade"), "48-49": (38, "Transportation and warehousing"),
    "51": (47, "Information"), "52": (53, "Finance and insurance"),
    "53": (58, "Real estate and rental and leasing"),
    "54": (64, "Professional, scientific, and technical services"),
    "55": (68, "Management of companies and enterprises"),
    "56": (69, "Administrative and waste management services"),
    "61": (73, "Educational services"), "62": (74, "Health care and social assistance"),
    "71": (80, "Arts, entertainment, and recreation"),
    "72": (83, "Accommodation and food services"), "81": (86, "Other services, except government"),
}
GROUP_NAMES = {2: "half", 4: "quartile", 5: "quintile"}
COLORS = {2: ["#356A8A", "#81559C"],
          4: ["#356A8A", "#33958F", "#CC713A", "#81559C"],
          5: ["#356A8A", "#33958F", "#AE9029", "#CC713A", "#81559C"]}


def group_label(groups, group):
    if groups == 2:
        return {1: "Lower-adoption half", 2: "Higher-adoption half"}[group]
    return f"Q{group}"


def load_panel(path, members):
    panel = pd.read_csv(path)
    panel["quarter"] = pd.PeriodIndex(panel.quarter, freq="Q")
    panel = panel[panel.gdp_line.isin(members.gdp_line) & panel.quarter.ge(BASE)].copy()
    if panel.duplicated(["gdp_line", "quarter"]).any():
        raise ValueError("Duplicate industry-quarter observations")
    periods = pd.period_range(BASE, panel.quarter.max(), freq="Q")
    expected = pd.MultiIndex.from_product([sorted(members.gdp_line), periods], names=["gdp_line", "quarter"])
    actual = pd.MultiIndex.from_frame(panel[["gdp_line", "quarter"]]).sort_values()
    if not expected.equals(actual):
        raise ValueError("The productivity panel must contain every industry in every quarter")
    measures = ["labor_productivity_index", "total_hours_annualized", "nominal_output_linked_dollars"]
    if panel[measures].isna().any().any() or not (panel[measures] > 0).all().all():
        raise ValueError("Missing or nonpositive productivity, hours, or nominal-output input")
    if not panel.observation_status.isin(["published_qilp", "research_extension"]).all():
        raise ValueError("The panel includes an unsupported extension or benchmark row")
    if not panel.groupby("quarter").observation_status.nunique().eq(1).all():
        raise ValueError("Mixed source status within a quarter")
    names = members.set_index("gdp_line").qilp_industry
    if not panel.industry.eq(panel.gdp_line.map(names)).all():
        raise ValueError("QILP identifier and industry-name mismatch")
    last_published = panel.loc[panel.observation_status.eq("published_qilp"), "quarter"].max()
    if not panel.loc[panel.quarter.le(last_published), "observation_status"].eq("published_qilp").all():
        raise ValueError("Published data must precede the research extension")
    return panel.sort_values(["gdp_line", "quarter"]), last_published


def aggregate(group_panel):
    def pivot(column):
        return group_panel.pivot(index="quarter", columns="gdp_line", values=column).sort_index().sort_index(axis=1)
    lp = pivot("labor_productivity_index")
    hours = pivot("total_hours_annualized")
    nominal = pivot("nominal_output_linked_dollars")
    vshare = nominal.div(nominal.sum(axis=1), axis=0)
    hshare = hours.div(hours.sum(axis=1), axis=0)
    vw = (vshare + vshare.shift()) / 2
    hw = (hshare + hshare.shift()) / 2
    dlpa, dh = np.log(lp).diff(), np.log(hours).diff()
    # Infer quantity growth from the level identity LP = V/H. This preserves
    # the supplied LP series without relying on another sheet's growth convention.
    dv = dlpa + dh
    output_growth = (vw * dv).sum(axis=1, min_count=len(lp.columns))
    hours_growth = (hw * dh).sum(axis=1, min_count=len(lp.columns))
    growth = output_growth - hours_growth
    if growth.iloc[1:].isna().any():
        raise ValueError("Missing group growth after the base quarter")
    output_index = 100 * np.exp(output_growth.fillna(0).cumsum())
    hours_index = 100 * np.exp(hours_growth.fillna(0).cumsum())
    result = pd.DataFrame({
        "productivity_index": 100 * output_index / hours_index,
        "output_index": output_index, "hours_index": hours_index,
        "productivity_growth_annualized_log_pct": 400 * growth,
        "output_growth_annualized_log_pct": 400 * output_growth,
        "hours_growth_annualized_log_pct": 400 * hours_growth,
        "within_industry_growth_annualized_log_pct": 400 * (vw * dlpa).sum(axis=1, min_count=len(lp.columns)),
        "composition_growth_annualized_log_pct": 400 * ((vw-hw) * dh).sum(axis=1, min_count=len(lp.columns)),
    })
    assert np.allclose(result.productivity_index, 100*np.exp(growth.fillna(0).cumsum()))
    assert np.allclose(result.loc[BASE, ["productivity_index", "output_index", "hours_index"]], 100)
    assert np.allclose(vshare.sum(axis=1), 1) and np.allclose(hshare.sum(axis=1), 1)
    assert np.allclose(vw.iloc[1:].sum(axis=1), 1) and np.allclose(hw.iloc[1:].sum(axis=1), 1)
    decomposition = result.within_industry_growth_annualized_log_pct + result.composition_growth_annualized_log_pct
    assert np.allclose(decomposition.iloc[1:], result.productivity_growth_annualized_log_pct.iloc[1:])
    weights = []
    for q in lp.index:
        for line in lp.columns:
            weights.append({"quarter": q, "gdp_line": line,
                            "nominal_output_share": vshare.loc[q, line], "hours_share": hshare.loc[q, line],
                            "tornqvist_output_weight": vw.loc[q, line], "tornqvist_hours_weight": hw.loc[q, line],
                            "industry_index_2023q1_100": 100*lp.loc[q,line]/lp.loc[BASE,line]})
    return result, pd.DataFrame(weights)


def plot(indexes, groups, published_end, wave, path):
    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 11, "svg.fonttype": "none"})
    name = "halves" if groups == 2 else GROUP_NAMES[groups]
    fig, ax = plt.subplots(figsize=(13, 8), facecolor="white")
    fig.subplots_adjust(left=.075, right=.80, bottom=.235, top=.755)
    fig.text(.075, .94, f"Productivity by RPS AI adoption {name}", fontsize=23, weight="bold", color="#18313F")
    fig.text(.075, .895, "Industry output per hour, 2023 Q1 = 100", fontsize=13, color="#50636D")
    fig.text(.075, .855, f"18 sectors ranked using the {wave} RPS wave; group membership stays fixed", fontsize=11, color="#50636D")
    dates = indexes.index.to_timestamp()
    anchor = published_end.to_timestamp()
    latest = dates[-1]
    for i, g in enumerate(indexes.columns):
        color = COLORS[groups][i]
        label = group_label(groups, g)
        if groups != 2:
            label += "  Lowest AI" if g == 1 else "  Highest AI" if g == groups else ""
        official = indexes.index <= published_end
        ax.plot(dates[official], indexes.loc[official,g], lw=2.7, color=color, label=label)
        if published_end < indexes.index[-1]:
            estimate = indexes.index >= published_end
            ax.plot(dates[estimate], indexes.loc[estimate,g], lw=2.7, color=color, linestyle=(0,(4,2.5)))
        ax.scatter([latest], [indexes.iloc[-1][g]], s=29, color=color, zorder=5)
    ax.axhline(100, color="#87949B", lw=1, linestyle=(0,(3,3)), zorder=0)
    if published_end < indexes.index[-1]:
        ax.axvspan(anchor, latest, color="#EADBC5", alpha=.28, zorder=-1)
        ax.axvline(anchor, color="#AB9676", lw=.85, linestyle=(0,(2,3)), zorder=0)
        midpoint = anchor+(latest-anchor)/2
        ax.text(midpoint,.965,"Research extension",ha="center",va="top",transform=ax.get_xaxis_transform(),fontsize=9.5,color="#806945")
    ax.grid(axis="y", color="#E5EBEF", lw=.8)
    ax.set_axisbelow(True)
    for spine in ["top","right","left"]:
        ax.spines[spine].set_visible(False)
    ax.spines["bottom"].set_color("#C6D0D6")
    ax.tick_params(axis="both", length=0, pad=9, colors="#50636D")
    tickquarters = pd.period_range(BASE,indexes.index[-1],freq="Q")[::2]
    if tickquarters[-1] != indexes.index[-1]:
        tickquarters = tickquarters.append(pd.PeriodIndex([indexes.index[-1]],freq="Q"))
    ax.set_xticks(tickquarters.to_timestamp())
    ax.set_xticklabels([f"{q.year}\nQ{q.quarter}" for q in tickquarters])
    ax.set_xlim(dates[0], latest)
    low, high = indexes.min().min(), indexes.max().max()
    ax.set_ylim(min(98,np.floor(low-1)),np.ceil(high+2.5))
    ax.yaxis.set_major_locator(MultipleLocator(2))
    ordered = indexes.iloc[-1].sort_values()
    label_y = ordered.to_numpy().copy()
    gap = max(1.4,(ax.get_ylim()[1]-ax.get_ylim()[0])*.085)
    for i in range(1,len(label_y)):
        label_y[i] = max(label_y[i],label_y[i-1]+gap)
    label_y -= (label_y-ordered.to_numpy()).mean()
    for (g,value),y in zip(ordered.items(),label_y):
        color=COLORS[groups][g-1]
        label = ("Lower AI" if g == 1 else "Higher AI") if groups == 2 else f"Q{g}"
        ax.annotate(f"{label}  {value:.1f}\n{value-100:+.1f}% since 2023 Q1",xy=(latest,value),
                    xytext=(mdates.date2num(latest)+32,y),textcoords="data",va="center",
                    color=color,fontsize=10.5,annotation_clip=False,
                    arrowprops={"arrowstyle":"-","color":color,"lw":.7})
    fig.legend(*ax.get_legend_handles_labels(), loc="upper left", bbox_to_anchor=(.066,.820),
               frameon=False,ncol=groups,columnspacing=2.0,handlelength=2.2,fontsize=11)
    fig.text(.075,.145,"Output and hours use Törnqvist weights; the indexes include shifts in industry composition within each group.",fontsize=10,color="#50636D")
    if published_end < indexes.index[-1]:
        fig.text(.075,.108,f"Solid: published QILP inputs through {published_end.year} Q{published_end.quarter}. Dashed: research estimates using payroll-hours growth.",fontsize=10,color="#806945")
    fig.text(.075,.071,"Sources: Chicago Fed QILP; RPS (Bick, Blandin & Deming) via FRED; BEA and BLS for the extension.",fontsize=10,color="#50636D")
    fig.text(.075,.035,"These retrospective industry comparisons do not establish a causal effect of AI on productivity.",fontsize=9.5,color="#6D7D85")
    for ext in ["png","svg","pdf"]:
        fig.savefig(path.with_suffix("."+ext), dpi=200, facecolor="white")
    plt.close(fig)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--qilp-csv",type=Path,default=ROOT/"outputs/qilp_update_01a0a142/qilp_extension.csv")
    p.add_argument("--rps-raw-dir",type=Path,default=ROOT/"data/rps_ai")
    p.add_argument("--rps-quarter",default="",help="FRED quarter-start date; default latest archived common wave")
    p.add_argument("--outdir",type=Path,default=ROOT/"outputs/rps_ai_productivity")
    p.add_argument("--groups",type=int,nargs="+",choices=[2,4,5],default=[4,5],
                   help="Number of adoption groups; use 2 for halves (default: 4 5)")
    args=p.parse_args()
    members,_,quarter,wave=adoption(args.rps_raw_dir,args.rps_quarter)
    assert set(members.naics)==set(QILP_MAP)
    members["gdp_line"]=members.naics.map(lambda n:QILP_MAP[n][0])
    members["qilp_industry"]=members.naics.map(lambda n:QILP_MAP[n][1])
    panel,published_end=load_panel(args.qilp_csv,members)
    source_files=[args.qilp_csv,args.rps_raw_dir/"fred_series.json"]
    sources=[{"path":str(p.resolve()),"sha256":hashlib.sha256(p.read_bytes()).hexdigest()} for p in source_files]
    summaries=[]
    selected_groups=sorted(set(args.groups))
    for groups in selected_groups:
        name=GROUP_NAMES[groups]
        plural="halves" if groups==2 else f"{name}s"
        out=args.outdir/plural
        out.mkdir(parents=True,exist_ok=True)
        grouped=members.copy()
        grouped[name]=pd.qcut(grouped.adoption_rank,groups,labels=False)+1
        grouped["group_label"]=grouped[name].map(lambda g:group_label(groups,g))
        existing=ROOT/f"outputs/rps_ai_{plural}/industry_membership.csv"
        if existing.exists():
            old=pd.read_csv(existing,dtype={"naics":str})
            if old.rps_quarter_date.eq(quarter.date().isoformat()).all():
                assert old.set_index("naics")[name].sort_index().equals(grouped.set_index("naics")[name].sort_index())
        series,weight_parts=[],[]
        for g,gm in grouped.groupby(name):
            sub=panel[panel.gdp_line.isin(gm.gdp_line)]
            result,weights=aggregate(sub)
            result[name]=g
            series.append(result.reset_index())
            weights[name]=g
            weight_parts.append(weights)
        # A one-industry aggregate must reproduce its supplied productivity index.
        one=panel[panel.gdp_line.eq(grouped.iloc[0].gdp_line)].sort_values("quarter")
        single,_=aggregate(one)
        assert np.allclose(single.productivity_index,100*one.labor_productivity_index/one.labor_productivity_index.iloc[0])
        quarterly=pd.concat(series,ignore_index=True)
        quarterly["group_label"]=quarterly[name].map(lambda g:group_label(groups,g))
        quarterly["growth_since_2023q1_pct"]=quarterly.productivity_index-100
        quarterly["source_status"]=np.where(quarterly.quarter.le(published_end),"published_qilp_inputs","research_extension_inputs")
        quarterly["date"]=pd.PeriodIndex(quarterly.quarter).to_timestamp().strftime("%Y-%m-%d")
        indexes=quarterly.pivot(index="quarter",columns=name,values="productivity_index").sort_index()
        assert indexes.shape==(len(panel.quarter.unique()),groups)
        assert indexes.notna().all().all() and np.allclose(indexes.loc[BASE],100)
        group_sizes=grouped.groupby(name).size().tolist()
        assert sum(group_sizes)==18 and max(group_sizes)-min(group_sizes)<=1
        summary=grouped.groupby(name).agg(sectors=("naics","size"),adoption_min_pct=("ai_adoption_pct","min"),adoption_max_pct=("ai_adoption_pct","max"))
        summary["latest_quarter"]=str(indexes.index[-1])
        summary["latest_index"]=indexes.iloc[-1]
        summary["growth_since_2023q1_pct"]=summary.latest_index-100
        summary["published_end_index"]=indexes.loc[published_end]
        summary["group_label"]=[group_label(groups,g) for g in summary.index]
        plot(indexes,groups,published_end,wave,out/"productivity_index")
        grouped.to_csv(out/"industry_membership.csv",index=False)
        quarterly.to_csv(out/"quarterly_productivity.csv",index=False,float_format="%.10f")
        csv_labels={1:"lower_adoption_half",2:"higher_adoption_half"} if groups==2 else {g:f"Q{g}" for g in indexes.columns}
        indexes.rename(columns=csv_labels).to_csv(out/"productivity_index.csv",float_format="%.10f")
        weights=pd.concat(weight_parts,ignore_index=True)
        details=panel.merge(grouped[["gdp_line","naics","ai_adoption_pct",name]],on="gdp_line",validate="many_to_one").merge(weights,on=["gdp_line","quarter",name],validate="one_to_one")
        details.to_csv(out/"industry_quarterly_inputs.csv",index=False,float_format="%.10f")
        summary.to_csv(out/"summary.csv",float_format="%.10f")
        checks={"passed":True,"industries":18,"quarters":len(indexes),"group_sizes":group_sizes,
                "base_quarter":str(BASE),"latest_quarter":str(indexes.index[-1]),"published_through":str(published_end),
                "base_indexes_equal_100":True,"balanced_industry_panel":True,"single_industry_identity":True,
                "tornqvist_weights_sum_to_one":True,"output_hours_productivity_identity":True,
                "within_and_composition_growth_reconcile":True}
        (out/"validation.json").write_text(json.dumps(checks,indent=2))
        meta={"built_at_utc":datetime.now(timezone.utc).isoformat(),"ranking_wave":wave,
              "rps_quarter_date":quarter.date().isoformat(),"grouping":name,"sources":sources,
              "method":"Tornqvist output growth less Tornqvist hours growth; quantity growth inferred from LP and hours levels", "checks":checks,
              "source_urls":[QILP_PAPER,TRACKER_URL,PAPER_URL,*grouped.source_url.tolist()]}
        (out/"source_metadata.json").write_text(json.dumps(meta,indent=2))
        lines=[f"# Productivity by RPS AI adoption {plural}","",
               f"2023 Q1 = 100; {len(indexes)} quarters through {indexes.index[-1]}. Ranking wave: {wave}.","",
               "![Productivity indexes](productivity_index.png)","",
               f"| {name.title()} | Sectors | RPS work AI adoption (%) | Latest index | Growth since 2023 Q1 (%) |",
               "|---|---:|---:|---:|---:|"]
        for g,r in summary.iterrows():
            lines.append(f"| {group_label(groups,g)} | {r.sectors:.0f} | {r.adoption_min_pct:.2f}–{r.adoption_max_pct:.2f} | {r.latest_index:.2f} | {r.growth_since_2023q1_pct:+.2f} |")
        lines += ["","## Group construction","",
                  f"Rank 18 mutually exclusive broad nonfarm sectors by the {wave} RPS work-related genAI adoption estimates. "
                  f"Apply pandas.qcut to ranks to create {groups} groups with {', '.join(map(str,group_sizes))} sectors. "
                  f"{group_label(groups,1)} contains the lower-adoption sectors; {group_label(groups,groups)} contains the higher-adoption sectors. Ties are ordered by NAICS. "
                  "Membership matches the project's corresponding RPS employment charts and stays fixed across all quarters. "
                  "The ranking wave is later than the productivity endpoint; these are retrospective descriptive groups, not causal estimates.",
                  "","## Productivity aggregation","",
                  "Within each group, sV is the sector's nominal-output share and sH its total-hours share. "
                  "Tornqvist weights wV and wH average the current and prior-quarter shares. "
                  "Use dlog(V_i) = dlog(LP_i) + dlog(H_i) to infer quantity growth from the supplied productivity and hours levels. "
                  "This avoids mixing the level series with the separate Real Output Growth sheet's reported growth convention.","",
                  "Group dlog(LP) = sum[wV_i × dlog(V_i)] − sum[wH_i × dlog(H_i)]. "
                  "Chain these log changes forward from 2023 Q1 = 100. The group index includes within-group industry composition shifts. "
                  "The chart is an output-per-hour aggregate, not a simple average of industry index levels. "
                  "Shares, weights and normalized industry indexes are recorded in industry_quarterly_inputs.csv. "
                  "The quarterly output and hours indexes independently reconcile to the productivity index.",
                  "","## Sources and limits","",
                  f"Productivity uses Chicago Fed QILP through {published_end} and the project's independently constructed research extension afterward. "
                  "The original QILP input history is preserved. New-quarter hours assume combined employee/self-employed/family hours grow "
                  "at mapped CES payroll-hours rates; CPS microdata and X-13 are not rebuilt. New nominal-output amounts are linked to "
                  "the published anchor, not actual current-vintage BEA dollar levels. Shading and dashed lines identify the extension. "
                  "Group estimates are author calculations, not official Chicago Fed group statistics. "
                  "See the QILP extension methodology for mapping and overlap-error diagnostics; those industry diagnostics are not group confidence intervals.","",
                  "RPS is the Real-Time Population Survey of Bick, Blandin and Deming, distributed through the GenAI Adoption Tracker and "
                  "St. Louis Fed FRED. It reports the share of employed adults aged 18–64 using genAI for work. "
                  "It is not a Chicago Fed survey. The May 2026 wave is labeled 2026 Q2 (2026-04-01) in FRED. "
                  "These are point-estimate rankings without inferred confidence bands. RPS respondents and the private-sector QILP population "
                  "do not match perfectly, particularly in education and healthcare. Government and agriculture are excluded.","",
                  f"- [Chicago Fed QILP paper]({QILP_PAPER})",
                  f"- [GenAI Adoption Tracker]({TRACKER_URL})",
                  f"- [Bick, Blandin and Deming, The Rapid Adoption of Generative AI]({PAPER_URL})",
                  "- Per-industry FRED links are in industry_membership.csv; input hashes are in source_metadata.json.","",
                  "## Reproduce","","```bash",f"python3 scripts/rps_ai_productivity_quantiles.py --groups {groups}","```","",
                  "The script uses archived inputs without network requests. Refresh the QILP and RPS source pipelines separately to change vintages. "
                  "PNG, SVG, PDF, chart data, group membership, underlying weights, and validation are saved for each selected grouping.",""]
        (out/"analysis.md").write_text("\n".join(lines))
        summaries.append(summary.reset_index().rename(columns={name:"group"}).assign(grouping=name))
        print(name,summary.round(3).to_string(),sep="\n")
    summary_name="summary.csv" if selected_groups==[4,5] else "summary_groups_"+"_".join(map(str,selected_groups))+".csv"
    pd.concat(summaries,ignore_index=True).to_csv(args.outdir/summary_name,index=False,float_format="%.10f")


if __name__=="__main__":
    main()
