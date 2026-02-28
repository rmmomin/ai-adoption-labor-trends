# employment-ai

Reproducible employment analysis scripts using U.S. BLS CES data and AI-adoption groupings.

## Directory organization

```text
employment-ai/
  data/                               # local input files
    qilp.xlsx
  scripts/                            # runnable analysis scripts
    recompute_ai_quartile_growth.py
    reproduce_ces_monthly_employment_index.py
    reproduce_productivity_levels_quantiles_from_raw.py
  outputs/                            # generated result files (gitignored)
  bls_cache/                          # cached BLS bulk data (gitignored)
  requirements.txt
```

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Script 1: AI-intensity quartile growth recomputation

Purpose:
- Recompute "most AI-intensive quartile" vs "least AI-intensive quartile" CES employment growth and indexed-level charts.

Run:

```bash
python3 scripts/recompute_ai_quartile_growth.py \
  --outdir outputs/quartile_growth \
  --start 2016
```

Offline/no-download run:

```bash
python3 scripts/recompute_ai_quartile_growth.py \
  --outdir outputs/quartile_growth \
  --start 2016 \
  --data-file /path/to/ce.data.01a.CurrentSeasAE \
  --no-download
```

## Script 2: CES employment index by AI-adoption quantiles

Purpose:
- Build monthly employment index series for multiple AI-adoption splits (10vs90, 25vs75, 33vs66, BottomvsTop50).

Required input:
- Ramp monthly adoption CSV with `Date` and `naics_sector_*_ai_user_share` columns.

Recommended location:
- `data/ramp-data-wQR5S(1).csv` (or pass an explicit `--ramp-csv` path).

Run:

```bash
python3 scripts/reproduce_ces_monthly_employment_index.py \
  --ramp-csv data/ramp-data-wQR5S\(1\).csv \
  --outdir outputs/ces_monthly_employment_ai_quantiles
```

If `--ramp-csv` is omitted, the script searches for:

- `ramp-data-wQR5S(1).csv`
- `ramp-data-wQR5S.csv`
- `data/ramp-data-wQR5S(1).csv`
- `data/ramp-data-wQR5S.csv`

Common options:

- `--cache-dir bls_cache`
- `--bls-data-file /path/to/ce.data.01a.CurrentSeasAE`
- `--no-download`
- `--start-date 2023-01-01`
- `--base-date 2023-01-01`

Primary outputs:

- `ai_quantile_splits_membership_ces_employment_monthly_latest.csv`
- `employment_index_ces_monthly_2023m1_100_latest_10vs90.csv/.png`
- `employment_index_ces_monthly_2023m1_100_latest_25vs75.csv/.png`
- `employment_index_ces_monthly_2023m1_100_latest_33vs66.csv/.png`
- `employment_index_ces_monthly_2023m1_100_latest_BottomvsTop50.csv/.png`
- `employment_index_ces_monthly_2023m1_100_latest_all_splits_long.csv`

## Script 3: Productivity level index by AI-adoption quantiles

Purpose:
- Reproduce QILP labor-productivity level indexes (rebased to 2023Q1=100) for p10/p90, p25/p75, and p33/p66 AI-adoption splits.

Required inputs:
- `data/qilp.xlsx` (included in this repo)
- Ramp monthly adoption CSV (`Date` and `naics_sector_*_ai_user_share`)

Run:

```bash
python3 scripts/reproduce_productivity_levels_quantiles_from_raw.py \
  --qilp-xlsx data/qilp.xlsx \
  --ramp-csv data/ramp-data-wQR5S\(1\).csv \
  --outdir outputs/productivity_levels_quantiles_from_2023Q1
```

If `--ramp-csv` is omitted, the script searches for:

- `ramp-data-wQR5S(1).csv`
- `ramp-data-wQR5S.csv`
- `data/ramp-data-wQR5S(1).csv`
- `data/ramp-data-wQR5S.csv`

Common options:

- `--base-date 2023-01-01`

Primary outputs:

- `productivity_levels_index_2023Q1_100_p10_p90_from_2023Q1.csv/.png`
- `productivity_levels_index_2023Q1_100_p25_p75_from_2023Q1.csv/.png`
- `productivity_levels_index_2023Q1_100_p33_p66_from_2023Q1.csv/.png`
- `productivity_levels_index_2023Q1_100_all_quantile_splits_from_2023Q1.csv`
- `ai_quantile_membership_latestRampMonth.csv`
