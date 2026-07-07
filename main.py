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


# ================= 環境變數 =================

load_dotenv()


# ================= 家庭照護詞庫 =================

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



# ================= Flask =================

app = Flask(__name__)



# ================= OpenAI =================

client = OpenAI(
    api_key=os.getenv("OPENAI_API_KEY")
)



# ================= LINE =================

handler = WebhookHandler(
    os.getenv("LINE_CHANNEL_SECRET")
)


configuration = Configuration(
    access_token=os.getenv(
        "LINE_CHANNEL_ACCESS_TOKEN"
    )
)



# ================= Cloudinary =================

cloudinary.config(

    cloud_name=os.getenv(
        "CLOUDINARY_CLOUD_NAME"
    ),

    api_key=os.getenv(
        "CLOUDINARY_API_KEY"
    ),

    api_secret=os.getenv(
        "CLOUDINARY_API_SECRET"
    )

)



# ================= 語言判斷 =================

def is_chinese(text):

    return any(
        '\u4e00' <= ch <= '\u9fff'
        for ch in text
    )



# ================= AI 雙向翻譯 =================

def translate_text(text):


    if is_chinese(text):


        # 中文 → 印尼文

        prompt = f"""

你是台灣家庭照護印尼語翻譯助手。


請將以下繁體中文翻譯成自然的印尼文。


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

1. 只輸出印尼文。

2. 不要保留任何中文。

3. 不要加入「翻譯是」。

4. 不要加引號。

5. 使用印尼籍看護日常口語。

6. 保持照護語氣。



【家庭詞庫】

{json.dumps(
    CARE_DICT,
    ensure_ascii=False
)}



內容：

{text}

"""



    else:


        # 印尼文 → 中文


        prompt = f"""

你是台灣家庭照護印尼語翻譯助手。


請將以下印尼文翻譯成台灣繁體中文。


【固定照護詞彙】

kakek = 阿公

nenek = 阿嬤

minum obat = 吃藥

ganti popok = 換尿布

mandi = 洗澡

tidur = 睡覺

jatuh = 跌倒

terluka = 受傷



【重要規則】

1. 使用台灣繁體中文。

2. 禁止使用簡體中文。

3. 不使用中國大陸用語。

4. 不自行增加原文沒有的事情。

5. 只輸出翻譯結果。



【家庭詞庫】

{json.dumps(
    CARE_DICT,
    ensure_ascii=False
)}



內容：

{text}

"""



    response = client.responses.create(

        model="gpt-4o-mini",

        input=prompt

    )


    return (
        response.output_text
        .strip()
        .replace('"', '')
    )
# ================= 語音辨識 =================

def transcribe_audio(file_path):

    with open(file_path, "rb") as f:

        result = client.audio.transcriptions.create(

            model="whisper-1",

            file=f

        )


    return result.text.strip()



# ================= Google TTS 免費語音 =================

def generate_tts_audio(text, output_path):

    if is_chinese(text):

        lang = "zh-TW"

    else:

        lang = "id"



    tts = gTTS(

        text=text,

        lang=lang

    )


    tts.save(output_path)



# ================= Cloudinary 上傳 =================

def upload_audio(file_path):

    result = cloudinary.uploader.upload(

        file_path,

        resource_type="video"

    )


    return result["secure_url"]



# ================= 取得 MP3 長度 =================

def get_duration(path):

    audio = MP3(path)

    return int(
        audio.info.length * 1000
    )



# ================= LINE文字回覆 =================

def reply_text(token, text):

    with ApiClient(configuration) as api:

        MessagingApi(api).reply_message(

            ReplyMessageRequest(

                reply_token=token,

                messages=[

                    TextMessage(
                        text=text
                    )

                ]

            )

        )



# ================= LINE文字+語音回覆 =================

def reply_audio(
    token,
    text,
    url,
    duration
):

    with ApiClient(configuration) as api:

        MessagingApi(api).reply_message(

            ReplyMessageRequest(

                reply_token=token,

                messages=[

                    TextMessage(
                        text=text
                    ),

                    AudioMessage(

                        original_content_url=url,

                        duration=duration

                    )

                ]

            )

        )



# ================= LINE音訊儲存 =================

def save_line_audio(
    audio_content,
    file_path
):

    if isinstance(
        audio_content,
        bytes
    ):

        audio_bytes = audio_content

    else:

        audio_bytes = audio_content.read()



    with open(
        file_path,
        "wb"
    ) as f:

        f.write(audio_bytes)



# ================= Webhook =================

@app.route(
    "/callback",
    methods=["POST"]
)

def callback():

    signature = request.headers.get(
        "X-Line-Signature"
    )


    body = request.get_data(
        as_text=True
    )


    try:

        handler.handle(
            body,
            signature
        )


    except InvalidSignatureError:

        abort(400)



    return "OK"





# ================= 文字訊息 =================

@handler.add(
    MessageEvent,
    message=TextMessageContent
)

def handle_text(event):

    try:

        translated = translate_text(

            event.message.text

        )


        reply_text(

            event.reply_token,

            translated

        )


    except Exception as e:


        print(
            "Text error:",
            e
        )


        reply_text(

            event.reply_token,

            f"錯誤：{e}"

        )





# ================= 語音訊息 =================

@handler.add(
    MessageEvent,
    message=AudioMessageContent
)

def handle_audio(event):

    m4a_path = None

    tts_path = None


    try:


        # 下載 LINE 語音

        with ApiClient(configuration) as api:


            blob = MessagingApiBlob(api)


            content = blob.get_message_content(

                event.message.id

            )



        with tempfile.NamedTemporaryFile(

            delete=False,

            suffix=".m4a"

        ) as f:


            m4a_path = f.name



        save_line_audio(

            content,

            m4a_path

        )



        # Whisper 轉文字

        text = transcribe_audio(

            m4a_path

        )



        # AI 翻譯

        translated = translate_text(

            text

        )



        # 建立語音

        with tempfile.NamedTemporaryFile(

            delete=False,

            suffix=".mp3"

        ) as f:


            tts_path = f.name



        generate_tts_audio(

            translated,

            tts_path

        )



        duration = get_duration(

            tts_path

        )



        url = upload_audio(

            tts_path

        )



        reply_audio(

            event.reply_token,

            translated,

            url,

            duration

        )



    except Exception as e:


        print(

            "🔥 Audio error:",

            e

        )


        reply_text(

            event.reply_token,

            f"語音錯誤：{e}"

        )



    finally:


        if (
            m4a_path
            and os.path.exists(m4a_path)
        ):

            os.remove(
                m4a_path
            )


        if (
            tts_path
            and os.path.exists(tts_path)
        ):

            os.remove(
                tts_path
            )





# ================= 測試首頁 =================

@app.route("/")

def home():

    return "LINE Translate Bot OK"





# ================= Render 啟動 =================

if __name__ == "__main__":

    app.run(
        host="0.0.0.0",
        port=int(
            os.environ.get(
                "PORT",
                10000
            )
        )
    )    
