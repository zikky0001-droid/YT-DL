import express from "express";
import fetch from "node-fetch";
import FormData from "form-data";
import fs from "fs";
import fsExtra from "fs-extra";
import path from "path";
import crypto from "crypto";
import { pipeline } from "stream/promises";
import dotenv from "dotenv";
import config from "./config.js";

dotenv.config(); // ensure .env is loaded if config.js didn't already

// --- Safety: show only presence of secrets, not values
console.log("✅ Loaded config:", {
  TELEGRAM_TOKEN: !!config.TELEGRAM_TOKEN,
  API_MARKET_KEY: !!config.API_MARKET_KEY,
  PORT: config.PORT,
  TEMP_DIR: config.TEMP_DIR
});

const app = express();
app.use(express.json());

// Global error handlers so crashes are visible in console
process.on("uncaughtException", (err) => {
  console.error("❌ Uncaught Exception:", err && err.stack ? err.stack : err);
});
process.on("unhandledRejection", (reason) => {
  console.error("❌ Unhandled Rejection:", reason);
});

// Simple request logger (first middleware)
app.use((req, res, next) => {
  console.log(`📥 Incoming ${req.method} request to ${req.url} from ${req.ip || req.connection.remoteAddress}`);
  next();
});

// Health check
app.get("/", (req, res) => res.send("✅ YTDL (market-api) server online"));

// Helper: create temp filename
function tempFileName(ext = ".mp4") {
  const id = crypto.randomBytes(8).toString("hex");
  return path.join(config.TEMP_DIR || "/tmp", `ytdl-${id}${ext}`);
}

