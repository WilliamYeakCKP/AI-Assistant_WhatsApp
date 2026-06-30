from flask import Flask, request, jsonify
from flask_cors import CORS
import requests
import os
import sqlite3
import json
from datetime import datetime

# ======================================
# ENV
# ======================================

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
SERP_API_KEY = os.getenv("SERP_API_KEY")
GOOGLE_ACCESS_TOKEN = os.getenv("GOOGLE_ACCESS_TOKEN")

app = Flask(__name__)
CORS(app)

# ======================================
# DATABASE
# ======================================

DB_NAME = "chat.db"


def init_db():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()

    c.execute('''
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT,
            role TEXT,
            message TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    conn.commit()
    conn.close()


init_db()


def save_message(user_id, role, message):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute(
        "INSERT INTO messages (user_id, role, message) VALUES (?, ?, ?)",
        (user_id, role, message)
    )
    conn.commit()
    conn.close()



def get_history(user_id, limit=6):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()

    c.execute(
        """
        SELECT role, message
        FROM messages
        WHERE user_id=?
        ORDER BY id DESC
        LIMIT ?
        """,
        (user_id, limit)
    )

    rows = c.fetchall()
    conn.close()

    rows.reverse()

    history = []
    for role, msg in rows:
        history.append({
            "role": role,
            "content": msg
        })

    return history

# ======================================
# SERP SEARCH
# ======================================


def search_google(query):
    if not SERP_API_KEY:
        return "SERP_API_KEY not configured"

    try:
        params = {
            "q": query,
            "api_key": SERP_API_KEY,
            "engine": "google",
            "num": 5
        }

        r = requests.get(
            "https://serpapi.com/search.json",
            params=params,
            timeout=20
        )

        data = r.json()

        results = []

        for item in data.get("organic_results", [])[:5]:
            results.append({
                "title": item.get("title"),
                "link": item.get("link"),
                "snippet": item.get("snippet")
            })

        return json.dumps(results, ensure_ascii=False)

    except Exception as e:
        return f"Search error: {str(e)}"

# ======================================
# OPENAI
# ======================================


def call_openai(messages):

    headers = {
        "Authorization": f"Bearer {OPENAI_API_KEY}",
        "Content-Type": "application/json"
    }

    payload = {
        "model": "gpt-4o-mini",
        "messages": messages,
        "temperature": 0.7
    }

    response = requests.post(
        "https://api.openai.com/v1/chat/completions",
        headers=headers,
        json=payload,
        timeout=60
    )

    response.raise_for_status()

    return response.json()["choices"][0]["message"]["content"]

# ======================================
# GOOGLE CALENDAR
# ======================================

last_event_id = None


def create_google_event(title, time_str):
    global last_event_id

    if not GOOGLE_ACCESS_TOKEN:
        return {
            "success": False,
            "message": "GOOGLE_ACCESS_TOKEN missing"
        }

    start_time = datetime.fromisoformat(time_str)
    end_time = start_time.replace(hour=start_time.hour + 1)

    event = {
        "summary": title,
        "start": {
            "dateTime": start_time.isoformat(),
            "timeZone": "Asia/Kuala_Lumpur"
        },
        "end": {
            "dateTime": end_time.isoformat(),
            "timeZone": "Asia/Kuala_Lumpur"
        }
    }

    headers = {
        "Authorization": f"Bearer {GOOGLE_ACCESS_TOKEN}",
        "Content-Type": "application/json"
    }

    r = requests.post(
        "https://www.googleapis.com/calendar/v3/calendars/primary/events",
        headers=headers,
        json=event
    )

    if r.status_code in [200, 201]:
        data = r.json()
        last_event_id = data["id"]

        return {
            "success": True,
            "event": data
        }

    return {
        "success": False,
        "message": r.text
    }

# ======================================
# CHAT
# ======================================


@app.route("/chat", methods=["POST"])
def chat():

    data = request.json

    user_id = data.get("user_id", "default")
    user_message = data.get("message", "")

    save_message(user_id, "user", user_message)

    history = get_history(user_id)

    need_search = any(
        word in user_message.lower()
        for word in [
            "search",
            "google",
            "latest",
            "news",
            "current",
            "find"
        ]
    )

    search_context = ""

    if need_search:
        search_context = search_google(user_message)

    system_prompt = f"""
You are an AI assistant.

Current DateTime: {datetime.now()}

IMPORTANT:
- Normal conversation must be answered normally.
- ONLY output JSON if user requests calendar actions.
- If search results exist, use them.

SEARCH RESULTS:
{search_context}

Calendar JSON examples:

{{
  \"action\":\"create_calendar_event\",
  \"title\":\"Meeting\",
  \"time\":\"2026-07-01T15:00:00\"
}}

{{
  \"action\":\"delete_calendar_event\"
}}

{{
  \"action\":\"update_calendar_event\",
  \"time\":\"2026-07-01T17:00:00\"
}}
"""

    messages = [{
        "role": "system",
        "content": system_prompt
    }]

    messages.extend(history)

    ai_reply = call_openai(messages)

    try:
        action_data = json.loads(ai_reply)

        if action_data.get("action") == "create_calendar_event":
            result = create_google_event(
                action_data.get("title", "Meeting"),
                action_data.get("time")
            )

            save_message(user_id, "assistant", json.dumps(result))
            return jsonify(result)

    except:
        pass

    save_message(user_id, "assistant", ai_reply)

    return jsonify({
        "reply": ai_reply
    })

# ======================================
# HEALTH CHECK
# ======================================


@app.route("/")
def home():
    return "AI Assistant Running ✅"


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
