import pytest

from agent.catalog import get_catalog
from agent.db import Job, make_session_factory


@pytest.fixture
def catalog():
    return get_catalog()


@pytest.fixture
def session():
    with make_session_factory("sqlite://")() as s:
        yield s


def make_job(**kw) -> Job:
    defaults = dict(platform="upwork", external_id="x1", title="", description="", language="en",
                    budget_type="fixed", currency="USD", client_info={})
    defaults.update(kw)
    return Job(**defaults)
