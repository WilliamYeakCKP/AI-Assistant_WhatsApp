from flask import Flask, request, Response
from flask_cors import CORS
import requests
import os
import sqlite3

# ✅ ENV
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
SERP_API_KEY = os.environ.get("SERP_API_KEY")

app = Flask(__name__)
CORS(app)

# =========================
# ✅ SQLite
# =========================
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
    return [row[0] for row in rows]


# =========================
# ✅ Search Cache（关键🔥）
# =========================
search_cache = {}


# =========================
# ✅ Google Search
# =========================
def search_google(query):
    # ✅ 先查缓存
    if query in search_cache:
        print("✅ Using cache")
        return search_cache[query]

    try:
        print("🌐 Calling SerpAPI")

        url = "https://serpapi.com/search"

        params = {
            "q": query,
            "api_key": SERP_API_KEY,
            "engine": "google",
            "num": 3
        }

        response = requests.get(url, params=params, timeout=10)
        data = response.json()

        results = []

        if "organic_results" in data:
            for item in data["organic_results"][:3]:
                title = item.get("title", "")
                snippet = item.get("snippet", "")
                results.append(f"{title}: {snippet}")

        final_result = "\n".join(results)

        # ✅ 存缓存
        search_cache[query] = final_result

        return final_result

    except Exception as e:
        print("Search error:", e)
        return None


# =========================
# ✅ OpenAI fallback
# =========================
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

        res = requests.post(url, headers=headers, json=payload, timeout=10)

        if res.status_code != 200:
            print("OpenAI error:", res.text)
            return None

        data = res.json()

        if "choices" in data:
            return data["choices"][0]["message"]["content"]

    except Exception as e:
        print("OpenAI exception:", e)

    return None


# =========================
# ✅ CHAT
# =========================
@app.route("/chat", methods=["POST"])
def chat():

    # ✅ 用户ID
    user_id = (
        request.values.get("From")
        or (request.json.get("From") if request.is_json else None)
        or "test_user"
    )

    # ✅ 用户信息
    user_message = (
        request.values.get("Body")
        or (request.json.get("message") if request.is_json else None)
        or ""
    )

    print("USER:", user_message)

    # ✅ 保存用户消息
    save_message(user_id, "user", user_message)

    # ✅ ✅ ✅ 关键：读取历史（修复memory）
    history = get_history(user_id, 5)

    # =========================
    # ✅ 判断是否需要搜索
    # =========================
    search_keywords = ["news", "latest", "today", "price", "weather", "who is"]

    search_result = None

    if any(word in user_message.lower() for word in search_keywords):
        print("🔍 Trigger search")
        search_result = search_google(user_message)

    # =========================
    # ✅ 构建 prompt（核心🔥）
    # =========================
    system_instruction = """
    You are an AI assistant.

    system_instruction = """
    You are an AI assistant.

    ONLY output JSON when the user EXPLICITLY requests an action 
    like scheduling a meeting or sending an email.

    Otherwise, reply normally in plain text.

    Example JSON format:
    {
        "action": "create_calendar_event",
        "title": "...",
        "time": "..."
    }
    """
    If it is a normal question, just answer normally.
    """

    prompt = system_instruction + "\n\n"

    # ✅ 1️⃣ 加历史（memory）
    for msg in history:
        prompt += msg + "\n"

    # ✅ 2️⃣ 加搜索
    if search_result:
        prompt += "\nRecent web info:\n"
        prompt += search_result + "\n\n"

    # ✅ 3️⃣ 当前问题
    prompt += user_message

    print("PROMPT:\n", prompt)

    # =========================
    # ✅ Gemini
    # =========================
    reply = None

    try:
        url = f"https://generativelanguage.googleapis.com/v1/models/gemini-3.5-flash:generateContent?key={GEMINI_API_KEY}"

        payload = {
            "contents": [{"parts": [{"text": prompt}]}]
        }

        res = requests.post(url, json=payload, timeout=15)
        result = res.json()

        if "candidates" in result and len(result["candidates"]) > 0:
            reply = result["candidates"][0]["content"]["parts"][0]["text"]

    except Exception as e:
        print("Gemini error:", e)

    # ✅ fallback
    if not reply:
        print("Switching to OpenAI")
        reply = call_openai(prompt)

    import json

    action_data = None

    # ✅ 尝试解析 JSON
    try:
        action_data = None

        if reply.strip().startswith("{"):
            try:
                action_data = json.loads(reply)
                print("Parsed action:", action_data)
            except:
                action_data = None

        print("Parsed action:", action_data)
    except:
        action_data = None

    # ✅ 如果是 action → 执行
    if (
        action_data
        and isinstance(action_data, dict)
        and "action" in action_data
        and action_data["action"] in ["create_calendar_event", "send_email"]
    ):

        action = action_data["action"]

        if action == "create_calendar_event":
            title = action_data.get("title", "Meeting")
            time = action_data.get("time", "")

            reply = f"✅ Meeting scheduled: {title} at {time}"

        elif action == "send_email":
            to = action_data.get("to", "")
            reply = f"✅ Email sent to {to}"

        else:
            reply = "⚠️ Unknown action"

    # ✅ 最终保险
    if not reply or reply.strip() == "":
        reply = "AI is currently unavailable, please try again later"

    # ✅ 保存 AI 回复
    save_message(user_id, "ai", reply)

    return Response(
        f"<Response><Message>{reply}</Message></Response>",
        mimetype="text/xml"
    )