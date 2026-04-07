import json
import urllib.request
from datetime import datetime, timezone, timedelta

BITMEX_TRADE_API_URL = "https://www.bitmex.com/api/v1/trade"

def check_today_whales():
    # Today starts at 00:00:00 UTC
    today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    start_time_str = today_start.isoformat().replace("+00:00", "Z")
    
    # We can fetch up to 1000 trades at a time. 
    # For a whole day, we might need multiple pages, but let's start with 500 to see.
    params = f"symbol=XBTUSD&count=500&reverse=true&startTime={start_time_str}"
    url = f"{BITMEX_TRADE_API_URL}?{params}"
    
    print(f"--- BitMEX XBTUSD 1M+ Trades since {start_time_str} ---")
    
    try:
        with urllib.request.urlopen(url) as response:
            trades = json.loads(response.read().decode("utf-8"))
            
        found = False
        count_1m = 0
        total_fetched = len(trades)
        
        # Trades are reversed (newest first)
        for t in trades:
            size = t.get("size", 0)
            if size >= 1000000:
                dt = datetime.fromisoformat(t["timestamp"].replace("Z", "+00:00"))
                # Adjust to KST for the user (+9h)
                kst_dt = dt.astimezone(timezone(timedelta(hours=9)))
                print(f"[{kst_dt.strftime('%Y-%m-%d %H:%M:%S KST')}] {t['side']} {size:,} @ ${t['price']:,.2f}")
                found = True
                count_1m += 1
        
        if not found:
            print(f"오늘 하루(UTC 기준) 1M+ 체결 내역이 하나도 없느니라. (총 {total_fetched}건 확인)")
        else:
            print(f"\n총 {count_1m}건의 대형 체결을 확인했느니라.")
            
    except Exception as e:
        print(f"에러 났구나: {e}")

if __name__ == "__main__":
    check_today_whales()
