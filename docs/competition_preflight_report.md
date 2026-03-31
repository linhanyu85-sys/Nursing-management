# Competition Preflight Report

Generated at: 2026-03-31 20:30:31 +08:00

Target stack: api=8000, device=8013, patient_context=8002
Target owner: linmeili (u_linmeili)

## Check Results

| Check | Result | Detail |
|---|---|---|
| license_scan | PASS | skipped_by_param |
| api_gateway_health | PASS | status=ok |
| device_gateway_health | PASS | status=ok |
| device_owner_binding | PASS | owner_user_id=u_linmeili, owner_username=linmeili |
| bed_mapping_coverage | PASS | [verify] department=dep-card-01 coverage_mode=existing target_beds=17 / [verify] mapped_beds_in_db=17 / [verify] missing_in_db=0 / [verify] missing_in_api=0 / [verify] PASS: all beds map to real patient context. |
| sample_bed_selected | PASS | bed_no=12 |
| workflow_patient_query | PASS | status=completed; bed=12; patient=ec328696-59c5-4ba5-9714-281152afa0ed; stt_len=18; summary_len=157; review_required=True |
| workflow_document | PASS | status=completed; bed=12; patient=ec328696-59c5-4ba5-9714-281152afa0ed; stt_len=28; summary_len=109; review_required=True |
| workflow_handover | PASS | status=completed; bed=12; patient=ec328696-59c5-4ba5-9714-281152afa0ed; stt_len=29; summary_len=202; review_required=True |
| workflow_recommendation | PASS | status=completed; bed=12; patient=ec328696-59c5-4ba5-9714-281152afa0ed; stt_len=68; summary_len=308; review_required=True |
| db_persist_document_drafts | PASS | before=33, after=34, delta=1 |
| db_persist_handover_records | PASS | before=15, after=16, delta=1 |
| db_persist_ai_recommendations | PASS | before=40, after=41, delta=1 |
| db_persist_audit_logs | PASS | before=237, after=244, delta=7 |

## DB Counters

| Table | Before | After | Delta |
|---|---:|---:|---:|
| document_drafts | 33 | 34 | 1 |
| handover_records | 15 | 16 | 1 |
| ai_recommendations | 40 | 41 | 1 |
| audit_logs | 237 | 244 | 7 |
