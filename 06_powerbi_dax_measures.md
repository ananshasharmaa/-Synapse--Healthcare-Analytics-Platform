# SYNAPSE HEALTHCARE ANALYTICS PLATFORM
# STEP 6: Power BI — DAX Measures Reference
# Paste these into Power BI Desktop → Model view → New Measure

---

## ════════════════════════════════════════════════
## PAGE 1: HOSPITAL CAPACITY DASHBOARD
## ════════════════════════════════════════════════

### Core Occupancy Measures

```dax
-- Current occupancy percentage (respects all slicers)
Avg Occupancy % =
AVERAGE(FACT_BED_OCCUPANCY[OCCUPANCY_PCT])

-- Peak occupancy in selected period
Peak Occupancy % =
MAXX(
    FACT_BED_OCCUPANCY,
    FACT_BED_OCCUPANCY[OCCUPANCY_PCT]
)

-- Occupied beds vs total (for gauge visuals)
Total Occupied Beds =
SUM(FACT_BED_OCCUPANCY[OCCUPIED_BEDS])

Total Available Beds =
SUM(FACT_BED_OCCUPANCY[AVAILABLE_BEDS])

Total Bed Capacity =
SUM(FACT_BED_OCCUPANCY[TOTAL_BEDS])

-- Count of snapshots where occupancy exceeded 90%
Critical Snapshots =
COUNTROWS(
    FILTER(
        FACT_BED_OCCUPANCY,
        FACT_BED_OCCUPANCY[OCCUPANCY_PCT] >= 90
    )
)

-- % of time hospital is in critical state
Critical % of Time =
DIVIDE(
    [Critical Snapshots],
    COUNTROWS(FACT_BED_OCCUPANCY),
    0
) * 100
```

### Trend & Comparison Measures

```dax
-- Occupancy same period last month (for comparison cards)
Occupancy % Last Month =
CALCULATE(
    [Avg Occupancy %],
    DATEADD(DIM_DATE[FULL_DATE], -1, MONTH)
)

-- Month-over-month change
Occupancy MoM Change =
[Avg Occupancy %] - [Occupancy % Last Month]

-- 7-day rolling average (for trend line charts)
Occupancy 7D Rolling Avg =
AVERAGEX(
    DATESINPERIOD(
        DIM_DATE[FULL_DATE],
        LASTDATE(DIM_DATE[FULL_DATE]),
        -7,
        DAY
    ),
    [Avg Occupancy %]
)

-- YTD average occupancy
Occupancy YTD =
CALCULATE(
    [Avg Occupancy %],
    DATESYTD(DIM_DATE[FULL_DATE])
)

-- Occupancy vs YTD benchmark
Vs YTD Benchmark =
[Avg Occupancy %] - [Occupancy YTD]
```

### Bed Utilization KPIs

```dax
-- Bed turnover rate: admissions per available bed
Bed Turnover Rate =
DIVIDE(
    [Total Admissions],
    AVERAGE(FACT_BED_OCCUPANCY[TOTAL_BEDS]),
    0
)

-- Beds on hold as % of total
On Hold Bed % =
DIVIDE(
    SUM(FACT_BED_OCCUPANCY[ON_HOLD_BEDS]),
    SUM(FACT_BED_OCCUPANCY[TOTAL_BEDS]),
    0
) * 100

-- Color coding for KPI cards (Red/Amber/Green)
Occupancy Status =
SWITCH(
    TRUE(),
    [Avg Occupancy %] >= 90, "🔴 Critical",
    [Avg Occupancy %] >= 75, "🟡 High",
    [Avg Occupancy %] >= 50, "🟢 Normal",
    "🔵 Low"
)
```

---

## ════════════════════════════════════════════════
## PAGE 2: AMBULANCE OPERATIONS
## ════════════════════════════════════════════════

### Dispatch Volume Measures

```dax
-- Total dispatches in period
Total Dispatches =
COUNTROWS(FACT_AMBULANCE_DISPATCH)

-- Emergency dispatches only
Emergency Dispatches =
CALCULATE(
    [Total Dispatches],
    FACT_AMBULANCE_DISPATCH[CALL_TYPE] = "Emergency"
)

-- Emergency % of all dispatches
Emergency Dispatch % =
DIVIDE([Emergency Dispatches], [Total Dispatches], 0) * 100

-- Dispatches per ambulance (fleet utilization)
Dispatches Per Ambulance =
DIVIDE(
    [Total Dispatches],
    DISTINCTCOUNT(FACT_AMBULANCE_DISPATCH[AMBULANCE_SK]),
    0
)
```

### Response Time Measures

