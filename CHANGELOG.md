# Changelog

All notable changes are listed here. Versions follow semantic versioning.

## Unreleased

- `model/`: value model for the extraction store. Fixed vocabularies (value states `value`, `empty`, `dash`, `not_on_page` and `unreadable`; read methods; column roles with distinct pre and post roles; standard parameters with kinds), the observation natural key with its string form (display position 1 is always the Best column), frozen `Record`, `Page` and `Observation` types with exact row round trips, and ratio parsing that stores FEV1/FVC, RV/TLC and FRC/TLC as fractions with the printed form kept. A struck-through value is a readable `value` with the `struck` flag set on the observation, not a value state. Record ids are `11`, `11A` / `11B`, `f` plus eight hex characters of the file hash when the file name gives no subject id, and `-2`, `-3`, ... for further files with the same subject id. `ParameterInfo.site_identifier` marks device serial and software version for the export guard. `never_extract_hits` matches the never-extract words and sign-off phrases as whole words, and a test keeps every parameter name clear of them.
- `config.py`: loads `spiro.toml` and `profiles/<name>.toml` with `tomllib`, validates them against a declared schema (unknown keys refused, profiles limited to switches), fills defaults, and returns one frozen settings object with a hash of the parsed settings.

## 0.0.1 (2026-10-08)

- Package skeleton: name reserved, planned module layout, command-line stub, CI, contribution guidelines, draft evaluation analysis plan.
