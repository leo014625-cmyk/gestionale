import urllib.request
import re
import urllib.parse
import ssl

ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE

query = "MOZZARELLA PREGIS"
url = f"https://www.google.com/search?q={urllib.parse.quote(query)}&tbm=isch"
req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36'})
try:
    with urllib.request.urlopen(req, context=ctx) as response:
        html = response.read().decode('utf-8', errors='ignore')
        with open("scratch/google_test.html", "w") as f: f.write(html)
except Exception as e:
    pass
