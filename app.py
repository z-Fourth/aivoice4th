from flask import Flask, request, send_file, render_template
import os
import subprocess
import srt
import azure.cognitiveservices.speech as speechsdk

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
    speech_config = speechsdk.SpeechConfig(subscription=SPEECH_KEY, region=SERVICE_REGION)
    speech_config.speech_synthesis_voice_name = voice
    synthesizer = speechsdk.SpeechSynthesizer(speech_config=speech_config, audio_config=None)
    result = synthesizer.speak_text_async(text).get()
    if result.reason == speechsdk.ResultReason.SynthesizingAudioCompleted:
        return result.audio_data
    return None

def get_audio_duration(file_path):
    result = subprocess.run(
        ["ffprobe", "-i", file_path, "-show_entries", "format=duration", "-v", "quiet", "-of", "csv=p=0"],
        stdout=subprocess.PIPE
    )
    return float(result.stdout)

# =========================
# 🚀 ROUTES
# =========================

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
    final_files = []
    current_time = 0  # timeline

    for i, sub in enumerate(subs):
        start = sub.start.total_seconds()
        end = sub.end.total_seconds()
        duration = end - start

        # 🔹 TTS Azure
        audio_data = tts_azure(sub.content, voice)
        if not audio_data:
            continue

        temp_wav = f"{OUTPUT_FOLDER}/seg_{i}.wav"
        with open(temp_wav, "wb") as f:
            f.write(audio_data)

        # 🔹 Điều chỉnh duration
        real_duration = get_audio_duration(temp_wav)
        adjusted_wav = f"{OUTPUT_FOLDER}/adj_{i}.wav"

        if real_duration > duration:
            speed = real_duration / duration
            filters = []
            while speed > 2.0:
                filters.append("atempo=2.0")
                speed /= 2.0
            filters.append(f"atempo={speed}")
            subprocess.run(["ffmpeg", "-y", "-i", temp_wav, "-filter:a", ",".join(filters), adjusted_wav])
        else:
            silence_time = duration - real_duration
            subprocess.run([
                "ffmpeg", "-y",
                "-i", temp_wav,
                "-f", "lavfi", "-t", str(silence_time), "-i", "anullsrc=r=22050:cl=mono",
                "-filter_complex", "[0:a][1:a]concat=n=2:v=0:a=1",
                adjusted_wav
            ])

        # 🔹 Thêm silence trước câu nếu cần để timeline đúng
        silence_before = start - current_time
        if silence_before > 0:
            with_silence = f"{OUTPUT_FOLDER}/final_{i}.wav"
            subprocess.run([
                "ffmpeg", "-y",
                "-f", "lavfi", "-t", str(silence_before), "-i", "anullsrc=r=22050:cl=mono",
                "-i", adjusted_wav,
                "-filter_complex", "[0:a][1:a]concat=n=2:v=0:a=1",
                with_silence
            ])
        else:
            with_silence = adjusted_wav

        final_files.append(with_silence)
        current_time = end  # cập nhật timeline

    # 🔹 Tạo file list để concat
    list_path = os.path.join(OUTPUT_FOLDER, "concat_list.txt")
    with open(list_path, "w", encoding="utf-8") as f:
        for file_path in final_files:
            f.write(f"file '{file_path}'\n")

    # 🔹 Concat tất cả các file theo thứ tự
    output_wav = os.path.join(OUTPUT_FOLDER, "output.wav")
    subprocess.run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", list_path, "-c", "copy", output_wav])

    # 🔹 Convert sang MP3
    output_mp3 = os.path.join(OUTPUT_FOLDER, "output.mp3")
    subprocess.run(["ffmpeg", "-y", "-i", output_wav, "-acodec", "libmp3lame", output_mp3])

    return send_file(output_mp3, as_attachment=True)

# =========================
# ▶️ RUN
# =========================
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
