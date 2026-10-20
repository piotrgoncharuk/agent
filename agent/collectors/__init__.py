from .base import Collector, JobIn
from .freelancehunt import FreelancehuntCollector
from .freelancer import FreelancerCollector
from .manual import parse_pasted
from .rss import RSSCollector

__all__ = ["Collector", "JobIn", "FreelancehuntCollector", "FreelancerCollector", "RSSCollector", "parse_pasted"]
