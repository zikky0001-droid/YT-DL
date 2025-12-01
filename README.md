# YT-DL (Render + Flask + yt-dlp)

Backend service for Telegram /ytdl command. Receives a YouTube URL via POST, downloads with yt-dlp, and streams the file back.

## Endpoints
- POST /ytdl
  - Headers: `X-BOT-TOKEN: <secret>`
  - JSON: `{ "url": "https://youtube.com/...", "quality": "best|18|bestaudio" }`
- GET /health

## Environment variables
- `BOT_TOKEN`: Secret to authenticate requests from your Telegram bot.

## Deployment on Render
1. Push this repo to GitHub.
2. Create a Web Service from this repo in Render.
3. Build command: `pip install -r requirements.txt`
4. Start command: `gunicorn main:app`
5. Add environment variable `BOT_TOKEN`.

## Notes
- Use `quality: "18"` for MP4 360p to help stay under Telegram's 2 GB limit.
- For audio-only, use `quality: "bestaudio"`.
- Consider returning a cloud link for very large files instead of streaming.
