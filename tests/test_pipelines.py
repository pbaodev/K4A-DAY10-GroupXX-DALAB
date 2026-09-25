from __future__ import annotations

from dataclasses import fields, replace
from pathlib import Path
import shutil

import pytest

from core.config import load_settings
from core.utils import read_json, write_json
from pipelines import corruption_flow, phase1
from retrieval import agent as agent_module
from retrieval.agent import run_agent_demo


class _FakeEmbeddings:
    def __init__(self, model_name: str):
        self.model_name = model_name

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [[float(len(text) % 7 + 1), 0.2, 0.3] for text in texts]

    def embed_query(self, text: str) -> list[float]:
        return [1.0, 0.2, 0.3]


@pytest.fixture
def pipeline_settings(tmp_path, monkeypatch):
    """Every data path redirected into tmp_path, raw snapshot copied, mock LLM, fake embeddings."""
    base = load_settings()
    data = base.paths.project_dir / "data"
    redirected = {
        field.name: tmp_path / Path(getattr(base.paths, field.name)).relative_to(data)
        for field in fields(base.paths)
        if Path(getattr(base.paths, field.name)).is_relative_to(data)
    }
    settings = replace(
        base,
        llm_provider="mock",
        refresh_source=False,
        refresh_test_set=False,
        paths=replace(base.paths, project_dir=tmp_path, **redirected),
    )
    for name in ("raw_api_response", "raw_records_json"):
        target = getattr(settings.paths, name)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(getattr(base.paths, name), target)

    monkeypatch.setattr("retrieval.index.MiniLMEmbeddings", _FakeEmbeddings)
    monkeypatch.setattr(phase1, "load_settings", lambda: settings)
    monkeypatch.setattr(corruption_flow, "load_settings", lambda: settings)
    return settings


def test_phase1_then_corruption_flow_write_all_artifacts(pipeline_settings, capsys):
    paths = pipeline_settings.paths
    phase1.main()
    for path in (
        paths.clean_csv,
        paths.clean_json,
        paths.eval_testset,
        paths.baseline_metrics,
        paths.baseline_report,
        paths.baseline_quality_report,
        paths.freshness_report,
        paths.demo_answers,
    ):
        assert path.exists(), path
    assert len(read_json(paths.eval_testset)) == 10
    assert all(row["status"] == "skipped" for row in read_json(paths.demo_answers))

    phase1.main()
    assert "Reusing test_set.json" in capsys.readouterr().out

    corruption_flow.main()
    for path in (
        paths.corruption_log,
        paths.corrupted_clean_json,
        paths.corrupted_metrics,
        paths.repaired_metrics,
        paths.corrupted_quality_report,
        paths.comparison_report,
    ):
        assert path.exists(), path
    assert read_json(paths.corrupted_quality_report)["success"] is False
    assert read_json(paths.quality_dir / "repaired_quality_report.json")["success"] is True
    assert read_json(paths.quality_dir / "freshness_report_corrupted.json")["is_fresh"] is False
    report = paths.comparison_report.read_text(encoding="utf-8")
    assert "Baseline" in report and "Corrupted" in report and "Repaired" in report
    assert "WARNING: quality gate would block" in capsys.readouterr().out


def test_phase1_rebuilds_a_test_set_that_points_at_unknown_papers(pipeline_settings, capsys):
    write_json(
        pipeline_settings.paths.eval_testset,
        [{"id": "eval_001", "question_type": "date", "question": "q", "ground_truth": "x", "ground_truth_doc_ids": ["10.0/gone"]}],
    )
    phase1.main()
    assert "rebuilding" in capsys.readouterr().out
    assert len(read_json(pipeline_settings.paths.eval_testset)) == 10


def test_phase1_stops_when_the_quality_gate_fails(pipeline_settings, monkeypatch):
    failing = {
        "success": False,
        "expectations": [{"expectation": "expect_column_values_to_be_unique", "column": "paper_id", "success": False}],
    }
    monkeypatch.setattr(phase1, "run_data_quality_checks", lambda *_args: failing)
    with pytest.raises(SystemExit, match="failed GX checks"):
        phase1.main()
    assert not pipeline_settings.paths.baseline_metrics.exists()


def test_phase1_warns_when_data_is_stale(pipeline_settings, monkeypatch, capsys):
    stale = {"stale_ratio": 0.9, "is_fresh": False}
    monkeypatch.setattr(phase1, "build_freshness_report", lambda *_args: stale)
    phase1.main()
    assert "WARNING: stale ratio exceeds the SLA" in capsys.readouterr().out


def test_corruption_flow_requires_phase1_artifacts(pipeline_settings):
    with pytest.raises(SystemExit, match="run_phase1.py"):
        corruption_flow.main()


def test_run_agent_demo_records_ok_and_skip_reasons(settings, tmp_path, monkeypatch):
    output = tmp_path / "demo.json"

    class _Message:
        content = "agent answer"

    class _Agent:
        def invoke(self, payload):
            if "boom" in payload["messages"][0]["content"]:
                raise NotImplementedError()
            return {"messages": [_Message()]}

    monkeypatch.setattr(agent_module, "build_agent", lambda *_args: _Agent())
    rows = run_agent_demo(settings, None, ["fine question", "boom question"], output)
    assert [row["status"] for row in rows] == ["ok", "skipped"]
    assert rows[0]["answer"] == "agent answer"
    assert rows[1]["reason"] == "NotImplementedError: the mock LLM cannot call tools"
    assert read_json(output) == rows

    def _cannot_build(*_args):
        raise RuntimeError("missing key")

    monkeypatch.setattr(agent_module, "build_agent", _cannot_build)
    skipped = run_agent_demo(replace(settings, llm_provider="gemini"), None, ["q"], output)
    assert skipped[0]["status"] == "skipped"
    assert skipped[0]["reason"] == "Agent unavailable: RuntimeError: missing key"
