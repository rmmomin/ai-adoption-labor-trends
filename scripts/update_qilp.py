#!/usr/bin/env python3
"""Create a labeled CES-hours research extension of the published Chicago Fed QILP.

This is not an exact replication. See the generated methodology.md and coverage.csv.
Uses stdlib HTTP so that a BLS key is optional. Raw responses support --offline.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import re
import urllib.request
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
URLS = {
    "qilp_published.xlsx": "https://www.chicagofed.org/-/media/others/people/research-resources/hobijin-bart/qilp.xlsx",
    "ValueAdded.xlsx": "https://apps.bea.gov/industry/Release/XLS/GDPxInd/ValueAdded.xlsx",
    "ce.series": "https://downloadt.bls.gov/pub/time.series/ce/ce.series",
    "ce.industry": "https://downloadt.bls.gov/pub/time.series/ce/ce.industry",
    "pr.series": "https://downloadt.bls.gov/pub/time.series/pr/pr.series",
    "qilp-release-notes.pdf": "https://www.chicagofed.org/-/media/others/people/research-resources/hobijin-bart/qilp-release-notes.pdf",
    "article.html": "https://www.chicagofed.org/publications/economic-perspectives/2025/1",
}
BLS_URL = "https://api.bls.gov/publicAPI/v2/timeseries/data/"
BENCHMARK = "PRS85006093"
# Industry codes refer to the BLS CES catalog, not BEA line numbers.
DIRECT = {
    4: "10210000", 5: "10211000", 6: "10212000", 7: "10213000",
    8: "44220000", 9: "20000000", 10: "30000000", 11: "31000000",
    12: "31321000", 13: "31327000", 14: "31331000", 15: "31332000",
    16: "31333000", 17: "31334000", 18: "31335000", 19: "31336001",
    21: "31337000", 22: "31339000", 23: "32000000", 26: "32315000",
    27: "32322000", 28: "32323000", 29: "32324000", 30: "32325000",
    31: "32326000", 32: "41420000", 33: "42000000", 34: "42441000",
    35: "42445000", 36: "42455000", 38: "43000000", 39: "43481000",
    40: "43482000", 41: "43483000", 42: "43484000", 43: "43485000",
    44: "43486000", 46: "43493000", 47: "50000000", 48: "50513000",
    49: "50512000", 52: "55000000", 53: "55520000", 55: "55523000",
    56: "55524000", 58: "55530000", 59: "55531000", 60: "55531110",
    63: "60000000", 64: "60540000", 65: "60541100", 66: "60541500",
    68: "60550000", 69: "60560000", 70: "60561000", 71: "60562000",
    72: "65000000", 74: "65620000", 75: "65621000", 76: "65622000",
    77: "65623000", 78: "65624000", 79: "70000000", 80: "70710000",
    82: "70713000", 83: "70720000", 84: "70721000", 85: "70722000",
    86: "80000000",
}
# Signed components express nonoverlapping sums or residuals of payroll hours.
COMPOSITE = {
    20: [("31336000", 1), ("31336001", -1)],
    24: [("32311000", 1), ("32329100", 1)],
    25: [("32313000", 1), ("32314000", 1)],
    37: [("42000000", 1), ("42441000", -1), ("42445000", -1), ("42455000", -1)],
    45: [("43487000", 1), ("43488000", 1), ("43492000", 1)],
    50: [("50516000", 1), ("50517000", 1)],
    51: [("50518000", 1), ("50519000", 1)],
    53: [("55521000", 1), ("55522000", 1), ("55523000", 1), ("55524000", 1)],
    54: [("55521000", 1), ("55522000", 1)],
    58: [("55531000", 1), ("55532000", 1), ("55533000", 1)],
    61: [("55531000", 1), ("55531110", -1)],
    62: [("55532000", 1), ("55533000", 1)],
    67: [("60540000", 1), ("60541100", -1), ("60541500", -1)],
    73: [("65000000", 1), ("65620000", -1)],
    81: [("70711000", 1), ("70712000", 1)],
}
# Explicit AWH substitutions where CES does not publish the target's AWH.
AWH_PROXY = {
    "32324000": "32000000", "32329100": "32000000",
    "43482000": "43000000", "43483000": "43000000",
    "43486000": "43000000", "43487000": "43000000",
    "55521000": "55522000", "55533000": "55532000",
}
MAPPING_NOTES = {
    24: "Food plus beverage payrolls; tobacco omitted because the current CES grouping combines tobacco with leather.",
    26: "Apparel payrolls proxy apparel and leather; no separable current CES leather series.",
    35: "CES 2022 retail definitions may differ from BEA industry definitions.",
    36: "CES 2022 retail definitions may differ from BEA industry definitions.",
    37: "Residual retail hours; CES 2022 retail definitions may differ from BEA definitions.",
    48: "CES 2022 publishing definition is an approximation to the BEA publishing group.",
    50: "CES 2022 broadcasting/content providers plus telecommunications approximate the BEA group.",
    51: "CES 2022 computing infrastructure plus other information services approximate the BEA group.",
    55: "Current CES 523/525 combined payrolls proxy securities; includes funds/trusts.",
    60: "Residential lessors payrolls proxy housing labor input; output includes imputed owner-occupied rent.",
    61: "Total real estate less residential lessors payrolls approximate other real estate.",
    73: "Education hours are the residual of private education/health minus health/social assistance.",
}
SECTORS = [4, 8, 9, 10, 32, 33, 38, 47, 53, 58, 64, 68, 69, 73, 74, 80, 83, 86]


def request(url, payload=None):
    headers = {"User-Agent": "employment-ai QILP research", "Accept": "*/*"}
    data = None
    if payload is not None:
        data = json.dumps(payload).encode()
        headers["Content-Type"] = "application/json"
    with urllib.request.urlopen(urllib.request.Request(url, data=data, headers=headers), timeout=60) as r:
        return r.read()


def read_bea(path, sheet):
    df = pd.read_excel(path, sheet, header=7)
    lines = pd.to_numeric(df.iloc[:, 0], errors="coerce")
    mask = lines.notna()
    cols = [c for c in df if re.fullmatch(r"\d{4}Q[1-4]", str(c))]
    values = df.loc[mask, cols].apply(pd.to_numeric, errors="coerce")
    values.index = lines[mask].astype(int).to_numpy() - 2
    values.columns = pd.PeriodIndex(cols, freq="Q")
    names = pd.Series(df.loc[mask].iloc[:, 1].str.strip().to_numpy(), index=values.index)
    return values, names


def read_published(path, sheet):
    df = pd.read_excel(path, sheet)
    dates = [c for c in df if isinstance(c, dt.datetime)]
    values = df.set_index("gdp_line")[dates].apply(pd.to_numeric, errors="coerce")
    values.columns = pd.DatetimeIndex(dates).to_period("Q")
    return values, df[["industry", "level", "gdp_line"]]


def read_catalog(path):
    df = pd.read_csv(path, sep="\t", dtype=str)
    df.columns = df.columns.str.strip()
    return df.map(lambda v: v.strip() if isinstance(v, str) else v)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--offline", action="store_true")
    p.add_argument("--reuse-sources", action="store_true", help="Reuse downloaded workbooks/catalogs and fetch BLS observations only")
    p.add_argument("--raw-dir", type=Path, default=ROOT / "data/qilp_update")
    p.add_argument("--outdir", type=Path, default=ROOT / "outputs/qilp_update_01a0a142")
    args = p.parse_args()
    raw, out = args.raw_dir, args.outdir
    raw.mkdir(parents=True, exist_ok=True)
    out.mkdir(parents=True, exist_ok=True)
    if not args.offline and not args.reuse_sources:
        for name, url in URLS.items():
            (raw / name).write_bytes(request(url))
        (raw / "retrieval.json").write_text(json.dumps({
            "retrieved_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(), "urls": URLS,
        }, indent=2))
    published = {}
    for sheet in ["Labor Productivity", "Real Output Growth", "Total Hours", "Hours Growth", "Employment", "Nominal Output"]:
        published[sheet], industries = read_published(raw / "qilp_published.xlsx", sheet)
    lp = published["Labor Productivity"]
    base = lp.columns.max()
    quantity, bea_names = read_bea(raw / "ValueAdded.xlsx", "TVA103-Q")
    nominal, _ = read_bea(raw / "ValueAdded.xlsx", "TVA105-Q")
    nominal *= 1e6  # BEA table TVA105: millions of current dollars, annual rate.
    sector_residual = nominal.loc[SECTORS].sum(axis=0) - nominal.loc[0] + nominal.loc[1]
    if sector_residual.abs().max() > (len(SECTORS) + 2) * 0.5e6:
        raise ValueError("The broad-sector mapping does not reconcile with BEA private output less agriculture")
    latest = quantity.columns.max()
    if latest <= base:
        raise ValueError(f"BEA ends at {latest}; published QILP already ends at {base}.")
    new_quarters = pd.period_range(base + 1, latest, freq="Q")
    catalog = read_catalog(raw / "ce.series").set_index("series_id")
    pr_catalog = read_catalog(raw / "pr.series").set_index("series_id")
    if "Index (2017=100)" not in pr_catalog.loc[BENCHMARK, "series_title"]:
        raise ValueError("BLS benchmark must be a productivity level index, not a growth rate")
    mappings = {i: [(code, 1)] for i, code in DIRECT.items()} | COMPOSITE
    components = {}
    for line, terms in mappings.items():
        components[line] = []
        for code, sign in terms:
            e = "CES" + code + "01"
            hcode = AWH_PROXY.get(code, code)
            h = "CES" + hcode + "02"
            for sid in [e, h]:
                if sid not in catalog.index:
                    raise ValueError(f"Missing CES catalog entry {sid} for QILP {line}.")
                row = catalog.loc[sid]
                if row.seasonal != "S":
                    raise ValueError(f"Not seasonally adjusted: {sid}")
            components[line].append((e, h, sign))
    ids = sorted({s for ts in components.values() for e, h, _ in ts for s in [e, h]})
    ids.append(BENCHMARK)
    if not args.offline:
        batches = []
        # No credential is recorded. Unregistered API supports 25 series and 10 years per call.
        for start in range(0, len(ids), 25):
            payload = {"seriesid": ids[start:start+25], "startyear": str(base.year - 3), "endyear": str(latest.year)}
            body = json.loads(request(BLS_URL, payload))
            if body.get("status") != "REQUEST_SUCCEEDED":
                raise RuntimeError(f"BLS failed: {body.get('message')}")
            batches.append(body)
            print(f"Fetched BLS batch {len(batches)} ({len(payload['seriesid'])} series)", flush=True)
        (raw / "bls_responses.json").write_text(json.dumps(batches, indent=2))
        (raw / "bls_retrieval.json").write_text(json.dumps({"retrieved_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(), "url": BLS_URL}, indent=2))
    observations = []
    for body in json.loads((raw / "bls_responses.json").read_text()):
        for s in body.get("Results", {}).get("series", []):
            for obs in s.get("data", []):
                period = obs["period"]
                if re.fullmatch(r"[MQ]\d{2}", period) and period not in ("M13", "Q05"):
                    observations.append({"series_id": s["seriesID"], "year": int(obs["year"]),
                                         "period": period, "value": float(obs["value"]),
                                         "preliminary": any(x.get("code") == "P" for x in obs.get("footnotes", []))})
    obs = pd.DataFrame(observations)
    if obs.duplicated(["series_id", "year", "period"]).any():
        raise ValueError("Duplicate BLS observations")
    obs.to_csv(out / "bls_observations.csv", index=False)
    monthly = obs[obs.period.str.startswith("M")].copy()
    monthly["date"] = pd.to_datetime(monthly.year.astype(str) + "-" + monthly.period.str[1:] + "-01")
    wide = monthly.pivot(index="date", columns="series_id", values="value").sort_index()
    required_dates = pd.date_range(f"{base.year - 3}-01-01", latest.end_time.normalize(), freq="MS")
    wide = wide.reindex(required_dates)
    required_ids = [s for s in ids if s != BENCHMARK]
    missing = wide.reindex(columns=required_ids).isna()
    if missing.any().any():
        raise ValueError("Missing monthly CES observations: " + str(missing.sum()[missing.any()].to_dict()))
    hours, employment, rows = {}, {}, []
    for line, terms in components.items():
        # Employment is thousands, hence *1000. Mean MONTHLY PRODUCTS gives quarterly weekly hours.
        hm = sum(sign * wide[e] * 1000 * wide[h] for e, h, sign in terms)
        em = sum(sign * wide[e] * 1000 for e, _, sign in terms)
        if (hm <= 0).any() or (em <= 0).any():
            raise ValueError(f"Nonpositive payroll residual for {line}.")
        hours[line] = hm.groupby(hm.index.to_period("Q")).mean()
        employment[line] = em.groupby(em.index.to_period("Q")).mean()
        for e, h, sign in terms:
            rows.append({"gdp_line": line, "industry": industries.set_index("gdp_line").loc[line, "industry"],
                         "coefficient": sign, "employment_series": e, "awh_series": h,
                         "employment_title": catalog.loc[e, "series_title"],
                         "awh_title": catalog.loc[h, "series_title"],
                         "awh_proxy": e[3:-2] != h[3:-2], "notes": MAPPING_NOTES.get(line, ""),
                         "source_url": BLS_URL})
    hours = pd.DataFrame(hours).T
    employment = pd.DataFrame(employment).T
    # Aggregate the 18 mutually exclusive broad nonfarm sectors using the paper's Tornqvist formula.
    qgrowth = np.log(quantity.loc[SECTORS]).diff(axis=1)
    shares = nominal.loc[SECTORS].div(nominal.loc[SECTORS].sum(axis=0), axis=1)
    nfp_growth = (qgrowth * (shares + shares.shift(1, axis=1)) / 2).sum(axis=0, min_count=len(SECTORS))
    quantity.loc[87] = np.exp(nfp_growth.fillna(0).cumsum())
    nominal.loc[87] = nominal.loc[SECTORS].sum(axis=0)
    # Fix broad-sector labor-input weights at the published QILP anchor.
    hours.loc[87] = hours.loc[SECTORS].div(hours.loc[SECTORS, base], axis=0).mul(published["Total Hours"].loc[SECTORS, base], axis=0).sum(axis=0)
    employment.loc[87] = employment.loc[SECTORS].div(employment.loc[SECTORS, base], axis=0).mul(published["Employment"].loc[SECTORS, base], axis=0).sum(axis=0)
    b = obs[obs.series_id.eq(BENCHMARK) & obs.period.str.startswith("Q")].copy()
    b.index = pd.PeriodIndex(b.year.astype(str) + "Q" + b.period.str[1:].astype(int).astype(str), freq="Q")
    benchmark = b.value.sort_index()
    if not set([base, *new_quarters]).issubset(benchmark.index):
        raise ValueError("Missing BLS nonfarm business benchmark quarters")
    coverage = industries.copy()
    coverage["status"] = "research_extension"
    coverage["method_note"] = coverage.gdp_line.map(MAPPING_NOTES).fillna("")
    coverage.loc[coverage.gdp_line.eq(87), "method_note"] = "18-sector Tornqvist output; growth of summed sector hours linked to the published aggregate anchor."
    excluded = {0: "Aggregate includes agriculture; outside nonfarm extension scope.",
                1: "Agriculture is outside nonfarm extension scope.", 2: "Published productivity is missing; agriculture excluded.",
                3: "Forestry/fishing is outside nonfarm extension scope.",
                57: "Published anchor productivity is negative; proportional extension is invalid."}
    for line, note in excluded.items():
        coverage.loc[coverage.gdp_line.eq(line), ["status", "method_note"]] = ["not_extended", note]
    coverage.loc[coverage.gdp_line.eq(88), ["status", "method_note"]] = ["linked_bls_benchmark", "BLS PRS85006092 growth linked to published QILP anchor; not a newly constructed industry estimate."]
    active = sorted(set(mappings) | {87})
    if set(active) | set(excluded) | {88} != set(industries.gdp_line):
        raise ValueError("Unclassified industry")
    for line in mappings:
        name = industries.set_index("gdp_line").loc[line, "industry"]
        if name.strip() != bea_names.loc[line].strip():
            raise ValueError(f"BEA name mismatch for {line}: {name} vs {bea_names.loc[line]}")
    if not (lp.loc[active, base] > 0).all():
        raise ValueError("Nonpositive published anchor in extended industries")
    input_rows = []
    for line in active + [88]:
        for q in new_quarters:
            vr = quantity.loc[line, q] / quantity.loc[line, base] if line != 88 else np.nan
            hr = hours.loc[line, q] / hours.loc[line, base] if line != 88 else np.nan
            er = employment.loc[line, q] / employment.loc[line, base] if line != 88 else np.nan
            factor = vr / hr if line != 88 else benchmark.loc[q] / benchmark.loc[base]
            input_rows.append({"gdp_line": line, "industry": industries.set_index("gdp_line").loc[line, "industry"],
                               "quarter": str(q), "output_factor": vr, "hours_factor": hr,
                               "employment_factor": er, "productivity_factor": factor,
                               "nominal_factor": nominal.loc[line, q] / nominal.loc[line, base] if line != 88 else np.nan})
    inputs = pd.DataFrame(input_rows)
    allquarters = pd.period_range(lp.columns.min(), latest, freq="Q")
    sheets = {name: data.reindex(columns=allquarters).copy() for name, data in published.items()}
    # Historical published values are preserved exactly in all six exported measure sheets.
    # Nominal output is also linked at the anchor to avoid a source-vintage seam in weights.
    for line in active + [88]:
        for q in new_quarters:
            x = inputs[(inputs.gdp_line == line) & (inputs.quarter == str(q))].iloc[0]
            sheets["Labor Productivity"].loc[line, q] = lp.loc[line, base] * x.productivity_factor
            if line == 88:
                continue
            sheets["Total Hours"].loc[line, q] = published["Total Hours"].loc[line, base] * x.hours_factor
            sheets["Employment"].loc[line, q] = published["Employment"].loc[line, base] * x.employment_factor
            sheets["Nominal Output"].loc[line, q] = published["Nominal Output"].loc[line, base] * nominal.loc[line, q] / nominal.loc[line, base]
            sheets["Real Output Growth"].loc[line, q] = 400 * np.log(quantity.loc[line, q] / quantity.loc[line, q-1])
            sheets["Hours Growth"].loc[line, q] = 400 * np.log(hours.loc[line, q] / hours.loc[line, q-1])
    # Compare 3-quarter changes against published QILP in rolling historical windows.
    backtests = []
    for line in active:
        if line == 87:  # Avoid using the final anchor's sector weights in a historical holdout.
            continue
        for origin in pd.period_range(f"{base.year-2}Q1", base-3, freq="Q"):
            target = origin + 3
            if lp.loc[line, origin] <= 0 or lp.loc[line, target] <= 0:
                continue
            estimate = 100 * (quantity.loc[line, target] / quantity.loc[line, origin] / (hours.loc[line, target] / hours.loc[line, origin]) - 1)
            actual = 100 * (lp.loc[line, target] / lp.loc[line, origin] - 1)
            backtests.append({"gdp_line": line, "origin": str(origin), "target": str(target),
                              "proxy_change_pct": estimate, "published_change_pct": actual,
                              "error_pp": estimate - actual})
    backtest = pd.DataFrame(backtests)
    errors = backtest.groupby("gdp_line").error_pp.agg(overlap_windows="count", mean_error_pp="mean", mae_pp=lambda s:s.abs().mean(), max_abs_error_pp=lambda s:s.abs().max()).reset_index()
    coverage = coverage.merge(errors, on="gdp_line", how="left", validate="one_to_one")
    coverage["anchor_productivity"] = coverage.gdp_line.map(lp[base])
    coverage["latest_productivity"] = coverage.gdp_line.map(sheets["Labor Productivity"][latest])
    coverage["latest_quarter"] = str(latest)
    for name, data in sheets.items():
        if not np.allclose(data.loc[published[name].index, published[name].columns], published[name], equal_nan=True, rtol=0, atol=0):
            raise AssertionError(f"Published history changed: {name}")
    lp_growth = 400 * np.log(sheets["Labor Productivity"].loc[active, new_quarters].div(sheets["Labor Productivity"].loc[active].shift(1, axis=1)[new_quarters]))
    residual = (lp_growth - sheets["Real Output Growth"].loc[active, new_quarters] + sheets["Hours Growth"].loc[active, new_quarters]).abs().max().max()
    if residual > 1e-8:
        raise AssertionError("Productivity growth identity failed")
    if any(sheets["Labor Productivity"].loc[active, new_quarters].isna().any()):
        raise AssertionError("Incomplete extension")
    long = None
    names = {"Labor Productivity": "labor_productivity_index", "Real Output Growth": "real_output_growth_annualized_log_pct", "Total Hours": "total_hours_annualized", "Hours Growth": "hours_growth_annualized_log_pct", "Employment": "employment_persons", "Nominal Output": "nominal_output_linked_dollars"}
    for name, data in sheets.items():
        frame = data.rename_axis(index="gdp_line", columns="quarter").stack(future_stack=True).rename(names[name]).reset_index()
        long = frame if long is None else long.merge(frame, on=["gdp_line", "quarter"], validate="one_to_one")
    long = long.merge(coverage[["gdp_line", "industry", "level", "status", "method_note"]], on="gdp_line", validate="many_to_one")
    long["observation_status"] = np.where(long.quarter <= base, "published_qilp", long.status)
    long["quarter"] = long.quarter.astype(str)
    long["date"] = pd.PeriodIndex(long.quarter, freq="Q").to_timestamp().strftime("%Y-%m-%d")
    long["source_url"] = np.where(long.observation_status.eq("published_qilp"), URLS["qilp_published.xlsx"], URLS["ValueAdded.xlsx"] + " ; " + BLS_URL)
    long.to_csv(out / "qilp_extension.csv", index=False)
    coverage.to_csv(out / "coverage.csv", index=False)
    inputs.to_csv(out / "extension_inputs.csv", index=False)
    backtest.to_csv(out / "overlap_validation.csv", index=False)
    pd.DataFrame(rows).to_csv(out / "ces_mapping.csv", index=False)
    # Preserve actual current-vintage BEA nominal dollars separately from the linked compatibility sheet.
    nominal.rename_axis(index="gdp_line", columns="quarter").stack().rename("nominal_output_current_vintage_dollars").reset_index().to_csv(out / "bea_nominal_current_vintage.csv", index=False)
    catalog.loc[[s for s in ids if s in catalog.index]].reset_index().to_csv(out / "ces_series_catalog.csv", index=False)
    broad_errors = backtest[backtest.gdp_line.isin(SECTORS)]
    checks = {"passed": True, "published_history_unchanged": True, "complete_months_per_quarter": 3,
              "published_last_quarter": str(base), "latest_bea_quarter": str(latest),
              "industry_rows_retained": len(industries), "research_rows_extended": len(active),
              "benchmark_rows_extended": 1, "unextended_rows": len(excluded),
              "bea_sector_reconciliation_max_dollars": float(sector_residual.abs().max()),
              "anchor_sector_hours_divided_by_published_aggregate": float(published["Total Hours"].loc[SECTORS, base].sum() / published["Total Hours"].loc[87, base]),
              "new_quarters": [str(q) for q in new_quarters], "growth_identity_max_error_pp": float(residual),
              "overlap_three_quarter_mae_pp": float(backtest.error_pp.abs().mean()),
              "broad_sector_overlap_three_quarter_mae_pp": float(broad_errors.error_pp.abs().mean()),
              "overlap_is_real_time": False}
    (out / "validation.json").write_text(json.dumps(checks, indent=2))
    metadata = json.loads((raw / "retrieval.json").read_text())
    metadata["urls"] = URLS
    if (raw / "bls_retrieval.json").exists():
        metadata["bls_retrieval"] = json.loads((raw / "bls_retrieval.json").read_text())
    metadata.update({"method": "CES-hours research extension, not official QILP or exact replication", "checks": checks,
                     "files": {p.name: {"sha256": hashlib.sha256(p.read_bytes()).hexdigest(), "bytes": p.stat().st_size} for p in raw.iterdir() if p.is_file()}})
    (out / "source_metadata.json").write_text(json.dumps(metadata, indent=2))
    report = f"""# Quarterly industry labor productivity research extension

