import requests
import os

SYSTEM_PROMPT = """
Du bist JARVIS.

Du bist der persönliche Assistent von Leon.

Du sprichst Deutsch.

Du bist höflich, intelligent und ruhig.

Begrüße Leon freundlich.
"""

print("JARVIS aktiviert.")
print("Zum Beenden: exit")

while True:
    user_input = input("\nLeon: ")

    if user_input.lower() == "exit":
        print("JARVIS: Auf Wiedersehen Leon.")
        break

    response = requests.post(
        "http://localhost:11434/api/generate",
        json={
            "model": "gemma3:4b",
            "prompt": SYSTEM_PROMPT + "\nLeon: " + user_input,
            "stream": False
        }
    )

    answer = response.json()["response"]

    print("\nJARVIS:", answer)
    os.system(f'say "{answer}"')