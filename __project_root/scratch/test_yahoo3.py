import requests
import urllib.parse
import re

query = "MOZZARELLA PREGIS"
headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/114.0.0.0 Safari/537.36'
}
url = f"https://images.search.yahoo.com/search/images?p={urllib.parse.quote(query)}"
r = requests.get(url, headers=headers)

with open("scratch/yahoo.html", "w") as f:
    f.write(r.text)

imgs = re.findall(r'imgurl=&quot;(.*?)&quot;', r.text)
print("regex 1 count:", len(imgs))

imgs2 = re.findall(r'src="(https://tse[0-9]\.mm\.bing\.net[^"]+)"', r.text)
print("regex 2 count:", len(imgs2))
for i in imgs2[:3]: print(i)

