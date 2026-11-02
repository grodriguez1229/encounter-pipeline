import importlib.util
from pathlib import Path

import pytest

DAG_FILE = Path(__file__).resolve().parents[1] / "dags" / "encounters_dag.py"


def test_dag_imports_with_tasks_in_order():
    pytest.importorskip("airflow", reason="Airflow not installed (uv run --with apache-airflow)")
    spec = importlib.util.spec_from_file_location("encounters_dag", DAG_FILE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    dag = module.encounters()
    order = [t.task_id for t in dag.topological_sort()]
    assert order == ["generate", "build", "simulate", "ingest",
                     "resubmit_1", "simulate_1", "ingest_1",
                     "resubmit_2", "simulate_2", "ingest_2",
                     "resubmit_3", "simulate_3", "ingest_3", "report"]
