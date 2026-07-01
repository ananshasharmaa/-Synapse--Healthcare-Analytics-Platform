"""
SYNAPSE HEALTHCARE ANALYTICS PLATFORM
STEP 1: Synthetic Data Generator
Generates realistic hospital occupancy, ambulance dispatch, and patient flow data.
Run: python 01_generate_synthetic_data.py
Output: /data/*.csv
"""

import pandas as pd
import numpy as np
from faker import Faker
from datetime import datetime, timedelta
import random
import os

fake = Faker()
np.random.seed(42)
random.seed(42)
os.makedirs("data", exist_ok=True)

# ─────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────
NUM_HOSPITALS      = 8
NUM_DEPARTMENTS    = 6
NUM_AMBULANCES     = 40
NUM_PATIENTS       = 5000
START_DATE         = datetime(2024, 1, 1)
END_DATE           = datetime(2024, 12, 31)

DEPARTMENTS = ["Emergency", "ICU", "General Ward", "Pediatrics", "Surgery", "Cardiology"]
HOSPITAL_NAMES = [
    "Apollo Hospitals Bangalore", "Fortis Hospital Bannerghatta",
    "Manipal Hospital HAL Airport", "Narayana Health City",
    "Columbia Asia Referral Hospital", "Sakra World Hospital",
    "Aster CMI Hospital", "BGS Gleneagles Global Hospital"
]

# Bed capacity per department per hospital
BED_CAPACITY = {
    "Emergency": 30, "ICU": 20, "General Ward": 80,
    "Pediatrics": 40, "Surgery": 25, "Cardiology": 35
}

# Peak hour multipliers for occupancy realism
def occupancy_multiplier(hour):
    if 8 <= hour <= 12:   return 1.3    # morning rush
    elif 13 <= hour <= 18: return 1.1   # afternoon
    elif 19 <= hour <= 23: return 0.85  # evening decline
    else:                  return 0.65  # night low

# ─────────────────────────────────────────────
# 1. DIM_HOSPITAL
# ─────────────────────────────────────────────
print("Generating dim_hospital...")
hospitals = []
for i, name in enumerate(HOSPITAL_NAMES, 1):
    hospitals.append({
        "hospital_id":   i,
        "hospital_name": name,
        "city":          "Bangalore",
        "state":         "Karnataka",
        "tier":          random.choice(["Tier-1", "Tier-2"]),
        "total_beds":    random.randint(200, 600),
        "icu_beds":      random.randint(20, 60),
        "ventilators":   random.randint(10, 30),
        "lat":           12.97 + random.uniform(-0.1, 0.1),
        "lon":           77.59 + random.uniform(-0.1, 0.1)
    })
df_hospitals = pd.DataFrame(hospitals)
df_hospitals.to_csv("data/dim_hospital.csv", index=False)
print(f"  ✓ {len(df_hospitals)} hospitals")

# ─────────────────────────────────────────────
# 2. DIM_DEPARTMENT
# ─────────────────────────────────────────────
print("Generating dim_department...")
departments = []
dept_id = 1
for h_id in range(1, NUM_HOSPITALS + 1):
    for dept in DEPARTMENTS:
        departments.append({
            "department_id":   dept_id,
            "hospital_id":     h_id,
            "department_name": dept,
            "total_beds":      BED_CAPACITY[dept],
            "floor_number":    random.randint(1, 8)
        })
        dept_id += 1
df_departments = pd.DataFrame(departments)
df_departments.to_csv("data/dim_department.csv", index=False)
print(f"  ✓ {len(df_departments)} department records")

# ─────────────────────────────────────────────
# 3. DIM_AMBULANCE
# ─────────────────────────────────────────────
print("Generating dim_ambulance...")
vehicle_types = ["ALS", "BLS", "Neonatal", "Mobile ICU"]
ambulances = []
for i in range(1, NUM_AMBULANCES + 1):
    ambulances.append({
        "ambulance_id":       i,
        "registration_no":    f"KA-{random.randint(10,99)}-{fake.bothify('??-####').upper()}",
        "hospital_id":        random.randint(1, NUM_HOSPITALS),
        "vehicle_type":       random.choice(vehicle_types),
        "manufacture_year":   random.randint(2018, 2023),
        "status":             random.choice(["Active", "Active", "Active", "Maintenance"])
    })
