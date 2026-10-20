from types import SimpleNamespace

from fastapi.testclient import TestClient

from agent import api, pipeline, reports
from agent.proposals import ProposalDraft
from agent.settings import Settings


def _fake_parse(output):
    def parse(**kwargs):
        assert kwargs["model"] == "claude-sonnet-5-5"
        assert kwargs["fallbacks"] == "default"
        return SimpleNamespace(stop_reason="end_turn", stop_details=None, parsed_output=output)
    return SimpleNamespace(beta=SimpleNamespace(messages=SimpleNamespace(parse=parse)))


def test_api_end_to_end(monkeypatch, tmp_path):
    draft = ProposalDraft(text="Hi! I can run the mixed model…", questions=["How many timepoints?"],
                          estimated_days=4, decline=False, decline_reason="")
    monkeypatch.setattr("agent.llm.get_client", lambda: _fake_parse(draft))
    monkeypatch.setattr(api, "_factory", None)
    monkeypatch.setattr("agent.db.get_settings", lambda: Settings(database_url=f"sqlite:///{tmp_path}/t.db"))
    c = TestClient(api.app)

    text = ("Biostatistician needed: mixed model in R\nBudget: $600\n"
            "Longitudinal clinical trial, logistic regression, methods section and figures.")
    r = c.post("/jobs/import", json={"platform": "upwork", "text": text, "url": "https://upwork.com/j/1"})
    assert r.status_code == 200, r.text
    job = r.json()
    assert job["stage"] == "qualified" and job["service_id"] == "stat_analysis"
    assert c.post("/jobs/import", json={"platform": "upwork", "text": text, "url": "https://upwork.com/j/1"}).status_code == 409

    d = c.post(f"/jobs/{job['id']}/draft").json()
    assert d["questions"] == ["How many timepoints?"] and d["price"] == 460  # бюджет $600 выше расчёта $400 → 400×1.15

    for stage, extra in [("sent", {}), ("replied", {}), ("won", {"contract_value": 600})]:
        assert c.post(f"/jobs/{job['id']}/stage", json={"stage": stage, **extra}).status_code == 200
    assert c.post(f"/jobs/{job['id']}/stage", json={"stage": "new"}).status_code == 400

    s = c.get("/reports/summary").json()
    assert s["won_total"] == 1 and s["revenue_usd"] == 600 and s["conversion"] == 1.0
    assert "Выручка: $600" in reports.format_text(s)


def test_collection_isolates_failing_source(session, catalog, monkeypatch):
    class Broken:
        platform = "broken"
        def fetch(self):
            raise RuntimeError("boom")

    class Ok:
        platform = "freelancer"
        def fetch(self):
            return [pipeline.JobIn(platform="freelancer", external_id="1", title="SPSS regression analysis",
                                   description="ANOVA and regression for thesis", budget_max=300)]

    monkeypatch.setattr(pipeline, "build_collectors", lambda s, c: [Broken(), Ok()])
    stats = pipeline.run_collection(session, catalog, Settings())
    assert stats["new"] == 1 and stats["errors"] == ["broken: boom"]
    assert pipeline.run_collection(session, catalog, Settings())["new"] == 0  # дедупликация
