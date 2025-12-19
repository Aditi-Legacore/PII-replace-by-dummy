PII Extraction & Page-Wise Sanitization Pipeline
===============================================

Overview
--------

This project implements a deterministic, auditable, page-scoped PII sanitization pipeline for PDF documents using OCR.

Key goals:
- Replace only values listed in page-level PII files (`combined_pii.json`).
- Ensure the same original value always maps to the same dummy value.
- Keep replacements page-scoped to avoid cross-page contamination.
- Produce persistent JSON artifacts for auditing.

Core Principles
---------------
- **Page Scoped:** Each PDF page is processed independently; replacements for page N come from `replace_page_n.json` only.
- **Master Source:** `master_pii.json` is the authoritative historical map of originals → dummies.
- **Value-Only Matching:** Matching and replacement operate on PII values (not PII keys).
- **Deterministic Mapping:** If an original value exists in `master_pii.json`, its dummy is reused; otherwise a dummy is assigned from `dummy.json` and recorded.
- **Longest-First Replacement:** During sanitization, longer PII values are replaced first to avoid partial collisions.
- **Auditability:** All artifacts (`replace_page_n.json`, `master_pii.json`, `page_n_sanitized.txt`) are retained for traceability.

Directory Structure (example)
-----------------------------
```powershell
project/
│
├── dummy.json                                     # Predefined dummy pools per PII type
├── personal_info_replace_by_dummy.py              # Main pipeline runner
├── MR.pdf                      # PII pdf
├── output/
│   ├── pii_page_1.json         # Input PII (page 1)
│   ├── replace_page_1.json     # Authoritative replacements for page 1
│   ├── page_1_sanitized.txt    # Resulting sanitized text for page 1
│   └── master_pii.json         # Historical mapping of originals -> dummies
```

Inputs
------
1) PDF file (original document) — OCR step extracts raw text per page.
2) `combined_pii.json` — page-scoped PII values (either produced manually or by an extractor).
	 Example:

```
{
	"Patient_Name": "James Freer",
	"MRN": "131017766"
}
```

3) `dummy.json` — pools of dummy values per PII type. Example:

```
{
	"Patient_Name": ["Alex Brown"],
	"MRN": ["SWH07605906"]
}
```

Outputs
-------
- `replace_page_n.json` (MANDATORY per page): authoritative mapping used to sanitize that page. Example:

```
{
	"Patient_Name": {"original": "James Freer", "dummy": "Alex Brown"},
	"MRN": {"original": "131017766", "dummy": "SWH07605906"}
}
```

- `master_pii.json`: historical, page-wise mapping of originals → dummies:

```
{
	"page_1": {
		"Patient_Name": {"original": "James Freer", "dummy": "Alex Brown"}
	}
}
```

- `page_n_sanitized.txt`: final sanitized OCR text for each page.

Processing Flow
---------------
1. OCR: extract raw page text using Tesseract (or pre-extracted OCR text).
2. Load Page PII: read `combined_pii.json` and use values only (never PII keys) to drive replacements.
3. Build `replace_page_n.json`:
	 - If a value is already present in `master_pii.json`, reuse its dummy.
	 - Otherwise assign a new dummy from `dummy.json` and update `master_pii.json`.
4. Initial Sanitization:
	 - Replace PII values in the page's text, matching values even when embedded inside longer strings.
	 - Perform replacements in descending length order to avoid partial matches.
5. Enforced Page-Wise Replacement:
	 - Re-scan `page_n_sanitized.txt` and ensure only values from `combined_pii.json` were replaced.
	 - Use only `replace_page_n.json` when re-applying replacements for that page.

Safety Guarantees
-----------------
- **Partial replacements:** Avoided by longest-match-first strategy.
- **Cross-page contamination:** Prevented because replacements for page N only use `replace_page_n.json`.
- **Wrong dummy reuse:** Prevented by consulting `master_pii.json` before assigning new dummies.
- **Over-sanitization:** Matching is value-only; keys and unrelated text are not considered.
- **Auditability:** Persistent JSON artifacts record decisions for later review.

Examples and Edge Cases
-----------------------
- Embedded strings are sanitized (e.g., `SWHC-Freer, James-Enc #131017766` will have `James`/`Freer`/`131017766` replaced according to the page's `replace_page_n.json`).
- Same original -> same dummy: mapping is stable across pages if present in `master_pii.json`.

Environment Requirements
------------------------
- Python 3.10+
- Tesseract OCR installed locally and callable from the environment.
- Libraries:

```
pip install pytesseract pdfplumber pymupdf pillow
```

Windows notes: this project has been tested on Windows; ensure the Tesseract binary path is set in `personal_info_replace_by_dummy.py` if required.

How to Run
----------
Ensure the following exist in the project root:
- `dummy.json` populated with dummy pools
- `combined_pii.json` files for pages to be sanitized

Then run:

```powershell
python personal_info_replace_by_dummy.py
```

What the script guarantees
-------------------------
- If a value appears in `combined_pii.json`, it WILL be replaced in that page's sanitized output.
- If a value does NOT appear in `combined_pii.json`, it WILL NOT be touched.

This behavior ensures deterministic, auditable, and page-scoped sanitization suitable for compliance workflows.

Next steps
----------
- Optionally commit this change and run the pipeline against a sample PDF.
- I can also add a small example `pii_page_1.json` and `dummy.json` plus a minimal test harness — tell me if you want that.

