# encounter-pipeline

A small encounter submission pipeline for non-emergency medical transportation (NEMT), built on fake data. It builds X12 837P encounter files from rides, gets 999 and 277CA responses back from a simulated payer, matches them up, resubmits what can be fixed, and reports completeness, accuracy and timeliness.

I've done a lot of partner data exchange (eligibility and claims files, HL7, FHIR), but never raw X12. So this writes and parses it all by hand, no X12 libraries, to actually learn how the 837 / 999 / 277CA loop works. Everything is synthetic: fake members, fake vendors, fake NPIs (they start with 9, which real ones never do), fake payers.

## Run it

```
uv sync
uv run encounters run-all
```

That wipes `data/`, then:

1. **generate** makes 1,000 members, 17 vendors and about 6,000 ride legs for Jan-Jun 2026, and breaks 5% of the completed ones on purpose (not eligible, missing NPI, bad NPI, future date, duplicate, bad ZIP).
2. **build** acts like a nightly job: each ride goes out as an 837P the night after the vendor reports it, batched by plan.
3. **simulate** is the fake payer. It runs syntax checks and sends a 999 per file, then business edits and a 277CA per claim. Some responses come back days late.
4. **ingest** loads the responses and matches them by control numbers, never file names. Anything that doesn't match goes to a quarantine table.
5. **resubmit** works the rejections: fix what can be fixed and resend it, finalize what can't (not eligible, duplicates), and send late mileage corrections as replacements. Steps 3-5 repeat until nothing new goes out.
6. **report** builds dbt-style SQL models in DuckDB and writes `data/report.md`.

Each step also runs on its own (`uv run encounters build`, etc.). Same seed, same output, byte for byte.

The models also run as a real dbt project (dbt-duckdb), with tests on keys, statuses and relationships:

```
uv sync --group dbt
uv run --group dbt dbt build
```

```
- Completeness: 95.1% of completed trips have an accepted encounter
- First-pass acceptance: 86.6%, resubmission success: 98.6%
- Median days from trip to submission: 4; 2.8% past the 30-day deadline
```

## What the files look like

An 837P with one claim (one ride leg, dialysis clinic back home), trimmed:

```
ISA*00*          *00*          *ZZ*SYNNEMT        *ZZ*SYNMA1         *260618*0200*^*00501*000000668*0*T*:~
GS*HC*SYNNEMT*SYNMA1*20260618*0200*668*X*005010X222A1~
ST*837*0668*005010X222A1~
BHT*0019*00*000000668*20260618*0200*RP~           RP = reporting: an encounter, not a bill
...
HL*1**20*1~                                       billing provider (the vendor)
NM1*85*2*WALL TRANSPORT LLC*****XX*9708620957~
HL*2*1*22*0~                                      subscriber (the member), child of HL 1
NM1*IL*1*FARMER*BRITTANY****MI*M00000008~
...
CLM*T00005352*55.25***99:B:1*Y*A*Y*Y~             CLM01 = our trip ID, CLM05-3 = 1 (original)
HI*ABK:Z992~                                      dependence on renal dialysis
LX*1~
SV1*HC:A0100:JR*25*UN*1***1~                      base rate, modifier JR = dialysis to residence
DTP*472*D8*20260610~
LX*2~
SV1*HC:S0215:JR*30.25*UN*12.1***1~                12.1 loaded miles
DTP*472*D8*20260610~
SE*32*0668~
GE*1*668~
IEA*1*000000668~
```

A 999 rejecting a whole file because one vendor had no NPI:

```
AK1*HC*234*005010X222A1~       our GS06
AK2*837*0234*005010X222A1~     our ST02
IK3*NM1*263*2010AA*8~          segment 263, billing provider loop
IK4*9*67*2~                    NM109 (the NPI) missing
IK5*R*5~                       transaction rejected
AK9*R*1*1*0~                   group rejected
```

A 277CA rejecting one claim for a bad NPI check digit (the 999 can't catch that, the syntax is fine):

```
NM1*85*2*WARE TRANSPORT LLC*****XX*9870894100~
HL*32*31*PT~
NM1*QC*1*SMITH*JOSHUA****MI*M00000369~
TRN*2*T00001188~                    our CLM01
STC*A7:562:85*20260207*U*43.75~     A7 invalid info, 562 NPI, 85 billing provider
```

## Layout

```
src/encounter_pipeline/
  generate.py  build.py  payer.py  ingest.py  resubmit.py  report.py
  models.py            tiny stand-in for `dbt run` (ref, source, var)
  x12/                 segment writer, envelopes, 837P/999/277CA writers and readers
models/                staging, intermediate, marts, metrics (dbt SQL + schema tests)
dbt_project.yml        same models as a dbt-duckdb project
tests/                 including hand-written golden 999 and 277CA files
docs/                  spec, plan, dev log
```

## Not here

Real clearinghouse connections, SFTP, full 837P validation against the implementation guide, 835 remittances, and the ambulance-only segments (CR1). The payer is a simulation, so its edits are the ones I chose, not any real payer's.

## How I built it

I built this with Claude Code. I wrote the spec, Claude turned it into a step-by-step [plan](docs/plan.md), and then it wrote the code one small commit at a time while I reviewed each one. [CLAUDE.md](CLAUDE.md) has the ground rules I gave it, and [docs/devlog.md](docs/devlog.md) has what got built when, including the mistakes that tests or review caught.
