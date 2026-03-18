from flask import Flask, request, send_file, render_template
import os
import srt
import time
import io
import subprocess
from datetime import timedelta
from collections import Counter

import azure.cognitiveservices.speech as speechsdk
from pydub import AudioSegment
from langdetect import detect

app = Flask(__name__)

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
UPLOAD_FOLDER = os.path.join(BASE_DIR, "uploads")
OUTPUT_FOLDER = os.path.join(BASE_DIR, "outputs")

os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(OUTPUT_FOLDER, exist_ok=True)

# 🔑 Azure config
SPEECH_KEY = "FRWM9EPWSqtWOHmr37bRN81quMyXT1NnjqIVRrQku3g0C60vfKeIJQQJ99CCACYeBjFXJ3w3AAAYACOG70Xz"
SERVICE_REGION = "eastus"

# =========================
# 🧠 FUNCTIONS
# =========================

def parse_srt(file_path):
    with open(file_path, 'r', encoding='utf-8') as f:
        subs = srt.parse(f.read())
        return [(sub.start, sub.end, sub.content) for sub in subs]


def detect_majority_language(segments):
    langs = []
    for _, _, content in segments:
        try:
            langs.append(detect(content))
        except:
            pass
    return Counter(langs).most_common(1)[0][0] if langs else "en"


def tts_azure_to_file(text, voice, rate, output_path):
    speech_config = speechsdk.SpeechConfig(
        subscription=SPEECH_KEY,
        region=SERVICE_REGION
    )

    speech_config.speech_synthesis_voice_name = voice

    ssml = f"""
    <speak version='1.0' xml:lang='{voice.split('-')[0]}'>
        <voice name='{voice}'>
            <prosody rate='{rate}'>
                {text}
            </prosody>
        </voice>
    </speak>
    """

    audio_config = speechsdk.audio.AudioOutputConfig(filename=output_path)

    synthesizer = speechsdk.SpeechSynthesizer(
        speech_config=speech_config,
        audio_config=audio_config
    )

    result = synthesizer.speak_ssml_async(ssml).get()

    return result.reason == speechsdk.ResultReason.SynthesizingAudioCompleted


def get_duration(file_path):
    result = subprocess.run(
        ["ffprobe", "-i", file_path,
         "-show_entries", "format=duration",
         "-v", "quiet",
         "-of", "csv=p=0"],
        stdout=subprocess.PIPE
    )
    return float(result.stdout)


# =========================
# 🔥 CORE PROCESS
# =========================

def process_segments(segments, voice):
    combined = AudioSegment.silent(duration=0)
    current_time = 0

    for i, (start, end, text) in enumerate(segments):
        print(f"Processing segment {i}")

        target_duration = (end - start).total_seconds()

        raw_path = f"{OUTPUT_FOLDER}/raw_{i}.wav"
        final_path = f"{OUTPUT_FOLDER}/final_{i}.wav"

        # 🔁 Retry logic
        for _ in range(3):
            if tts_azure_to_file(text, voice, "1.0", raw_path):
                break
            time.sleep(2)

        if not os.path.exists(raw_path):
            print("TTS failed → silence")
            audio = AudioSegment.silent(duration=target_duration * 1000)
        else:
            real_duration = get_duration(raw_path)
            speed = real_duration / target_duration

            for _ in range(3):
                if tts_azure_to_file(text, voice, str(speed), final_path):
                    break
                time.sleep(2)

            if os.path.exists(final_path):
                audio = AudioSegment.from_wav(final_path)
            else:
                audio = AudioSegment.silent(duration=target_duration * 1000)

        # ⏱ sync timeline
        silence_before = start.total_seconds() * 1000 - len(combined)
        if silence_before > 0:
            combined += AudioSegment.silent(duration=silence_before)

        combined += audio

    return combined


# =========================
# 🚀 ROUTES
# =========================

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/upload", methods=["POST"])
def upload():
    try:
        file = request.files["file"]
        voice = request.form.get("voice", "vi-VN-HoaiMyNeural")

        input_path = os.path.join(UPLOAD_FOLDER, file.filename)
        file.save(input_path)

        segments = parse_srt(input_path)

        if not segments:
            return {"error": "Empty SRT"}

        combined_audio = process_segments(segments, voice)

        output_wav = os.path.join(OUTPUT_FOLDER, "output.wav")
        output_mp3 = os.path.join(OUTPUT_FOLDER, "output.mp3")

        combined_audio.export(output_wav, format="wav")

        subprocess.run([
            "ffmpeg", "-y",
            "-i", output_wav,
            "-codec:a", "libmp3lame",
            "-b:a", "192k",
            output_mp3
        ])

        if not os.path.exists(output_mp3):
            return {"error": "MP3 failed"}

        return send_file(output_mp3, as_attachment=True)

    except Exception as e:
        return {"error": str(e)}


# =========================
# ▶️ RUN
# =========================

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
