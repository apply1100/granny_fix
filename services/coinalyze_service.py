import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone


API_BASE_URL = "https://api.coinalyze.net/v1"
DEFAULT_INTERVAL = "5min"
LOOKBACK_MINUTES = 60
WINDOW_BARS = 3
_SYMBOL_CACHE = None
SEOUL_TZ = timezone(timedelta(hours=9), "KST")
ANALYSIS_CACHE_TTL_SECONDS = 15
_ANALYSIS_CACHE = {"expires_at": 0.0, "analysis": None}
_DIRECT_HTTP_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


class CoinalyzeError(RuntimeError):
    """Raised when Coinalyze data cannot be fetched or interpreted."""


@dataclass
class BitmexWhaleAnalysis:
    as_of: str
    exchange_symbol: str
    price: float
    price_change_pct: float
    oi_change_pct: float
    buy_share_pct: float
    cvd_delta: float
    long_liquidations_usd: float
    short_liquidations_usd: float
    funding_rate_pct: float | None
    predicted_funding_rate_pct: float | None
    stance: str
    confidence: str
    summary: str
    reasons: list[str]


def get_bitmex_whale_report() -> str:
    analysis = build_bitmex_whale_analysis()
    return format_bitmex_whale_analysis(analysis)


def get_bitmex_whale_grandma_reply(user_question: str) -> str:
    analysis = build_bitmex_whale_analysis()
    return format_bitmex_whale_grandma_reply(user_question, analysis)


def build_bitmex_whale_analysis(force_refresh: bool = False) -> BitmexWhaleAnalysis:
    global _ANALYSIS_CACHE

    now_time = time.time()
    cached_analysis = _ANALYSIS_CACHE.get("analysis")
    if (
        not force_refresh
        and cached_analysis is not None
        and now_time < float(_ANALYSIS_CACHE.get("expires_at", 0.0))
    ):
        return cached_analysis

    api_key = os.getenv("COINALYZE_API_KEY", "").strip()
    if not api_key:
        raise CoinalyzeError(
            "COINALYZE_API_KEY가 비어 있어서 실시간 BitMEX 추정을 할 수 없습니다."
        )

    symbol_info = _resolve_bitmex_btc_perp_symbol(api_key)
    now = int(time.time())
    from_ts = now - LOOKBACK_MINUTES * 60

    price_history = _get_history(
        api_key,
        "/ohlcv-history",
        symbol_info["symbol"],
        DEFAULT_INTERVAL,
        from_ts,
        now,
    )
    oi_history = _get_history(
        api_key,
        "/open-interest-history",
        symbol_info["symbol"],
        DEFAULT_INTERVAL,
        from_ts,
        now,
        convert_to_usd=True,
    )
    liquidation_history = _get_history(
        api_key,
        "/liquidation-history",
        symbol_info["symbol"],
        DEFAULT_INTERVAL,
        from_ts,
        now,
        convert_to_usd=True,
        allow_empty=True,
    )
    funding_rate = _get_current_value(api_key, "/funding-rate", symbol_info["symbol"])
    predicted_funding_rate = _get_current_value(
        api_key,
        "/predicted-funding-rate",
        symbol_info["symbol"],
    )

    if len(price_history) < 2 or len(oi_history) < 2:
        raise CoinalyzeError("BitMEX 분석에 필요한 최근 시세/OI 데이터가 부족합니다.")

    last_price = price_history[-1]
    prev_price = price_history[-2]
    last_oi = oi_history[-1]
    prev_oi = oi_history[-2]

    price_change_pct = _pct_change(prev_price["c"], last_price["c"])
    oi_change_pct = _pct_change(prev_oi["c"], last_oi["c"])

    recent_price_bars = price_history[-WINDOW_BARS:]
    total_volume = sum(max(float(bar.get("v", 0)), 0.0) for bar in recent_price_bars)
    total_buy_volume = sum(max(float(bar.get("bv", 0)), 0.0) for bar in recent_price_bars)
    buy_share_pct = (total_buy_volume / total_volume * 100.0) if total_volume else 50.0
    cvd_delta = sum((2.0 * float(bar.get("bv", 0))) - float(bar.get("v", 0)) for bar in recent_price_bars)

    recent_liquidations = liquidation_history[-WINDOW_BARS:] if liquidation_history else []
    long_liquidations_usd = sum(float(bar.get("l", 0)) for bar in recent_liquidations)
    short_liquidations_usd = sum(float(bar.get("s", 0)) for bar in recent_liquidations)

    analysis = _infer_analysis(
        as_of_ts=last_price["t"],
        exchange_symbol=symbol_info["symbol_on_exchange"],
        price=float(last_price["c"]),
        price_change_pct=price_change_pct,
        oi_change_pct=oi_change_pct,
        buy_share_pct=buy_share_pct,
        cvd_delta=cvd_delta,
        long_liquidations_usd=long_liquidations_usd,
        short_liquidations_usd=short_liquidations_usd,
        funding_rate_pct=_normalize_rate(funding_rate),
        predicted_funding_rate_pct=_normalize_rate(predicted_funding_rate),
    )
    _ANALYSIS_CACHE = {
        "expires_at": time.time() + ANALYSIS_CACHE_TTL_SECONDS,
        "analysis": analysis,
    }
    return analysis


