#!/usr/bin/env python
# coding: utf-8

# In[ ]:


import os
import re
import json
import fitz
import pdfplumber
import pytesseract
import random

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

        # reuse existing dummy if original already mapped
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
# SAFE REPLACEMENT (EMBEDDED STRINGS OK)
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
# SECOND PASS: STRICTLY USE replace_page_n.json
# -------------------------------------------------
def final_replace_using_replace_page(page_no, output_dir):
    pii_path = os.path.join(output_dir, f"pii_page_{page_no}.json")
    replace_path = os.path.join(output_dir, f"replace_page_{page_no}.json")
    txt_path = os.path.join(output_dir, f"page_{page_no}_sanitized.txt")

    if not (os.path.exists(pii_path)
            and os.path.exists(replace_path)
            and os.path.exists(txt_path)):
        return

    pii_values = load_json(pii_path)
    replace_page = load_json(replace_path)

    with open(txt_path, "r", encoding="utf-8") as f:
        text = f.read()

    for value in pii_values.values():
        for entry in replace_page.values():
            if entry["original"] == value:
                text = re.sub(
                    re.escape(value),
                    entry["dummy"],
                    text,
                    flags=re.IGNORECASE
                )

    with open(txt_path, "w", encoding="utf-8") as f:
        f.write(text)

    print(f"✔ Final enforced replacement done for page {page_no}")

# -------------------------------------------------
# MAIN PIPELINE
# -------------------------------------------------
def process_pdf(pdf_path, output_dir, dummy_file):
    os.makedirs(output_dir, exist_ok=True)

    dummy_pool = load_json(dummy_file)
    master_path = os.path.join(output_dir, "master_pii.json")
    master_pii = load_json(master_path, {})

    doc = fitz.open(pdf_path)

    for i in range(len(doc)):
        page_no = i + 1
        print(f"\nProcessing page {page_no}")

        text = extract_text_from_page(pdf_path, i)

        pii_path = os.path.join(output_dir, f"pii_page_{page_no}.json")
        extracted_pii = load_json(pii_path)

        if not extracted_pii:
            print("⚠ No pii_page file")
            continue

        # 1️⃣ Build replace_page_n.json + update master
        replace_page = build_replace_page(
            page_no,
            extracted_pii,
            dummy_pool,
            master_pii
        )

        save_json(
            os.path.join(output_dir, f"replace_page_{page_no}.json"),
            replace_page
        )
        save_json(master_path, master_pii)

        # 2️⃣ First sanitization
        sanitized = replace_from_map(text, replace_page)
        sanitized_path = os.path.join(
            output_dir, f"page_{page_no}_sanitized.txt"
        )

        with open(sanitized_path, "w", encoding="utf-8") as f:
            f.write(sanitized)

        # 3️⃣ Enforced second-pass replacement
        final_replace_using_replace_page(page_no, output_dir)

    print("\n✅ PIPELINE COMPLETED SUCCESSFULLY")

# -------------------------------------------------
# RUN
# -------------------------------------------------
if __name__ == "__main__":
    process_pdf(
        # pdf_path=r"D:\py-tesseract\BF - James Freer\Arranged Medical Records and Bills\Medical Provider Records\MR.pdf",
        pdf_path=r"D:\\py-tesseract\\PII replace by dummy\\MR.pdf",
        output_dir="output",
        dummy_file="dummy.json"
    )

