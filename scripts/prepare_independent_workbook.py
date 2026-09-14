#!/usr/bin/env python3
"""Prepare typed research tables for the downloadable Excel workbook."""
import json
import numpy as np
import pandas as pd
from independent_productivity_inputs import OUT, BEA_URL, BLS_URL, CPS_URL


def rows(frame):
    return json.loads(frame.to_json(orient="values", date_format="iso"))


def main():
    p = pd.read_csv(OUT/"quarterly_industry_productivity.csv", dtype={"naics":str})
    p = p.sort_values(["naics","quarter"])
    base = p[p.quarter.eq("2023Q1")].set_index("naics")
    core = pd.DataFrame({"NAICS":p.naics,"Industry":p.industry,"Quarter":p.quarter,
        "Real output index":p.real_value_added_quantity_index,"Annualized hours (millions)":p.annualized_hours/1e6,
        "Nominal output ($ billions)":p.nominal_value_added_dollars/1e9,
        "Base output (2023 Q1)":p.naics.map(base.real_value_added_quantity_index),
        "Base hours (millions)":p.naics.map(base.annualized_hours)/1e6,
        "Productivity (2023 Q1=100)":p.productivity_index_2023q1_100,
        "Quarterly growth (annualized)":p.productivity_growth_annualized_pct/100,
        "CPS months imputed":p.cps_imputed_months,
        "Mapping note":p.mapping_note.fillna("")})
    monthly = pd.read_csv(OUT/"monthly_inputs_and_adjustment.csv",dtype={"naics":str})
    monthly = monthly[["naics","industry","date","ces_employment_nsa","payroll_average_weekly_hours_nsa",
        "cps_nonpayroll_employed_persons","cps_household_payroll_employed_persons",
        "payroll_weekly_hours_nsa","total_weekly_hours_nsa","total_weekly_hours_x13",
        "cps_nonpayroll_sample_persons","cps_household_payroll_sample_persons","cps_month_imputed"]]
    monthly.columns=["NAICS","Industry","Month","CES employees (NSA)","CES average weekly hours (NSA)",
        "CPS nonpayroll workers","CPS household employees","Payroll weekly hours (NSA)","Total weekly hours (NSA)",
        "Total weekly hours (X-13)","Nonpayroll sample count","Household employee sample count","CPS month imputed"]
    detail = pd.read_csv(OUT/"detailed_payroll_productivity.csv")
    detail = detail[["bea_line","industry","quarter","real_value_added_quantity_index","annualized_hours",
                     "productivity_index_2023q1_100","employment_series","hours_series","hours_scope"]]
    detail["annualized_hours"] /= 1e6
    detail.columns=["BEA line","Industry","Quarter","Real output index","Payroll hours (millions, annualized)",
                    "Productivity (2023 Q1=100)","Employment series","AWH series","Hours scope"]
    variants = pd.read_csv(OUT/"quarterly_productivity_all_variants.csv",dtype={"naics":str})
    variants = variants.pivot(index=["naics","industry","quarter"],columns="variant",values="productivity_index_2023q1_100").reset_index()
    variants = variants[["naics","industry","quarter","all_workers","payroll_only","cps_actual_self_hours","bls_sa_payroll"]]
    variants.columns=["NAICS","Industry","Quarter","Main all-worker proxy","Own X-13 payroll only","Reported self-employment hours","BLS SA payroll only"]
    groups = pd.read_csv(OUT/"group_productivity_all_variants.csv")
    groups = groups[groups.quarter.ge("2023Q1")][["quarter","variant","groups","group","productivity_index",
        "real_output_index","hours_index","productivity_growth_annualized_pct"]]
    groups["productivity_growth_annualized_pct"] /= 100
    groups.columns=["Quarter","Hours variant","Number of groups","Adoption group",
        "Productivity (2023 Q1=100)","Output (2023 Q1=100)","Hours (2023 Q1=100)","Quarterly growth (annualized)"]
    halves=pd.read_csv(OUT/"halves/productivity_index.csv")
    halves.columns=["Quarter","Lower-adoption half","Higher-adoption half"]
    mapping=pd.read_csv(OUT/"ces_industry_mapping.csv",dtype={"naics":str,"employment_code":str,"awh_code":str})
    checks=json.loads((OUT/"validation.json").read_text())
    overview=[
        ["Coverage",f"18 broad industries, {checks['first_quarter']}–{checks['last_quarter']} ({checks['quarters']} quarters). 38 additional payroll-only industry rows per quarter."],
        ["Normalization","2023 Q1 = 100. Quarterly percentage changes are annualized geometrically."],
        ["Output","BEA seasonally adjusted real value-added quantity indexes. Actual nominal value added supplies aggregation weights."],
        ["Main hours","CES nonseasonally adjusted employment and all-employee average weekly hours, plus CPS unincorporated self-employed, unpaid family and private-household workers at the sector CES workweek."],
        ["Seasonal adjustment","Monthly Census X-13, log transform and X-11 decomposition with automatic ARIMA and outlier detection. The final adjusted series retains the irregular component."],
        ["October 2025","CPS employment and actual hours = (September + November) / 2. CES payroll inputs are observed. All 18 industries have complete October inputs and three months in Q4. Sample counts are 0 observed respondents; imputation flags identify the estimates."],
        ["Alternatives","Own X-13 payroll-only hours, BLS seasonally adjusted payroll hours, and CPS-reported actual hours for nonpayroll workers. These help assess denominator sensitivity."],
        ["Industry groups","Fixed May 2026 RPS adoption rankings. Group output is chained with adjacent-quarter nominal-value-added shares; group hours are summed."],
        ["Interpretation","Research estimates of value added per labor-hour proxy. CES reports hours paid; unpublished paid-to-worked adjustments are unavailable. AI comparisons are descriptive."],
        ["Housing and population scope","Real estate includes imputed owner-occupied rent. Nonfarm private output includes nonprofits. The BLS nonfarm-business benchmark has a different scope."],
        ["Independent construction","No Chicago Fed QILP observations enter the output or hours calculation. All history is reconstructed from primary data."],
        ["CPS validation",f"{checks['cps_bls_comparison_months']} monthly national employment totals compared with BLS; largest difference {checks['cps_bls_max_absolute_difference_pct']:.5f}%."],
        ["BEA source",BEA_URL],["BLS source",BLS_URL],["Census source",CPS_URL],
        ["RPS source","https://www.genaiadoptiontracker.com/"],
    ]
    sheets=[{"name":"Guide","headers":["Item","Definition or source"],"rows":overview},
            {"name":"Productivity","headers":core.columns.tolist(),"rows":rows(core)},
            {"name":"Monthly inputs","headers":monthly.columns.tolist(),"rows":rows(monthly)},
            {"name":"Hours alternatives","headers":variants.columns.tolist(),"rows":rows(variants)},
            {"name":"Detailed payroll","headers":detail.columns.tolist(),"rows":rows(detail)},
            {"name":"AI halves","headers":halves.columns.tolist(),"rows":rows(halves)},
            {"name":"AI group data","headers":groups.columns.tolist(),"rows":rows(groups)},
            {"name":"CES mapping","headers":mapping.columns.tolist(),"rows":rows(mapping)}]
    (OUT/"workbook_data.json").write_text(json.dumps({"sheets":sheets,"checks":checks},allow_nan=False))


if __name__=="__main__":
    main()
