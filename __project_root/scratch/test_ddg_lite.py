import requests, re, urllib.parse
query = "MOZZARELLA PREGIS"
url = f"https://lite.duckduckgo.com/lite/"
headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/114.0.0.0 Safari/537.36"}
data = {"q": query + " image"}
r = requests.post(url, headers=headers, data=data)
imgs = re.findall(r'src=\"(.*?\.jpg)\"', r.text)
print(len(imgs))
for img in imgs[:6]: print(img)
