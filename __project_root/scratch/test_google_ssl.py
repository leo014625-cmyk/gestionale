import urllib.request
import re
import urllib.parse
import ssl

ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE

query = "MOZZARELLA PREGIS"
url = f"https://www.google.com/search?q={urllib.parse.quote(query)}&tbm=isch"
req = urllib.request.Request(url, headers={'User-Agent': 'Googlebot/2.1 (+http://www.google.com/bot.html)'})
try:
    with urllib.request.urlopen(req, context=ctx) as response:
        html = response.read().decode('utf-8', errors='ignore')
        imgs = re.findall(r'<img.*?src="(https?://encrypted-tbn[0-9]\.gstatic\.com/images\?q=tbn:[^&"\'\s]+)"', html)
        for img in imgs[:6]:
            print(img)
except Exception as e:
    print(f"Error: {e}")
