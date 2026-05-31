import os
import tempfile
import threading
import unittest
from services.base import BaseService


class ConcreteService(BaseService):
    name = "test_service"
    signup_url = "https://test.example.com"
    api_key_prefix = "test-"
    output_file = None
    headless_config_key = "TEST_HEADLESS"

    def _navigate_to_signup(self, page): pass
    def _fill_form(self, page, email, password): pass
    def _submit_form(self, page): pass
    def _verify_email(self, page, email): pass
    def _extract_api_key(self, page): return "test-key-123"


class TestBaseServiceContract(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False)
        self.tmp.close()
        ConcreteService.output_file = self.tmp.name

    def tearDown(self):
        os.unlink(self.tmp.name)

    def test_save_lock_is_class_attribute(self):
        assert '_SAVE_LOCK' in BaseService.__dict__, "_SAVE_LOCK must be in class dict"
        assert isinstance(BaseService._SAVE_LOCK, threading.Lock)

    def test_save_lock_shared_across_instances(self):
        svc1 = ConcreteService()
        svc2 = ConcreteService()
        assert svc1._SAVE_LOCK is svc2._SAVE_LOCK, "Lock must be shared"

    def test_save_result_writes_to_file(self):
        svc = ConcreteService()
        svc._save_result("test@test.com", "pass123", "test-key-abc")
        with open(self.tmp.name) as f:
            content = f.read()
        assert "test@test.com" in content
        assert "test-key-abc" in content

    def test_pre_register_hook_is_noop_by_default(self):
        svc = ConcreteService()
        svc._pre_register_hook()

    def test_cannot_instantiate_base_service(self):
        with self.assertRaises(TypeError):
            BaseService()
