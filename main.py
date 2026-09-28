# LINE AI Care Translator V3.1 COMPLETE
# 中文 / 印尼文 / 英文翻譯
# LINE Webhook + Whisper + Google TTS + Cloudinary

import os
import json
import tempfile

from flask import Flask, request, abort
from dotenv import load_dotenv
from openai import OpenAI
from gtts import gTTS
from mutagen.mp3 import MP3

import cloudinary
import cloudinary.uploader

from linebot.v3 import WebhookHandler
from linebot.v3.exceptions import InvalidSignatureError
from linebot.v3.messaging import (
    Configuration,
    ApiClient,
    MessagingApi,
    MessagingApiBlob,
    ReplyMessageRequest,
    TextMessage,
    AudioMessage
)
from linebot.v3.webhooks import (
    MessageEvent,
    TextMessageContent,
    AudioMessageContent
)

load_dotenv()

app = Flask(__name__)

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

handler = WebhookHandler(os.getenv("LINE_CHANNEL_SECRET"))

configuration = Configuration(
    access_token=os.getenv("LINE_CHANNEL_ACCESS_TOKEN")
)

cloudinary.config(
    cloud_name=os.getenv("CLOUDINARY_CLOUD_NAME"),
    api_key=os.getenv("CLOUDINARY_API_KEY"),
    api_secret=os.getenv("CLOUDINARY_API_SECRET")
)


def load_dictionary():
    try:
        with open("care_dictionary.json", "r", encoding="utf-8") as f:
            return json.load(f)
    except:
        return {}


CARE_DICT = load_dictionary()


def is_chinese(text):
    return any('\u4e00' <= c <= '\u9fff' for c in text)


def detect_language(text):
    if is_chinese(text):
        return "zh"

    t = text.lower()

    indo = [
        "saya", "tolong", "bisa", "tidak",
        "kakek", "nenek", "obat",
        "jatuh", "terluka", "mandi"
    ]

    if any(x in t for x in indo):
        return "id"

    return "en"


def translate_text(text):

    lang = detect_language(text)

    if lang == "zh":
        task = "把台灣繁體中文翻譯成自然印尼文"
    elif lang == "id":
        task = "把印尼文翻譯成台灣繁體中文"
    else:
        task = "把英文翻譯成台灣繁體中文"

    prompt = f"""
你是台灣家庭照護翻譯助手。

{task}

規則：
1. 只輸出翻譯結果。
2. 不加解釋。
3. 不加引號。
4. 使用台灣繁體中文，不使用簡體中文。
5. 保持照護日常口語。

固定詞彙：
阿公 = kakek
阿嬤 = nenek
吃藥 = minum obat
換尿布 = ganti popok
跌倒 = jatuh
受傷 = terluka

家庭詞庫：
{json.dumps(CARE_DICT, ensure_ascii=False)}

內容：
{text}
"""

    r = client.responses.create(
        model="gpt-4o-mini",
        input=prompt
    )

    return r.output_text.strip().replace('"', '')


def transcribe_audio(path):
    with open(path, "rb") as f:
        r = client.audio.transcriptions.create(
            model="whisper-1",
            file=f
        )
    return r.text.strip()


def generate_tts(text, path):
    lang = "zh-TW" if is_chinese(text) else "id"
    gTTS(text=text, lang=lang).save(path)


def upload_audio(path):
    r = cloudinary.uploader.upload(
        path,
        resource_type="video"
    )
    return r["secure_url"]


def duration(path):
    return int(MP3(path).info.length * 1000)


def reply_text(token, text):
    with ApiClient(configuration) as api:
        MessagingApi(api).reply_message(
            ReplyMessageRequest(
                reply_token=token,
                messages=[TextMessage(text=text)]
            )
        )


def reply_audio(token, text, url, ms):
    with ApiClient(configuration) as api:
        MessagingApi(api).reply_message(
            ReplyMessageRequest(
                reply_token=token,
                messages=[
                    TextMessage(text=text),
                    AudioMessage(
                        original_content_url=url,
                        duration=ms
                    )
                ]
            )
        )


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


@handler.add(MessageEvent, message=TextMessageContent)
def handle_text(event):
    try:
        reply_text(
            event.reply_token,
            translate_text(event.message.text)
        )
    except Exception as e:
        reply_text(event.reply_token, f"錯誤：{e}")


@handler.add(MessageEvent, message=AudioMessageContent)
def handle_audio(event):

    m4a = None
    mp3 = None

    try:
        with ApiClient(configuration) as api:
            blob = MessagingApiBlob(api)
            content = blob.get_message_content(
                event.message.id
            )

        with tempfile.NamedTemporaryFile(
            delete=False,
            suffix=".m4a"
        ) as f:
            m4a = f.name
            f.write(content if isinstance(content, bytes) else content.read())

        text = transcribe_audio(m4a)
        result = translate_text(text)

        with tempfile.NamedTemporaryFile(
            delete=False,
            suffix=".mp3"
        ) as f:
            mp3 = f.name

        generate_tts(result, mp3)

        reply_audio(
            event.reply_token,
            result,
            upload_audio(mp3),
            duration(mp3)
        )

    except Exception as e:
        reply_text(event.reply_token, f"語音錯誤：{e}")

    finally:
        for p in [m4a, mp3]:
            if p and os.path.exists(p):
                os.remove(p)


if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(os.getenv("PORT", 10000))
    )
