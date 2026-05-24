import requests
import re
import urllib.parse

query = "CACIOTTA ABRUZZO MISTA KG2"
headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/110.0.0.0 Safari/537.36"}

# DuckDuckGo approach
print("Trying DDG...")
res = requests.get(f"https://html.duckduckgo.com/html/?q={urllib.parse.quote(query)}+foto", headers=headers)
imgs = re.findall(r'src="//(external-content\.duckduckgo\.com/iu/\?u=[^"&]+)', res.text)
for img in imgs[:5]:
    print("DDG:", "https://" + img)

# Google approach
print("Trying Google...")
res = requests.get(f"https://www.google.com/search?q={urllib.parse.quote(query)}&tbm=isch", headers=headers)
# Let's try a very broad regex for anything ending in jpg/png
google_imgs = re.findall(r'(https?://[^"\s]+\.(?:jpg|png))', res.text, re.IGNORECASE)
for img in google_imgs[:5]:
    print("Google:", img)
