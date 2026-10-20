"""Freelancehunt API v2: https://apidocs.freelancehunt.com"""
import httpx

from .base import JobIn

# Ключевые навыки Freelancehunt можно передать как filter[skill_id]; пока — поиск по всем открытым проектам.
API = "https://api.freelancehunt.com/v2/projects"


class FreelancehuntCollector:
    platform = "freelancehunt"

    def __init__(self, token: str, pages: int = 3, http: httpx.Client | None = None):
        self.token = token
        self.pages = pages
        self.http = http or httpx.Client(timeout=20)

    def fetch(self) -> list[JobIn]:
        if not self.token:
            return []
        jobs = []
        for page in range(1, self.pages + 1):
            r = self.http.get(API, params={"page[number]": page},
                              headers={"Authorization": f"Bearer {self.token}"})
            r.raise_for_status()
            for item in r.json().get("data", []):
                a = item.get("attributes", {})
                budget = a.get("budget") or {}
                employer = a.get("employer") or {}
                jobs.append(JobIn(
                    platform=self.platform,
                    external_id=str(item["id"]),
                    title=a.get("name", ""),
                    description=a.get("description", "") or "",
                    url=(item.get("links") or {}).get("self", {}).get("web", ""),
                    budget_max=budget.get("amount"),
                    budget_type="fixed" if budget else "unknown",
                    currency=budget.get("currency", "UAH"),
                    client_info={"proposals_count": a.get("bid_count"),
                                 "rating": employer.get("rating")},
                ))
        return jobs
