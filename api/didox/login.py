
from http.server import BaseHTTPRequestHandler
import json
import re
import urllib.request
import urllib.error

DIDOX_URL = "https://api2.didox.uz"

class handler(BaseHTTPRequestHandler):

    def do_POST(self):
        try:
            length = int(self.headers.get("Content-Length", "0"))

            if length <= 0 or length > 4096:
                return self.reply(400, {"error": "So'rov noto'g'ri"})

            data = json.loads(self.rfile.read(length))
            inn = str(data.get("inn", "")).strip()
            password = data.get("password", "")

            if not re.fullmatch(r"\d{9}", inn):
                return self.reply(400, {"error": "STIR 9 raqam bo'lishi kerak"})

            if not isinstance(password, str) or not password:
                return self.reply(400, {"error": "Parolni kiriting"})

            payload = json.dumps({"password": password}).encode("utf-8")

            req = urllib.request.Request(
                DIDOX_URL + "/v1/auth/" + inn + "/password/uz",
                data=payload,
                headers={
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                    "Accept-Language": "uz",
                    "User-Agent": "Mozilla/5.0"
                },
                method="POST"
            )

            try:
                with urllib.request.urlopen(req, timeout=25) as response:
                    result = json.load(response)

            except urllib.error.HTTPError as error:
                if error.code == 423:
                    return self.reply(423, {
                        "error": "Didox kirishni bloklagan. Qayta urinmang."
                    })

                if error.code in (400, 401, 403, 422):
                    return self.reply(401, {
                        "error": "STIR yoki parol noto'g'ri"
                    })

                if error.code == 429:
                    return self.reply(429, {
                        "error": "Ko'p urinish. Keyinroq urinib ko'ring."
                    })

                return self.reply(502, {
                    "error": "Didox serveri HTTP " + str(error.code)
                })

            token = result.get("token")

            if not token:
                token = (result.get("data") or {}).get("token")

            if not token:
                token = (result.get("user") or {}).get("token")

            if not token:
                return self.reply(502, {
                    "error": "Didox token qaytarmadi"
                })

            return self.reply(200, {
                "ok": True,
                "inn": inn
            })

        except Exception:
            return self.reply(502, {
                "error": "Didox bilan ulanishda xatolik"
            })

    def reply(self, status, data):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")

        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
