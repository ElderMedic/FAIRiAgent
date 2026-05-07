.PHONY: paper-results paper-smoke paper-analysis paper-figures paper-clean

PYTHON ?= /home/WUR/ke003/mambaforge/envs/FAIRiAgent/bin/python

paper-results: paper-smoke paper-analysis paper-figures

paper-smoke:
	$(PYTHON) evaluation/paper_experiments_v1/run_local_paper_smoke.py --doc earthworm --models qwen3.6-35b --repeats 1

paper-analysis:
	$(PYTHON) evaluation/paper_experiments_v1/run_paper_analysis.py

paper-figures:
	$(PYTHON) evaluation/paper_experiments_v1/generate_figures.py

paper-clean:
	rm -rf evaluation/paper_experiments_v1/runs/local_smoke
