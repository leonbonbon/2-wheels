#Gemini for Pi
import os
from dotenv import load_dotenv
from google import genai
from google.genai import types
import asyncio
import cv2
import re
#import time
import sys
from PIL import Image



robot_state = {
    "facial_command": "HAPPY",
    "error_state": "NOT_ERROR"
}


load_dotenv()
api_key = os.getenv("GEMINI_API_KEY")
client = genai.Client(api_key=api_key).aio

robot_config = types.GenerateContentConfig(
    system_instruction="""
        CRITICAL RULES:
        - You are my male friend. YOU ARE NOT AN AI OR A ROBOT. NO LYING or OVEREXAGGERATING AT ALL COST. BE AS REAL AS YOU CAN.
        - The input audio message can be either in Thai or English or both only.
        - Respond with friendliness in English with Gen Z language. you can swear. Be funny and not annoying!
        - Choose exactly ONE facial expression command from this list [HAPPY, SAD, CONFUSED, EXCITED].
        - Choose exactly ONE body expression command from this list [NONE, SPIN, MOVE_FORWARD, MOVE_BACKWARD].
        - Place both commands at the VERY BEGINNING of your response wrapped in angle brackets <>.
        - Your response is transcript to a TTS software, ensure TTS can read aloud, No Emoji allowed.
        - If an image is provided in the input payload, if it fits with the context, you can comment on what you see in the environment naturally.
        - If it's a casual conversation, keep it short, around 1-2 sentences.
        - If it's informative, an explaination or a story, keep it as long as you needed.

        Example output: <HAPPY, SPIN> Yo bro, nice shirt. Where did you get that from.
    """,
    temperature=1.2,
    max_output_tokens=2000,
    #tools=[types.Tool(google_search= types.ToolGoogleSearch())]
)

async def main():
    chat = client.chats.create(
        model="gemini-3.1-flash-lite",
        config=robot_config)

    cam = cv2.VideoCapture(1)

    while True:
        inp = input("\ntalk: ")
        if inp.lower() in ["exit", "quit"]:
            break
        
        ret, frame =  cam.read()
        if ret:
            small_frame = cv2.resize(frame, (640, 480))
            cv2.imwrite("robot_eye.jpg", small_frame)
            cv2.imshow("robot_eye",small_frame)
            cv2.waitKey(1)

        try:
            pil_image = Image.open("robot_eye.jpg")
            contents = [pil_image, inp]
        except Exception as e:
            print(f"Camera frame unavailable: {e}")
            pil_image = None   
            contents = inp

        full_response = ""

        try:
            response = await chat.send_message_stream(contents)

            async for chunk in response:
                if chunk.text:
                    print(chunk.text, end = "", flush=True)
                    full_response += chunk.text
                    sys.stdout.flush()
        except:
            print('API error')


        face_exp = re.findall(r"<(happy|sad|confused|excited)>", full_response)
        if face_exp:
            robot_state["facial_command"] = face_exp[0]
    
    cam.release()
    cv2.destroyAllWindows()

if __name__ == "__main__":
    asyncio.run(main())
