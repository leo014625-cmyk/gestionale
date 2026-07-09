import requests
import urllib.parse

query = "gambero rosso"
headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/100.0.0.0 Safari/537.36"
}
cookies = {
    "CONSENT": "YES+"
}
url = f"https://www.google.com/search?tbm=isch&q={urllib.parse.quote(query)}"

try:
    r = requests.get(url, headers=headers, cookies=cookies, timeout=5)
    with open("google_output.html", "w", encoding="utf-8") as f:
        f.write(r.text)
    print("Saved HTML to google_output.html. Length:", len(r.text))
except Exception as e:
    print("Error:", e)
