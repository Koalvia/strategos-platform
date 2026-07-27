"""Tests for the on-demand BOPA pipeline runner (scripts/run_bopa_pipeline.py).

The runner is a thin orchestrator: it calls the three domain tasks in order,
in-process. Here we replace those tasks with recorders so the test stays fast and
has no DB/Celery side effects, and assert the order of execution.
"""

import pytest

from scripts import run_bopa_pipeline


@pytest.mark.unit
def test_run_pipeline_calls_steps_in_order(monkeypatch):
    """sync -> analyze -> obligation-alerts, each once, in that order."""
    calls: list[str] = []

    monkeypatch.setattr(
        run_bopa_pipeline, "sync_bopa_daily", lambda: calls.append("sync")
    )
    monkeypatch.setattr(
        run_bopa_pipeline, "analyze_bopa_matches", lambda: calls.append("analyze")
    )
    monkeypatch.setattr(
        run_bopa_pipeline,
        "generate_obligation_alerts",
        lambda: calls.append("obligation_alerts"),
    )

    run_bopa_pipeline.run_pipeline()

    assert calls == ["sync", "analyze", "obligation_alerts"]