df_ambulances = pd.DataFrame(ambulances)
df_ambulances.to_csv("data/dim_ambulance.csv", index=False)
print(f"  ✓ {len(df_ambulances)} ambulances")

# ─────────────────────────────────────────────
# 4. DIM_DATE
# ─────────────────────────────────────────────
print("Generating dim_date...")
date_range = pd.date_range(START_DATE, END_DATE, freq="D")
date_dim = pd.DataFrame({
    "date_id":      date_range.strftime("%Y%m%d").astype(int),
    "full_date":    date_range,
    "day_of_week":  date_range.day_name(),
    "day_num":      date_range.day,
    "week_num":     date_range.isocalendar().week.values,
    "month_num":    date_range.month,
    "month_name":   date_range.month_name(),
    "quarter":      date_range.quarter,
    "year":         date_range.year,
    "is_weekend":   date_range.dayofweek >= 5,
    "is_holiday":   False   # can update with India public holidays
})
# Mark Indian public holidays
indian_holidays = ["2024-01-26", "2024-08-15", "2024-10-02", "2024-11-01"]
date_dim.loc[date_dim["full_date"].astype(str).isin(indian_holidays), "is_holiday"] = True
date_dim.to_csv("data/dim_date.csv", index=False)
print(f"  ✓ {len(date_dim)} date records")

# ─────────────────────────────────────────────
# 5. FACT_BED_OCCUPANCY (hourly snapshots)
# ─────────────────────────────────────────────
print("Generating fact_bed_occupancy (this takes ~30 seconds)...")
occupancy_records = []
record_id = 1

for dept_row in df_departments.itertuples():
    # Generate daily hourly snapshots for the full year
    current_date = START_DATE
    while current_date <= END_DATE:
        # Sample 4 hours per day to keep volume manageable
        for hour in [6, 12, 18, 23]:
            capacity    = dept_row.total_beds
            mult        = occupancy_multiplier(hour)
            # Weekend/night effect
            if current_date.weekday() >= 5:
                mult *= 0.85
            base_occ    = random.uniform(0.5, 0.95) * mult
            occupied    = int(min(capacity, max(0, round(capacity * base_occ))))
            available   = capacity - occupied
            occupancy_pct = round((occupied / capacity) * 100, 2)

            occupancy_records.append({
                "occupancy_id":    record_id,
                "department_id":   dept_row.department_id,
                "hospital_id":     dept_row.hospital_id,
                "date_id":         int(current_date.strftime("%Y%m%d")),
                "snapshot_hour":   hour,
                "snapshot_ts":     current_date.replace(hour=hour),
                "total_beds":      capacity,
                "occupied_beds":   occupied,
                "available_beds":  available,
                "occupancy_pct":   occupancy_pct,
                "on_hold_beds":    random.randint(0, 3),
                "critical_flag":   1 if occupancy_pct >= 90 else 0
            })
            record_id += 1
        current_date += timedelta(days=1)

df_occupancy = pd.DataFrame(occupancy_records)
df_occupancy.to_csv("data/fact_bed_occupancy.csv", index=False)
print(f"  ✓ {len(df_occupancy):,} occupancy snapshot records")

# ─────────────────────────────────────────────
# 6. FACT_AMBULANCE_DISPATCH
# ─────────────────────────────────────────────
print("Generating fact_ambulance_dispatch...")
dispatch_records = []
dispatch_id = 1
call_types    = ["Emergency", "Transfer", "Scheduled", "Trauma"]
call_outcomes = ["Admitted", "Treated & Released", "DOA", "Refused Transport"]

