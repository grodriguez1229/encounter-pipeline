# encounter-pipeline

A small encounter submission pipeline for non-emergency medical transportation, built on fake data. It builds X12 837P encounter files from rides, gets 999 and 277CA responses back from a simulated payer, matches them up, resubmits what can be fixed, and reports completeness, accuracy and timeliness.

Work in progress. Design is in [docs/spec.md](docs/spec.md).
