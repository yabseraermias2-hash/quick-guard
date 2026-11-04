import speech_recognition as sr
import subprocess
import requests

# This makes QUICK speak
def speak(text):
    print(f"QUICK: {text}")
    subprocess.run(['say', '-r', '175', text])

# This makes QUICK listen to you
def listen():
    recognizer = sr.Recognizer()
    with sr.Microphone() as source:
        print("Listening...")
        recognizer.adjust_for_ambient_noise(source, duration=1)
        audio = recognizer.listen(source, timeout=5)
    try:
        text = recognizer.recognize_google(audio)
        print(f"You said: {text}")
        return text
    except:
        return None

# This sends your words to the AI brain
def ask_quick(question):
    response = requests.post(
        "http://localhost:11434/api/generate",
        json={
            "model": "llama3",
            "prompt": f"You are QUICK, a smart AI assistant. Be helpful and concise. User says: {question}",
            "stream": False
        }
    )
    data = response.json()
    return data["response"]

# Main loop - QUICK keeps running until you say goodbye
def run():
    speak("QUICK online. How can I help you?")
    while True:
        user_input = listen()
        if user_input is None:
            speak("I didn't catch that. Try again.")
            continue
        if "goodbye" in user_input.lower() or "shut down" in user_input.lower():
            speak("Shutting down. Goodbye.")
            break
        response = ask_quick(user_input)
        speak(response)

run()