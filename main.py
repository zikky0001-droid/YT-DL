# main.py
import os, tempfile, asyncio
from fastapi import FastAPI, Request, BackgroundTasks, HTTPException
import httpx

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
API_MARKET_KEY = os.getenv("API_MARKET_KEY")
TEMP_DIR = os.getenv("TEMP_DIR", "/tmp")

app = FastAPI()

def cleanup(path): 
    try: os.remove(path)
    except: pass

@app.get("/")
async def health(): return {"status": "ok"}

@app.post("/api/ytdl")
async def ytdl(request: Request, background: BackgroundTasks):
    body = await request.json()
    chat_id, url = body.get("chat_id"), body.get("url")
    if not chat_id or not url: raise HTTPException(400, "Missing chat_id or url")

    info_url = f"https://prod.api.market/api/v1/beatom/media-downloader/v1/youtube-media/info?url={httpx.utils.quote(url)}"
    async with httpx.AsyncClient(timeout=30.0) as client:
        res = await client.get(info_url, headers={"x-api-market-key": API_MARKET_KEY})
        if res.status_code != 200: raise HTTPException(502, "Market API error")
        info = res.json()

    media_url = info.get("data", {}).get("download_url") or info.get("data", {}).get("url")
    if not media_url: raise HTTPException(500, "No media URL found")

    method = "sendVideo" if ".mp4" in media_url else "sendDocument"
    tg_url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/{method}"
    payload = {"chat_id": str(chat_id), "caption": "✅ Downloaded from YouTube", method[:-4].lower(): media_url}

    async with httpx.AsyncClient(timeout=60.0) as client:
        tg_res = await client.post(tg_url, json=payload)
        tg_json = tg_res.json()

    if tg_json.get("ok"): return {"ok": True, "result": tg_json["result"]}

    # fallback: download then upload
    fd, path = tempfile.mkstemp(suffix=".mp4", dir=TEMP_DIR); os.close(fd)
    try:
        async with httpx.AsyncClient(timeout=300.0) as client:
            r = await client.stream("GET", media_url)
            if r.status_code != 200: raise HTTPException(502, "Download failed")
            with open(path, "wb") as f:
                async for chunk in r.aiter_bytes(): f.write(chunk)

        with open(path, "rb") as f:
            files = {method[:-4].lower(): (os.path.basename(path), f)}
            data = {"chat_id": str(chat_id), "caption": "✅ Downloaded from YouTube"}
            upload = httpx.post(tg_url, data=data, files=files, timeout=300.0).json()
    finally:
        background.add_task(cleanup, path)

    if not upload.get("ok"): raise HTTPException(500, "Telegram upload failed")
    return {"ok": True, "result": upload["result"]}
