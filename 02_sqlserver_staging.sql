-- =====================================================
-- SYNAPSE HEALTHCARE ANALYTICS PLATFORM
-- STEP 2: SQL Server Staging Layer
-- Run this in SQL Server Management Studio (SSMS)
-- or Azure Data Studio
-- =====================================================

-- Create database
CREATE DATABASE SynapseStaging;
GO
USE SynapseStaging;
GO

-- ─────────────────────────────────────────────────────
-- SCHEMA SETUP
-- raw  → as-landed CSVs, no transformation
-- stg  → cleaned, typed, validated
-- ─────────────────────────────────────────────────────
CREATE SCHEMA raw;
GO
CREATE SCHEMA stg;
GO

-- =====================================================
-- RAW TABLES (exact shape of CSVs)
-- =====================================================

-- RAW: Hospitals
CREATE TABLE raw.hospital (
    hospital_id     INT,
    hospital_name   VARCHAR(100),
    city            VARCHAR(50),
    state           VARCHAR(50),
    tier            VARCHAR(10),
    total_beds      INT,
    icu_beds        INT,
    ventilators     INT,
    lat             FLOAT,
    lon             FLOAT,
    load_ts         DATETIME DEFAULT GETDATE()
);

-- RAW: Departments
CREATE TABLE raw.department (
    department_id   INT,
    hospital_id     INT,
    department_name VARCHAR(50),
    total_beds      INT,
    floor_number    INT,
    load_ts         DATETIME DEFAULT GETDATE()
);

-- RAW: Ambulances
CREATE TABLE raw.ambulance (
    ambulance_id        INT,
    registration_no     VARCHAR(20),
    hospital_id         INT,
    vehicle_type        VARCHAR(20),
    manufacture_year    INT,
    status              VARCHAR(20),
    load_ts             DATETIME DEFAULT GETDATE()
);

-- RAW: Date Dimension
CREATE TABLE raw.dim_date (
    date_id         INT,
    full_date       DATE,
    day_of_week     VARCHAR(10),
    day_num         INT,
    week_num        INT,
    month_num       INT,
    month_name      VARCHAR(15),
    quarter         INT,
    year            INT,
    is_weekend      BIT,
    is_holiday      BIT,
    load_ts         DATETIME DEFAULT GETDATE()
);

-- RAW: Bed Occupancy Fact
CREATE TABLE raw.bed_occupancy (
    occupancy_id    INT,
    department_id   INT,
    hospital_id     INT,
    date_id         INT,
    snapshot_hour   INT,
    snapshot_ts     VARCHAR(30),        -- land as string, parse in stg
    total_beds      INT,
    occupied_beds   INT,
    available_beds  INT,
    occupancy_pct   FLOAT,
    on_hold_beds    INT,
    critical_flag   INT,
    load_ts         DATETIME DEFAULT GETDATE()
);

-- RAW: Ambulance Dispatch Fact
CREATE TABLE raw.ambulance_dispatch (
    dispatch_id             INT,
    ambulance_id            INT,
    hospital_id             INT,
    date_id                 INT,
    call_timestamp          VARCHAR(30),
    dispatch_timestamp      VARCHAR(30),
    on_scene_timestamp      VARCHAR(30),
    hospital_arrival_ts     VARCHAR(30),
    call_type               VARCHAR(20),
    call_outcome            VARCHAR(30),
    response_time_min       INT,
    on_scene_time_min       INT,
    transport_time_min      INT,
    total_time_min          INT,
    sla_breached            INT,
    crew_count              INT,
    load_ts                 DATETIME DEFAULT GETDATE()
);

-- RAW: Patient Flow Fact
CREATE TABLE raw.patient_flow (
    flow_id                 INT,
    patient_id              VARCHAR(15),
    hospital_id             INT,
    department_id           INT,
    admit_date_id           INT,
    admit_timestamp         VARCHAR(30),
    discharge_timestamp     VARCHAR(30),
    length_of_stay_hrs      INT,
    condition               VARCHAR(50),
    entry_mode              VARCHAR(20),
    age_group               VARCHAR(10),
    gender                  CHAR(1),
    er_to_ward_hrs          FLOAT,
    readmission_flag        INT,
    discharge_type          VARCHAR(20),
    load_ts                 DATETIME DEFAULT GETDATE()
);
GO

