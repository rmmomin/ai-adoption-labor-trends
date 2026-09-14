#!/usr/bin/env python3
"""Independent industry definitions and parsers. No Chicago Fed data are loaded."""
from pathlib import Path
import gzip
import hashlib
import io
import json
import os
import re
import zipfile

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
RAW = Path(os.environ.get("PRODUCTIVITY_RAW_DIR", ROOT / "data/independent_productivity")).resolve()
OUT = Path(os.environ.get("PRODUCTIVITY_OUT_DIR", ROOT / "outputs/independent_productivity_01a0a142")).resolve()
BEA_URL = "https://apps.bea.gov/industry/Release/XLS/GDPxInd/ValueAdded.xlsx"
BLS_URL = "https://api.bls.gov/publicAPI/v2/timeseries/data/"
CPS_URL = "https://www.census.gov/programs-surveys/cps/data/datasets.html"
# BEA table line numbers, independently validated against the table's names.
# BLS series use CES industry identifiers. Each hours term is (E code, AWH code, sign).
BROAD = [
    ("21", 6, "Mining", "10210000"),
    ("22", 10, "Utilities", "44220000"),
    ("23", 11, "Construction", "20000000"),
    ("31-33", 12, "Manufacturing", "30000000"),
    ("42", 34, "Wholesale trade", "41420000"),
    ("44-45", 35, "Retail trade", "42000000"),
    ("48-49", 40, "Transportation and warehousing", "43000000"),
    ("51", 49, "Information", "50000000"),
    ("52", 55, "Finance and insurance", "55520000"),
    ("53", 60, "Real estate and rental and leasing", "55530000"),
    ("54", 66, "Professional, scientific, and technical services", "60540000"),
    ("55", 70, "Management of companies and enterprises", "60550000"),
    ("56", 71, "Administrative and waste management services", "60560000"),
    ("61", 75, "Educational services", "65610000"),
    ("62", 76, "Health care and social assistance", "65620000"),
    ("71", 82, "Arts, entertainment, and recreation", "70710000"),
    ("72", 85, "Accommodation and food services", "70720000"),
    ("81", 88, "Other services, except government", "80000000"),
]
REAL_TERMS = [("55531000", "55531000", 1), ("55532000", "55532000", 1),
              ("55533000", "55532000", 1)]
HOURS_TERMS = {n: [(code, code, 1)] for n, _, _, code in BROAD}
HOURS_TERMS["53"] = REAL_TERMS
HOURS_TERMS["52"] = [("55000000", "55000000", 1)] + [(e, h, -s) for e, h, s in REAL_TERMS]
HOURS_TERMS["61"] = [("65000000", "65000000", 1), ("65620000", "65620000", -1)]
NOTES = {
    "52": "Financial-activities hours less real-estate/rental/leasing hours; inherits the small NAICS 533 AWH proxy.",
    "53": "Sum NAICS 531, 532, 533 payroll hours; 533 uses NAICS 532 AWH. Output includes imputed owner-occupied housing rent.",
    "61": "Private education hours are private education/health hours less health/social-assistance hours.",
    "81": "CPS private-household employees are added to match the broader BEA output scope.",
}
# Optional detail is restricted to direct, similarly scoped CES employment/AWH pairs.
# It is a payroll-hours productivity proxy, not an all-worker estimate.
DETAIL = {
    7: "10211000", 8: "10212000", 9: "10213000", 13: "31000000",
    14: "31321000", 15: "31327000", 16: "31331000", 17: "31332000",
    18: "31333000", 19: "31334000", 20: "31335000", 21: "31336001",
    23: "31337000", 24: "31339000", 25: "32000000", 29: "32322000",
    30: "32323000", 32: "32325000", 33: "32326000",
    36: "42441000", 41: "43481000", 42: "43482000", 43: "43483000", 44: "43484000",
    45: "43485000", 46: "43486000", 48: "43493000", 50: "50513000",
    51: "50512000", 58: "55524000", 61: "55531000", 67: "60541100",
    68: "60541500", 72: "60561000", 73: "60562000", 77: "65621000",
    78: "65622000", 79: "65623000", 80: "65624000", 84: "70713000",
    86: "70721000", 87: "70722000",
}
# Drop unsupported AWH and changed publishing classification rather than invent a series.
DETAIL_EXCLUDE = {42: "No direct all-employee AWH series", 43: "No direct all-employee AWH series",
                  46: "No direct all-employee AWH series", 50: "CES 2022 publishing scope does not exactly match BEA"}


