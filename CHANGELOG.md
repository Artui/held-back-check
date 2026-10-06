# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- **A composite action that fails a drift job when an unpinned resolve holds a
  direct dependency below its newest release, and names the requirement that
  holds it.** A resolver that cannot reach a release backs off to one it can
  and logs an ordinary update, so the suite passes against a version nobody
  chose. That is how a drift job stayed green with `pydantic-ai-slim` at 2.46
  and 2.54 published.
  - Every direct requirement (dependencies, extras, dependency groups and uv's
    `dev-dependencies`, with markers that name an extra treated as that extra)
    is compared with the newest final, unyanked release that admits the
    running Python and satisfies what the project declares, including
    `[tool.uv]` constraints and overrides.
  - A release younger than `min-age-days` (default 7, the Dependabot cooldown)
    is reported as a notice and never fails the step.
  - Each hold is explained by re-locking with the newer release required, which
    makes uv print its derivation.
  - The report goes to a file (the `report` output, which is set even when the
    step fails), to the job summary and to annotations.
  - A check that could not look (an index that cannot be reached or read, an
    unparseable requirement, an environment without `packaging`, or one where
    nothing declared is installed) exits 2 and never passes. Reading the index
    is retried twice first.

[Unreleased]: https://github.com/Artui/held-back-check/compare/v0.0.0...HEAD
