import requests, re, urllib.parse
query = "MOZZARELLA PREGIS"
url = f"https://www.bing.com/images/search?q={urllib.parse.quote(query)}"
headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/114.0.0.0 Safari/537.36"}
r = requests.get(url, headers=headers)
imgs = re.findall(r'murl&quot;:&quot;(https?://[^&]+?)&quot;', r.text)
print(len(imgs))
for img in imgs[:6]: print(img)
