PY := services_env/bin/python

.PHONY: help test eval eval-refresh eval-strict

help:
	@echo "Targets:"
	@echo "  make test           Run all SHAIL unit tests"
	@echo "  make eval           Run retrieval-precision eval suite"
	@echo "  make eval-strict    Run eval suite as CI gate (fails on golden drift)"
	@echo "  make eval-refresh   Regenerate golden snapshots (use sparingly)"

test:
	$(PY) -m pytest apps/shail/tests/ -q

eval:
	$(PY) -m pytest apps/shail/tests/retrieval_precision.py -v

eval-strict:
	$(PY) -m pytest apps/shail/tests/retrieval_precision.py \
	  -v --tb=short \
	  -p no:cacheprovider \
	  --no-header

eval-refresh:
	SHAIL_REFRESH_GOLDEN=1 $(PY) -m pytest apps/shail/tests/retrieval_precision.py -v
