# FaultForge - judge entry points.   make replay  (no API key)   |   make live  (needs MUSE_API_KEY)
PY ?= $(if $(wildcard .venv/bin/python3),.venv/bin/python3,python3)

# MUSE_API_KEY: taken from the environment, else from .env (KEY=value, no quotes)
ifeq ($(strip $(MUSE_API_KEY)),)
-include .env
endif
export MUSE_API_KEY

.PHONY: help setup replay live
help:
	@echo "make setup   - create .venv and install pinned requirements"
	@echo "make replay  - keyless: re-simulate headline case a6e8087b policy on/off + replay recorded Muse calls with provenance"
	@echo "make live    - one LIVE Muse Spark search round (needs MUSE_API_KEY), prints model id, endpoint, request id"

setup:
	python3 -m venv .venv && .venv/bin/pip install -q --upgrade pip && .venv/bin/pip install -q -r requirements.txt

replay:
	@$(PY) src/replay_demo.py

live:
	@if [ -z "$$MUSE_API_KEY" ]; then echo "MUSE_API_KEY not set: cp .env.example .env and fill it in (or export it)"; exit 2; fi
	@$(PY) src/live_round.py $(LIVE_ARGS)
