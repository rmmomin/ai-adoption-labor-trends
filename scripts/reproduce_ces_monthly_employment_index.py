#!/usr/bin/env python3
"""
Reproduce monthly CES employment index charts by AI-adoption quantile splits.

Inputs:
  - Ramp AI adoption by NAICS sector (monthly CSV with columns like
    `naics_sector_*_ai_user_share` and a `Date` column).

Data source:
  - U.S. BLS Current Employment Statistics (CES), national, all employees (SA)
    https://download.bls.gov/pub/time.series/ce/ce.data.01a.CurrentSeasAE

Outputs:
  - Split membership CSV
  - Per-split indexed employment CSV + PNG chart
  - Combined long-format CSV across all splits
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from dataclasses import dataclass
from typing import Dict, List, Tuple

import matplotlib.pyplot as plt
from matplotlib.dates import DateFormatter
import numpy as np
import pandas as pd
import requests


BLS_BASE = "https://download.bls.gov/pub/time.series/ce"
BLS_DATA_FILE = "ce.data.01a.CurrentSeasAE"

DEFAULT_RAMP_CANDIDATES = [
    "ramp-data-wQR5S(1).csv",
    "ramp-data-wQR5S.csv",
    "data/ramp-data-wQR5S(1).csv",
    "data/ramp-data-wQR5S.csv",
]

# Map Ramp NAICS keys -> display names.
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

# Map display names -> CES SA all-employees series IDs (values in thousands).
INDUSTRY_TO_CES: Dict[str, str] = {
    "Accommodation and food services": "CES7072000001",
    "Administrative and waste management services": "CES6056000001",
    "Arts, entertainment, and recreation": "CES7071000001",
    "Construction": "CES2000000001",
    "Educational services": "CES6561000001",  # private educational services
    "Finance and insurance": "CES5552000001",
    "Health care and social assistance": "CES6562000001",
    "Information": "CES5000000001",
    "Management of companies and enterprises": "CES6055000001",
    "Manufacturing": "CES3000000001",
    "Mining": "CES1021000001",
    "Other services, except government": "CES8000000001",
    "Professional, scientific, and technical services": "CES6054000001",
    "Real estate and rental and leasing": "CES5553000001",
    "Retail trade": "CES4200000001",
    "Transportation and warehousing": "CES4300000001",
    "Utilities": "CES4422000001",
    "Wholesale trade": "CES4142000001",
}


@dataclass(frozen=True)
class SplitSpec:
    name: str
    q_low: float
    q_high: float
    median_split: bool = False


SPLITS: List[SplitSpec] = [
    SplitSpec("10vs90", 0.10, 0.90, False),
    SplitSpec("25vs75", 0.25, 0.75, False),
    SplitSpec("33vs66", 0.33, 0.66, False),
    SplitSpec("BottomvsTop50", 0.50, 0.50, True),
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Reproduce CES monthly employment index by AI-adoption quantile split."
    )
    parser.add_argument(
        "--ramp-csv",
        default="",
        help=(
            "Path to Ramp monthly AI adoption CSV. If omitted, the script searches for: "
            + ", ".join(DEFAULT_RAMP_CANDIDATES)
        ),
    )
    parser.add_argument(
        "--outdir",
        default="outputs/ces_monthly_employment_ai_quantiles",
        help="Directory for generated CSV/PNG outputs.",
    )
    parser.add_argument(
        "--cache-dir",
        default="bls_cache",
        help="Directory to store downloaded BLS bulk files.",
    )
    parser.add_argument(
        "--bls-data-file",
        default="",
        help=(
            "Path to local ce.data.01a.CurrentSeasAE file. "
            "If not provided, uses <cache-dir>/ce.data.01a.CurrentSeasAE."
        ),
    )
    parser.add_argument(
        "--no-download",
        action="store_true",
        help="Fail if BLS data file is missing instead of downloading it.",
    )
    parser.add_argument(
        "--start-date",
        default="2023-01-01",
        help="First month to include from CES data (YYYY-MM-DD).",
    )
    parser.add_argument(
        "--base-date",
        default="2023-01-01",
        help="Index base month where level index is 100 (YYYY-MM-DD).",
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


def resolve_ramp_csv(path_arg: str) -> str:
    if path_arg:
        resolved = os.path.abspath(os.path.expanduser(path_arg))
        if not os.path.exists(resolved):
            raise FileNotFoundError(f"Ramp CSV not found: {resolved}")
        return resolved

    for candidate in DEFAULT_RAMP_CANDIDATES:
        if os.path.exists(candidate):
            return os.path.abspath(candidate)

    raise FileNotFoundError(
        "Ramp CSV not found. Provide --ramp-csv or place one of these files in the working directory: "
        + ", ".join(DEFAULT_RAMP_CANDIDATES)
    )


def load_ramp_latest(ramp_csv: str) -> Tuple[pd.DataFrame, pd.Timestamp]:
    ramp = pd.read_csv(ramp_csv)
    if "Date" not in ramp.columns:
        raise ValueError("Ramp CSV is missing required 'Date' column.")
    ramp["Date"] = pd.to_datetime(ramp["Date"])

    latest_date = ramp["Date"].max()
    latest_row = ramp.loc[ramp["Date"] == latest_date].iloc[0]

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
                "ramp_key": key,
                "ai_user_share": pct_to_float(latest_row[col]),
            }
        )

    adopt = pd.DataFrame(rows).dropna()
    adopt = adopt[adopt["industry"].isin(INDUSTRY_TO_CES.keys())].copy()
    if adopt.empty:
        raise ValueError("No Ramp sectors matched CES industry mapping.")
    adopt = adopt.sort_values("ai_user_share").reset_index(drop=True)
    return adopt, latest_date


def assign_groups(adopt: pd.DataFrame, spec: SplitSpec) -> Tuple[List[str], List[str], Dict[str, float]]:
    if spec.median_split:
        median = float(adopt["ai_user_share"].quantile(0.5))
        bottom = adopt.loc[adopt["ai_user_share"] < median, "industry"].tolist()
        top = adopt.loc[adopt["ai_user_share"] >= median, "industry"].tolist()
        return bottom, top, {"median": median}

    q_low = float(adopt["ai_user_share"].quantile(spec.q_low))
    q_high = float(adopt["ai_user_share"].quantile(spec.q_high))
    bottom = adopt.loc[adopt["ai_user_share"] <= q_low, "industry"].tolist()
    top = adopt.loc[adopt["ai_user_share"] >= q_high, "industry"].tolist()
    return bottom, top, {"q_low": q_low, "q_high": q_high}


def ensure_bls_data_file(cache_dir: str, data_file_arg: str, no_download: bool) -> str:
    if data_file_arg:
        data_path = os.path.abspath(os.path.expanduser(data_file_arg))
    else:
        data_path = os.path.abspath(os.path.join(cache_dir, BLS_DATA_FILE))

    if os.path.exists(data_path):
        return data_path

    if no_download or data_file_arg:
        raise FileNotFoundError(
            f"BLS data file not found at {data_path}. "
            "Download it from https://download.bls.gov/pub/time.series/ce/ce.data.01a.CurrentSeasAE "
            "or remove --no-download."
        )

    os.makedirs(os.path.dirname(data_path), exist_ok=True)
    data_url = f"{BLS_BASE}/{BLS_DATA_FILE}"
    print(f"Downloading {data_url} -> {data_path}", file=sys.stderr)

    with requests.get(data_url, stream=True, timeout=120) as response:
        response.raise_for_status()
        with open(data_path, "wb") as handle:
            for chunk in response.iter_content(chunk_size=1 << 20):
                if chunk:
                    handle.write(chunk)

    return data_path


def load_bls_ces_all_employees(data_path: str, start_date: str) -> pd.DataFrame:
    target_series = set(INDUSTRY_TO_CES.values())
    chunks = []

    column_names = ["series_id", "year", "period", "value", "footnote_codes"]
    for chunk in pd.read_csv(
        data_path,
        sep="\t",
        names=column_names,
        header=None,
        dtype=str,
        chunksize=500000,
    ):
        chunk["series_id"] = chunk["series_id"].str.strip()
        chunk = chunk[chunk["series_id"] != "series_id"]  # header row if present
        chunk = chunk[chunk["year"].str.fullmatch(r"\d{4}", na=False)]
        if chunk.empty:
            continue
        chunk = chunk[chunk["series_id"].isin(target_series)]
        if chunk.empty:
            continue

        chunk["year"] = chunk["year"].astype(int)
        chunk = chunk[chunk["year"] >= 2022]
        chunk = chunk[chunk["period"].str.match(r"M(0[1-9]|1[0-2])$")]
        if chunk.empty:
            continue

        chunk["value"] = pd.to_numeric(chunk["value"], errors="coerce")
        chunk["month"] = chunk["period"].str[1:].astype(int)
        chunk["date"] = pd.to_datetime(dict(year=chunk["year"], month=chunk["month"], day=1))
        chunks.append(chunk[["series_id", "date", "value"]])

    if not chunks:
        raise ValueError("No CES rows were loaded. Check the data file format and expected series IDs.")

    df = pd.concat(chunks, ignore_index=True)
    series_to_industry = {series_id: industry for industry, series_id in INDUSTRY_TO_CES.items()}
    df["industry"] = df["series_id"].map(series_to_industry)

    emp = df.pivot_table(index="date", columns="industry", values="value", aggfunc="first").sort_index()
    emp = emp.loc[emp.index >= pd.to_datetime(start_date)]
    if emp.empty:
        raise ValueError(f"No employment rows found on or after start date {start_date}.")
    return emp


def make_outputs(
    emp: pd.DataFrame,
    adopt: pd.DataFrame,
    adoption_month: pd.Timestamp,
    out_dir: str,
    base_date: str,
) -> None:
    os.makedirs(out_dir, exist_ok=True)

    base_dt = pd.to_datetime(base_date)
    if base_dt not in emp.index:
        raise ValueError(
            f"Base date {base_dt.date()} is not present in employment data. "
            "Adjust --base-date or --start-date."
        )

    latest_dt = emp.index.max()

    membership_rows = []
    for _, row in adopt.iterrows():
        industry = row["industry"]
        rec = {
            "industry": industry,
            "ai_user_share_latest": row["ai_user_share"],
            "ces_series_id": INDUSTRY_TO_CES[industry],
        }
        for spec in SPLITS:
            bottom, top, _thresholds = assign_groups(adopt, spec)
            if industry in bottom:
                rec[f"group_{spec.name}"] = "bottom"
            elif industry in top:
                rec[f"group_{spec.name}"] = "top"
            else:
                rec[f"group_{spec.name}"] = "middle"
        membership_rows.append(rec)

    membership = pd.DataFrame(membership_rows).sort_values("ai_user_share_latest")
    membership.to_csv(
        os.path.join(out_dir, "ai_quantile_splits_membership_ces_employment_monthly_latest.csv"),
        index=False,
    )

    split_long_frames = []
    for spec in SPLITS:
        bottom, top, thresholds = assign_groups(adopt, spec)
        bottom = [industry for industry in bottom if industry in emp.columns]
        top = [industry for industry in top if industry in emp.columns]
        if not bottom or not top:
            raise ValueError(f"Split {spec.name} produced an empty group after CES matching.")

        bottom_level = emp[bottom].sum(axis=1)
        top_level = emp[top].sum(axis=1)
        df = pd.DataFrame(
            {
                "date": emp.index,
                "bottom_employment_level_thousands": bottom_level.values,
                "top_employment_level_thousands": top_level.values,
            }
        ).set_index("date")

        df["bottom_employment_index_2023m1_100"] = (
            100
            * df["bottom_employment_level_thousands"]
            / df.loc[base_dt, "bottom_employment_level_thousands"]
        )
        df["top_employment_index_2023m1_100"] = (
            100
            * df["top_employment_level_thousands"]
            / df.loc[base_dt, "top_employment_level_thousands"]
        )

        split_csv = os.path.join(
            out_dir, f"employment_index_ces_monthly_2023m1_100_latest_{spec.name}.csv"
        )
        df.reset_index().to_csv(split_csv, index=False)

        fig, ax = plt.subplots(figsize=(10, 5.5))
        ax.plot(df.index, df["top_employment_index_2023m1_100"], label="Top AI-adoption industries")
        ax.plot(
            df.index,
            df["bottom_employment_index_2023m1_100"],
            label="Bottom AI-adoption industries",
        )
        ax.set_title(
            f"Employment Index by AI Adoption Quantiles ({spec.name})\n"
            "Indexed to 2023m1 = 100 (Seasonally Adjusted)"
        )
        ax.set_ylabel("Employment index (2023m1 = 100)")
        ax.xaxis.set_major_formatter(DateFormatter("%Y-%m"))
        ax.grid(alpha=0.2)
        ax.legend()
        fig.autofmt_xdate(rotation=45)

        threshold_text = (
            f"thresholds={thresholds}"
            if not spec.median_split
            else f"median={thresholds['median']:.4f}"
        )
        note = (
            f"Method: group industries by latest Ramp AI user share ({adoption_month:%Y-%m}), "
            f"{threshold_text}. Employment uses BLS CES SA all-employees (thousands), "
            "group levels are summed and indexed to 2023m1. "
            "Educational services proxied by private educational services; agriculture excluded. "
            f"Latest CES month shown: {latest_dt:%Y-%m}."
        )
        fig.text(0.01, 0.01, note, ha="left", va="bottom", fontsize=8, wrap=True)
        fig.tight_layout(rect=[0, 0.07, 1, 1])

        split_png = os.path.join(
            out_dir, f"employment_index_ces_monthly_2023m1_100_latest_{spec.name}.png"
        )
        fig.savefig(split_png, dpi=200)
        plt.close(fig)

        frame_long = df.reset_index().copy()
        frame_long["split"] = spec.name
        split_long_frames.append(frame_long)

    combined = pd.concat(split_long_frames, ignore_index=True)
    combined.to_csv(
        os.path.join(out_dir, "employment_index_ces_monthly_2023m1_100_latest_all_splits_long.csv"),
        index=False,
    )


def main() -> None:
    args = parse_args()

    ramp_csv = resolve_ramp_csv(args.ramp_csv)
    adopt, adoption_month = load_ramp_latest(ramp_csv)

    data_path = ensure_bls_data_file(args.cache_dir, args.bls_data_file, args.no_download)
    emp = load_bls_ces_all_employees(data_path=data_path, start_date=args.start_date)

    make_outputs(
        emp=emp,
        adopt=adopt,
        adoption_month=adoption_month,
        out_dir=args.outdir,
        base_date=args.base_date,
    )

    print(f"Done. Outputs written to: {os.path.abspath(args.outdir)}", file=sys.stderr)


if __name__ == "__main__":
    main()
