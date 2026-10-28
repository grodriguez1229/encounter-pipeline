from encounter_pipeline import generate
from encounter_pipeline.config import Config
from encounter_pipeline.db import connect
from encounter_pipeline.npi import is_valid_npi

TABLES = ["plans", "members", "vendors"]


def snapshot(con):
    return {t: con.execute(f"SELECT * FROM {t} ORDER BY 1").fetchall() for t in TABLES}


def test_same_seed_same_data_and_rerun_is_idempotent(tmp_path):
    config = Config(data_dir=tmp_path / "data", n_members=50, n_vendors=5)
    with connect(config) as con:
        generate.run(config, con)
        first = snapshot(con)
        generate.run(config, con)
        assert snapshot(con) == first

    other = Config(data_dir=tmp_path / "other", n_members=50, n_vendors=5)
    with connect(other) as con:
        generate.run(other, con)
        assert snapshot(con) == first


def test_vendor_npis_are_valid_and_fake(tmp_path):
    config = Config(data_dir=tmp_path / "data")
    with connect(config) as con:
        generate.run(config, con)
        npis = [r[0] for r in con.execute("SELECT npi FROM vendors").fetchall()]
    assert npis and all(is_valid_npi(n) and n.startswith("9") for n in npis)
