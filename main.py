import os, tempfile, subprocess, base64, sys, json, time
from flask import Flask, request, jsonify

app = Flask(__name__)
BOT_TOKEN = os.environ.get("BOT_TOKEN")

@app.route("/ytdl", methods=["POST"])
def ytdl():
    token = request.headers.get("X-BOT-TOKEN")
    if BOT_TOKEN and token != BOT_TOKEN:
        return jsonify({"error": "Unauthorized"}), 401

    data = request.get_json(silent=True) or {}
    url = data.get("url")
    quality = data.get("quality", "18")

    if not url:
        return jsonify({"error": "No URL provided"}), 400

    print(f"[YT-DL] Checking metadata for {url}", file=sys.stderr)

    # Step 1: Get metadata
    try:
        result = subprocess.run(
            ["yt-dlp", "--print-json", "-f", quality, url],
            capture_output=True, text=True, check=True
        )
        info = json.loads(result.stdout.splitlines()[0])
        duration = info.get("duration", 0)  # seconds
        filesize = info.get("filesize", 0) or info.get("filesize_approx", 0)

        print(f"[YT-DL] Duration: {duration}s, Size: {filesize} bytes", file=sys.stderr)

        # Step 2: Apply limits
        if duration > 300 or (filesize and filesize > 50 * 1024 * 1024):
            return jsonify({"error": "File too long for the bot to execute"}), 400

    except Exception as e:
        print(f"[YT-DL] Metadata check failed: {e}", file=sys.stderr)
        time.sleep(20)  # spin down before error
        return jsonify({"error": "Unable to process URL"}), 500

    # Step 3: Download
    tmpdir = tempfile.mkdtemp()
    output_template = os.path.join(tmpdir, "%(title)s.%(ext)s")
    cmd = ["yt-dlp", "-o", output_template, "-f", quality, url]

    print(f"[YT-DL] Starting download...", file=sys.stderr)
    try:
        subprocess.check_call(cmd)
    except subprocess.CalledProcessError as e:
        print(f"[YT-DL] Download failed: {e}", file=sys.stderr)
        time.sleep(20)  # spin down before error
        return jsonify({"error": "Download failed"}), 500

    files = [os.path.join(tmpdir, f) for f in os.listdir(tmpdir)]
    if not files:
        print("[YT-DL] No output file found", file=sys.stderr)
        return jsonify({"error": "No output file found"}), 500

    output_path = files[0]
    print(f"[YT-DL] Download complete: {output_path}", file=sys.stderr)

    with open(output_path, "rb") as f:
        encoded = base64.b64encode(f.read()).decode("utf-8")

    return jsonify({
        "status": "ok",
        "fileName": os.path.basename(output_path),
        "mime": "video/mp4",
        "base64": encoded
    })

@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"})
