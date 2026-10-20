from agent import crm
from agent.collectors import parse_pasted
from agent.db import Stage
from agent.lang import detect_language
from agent.pricing import quote
from agent.scoring import extract_quantity, score_rules
from tests.conftest import make_job


def test_detect_language():
    assert detect_language("Need help with logistic regression in R") == "en"
    assert detect_language("Potrzebuję analizy statystycznej do pracy magisterskiej, wyniki w SPSS") == "pl"
    assert detect_language("Нужен статистический анализ данных для диссертации, объём выборки 300") == "ru"
    assert detect_language("Потрібен статистичний аналіз даних для дисертації, їх обробка") == "ua"


def test_good_job_scores_high(catalog):
    job = make_job(
        title="Biostatistician for mixed model analysis in R",
        description="Longitudinal clinical trial data, need mixed model and logistic regression, "
                    "plus methods section and publication-ready figures.",
        budget_max=800, client_info={"payment_verified": True, "rating": 4.9, "total_spent": 5000,
                                     "hire_rate": 0.8, "proposals_count": 3})
    r = score_rules(job, catalog)
    assert r.service_id == "stat_analysis"
    assert r.total >= 80
    assert not r.red_flags


def test_red_flag_and_offtopic(catalog):
    cheat = make_job(title="Take my exam in statistics", description="online exam tomorrow, spss")
    assert score_rules(cheat, catalog).red_flags
    assert score_rules(cheat, catalog).total < 40
    off = make_job(title="Build a Shopify store", description="E-commerce website with payment gateway")
    r = score_rules(off, catalog)
    assert r.service_id is None and r.total <= 10


def test_polish_and_ukrainian_jobs_match(catalog):
    pl = make_job(language="pl", title="Metaanaliza do artykułu", description="Przegląd systematyczny wg PRISMA")
    assert score_rules(pl, catalog).service_id == "meta_analysis"
    ua = make_job(language="ua", title="Оформлення дисертації за ДСТУ", description="список літератури, 120 сторінок")
    assert score_rules(ua, catalog).service_id == "formatting"


def test_extract_quantity():
    assert extract_quantity("manuscript of 8,000 words") == (8000, "words")
    assert extract_quantity("около 50 страниц") == (50, "pages")
    assert extract_quantity("tekst 12.000 słów") == (12000, "words")
    assert extract_quantity("no size here") == (None, None)


def test_quote_per_word_and_budget(catalog):
    job = make_job(title="Scientific editing", description="Manuscript 6000 words, native english editing",
                   service_id="sci_editing")
    q = quote(job, catalog)
    assert q.price == 210  # 6000 × $35/1000
    job.budget_max = 190
    assert quote(job, catalog).price == 190  # в пределах 20% — берём бюджет клиента
    job.description += " urgent"
    job.budget_max = None
    assert quote(job, catalog).price == 275  # ×1.3 → 273 → округление до 5


def test_quote_converts_currency(catalog):
    job = make_job(platform="useme", title="Analiza statystyczna", description="SPSS, regresja",
                   service_id="stat_analysis", budget_max=1500, currency="PLN")
    q = quote(job, catalog)
    assert q.price == 405  # 1500 PLN ≈ $405 (≥80% от $400)


def test_parse_pasted():
    j = parse_pasted("upwork", "Meta-analysis for RCTs\nBudget: $300 - $500\nNeed forest plots", url="https://u/1")
    assert (j.title, j.budget_min, j.budget_max, j.currency) == ("Meta-analysis for RCTs", 300, 500, "USD")
    j2 = parse_pasted("useme", "Korekta artykułu\nBudżet: 400 zł")
    assert (j2.budget_max, j2.currency) == (400, "PLN")


def test_crm_transitions(session):
    job = make_job()
    session.add(job)
    crm.move(session, job, Stage.QUALIFIED)
    crm.move(session, job, Stage.DRAFTED)
    crm.move(session, job, Stage.SENT)
    try:
        crm.move(session, job, Stage.DELIVERED)
        assert False, "should fail"
    except crm.TransitionError:
        pass
    crm.move(session, job, Stage.REPLIED)
    crm.move(session, job, Stage.WON, contract_value=500)
    session.commit()
    assert job.contract_value == 500 and len(job.events) == 5
