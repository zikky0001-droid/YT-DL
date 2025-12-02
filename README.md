🎬 Telegram YouTube Downloader Bot

A sleek Telegram bot built with Python, powered by python-telegram-bot and yt-dlp, deployed on Render (Free Web Service).  
It lets you download YouTube videos directly inside Telegram with live progress updates, elapsed time, and automatic file delivery.

---

✨ Features
- /start → Welcome message & usage guide  
- /help → Full command list + inline button to return to start  
- /profile → Shows your Telegram profile info  
- /ytdl <YouTube link> → Downloads YouTube video (360p MP4) with:
  - ✅ Link validation  
  - ✅ Real‑time progress updates (phase, speed, ETA, elapsed)  
  - ✅ Automatic upload back to Telegram  
  - ✅ Fallback to document if video upload fails  

---

🚀 Deployment on Render
1. Fork/clone this repo to your GitHub.  
2. On Render, create a Web Service (Free plan).  
3. Connect your repo and set:
   - Build Command:  
     `bash
     pip install -r requirements.txt
     `
   - Start Command:  
     `bash
     python main.py
     `
4. Add environment variable:
   - TELEGRAMBOTTOKEN → your bot token from BotFather.  
5. Deploy! Render will run Flask for health checks and the bot in the background.

---

🛠 Tech Stack
- Python 3.10+
- python-telegram-bot → Telegram API wrapper  
- yt-dlp → YouTube downloader backend  
- Flask → Lightweight web server for Render health checks  

---

📂 Project Structure
`
├── main.py          # Bot + Flask server
├── requirements.txt # Dependencies
├── Procfile         # Render start command
├── render.yaml      # Render service config
└── README.md        # Documentation
`

---

📝 Notes
- Video downloads are capped at 360p MP4 for speed and Telegram compatibility.  
- Large files may fail on free tier; bot automatically falls back to sending as a document.  
- Logs are streamed to Render dashboard for monitoring.  

---

❤️ Credits
Built with love by DEV•ZIKKY, deployed with Render, and powered by open‑source libraries.
`

---
