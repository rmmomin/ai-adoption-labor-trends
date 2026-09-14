#!/usr/bin/env python3
"""Rebuild quarterly industry output per hour from BEA, CES and CPS inputs.

Run fetch_independent_productivity.py first. This builder never reads QILP.
It uses Census X-13 via the R seasonal package; all specifications are archived.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import time
import urllib.request

import numpy as np
import pandas as pd

from independent_productivity_inputs import (
    ROOT, RAW, OUT, BROAD, HOURS_TERMS, NOTES, DETAIL, DETAIL_EXCLUDE,
    BEA_URL, BLS_URL, CPS_URL, read_bea, read_catalog, monthly_cps,
)


def refresh_bls(ids):
    """Refresh the full supported history; retain raw API responses without credentials."""
    from bls_api import resolve_bls_api_key
    try:
        key = resolve_bls_api_key()
    except ValueError:
        key = ""
    raw = RAW / "api"
    raw.mkdir(exist_ok=True)
    covered = set()
    for cached in raw.glob("*.json"):
        for series in json.loads(cached.read_text()).get("Results", {}).get("series", []):
            covered.update((series["seriesID"], int(row["year"])) for row in series["data"])
    batch_size = 50 if key else 25
    years = [(2006, 2025), (2026, 2026)] if key else [(2006, 2015), (2016, 2025), (2026, 2026)]
    for start in range(0, len(ids), batch_size):
        batch = ids[start:start+batch_size]
        for first, last in years:
            needed = [sid for sid in batch if any((sid, y) not in covered for y in range(first, last+1))]
            if not needed:
                continue
            tag = hashlib.sha256(" ".join(needed).encode()).hexdigest()[:12]
            path = raw / f"{tag}_{first}_{last}.json"
            if path.exists():
                continue
            payload = {"seriesid": needed, "startyear": str(first), "endyear": str(last)}
            if key:
                payload["registrationkey"] = key
            request = urllib.request.Request(BLS_URL, data=json.dumps(payload).encode(),
                      headers={"Content-Type": "application/json", "User-Agent": "economic research"})
            for attempt in range(3):
                try:
                    with urllib.request.urlopen(request, timeout=60) as response:
                        body = json.loads(response.read())
                    break
                except Exception:
                    if attempt == 2:
                        raise
                    time.sleep(attempt+1)
            if body.get("status") != "REQUEST_SUCCEEDED":
                raise RuntimeError(body.get("message"))
            body["retrieved_at_utc"] = datetime.now(timezone.utc).isoformat()
            body["source_url"] = BLS_URL
            path.write_text(json.dumps(body, indent=2))
            print(f"Refreshed CES API batch {start//batch_size+1}: {first}–{last}", flush=True)


def bls_panel(ids, offline):
    if not offline:
        refresh_bls(ids)
        refresh_bls(["LNU02000000", "PRS85006093"])
    rows = []
    for path in sorted((RAW / "api").glob("*.json")):
        body = json.loads(path.read_text())
        for s in body.get("Results", {}).get("series", []):
            if s["seriesID"] not in ids:
                continue
            for row in s["data"]:
                period = row["period"]
                if period.startswith("M") and period != "M13":
                    rows.append({"series_id": s["seriesID"], "date": f"{row['year']}-{period[1:]}-01",
                                 "value": float(row["value"]), "api_file": path.name,
                                 "preliminary": any(x.get("code") == "P" for x in row.get("footnotes", []))})
    data = pd.DataFrame(rows)
    if data.empty:
        raise ValueError("No archived CES API observations. Run without --offline once.")
    if data.duplicated(["series_id", "date"]).any():
        # Overlapping batch caches must agree rather than silently selecting a vintage.
        assert data.groupby(["series_id", "date"]).value.nunique().max() == 1
        data = data.drop_duplicates(["series_id", "date"])
    data["date"] = pd.to_datetime(data.date)
    data.to_csv(OUT / "ces_observations.csv", index=False)
    return data.pivot(index="date", columns="series_id", values="value").sort_index()


def make_monthly(wide, cps, latest):
    dates = pd.date_range("2006-03-01", latest.end_time.normalize(), freq="MS")
    wide = wide.reindex(dates)
    data = []
    cps = cps.copy()
    cps["nonpayroll"] = cps.class_of_worker.isin([7, 8]) & cps.naics.ne("excluded")
    cps["private_payroll"] = cps.class_of_worker.isin([4, 5, 6]) & cps.naics.ne("excluded") & cps.census_industry.ne(9290)
    cps["household_payroll"] = cps.class_of_worker.isin([4, 5, 6]) & cps.census_industry.eq(9290)
    for naics, line, industry, code in BROAD:
        frame = pd.DataFrame(index=dates)
        frame["ces_employment_nsa"] = wide["CEU"+code+"01"]*1000
        frame["ces_employment_sa"] = wide["CES"+code+"01"]*1000
        for prefix, suffix in [("CEU", "nsa"), ("CES", "sa")]:
            terms = [sign*wide[prefix+e+"01"]*1000*wide[prefix+h+"02"] for e,h,sign in HOURS_TERMS[naics]]
            frame[f"payroll_weekly_hours_{suffix}"] = sum(terms)
        frame["payroll_average_weekly_hours_nsa"] = frame.payroll_weekly_hours_nsa/frame.ces_employment_nsa
        assert frame.notna().all().all(), (naics, frame.isna().sum().to_dict())
        assert (frame > 0).all().all(), naics
        sector = cps[cps.naics.eq(naics)]
        for flag in ["nonpayroll", "private_payroll", "household_payroll"]:
            for column in ["employed_persons", "actual_weekly_hours", "sample_persons"]:
                sums = sector[sector[flag]].groupby("date")[column].sum()
                # Empty cells are genuine zero sample observations; a missing survey month remains NA.
                available = pd.Index(cps.date.unique())
                sums = sums.reindex(available, fill_value=0).reindex(dates)
                frame[f"cps_{flag}_{column}"] = sums
        missing_dates = frame.index[frame.cps_nonpayroll_employed_persons.isna()]
        assert list(missing_dates) == [pd.Timestamp("2025-10-01")], (naics, missing_dates)
        cps_cols = [c for c in frame if c.startswith("cps_") and not c.endswith("sample_persons")]
        # One calendar-month midpoint, not day-weighted interpolation. Apply only to
        # the known survey gap; all source observations and CES inputs stay observed.
        october = pd.Timestamp("2025-10-01")
        neighbors = frame.loc[["2025-09-01", "2025-11-01"], cps_cols]
        assert neighbors.notna().all().all(), naics
        frame.loc[october, cps_cols] = neighbors.mean(axis=0)
        sample_cols = [c for c in frame if c.endswith("sample_persons")]
        # These fields count records actually observed, not estimated employment.
        # No October survey was collected, so its observed record count is zero.
        frame.loc[october, sample_cols] = 0
        frame["cps_month_imputed"] = frame.index == october
        assert frame.notna().all().all(), (naics, "Incomplete monthly inputs")
        extra = frame.cps_nonpayroll_employed_persons + frame.cps_household_payroll_employed_persons
        frame["total_employed_persons_nsa"] = frame.ces_employment_nsa + extra
        frame["total_weekly_hours_nsa"] = frame.total_employed_persons_nsa*frame.payroll_average_weekly_hours_nsa
        frame["actual_self_hours_weekly_nsa"] = (frame.payroll_weekly_hours_nsa +
            frame.cps_nonpayroll_actual_weekly_hours + frame.cps_household_payroll_actual_weekly_hours)
        # Diagnostic only. A zero CPS payroll sample is missing, not an infinite population ratio.
        frame["cps_nonpayroll_to_payroll_ratio"] = frame.cps_nonpayroll_employed_persons/frame.cps_private_payroll_employed_persons.where(frame.cps_private_payroll_employed_persons.gt(0))
        frame["naics"], frame["bea_line"], frame["industry"] = naics, line, industry
        frame.index.name = "date"
        data.append(frame.reset_index())
    return pd.concat(data, ignore_index=True)


def october_imputation_audit(monthly):
    """Expose each endpoint and estimate, and verify the one-month treatment."""
    columns = [c for c in monthly if c.startswith("cps_") and
               (c.endswith("employed_persons") or c.endswith("actual_weekly_hours"))]
    records = []
    for naics, sector in monthly.groupby("naics"):
        sector = sector.set_index("date")
        for column in columns:
            september, october, november = sector.loc[
                ["2025-09-01", "2025-10-01", "2025-11-01"], column].to_numpy()
            midpoint = (september + november)/2
            assert np.isclose(october, midpoint, rtol=1e-12, atol=1e-8)
            records.append({"naics": naics, "industry": sector.industry.iloc[0],
                "field": column, "unit": "people" if column.endswith("employed_persons") else "hours per week",
                "september_2025_observed": september, "october_2025_estimated": october,
                "november_2025_observed": november, "month": "2025-10",
                "method": "0.5 * September 2025 + 0.5 * November 2025 (NSA levels)",
                "observed_october_sample_count": 0,
                "source_url": CPS_URL,
                "collection_gap_source_url": "https://www.bls.gov/cps/methods/2025-federal-government-shutdown-impact-cps.htm"})
    audit = pd.DataFrame(records)
    assert len(audit) == 18*6 and audit.notna().all().all()
    audit.to_csv(OUT/"october_2025_imputation.csv", index=False)


def adjust_hours(monthly):
    columns = {"total": "total_weekly_hours_nsa", "payroll": "payroll_weekly_hours_nsa",
               "actual_self": "actual_self_hours_weekly_nsa"}
    inputs = []
    for variant, column in columns.items():
        x = monthly[["date", "naics", column]].rename(columns={column: "value"})
        x["series"] = x.naics.str.replace("-", "_", regex=False)+"_"+variant
        x["variant"] = variant
        inputs.append(x)
    pd.concat(inputs).to_csv(OUT / "x13_monthly_inputs.csv", index=False)
    subprocess.run(["Rscript", str(ROOT/"scripts/seasonally_adjust_independent_hours.R"), str(OUT), str(ROOT)], check=True)
    adjusted = pd.read_csv(OUT / "x13_monthly_adjusted.csv", parse_dates=["date"], dtype={"naics": str})
    result = monthly.copy()
    for variant in columns:
        x = adjusted[adjusted.variant.eq(variant)][["date", "naics", "adjusted"]].rename(columns={"adjusted": f"{variant}_weekly_hours_x13"})
        result = result.merge(x, on=["date", "naics"], validate="one_to_one")
    return result


def quarterly_panel(monthly, bea):
    monthly["quarter"] = monthly.date.dt.to_period("Q")
    columns = [c for c in monthly.select_dtypes(include=["number", "bool"]) if c != "bea_line"]
    means = monthly.groupby(["naics", "quarter"])[columns].mean().reset_index()
    means = means.drop(columns="cps_month_imputed")
    imputed = monthly.groupby(["naics", "quarter"]).cps_month_imputed.sum().rename("cps_imputed_months").reset_index()
    means = means.merge(imputed, on=["naics", "quarter"], validate="one_to_one")
    counts = monthly.groupby(["naics", "quarter"]).size()
    complete = counts[counts.eq(3)].reset_index()[["naics", "quarter"]]
    means = means.merge(complete, on=["naics", "quarter"], validate="one_to_one")
    means["bea_line"] = means.naics.map({n:l for n,l,_,_ in BROAD})
    panel = means.merge(bea, on=["bea_line", "quarter"], validate="many_to_one").sort_values(["naics", "quarter"])
    measures = {"all_workers": "total_weekly_hours_x13", "payroll_only": "payroll_weekly_hours_x13",
                "cps_actual_self_hours": "actual_self_weekly_hours_x13", "bls_sa_payroll": "payroll_weekly_hours_sa"}
    frames = []
    for variant, hours in measures.items():
        f = panel.copy()
        f["variant"] = variant
        f["annualized_hours"] = 52*f[hours]
        f["nominal_value_added_dollars"] = 1e6*f.nominal_value_added_millions
        f["real_output_growth_log_pct"] = f.groupby("naics").real_value_added_quantity_index.transform(lambda s: 100*np.log(s).diff())
        f["hours_growth_log_pct"] = f.groupby("naics").annualized_hours.transform(lambda s: 100*np.log(s).diff())
        raw = f.real_value_added_quantity_index/f.annualized_hours
        base = pd.Series(raw[f.quarter.eq(pd.Period("2023Q1"))].to_numpy(), index=f.loc[f.quarter.eq(pd.Period("2023Q1")), "naics"])
        f["productivity_index_2023q1_100"] = 100*raw/f.naics.map(base)
        f["productivity_growth_log_pct"] = f.real_output_growth_log_pct-f.hours_growth_log_pct
        f["productivity_growth_annualized_pct"] = 100*np.expm1(4*f.productivity_growth_log_pct/100)
        f["hours_scope"] = "payroll hours" if variant in ["payroll_only", "bls_sa_payroll"] else "payroll plus nonpayroll labor hours proxy"
        f["cps_imputation_note"] = np.where(f.quarter.eq(pd.Period("2025Q4")) & ~f.variant.isin(["payroll_only", "bls_sa_payroll"]), "October CPS counts/hours interpolated between September and November", "")
        f["mapping_note"] = f.naics.map(NOTES).fillna("")
        f["source_urls"] = BEA_URL+" ; "+BLS_URL+" ; "+CPS_URL
        frames.append(f)
    return pd.concat(frames, ignore_index=True)


def detailed_panel(wide, bea, catalog):
    records, coverage = [], []
    for line, code in DETAIL.items():
        e, h = "CES"+code+"01", "CES"+code+"02"
        name = bea.loc[bea.bea_line.eq(line), "industry"].iloc[0]
        note = DETAIL_EXCLUDE.get(line, "")
        if h not in catalog.index:
            note = "No direct all-employee AWH series"
        if note:
            coverage.append({"bea_line": line, "industry": name, "included": False, "reason": note})
            continue
        monthly = pd.DataFrame({"employment_persons": wide[e]*1000, "annualized_hours": 52*wide[e]*1000*wide[h]})
        monthly["quarter"] = monthly.index.to_period("Q")
        valid = monthly.groupby("quarter").annualized_hours.count().eq(3)
        q = monthly.groupby("quarter")[["employment_persons", "annualized_hours"]].mean()
        q = q[valid].reset_index()
        q["bea_line"] = line
        q = q.merge(bea, on=["bea_line", "quarter"], validate="one_to_one")
        if not q.quarter.eq(pd.Period("2023Q1")).any():
            raise ValueError(f"Missing detail baseline for {line}")
        ratio = q.real_value_added_quantity_index/q.annualized_hours
        q["productivity_index_2023q1_100"] = 100*ratio/ratio[q.quarter.eq(pd.Period("2023Q1"))].iloc[0]
        q["employment_series"], q["hours_series"] = e, h
        q["hours_scope"] = "payroll only; self-employed and unpaid family workers excluded"
        q["source_urls"] = BEA_URL+" ; "+BLS_URL
        records.append(q)
        coverage.append({"bea_line": line, "industry": name, "included": True,
                         "reason": "Direct CES employment and AWH match; payroll-only proxy", "employment_title": catalog.loc[e, "series_title"], "hours_title": catalog.loc[h, "series_title"]})
    return pd.concat(records, ignore_index=True), pd.DataFrame(coverage)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--offline", action="store_true", help="Use archived BLS API responses")
    p.add_argument("--prepare-ces-only", action="store_true", help="Fetch CES history while Census files download")
    args = p.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    bea = read_bea(RAW/"bea/ValueAdded.xlsx")
    bea.to_csv(OUT/"bea_value_added.csv", index=False)
    latest = bea.quarter.max()
    catalog = read_catalog(RAW/"bls/ce.series").set_index("series_id")
    ids = {prefix+code+"01" for _,_,_,code in BROAD for prefix in ["CEU", "CES"]}
    mapping = []
    for n, terms in HOURS_TERMS.items():
        for e,h,sign in terms:
            for prefix in ["CEU", "CES"]:
                ids.update([prefix+e+"01", prefix+h+"02"])
            mapping.append({"naics": n, "employment_code": e, "awh_code": h, "coefficient": sign,
                            "employment_title": catalog.loc["CEU"+e+"01", "series_title"],
                            "awh_title": catalog.loc["CEU"+h+"02", "series_title"], "note": NOTES.get(n, "Direct sector employment × all-employee AWH")})
    for line,code in DETAIL.items():
        for kind in ["01", "02"]:
            sid = "CES"+code+kind
            if line not in DETAIL_EXCLUDE and sid in catalog.index:
                ids.add(sid)
    assert ids.issubset(set(catalog.index)), sorted(ids-set(catalog.index))
    pd.DataFrame(mapping).to_csv(OUT/"ces_industry_mapping.csv", index=False)
    wide = bls_panel(sorted(ids), args.offline)
    detail, coverage = detailed_panel(wide, bea, catalog)
    detail.to_csv(OUT/"detailed_payroll_productivity.csv", index=False)
    coverage.to_csv(OUT/"detailed_coverage.csv", index=False)
    if args.prepare_ces_only:
        print(f"Prepared {len(ids)} CES series and {detail.bea_line.nunique()} detailed industries", flush=True)
        return
    cps, metadata = monthly_cps()
    cps.to_csv(OUT/"cps_monthly_industry_cells.csv", index=False)
    (OUT/"cps_parsing_validation.json").write_text(json.dumps(metadata, indent=2))
    benchmark = []
    for path in [*sorted((RAW/"benchmarks").glob("bls_*.json")), *sorted((RAW/"api").glob("*.json"))]:
        for series in json.loads(path.read_text()).get("Results", {}).get("series", []):
            if series["seriesID"] == "LNU02000000":
                for row in series["data"]:
                    if row["period"].startswith("M") and row["period"] != "M13":
                        if row["value"] == "-" and row["year"] == "2025" and row["period"] == "M10":
                            continue  # BLS explicitly marks the uncollected survey month missing.
                        benchmark.append({"date": f"{row['year']}-{row['period'][1:]}-01", "bls_employed_persons": float(row["value"])*1000})
    benchmark = pd.DataFrame(benchmark)
    assert benchmark.groupby("date").bls_employed_persons.nunique().max() == 1
    comparison = pd.DataFrame(metadata)[["date", "employed_persons"]].merge(benchmark.drop_duplicates("date"), on="date", validate="one_to_one")
    comparison["difference_persons"] = comparison.employed_persons-comparison.bls_employed_persons
    comparison["difference_pct"] = 100*comparison.difference_persons/comparison.bls_employed_persons
    comparison.to_csv(OUT/"cps_national_validation.csv", index=False)
    # Differences beyond rounding may signal revised weights or parsing errors; never hide them.
    if comparison.difference_persons.abs().max() > 501:
        raise ValueError("CPS microdata national employment exceeds the BLS rounding tolerance; inspect cps_national_validation.csv")
    monthly = make_monthly(wide, cps, latest)
    october_imputation_audit(monthly)
    monthly.to_csv(OUT/"monthly_inputs_unadjusted.csv", index=False)
    monthly = adjust_hours(monthly)
    monthly.to_csv(OUT/"monthly_inputs_and_adjustment.csv", index=False)
    panel = quarterly_panel(monthly, bea)
    panel.to_csv(OUT/"quarterly_productivity_all_variants.csv", index=False, float_format="%.10f")
    main = panel[panel.variant.eq("all_workers")]
    main.to_csv(OUT/"quarterly_industry_productivity.csv", index=False, float_format="%.10f")
    validation = {"independent_of_qilp": True, "first_quarter": str(main.quarter.min()),
        "last_quarter": str(main.quarter.max()), "quarters": int(main.quarter.nunique()),
        "broad_industries": int(main.naics.nunique()), "detailed_payroll_industries": int(detail.bea_line.nunique()),
        "cps_months_parsed": len(metadata), "cps_missing_month": "2025-10",
        "cps_missing_month_treatment": "October CPS employment and actual hours = arithmetic mean of September and November NSA levels; observed sample counts = 0; month flagged as imputed",
        "ces_monthly_observations_complete": True, "bea_nominal_industry_totals_reconcile": True}
    validation["cps_bls_comparison_months"] = len(comparison)
    validation["cps_bls_max_absolute_difference_pct"] = float(comparison.difference_pct.abs().max())
    validation["cps_national_employment_matches_bls_to_rounding"] = bool(comparison.difference_persons.abs().max() <= 501)
    assert monthly.select_dtypes(include="number").notna().all().all()
    assert monthly.loc[monthly.cps_month_imputed, "date"].eq(pd.Timestamp("2025-10-01")).all()
    assert int(monthly.cps_month_imputed.sum()) == 18
    assert monthly.loc[monthly.cps_month_imputed, [c for c in monthly if c.endswith("sample_persons")]].eq(0).all().all()
    level_columns = ["real_value_added_quantity_index", "annualized_hours", "productivity_index_2023q1_100"]
    assert np.isfinite(panel[level_columns].to_numpy()).all()
    assert panel.groupby(["variant", "quarter"]).size().eq(18).all()
    q4 = monthly[monthly.quarter.eq(pd.Period("2025Q4"))]
    assert q4.groupby("naics").size().eq(3).all()
    assert np.allclose(main[main.quarter.eq(pd.Period("2025Q4"))].set_index("naics").annualized_hours.sort_index(),
                       52*q4.groupby("naics").total_weekly_hours_x13.mean().sort_index())
    validation.update({"monthly_numeric_inputs_complete": True,
        "quarterly_output_hours_productivity_levels_complete_all_variants": True,
        "october_2025_completed_industries": 18, "october_2025_cps_fields_audited": 108,
        "october_2025_observed_sample_counts_zero": True,
        "q4_2025_uses_three_months_per_industry": True})
    assert main.groupby("quarter").naics.nunique().eq(18).all()
    assert not main.duplicated(["naics", "quarter"]).any()
    assert np.allclose(main.loc[main.quarter.eq(pd.Period("2023Q1")), "productivity_index_2023q1_100"], 100)
    assert np.allclose(main.groupby("naics").productivity_index_2023q1_100.transform(lambda s: 100*np.log(s).diff()).dropna(), main.productivity_growth_log_pct.dropna())
    validation["productivity_output_hours_identity"] = True
    (OUT/"validation.json").write_text(json.dumps(validation, indent=2))
    source_files = [RAW/"bea/ValueAdded.xlsx", *sorted((RAW/"api").glob("*.json")), *sorted((RAW/"benchmarks").glob("*.json")), RAW/"manifest.json"]
    provenance = {"created_at_utc": datetime.now(timezone.utc).isoformat(), "sources": [
        {"file": str(f.relative_to(ROOT)), "sha256": hashlib.sha256(f.read_bytes()).hexdigest()} for f in source_files],
        "qilp_used_as_input": False, "base_quarter": "2023Q1", "method": "Direct BEA quantity index divided by independently constructed CES+CPS hours; Census X-13 monthly seasonal adjustment"}
    (OUT/"source_metadata.json").write_text(json.dumps(provenance, indent=2))
    print(json.dumps(validation, indent=2))


if __name__ == "__main__":
    main()