```dax
-- Average response time (all call types)
Avg Response Time (min) =
AVERAGE(FACT_AMBULANCE_DISPATCH[RESPONSE_TIME_MIN])

-- Average emergency-only response time
Avg Emergency Response (min) =
CALCULATE(
    AVERAGE(FACT_AMBULANCE_DISPATCH[RESPONSE_TIME_MIN]),
    FACT_AMBULANCE_DISPATCH[CALL_TYPE] = "Emergency"
)

-- 90th percentile response time
-- (Power BI doesn't have PERCENTILE natively, use PERCENTILEX.INC)
P90 Response Time =
PERCENTILEX.INC(
    FACT_AMBULANCE_DISPATCH,
    FACT_AMBULANCE_DISPATCH[RESPONSE_TIME_MIN],
    0.90
)

-- Average total trip time
Avg Total Trip Time (min) =
AVERAGE(FACT_AMBULANCE_DISPATCH[TOTAL_TIME_MIN])

-- Response time vs SLA target (15 min for emergency)
SLA Target =
15    -- minutes (define as a measure for easy adjustment)

Response Time vs SLA =
[Avg Emergency Response (min)] - [SLA Target]

-- Response time trend vs last week
Response Time Last Week =
CALCULATE(
    [Avg Response Time (min)],
    DATEADD(DIM_DATE[FULL_DATE], -7, DAY)
)

Response Time WoW Change =
[Avg Response Time (min)] - [Response Time Last Week]
```

### SLA Breach Measures

```dax
-- Total SLA breaches
SLA Breach Count =
SUM(FACT_AMBULANCE_DISPATCH[SLA_BREACHED])

-- SLA breach rate
SLA Breach Rate % =
DIVIDE([SLA Breach Count], [Total Dispatches], 0) * 100

-- SLA compliance (inverse)
SLA Compliance % =
100 - [SLA Breach Rate %]

-- SLA status indicator
SLA Status =
SWITCH(
    TRUE(),
    [SLA Breach Rate %] > 20, "🔴 Breach Alert",
    [SLA Breach Rate %] > 10, "🟡 Watch",
    "🟢 Compliant"
)

-- Breach trend: are things getting better or worse?
SLA Breach Rate Last Month =
CALCULATE(
    [SLA Breach Rate %],
    DATEADD(DIM_DATE[FULL_DATE], -1, MONTH)
)

SLA Breach Trend =
[SLA Breach Rate %] - [SLA Breach Rate Last Month]
```

---

## ════════════════════════════════════════════════
## PAGE 3: PATIENT FLOW
## ════════════════════════════════════════════════

### Admission & Discharge Measures

```dax
-- Total admissions
Total Admissions =
COUNTROWS(FACT_PATIENT_FLOW)

-- Daily average admissions
Daily Avg Admissions =
DIVIDE(
    [Total Admissions],
    DISTINCTCOUNT(DIM_DATE[DATE_ID]),
    0
)

-- Admissions via ambulance
Ambulance Admissions =
CALCULATE(
    [Total Admissions],
    FACT_PATIENT_FLOW[ENTRY_MODE] = "Ambulance"
)

-- Ambulance % of all admissions
Ambulance Admission % =
DIVIDE([Ambulance Admissions], [Total Admissions], 0) * 100

-- Total discharges (non-null discharge timestamps)
Total Discharges =
CALCULATE(
    COUNTROWS(FACT_PATIENT_FLOW),
    NOT ISBLANK(FACT_PATIENT_FLOW[DISCHARGE_TIMESTAMP])
)

-- Net patient inflow (admissions minus discharges)
Net Patient Inflow =
[Total Admissions] - [Total Discharges]
```

### Length of Stay Measures

```dax
-- Average length of stay in hours
Avg LOS (hrs) =
AVERAGE(FACT_PATIENT_FLOW[LENGTH_OF_STAY_HRS])

-- Convert to days for display
Avg LOS (days) =
DIVIDE([Avg LOS (hrs)], 24, 0)

-- LOS by condition (for condition-level drill-through)
Avg LOS by Condition =
AVERAGEX(
    VALUES(FACT_PATIENT_FLOW[CONDITION]),
    CALCULATE(AVERAGE(FACT_PATIENT_FLOW[LENGTH_OF_STAY_HRS]))
)

-- LOS benchmark: flag if avg > 5 days
LOS Flag =
IF([Avg LOS (days)] > 5, "⚠️ Above Threshold", "✅ Normal")

-- 90th percentile LOS
P90 LOS (hrs) =
PERCENTILEX.INC(
    FACT_PATIENT_FLOW,
    FACT_PATIENT_FLOW[LENGTH_OF_STAY_HRS],
    0.90
)
```

### ER Throughput Measures

```dax
-- Average ER → ward transfer time
Avg ER to Ward Transfer (hrs) =
AVERAGE(FACT_PATIENT_FLOW[ER_TO_WARD_HRS])

-- ER transfers > 4 hrs (breach)
ER Transfer Breach Count =
CALCULATE(
    COUNTROWS(FACT_PATIENT_FLOW),
    FACT_PATIENT_FLOW[ER_TO_WARD_HRS] > 4
)

ER Transfer Breach % =
DIVIDE([ER Transfer Breach Count], [Total Admissions], 0) * 100
```

### Readmission Measures

