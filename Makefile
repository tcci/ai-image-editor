.DEFAULT_GOAL:=all
paths = src

.PHONY: install
install:
	pip install -U pip pre-commit pip-tools
	pip install -r requirements/all.txt
	pre-commit install

.PHONY: update-lockfiles
update-lockfiles:
	@echo "Updating requirements files using pip-compile"
	pip-compile -q --strip-extras -o requirements/linting.txt requirements/linting.in
	pip-compile -q --strip-extras -o requirements/pyproject.txt pyproject.toml
	pip install --dry-run -r requirements/all.txt

.PHONY: format
format:
	ruff --fix-only $(paths)
	black $(paths)

.PHONY: lint
lint:
	ruff $(paths)
	black $(paths) --check --diff

.PHONY: pyright
pyright:
	pyright src

.PHONY: test
test:
	coverage run -m pytest tests

.PHONY: testcov
testcov: test
	coverage html

.PHONY: dev
dev:
	uvicorn src.main:app --reload

.PHONY: all
all: testcov lint
