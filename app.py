import io

def get_audio_duration(file_path):
    result = subprocess.run(
        ["ffprobe", "-i", file_path, "-show_entries",
         "format=duration", "-v", "quiet", "-of", "csv=p=0"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT
    )
    return float(result.stdout)

@app.route("/upload", methods=["POST"])
def upload():
    file = request.files["file"]
    voice = request.form["voice"]

    input_path = os.path.join(UPLOAD_FOLDER, file.filename)
    file.save(input_path)

    subs = parse_srt(input_path)

    timeline_audio = f"{OUTPUT_FOLDER}/timeline.wav"

    # 👉 bắt đầu bằng audio rỗng
    subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "anullsrc=r=22050:cl=mono", "-t", "0", timeline_audio])

    current_time = 0

    for i, sub in enumerate(subs):
        start = sub.start.total_seconds()
        end = sub.end.total_seconds()
        duration = end - start

        # 👉 tạo audio từ Azure
        audio_data = tts_azure(sub.content, voice)
        if not audio_data:
            continue

        temp_wav = f"{OUTPUT_FOLDER}/seg_{i}.wav"
        with open(temp_wav, "wb") as f:
            f.write(audio_data)

        real_duration = get_audio_duration(temp_wav)

        adjusted_wav = f"{OUTPUT_FOLDER}/adj_{i}.wav"

        # 🎯 nếu dài hơn → tăng tốc
        if real_duration > duration:
            speed = real_duration / duration
            subprocess.run([
                "ffmpeg", "-y",
                "-i", temp_wav,
                "-filter:a", f"atempo={speed}",
                adjusted_wav
            ])
        else:
            # 🎯 nếu ngắn → thêm silence
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

        # 👉 chèn vào đúng vị trí timeline
        delay = max(0, start - current_time)

        final_seg = f"{OUTPUT_FOLDER}/final_{i}.wav"

        subprocess.run([
            "ffmpeg", "-y",
            "-i", adjusted_wav,
            "-af", f"adelay={int(delay*1000)}|{int(delay*1000)}",
            final_seg
        ])

        # 👉 merge vào timeline
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
