import os
import tempfile
from flask import Flask, request, abort
from dotenv import load_dotenv
from openai import OpenAI
from mutagen.mp3 import MP3

import cloudinary
import cloudinary.uploader

from linebot.v3 import WebhookHandler
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
from linebot.v3.exceptions import InvalidSignatureError

load_dotenv()

app = Flask(__name__)

LINE_CHANNEL_SECRET = os.getenv("LINE_CHANNEL_SECRET")
LINE_CHANNEL_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

handler = WebhookHandler(LINE_CHANNEL_SECRET)
configuration = Configuration(access_token=LINE_CHANNEL_ACCESS_TOKEN)
client = OpenAI(api_key=OPENAI_API_KEY)

cloudinary.config(
    cloud_name=os.getenv("CLOUDINARY_CLOUD_NAME"),
    api_key=os.getenv("CLOUDINARY_API_KEY"),
    api_secret=os.getenv("CLOUDINARY_API_SECRET")
)

# ================= 語言判斷 =================
def is_chinese(text):
    return any('\u4e00' <= ch <= '\u9fff' for ch in text)

# ================= 翻譯 =================
def translate_text(text):
    if is_chinese(text):
        prompt = f"請翻譯成印尼文：{text}"
    else:
        prompt = f"請翻譯成繁體中文：{text}"

    response = client.responses.create(
        model="gpt-4o-mini",
        input=prompt
    )
    return response.output_text.strip()

# ================= 語音辨識 =================
def transcribe_audio(file_path):
    with open(file_path, "rb") as audio_file:
        transcript = client.audio.transcriptions.create(
            model="whisper-1",
            file=audio_file
        )
    return transcript.text.strip()

# ================= TTS（完全穩定版）=================
def generate_tts_audio(text, output_path):
    response = client.audio.speech.create(
        model="gpt-4o-mini-tts",
        voice="alloy",
        input=text
    )

    with open(output_path, "wb") as f:
        for chunk in response.iter_bytes():
            if isinstance(chunk, bytes):
                f.write(chunk)

# ================= Cloudinary =================
def upload_audio_to_cloudinary(file_path):
    result = cloudinary.uploader.upload(file_path, resource_type="video")
    return result["secure_url"]

def get_mp3_duration_ms(file_path):
    return int(MP3(file_path).info.length * 1000)

# ================= 回覆 =================
def reply_text(reply_token, text):
    with ApiClient(configuration) as api_client:
        MessagingApi(api_client).reply_message(
            ReplyMessageRequest(
                reply_token=reply_token,
                messages=[TextMessage(text=text)]
            )
        )

def reply_text_and_audio(reply_token, text, audio_url, duration):
    with ApiClient(configuration) as api_client:
        MessagingApi(api_client).reply_message(
            ReplyMessageRequest(
                reply_token=reply_token,
                messages=[
                    TextMessage(text=text),
                    AudioMessage(
                        original_content_url=audio_url,
                        duration=duration
                    )
                ]
            )
        )

# ================= 🔥 修正這裡（最關鍵） =================
def save_line_audio(audio_content, temp_audio):
    try:
        for chunk in audio_content:
            if isinstance(chunk, bytes):
                temp_audio.write(chunk)
    except Exception as e:
        print("🔥 save_line_audio error:", e)

# ================= Webhook =================
@app.route("/callback", methods=["POST"])
def callback():
    signature = request.headers.get("X-Line-Signature")
    body = request.get_data(as_text=True)

    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)

    return "OK"

# ================= 文字 =================
@handler.add(MessageEvent, message=TextMessageContent)
def handle_text(event):
    try:
        text = event.message.text
        translated = translate_text(text)
        reply_text(event.reply_token, translated)
    except Exception as e:
        reply_text(event.reply_token, f"錯誤：{str(e)}")

# ================= 語音 =================
@handler.add(MessageEvent, message=AudioMessageContent)
def handle_audio(event):
    temp_audio_path = None
    tts_path = None

    try:
        with ApiClient(configuration) as api_client:
            blob_api = MessagingApiBlob(api_client)
            audio_content = blob_api.get_message_content(event.message.id)

            with tempfile.NamedTemporaryFile(delete=False, suffix=".m4a") as temp_audio:
                save_line_audio(audio_content, temp_audio)
                temp_audio_path = temp_audio.name

        text = transcribe_audio(temp_audio_path)
        translated = translate_text(text)

        with tempfile.NamedTemporaryFile(delete=False, suffix=".mp3") as temp_tts:
            tts_path = temp_tts.name

        generate_tts_audio(translated, tts_path)

        duration = get_mp3_duration_ms(tts_path)
        url = upload_audio_to_cloudinary(tts_path)

        reply_text_and_audio(event.reply_token, translated, url, duration)

    except Exception as e:
        print("🔥 Audio error:", e)
        reply_text(event.reply_token, f"語音錯誤：{str(e)}")

    finally:
        if temp_audio_path and os.path.exists(temp_audio_path):
            os.remove(temp_audio_path)
        if tts_path and os.path.exists(tts_path):
            os.remove(tts_path)

@app.route("/")
def home():
    return "OK"

if __name__ == "__main__":
    app.run()
