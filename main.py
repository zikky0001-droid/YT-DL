# main.py
import os
import tempfile
from urllib.parse import quote
from fastapi import FastAPI, Request, BackgroundTasks, HTTPException
import httpx

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
API_MARKET_KEY = os.getenv("API_MARKET_KEY")
TEMP_DIR = os.getenv("TEMP_DIR", "/tmp")

os.makedirs(TEMP_DIR, exist_ok=True)

app = FastAPI()

def cleanup_file(path: str):
    try:
        if os.path.exists(path):
            os.remove(path)
    except Exception:
        pass

@app.get("/")
async def health():
    return {"status": "ok"}

@app.post("/api/ytdl")
async def ytdl_endpoint(request: Request, background_tasks: BackgroundTasks):
    body = await request.json()
    chat_id = body.get("chat_id")
    url = body.get("url")
    if not chat_id or not url:
        raise HTTPException(status_code=400, detail="Missing chat_id or url")
    if not TELEGRAM_TOKEN or not API_MARKET_KEY:
        raise HTTPException(status_code=500, detail="Missing env vars")

    # 1) Get media info from Market API
    info_url = f"https://prod.api.market/api/v1/beatom/media-downloader/v1/youtube-media/info?url={quote(url)}"
    async with httpx.AsyncClient(timeout=30.0) as client:
        info_res = await client.get(info_url, headers={"x-api-market-key": API_MARKET_KEY})
        if info_res.status_code != 200:
            raise HTTPException(status_code=502, detail="Market API error")
        info = info_res.json()

    media_url = (
        info.get("data", {}).get("download_url")
        or info.get("data", {}).get("url")
        or info.get("download_url")
        or info.get("url")
    )
    if not media_url:
        raise HTTPException(status_code=500, detail="No media URL found")

    # 2) Try sending remote URL to Telegram
    is_video = ".mp4" in media_url.lower()
    tg_method = "sendVideo" if is_video else "sendDocument"
    tg_endpoint = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/{tg_method}"
    payload = {
        "chat_id": str(chat_id),
        "caption": "✅ Downloaded from YouTube",
        "video" if is_video else "document": media_url
    }

    async with httpx.AsyncClient(timeout=60.0) as client:
        tg_res = await client.post(tg_endpoint, json=payload)
        try:
            tg_json = tg_res.json()
        except Exception:
            tg_json = None

    if tg_json and tg_json.get("ok"):
        return {"ok": True, "result": tg_json.get("result")}

    # 3) Fallback: download then upload
    tmp_fd, tmp_path = tempfile.mkstemp(suffix=".mp4", dir=TEMP_DIR)
    os.close(tmp_fd)
    try:
        async with httpx.AsyncClient(timeout=300.0) as client:
            r = await client.stream("GET", media_url)
            if r.status_code != 200:
                raise HTTPException(status_code=502, detail="Failed to download media")
            with open(tmp_path, "wb") as f:
                async for chunk in r.aiter_bytes():
                    if chunk:
                        f.write(chunk)

        async with httpx.AsyncClient(timeout=300.0) as client:
            with open(tmp_path, "rb") as f:
                files = {
                    "video" if is_video else "document": (os.path.basename(tmp_path), f)
                }
                data = {
                    "chat_id": str(chat_id),
                    "caption": "✅ Downloaded from YouTube"
                }
                upload_res = await client.post(tg_endpoint, data=data, files=files)
                upload_json = upload_res.json()
    finally:
        background_tasks.add_task(cleanup_file, tmp_path)

    if not upload_json.get("ok"):
        raise HTTPException(status_code=500, detail="Telegram upload failed")
    return {"ok": True, "result": upload_json.get("result")}
