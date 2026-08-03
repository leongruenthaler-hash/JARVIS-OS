import whisper
import requests
import os
print("Lade Whisper-Modell...")
model = whisper.load_model("base")
print("JARVIS Wake-Word-Modus gestartet.")
print("Sage: Jarvis")
while True:
    print("\nWarte auf Aktivierungswort...")
    os.system(
        'ffmpeg -y -f avfoundation -i ":0" -t 3 wake.wav >/dev/null 2>&1'
    )
    result = model.transcribe("wake.wav", language="de")
    wake_text = result["text"].strip().lower()
    print("Erkannt:", wake_text)
    if "jarvis" not in wake_text:
        continue
    print("\nJARVIS: Ja Leon?")
    os.system('say "Ja Leon?"')
    print("\nSprich jetzt deine Frage...")
    os.system(
        'ffmpeg -y -f avfoundation -i ":0" -t 8 question.wav >/dev/null 2>&1'
    )
    result = model.transcribe("question.wav", language="de")
    user_input = result["text"].strip()
    if len(user_input) < 3:
        continue
    print("\nLeon:", user_input)
    if user_input.lower() == "exit":
        print("JARVIS: Auf Wiedersehen Leon.")
        os.system('say "Auf Wiedersehen Leon."')
        break
    response = requests.post(
        "http://localhost:11434/api/generate",
        json={
            "model": "gemma3:4b",
            "prompt": f"""
Du bist JARVIS.
Du bist der persönliche Assistent von Leon.
Antworte kurz, hilfreich und auf Deutsch.
Leon: {user_input}
""",
            "stream": False
        }
    )
    answer = response.json()["response"].strip()
    print("\nJARVIS:", answer)
    safe_answer = answer.replace('"', "'")
    os.system(f'say "{safe_answer}"')