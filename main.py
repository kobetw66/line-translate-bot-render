import os
from flask import Flask, request, abort
from dotenv import load_dotenv
from openai import OpenAI

from linebot.v3 import WebhookHandler
from linebot.v3.messaging import (
    Configuration,
    ApiClient,
    MessagingApi,
    ReplyMessageRequest,
    TextMessage
)
from linebot.v3.webhooks import MessageEvent, TextMessageContent
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
def handle_message(event):
    user_text = event.message.text

    translated = translate_text(user_text)

    with ApiClient(configuration) as api_client:
        line_bot_api = MessagingApi(api_client)

        line_bot_api.reply_message(
            ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[
                    TextMessage(text=translated)
                ]
            )
        )


@app.route("/")
def home():
    return "LINE Translate Bot Running!"


if __name__ == "__main__":
    app.run(port=5000)