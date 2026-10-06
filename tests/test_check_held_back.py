"""The rules that decide whether a direct dependency is held back.

What the check exists to catch went unseen for weeks: ``pydantic-ai-slim[ag-ui]``
from 2.47 caps ``ag-ui-protocol<1`` while django-ag-ui requires ``>=1.0``, so
every unpinned resolve there stopped at 2.46 and a drift job passed with 2.54 on
PyPI. Each rule below would otherwise fail quietly in one direction or the
other: a rule that admits too much makes a scheduled job flap, and one that
admits too little is the green run again.

The real resolver and the real index are exercised by the ``action`` job in
``tests.yml``, which runs the action against the projects under
``tests/fixtures``. Here the index is a list of files shaped as PyPI's simple
API serves them in its JSON form (``api-version`` 1.4): ``yanked`` is ``false``
or the reason string, and ``upload-time`` carries microseconds and a ``Z``.
``_REAL_FILE`` is one entry copied verbatim from
``https://pypi.org/simple/ag-ui-protocol/``.
"""

from __future__ import annotations

import datetime
import io
import json
import runpy
import subprocess
import sys
import urllib.error
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
import tomli
from packaging.specifiers import SpecifierSet
from packaging.version import Version

from tests.helpers import SCRIPT, load_script

_NOW = datetime.datetime(2026, 10, 6, 12, tzinfo=datetime.timezone.utc)
_WEEK = datetime.timedelta(days=7)
_PY314 = Version("3.14.2")

_REAL_FILE: dict[str, Any] = {
    "core-metadata": False,
    "data-dist-info-metadata": False,
    "filename": "ag_ui_protocol-1.0.0.tar.gz",
    "hashes": {"sha256": "cfebecef2e7bc942cc8a52d908a4ea86a98f631d2ffdc6ec5812bb843eac74fb"},
    "provenance": None,
    "requires-python": ">=3.9",
    "size": 30759,
    "upload-time": "2026-09-17T18:31:19.448434Z",
    "url": "https://files.pythonhosted.org/packages/57/92/"
    "d88fdc7f4648dc38d3d54c595066bb3e63a4c091884ffb2f98272c33eef8/ag_ui_protocol-1.0.0.tar.gz",
    "yanked": False,
}


def _days_ago(days: float) -> str:
    when = _NOW - datetime.timedelta(days=days)
    return when.strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _wheel(
    version: str,
    days: float,
    *,
    requires_python: str | None = ">=3.10",
    yanked: bool | str = False,
    name: str = "pydantic_ai_slim",
) -> dict[str, Any]:
    return {
        **_REAL_FILE,
        "filename": f"{name}-{version}-py3-none-any.whl",
        "requires-python": requires_python,
        "upload-time": _days_ago(days),
        "yanked": yanked,
    }


def _classify(
    script: ModuleType, installed: str, files: list[dict[str, Any]], declared: str = ""
) -> Any:
    return script.classify(
        "pydantic-ai-slim",
        Version(installed),
        script.releases_from_index(files, _PY314),
        SpecifierSet(declared),
        _NOW,
        _WEEK,
    )


# -- classification -----------------------------------------------------------


def test_a_release_past_the_window_that_did_not_resolve_is_held(script: ModuleType) -> None:
    finding = _classify(
        script, "2.46.0", [_wheel("2.46.0", 30), _wheel("2.51.0", 10), _wheel("2.54.0", 1)]
    )

    assert finding.held
    assert not finding.fresh
    assert finding.settled.version == Version("2.51.0")
    assert finding.newest.version == Version("2.54.0")


def test_a_release_inside_the_window_is_reported_and_does_not_fail(script: ModuleType) -> None:
    # Published a day ago: the index this read and the one the resolver read
    # may disagree about it, which is the flap the window exists to absorb.
    finding = _classify(script, "2.46.0", [_wheel("2.46.0", 30), _wheel("2.54.0", 1)])

    assert not finding.held
    assert finding.fresh


def test_the_window_is_inclusive_at_exactly_its_length(script: ModuleType) -> None:
    finding = _classify(script, "2.46.0", [_wheel("2.46.0", 30), _wheel("2.54.0", 7)])

    assert finding.held


