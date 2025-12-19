#!/usr/bin/env python
# coding: utf-8

import os
import re
import json
import fitz
import pytesseract
import random
from PIL import Image

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
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return default if default is not None else {}

def save_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)

# -------------------------------------------------
# PYMuPDF TEXT EXTRACTION (PAGE-WISE)
# -------------------------------------------------
def extract_pymupdf_page(doc, page_index, out_dir):
    page = doc[page_index]
    text = clean(page.get_text())

    page_dir = os.path.join(out_dir, "pymupdf", f"page_{page_index+1}")
    os.makedirs(page_dir, exist_ok=True)

    path = os.path.join(page_dir, f"page_{page_index+1}_mu.txt")
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)

    return text, path

# -------------------------------------------------
# OCR EXTRACTION (PAGE-WISE)
# -------------------------------------------------
def extract_ocr_page(doc, page_index, out_dir):
    page = doc[page_index]
    pix = page.get_pixmap(dpi=300)
    img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)

    text = clean(pytesseract.image_to_string(img))

    page_dir = os.path.join(out_dir, "ocr", f"page_{page_index+1}")
    os.makedirs(page_dir, exist_ok=True)

    path = os.path.join(page_dir, f"page_{page_index+1}_ocr.txt")
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)

    return text, path

# -------------------------------------------------
# TEXT NORMALIZATION
# -------------------------------------------------
def normalize(text):
    text = text.lower()
    text = re.sub(r"[^a-z0-9\s]", "", text)
    return set(text.split())

# -------------------------------------------------
# PAGE-WISE COMPARISON + ACCURACY
# -------------------------------------------------
def compare_page(mu_text, ocr_text, out_dir, page_no):
    mu_words = normalize(mu_text)
    ocr_words = normalize(ocr_text)

    common = mu_words & ocr_words
    missing = mu_words - ocr_words
    extra = ocr_words - mu_words

    accuracy = round(
        (len(common) / max(len(mu_words), 1)) * 100, 2
    )

    comparison = {
        "page": page_no,
        "pymupdf_word_count": len(mu_words),
        "ocr_word_count": len(ocr_words),
        "common_words": len(common),
        "missing_in_ocr": len(missing),
        "extra_in_ocr": len(extra),
        "accuracy_percentage": accuracy
    }

    path = os.path.join(
        out_dir, "comparison", f"page_{page_no}_comparison.json"
    )
    save_json(path, comparison)

    # 🔹 PRINT PAGE ACCURACY
    print(f"📄 Page {page_no} Extraction Accuracy: {accuracy}%")

    return accuracy

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
# UPDATE MASTER + CREATE REPLACE_PAGE_N
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
# SAFE REPLACEMENT
# -------------------------------------------------
def replace_from_map(text, replace_map):
    entries = sorted(
        replace_map.values(),
        key=lambda x: len(x["original"]),
        reverse=True
    )

    for e in entries:
        if e["original"].strip():
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
def process_pdf(pdf_path, output_dir, dummy_file):
    os.makedirs(output_dir, exist_ok=True)

    dummy_pool = load_json(dummy_file)
    master_path = os.path.join(output_dir, "master_pii.json")
    master_pii = load_json(master_path, {})

    doc = fitz.open(pdf_path)

    page_accuracies = []

    for i in range(len(doc)):
        page_no = i + 1
        print(f"\nProcessing page {page_no}")

        mu_text, _ = extract_pymupdf_page(doc, i, output_dir)
        ocr_text, _ = extract_ocr_page(doc, i, output_dir)

        accuracy = compare_page(mu_text, ocr_text, output_dir, page_no)
        page_accuracies.append(accuracy)

        pii_path = os.path.join(output_dir, f"pii_page_{page_no}.json")
        extracted_pii = load_json(pii_path)

        if not extracted_pii:
            print("⚠ No pii_page file")
            continue

        replace_page = build_replace_page(
            page_no, extracted_pii, dummy_pool, master_pii
        )

        save_json(
            os.path.join(output_dir, f"replace_page_{page_no}.json"),
            replace_page
        )
        save_json(master_path, master_pii)

        sanitized = replace_from_map(mu_text, replace_page)
        with open(
            os.path.join(output_dir, f"page_{page_no}_sanitized.txt"),
            "w",
            encoding="utf-8"
        ) as f:
            f.write(sanitized)

    # -------------------------------------------------
    # OVERALL DOCUMENT ACCURACY
    # -------------------------------------------------
    if page_accuracies:
        overall_accuracy = round(
            sum(page_accuracies) / len(page_accuracies), 2
        )
        print("\n📊 OVERALL DOCUMENT EXTRACTION ACCURACY")
        print(f"✅ Average Accuracy: {overall_accuracy}%")

        save_json(
            os.path.join(output_dir, "comparison", "document_accuracy.json"),
            {
                "total_pages": len(page_accuracies),
                "average_accuracy_percentage": overall_accuracy
            }
        )

    print("\n✅ PIPELINE COMPLETED SUCCESSFULLY")

# -------------------------------------------------
# RUN
# -------------------------------------------------
if __name__ == "__main__":
    process_pdf(
        pdf_path=r"D:\\py-tesseract\\BF - James Freer\\Arranged Medical Records and Bills\\Medical Provider Records\\2024.03.07 Imaging Healthcare Specialists.pdf",
        output_dir="output",
        dummy_file="dummy.json"
    )
