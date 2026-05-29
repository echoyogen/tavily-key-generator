import importlib
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import cli.bootstrap as bootstrap


def _import_run_with_stubbed_check_call():
    commands = []

    def fake_check_call(cmd, *args, **kwargs):
        commands.append(list(cmd))
        return 0

    sys.modules.pop("run", None)
    with (
        patch("os.execv"),
        patch("subprocess.check_call", side_effect=fake_check_call),
        patch("cli.bootstrap._get_venv_python", return_value="/fake/venv/bin/python"),
    ):
        module = importlib.import_module("run")
    return module, commands


class RunBootstrapTests(unittest.TestCase):
    def tearDown(self) -> None:
        sys.modules.pop("run", None)

    def test_importing_run_does_not_install_browsers(self) -> None:
        _, commands = _import_run_with_stubbed_check_call()

        browser_commands = [
            command
            for command in commands
            if command[:3] == [sys.executable, "-m", "patchright"]
        ]

        self.assertEqual(browser_commands, [])

    def test_ensure_service_browsers_uses_patchright_for_exa(self) -> None:
        with patch.object(bootstrap, "_ensure_patchright_browser") as ensure_patchright:
            bootstrap._ensure_service_browsers("exa")
        ensure_patchright.assert_called_once_with()

    def test_ensure_service_browsers_uses_patchright_for_tavily(self) -> None:
        with patch.object(bootstrap, "_ensure_patchright_browser") as ensure_patchright:
            bootstrap._ensure_service_browsers("tavily")
        ensure_patchright.assert_called_once_with()

    def test_ensure_service_browsers_uses_patchright_for_you(self) -> None:
        with patch.object(bootstrap, "_ensure_patchright_browser") as ensure_patchright:
            bootstrap._ensure_service_browsers("you")
        ensure_patchright.assert_called_once_with()

    def test_patchright_browser_ready_uses_expected_install_location(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            expected_path = Path(temp_dir, "chromium-1208")
            expected_path.mkdir()
            completed = subprocess.CompletedProcess(
                args=[sys.executable, "-m", "patchright", "install", "--dry-run", "chromium"],
                returncode=0,
                stdout=f"""
Playwright version: 1.58.2
Chrome for Testing 145.0.7632.6 (playwright chromium v1208)
  Install location:    {expected_path}
""".strip(),
                stderr="",
            )

            with patch.object(bootstrap.subprocess, "run", return_value=completed) as mock_run:
                self.assertTrue(bootstrap._patchright_browser_ready())

        mock_run.assert_called_once()

    def test_patchright_browser_ready_ignores_unrelated_installs(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            unrelated_root = Path(temp_dir, "cache")
            unrelated_root.mkdir()
            Path(unrelated_root, "chromium-1208").mkdir()
            missing_expected_path = Path(temp_dir, "expected", "chromium-9999")
            completed = subprocess.CompletedProcess(
                args=[sys.executable, "-m", "patchright", "install", "--dry-run", "chromium"],
                returncode=0,
                stdout=f"""
Chrome for Testing 145.0.7632.6 (playwright chromium v9999)
  Install location:    {missing_expected_path}
""".strip(),
                stderr="",
            )

            with (
                patch.object(bootstrap.subprocess, "run", return_value=completed),
                patch.object(bootstrap, "_default_patchright_browser_root", return_value=str(unrelated_root)),
            ):
                self.assertFalse(bootstrap._patchright_browser_ready())

    def test_patchright_browser_ready_falls_back_to_cache_dir(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            Path(temp_dir, "chromium-1208").mkdir()
            completed = subprocess.CompletedProcess(
                args=[sys.executable, "-m", "patchright", "install", "--list"],
                returncode=1,
                stdout="",
                stderr="unsupported",
            )

            with (
                patch.object(bootstrap.subprocess, "run", return_value=completed),
                patch.object(bootstrap, "_default_patchright_browser_root", return_value=temp_dir),
            ):
                self.assertTrue(bootstrap._patchright_browser_ready())


if __name__ == "__main__":
    unittest.main()
