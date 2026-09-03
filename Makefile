# Activate the virtualenv first (see README "Setup"), or override PYTHON,
# e.g. `make refresh PYTHON=.venv/Scripts/python.exe`.
PYTHON ?= python

.PHONY: refresh provenance

# Full Refresh in place: fetch the Raw dataset from Upstream, rebuild the derived
# files, regenerate data/PROVENANCE.md, run the validator (ADR 0004).
refresh:
	$(PYTHON) -m scripts.refresh

# Just regenerate data/PROVENANCE.md from the files already on disk.
provenance:
	$(PYTHON) -m scripts.refresh --provenance-only
