from flask import Flask, request, Response
from flask_cors import CORS
import requests
import os
import sqlite3
import json

# ✅ ENV
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
SERP_API_KEY = os.environ.get("SERP_API_KEY")
GOOGLE_ACCESS_TOKEN = os.environ.get("GOOGLE_ACCESS_TOKEN")

app = Flask(__name__)
CORS(app)

# ======================
# ✅ SQLite
# ======================
def init_db():
    conn = sqlite3.connect("chat.db")
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS chat_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT,
            role TEXT,
            message TEXT
        )
    """)

    conn.commit()
    conn.close()

init_db()


def save_message(user_id, role, message):
    conn = sqlite3.connect("chat.db")
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO chat_history (user_id, role, message) VALUES (?, ?, ?)",
        (user_id, role, message)
    )
    conn.commit()
    conn.close()


def get_history(user_id, limit=5):
    conn = sqlite3.connect("chat.db")
    cursor = conn.cursor()

    cursor.execute(
        "SELECT message FROM chat_history WHERE user_id = ? ORDER BY id DESC LIMIT ?",
        (user_id, limit)
    )

    rows = cursor.fetchall()
    conn.close()

    rows.reverse()
    return [r[0] for r in rows]


# ======================
# ✅ Google Calendar
# ======================
def create_google_event(title, time_str):
    url = "https://www.googleapis.com/calendar/v3/calendars/primary/events"

    headers = {
        "Authorization": f"Bearer {GOOGLE_ACCESS_TOKEN}",
        "Content-Type": "application/json"
    }

    payload = {
        "summary": title,
        "start": {
            "dateTime": time_str,
            "timeZone": "Asia/Kuala_Lumpur"
        },
        "end": {
            "dateTime": time_str,
            "timeZone": "Asia/Kuala_Lumpur"
        }
    }

    res = requests.post(url, headers=headers, json=payload)

    return res.status_code == 200


# ======================
# ✅ CHAT
# ======================
@app.route("/chat", methods=["POST"])
def chat():

    user_id = (
        request.values.get("From")
        or (request.json.get("From") if request.is_json else None)
        or "test_user"
    )

    user_message = (
        request.values.get("Body")
        or (request.json.get("message") if request.is_json else None)
        or ""
    )

    save_message(user_id, "user", user_message)
    history = get_history(user_id, 5)

    # ✅ prompt
    system_instruction = """
You are an AI assistant.

ONLY output JSON when the user explicitly asks to perform an action like scheduling a meeting.

Otherwise, reply normally.

Example JSON:
{
  "action": "create_calendar_event",
  "title": "...",
  "time": "..."
}
"""

    prompt = system_instruction + "\n\n"

    for msg in history:
        prompt += msg + "\n"

    prompt += user_message

    # ✅ Gemini
    reply = None

    try:
        url = f"https://generativelanguage.googleapis.com/v1/models/gemini-3.5-flash:generateContent?key={GEMINI_API_KEY}"

        payload = {
            "contents": [{"parts": [{"text": prompt}]}]
        }

        res = requests.post(url, json=payload)
        result = res.json()

        if "candidates" in result:
            reply = result["candidates"][0]["content"]["parts"][0]["text"]

    except:
        pass

    # ✅ parsing action
    action_data = None

    if reply and reply.strip().startswith("{"):
        try:
            action_data = json.loads(reply)
        except:
            action_data = None

    if action_data and "action" in action_data:

        if action_data["action"] == "create_calendar_event":
            title = action_data.get("title", "Meeting")
            time = action_data.get("time", "")

            success = create_google_event(title, time)

            if success:
                reply = f"✅ Google Calendar event created: {title}"
            else:
                reply = "❌ Failed to create event"

    if not reply:
        reply = "AI error"

    save_message(user_id, "ai", reply)

    return Response(
        f"<Response><Message>{reply}</Message></Response>",
        mimetype="text/xml"
    )