from __future__ import annotations

from types import ModuleType

import pytest

from tests.helpers import load_script


@pytest.fixture
def script(monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    # Never the step summary of the CI job running this suite.
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    return load_script()
