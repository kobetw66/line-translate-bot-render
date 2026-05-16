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

MAX_AUDIO_DURATION_MS = 60000

cloudinary.config(
    cloud_name=os.getenv("CLOUDINARY_CLOUD_NAME"),
    api_key=os.getenv("CLOUDINARY_API_KEY"),
    api_secret=os.getenv("CLOUDINARY_API_SECRET")
)

# ================= 翻譯 =================
def translate_text(text):
    try:
        response = client.responses.create(
            model="gpt-4o-mini",  # ✅ 改成穩定版
            input=text
        )
        return response.output_text.strip()
    except Exception as e:
        print("🔥 Translate error:", str(e))
        raise


# ================= 語音辨識 =================
def transcribe_audio(file_path):
    try:
        with open(file_path, "rb") as audio_file:
            transcript = client.audio.transcriptions.create(
                model="whisper-1",
                file=audio_file
            )
        return transcript.text.strip()
    except Exception as e:
        print("🔥 Transcribe error:", str(e))
        raise


# ================= TTS =================
def generate_tts_audio(text, output_path):
    try:
        response = client.audio.speech.create(
            model="gpt-4o-mini-tts",
            voice="alloy",
            input=text
        )

        with open(output_path, "wb") as f:
            f.write(response.read())

    except Exception as e:
        print("🔥 TTS error:", str(e))
        raise


def get_mp3_duration_ms(file_path):
    audio = MP3(file_path)
    return int(audio.info.length * 1000)


# ================= Cloudinary =================
def upload_audio_to_cloudinary(file_path):
    try:
        result = cloudinary.uploader.upload(
            file_path,
            resource_type="video"
        )
        return result["secure_url"]
    except Exception as e:
        print("🔥 Cloudinary error:", str(e))
        raise


# ================= 回覆 =================
def reply_text(reply_token, text):
    with ApiClient(configuration) as api_client:
        MessagingApi(api_client).reply_message(
            ReplyMessageRequest(
                reply_token=reply_token,
                messages=[TextMessage(text=text)]
            )
        )


# 🔥 用 LINE 原始 mention（真正 tag）
def reply_with_original_mention(reply_token, original_text, mention, translated_text):
    new_text = original_text + "\n" + translated_text

    with ApiClient(configuration) as api_client:
        MessagingApi(api_client).reply_message(
            ReplyMessageRequest(
                reply_token=reply_token,
                messages=[
                    TextMessage(
                        text=new_text,
                        mention=mention
                    )
                ]
            )
        )


def reply_text_and_audio(reply_token, text, audio_url, duration_ms):
    with ApiClient(configuration) as api_client:
        MessagingApi(api_client).reply_message(
            ReplyMessageRequest(
                reply_token=reply_token,
                messages=[
                    TextMessage(text=text),
                    AudioMessage(
                        original_content_url=audio_url,
                        duration=duration_ms
                    )
                ]
            )
        )


# ================= 音訊處理 =================
def save_line_audio(audio_content, temp_audio):
    if hasattr(audio_content, "data"):
        temp_audio.write(audio_content.data)
    else:
        for chunk in audio_content:
            if chunk:
                temp_audio.write(chunk)


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


# ================= 文字處理 =================
@handler.add(MessageEvent, message=TextMessageContent)
def handle_text_message(event):
    try:
        user_text = event.message.text.strip()

        if not user_text:
            return

        mention = getattr(event.message, "mention", None)

        translated = translate_text(user_text)

        if mention:
            reply_with_original_mention(
                event.reply_token,
                user_text,
                mention,
                translated
            )
        else:
            reply_text(event.reply_token, translated)

    except Exception as e:
        print("🔥 Text error:", str(e))
        reply_text(event.reply_token, f"錯誤：{str(e)}")  # ✅ 顯示錯誤


# ================= 語音處理 =================
@handler.add(MessageEvent, message=AudioMessageContent)
def handle_audio_message(event):
    temp_audio_path = None
    tts_path = None

    try:
        duration_ms = getattr(event.message, "duration", 0)

        if duration_ms and duration_ms >= MAX_AUDIO_DURATION_MS:
            reply_text(event.reply_token, "語音太長")
            return

        with ApiClient(configuration) as api_client:
            blob_api = MessagingApiBlob(api_client)
            audio_content = blob_api.get_message_content(event.message.id)

            with tempfile.NamedTemporaryFile(delete=False, suffix=".m4a") as temp_audio:
                save_line_audio(audio_content, temp_audio)
                temp_audio_path = temp_audio.name

        transcript_text = transcribe_audio(temp_audio_path)

        translated = translate_text(transcript_text)

        with tempfile.NamedTemporaryFile(delete=False, suffix=".mp3") as temp_tts:
            tts_path = temp_tts.name

        generate_tts_audio(translated, tts_path)

        duration = get_mp3_duration_ms(tts_path)
        audio_url = upload_audio_to_cloudinary(tts_path)

        reply_text_and_audio(
            event.reply_token,
            translated,
            audio_url,
            duration
        )

    except Exception as e:
        print("🔥 Audio error:", str(e))
        reply_text(event.reply_token, f"語音錯誤：{str(e)}")

    finally:
        if temp_audio_path and os.path.exists(temp_audio_path):
            os.remove(temp_audio_path)

        if tts_path and os.path.exists(tts_path):
            os.remove(tts_path)


@app.route("/")
def home():
    return "LINE Translate Bot Running!"


if __name__ == "__main__":
    app.run(port=5000)
