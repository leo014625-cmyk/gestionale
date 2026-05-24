import requests
import re
import urllib.parse

query = "MOZZARELLA PREGIS"
headers = {"User-Agent": "Mozilla/5.0 (Windows NT 6.1; WOW64; rv:40.0) Gecko/20100101 Firefox/40.1"}
url = f"https://www.google.com/search?q={urllib.parse.quote(query)}&tbm=isch"
res = requests.get(url, headers=headers)
imgs = re.findall(r'<img.*?src="(https?://encrypted-tbn[0-9]\.gstatic\.com/images\?q=tbn:[^&"\'\s]+)"', res.text)
for img in imgs[:5]:
    print(img)
