import os
import requests
from dotenv import load_dotenv

load_dotenv()

api_key = os.environ.get('VITE_GEMINI_API_KEY')
print(f"API Key found: {api_key[:5]}...{api_key[-5:] if api_key else 'None'}")

url = (
    'https://generativelanguage'
    '.googleapis.com/v1beta/models/'
    'gemini-2.0-flash:generateContent'
    f'?key={api_key}'
)

payload = {
    'contents': [{'role': 'user', 'parts': [{'text': 'Hello'}]}]
}

resp = requests.post(url, json=payload)
print(f"Status: {resp.status_code}")
if resp.ok:
    print("Response:", resp.json()['candidates'][0]['content']['parts'][0]['text'])
else:
    print("Error:", resp.json())
