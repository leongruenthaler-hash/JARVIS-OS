import sounddevice as sd

print("Starte Aufnahme...")

audio = sd.rec(
    int(3 * 16000),
    samplerate=16000,
    channels=1,
    device=0
)

sd.wait()

print("Aufnahme erfolgreich")
print(audio.shape)