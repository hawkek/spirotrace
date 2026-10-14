# Changelog

All notable changes are listed here. Versions follow semantic versioning.

## Unreleased

- `config.py`: loads `spiro.toml` and `profiles/<name>.toml` with `tomllib`, validates them against a declared schema (unknown keys refused, profiles limited to switches), fills defaults, and returns one frozen settings object with a hash of the parsed settings.

## 0.0.1 (2026-10-08)

- Package skeleton: name reserved, planned module layout, command-line stub, CI, contribution guidelines, draft evaluation analysis plan.