def format_bitmex_whale_analysis(analysis: BitmexWhaleAnalysis) -> str:
    funding_line = _format_percent_or_na(analysis.funding_rate_pct)
    predicted_funding_line = _format_percent_or_na(analysis.predicted_funding_rate_pct)
    reasons = "\n".join(f"- {reason}" for reason in analysis.reasons)

    return (
        "BitMEX 고래 포지션 추정\n"
        f"- 기준 시각: {analysis.as_of}\n"
        f"- 마켓: {analysis.exchange_symbol}\n"
        f"- 추정: {analysis.stance}\n"
        f"- 신뢰도: {analysis.confidence}\n"
        f"- 한줄 요약: {analysis.summary}\n"
        f"- 가격: ${analysis.price:,.2f} ({analysis.price_change_pct:+.2f}%)\n"
        f"- OI 변화(최근 5분): {analysis.oi_change_pct:+.2f}%\n"
        f"- 매수 비중(최근 15분): {analysis.buy_share_pct:.1f}%\n"
        f"- CVD 델타(최근 15분): {analysis.cvd_delta:,.0f}\n"
        f"- 롱 청산(최근 15분): ${analysis.long_liquidations_usd:,.0f}\n"
        f"- 숏 청산(최근 15분): ${analysis.short_liquidations_usd:,.0f}\n"
        f"- 현재 펀딩: {funding_line}\n"
        f"- 예측 펀딩: {predicted_funding_line}\n"
        "근거\n"
        f"{reasons}\n\n"
        "메모: OI만으로는 롱/숏 확정이 아니라, 가격·매수우위·청산을 같이 본 추정입니다."
    )


def format_bitmex_whale_grandma_reply(
    user_question: str,
    analysis: BitmexWhaleAnalysis,
) -> str:
    reasons = analysis.reasons[:2] or ["지금 구간은 단정하기보다 조금 더 지켜보는 편이 낫습니다."]
    reason_lines = "\n".join(f"- {reason}" for reason in reasons)

    return (
        f"{_grandma_opening(analysis)}\n\n"
        f"- 기준 시각: {analysis.as_of}\n"
        f"- 마켓: {analysis.exchange_symbol}\n"
        f"- 가격: ${analysis.price:,.2f}\n"
        f"- OI 변화(최근 5분): {analysis.oi_change_pct:+.2f}%\n"
        f"- 매수 비중(최근 15분): {analysis.buy_share_pct:.1f}%\n"
        f"- 현재 펀딩: {_format_percent_or_na(analysis.funding_rate_pct)}\n"
        f"- 신뢰도: {analysis.confidence}\n\n"
        f"할매 한마디:\n{_grandma_action_line(user_question, analysis)}\n\n"
        f"근거:\n{reason_lines}\n\n"
        "메모: 이건 BitMEX 단기 흐름 추정이니 확정 신호처럼만 보진 말거라."
    )


