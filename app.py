from flask import Flask, request, Response
from flask_cors import CORS
import requests
import os
import sqlite3
import json
from datetime import datetime, timedelta

# ======================
# ENV
# ======================
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
GOOGLE_ACCESS_TOKEN = os.environ.get("GOOGLE_ACCESS_TOKEN")
SERP_API_KEY = os.environ.get("SERP_API_KEY")

app = Flask(__name__)
CORS(app)

# ======================
# MEMORY
# ======================

def init_db():
    conn = sqlite3.connect("chat.db")

    conn.execute("""
        CREATE TABLE IF NOT EXISTS chat_history(
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

    conn.execute(
        """
        INSERT INTO chat_history
        (user_id, role, message)
        VALUES (?, ?, ?)
        """,
        (user_id, role, message)
    )

    conn.commit()
    conn.close()


def get_history(user_id, limit=6):

    conn = sqlite3.connect("chat.db")

    rows = conn.execute(
        """
        SELECT role,message
        FROM chat_history
        WHERE user_id=?
        ORDER BY id DESC
        LIMIT ?
        """,
        (user_id, limit)
    ).fetchall()

    conn.close()

    rows.reverse()

    history = ""

    for role, msg in rows:
        history += f"{role}: {msg}\n"

    return history


# ======================
# SEARCH
# ======================

search_cache = {}

def search_google(query):

    if query in search_cache:
        print("Using cached search")
        return search_cache[query]

    try:

        url = "https://serpapi.com/search.json"

        params = {
            "q": query,
            "api_key": SERP_API_KEY,
            "num": 5
        }

        res = requests.get(
            url,
            params=params,
            timeout=10
        )

        data = res.json()

        snippets = []

        for item in data.get("organic_results", [])[:5]:

            title = item.get("title", "")
            snippet = item.get("snippet", "")

            snippets.append(
                f"{title}: {snippet}"
            )

        result = "\n".join(snippets)

        search_cache[query] = result

        return result

    except Exception as e:

        print("Search error:", e)

        return ""


# ======================
# OPENAI
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
                {
                    "role": "user",
                    "content": prompt
                }
            ]
        }

        res = requests.post(
            url,
            headers=headers,
            json=payload,
            timeout=30
        )

        data = res.json()

        print("OpenAI:", data)

        if "choices" in data:
            return data["choices"][0]["message"]["content"]

    except Exception as e:
        print("OpenAI error:", e)

    return None


# ======================
# GOOGLE CALENDAR
# ======================

last_event_id = None


def create_google_event(title, time_str):

    global last_event_id

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
            "dateTime": (
                datetime.fromisoformat(time_str)
                + timedelta(hours=1)
            ).isoformat(),
            "timeZone": "Asia/Kuala_Lumpur"
        }
    }

    res = requests.post(
        url,
        headers=headers,
        json=payload
    )

    print("Google Create:", res.status_code)
    print(res.text)

    if res.status_code == 200:
        event = res.json()

        last_event_id = event.get("id")

        return True

    return False


# ======================
# CHAT
# ======================

@app.route("/chat", methods=["POST"])
def chat():

    user_id = (
        request.values.get("From")
        or (
            request.json.get("From")
            if request.is_json else None
        )
        or "test_user"
    )

    user_message = (
        request.values.get("Body")
        or (
            request.json.get("message")
            if request.is_json else None
        )
        or ""
    )

    print("USER:", user_message)

    save_message(
        user_id,
        "user",
        user_message
    )

    history = get_history(user_id)

    search_words = [
        "latest",
        "news",
        "today",
        "current",
        "price",
        "stock",
        "weather",
        "search",
        "find",
        "who is",
        "what is microsoft",
        "what is openai"
    ]

    needs_search = any(
        word in user_message.lower()
        for word in search_words
    )

    search_result = ""

    if needs_search:

        print("SEARCH TRIGGERED")

        search_result = search_google(user_message)

        print(search_result)

    now_str = datetime.now().isoformat()

    system_instruction = f"""
You are an AI assistant.

Current DateTime:
{now_str}

IMPORTANT:

Normal conversation MUST be answered normally.

Examples:

hi
hello
how are you
who are you
what is my name

These MUST NOT return JSON.

ONLY return JSON if the user explicitly wants a calendar action.
If Web Search Results contains information,
use it when answering questions about news,
current events, weather, stock prices and recent topics.

Examples:

Schedule a meeting tomorrow at 3pm

{{
  "action":"create_calendar_event",
  "title":"Meeting",
  "time":"2026-06-30T15:00:00"
}}

Cancel my meeting

{{
  "action":"delete_calendar_event"
}}

Move my meeting tomorrow 5pm

{{
  "action":"update_calendar_event",
  "time":"2026-06-30T17:00:00"
}}
"""

    prompt = f"""
    {system_instruction}

    Conversation History:
    {history}

    Web Search Results:
    {search_result}

    User:
    {user_message}
    """
    
    reply = call_openai(prompt)

    print("AI:", reply)

    action_data = None

    if reply and reply.strip().startswith("{"):

        try:
            action_data = json.loads(reply)

        except Exception as e:
            print("JSON parse error:", e)

    calendar_words = [
        "meeting",
        "schedule",
        "calendar",
        "appointment"
    ]

    is_calendar_request = any(
        word in user_message.lower()
        for word in calendar_words
    )

    if (
        is_calendar_request
        and action_data
        and "action" in action_data
    ):

        action = action_data["action"]

        if action == "create_calendar_event":

            title = action_data.get(
                "title",
                "Meeting"
            )

            time_str = action_data.get(
                "time",
                ""
            )

            try:

                event_time = datetime.fromisoformat(
                    time_str
                )

                if event_time < datetime.now():

                    event_time = (
                        datetime.now()
                        + timedelta(days=1)
                    )

                    event_time = event_time.replace(
                        hour=15,
                        minute=0,
                        second=0,
                        microsecond=0
                    )

                time_str = event_time.isoformat()

            except:

                time_str = (
                    datetime.now()
                    + timedelta(days=1)
                ).replace(
                    hour=15,
                    minute=0,
                    second=0,
                    microsecond=0
                ).isoformat()

            success = create_google_event(
                title,
                time_str
            )

            if success:

                reply = (
                    f"✅ Google Calendar event created: "
                    f"{title} at {time_str}"
                )

            else:

                reply = (
                    "❌ Create failed "
                    "(check GOOGLE_ACCESS_TOKEN)"
                )

    if not reply:
        reply = "Sorry, something went wrong."

    save_message(
        user_id,
        "assistant",
        reply
    )

    return Response(
        f"<Response><Message>{reply}</Message></Response>",
        mimetype="text/xml"
    )


@app.route("/")
def home():
    return "AI Assistant Running ✅"


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)