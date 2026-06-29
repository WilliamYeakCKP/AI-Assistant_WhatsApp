from flask import Flask, request, Response
from flask_cors import CORS
import requests
import os
import sqlite3
import faiss
import numpy as np
from sentence_transformers import SentenceTransformer

# =======================
# ✅ API KEYS
# =======================
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")

app = Flask(__name__)
CORS(app)

# =======================
# ✅ SQLite 初始化
# =======================
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

# =======================
# ✅ SQLite 存 / 读
# =======================
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


# =======================
# ✅ FAISS VECTOR
# =======================
model = SentenceTransformer("all-MiniLM-L6-v2")

dimension = 384
index = faiss.IndexFlatL2(dimension)

vector_store = []


def store_vector(text):
    vector = model.encode([text])
    index.add(np.array(vector))
    vector_store.append(text)


def search_vector(query, top_k=3):
    if len(vector_store) == 0:
        return []

    query_vector = model.encode([query])
    D, I = index.search(np.array(query_vector), top_k)

    results = []

    for i in I[0]:
        if i < len(vector_store):
            results.append(vector_store[i])

    return results


# =======================
# ✅ OpenAI fallback
# =======================
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


# =======================
# ✅ CHAT ENDPOINT
# =======================
@app.route("/chat", methods=["POST"])
def chat():

    # ✅ user id（支持 WhatsApp + Hoppscotch）
    user_id = (
        request.values.get("From")
        or (request.json.get("From") if request.is_json else None)
        or "test_user"
    )

    # ✅ message
    user_message = (
        request.values.get("Body")
        or (request.json.get("message") if request.is_json else None)
        or ""
    )

    print("USER:", user_message, "| ID:", user_id)

    # ✅ 存入SQLite
    save_message(user_id, "user", user_message)

    # ✅ 存入vector
    store_vector(user_message)

    # ===================
    # ✅ 取 relevant memory
    # ===================
    relevant_memory = search_vector(user_message)

    # ✅ fallback（没vector时）
    if not relevant_memory:
        relevant_memory = get_history(user_id, 5)

    # ✅ 拼 prompt
    prompt = "\n".join(relevant_memory)
    prompt += "\n" + user_message

    print("PROMPT:", prompt)

    # ===================
    # ✅ Gemini
    # ===================
    reply = None

    try:
        url = f"https://generativelanguage.googleapis.com/v1/models/gemini-3.5-flash:generateContent?key={GEMINI_API_KEY}"

        payload = {
            "contents": [{"parts": [{"text": prompt}]}]
        }

        res = requests.post(url, json=payload, timeout=15)
        result = res.json()

        print("Gemini:", result)

        if "candidates" in result and len(result["candidates"]) > 0:
            reply = result["candidates"][0]["content"]["parts"][0]["text"]

    except Exception as e:
        print("Gemini error:", e)

    # ===================
    # ✅ fallback → OpenAI
    # ===================
    if not reply:
        print("Switching to OpenAI")
        reply = call_openai(prompt)

    # ===================
    # ✅ 最终保险
    # ===================
    if not reply or reply.strip() == "":
        reply = "AI is currently unavailable, please try again later"

    # ✅ 存 AI 回复
    save_message(user_id, "ai", reply)
    store_vector(reply)

    # ✅ 返回
    return Response(
        f"<Response><Message>{reply}</Message></Response>",
        mimetype="text/xml"
    )