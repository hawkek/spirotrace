# spirotrace

**Traceable extraction of lung function data from printed and scanned reports.**

> Status: early development. Nothing here is ready for use yet. The working prototype that this package replaces is not public; this repository is being built up from it module by module, with tests.

## Statement of need

Lung function results (spirometry, lung volumes, gas transfer) often reach researchers only as printed or scanned PDF reports, not as structured data. Typing them by hand is slow and error-prone, and generic PDF or OCR extraction gives values with no indication of which ones are wrong.

spirotrace turns such reports into an audited, analysis-ready dataset with a measured error rate:

- **Extraction.** Report layouts are described in template files (geometry and vocabulary); one reader handles every layout.
- **Auditability.** Every value keeps its raw text, its position on the page, how it was read, and every human correction made to it (who, when, before, after).
- **Physiology-informed checks.** Values are checked against each other and against reference equations (for example, the printed z-score against a GLI recalculation, FEV1/FVC against FEV1 and FVC, LLN against the sign of the z-score), so errors that look like plausible numbers are still caught.
- **Measured reliability.** Built-in tools compare the extraction with a blinded manual reference sample and report accuracy, flag sensitivity and residual (silent) errors.
- **Local by default.** Everything runs on the user's machine. Nothing is uploaded; there is no telemetry.

Similar tools exist ([PFT-Extractor](https://github.com/lindseyboulet/PFT-Extractor), an R app for Vmax reports; [pft-extractor](https://github.com/Automate-Medical/pft-extractor), a cloud pipeline using Amazon Textract). Neither describes validation of the extracted values or detection of extraction errors.

## Planned scope

| Tier | Contents |
| --- | --- |
| Research MVP | Two report layouts, deterministic extraction, provenance on every value, core checks, review corrections as an event log, derived variables (ATS/ERS 2022 pattern, severity, PRISm, bronchodilator response) after review, GLI recalculation via [rspiro](https://cran.r-project.org/package=rspiro), reference-standard evaluation |
| v1.0 | Add-your-own layout templates, a local browser review app, documentation |
| Later | Installers for non-programmers, template editor, further OCR engines |

## Data protection

spirotrace is meant for clinical reports. Please:

- **never** attach a report, a screenshot of one, or extracted values to an issue or pull request;
- report layout problems with the masked, structure-only survey output instead (instructions will be in the docs);
- check that your ethics and data-access approvals cover your use.

Outputs written to a project's `share/` folder are masked or aggregate by default. Whether any file may be shared is a decision for your study's governance, not something the software can certify.

## Installation

Not yet. When the first usable release is out: `pip install spirotrace`.

## Citation

See [CITATION.cff](CITATION.cff). A software paper is planned.

## Licence

To be confirmed (an OSI-approved permissive licence is intended).
