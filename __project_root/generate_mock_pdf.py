from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas

def create_mock_pdf(filename):
    c = canvas.Canvas(filename, pagesize=letter)
    
    # Intestazione mock
    c.setFont("Helvetica-Bold", 16)
    c.drawString(100, 750, "Fattura Mock / Listino Prodotti")
    
    c.setFont("Helvetica", 12)
    c.drawString(100, 720, "Cliente: Ristorante Test")
    c.drawString(100, 700, "Data: 2026-03-08")
    
    # Righe prodotti (Codice - Nome - ... - Prezzo)
    c.setFont("Helvetica", 10)
    
    # Prodotto 1: Esistente in DB (assumiamo che il DB abbia un prodotto con codice '0000', o si creerà)
    c.drawString(100, 650, "1001   Acqua Minerale Naturale 1L                 0.50")
    
    # Prodotto 2: Esistente, diverso
    c.drawString(100, 630, "1002   Vino Rosso Chianti Classico 75cl           8.50")
    
    # Prodotto 3: Nuovo, codice mai visto
    c.drawString(100, 610, "9099   Birra Artigianale Speziata 33cl            3.20")
    
    c.save()

if __name__ == "__main__":
    create_mock_pdf("mock_import.pdf")
    print("Mock PDF creato!")
