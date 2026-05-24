import requests, re, urllib.parse
query = "MOZZARELLA PREGIS"
url = f"https://www.bing.com/images/search?q={urllib.parse.quote(query)}"
headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/114.0.0.0 Safari/537.36"}
cookies = {"SRCHD": "AF=NOFORM"}
r = requests.get(url, headers=headers, cookies=cookies)
imgs = re.findall(r'murl&quot;:&quot;([^&]+?)&quot;', r.text)
print(len(imgs))
for img in imgs[:6]: print(img)
