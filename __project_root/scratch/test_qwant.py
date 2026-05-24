import requests
import urllib.parse

query = "MOZZARELLA PREGIS"
headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/114.0.0.0 Safari/537.36'
}
url = f"https://api.qwant.com/v3/search/images?q={urllib.parse.quote(query)}&count=6&locale=it_IT"
try:
    r = requests.get(url, headers=headers)
    print(r.status_code)
    data = r.json()
    for item in data.get("data", {}).get("result", {}).get("items", []):
        print(item.get("media"))
except Exception as e:
    print(e)
