from flask import Flask, request, Response
from flask_cors import CORS
import requests
import os
import sqlite3
import json

# ======================
# ✅ ENV
# ======================
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
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
# ✅ OpenAI（主模型🔥）
# ======================
def call_openai(prompt):
    try:
        url = "https://api.openai.com/v1/chat/completions"

        headers = {
            "Authorization": f"Bearer {OPENAI_API_KEY}",
            "Content-Type": "application/json"
        }

        payload = {
            "model": "gpt-4o-mini",
            "messages": [
                {"role": "user", "content": prompt}
            ]
        }

        res = requests.post(url, headers=headers, json=payload)
        data = res.json()

        print("OpenAI RAW:", data)

        if "choices" in data:
            return data["choices"][0]["message"]["content"]

    except Exception as e:
        print("OpenAI error:", e)

    return None


# ======================
# ✅ Gemini（备用）
# ======================
def call_gemini(prompt):
    try:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={GEMINI_API_KEY}"

        payload = {
            "contents": [{"parts": [{"text": prompt}]}]
        }

        res = requests.post(url, json=payload)
        result = res.json()

        print("Gemini RAW:", result)

        if "candidates" in result:
            return result["candidates"][0]["content"]["parts"][0]["text"]

    except Exception as e:
        print("Gemini error:", e)

    return None


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

    print("Google response:", res.status_code, res.text)

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

    print("USER:", user_message)

    # ✅ memory
    save_message(user_id, "user", user_message)
    history = get_history(user_id, 5)

    # ======================
    # ✅ Prompt
    # ======================
    system_instruction = """
You are an AI assistant.

ONLY output JSON when the user explicitly asks to perform an action such as scheduling a meeting.

Otherwise reply normally.

When outputting JSON, DO NOT include explanation text.

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

    print("PROMPT:", prompt)

    # ======================
    # ✅ AI call（OpenAI优先🔥）
    # ======================
    reply = call_openai(prompt)

    if not reply:
        print("Switching to Gemini...")
        reply = call_gemini(prompt)

    print("AI reply:", reply)

    # ======================
    # ✅ Action Parsing
    # ======================
    action_data = None

    if reply and reply.strip().startswith("{"):
        try:
            action_data = json.loads(reply)
            print("Parsed action:", action_data)
        except:
            action_data = None

    # ======================
    # ✅ Execute Action
    # ======================
    if action_data and "action" in action_data:

        if action_data["action"] == "create_calendar_event":

            title = action_data.get("title", "Meeting")
            time = action_data.get("time", "")

            success = create_google_event(title, time)

            if success:
                reply = f"✅ Google Calendar event created: {title}"
            else:
                reply = "❌ Failed to create event"

    # ======================
    # ✅ Final fallback
    # ======================
    if not reply:
        reply = "AI error"

    save_message(user_id, "ai", reply)

    return Response(
        f"<Response><Message>{reply}</Message></Response>",
        mimetype="text/xml"
    )