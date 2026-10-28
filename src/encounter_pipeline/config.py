"""Pipeline settings. Everything that changes the output lives here so a run is reproducible."""

from dataclasses import dataclass
from datetime import date
from pathlib import Path


@dataclass(frozen=True)
class Config:
    seed: int = 42
    n_members: int = 1000
    n_vendors: int = 15
    n_trips: int = 6000
    # Trips are spread from this date up to the day before run_date.
    trips_start_date: date = date(2026, 1, 1)
    # Share of completed trips that get a deliberate data problem.
    error_rate: float = 0.05
    # Stands in for "today" everywhere (timestamps, response arrival, deadlines),
    # so a seeded run gives the same numbers no matter when it runs.
    run_date: date = date(2026, 6, 30)
    max_claims_per_file: int = 500
    # Days after the trip date by which the encounter should be submitted.
    submission_deadline_days: int = 30
    data_dir: Path = Path("data")

    @property
    def db_path(self) -> Path:
        return self.data_dir / "warehouse.duckdb"

    @property
    def outbound_dir(self) -> Path:
        return self.data_dir / "outbound"

    @property
    def inbound_dir(self) -> Path:
        return self.data_dir / "inbound"