As of {metadata['retrieved_at_utc'][:10]}, published Chicago Fed QILP ends in {base}. Current BEA industry data end in {latest}. This dataset adds {len(new_quarters)} quarters for {len(active)} industry/aggregate rows and links one BLS nonfarm-business benchmark. All 89 original rows remain; five rows have no new estimates. This is an independent research extension, not an official Chicago Fed update or exact replication.

## Construction

For each covered industry, compute quarterly payroll hours as the mean of the three monthly products of seasonally adjusted CES employment and all-employee average weekly hours. Sum or subtract component hours before quarterly averaging. No incomplete quarters are used. Extend published hours from {base} by this payroll-hours ratio. This assumes the combined self-employed/family/payroll hours in QILP grow at the payroll proxy's rate; it does not update CPS microdata or re-run X-13. Actual worked hours can differ from paid hours.

Productivity at quarter t = published productivity at {base} × [BEA quantity index(t) / BEA quantity index({base})] / [CES payroll hours(t) / CES payroll hours({base})]. Growth rates are 400 × log quarterly ratios, in annualized percent. Higher-level rows generally use BEA's directly published quantity indexes and the mapped CES group, rather than reproducing the authors' aggregation of detailed industries. Do not sum parent and child rows.

Nonfarm private output uses a Tornqvist index across 18 mutually exclusive broad nonfarm sectors, with adjacent-quarter nominal-value-added shares. Its hours follow the growth of summed sector extensions and are rescaled to the published aggregate anchor. Published sector hours sum to 99.73% of published aggregate hours at this vintage's anchor, so preserving both histories prevents exact level additivity. This differs from the paper's finer aggregation. Private Nonfarm Business links BLS {BENCHMARK} productivity growth to its published QILP anchor; its other measures are not extended.

