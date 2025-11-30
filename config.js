import dotenv from "dotenv";
dotenv.config();

export default {
  TELEGRAM_TOKEN: process.env.TELEGRAM_TOKEN,
  API_MARKET_KEY: process.env.API_MARKET_KEY,
  PORT: process.env.PORT || 3000,
  TEMP_DIR: process.env.TEMP_DIR || "/tmp"
};