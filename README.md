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

## Census BTOS AI-adoption quintiles

Rank 18 broad nonfarm NAICS sectors by the latest Census BTOS current AI-use
estimate, divide them into five groups by sector count, and plot summed BLS CES
seasonally adjusted payroll employment with January 2023 = 100. Membership stays
fixed across the employment history. These descriptive groups use the recent
adoption snapshot; they do not estimate a causal effect of AI on employment.

```bash
python3 scripts/btos_ai_employment_quintiles.py
# Reproduce the saved Census/BLS source vintage without downloading again:
python3 scripts/btos_ai_employment_quintiles.py --offline
# Build quartiles from the same source vintage in a separate output directory:
python3 scripts/btos_ai_employment_quintiles.py --groups 4 --offline
```

Raw Census workbooks and the BLS API response are saved in `data/btos_ai/`.
The BLS key is read using the existing environment/.env configuration.
Use `--period 202618` to select a specific published BTOS period in the workbook.
With `--groups 4`, outputs are saved in `outputs/btos_ai_quartiles/`, with
`quartile_monthly_employment.csv` and `quartile_summary.csv` replacing the
corresponding quintile filenames.

Outputs in `outputs/btos_ai_quintiles/` include:

- `employment_index.png` and `.svg`: the five employment indexes.
- `employment_index.csv`: monthly indexes in wide format.
- `quintile_monthly_employment.csv`: monthly employment levels and indexes.
- `industry_membership.csv`: AI adoption, standard errors, quintiles, and CES IDs.
- `industry_monthly_employment.csv`: the underlying employment panel.
- `quintile_summary.csv`: employment levels, growth, and adoption ranges by group.
- `analysis.md`: methods, results, coverage, and interpretation.
- `source_metadata.json`, `bls_series_catalog.csv`, and `validation.json`: provenance and checks.

## Ramp AI-adoption quartiles and quintiles

Use the same 18 sectors and archived BLS employment vintage, ranked by Ramp's
paid AI adoption rates. Both groupings are built in one run:

```bash
python3 scripts/ramp_ai_employment_quantiles.py
# Reproduce the April 2026 full-sector snapshot used in these charts:
python3 scripts/ramp_ai_employment_quantiles.py --offline --month 2026-04-01
```

The public Ramp sector chart's full CSV is archived in `data/ramp_ai/`.
That full-sector download ends in April 2026; the August 2026 redesigned
dashboard displays only seven sectors. These charts retain all 18 industries
using April adoption and the same employment data through August 2026.

Separate charts, monthly employment, industry assignments, summaries, methods,
and source metadata are in `outputs/ramp_ai_quartiles/` and
`outputs/ramp_ai_quintiles/`. The combined summary is in
`outputs/ramp_ai_quantiles/summary.csv`. Each index uses total group payroll
employment and sets January 2023 to 100. Ramp measures paid adoption among its
business customers, which differs from the Census survey population and measure.

## RPS generative-AI adoption quartiles and quintiles

Rank the same 18 sectors using the share of employed adults aged 18–64 who report
using generative AI for their job in the Real-Time Population Survey (RPS).
The source is the GenAI Adoption Tracker by Bick, Blandin, and Deming, available
through St. Louis Fed/FRED. The latest downloaded wave is May 2026, labeled
2026 Q2 (2026-04-01) in FRED; April 1 is a quarter timestamp, not the survey month.

```bash
python3 scripts/rps_ai_employment_quantiles.py
# Reproduce the saved May 2026 / Q2 ranking and original BLS vintage:
python3 scripts/rps_ai_employment_quantiles.py --offline --quarter 2026-04-01
# Split the same ranked industries into two halves (9 sectors per half):
python3 scripts/rps_ai_employment_quantiles.py --groups 2 --offline --quarter 2026-04-01
```

The halves chart and associated data are saved separately in `outputs/rps_ai_halves/`.

The script reuses the same archived BLS CES data through August 2026 and builds
both fixed groupings with January 2023 = 100. Raw FRED tables, a structured JSON
copy, and quarterly industry adoption data are in `data/rps_ai/`. Charts, monthly
employment, industry assignments, methods, source hashes, and validation results
are in `outputs/rps_ai_quartiles/` and `outputs/rps_ai_quintiles/`; the combined
summary is `outputs/rps_ai_quantiles/summary.csv`.

RPS measures workers' self-reported use, including unpaid tools. Its population
differs from both business adoption measures and the private payroll employment
panel. These retrospective groups do not estimate a causal effect of AI on jobs.

## Quarterly industry productivity research extension

`scripts/update_qilp.py` extends the published Chicago Fed QILP history using
current BEA industry output and mapped CES payroll-hours growth. This is an
independent research extension, **not an official QILP update or exact replication**:
it assumes total hours including self-employment grow at the payroll proxy's rate,
and does not rebuild CPS microdata or the authors' X-13 seasonal adjustment.

