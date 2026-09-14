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

## BLS annual detailed-industry productivity by RPS adoption

```bash
python3 scripts/rps_ai_bls_annual_productivity.py
```

Uses the BLS `labor-productivity-detailed-industries.xlsx` workbook (August 26,
2026 release) for annual observations from 2023 through 2025, with **2023 annual
average = 100**. The source workbook and metadata are archived in
`data/bls_annual_productivity/`, and the RPS source is in
`data/rps_ai/fred_series.json`. Updated workbooks can be downloaded from the
[BLS tables page](https://www.bls.gov/productivity/tables/). The command uses
archived inputs without network requests; `--bls-xlsx`, `--rps-raw-dir`, `--rps-quarter`, `--end-year`, and
`--outdir` select other inputs or output locations.

The default balanced panel contains 45 nonoverlapping BLS industry series mapped
to 15 RPS sectors. Construction, management of companies, and education have no
productivity series in this workbook. Quartiles, quintiles, and halves are
recomputed among the covered sectors using the May 2026 RPS adoption wave.
Within each sector, normalized industry productivity indexes use fixed 2023
hours weights; sectors receive equal weights within their adoption group.
Service-sector coverage can be narrow, so these are descriptive composites of
covered industries, not official BLS aggregates or whole-sector estimates.

`outputs/rps_ai_bls_annual_productivity/` contains the combined chart in PNG,
SVG, and PDF; separate charts for all three splits; annual index data; sector and
industry assignments and weights; a row-selection audit; source hashes; and
`analysis.md` with methods and coverage. Validation checks source growth rates,
complete annual coverage, base normalization, and the aggregation weights.
