import concurrent.futures
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import mail_provider


class OnlinemailProviderTests(unittest.TestCase):
    def setUp(self):
        self._orig_provider = mail_provider.EMAIL_PROVIDER
        self._orig_mode = mail_provider.ONLINEMAIL_MODE
        self._orig_orders_file = mail_provider.ONLINEMAIL_ORDERS_FILE
        mail_provider.EMAIL_PROVIDER = "onlinemail"
        mail_provider.ONLINEMAIL_MODE = "file"
        mail_provider._ONLINEMAIL_MAILBOX_CACHE.clear()
        self._tmpfiles = []

    def tearDown(self):
        mail_provider.EMAIL_PROVIDER = self._orig_provider
        mail_provider.ONLINEMAIL_MODE = self._orig_mode
        mail_provider.ONLINEMAIL_ORDERS_FILE = self._orig_orders_file
        mail_provider._ONLINEMAIL_MAILBOX_CACHE.clear()
        for path in self._tmpfiles:
            try:
                os.unlink(path)
            except OSError:
                pass

    def _make_tmpfile(self, content):
        f = tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False)
        f.write(content)
        f.close()
        self._tmpfiles.append(f.name)
        return f.name

    def test_file_mode_creates_email_and_consumes_line(self):
        path = self._make_tmpfile("foo@gmail.com----order99\n")
        mail_provider.ONLINEMAIL_ORDERS_FILE = path

        result = mail_provider.create_email("exa")

        self.assertEqual(result, ("foo@gmail.com", ""))
        remaining = open(path, encoding="utf-8").read().strip()
        self.assertEqual(remaining, "")

    def test_file_mode_exhausted_raises_runtime_error(self):
        path = self._make_tmpfile("")
        mail_provider.ONLINEMAIL_ORDERS_FILE = path

        with self.assertRaises(RuntimeError) as ctx:
            mail_provider._create_onlinemail_mailbox("exa")

        self.assertIn(path, str(ctx.exception))

    def test_file_mode_concurrent_safety(self):
        lines = "\n".join(f"email{i}@x.com----oid{i}" for i in range(1, 6)) + "\n"
        path = self._make_tmpfile(lines)
        mail_provider.ONLINEMAIL_ORDERS_FILE = path

        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
            futures = [executor.submit(mail_provider.create_email, "exa") for _ in range(5)]
            results = [f.result() for f in concurrent.futures.as_completed(futures)]

        emails = [r[0] for r in results]
        self.assertEqual(len(set(emails)), 5)

        remaining = open(path, encoding="utf-8").read().strip()
        self.assertEqual(remaining, "")

    def test_unsupported_service_raises(self):
        mail_provider.EMAIL_PROVIDER = "onlinemail"

        with self.assertRaises(RuntimeError) as ctx:
            mail_provider._create_onlinemail_mailbox("firecrawl")

        self.assertIn("firecrawl", str(ctx.exception))

    @patch("mail_provider.std_requests.get")
    def test_api_mode_waiting_returns_empty_iter(self, mock_get):
        mock_get.return_value.raise_for_status.return_value = None
        mock_get.return_value.json.return_value = {
            "code": 401,
            "msg": "Waiting to receive verification code",
            "data": None,
        }
        mail_provider._ONLINEMAIL_MAILBOX_CACHE["test@e.com"] = {"order_id": "oid123"}

        result = list(mail_provider._onlinemail_iter_messages("test@e.com"))

        self.assertEqual(result, [])

    @patch("mail_provider.std_requests.get")
    def test_api_mode_code_received_yields_message(self, mock_get):
        mock_get.return_value.raise_for_status.return_value = None
        mock_get.return_value.json.return_value = {
            "code": 200,
            "data": {"code": "987654", "content": "<html>test</html>"},
        }
        mail_provider._ONLINEMAIL_MAILBOX_CACHE["test2@e.com"] = {"order_id": "oid456"}

        result = list(mail_provider._onlinemail_iter_messages("test2@e.com"))

        self.assertEqual(
            result,
            [{"subject": "", "from": "", "html": "<html>test</html>", "text": "987654"}],
        )


if __name__ == "__main__":
    unittest.main()
