"""
SYNAPSE HEALTHCARE ANALYTICS PLATFORM
STEP 4: ETL Pipeline — Load CSVs into Snowflake Staging
Simulates loading from SQL Server → Snowflake via Python.
In production: replace pd.read_csv() with pyodbc/SQLAlchemy SQL Server reads.

Install: pip install snowflake-connector-python pandas python-dotenv
Run:     python 04_etl_pipeline.py
Prereq:  Create a .env file with Snowflake credentials (see below)
"""

import os
import pandas as pd
import numpy as np
import logging
from datetime import datetime
from dotenv import load_dotenv

# ── Logging setup ─────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s │ %(levelname)s │ %(message)s",
    handlers=[
        logging.FileHandler("logs/etl_pipeline.log"),
        logging.StreamHandler()
    ]
)
log = logging.getLogger("synapse_etl")
os.makedirs("logs", exist_ok=True)

load_dotenv()

# ─────────────────────────────────────────────────────
# CONFIGURATION
# Create a .env file with:
#
# SNOWFLAKE_ACCOUNT=your_account.region.cloud
# SNOWFLAKE_USER=your_username
# SNOWFLAKE_PASSWORD=your_password
# SNOWFLAKE_DATABASE=SYNAPSE_DB
# SNOWFLAKE_WAREHOUSE=SYNAPSE_WH
# SNOWFLAKE_ROLE=SYSADMIN
# ─────────────────────────────────────────────────────

SNOWFLAKE_CONFIG = {
    "account":   os.getenv("SNOWFLAKE_ACCOUNT",   "your_account"),
    "user":      os.getenv("SNOWFLAKE_USER",       "your_user"),
    "password":  os.getenv("SNOWFLAKE_PASSWORD",   "your_password"),
    "database":  os.getenv("SNOWFLAKE_DATABASE",   "SYNAPSE_DB"),
    "warehouse": os.getenv("SNOWFLAKE_WAREHOUSE",  "SYNAPSE_WH"),
    "role":      os.getenv("SNOWFLAKE_ROLE",       "SYSADMIN"),
    "schema":    "STAGING"
}

DATA_DIR = "data"

# Table configs: csv file → snowflake table → date columns to parse
LOAD_CONFIG = [
    {
        "csv":        "dim_hospital.csv",
        "table":      "STAGING.HOSPITAL",
        "date_cols":  [],
        "chunk_size": 1000
    },
    {
        "csv":        "dim_department.csv",
        "table":      "STAGING.DEPARTMENT",
        "date_cols":  [],
        "chunk_size": 1000
    },
    {
        "csv":        "dim_ambulance.csv",
        "table":      "STAGING.AMBULANCE",
        "date_cols":  [],
        "chunk_size": 1000
    },
    {
        "csv":        "dim_date.csv",
        "table":      "STAGING.DIM_DATE",
        "date_cols":  ["full_date"],
        "chunk_size": 500
    },
    {
        "csv":        "fact_bed_occupancy.csv",
        "table":      "STAGING.BED_OCCUPANCY",
        "date_cols":  ["snapshot_ts"],
        "chunk_size": 5000        # larger chunks for big fact tables
    },
    {
        "csv":        "fact_ambulance_dispatch.csv",
        "table":      "STAGING.AMBULANCE_DISPATCH",
        "date_cols":  ["call_timestamp", "dispatch_timestamp",
                       "on_scene_timestamp", "hospital_arrival_ts"],
        "chunk_size": 2000
    },
    {
        "csv":        "fact_patient_flow.csv",
        "table":      "STAGING.PATIENT_FLOW",
        "date_cols":  ["admit_timestamp", "discharge_timestamp"],
        "chunk_size": 2000
    }
]


# ─────────────────────────────────────────────────────
# SNOWFLAKE CONNECTION
# ─────────────────────────────────────────────────────
def get_snowflake_connection():
    """Create and return a Snowflake connection."""
    try:
        import snowflake.connector
        conn = snowflake.connector.connect(**SNOWFLAKE_CONFIG)
        log.info("✅ Snowflake connection established")
        return conn
    except ImportError:
        log.error("snowflake-connector-python not installed. Run: pip install snowflake-connector-python")
        raise
    except Exception as e:
        log.error(f"Snowflake connection failed: {e}")
        raise


