import re
from pathlib import Path

import pytest

from encounter_pipeline.cli import run_all
from encounter_pipeline.config import Config
from encounter_pipeline.db import connect
from encounter_pipeline.models import MODELS_DIR, load_models

ROOT = Path(__file__).resolve().parents[1]


def test_dbt_vars_match_config():
    text = (ROOT / "dbt_project.yml").read_text()
    config = Config()
    assert re.search(r'run_date: "(.+)"', text).group(1) == config.run_date.isoformat()
    assert int(re.search(r"submission_deadline_days: (\d+)", text).group(1)) == \
        config.submission_deadline_days


def model_rows(config: Config) -> dict[str, list]:
    with connect(config) as con:
        return {name: sorted(con.execute(f"SELECT * FROM {name}").fetchall(), key=repr)
                for name in load_models(MODELS_DIR)}


def test_dbt_build_matches_python_runner(tmp_path, monkeypatch):
    dbt_main = pytest.importorskip("dbt.cli.main", reason="dbt not installed (uv sync --group dbt)")
    config = Config(data_dir=tmp_path / "data", n_members=150, n_trips=800, error_rate=0.1)
    run_all(config)  # ends by building the models with the Python runner
    expected = model_rows(config)

    monkeypatch.setenv("ENCOUNTERS_DB", str(config.db_path))
    result = dbt_main.dbtRunner().invoke([
        "build", "--project-dir", str(ROOT), "--profiles-dir", str(ROOT),
        "--target-path", str(tmp_path / "target"), "--log-path", str(tmp_path / "logs"),
    ])
    assert result.success
    assert model_rows(config) == expected
