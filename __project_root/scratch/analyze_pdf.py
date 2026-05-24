import pdfplumber
import sys

try:
    with pdfplumber.open("scratch/debug_scadenze.pdf") as pdf:
        page = pdf.pages[0]
        tables = page.extract_tables()
        print(f"Number of tables found: {len(tables)}")
        if tables:
            for i, table in enumerate(tables):
                print(f"\n--- TABLE {i+1} ---")
                for j, row in enumerate(table[:15]): # print first 15 rows
                    print(f"Row {j}: {row}")
        else:
            print("No tables found. Printing raw text layout:")
            print(page.extract_text(layout=True)[:1000])
except Exception as e:
    print(f"Error: {e}")
