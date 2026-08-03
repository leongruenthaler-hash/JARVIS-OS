import sounddevice as sd
import scipy.io.wavfile as wav

print("Sage jetzt: Jarvis")

audio = sd.rec(
    int(3 * 16000),
    samplerate=16000,
    channels=1,
    device=0
)

sd.wait()

wav.write("wake.wav", 16000, audio)

print("Aufnahme gespeichert.")