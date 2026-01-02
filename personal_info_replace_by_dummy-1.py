#!/usr/bin/env python
# coding: utf-8

"""
PDF Extraction & PII Anonymization Pipeline (SINGLE FILE)
Complete workflow:
Extract → Map → Replace → Save
"""

# =====================================================
# IMPORTS
# =====================================================
import sys
import os
import re
import io
import json
import time
import random
from pathlib import Path

import fitz
import pdfplumber
import pytesseract
from PIL import Image
import cv2
import numpy as np
from rapidfuzz import fuzz

# =====================================================
# TESSERACT CONFIG (WINDOWS)
# =====================================================
pytesseract.pytesseract.tesseract_cmd = (
    r"C:\\Program Files\\Tesseract-OCR\\tesseract.exe"
)

# =====================================================
# -------------------- CONFIG -------------------------
# =====================================================
PDF_PATH = r"D:\\py-tesseract\\BF - James Freer\\Arranged Medical Records and Bills\\Medical Provider Records\\2024.06.30 Big Bear Fire Department.pdf"

OUTPUT_DIR = Path("output")
OUTPUT_DIR.mkdir(exist_ok=True)

EXTRACTED_TEXT_FILE = OUTPUT_DIR / "extracted.txt"
SANITIZED_TEXT_FILE = OUTPUT_DIR / "sanitized.txt"
REPLACEMENT_LOG_FILE = OUTPUT_DIR / "log.txt"

PII_FILE = "D:\\py-tesseract\\PII replace by dummy\\output\\combined_pii.json"
DUMMY_FILE = "D:\\py-tesseract\\PII replace by dummy\\dummy.json"

REPLACEMENT_PII_FILE = OUTPUT_DIR / "replacement_pii.json"
MASTER_PII_FILE = OUTPUT_DIR / "master_pii.json"

FIELD_THRESHOLDS = {
    "Name": 75,
    "MRN": 85,
    "DOB": 90,
    "Phone": 85,
    "Email": 90,
    "Address": 75
}

# =====================================================
# ------------------ UTILITIES ------------------------
# =====================================================
def normalize(value):
    return re.sub(r"\s+", " ", str(value).lower()).strip()

def load_json(path):
    path = Path(path)
    if path.exists():
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    print(f"⚠️ Warning: {path} not found")
    return {}

def save_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)
    print(f"✅ Saved: {path}")

