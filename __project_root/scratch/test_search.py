import requests
import urllib.parse
query = "MOZZARELLA PREGIS"
url = f"http://127.0.0.1:5050/api/cerca_immagini_prodotto?q={urllib.parse.quote(query)}"
r = requests.get(url)
print(r.text)
