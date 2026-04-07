"""
config.py - 봇 설정 파일
환경변수에서 API 키를 읽어오고, 모니터링할 코인 목록 등을 관리합니다.
"""

import os
from dotenv import load_dotenv

# .env 파일에서 환경변수 로드
load_dotenv()

# === API 키 설정 ===
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
COINGECKO_API_KEY = os.getenv("COINGECKO_API_KEY", "")
CRYPTOPANIC_API_KEY = os.getenv("CRYPTOPANIC_API_KEY", "")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_CASUAL_MODEL = os.getenv("OPENAI_CASUAL_MODEL", "gpt-4o-mini")

# === Codex CLI 설정 (ChatGPT 로그인 모드 — API 키 불필요) ===
CODEX_TIMEOUT = int(os.getenv("CODEX_TIMEOUT", "120"))

# === Glassnode 설정 ===
GLASSNODE_API_KEY = os.getenv("GLASSNODE_API_KEY", "")

# === 모니터링할 코인 목록 ===
# CoinGecko에서 사용하는 코인 ID와 표시 이름
COINS = {
    "bitcoin": {"symbol": "BTC", "emoji": "🪙"},
    "ethereum": {"symbol": "ETH", "emoji": "💎"},
    "solana": {"symbol": "SOL", "emoji": "☀️"},
    "ripple": {"symbol": "XRP", "emoji": "💧"},
    "dogecoin": {"symbol": "DOGE", "emoji": "🐕"},
}

# === 자동 알림 시간 (24시간 형식) ===
DAILY_BRIEFING_HOUR = 8   # 오전 8시
DAILY_BRIEFING_MINUTE = 0  # 0분

# === API URL ===
COINGECKO_BASE_URL = "https://api.coingecko.com/api/v3"
CRYPTOPANIC_BASE_URL = "https://cryptopanic.com/api/developer/v2"
GLASSNODE_BASE_URL = "https://api.glassnode.com/v1/metrics"

# === RSS 피드 (경제 지표용) ===
ECONOMY_RSS_FEEDS = [
    {
        "name": "Investing.com 경제 뉴스",
        "url": "https://www.investing.com/rss/news_301.rss",
    },
    {
        "name": "CoinDesk",
        "url": "https://www.coindesk.com/arc/outboundfeeds/rss/",
    },
]
