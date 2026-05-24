import urllib.request
import re
import urllib.parse
import ssl

ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE

query = "MOZZARELLA PREGIS"
url = f"https://www.google.com/search?q={urllib.parse.quote(query)}&tbm=isch"
headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36',
    'Cookie': 'CONSENT=YES+cb.20210720-07-p0.en+FX+410;'
}
req = urllib.request.Request(url, headers=headers)
try:
    with urllib.request.urlopen(req, context=ctx) as response:
        html = response.read().decode('utf-8', errors='ignore')
        # match base64 or urls
        imgs = re.findall(r'\[\"(https://encrypted-tbn0\.gstatic\.com/images\?q=tbn:[^\"]+)\"', html)
        for img in imgs[:6]:
            print(img)
except Exception as e:
    print(f"Error: {e}")
