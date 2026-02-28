#!/usr/bin/env python3
"""
Recompute "AI affected" (most/least AI-intensity quartiles) job-growth charts using BLS CES bulk files.

Outputs (in --outdir):
  - ai_intensity_quartile_membership.csv
  - most_affected_quartile_timeseries.csv
  - least_affected_quartile_timeseries.csv
  - most_affected_quartile_indexed_level_timeseries.csv
  - least_affected_quartile_indexed_level_timeseries.csv
  - quartile_indexed_level_combined_from_nov2022.csv
  - most_affected_quartile_sector_inputs.csv
  - least_affected_quartile_sector_inputs.csv
  - plot_most_affected_quartile.png
  - plot_least_affected_quartile.png
  - plot_most_affected_quartile_indexed_level.png
  - plot_least_affected_quartile_indexed_level.png
  - plot_quartile_indexed_level_combined_from_nov2022.png

Method:
  - Use CES All Employees (AE), seasonally adjusted series (CES...0001).
  - Convert levels from thousands to jobs (x 1,000).
  - Trailing 3-month average monthly job change:
        avg3_change_jobs[t] = (emp_jobs[t] - emp_jobs[t-3]) / 3

Data source:
  - https://download.bls.gov/pub/time.series/ce/
    - ce.data.01a.CurrentSeasAE (seasonally adjusted, all employees, current)
    - (optional) ce.series (not required if you hardcode series IDs below)

Notes:
  - CES is a *nonfarm* payroll survey. Agriculture (NAICS 11) is not covered and is excluded.
"""

from __future__ import annotations

import argparse
import csv
import io
import os
import sys
import textwrap
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, Iterable, List, Tuple

import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import requests


BLS_BASE = "https://download.bls.gov/pub/time.series/ce"


@dataclass(frozen=True)
class Sector:
    group: str  # "most_affected" or "least_affected"
    naics: str
    sector_name: str
    series_id: str  # CES series for All Employees, thousands, SA


def get_quartile_membership() -> List[Sector]:
    """
    Union of sectors in the lowest and highest AI-intensity quartiles in 2018/2022 (Table 2),
    mapped to CES series IDs.

    Most affected (highest AI intensity quartile union):
      - 51 Information
      - 52 Finance and insurance
      - 53 Real estate and rental and leasing
      - 54 Professional, scientific, and technical services
      - 55 Management of companies and enterprises
      - 61 Educational services

    Least affected (lowest AI intensity quartile union), excluding NAICS 11 (not covered by CES):
      - 21 Mining, extraction, and support activities (proxy: Mining and logging)
      - 23 Construction
      - 48-49 Transportation and warehousing
      - 71 Arts, entertainment, and recreation
      - 72 Accommodation and food services
      - 81 Other services (except public administration)
    """
    sectors: List[Sector] = [
        # Most affected / highest AI intensity
        Sector("most_affected", "51", "Information", "CES5000000001"),
        Sector("most_affected", "52", "Finance and insurance", "CES5552000001"),
        Sector("most_affected", "53", "Real estate and rental and leasing", "CES5553000001"),
        Sector("most_affected", "54", "Professional, scientific, and technical services", "CES6054000001"),
        Sector("most_affected", "55", "Management of companies and enterprises", "CES6055000001"),
        Sector("most_affected", "61", "Educational services (private)", "CES6561000001"),

        # Least affected / lowest AI intensity
        Sector("least_affected", "21", "Mining, extraction, and support activities (proxy: Mining and logging)", "CES1000000001"),
        Sector("least_affected", "23", "Construction", "CES2000000001"),
        Sector("least_affected", "48-49", "Transportation and warehousing", "CES4300000001"),
        Sector("least_affected", "71", "Arts, entertainment, and recreation", "CES7071000001"),
        Sector("least_affected", "72", "Accommodation and food services", "CES7072000001"),
        Sector("least_affected", "81", "Other services (except public administration)", "CES8000000001"),
    ]
    return sectors


def download_if_missing(url: str, path: str, *, chunk_size: int = 1 << 20) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if os.path.exists(path) and os.path.getsize(path) > 0:
        return
    print(f"Downloading {url} -> {path}", file=sys.stderr)
    with requests.get(url, stream=True, timeout=120) as r:
        r.raise_for_status()
        with open(path, "wb") as f:
            for chunk in r.iter_content(chunk_size=chunk_size):
                if chunk:
                    f.write(chunk)


