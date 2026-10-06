"""The composite action's wiring, which no test of the script can see.

The ``action`` job in ``tests.yml`` runs it for real. These pin the properties
whose failure would not show there: an input spliced into shell, a sync that
re-resolves what a consumer installed, an output that disappears exactly when
the step fails.
"""

from __future__ import annotations

import re
from typing import Any

import pytest
import yaml

from tests.helpers import ROOT

_ACTION: dict[str, Any] = yaml.safe_load((ROOT / "action.yml").read_text(encoding="utf-8"))
_STEPS: list[dict[str, Any]] = _ACTION["runs"]["steps"]


def _check_step() -> dict[str, Any]:
    (step,) = [step for step in _STEPS if "check_held_back.py" in step.get("run", "")]
    return step


def test_it_is_a_composite_action() -> None:
    assert _ACTION["runs"]["using"] == "composite"


@pytest.mark.parametrize("index", range(len(_STEPS)))
def test_no_input_or_output_is_spliced_into_shell(index: int) -> None:
    # An expression inside ``run`` is substituted before the shell parses it,
    # so a value containing ``"; rm -rf`` would run. Through ``env`` it is data.
    assert "${{" not in _STEPS[index].get("run", "")


def test_every_input_reaches_the_steps() -> None:
    wired = "".join(
        str(step.get("env", {})) + str(step.get("working-directory", "")) for step in _STEPS
    )

    for name in _ACTION["inputs"]:
        assert f"inputs.{name} }}}}" in wired, name


def test_the_check_measures_what_the_consumer_installed() -> None:
    # A sync would re-resolve under uv's defaults -- no extras, the default
    # groups -- and the check would measure that instead of the job's install.
    command = _check_step()["run"]

    assert 'uv run --no-sync python "$GITHUB_ACTION_PATH/check_held_back.py"' in command
    assert "uv sync" not in command
    assert _check_step()["working-directory"] == "${{ inputs.working-directory }}"


def test_the_report_output_is_set_before_the_check_can_fail() -> None:
    # A consumer reads the report when the check failed, so the output has to
    # come from a step that ran before it, and the check has to write there.
    output = _ACTION["outputs"]["report"]["value"]
    (producer,) = re.findall(r"steps\.([\w-]+)\.outputs\.report", output)
    ids = [step.get("id") for step in _STEPS]

    assert ids.index(producer) < _STEPS.index(_check_step())
    assert _check_step()["env"]["REPORT"] == f"${{{{ steps.{producer}.outputs.report }}}}"


def test_a_stale_report_is_removed_before_the_check_runs() -> None:
    (paths,) = [step for step in _STEPS if step.get("id") == "paths"]

    assert 'rm -f "$report"' in paths["run"]


_PIN = re.compile(r"uses: (?P<action>[\w.-]+/[\w./-]+)@(?P<ref>\S+)(?P<comment>.*)")


@pytest.mark.parametrize(
    "path",
    sorted((ROOT / ".github" / "workflows").glob("*.yml")),
    ids=lambda path: path.name,
)
def test_every_action_is_pinned_to_a_commit_with_its_version(path: Any) -> None:
    # The SHA because a tag can be repointed; the comment because Dependabot
    # reads it to know which release the SHA is.
    pins = list(_PIN.finditer(path.read_text(encoding="utf-8")))

    assert pins
    for pin in pins:
        assert re.fullmatch(r"[0-9a-f]{40}", pin["ref"]), pin[0]
        assert re.fullmatch(r" # v\d+\.\d+\.\d+", pin["comment"]), pin[0]
