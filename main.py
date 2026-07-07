# ==============================
# LINE AI 照護翻譯助手
# main.py 第 1 段
# ==============================


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



# ==============================
# 環境變數
# ==============================

load_dotenv()



# ==============================
# 讀取家庭照護詞庫
# ==============================

def load_care_dictionary():

    try:

        with open(

            "care_dictionary.json",

            "r",

            encoding="utf-8"

        ) as f:

            return json.load(f)



    except Exception as e:

        print(
            "Care dictionary error:",
            e
        )

        return {}



CARE_DICT = load_care_dictionary()



# ==============================
# Flask
# ==============================

app = Flask(__name__)




# ==============================
# OpenAI
# ==============================

client = OpenAI(

    api_key=os.getenv(
        "OPENAI_API_KEY"
    )

)




# ==============================
# LINE
# ==============================

handler = WebhookHandler(

    os.getenv(
        "LINE_CHANNEL_SECRET"
    )

)



configuration = Configuration(

    access_token=os.getenv(

        "LINE_CHANNEL_ACCESS_TOKEN"

    )

)




# ==============================
# Cloudinary
# ==============================

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




# ==============================
# 語言判斷
# ==============================

def is_chinese(text):

    return any(

        '\u4e00' <= ch <= '\u9fff'

        for ch in text

    )





# ==============================
# AI 雙向翻譯
# ==============================

def translate_text(text):


    if is_chinese(text):


        # ======================
        # 中文 → 印尼文
        # ======================


        prompt = f"""

你是台灣家庭照護印尼語翻譯助手。


任務：

將以下繁體中文翻譯成自然的印尼文。


【強制規則】

1. 所有中文都必須翻譯成印尼文。

2. 即使只有一個詞，也必須翻譯。

3. 不可以保留中文原文。

4. 不要輸出中文。

5. 不要加入說明。

6. 不要加入「翻譯是」。

7. 不要加引號。

8. 使用印尼家庭照護日常口語。



【常用翻譯】

測試 = Tes

你好 = Halo

謝謝 = Terima kasih



【照護固定詞】

阿公 = kakek

阿嬤 = nenek

吃藥 = minum obat

換尿布 = ganti popok

洗澡 = mandi

睡覺 = tidur

跌倒 = jatuh

受傷 = terluka



【家庭照護詞庫】

{json.dumps(

    CARE_DICT,

    ensure_ascii=False

)}



內容：

{text}

"""



    else:


        # ======================
        # 印尼文 → 中文
        # ======================


        prompt = f"""


你是台灣家庭照護印尼語翻譯助手。


任務：

將以下印尼文翻譯成台灣繁體中文。


【強制規則】

1. 使用繁體中文。

2. 禁止使用簡體中文。

3. 不使用中國大陸用語。

4. 不增加原文沒有的事情。

5. 只輸出翻譯結果。

6. 不加入解釋。



【固定詞】

kakek = 阿公

nenek = 阿嬤

minum obat = 吃藥

ganti popok = 換尿布

mandi = 洗澡

tidur = 睡覺

jatuh = 跌倒

terluka = 受傷



【家庭照護詞庫】

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

# ==============================
# 語音辨識 Whisper
# ==============================

def transcribe_audio(file_path):

    with open(
        file_path,
        "rb"
    ) as audio_file:


        result = client.audio.transcriptions.create(

            model="whisper-1",

            file=audio_file

        )


    return result.text.strip()





# ==============================
# Google TTS 語音生成
# ==============================

def generate_tts_audio(
    text,
    output_path
):


    # 中文 → 中文語音
    # 印尼文 → 印尼語音

    if is_chinese(text):

        lang = "zh-TW"

    else:

        lang = "id"



    tts = gTTS(

        text=text,

        lang=lang

    )


    tts.save(output_path)






# ==============================
# Cloudinary 上傳 MP3
# ==============================

def upload_audio(file_path):


    result = cloudinary.uploader.upload(

        file_path,

        resource_type="video"

    )


    return result["secure_url"]






# ==============================
# 取得 MP3 秒數
# ==============================

def get_duration(path):


    audio = MP3(path)


    return int(

        audio.info.length * 1000

    )






# ==============================
# LINE 回覆文字
# ==============================

def reply_text(
    token,
    text
):


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






# ==============================
# LINE 回覆文字 + 語音
# ==============================

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







# ==============================
# LINE 音訊存檔
# ==============================

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

# ==============================
# LINE Webhook
# ==============================

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





# ==============================
# 文字訊息處理
# ==============================

@handler.add(

    MessageEvent,

    message=TextMessageContent

)

def handle_text(event):


    try:


        user_text = event.message.text.strip()



        if not user_text:

            return



        translated = translate_text(

            user_text

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

            f"翻譯錯誤：{e}"

        )






# ==============================
# 語音訊息處理
# ==============================

@handler.add(

    MessageEvent,

    message=AudioMessageContent

)

def handle_audio(event):


    m4a_path = None

    mp3_path = None



    try:



        # 下載 LINE 語音

        with ApiClient(configuration) as api:


            blob_api = MessagingApiBlob(api)



            audio_content = blob_api.get_message_content(

                event.message.id

            )




        # 暫存 m4a

        with tempfile.NamedTemporaryFile(

            delete=False,

            suffix=".m4a"

        ) as f:


            m4a_path = f.name



        save_line_audio(

            audio_content,

            m4a_path

        )




        # Whisper 語音轉文字

        original_text = transcribe_audio(

            m4a_path

        )



        if not original_text:


            reply_text(

                event.reply_token,

                "沒有辨識到語音內容"

            )

            return





        # AI翻譯

        translated = translate_text(

            original_text

        )





        # 建立 TTS MP3

        with tempfile.NamedTemporaryFile(

            delete=False,

            suffix=".mp3"

        ) as f:


            mp3_path = f.name




        generate_tts_audio(

            translated,

            mp3_path

        )





        # 上傳 Cloudinary

        url = upload_audio(

            mp3_path

        )



        duration = get_duration(

            mp3_path

        )





        # 回 LINE

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

            mp3_path

            and os.path.exists(mp3_path)

        ):


            os.remove(

                mp3_path

            )







# ==============================
# 首頁測試
# ==============================

@app.route("/")

def home():

    return "LINE AI Care Translator Running"







# ==============================
# Render 啟動
# ==============================

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
