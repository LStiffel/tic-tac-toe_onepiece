"""Reproducible build scripts for the derived dataset files (ADR 0004).

The Raw dataset (``characters.json``, ``devil_fruits.json``, ``islands.json``) is
vendored; the files the game plays from (``categories.json``, ``categories.txt``)
are *derived* and must be rebuildable. :mod:`scripts.build_categories` is that
builder.
"""
