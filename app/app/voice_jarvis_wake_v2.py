import sounddevice as sd
import scipy.io.wavfile as wav
import whisper
import requests
import os
import time

print("Lade Whisper...")
model = whisper.load_model("base")

print("JARVIS bereit.")
print("Sage 'Jarvis' zum Aktivieren.")

while True:

    print("\nWarte auf Wakeword...")

    audio = sd.rec(
        int(3 * 16000),
        samplerate=16000,
        channels=1,
        device=0
    )

    sd.wait()

    wav.write("wake.wav", 16000, audio)

    result = model.transcribe("wake.wav")
    wake_text = result["text"].lower()

    print("Erkannt:", wake_text)

    if "jarvis" not in wake_text:
        continue

    os.system('say "Ja Leon?"')

    print("Jarvis aktiviert.")

    audio = sd.rec(
        int(8 * 16000),
        samplerate=16000,
        channels=1,
        device=0
    )

    sd.wait()

    wav.write("question.wav", 16000, audio)

    result = model.transcribe("question.wav")
    user_input = result["text"]

    print("\nLeon:", user_input)

    if not user_input.strip():
        continue

    response = requests.post(
        "http://localhost:11434/api/generate",
        json={
            "model": "gemma3:4b",
            "prompt": user_input,
            "stream": False
        }
    )

    answer = response.json()["response"]

    print("\nJARVIS:", answer)

    safe_answer = answer.replace('"', "'")

    os.system(f'say "{safe_answer}"')

    time.sleep(1)