import sys
sys.path.append('.')
from app import parse_offers_from_pdf

offers = parse_offers_from_pdf("scratch/debug_scadenze.pdf")
for o in offers[:5]:
    print(o)
