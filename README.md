# encounter-pipeline

A small encounter submission pipeline for non-emergency medical transportation, built on fake data. It builds X12 837P encounter files from rides, gets 999 and 277CA responses back from a simulated payer, matches them up, resubmits what can be fixed, and reports completeness, accuracy and timeliness.

Work in progress. Design is in [docs/spec.md](docs/spec.md).

## How I built it

I built this with Claude Code. I wrote the spec, Claude turned it into a step-by-step [plan](docs/plan.md), and then it wrote the code one small commit at a time while I reviewed each one. [CLAUDE.md](CLAUDE.md) has the ground rules I gave it, and [docs/devlog.md](docs/devlog.md) has what got built when, including the mistakes that tests or review caught.
