# Dev log

How this got built, in order. I used Claude Code as the main coder and reviewed each commit myself. The rules it worked under are in [CLAUDE.md](../CLAUDE.md): small commits, plain Python, no X12 libraries, and an explanation for anything X12-specific so I can walk through every line.

## 2026-10-27

**Spec, then plan, then code.** I wrote [spec.md](spec.md) first, had Claude break it into [plan.md](plan.md), and went over the plan before any code got written. Two things changed in the spec during that review:

- Resubmits. The spec said to send fixed rejections as CLM05-3 = 7 (replacement). That's wrong for a claim rejected on the 277CA: it never got into the payer's system, so there's nothing to replace. Those go back as new originals (1). Replacements (7 with REF*F8) are for correcting encounters the payer already accepted.
- Warehouse SQL is written as dbt-style models (`ref()`/`source()`, staging/intermediate/marts), run by a small Python runner, so the same files can move into a real dbt project later.

**Synthetic data (step 1).** Members, vendors, round-trip rides, and about 5% of completed trips broken on purpose: not eligible, missing NPI, bad NPI check digit, future date, duplicate, bad ZIP. The broken trips go in an answer key table that the fake payer never reads. Tests check its rejections against that key.

**837P writer (steps 2-3).** Hand-written envelope, HL hierarchy, claims and service lines. `build` acts like a nightly job: each trip goes out the night after the vendor reports it. The first version had nothing like `reported_date` and would have submitted everything on the last day, which makes timeliness meaningless.

**Parser and payer simulator (steps 4-5).** The parser reads delimiters from the ISA instead of assuming them. The simulator runs real syntax checks for the 999 (a missing NPI breaks the NM108/NM109 pairing rule and takes down the whole file) and business edits for the 277CA.

**Ingest (steps 6-7).** Readers tested against hand-written golden files, then matching by control numbers only: GS06/ST02 for the 999, BHT03 then CLM01 for the 277CA. Anything that doesn't match goes to quarantine.

### Things that were wrong and got caught

- STC status codes. The first pick for duplicates was 78; checking X12's code list showed 78 is "duplicate, awaiting processing" and 54 is "duplicate of a previously processed claim".
- The generator booked some members for two identical round trips on the same day, which the payer would have rejected as duplicates nobody injected. A test comparing problems to the answer key caught it.
- Control numbers were assigned plan by plan instead of night by night.
- Moving a trip outside eligibility didn't move its reported date, so the ride was "reported" before it happened and got rejected for the wrong reason. Same answer-key test caught it.
- The billing provider ZIP needs ZIP+4 in 5010. The vendors only had 5 digits.

**Resubmit (step 8).** Ops decisions come from the rejection codes only. Fixable problems (NPI, ZIP, date) get corrected in the source data, logged in `source_adjustments`, and go back as new originals. Not-eligible and duplicates become final rejections. Vendors' late mileage corrections on accepted encounters go out as replacements (CLM05-3 = 7, REF*F8 = payer claim number), and the fake payer now rejects a replacement that points at a claim number it never issued (A7:464). After three rounds everything is either accepted, final, or still waiting near the end of the data.

- First version gave each claim from a 999-rejected file its own fix delay. A duplicate copy could go back before its original, get accepted, and the real trip got rejected as the duplicate. Ops resends a bounced file together, so the delay is now per file for 999s. The test for this fails if the old behavior comes back; I checked.

**Models and report (step 9).** A 60-line runner stands in for `dbt run`: it resolves `ref()`, `source()` and `var()`, orders models with the standard library's `graphlib`, and creates each one as a DuckDB view. Staging is one model per raw table, intermediate works out each trip's first pass, first acceptance and current status, and the marts have the dims, `fct_encounter`, `fct_claim_status` and four metric models built with `GROUPING SETS` so every table has an all-plans row. `report` prints three headline numbers and writes `data/report.md`. A test checks completeness against a count straight from the raw tables, so the models can't drift quietly.

- Duplicates: left out of completeness and timeliness (same ride, not another one owed), but counted against first-pass accuracy (we sent them, and they were wrong).
- Future-dated trips that are still waiting on a fix showed up as one row per 2027 month in the report. They're folded into one "future date (bad data)" row now.