def _infer_analysis(
    *,
    as_of_ts: int,
    exchange_symbol: str,
    price: float,
    price_change_pct: float,
    oi_change_pct: float,
    buy_share_pct: float,
    cvd_delta: float,
    long_liquidations_usd: float,
    short_liquidations_usd: float,
    funding_rate_pct: float | None,
    predicted_funding_rate_pct: float | None,
) -> BitmexWhaleAnalysis:
    oi_up = oi_change_pct >= 0.2
    oi_down = oi_change_pct <= -0.2
    buy_pressure = buy_share_pct >= 55.0 and cvd_delta > 0
    sell_pressure = buy_share_pct <= 45.0 and cvd_delta < 0
    price_up = price_change_pct >= 0.15
    price_down = price_change_pct <= -0.15
    short_liq_dominant = short_liquidations_usd > long_liquidations_usd * 1.25 and short_liquidations_usd > 0
    long_liq_dominant = long_liquidations_usd > short_liquidations_usd * 1.25 and long_liquidations_usd > 0

    stance = "방향 불명확"
    confidence_score = 1
    reasons = []

    if oi_up and buy_pressure:
        stance = "신규 롱 진입 우세"
        confidence_score += 3
        reasons.append("OI가 증가했고 최근 15분 매수 우위라 새 롱 유입 쪽에 가깝습니다.")
        if price_up:
            confidence_score += 1
            reasons.append("가격도 같은 방향으로 밀려서 단순 숏 커버보다 신규 롱 진입 쪽이 더 자연스럽습니다.")
        elif short_liq_dominant:
            reasons.append("숏 청산도 같이 붙어 상방 가속이 나온 구간입니다.")
        else:
            reasons.append("다만 가격 반응이 약하면 아직 체결 흡수 단계일 수 있습니다.")
    elif oi_up and sell_pressure:
        stance = "신규 숏 진입 우세"
        confidence_score += 3
        reasons.append("OI가 증가했고 최근 15분 매도 우위라 새 숏 유입 쪽에 가깝습니다.")
        if price_down:
            confidence_score += 1
            reasons.append("가격도 하방으로 같이 밀려서 단순 롱 정리보다 신규 숏 진입 해석이 강합니다.")
        elif long_liq_dominant:
            reasons.append("롱 청산이 같이 붙어 하방 압력을 더 키우는 모습입니다.")
        else:
            reasons.append("다만 가격 반응이 약하면 위쪽 체결 대기나 흡수 가능성도 남아 있습니다.")
    elif oi_down and sell_pressure:
        stance = "롱 정리 또는 롱 청산 우세"
        confidence_score += 2
        reasons.append("OI가 줄면서 매도 우위라 신규 숏보다 기존 롱 정리/청산 가능성이 큽니다.")
        if long_liq_dominant:
            confidence_score += 1
            reasons.append("최근 롱 청산 규모가 더 커서 강제 정리 쪽 힌트가 붙습니다.")
        elif price_down:
            reasons.append("가격도 아래로 밀려 롱 포지션이 불리했던 구간으로 보입니다.")
    elif oi_down and buy_pressure:
        stance = "숏 커버링 우세"
        confidence_score += 2
        reasons.append("OI가 줄면서 매수 우위라 신규 롱보다 숏 커버링 가능성이 큽니다.")
        if short_liq_dominant:
            confidence_score += 1
            reasons.append("최근 숏 청산 규모가 더 커서 숏 정리 해석이 더 강해집니다.")
        elif price_up:
            reasons.append("가격도 위로 반응해 숏 커버 압력이 붙은 흐름과 잘 맞습니다.")
    else:
        if oi_up:
            reasons.append("OI는 증가했지만 매수/매도 우위가 한쪽으로 충분히 기울지 않아 방향 확정이 어렵습니다.")
        elif oi_down:
            reasons.append("OI는 감소했지만 체결 편향이 약해서 정리 쪽인지 반대 포지션 진입인지 모호합니다.")
        else:
            reasons.append("OI 변화가 작아서 지금 구간만으로 신규 포지션 방향을 단정하기 어렵습니다.")

    if funding_rate_pct is not None:
        if funding_rate_pct > 0:
            reasons.append("현재 펀딩이 플러스라 기존 시장은 롱 쏠림 쪽이 조금 더 강합니다.")
        elif funding_rate_pct < 0:
            reasons.append("현재 펀딩이 마이너스라 기존 시장은 숏 쏠림 쪽이 조금 더 강합니다.")

    confidence = "높음" if confidence_score >= 5 else "중간" if confidence_score >= 3 else "낮음"
    summary = _build_summary(
        stance=stance,
        confidence=confidence,
        price_change_pct=price_change_pct,
        oi_change_pct=oi_change_pct,
        buy_share_pct=buy_share_pct,
    )

    return BitmexWhaleAnalysis(
        as_of=datetime.fromtimestamp(as_of_ts, timezone.utc)
        .astimezone(SEOUL_TZ)
        .strftime("%Y-%m-%d %H:%M:%S KST"),
        exchange_symbol=exchange_symbol,
        price=price,
        price_change_pct=price_change_pct,
        oi_change_pct=oi_change_pct,
        buy_share_pct=buy_share_pct,
        cvd_delta=cvd_delta,
        long_liquidations_usd=long_liquidations_usd,
        short_liquidations_usd=short_liquidations_usd,
        funding_rate_pct=funding_rate_pct,
        predicted_funding_rate_pct=predicted_funding_rate_pct,
        stance=stance,
        confidence=confidence,
        summary=summary,
        reasons=reasons,
    )


