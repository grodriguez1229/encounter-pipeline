from encounter_pipeline.cli import run_all
from encounter_pipeline.config import Config
from encounter_pipeline.db import connect
from encounter_pipeline.trip import run


def test_trip_shows_files_and_responses_in_order(tmp_path, capsys):
    config = Config(data_dir=tmp_path / "data", n_members=150, n_trips=800, error_rate=0.1)
    run_all(config)
    with connect(config) as con:
        trip_id = con.execute(
            "SELECT trip_id FROM claim_status_history WHERE status_codes = 'A7:500:PW' LIMIT 1"
        ).fetchone()[0]
        capsys.readouterr()
        run(config, con, trip_id)
        out = capsys.readouterr().out
        kinds = [line.split()[2] for line in out.splitlines()[3:]]
        assert kinds[:3] == ["sent", "999", "277CA"]
        assert "Pickup ZIP invalid" in out
        assert "trips.pickup_zip" in out

        run(config, con, "T99999999")
        assert capsys.readouterr().out == "no trip T99999999\n"