// Main route: POST /api/ytdl
app.post("/api/ytdl", async (req, res) => {
  const { chat_id, url } = req.body;
  const TELEGRAM_TOKEN = config.TELEGRAM_TOKEN;
  const API_MARKET_KEY = config.API_MARKET_KEY;

  console.log("🔗 Received YTDL request:", { chat_id: typeof chat_id === "number" ? chat_id : String(chat_id), url });

  if (!chat_id || !url) {
    console.error("❌ Missing chat_id or url in request body");
    return res.status(400).json({ error: "Missing chat_id or url" });
  }
  if (!TELEGRAM_TOKEN || !API_MARKET_KEY) {
    console.error("❌ Missing TELEGRAM_TOKEN or API_MARKET_KEY in environment");
    return res.status(500).json({ error: "Missing TELEGRAM_TOKEN or API_MARKET_KEY in environment" });
  }

  try {
    // 1) Call the market API to get media info
    const infoUrl = `https://prod.api.market/api/v1/beatom/media-downloader/v1/youtube-media/info?url=${encodeURIComponent(url)}`;
    console.log("➡️ Calling market API:", infoUrl);

    const infoRes = await fetch(infoUrl, {
      method: "GET",
      headers: {
        accept: "application/json",
        "x-api-market-key": API_MARKET_KEY
      }
    });

    if (!infoRes.ok) {
      const text = await infoRes.text().catch(() => "");
      console.error("❌ Market API returned non-200:", infoRes.status, text.slice(0, 1000));
      throw new Error(`Market API error: ${infoRes.status}`);
    }

    const infoJson = await infoRes.json();
    console.log("📥 Market API response (trimmed):", JSON.stringify(infoJson).slice(0, 1000));

    // 2) Extract media URL from common fields
    const mediaUrl =
      infoJson?.data?.download_url ||
      infoJson?.data?.url ||
      infoJson?.download_url ||
      infoJson?.url ||
      infoJson?.data?.formats?.[0]?.url ||
      infoJson?.formats?.[0]?.url ||
      null;

    if (!mediaUrl) {
      console.error("❌ No media URL found in market API response");
      return res.status(500).json({ error: "No media URL found in market API response", raw: infoJson });
    }

    console.log("🔎 Found media URL:", mediaUrl);

    // 3) Try to send the media to Telegram by URL first
    const isMp4 = mediaUrl.toLowerCase().includes(".mp4") || mediaUrl.toLowerCase().includes("video");
    const telegramMethod = isMp4 ? "sendVideo" : "sendDocument";
    const telegramEndpoint = `https://api.telegram.org/bot${TELEGRAM_TOKEN}/${telegramMethod}`;

    const payload = {
      chat_id: String(chat_id),
      caption: "✅ Downloaded from YouTube",
      ...(isMp4 ? { video: mediaUrl } : { document: mediaUrl })
    };

    console.log(`📤 Attempting Telegram ${telegramMethod} with remote URL...`);
    const tgRes = await fetch(telegramEndpoint, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    });

    let tgJson;
    try {
      tgJson = await tgRes.json();
    } catch (e) {
      const txt = await tgRes.text().catch(() => "");
      console.warn("⚠️ Telegram returned non-JSON response:", txt.slice(0, 1000));
      tgJson = null;
    }

    console.log("📥 Telegram response (trimmed):", tgJson ? JSON.stringify(tgJson).slice(0, 1000) : "no-json");

    // If Telegram accepted the URL, return success
    if (tgJson && tgJson.ok) {
      console.log("✅ Telegram accepted remote URL and sent media");
      return res.json({ ok: true, result: tgJson.result });
    }

    // 4) Fallback: download the media locally then upload to Telegram
    console.warn("⚠️ Telegram could not fetch remote URL directly; falling back to download+upload", tgJson);

    const tmpPath = tempFileName(isMp4 ? ".mp4" : ".bin");
    await fsExtra.ensureDir(path.dirname(tmpPath));
    console.log("⬇️ Downloading media to", tmpPath);

    const mediaRes = await fetch(mediaUrl);
    if (!mediaRes.ok) {
      const txt = await mediaRes.text().catch(() => "");
      console.error("❌ Failed to download media:", mediaRes.status, txt.slice(0, 1000));
      throw new Error(`Failed to download media: ${mediaRes.status}`);
    }

    const fileStream = fs.createWriteStream(tmpPath);
    await pipeline(mediaRes.body, fileStream);
    console.log("✅ Download finished:", tmpPath);

    // Upload file using multipart/form-data
    const uploadForm = new FormData();
    uploadForm.append("chat_id", String(chat_id));
    uploadForm.append("caption", "✅ Downloaded from YouTube");
    uploadForm.append(isMp4 ? "video" : "document", fs.createReadStream(tmpPath), { filename: path.basename(tmpPath) });

    console.log("📤 Uploading file to Telegram via", telegramMethod);
    const uploadRes = await fetch(telegramEndpoint, { method: "POST", body: uploadForm, headers: uploadForm.getHeaders() });
    const uploadJson = await uploadRes.json().catch(() => null);
    console.log("📥 Telegram upload response (trimmed):", uploadJson ? JSON.stringify(uploadJson).slice(0, 1000) : "no-json");

    // Clean up temp file
    try {
      await fsExtra.remove(tmpPath);
      console.log("🧹 Temp file removed:", tmpPath);
    } catch (e) {
      console.warn("⚠️ Failed to remove temp file:", tmpPath, e && e.message ? e.message : e);
    }

    if (!uploadJson || !uploadJson.ok) {
      console.error("❌ Telegram upload failed:", uploadJson);
      return res.status(500).json({ error: "Telegram upload failed", details: uploadJson });
    }

    console.log("📤 Sent media to Telegram successfully (uploaded file)");
    return res.json({ ok: true, result: uploadJson.result });
  } catch (err) {
    console.error("❌ YTDL (market-api) error:", err && err.stack ? err.stack : err);
    return res.status(500).json({ error: err && err.message ? err.message : String(err) });
  }
});

// Bind to 0.0.0.0 so container accepts external connections
const HOST = "0.0.0.0";
const PORT = config.PORT || 3000;

try {
  app.listen(PORT, HOST, () => {
    console.log(`🚀 YTDL (market-api) server running on ${HOST}:${PORT}`);
  });
} catch (e) {
  console.error("❌ Failed to start server:", e && e.stack ? e.stack : e);
  process.exit(1);
}