# ─────────────────────────────────────────────────────
# DATA QUALITY CHECKS (pre-load validation)
# ─────────────────────────────────────────────────────
def run_dq_checks(df: pd.DataFrame, table_name: str) -> dict:
    """Run pre-load data quality checks and return a DQ report."""
    report = {
        "table":         table_name,
        "row_count":     len(df),
        "null_summary":  df.isnull().sum().to_dict(),
        "duplicate_pk":  None,
        "dq_pass":       True,
        "issues":        []
    }

    # Check for entirely null columns
    all_null_cols = [c for c in df.columns if df[c].isnull().all()]
    if all_null_cols:
        report["issues"].append(f"Entirely null columns: {all_null_cols}")

    # Check for negative values in numeric columns that shouldn't be
    non_neg_cols = [c for c in df.columns if any(
        kw in c for kw in ["beds", "time_min", "pct", "hrs"]
    )]
    for col in non_neg_cols:
        if col in df.columns and pd.api.types.is_numeric_dtype(df[col]):
            neg_count = (df[col] < 0).sum()
            if neg_count > 0:
                report["issues"].append(f"{col}: {neg_count} negative values")

    # Check occupancy_pct range
    if "occupancy_pct" in df.columns:
        invalid = ((df["occupancy_pct"] < 0) | (df["occupancy_pct"] > 100)).sum()
        if invalid > 0:
            report["issues"].append(f"occupancy_pct: {invalid} values outside [0,100]")

    if report["issues"]:
        report["dq_pass"] = False
        log.warning(f"DQ Issues in {table_name}: {report['issues']}")
    else:
        log.info(f"✅ DQ passed for {table_name} ({len(df):,} rows)")

    return report


# ─────────────────────────────────────────────────────
# CORE LOAD FUNCTION
# ─────────────────────────────────────────────────────
def load_to_snowflake(conn, df: pd.DataFrame, table: str, chunk_size: int = 5000):
    """Write pandas DataFrame to Snowflake in chunks using write_pandas."""
    from snowflake.connector.pandas_tools import write_pandas

    # Snowflake column names must be UPPERCASE
    df.columns = [c.upper() for c in df.columns]

    # Convert NaN to None for proper NULL handling
    df = df.where(pd.notnull(df), other=None)

    schema, tbl = table.split(".")
    total_rows = 0
    chunks = [df[i:i+chunk_size] for i in range(0, len(df), chunk_size)]

    log.info(f"Loading {len(df):,} rows into {table} in {len(chunks)} chunks...")

    for i, chunk in enumerate(chunks, 1):
        success, num_chunks, num_rows, output = write_pandas(
            conn=conn,
            df=chunk,
            table_name=tbl,
            schema=schema,
            database=SNOWFLAKE_CONFIG["database"],
            overwrite=(i == 1),     # truncate + insert on first chunk
            auto_create_table=False
        )
        total_rows += num_rows
        log.info(f"  Chunk {i}/{len(chunks)}: {num_rows} rows loaded")

    log.info(f"✅ {table}: {total_rows:,} total rows loaded")
    return total_rows


# ─────────────────────────────────────────────────────
# INCREMENTAL LOAD HELPER (for production use)
# ─────────────────────────────────────────────────────
def get_max_date_from_snowflake(conn, table: str, date_col: str) -> str:
    """Get the latest date already in Snowflake (for incremental loads)."""
    cursor = conn.cursor()
    try:
        cursor.execute(f"SELECT MAX({date_col}) FROM {table}")
        result = cursor.fetchone()[0]
        return str(result) if result else "1900-01-01"
    except Exception:
        return "1900-01-01"
    finally:
        cursor.close()