def test_the_newest_release_installed_is_current(script: ModuleType) -> None:
    finding = _classify(script, "2.54.0", [_wheel("2.46.0", 30), _wheel("2.54.0", 10)])

    assert not finding.held
    assert not finding.fresh


def test_a_declared_ceiling_is_honoured(script: ModuleType) -> None:
    # The way a hold is accepted on purpose: a ceiling the project wrote down.
    finding = _classify(script, "2.54.0", [_wheel("2.54.0", 30), _wheel("3.0.0", 10)], "<3")

    assert not finding.held
    assert not finding.fresh


def test_nothing_the_declared_window_admits_is_neither_held_nor_fresh(script: ModuleType) -> None:
    # Installed outside every release the index lists for this Python: there is
    # no newer release to be held below, and that must not read as one.
    finding = _classify(script, "2.54.0", [_wheel("2.54.0", 30)], ">=3")

    assert finding.newest is None
    assert not finding.held
    assert not finding.fresh


@pytest.mark.parametrize("declared", ["", ">=2.0.0rc1"])
def test_pre_and_dev_releases_are_not_newer(script: ModuleType, declared: str) -> None:
    # The second case is a floor that itself names a pre-release, which on its
    # own would make the specifier admit them.
    finding = _classify(
        script,
        "2.54.0",
        [_wheel("2.54.0", 30), _wheel("2.55.0b1", 10), _wheel("2.55.0.dev3", 10)],
        declared,
    )

    assert not finding.held
    assert not finding.fresh


@pytest.mark.parametrize("yanked", [True, "broken metadata"])
def test_a_yanked_release_is_not_newer(script: ModuleType, yanked: bool | str) -> None:
    finding = _classify(
        script, "2.54.0", [_wheel("2.54.0", 30), _wheel("2.55.0", 10, yanked=yanked)]
    )

    assert not finding.held


def test_a_release_that_has_not_reached_this_python_is_not_held(script: ModuleType) -> None:
    # A drift job runs on the newest Python, and nothing the project declares
    # holds back a release that does not install on it.
    finding = _classify(
        script, "2.54.0", [_wheel("2.54.0", 30), _wheel("2.55.0", 10, requires_python=">=3.15")]
    )

    assert not finding.held


@pytest.mark.parametrize("requires_python", [None, ""])
def test_a_file_with_no_python_requirement_admits_every_python(
    script: ModuleType, requires_python: str | None
) -> None:
    (release,) = script.releases_from_index(
        [_wheel("2.55.0", 10, requires_python=requires_python)], _PY314
    )

    assert release.version == Version("2.55.0")


def test_a_file_whose_python_requirement_does_not_parse_is_skipped(script: ModuleType) -> None:
    # Only ancient files carry one, and the resolver refuses them too.
    files = [_wheel("2.55.0", 10, requires_python=">=2.7.*")]

    assert script.releases_from_index(files, _PY314) == []


def test_a_release_counts_from_its_earliest_installable_file(script: ModuleType) -> None:
    # The sdist went up ten days ago and a wheel a day ago: a resolver could
    # have picked the release from the first of them. The wheel is listed
    # first and last, so the earliest wins in either order.
    sdist = {**_wheel("2.55.0", 10), "filename": "pydantic_ai_slim-2.55.0.tar.gz"}
    files = [_wheel("2.54.0", 30), _wheel("2.55.0", 1), sdist, _wheel("2.55.0", 2)]
    finding = _classify(script, "2.54.0", files)

    assert finding.held
    assert finding.settled.version == Version("2.55.0")
    assert finding.settled.published == _NOW - datetime.timedelta(days=10)


def test_the_index_entry_pypi_serves_parses(script: ModuleType) -> None:
    (release,) = script.releases_from_index([_REAL_FILE], _PY314)

    assert release.version == Version("1.0.0")
    assert release.published == datetime.datetime(
        2026, 9, 17, 18, 31, 19, 448434, tzinfo=datetime.timezone.utc
    )


