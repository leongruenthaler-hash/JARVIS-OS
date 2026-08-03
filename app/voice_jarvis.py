import whisper
import requests
import os

model = whisper.load_model("base")

print("JARVIS Sprachmodus gestartet.")

while True:
    audio_file = "test.wav"

    print("\nSprich jetzt 5 Sekunden...")

    os.system('ffmpeg -y -f avfoundation -i ":0" -t 5 test.wav >/dev/null 2>&1')

    result = model.transcribe(audio_file)
    user_input = result["text"]

    print("\nLeon:", user_input)

    if "exit" in user_input.lower():
        break

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

    os.system(f'say "{answer}"')