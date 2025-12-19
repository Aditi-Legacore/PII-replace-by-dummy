#!/usr/bin/env python
# coding: utf-8

import os
import re
import json
import fitz
import pdfplumber
import pytesseract
import random
import sys

# -------------------------------------------------
# TESSERACT PATH (WINDOWS)
# -------------------------------------------------
pytesseract.pytesseract.tesseract_cmd = (
    r"C:\\Program Files\\Tesseract-OCR\\tesseract.exe"
)

# -------------------------------------------------
# CLEAN TEXT
# -------------------------------------------------
def clean(text):
    if not text:
        return ""
    text = text.replace("\t", " ")
    text = re.sub(r" +", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()

# -------------------------------------------------
# JSON HELPERS
# -------------------------------------------------
def load_json(path, default=None):
    if not os.path.exists(path):
        return default if default is not None else {}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)

# -------------------------------------------------
# OCR PAGE
# -------------------------------------------------
def extract_text_from_page(pdf_path, page_index):
    with pdfplumber.open(pdf_path) as pdf:
        page = pdf.pages[page_index]
        img = page.to_image(resolution=300)
        return clean(pytesseract.image_to_string(img.original))

# -------------------------------------------------
# PROGRESS BAR
# -------------------------------------------------
def print_progress_bar(current, total, bar_length=30):
    progress = current / total
    filled = int(bar_length * progress)
    bar = "█" * filled + "░" * (bar_length - filled)
    print(
        f"\rProcessing PDF: [{bar}] {current}/{total} pages",
        end="",
        flush=True
    )

# -------------------------------------------------
# PICK DUMMY VALUE
# -------------------------------------------------
def pick_dummy(field, dummy_pool, used_dummies):
    options = dummy_pool.get(field, [])
    if not options:
        return "REDACTED"

    unused = [o for o in options if o not in used_dummies]
    return random.choice(unused if unused else options)

# -------------------------------------------------
# BUILD REPLACE PAGE + UPDATE MASTER
# -------------------------------------------------
def build_replace_page(page_no, extracted_pii, dummy_pool, master_pii):
    page_key = f"page_{page_no}"
    replace_page = {}

    used_dummies = {
        v["dummy"]
        for p in master_pii.values()
        for v in p.values()
    }

    for field, original in extracted_pii.items():
        dummy = None

        # reuse existing dummy if already mapped
        for page in master_pii.values():
            for entry in page.values():
                if entry["original"] == original:
                    dummy = entry["dummy"]
                    break
            if dummy:
                break

        if not dummy:
            dummy = pick_dummy(field, dummy_pool, used_dummies)
            used_dummies.add(dummy)

        replace_page[field] = {
            "original": original,
            "dummy": dummy
        }

    master_pii[page_key] = replace_page
    return replace_page

# -------------------------------------------------
# SAFE TEXT REPLACEMENT
# -------------------------------------------------
def replace_from_map(text, replace_map):
    entries = sorted(
        replace_map.values(),
        key=lambda x: len(x["original"]),
        reverse=True
    )

    for e in entries:
        if not e["original"].strip():
            continue

        text = re.sub(
            re.escape(e["original"]),
            e["dummy"],
            text,
            flags=re.IGNORECASE
        )

    return text

# -------------------------------------------------
# MAIN PIPELINE
# -------------------------------------------------
def process_pdf(pdf_path, output_dir, dummy_file, combined_pii_file):
    os.makedirs(output_dir, exist_ok=True)

    dummy_pool = load_json(dummy_file)

    combined_pii_file = os.path.abspath(combined_pii_file)
    combined_pii = load_json(combined_pii_file)

    if not combined_pii:
        print("❌ combined_pii.json is EMPTY or NOT FOUND")
        sys.exit(1)

    doc = fitz.open(pdf_path)
    total_pages = len(doc)

    master_pii = {}
    replace_combine = {}
    combined_sanitized_pages = []

    for i in range(total_pages):
        page_no = i + 1
        print_progress_bar(page_no, total_pages)

        text = extract_text_from_page(pdf_path, i)

        replace_page = build_replace_page(
            page_no,
            combined_pii,
            dummy_pool,
            master_pii
        )

        sanitized = replace_from_map(text, replace_page)

        # enforced second pass
        for value in combined_pii.values():
            for entry in replace_page.values():
                if entry["original"] == value:
                    sanitized = re.sub(
                        re.escape(value),
                        entry["dummy"],
                        sanitized,
                        flags=re.IGNORECASE
                    )

        combined_sanitized_pages.append(
            f"\n\n===== PAGE {page_no} =====\n\n{sanitized}"
        )

        replace_combine[f"page_{page_no}"] = replace_page

    print()  # newline after progress bar

    # -------------------------------------------------
    # WRITE FINAL OUTPUTS
    # -------------------------------------------------
    save_json(os.path.join(output_dir, "master_pii.json"), master_pii)
    save_json(os.path.join(output_dir, "replace_combine.json"), replace_combine)

    with open(
        os.path.join(output_dir, "combine_sanitized.txt"),
        "w",
        encoding="utf-8"
    ) as f:
        f.write("".join(combined_sanitized_pages))

    print("\n✅ PIPELINE COMPLETED SUCCESSFULLY")
    print("📄 combine_sanitized.txt")
    print("📄 replace_combine.json")
    print("📄 master_pii.json")

# -------------------------------------------------
# RUN
# -------------------------------------------------
if __name__ == "__main__":
    process_pdf(
        pdf_path=r"D:\\py-tesseract\\BF - James Freer\\Arranged Medical Records and Bills\\Medical Provider Records\\2025.01.10 Inland Valley Medical Center - Mark up and comment done.pdf",
        output_dir="output",
        dummy_file="dummy.json",
        combined_pii_file=r"D:\\py-tesseract\\PII replace by dummy\\output\\combined_pii.json"
    )