def _build_summary(
    *,
    stance: str,
    confidence: str,
    price_change_pct: float,
    oi_change_pct: float,
    buy_share_pct: float,
) -> str:
    return (
        f"{stance}, 신뢰도 {confidence.lower()}."
        f" 가격 {price_change_pct:+.2f}%, OI {oi_change_pct:+.2f}%,"
        f" 최근 15분 매수 비중 {buy_share_pct:.1f}%입니다."
    )


def _grandma_opening(analysis: BitmexWhaleAnalysis) -> str:
    if analysis.stance == "신규 롱 진입 우세":
        return "허허, 지금은 비트맥스 기준으로 롱 쪽 새 돈이 붙는 그림에 조금 더 가깝구나."
    if analysis.stance == "신규 숏 진입 우세":
        return "허허, 지금은 비트맥스 기준으로 숏 쪽 새 물량이 붙는 그림에 조금 더 가깝구나."
    if analysis.stance == "롱 정리 또는 롱 청산 우세":
        return "허허, 새 숏이라기보다 롱 쪽 정리나 청산 냄새가 더 나는 구간이구나."
    if analysis.stance == "숏 커버링 우세":
        return "허허, 새 롱보다는 숏 커버링이 먼저 붙는 그림에 가까워 보이는구나."
    return "허허, 지금은 한쪽으로 딱 잘라 말하기엔 아직 근거가 좀 약하구나."


def _grandma_action_line(user_question: str, analysis: BitmexWhaleAnalysis) -> str:
    question = (user_question or "").lower()
    asks_direction = any(token in question for token in ("롱", "숏", "long", "short", "방향"))

    if analysis.confidence == "낮음":
        return "섣불리 롱이니 숏이니 단정하지 말고, 1M 알림이 다시 붙는지랑 OI가 더 커지는지 한 번 더 보거라."
    if analysis.stance == "신규 롱 진입 우세":
        if asks_direction:
            return "억지로 말하면 롱 쪽으로 기우는 편이지만, 추격보다는 눌림이나 재확인 한 번 보고 들어가는 게 낫다."
        return "위로 미는 힘은 보이는데, 추격 매수보다는 한 번 더 확인하고 움직이는 게 낫다."
    if analysis.stance == "신규 숏 진입 우세":
        if asks_direction:
            return "억지로 말하면 숏 쪽으로 기우는 편인데, 반등 한 번 주는지 보고 들어가야 덜 다친다."
        return "아래로 누르는 힘은 보이는데, 급하게 따라붙기보다 반등 확인 뒤 보는 게 낫다."
    if analysis.stance == "롱 정리 또는 롱 청산 우세":
        return "이건 새 방향 베팅보다 기존 롱이 정리되는 그림일 수 있으니, 하방이 이어지는지부터 확인해 보거라."
    if analysis.stance == "숏 커버링 우세":
        return "이건 새 상방 베팅이라기보다 숏 정리일 수 있으니, 윗방향 지속성이 있는지부터 봐야 한다."
    return "지금은 애매하니 무리해서 포지션 잡기보다, OI나 대형 체결이 한 번 더 붙는지 기다리는 편이 낫다."


