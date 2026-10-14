# Changelog

All notable changes are listed here. Versions follow semantic versioning.

## Unreleased

- `model/`: value model for the extraction store. Fixed vocabularies (value states, read methods, column roles with distinct pre and post roles, standard parameters with kinds), the observation natural key with its string form, frozen `Record`, `Page` and `Observation` types with exact row round trips, and ratio parsing that stores FEV1/FVC, RV/TLC and FRC/TLC as fractions with the printed form kept.
- `config.py`: loads `spiro.toml` and `profiles/<name>.toml` with `tomllib`, validates them against a declared schema (unknown keys refused, profiles limited to switches), fills defaults, and returns one frozen settings object with a hash of the parsed settings.

## 0.0.1 (2026-10-08)

- Package skeleton: name reserved, planned module layout, command-line stub, CI, contribution guidelines, draft evaluation analysis plan.
