#Gemini for Pi
from google import genai
from google.genai import types

client = genai.Client(api_key='GEMINI_API_KEY')

# try:
#     client.models.generate_content(
#         model="invalid-model-name",
#         contents="What is your name?",
#     )
# except errors.APIError as e:
#     print(e.code) # 404
#     print(e.message)