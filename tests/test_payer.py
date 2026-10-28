from encounter_pipeline import build, generate, payer
from encounter_pipeline.config import Config
from encounter_pipeline.db import connect
from encounter_pipeline.x12.parser import parse

EXPECTED_STATUS = {
    "future_date": "187",
    "invalid_npi": "562",
    "bad_zip": "500",
    "not_eligible": "109",
    "duplicate": "54",
}


def responses(config):
    """trip_id -> STC01 from every 277CA, and the 837 claim IDs in files a 999 rejected."""
    statuses, rejected_by_999 = {}, set()
    rejected_groups = set()
    for path in config.inbound_dir.glob("999_*"):
        segs = parse(path.read_text())
        ak1 = next(s for s in segs if s.id == "AK1")
        if any(s.id == "AK9" and s[1] == "R" for s in segs):
            rejected_groups.add(ak1[2])
    for path in config.outbound_dir.glob("*.x12"):
        segs = parse(path.read_text())
        if segs[1][6] in rejected_groups:
            rejected_by_999 |= {s[1] for s in segs if s.id == "CLM"}
    for path in config.inbound_dir.glob("277CA_*"):
        trip_id = None
        for s in parse(path.read_text()):
            if s.id == "TRN" and s[1] == "2" and s[2].startswith("T"):
                trip_id = s[2]
            elif s.id == "STC" and trip_id:
                statuses[trip_id] = s.composite(1)
                trip_id = None
    return statuses, rejected_by_999


def test_payer_rejects_exactly_the_injected_problems(tmp_path):
    config = Config(data_dir=tmp_path / "data", n_members=150, n_trips=800, error_rate=0.2)
    with connect(config) as con:
        generate.run(config, con)
        build.run(config, con)
        payer.run(config, con)
        key = dict(con.execute("SELECT trip_id, problem FROM injected_problems").fetchall())

    statuses, rejected_by_999 = responses(config)
    assert statuses and rejected_by_999

    # Every 999 rejection is a file with a missing NPI in it, and it takes the
    # clean claims in that file down with it.
    missing_npi = {t for t, p in key.items() if p == "missing_npi"}
    assert missing_npi & rejected_by_999
    assert not missing_npi & set(statuses)
    assert rejected_by_999 - missing_npi, "expected innocent claims in rejected files"

    for trip_id, (category, code, *_) in statuses.items():
        problem = key.get(trip_id)
        if problem is None:
            assert (category, code) == ("A2", "20"), trip_id
        else:
            assert category in ("A3", "A7"), trip_id
            assert code == EXPECTED_STATUS[problem], (trip_id, problem)


def test_rerun_writes_nothing_new(tmp_path):
    config = Config(data_dir=tmp_path / "data", n_members=100, n_trips=300)
    with connect(config) as con:
        generate.run(config, con)
        build.run(config, con)
        payer.run(config, con)
        before = {p.name: p.read_text() for p in config.inbound_dir.iterdir()}
        payer.run(config, con)
        after = {p.name: p.read_text() for p in config.inbound_dir.iterdir()}
    assert before == after
    assert all(p.startswith(("999_", "277CA_")) for p in before)
