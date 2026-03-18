from flask import Flask, request, send_file
import os
import subprocess
import srt
import azure.cognitiveservices.speech as speechsdk

# 🔥 QUAN TRỌNG: phải có dòng này trước @app.route
app = Flask(__name__)

UPLOAD_FOLDER = "uploads"
OUTPUT_FOLDER = "outputs"

os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(OUTPUT_FOLDER, exist_ok=True)

# 🔑 Azure config
SPEECH_KEY = "FRWM9EPWSqtWOHmr37bRN81quMyXT1NnjqIVRrQku3g0C60vfKeIJQQJ99CCACYeBjFXJ3w3AAAYACOG70Xz"
SERVICE_REGION = "eastus"


# =========================
# 🧠 FUNCTIONS
# =========================

def parse_srt(file_path):
    with open(file_path, "r", encoding="utf-8") as f:
        return list(srt.parse(f.read()))


def tts_azure(text, voice):
    speech_config = speechsdk.SpeechConfig(
        subscription=SPEECH_KEY,
        region=SERVICE_REGION
    )
    speech_config.speech_synthesis_voice_name = voice

    synthesizer = speechsdk.SpeechSynthesizer(
        speech_config=speech_config,
        audio_config=None
    )

    result = synthesizer.speak_text_async(text).get()

    if result.reason == speechsdk.ResultReason.SynthesizingAudioCompleted:
        return result.audio_data
    return None


def get_audio_duration(file_path):
    result = subprocess.run(
        [
            "ffprobe", "-i", file_path,
            "-show_entries", "format=duration",
            "-v", "quiet",
            "-of", "csv=p=0"
        ],
        stdout=subprocess.PIPE
    )
    return float(result.stdout)


# =========================
# 🚀 ROUTE
# =========================
from flask import render_template

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/upload", methods=["POST"])
def upload():
    file = request.files["file"]
    voice = request.form["voice"]

    input_path = os.path.join(UPLOAD_FOLDER, file.filename)
    file.save(input_path)

    subs = parse_srt(input_path)

    timeline_audio = f"{OUTPUT_FOLDER}/timeline.wav"

    # tạo audio rỗng ban đầu
    subprocess.run([
        "ffmpeg", "-y",
        "-f", "lavfi",
        "-i", "anullsrc=r=22050:cl=mono",
        "-t", "0",
        timeline_audio
    ])

    current_time = 0

    for i, sub in enumerate(subs):
        start = sub.start.total_seconds()
        end = sub.end.total_seconds()
        duration = end - start

        audio_data = tts_azure(sub.content, voice)
        if not audio_data:
            continue

        temp_wav = f"{OUTPUT_FOLDER}/seg_{i}.wav"
        with open(temp_wav, "wb") as f:
            f.write(audio_data)

        real_duration = get_audio_duration(temp_wav)
        adjusted_wav = f"{OUTPUT_FOLDER}/adj_{i}.wav"

        # 🔥 FIX: atempo > 2 sẽ lỗi → chia nhỏ
        if real_duration > duration:
            speed = real_duration / duration

            filters = []
            while speed > 2.0:
                filters.append("atempo=2.0")
                speed /= 2.0
            filters.append(f"atempo={speed}")

            subprocess.run([
                "ffmpeg", "-y",
                "-i", temp_wav,
                "-filter:a", ",".join(filters),
                adjusted_wav
            ])
        else:
            silence_time = duration - real_duration

            subprocess.run([
                "ffmpeg", "-y",
                "-i", temp_wav,
                "-f", "lavfi",
                "-t", str(silence_time),
                "-i", "anullsrc",
                "-filter_complex", "[0:a][1:a]concat=n=2:v=0:a=1",
                adjusted_wav
            ])

        delay = max(0, start - current_time)

        final_seg = f"{OUTPUT_FOLDER}/final_{i}.wav"

        subprocess.run([
            "ffmpeg", "-y",
            "-i", adjusted_wav,
            "-af", f"adelay={int(delay*1000)}|{int(delay*1000)}",
            final_seg
        ])

        merged = f"{OUTPUT_FOLDER}/merged_{i}.wav"

        subprocess.run([
            "ffmpeg", "-y",
            "-i", timeline_audio,
            "-i", final_seg,
            "-filter_complex", "[0:a][1:a]amix=inputs=2:duration=longest",
            merged
        ])

        os.replace(merged, timeline_audio)
        current_time = start + duration

    output_mp3 = f"{OUTPUT_FOLDER}/output.mp3"

    subprocess.run([
        "ffmpeg", "-y",
        "-i", timeline_audio,
        "-acodec", "libmp3lame",
        output_mp3
    ])

    return send_file(output_mp3, as_attachment=True)


# =========================
# ▶️ RUN
# =========================

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
