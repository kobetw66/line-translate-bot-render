import os
import tempfile
import json
from flask import Flask, request, abort
from dotenv import load_dotenv
from openai import OpenAI
from gtts import gTTS
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

def load_care_dictionary():
    try:
        with open(
            "care_dictionary.json",
            "r",
            encoding="utf-8"
        ) as f:
            return json.load(f)

    except Exception as e:
        print("Care dictionary error:", e)
        return {}


CARE_DICT = load_care_dictionary()

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

# ================= 翻譯（乾淨輸出）=================
def translate_text(text):
    if is_chinese(text):
        prompt = f"""
你是台灣家庭照護印尼語翻譯助手。

重要設定：
- 使用地區：台灣
- 中文輸出：繁體中文（Traditional Chinese）
- 禁止輸出簡體中文
- 禁止使用中國大陸詞語

家庭照護詞庫：

{CARE_DICT}
家庭稱呼規則：

kakek 固定翻譯為「阿公」
nenek 固定翻譯為「阿嬤」

禁止翻譯成：
祖父
祖母
爺爺
奶奶

請使用台灣家庭照護稱呼。
翻譯規則：

1. 印尼文翻譯成自然的台灣繁體中文。
2. 中文翻譯成印尼看護容易理解的口語。
3. 不逐字翻譯，要理解照護情境。
4. 不可增加原文沒有的事情。
5. 跌倒、受傷、吃藥相關訊息要保持原意。
6. 不要加入解釋。
7. 只輸出翻譯結果。

中文用字要求：

爺爺，不使用 爷爷
奶奶，不使用 奶奶（簡體相同，保持繁體）
臉，不使用 脸
藥，不使用 药
幫助，不使用 帮助
裡，不使用 里

內容：

{text}
"""
else:
    prompt = f"""
你是台灣家庭照護印尼語翻譯助手。

請將中文翻譯成印尼籍看護容易理解的自然印尼文。


【固定照護詞彙】

阿公 = kakek
阿嬤 = nenek
吃藥 = minum obat
換尿布 = ganti popok
洗澡 = mandi
睡覺 = tidur
跌倒 = jatuh
受傷 = terluka


【重要規則】

1. 中文詞彙必須轉換成上述印尼照護用語。

2. 不可以保留中文。

3. 只輸出印尼文。

4. 不要加入說明。

5. 使用家庭口語，例如：
Tolong ... ya.


內容：

{text}
"""


    response = client.responses.create(
        model="gpt-4o-mini",
        input=prompt
    )

    return response.output_text.strip().replace('"', '')

# ================= 語音辨識 =================
def transcribe_audio(file_path):
    with open(file_path, "rb") as f:
        result = client.audio.transcriptions.create(
            model="whisper-1",
            file=f
        )
    return result.text.strip()

# ================= gTTS（免費語音）=================
def generate_tts_audio(text, output_path):
    if is_chinese(text):
        lang = "zh-TW"
    else:
        lang = "id"

    tts = gTTS(text=text, lang=lang)
    tts.save(output_path)

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

# ================= 音訊儲存（穩定版）=================
def save_line_audio(audio_content, file_path):
    if isinstance(audio_content, bytes):
        audio_bytes = audio_content
    else:
        audio_bytes = audio_content.read()

    with open(file_path, "wb") as f:
        f.write(audio_bytes)

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

# ================= 語音 =================
@handler.add(MessageEvent, message=AudioMessageContent)
def handle_audio(event):
    m4a_path = None
    tts_path = None

    try:
        with ApiClient(configuration) as api:
            blob = MessagingApiBlob(api)
            content = blob.get_message_content(event.message.id)

            with tempfile.NamedTemporaryFile(delete=False, suffix=".m4a") as f:
                m4a_path = f.name

        save_line_audio(content, m4a_path)

        text = transcribe_audio(m4a_path)
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
        if m4a_path and os.path.exists(m4a_path):
            os.remove(m4a_path)
        if tts_path and os.path.exists(tts_path):
            os.remove(tts_path)

@app.route("/")
def home():
    return "OK"

if __name__ == "__main__":
    app.run()
