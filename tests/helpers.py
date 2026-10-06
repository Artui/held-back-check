from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "check_held_back.py"


def load_script() -> ModuleType:
    """Execute the script as a fresh module.

    By path, because that is how the action runs it: it is not a package, and
    a consumer never imports it. Fresh each time, so a test that hides an
    import from it sees the module's import guard run again.
    """
    spec = importlib.util.spec_from_file_location("check_held_back", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # Registered before it runs: ``dataclass`` resolves string annotations
    # through ``sys.modules[cls.__module__]``.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module
