import re
import sys

def test_parse(lines):
    offers = []
    
    # regex per riga base (Codice ... Descrizione ... UM ... Qtà ... Prezzo)
    # L'utente ha codice a 8 cifre "00200473" o "11400048"
    # La descrizione può essere staccata.
    
    current_code = None
    current_desc = ""
    current_price = None

    code_re = re.compile(r"^(\d{6,10})")
    
    # Prezzo is usually after Qtà, looking like 12,84 or 9,59 and before Pz/Car or Iva
    # Match something like " 12,84 " or " 9,59 " at the end of the line numeric clusters
    # Or just look for the first match of price-like near the end.
    
    for row_text in lines:
        row_text = row_text.strip()
        if not row_text:
            continue
            
        # Is this a new product line? (Starts with Code)
        m_code = code_re.match(row_text)
        if m_code:
            # save previous
            if current_code and current_price:
                offers.append((current_code, current_desc.strip(), current_price))
            
            current_code = m_code.group(1)
            rest = row_text[len(current_code):].strip()
            
            # Extract price. Look for standard patterns like " PZ | 2,600 | 7,55 | 2.6 | 10"
            # Or from our horizontal parser: "00200473 | POLLO PETTO... | KG | 2,600 | 7,55 | 2.6 | 10"
            # Actually let's assume raw text splits by spaces: "00200473 POLLO PETTO GR650X4 S/V F V.FATTORIA KG 2,600 7,55 2.6 10"
            
            parts = rest.split()
            # The price is usually the 3rd or 4th item from the end if it's "Qtà Prezzo Pz/Car Iva" -> 2,600 7,55 2.6 10
            # Let's find UM (PZ or KG) to split description from numbers.
            um_idx = -1
            for i, p in enumerate(parts):
                if p in ("PZ", "KG", "BT", "CT", "LT"):
                    um_idx = i
                    break
            
            if um_idx != -1:
                current_desc = " ".join(parts[:um_idx])
                numeric_parts = parts[um_idx+1:]
                if len(numeric_parts) >= 2:
                    current_price = numeric_parts[1] # usually Qtà is 0, Prezzo is 1
            else:
                current_desc = rest
                current_price = None
                
        else:
            # This might be an overflow description line for the current product
            # e.g. "PECORINO ROMANO DOP NERO 1/8 KG3,5 CAO"
            if current_code:
                # ignore headers or footers
                if "Pag." not in row_text and "Spett.le" not in row_text and "Codice Art" not in row_text:
                    if row_text.isupper() or any(char.isdigit() for char in row_text):
                        current_desc += " " + row_text

    if current_code and current_price:
        offers.append((current_code, current_desc.strip(), current_price))
        
    for o in offers:
        print(f"[{o[0]}] {o[1]} => €{o[2]}")

if __name__ == "__main__":
    test_lines = [
        "00200473 POLLO PETTO GR650X4 S/V F V.FATTORIA KG 2,600 7,55 2.6 10",
        "01050581 KG 3,500 14,99 3.5 4",
        "PECORINO ROMANO DOP NERO 1/8 KG3,5 CAO",
        "04050111 PZ 1,000 3,74 1.0 22",
        "ALBUME UOVA TERRA PAST S/Z BRIK KG1F AIA",
        "23000459 FARINA 00 6384 PANETTONE W370/390 KG12,5 PZ 1,000 23,52 1.0 4"
    ]
    test_parse(test_lines)
