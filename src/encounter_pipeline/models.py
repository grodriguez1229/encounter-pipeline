"""A tiny stand-in for `dbt run`: build the SQL models in models/ as DuckDB views.

Each model is one SELECT in its own file, named after the file. Models point at each
other with {{ ref('model') }}, at raw tables with {{ source('raw', 'table') }}, and
at settings with {{ var('name') }}, the same syntax dbt uses, so the files can move
into a real dbt project later. This runner swaps those for plain names and values,
works out the build order from the refs, and creates each model as a view.
"""

import re
from graphlib import TopologicalSorter
from pathlib import Path

import duckdb

# models/ lives at the repo root, next to src/, the way a dbt project would have it.
MODELS_DIR = Path(__file__).resolve().parents[2] / "models"

REF = re.compile(r"""\{\{\s*ref\(\s*['"](\w+)['"]\s*\)\s*\}\}""")
SOURCE = re.compile(r"""\{\{\s*source\(\s*['"]\w+['"]\s*,\s*['"](\w+)['"]\s*\)\s*\}\}""")
VAR = re.compile(r"""\{\{\s*var\(\s*['"](\w+)['"]\s*\)\s*\}\}""")


def load_models(models_dir: Path) -> dict[str, str]:
    """Model name -> SQL, for every .sql file under models_dir."""
    return {path.stem: path.read_text() for path in sorted(models_dir.rglob("*.sql"))}


def build_order(models: dict[str, str]) -> list[str]:
    graph = {}
    for name, sql in models.items():
        refs = set(REF.findall(sql))
        if missing := refs - models.keys():
            raise ValueError(f"{name} refs unknown model(s): {', '.join(sorted(missing))}")
        graph[name] = refs
    return list(TopologicalSorter(graph).static_order())


def compile_sql(sql: str, variables: dict) -> str:
    # Vars go in as-is, unquoted, like dbt: the SQL adds quotes where it needs them.
    sql = REF.sub(lambda m: m.group(1), sql)
    sql = SOURCE.sub(lambda m: m.group(1), sql)
    return VAR.sub(lambda m: str(variables[m.group(1)]), sql)


def build_models(con: duckdb.DuckDBPyConnection, variables: dict,
                 models_dir: Path = MODELS_DIR) -> list[str]:
    """Create or replace every model as a view, dependencies first. Returns the order."""
    models = load_models(models_dir)
    order = build_order(models)
    for name in order:
        sql = compile_sql(models[name], variables).strip().rstrip(";")
        con.execute(f"CREATE OR REPLACE VIEW {name} AS {sql}")
    return order
