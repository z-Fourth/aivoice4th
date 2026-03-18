import srt
import io
import os
from concurrent.futures import ThreadPoolExecutor

from flask import Flask, request, send_file, render_template
from pydub import AudioSegment
import azure.cognitiveservices.speech as speechsdk

app = Flask(__name__)

speech_key = os.environ.get("SPEECH_KEY")
service_region = os.environ.get("SPEECH_REGION")


# ===== PARSE SRT =====
def parse_srt(content):
    subtitles = list(srt.parse(content))
    return [(sub.start.total_seconds(), sub.end.total_seconds(), sub.content) for sub in subtitles]


# ===== ESTIMATE SPEED =====
def estimate_rate(text, target_duration):
    words = len(text.split())
    expected = words * 0.4
    if target_duration == 0:
        return "1.0"
    rate = expected / target_duration
    return f"{rate:.2f}"


# ===== AZURE TTS =====
def tts(text, voice, rate):
    speech_config = speechsdk.SpeechConfig(subscription=speech_key, region=service_region)
    speech_config.speech_synthesis_voice_name = voice

    ssml = f"""
    <speak version='1.0'>
      <voice name='{voice}'>
        <prosody rate='{rate}'>
          {text}
        </prosody>
      </voice>
    </speak>
    """

    synthesizer = speechsdk.SpeechSynthesizer(speech_config=speech_config, audio_config=None)
    result = synthesizer.speak_ssml_async(ssml).get()

    if result.reason == speechsdk.ResultReason.SynthesizingAudioCompleted:
        return result.audio_data
    return None


# ===== XỬ LÝ 1 SEGMENT =====
def process_segment(args):
    i, start, end, text, voice = args

    duration = end - start
    rate = estimate_rate(text, duration)

    audio_data = tts(text, voice, rate)

    if audio_data is None:
        return (start, AudioSegment.silent(duration=duration * 1000))

    audio = AudioSegment.from_file(io.BytesIO(audio_data), format="wav")
    return (start, audio)


# ===== ROUTE UI =====
@app.route("/")
def home():
    return render_template("index.html")


# ===== API =====
@app.route("/upload", methods=["POST"])
def upload():
    file = request.files["file"]
    voice = request.form.get("voice", "vi-VN-HoaiMyNeural")

    content = file.read().decode("utf-8")
    segments = parse_srt(content)

    tasks = [(i, start, end, text, voice) for i, (start, end, text) in enumerate(segments)]

    # ⚡ chạy song song
    with ThreadPoolExecutor(max_workers=3) as executor:
        results = list(executor.map(process_segment, tasks))

    results.sort(key=lambda x: x[0])

    combined = AudioSegment.silent(duration=0)

    for start, audio in results:
        silence = AudioSegment.silent(duration=(start * 1000) - len(combined))
        combined += silence + audio

    output = io.BytesIO()
    combined.export(output, format="mp3")
    output.seek(0)

    return send_file(output, as_attachment=True, download_name="output.mp3", mimetype="audio/mpeg")


# ===== RUN =====
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=3000)