def _resolve_bitmex_btc_perp_symbol(api_key: str) -> dict:
    global _SYMBOL_CACHE
    if _SYMBOL_CACHE is not None:
        return _SYMBOL_CACHE

    markets = _request_json(api_key, "/future-markets", {})
    candidates = [
        market
        for market in markets
        if bool(market.get("is_perpetual"))
        and str(market.get("quote_asset", "")).upper() == "USD"
        and str(market.get("base_asset", "")).upper() == "BTC"
    ]

    preferred = [
        market
        for market in candidates
        if str(market.get("symbol_on_exchange", "")).upper() == "XBTUSD"
    ]
    if not preferred:
        preferred = [
            market
            for market in candidates
            if str(market.get("symbol", "")).upper() == "BTCUSD_PERP.0"
        ]

    if preferred:
        _SYMBOL_CACHE = preferred[0]
        return _SYMBOL_CACHE

    if not candidates:
        raise CoinalyzeError("BitMEX XBTUSD Perp 심볼을 Coinalyze API에서 찾지 못했습니다.")

    _SYMBOL_CACHE = candidates[0]
    return _SYMBOL_CACHE


def _get_history(
    api_key: str,
    path: str,
    symbol: str,
    interval: str,
    from_ts: int,
    to_ts: int,
    convert_to_usd: bool = False,
    allow_empty: bool = False,
) -> list[dict]:
    params = {
        "symbols": symbol,
        "interval": interval,
        "from": from_ts,
        "to": to_ts,
    }
    if convert_to_usd:
        params["convert_to_usd"] = "true"

    payload = _request_json(api_key, path, params)
    if not payload or not payload[0].get("history"):
        if allow_empty:
            return []
        raise CoinalyzeError(f"{path}에서 히스토리 데이터를 받지 못했습니다.")
    return payload[0]["history"]


def _get_current_value(api_key: str, path: str, symbol: str) -> float | None:
    payload = _request_json(api_key, path, {"symbols": symbol})
    if not payload:
        return None
    return payload[0].get("value")


def _request_json(api_key: str, path: str, params: dict) -> list[dict]:
    query = dict(params)
    query["api_key"] = api_key
    url = f"{API_BASE_URL}{path}?{urllib.parse.urlencode(query)}"
    request = urllib.request.Request(url, headers={"Accept": "application/json"})

    try:
        with _DIRECT_HTTP_OPENER.open(request, timeout=10) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code == 401:
            raise CoinalyzeError("COINALYZE_API_KEY가 없거나 잘못되었습니다.") from exc
        if exc.code == 429:
            raise CoinalyzeError("Coinalyze API 호출 한도를 잠시 넘었습니다. 잠깐 뒤 다시 시도해 주세요.") from exc
        raise CoinalyzeError(f"Coinalyze API 호출 실패: HTTP {exc.code}") from exc
    except urllib.error.URLError as exc:
        raise CoinalyzeError("Coinalyze API에 연결하지 못했습니다.") from exc
    except json.JSONDecodeError as exc:
        raise CoinalyzeError("Coinalyze 응답을 해석하지 못했습니다.") from exc


def _pct_change(before: float, after: float) -> float:
    if not before:
        return 0.0
    return ((after - before) / before) * 100.0


def _normalize_rate(value: float | None) -> float | None:
    if value is None:
        return None
    return float(value)


def _format_percent_or_na(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value:+.4f}%"