All six measure sheets preserve the published history, including existing missing or problematic values. New nominal-output values are linked using current BEA nominal growth from the old anchor to avoid a revision jump. These are NOT current-vintage BEA dollar levels. Actual current-vintage nominal values are provided separately in bea_nominal_current_vintage.csv. The extension does not incorporate historical revisions into QILP or refresh compensation, payroll shares, or unit labor costs.

## Coverage and uncertainty

coverage.csv identifies all 89 rows and their treatment. Agriculture, forestry/fishing, and the all-private aggregate including agriculture are not extended (four rows). Funds/trusts is not extended because its published anchor productivity is negative. CES mappings, AWH substitutions, classification mismatches, and omitted components appear in ces_mapping.csv. Every extension uses a payroll proxy; a direct mapping does not remove self-employment uncertainty. Manufacturing apparel/leather and food/beverage/tobacco, information subsectors, securities, and housing deserve particular care.

Rolling overlap comparisons predict three-quarter changes using current source vintages and compare with published QILP changes. They include source revisions and method differences and are NOT real-time forecast tests or confidence intervals. The mean absolute error is {checks['overlap_three_quarter_mae_pp']:.2f} percentage points across mapped rows and {checks['broad_sector_overlap_three_quarter_mae_pp']:.2f} points for the 18 broad sectors. Industry-specific errors appear in coverage.csv. Results can be unsuitable for fine industry rankings even when aggregate behavior looks reasonable.

