#!/usr/bin/env python3
"""
valtera-indonesia-regions
Build pipeline to normalize raw administrative region data into:
- Static CDN-ready hierarchical JSON APIs (with postal_code)
- Relational normalized CSVs
- Database dumps (MySQL, PostgreSQL, SQLite)
- Full monolithic JSON
"""

import csv
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Dict, List, Tuple

BASE_DIR = Path(__file__).resolve().parent.parent
SOURCE_CSV = BASE_DIR / "data" / "kode_wilayah.csv"
POSTAL_CSV = BASE_DIR / "data" / "postal_codes.csv"
DIST_DIR = BASE_DIR / "dist"
API_DIR = DIST_DIR / "api"
CSV_DIR = DIST_DIR / "csv"
SQL_DIR = DIST_DIR / "sql"


def clean_text(val: str) -> str:
    """Sanitize string values by fixing unescaped quotes, stray ticks, and spacing."""
    if not val:
        return ""
    val = val.strip()
    if val.startswith("'") and val.endswith("'") and len(val) > 1:
        val = val[1:-1]
    val = val.replace("''", "'")
    val = re.sub(r"\s+", " ", val).strip()
    return val


def escape_sql(val: str) -> str:
    """Escape single quotes for SQL insert statements."""
    return val.replace("'", "''")


