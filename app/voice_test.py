import whisper

model = whisper.load_model("base")

result = model.transcribe(
    "neue_aufnahme.wav",
    language="de"
)

print(result["text"])