def test_a_zip_sdist_is_a_release(script: ModuleType) -> None:
    (release,) = script.releases_from_index(
        [{**_REAL_FILE, "filename": "ag_ui_protocol-1.1.0.zip"}], _PY314
    )

    assert release.version == Version("1.1.0")


@pytest.mark.parametrize(
    "filename",
    [
        "ag-ui-protocol-0.1.win32.exe",
        "ag_ui_protocol-0.1-py2.7.egg",
        "not-a-valid-wheel.whl",
        "ag_ui_protocol-not.a.version.tar.gz",
    ],
)
def test_files_with_no_parseable_version_are_ignored(script: ModuleType, filename: str) -> None:
    assert script.releases_from_index([{**_REAL_FILE, "filename": filename}], _PY314) == []


def test_a_file_with_no_upload_time_counts_as_old(script: ModuleType) -> None:
    # A mirror that omits PEP 700 times can only make a hold more visible.
    undated = {**_wheel("2.55.0", 1), "upload-time": None}
    finding = _classify(script, "2.54.0", [_wheel("2.54.0", 30), undated])

    assert finding.held


# -- what the project declares ------------------------------------------------


def test_declared_bounds_intersect_every_occurrence_the_job_installs(script: ModuleType) -> None:
    pyproject = {
        "project": {
            "name": "Django-AG-UI",
            "dependencies": [
                "pydantic-ai-slim[ag-ui]>=2.37,<3",
                # A marker no interpreter running this suite satisfies.
                "tomli>=2; python_version < '3'",
            ],
            "optional-dependencies": {"anthropic": ["pydantic-ai-slim[anthropic]>=2.33,<3"]},
        },
        "dependency-groups": {
            # Including another group is skipped rather than followed, since
            # every group is walked anyway; and a group installing the project's
            # own extras names the project, which has no release to compare.
            "dev": [{"include-group": "lint"}, "django-ag-ui[anthropic]"],
            "lint": ["Ruff>=0.9"],
        },
        "tool": {
            "uv": {
                "constraint-dependencies": ["ruff<1", "not-direct<2"],
                "override-dependencies": ["also-not-direct>=1"],
            }
        },
    }

    bounds = script.declared_bounds(pyproject)

    assert bounds == {
        "pydantic-ai-slim": SpecifierSet(">=2.37,<3") & SpecifierSet(">=2.33,<3"),
        # Under its normalised name, with the uv constraint folded in as the
        # project's own ceiling. Neither uv table adds a name.
        "ruff": SpecifierSet(">=0.9,<1"),
    }


def test_an_override_replaces_what_the_project_declares(script: ModuleType) -> None:
    # uv resolves an overridden name against the override alone, so a ceiling
    # declared beside it no longer binds the resolve, and must not bind this.
    pyproject = {
        "project": {"name": "demo", "dependencies": ["pydantic-ai-slim>=2.37,<3"]},
        "tool": {"uv": {"override-dependencies": ["pydantic-ai-slim>=2.37"]}},
    }

    assert script.declared_bounds(pyproject) == {"pydantic-ai-slim": SpecifierSet(">=2.37")}


def test_a_requirement_that_does_not_parse_stops_the_check(script: ModuleType) -> None:
    with pytest.raises(script.CannotCheck, match="cannot parse requirement 'slim >= = 2'"):
        script.declared_bounds({"project": {"dependencies": ["slim >= = 2"]}})


def _dist_info(root: Path, name: str, version: str, *, direct_url: bool) -> None:
    info = root / f"{name.replace('-', '_')}-{version}.dist-info"
    info.mkdir()
    (info / "METADATA").write_text(f"Metadata-Version: 2.1\nName: {name}\nVersion: {version}\n")
    if direct_url:
        (info / "direct_url.json").write_text(
            '{"url": "file:///src", "dir_info": {"editable": true}}'
        )


