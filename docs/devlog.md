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
