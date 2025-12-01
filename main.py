import os
import tempfile
import subprocess
from flask import Flask, request, jsonify, send_file

app = Flask(__name__)

BOT_TOKEN = os.environ.get("BOT_TOKEN")

@app.route("/ytdl", methods=["POST"])
def ytdl():
    token = request.headers.get("X-BOT-TOKEN")
    if BOT_TOKEN and token != BOT_TOKEN:
        return jsonify({"error": "Unauthorized"}), 401

    data = request.get_json(silent=True) or {}
    url = data.get("url")
    quality = data.get("quality", "18")   # default 360p MP4

    if not url:
        return jsonify({"error": "No URL provided"}), 400

    tmpdir = tempfile.mkdtemp()
    output_template = os.path.join(tmpdir, "%(title)s.%(ext)s")

    cmd = ["yt-dlp", "-o", output_template]
    if quality:
        cmd.extend(["-f", quality])

    try:
        subprocess.check_call(cmd + [url])
    except subprocess.CalledProcessError as e:
        return jsonify({"error": "Download failed", "details": str(e)}), 500

    files = [os.path.join(tmpdir, f) for f in os.listdir(tmpdir)]
    if not files:
        return jsonify({"error": "No output file found"}), 500

    output_path = files[0]
    return send_file(output_path, as_attachment=True)

@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"})
