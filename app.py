from flask import Flask, request, jsonify, Response
from flask_cors import CORS
import requests
import random
import os
API_KEY = os.environ.get("GEMINI_API_KEY")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")

app = Flask(__name__) 
CORS(app)

chat_history = []

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

        if response.status_code != 200:
            print("OpenAI failed:", response.text)
            return None

        data = response.json()
        return data["choices"][0]["message"]["content"]

    except Exception as e:
        print("OpenAI error:", e)
        return None

@app.route("/chat", methods=["POST"])
def chat():
    global chat_history

    # ✅ ✅ 改这里：支持 WhatsApp
    user_message = request.values.get("Body", "Hello")

    chat_history.append({"role": "user", "text": user_message})

    if len(chat_history) > 3:
        chat_history = chat_history[-3:]

    history_text = ""
    for item in chat_history:
        history_text += f"{item['text']}\n"

    history_text += f"#{random.randint(1,10000)}"

    url = f"https://generativelanguage.googleapis.com/v1/models/gemini-3.5-flash:generateContent?key={API_KEY}"

    payload = {
        "contents": [{"parts": [{"text": history_text}]}],
        "generationConfig": {
            "temperature": 0.9,
            "topP": 0.9
        }
    }

    try:
        response = requests.post(url, json=payload, timeout=20)
        result = response.json()
        print("DEBUG:", result)

        reply = None

        if "candidates" in result and len(result["candidates"]) > 0:
            try:
                reply = result["candidates"][0]["content"]["parts"][0]["text"]
            except:
                reply = None

        # ✅ ✅ 如果 Gemini失败 → 用 OpenAI
        if not reply:
            print("Switching to OpenAI fallback...")
            reply = call_openai(history_text)

        # ✅ ✅ 如果全部失败
        if not reply:
            reply = "AI is busy right now, please try again later 🚦"


        chat_history.append({"role": "ai", "text": reply})

    except Exception as e:
        reply = f"Error: {str(e)}"

    # ✅ ✅ ✅ 返回 Twilio 格式（关键）
    return Response(
        f"<Response><Message>{reply}</Message></Response>",
        mimetype="text/xml"
    )