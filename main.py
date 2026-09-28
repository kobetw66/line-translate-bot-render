# LINE AI Care Translator V3.1
# 中文 / 印尼文 / 英文 自動翻譯版
# 保留 LINE Webhook、Whisper、Google TTS、Cloudinary 架構

import os
import json
from flask import Flask, request, abort
from dotenv import load_dotenv
from openai import OpenAI
from gtts import gTTS
import cloudinary
import cloudinary.uploader

from linebot.v3 import WebhookHandler
from linebot.v3.exceptions import InvalidSignatureError

load_dotenv()

app = Flask(__name__)

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

handler = WebhookHandler(os.getenv("LINE_CHANNEL_SECRET"))

def is_chinese(text):
    return any('\u4e00' <= c <= '\u9fff' for c in text)

def detect_language(text):
    if is_chinese(text):
        return "zh"

    id_words = [
        "saya","sudah","tidak","tolong",
        "bisa","kakek","nenek","obat",
        "jatuh","terluka","mandi"
    ]

    lower = text.lower()

    if any(w in lower for w in id_words):
        return "id"

    return "en"


def translate_text(text):

    lang = detect_language(text)

    if lang == "zh":
        task = "請將繁體中文翻譯成自然印尼文"
    elif lang == "id":
        task = "請將印尼文翻譯成台灣繁體中文"
    else:
        task = "請將英文翻譯成台灣繁體中文"

    prompt = f"""
你是台灣家庭照護翻譯助手。

{task}

規則：
1. 只輸出翻譯結果。
2. 不要加入說明。
3. 不要加引號。
4. 禁止簡體中文。
5. 使用家庭照護自然口語。

固定詞彙：
阿公 = kakek
阿嬤 = nenek
吃藥 = minum obat
換尿布 = ganti popok
跌倒 = jatuh
受傷 = terluka

內容：
{text}
"""

    result = client.responses.create(
        model="gpt-4o-mini",
        input=prompt
    )

    return result.output_text.strip().replace('"','')


@app.route("/")
def home():
    return "LINE AI Care Translator V3.1 OK"


@app.route("/callback", methods=["POST"])
def callback():

    signature = request.headers.get("X-Line-Signature")
    body = request.get_data(as_text=True)

    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)

    return "OK"


if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(os.getenv("PORT",10000))
    )
