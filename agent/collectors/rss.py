import hashlib
from datetime import datetime, timezone

import feedparser

from .base import JobIn


class RSSCollector:
    def __init__(self, platform: str, feeds: list[str]):
        self.platform = platform
        self.feeds = feeds

    def fetch(self) -> list[JobIn]:
        jobs = []
        for url in self.feeds:
            for e in feedparser.parse(url).entries:
                link = e.get("link", "")
                ext = e.get("id") or link or hashlib.sha1(e.get("title", "").encode()).hexdigest()
                posted = None
                if e.get("published_parsed"):
                    posted = datetime(*e.published_parsed[:6], tzinfo=timezone.utc)
                jobs.append(JobIn(platform=self.platform, external_id=str(ext)[:128], title=e.get("title", "")[:512],
                                  description=e.get("summary", ""), url=link, posted_at=posted))
        return jobs
