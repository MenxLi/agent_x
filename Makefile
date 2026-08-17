.PHONY: build-web test

build-web:
	cd web && npm i && npm run build

test:
	uv run python -m unittest discover -s test -v