from flask import Flask, request, jsonify
from flask_cors import CORS

app = Flask(__name__) 
CORS(app)

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

        reply = result["candidates"][0]["content"]["parts"][0]["text"]

        chat_history.append({"role": "ai", "text": reply})

    except Exception as e:
        reply = f"Error: {str(e)}"

    # ✅ ✅ ✅ 返回 Twilio 格式（关键）
    return f"""
    <Response>
        <Message>{reply}</Message>
    </Response>
    """