def load_ce_data_current_seas_ae(path: str, series_ids: Iterable[str], start_year: int) -> pd.DataFrame:
    """
    Reads BLS bulk file ce.data.01a.CurrentSeasAE and returns a tidy dataframe:

      date (Timestamp at first of month)
      series_id
      value_thousands (float)

    Only M01..M12 are kept (drops annual averages like M13).
    """
    wanted = set(series_ids)

    rows = []
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        reader = csv.reader(f, delimiter="\t")
        for parts in reader:
            if not parts:
                continue
            # BLS format: series_id, year, period, value, footnote_codes
            try:
                sid, year_str, period, value_str = parts[0], parts[1], parts[2], parts[3]
            except Exception:
                continue

            if sid not in wanted:
                continue
            year = int(year_str)
            if year < start_year:
                continue
            if not period.startswith("M") or period == "M13":
                continue
            month = int(period[1:])
            # first-of-month timestamp
            date = pd.Timestamp(year=year, month=month, day=1)
            try:
                val = float(value_str)
            except ValueError:
                continue
            rows.append((date, sid, val))

    df = pd.DataFrame(rows, columns=["date", "series_id", "value_thousands"])
    df = df.sort_values(["series_id", "date"]).reset_index(drop=True)
    return df


def compute_trailing_3mo_avg_change_jobs(levels_jobs: pd.Series) -> pd.Series:
    return (levels_jobs - levels_jobs.shift(3)) / 3.0


def make_plot(df_group: pd.DataFrame, title: str, out_path: str) -> None:
    """
    df_group columns: date, avg3_change_jobs
    """
    fig = plt.figure(figsize=(11, 5.5))
    ax = plt.gca()
    ax.plot(df_group["date"], df_group["avg3_change_jobs"])
    ax.axhline(0, linewidth=1)
    ax.set_title(title)
    ax.set_xlabel("Month")
    ax.set_ylabel("Avg monthly job change over last 3 months (jobs)")
    fig.tight_layout()
    fig.savefig(out_path, dpi=200)
    plt.close(fig)


def add_level_index(df_group: pd.DataFrame, base_date: pd.Timestamp) -> pd.DataFrame:
    """
    Adds an index column where total employment level at base_date is 100 for each group.
    """
    base_levels = (
        df_group.loc[df_group["date"] == base_date, ["group", "total_employment_jobs"]]
                .rename(columns={"total_employment_jobs": "base_employment_jobs"})
    )
    missing_groups = sorted(set(df_group["group"]) - set(base_levels["group"]))
    if missing_groups:
        missing = ", ".join(missing_groups)
        raise ValueError(f"Missing base date {base_date.date()} for group(s): {missing}")
    if (base_levels["base_employment_jobs"] == 0).any():
        raise ValueError(f"Base employment is zero for date {base_date.date()}, cannot index levels.")

    out = df_group.merge(base_levels, on="group", how="left")
    out["level_index_nov2022_100"] = (out["total_employment_jobs"] / out["base_employment_jobs"]) * 100.0
    return out


def make_indexed_level_plot(df_group: pd.DataFrame, title: str, out_path: str, base_date: pd.Timestamp) -> None:
    """
    df_group columns: date, level_index_nov2022_100
    """
    fig = plt.figure(figsize=(11, 5.5))
    ax = plt.gca()
    ax.plot(df_group["date"], df_group["level_index_nov2022_100"])
    ax.axhline(100, linewidth=1)
    ax.axvline(base_date, linewidth=1, linestyle="--", color="gray")
    ax.set_title(title)
    ax.set_xlabel("Month")
    ax.set_ylabel("Employment level index (Nov 2022 = 100)")
    fig.tight_layout()
    fig.savefig(out_path, dpi=200)
    plt.close(fig)


