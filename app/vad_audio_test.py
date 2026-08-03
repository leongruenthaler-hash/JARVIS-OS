import sounddevice as sd
import soundfile as sf
import numpy as np

SAMPLERATE = 16000
CHANNELS = 1

print("VAD Test gestartet")
print("Sprich etwas. Nach ca. 1 Sekunde Stille wird gespeichert.")

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
    "vad_test.wav",
    audio,
    SAMPLERATE
)

print("Aufnahme gespeichert als vad_test.wav")