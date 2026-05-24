import requests
import re
import urllib.parse
query = "MOZZARELLA PREGIS"
headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
res = requests.get(f"https://html.duckduckgo.com/html/?q={urllib.parse.quote(query)}", headers=headers)
imgs = re.findall(r'src="//(external-content\.duckduckgo\.com/iu/\?u=[^"&]+)', res.text)
for img in imgs[:5]:
    print("https://" + img)
