import os
import re
import tempfile
from flask import Flask, request, abort

from linebot.v3 import WebhookHandler
from linebot.v3.exceptions import InvalidSignatureError
from linebot.v3.messaging import (
    Configuration,
    ApiClient,
    MessagingApi,
    MessagingApiBlob,
    ReplyMessageRequest,
    TextMessage,
)
from linebot.v3.webhooks import (
    MessageEvent,
    TextMessageContent,
    AudioMessageContent,
)

from deep_translator import GoogleTranslator
from langdetect import detect
from openai import OpenAI


app = Flask(__name__)

LINE_CHANNEL_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")
LINE_CHANNEL_SECRET = os.getenv("LINE_CHANNEL_SECRET")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

configuration = Configuration(access_token=LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)
openai_client = OpenAI(api_key=OPENAI_API_KEY)


# =========================
# 語言判斷
# =========================

INDONESIAN_WORDS = [
    "saya", "aku", "kamu", "dia", "mereka",
    "tidak", "bukan", "sudah", "belum",
    "makan", "minum", "mandi", "tidur",
    "obat", "dokter", "sakit", "pusing",
    "terima", "kasih", "selamat", "pagi",
    "siang", "malam", "tolong", "bantu",
    "darah", "gula", "tekanan", "rumah",
    "ibu", "bapak", "nenek", "kakek",
]


def clean_text(text):
    text = re.sub(r"@\S+", "", text)
    text = re.sub(r"http\S+", "", text)
    text = re.sub(r"[^\w\s\u4e00-\u9fff]", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def has_chinese(text):
    return bool(re.search(r"[\u4e00-\u9fff]", text))


def has_indonesian_words(text):
    words = clean_text(text).lower().split()
    return any(word in words for word in INDONESIAN_WORDS)


def detect_language_smart(text):
    cleaned = clean_text(text)

    if not cleaned:
        return "unknown"

    if has_chinese(cleaned):
        return "zh"

    if has_indonesian_words(cleaned):
        return "id"

    try:
        lang = detect(cleaned)

        if lang in ["zh-cn", "zh-tw", "zh"]:
            return "zh"

        if lang == "id":
            return "id"

        return lang

    except Exception:
        return "unknown"


# =========================
# 翻譯
# =========================

def translate_by_language(text):
    lang = detect_language_smart(text)

    if lang == "zh":
        translated = GoogleTranslator(source="auto", target="id").translate(text)
        return (
            "【中文 → 印尼文】\n"
            f"{translated}"
        )

    elif lang == "id":
        translated = GoogleTranslator(source="auto", target="zh-TW").translate(text)
        return (
            "【印尼文 → 中文】\n"
            f"{translated}"
        )

    else:
        translated = GoogleTranslator(source="auto", target="zh-TW").translate(text)
        return (
            "【自動翻譯 → 中文】\n"
            f"{translated}"
        )


# =========================
# 語音轉文字
# =========================

def speech_to_text(audio_bytes):
    with tempfile.NamedTemporaryFile(delete=False, suffix=".m4a") as temp_audio:
        temp_audio.write(audio_bytes)
        temp_audio_path = temp_audio.name

    try:
        with open(temp_audio_path, "rb") as audio_file:
            transcript = openai_client.audio.transcriptions.create(
                model="whisper-1",
                file=audio_file
            )

        return transcript.text

    finally:
        if os.path.exists(temp_audio_path):
            os.remove(temp_audio_path)


# =========================
# LINE Webhook
# =========================

@app.route("/callback", methods=["POST"])
def callback():
    signature = request.headers.get("X-Line-Signature")
    body = request.get_data(as_text=True)

    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)

    return "OK"


# =========================
# 處理文字訊息
# =========================

@handler.add(MessageEvent, message=TextMessageContent)
def handle_text_message(event):
    text = event.message.text.strip()

    if not text:
        return

    try:
        reply_text = translate_by_language(text)

    except Exception as e:
        reply_text = f"翻譯失敗：{e}"

    with ApiClient(configuration) as api_client:
        line_bot_api = MessagingApi(api_client)
        line_bot_api.reply_message(
            ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[
                    TextMessage(text=reply_text)
                ]
            )
        )


# =========================
# 處理語音訊息
# =========================

@handler.add(MessageEvent, message=AudioMessageContent)
def handle_audio_message(event):
    try:
        with ApiClient(configuration) as api_client:
            blob_api = MessagingApiBlob(api_client)
            audio_content = blob_api.get_message_content(event.message.id)

        recognized_text = speech_to_text(audio_content)

        translated_text = translate_by_language(recognized_text)

        reply_text = (
            "【語音辨識】\n"
            f"{recognized_text}\n\n"
            f"{translated_text}"
        )

    except Exception as e:
        reply_text = f"語音處理失敗：{e}"

    with ApiClient(configuration) as api_client:
        line_bot_api = MessagingApi(api_client)
        line_bot_api.reply_message(
            ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[
                    TextMessage(text=reply_text)
                ]
            )
        )


# =========================
# 首頁測試
# =========================

@app.route("/", methods=["GET"])
def home():
    return "LINE BOT Translation Bot is running."


# =========================
# 啟動
# =========================

if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(os.getenv("PORT", 5000))
    )
