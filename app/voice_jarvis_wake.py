import sounddevice as sd
import scipy.io.wavfile as wav
import whisper
from difflib import SequenceMatcher

print("Lade Whisper...")
model = whisper.load_model("base")

print("JARVIS bereit.")
print("Sage 'Hallo Jarvis'.")

def similar(a, b):
    return SequenceMatcher(None, a, b).ratio()

while True:

    print("\nSprich jetzt 5 Sekunden...")

    audio = sd.rec(
        int(5 * 16000),
        samplerate=16000,
        channels=1,
        dtype="int16"
    )

    sd.wait()

    wav.write("wake.wav", 16000, audio)

    result = model.transcribe(
        "wake.wav",
        language="de"
    )

    text = result["text"].lower().strip()

    print(f"\nErkannt: {text}")

    wake_phrases = [
        "hallo jarvis",
        "jarvis",
        "hallo javus",
        "hallo javas",
        "hallo jarosz",
        "hallo travis"
    ]

    wake_detected = False

    for phrase in wake_phrases:

        if phrase in text:
            wake_detected = True
            break

        if similar(text, phrase) > 0.65:
            wake_detected = True
            break

    if wake_detected:

        print("\n✅ JARVIS AKTIVIERT!")
        print("Sprich deine Frage...")

        audio = sd.rec(
            int(10 * 16000),
            samplerate=16000,
            channels=1,
            dtype="int16"
        )

        sd.wait()

        wav.write("frage.wav", 16000, audio)

        result = model.transcribe(
            "frage.wav",
            language="de"
        )

        frage = result["text"]

        print(f"\nLeon: {frage}")

    else:

        print("\n❌ Kein Wakeword erkannt.")