def test_only_an_index_install_has_a_release_to_compare(
    script: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A path, URL or VCS install carries a PEP 610 ``direct_url.json`` and has
    # no index release to fall behind; the project itself, installed editable,
    # is the usual one.
    _dist_info(tmp_path, "from-the-index", "1.2.3", direct_url=False)
    _dist_info(tmp_path, "from-a-path", "4.5.6", direct_url=True)
    monkeypatch.syspath_prepend(str(tmp_path))

    assert script._installed("from-the-index") == Version("1.2.3")
    assert script._installed("from-a-path") is None
    assert script._installed("no-such-distribution-here") is None


# -- the index ----------------------------------------------------------------


class _Response(io.BytesIO):
    def __enter__(self) -> _Response:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


def test_the_index_is_read_from_the_simple_api_in_its_json_form(
    script: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The form uv itself reads, so the two answer from the same source.
    seen: list[Any] = []

    def urlopen(request: Any, timeout: float) -> _Response:
        seen.append(request)
        return _Response(json.dumps({"files": [_REAL_FILE]}).encode())

    monkeypatch.setattr(script.urllib.request, "urlopen", urlopen)

    assert script.fetch_files("ag-ui-protocol") == [_REAL_FILE]
    assert seen[0].full_url == "https://pypi.org/simple/ag-ui-protocol/"
    assert seen[0].get_header("Accept") == "application/vnd.pypi.simple.v1+json"


def test_a_transient_index_failure_is_retried(
    script: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    attempts: list[int] = []
    slept: list[float] = []

    def urlopen(request: Any, timeout: float) -> _Response:
        attempts.append(1)
        if len(attempts) < 3:
            raise TimeoutError("read timed out")
        return _Response(b'{"files": []}')

    monkeypatch.setattr(script.urllib.request, "urlopen", urlopen)
    monkeypatch.setattr(script.time, "sleep", slept.append)

    assert script.fetch_files("slim") == []
    assert slept == [1, 2]


def test_an_index_that_stays_unreadable_stops_the_check(
    script: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Retried and then fatal: a check that passes when it could not look is the
    # failure it exists to prevent.
    def urlopen(request: Any, timeout: float) -> _Response:
        raise urllib.error.URLError("name resolution failed")

    monkeypatch.setattr(script.urllib.request, "urlopen", urlopen)
    monkeypatch.setattr(script.time, "sleep", lambda seconds: None)

    with pytest.raises(script.CannotCheck, match="cannot read https://pypi.org/simple/slim/"):
        script.fetch_files("slim")


# -- asking the resolver why --------------------------------------------------


def _completed(returncode: int, stdout: str = "", stderr: str = "") -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess([], returncode, stdout=stdout, stderr=stderr)


def test_the_resolver_is_asked_for_exactly_the_release_it_did_not_reach(
    script: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # ``==`` rather than ``>=``: a range makes uv walk every newer release too,
    # which multiplies the derivation without adding a reason.
    calls: list[dict[str, Any]] = []
    derivation = "Because pydantic-ai-slim[ag-ui]==2.51.0 depends on ag-ui-protocol<1 ..."

    def run(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess:
        calls.append({"command": command, **kwargs})
        return _completed(1, stderr=f"  {derivation}\n")

    monkeypatch.setattr(script.subprocess, "run", run)

    assert script.ask_the_resolver(tmp_path, "pydantic-ai-slim", Version("2.51.0")) == derivation
    (call,) = calls
    assert call["command"] == [
        "uv",
        "lock",
        "--dry-run",
        "--upgrade-package",
        "pydantic-ai-slim==2.51.0",
    ]
    assert call["cwd"] == tmp_path
    # Colour codes would land verbatim in the issue the report becomes.
    assert call["env"]["NO_COLOR"] == "1"


def test_a_release_nothing_excludes_was_passed_over_for_another(
    script: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def run(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess:
        return _completed(0, stdout="Update other-package v2.0.0 -> v1.9.0", stderr="Resolved 9")

    monkeypatch.setattr(script.subprocess, "run", run)

    reason = script.ask_the_resolver(tmp_path, "slim", Version("2.51.0"))

    assert "no requirement excludes it" in reason
    assert reason.endswith("Resolved 9\nUpdate other-package v2.0.0 -> v1.9.0")


# -- output -------------------------------------------------------------------


def test_an_annotation_title_cannot_split_into_another_property(script: ModuleType) -> None:
    # A property value ends at a comma: unescaped, this title would be cut at
    # "Newer" and the rest read as a malformed second property. A message ends
    # at a newline, so an unescaped one shows only its first line.
    line = script._annotation("notice", "Newer, 100% inside: x", "a\r\nb 5%")

    assert line == "::notice title=Newer%2C 100%25 inside%3A x::a%0D%0Ab 5%25"


@pytest.mark.parametrize(("days", "text"), [(1, "1 day ago"), (2, "2 days ago")])
def test_an_age_reads_as_english(script: ModuleType, days: int, text: str) -> None:
    published = _NOW - datetime.timedelta(days=days)

    assert script._age(_NOW, published) == f"{published:%Y-%m-%d} ({text})"


def _pyproject(root: Path, *dependencies: str) -> None:
    listed = ", ".join(f'"{dependency}"' for dependency in dependencies)
    (root / "pyproject.toml").write_text(f'[project]\nname = "demo"\ndependencies = [{listed}]\n')


def _index(script: ModuleType, monkeypatch: pytest.MonkeyPatch, **listing: Any) -> None:
    """Serve ``listing[name] = (installed, files)`` in place of the environment and PyPI."""
    monkeypatch.setattr(script, "fetch_files", lambda name: listing[name.replace("-", "_")][1])
    monkeypatch.setattr(
        script, "_installed", lambda name: Version(listing[name.replace("-", "_")][0])
    )
    monkeypatch.setattr(script, "datetime", _FrozenDatetime)


class _FrozenDatetime:
    """The script's ``datetime`` module, with ``now`` fixed at ``_NOW``."""

    timedelta = datetime.timedelta
    timezone = datetime.timezone

    class datetime(datetime.datetime):
        @classmethod
        def now(cls, tz: Any = None) -> Any:
            return _NOW


def test_main_fails_on_a_hold_and_explains_it(
    script: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _pyproject(tmp_path, "pydantic-ai-slim[ag-ui]>=2.37,<3", "httpx")
    _index(
        script,
        monkeypatch,
        pydantic_ai_slim=("2.46.0", [_wheel("2.46.0", 30), _wheel("2.51.0", 10)]),
        httpx=("0.28.0", [_wheel("0.28.0", 30, name="httpx"), _wheel("0.29.0", 2, name="httpx")]),
    )
    asked: list[tuple[Path, str, Version]] = []

    def ask(root: Path, name: str, version: Version) -> str:
        asked.append((root, name, version))
        return "Because pydantic-ai-slim[ag-ui]==2.51.0 depends on ag-ui-protocol<1"

    monkeypatch.setattr(script, "ask_the_resolver", ask)
    summary = tmp_path / "summary.md"
    summary.write_text("earlier step\n")
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    report = tmp_path / "held-back.md"

    status = script.main(["--project", str(tmp_path), "--report", str(report)])

    assert status == 1
    assert asked == [(tmp_path, "pydantic-ai-slim", Version("2.51.0"))]
    text = report.read_text()
    assert "| `pydantic-ai-slim` | 2.46.0 | 2.51.0, 2026-09-26 (10 days ago) | 2.51.0 |" in text
    assert "depends on ag-ui-protocol<1" in text
    # Inside the window: listed, and not what failed the run.
    assert "- `httpx` 0.28.0: 0.29.0 published 2026-10-04 (2 days ago)" in text
    # Appended, never overwriting what earlier steps wrote to the summary.
    assert summary.read_text() == "earlier step\n" + text
    out = capsys.readouterr().out
    assert "::error title=Held back%3A pydantic-ai-slim::" in out
    assert "::notice title=Newer%2C inside the window%3A httpx::" in out


def test_main_can_skip_asking_the_resolver(
    script: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _pyproject(tmp_path, "pydantic-ai-slim>=2.37")
    _index(
        script,
        monkeypatch,
        pydantic_ai_slim=("2.46.0", [_wheel("2.46.0", 30), _wheel("2.51.0", 10)]),
    )
    report = tmp_path / "held-back.md"

    assert script.main(["--project", str(tmp_path), "--report", str(report), "--no-explain"]) == 1
    assert "(not asked: --no-explain)" in report.read_text()


def test_the_window_is_a_flag(
    script: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Two days old: inside the default week, outside a one-day window.
    _pyproject(tmp_path, "pydantic-ai-slim>=2.37")
    _index(
        script,
        monkeypatch,
        pydantic_ai_slim=("2.46.0", [_wheel("2.46.0", 30), _wheel("2.51.0", 2)]),
    )

    assert script.main(["--project", str(tmp_path), "--no-explain"]) == 0
    assert script.main(["--project", str(tmp_path), "--no-explain", "--min-age-days", "1"]) == 1


def test_main_passes_when_everything_is_current(
    script: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _pyproject(tmp_path, "pydantic-ai-slim>=2.37,<3", "not-installed-here")
    _index(script, monkeypatch, pydantic_ai_slim=("2.54.0", [_wheel("2.54.0", 30)]))
    monkeypatch.setattr(
        script,
        "_installed",
        lambda name: None if name == "not-installed-here" else Version("2.54.0"),
    )

    assert script.main(["--project", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert "Checked 1 direct dependency against PyPI on Python" in out
    assert "Every direct dependency resolved to its newest allowed release." in out
    assert "::" not in out


@pytest.mark.parametrize(
    ("setup", "message"),
    [
        # Nothing declared is installed, so nothing was compared, and a check
        # that could not look must not report that it found nothing.
        ("outside", "none of the direct dependencies is installed for"),
        ("no-manifest", "no pyproject.toml in"),
        ("bad-requirement", "cannot parse requirement"),
        ("index-down", "cannot read https://pypi.org/simple/pydantic-ai-slim/"),
    ],
)
def test_a_check_that_could_not_look_does_not_pass(
    script: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    setup: str,
    message: str,
) -> None:
    if setup != "no-manifest":
        _pyproject(tmp_path, "slim >= = 2" if setup == "bad-requirement" else "pydantic-ai-slim")
    monkeypatch.setattr(
        script, "_installed", lambda name: None if setup == "outside" else Version("1")
    )

    def unreadable(name: str) -> list[dict[str, Any]]:
        raise script.CannotCheck(f"cannot read https://pypi.org/simple/{name}/: down")

    monkeypatch.setattr(script, "fetch_files", unreadable)
    report = tmp_path / "held-back.md"

    assert script.main(["--project", str(tmp_path), "--report", str(report)]) == 2
    out = capsys.readouterr().out
    assert out.startswith("::error title=held-back-check cannot run::")
    assert message in out
    # No report, so a workflow reading it falls back to the run's log.
    assert not report.exists()


def test_run_as_a_script_it_exits_with_the_status(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(sys, "argv", [str(SCRIPT), "--project", str(tmp_path)])

    with pytest.raises(SystemExit) as exited:
        runpy.run_path(str(SCRIPT), run_name="__main__")

    assert exited.value.code == 2


# -- the environment it runs in -----------------------------------------------


def test_without_packaging_it_says_where_to_declare_it(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # The script runs in the consumer's environment, so a missing import is a
    # fact about that environment, and the message has to say so.
    for name in [name for name in sys.modules if name.split(".")[0] == "packaging"]:
        monkeypatch.setitem(sys.modules, name, None)

    with pytest.raises(SystemExit) as exited:
        load_script()

    assert exited.value.code == 2
    err = capsys.readouterr().err
    assert err.startswith("::error title=held-back-check cannot run::")
    assert "declare packaging there, and tomli on Python 3.10" in err


@pytest.mark.parametrize("stdlib", [True, False], ids=["tomllib", "tomli"])
def test_pyproject_is_read_with_tomllib_or_tomli(
    monkeypatch: pytest.MonkeyPatch, stdlib: bool
) -> None:
    # Both arms on every Python: ``tomllib`` is stood in by ``tomli`` where it
    # does not exist, and hidden where it does.
    monkeypatch.setitem(sys.modules, "tomllib", tomli if stdlib else None)

    assert load_script().tomllib is tomli
