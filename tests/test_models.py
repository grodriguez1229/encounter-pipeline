import graphlib

import duckdb
import pytest

from encounter_pipeline.models import build_models, build_order, compile_sql


def write(dir, name, sql):
    (dir / f"{name}.sql").write_text(sql)


def test_builds_in_dependency_order_with_refs_sources_and_vars(tmp_path):
    (tmp_path / "staging").mkdir()
    (tmp_path / "marts").mkdir()
    # Named so alphabetical order would be wrong.
    write(tmp_path / "marts", "a_mart",
          "select n * {{ var('factor') }} as n from {{ ref('z_stg') }}")
    write(tmp_path / "staging", "z_stg", "select n from {{ source('raw', 'numbers') }} where n > 1")

    con = duckdb.connect()
    con.execute("create table numbers as select * from range(4) t(n)")
    assert build_models(con, {"factor": 10}, tmp_path) == ["z_stg", "a_mart"]
    assert con.execute("select n from a_mart order by n").fetchall() == [(20,), (30,)]


def test_string_vars_are_quoted():
    assert compile_sql("select {{ var('d') }}", {"d": "2026-06-30"}) == "select '2026-06-30'"


def test_unknown_ref_and_cycles_fail():
    with pytest.raises(ValueError, match="nope"):
        build_order({"a": "select * from {{ ref('nope') }}"})
    with pytest.raises(graphlib.CycleError):
        build_order({"a": "select * from {{ ref('b') }}", "b": "select * from {{ ref('a') }}"})
