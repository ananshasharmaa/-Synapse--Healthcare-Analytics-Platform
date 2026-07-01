"""
SYNAPSE HEALTHCARE ANALYTICS PLATFORM
STEP 5: KPI Aggregation + LLM Narrative Generation

This module:
  1. Reads fact tables and computes daily/weekly KPIs using pandas
  2. Calls OpenAI/Anthropic API to generate natural-language operational summaries
  3. Writes both KPI tables and narratives back to Snowflake SUMMARY schema

Install: pip install openai anthropic pandas python-dotenv
Run:     python 05_kpi_and_llm_narrative.py --date 2024-03-15
         python 05_kpi_and_llm_narrative.py --weekly  (last 7 days)
"""

import os
import json
import pandas as pd
import numpy as np
import argparse
import logging
from datetime import datetime, timedelta, date
from dotenv import load_dotenv

load_dotenv()
os.makedirs("logs", exist_ok=True)
os.makedirs("output", exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s │ %(message)s",
    handlers=[logging.StreamHandler(), logging.FileHandler("logs/kpi_narrative.log")]
)
log = logging.getLogger("synapse_kpi")

# ─────────────────────────────────────────────────────
# LLM CONFIG  (set one of these in .env)
# OPENAI_API_KEY=sk-...
# ANTHROPIC_API_KEY=sk-ant-...
# ─────────────────────────────────────────────────────
LLM_PROVIDER  = os.getenv("LLM_PROVIDER", "openai")   # "openai" or "anthropic"
OPENAI_KEY    = os.getenv("OPENAI_API_KEY", "")
ANTHROPIC_KEY = os.getenv("ANTHROPIC_API_KEY", "")


# ─────────────────────────────────────────────────────
# 1. KPI COMPUTATION
# ─────────────────────────────────────────────────────

def compute_occupancy_kpis(occ_df: pd.DataFrame, target_date: str) -> pd.DataFrame:
    """
    Compute bed occupancy KPIs per hospital for a given date.
    Returns a summary DataFrame.
    """
    day_df = occ_df[occ_df["date_id"] == int(target_date.replace("-", ""))].copy()
    if day_df.empty:
        log.warning(f"No occupancy data for {target_date}")
        return pd.DataFrame()

    kpis = day_df.groupby("hospital_id").agg(
        avg_occupancy_pct   = ("occupancy_pct", "mean"),
        peak_occupancy_pct  = ("occupancy_pct", "max"),
        min_occupancy_pct   = ("occupancy_pct", "min"),
        critical_snapshots  = ("critical_flag", "sum"),
        total_snapshots     = ("critical_flag", "count"),
        avg_available_beds  = ("available_beds", "mean")
    ).reset_index()

    kpis["critical_dept_count"] = kpis["critical_snapshots"] // 4  # ~4 snapshots per dept per day
    kpis["avg_occupancy_pct"]   = kpis["avg_occupancy_pct"].round(2)
    kpis["peak_occupancy_pct"]  = kpis["peak_occupancy_pct"].round(2)

    # 7-day rolling trend
    week_ago = (datetime.strptime(target_date, "%Y-%m-%d") - timedelta(days=7)).strftime("%Y%m%d")
    week_df  = occ_df[occ_df["date_id"].astype(str) >= week_ago]
    rolling  = week_df.groupby("hospital_id").agg(
        week_avg_occ = ("occupancy_pct", "mean")
    ).reset_index()
    kpis = kpis.merge(rolling, on="hospital_id", how="left")
    kpis["occ_trend"] = (kpis["avg_occupancy_pct"] - kpis["week_avg_occ"]).round(2)

    return kpis


