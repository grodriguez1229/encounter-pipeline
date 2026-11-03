import pytest

from encounter_pipeline import generate, report
from encounter_pipeline.cli import run_nights
from encounter_pipeline.config import Config
from encounter_pipeline.db import connect


@pytest.fixture(scope="module")
def reported(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("report")
    config = Config(data_dir=tmp / "data", n_members=200, n_trips=1200, error_rate=0.2)
    con = connect(config)
    generate.run(config, con)
    run_nights(config, con)
    report.run(config, con)
    return config, con


def test_completeness_matches_a_count_from_raw_tables(reported):
    _, con = reported
    # Straight from the raw tables, no models: completed trips that aren't final-rejected
    # duplicates, and how many of those were ever accepted.
    expected = con.execute("""
        SELECT count(*), count(*) FILTER (WHERE trip_id IN (
            SELECT trip_id FROM claim_status_history WHERE status = 'accepted'))
        FROM trips
        WHERE status = 'completed'
          AND trip_id NOT IN (SELECT trip_id FROM final_rejections WHERE status_codes = 'A3:54')
    """).fetchone()
    got = con.execute("""
        SELECT completed_trips, accepted FROM metric_completeness
        WHERE plan_id = 'All plans' AND trip_month IS NULL
    """).fetchone()
    assert got == expected


def test_plan_rows_add_up_to_the_total(reported):
    _, con = reported
    for metric, column in [("metric_completeness", "completed_trips"),
                           ("metric_accuracy", "submitted"),
                           ("metric_timeliness", "past_deadline")]:
        extra = "AND trip_month IS NULL" if metric == "metric_completeness" else ""
        plans, total = con.execute(f"""
            SELECT sum({column}) FILTER (WHERE plan_id <> 'All plans'),
                   max({column}) FILTER (WHERE plan_id = 'All plans')
            FROM {metric} WHERE true {extra}
        """).fetchone()
        assert plans == total, metric


def test_status_breakdown_adds_up(reported):
    _, con = reported
    bad = con.execute("""
        SELECT count(*) FROM metric_completeness
        WHERE completed_trips <> accepted + awaiting_response + rejected_open
                                 + rejected_final + not_submitted
    """).fetchone()[0]
    assert bad == 0


def test_report_file_has_every_section(reported):
    config, _ = reported
    text = (config.data_dir / "report.md").read_text()
    for title, _ in report.SECTIONS:
        assert f"## {title}" in text
