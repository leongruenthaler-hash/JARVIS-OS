import sounddevice as sd
import soundfile as sf
import whisper

SAMPLERATE = 16000
SECONDS = 5

print("Aufnahme startet...")

audio = sd.rec(
    int(SECONDS * SAMPLERATE),
    samplerate=SAMPLERATE,
    channels=1,
    dtype="int16"
)

sd.wait()

sf.write("test_v2.wav", audio, SAMPLERATE)

print("Aufnahme gespeichert.")

model = whisper.load_model("tiny")

result = model.transcribe("test_v2.wav")

print("\nErkannt:")
print(result["text"])