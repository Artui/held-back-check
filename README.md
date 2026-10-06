# held-back-check

A GitHub Action for a scheduled drift job: it fails when an unpinned `uv`
resolve holds a **direct** dependency below its newest release, and it names
the requirement that holds it.

## Why

A drift job resolves the newest versions `pyproject.toml` allows
(`uv lock --upgrade`) and runs the suite, so an upstream release that breaks the
project is found on a schedule rather than by a user. It answers "does the
newest *resolvable* set pass". It does not answer whether the newest resolvable
set is the newest *released* one.

A resolver that cannot reach a release does not fail. It backs off to an older
version that does resolve, logs an ordinary `Updated` line, and the suite passes
against something nobody chose. From 2.47, `pydantic-ai-slim[ag-ui]` declares
`ag-ui-protocol<1`. django-ag-ui requires `ag-ui-protocol>=1.0`, so its unpinned
resolve stopped at slim 2.46, and the drift job stayed green with 2.54 on PyPI.

This action compares every direct dependency the job installed with PyPI, and
fails on one held back. For each hold it re-locks with the newer release
required, and reports uv's derivation:

```text
Because djangorestframework==3.18.1 depends on django>=5.2
and your project depends on django<4, we can conclude that
djangorestframework==3.18.1 and your project are incompatible.
```

## Usage

Put it after the step that syncs the environment the suite runs in, and before
the suite:

```yaml
      - uses: astral-sh/setup-uv@<sha> # vX.Y.Z

      - name: Resolve the newest versions pyproject allows
        run: uv lock --upgrade

      - name: Install
        id: install
        run: uv sync --all-groups --all-extras

      - name: Check no direct dependency is held back
        id: held-back
        uses: Artui/held-back-check@<sha> # v0.1.0

      # Run the suite whether or not the check failed: they answer different
      # questions, and a hold is no reason to stop measuring what did resolve.
      - name: Test
        if: ${{ !cancelled() && steps.install.outcome == 'success' }}
        run: uv run pytest
```

Pin the release's commit SHA, with the version as a trailing comment.
Dependabot's `github-actions` updater reads that comment and proposes new
releases. The release notes give the SHA for each version.

To quote the report in an issue that a failed scheduled run opens, read
`steps.held-back.outputs.report`. It is set even when the step fails. The file
is missing when the check could not compare anything, and the run's log then
says why.

### Inputs

| Input | Default | |
| --- | --- | --- |
| `working-directory` | `.` | Directory holding `pyproject.toml` and the synced environment. |
| `min-age-days` | `7` | A newer release younger than this is a notice, never a failure. |
| `report` | `$RUNNER_TEMP/held-back.md` | Where to write the markdown report, relative to the workspace. |

### Outputs

| Output | |
| --- | --- |
| `report` | Absolute path of the markdown report. |

The same report is appended to the job summary.

### Requirements

- `uv` on `PATH`, from `astral-sh/setup-uv`.
- A synced project environment that contains `packaging` (and `tomli` on Python
  3.10). The action runs inside that environment, because what it measures is
  that environment. pytest brings both packages. A project without pytest must
  declare them in a dependency group.
- Network access to `pypi.org`.

## What counts as held back

The check covers each requirement in `[project] dependencies`, in every extra
and in every dependency group, because a drift job installs all of them. It
compares the installed version with the newest release that meets all of these:

- **It is final.** Pre-releases, dev releases and yanked files do not count,
  even where the declared specifier names a pre-release.
- **It admits the running Python.** A release that has not reached it is not
  held back by anything the project declares.
- **It satisfies everything the project declares** for that name. The bounds
  are intersected across all occurrences. A `[tool.uv]` constraint narrows
  them, and an override replaces them.
- **It is at least `min-age-days` old.** A release newer than the window is
  reported as a notice and does not fail the run. Two things motivate the
  window:
  - The index this action reads and the one the resolver read can disagree for
    minutes after a release.
  - Seven days matches a Dependabot cooldown of seven days, so the project
    would not have adopted the release yet anyway.

A dependency installed from a path, URL or VCS (PEP 610) has no index release to
fall behind, so the check skips it.

### Accepting a hold

To accept a hold, declare it. Add a ceiling with a comment that says why, either
in `pyproject.toml` or, to keep it out of what you publish, in
`[tool.uv] constraint-dependencies`. The check honours both. Do not silence the
step.

### Direct dependencies only

The check covers direct dependencies only. When a transitive dependency is held
back, the repository that declares the conflicting pair reports it, and that
repository is also the one that can fix it.

## Exit status

| Status | Meaning |
| --- | --- |
| 0 | Nothing is held back. |
| 1 | Something is held back past the window. |
| 2 | The check could not look. Causes include an unreadable index, an unparseable requirement, a missing import, or an environment with none of the declared dependencies installed. |

The action fails rather than warns. A scheduled run's warnings go unread, so a
failure is the only signal that anyone sees.

## License

MIT
