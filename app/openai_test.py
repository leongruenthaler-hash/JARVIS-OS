from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

client = OpenAI()

response = client.responses.create(
    model="gpt-5",
    input="Sag nur: Hallo Leon, OpenAI funktioniert."
)

print(response.output_text)