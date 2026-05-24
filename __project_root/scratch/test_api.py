import requests
try:
    r = requests.get('http://127.0.0.1:5050/api/cerca_immagini_prodotto?q=mozzarella', timeout=10)
    print(r.status_code)
    print(r.json())
except Exception as e:
    print(f"Error: {e}")
