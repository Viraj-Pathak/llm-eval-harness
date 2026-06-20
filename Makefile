.PHONY: install test eval baseline gate lint report sweep report-adversarial
install:
	pip install -e ".[dev]"
test:
	pytest -q
eval:
	python -m llm_eval run suites/summarize.json
baseline:
	python -m llm_eval baseline suites/summarize.json
gate:
	python -m llm_eval gate suites/summarize.json
lint:
	ruff check llm_eval tests
report:
	python -m llm_eval dashboard suites/summarize.json --out report.html
report-adversarial:
	python -m llm_eval dashboard suites/adversarial.json --out report-adversarial.html
sweep:
	python -m llm_eval sweep suites/summarize.json \
		--variants mock:mock-1:prompts/summarize.v1.txt mock:mock-1:prompts/summarize.v2.txt
