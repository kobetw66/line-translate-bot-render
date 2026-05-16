import os
import tempfile
from flask import Flask, request, abort
from dotenv import load_dotenv
from openai import OpenAI

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


def translate_text(text):
    response = client.responses.create(
        model="gpt-4.1-mini",
        instructions="""
你是 LINE 中文↔印尼文雙向翻譯助手。

規則：
1. 中文翻成自然、口語、禮貌的印尼文。
2. 印尼文翻成自然、口語、禮貌的繁體中文。
3. 中印尼文混合時，依主要語言判斷翻譯方向。
4. 只輸出翻譯結果。
5. 不要解釋、不要加標題、不要加括號。
6. 適合家庭、長輩、外籍看護日常溝通使用。
""",
        input=text
    )
    return response.output_text.strip()


def transcribe_audio(file_path):
    with open(file_path, "rb") as audio_file:
        transcript = client.audio.transcriptions.create(
            model="whisper-1",
            file=audio_file
        )
    return transcript.text.strip()


def generate_tts_audio(text, output_path):
    response = client.audio.speech.create(
        model="gpt-4o-mini-tts",
        voice="alloy",
        input=text
    )

    with open(output_path, "wb") as f:
        f.write(response.read())


def upload_audio_to_cloudinary(file_path):
    result = cloudinary.uploader.upload(
        file_path,
        resource_type="video"
    )
    return result["secure_url"]


def reply_text(reply_token, text):
    with ApiClient(configuration) as api_client:
        line_bot_api = MessagingApi(api_client)
        line_bot_api.reply_message(
            ReplyMessageRequest(
                reply_token=reply_token,
                messages=[TextMessage(text=text)]
            )
        )


def reply_text_and_audio(reply_token, text, audio_url, duration_ms):
    with ApiClient(configuration) as api_client:
        line_bot_api = MessagingApi(api_client)
        line_bot_api.reply_message(
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


def save_line_audio(audio_content, temp_audio):
    if isinstance(audio_content, (bytes, bytearray)):
        temp_audio.write(audio_content)
    elif hasattr(audio_content, "data"):
        temp_audio.write(audio_content.data)
    elif hasattr(audio_content, "read"):
        temp_audio.write(audio_content.read())
    elif hasattr(audio_content, "iter_content"):
        for chunk in audio_content.iter_content():
            if chunk:
                temp_audio.write(chunk)
    else:
        for chunk in audio_content:
            if chunk:
                temp_audio.write(chunk)


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
def handle_text_message(event):
    try:
        user_text = event.message.text.strip()

        if not user_text:
            return

        translated = translate_text(user_text)
        reply_text(event.reply_token, translated)

    except Exception as e:
        print("Text error:", e)
        reply_text(event.reply_token, "文字翻譯失敗，請再試一次。")


@handler.add(MessageEvent, message=AudioMessageContent)
def handle_audio_message(event):
    temp_audio_path = None
    tts_path = None

    try:
        duration_ms = getattr(event.message, "duration", 0)
        print("Audio duration:", duration_ms)

        if duration_ms and duration_ms >= MAX_AUDIO_DURATION_MS:
            reply_text(event.reply_token, "語音超過60秒，請縮短後再試。")
            return

        with ApiClient(configuration) as api_client:
            blob_api = MessagingApiBlob(api_client)
            audio_content = blob_api.get_message_content(event.message.id)

            with tempfile.NamedTemporaryFile(delete=False, suffix=".m4a") as temp_audio:
                save_line_audio(audio_content, temp_audio)
                temp_audio_path = temp_audio.name

        file_size = os.path.getsize(temp_audio_path)
        print("Audio file size:", file_size)

        if file_size == 0:
            reply_text(event.reply_token, "語音檔下載失敗，請再試一次。")
            return

        transcript_text = transcribe_audio(temp_audio_path)

        if not transcript_text:
            reply_text(event.reply_token, "沒有辨識到語音內容，請再試一次。")
            return

        translated = translate_text(transcript_text)

        with tempfile.NamedTemporaryFile(delete=False, suffix=".mp3") as temp_tts:
            tts_path = temp_tts.name

        generate_tts_audio(translated, tts_path)

        if not os.path.exists(tts_path) or os.path.getsize(tts_path) == 0:
            reply_text(event.reply_token, "語音檔產生失敗，請再試一次。")
            return

        audio_url = upload_audio_to_cloudinary(tts_path)

        reply_text_and_audio(
            event.reply_token,
            f"語音辨識：{transcript_text}\n\n翻譯：{translated}",
            audio_url,
            5000
        )

    except Exception as e:
        print("Audio error:", e)
        reply_text(event.reply_token, "語音翻譯失敗，請再試一次。")

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
