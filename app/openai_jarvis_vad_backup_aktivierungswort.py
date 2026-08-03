from openai import OpenAI
from dotenv import load_dotenv
import whisper
import sounddevice as sd
import soundfile as sf
import numpy as np
import os

load_dotenv()

client = OpenAI()

print("Whisper Turbo wird geladen...")
model = whisper.load_model("turbo")

SAMPLERATE = 16000
CHANNELS = 1

verlauf = []

AKTIVIERUNGSWORT = "jarvis"

print("JARVIS GPT-5 NANO VAD gestartet.")

while True:

    print("\nSprich jetzt...")

    aufnahme = []

    def callback(indata, frames, time, status):
        aufnahme.append(indata.copy())

    with sd.InputStream(
        samplerate=SAMPLERATE,
        channels=CHANNELS,
        callback=callback
    ):

        stille_zeit = 0

        while True:

            if len(aufnahme) == 0:
                sd.sleep(100)
                continue

            letzter_block = aufnahme[-1]

            lautstaerke = np.abs(letzter_block).mean()

            if lautstaerke < 0.01:
                stille_zeit += 0.1
            else:
                stille_zeit = 0

            if stille_zeit >= 1.0:
                break

            sd.sleep(100)

    audio = np.concatenate(aufnahme, axis=0)

    sf.write(
        "test.wav",
        audio,
        SAMPLERATE
    )

    try:

        result = model.transcribe(
            "test.wav",
            language="de"
        )

        frage = result["text"].strip()

        if frage == "":
            continue

        blacklist = [
            "vielen dank",
            "vielen dank.",
            "danke",
            "danke.",
            "tschüss",
            "tschüss.",
            "bis zum nächsten mal",
            "bis zum nächsten mal.",
            "untertitel im auftrag des zdf",
            "untertitel im auftrag des zdf."
        ]

        if frage.lower() in blacklist:
            print("Halluzination erkannt -> ignoriert")
            continue

        print(f"\nLeon: {frage}")

        if "exit" in frage.lower():
            break

        # Aktivierungswort prüfen
        if AKTIVIERUNGSWORT not in frage.lower():
            print("Aktivierungswort nicht erkannt -> ignoriert")
            continue

        frage = frage.replace("Jarvis", "")
        frage = frage.replace("jarvis", "")
        frage = frage.strip()

        verlauf.append({
            "role": "user",
            "content": frage
        })

        antwort = client.responses.create(
            model="gpt-5-nano",
            input=verlauf
        )

        text = antwort.output_text.strip()

        verlauf.append({
            "role": "assistant",
            "content": text
        })

        if len(verlauf) > 20:
            verlauf = verlauf[-20:]

        print(f"\nJARVIS: {text}")

        os.system(f'say "{text}"')

    except Exception as e:
        print("Fehler:", e)