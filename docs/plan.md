# Implementation plan

Breaks `docs/spec.md` into small steps. Each step is one commit (sometimes two) that leaves tests passing. Order follows the pipeline: data, writer, parser, simulator, ingest, resubmit, report, README, Airflow.

## Ground rules

- `argparse` for the CLI, not typer. One less dependency, nothing to explain.
- Dependencies: `duckdb`, `faker`. Dev: `pytest`, `ruff`. Nothing else unless we agree on it.
- A fixed `run_date` (as-of date) in config drives every "now" in the pipeline: submission timestamps, response arrival, deadlines. No wall clock, so a seeded run gives the same numbers every time.
- Warehouse SQL is written as dbt-style models (see step 9): one `SELECT` per file, `stg_`/`int_`/`dim_`/`fct_` layers, references via `{{ ref() }}` and `{{ source() }}`. A small Python runner resolves those and builds the models in DuckDB, so the same files can drop into a real dbt project later.
- `run-all` starts from an empty `data/` folder. Single steps are idempotent: `build` only picks up trips that haven't been submitted, `ingest` skips files it has already loaded.

## Layout

```
src/encounter_pipeline/
  cli.py          argparse subcommands
  config.py       seed, error rate, run_date, max claims per file, paths
  db.py           DuckDB connection + schema setup
  generate.py     synthetic members, vendors, trips, injected problems
  x12/
    segments.py   delimiters, segment/element joining, ISA fixed-width fields
    envelope.py   ISA/GS/ST wrappers, control numbers
    writer_837.py 837P loops
    parser.py     tokenizer (delimiters read from ISA) + segment list
    read_837.py   837 claims back out of a parsed file
    read_999.py
    read_277ca.py
  payer.py        simulate_payer: 999 + 277CA
  ingest.py
  resubmit.py
  report.py
  sql/            raw/operational table DDL
  models.py       tiny dbt-like runner: resolve ref/source, order by deps, create views
models/
  staging/        stg_ models, one per raw table, light renaming/typing
  intermediate/   int_ models, e.g. latest status per trip
  marts/          dim_ and fct_ models, metric models
tests/
  fixtures/       hand-written golden 999 and 277CA
```

## Steps

### 0. Setup
- Add deps, `cli.py` with stub subcommands, `config.py`, `db.py` that creates the schema. `uv run encounters --help` works.

### 1. Synthetic data
- 1a. `dim_plan` (3 fake plans: 2 MA, 1 Medicaid), members with eligibility spans, vendors with fake NPIs. NPI Luhn check digit helper with tests (NPIs use Luhn over the number with an `80840` prefix).
- 1b. Trips: date, addresses, level of service, loaded miles, status (completed/cancelled/no-show).
- 1c. Problem injection at `error_rate` (default 5%): not eligible on trip date, missing NPI, invalid NPI (bad check digit), future trip date, duplicate trip, bad ZIP. Each injected problem gets a row in `injected_problems` so tests can check the simulator catches exactly those.

### 2. X12 writer basics
- `segments.py`: delimiters as data (element `*`, sub-element `:`, repetition `^`, segment `~`), escape/validate that values don't contain them, ISA fixed-width padding.
- `envelope.py`: ISA/IEA, GS/GE, ST/SE. Control numbers come from a `control_numbers` table so they keep incrementing across runs.
- Tests: ISA is exactly 106 characters, SE01 = segment count including ST and SE, GE01/IEA01 counts, ISA13 = IEA02, GS06 = GE02, ST02 = SE02.

### 3. 837P
- 3a. Header + 1000A submitter / 1000B receiver, 2000A billing provider (the vendor), 2000B subscriber (the member) with 2010BA/2010BB. I'll explain the HL hierarchy (HL01 id, HL02 parent, HL03 level code) here since it's the part of the 837 that trips people up.
- 3b. 2300 claim (CLM, CLM05-3 frequency code, HI diagnosis, pickup/dropoff in 2310E/2310F) and 2400 lines: base HCPCS by level of service + S0215 mileage, origin/destination modifiers, DTP*472.
- 3c. `build` step: acts like a nightly job. Each trip goes out the night after its `reported_date` (when the vendor confirmed it), batched by plan and night, capped at `max_claims_per_file`. Writes to `data/outbound/`, records `submissions` and `submission_claims`.

