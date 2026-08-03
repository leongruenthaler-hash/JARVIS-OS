from openai import OpenAI
from dotenv import load_dotenv
import whisper
import os

load_dotenv()

client = OpenAI()

print("Lade Whisper Tiny...")
model = whisper.load_model("small")

print("JARVIS GPT-5 Nano gestartet.")

while True:

    print("\nSprich jetzt 5 Sekunden...")

    os.system(
        'ffmpeg -y -f avfoundation -i ":0" -t 5 test.wav >/dev/null 2>&1'
    )

    try:
        result = model.transcribe("test.wav")
        frage = result["text"].strip()

        if len(frage) < 3:
            print("⚠️ Nichts erkannt")
            continue

        print(f"\nLeon: {frage}")

        if "exit" in frage.lower():
            print("JARVIS wird beendet.")
            break

        antwort = client.responses.create(
            model="gpt-5-nano",
            input=frage
        )

        text = antwort.output_text.strip()

        print(f"\nJARVIS: {text}")

        os.system(f'say "{text}"')

    except Exception as e:
        print(f"❌ Fehler: {e}")