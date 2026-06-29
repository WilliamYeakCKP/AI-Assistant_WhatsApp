from flask import Flask, request, Response
from flask_cors import CORS
import requests
import random
import os

# ✅ API keys
API_KEY = os.environ.get("GEMINI_API_KEY")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")

app = Flask(__name__)
CORS(app)

# ✅ 简单记忆
chat_history = []


# ✅ ✅ ✅ OpenAI fallback（安全版）
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

        response = requests.post(url, headers=headers, json=payload, timeout=10)

        # ✅ 状态码检查
        if response.status_code != 200:
            print("OpenAI failed:", response.text)
            return None

        data = response.json()

        # ✅ ✅ 结构严格检查（关键）
        if "choices" in data and len(data["choices"]) > 0:
            return data["choices"][0]["message"]["content"]

        return None

    except Exception as e:
        print("OpenAI error:", e)
        return None


@app.route("/chat", methods=["POST"])
def chat():
    global chat_history

    # ✅ WhatsApp 输入
    user_message = request.values.get("Body", "Hello")

    chat_history.append({"role": "user", "text": user_message})

    # ✅ 限制长度
    if len(chat_history) > 3:
        chat_history = chat_history[-3:]

    # ✅ 组 prompt（可以后续优化）
    history_text = ""
    for item in chat_history:
        history_text += f"{item['text']}\n"

    history_text += f"#{random.randint(1,10000)}"

    # ✅ Gemini URL
    url = f"https://generativelanguage.googleapis.com/v1/models/gemini-3.5-flash:generateContent?key={API_KEY}"

    payload = {
        "contents": [{"parts": [{"text": history_text}]}],
        "generationConfig": {
            "temperature": 0.9,
            "topP": 0.9
        }
    }

    try:
        # ✅ 调 Gemini
        response = requests.post(url, json=payload, timeout=20)
        result = response.json()
        print("DEBUG Gemini:", result)

        reply = None

        # ✅ ✅ Gemini 解析（安全）
        if (
            "candidates" in result
            and len(result["candidates"]) > 0
            and "content" in result["candidates"][0]
        ):
            try:
                reply = result["candidates"][0]["content"]["parts"][0]["text"]
            except:
                reply = None

        # ✅ ✅ fallback 到 OpenAI
        if not reply:
            print("Switching to OpenAI fallback...")
            reply = call_openai(history_text)

        # ✅ ✅ ✅ 最终保险（绝对不会空）
        if not reply or str(reply).strip() == "":
            reply = "AI is currently unavailable, please try again later 🙏"

        # ✅ 保存回复
        chat_history.append({"role": "ai", "text": reply})

    except Exception as e:
        print("SYSTEM ERROR:", e)
        reply = "System error, please try again later ⚠️"

    # ✅ Twilio格式
    return Response(
        f"<Response><Message>{reply}</Message></Response>",
        mimetype="text/xml"
    )
``