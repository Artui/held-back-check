# Repo conventions for `held-back-check`

## What this is

A composite GitHub Action (`action.yml`) that runs one script
(`check_held_back.py`) inside a consumer's synced uv environment. It fails a
drift job when an unpinned resolve holds a direct dependency below its newest
release, and it reports uv's derivation of what holds it. The README covers the
rules. This file covers how to change them.

Consumers are the drift jobs (`upstream-drift.yml`) of the family's Python
repositories. They pin the action to a release's commit SHA, with a
`# vX.Y.Z` comment.

## Commands

| Target | What it does |
| --- | --- |
| `make init` | `uv sync --all-groups` + install pre-commit hooks |
| `make test` | pytest with the 100% line + branch gate |
| `make lint` | `ruff check .` + `ty check check_held_back.py` |
| `make format` / `make format-check` | `ruff format`; CI runs the check, and `lint` does not |
| `make release-bump VERSION=X.Y.Z` | rewrite the version in `pyproject.toml` + promote `[Unreleased]` |

## Structural rules

1. **The script stays one file, run by path.** It executes in the consumer's
   environment, as `uv run --no-sync python "$GITHUB_ACTION_PATH/check_held_back.py"`,
   so it is never imported as a package. Splitting it would mean shipping a
   package into environments that never asked for one.
2. **Its imports are the standard library plus `packaging` (and `tomli` on
   3.10), and that is a hard limit.** Every import has to already exist in the
   consumer's environment. pytest brings these two, and nothing else can be
   assumed. A new import means every consumer must declare it.
3. **Python 3.10 is the floor**, because consumers run the script on whatever
   Python they test with. The matrix covers 3.10 to 3.14, and every arm is
   covered on every version. The tests load the script with an import hidden
   or substituted rather than branching on the version.
4. **"Could not look" is never a pass.** Anything that stops the comparison
   raises `CannotCheck`, which exits 2 with an annotation. A new failure mode
   follows the same path.
5. **Inputs reach shell through `env`**, never as `${{ }}` inside `run`.
   `tests/test_action.py` enforces this.
6. **`from __future__ import annotations`** and absolute imports, which ruff
   enforces.

## Tests

- `tests/test_check_held_back.py` covers the rules. The tests replace the index
  with files shaped like PyPI's simple JSON API, one of them copied verbatim
  from a real response.
- `tests/test_action.py` covers the action's wiring, reading `action.yml` as
  YAML.
- The `action` job in `tests.yml` runs the action as a consumer does. It uses
  `uses: ./`, the real index and the real uv, against the projects in
  `tests/fixtures/`, and it needs all three:
  - a hold, plus a ceiling the check must honour;
  - a project that is current;
  - an environment without `packaging`, where the check must fail, not pass.
- `tests/helpers.py` loads the script fresh for each test. Import it from there,
  never from `conftest.py`.

## Releases

`release.yml` runs on every push to `main`. When `pyproject.toml` carries a
version with no tag on origin, it does the following:

1. runs the suite;
2. extracts that version's CHANGELOG section;
3. runs `gh release create vX.Y.Z --target <sha>`, which creates the tag.

The job summary prints the line to pin. Nothing is uploaded, because the tag is
the release.

```bash
git checkout -b release/0.2.0
make release-bump VERSION=0.2.0
git diff
git commit -am "Release 0.2.0"
git push -u origin release/0.2.0
gh pr create
```

After a release, adopt it in each consumer, or nothing changes. Dependabot's
`github-actions` updater proposes the new pin only after its cooldown.

## Branching

Never commit to `main`. Branch, push, and open a PR. The owner merges.
