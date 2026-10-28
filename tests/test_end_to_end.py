from encounter_pipeline.cli import run_all
from encounter_pipeline.config import Config
from encounter_pipeline.db import connect


def snapshot(config: Config) -> dict[str, str]:
    """Every X12 file and the report, by relative path."""
    files = {}
    for folder in (config.outbound_dir, config.inbound_dir):
        for path in folder.iterdir():
            files[f"{folder.name}/{path.name}"] = path.read_text()
    files["report.md"] = (config.data_dir / "report.md").read_text()
    return files


def small(data_dir, seed=7):
    return Config(data_dir=data_dir, seed=seed, n_members=150, n_trips=800, error_rate=0.1)


def test_same_seed_gives_identical_files_and_metrics(tmp_path):
    first, second = small(tmp_path / "a"), small(tmp_path / "b")
    run_all(first)
    run_all(second)
    a, b = snapshot(first), snapshot(second)
    assert a.keys() == b.keys()
    assert [name for name in a if a[name] != b[name]] == []


def test_different_seed_gives_different_data(tmp_path):
    run_all(small(tmp_path / "a", seed=1))
    run_all(small(tmp_path / "b", seed=2))
    assert snapshot(small(tmp_path / "a", 1))["report.md"] != \
        snapshot(small(tmp_path / "b", 2))["report.md"]


def test_run_all_starts_clean_and_settles(tmp_path):
    config = small(tmp_path / "data")
    run_all(config)
    first = snapshot(config)
    (config.outbound_dir / "leftover.x12").write_text("stale")
    run_all(config)
    assert snapshot(config) == first
    with connect(config) as con:
        # Settled: no rejection is left open for a reason other than timing.
        open_rejections = con.execute(
            "SELECT count(*) FROM fct_encounter WHERE current_status = 'rejected_open' "
            "AND first_submitted_at < DATE '2026-06-20'"
        ).fetchone()[0]
    assert open_rejections == 0
