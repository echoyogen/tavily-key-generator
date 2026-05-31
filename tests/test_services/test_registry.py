import unittest
from services.registry import get_service, list_services


class TestServiceRegistry(unittest.TestCase):
    def test_list_services_returns_six(self):
        services = list_services()
        assert len(services) == 6, f"Expected 6 services, got {len(services)}: {services}"

    def test_list_services_contains_expected(self):
        services = set(list_services())
        expected = {'tavily', 'firecrawl', 'exa', 'you', 'serper', 'valyu'}
        assert services == expected, f"Wrong services: {services}"

    def test_get_service_firecrawl(self):
        svc = get_service("firecrawl")
        assert svc.name == "firecrawl"

    def test_get_service_unknown_raises_value_error(self):
        with self.assertRaises(ValueError):
            get_service("unknown_service_xyz")

    def test_each_service_name_matches_key(self):
        for name in list_services():
            svc = get_service(name)
            assert svc.name == name, f"Service name mismatch: key={name}, svc.name={svc.name}"