-- =====================================================
-- BULK LOAD FROM CSV (run from SSMS or sqlcmd)
-- Replace C:\synapse\data\ with your actual path
-- =====================================================

-- NOTE: Enable BULK INSERT permissions in SQL Server config if needed
-- EXEC sp_configure 'show advanced options', 1; RECONFIGURE;
-- EXEC sp_configure 'Ad Hoc Distributed Queries', 1; RECONFIGURE;

BULK INSERT raw.hospital
FROM 'C:\synapse\data\dim_hospital.csv'
WITH (FIRSTROW = 2, FIELDTERMINATOR = ',', ROWTERMINATOR = '\n', TABLOCK);

BULK INSERT raw.department
FROM 'C:\synapse\data\dim_department.csv'
WITH (FIRSTROW = 2, FIELDTERMINATOR = ',', ROWTERMINATOR = '\n', TABLOCK);

BULK INSERT raw.ambulance
FROM 'C:\synapse\data\dim_ambulance.csv'
WITH (FIRSTROW = 2, FIELDTERMINATOR = ',', ROWTERMINATOR = '\n', TABLOCK);

BULK INSERT raw.dim_date
FROM 'C:\synapse\data\dim_date.csv'
WITH (FIRSTROW = 2, FIELDTERMINATOR = ',', ROWTERMINATOR = '\n', TABLOCK);

BULK INSERT raw.bed_occupancy
FROM 'C:\synapse\data\fact_bed_occupancy.csv'
WITH (FIRSTROW = 2, FIELDTERMINATOR = ',', ROWTERMINATOR = '\n', TABLOCK);

BULK INSERT raw.ambulance_dispatch
FROM 'C:\synapse\data\fact_ambulance_dispatch.csv'
WITH (FIRSTROW = 2, FIELDTERMINATOR = ',', ROWTERMINATOR = '\n', TABLOCK);

BULK INSERT raw.patient_flow
FROM 'C:\synapse\data\fact_patient_flow.csv'
WITH (FIRSTROW = 2, FIELDTERMINATOR = ',', ROWTERMINATOR = '\n', TABLOCK);
GO

-- =====================================================
-- STAGING TRANSFORMS: Validate, cast, clean
-- =====================================================

-- STG: Hospital (add data quality flags)
SELECT
    hospital_id,
    LTRIM(RTRIM(hospital_name))         AS hospital_name,
    city, state, tier,
    total_beds, icu_beds, ventilators,
    lat, lon,
    CASE WHEN total_beds IS NULL OR total_beds <= 0 THEN 1 ELSE 0 END AS dq_flag,
    GETDATE()                           AS stg_load_ts
INTO stg.hospital
FROM raw.hospital
WHERE hospital_id IS NOT NULL;

-- STG: Department
SELECT
    department_id, hospital_id,
    LTRIM(RTRIM(department_name))       AS department_name,
    total_beds, floor_number,
    GETDATE()                           AS stg_load_ts
INTO stg.department
FROM raw.department
WHERE department_id IS NOT NULL
  AND hospital_id IS NOT NULL;

-- STG: Ambulance
SELECT
    ambulance_id,
    UPPER(LTRIM(RTRIM(registration_no))) AS registration_no,
    hospital_id, vehicle_type,
    manufacture_year,
    CASE WHEN status NOT IN ('Active','Maintenance') THEN 'Unknown' ELSE status END AS status,
    GETDATE() AS stg_load_ts
INTO stg.ambulance
FROM raw.ambulance
WHERE ambulance_id IS NOT NULL;