def load_postal_codes(postal_path: Path) -> Dict[str, str]:
    """Load village_code -> postal_code dictionary if available."""
    if not postal_path.exists():
        return {}
    mapping = {}
    with open(postal_path, mode="r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            mapping[row["village_code"].strip()] = row["postal_code"].strip()
    return mapping


def load_and_normalize(source_path: Path, postal_map: Dict[str, str]) -> Tuple[List[dict], List[dict], List[dict], List[dict]]:
    """Parse raw CSV and extract normalized entities with postal codes."""
    provinces: Dict[str, dict] = {}
    regencies: Dict[str, dict] = {}
    districts: Dict[str, dict] = {}
    villages: List[dict] = []

    with open(source_path, mode="r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            p_code = row["kode_provinsi"].strip()
            p_name = clean_text(row["nama_provinsi"])

            k_code = row["kode_kabko"].strip()
            k_name = clean_text(row["nama_kabko"])

            kec_code = row["kode_kecamatan"].strip()
            kec_name = clean_text(row["nama_kecamatan"])

            kel_code = row["kode_kelurahan"].strip()
            kel_name = clean_text(row["nama_kelurahan"])

            if p_code not in provinces:
                provinces[p_code] = {"code": p_code, "name": p_name}

            if k_code not in regencies:
                regencies[k_code] = {"code": k_code, "province_code": p_code, "name": k_name}

            if kec_code not in districts:
                districts[kec_code] = {"code": kec_code, "regency_code": k_code, "name": kec_name}

            p_code_val = postal_map.get(kel_code, "")
            villages.append({
                "code": kel_code,
                "district_code": kec_code,
                "name": kel_name,
                "postal_code": p_code_val,
            })

    sorted_provinces = sorted(provinces.values(), key=lambda x: x["code"])
    sorted_regencies = sorted(regencies.values(), key=lambda x: x["code"])
    sorted_districts = sorted(districts.values(), key=lambda x: x["code"])
    sorted_villages = sorted(villages, key=lambda x: x["code"])

    return sorted_provinces, sorted_regencies, sorted_districts, sorted_villages


def generate_static_api(
    provinces: List[dict],
    regencies: List[dict],
    districts: List[dict],
    villages: List[dict],
):
    """Generate hierarchical JSON files designed for CDN caching."""
    regencies_dir = API_DIR / "regencies"
    districts_dir = API_DIR / "districts"
    villages_dir = API_DIR / "villages"

    for d in [API_DIR, regencies_dir, districts_dir, villages_dir]:
        d.mkdir(parents=True, exist_ok=True)

    # 1. provinces.json
    with open(API_DIR / "provinces.json", "w", encoding="utf-8") as f:
        json.dump(provinces, f, ensure_ascii=False, indent=2)

    # 2. regencies grouped by province
    regencies_by_prov: Dict[str, List[dict]] = {}
    for r in regencies:
        regencies_by_prov.setdefault(r["province_code"], []).append(r)

    for prov_code, items in regencies_by_prov.items():
        with open(regencies_dir / f"{prov_code}.json", "w", encoding="utf-8") as f:
            json.dump(items, f, ensure_ascii=False, indent=2)

    # 3. districts grouped by regency
    districts_by_reg: Dict[str, List[dict]] = {}
    for d in districts:
        districts_by_reg.setdefault(d["regency_code"], []).append(d)

    for reg_code, items in districts_by_reg.items():
        with open(districts_dir / f"{reg_code}.json", "w", encoding="utf-8") as f:
            json.dump(items, f, ensure_ascii=False, indent=2)

    # 4. villages grouped by district
    villages_by_dist: Dict[str, List[dict]] = {}
    for v in villages:
        villages_by_dist.setdefault(v["district_code"], []).append(v)

    for dist_code, items in villages_by_dist.items():
        with open(villages_dir / f"{dist_code}.json", "w", encoding="utf-8") as f:
            json.dump(items, f, ensure_ascii=False, indent=2)


def generate_normalized_csv(
    provinces: List[dict],
    regencies: List[dict],
    districts: List[dict],
    villages: List[dict],
):
    """Write normalized CSV tables."""
    CSV_DIR.mkdir(parents=True, exist_ok=True)

    def write_csv(filepath: Path, fieldnames: List[str], rows: List[dict]):
        with open(filepath, "w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)

    write_csv(CSV_DIR / "provinces.csv", ["code", "name"], provinces)
    write_csv(CSV_DIR / "regencies.csv", ["code", "province_code", "name"], regencies)
    write_csv(CSV_DIR / "districts.csv", ["code", "regency_code", "name"], districts)
    write_csv(CSV_DIR / "villages.csv", ["code", "district_code", "name", "postal_code"], villages)


def generate_monolithic_json(
    provinces: List[dict],
    regencies: List[dict],
    districts: List[dict],
    villages: List[dict],
):
    """Write all records in a single minified bundle."""
    DIST_DIR.mkdir(parents=True, exist_ok=True)
    bundle = {
        "metadata": {
            "version": "1.0.0",
            "total_provinces": len(provinces),
            "total_regencies": len(regencies),
            "total_districts": len(districts),
            "total_villages": len(villages),
        },
        "provinces": provinces,
        "regencies": regencies,
        "districts": districts,
        "villages": villages,
    }
    with open(DIST_DIR / "indonesia-regions.min.json", "w", encoding="utf-8") as f:
        json.dump(bundle, f, ensure_ascii=False, separators=(",", ":"))


def generate_sql_dumps(
    provinces: List[dict],
    regencies: List[dict],
    districts: List[dict],
    villages: List[dict],
):
    """Generate ready-to-import SQL dumps for MySQL, PostgreSQL, and SQLite."""
    SQL_DIR.mkdir(parents=True, exist_ok=True)
    batch_size = 500

    def batch_inserts(table: str, columns: List[str], data: List[dict]) -> List[str]:
        lines = []
        cols_joined = ", ".join(columns)
        for i in range(0, len(data), batch_size):
            chunk = data[i : i + batch_size]
            values = []
            for row in chunk:
                vals = []
                for col in columns:
                    val = row.get(col, "")
                    if val == "" and col == "postal_code":
                        vals.append("NULL")
                    else:
                        vals.append(f"'{escape_sql(val)}'")
                values.append(f"({', '.join(vals)})")
            lines.append(f"INSERT INTO {table} ({cols_joined}) VALUES\n  " + ",\n  ".join(values) + ";")
        return lines

    # --- MySQL ---
    mysql_file = SQL_DIR / "mysql.sql"
    with open(mysql_file, "w", encoding="utf-8") as f:
        f.write("-- Valtera Indonesia Regions (MySQL)\n")
        f.write("SET FOREIGN_KEY_CHECKS = 0;\n")
        f.write("SET NAMES utf8mb4;\n\n")

        f.write("DROP TABLE IF EXISTS `villages`;\n")
        f.write("DROP TABLE IF EXISTS `districts`;\n")
        f.write("DROP TABLE IF EXISTS `regencies`;\n")
        f.write("DROP TABLE IF EXISTS `provinces`;\n\n")

        f.write("CREATE TABLE `provinces` (\n")
        f.write("  `code` CHAR(2) NOT NULL PRIMARY KEY,\n")
        f.write("  `name` VARCHAR(100) NOT NULL\n")
        f.write(") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;\n\n")

        f.write("CREATE TABLE `regencies` (\n")
        f.write("  `code` CHAR(4) NOT NULL PRIMARY KEY,\n")
        f.write("  `province_code` CHAR(2) NOT NULL,\n")
        f.write("  `name` VARCHAR(100) NOT NULL,\n")
        f.write("  KEY `idx_regencies_province` (`province_code`),\n")
        f.write("  CONSTRAINT `fk_regencies_province` FOREIGN KEY (`province_code`) REFERENCES `provinces` (`code`) ON DELETE CASCADE\n")
        f.write(") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;\n\n")

        f.write("CREATE TABLE `districts` (\n")
        f.write("  `code` CHAR(6) NOT NULL PRIMARY KEY,\n")
        f.write("  `regency_code` CHAR(4) NOT NULL,\n")
        f.write("  `name` VARCHAR(100) NOT NULL,\n")
        f.write("  KEY `idx_districts_regency` (`regency_code`),\n")
        f.write("  CONSTRAINT `fk_districts_regency` FOREIGN KEY (`regency_code`) REFERENCES `regencies` (`code`) ON DELETE CASCADE\n")
        f.write(") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;\n\n")

        f.write("CREATE TABLE `villages` (\n")
        f.write("  `code` CHAR(10) NOT NULL PRIMARY KEY,\n")
        f.write("  `district_code` CHAR(6) NOT NULL,\n")
        f.write("  `name` VARCHAR(100) NOT NULL,\n")
        f.write("  `postal_code` CHAR(5) DEFAULT NULL,\n")
        f.write("  KEY `idx_villages_district` (`district_code`),\n")
        f.write("  KEY `idx_villages_postal` (`postal_code`),\n")
        f.write("  CONSTRAINT `fk_villages_district` FOREIGN KEY (`district_code`) REFERENCES `districts` (`code`) ON DELETE CASCADE\n")
        f.write(") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;\n\n")

        for stmt in batch_inserts("provinces", ["code", "name"], provinces):
            f.write(stmt + "\n\n")
        for stmt in batch_inserts("regencies", ["code", "province_code", "name"], regencies):
            f.write(stmt + "\n\n")
        for stmt in batch_inserts("districts", ["code", "regency_code", "name"], districts):
            f.write(stmt + "\n\n")
        for stmt in batch_inserts("villages", ["code", "district_code", "name", "postal_code"], villages):
            f.write(stmt + "\n\n")

        f.write("SET FOREIGN_KEY_CHECKS = 1;\n")

    # --- PostgreSQL ---
    pg_file = SQL_DIR / "postgresql.sql"
    with open(pg_file, "w", encoding="utf-8") as f:
        f.write("-- Valtera Indonesia Regions (PostgreSQL)\n")
        f.write("BEGIN;\n\n")

        f.write("DROP TABLE IF EXISTS villages CASCADE;\n")
        f.write("DROP TABLE IF EXISTS districts CASCADE;\n")
        f.write("DROP TABLE IF EXISTS regencies CASCADE;\n")
        f.write("DROP TABLE IF EXISTS provinces CASCADE;\n\n")

        f.write("CREATE TABLE provinces (\n")
        f.write("  code CHAR(2) PRIMARY KEY,\n")
        f.write("  name VARCHAR(100) NOT NULL\n")
        f.write(");\n\n")

        f.write("CREATE TABLE regencies (\n")
        f.write("  code CHAR(4) PRIMARY KEY,\n")
        f.write("  province_code CHAR(2) NOT NULL REFERENCES provinces(code) ON DELETE CASCADE,\n")
        f.write("  name VARCHAR(100) NOT NULL\n")
        f.write(");\n")
        f.write("CREATE INDEX idx_regencies_province ON regencies(province_code);\n\n")

        f.write("CREATE TABLE districts (\n")
        f.write("  code CHAR(6) PRIMARY KEY,\n")
        f.write("  regency_code CHAR(4) NOT NULL REFERENCES regencies(code) ON DELETE CASCADE,\n")
        f.write("  name VARCHAR(100) NOT NULL\n")
        f.write(");\n")
        f.write("CREATE INDEX idx_districts_regency ON districts(regency_code);\n\n")

        f.write("CREATE TABLE villages (\n")
        f.write("  code CHAR(10) PRIMARY KEY,\n")
        f.write("  district_code CHAR(6) NOT NULL REFERENCES districts(code) ON DELETE CASCADE,\n")
        f.write("  name VARCHAR(100) NOT NULL,\n")
        f.write("  postal_code CHAR(5)\n")
        f.write(");\n")
        f.write("CREATE INDEX idx_villages_district ON villages(district_code);\n")
        f.write("CREATE INDEX idx_villages_postal ON villages(postal_code);\n\n")

        for stmt in batch_inserts("provinces", ["code", "name"], provinces):
            f.write(stmt + "\n\n")
        for stmt in batch_inserts("regencies", ["code", "province_code", "name"], regencies):
            f.write(stmt + "\n\n")
        for stmt in batch_inserts("districts", ["code", "regency_code", "name"], districts):
            f.write(stmt + "\n\n")
        for stmt in batch_inserts("villages", ["code", "district_code", "name", "postal_code"], villages):
            f.write(stmt + "\n\n")

        f.write("COMMIT;\n")

    # --- SQLite ---
    sqlite_file = SQL_DIR / "sqlite.sql"
    with open(sqlite_file, "w", encoding="utf-8") as f:
        f.write("-- Valtera Indonesia Regions (SQLite)\n")
        f.write("PRAGMA foreign_keys = OFF;\n")
        f.write("BEGIN TRANSACTION;\n\n")

        f.write("DROP TABLE IF EXISTS villages;\n")
        f.write("DROP TABLE IF EXISTS districts;\n")
        f.write("DROP TABLE IF EXISTS regencies;\n")
        f.write("DROP TABLE IF EXISTS provinces;\n\n")

        f.write("CREATE TABLE provinces (\n")
        f.write("  code TEXT PRIMARY KEY,\n")
        f.write("  name TEXT NOT NULL\n")
        f.write(");\n\n")

        f.write("CREATE TABLE regencies (\n")
        f.write("  code TEXT PRIMARY KEY,\n")
        f.write("  province_code TEXT NOT NULL,\n")
        f.write("  name TEXT NOT NULL,\n")
        f.write("  FOREIGN KEY (province_code) REFERENCES provinces(code)\n")
        f.write(");\n")
        f.write("CREATE INDEX idx_regencies_province ON regencies(province_code);\n\n")

        f.write("CREATE TABLE districts (\n")
        f.write("  code TEXT PRIMARY KEY,\n")
        f.write("  regency_code TEXT NOT NULL,\n")
        f.write("  name TEXT NOT NULL,\n")
        f.write("  FOREIGN KEY (regency_code) REFERENCES regencies(code)\n")
        f.write(");\n")
        f.write("CREATE INDEX idx_districts_regency ON districts(regency_code);\n\n")

        f.write("CREATE TABLE villages (\n")
        f.write("  code TEXT PRIMARY KEY,\n")
        f.write("  district_code TEXT NOT NULL,\n")
        f.write("  name TEXT NOT NULL,\n")
        f.write("  postal_code TEXT,\n")
        f.write("  FOREIGN KEY (district_code) REFERENCES districts(code)\n")
        f.write(");\n")
        f.write("CREATE INDEX idx_villages_district ON villages(district_code);\n")
        f.write("CREATE INDEX idx_villages_postal ON villages(postal_code);\n\n")

        for stmt in batch_inserts("provinces", ["code", "name"], provinces):
            f.write(stmt + "\n\n")
        for stmt in batch_inserts("regencies", ["code", "province_code", "name"], regencies):
            f.write(stmt + "\n\n")
        for stmt in batch_inserts("districts", ["code", "regency_code", "name"], districts):
            f.write(stmt + "\n\n")
        for stmt in batch_inserts("villages", ["code", "district_code", "name", "postal_code"], villages):
            f.write(stmt + "\n\n")

        f.write("COMMIT;\n")
        f.write("PRAGMA foreign_keys = ON;\n")


def main():
    if not SOURCE_CSV.exists():
        print(f"Error: Source file not found at {SOURCE_CSV}", file=sys.stderr)
        sys.exit(1)

    start_time = time.time()
    print("-> Loading postal code mapping...")
    postal_map = load_postal_codes(POSTAL_CSV)
    print(f"   * Loaded {len(postal_map):,} postal codes from {POSTAL_CSV.name}")

    print("-> Reading & sanitizing raw region dataset...")
    provinces, regencies, districts, villages = load_and_normalize(SOURCE_CSV, postal_map)

    mapped_postal_count = sum(1 for v in villages if v.get("postal_code"))
    print(f"   * Provinces:  {len(provinces):>6,}")
    print(f"   * Regencies:  {len(regencies):>6,}")
    print(f"   * Districts:  {len(districts):>6,}")
    print(f"   * Villages:   {len(villages):>6,} ({mapped_postal_count:,} with postal codes)")

    print("-> Generating static CDN API...")
    generate_static_api(provinces, regencies, districts, villages)

    print("-> Generating normalized CSV files...")
    generate_normalized_csv(provinces, regencies, districts, villages)

    print("-> Generating monolithic minified JSON...")
    generate_monolithic_json(provinces, regencies, districts, villages)

    print("-> Generating SQL dumps (MySQL, PostgreSQL, SQLite)...")
    generate_sql_dumps(provinces, regencies, districts, villages)

    elapsed = time.time() - start_time
    print(f"\nDone in {elapsed:.2f}s! All artifacts written to ./dist/")


if __name__ == "__main__":
    main()
