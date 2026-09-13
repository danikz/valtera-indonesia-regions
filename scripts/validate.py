#!/usr/bin/env python3
"""
valtera-indonesia-regions
Data integrity and relational validation test suite.
"""

import csv
import re
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
CSV_DIR = BASE_DIR / "dist" / "csv"


def load_csv(path: Path) -> list[dict]:
    if not path.exists():
        print(f"Error: {path} does not exist. Run scripts/build.py first.", file=sys.stderr)
        sys.exit(1)
    with open(path, mode="r", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def validate():
    print("-> Running dataset integrity checks...")

    provinces = load_csv(CSV_DIR / "provinces.csv")
    regencies = load_csv(CSV_DIR / "regencies.csv")
    districts = load_csv(CSV_DIR / "districts.csv")
    villages = load_csv(CSV_DIR / "villages.csv")

    errors = []

    # 1. Check unique keys and code formatting
    def check_entities(name, items, pattern):
        seen = set()
        for idx, item in enumerate(items, 1):
            code = item.get("code", "")

            if not code or not re.match(pattern, code):
                errors.append(f"[{name}] Invalid code format at row {idx}: '{code}'")
            if code in seen:
                errors.append(f"[{name}] Duplicate primary key at row {idx}: '{code}'")
            seen.add(code)

        return seen

    prov_codes = check_entities("Provinces", provinces, r"^\d{2}$")
    reg_codes = check_entities("Regencies", regencies, r"^\d{4}$")
    dist_codes = check_entities("Districts", districts, r"^\d{6}$")
    vill_codes = check_entities("Villages", villages, r"^\d{10}$")

    # 2. Check foreign keys and prefix hierarchy
    for r in regencies:
        p_code = r["province_code"]
        if p_code not in prov_codes:
            errors.append(f"[Regencies] Missing parent province '{p_code}' for regency '{r['code']}'")
        if not r["code"].startswith(p_code):
            errors.append(f"[Regencies] Code '{r['code']}' does not start with parent prefix '{p_code}'")

    for d in districts:
        r_code = d["regency_code"]
        if r_code not in reg_codes:
            errors.append(f"[Districts] Missing parent regency '{r_code}' for district '{d['code']}'")
        if not d["code"].startswith(r_code):
            errors.append(f"[Districts] Code '{d['code']}' does not start with parent prefix '{r_code}'")

    for v in villages:
        d_code = v["district_code"]
        if d_code not in dist_codes:
            errors.append(f"[Villages] Missing parent district '{d_code}' for village '{v['code']}'")
        if not v["code"].startswith(d_code):
            errors.append(f"[Villages] Code '{v['code']}' does not start with parent prefix '{d_code}'")

    if errors:
        print(f"\n[FAIL] Found {len(errors)} integrity errors:")
        for err in errors[:20]:
            print(f"  - {err}")
        if len(errors) > 20:
            print(f"  ... and {len(errors) - 20} more errors.")
        sys.exit(1)

    print(f"   [PASS] {len(provinces)} Provinces validated (unique, valid 2-digit format)")
    print(f"   [PASS] {len(regencies):,} Regencies validated (unique, valid 4-digit format & parent hierarchy)")
    print(f"   [PASS] {len(districts):,} Districts validated (unique, valid 6-digit format & parent hierarchy)")
    print(f"   [PASS] {len(villages):,} Villages validated (unique, valid 10-digit format & parent hierarchy)")
    print("\nAll relational integrity checks passed successfully!\n")


if __name__ == "__main__":
    validate()
