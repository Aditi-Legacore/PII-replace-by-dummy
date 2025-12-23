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
from rapidfuzz import fuzz

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
# NORMALIZE TEXT
# -------------------------------------------------
def normalize_text(text):
    if not text:
        return ""
    if isinstance(text, list):
        text = " ".join(text)
    text = text.lower()
    text = re.sub(r"[^a-z]", " ", text)
    return re.sub(r"\s+", " ", text).strip()

# -------------------------------------------------
# JSON HELPERS
# -------------------------------------------------
def load_json(path, default=None):
    if not os.path.exists(path):
        return default if default is not None else {}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

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
    print(f"\rProcessing PDF: [{bar}] {current}/{total}", end="", flush=True)

# -------------------------------------------------
# NAME UTILITIES
# -------------------------------------------------
def is_name_field(field):
    return "name" in field.lower()

def generate_name_variants(name):
    """
    From 'Begle Peter' generate:
    - begle peter
    - peter begle
    - beglepeter
    - peterbegle
    """
    norm = normalize_text(name)
    parts = norm.split()
    variants = set()

    if len(parts) >= 2:
        first, last = parts[0], parts[1]
        variants.add(f"{first} {last}")
        variants.add(f"{last} {first}")
        variants.add(f"{first}{last}")
        variants.add(f"{last}{first}")
    elif parts:
        variants.add(parts[0])

    return variants

# -------------------------------------------------
# BUILD FUZZY NAME MAP (FROM combined_pii.json)
# -------------------------------------------------
def build_fuzzy_name_map(combined_pii, dummy_pool):
    name_map = {}

    # pick dummy dynamically
    name_dummies = (
        dummy_pool.get("Name")
        or dummy_pool.get("Patient Name")
        or []
    )
    default_dummy = random.choice(name_dummies) if name_dummies else "REDACTED Peter"

    for field, value in combined_pii.items():

        # ---- FLAT JSON (your current structure)
        if isinstance(value, str) and is_name_field(field):
            for v in generate_name_variants(value):
                name_map[v] = default_dummy

        # ---- FUTURE: dict-based PII
        elif isinstance(value, dict):
            original = value.get("original")
            dummy = value.get("dummy", default_dummy)
            originals = original if isinstance(original, list) else [original]

            for o in originals:
                for v in generate_name_variants(o):
                    name_map[v] = dummy

    return name_map

# -------------------------------------------------
# FUZZY FULL NAME REPLACEMENT
# -------------------------------------------------
def fuzzy_name_replace(text, fuzzy_name_map, threshold=82):
    """
    Handles:
    - Begle , Peter
    - Begle, Peter
    - Segie Peter
    - BeglePeter
    - Mr / Dr Begle , Peter
    """

    original_text = text
    norm_text = normalize_text(text)

    for norm_name, dummy in fuzzy_name_map.items():
        name_len = len(norm_name.split())

        norm_words = norm_text.split()

        for i in range(len(norm_words) - name_len + 1):
            chunk = " ".join(norm_words[i:i + name_len])

            score = fuzz.token_sort_ratio(chunk, norm_name)

            if score >= threshold:
                # build flexible regex for original text
                pattern = norm_name.replace(" ", r"[\s,.\-]*")

                # titles
                title_pattern = rf"(?:\b(mr|mrs|ms|dr)\.?\s+)?{pattern}"

                original_text = re.sub(
                    title_pattern,
                    lambda m: (
                        f"{m.group(1)}. {dummy}"
                        if m.group(1)
                        else dummy
                    ),
                    original_text,
                    flags=re.IGNORECASE
                )

        # ---- joined names (BeglePeter)
        joined = norm_name.replace(" ", "")
        original_text = re.sub(
            joined,
            dummy,
            original_text,
            flags=re.IGNORECASE
        )

    return original_text

# -------------------------------------------------
# MAIN PIPELINE
# -------------------------------------------------
def process_pdf(pdf_path, output_dir, dummy_file, combined_pii_file):
    os.makedirs(output_dir, exist_ok=True)

    combined_pii = load_json(combined_pii_file)
    dummy_pool = load_json(dummy_file)

    if not combined_pii:
        print("❌ combined_pii.json EMPTY")
        sys.exit(1)

    fuzzy_name_map = build_fuzzy_name_map(combined_pii, dummy_pool)

    doc = fitz.open(pdf_path)
    total_pages = len(doc)
    sanitized_pages = []

    for i in range(total_pages):
        page_no = i + 1
        print_progress_bar(page_no, total_pages)

        text = extract_text_from_page(pdf_path, i)

        # 🔥 FUZZY NAME REPLACEMENT
        text = fuzzy_name_replace(text, fuzzy_name_map)

        sanitized_pages.append(
            f"\n\n===== PAGE {page_no} =====\n\n{text}"
        )

    print()

    out_file = os.path.join(output_dir, "combine_sanitized.txt")
    with open(out_file, "w", encoding="utf-8") as f:
        f.write("".join(sanitized_pages))

    print("\n✅ PIPELINE COMPLETED SUCCESSFULLY")
    print(f"📄 {out_file}")

# -------------------------------------------------
# RUN
# -------------------------------------------------
if __name__ == "__main__":
    process_pdf(
        pdf_path=r"D:\\py-tesseract\\BF - James Freer\\Arranged Medical Records and Bills\\Medical Provider Records\\2024.06.30 Big Bear Fire Department.pdf",
        # pdf_path=r"D:\\py-tesseract\\BF - James Freer\\Arranged Medical Records and Bills\\Medical Provider Records\\MR.pdf",
        # pdf_path=r"D:\\py-tesseract\\BF - James Freer\\Arranged Medical Records and Bills\\Medical Provider Records\\2024.06.30 Big Bear Fire Department.pdf",
        output_dir="output",
        dummy_file="dummy.json",
        combined_pii_file=r"D:\\py-tesseract\\PII replace by dummy\\output\\combined_pii.json"
    )