## Validation and refresh

Checks confirm identical published history, complete monthly CES coverage, exact BEA name matches, positive extended anchors and hours, unique observations, and the productivity growth identity (maximum residual {residual:.2g} percentage points). Archived raw files and SHA-256 hashes identify this vintage. Rebuild the CSVs and workbook inputs with `python3 scripts/update_qilp.py --offline`; omit `--offline` to download current sources. The script fails on missing required data or changed mappings. The workbook builder is `scripts/build_qilp_workbook.mjs`.

BEA says industry data are released with the third GDP estimate. As checked on September 14, 2026, the next industry release is September 30, 2026, covering 2026 Q2. This extension contains no forecasts for quarters lacking BEA industry output.

## Sources

- [Chicago Fed paper]({URLS['article.html']})
- [Published QILP workbook]({URLS['qilp_published.xlsx']})
- [QILP release notes]({URLS['qilp-release-notes.pdf']})
- [BEA value added tables]({URLS['ValueAdded.xlsx']})
- [BEA industry release schedule](https://www.bea.gov/data/gdp/gdp-industry)
- [CES data and definitions](https://www.bls.gov/ces/data/)
- [BLS API]({BLS_URL})
"""
    (out / "methodology.md").write_text(report)
    payload = {"metadata": metadata, "base": str(base), "latest": str(latest), "quarters": [str(q) for q in allquarters],
               "industries": industries.to_dict("records"), "coverage": coverage.to_dict("records"),
               "inputs": inputs.to_dict("records"), "mapping": rows,
               "sheets": {name: data.to_numpy().tolist() for name, data in sheets.items()}}
    # JSON has no NaN type. Null represents missing values in the workbook builder.
    def clean(value):
        if isinstance(value, dict): return {k: clean(v) for k, v in value.items()}
        if isinstance(value, list): return [clean(v) for v in value]
        if isinstance(value, float) and not np.isfinite(value): return None
        return value
    (out / "workbook_data.json").write_text(json.dumps(clean(payload), allow_nan=False))
    print(json.dumps(checks, indent=2))


if __name__ == "__main__":
    main()