date_list = pd.date_range(START_DATE, END_DATE, freq="D").tolist()
for dt in date_list:
    # 5–20 dispatches per day across fleet
    n_dispatches = random.randint(5, 20)
    for _ in range(n_dispatches):
        amb        = random.choice(df_ambulances.to_dict("records"))
        call_time  = dt + timedelta(hours=random.randint(0,23), minutes=random.randint(0,59))
        # Response time: 8–25 min for emergency, 15–40 for others
        call_type  = random.choice(call_types)
        resp_min   = random.randint(8, 20) if call_type == "Emergency" else random.randint(12, 35)
        on_scene_min = random.randint(10, 30)
        transport_min = random.randint(5, 25)
        total_min  = resp_min + on_scene_min + transport_min

        dispatch_records.append({
            "dispatch_id":         dispatch_id,
            "ambulance_id":        amb["ambulance_id"],
            "hospital_id":         amb["hospital_id"],
            "date_id":             int(dt.strftime("%Y%m%d")),
            "call_timestamp":      call_time,
            "dispatch_timestamp":  call_time + timedelta(minutes=2),
            "on_scene_timestamp":  call_time + timedelta(minutes=resp_min),
            "hospital_arrival_ts": call_time + timedelta(minutes=total_min),
            "call_type":           call_type,
            "call_outcome":        random.choice(call_outcomes),
            "response_time_min":   resp_min,
            "on_scene_time_min":   on_scene_min,
            "transport_time_min":  transport_min,
            "total_time_min":      total_min,
            "sla_breached":        1 if (call_type == "Emergency" and resp_min > 15) else 0,
            "crew_count":          random.randint(2, 3)
        })
        dispatch_id += 1

df_dispatch = pd.DataFrame(dispatch_records)
df_dispatch.to_csv("data/fact_ambulance_dispatch.csv", index=False)
print(f"  ✓ {len(df_dispatch):,} dispatch records")

# ─────────────────────────────────────────────
# 7. FACT_PATIENT_FLOW
# ─────────────────────────────────────────────
print("Generating fact_patient_flow...")
flow_records = []
conditions   = ["Cardiac Arrest", "Stroke", "Fracture", "Fever", "Appendicitis",
                "Pneumonia", "Diabetes Crisis", "Road Accident", "Delivery", "Burns"]
entry_modes  = ["Walk-in", "Ambulance", "Referral", "Transfer"]

for patient_id in range(1, NUM_PATIENTS + 1):
    admit_date   = fake.date_between(START_DATE, END_DATE)
    admit_dt     = datetime(admit_date.year, admit_date.month, admit_date.day,
                            random.randint(0, 23), random.randint(0, 59))
    dept_row     = random.choice(df_departments.to_dict("records"))
    los_hours    = random.randint(2, 240)   # 2 hrs to 10 days
    discharge_dt = admit_dt + timedelta(hours=los_hours)

    flow_records.append({
        "flow_id":             patient_id,
        "patient_id":          f"PAT-{patient_id:06d}",
        "hospital_id":         dept_row["hospital_id"],
        "department_id":       dept_row["department_id"],
        "admit_date_id":       int(admit_dt.strftime("%Y%m%d")),
        "admit_timestamp":     admit_dt,
        "discharge_timestamp": discharge_dt if discharge_dt <= datetime(2024, 12, 31, 23, 59) else None,
        "length_of_stay_hrs":  los_hours,
        "condition":           random.choice(conditions),
        "entry_mode":          random.choice(entry_modes),
        "age_group":           random.choice(["0-17", "18-34", "35-54", "55-64", "65+"]),
        "gender":              random.choice(["M", "F"]),
        "er_to_ward_hrs":      round(random.uniform(0.5, 6), 2),
        "readmission_flag":    1 if random.random() < 0.08 else 0,
        "discharge_type":      random.choice(["Recovered", "Referred", "LAMA", "Expired"])
    })

df_flow = pd.DataFrame(flow_records)
df_flow.to_csv("data/fact_patient_flow.csv", index=False)
print(f"  ✓ {len(df_flow):,} patient flow records")

# ─────────────────────────────────────────────
# SUMMARY
# ─────────────────────────────────────────────
print("\n" + "="*50)
print("ALL DATA GENERATED SUCCESSFULLY")
print("="*50)
for fname in os.listdir("data"):
    size = os.path.getsize(f"data/{fname}") // 1024
    print(f"  data/{fname:<35} {size:>5} KB")
