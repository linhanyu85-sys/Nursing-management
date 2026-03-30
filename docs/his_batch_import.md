# HIS Batch Import (linmeili)

## Goal
Import real HIS/case records into PostgreSQL so device queries use real patients instead of virtual empty-bed placeholders.

## Script
- Path: `scripts/import_his_cases_to_postgres.ps1`
- Default target user: `linmeili`
- Default database: `ai_nursing` in container `ai_nursing_postgres`

## Source File
Supported source formats:
- `.csv`
- `.json`
- `.jsonl`

Recommended columns:
- `bed_no` (required)
- `full_name` (required)
- `mrn` (required, or provide `inpatient_no` and script will generate `AUTO-<inpatient_no>`)
- `inpatient_no`
- `room_no`
- `gender`
- `age`
- `birth_date`
- `chief_complaint`
- `admission_diagnosis`

Template:
- `data/his_import/linmeili_his_template.csv`

Optional export snapshot from current DB:
```powershell
.\scripts\export_department_cases_csv.ps1 -DepartmentCode "dep-card-01"
```
This writes:
- `data/his_import/dep-card-01_current_cases.csv`

## Run
```powershell
cd "D:\Desktop\ai agent 护理精细化部署"

# 1) Dry run (validation only)
.\scripts\import_his_cases_to_postgres.ps1 `
  -SourcePath ".\data\his_import\linmeili_his_template.csv" `
  -Username "linmeili" `
  -RequireFullBedRange `
  -BedStart 1 `
  -BedEnd 40 `
  -DryRun

# 2) Execute import
.\scripts\import_his_cases_to_postgres.ps1 `
  -SourcePath ".\data\his_import\linmeili_his_template.csv" `
  -Username "linmeili" `
  -RequireFullBedRange `
  -BedStart 1 `
  -BedEnd 40 `
  -ClearDepartmentBeds
```

## Notes
- `-RequireFullBedRange` makes the run fail if any bed in range is missing from source.
- `-ClearDepartmentBeds` marks non-imported beds as empty in target department.
- Startup scripts now force:
  - `INCLUDE_VIRTUAL_EMPTY_BEDS=false`
  - `DB_ERROR_FALLBACK_TO_MOCK=false`
  so missing beds are not auto-filled by virtual placeholders.

## Post-Import Verification
```powershell
.\scripts\verify_bed_mapping.ps1 `
  -DepartmentCode "dep-card-01" `
  -BedStart 1 `
  -BedEnd 40 `
  -PatientContextPort 39002
```
If any bed is missing in DB or API context, the script exits with code `1`.
