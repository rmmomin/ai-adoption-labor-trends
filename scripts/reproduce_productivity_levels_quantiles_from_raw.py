#!/usr/bin/env python3
"""
Reproduce QILP labor-productivity level index (2023Q1=100) for AI-adoption quantile splits.

Inputs:
  - QILP workbook (xlsx) with "Labor Productivity" and "Nominal Output" sheets.
  - Ramp monthly AI adoption CSV with Date and naics_sector_*_ai_user_share columns.

Outputs:
  - Per-split CSV/PNG files and combined CSVs in --outdir.
"""

from __future__ import annotations

import argparse
import datetime as dt
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Tuple

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


DEFAULT_RAMP_CANDIDATES = [
    "ramp-data-wQR5S(1).csv",
    "ramp-data-wQR5S.csv",
    "data/ramp-data-wQR5S(1).csv",
    "data/ramp-data-wQR5S.csv",
]

RAMP_SECTOR_MAP: Dict[str, str | None] = {
    "accommodation_and_food_services": "Accommodation and food services",
    "administrative_and_support_and_waste_management_and_remediation_services": "Administrative and waste management services",
    "agriculture_forestry_fishing_and_hunting": "Agriculture, forestry, fishing, and hunting",
    "arts_entertainment_and_recreation": "Arts, entertainment, and recreation",
    "construction": "Construction",
    "educational_services": "Educational services",
    "finance_and_insurance": "Finance and insurance",
    "health_care_and_social_assistance": "Health care and social assistance",
    "information": "Information",
    "management_of_companies_and_enterprises": "Management of companies and enterprises",
    "manufacturing": "Manufacturing",
    "mining_quarrying_and_oil_and_gas_extraction": "Mining",
    "other_services_except_public_administration": "Other services, except government",
    "professional_scientific_and_technical_services": "Professional, scientific, and technical services",
    "public_administration": None,  # excluded
    "real_estate_and_rental_and_leasing": "Real estate and rental and leasing",
    "retail_trade": "Retail trade",
    "transportation_and_warehousing": "Transportation and warehousing",
    "utilities": "Utilities",
    "wholesale_trade": "Wholesale trade",
}


@dataclass(frozen=True)
class SplitSpec:
    name: str
    label: str
    low_q: float
    high_q: float


SPLITS: List[SplitSpec] = [
    SplitSpec("p10_p90", "90th vs 10th percentile", 0.10, 0.90),
    SplitSpec("p25_p75", "75th vs 25th percentile", 0.25, 0.75),
    SplitSpec("p33_p66", "66th vs 33rd percentile", 0.33, 0.66),
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Reproduce productivity level indexes for AI-adoption quantile splits."
    )
    parser.add_argument(
        "--qilp-xlsx",
        default="data/qilp.xlsx",
        help="Path to QILP workbook (xlsx).",
    )
    parser.add_argument(
        "--ramp-csv",
        default="",
        help=(
            "Path to Ramp monthly AI adoption CSV. If omitted, script searches for: "
            + ", ".join(DEFAULT_RAMP_CANDIDATES)
        ),
    )
    parser.add_argument(
        "--outdir",
        default="outputs/productivity_levels_quantiles_from_2023Q1",
        help="Directory for generated outputs.",
    )
    parser.add_argument(
        "--base-date",
        default="2023-01-01",
        help="Quarter-start base date for index rebasing (YYYY-MM-DD).",
    )
    return parser.parse_args()


def pct_to_float(value: object) -> float:
    if pd.isna(value):
        return np.nan
    if isinstance(value, str):
        stripped = value.strip()
        if stripped.endswith("%"):
            return float(stripped[:-1]) / 100.0
        return float(stripped)
    return float(value)


def resolve_existing_file(path_arg: str, candidates: List[str]) -> str:
    if path_arg:
        resolved = os.path.abspath(os.path.expanduser(path_arg))
        if not os.path.exists(resolved):
            raise FileNotFoundError(f"File not found: {resolved}")
        return resolved

    for candidate in candidates:
        if os.path.exists(candidate):
            return os.path.abspath(candidate)

    raise FileNotFoundError(
        "No input file found. Checked: " + ", ".join(candidates)
    )