```bash
python3 scripts/update_qilp.py
# Reproduce the archived sources without downloading:
python3 scripts/update_qilp.py --offline
```

The September 14, 2026 vintage adds 2025 Q3, 2025 Q4 and 2026 Q1 for 83
industry/aggregate rows, plus a linked BLS productivity benchmark. All 89 source
rows remain. Four rows involving agriculture and one funds/trusts row with a
negative published productivity anchor receive no extensions. Existing
`data/qilp.xlsx` remains unchanged.

Raw sources are archived in `data/qilp_update/`. Outputs in
`outputs/qilp_update_01a0a142/` include `qilp_extension.csv`, `coverage.csv`,
`ces_mapping.csv`, `overlap_validation.csv`, `source_metadata.json`, and
`methodology.md`. The methodology explains classification approximations,
historical overlap errors, aggregation, and the linked nominal-dollar series.
Actual current-vintage BEA nominal dollars are supplied separately.

`scripts/build_qilp_workbook.mjs` builds `qilp_research_extension.xlsx` using the
Codex bundled Node runtime and `@oai/artifact-tool`. Its default dependency path
can be overridden with `CODEX_WORKSPACE_NODE_MODULES`. The workbook retains
datetime quarter headers and the `Labor Productivity` and `Nominal Output` sheet
names for the existing productivity analysis script; pass its path explicitly
with `--qilp-xlsx`. Review the coverage and overlap diagnostics before using fine
industry rankings. Exclude unextended industries when building a panel with the
same membership in every quarter. The workbook's six measure sheets preserve published history;
the three added quarters are explicitly marked as research estimates.

## Productivity by RPS AI adoption halves, quartiles and quintiles

```bash
python3 scripts/rps_ai_productivity_quantiles.py
# Two groups of nine sectors:
python3 scripts/rps_ai_productivity_quantiles.py --groups 2
```

Creates two productivity charts with 2023 Q1 = 100, using the same fixed RPS
industry assignments as the employment charts. The current inputs use the May
2026 RPS wave and quarterly productivity through 2026 Q1. RPS adoption comes
from Bick, Blandin and Deming via St. Louis Fed FRED; productivity comes from
Chicago Fed QILP and the research extension above.

Each group's output and hours growth use Tornqvist weights from adjacent-quarter
nominal-output and hours shares. Output growth is inferred from the supplied
productivity and hours levels. The resulting output and hours indexes produce a
group output-per-hour index that includes industry-composition changes. All 18
sectors must be present for every quarter. Shading and dashed lines identify
the research extension after the last published QILP quarter.

Charts in PNG, SVG and PDF, chart data, industry assignments, quarterly inputs
and weights, methods, source hashes, and checks are saved under
`outputs/rps_ai_productivity/quartiles/` and
`outputs/rps_ai_productivity/quintiles/`. The halves chart and its supporting
data are saved under `outputs/rps_ai_productivity/halves/`. Use `--groups` to
select any combination of 2, 4 and 5 groups. The command uses archived inputs without
network requests. `--qilp-csv`, `--rps-raw-dir`, `--rps-quarter`, and `--outdir`
allow explicit source and output selection.

## Independent quarterly industry productivity

The independent pipeline rebuilds the entire history from primary BEA, BLS CES,
and Census CPS data. Chicago Fed QILP is not an input. The core panel has 18 broad
industries from 2006 Q2 through the latest available BEA quarter, with 2023 Q1 =
100. A separate supplement contains 38 finer industries with direct CES payroll
employment and all-employee hours matches. Those supplemental estimates exclude
self-employed labor and are explicitly labeled payroll-only proxies.

```bash
python3 scripts/fetch_independent_productivity.py --workers 8
python3 scripts/build_independent_productivity.py
python3 scripts/analyze_independent_productivity.py
python3 scripts/document_independent_productivity.py
python3 scripts/prepare_independent_workbook.py
```

For exact reconstruction from the downloaded observations, skip fetching and
pass `--offline` to the builder. It loads archived API responses and CPS files.
The source archive is about 3 GB. The pipeline requires Python with pandas,
NumPy, openpyxl for source reads, requests and matplotlib, plus R with `seasonal`
and `x13binary`. The local R library is `.research-runtime/R-library`; runtime
versions and all X-13 input/output files are recorded in the results. Census
archive formats are checked by their contents, including the January 2024 ZIP
served at a `.gz` URL.

Outputs are under `outputs/independent_productivity_01a0a142/`. The primary file
is `quarterly_industry_productivity.csv`. Also included are alternative hours
definitions, monthly inputs, the 38-industry payroll supplement, CES mappings,
national CPS validation against BLS, AI halves/quartiles/quintiles charts and a
2025 Q1 diagnostic. `scripts/build_independent_workbook.mjs` exports the Excel
workbook with the bundled Node runtime and artifact-tool dependency.

