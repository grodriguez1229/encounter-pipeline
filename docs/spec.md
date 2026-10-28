# encounter-pipeline: design spec

A small, end-to-end encounter submission pipeline for non-emergency medical transportation (NEMT), built on synthetic data. It takes completed rides, builds X12 837P encounter files, simulates the payer's 999 and 277CA responses, ingests those responses, and measures encounter completeness, accuracy and timeliness.

Everything is synthetic. No real member, provider or payer data, and nothing copied from any employer.

## Why NEMT

Medicare Advantage and Medicaid plans that cover rides have to report each ride as an encounter, even when nothing is billed per ride. Rides are a simple domain to model (one trip = one claim with a couple of service lines), and the hard part is the same as any encounter program: files out, responses back, reconcile, resubmit, measure.

## Pipeline

```
generate   ->  build_837  ->  simulate_payer  ->  ingest_responses  ->  resubmit  ->  report
(trips)        (837P out)     (999 + 277CA)       (parse + match)       (fix + 837 freq 7)
```

Each step reads from and writes to a local DuckDB file (`data/warehouse.duckdb`) plus a `data/outbound/` and `data/inbound/` folder for the X12 files. Steps are idempotent and can be re-run.

### 1. generate (synthetic source data)

Seeded (same seed = same data). Use Faker.

- `members`: member_id, plan (2-3 fake MA/Medicaid plans), name, DOB, gender, address, eligibility start/end.
- `vendors`: transportation providers, fake 10-digit NPIs (valid Luhn check digit), tax ID, name, address.
- `trips`: trip_id, member_id, vendor_id, trip_date, pickup/dropoff address, level of service (ambulatory, wheelchair, stretcher), loaded miles, status (completed, cancelled, no-show). Only completed trips become encounters.

Inject data problems on purpose at a configurable rate (default ~5%) so the payer has something to reject: member not eligible on trip date, missing or invalid NPI, trip date in the future, duplicate trip, bad ZIP.

### 2. build_837 (outbound encounter files)

Hand-written X12 writer. No X12 library, so the code shows the format is understood.

- 837P 005010X222A1. Envelope: ISA/IEA, GS/GE, ST/SE with control numbers that increment and are stored.
- One claim (2300 loop) per trip. CLM01 = our patient control number (trip_id), CLM05-3 = 1 (original). Charge can be 0 or a fee-schedule amount, since this is an encounter.
- Service lines (2400): base rate HCPCS by level of service (A0100 taxi, A0130 wheelchair van, T2005 stretcher van) plus mileage (S0215), with origin/destination modifiers (e.g. RH = residence to hospital). DTP*472 service date.
- Batch by plan and by day, with a configurable max claims per file.
- Record every submission in `submissions` (file name, ISA13, GS06, ST02, claim count, created_at) and `submission_claims` (trip_id, submission id, frequency code, line count).

### 3. simulate_payer (fake clearinghouse)

Reads outbound files and writes response files to `data/inbound/`. This exists so there's something realistic to ingest.

- 999 per functional group: AK9 accepted, or rejected with IK3/IK4 errors for structural problems.
- 277CA per file: one STC per claim. Accept (A1/A2) or reject (A3/A7) with category/status codes tied to the injected problems (e.g. member not found, invalid provider ID, duplicate).
- Some responses arrive a few days late, so timeliness has real spread.

### 4. ingest_responses (parse and match)

Hand-written X12 parser: split on the delimiters from the ISA segment, never hard-code them.

- Match 999s to submissions by GS06/ST02. Match 277CA claim statuses to `submission_claims` by CLM01/trip_id.
- Write `response_files` (raw file, type, received_at) and `claim_status_history` (trip_id, submission id, status, STC codes, received_at). Keep history, don't overwrite.
- Unmatched responses go to a quarantine table instead of failing the load.

### 5. resubmit

- Fix the correctable rejections in the source data (simulate an ops fix) and resubmit them as new originals (CLM05-3 = 1). A claim rejected on the 277CA never made it into the payer's system, so there's no payer claim number to replace.
- Also correct a few already-accepted encounters (e.g. wrong mileage) and send those as replacements (CLM05-3 = 7) with REF*F8 = the payer claim number from the 277CA.
- Leave the uncorrectable ones (e.g. member not eligible) as final rejections with a reason.

### 6. report (measurement)

dbt-style SQL models in DuckDB (staging, intermediate, marts; `ref()`/`source()` resolved by a small Python runner) plus a CLI that prints a short summary (or writes a Markdown report):

- Completeness: completed trips with an accepted encounter / all completed trips, by plan and month.
- Accuracy: first-pass acceptance rate, rejections by reason, resubmission success rate.
- Timeliness: days from trip date to submission and to acceptance (median, p90). Count trips past a configurable submission deadline.

## Data model (DuckDB)

Star-ish, kept small:

- dims: `dim_member`, `dim_vendor`, `dim_plan`, `dim_date`
- facts: `fct_encounter` (one row per trip, current status), `fct_claim_status` (one row per status event)
- operational: `submissions`, `submission_claims`, `response_files`, `quarantine`

## Tech

- Python 3.12, uv, DuckDB, Faker, pytest, ruff.
- CLI with plain `argparse` or `typer`: `encounters generate | build | simulate | ingest | resubmit | report | run-all`.
- Orchestration: `run-all` runs the steps in order. Stretch: a small Airflow DAG file that calls the same functions, to show the steps map onto Airflow tasks (no need to run a real Airflow cluster). Stretch: a local dbt-duckdb project over the same model files.

## Tests

- X12 writer/parser round-trip: build a file, parse it back, same claims.
- Envelope checks: SE01 segment count, IEA/GE counts, control numbers match.
- A golden 999 and 277CA fixture parsed into the expected rows.
- End-to-end: seeded run produces the same metrics every time.

## Out of scope

Real clearinghouse connections, SFTP, PHI handling beyond "it's all fake", full 837P validation against the implementation guide, 835 remittance.

## Done looks like

`uv run encounters run-all` on a fresh clone generates data, writes 837s, gets responses back, resubmits fixes, and prints the completeness/accuracy/timeliness numbers. The README explains it in a few short paragraphs with a sample of each file type.
