
.PHONY: docs-serve docs-build

docs-serve:
	poetry run mkdocs serve

docs-build:
	poetry run mkdocs build
