import concurrent.futures
import os
import tempfile
import unittest
from unittest.mock import patch

from mail.onlinemail import OnlineMailProvider


class OnlinemailProviderTests(unittest.TestCase):
    def setUp(self):
        self._tmpfiles = []

    def tearDown(self):
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

    def _make_provider(self, orders_file="", mode="file"):
        return OnlineMailProvider(
            api_url="https://api.online-disposablemail.com/api",
            api_key="",
            orders_file=orders_file,
            mode=mode,
        )

    def test_file_mode_creates_email_and_consumes_line(self):
        path = self._make_tmpfile("foo@gmail.com----order99\n")
        provider = self._make_provider(orders_file=path)

        result = provider.create_mailbox("exa")

        self.assertEqual(result, ("foo@gmail.com", ""))
        remaining = open(path, encoding="utf-8").read().strip()
        self.assertEqual(remaining, "")

    def test_file_mode_exhausted_raises_runtime_error(self):
        path = self._make_tmpfile("")
        provider = self._make_provider(orders_file=path)

        with self.assertRaises(RuntimeError) as ctx:
            provider.create_mailbox("exa")

        self.assertIn(path, str(ctx.exception))

    def test_file_mode_concurrent_safety(self):
        lines = "\n".join(f"email{i}@x.com----oid{i}" for i in range(1, 6)) + "\n"
        path = self._make_tmpfile(lines)
        provider = self._make_provider(orders_file=path)

        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
            futures = [executor.submit(provider.create_mailbox, "exa") for _ in range(5)]
            results = [f.result() for f in concurrent.futures.as_completed(futures)]

        emails = [r[0] for r in results]
        self.assertEqual(len(set(emails)), 5)

        remaining = open(path, encoding="utf-8").read().strip()
        self.assertEqual(remaining, "")

    def test_unsupported_service_raises(self):
        path = self._make_tmpfile("x@y.com----oid1\n")
        provider = self._make_provider(orders_file=path)

        with self.assertRaises(RuntimeError) as ctx:
            provider.create_mailbox("firecrawl")

        self.assertIn("firecrawl", str(ctx.exception))

    @patch("mail.onlinemail.requests.get")
    def test_api_mode_waiting_returns_empty_iter(self, mock_get):
        mock_get.return_value.raise_for_status.return_value = None
        mock_get.return_value.json.return_value = {
            "code": 401,
            "msg": "Waiting to receive verification code",
            "data": None,
        }
        provider = self._make_provider(mode="api")
        provider._mailbox_cache["test@e.com"] = {"order_id": "oid123"}

        result = list(provider.get_messages("test@e.com"))

        self.assertEqual(result, [])

    @patch("mail.onlinemail.requests.get")
    def test_api_mode_code_received_yields_message(self, mock_get):
        mock_get.return_value.raise_for_status.return_value = None
        mock_get.return_value.json.return_value = {
            "code": 200,
            "data": {"code": "987654", "content": "<html>test</html>"},
        }
        provider = self._make_provider(mode="api")
        provider._mailbox_cache["test2@e.com"] = {"order_id": "oid456"}

        result = list(provider.get_messages("test2@e.com"))

        self.assertEqual(
            result,
            [{"subject": "", "from": "", "html": "<html>test</html>", "text": "987654"}],
        )


if __name__ == "__main__":
    unittest.main()
