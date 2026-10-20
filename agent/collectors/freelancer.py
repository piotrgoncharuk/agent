"""Freelancer.com API: https://developers.freelancer.com"""
import httpx

from .base import JobIn

API = "https://www.freelancer.com/api/projects/0.1/projects/active/"
QUERIES = ["statistics", "spss", "meta-analysis", "biostatistics", "scientific editing", "data analysis R"]


class FreelancerCollector:
    platform = "freelancer"

    def __init__(self, token: str = "", queries: list[str] | None = None, http: httpx.Client | None = None):
        self.token = token
        self.queries = queries or QUERIES
        self.http = http or httpx.Client(timeout=20)

    def fetch(self) -> list[JobIn]:
        headers = {"freelancer-oauth-v1": self.token} if self.token else {}
        seen, jobs = set(), []
        for q in self.queries:
            r = self.http.get(API, headers=headers, params={"query": q, "limit": 30, "full_description": "true",
                                                           "job_details": "true"})
            r.raise_for_status()
            for p in r.json().get("result", {}).get("projects", []):
                if p["id"] in seen:
                    continue
                seen.add(p["id"])
                budget = p.get("budget") or {}
                jobs.append(JobIn(
                    platform=self.platform,
                    external_id=str(p["id"]),
                    title=p.get("title", ""),
                    description=p.get("description") or p.get("preview_description", ""),
                    url=f"https://www.freelancer.com/projects/{p.get('seo_url', p['id'])}",
                    budget_min=budget.get("minimum"),
                    budget_max=budget.get("maximum"),
                    budget_type=p.get("type", "unknown"),
                    currency=(p.get("currency") or {}).get("code", "USD"),
                    client_info={"proposals_count": (p.get("bid_stats") or {}).get("bid_count")},
                ))
        return jobs
