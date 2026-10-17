#!/usr/bin/env python3
"""Send a voice note (WhatsApp PTT bubble) through the local OpenWA gateway."""
import base64, os, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import send_whatsapp as wa  # noqa: E402  (reuses session handling, call(), SETTLE_SECONDS)

PTT_MIMETYPE = "audio/ogg; codecs=opus"
DELIVERY_TIMEOUT = int(os.environ.get("WA_DELIVERY_TIMEOUT", "180"))


def main(audio):
    wa.API_KEY = wa.load_key()
    sessions = wa.call("GET", "/api/sessions")[1]
    sid = next((s["id"] for s in sessions if s["name"] == wa.SESSION), None)
    if not sid:
        sys.exit(f"Session '{wa.SESSION}' not found")

    status = wa.call("GET", f"/api/sessions/{sid}")[1]["status"]
    for attempt in range(3):
        if status == "ready":
            break
        print(f"starting session (attempt {attempt + 1}, status={status})")
        wa.call("POST", f"/api/sessions/{sid}/start")
        for _ in range(60):
            time.sleep(3)
            status = wa.call("GET", f"/api/sessions/{sid}")[1]["status"]
            if status in ("ready", "qr_ready", "failed"):
                break
        if status == "qr_ready":
            sys.exit("Session needs re-linking: scan the QR code in the OpenWA dashboard.")
    if status != "ready":
        sys.exit(f"Session not ready after 3 attempts (status={status}).")

    time.sleep(wa.SETTLE_SECONDS)

    with open(audio, "rb") as f:
        b64 = base64.b64encode(f.read()).decode()
    chat_id = wa.CHAT if "@" in wa.CHAT else wa.CHAT.lstrip("+") + "@c.us"
    body = {"chatId": chat_id, "base64": b64, "mimetype": PTT_MIMETYPE,
            "ptt": True, "filename": os.path.basename(audio)}

    for attempt in range(3):
        code, resp = wa.call("POST", f"/api/sessions/{sid}/messages/send-audio", body, timeout=180)
        if code in (200, 201):
            print("queued", resp["messageId"])
            break
        print(f"attempt {attempt + 1}: {code} {resp}", file=sys.stderr)
        time.sleep(10)
    else:
        sys.exit("voice send failed")

    msg_id = resp["messageId"]
    stored_chat = msg_id.split("_")[1]
    status = "sent"
    for _ in range(DELIVERY_TIMEOUT // 3):
        time.sleep(3)
        _, found = wa.call("GET", f"/api/sessions/{sid}/messages?chatId={stored_chat}"
                                  f"&messageId={msg_id}&inlineMedia=false&limit=1")
        rows = found.get("messages", []) if isinstance(found, dict) else []
        status = rows[0]["status"] if rows else status
        if status in ("delivered", "read"):
            print("delivered", msg_id, status)
            return
        if status == "failed":
            sys.exit(f"WhatsApp reported the voice note as failed: {msg_id}")
    sys.exit(f"Voice note not confirmed delivered after {DELIVERY_TIMEOUT}s (status={status}).")


if __name__ == "__main__":
    main(sys.argv[1])
