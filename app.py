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

# ✅ ======================
# ✅ SQLite
# ✅ ======================
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


# ✅ ======================
# ✅ 搜索缓存（核心🔥）
# ✅ ======================
search_cache = {}


# ✅ ======================
# ✅ Google Search
# ✅ ======================
def search_google(query):
    # ✅ 优先用缓存
    if query in search_cache:
        print("Using cached result ✅")
        return search_cache[query]

    try:
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


# ✅ ======================
# ✅ OpenAI fallback
# ✅ ======================
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


# ✅ ======================
# ✅ CHAT
# ✅ ======================
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

    # ✅ 存用户消息
    save_message(user_id, "user", user_message)

    # ✅ ======================
    # ✅ 判断是否需要搜索
    # ✅ ======================
    search_keywords = [
        "news", "latest", "today", "price", "weather", "who is"
    ]

    search_result = None

    if any(word in user_message.lower() for word in search_keywords):
        print("Trigger search 🔍")
        search_result = search_google(user_message)

    # ✅ ======================
    # ✅ 构建 prompt
    # ✅ ======================
    prompt = ""

    # ✅ 如果有搜索结果 → 加进去
    if search_result:
        prompt += "Here is some recent information from the web:\n"
        prompt += search_result + "\n\n"

    prompt += user_message

    print("PROMPT:", prompt)

    # ✅ ======================
    # ✅ Gemini
    # ✅ ======================
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

    # ✅ 最终保险
    if not reply or reply.strip() == "":
        reply = "AI is currently unavailable, please try again later"

    # ✅ 存 AI 回复
    save_message(user_id, "ai", reply)

    return Response(
        f"<Response><Message>{reply}</Message></Response>",
        mimetype="text/xml"
    )