-- STG: Bed Occupancy (parse timestamps, validate ranges)
SELECT
    occupancy_id, department_id, hospital_id, date_id,
    snapshot_hour,
    TRY_CAST(snapshot_ts AS DATETIME)   AS snapshot_ts,
    total_beds, occupied_beds, available_beds,
    ROUND(occupancy_pct, 2)             AS occupancy_pct,
    on_hold_beds, critical_flag,
    -- DQ checks
    CASE WHEN occupied_beds > total_beds THEN 1 ELSE 0 END AS dq_occupied_exceeds_total,
    CASE WHEN occupancy_pct < 0 OR occupancy_pct > 100 THEN 1 ELSE 0 END AS dq_invalid_pct,
    GETDATE() AS stg_load_ts
INTO stg.bed_occupancy
FROM raw.bed_occupancy
WHERE occupancy_id IS NOT NULL
  AND total_beds > 0;

-- STG: Ambulance Dispatch (parse all timestamps)
SELECT
    dispatch_id, ambulance_id, hospital_id, date_id,
    TRY_CAST(call_timestamp AS DATETIME)      AS call_timestamp,
    TRY_CAST(dispatch_timestamp AS DATETIME)  AS dispatch_timestamp,
    TRY_CAST(on_scene_timestamp AS DATETIME)  AS on_scene_timestamp,
    TRY_CAST(hospital_arrival_ts AS DATETIME) AS hospital_arrival_ts,
    call_type, call_outcome,
    response_time_min, on_scene_time_min, transport_time_min, total_time_min,
    sla_breached, crew_count,
    CASE WHEN response_time_min < 0 OR response_time_min > 120 THEN 1 ELSE 0 END AS dq_invalid_response,
    GETDATE() AS stg_load_ts
INTO stg.ambulance_dispatch
FROM raw.ambulance_dispatch
WHERE dispatch_id IS NOT NULL;

-- STG: Patient Flow
SELECT
    flow_id,
    UPPER(patient_id)                         AS patient_id,
    hospital_id, department_id, admit_date_id,
    TRY_CAST(admit_timestamp AS DATETIME)     AS admit_timestamp,
    TRY_CAST(discharge_timestamp AS DATETIME) AS discharge_timestamp,
    length_of_stay_hrs, condition, entry_mode,
    age_group, gender, er_to_ward_hrs,
    readmission_flag, discharge_type,
    CASE WHEN discharge_timestamp IS NOT NULL
         AND TRY_CAST(discharge_timestamp AS DATETIME) < TRY_CAST(admit_timestamp AS DATETIME)
         THEN 1 ELSE 0 END AS dq_discharge_before_admit,
    GETDATE() AS stg_load_ts
INTO stg.patient_flow
FROM raw.patient_flow
WHERE flow_id IS NOT NULL;
GO

-- =====================================================
-- DATA QUALITY REPORT
-- Run after staging to spot issues before Snowflake load
-- =====================================================
SELECT 'raw.hospital'          AS tbl, COUNT(*) AS row_count FROM raw.hospital          UNION ALL
SELECT 'raw.department',                COUNT(*)              FROM raw.department         UNION ALL
SELECT 'raw.ambulance',                 COUNT(*)              FROM raw.ambulance          UNION ALL
SELECT 'raw.bed_occupancy',             COUNT(*)              FROM raw.bed_occupancy      UNION ALL
SELECT 'raw.ambulance_dispatch',        COUNT(*)              FROM raw.ambulance_dispatch UNION ALL
SELECT 'raw.patient_flow',              COUNT(*)              FROM raw.patient_flow;
GO

-- DQ summary: flag rates
SELECT
    'bed_occupancy'          AS table_name,
    SUM(dq_occupied_exceeds_total) AS dq_occupied_exceeds_total,
    SUM(dq_invalid_pct)            AS dq_invalid_pct
FROM stg.bed_occupancy
UNION ALL
SELECT
    'ambulance_dispatch',
    SUM(dq_invalid_response), 0
FROM stg.ambulance_dispatch
UNION ALL
SELECT
    'patient_flow',
    SUM(dq_discharge_before_admit), 0
FROM stg.patient_flow;
GO
