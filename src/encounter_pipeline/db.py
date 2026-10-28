"""DuckDB connection and schema setup."""

from importlib.resources import files

import duckdb

from encounter_pipeline.config import Config


def connect(config: Config) -> duckdb.DuckDBPyConnection:
    """Open the warehouse, creating the data folders and any missing tables."""
    for folder in (config.data_dir, config.outbound_dir, config.inbound_dir):
        folder.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(config.db_path))
    con.execute(files("encounter_pipeline.sql").joinpath("schema.sql").read_text())
    return con