The hours measure adds CPS unincorporated self-employed and unpaid family
workers to CES employment, plus private-household employees omitted by CES,
and applies the industry's payroll workweek. Each monthly product is seasonally
adjusted with Census X-13 before taking complete three-month quarterly averages.
The panel includes payroll-only and actual self-employment-hours alternatives.
October 2025 CPS employment and actual hours equal the arithmetic mean of September
and November because the survey was not collected. CES payroll inputs remain
observed. All monthly numeric inputs are complete, and 2025 Q4 uses all three months.
Observed October CPS sample counts are zero, with the month and quarter flagged
as imputed. `october_2025_imputation.csv` records all 108 estimates and endpoints.
No other missing observations are filled. CES measures paid hours, so the result
is a labor-hours proxy rather than an exact reconstruction of BLS hours worked.

The fetcher and builder cache sources. For a genuinely new vintage, set
`PRODUCTIVITY_RAW_DIR` and `PRODUCTIVITY_OUT_DIR` to new directories under this
project and rerun the pipeline, preserving the existing vintage. Current BEA
and CES revisions then rebuild the history together. Model choices, seasonal
factors and endpoint estimates can change when new observations arrive.

The large CPS microdata archives and redundant CES bulk observations are local
caches excluded from Git. Their download URLs and SHA-256 hashes are retained
in the source manifest and sidecar metadata. After cloning, run the fetcher
before the independent builder to restore those downloads. Install the R packages
with `install.packages(c("seasonal", "x13binary"))` in R before building.

## Independent productivity across BTOS, RPS and Ramp adoption groups

After building the independent quarterly panel, reproduce all nine charts:

```bash
python3 scripts/compare_ai_adoption_productivity.py
```

The script plots quartiles, quintiles and halves for each adoption source, using
the same 18 industries, independent hours/output data, and a common vertical
scale. All indexes equal 100 in 2023 Q1 and extend through 2026 Q1 without missing
quarters. October 2025 retains the CPS interpolation described above.

Rankings reproduce BTOS period 202618 (August 10–23, 2026), the May 2026 RPS wave,
and Ramp's complete April 2026 sector download. Membership stays fixed. Group
output uses adjacent-quarter nominal-value-added shares; group hours are summed.
The rankings differ in date, population and definition, so comparisons are
descriptive rather than estimates of an AI treatment effect.

Outputs are in `outputs/ai_adoption_productivity_comparison_01a0a142/`: a nine-panel
overview, nine individual PNG/SVG/PDF charts, a combined PDF, chart data, industry
memberships, endpoint summaries, methods, input hashes, validation, and a ZIP
containing all results. Generated outputs follow the repository's existing
Git exclusion convention.

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

## Payroll employment across BTOS, RPS and Ramp adoption groups

Reproduce quartiles, quintiles and halves for each of the three adoption sources:

```bash
python3 scripts/compare_ai_adoption_employment.py
```

The nine-chart comparison uses the same 18 private industries and archived BLS
CES seasonally adjusted payroll employment in every panel. It sums constituent
industry employment, averages all three months of each quarter, and sets
**2023 Q1 average = 100**. The saved vintage covers 14 complete quarters through
2026 Q2. The monthly companion extends through August 2026 using the same
quarterly-average base. No employment observations are interpolated or forecast;
July–August 2026 are not treated as a complete quarter.

Fixed rankings reproduce BTOS period 202618 (August 10–23, 2026), the May 2026
RPS wave via St. Louis Fed/FRED, and Ramp's complete April 2026 sector download.
Quartiles contain 5/4/4/5 industries, quintiles 4/3/4/3/4, and halves 9/9.
These are descriptive industry comparisons, with different adoption measures
and ranking dates. RPS is the Bick–Blandin–Deming survey; Chicago Fed QILP and
the independent productivity estimates are not inputs to these payroll charts.

Outputs in `outputs/ai_adoption_employment_comparison/` include the overview and
nine individual PNG/SVG/PDF charts, a combined PDF, monthly overview, quarterly
and monthly chart data, industry memberships and baseline employment weights,
endpoint summaries, methods, input hashes, validation, and a ZIP of the results.
Validation checks complete coverage, base normalization, sector-total
reconciliation, the equivalent employment-weighted index formula, and agreement
with the earlier monthly employment levels. Use `--outdir` to select another
destination. The command uses archived sources and makes no network requests.

The companion Excel workbook consolidates the quarterly indexes, detailed
quarterly and monthly observations, industry assignments, CES inputs, and
source notes. Its formulas reproduce the chart indexes and baseline weights.
Build it after the comparison script with the Codex bundled Node runtime:

```bash
node scripts/build_ai_employment_workbook.mjs
```

The builder uses `@oai/artifact-tool` from the bundled dependency directory;
set `CODEX_WORKSPACE_NODE_MODULES` to override that location. An optional first
argument selects the output directory. The requested
`outputs/ai_adoption_employment_comparison/ai_adoption_payroll_employment.xlsx`
is versioned explicitly; other generated charts, previews and data exports keep
the repository's usual ignore behavior.
