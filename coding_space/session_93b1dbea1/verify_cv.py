#!/usr/bin/env python3
"""Verify the generated CV files exist and check integrity."""
import os
import sys

docx_path = 'CV_Tim_Chu.docx'
pdf_path = 'CV_Tim_Chu.pdf'

results = []

# Check docx
if os.path.exists(docx_path):
    size = os.path.getsize(docx_path)
    results.append(f"[OK] {docx_path} exists, size={size} bytes")
else:
    results.append(f"[ERROR] {docx_path} does NOT exist")
    sys.exit(1)

# Check pdf
if os.path.exists(pdf_path):
    size = os.path.getsize(pdf_path)
    results.append(f"[OK] {pdf_path} exists, size={size} bytes")
else:
    results.append(f"[ERROR] {pdf_path} does NOT exist")
    sys.exit(1)

# Check that files have reasonable sizes (not empty)
if os.path.getsize(docx_path) < 100:
    results.append("[WARNING] docx file seems too small, may be corrupted")
if os.path.getsize(pdf_path) < 100:
    results.append("[WARNING] pdf file seems too small, may be corrupted")

# Check the skills were updated by reading the generate_cv.py
with open('generate_cv.py', 'r') as f:
    content = f.read()

if 'Fullstack Development' in content and 'React, TypeScript, NodeJS, FastAPI' in content:
    results.append("[OK] generate_cv.py contains the new Fullstack Development skills")
else:
    results.append("[ERROR] generate_cv.py missing the new skills - update may have failed")
    sys.exit(1)

print('\n'.join(results))
sys.exit(0)