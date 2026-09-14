#!/usr/bin/env python3
"""Helpers for loading BLS API v2 time-series data."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Iterable, List, Tuple

import pandas as pd
import requests


BLS_V2_TIMESERIES_URL = "https://api.bls.gov/publicAPI/v2/timeseries/data/"
MAX_SERIES_PER_REQUEST = 50
MAX_YEARS_PER_REQUEST_WITH_KEY = 20


def _chunked(items: List[str], size: int) -> Iterable[List[str]]:
    for idx in range(0, len(items), size):
        yield items[idx : idx + size]


def _year_windows(start_year: int, end_year: int, window_size: int) -> Iterable[Tuple[int, int]]:
    year = start_year
    while year <= end_year:
        stop = min(year + window_size - 1, end_year)
        yield year, stop
        year = stop + 1


def _read_key_from_env_file(env_file: Path, key_name: str) -> str:
    if not env_file.exists():
        return ""

    for raw_line in env_file.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        if key.strip() != key_name:
            continue
        return value.strip().strip("'").strip('"')
    return ""


def resolve_bls_api_key(explicit_key: str = "", env_var: str = "BLS_API_KEY") -> str:
    """
    Resolve BLS API key from:
      1) explicit function argument
      2) process environment variable `BLS_API_KEY`
      3) .env file in cwd or repo root
    """
    if explicit_key and explicit_key.strip():
        return explicit_key.strip()

    from_env = os.getenv(env_var, "").strip()
    if from_env:
        return from_env

    candidate_files = [
        Path.cwd() / ".env",
        Path(__file__).resolve().parents[1] / ".env",
    ]
    for env_file in candidate_files:
        value = _read_key_from_env_file(env_file, env_var)
        if value:
            return value

    raise ValueError(
        "BLS API key is required for BLS API v2. Set BLS_API_KEY in environment/.env "
        "or pass --bls-api-key."
    )


def fetch_ces_monthly_series(
    series_ids: Iterable[str],
    start_year: int,
    end_year: int,
    api_key: str,
    timeout: int = 120,
) -> pd.DataFrame:
    """
    Fetch monthly CES series from BLS API v2.

    Returns dataframe with:
      - date (Timestamp)
      - series_id
      - value_thousands
    """
    if start_year > end_year:
        raise ValueError(f"start_year ({start_year}) cannot be greater than end_year ({end_year}).")
    if not api_key:
        raise ValueError("api_key is required.")

    unique_series = sorted(set(series_ids))
    rows = []

    for series_chunk in _chunked(unique_series, MAX_SERIES_PER_REQUEST):
        for window_start, window_end in _year_windows(
            start_year, end_year, MAX_YEARS_PER_REQUEST_WITH_KEY
        ):
            payload = {
                "seriesid": series_chunk,
                "startyear": str(window_start),
                "endyear": str(window_end),
                "registrationkey": api_key,
                "annualaverage": False,
            }
            response = requests.post(BLS_V2_TIMESERIES_URL, json=payload, timeout=timeout)
            response.raise_for_status()
            body = response.json()

            if body.get("status") != "REQUEST_SUCCEEDED":
                message = "; ".join(body.get("message", [])) if body.get("message") else str(body)
                raise RuntimeError(f"BLS API request failed: {message}")

            for series in body.get("Results", {}).get("series", []):
                sid = series.get("seriesID", "")
                for obs in series.get("data", []):
                    period = obs.get("period", "")
                    if not period.startswith("M") or period == "M13":
                        continue

                    year = int(obs["year"])
                    month = int(period[1:])
                    value_str = str(obs.get("value", "")).replace(",", "")
                    try:
                        value = float(value_str)
                    except ValueError:
                        continue
                    rows.append((pd.Timestamp(year=year, month=month, day=1), sid, value))

    if not rows:
        raise ValueError("No monthly data was returned by BLS API.")

    df = pd.DataFrame(rows, columns=["date", "series_id", "value_thousands"])
    df = df.drop_duplicates(subset=["series_id", "date"], keep="last")
    df = df.sort_values(["series_id", "date"]).reset_index(drop=True)
    return df
