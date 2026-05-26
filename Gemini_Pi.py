#Gemini for Pi
import os
from dotenv import load_dotenv
from google import genai
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