def compute_ambulance_kpis(disp_df: pd.DataFrame, target_date: str) -> pd.DataFrame:
    """Compute ambulance dispatch KPIs per hospital for a given date."""
    day_df = disp_df[disp_df["date_id"] == int(target_date.replace("-", ""))].copy()
    if day_df.empty:
        return pd.DataFrame()

    kpis = day_df.groupby("hospital_id").agg(
        total_dispatches        = ("dispatch_id", "count"),
        avg_response_min        = ("response_time_min", "mean"),
        p90_response_min        = ("response_time_min", lambda x: np.percentile(x, 90)),
        sla_breach_count        = ("sla_breached", "sum"),
        emergency_count         = ("call_type", lambda x: (x == "Emergency").sum()),
        avg_total_time_min      = ("total_time_min", "mean")
    ).reset_index()

    kpis["sla_breach_pct"]  = (kpis["sla_breach_count"] / kpis["total_dispatches"] * 100).round(2)
    kpis["avg_response_min"]= kpis["avg_response_min"].round(2)
    kpis["p90_response_min"]= kpis["p90_response_min"].round(2)

    return kpis


def compute_patient_kpis(flow_df: pd.DataFrame, target_date: str) -> pd.DataFrame:
    """Compute patient flow KPIs per hospital for a given date."""
    date_id = int(target_date.replace("-", ""))
    admissions = flow_df[flow_df["admit_date_id"] == date_id].copy()
    if admissions.empty:
        return pd.DataFrame()

    kpis = admissions.groupby("hospital_id").agg(
        total_admissions        = ("patient_id", "count"),
        avg_los_hrs             = ("length_of_stay_hrs", "mean"),
        readmission_count       = ("readmission_flag", "sum"),
        ambulance_arrivals      = ("entry_mode", lambda x: (x == "Ambulance").sum()),
        avg_er_to_ward_hrs      = ("er_to_ward_hrs", "mean")
    ).reset_index()

    kpis["readmission_rate"]    = (kpis["readmission_count"] / kpis["total_admissions"] * 100).round(2)
    kpis["avg_los_hrs"]         = kpis["avg_los_hrs"].round(2)
    kpis["avg_er_to_ward_hrs"]  = kpis["avg_er_to_ward_hrs"].round(2)

    return kpis


def merge_all_kpis(occ_kpi, amb_kpi, pat_kpi, hospitals_df) -> pd.DataFrame:
    """Merge all KPI DataFrames into one summary per hospital."""
    base = hospitals_df[["hospital_id", "hospital_name"]].copy()
    merged = base.merge(occ_kpi, on="hospital_id", how="left") \
                 .merge(amb_kpi, on="hospital_id", how="left") \
                 .merge(pat_kpi, on="hospital_id", how="left")
    merged = merged.fillna(0)
    return merged


# ─────────────────────────────────────────────────────
# 2. LLM NARRATIVE GENERATION
# ─────────────────────────────────────────────────────

def build_prompt(kpi_row: dict, report_date: str, narrative_type: str = "daily_ops") -> str:
    """Build the prompt to send to the LLM."""
    hospital = kpi_row.get("hospital_name", "Unknown Hospital")

    if narrative_type == "daily_ops":
        return f"""You are a healthcare operations analyst generating a daily briefing.
Report Date: {report_date}
Hospital: {hospital}

KPI Data:
- Bed Occupancy: {kpi_row.get('avg_occupancy_pct', 'N/A')}% average, {kpi_row.get('peak_occupancy_pct', 'N/A')}% peak
- Critical departments (>90% occupancy): {int(kpi_row.get('critical_dept_count', 0))}
- 7-day occupancy trend: {kpi_row.get('occ_trend', 0):+.1f}% vs last week
- Ambulance dispatches: {int(kpi_row.get('total_dispatches', 0))} total
- Average response time: {kpi_row.get('avg_response_min', 'N/A')} min
- SLA breaches: {int(kpi_row.get('sla_breach_count', 0))} ({kpi_row.get('sla_breach_pct', 0):.1f}%)
- Patient admissions: {int(kpi_row.get('total_admissions', 0))}
- Average length of stay: {kpi_row.get('avg_los_hrs', 'N/A')} hrs
- Readmission rate: {kpi_row.get('readmission_rate', 'N/A')}%
- Avg ER → ward transfer: {kpi_row.get('avg_er_to_ward_hrs', 'N/A')} hrs

Write a concise 3-4 sentence operational summary for the hospital operations manager.
Highlight the most critical issues and call out any metric that needs immediate attention.
Use professional but plain language. Do not include bullet points."""

    elif narrative_type == "alert":
        return f"""You are a healthcare operations analyst generating an urgent alert.
Hospital: {hospital} | Date: {report_date}
Bed occupancy is at {kpi_row.get('avg_occupancy_pct', 'N/A')}% with {kpi_row.get('critical_dept_count', 0)} departments critically full.
SLA breach rate: {kpi_row.get('sla_breach_pct', 0):.1f}%.
Write a 2-sentence urgent alert for the hospital administrator.
Be direct and action-oriented."""


