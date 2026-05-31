import sys
import types
from unittest.mock import MagicMock

_patchright_sync_api = types.ModuleType("patchright.sync_api")
_patchright_sync_api.sync_playwright = MagicMock()
sys.modules.setdefault("patchright", types.ModuleType("patchright"))
sys.modules.setdefault("patchright.sync_api", _patchright_sync_api)
