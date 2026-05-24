import requests, re, json
import urllib.parse
query = "MOZZARELLA PREGIS"
url = f"https://www.google.com/search?q={urllib.parse.quote(query)}&tbm=isch"
headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
r = requests.get(url, headers=headers)
matches = re.findall(r"\[\"https://encrypted-tbn0\.gstatic\.com/images\?q=tbn:[^\"]+\"", r.text)
for m in matches[:6]: print(m.strip('["'))
