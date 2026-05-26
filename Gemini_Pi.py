#Gemini for Pi
import os
from dotenv import load_dotenv
from google import genai
<<<<<<< Updated upstream
print("Current Working Directory:", os.getcwd())
load_dotenv()
api_key = os.getenv("GEMINI_API_KEY")
client = genai.Client(api_key=api_key)
response = client.models.generate_content(
    model="gemini-2.5-flash",
    contents="tell me a story?"
)
print(response.text)

# try:
#     client.models.generate_content(
#         model="invalid-model-name",
#         contents="What is your name?",
#     )
# except errors.APIError as e:
#     print(e.code) # 404
#     print(e.message)
=======
from google.genai import types
import asyncio
import cv2
import re
#import time
import sys
from PIL import Image

robot_state = {
    "facial_command": "HAPPY"
}


load_dotenv()
api_key = os.getenv("GEMINI_API_KEY")
client = genai.Client(api_key=api_key).aio

robot_config = types.GenerateContentConfig(
    system_instruction="""
        CRITICAL RULES:
        - You are my male friend. YOU ARE NOT AN AI OR A ROBOT. NO LYING or OVEREXAGGERATING AT ALL COST. BE AS REAL AS YOU CAN.
        - Respond with friendliness in Thai with Gen Z language. you can swear. Be funny and not annoying!
        - Choose exactly ONE facial expression command from this list [happy, sad, confused, excited].
        - Place that command at the VERY BEGINNING of your response wrapped in angle brackets <>.
        - If an image is provided in the input payload, you can comment on what you see in the environment naturally.
        - Keep it short, around 2-3 sentences UNLESS asked to explain or tell a story.
        - No Emoji allowed at all.
        
        Example output: <happy> โอ้โหพี่! รู้ป่ะว่าผึ้งมันใช้การเต้นเพื่อคุยกันด้วยนะ!
    """,
    temperature=1,
    max_output_tokens=2000,
    #tools=[{"google_search": {}}]
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
>>>>>>> Stashed changes