```dax
-- Total readmissions
Total Readmissions =
SUM(FACT_PATIENT_FLOW[READMISSION_FLAG])

-- Readmission rate
Readmission Rate % =
DIVIDE([Total Readmissions], [Total Admissions], 0) * 100

-- Readmission rate benchmark (WHO target < 10%)
Readmission Status =
IF([Readmission Rate %] > 10, "🔴 Above WHO Benchmark", "🟢 Within Target")

-- Readmission trend
Readmission Rate Last Month =
CALCULATE(
    [Readmission Rate %],
    DATEADD(DIM_DATE[FULL_DATE], -1, MONTH)
)

Readmission MoM Change =
[Readmission Rate %] - [Readmission Rate Last Month]
```

---

## ════════════════════════════════════════════════
## PAGE 4: EXECUTIVE SUMMARY
## ════════════════════════════════════════════════

```dax
-- Composite health score (0–100, weighted KPIs)
-- Lower breach rates and LOS = higher score
Operational Health Score =
VAR occ_score  = 100 - MAX(0, [Avg Occupancy %] - 75)        -- penalise above 75%
VAR sla_score  = 100 - [SLA Breach Rate %] * 2               -- penalise breaches heavily
VAR los_score  = MAX(0, 100 - ([Avg LOS (days)] - 3) * 10)  -- penalise LOS > 3 days
VAR readm_score= 100 - [Readmission Rate %] * 3
RETURN
ROUND(
    (occ_score * 0.35) + (sla_score * 0.25) +
    (los_score * 0.25) + (readm_score * 0.15),
    1
)

-- Health score label
Health Score Label =
SWITCH(
    TRUE(),
    [Operational Health Score] >= 85, "🟢 Excellent",
    [Operational Health Score] >= 70, "🟡 Good",
    [Operational Health Score] >= 55, "🟠 Fair",
    "🔴 Needs Attention"
)

-- ICU vs General Ward occupancy split
ICU Occupancy % =
CALCULATE(
    [Avg Occupancy %],
    DIM_DEPARTMENT[DEPARTMENT_NAME] = "ICU"
)

ER Occupancy % =
CALCULATE(
    [Avg Occupancy %],
    DIM_DEPARTMENT[DEPARTMENT_NAME] = "Emergency"
)
```

---

## ════════════════════════════════════════════════
## POWER BI SETUP NOTES
## ════════════════════════════════════════════════

### Snowflake Connection Steps
1. Home → Get Data → Snowflake
2. Server: `your_account.snowflakecomputing.com`
3. Warehouse: `SYNAPSE_WH`
4. Database: `SYNAPSE_DB`
5. Select mode: **Import** (for dashboards < 10M rows) or **DirectQuery** (for real-time)
6. Load tables: ANALYTICS.VW_HOSPITAL_CAPACITY, VW_AMBULANCE_OPS, VW_PATIENT_FLOW
   + all DIM_ tables

### Model Relationships (set in Model View)
```
DIM_HOSPITAL    [HOSPITAL_SK]    → FACT_BED_OCCUPANCY    [HOSPITAL_SK]   (1:Many)
DIM_HOSPITAL    [HOSPITAL_SK]    → FACT_AMBULANCE_DISPATCH[HOSPITAL_SK]  (1:Many)
DIM_HOSPITAL    [HOSPITAL_SK]    → FACT_PATIENT_FLOW     [HOSPITAL_SK]   (1:Many)
DIM_DEPARTMENT  [DEPARTMENT_SK]  → FACT_BED_OCCUPANCY    [DEPARTMENT_SK] (1:Many)
DIM_DEPARTMENT  [DEPARTMENT_SK]  → FACT_PATIENT_FLOW     [DEPARTMENT_SK] (1:Many)
DIM_AMBULANCE   [AMBULANCE_SK]   → FACT_AMBULANCE_DISPATCH[AMBULANCE_SK] (1:Many)
DIM_DATE        [DATE_ID]        → FACT_BED_OCCUPANCY    [DATE_ID]       (1:Many)
DIM_DATE        [DATE_ID]        → FACT_AMBULANCE_DISPATCH[DATE_ID]      (1:Many)
DIM_DATE        [DATE_ID]        → FACT_PATIENT_FLOW     [DATE_ID]       (1:Many)
```
Cross-filter direction: **Single** on all fact relationships (avoids ambiguous paths).

### Recommended Visuals Per Page
| Page                  | Visuals                                                                |
|-----------------------|------------------------------------------------------------------------|
| Capacity Overview     | Heatmap (matrix), Gauge, Line chart (7d rolling), Card KPIs            |
| Ambulance Operations  | Bar (response time by type), Bullet chart (vs SLA), Line (SLA trend)  |
| Patient Flow          | Funnel (entry→ward→discharge), Scatter (LOS vs condition), Area chart  |
| Executive Summary     | Scorecard, Radial gauge, AI Narrative text card, Map (hospital locs)   |

### AI Narrative Text Card (LLM Output)
1. Load SUMMARY.LLM_NARRATIVES table
2. Create a table visual filtered to selected hospital + date
3. Show NARRATIVE_TEXT column in a text card visual
4. Add a slicer on NARRATIVE_TYPE to toggle between daily_ops / alert
```