# =====================================================
# ---------------- TEXT CLEANING ----------------------
# =====================================================
def clean_text(text):
    if not text:
        return ""
    text = text.replace("\t", " ")
    text = re.sub(r" +", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()

# =====================================================
# ------------ OCR IMAGE PREPROCESSING ----------------
# =====================================================
def preprocess_image_for_ocr(image_bytes, level="medium"):
    image = Image.open(io.BytesIO(image_bytes))
    img = cv2.cvtColor(np.array(image), cv2.COLOR_RGB2BGR)
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    if level in ["medium", "aggressive"]:
        h, w = gray.shape
        if w < 1500:
            scale = 1500 / w
            gray = cv2.resize(gray, (int(w*scale), int(h*scale)))

    if level == "light":
        _, gray = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    elif level == "medium":
        gray = cv2.fastNlMeansDenoising(gray)
        gray = cv2.adaptiveThreshold(gray,255,cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                                     cv2.THRESH_BINARY,11,2)
    else:
        gray = cv2.fastNlMeansDenoising(gray)
        clahe = cv2.createCLAHE(2.0,(8,8))
        gray = clahe.apply(gray)
        kernel = np.array([[-1,-1,-1],[-1,9,-1],[-1,-1,-1]])
        gray = cv2.filter2D(gray,-1,kernel)
        gray = cv2.adaptiveThreshold(gray,255,cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                                     cv2.THRESH_BINARY,11,2)

    return Image.fromarray(gray)

# =====================================================
# ---------------- OCR ENGINE --------------------------
# =====================================================
def ocr_image_with_layout(image_bytes, aggressive=True):
    best_text = ""
    best_score = 0

    for level in ["light","medium","aggressive"] if aggressive else ["medium"]:
        img = preprocess_image_for_ocr(image_bytes, level)
        for psm in [6,4,3,1]:
            cfg = f"--oem 3 --psm {psm}"
            data = pytesseract.image_to_data(img, config=cfg, output_type=pytesseract.Output.DICT)
            confs = [int(c) for c in data["conf"] if c != "-1"]
            score = (sum(confs)/len(confs) if confs else 0)
            text = clean_text(pytesseract.image_to_string(img, config=cfg))
            score *= len(text)
            if score > best_score:
                best_score = score
                best_text = text

    return best_text

# =====================================================
# --------------- PDF EXTRACTION ----------------------
# =====================================================
def extract_pdf_to_text(pdf_path, aggressive_ocr=True, verbose=True):
    doc = fitz.open(pdf_path)
    pages = []
    stats = {"total_pages":len(doc),"pages_with_ocr":0,"images_processed":0}

    for i,page in enumerate(doc):
        parts = [f"\n{'='*60}\nPAGE {i+1}\n{'='*60}\n"]
        text = clean_text(page.get_text())
        if text:
            parts.append(text)

        images = page.get_images(full=True)
        if images:
            stats["pages_with_ocr"] += 1
            for img in images:
                base = doc.extract_image(img[0])
                stats["images_processed"] += 1
                ocr = ocr_image_with_layout(base["image"], aggressive_ocr)
                if ocr:
                    parts.append("\n[OCR]\n"+ocr)

        pages.append("\n".join(parts))
        if verbose:
            print(f"Page {i+1}/{len(doc)} ✓")

    doc.close()
    return "\n".join(pages), stats

# =====================================================
# ------------- PII MAPPING ENGINE --------------------
# =====================================================
def build_replacement_map(pii_data, dummy_data, output_path):
    replacement_map = {}
    used = set()

    for field, values in pii_data.items():
        values = values if isinstance(values,list) else [values]
        dummy_pool = dummy_data.get(field,[])
        dummy_pool = dummy_pool if isinstance(dummy_pool,list) else [dummy_pool]

        for val in values:
            key = f"{field}::{normalize(val)}"
            if key in replacement_map:
                continue
            available = [d for d in dummy_pool if d not in used]
            dummy = random.choice(available) if available else f"[REDACTED-{field}]"
            used.add(dummy)
            replacement_map[key] = {
                "field": field,
                "original": val,
                "dummy": dummy
            }

    save_json(output_path, replacement_map)
    return replacement_map

def build_master_pii(replacement_map, output_path):
    master = {}
    for k,v in replacement_map.items():
        rk = f"{v['field']}::{normalize(v['dummy'])}"
        master[rk] = {
            "field": v["field"],
            "original": v["dummy"],
            "dummy": v["original"]
        }
    save_json(output_path, master)
    return master

# =====================================================
# ---------------- REPLACEMENT ENGINE -----------------
# =====================================================
def normalize_text(text):
    text = text.lower()
    text = re.sub(r"[^\w\s]"," ",text)
    return re.sub(r"\s+"," ",text).strip()

def preserve_case(orig, repl):
    if orig.isupper():
        return repl.upper()
    if orig[0].isupper():
        return " ".join(w.capitalize() for w in repl.split())
    return repl.lower()

def find_spans(text, target, threshold):
    spans = []
    words = list(re.finditer(r"\S+", text))
    t_norm = normalize_text(target)
    t_len = len(t_norm.split())

    for size in range(max(1,t_len-1), t_len+3):
        for i in range(len(words)-size+1):
            s = words[i].start()
            e = words[i+size-1].end()
            chunk = text[s:e]
            score = fuzz.token_set_ratio(normalize_text(chunk), t_norm)
            if score >= threshold:
                spans.append((s,e,chunk,score))

    spans.sort(key=lambda x:(-x[3],x[0]))
    result = []
    used = []
    for s,e,t,sc in spans:
        if not any(s<u[1] and e>u[0] for u in used):
            used.append((s,e))
            result.append((s,e,t,sc))
    return result

def smart_replace(text, replacement_map, custom_thresholds=None, verbose=False):
    if custom_thresholds is None:
        custom_thresholds = {}

    replacements = []
    log = []

    for entry in replacement_map.values():
        field = entry["field"]
        orig = entry["original"]
        dummy = entry["dummy"]
        threshold = custom_thresholds.get(field,75)

        spans = find_spans(text, orig, threshold)
        for s,e,match,score in spans:
            final = preserve_case(match, dummy)
            replacements.append((s,e,final))
            if verbose:
                log.append({
                    "field":field,
                    "original_value":orig,
                    "matched_text":match,
                    "dummy_value":final,
                    "similarity":score,
                    "position":(s,e)
                })

    replacements.sort(key=lambda x:x[0], reverse=True)
    for s,e,val in replacements:
        text = text[:s] + val + text[e:]

    return (text, log) if verbose else (text, len(replacements))

# =====================================================
# -------------------- MAIN ----------------------------
# =====================================================
def main():
    print("\nPDF SANITIZATION PIPELINE\n")

    if not Path(PDF_PATH).exists():
        print("❌ PDF not found")
        sys.exit(1)

    pii = load_json(PII_FILE)
    dummy = load_json(DUMMY_FILE)

    extracted, stats = extract_pdf_to_text(PDF_PATH)
    EXTRACTED_TEXT_FILE.write_text(extracted, encoding="utf-8")

    replacement_map = build_replacement_map(pii, dummy, REPLACEMENT_PII_FILE)
    build_master_pii(replacement_map, MASTER_PII_FILE)

    sanitized, log = smart_replace(
        extracted,
        replacement_map,
        custom_thresholds=FIELD_THRESHOLDS,
        verbose=True
    )

    SANITIZED_TEXT_FILE.write_text(sanitized, encoding="utf-8")

    if log:
        with open(REPLACEMENT_LOG_FILE,"w",encoding="utf-8") as f:
            for r in log:
                f.write(json.dumps(r,indent=2)+"\n")

    print("\n✅ PIPELINE COMPLETED SUCCESSFULLY")
    print(f"Pages: {stats['total_pages']}")
    print(f"Replacements: {len(log)}")

# =====================================================
# ------------------ RUN ------------------------------
# =====================================================
if __name__ == "__main__":
    main()