def read_catalog(path):
    data = pd.read_csv(path, sep="\t", dtype=str)
    data.columns = data.columns.str.strip()
    return data.apply(lambda c: c.str.strip())


def read_bea(path):
    panels = []
    for sheet, measure in [("TVA103-Q", "real_value_added_quantity_index"),
                           ("TVA105-Q", "nominal_value_added_millions")]:
        raw = pd.read_excel(path, sheet_name=sheet, header=7)
        nums = pd.to_numeric(raw.iloc[:, 0], errors="coerce")
        keep = nums.notna()
        quarters = [c for c in raw if re.fullmatch(r"\d{4}Q[1-4]", str(c))]
        data = raw.loc[keep, quarters].apply(pd.to_numeric, errors="coerce")
        data.index = nums[keep].astype(int).to_numpy()
        data.index.name = "bea_line"
        data.columns.name = "quarter"
        panel = data.stack(dropna=False).rename(measure).reset_index()
        names = pd.Series(raw.loc[keep].iloc[:, 1].str.strip().to_numpy(), index=data.index)
        panel["industry"] = panel.bea_line.map(names)
        panels.append(panel)
    result = panels[0].merge(panels[1], on=["bea_line", "quarter", "industry"], validate="one_to_one")
    result["quarter"] = pd.PeriodIndex(result.quarter, freq="Q")
    for _, line, name, _ in BROAD:
        assert names.loc[line] == name, (line, name, names.loc[line])
    # Direct nominal-value-added components must reconcile with private output less agriculture.
    nominal = result.pivot(index="quarter", columns="bea_line", values="nominal_value_added_millions")
    residual = nominal[[r[1] for r in BROAD]].sum(axis=1) - nominal[2] + nominal[3]
    assert residual.abs().max() <= 10, residual.abs().max()  # table rounded to $1 million
    return result


def cps_sector(code):
    ranges = [(370, 490, "21"), (570, 690, "22"), (770, 770, "23"),
              (1070, 3990, "31-33"), (4070, 4590, "42"), (4670, 5799, "44-45"),
              (6070, 6390, "48-49"), (6470, 6789, "51"), (6870, 6999, "52"),
              (7070, 7190, "53"), (7270, 7490, "54"), (7570, 7570, "55"),
              (7580, 7790, "56"), (7860, 7890, "61"), (7970, 8470, "62"),
              (8560, 8599, "71"), (8660, 8699, "72"), (8770, 9290, "81")]
    for lo, hi, name in ranges:
        if lo <= code <= hi:
            return name
    return "excluded"


def dictionary_for(year, month):
    # Select the dictionaries linked by each year's Census landing page.
    from fetch_independent_productivity import hrefs
    urls = [u for u in hrefs((RAW / f"cps_index_{year}.html").read_text())
            if u.endswith(".txt") and "www2.census.gov" in u and "revwgts" not in u]
    if year == 2012:
        urls = [u for u in urls if ("may12" in u) == (month >= 5)]
    full = [u for u in urls if "cps_dd_record_layout" not in u]
    assert len(full) == 1, (year, month, full)
    return RAW / "cps_dict" / full[0].rsplit("/", 1)[-1]


