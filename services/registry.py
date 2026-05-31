from services.tavily.service import TavilyService
from services.firecrawl.service import FirecrawlService
from services.exa.service import ExaService
from services.you.service import YouService
from services.serper.service import SerperService
from services.valyu.service import ValyuService

_REGISTRY = {
    "tavily": TavilyService,
    "firecrawl": FirecrawlService,
    "exa": ExaService,
    "you": YouService,
    "serper": SerperService,
    "valyu": ValyuService,
}


def register_service(name, service_class):
    _REGISTRY[name] = service_class


def get_service(name):
    cls = _REGISTRY.get(name)
    if cls is None:
        raise ValueError(f"Unknown service: {name!r}. Available: {list(_REGISTRY)}")
    return cls()


def list_services():
    return list(_REGISTRY.keys())