### 4. X12 parser
- 4a. Tokenizer: read delimiters from ISA positions (element sep at char 3, repetition at ISA11, sub-element at ISA16, segment terminator after ISA16). Tests with non-default delimiters.
- 4b. `read_837.py`: walk the HL loops back into claims. Round-trip test: build a file, parse it, same claims and lines.

### 5. Payer simulator
- 5a. 999 per functional group. Real structural checks on what we sent (required elements present, counts and control numbers match). The injected "missing NPI" lands here as an IK4 required-element error, so 999 rejections come from actual checks, not a coin flip. A rejected transaction set (IK5*R) rejects every claim in it.
- 5b. 277CA per file for transaction sets that passed the 999: one STC per claim. A1/A2 accepts with a payer claim number (REF*1K), A3/A7 rejects with category/status codes mapped to each injected problem.
- 5c. Response delay: seeded 0-5 days after submission, so timeliness has spread.

### 6. Response parsing
- Golden fixtures: a small hand-written 999 (one accepted, one rejected with IK3/IK4) and 277CA (mix of accepts and rejects). Tests parse them into expected rows.

### 7. Ingest
- 7a. `response_files` (raw text, type, received_at). Match 999 to submissions by GS06/ST02 (via AK1/AK2).
- 7b. 277CA claim statuses to `submission_claims` by CLM01 (trip_id) into `claim_status_history`. Append only.
- 7c. Anything that doesn't match goes to `quarantine` with a reason.

### 8. Resubmit
- Classify rejections: correctable (missing/invalid NPI, bad ZIP, future date typo) vs final (not eligible, duplicate). Apply a simulated ops fix to the source rows, rebuild, and record final rejections with a reason.
- See open question 1 on the frequency code.

### 9. Warehouse models + report
- 9a. Model runner (`models.py`): find `.sql` files under `models/`, swap `{{ ref('x') }}` for `x` and `{{ source('raw', 'y') }}` for `y`, sort by those dependencies, and `CREATE OR REPLACE VIEW` each one. About 40 lines, with a test for the dependency order.
- 9b. Staging: `stg_members`, `stg_vendors`, `stg_trips`, `stg_submissions`, `stg_submission_claims`, `stg_claim_status_history`.
- 9c. Intermediate: `int_claim_status_latest` (current status per trip), `int_trip_submissions` (first submission, first acceptance per trip).
- 9d. Marts: `dim_member`, `dim_vendor`, `dim_plan`, `dim_date`, `fct_encounter` (one row per completed trip, current status), `fct_claim_status` (one row per event).
- 9e. Metric models: completeness by plan/month, first-pass acceptance, rejections by reason, resubmission success, days to submission/acceptance (median, p90), trips past deadline.
- 9f. `report` prints a short summary and writes `data/report.md`.

### 10. run-all + end-to-end test
- `run-all` runs every step, including a second simulate/ingest pass after resubmit. Test: two seeded runs produce identical metrics.

### 11. README
- A few short paragraphs, how to run it, a trimmed sample of an 837P, 999 and 277CA.

### 12. Stretch: local dbt project (done)
- `dbt_project.yml` + `profiles.yml` for dbt-duckdb pointing `model-paths` at `models/`, a `sources.yml` for the raw tables, and `schema.yml` tests (`unique`, `not_null`, `accepted_values` on status). `dbt build` should give the same tables as the Python runner. dbt-duckdb goes in an optional dependency group so the main install stays small.

### 13. Stretch: Airflow DAG
- `dags/encounters_dag.py` with one task per step calling the same functions. Not run in CI, just importable if Airflow is installed.

## Decisions (agreed 2026-10-27)

1. **Frequency code on resubmits.** Claims rejected on the 277CA never got into the payer's system and have no payer claim number, so they go back as a new original (CLM05-3 = 1). Replacements (CLM05-3 = 7 with REF*F8 = payer claim number) are for correcting encounters the payer already accepted; the ops-fix step corrects a few accepted ones (e.g. wrong mileage) so both paths show up.
2. **999 rejections** come from real structural checks. Missing NPI fails at the 999 (IK4 required element missing); a bad NPI check digit passes the 999 and fails at the 277CA.
3. **Charges** use a small fake fee schedule instead of $0.
4. **Diagnosis** is picked from a short list of generic ICD-10 Z codes.
