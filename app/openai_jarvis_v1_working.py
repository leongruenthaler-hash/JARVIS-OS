from openai import OpenAI
from dotenv import load_dotenv
import whisper
import os

load_dotenv()

client = OpenAI()

print("Whisper Turbo wird geladen...")
model = whisper.load_model("turbo")

print("JARVIS GPT-5 NANO gestartet.")

while True:

    print("\nSprich jetzt...")

    os.system(
        'ffmpeg -y -f avfoundation -i ":0" -t 10 test.wav >/dev/null 2>&1'
    )

    try:

        result = model.transcribe(
            "test.wav",
            language="de"
        )

        frage = result["text"].strip()

        if frage == "":
            continue

        print(f"\nLeon: {frage}")

        if "exit" in frage.lower():
            break

        antwort = client.responses.create(
            model="gpt-5-nano",
            input=frage
        )

        text = antwort.output_text.strip()

        print(f"\nJARVIS: {text}")

        os.system(f'say "{text}"')

    except Exception as e:
        print("Fehler:", e)