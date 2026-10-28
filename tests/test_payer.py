from encounter_pipeline import build, generate, payer
from encounter_pipeline.config import Config
from encounter_pipeline.db import connect
from encounter_pipeline.x12.read_277ca import read_277ca
from encounter_pipeline.x12.read_837 import read_837
from encounter_pipeline.x12.read_999 import read_999

EXPECTED_STATUS = {
    "future_date": "187",
    "invalid_npi": "562",
    "bad_zip": "500",
    "not_eligible": "109",
    "duplicate": "54",
}


def responses(config):
    """trip_id -> status codes from every 277CA, and the claim IDs in files a 999 rejected."""
    rejected = set()
    for path in config.inbound_dir.glob("999_*"):
        for ack in read_999(path.read_text()).transactions:
            if not ack.accepted:
                rejected.add((ack.gs06, ack.st02))
    rejected_by_999 = set()
    for path in config.outbound_dir.glob("*.x12"):
        f = read_837(path.read_text())
        if (f.gs06, f.st02) in rejected:
            rejected_by_999 |= {c.trip_id for c in f.claims}
    statuses = {}
    for path in config.inbound_dir.glob("277CA_*"):
        for claim in read_277ca(path.read_text()).claims:
            statuses[claim.trip_id] = claim.status_codes[0].split(":")
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
