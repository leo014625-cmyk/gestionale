import urllib.request
import re
import urllib.parse
query = "MOZZARELLA PREGIS"
url = f"https://www.google.com/search?q={urllib.parse.quote(query)}&tbm=isch"
req = urllib.request.Request(url, headers={'User-Agent': 'Googlebot/2.1 (+http://www.google.com/bot.html)'})
try:
    with urllib.request.urlopen(req) as response:
        html = response.read().decode('utf-8')
        # Google often embeds small thumbnails inline as base64 or plain URLs
        imgs = re.findall(r'<img.*?src="(https?://encrypted-tbn[0-9]\.gstatic\.com/images\?q=tbn:[^&"\'\s]+)"', html)
        for img in imgs[:5]:
            print(img)
except Exception as e:
    print(f"Error: {e}")
