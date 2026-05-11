import os
import tempfile
from flask import Flask, request, abort
from dotenv import load_dotenv
from openai import OpenAI

from linebot.v3 import WebhookHandler
from linebot.v3.messaging import (
    Configuration,
    ApiClient,
    MessagingApi,
    MessagingApiBlob,
    ReplyMessageRequest,
    TextMessage
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


def translate_text(text):
    response = client.responses.create(
        model="gpt-4.1-mini",
        instructions="""
你是 LINE 中文↔印尼文雙向翻譯助手。

請自動判斷使用者輸入的語言：

1. 如果輸入是繁體中文或簡體中文，請翻譯成自然、口語、禮貌的印尼文。
2. 如果輸入是印尼文，請翻譯成自然、口語、禮貌的繁體中文。
3. 如果中印尼文混合，請依主要語言判斷翻譯方向。
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


def reply_text(reply_token, text):
    with ApiClient(configuration) as api_client:
        line_bot_api = MessagingApi(api_client)
        line_bot_api.reply_message(
            ReplyMessageRequest(
                reply_token=reply_token,
                messages=[TextMessage(text=text)]
            )
        )


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
    user_text = event.message.text.strip()
    translated = translate_text(user_text)
    reply_text(event.reply_token, translated)


@handler.add(MessageEvent, message=AudioMessageContent)
def handle_audio_message(event):
    with ApiClient(configuration) as api_client:
        blob_api = MessagingApiBlob(api_client)
        audio_content = blob_api.get_message_content(event.message.id)

        with tempfile.NamedTemporaryFile(delete=False, suffix=".m4a") as temp_audio:
            temp_audio.write(audio_content)
            temp_audio_path = temp_audio.name

    try:
        transcript_text = transcribe_audio(temp_audio_path)
        translated = translate_text(transcript_text)

        reply = f"語音辨識：{transcript_text}\n\n翻譯：{translated}"
        reply_text(event.reply_token, reply)

    finally:
        if os.path.exists(temp_audio_path):
            os.remove(temp_audio_path)


@app.route("/")
def home():
    return "LINE Translate Bot Running!"


if __name__ == "__main__":
    app.run(port=5000)