def parse_cps(path):
    year = int(path.parent.name)
    month = {m: i for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}[path.name[:3]]
    dictionary = dictionary_for(year, month)
    documentation = dictionary.read_text(errors="replace")
    fields = ["HRMONTH", "HRYEAR4", "PEMLR", "PEIO1COW", "PEIO1ICD", "PWCMPWGT", "PEHRACT1", "PRTAGE"]
    offsets, widths = [], []
    for field in fields:
        alternatives = [field, "PEAGE"] if field == "PRTAGE" else [field]
        found = []
        for key in alternatives:
            matches = re.findall(r"^\s*"+key+r"\s+(\d+)\s+[^\n]*?\(?\s*(\d+)\s*-\s*(\d+)\s*\)?\s*$", documentation, re.M)
            found = [(lo, hi) for size, lo, hi in matches if int(hi)-int(lo)+1 == int(size)]
            if found:
                break
        assert len(found) == 1, (dictionary.name, field, found)
        lo, hi = map(int, found[0])
        offsets.append(lo-1)
        widths.append(hi-lo+1)
    compressed = path.read_bytes()
    if compressed.startswith(b"\x1f\x8b"):
        blob = gzip.decompress(compressed)
        compression = "gzip"
    elif compressed.startswith(b"PK"):
        # Some Census .dat.gz URLs return a ZIP archive. Inspect its actual format.
        with zipfile.ZipFile(io.BytesIO(compressed)) as archive:
            files = [n for n in archive.namelist() if n.lower().endswith((".dat", ".cps"))]
            assert len(files) == 1, (path, archive.namelist())
            blob = archive.read(files[0])
        compression = "zip served at .gz URL"
    else:
        raise ValueError(f"Unrecognized Census archive format: {path}")
    record_size = blob.index(b"\n")+1
    # Census fixed-width files have a constant record size including the newline.
    assert len(blob) % record_size == 0, (path.name, len(blob), record_size)
    dtype = np.dtype({"names": fields, "formats": [f"S{w}" for w in widths],
                      "offsets": offsets, "itemsize": record_size})
    raw = np.frombuffer(blob, dtype=dtype)
    arrays = {}
    for field in fields:
        value = np.char.strip(raw[field])
        arrays[field] = np.where(value == b"", b"-1", value).astype(np.int64)
    assert np.all(arrays["HRYEAR4"] == year) and np.all(arrays["HRMONTH"] == month)
    persons = pd.DataFrame(arrays)
    persons = persons[persons.PRTAGE.ge(16) & persons.PEMLR.isin([1, 2]) & persons.PWCMPWGT.gt(0)].copy()
    persons["weight"] = persons.PWCMPWGT / 10000
    # The comparison hours measure uses actual primary-job hours, zero for employed absent.
    hours = persons.PEHRACT1.where(persons.PEMLR.eq(1), 0)
    assert hours.between(0, 99).all(), path.name
    persons["weighted_actual_hours"] = persons.weight * hours
    tab = persons.groupby(["PEIO1ICD", "PEIO1COW"]).agg(
        employed_persons=("weight", "sum"), actual_weekly_hours=("weighted_actual_hours", "sum"),
        sample_persons=("weight", "size")).reset_index()
    tab.columns = ["census_industry", "class_of_worker", "employed_persons", "actual_weekly_hours", "sample_persons"]
    tab["date"] = f"{year}-{month:02d}-01"
    tab["naics"] = tab.census_industry.map(cps_sector)
    national = tab.employed_persons.sum()
    assert 100e6 < national < 200e6, (path.name, national)
    selected = tab[tab.class_of_worker.isin([4, 5, 6, 7, 8]) & tab.naics.eq("excluded")]
    # Excluded private jobs should only be agriculture, public administration or military.
    bad = selected[~(selected.census_industry.lt(370) | selected.census_industry.ge(9370))]
    assert bad.empty, bad.to_string()
    meta = {"date": tab.date.iloc[0], "raw_records": len(raw), "employed_sample": len(persons),
            "employed_persons": national, "dictionary": dictionary.name,
            "dictionary_sha256": hashlib.sha256(dictionary.read_bytes()).hexdigest(),
            "raw_sha256": hashlib.sha256(compressed).hexdigest(), "archive_format": compression,
            "fields": {k: [o+1, o+w] for k, o, w in zip(fields, offsets, widths)}}
    return tab, meta


def monthly_cps():
    cache = RAW / "cps_aggregates"
    cache.mkdir(exist_ok=True)
    all_tabs, metadata = [], []
    files = sorted((RAW / "cps").glob("*/*pub.dat.gz"))
    for i, path in enumerate(files, 1):
        dest = cache / (path.parent.name+"_"+path.name[:5]+".csv")
        if dest.exists() and dest.with_suffix(".json").exists():
            tab = pd.read_csv(dest, dtype={"naics": str})
            meta = json.loads(dest.with_suffix(".json").read_text())
        else:
            tab, meta = parse_cps(path)
            tab.to_csv(dest, index=False)
            dest.with_suffix(".json").write_text(json.dumps(meta, indent=2))
        all_tabs.append(tab)
        metadata.append(meta)
        if i % 12 == 0:
            print(f"Parsed {i}/{len(files)} CPS months", flush=True)
    tabs = pd.concat(all_tabs, ignore_index=True)
    tabs["date"] = pd.to_datetime(tabs.date)
    return tabs, metadata
