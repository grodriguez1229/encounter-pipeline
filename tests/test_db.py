from encounter_pipeline.config import Config
from encounter_pipeline.db import connect


def test_connect_creates_folders_and_schema(tmp_path):
    config = Config(data_dir=tmp_path / "data")
    con = connect(config)
    assert config.outbound_dir.is_dir()
    assert config.inbound_dir.is_dir()
    tables = {row[0] for row in con.execute("SHOW TABLES").fetchall()}
    assert "control_numbers" in tables
    con.close()
    # Reconnecting to an existing warehouse doesn't fail.
    connect(config).close()
