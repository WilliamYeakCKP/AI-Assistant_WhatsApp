from flask import Flask, request, Response
from flask_cors import CORS
import requests
import os
import sqlite3
import json
from datetime import datetime, timedelta

# ======================
# ✅ ENV
# ======================
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

GOOGLE_REFRESH_TOKEN = os.environ.get("GOOGLE_REFRESH_TOKEN")
GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID")
GOOGLE_CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET")

app = Flask(__name__)
CORS(app)

# ======================
# ✅ GLOBAL（简化 demo）
# ======================
last_event_id = None

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
# ✅ TOKEN REFRESH 🔥
# ======================
def refresh_access_token():
    try:
        url = "https://oauth2.googleapis.com/token"

        payload = {
            "client_id": GOOGLE_CLIENT_ID,
            "client_secret": GOOGLE_CLIENT_SECRET,
            "refresh_token": GOOGLE_REFRESH_TOKEN,
            "grant_type": "refresh_token"
        }

        res = requests.post(url, data=payload)
        data = res.json()

        print("Refresh:", data)

        return data.get("access_token")

    except Exception as e:
        print("Refresh error:", e)
        return None


# ======================
# ✅ OPENAI（主）
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
            "messages": [{"role": "user", "content": prompt}]
        }

        res = requests.post(url, headers=headers, json=payload)
        data = res.json()

        print("OpenAI:", data)

        if "choices" in data:
            return data["choices"][0]["message"]["content"]

    except Exception as e:
        print("OpenAI error:", e)

    return None


# ======================
# ✅ GOOGLE ACTIONS
# ======================
def create_event(title, time_str):
    global last_event_id

    access_token = refresh_access_token()

    url = "https://www.googleapis.com/calendar/v3/calendars/primary/events"

    headers = {
        "Authorization": f"Bearer {access_token}",
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

    print("Create:", res.status_code, res.text)

    if res.status_code == 200:
        event = res.json()
        last_event_id = event.get("id")
        return True

    return False


def update_event(new_time):
    global last_event_id

    if not last_event_id:
        return False

    access_token = refresh_access_token()

    url = f"https://www.googleapis.com/calendar/v3/calendars/primary/events/{last_event_id}"

    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json"
    }

    payload = {
        "start": {
            "dateTime": new_time,
            "timeZone": "Asia/Kuala_Lumpur"
        },
        "end": {
            "dateTime": new_time,
            "timeZone": "Asia/Kuala_Lumpur"
        }
    }

    res = requests.patch(url, headers=headers, json=payload)

    print("Update:", res.status_code)

    return res.status_code == 200


def delete_event():
    global last_event_id

    if not last_event_id:
        return False

    access_token = refresh_access_token()

    url = f"https://www.googleapis.com/calendar/v3/calendars/primary/events/{last_event_id}"

    headers = {
        "Authorization": f"Bearer {access_token}"
    }

    res = requests.delete(url, headers=headers)

    print("Delete:", res.status_code)

    return res.status_code == 204


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

    save_message(user_id, "user", user_message)
    history = get_history(user_id, 5)

    # ✅ 动态时间
    current_time = datetime.now().isoformat()

    system_instruction = f"""
You are an AI assistant.

Current date: {current_time}

Supported actions:
- create_calendar_event
- update_calendar_event
- delete_calendar_event

Always:
- Use FUTURE time
- Use correct year

Examples:

Create:
{{"action": "create_calendar_event", "title": "Meeting", "time": "YYYY-MM-DDTHH:MM:SS"}}

Move:
{{"action": "update_calendar_event", "time": "YYYY-MM-DDTHH:MM:SS"}}

Delete:
{{"action": "delete_calendar_event"}}
"""

    prompt = system_instruction + "\n\n"

    for msg in history:
        prompt += msg + "\n"

    prompt += user_message

    reply = call_openai(prompt)

    print("AI:", reply)

    # ✅ JSON parse
    action_data = None

    if reply and reply.strip().startswith("{"):
        try:
            action_data = json.loads(reply)
        except:
            action_data = None

    # ✅ EXECUTE
    if action_data and "action" in action_data:

        action = action_data["action"]

        if action == "create_calendar_event":

            title = action_data.get("title", "Meeting")
            time_str = action_data.get("time", "")

            try:
                event_time = datetime.fromisoformat(time_str)

                if event_time < datetime.now():
                    event_time = datetime.now() + timedelta(days=1)
                    event_time = event_time.replace(hour=15, minute=0, second=0)

                time_str = event_time.isoformat()

            except:
                time_str = (datetime.now() + timedelta(days=1)).isoformat()

            if create_event(title, time_str):
                reply = f"✅ Created: {title} at {time_str}"
            else:
                reply = "❌ Create failed"

        elif action == "update_calendar_event":

            new_time = action_data.get("time", "")

            if update_event(new_time):
                reply = "✅ Event moved"
            else:
                reply = "❌ Move failed (no event?)"

        elif action == "delete_calendar_event":

            if delete_event():
                reply = "✅ Event deleted"
            else:
                reply = "❌ Delete failed (no event?)"

    if not reply:
        reply = "AI error"

    save_message(user_id, "ai", reply)

    return Response(
        f"<Response><Message>{reply}</Message></Response>",
        mimetype="text/xml"
    )