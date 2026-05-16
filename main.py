import os
import tempfile
import subprocess
from flask import Flask, request, abort
from dotenv import load_dotenv
from openai import OpenAI
from mutagen.mp3 import MP3

import cloudinary
import cloudinary.uploader

from linebot.v3 import WebhookHandler
from linebot.v3.messaging import *
from linebot.v3.webhooks import *
from linebot.v3.exceptions import InvalidSignatureError

load_dotenv()

app = Flask(__name__)

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

handler = WebhookHandler(os.getenv("LINE_CHANNEL_SECRET"))
configuration = Configuration(access_token=os.getenv("LINE_CHANNEL_ACCESS_TOKEN"))

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

# ================= 語音轉 wav（關鍵修正）=================
def convert_to_wav(input_path, output_path):
    subprocess.run([
        "ffmpeg",
        "-y",
        "-i", input_path,
        output_path
    ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

# ================= 語音辨識 =================
def transcribe_audio(file_path):
    with open(file_path, "rb") as f:
        result = client.audio.transcriptions.create(
            model="whisper-1",
            file=f
        )
    return result.text.strip()

# ================= TTS =================
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
def upload_audio(file_path):
    result = cloudinary.uploader.upload(file_path, resource_type="video")
    return result["secure_url"]

def get_duration(path):
    return int(MP3(path).info.length * 1000)

# ================= 回覆 =================
def reply_text(token, text):
    with ApiClient(configuration) as api:
        MessagingApi(api).reply_message(
            ReplyMessageRequest(
                reply_token=token,
                messages=[TextMessage(text=text)]
            )
        )

def reply_audio(token, text, url, duration):
    with ApiClient(configuration) as api:
        MessagingApi(api).reply_message(
            ReplyMessageRequest(
                reply_token=token,
                messages=[
                    TextMessage(text=text),
                    AudioMessage(
                        original_content_url=url,
                        duration=duration
                    )
                ]
            )
        )

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
        translated = translate_text(event.message.text)
        reply_text(event.reply_token, translated)
    except Exception as e:
        reply_text(event.reply_token, f"錯誤：{e}")

# ================= 語音（已完全修好）=================
@handler.add(MessageEvent, message=AudioMessageContent)
def handle_audio(event):
    m4a_path = None
    wav_path = None
    tts_path = None

    try:
        with ApiClient(configuration) as api:
            blob = MessagingApiBlob(api)
            content = blob.get_message_content(event.message.id)

            with tempfile.NamedTemporaryFile(delete=False, suffix=".m4a") as f:
                for chunk in content:
                    if isinstance(chunk, bytes):
                        f.write(chunk)
                m4a_path = f.name

        # 🔥 轉 wav（關鍵）
        wav_path = m4a_path.replace(".m4a", ".wav")
        convert_to_wav(m4a_path, wav_path)

        text = transcribe_audio(wav_path)
        translated = translate_text(text)

        with tempfile.NamedTemporaryFile(delete=False, suffix=".mp3") as f:
            tts_path = f.name

        generate_tts_audio(translated, tts_path)

        duration = get_duration(tts_path)
        url = upload_audio(tts_path)

        reply_audio(event.reply_token, translated, url, duration)

    except Exception as e:
        print("🔥 Audio error:", e)
        reply_text(event.reply_token, f"語音錯誤：{e}")

    finally:
        for p in [m4a_path, wav_path, tts_path]:
            if p and os.path.exists(p):
                os.remove(p)

@app.route("/")
def home():
    return "OK"

if __name__ == "__main__":
    app.run()
