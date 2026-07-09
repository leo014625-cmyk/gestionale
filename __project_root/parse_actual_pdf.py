import pdfplumber
import sys

pdf_path = "PROMO P0 D250 RM_01.06-30.06.2026.pdf"
output_txt = "pdf_text.txt"

print(f"Reading {pdf_path}...")
try:
    with pdfplumber.open(pdf_path) as pdf:
        all_text = []
        for i, page in enumerate(pdf.pages):
            print(f"Parsing page {i+1}/{len(pdf.pages)}...")
            text = page.extract_text()
            all_text.append(f"--- PAGE {i+1} ---")
            all_text.append(text or "[No Text Extracted]")
        
        with open(output_txt, "w", encoding="utf-8") as f:
            f.write("\n".join(all_text))
    print(f"Done! Raw text saved to {output_txt}")
except Exception as e:
    print(f"Error: {e}")
    sys.exit(1)
