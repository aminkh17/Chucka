#!/usr/bin/env python3
"""Send a PNG to WhatsApp through a local OpenWA gateway."""
import base64, json, os, sys, time, urllib.request, urllib.error

import envload; envload.load_env()  # personal config lives in .env, never in git

BASE = os.environ.get("OPENWA_URL", "http://localhost:2785")
KEY_FILE = os.environ.get("OPENWA_KEY_FILE", os.path.join(os.path.dirname(os.path.abspath(__file__)), "OpenWA/data/.api-key"))
SESSION = os.environ.get("OPENWA_SESSION", "")
CHAT = os.environ.get("WA_TO", "")
DELIVERY_TIMEOUT = int(os.environ.get("WA_DELIVERY_TIMEOUT", "180"))
SETTLE_SECONDS = int(os.environ.get("WA_SETTLE_SECONDS", "20"))

def load_key():
    return open(KEY_FILE).read().strip()

def call(method, path, body=None, timeout=60):
    req = urllib.request.Request(BASE + path, method=method,
                                 data=json.dumps(body).encode() if body is not None else None,
                                 headers={"X-API-Key": API_KEY, "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read() or b"null")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode(errors="ignore")

def main(png):
    if not SESSION or not CHAT:
        sys.exit("Set OPENWA_SESSION and WA_TO in .env (copy .env.example to .env).")
    sessions = call("GET", "/api/sessions")[1]
    sid = next((s["id"] for s in sessions if s["name"] == SESSION), None)
    if not sid:
        sys.exit(f"Session '{SESSION}' not found")

    status = call("GET", f"/api/sessions/{sid}")[1]["status"]
    for attempt in range(3):
        if status == "ready":
            break
        print(f"starting session (attempt {attempt + 1}, status={status})")
        call("POST", f"/api/sessions/{sid}/start")
        for _ in range(60):
            time.sleep(3)
            status = call("GET", f"/api/sessions/{sid}")[1]["status"]
            if status in ("ready", "qr_ready", "failed"):
                break
        if status == "qr_ready":
            sys.exit("Session needs re-linking: scan the QR code in the OpenWA dashboard.")
    if status != "ready":
        sys.exit(f"Session not ready after 3 attempts (status={status}).")

    # WhatsApp Web often reloads its page right after reporting ready; a send queued during that
    # reload can be lost, so let it settle first.
    time.sleep(SETTLE_SECONDS)

    with open(png, "rb") as f:
        b64 = base64.b64encode(f.read()).decode()
    chat_id = CHAT if "@" in CHAT else CHAT.lstrip("+") + "@c.us"
    body = {"chatId": chat_id, "base64": b64, "mimetype": "image/png",
            "filename": os.path.basename(png),
            "caption": f"Chucka — {time.strftime('%a %d %b %Y')}"}
    for attempt in range(3):
        code, resp = call("POST", f"/api/sessions/{sid}/messages/send-image", body,
                          timeout=120)
        if code in (200, 201):
            print("queued", resp["messageId"])
            break
        print(f"attempt {attempt + 1}: {code} {resp}", file=sys.stderr)
        time.sleep(10)
    else:
        sys.exit("send failed")

    # The send call returns once WhatsApp Web has queued the message; the media upload happens
    # afterwards. Keep the gateway up until WhatsApp confirms delivery.
    msg_id = resp["messageId"]
    stored_chat = msg_id.split("_")[1]
    status = "sent"
    for _ in range(DELIVERY_TIMEOUT // 3):
        time.sleep(3)
        _, found = call("GET", f"/api/sessions/{sid}/messages?chatId={stored_chat}"
                               f"&messageId={msg_id}&inlineMedia=false&limit=1")
        rows = found.get("messages", []) if isinstance(found, dict) else []
        status = rows[0]["status"] if rows else status
        if status in ("delivered", "read"):
            print("delivered", msg_id, status)
            return
        if status == "failed":
            sys.exit(f"WhatsApp reported the message as failed: {msg_id}")
    sys.exit(f"Not confirmed delivered after {DELIVERY_TIMEOUT}s (status={status}). "
             "Is the recipient's phone offline?")

if __name__ == "__main__":
    API_KEY = load_key()
    main(sys.argv[1])
