import requests, json, urllib.parse
query = "MOZZARELLA PREGIS"
url = f"https://images.search.yahoo.com/search/images?p={urllib.parse.quote(query)}"
headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/114.0.0.0 Safari/537.36"}
r = requests.get(url, headers=headers)
import re
imgs = re.findall(r'"imgurl":"([^"]+)"', r.text)
print(len(imgs))
for img in imgs[:6]: print(img.replace('\\/', '/'))
