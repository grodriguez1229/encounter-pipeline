from decimal import Decimal

from encounter_pipeline import build, generate
from encounter_pipeline.config import Config
from encounter_pipeline.db import connect
from encounter_pipeline.x12.read_837 import read_837


def test_round_trip_built_files_parse_back_to_the_same_claims(tmp_path):
    config = Config(data_dir=tmp_path / "data", n_members=100, n_trips=600, error_rate=0.2)
    with connect(config) as con:
        generate.run(config, con)
        build.run(config, con)
        submissions = con.execute(
            "SELECT submission_id, file_name, isa13, gs06, st02 FROM submissions"
        ).fetchall()
        expected = {
            row[0]: row[1:]
            for row in con.execute("""
                SELECT sc.trip_id, sc.charge, sc.frequency_code, sc.line_count,
                       t.member_id, v.npi, p.payer_id, t.trip_date, t.loaded_miles,
                       t.pickup_zip, t.dropoff_zip,
                       t.origin_type || t.destination_type
                FROM submission_claims sc
                JOIN trips t USING (trip_id)
                JOIN vendors v USING (vendor_id)
                JOIN members m USING (member_id)
                JOIN plans p ON p.plan_id = m.plan_id
            """).fetchall()
        }

    seen = set()
    for _, file_name, isa13, gs06, st02 in submissions:
        parsed = read_837((config.outbound_dir / file_name).read_text())
        assert (parsed.isa13, parsed.gs06, parsed.st02) == (isa13, gs06, st02)
        for c in parsed.claims:
            (charge, freq, line_count, member_id, npi, payer_id, trip_date, miles,
             pickup_zip, dropoff_zip, modifier) = expected[c.trip_id]
            assert c.charge == charge
            assert c.frequency_code == freq
            assert len(c.lines) == line_count
            assert sum(line.charge for line in c.lines) == charge
            assert c.member_id == member_id
            assert c.billing_npi == npi        # None for the missing-NPI vendor
            assert c.payer_id == payer_id
            assert (c.pickup_zip, c.dropoff_zip) == (pickup_zip, dropoff_zip)
            assert all(line.service_date == trip_date for line in c.lines)
            assert all(line.modifier == modifier for line in c.lines)
            assert c.lines[1].units == Decimal(miles)
            seen.add(c.trip_id)
    assert seen == set(expected)
