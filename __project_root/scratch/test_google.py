import requests
import urllib.parse
query = "MOZZARELLA"
headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
res = requests.get(f"https://www.google.com/search?q={query}&tbm=isch", headers=headers)
with open("scratch/google_dump.html", "w") as f:
    f.write(res.text)
