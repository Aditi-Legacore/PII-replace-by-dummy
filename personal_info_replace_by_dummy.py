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
# NORMALIZE TEXT (STRING OR LIST SAFE)
# -------------------------------------------------
def normalize_text(text):
    if not text:
        return ""

    # ✅ FIX: handle list of variants
    if isinstance(text, list):
        text = " ".join(map(str, text))

    text = text.lower()
    text = re.sub(r"[^a-z]", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()

def tokenize(text):
    return set(normalize_text(text).split())

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

    # 🔑 token → dummy map (from previous pages)
    token_dummy_map = {}
    for page in master_pii.values():
        for entry in page.values():
            for t in tokenize(entry["original"]):
                if len(t) >= 3:
                    token_dummy_map[t] = entry["dummy"]

    for field, original in extracted_pii.items():
        orig_tokens = tokenize(original)
        dummy = None

        # 🔥 TOKEN-LEVEL REUSE WITH FUZZY MATCHING
        for t in orig_tokens:
            best_match = None
            best_score = 0
            for existing_token in token_dummy_map:
                score = fuzz.ratio(t, existing_token)
                if score > best_score and score >= 80:  # threshold 80%
                    best_score = score
                    best_match = existing_token
            if best_match:
                dummy = token_dummy_map[best_match]
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
# SAFE TEXT REPLACEMENT (LIST AWARE)
# -------------------------------------------------
def replace_from_map(text, replace_map):
    entries = []

    for e in replace_map.values():
        original = e["original"]

        # ✅ expand list variants
        if isinstance(original, list):
            for v in original:
                entries.append({"original": v, "dummy": e["dummy"]})
        else:
            entries.append(e)

    entries.sort(key=lambda x: len(x["original"]), reverse=True)

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

def extract_dummy_lastname(dummy):
    parts = dummy.split()
    return parts[1] if len(parts) > 1 else dummy

# -------------------------------------------------
# AGGRESSIVE NAME VARIANT REPLACEMENT
# -------------------------------------------------
def replace_name_variants(text, master_pii, page_key, replace_combine):
    token_dummy_map = {}

    for page in master_pii.values():
        for entry in page.values():
            for t in tokenize(entry["original"]):
                if len(t) >= 3:
                    token_dummy_map[t] = entry["dummy"]

    for token, dummy in token_dummy_map.items():
        dummy_last = extract_dummy_lastname(dummy)

        # Mr. Handrop → Mr. <dummy_lastname>
        pattern = re.compile(
            rf"\b(mr|mrs|ms|dr)\.?\s+{re.escape(token)}\b",
            flags=re.IGNORECASE
        )

        def _repl(match):
            title = match.group(1)
            replaced = f"{title}. {dummy_last}"

            # ✅ add separate object into master + replace_combine
            master_pii[page_key][f"{title}_variant_{token}"] = {
                "original": match.group(0),
                "dummy": replaced
            }

            if f"{title}_variant_{token}" not in replace_combine:
                replace_combine[f"{title}_variant_{token}"] = {
                    "original": match.group(0),
                    "dummy": replaced
                }

            return replaced

        text = pattern.sub(_repl, text)

    return text

def get_output_paths(pdf_path):
    pdf_dir = os.path.dirname(pdf_path)
    pdf_name = os.path.splitext(os.path.basename(pdf_path))[0]
    safe_name = re.sub(r"\s+", "_", pdf_name)

    out_dir = os.path.join(pdf_dir, "extracted_files")
    os.makedirs(out_dir, exist_ok=True)

    return {
        "dir": out_dir,
        "sanitized_txt": os.path.join(
            out_dir, f"{safe_name}_combine_sanitized.txt"
        ),
        "replace_combine": os.path.join(
            out_dir, f"{safe_name}_replace_combine.json"
        ),
        "master_pii": os.path.join(
            out_dir, f"{safe_name}_master_pii.json"
        ),
    }


# -------------------------------------------------
# MAIN PIPELINE
# -------------------------------------------------
def process_pdf(pdf_path, output_dir, dummy_file, combined_pii_file):
    os.makedirs(output_dir, exist_ok=True)

    dummy_pool = load_json(dummy_file)
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
        sanitized = replace_name_variants(
            sanitized,
            master_pii,
            page_key=f"page_{page_no}",
            replace_combine=replace_combine
        )

        combined_sanitized_pages.append(
            f"\n\n===== PAGE {page_no} =====\n\n{sanitized}"
        )

        for field, entry in replace_page.items():
            if field not in replace_combine:
                replace_combine[field] = entry

    print()

    # -------------------------------------------------
    # WRITE OUTPUTS
    # -------------------------------------------------
    save_json(os.path.join(output_dir, "master_pii.json"), master_pii)
    save_json(os.path.join(output_dir, "replace_combine.json"), replace_combine)

    with open(
        os.path.join(output_dir, "combine_sanitized.txt"),
        "w",
        encoding="utf-8"
    ) as f:
        f.write("".join(combined_sanitized_pages))

        paths = get_output_paths(pdf_path)

    save_json(paths["master_pii"], master_pii)
    save_json(paths["replace_combine"], replace_combine)

    with open(paths["sanitized_txt"], "w", encoding="utf-8") as f:
        f.write("".join(combined_sanitized_pages))

    print("\n✅ PIPELINE COMPLETED SUCCESSFULLY")
    print(f"📄 {os.path.basename(paths['sanitized_txt'])}")
    print(f"📄 {os.path.basename(paths['replace_combine'])}")
    print(f"📄 {os.path.basename(paths['master_pii'])}")

# -------------------------------------------------
# RUN
# -------------------------------------------------
if __name__ == "__main__":
    process_pdf(
        pdf_path=r"D:\\py-tesseract\\BF - James Freer\\Arranged Medical Records and Bills\\Medical Provider Records\\2023.11.16 Senta Neurosurgery.pdf",
        # pdf_path=r"D:\\py-tesseract\\BF - James Freer\\Arranged Medical Records and Bills\\Medical Provider Records\\MR.pdf",
        # pdf_path=r"D:\\py-tesseract\\BF - James Freer\\Arranged Medical Records and Bills\\Medical Provider Records\\2024.06.30 Big Bear Fire Department.pdf",
        output_dir="output",
        dummy_file="dummy.json",
        combined_pii_file=r"D:\\py-tesseract\\PII replace by dummy\\output\\combined_pii.json"
    )
