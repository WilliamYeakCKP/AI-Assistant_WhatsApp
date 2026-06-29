from flask import Flask, request, Response
from flask_cors import CORS
import requests
import os
import sqlite3

# ✅ API keys
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")

app = Flask(__name__)
CORS(app)

# ✅ ✅ ✅ 初始化数据库
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


# ✅ ✅ 存消息
def save_message(user_id, role, message):
    conn = sqlite3.connect("chat.db")
    cursor = conn.cursor()

    cursor.execute(
        "INSERT INTO chat_history (user_id, role, message) VALUES (?, ?, ?)",
        (user_id, role, message)
    )

    conn.commit()
    conn.close()


# ✅ ✅ 读取最近历史（限制长度防爆 token）
def get_history(user_id, limit=5):
    conn = sqlite3.connect("chat.db")
    cursor = conn.cursor()

    cursor.execute(
        "SELECT role, message FROM chat_history WHERE user_id = ? ORDER BY id DESC LIMIT ?",
        (user_id, limit)
    )

    rows = cursor.fetchall()
    conn.close()

    # ✅ 反转顺序（最旧 → 最新）
    rows.reverse()

    return rows


# ✅ ✅ OpenAI fallback
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

        if "choices" in data and len(data["choices"]) > 0:
            return data["choices"][0]["message"]["content"]

    except Exception as e:
        print("OpenAI exception:", e)

    return None


@app.route("/chat", methods=["POST"])
def chat():
    # ✅ 用户ID（WhatsApp / Hoppscotch兼容）
    user_id = request.values.get("From") or request.json.get("From") or "test_user"

    # ✅ 用户消息
    user_message = request.values.get("Body") or request.json.get("message")

    # ✅ 保存用户消息
    save_message(user_id, "user", user_message)

    # ✅ 获取历史
    history_rows = get_history(user_id, limit=5)

    # ✅ 拼 prompt
    history_text = ""
    for role, message in history_rows:
        history_text += f"{message}\n"

    print("PROMPT:", history_text)

    # ✅ Gemini API
    url = f"https://generativelanguage.googleapis.com/v1/models/gemini-3.5-flash:generateContent?key={GEMINI_API_KEY}"

    payload = {
        "contents": [{"parts": [{"text": history_text}]}]
    }

    reply = None

    try:
        res = requests.post(url, json=payload, timeout=15)
        result = res.json()
        print("Gemini:", result)

        if "candidates" in result and len(result["candidates"]) > 0:
            reply = result["candidates"][0]["content"]["parts"][0]["text"]

    except Exception as e:
        print("Gemini error:", e)

    # ✅ fallback
    if not reply:
        print("Switching to OpenAI fallback...")
        reply = call_openai(history_text)

    # ✅ 最终保险
    if not reply or reply.strip() == "":
        reply = "AI is currently unavailable, please try again later"

    # ✅ 保存 AI 回复
    save_message(user_id, "ai", reply)

    # ✅ 返回 Twilio
    return Response(
        f"<Response><Message>{reply}</Message></Response>",
        mimetype="text/xml"
    )