def load_latest_ramp_adoption(ramp_csv_path: str) -> Tuple[pd.DataFrame, pd.Timestamp]:
    ramp = pd.read_csv(ramp_csv_path)
    if "Date" not in ramp.columns:
        raise ValueError("Ramp CSV missing required column: Date")

    ramp["Date"] = pd.to_datetime(ramp["Date"])
    latest_ramp_month = ramp["Date"].max()
    latest_row = ramp.loc[ramp["Date"] == latest_ramp_month].iloc[0]

    rows = []
    for col in ramp.columns:
        if col == "Date":
            continue
        match = re.match(r"naics_sector_(.*)_ai_user_share", col)
        if not match:
            continue
        key = match.group(1)
        industry = RAMP_SECTOR_MAP.get(key)
        if industry is None:
            continue
        rows.append(
            {
                "industry": industry,
                "ai_user_share": pct_to_float(latest_row[col]),
                "ramp_col": col,
            }
        )

    adopt_df = (
        pd.DataFrame(rows)
        .dropna(subset=["ai_user_share"])
        .sort_values("ai_user_share")
        .reset_index(drop=True)
    )
    if adopt_df.empty:
        raise ValueError("No Ramp AI adoption rows matched known industry mappings.")
    return adopt_df, latest_ramp_month


def load_qilp_panel(qilp_path: str, industries: List[str]) -> pd.DataFrame:
    workbook = pd.read_excel(qilp_path, sheet_name=["Labor Productivity", "Nominal Output"])
    lp = workbook["Labor Productivity"].copy()
    nominal = workbook["Nominal Output"].copy()

    required_column = "industry"
    if required_column not in lp.columns or required_column not in nominal.columns:
        raise ValueError("QILP sheets must contain an 'industry' column.")

    date_cols = [
        c
        for c in lp.columns
        if isinstance(c, (pd.Timestamp, dt.datetime, np.datetime64))
    ]
    date_cols = sorted(date_cols)
    if not date_cols:
        raise ValueError("No quarterly date columns found in QILP workbook.")

    lp_long = (
        lp[lp["industry"].isin(industries)][["industry"] + date_cols]
        .melt(id_vars="industry", var_name="date", value_name="lp_index")
        .dropna()
    )
    lp_long["date"] = pd.to_datetime(lp_long["date"])

    nominal_long = (
        nominal[nominal["industry"].isin(industries)][["industry"] + date_cols]
        .melt(id_vars="industry", var_name="date", value_name="nom_va")
        .dropna()
    )
    nominal_long["date"] = pd.to_datetime(nominal_long["date"])

    panel = lp_long.merge(nominal_long, on=["industry", "date"], how="left")
    if panel.empty:
        raise ValueError("Merged QILP panel is empty after industry filtering.")
    return panel


def weighted_geometric_mean(values: pd.Series, weights: pd.Series) -> float:
    values_arr = np.asarray(values, dtype=float)
    weights_arr = np.asarray(weights, dtype=float)
    mask = (
        np.isfinite(values_arr)
        & np.isfinite(weights_arr)
        & (values_arr > 0)
        & (weights_arr > 0)
    )
    if mask.sum() == 0:
        return np.nan
    v = values_arr[mask]
    w = weights_arr[mask]
    w = w / w.sum()
    return float(np.exp(np.sum(w * np.log(v))))


