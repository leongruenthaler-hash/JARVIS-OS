import sounddevice as sd
import scipy.io.wavfile as wav

print("Sprich jetzt 5 Sekunden deutlich ins Mikrofon...")

audio = sd.rec(
    int(5 * 16000),
    samplerate=16000,
    channels=1,
    dtype="int16",
    device=0
)

sd.wait()

wav.write("mic_test.wav", 16000, audio)

print("Fertig.")