def make_combined_indexed_level_plot(df_group: pd.DataFrame, out_path: str, base_date: pd.Timestamp) -> None:
    """
    Overlays most_affected and least_affected indexed levels in one chart from base_date onward.
    """
    d = df_group[df_group["date"] >= base_date].copy()
    label_map = {
        "most_affected": "Most AI-intensive quartile",
        "least_affected": "Least AI-intensive quartile",
    }

    fig = plt.figure(figsize=(11, 5.5))
    ax = plt.gca()
    for grp in ["most_affected", "least_affected"]:
        g = d[d["group"] == grp]
        ax.plot(g["date"], g["level_index_nov2022_100"], label=label_map[grp])
    ax.axhline(100, linewidth=1)
    ax.axvline(base_date, linewidth=1, linestyle="--", color="gray")
    ax.set_title("Employment level index by quartile (from Nov 2022)\nNov 2022 = 100")
    ax.set_xlabel("Month")
    ax.set_ylabel("Employment level index (Nov 2022 = 100)")
    ax.legend()
    fig.tight_layout()
    fig.savefig(out_path, dpi=200)
    plt.close(fig)


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Recompute AI-intensity quartile job-growth charts from BLS CES bulk files.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent(
            """\
            Example:
              python recompute_ai_quartile_growth.py --outdir outputs --start 2016

            Tip:
              Set --start to 2016 so you can compute the first 3-month change values for 2017-01.
            """
        ),
    )
    ap.add_argument("--outdir", default="outputs", help="Output directory")
    ap.add_argument("--cache", default="bls_cache", help="Directory to cache downloaded BLS files")
    ap.add_argument("--start", type=int, default=2016, help="First year to load (use 2016 to compute 2017-01 changes)")
    ap.add_argument(
        "--data-file",
        default="",
        help=(
            "Path to a local copy of the BLS CES bulk file ce.data.01a.CurrentSeasAE. "
            "If provided, the script will NOT attempt to download from download.bls.gov."
        ),
    )
    ap.add_argument(
        "--no-download",
        action="store_true",
        help="Fail if the BLS bulk file is missing instead of attempting to download it.",
    )
    args = ap.parse_args()

    outdir = args.outdir
    os.makedirs(outdir, exist_ok=True)

    # Membership
    membership = get_quartile_membership()
    df_membership = pd.DataFrame([s.__dict__ for s in membership])
    df_membership.to_csv(os.path.join(outdir, "ai_intensity_quartile_membership.csv"), index=False)

    # Resolve / acquire the data file
    if args.data_file:
        data_path = os.path.abspath(os.path.expanduser(args.data_file))
    else:
        data_path = os.path.join(args.cache, "ce.data.01a.CurrentSeasAE")

    if not os.path.exists(data_path):
        if args.no_download or args.data_file:
            raise FileNotFoundError(
                f"BLS CES bulk file not found at: {data_path}. "
                "Download it from https://download.bls.gov/pub/time.series/ce/ce.data.01a.CurrentSeasAE "
                "and re-run with --data-file /path/to/ce.data.01a.CurrentSeasAE."
            )
        data_url = f"{BLS_BASE}/ce.data.01a.CurrentSeasAE"
        download_if_missing(data_url, data_path)

    # Load required series
    series_ids = [s.series_id for s in membership]
    df = load_ce_data_current_seas_ae(data_path, series_ids=series_ids, start_year=args.start)

    # Map sector names
    sid_to_sector = {s.series_id: s for s in membership}
    df["sector_name"] = df["series_id"].map(lambda x: sid_to_sector[x].sector_name)
    df["group"] = df["series_id"].map(lambda x: sid_to_sector[x].group)
    df["naics"] = df["series_id"].map(lambda x: sid_to_sector[x].naics)

    # Convert to jobs
    df["employment_jobs"] = df["value_thousands"] * 1000.0

    # Sector-level 3mo avg change
    df["avg3_change_jobs"] = (
        df.sort_values(["series_id", "date"])
          .groupby("series_id")["employment_jobs"]
          .transform(compute_trailing_3mo_avg_change_jobs)
    )

    # Sector-level outputs
    for grp in ["most_affected", "least_affected"]:
        df_grp_sectors = df[df["group"] == grp].copy()
        df_grp_sectors = df_grp_sectors[[
            "date", "group", "naics", "sector_name", "series_id",
            "employment_jobs", "avg3_change_jobs"
        ]].sort_values(["date", "sector_name"])
        df_grp_sectors.to_csv(os.path.join(outdir, f"{grp}_quartile_sector_inputs.csv"), index=False)

    # Group-level aggregation
    df_group = (
        df.groupby(["group", "date"], as_index=False)
          .agg(total_employment_jobs=("employment_jobs", "sum"))
          .sort_values(["group", "date"])
    )
    df_group["avg3_change_jobs"] = (
        df_group.groupby("group")["total_employment_jobs"]
                .transform(compute_trailing_3mo_avg_change_jobs)
    )
    base_date = pd.Timestamp(year=2022, month=11, day=1)
    df_group = add_level_index(df_group, base_date=base_date)

    # Group-level outputs + plots
    for grp, title in [
        ("most_affected", "Most AI‑intensive quartile (union of 2018 & 2022)"),
        ("least_affected", "Least AI‑intensive quartile (union of 2018 & 2022)"),
    ]:
        d = df_group[df_group["group"] == grp].copy()
        d.to_csv(os.path.join(outdir, f"{grp}_quartile_timeseries.csv"), index=False)

        plot_path = os.path.join(outdir, f"plot_{grp}_quartile.png")
        make_plot(d, f"Avg monthly job growth (last 3 months)\n{title}", plot_path)

        d[["group", "date", "total_employment_jobs", "base_employment_jobs", "level_index_nov2022_100"]] \
            .to_csv(os.path.join(outdir, f"{grp}_quartile_indexed_level_timeseries.csv"), index=False)
        indexed_plot_path = os.path.join(outdir, f"plot_{grp}_quartile_indexed_level.png")
        make_indexed_level_plot(
            d,
            f"Employment level index (Nov 2022 = 100)\n{title}",
            indexed_plot_path,
            base_date=base_date,
        )

    combined = df_group[df_group["date"] >= base_date][["group", "date", "level_index_nov2022_100"]].copy()
    combined.to_csv(os.path.join(outdir, "quartile_indexed_level_combined_from_nov2022.csv"), index=False)
    make_combined_indexed_level_plot(
        df_group,
        os.path.join(outdir, "plot_quartile_indexed_level_combined_from_nov2022.png"),
        base_date=base_date,
    )

    print(f"Done. Wrote outputs to: {os.path.abspath(outdir)}", file=sys.stderr)


if __name__ == "__main__":
    main()
