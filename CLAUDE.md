# encounter-pipeline

Synthetic NEMT encounter pipeline: 837P out, 999/277CA back, reconcile, resubmit, measure. The design is in `docs/spec.md`; read it before changing anything.

## Working style

- The agent writes the code; Gus reviews it. Gus has to be able to explain every line in an interview, so work in small, reviewable commits (one step or concept at a time) and say briefly why a choice was made, especially anything X12-specific (loops, segments, control numbers, STC codes).
- Gus is a healthcare data engineer: fluent in claims, eligibility, HL7, FHIR, dbt, SQL, AWS. New to raw X12. Don't explain general healthcare terms; do explain X12 details the first time they come up.
- Keep it simple. Plain Python and SQL over frameworks. No X12 libraries: the hand-written writer and parser are the point.
- This repo will be public. All data is synthetic. Never add real names, NPIs, member IDs, employer code, or secrets.
- README and docs: short and plain. Casual, first person, no marketing tone, no emoji.

## Commands

- `uv sync` to install, `uv run pytest` to test, `uv run ruff check .` to lint.
- `uv run encounters run-all` runs the whole pipeline (once it exists).

## Git

Commit after each working step with a short, plain message. Don't push or create a GitHub repo unless Gus asks.
