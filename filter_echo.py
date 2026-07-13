#!/usr/bin/env python3
"""
ECHO weekly NPDES construction-stormwater lead extractor for DirtMatch.

Downloads EPA's weekly bulk NPDES file (~330 MB zip), filters general-permit
coverages (GPC) under construction master permits, joins facility addresses,
and writes a small CSV of fresh leads (operator name + site address).

Output columns match the n8n canonical lead schema.
Run weekly (GitHub Action provided in .github/workflows/echo-weekly.yml).
"""

import csv
import io
import os
import re
import sys
import zipfile
import urllib.request
from datetime import datetime, timedelta

ZIP_URL = "https://echo.epa.gov/files/echodownloads/npdes_downloads.zip"
ZIP_PATH = "npdes_downloads.zip"
OUT_PATH = "echo_leads.csv"
LOOKBACK_DAYS = int(os.environ.get("LOOKBACK_DAYS", "10"))  # weekly run + overlap
# States already covered by direct feeds in n8n (skip to avoid duplicates):
SKIP_STATES = {"TX", "UT", "IL", "SD", "MA", "NH", "NM", "DC", "PR", "VI"}

CGP_ID_RE = re.compile(r"^[A-Z]{2}R1[05]", re.I)  # e.g. FLR10..., SCR10..., COR40 handled via master list


def find_col(fieldnames, *candidates):
    norm = {re.sub(r"[^a-z]", "", f.lower()): f for f in fieldnames}
    for c in candidates:
        key = re.sub(r"[^a-z]", "", c.lower())
        if key in norm:
            return norm[key]
    for c in candidates:
        key = re.sub(r"[^a-z]", "", c.lower())
        for k, orig in norm.items():
            if key in k:
                return orig
    return None


def download():
    if os.path.exists(ZIP_PATH):
        print("zip already present, skipping download")
        return
    print("downloading", ZIP_URL)
    urllib.request.urlretrieve(ZIP_URL, ZIP_PATH)
    print("downloaded", os.path.getsize(ZIP_PATH), "bytes")


def member(zf, name_part):
    for n in zf.namelist():
        if name_part.lower() in n.lower():
            return n
    raise FileNotFoundError(name_part)


def reader(zf, name):
    raw = zf.open(name)
    return csv.DictReader(io.TextIOWrapper(raw, encoding="utf-8", errors="replace"))


def main():
    download()
    cutoff = datetime.utcnow() - timedelta(days=LOOKBACK_DAYS)
    zf = zipfile.ZipFile(ZIP_PATH)

    # Pass 0: construction master permit numbers
    masters = set()
    try:
        r = reader(zf, member(zf, "ICIS_MASTER_GENERAL_PERMITS"))
        c_num = find_col(r.fieldnames, "EXTERNAL_PERMIT_NMBR", "PERMIT_NMBR")
        c_name = find_col(r.fieldnames, "PERMIT_NAME", "MASTER_PERMIT_NAME")
        for row in r:
            if c_name and re.search(r"constr", row.get(c_name, "") or "", re.I):
                masters.add((row.get(c_num) or "").strip())
        print("construction masters:", len(masters))
    except FileNotFoundError:
        print("master file not found; falling back to permit-number pattern only")

    # Pass 1: permits — GPC + construction master + effective recently
    hits = {}
    r = reader(zf, member(zf, "ICIS_PERMITS"))
    f = r.fieldnames
    c_type = find_col(f, "PERMIT_TYPE_CODE")
    c_status = find_col(f, "PERMIT_STATUS_CODE")
    c_num = find_col(f, "EXTERNAL_PERMIT_NMBR")
    c_master = find_col(f, "MASTER_EXTERNAL_PERMIT_NMBR")
    c_name = find_col(f, "PERMIT_NAME")
    c_eff = find_col(f, "EFFECTIVE_DATE")
    c_state = find_col(f, "STATE_CODE", "PERMIT_STATE")
    n = 0
    for row in r:
        n += 1
        if (row.get(c_type) or "").strip() != "GPC":
            continue
        master = (row.get(c_master) or "").strip()
        num = (row.get(c_num) or "").strip()
        if masters:
            if master not in masters and not CGP_ID_RE.match(num):
                continue
        elif not CGP_ID_RE.match(num):
            continue
        eff_raw = (row.get(c_eff) or "").strip()
        eff = None
        for fmt in ("%m/%d/%Y", "%Y-%m-%d", "%d-%b-%y"):
            try:
                eff = datetime.strptime(eff_raw, fmt)
                break
            except ValueError:
                continue
        if not eff or eff < cutoff:
            continue
        st = (row.get(c_state) or num[:2]).strip().upper()
        if st in SKIP_STATES:
            continue
        operator = (row.get(c_name) or "").strip()
        if not operator:
            continue
        hits[num] = {
            "permit_number": num,
            "operator": operator,
            "effective": eff.strftime("%Y-%m-%d"),
            "state": st,
        }
    print("permit rows scanned:", n, "| fresh construction GPCs:", len(hits))

    # Pass 2: facilities — join address
    r = reader(zf, member(zf, "ICIS_FACILITIES"))
    f = r.fieldnames
    c_id = find_col(f, "NPDES_ID", "EXTERNAL_PERMIT_NMBR")
    c_fac = find_col(f, "FACILITY_NAME")
    c_addr = find_col(f, "LOCATION_ADDRESS", "STREET_ADDRESS", "ADDRESS")
    c_city = find_col(f, "CITY")
    c_st = find_col(f, "STATE_CODE", "STATE")
    c_zip = find_col(f, "ZIP", "ZIP_CODE")
    c_cty = find_col(f, "COUNTY_NAME", "COUNTY")
    for row in r:
        pid = (row.get(c_id) or "").strip()
        if pid in hits:
            h = hits[pid]
            h["site"] = (row.get(c_fac) or "").strip()
            h["address"] = (row.get(c_addr) or "").strip() if c_addr else ""
            h["city"] = (row.get(c_city) or "").strip() if c_city else ""
            h["fac_state"] = (row.get(c_st) or "").strip() if c_st else ""
            h["zip"] = (row.get(c_zip) or "").strip() if c_zip else ""
            h["county"] = (row.get(c_cty) or "").strip() if c_cty else ""

    # Write canonical-schema CSV
    with open(OUT_PATH, "w", newline="", encoding="utf-8") as out:
        w = csv.writer(out)
        w.writerow(["source", "permit_id", "permit_number", "permit_type", "issued_date",
                    "contractor_raw", "contact_email", "contact_phone", "source_contact_name",
                    "address", "city", "county", "zip", "state", "work_description",
                    "valuation", "permit_link", "dirt_volume"])
        for h in sorted(hits.values(), key=lambda x: x["effective"], reverse=True):
            st = h.get("fac_state") or h["state"]
            city = h.get("city", "")
            w.writerow([
                "EPA ECHO (" + st + ")",
                "ECHO_" + h["permit_number"],
                h["permit_number"],
                "Construction Stormwater NOI (1+ acre)",
                h["effective"],
                h["operator"],
                "", "", "",
                h.get("address", ""),
                (city + ", " + st) if city else "",
                h.get("county", ""),
                h.get("zip", ""),
                st,
                "Site: " + h.get("site", ""),
                "", "", "",
            ])
    print("wrote", OUT_PATH, "with", len(hits), "leads")


if __name__ == "__main__":
    sys.exit(main())
