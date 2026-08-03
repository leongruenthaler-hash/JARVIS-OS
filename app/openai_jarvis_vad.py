from openai import OpenAI
from dotenv import load_dotenv
import whisper
import sounddevice as sd
import soundfile as sf
import numpy as np
import os

from memory import Memory

load_dotenv()

client = OpenAI()
memory = Memory()

print("Whisper Turbo wird geladen...")
model = whisper.load_model("turbo")

SAMPLERATE = 16000
CHANNELS = 1

verlauf = []

AKTIVIERUNGSWOERTER = [
    "jarvis",
    "travis",
    "charvis",
    "jarwes",
    "jarviss"
]

print("JARVIS GPT-5 NANO VAD + MEMORY gestartet.")

while True:
    print("\nSprich jetzt...")

    aufnahme = []

    def callback(indata, frames, time, status):
        aufnahme.append(indata.copy())

    with sd.InputStream(samplerate=SAMPLERATE,
                        channels=CHANNELS,
                        callback=callback):

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
    sf.write("test.wav", audio, SAMPLERATE)

    try:
        result = model.transcribe("test.wav", language="de")
        frage = result["text"].strip()

        if not frage:
            continue

        print(f"\nLeon: {frage}")

        if "exit" in frage.lower():
            break

        text_lower = frage.lower()

        if not any(wort in text_lower for wort in AKTIVIERUNGSWOERTER):
            print("Aktivierungswort nicht erkannt -> ignoriert")
            continue

        for wort in AKTIVIERUNGSWOERTER:
            frage = frage.replace(wort, "").replace(wort.capitalize(), "")

        frage = frage.strip()

        memory.add_conversation("user", frage)

        verlauf.append({
            "role": "user",
            "content": frage
        })

        antwort = client.responses.create(
            model="gpt-5-nano",
            input=verlauf
        )

        text = antwort.output_text.strip()

        memory.add_conversation("assistant", text)

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