def call_openai(prompt: str) -> dict:
    """Call OpenAI API and return response + token usage."""
    import openai
    openai.api_key = OPENAI_KEY
    client = openai.OpenAI(api_key=OPENAI_KEY)
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": "You are a concise healthcare operations analyst."},
            {"role": "user",   "content": prompt}
        ],
        temperature=0.4,
        max_tokens=300
    )
    return {
        "text":              response.choices[0].message.content.strip(),
        "model":             response.model,
        "prompt_tokens":     response.usage.prompt_tokens,
        "completion_tokens": response.usage.completion_tokens
    }


def call_anthropic(prompt: str) -> dict:
    """Call Anthropic Claude API and return response + token usage."""
    import anthropic
    client = anthropic.Anthropic(api_key=ANTHROPIC_KEY)
    response = client.messages.create(
        model="claude-3-haiku-20240307",
        max_tokens=300,
        messages=[{"role": "user", "content": prompt}]
    )
    return {
        "text":              response.content[0].text.strip(),
        "model":             response.model,
        "prompt_tokens":     response.usage.input_tokens,
        "completion_tokens": response.usage.output_tokens
    }


def generate_narrative(kpi_row: dict, report_date: str,
                       narrative_type: str = "daily_ops") -> dict:
    """Generate an LLM narrative for one hospital KPI row."""
    prompt = build_prompt(kpi_row, report_date, narrative_type)

    # Demo mode (no API key): return a placeholder
    if not OPENAI_KEY and not ANTHROPIC_KEY:
        hospital = kpi_row.get("hospital_name", "Hospital")
        occ      = kpi_row.get("avg_occupancy_pct", 0)
        breaches = int(kpi_row.get("sla_breach_count", 0))
        trend    = kpi_row.get("occ_trend", 0)
        direction = "up" if trend > 0 else "down"
        return {
            "text": (
                f"{hospital} operated at {occ:.1f}% average bed occupancy on {report_date}, "
                f"trending {direction} {abs(trend):.1f}% versus the prior 7-day average. "
                f"Ambulance SLA breaches totalled {breaches}, requiring review of dispatch protocols. "
                f"Patient admissions and flow metrics remain within expected operational bands."
            ),
            "model": "demo-mode",
            "prompt_tokens": 0,
            "completion_tokens": 0
        }

    try:
        if LLM_PROVIDER == "anthropic" and ANTHROPIC_KEY:
            return call_anthropic(prompt)
        elif OPENAI_KEY:
            return call_openai(prompt)
    except Exception as e:
        log.error(f"LLM call failed: {e}")
        return {"text": f"Narrative generation failed: {e}", "model": "error",
                "prompt_tokens": 0, "completion_tokens": 0}


# ─────────────────────────────────────────────────────
# 3. MAIN PIPELINE
# ─────────────────────────────────────────────────────

