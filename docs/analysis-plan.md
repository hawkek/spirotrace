# Evaluation analysis plan (DRAFT, not yet fixed)

Status: draft. This plan is fixed, dated and committed **before** any reference coding starts; later changes are recorded below with their date and reason.

## Question

Does a transparent, physiology-informed pipeline extract structured lung function data accurately from printed and scanned clinical reports, and do its validation rules reduce undetected errors and the manual review burden?

## Data

- Reports: about 100 printed-and-scanned reports in two layouts (a portable-spirometer report and a hospital laboratory report with spirometry, lung volumes and gas transfer).
- Extraction runs, all with a tagged code version:
    - raw: no corrections applied;
    - reviewed: after the researcher's review of flagged values;
    - ablations: layout templates off; scan image checks off.

## Reference standard

- Coders: two, independent, blinded to all extraction output.
- Sample: TO DECIDE, either all reports (census) or a stratified random sample with recorded seed and sampling fractions (strata: post-bronchodilator present; lung volumes and gas transfer present; positional fallback used or many flags; none of these), weighted back for cohort-level rates.
- Variables: the core printed fields per layout (listed in an appendix generated from the templates).
- Coding protocol: see the coding protocol document (type as printed; '-' for a printed dash; empty if nothing printed; 'ill' if illegible; struck-through numbers typed and marked).
- Adjudication: disagreements resolved by a third reader against the report; unresolved and illegible fields are excluded and counted.

## Comparison rules

A printed dash and an empty cell both mean "no value". Numbers compare after parsing (decimal comma, leading '+', '*' and '%' removed). Dates compare as calendar dates. FEV1/FVC compares as a fraction. Text fields compare after case and whitespace normalisation and a fixed synonym list.

## Endpoints

- **Primary (TO CONFIRM):** proportion of extractable core fields in the reviewed dataset that match the adjudicated reference, at field level, with a 95% interval from resampling whole reports.
- **Secondary:**
    - the same for the raw output;
    - report-level error-free rate;
    - silent-error rate (wrong in the raw output and never flagged);
    - flag sensitivity, precision and false-alarm rate against the reference;
    - cumulative sensitivity and review burden as check layers are added (ablation);
    - review minutes per report against manual coding minutes;
    - error class for every raw error (OCR, parsing, localisation, positional fallback).
- Coder agreement: per variable, percentage agreement, and Cohen's kappa for categorical fields.

## Statistical methods

Wilson 95% intervals for proportions; report-level bootstrap (2,000 resamples, fixed seed) for overall rates, because fields from one report are not independent. Weighted estimates if a stratified sample is used.

## Changes after fixing

| Date | Change | Reason |
| --- | --- | --- |
