import requests
import re
import urllib.parse
query = "MOZZARELLA PREGIS"
headers = {"User-Agent": "Mozilla/5.0 (Windows NT 6.1; WOW64; rv:40.0) Gecko/20100101 Firefox/40.1"}
url = f"https://www.google.com/search?q={urllib.parse.quote(query)}&tbm=isch"
res = requests.get(url, headers=headers)
with open("scratch/google_dump2.html", "w") as f:
    f.write(res.text)
