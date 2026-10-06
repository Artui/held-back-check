.PHONY: help init test lint lint-fix format format-check type-check release-bump

help:
	@echo "Available targets:"
	@echo "  init           Sync deps (all groups) and install pre-commit hooks"
	@echo "  test           Run pytest with coverage (100% line and branch required)"
	@echo "  lint           Run ruff check + ty check"
	@echo "  lint-fix       Auto-fix lint issues with ruff"
	@echo "  format         Format with ruff"
	@echo "  format-check   Verify formatting (CI runs this; lint does not)"
	@echo "  type-check     Run ty over the script"
	@echo "  release-bump   Bump pyproject.toml + CHANGELOG. Usage: make release-bump VERSION=X.Y.Z"

init:
	uv sync --all-groups
	uv run pre-commit install

test:
	uv run pytest

lint:
	uv run ruff check .
	uv run ty check check_held_back.py

lint-fix:
	uv run ruff check --fix .

format:
	uv run ruff format .

format-check:
	uv run ruff format --check --diff .

type-check:
	uv run ty check check_held_back.py

# The release itself is release.yml, on the merge to main that carries the bump.
# The lock records the project's own version, so it is relocked with it, by the
# uv that writes the revision the lock already has.
release-bump:
	@if [ -z "$(VERSION)" ]; then \
		echo "Usage: make release-bump VERSION=X.Y.Z"; exit 1; \
	fi
	uvx bump-my-version bump --new-version "$(VERSION)" patch
	uvx uv@0.12.0 lock
	@echo ""
	@echo "Bumped to $(VERSION). Review with 'git diff', then commit on release/$(VERSION) and open a PR."