# ─────────────────────────────────────────────────────
# PIPELINE ORCHESTRATOR
# ─────────────────────────────────────────────────────
def run_pipeline(incremental: bool = False):
    """Main ETL pipeline orchestrator."""
    start_time = datetime.now()
    log.info("=" * 60)
    log.info("SYNAPSE ETL PIPELINE STARTED")
    log.info(f"Mode: {'INCREMENTAL' if incremental else 'FULL LOAD'}")
    log.info("=" * 60)

    all_dq_reports = []
    load_stats = []

    try:
        conn = get_snowflake_connection()
    except Exception:
        log.error("Could not connect to Snowflake. Running DQ checks only (demo mode).")
        conn = None

    for cfg in LOAD_CONFIG:
        csv_path = os.path.join(DATA_DIR, cfg["csv"])
        table    = cfg["table"]
        log.info(f"\n── Processing {cfg['csv']} → {table}")

        # ── Read CSV
        try:
            df = pd.read_csv(
                csv_path,
                parse_dates=cfg["date_cols"] if cfg["date_cols"] else False,
                low_memory=False
            )
            log.info(f"   Read {len(df):,} rows from {cfg['csv']}")
        except FileNotFoundError:
            log.error(f"   File not found: {csv_path} — skipping")
            continue

        # ── DQ Checks
        dq = run_dq_checks(df, table)
        all_dq_reports.append(dq)

        if not dq["dq_pass"]:
            log.warning(f"   DQ failures detected — loading with caution")

        # ── Snowflake Load
        if conn:
            if incremental and cfg.get("incremental_col"):
                max_date = get_max_date_from_snowflake(
                    conn, table, cfg["incremental_col"].upper()
                )
                df = df[df[cfg["incremental_col"]] > max_date]
                log.info(f"   Incremental: {len(df):,} new rows after {max_date}")

            try:
                rows = load_to_snowflake(conn, df, table, cfg["chunk_size"])
                load_stats.append({"table": table, "rows": rows, "status": "SUCCESS"})
            except Exception as e:
                log.error(f"   Load failed for {table}: {e}")
                load_stats.append({"table": table, "rows": 0, "status": f"FAILED: {e}"})
        else:
            log.info(f"   [Demo mode] Would load {len(df):,} rows to {table}")
            load_stats.append({"table": table, "rows": len(df), "status": "DEMO"})

    # ── Pipeline Summary
    elapsed = (datetime.now() - start_time).total_seconds()
    log.info("\n" + "=" * 60)
    log.info("PIPELINE SUMMARY")
    log.info("=" * 60)
    for stat in load_stats:
        log.info(f"  {stat['table']:<40} {stat['rows']:>8,} rows   [{stat['status']}]")
    log.info(f"\nTotal elapsed: {elapsed:.1f}s")

    if conn:
        conn.close()
        log.info("Snowflake connection closed.")

    # Save DQ report
    dq_df = pd.DataFrame([
        {"table": r["table"], "rows": r["row_count"], "dq_pass": r["dq_pass"],
         "issues": "; ".join(r["issues"]) if r["issues"] else "None"}
        for r in all_dq_reports
    ])
    dq_df.to_csv("logs/dq_report.csv", index=False)
    log.info("DQ report saved to logs/dq_report.csv")
    return load_stats


# ─────────────────────────────────────────────────────
# ENTRY POINT
# ─────────────────────────────────────────────────────
if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Synapse ETL Pipeline")
    parser.add_argument("--incremental", action="store_true",
                        help="Run in incremental mode (only new records)")
    args = parser.parse_args()
    run_pipeline(incremental=args.incremental)

# ─────────────────────────────────────────────────────
# USAGE EXAMPLES:
#
# Full load (first run):
#   python 04_etl_pipeline.py
#
# Incremental load (daily cron):
#   python 04_etl_pipeline.py --incremental
#
# Schedule with Windows Task Scheduler or Linux cron:
#   0 6 * * * /usr/bin/python /path/to/04_etl_pipeline.py --incremental
# ─────────────────────────────────────────────────────