def run(report_date: str, weekly: bool = False, save_to_snowflake: bool = False):
    log.info("=" * 60)
    log.info(f"SYNAPSE KPI + LLM PIPELINE | Date: {report_date}")
    log.info("=" * 60)

    # ── Load data from CSVs (replace with Snowflake reads in production)
    log.info("Loading data...")
    hospitals   = pd.read_csv("data/dim_hospital.csv")
    occ_df      = pd.read_csv("data/fact_bed_occupancy.csv")
    disp_df     = pd.read_csv("data/fact_ambulance_dispatch.csv")
    flow_df     = pd.read_csv("data/fact_patient_flow.csv")
    log.info(f"  Occupancy records: {len(occ_df):,}")
    log.info(f"  Dispatch records:  {len(disp_df):,}")
    log.info(f"  Patient records:   {len(flow_df):,}")

    # ── KPI Computation
    log.info(f"Computing KPIs for {report_date}...")
    occ_kpi = compute_occupancy_kpis(occ_df, report_date)
    amb_kpi = compute_ambulance_kpis(disp_df, report_date)
    pat_kpi = compute_patient_kpis(flow_df, report_date)

    if occ_kpi.empty:
        log.warning("No data for this date. Try a date between 2024-01-01 and 2024-12-31.")
        return

    kpi_summary = merge_all_kpis(occ_kpi, amb_kpi, pat_kpi, hospitals)
    log.info(f"  KPIs computed for {len(kpi_summary)} hospitals")

    # ── Save KPI summary
    kpi_summary["report_date"] = report_date
    kpi_output_path = f"output/kpi_summary_{report_date.replace('-','')}.csv"
    kpi_summary.to_csv(kpi_output_path, index=False)
    log.info(f"  KPI summary saved: {kpi_output_path}")

    # ── Narrative Generation
    log.info("Generating LLM narratives...")
    narratives = []
    for _, row in kpi_summary.iterrows():
        kpi_dict = row.to_dict()

        # Determine narrative type
        n_type = "alert" if row.get("avg_occupancy_pct", 0) >= 88 \
                         or row.get("sla_breach_pct", 0) >= 20 else "daily_ops"

        log.info(f"  Generating [{n_type}] narrative for {row['hospital_name']}...")
        result = generate_narrative(kpi_dict, report_date, n_type)

        narratives.append({
            "report_date":        report_date,
            "hospital_id":        int(row["hospital_id"]),
            "hospital_name":      row["hospital_name"],
            "narrative_type":     n_type,
            "narrative_text":     result["text"],
            "model_used":         result["model"],
            "prompt_tokens":      result["prompt_tokens"],
            "completion_tokens":  result["completion_tokens"]
        })
        log.info(f"    → {result['text'][:100]}...")

    # ── Save narratives
    narratives_df = pd.DataFrame(narratives)
    narr_path = f"output/narratives_{report_date.replace('-','')}.csv"
    narratives_df.to_csv(narr_path, index=False)
    log.info(f"  Narratives saved: {narr_path}")

    # ── Print sample
    log.info("\n── SAMPLE NARRATIVE OUTPUT ─────────────────────────────")
    for _, n in narratives_df.head(2).iterrows():
        log.info(f"\n[{n['hospital_name']}] [{n['narrative_type'].upper()}]")
        log.info(n["narrative_text"])
    log.info("─" * 60)

    if save_to_snowflake:
        log.info("Saving to Snowflake SUMMARY schema... (requires connection)")
        # conn = get_snowflake_connection()
        # write_pandas(conn, kpi_summary, "DAILY_KPI_SUMMARY", schema="SUMMARY")
        # write_pandas(conn, narratives_df, "LLM_NARRATIVES", schema="SUMMARY")
        log.info("(Snowflake write skipped in demo mode)")

    log.info("\nPipeline complete.")
    return kpi_summary, narratives_df


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Synapse KPI + LLM Narrative Generator")
    parser.add_argument("--date",   type=str, default="2024-06-15", help="Report date YYYY-MM-DD")
    parser.add_argument("--weekly", action="store_true", help="Generate for last 7 days")
    parser.add_argument("--snowflake", action="store_true", help="Write results to Snowflake")
    args = parser.parse_args()

    if args.weekly:
        report_dt = datetime.strptime(args.date, "%Y-%m-%d")
        for i in range(7):
            d = (report_dt - timedelta(days=i)).strftime("%Y-%m-%d")
            run(d, weekly=True, save_to_snowflake=args.snowflake)
    else:
        run(args.date, save_to_snowflake=args.snowflake)
