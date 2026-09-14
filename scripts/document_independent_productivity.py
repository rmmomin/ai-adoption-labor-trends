#!/usr/bin/env python3
"""Write the dataset's methods, data dictionary and diagnostic summary."""
import json
import numpy as np
import pandas as pd
from independent_productivity_inputs import OUT, BEA_URL, BLS_URL, CPS_URL


def main():
    checks=json.loads((OUT/"validation.json").read_text())
    diag=pd.read_csv(OUT/"2025q1_comparison_with_previous_chart.csv")
    diag["qoq_pct"]=100*np.expm1(diag.productivity_growth_log_pct/100)
    diag["previous_qoq_pct"]=100*np.expm1(diag.old_qilp_growth_annualized_log_pct/400)
    summary=pd.read_csv(OUT/"ai_group_summary.csv")
    half=summary[summary.groups.eq(2)].set_index("group")
    text=f"""# Independent quarterly industry productivity

The dataset reconstructs 18 broad U.S. nonfarm private industries from {checks['first_quarter']} through {checks['last_quarter']}: {checks['quarters']} quarters and 1,440 industry-quarter observations. A supplement contains 38 more detailed industry series based on payroll hours. Chicago Fed QILP observations do not enter either construction.

## What the rebuild changes

The higher-AI-adoption half gains {half.loc[2,'growth_since_2023q1_pct']:.2f}% from 2023 Q1 through 2026 Q1; the lower-adoption half gains {half.loc[1,'growth_since_2023q1_pct']:.2f}%. Each contains nine sectors ranked using the May 2026 RPS wave. Quartile and quintile charts are also supplied.

The 2025 Q1 decline is much smaller in the higher-adoption half than in the previous chart. The lower-adoption half still falls under every denominator examined. Rebuilding the data does not justify deleting that decline.

| Hours measure | Lower-adoption half: 2025 Q1 change | Higher-adoption half: 2025 Q1 change |
|---|---:|---:|
"""
    names={"all_workers":"Main CES+CPS workweek proxy, own X-13", "payroll_only":"Payroll only, own X-13", "bls_sa_payroll":"Payroll only, BLS seasonal adjustment", "cps_actual_self_hours":"CES plus reported CPS nonpayroll hours, own X-13"}
    for variant,label in names.items():
        d=diag[diag.variant.eq(variant)].set_index("group")
        text+=f"| {label} | {d.loc[1,'qoq_pct']:+.3f}% | {d.loc[2,'qoq_pct']:+.3f}% |\n"
    old=diag[diag.variant.eq("all_workers")].set_index("group")
    text+=f"| Previous QILP-based chart | {old.loc[1,'previous_qoq_pct']:+.3f}% | {old.loc[2,'previous_qoq_pct']:+.3f}% |\n"
    text+="""
Changes in this table are ordinary quarter-over-quarter percentages, not annualized rates. The higher-half sign is sensitive to the denominator and seasonal adjustment. The lower-half output declines approximately 0.73% in log terms in 2025 Q1, so its productivity weakness is not solely an hours-data phenomenon.

This comparison does not identify a specific error in the Chicago Fed dataset. Input vintages, the hours construction, seasonal adjustment, and group aggregation differ. In particular, the new series uses current CES history and one BEA workbook vintage. A controlled attribution of a QILP error would require the authors' exact original source vintages, mappings and adjustment specifications. BLS also reported an aggregate productivity decline for 2025 Q1 in its contemporaneous release.

## Primary inputs

1. **Output:** BEA GDP by Industry, table TVA103-Q (seasonally adjusted real value-added quantity indexes) and TVA105-Q (nominal value added in millions of dollars at annual rates). Use the currently downloaded workbook's entire history. Never sum chained-dollar real output across industries.
2. **Payroll employment and workweeks:** BLS CES all-employee employment (data type 01) and average weekly hours (02). Download both CEU, not seasonally adjusted, and CES, seasonally adjusted. BLS API observations supply the full 2006 onward history; bulk catalogs validate titles, identifiers and scope. The archived bulk files may predate the API observations and do not override them.
3. **Nonpayroll workers:** Census Basic Monthly CPS public-use records. The parser selects employed people aged 16+ using PEMLR 1 or 2 and the composite PWCMPWGT weight divided by 10,000. PEIO1ICD assigns primary-job industry. PEIO1COW 7 identifies unincorporated self-employment and 8 unpaid family work. Incorporated self-employed people are not added, since they belong to the payroll-worker concept. CPS private-household wage/salary workers, excluded from CES, are added to other services. Secondary jobs outside the primary-job classification are not separately added.

## Hours calculation

For industry i and month m, construct payroll weekly hours from employment E and the all-employee workweek A:

`P_im = 1,000 × CES employment in thousands × CES average weekly hours`.

The main unadjusted hours proxy is:

`H_im = (payroll employment + unincorporated self-employed + unpaid family workers + household employees) × sector payroll workweek`.

For composite industries the workweek equals their reconstructed payroll weekly hours divided by payroll employment. Most sectors use direct series. Finance uses financial-activities hours less real-estate/rental/leasing hours. Real estate combines NAICS 531, 532 and 533, with 532's workweek assigned to the small 533 component. Private education uses education/health hours less health/social-assistance hours. The complete signed mapping is in `ces_industry_mapping.csv`.

The main proxy assigns the payroll workweek to nonpayroll workers. An alternative adds CPS-reported actual primary-job hours for those workers instead. CES payroll hours remain a paid-hours measure in both versions; the unpublished paid-to-worked adjustment used in official BLS productivity is unavailable.

## Seasonal adjustment and quarterly conversion

Apply Census X-13 to each independently constructed monthly hours series, using a log transform, automatic ARIMA selection and outlier detection, and X-11 decomposition. The final seasonally adjusted series retains the irregular component; it is not a trend-cycle or smoothed productivity estimate. No trading-day or Easter regressors are used because these are reference-week labor observations. Automatic estimation permits 2,000 iterations. A standard airline-model fallback is coded for nonconvergence, but all 54 series converged automatically in this run and no fallback was used.

The seasonal estimation sample is March 2006 through March 2026, matching the output endpoint. Every accepted quarter has all three monthly CES observations. Quarter hours equal 52 times the mean of the three adjusted monthly weekly-hours observations. A constant 52-week annualization is used throughout; its level cancels in the normalized productivity index. March is the first month with all-employee CES workweeks, so 2006 Q1 is not fabricated from one month. The full panel begins in 2006 Q2.

October 2025 CPS data were not collected during the federal shutdown. For each broad industry and worker category, set the October CPS employment estimate to `(September employment + November employment) / 2`, using nonseasonally adjusted levels. Apply the same arithmetic midpoint to CPS actual weekly hours used in the alternative denominator. This fills a single missing calendar month. It assumes a linear path between the two observed endpoints and does not estimate an October-specific seasonal pattern separately.

CES October payroll employment and workweeks are observed. Calculate the main October hours proxy from observed CES payroll employment plus interpolated CPS nonpayroll and household employment, multiplied by the observed CES workweek. Then apply X-13 and average all three months for 2025 Q4. Interpolation can influence nearby seasonal-adjustment estimates as well as 2025 Q4.

All monthly numeric inputs are complete for all 18 industries. October's observed CPS sample-record counts are zero because no survey was collected; zero here does not mean zero employment. The month and 2025 Q4 remain flagged as imputed, while raw survey files and cells retain the actual collection history. The audit table `october_2025_imputation.csv` contains all 108 CPS field-by-industry estimates with their September and November endpoints. Quarterly sample counts are calendar-month averages, including October's zero observed count.

Annual CPS population-control updates remain in the underlying survey weights. There is no publicly identified industry-specific correction applied here. Broad sector aggregation and the payroll-only comparisons help evaluate sensitivity; they do not eliminate all household-survey measurement error.

## Productivity and aggregation

For each industry, divide the BEA real-value-added quantity index by annualized hours, then rebase the ratio to 2023 Q1 = 100. Store quarterly output, hours and productivity log changes as `100 × Δln`, and annualized productivity growth as `100 × [exp(4 × Δln productivity) − 1]`.

For the AI groups and the nonfarm private aggregate, chain output growth with the average of adjacent-quarter nominal-value-added shares (Törnqvist weights). Sum industry hours directly because hours are additive. Divide the resulting output index by the summed-hours index. The previous group charts instead approximated hours aggregation with Törnqvist hours weights. Both methods include within-group industry-composition effects.

RPS membership is fixed at the May 2026 adoption ranking, which FRED labels 2026 Q2. The grouping is retrospective and cannot identify a causal AI effect. The RPS comes from Bick, Blandin and Deming and is distributed through the GenAI Adoption Tracker and St. Louis Fed FRED.

The 38-industry supplement uses direct, similarly scoped CES employment/AWH pairs and BLS seasonal adjustment. It excludes nonpayroll labor and is an output-per-payroll-hour proxy. Missing workweeks and mismatched definitions are excluded rather than silently replaced. Its 38 rows include some aggregates, so they must not be summed together or added to the broad panel.

## Validation and limits

- All 247 monthly CPS national employment totals agree with BLS series LNU02000000 to its published rounding precision. This validates extraction and weighting at the national level; it does not imply that every industry estimate is precise.
- All 18 broad industries have observations in every one of the 80 quarters, and every index equals 100 in 2023 Q1.
- All monthly numeric inputs and all quarterly output, hours and productivity levels are complete. Every 2025 Q4 industry has three monthly inputs. Every interpolated October CPS employment/hour estimate equals its September-November midpoint.
- Industry productivity changes reconcile algebraically to output less hours changes. Group output and hours indexes reconcile independently to group productivity.
- Broad-industry nominal output reconciles with BEA private output less agriculture within the source table's rounding precision.
- Raw file hashes, dictionary positions, per-month sample counts, X-13 input specifications, model output and runtime versions are retained.
- The Excel core productivity formulas were checked against the Python results, and the workbook was scanned for formula errors.

The estimates are research measures, not official BLS productivity. They retain survey sampling error, paid-hours versus worked-hours differences, revisions and endpoint seasonal-adjustment uncertainty. Real estate includes imputed owner-occupied rent, so its output-per-hour measure has a distinctive interpretation. Nonfarm private output includes nonprofits, whereas the BLS nonfarm-business benchmark excludes certain nonprofit and household production and includes government enterprises. Education and healthcare are private on the output/CES side; CPS filters exclude government workers from additions.

## Reproduction and files

Run `fetch_independent_productivity.py`, then `build_independent_productivity.py`, `analyze_independent_productivity.py`, `document_independent_productivity.py`, and `prepare_independent_workbook.py`. `build_independent_workbook.mjs` exports Excel. For the archived vintage, skip the fetcher and use `--offline` with the builder. Dependencies and commands are described in the repository README.

The cache is intentional. To fetch a new vintage without mixing or overwriting the old one, set `PRODUCTIVITY_RAW_DIR` and `PRODUCTIVITY_OUT_DIR` to new directories under the project before running the pipeline. Preserve the R package versions listed in `seasonal_runtime.txt` for exact algorithmic reproduction.

Primary outputs are `quarterly_industry_productivity.csv`, `quarterly_productivity_all_variants.csv`, `detailed_payroll_productivity.csv`, and `independent_quarterly_productivity.xlsx`. Monthly inputs, mapping, source hashes, validation and 2025 Q1 diagnostics are supplied alongside them. AI charts and their data are in `halves`, `quartiles` and `quintiles`.

## Sources

"""
    sources=[("BEA GDP by Industry workbook",BEA_URL),("BLS CES data","https://www.bls.gov/ces/data/"),
        ("BLS time-series API",BLS_URL),("Census CPS datasets",CPS_URL),
        ("CPS January 2025 population controls","https://www.bls.gov/cps/methods/population-controls/population-control-adjustments-2025.pdf"),
        ("October 2025 CPS collection gap","https://www.bls.gov/cps/methods/2025-federal-government-shutdown-impact-cps.htm"),
        ("Census X-13 seasonal adjustment","https://www.census.gov/data/software/x13as.X-13ARIMA-SEATS.html"),
        ("BLS contemporaneous 2025 Q1 productivity release","https://www.bls.gov/news.release/archives/prod2_06052025.htm"),
        ("Chicago Fed methodological inspiration","https://www.chicagofed.org/publications/economic-perspectives/2025/1"),
        ("RPS GenAI Adoption Tracker","https://www.genaiadoptiontracker.com/")]
    text+="\n".join(f"- [{title}]({url})" for title,url in sources)+"\n"
    (OUT/"methodology.md").write_text(text)
    core=pd.read_csv(OUT/"quarterly_industry_productivity.csv")
    definitions={
        "naics":("identifier","Broad NAICS sector; government and agriculture excluded"),
        "quarter":("calendar quarter","Quarter YYYYQn; every accepted quarter has three CES monthly observations"),
        "bea_line":("identifier","Line number in the downloaded BEA value-added tables"),
        "industry":("text","BEA industry name"),
        "variant":("category","all_workers in the core file; other variants in the alternatives file"),
        "real_value_added_quantity_index":("2017=100","BEA TVA103-Q real value-added quantity index, seasonally adjusted"),
        "nominal_value_added_millions":("USD millions, annual rate","BEA TVA105-Q nominal value added"),
        "nominal_value_added_dollars":("USD, annual rate","TVA105-Q multiplied by 1,000,000"),
        "annualized_hours":("hours per year","52 × quarterly mean of the selected seasonally adjusted weekly-hours measure"),
        "productivity_index_2023q1_100":("2023Q1=100","BEA real output index divided by annualized hours, normalized at 2023Q1"),
        "productivity_growth_annualized_pct":("percent, annualized","100 × [exp(4 × quarterly log productivity change) − 1]"),
        "real_output_growth_log_pct":("100 × quarterly log change","First accepted quarter is missing"),
        "hours_growth_log_pct":("100 × quarterly log change","First accepted quarter is missing"),
        "productivity_growth_log_pct":("100 × quarterly log change","Output log growth minus hours log growth; first accepted quarter missing"),
        "cps_imputed_months":("count","1 in 2025Q4; 0 otherwise. Payroll-only variants do not use imputed CPS hours"),
        "cps_nonpayroll_to_payroll_ratio":("ratio","Quarterly mean of monthly CPS nonpayroll/payroll person ratios; diagnostic only, not used to construct hours"),
        "payroll_average_weekly_hours_nsa":("hours per worker per week","Quarterly mean of monthly reconstructed CES payroll workweeks"),
        "hours_scope":("text","Definition of the selected hours denominator"),
        "cps_imputation_note":("text","Known missing-CPS-month treatment, where applicable"),
        "mapping_note":("text","CES sector composite or proxy mapping, where applicable"),
        "source_urls":("URLs","Primary BEA, BLS and Census source locations"),
    }
    records=[]
    for column in core:
        if column in definitions:
            unit,meaning=definitions[column]
        elif "sample_persons" in column:
            unit,meaning="unweighted people per calendar month","Quarterly mean of observed sample-record counts, including zero in October 2025 because no survey was collected; zero observed records does not mean zero employment"
        elif "employed_persons" in column or column.startswith("ces_employment"):
            unit,meaning="people or payroll jobs","Quarterly mean of monthly employment levels; CPS values are person-weighted, CES values are payroll jobs"
        elif "hours" in column:
            unit,meaning="weekly hours","Quarterly mean of monthly weekly-hours totals; nsa=unadjusted, sa=BLS adjusted, x13=own X-13 adjustment"
        else:
            raise ValueError(column)
        records.append({"field":column,"unit":unit,"definition":meaning,"source_urls":BEA_URL+" ; "+BLS_URL+" ; "+CPS_URL})
    pd.DataFrame(records).to_csv(OUT/"data_dictionary.csv",index=False)


if __name__=="__main__":
    main()