def run_split(
    panel: pd.DataFrame,
    adopt_df: pd.DataFrame,
    split: SplitSpec,
    base_date: pd.Timestamp,
    latest_ramp_month: pd.Timestamp,
    out_dir: Path,
) -> Tuple[pd.DataFrame, pd.DataFrame]:
    low_thr = float(adopt_df["ai_user_share"].quantile(split.low_q))
    high_thr = float(adopt_df["ai_user_share"].quantile(split.high_q))

    members = adopt_df.copy()
    members["ai_group"] = np.select(
        [
            members["ai_user_share"] <= low_thr,
            members["ai_user_share"] >= high_thr,
        ],
        ["Low AI adopters", "High AI adopters"],
        default="Middle (excluded)",
    )
    members = members[members["ai_group"].isin(["Low AI adopters", "High AI adopters"])].copy()
    members["split"] = split.name
    members["split_label"] = split.label
    members["low_thr"] = low_thr
    members["high_thr"] = high_thr

    panel_split = panel.merge(members[["industry", "ai_group"]], on="industry", how="inner")
    if panel_split.empty:
        raise ValueError(f"Split {split.name} produced an empty panel after industry matching.")

    rows = []
    for (ai_group, date), grp in panel_split.groupby(["ai_group", "date"]):
        rows.append(
            {
                "ai_group": ai_group,
                "date": pd.Timestamp(date),
                "lp_level_group": weighted_geometric_mean(grp["lp_index"], grp["nom_va"]),
            }
        )

    ts = pd.DataFrame(rows).sort_values(["ai_group", "date"]).reset_index(drop=True)
    ts["split"] = split.name
    ts["split_label"] = split.label
    ts["low_thr"] = low_thr
    ts["high_thr"] = high_thr

    base_vals = ts[ts["date"] == base_date].set_index("ai_group")["lp_level_group"]
    if base_vals.empty:
        raise ValueError(
            f"Base date {base_date.date()} missing for split {split.name}. "
            "Adjust --base-date."
        )

    ts["index_2023Q1_100"] = ts.apply(
        lambda row: 100.0 * row["lp_level_group"] / base_vals.get(row["ai_group"], np.nan),
        axis=1,
    )
    ts = ts[ts["date"] >= base_date].copy()

    ts.to_csv(
        out_dir / f"productivity_levels_index_2023Q1_100_{split.name}_from_2023Q1.csv",
        index=False,
    )

    n_high = int((members["ai_group"] == "High AI adopters").sum())
    n_low = int((members["ai_group"] == "Low AI adopters").sum())

    fig = plt.figure(figsize=(11, 6.6))
    ax = fig.add_subplot(111)
    for group_name in ["High AI adopters", "Low AI adopters"]:
        subset = ts[ts["ai_group"] == group_name]
        if subset.empty:
            continue
        n = n_high if group_name == "High AI adopters" else n_low
        ax.plot(subset["date"], subset["index_2023Q1_100"], label=f"{group_name} (n={n})")

    ax.axhline(100, linewidth=1)
    ax.set_title(
        "Labor productivity level index (2023Q1=100): High vs Low AI adopters\n"
        f"({split.label})"
    )
    ax.set_ylabel("Index (2023Q1=100)")
    ax.set_xlabel("Quarter")
    ax.legend()

    note_1 = (
        f"Methodology: groups defined by latest Ramp AI user share ({latest_ramp_month:%Y-%m}); "
        f"cutoffs = {int(split.high_q*100)}th/{int(split.low_q*100)}th percentiles "
        f"(High >= {high_thr*100:.1f}%, Low <= {low_thr*100:.1f}%). Middle industries excluded."
    )
    note_2 = (
        "Group index uses weighted geometric mean of QILP labor productivity levels with "
        "within-group nominal value-added weights; rebased to 2023Q1=100 from 2023Q1 onward."
    )
    note_3 = "Source: Chicago Fed QILP, Ramp, and author calculations."
    fig.tight_layout(rect=[0, 0.16, 1, 1])
    fig.text(0.01, 0.09, note_1, ha="left", va="bottom", fontsize=8.6)
    fig.text(0.01, 0.055, note_2, ha="left", va="bottom", fontsize=8.6)
    fig.text(0.01, 0.02, note_3, ha="left", va="bottom", fontsize=8.6)

    fig.savefig(
        out_dir / f"productivity_levels_index_2023Q1_100_{split.name}_from_2023Q1.png",
        dpi=200,
    )
    plt.close(fig)

    members_out = members[
        ["split", "split_label", "industry", "ai_user_share", "ai_group", "low_thr", "high_thr"]
    ].copy()
    return ts, members_out


def main() -> None:
    args = parse_args()

    qilp_path = resolve_existing_file(args.qilp_xlsx, ["data/qilp.xlsx"])
    ramp_path = resolve_existing_file(args.ramp_csv, DEFAULT_RAMP_CANDIDATES)
    out_dir = Path(args.outdir)
    out_dir.mkdir(parents=True, exist_ok=True)

    base_date = pd.Timestamp(args.base_date)

    adopt_df, latest_ramp_month = load_latest_ramp_adoption(ramp_path)
    panel = load_qilp_panel(qilp_path, industries=adopt_df["industry"].unique().tolist())

    all_ts = []
    all_members = []
    for split in SPLITS:
        ts, members = run_split(
            panel=panel,
            adopt_df=adopt_df,
            split=split,
            base_date=base_date,
            latest_ramp_month=latest_ramp_month,
            out_dir=out_dir,
        )
        all_ts.append(ts)
        all_members.append(members)

    pd.concat(all_ts, ignore_index=True).to_csv(
        out_dir / "productivity_levels_index_2023Q1_100_all_quantile_splits_from_2023Q1.csv",
        index=False,
    )
    pd.concat(all_members, ignore_index=True).to_csv(
        out_dir / "ai_quantile_membership_latestRampMonth.csv",
        index=False,
    )

    print(f"Done. Latest Ramp month: {latest_ramp_month:%Y-%m}", file=sys.stderr)
    print(f"Outputs written to: {out_dir.resolve()}", file=sys.stderr)


if __name__ == "__main__":
    main()
