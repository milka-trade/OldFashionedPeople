#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
BB Bounce Hunter v24.1 - 품질 복원판

v24.0 전략 100% 유지 + 기존 코드 인프라 품질 복원

매수 3단계:
  ① 일봉 상승장 확인 (시가 대비 양봉 OR 최근 3일 중 2일 양봉)
  ② 15분봉 BB 하단 터치 (BB Position ≤ 20%, BB 폭 ≥ 1.5%)
  ③ 반등 확인 (RSI상승, SRSI %K>%D, 양봉 중 2개 이상)

매도 4단계 (우선순위):
  ① 손절: -2.5%
  ② 강제 익절: +2.5%
  ③ 안전 익절: +1.2% AND (RSI하락 OR BB≥60%)
  ④ 트레일링: 1.5% 도달 후 고점 대비 -0.8%

v24.1 복원 사항:
  - 매시간 상세 Discord 보고서 (시장모멘텀+코인미니맵+보유상세+관심코인)
  - format_price_compact / format_profit_amount / calculate_coin_status_for_report
  - 매수/매도 시그널 상세 터미널 출력 (박스 형태)
  - 매도 스레드 peak_price 실시간 갱신 + 신고가 로그
  - 수동매도 감지 상세 Discord 경고
  - check_market_condition (시장 급락 감지)
  - 매수 차단 시간대 (08:59~09:15)
  - check_daily_trade_limit
  - 네트워크 오류 30초 대기
  - 크리티컬 에러 Discord 알림
  - 포지션 사이징 상세 로그
  - 동기화 경고 Discord 메시지
"""

import os
from dotenv import load_dotenv
load_dotenv()       #pip install python-dotenv PyJWT websocket-client pandas requests numpy

import jwt           
import uuid
import hashlib
import urllib.parse
import json
import websocket        
import pandas as pd
from datetime import datetime, timedelta
import time
import requests     
import numpy as np
from collections import deque
import traceback
import threading
from threading import Lock, Event


# ============================================================================
# SECTION 1: 터미널 색상
# ============================================================================

class Colors:
    HEADER = '\033[95m'
    BLUE = '\033[94m'
    CYAN = '\033[96m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'
    UNDERLINE = '\033[4m'
    MAGENTA = '\033[35m'


# ============================================================================
# SECTION 2: 시스템 설정
# ============================================================================

DEBUG_MODE = True
TEST_MODE = False
VERSION = "25.0 BB_BOUNCE_HUNTER"

# 거래 대상 (고정 7개)
FIXED_STABLE_COINS = [
    "KRW-ETH", "KRW-XRP", "KRW-SOL",
    "KRW-ADA", "KRW-LINK", "KRW-BCH", "KRW-SUI"
]

# 포지션 관리
MAX_HOLDINGS = 2
FIRST_BUY_RATIO = 0.5
BUY_FEE_BUFFER = 0.995
MIN_BUY_PRICE = 500
MAX_DAILY_TRADES = 999

# ============================================================================
# ★ 시장 등급별 파라미터 테이블 (v25.0 신규)
# ============================================================================
# 우선순위: BBW 실시간 측정(ETH+XRP) > 시간대 기본값(폴백)
#
# 등급 결정 기준:
#   HIGH : BBW ≥ 4.0%  (또는 시간대 00~05, 22~23시)
#   MID  : BBW 2.0~4.0% (또는 시간대 06~10, 20~21시)  ← v24.1 기본값과 동일
#   LOW  : BBW < 2.0%  (또는 시간대 11~19시)

MARKET_GRADE_PARAMS = {
    'HIGH': {
        # 高변동성: 넓은 진입 허용, 느슨한 추적
        'BUY_BB_MAX':            30,
        'BUY_BB_WIDTH_MIN':     1.5,
        'SELL_SAFE_PROFIT':     1.2,
        'SELL_SAFE_BB_MIN':      75,
        'SELL_TRAIL_ACTIVATION': 1.5,
        'SELL_TRAIL_DISTANCE':   0.8,
        'SELL_STOP_LOSS':       -2.5,
        'SELL_FORCE_PROFIT':     2.5,
        'BUY_MIN_HOLD_SEC':      120,
    },
    'MID': {
        # 中변동성: v24.1 기본값 그대로
        'BUY_BB_MAX':            25,
        'BUY_BB_WIDTH_MIN':     1.0,
        'SELL_SAFE_PROFIT':     1.2,
        'SELL_SAFE_BB_MIN':      70,
        'SELL_TRAIL_ACTIVATION': 1.2,
        'SELL_TRAIL_DISTANCE':   0.6,
        'SELL_STOP_LOSS':       -2.5,
        'SELL_FORCE_PROFIT':     2.5,
        'BUY_MIN_HOLD_SEC':      180,
    },
    'LOW': {
        # 低변동성: 엄격한 진입, 빠른 이익 실현
        'BUY_BB_MAX':            20,
        'BUY_BB_WIDTH_MIN':     0.8,
        'SELL_SAFE_PROFIT':     1.0,
        'SELL_SAFE_BB_MIN':      65,
        'SELL_TRAIL_ACTIVATION': 1.0,
        'SELL_TRAIL_DISTANCE':   0.5,
        'SELL_STOP_LOSS':       -2.0,
        'SELL_FORCE_PROFIT':     2.0,
        'BUY_MIN_HOLD_SEC':      240,
    },
}

# BBW 등급 임계값
GRADE_BBW_HIGH = 4.0    # BBW ≥ 4.0% → HIGH
GRADE_BBW_LOW  = 2.0    # BBW < 2.0% → LOW

# 시간대 → 기본 등급 매핑 (BBW 측정 실패 시 폴백)
HOUR_TO_GRADE = {}
for _h in range(24):
    if _h <= 5 or _h >= 22:
        HOUR_TO_GRADE[_h] = 'HIGH'
    elif (6 <= _h <= 10) or (20 <= _h <= 21):
        HOUR_TO_GRADE[_h] = 'MID'
    else:
        HOUR_TO_GRADE[_h] = 'LOW'

# BBW 측정 대표 코인 (ETH + XRP — 가볍고 대표성 높음)
GRADE_REFERENCE_COINS = ['KRW-ETH', 'KRW-XRP']

# 스레드 주기 (초)
BUY_THREAD_INTERVAL = 10
SELL_THREAD_INTERVAL = 5
MONITOR_THREAD_INTERVAL = 60
BUY_SLEEP_WHEN_FULL = 30          # 보유 가득 차면 30초 대기

# 캐시 TTL (초)
CACHE_TTL_CANDLE = 30
CACHE_TTL_DAILY = 60

# ── 매수 파라미터 (MID 등급 기본값 — 동적 파라미터 폴백용) ──
BUY_BB_MAX = 25
BUY_BB_WIDTH_MIN = 1.0
BUY_BOUNCE_MIN = 2
BUY_MIN_HOLD_SEC = 180

# ── 매도 파라미터 (MID 등급 기본값 — 동적 파라미터 폴백용) ──
SELL_STOP_LOSS = -2.5
SELL_FORCE_PROFIT = 2.5
SELL_SAFE_PROFIT = 1.2
SELL_SAFE_BB_MIN = 70
SELL_TRAIL_ACTIVATION = 1.2
SELL_TRAIL_DISTANCE = 0.6

# ── 리스크 관리 ──
REENTRY_COOLDOWN_MIN = 10
CONSECUTIVE_LOSS_LIMIT = 3
COOLDOWN_AFTER_LOSS = 30
MARKET_BREAKER_THRESHOLD = -3.0   # [복원] 시장 급락 감지 기준

# ── 매수 차단 시간대 (업비트 정산) ──  [복원]
BUY_BLOCK_START_HOUR = 8
BUY_BLOCK_START_MINUTE = 59
BUY_BLOCK_END_HOUR = 9
BUY_BLOCK_END_MINUTE = 15

# ── 기술 지표 기본값 ──
BB_PERIOD = 20
BB_STD_DEV = 2.0
RSI_PERIOD = 14
STOCH_RSI_PERIOD = 14
STOCH_K_PERIOD = 3
STOCH_D_PERIOD = 3


# ============================================================================
# SECTION 3: 환경 변수 및 글로벌 상태
# ============================================================================

DISCORD_WEBHOOK_URL = os.getenv("discord_webhook")
ACCESS_KEY = os.getenv("UPBIT_ACCESS_KEY")
SECRET_KEY = os.getenv("UPBIT_SECRET_KEY")

# 스레드 제어
stop_event = Event()
held_coins_lock = Lock()
trade_lock = Lock()
statistics_lock = Lock()
cache_lock = Lock()

# 글로벌 상태
upbit = None
held_coins = {}
recent_sells = {}
daily_trade_count = 0
last_reset_date = datetime.now().date()
data_cache = {}
cache_timestamps = {}

# ★ 현재 시장 등급 상태 (v25.0 신규)
current_market_grade = 'MID'           # 현재 적용 중인 등급
current_grade_source = 'init'          # 'bbw' | 'time' | 'init'
current_grade_bbw = 0.0                # 측정된 BBW 값
last_grade_check_time = None           # 마지막 등급 확인 시각
grade_lock = Lock()                    # 등급 갱신 동기화

# 통계
start_time = datetime.now()
total_trades = 0
winning_trades = 0
losing_trades = 0
total_profit = 0.0
trade_history = deque(maxlen=100)
consecutive_losses = 0
last_loss_time = None

# 일일 통계
daily_buy_count = 0
daily_sell_count = 0
daily_winning_trades = 0
daily_losing_trades = 0


# ============================================================================
# SECTION 4: 시작 메시지
# ============================================================================

print(f"\n{Colors.BOLD}{Colors.CYAN}{'='*60}")
print(f"  BB BOUNCE HUNTER {VERSION}")
print(f"  ★ 시장 등급 시스템: HIGH/MID/LOW 동적 파라미터")
print(f"  HIGH(BBW≥4%): BB≤30% 폭≥1.5% 손절-2.5% 강제+2.5%")
print(f"  MID (BBW2~4%): BB≤25% 폭≥1.0% 손절-2.5% 강제+2.5%")
print(f"  LOW (BBW<2%): BB≤20% 폭≥0.8% 손절-2.0% 강제+2.0%")
print(f"  BBW 측정: ETH+XRP 캐시 재활용 (매 10초 갱신)")
print(f"{'='*60}")
print(f"  Thread 1: 매수 ({BUY_THREAD_INTERVAL}초) | Thread 2: 매도 ({SELL_THREAD_INTERVAL}초)")
print(f"  Thread 3: 모니터 ({MONITOR_THREAD_INTERVAL}초) | Thread 4: WebSocket")
print(f"  MAX_HOLDINGS: {MAX_HOLDINGS} | 1차:{FIRST_BUY_RATIO:.0%} 2차:전량")
print(f"  매수차단: {BUY_BLOCK_START_HOUR:02d}:{BUY_BLOCK_START_MINUTE:02d}~{BUY_BLOCK_END_HOUR:02d}:{BUY_BLOCK_END_MINUTE:02d}")
print(f"  시장급락 차단: 평균 ≤ {MARKET_BREAKER_THRESHOLD}%")
print(f"{'='*60}{Colors.ENDC}\n")


# ============================================================================
# SECTION 5: Upbit REST API 클라이언트
# ============================================================================

UPBIT_API_BASE = "https://api.upbit.com"

class UpbitAPI:
    """Upbit 공식 REST API 클라이언트 (JWT 인증)"""

    def __init__(self, access_key, secret_key):
        self.access_key = access_key
        self.secret_key = secret_key

    def _make_jwt_token(self, query_params=None):
        payload = {
            'access_key': self.access_key,
            'nonce': str(uuid.uuid4()),
        }
        if query_params:
            query_string = urllib.parse.urlencode(query_params).encode()
            m = hashlib.sha512()
            m.update(query_string)
            payload['query_hash'] = m.hexdigest()
            payload['query_hash_alg'] = 'SHA512'
        token = jwt.encode(payload, self.secret_key, algorithm='HS256')
        if isinstance(token, bytes):
            token = token.decode('utf-8')
        return token

    def _auth_headers(self, query_params=None):
        token = self._make_jwt_token(query_params)
        return {'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'}

    def get_balances(self):
        try:
            headers = self._auth_headers()
            resp = requests.get(f"{UPBIT_API_BASE}/v1/accounts", headers=headers, timeout=10)
            if resp.status_code == 200:
                return resp.json()
            return None
        except Exception as e:
            if DEBUG_MODE:
                print(f"{Colors.RED}[API] get_balances 예외: {e}{Colors.ENDC}")
            return None

    def get_balance(self, currency):
        try:
            if '-' in str(currency):
                currency = currency.split('-')[1]
            balances = self.get_balances()
            if not balances:
                return 0.0
            for bal in balances:
                if bal.get('currency') == currency:
                    return float(bal.get('balance', 0.0))
            return 0.0
        except Exception:
            return 0.0

    def buy_market_order(self, ticker, price):
        try:
            params = {
                'market': ticker, 'side': 'bid',
                'price': str(round(price, 0)), 'ord_type': 'price',
            }
            headers = self._auth_headers(params)
            resp = requests.post(f"{UPBIT_API_BASE}/v1/orders", json=params, headers=headers, timeout=10)
            result = resp.json()
            if DEBUG_MODE:
                print(f"{Colors.CYAN}[API] buy {ticker} {price:,.0f}원 → {resp.status_code}{Colors.ENDC}")
            return result
        except Exception as e:
            if DEBUG_MODE:
                print(f"{Colors.RED}[API] buy_market_order 예외: {e}{Colors.ENDC}")
            return None

    def sell_market_order(self, ticker, volume):
        try:
            params = {
                'market': ticker, 'side': 'ask',
                'volume': str(volume), 'ord_type': 'market',
            }
            headers = self._auth_headers(params)
            resp = requests.post(f"{UPBIT_API_BASE}/v1/orders", json=params, headers=headers, timeout=10)
            result = resp.json()
            if DEBUG_MODE:
                print(f"{Colors.CYAN}[API] sell {ticker} {volume} → {resp.status_code}{Colors.ENDC}")
            return result
        except Exception as e:
            if DEBUG_MODE:
                print(f"{Colors.RED}[API] sell_market_order 예외: {e}{Colors.ENDC}")
            return None

    def get_order(self, uuid_str):
        try:
            params = {'uuid': uuid_str}
            headers = self._auth_headers(params)
            resp = requests.get(f"{UPBIT_API_BASE}/v1/order", params=params, headers=headers, timeout=10)
            if resp.status_code == 200:
                return resp.json()
            return None
        except Exception:
            return None

    def wait_order_filled(self, uuid_str, timeout_sec=5):
        try:
            elapsed = 0
            interval = 0.5
            while elapsed < timeout_sec:
                order = self.get_order(uuid_str)
                if order is None:
                    time.sleep(interval)
                    elapsed += interval
                    continue
                state = order.get('state', '')
                if state in ('done', 'cancel'):
                    trades = order.get('trades', [])
                    total_funds = 0.0
                    total_volume = 0.0
                    total_fee = float(order.get('paid_fee', 0))
                    if trades:
                        for t in trades:
                            total_funds += float(t.get('funds', 0))
                            total_volume += float(t.get('volume', 0))
                        avg_price = total_funds / total_volume if total_volume > 0 else 0
                    else:
                        exec_vol = float(order.get('executed_volume', 0))
                        exec_funds = float(order.get('executed_funds', 0))
                        avg_price = exec_funds / exec_vol if exec_vol > 0 else 0
                        total_volume = exec_vol
                    return {
                        'avg_price': avg_price, 'paid_fee': total_fee,
                        'executed_volume': total_volume, 'state': state
                    }
                time.sleep(interval)
                elapsed += interval

            order = self.get_order(uuid_str)
            if order:
                exec_vol = float(order.get('executed_volume', 0))
                exec_funds = float(order.get('executed_funds', 0))
                avg_price = exec_funds / exec_vol if exec_vol > 0 else 0
                return {
                    'avg_price': avg_price,
                    'paid_fee': float(order.get('paid_fee', 0)),
                    'executed_volume': exec_vol,
                    'state': order.get('state', 'timeout')
                }
            return None
        except Exception as e:
            if DEBUG_MODE:
                print(f"{Colors.RED}[API] wait_order_filled 예외: {e}{Colors.ENDC}")
            return None


# ============================================================================
# SECTION 6: WebSocket 실시간 가격 시스템
# ============================================================================

UPBIT_WS_URL = "wss://api.upbit.com/websocket/v1"

ws_price_cache = {}
ws_price_lock = threading.Lock()

ws_status = {
    'connected': False, 'last_received': 0.0,
    'reconnect_count': 0, 'subscribed_tickers': [],
    'error_count': 0,
}
ws_status_lock = threading.Lock()

_ws_app = None
_ws_app_lock = threading.Lock()

WS_CACHE_STALE_SEC = 30.0

_api_last_call_time = 0.0
_api_call_lock = threading.Lock()


def _rate_limit_wait(min_interval=0.12):
    global _api_last_call_time
    with _api_call_lock:
        now = time.time()
        elapsed = now - _api_last_call_time
        if elapsed < min_interval:
            time.sleep(min_interval - elapsed)
        _api_last_call_time = time.time()


def _get_ws_subscribe_tickers():
    tickers = set(FIXED_STABLE_COINS)
    try:
        with held_coins_lock:
            tickers.update(held_coins.keys())
    except Exception:
        pass
    return sorted(tickers)


def _build_subscribe_message(tickers):
    return json.dumps([
        {"ticket": str(uuid.uuid4())},
        {"type": "ticker", "codes": tickers, "isOnlyRealtime": False}
    ])


def _ws_on_open(ws):
    tickers = _get_ws_subscribe_tickers()
    msg = _build_subscribe_message(tickers)
    ws.send(msg)
    with ws_status_lock:
        ws_status['connected'] = True
        ws_status['subscribed_tickers'] = tickers
    print(f"{Colors.GREEN}[WS] 연결 성공 ({len(tickers)}개 구독){Colors.ENDC}")


def _ws_on_message(ws, message):
    try:
        data = json.loads(message)
        code = data.get('code', '')
        price = data.get('trade_price', 0)
        if code and price > 0:
            with ws_price_lock:
                ws_price_cache[code] = {'price': price, 'ts': time.time()}
            with ws_status_lock:
                ws_status['last_received'] = time.time()
    except Exception:
        pass


def _ws_on_error(ws, error):
    with ws_status_lock:
        ws_status['error_count'] += 1
    if DEBUG_MODE:
        print(f"{Colors.RED}[WS] 오류: {error}{Colors.ENDC}")


def _ws_on_close(ws, close_status_code, close_msg):
    with ws_status_lock:
        ws_status['connected'] = False


def _ws_on_ping(ws, message):
    ws.pong(message)


def _create_ws_app():
    return websocket.WebSocketApp(
        UPBIT_WS_URL,
        on_open=_ws_on_open, on_message=_ws_on_message,
        on_error=_ws_on_error, on_close=_ws_on_close,
        on_ping=_ws_on_ping,
    )


def websocket_thread_worker():
    global _ws_app
    print(f"{Colors.BLUE}[Thread 4] WebSocket 스레드 시작{Colors.ENDC}")
    while not stop_event.is_set():
        try:
            app = _create_ws_app()
            with _ws_app_lock:
                _ws_app = app
            app.run_forever(
                ping_interval=30, ping_timeout=10,
                skip_utf8_validation=True,
            )
        except Exception as e:
            if DEBUG_MODE:
                print(f"{Colors.RED}[WS] run_forever 예외: {e}{Colors.ENDC}")
        with ws_status_lock:
            ws_status['connected'] = False
            ws_status['reconnect_count'] += 1
            rc = ws_status['reconnect_count']
        if not stop_event.is_set():
            wait = min(5 + rc * 2, 60)
            print(f"{Colors.YELLOW}[WS] 재연결 #{rc} ({wait}초 후){Colors.ENDC}")
            time.sleep(wait)
    print(f"{Colors.BLUE}[Thread 4] WebSocket 종료{Colors.ENDC}")


def get_ws_status_summary():
    with ws_status_lock:
        return {
            'connected': ws_status['connected'],
            'reconnect_count': ws_status['reconnect_count'],
            'subscribed': len(ws_status['subscribed_tickers']),
            'error_count': ws_status['error_count'],
        }


# ============================================================================
# SECTION 7: 현재가 조회 (WS 우선 + REST fallback)
# ============================================================================

def get_current_price(ticker):
    try:
        with ws_price_lock:
            if ticker in ws_price_cache:
                entry = ws_price_cache[ticker]
                age = time.time() - entry['ts']
                if age < WS_CACHE_STALE_SEC:
                    return entry['price']
        return _get_price_rest_single(ticker)
    except Exception:
        return None


def _get_price_rest_single(ticker):
    try:
        _rate_limit_wait()
        resp = requests.get(
            f"{UPBIT_API_BASE}/v1/ticker",
            params={'markets': ticker}, timeout=5
        )
        if resp.status_code == 200:
            data = resp.json()
            if data and len(data) > 0:
                return data[0].get('trade_price', None)
        return None
    except Exception:
        return None


# ============================================================================
# SECTION 8: OHLCV 데이터 수집
# ============================================================================

def get_ohlcv(ticker, interval="minute15", count=200, to=None):
    try:
        _rate_limit_wait()
        interval_map = {
            'minute1': '/v1/candles/minutes/1',
            'minute5': '/v1/candles/minutes/5',
            'minute15': '/v1/candles/minutes/15',
            'minute60': '/v1/candles/minutes/60',
            'day': '/v1/candles/days',
        }
        path = interval_map.get(interval, '/v1/candles/minutes/15')
        max_per_call = 200
        all_candles = []
        remaining = count
        current_to = to

        while remaining > 0:
            batch_count = min(remaining, max_per_call)
            params = {'market': ticker, 'count': batch_count}
            if current_to:
                params['to'] = current_to
            resp = requests.get(f"{UPBIT_API_BASE}{path}", params=params, timeout=10)
            if resp.status_code != 200:
                break
            candles = resp.json()
            if not candles:
                break
            all_candles.extend(candles)
            remaining -= len(candles)
            if len(candles) < batch_count:
                break
            last_dt = candles[-1].get('candle_date_time_utc', '')
            if last_dt:
                current_to = last_dt
            else:
                break
            time.sleep(0.15)

        if not all_candles:
            return None

        rows = [{
            'datetime': c.get('candle_date_time_kst', ''),
            'open': c.get('opening_price', 0.0),
            'high': c.get('high_price', 0.0),
            'low': c.get('low_price', 0.0),
            'close': c.get('trade_price', 0.0),
            'volume': c.get('candle_acc_trade_volume', 0.0),
            'value': c.get('candle_acc_trade_price', 0.0),
        } for c in all_candles]

        df = pd.DataFrame(rows)
        df['datetime'] = pd.to_datetime(df['datetime'])
        df = df.set_index('datetime').sort_index(ascending=True)
        df = df[~df.index.duplicated(keep='last')]
        if len(df) > count:
            df = df.iloc[-count:]
        return df

    except Exception as e:
        if DEBUG_MODE:
            print(f"{Colors.RED}[API] get_ohlcv({ticker},{interval},{count}) 예외: {e}{Colors.ENDC}")
        return None


# ============================================================================
# SECTION 9: 캐시 시스템
# ============================================================================

def get_cached_data(cache_key, ttl):
    try:
        with cache_lock:
            if cache_key in data_cache and cache_key in cache_timestamps:
                age = (datetime.now() - cache_timestamps[cache_key]).total_seconds()
                if age < ttl:
                    return data_cache[cache_key]
        return None
    except Exception:
        return None


def set_cached_data(cache_key, data):
    try:
        with cache_lock:
            data_cache[cache_key] = data
            cache_timestamps[cache_key] = datetime.now()
    except Exception:
        pass


def get_candles_15m(ticker, count=50):
    try:
        cache_key = f"{ticker}_15m_{count}"
        cached = get_cached_data(cache_key, CACHE_TTL_CANDLE)
        if cached is not None:
            return cached
        df = get_ohlcv(ticker, interval="minute15", count=count)
        if df is not None and len(df) >= 20:
            df = add_indicators(df)
            if df is not None:
                set_cached_data(cache_key, df)
                return df
        return None
    except Exception:
        return None


def get_candles_daily(ticker, count=10):
    try:
        cache_key = f"{ticker}_daily_{count}"
        cached = get_cached_data(cache_key, CACHE_TTL_DAILY)
        if cached is not None:
            return cached
        df = get_ohlcv(ticker, interval="day", count=count)
        if df is not None and len(df) >= 1:
            set_cached_data(cache_key, df)
            return df
        return None
    except Exception:
        return None


# ============================================================================
# SECTION 10: 기술 지표 계산
# ============================================================================

def calculate_rsi(series, period=RSI_PERIOD):
    delta = series.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = (-delta).where(delta < 0, 0.0)
    avg_gain = gain.ewm(com=period - 1, min_periods=period).mean()
    avg_loss = loss.ewm(com=period - 1, min_periods=period).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def calculate_stochastic_rsi(series, rsi_period=14, stoch_period=14, k_period=3, d_period=3):
    rsi = calculate_rsi(series, rsi_period)
    rsi_min = rsi.rolling(window=stoch_period).min()
    rsi_max = rsi.rolling(window=stoch_period).max()
    rsi_range = rsi_max - rsi_min
    stoch_rsi = ((rsi - rsi_min) / rsi_range.replace(0, np.nan)) * 100
    stoch_rsi = stoch_rsi.fillna(50)
    k = stoch_rsi.rolling(window=k_period).mean().fillna(50)
    d = k.rolling(window=d_period).mean().fillna(50)
    return k, d


def calculate_bollinger_bands(df, period=BB_PERIOD, std_dev=BB_STD_DEV):
    df['bb_mid'] = df['close'].rolling(window=period).mean()
    df['bb_std'] = df['close'].rolling(window=period).std()
    df['BB_UPPER'] = df['bb_mid'] + (df['bb_std'] * std_dev)
    df['BB_LOWER'] = df['bb_mid'] - (df['bb_std'] * std_dev)
    bb_range = df['BB_UPPER'] - df['BB_LOWER']
    df['bb_position'] = ((df['close'] - df['BB_LOWER']) / bb_range.replace(0, np.nan) * 100).clip(0, 100).fillna(50)
    df['bb_width'] = ((bb_range / df['BB_LOWER'].replace(0, np.nan)) * 100).fillna(0)
    return df


def add_indicators(df):
    try:
        if df is None or len(df) < 20:
            return None
        df = calculate_bollinger_bands(df)
        df['rsi'] = calculate_rsi(df['close'])
        df['srsi_k'], df['srsi_d'] = calculate_stochastic_rsi(df['close'])
        df['is_bull'] = df['close'] >= df['open']
        # SRSI 방향 (보고서용)
        df['srsi_direction'] = np.where(
            df['srsi_k'] > df['srsi_d'], '↗',
            np.where(df['srsi_k'] < df['srsi_d'], '↘', '→')
        )
        return df
    except Exception as e:
        if DEBUG_MODE:
            print(f"{Colors.RED}[Indicators] {e}{Colors.ENDC}")
        return None


# ============================================================================
# SECTION 11: Discord 알림 함수
# ============================================================================

def send_discord_message(message, is_critical=False):
    if not DISCORD_WEBHOOK_URL:
        return False
    try:
        header = f"EVOLUTION {VERSION}"
        if is_critical:
            full_message = f"@everyone\n**{header}**\n{message}"
        else:
            full_message = f"**{header}**\n{message}"
        data = {"content": full_message}
        resp = requests.post(DISCORD_WEBHOOK_URL, json=data, timeout=5)
        return resp.status_code == 204
    except Exception as e:
        if DEBUG_MODE:
            print(f"{Colors.RED}[Discord Error] {e}{Colors.ENDC}")
        return False


def send_buy_notification(ticker, signal, buy_amount, total_balance):
    """[복원] 매수 알림 - 기존 품질 유지"""
    try:
        portfolio = get_enhanced_portfolio_status()
        coin_name = ticker.replace('KRW-', '')
        asset_line = (f"💰 **자산** `총 {portfolio['total_assets']:,.0f}원` | "
                      f"`코인 {portfolio['total_coin_value']:,.0f}원` | "
                      f"`현금 {portfolio['krw_balance']:,.0f}원`")
        bb_w = f" [폭{signal.get('bb_width_pct', 0):.1f}%]"
        buy_info = (f"📈 **{coin_name} 매수완료**\n"
                    f"├ **거래** `{buy_amount:,.0f}원` @ `{signal['entry_price']:,.0f}원`\n"
                    f"└ 📊 `BB {signal['bb_position']:.0f}%{bb_w}` | "
                    f"**사유:** {signal['reason']}")

        holdings_text = ""
        if portfolio['coins']:
            holdings_text = f"\n\n📦 **보유 {len(portfolio['coins'])}/{MAX_HOLDINGS}**"
            for ci in portfolio['coins']:
                c_name = ci['ticker'].replace('KRW-', '')
                pft_str = format_profit_amount(ci['value'] * ci['profit_pct'] / 100)
                holdings_text += f"\n├ **{c_name}** `{ci['profit_pct']:+.2f}%({pft_str})` `({ci['value']:,.0f}원)`"

        message = (f"\n{'━'*10}\n{asset_line}\n{'━'*10}\n\n"
                   f"{buy_info}{holdings_text}\n\n⏱ {datetime.now().strftime('%H:%M:%S')}\n")
        send_discord_message(message)
    except Exception as e:
        if DEBUG_MODE:
            print(f"{Colors.RED}[Buy Noti Error] {e}{Colors.ENDC}")


def send_sell_notification(ticker, holding_info, signal, profit_amount, holding_duration):
    """[복원] 매도 알림 - 금일 성과 포함"""
    try:
        portfolio = get_enhanced_portfolio_status()
        coin_name = ticker.replace('KRW-', '')
        emoji = "📈" if signal['profit_pct'] > 0 else "📉"
        asset_line = (f"💰 **자산** `총 {portfolio['total_assets']:,.0f}원` | "
                      f"`코인 {portfolio['total_coin_value']:,.0f}원` | "
                      f"`현금 {portfolio['krw_balance']:,.0f}원`")
        bb_w = f" [폭{signal.get('bb_width_pct', 0):.1f}%]"
        pft_str = format_profit_amount(profit_amount)
        sell_info = (f"{emoji} **{coin_name} 매도완료** `({holding_duration} 보유)`\n"
                     f"├ **거래** `{holding_info['buy_price']:,.0f}원` → `{signal['exit_price']:,.0f}원`\n"
                     f"├ 💵 **{signal['profit_pct']:+.2f}%** `({pft_str})`\n"
                     f"└ 📊 `BB {signal['bb_position']:.0f}%{bb_w}` | **사유:** {signal['reason']}")

        holdings_text = ""
        if portfolio['coins']:
            holdings_text = f"\n\n📦 **보유 {len(portfolio['coins'])}/{MAX_HOLDINGS}**"
            for ci in portfolio['coins']:
                c_name = ci['ticker'].replace('KRW-', '')
                holdings_text += f"\n├ **{c_name}** `{ci['profit_pct']:+.2f}%` `({ci['value']:,.0f}원)`"
        else:
            holdings_text = f"\n\n📦 **보유** `0/{MAX_HOLDINGS}` (전량 청산)"

        # [복원] 금일 거래 성과
        if daily_sell_count == 0:
            trade_summary = f"\n🎯 **금일** 매수 `{daily_buy_count}건` | 매도 `1건` (이번 거래)"
        else:
            daily_wr = (daily_winning_trades / daily_sell_count * 100) if daily_sell_count > 0 else 0
            trade_summary = (f"\n🎯 **금일** 매수 `{daily_buy_count}건` | "
                             f"매도 `{daily_sell_count}건` | 승률 `{daily_wr:.1f}%`")

        message = (f"\n{'━'*10}\n{asset_line}\n{'━'*10}\n\n"
                   f"{sell_info}{holdings_text}{trade_summary}\n\n⏰ {datetime.now().strftime('%H:%M:%S')}\n")
        send_discord_message(message)
    except Exception as e:
        if DEBUG_MODE:
            print(f"{Colors.RED}[Sell Noti Error] {e}{Colors.ENDC}")


def send_error_notification(error_type, error_details):
    """오류 알림"""
    try:
        message = (f"\n**오류 발생**\n\n**유형:** `{error_type}`\n\n"
                   f"**상세 내용:**\n```\n{error_details[:500]}\n```\n\n"
                   f"**시각:** `{datetime.now().strftime('%H:%M:%S')}`\n")
        send_discord_message(message, is_critical=True)
    except Exception:
        pass


# ============================================================================
# SECTION 12: 유틸리티 함수 (format 함수 복원)
# ============================================================================

def format_duration(td):
    try:
        total_seconds = int(td.total_seconds())
        hours = total_seconds // 3600
        minutes = (total_seconds % 3600) // 60
        return f"{hours}시간 {minutes}분" if hours > 0 else f"{minutes}분"
    except Exception:
        return "0분"


def format_price_compact(price):
    """[복원] 가격 압축 표시: 1052만 / 350.2만 / 3,520 / 850.5"""
    if price >= 10_000_000:
        return f"{price/10000:.0f}만"
    elif price >= 10_000:
        return f"{price/10000:.1f}만"
    elif price >= 1_000:
        return f"{price:,.0f}"
    else:
        return f"{price:.1f}"


def format_profit_amount(amount):
    """[복원] 수익금 압축: +1.3만 / +8,500"""
    if abs(amount) >= 10_000:
        return f"{amount/10000:+.1f}만"
    else:
        return f"{amount:+,.0f}"


def get_portfolio_status():
    """[복원] 거래소 실제 잔고 기반 포트폴리오 (get_total_balance용)"""
    try:
        if not upbit:
            return {'krw_balance': 0.0, 'total_coin_value': 0.0, 'total_assets': 0.0, 'coins': []}
        krw_balance = upbit.get_balance("KRW")
        balances = upbit.get_balances()
        coins_info = []
        total_coin_value = 0.0
        if balances:
            for bal in balances:
                currency = bal.get('currency', '')
                if currency == 'KRW':
                    continue
                balance = float(bal.get('balance', 0))
                if balance > 0:
                    ticker = f"KRW-{currency}"
                    avg_buy_price = float(bal.get('avg_buy_price', 0))
                    current_price = get_current_price(ticker)
                    if current_price:
                        coin_value = balance * current_price
                        total_coin_value += coin_value
                        profit_pct = ((current_price - avg_buy_price) / avg_buy_price * 100) if avg_buy_price > 0 else 0
                        coins_info.append({
                            'ticker': ticker, 'balance': balance,
                            'avg_buy_price': avg_buy_price,
                            'current_price': current_price,
                            'value': coin_value, 'profit_pct': profit_pct
                        })
        total_assets = krw_balance + total_coin_value
        return {'krw_balance': krw_balance, 'total_coin_value': total_coin_value,
                'total_assets': total_assets, 'coins': coins_info}
    except Exception:
        return {'krw_balance': 0.0, 'total_coin_value': 0.0, 'total_assets': 0.0, 'coins': []}


def get_enhanced_portfolio_status():
    """향상된 포트폴리오 상태 조회 (held_coins + Upbit API 통합)"""
    try:
        if not upbit:
            return {'krw_balance': 0.0, 'total_coin_value': 0.0, 'total_assets': 0.0, 'coins': []}
        krw_balance = upbit.get_balance("KRW")
        coins_info = []
        total_coin_value = 0.0
        with held_coins_lock:
            for ticker, hold_info in held_coins.items():
                try:
                    current_price = get_current_price(ticker)
                    if not current_price:
                        continue
                    balance = upbit.get_balance(ticker)
                    if balance <= 0:
                        continue
                    coin_value = balance * current_price
                    total_coin_value += coin_value
                    buy_price = hold_info['buy_price']
                    profit_pct = ((current_price - buy_price) / buy_price) * 100
                    coins_info.append({
                        'ticker': ticker, 'balance': balance,
                        'buy_price': buy_price, 'current_price': current_price,
                        'value': coin_value, 'profit_pct': profit_pct,
                        'buy_time': hold_info.get('buy_time'),
                        'buy_reason': hold_info.get('buy_reason', '알 수 없음')
                    })
                except Exception:
                    continue
        total_assets = krw_balance + total_coin_value
        return {'krw_balance': krw_balance, 'total_coin_value': total_coin_value,
                'total_assets': total_assets, 'coins': coins_info}
    except Exception:
        return {'krw_balance': 0.0, 'total_coin_value': 0.0, 'total_assets': 0.0, 'coins': []}


def get_total_balance():
    """[복원] 총 자산 조회 - 거래소 실제 잔고 기반"""
    portfolio = get_portfolio_status()
    return portfolio['total_assets']


def calculate_coin_status_for_report(ticker):
    """[복원] 보고서용 코인 상태 (일봉 + 15분봉 통합)"""
    try:
        cur_price = get_current_price(ticker) or 0

        # === 일봉 ===
        df_daily = get_candles_daily(ticker, count=5)
        d_change = 0.0
        is_bullish = False
        if df_daily is not None and len(df_daily) >= 1:
            td = df_daily.iloc[-1]
            d_open = td['open']
            d_close = td['close']
            is_bullish = d_close >= d_open
            actual_price = cur_price if cur_price > 0 else d_close
            d_change = ((actual_price - d_open) / d_open * 100) if d_open > 0 else 0

        # === 15분봉 ===
        df_15m = get_candles_15m(ticker, count=30)
        bb15 = 50.0
        bw15 = 0.0
        rsi15 = 50.0
        srsi_k = 50.0
        srsi_direction = '→'
        if df_15m is not None and len(df_15m) >= 20:
            c = df_15m.iloc[-1]
            bb15 = c.get('bb_position', 50)
            bw15 = c.get('bb_width', 0)
            rsi15 = c.get('rsi', 50)
            srsi_k = c.get('srsi_k', 50)
            srsi_d = c.get('srsi_d', 50)
            srsi_direction = '↗' if srsi_k > srsi_d else ('↘' if srsi_k < srsi_d else '→')
            if cur_price == 0:
                cur_price = c.get('close', 0)

        return {
            'cur_price': cur_price,
            'cur_price_str': format_price_compact(cur_price) if cur_price > 0 else '-',
            'd_change': d_change, 'is_bullish': is_bullish,
            'bb15': bb15, 'bw15': bw15, 'rsi15': rsi15,
            'srsi_k': srsi_k, 'srsi_direction': srsi_direction,
        }
    except Exception:
        return {
            'cur_price': 0, 'cur_price_str': '-',
            'd_change': 0, 'is_bullish': False,
            'bb15': 50, 'bw15': 0, 'rsi15': 50,
            'srsi_k': 50, 'srsi_direction': '→',
        }


def check_reentry_cooldown(ticker):
    try:
        if ticker not in recent_sells:
            return True, "OK"
        sell_time = recent_sells[ticker]['time']
        elapsed = (datetime.now() - sell_time).total_seconds() / 60
        if elapsed < REENTRY_COOLDOWN_MIN:
            remaining = int(REENTRY_COOLDOWN_MIN - elapsed)
            return False, f"쿨다운 {remaining}분 남음"
        return True, "OK"
    except Exception:
        return True, "OK"


def reset_daily_counter():
    global daily_trade_count, last_reset_date
    global daily_buy_count, daily_sell_count, daily_winning_trades, daily_losing_trades
    try:
        today = datetime.now().date()
        if today != last_reset_date:
            daily_trade_count = 0
            daily_buy_count = 0
            daily_sell_count = 0
            daily_winning_trades = 0
            daily_losing_trades = 0
            last_reset_date = today
            print(f"{Colors.CYAN}[Reset] 일일 통계 초기화 ({today}){Colors.ENDC}")
    except Exception:
        pass


def check_consecutive_losses():
    """연속 손실 쿨다운 확인"""
    global consecutive_losses, last_loss_time
    if consecutive_losses >= CONSECUTIVE_LOSS_LIMIT:
        if last_loss_time:
            elapsed = (datetime.now() - last_loss_time).total_seconds() / 60
            if elapsed < COOLDOWN_AFTER_LOSS:
                remaining = int(COOLDOWN_AFTER_LOSS - elapsed)
                return False, f"연속손실 쿨다운 {remaining}분"
            else:
                consecutive_losses = 0
                last_loss_time = None
    return True, "OK"


def check_market_condition():
    """[복원] 시장 급락 감지"""
    try:
        total_change = 0.0
        valid_count = 0
        for ticker in FIXED_STABLE_COINS:
            df = get_candles_15m(ticker, count=3)
            if df is not None and len(df) >= 2:
                change = ((df.iloc[-1]['close'] - df.iloc[-2]['close']) / df.iloc[-2]['close']) * 100
                total_change += change
                valid_count += 1
        if valid_count == 0:
            return True, 0.0
        avg_change = total_change / valid_count
        if avg_change <= MARKET_BREAKER_THRESHOLD:
            return False, avg_change
        return True, avg_change
    except Exception:
        return True, 0.0


def check_daily_trade_limit():
    """[복원] 일일 거래 한도"""
    global daily_trade_count, last_reset_date
    today = datetime.now().date()
    if today != last_reset_date:
        daily_trade_count = 0
        last_reset_date = today
    return daily_trade_count < MAX_DAILY_TRADES


# ============================================================================
# ★ SECTION 12-B: 시장 등급 시스템 (v25.0 신규)
# ============================================================================

def get_time_based_grade() -> str:
    """
    현재 시각 기반 등급 반환 (BBW 측정 실패 시 폴백)
    HIGH: 00~05시, 22~23시
    MID : 06~10시, 20~21시
    LOW : 11~19시
    """
    hour = datetime.now().hour
    return HOUR_TO_GRADE.get(hour, 'MID')


def measure_reference_bbw() -> float | None:
    """
    ETH + XRP 캐시된 15분봉으로 BBW 평균 측정.
    API 추가 호출 없음 — 이미 캐시된 데이터 재활용.
    실패 시 None 반환.
    """
    try:
        bbw_values = []
        for ticker in GRADE_REFERENCE_COINS:
            df = get_candles_15m(ticker, count=30)
            if df is None or len(df) < 20:
                continue
            bbw = df.iloc[-1].get('bb_width', None)
            if bbw is not None and bbw > 0:
                bbw_values.append(bbw)
        if not bbw_values:
            return None
        return sum(bbw_values) / len(bbw_values)
    except Exception:
        return None


def update_market_grade() -> str:
    """
    ★ 현재 시장 등급 결정 및 글로벌 상태 업데이트.
    우선순위: BBW 실시간 > 시간대 폴백

    반환: 'HIGH' | 'MID' | 'LOW'
    """
    global current_market_grade, current_grade_source, current_grade_bbw
    global last_grade_check_time

    try:
        with grade_lock:
            # BBW 실시간 측정 (ETH+XRP 캐시 재활용)
            bbw = measure_reference_bbw()

            if bbw is not None:
                # BBW 기반 등급
                if bbw >= GRADE_BBW_HIGH:
                    grade = 'HIGH'
                elif bbw < GRADE_BBW_LOW:
                    grade = 'LOW'
                else:
                    grade = 'MID'
                source = 'bbw'
            else:
                # 폴백: 시간대 기반
                grade = get_time_based_grade()
                source = 'time'
                bbw = 0.0

            prev_grade = current_market_grade
            current_market_grade = grade
            current_grade_source = source
            current_grade_bbw = bbw
            last_grade_check_time = datetime.now()

            # 등급 변경 시 로그
            if prev_grade != grade and DEBUG_MODE:
                src_str = f"BBW {bbw:.1f}%" if source == 'bbw' else f"시간대 {datetime.now().hour}시"
                print(f"{Colors.MAGENTA}[Grade] {prev_grade} → {grade} ({src_str}){Colors.ENDC}")

            return grade

    except Exception as e:
        if DEBUG_MODE:
            print(f"{Colors.RED}[Grade] 등급 갱신 오류: {e}{Colors.ENDC}")
        return current_market_grade  # 오류 시 이전 등급 유지


def get_grade_params(grade: str = None) -> dict:
    """
    지정 등급(또는 현재 등급)의 파라미터 딕셔너리 반환.
    등급이 없거나 잘못된 경우 MID(기본값) 반환.
    """
    if grade is None:
        grade = current_market_grade
    return MARKET_GRADE_PARAMS.get(grade, MARKET_GRADE_PARAMS['MID'])


def get_grade_display_str() -> str:
    """터미널/Discord 표시용 등급 1줄 문자열"""
    grade = current_market_grade
    bbw = current_grade_bbw
    source = current_grade_source
    emoji = {'HIGH': '🔴', 'MID': '🟡', 'LOW': '🔵'}.get(grade, '⬜')
    src_str = f"BBW {bbw:.1f}%" if source == 'bbw' else f"시간대{datetime.now().hour}시"
    p = get_grade_params(grade)
    return (f"{emoji} [{grade}] {src_str} | "
            f"BB≤{p['BUY_BB_MAX']}% 폭≥{p['BUY_BB_WIDTH_MIN']}% "
            f"손절{p['SELL_STOP_LOSS']}% 강제+{p['SELL_FORCE_PROFIT']}%")


# ============================================================================
# SECTION 13: ★ 매수 신호 (핵심 - v24.0 전략 100% 유지)
# ============================================================================

def check_daily_bullish(ticker):
    """일봉 상승장 확인 (당일 양봉 OR 최근 3일 중 양봉 2일+)"""
    try:
        df_daily = get_candles_daily(ticker, count=5)
        if df_daily is None or len(df_daily) < 1:
            return False, "일봉 데이터 없음"
        today = df_daily.iloc[-1]
        today_change = ((today['close'] - today['open']) / today['open'] * 100) if today['open'] > 0 else 0
        if today_change >= 0:
            return True, f"당일양봉({today_change:+.2f}%)"
        if len(df_daily) >= 3:
            recent_3 = df_daily.iloc[-3:]
            bull_days = sum(1 for _, row in recent_3.iterrows() if row['close'] >= row['open'])
            if bull_days >= 2:
                return True, f"3일중{bull_days}일양봉(오늘{today_change:+.1f}%)"
        return False, f"하락장(오늘{today_change:+.2f}%)"
    except Exception as e:
        return False, f"오류: {e}"


def buy_signal(ticker):
    """
    ★ 매수 신호 - 3단계 간결 로직 (v24.0 100% 동일)
    Step 1: 일봉 상승장 확인
    Step 2: 15분봉 BB 하단 (≤BB_MAX%) + BB 폭 (≥BBW_MIN%)
    Step 3: 반등 확인 (RSI상승, SRSI, 양봉 중 2개+)

    ★ v25.0: 현재 시장 등급 파라미터 동적 적용
    """
    try:
        df = get_candles_15m(ticker, count=50)
        if df is None or len(df) < 25:
            return {'signal': False, 'reason': '데이터 부족',
                    'entry_price': 0, 'bb_position': 50, 'bb_width_pct': 0}
        current = df.iloc[-1]
        prev = df.iloc[-2]

        # ★ 현재 등급 파라미터 가져오기
        grade = current_market_grade
        p = get_grade_params(grade)
        _bb_max       = p['BUY_BB_MAX']
        _bbw_min      = p['BUY_BB_WIDTH_MIN']

        base = {
            'signal': False, 'reason': '',
            'entry_price': current['close'],
            'bb_position': current['bb_position'],
            'bb_width_pct': current['bb_width'],
            'market_grade': grade,          # ★ 등급 기록
        }

        # Step 1: 일봉 상승장
        is_bull, daily_reason = check_daily_bullish(ticker)
        if not is_bull:
            base['reason'] = f"일봉거부: {daily_reason}"
            return base

        # Step 2: BB 하단 + BB 폭 (★ 동적 파라미터)
        bb_pos = current['bb_position']
        bb_width = current['bb_width']
        if bb_pos > _bb_max:
            base['reason'] = f"BB{bb_pos:.0f}%>{_bb_max}%[{grade}]"
            return base
        if bb_width < _bbw_min:
            base['reason'] = f"BB폭{bb_width:.1f}%<{_bbw_min}%(횡보)[{grade}]"
            return base

        # Step 3: 반등 확인 (3개 중 2개+) — 기존 그대로
        bounce_signals = 0
        bounce_details = []

        if current['rsi'] > prev['rsi']:
            bounce_signals += 1
            bounce_details.append(f"RSI↑{current['rsi']:.0f}")

        srsi_k = current['srsi_k']
        srsi_d = current['srsi_d']
        if srsi_k > srsi_d or srsi_k > prev['srsi_k']:
            bounce_signals += 1
            detail = "K>D" if srsi_k > srsi_d else "K↑"
            bounce_details.append(f"SRSI_{detail}")

        if current['is_bull']:
            bounce_signals += 1
            bounce_details.append("양봉")

        if bounce_signals < BUY_BOUNCE_MIN:
            detail_str = '+'.join(bounce_details) if bounce_details else '없음'
            base['reason'] = f"반등부족({bounce_signals}/{BUY_BOUNCE_MIN}) [{detail_str}]"
            return base

        # 매수 확정
        detail_str = '+'.join(bounce_details)
        return {
            'signal': True,
            'reason': f"[{grade}]BB{bb_pos:.0f}% 폭{bb_width:.1f}% | {detail_str} | {daily_reason}",
            'entry_price': current['close'],
            'bb_position': bb_pos,
            'bb_width_pct': bb_width,
            'market_grade': grade,          # ★ 등급 기록
        }

    except Exception as e:
        if DEBUG_MODE:
            print(f"{Colors.RED}[Buy Signal] {ticker} 오류: {e}{Colors.ENDC}")
            traceback.print_exc()
        return {'signal': False, 'reason': f'오류: {e}',
                'entry_price': 0, 'bb_position': 50, 'bb_width_pct': 0}


# ============================================================================
# SECTION 14: ★ 매도 신호 (핵심 - v24.0 전략 100% 유지)
# ============================================================================

def sell_signal(df, buy_price, buy_time=None, held_info=None):
    """
    ★ 매도 신호 - 4단계 간결 로직 (v24.0 100% 동일)
    Step 1: 손절 → 즉시 매도
    Step 2: 강제 익절 → 즉시 매도
    Step 3: 안전 익절 (RSI↓ AND BB≥min%) → 매도
    Step 4: 트레일링 → 매도

    ★ v25.0: 매수 당시 파라미터 스냅샷 우선 사용 (진입 후 등급 변경 무관)
    """
    try:
        if df is None or len(df) < 5:
            return {'signal': False, 'reason': '데이터 부족',
                    'exit_price': 0, 'profit_pct': 0, 'bb_position': 50, 'bb_width_pct': 0}

        current = df.iloc[-1]
        prev = df.iloc[-2]
        current_price = current['close']
        profit_pct = ((current_price - buy_price) / buy_price) * 100
        bb_pos = current['bb_position']
        bb_width = current['bb_width']

        # ★ 파라미터 결정: 매수 당시 스냅샷 우선 → 현재 등급 → 기본값
        if held_info and 'param_snapshot' in held_info:
            p = held_info['param_snapshot']
            grade_str = held_info.get('market_grade', '?')
        else:
            grade_str = current_market_grade
            p = get_grade_params(grade_str)

        _stop_loss        = p.get('SELL_STOP_LOSS',        SELL_STOP_LOSS)
        _force_profit     = p.get('SELL_FORCE_PROFIT',     SELL_FORCE_PROFIT)
        _safe_profit      = p.get('SELL_SAFE_PROFIT',      SELL_SAFE_PROFIT)
        _safe_bb_min      = p.get('SELL_SAFE_BB_MIN',      SELL_SAFE_BB_MIN)
        _trail_activation = p.get('SELL_TRAIL_ACTIVATION', SELL_TRAIL_ACTIVATION)
        _trail_distance   = p.get('SELL_TRAIL_DISTANCE',   SELL_TRAIL_DISTANCE)
        _min_hold_sec     = p.get('BUY_MIN_HOLD_SEC',      BUY_MIN_HOLD_SEC)

        base = {
            'signal': False, 'exit_price': current_price,
            'profit_pct': profit_pct, 'bb_position': bb_pos,
            'bb_width_pct': bb_width, 'reason': ''
        }

        # 최소 보유 시간 (손절 제외)
        min_hold_active = False
        elapsed_sec = 0
        if buy_time:
            elapsed_sec = (datetime.now() - buy_time).total_seconds()
            if elapsed_sec < _min_hold_sec:
                min_hold_active = True

        # Step 1: 손절 (최소 보유 무시)
        if profit_pct <= _stop_loss:
            return {**base, 'signal': True,
                    'reason': f'손절({profit_pct:.2f}%≤{_stop_loss}%)[{grade_str}]'}

        # 최소 보유 시간 중 나머지 스킵
        if min_hold_active:
            remaining = int((_min_hold_sec - elapsed_sec) / 60) + 1
            base['reason'] = f'최소보유 대기({remaining}분, 수익{profit_pct:.2f}%)'
            return base

        # Step 2: 강제 익절
        if profit_pct >= _force_profit:
            return {**base, 'signal': True,
                    'reason': f'강제익절({profit_pct:.2f}%≥{_force_profit}%)[{grade_str}]'}

        # Step 3: 안전 익절
        if profit_pct >= _safe_profit:
            rsi_dropping = current['rsi'] < prev['rsi']
            bb_high = bb_pos >= _safe_bb_min
            if rsi_dropping and bb_high:
                reasons = [f"RSI↓{current['rsi']:.0f}", f"BB{bb_pos:.0f}%≥{_safe_bb_min}%"]
                return {**base, 'signal': True,
                        'reason': f'안전익절({profit_pct:.2f}%, {"+".join(reasons)})[{grade_str}]'}

        # Step 4: 트레일링
        if profit_pct >= _trail_activation and held_info:
            peak_price = held_info.get('peak_price', buy_price)
            if peak_price > 0:
                drawdown = (peak_price - current_price) / peak_price * 100
                if drawdown >= _trail_distance:
                    peak_profit = ((peak_price - buy_price) / buy_price) * 100
                    return {**base, 'signal': True,
                            'reason': (f'트레일링(고점{peak_profit:.1f}%→{profit_pct:.1f}%, '
                                       f'-{drawdown:.1f}%≥{_trail_distance}%)[{grade_str}]')}

        # 홀드
        trail_info = ""
        if profit_pct > 0 and held_info:
            peak_price = held_info.get('peak_price', buy_price)
            peak_profit = ((peak_price - buy_price) / buy_price) * 100
            trail_info = f" | 고점{peak_profit:.1f}%"
        base['reason'] = f'홀드(수익{profit_pct:.2f}%, BB{bb_pos:.0f}%{trail_info})[{grade_str}]'
        return base

    except Exception as e:
        if DEBUG_MODE:
            print(f"{Colors.RED}[Sell Signal] 오류: {e}{Colors.ENDC}")
            traceback.print_exc()
        return {'signal': False, 'reason': f'오류: {e}',
                'exit_price': 0, 'profit_pct': 0, 'bb_position': 50, 'bb_width_pct': 0}


# ============================================================================
# SECTION 15: 거래소 동기화
# ============================================================================

def sync_held_coins_with_exchange():
    """[복원] 봇 시작 시 거래소 보유량 동기화 + 상세 Discord 경고"""
    global held_coins
    print(f"\n{Colors.CYAN}{'='*50}")
    print(f"[Init] 기존 보유 코인 동기화 시작...")
    print(f"{'='*50}{Colors.ENDC}")

    try:
        balances = upbit.get_balances()
        synced_count = 0
        unmanaged_coins = []

        managed_tickers = set(FIXED_STABLE_COINS)

        if balances:
            for bal in balances:
                currency = bal.get('currency', '')
                if currency == 'KRW':
                    continue
                balance = float(bal.get('balance', 0))
                if balance <= 0:
                    continue

                ticker = f"KRW-{currency}"
                avg_price = float(bal.get('avg_buy_price', 0))
                current_price = get_current_price(ticker)
                is_managed = ticker in managed_tickers

                if not is_managed:
                    coin_value = balance * current_price if current_price else 0
                    unmanaged_coins.append(f"  - {currency}: {balance:.4f}개 ({coin_value:,.0f}원)")

                if avg_price > 0 and (is_managed or (current_price and balance * current_price > 5000)):
                    peak = max(avg_price, current_price) if current_price else avg_price
                    with held_coins_lock:
                        held_coins[ticker] = {
                            'buy_price': avg_price,
                            'buy_time': datetime.now() - timedelta(hours=1),
                            'buy_amount': balance * avg_price,
                            'peak_price': peak,
                            'peak_time': datetime.now(),
                            'buy_reason': '동기화 (봇 시작 전 매수)',
                            'ticker': ticker,
                            'managed': is_managed,
                        }
                    profit = ((current_price - avg_price) / avg_price * 100) if current_price and avg_price > 0 else 0
                    managed_tag = "✅" if is_managed else "⚠️비관리"
                    print(f"  {managed_tag} {currency}: {balance:.4f}개 @ {avg_price:,.0f}원"
                          f" (현재 {current_price:,.0f}원, {profit:+.2f}%)")
                    synced_count += 1

        print(f"{Colors.GREEN}[Init] 동기화 완료: {synced_count}개 코인{Colors.ENDC}\n")

        # [복원] Discord 동기화 알림 (경고 포함)
        if synced_count > 0:
            sync_msg = f"""
⚙️ **보유 코인 동기화**

**동기화:** `{synced_count}개 코인`

동기화된 {synced_count}개 코인은 봇 시작 **이전**에 매수된 코인입니다.

**주의사항:**
1. 보유 시간이 부정확할 수 있습니다.
2. 가능하면 수동 매도 후 봇이 새로 매수하도록 권장합니다.

⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
"""
            send_discord_message(sync_msg)

        if unmanaged_coins:
            print(f"{Colors.YELLOW}[Init] 비관리 코인 (고정 7개 외):{Colors.ENDC}")
            for line in unmanaged_coins:
                print(f"{Colors.YELLOW}{line}{Colors.ENDC}")

        return True

    except Exception as e:
        print(f"{Colors.RED}[Init Error] 동기화 실패: {e}{Colors.ENDC}")
        traceback.print_exc()
        send_error_notification("Sync Failed", str(e))
        return False


# ============================================================================
# SECTION 16: 거래 실행 함수 (상세 로그 + 안전장치 복원)
# ============================================================================

def execute_buy(ticker, signal):
    """[복원] 매수 실행 - 상세 로그 + 에러 처리"""
    global daily_trade_count, total_trades, daily_buy_count

    try:
        with trade_lock:
            reset_daily_counter()

            if daily_trade_count >= MAX_DAILY_TRADES:
                print(f"{Colors.YELLOW}[Buy Limit] 일일 거래 한도 도달{Colors.ENDC}")
                return False

            can_enter, msg = check_reentry_cooldown(ticker)
            if not can_enter:
                print(f"{Colors.YELLOW}[Buy Limit] {msg}{Colors.ENDC}")
                return False

            # 최소 가격 필터
            entry_price = signal.get('entry_price', 0)
            if entry_price < MIN_BUY_PRICE:
                coin_name = ticker.replace('KRW-', '')
                print(f"{Colors.YELLOW}[Buy Block] {coin_name}: {entry_price:,.0f}원 < 최소 {MIN_BUY_PRICE:,}원{Colors.ENDC}")
                return False

            with held_coins_lock:
                if ticker in held_coins:
                    return False
                managed_count = sum(1 for info in held_coins.values() if info.get('managed', True))
                if managed_count >= MAX_HOLDINGS:
                    return False
                current_holding_count = managed_count

            # KRW 잔고 확인
            try:
                krw_balance = upbit.get_balance("KRW") or 0
            except Exception as e:
                print(f"{Colors.RED}[Buy Failed] KRW 잔고 조회 실패: {e}{Colors.ENDC}")
                return False

            if krw_balance < 5000:
                print(f"{Colors.YELLOW}[Buy Skip] 가용 현금 부족 ({krw_balance:,.0f}원 < 5,000원){Colors.ENDC}")
                return False

            # 총 자산 (로그용)
            total_assets = get_total_balance() or krw_balance

            # 포지션 사이징
            if current_holding_count == 0:
                buy_amount = krw_balance * FIRST_BUY_RATIO * BUY_FEE_BUFFER
                buy_order = '1차'
                buy_order_num = 1
            else:
                buy_amount = krw_balance * BUY_FEE_BUFFER
                buy_order = '2차'
                buy_order_num = 2

            if buy_amount < 5000:
                print(f"{Colors.YELLOW}[Buy Limit] 매수 금액 부족 ({buy_amount:,.0f}원 < 5,000원){Colors.ENDC}")
                return False

            coin_name = ticker.replace('KRW-', '')
            coin_value = total_assets - krw_balance

            # [복원] 상세 포지션 사이징 로그
            print(f"{Colors.CYAN}[Buy Info] 총자산: {total_assets:,.0f}원"
                  f" (코인: {coin_value:,.0f}원 + 현금: {krw_balance:,.0f}원){Colors.ENDC}")
            if current_holding_count == 0:
                print(f"{Colors.CYAN}[Buy Info] {buy_order}매수 | "
                      f"현금{krw_balance:,.0f} × {FIRST_BUY_RATIO:.0%} × {BUY_FEE_BUFFER} = "
                      f"{buy_amount:,.0f}원{Colors.ENDC}")
            else:
                print(f"{Colors.CYAN}[Buy Info] {buy_order}매수 | "
                      f"잔여현금{krw_balance:,.0f} × {BUY_FEE_BUFFER} = {buy_amount:,.0f}원{Colors.ENDC}")

            # ── TEST MODE ──
            if TEST_MODE:
                print(f"{Colors.GREEN}[TEST] {buy_order}매수 시뮬레이션: {coin_name} {buy_amount:,.0f}원{Colors.ENDC}")
                with held_coins_lock:
                    held_coins[ticker] = {
                        'buy_price': signal['entry_price'],
                        'buy_time': datetime.now(),
                        'buy_amount': buy_amount,
                        'peak_price': signal['entry_price'],
                        'peak_time': datetime.now(),
                        'buy_reason': signal['reason'],
                        'ticker': ticker,
                        'buy_order': buy_order_num,
                        'managed': True,
                        # ★ v25.0: 매수 당시 등급+파라미터 스냅샷
                        'market_grade': signal.get('market_grade', current_market_grade),
                        'param_snapshot': get_grade_params(),
                    }
                daily_trade_count += 1
                daily_buy_count += 1
                total_trades += 1
                send_buy_notification(ticker, signal, buy_amount, total_assets)
                return True

            # ── LIVE MODE ──
            try:
                final_krw = upbit.get_balance("KRW")
                if final_krw is None or final_krw < buy_amount:
                    if final_krw and final_krw >= 5000:
                        buy_amount = final_krw * BUY_FEE_BUFFER
                        print(f"{Colors.CYAN}[Buy Info] 잔고 재조정: {buy_amount:,.0f}원{Colors.ENDC}")
                    else:
                        print(f"{Colors.RED}[Buy Failed] 매수 직전 잔고 부족{Colors.ENDC}")
                        return False

                result = upbit.buy_market_order(ticker, buy_amount)
                if result is None:
                    print(f"{Colors.RED}[Buy Failed] 주문 실패 (API 응답 없음){Colors.ENDC}")
                    return False
                if isinstance(result, dict) and 'error' in result:
                    error_info = result.get('error', {})
                    print(f"{Colors.RED}[Buy Failed] API 오류: "
                          f"{error_info.get('name')} - {error_info.get('message')}{Colors.ENDC}")
                    return False

                order_uuid = result.get('uuid', '')
                actual_buy_price = signal['entry_price']

                if order_uuid:
                    time.sleep(0.5)
                    order_detail = upbit.wait_order_filled(order_uuid, timeout_sec=5)
                    if order_detail and order_detail['avg_price'] > 0:
                        actual_buy_price = order_detail['avg_price']
                        paid_fee = order_detail['paid_fee']
                        print(f"{Colors.CYAN}[Buy Detail] 체결가: {actual_buy_price:,.0f}원 | "
                              f"수수료: {paid_fee:,.0f}원{Colors.ENDC}")
                    else:
                        time.sleep(0.5)
                        balances = upbit.get_balances()
                        if balances:
                            for bal in balances:
                                if bal['currency'] == ticker.split('-')[1]:
                                    actual_buy_price = float(bal['avg_buy_price'])
                                    break
                else:
                    time.sleep(1)
                    balances = upbit.get_balances()
                    if balances:
                        for bal in balances:
                            if bal['currency'] == ticker.split('-')[1]:
                                actual_buy_price = float(bal['avg_buy_price'])
                                break

                with held_coins_lock:
                    held_coins[ticker] = {
                        'buy_price': actual_buy_price,
                        'buy_time': datetime.now(),
                        'buy_amount': buy_amount,
                        'peak_price': actual_buy_price,
                        'peak_time': datetime.now(),
                        'buy_reason': signal['reason'],
                        'ticker': ticker,
                        'buy_order': buy_order_num,
                        'order_uuid': order_uuid,
                        'managed': True,
                        # ★ v25.0: 매수 당시 등급+파라미터 스냅샷
                        'market_grade': signal.get('market_grade', current_market_grade),
                        'param_snapshot': get_grade_params(),
                    }

                daily_trade_count += 1
                daily_buy_count += 1
                total_trades += 1

                print(f"{Colors.GREEN}[Buy Success] {buy_order}매수 {coin_name} @ "
                      f"{actual_buy_price:,.0f}원 (투자액: {buy_amount:,.0f}원){Colors.ENDC}")
                send_buy_notification(ticker, signal, buy_amount, total_assets)
                return True

            except Exception as e:
                error_str = str(e)
                print(f"{Colors.RED}[Buy Failed] 주문 실행 오류: {error_str}{Colors.ENDC}")
                # [복원] InsufficientFunds 상세 처리
                if 'InsufficientFunds' in error_str or 'insufficient' in error_str.lower():
                    print(f"{Colors.YELLOW}  └ 원인: 주문 금액이 가용 잔고를 초과{Colors.ENDC}")
                    try:
                        cur_krw = upbit.get_balance("KRW")
                        print(f"{Colors.YELLOW}  └ 현재 잔고: {cur_krw:,.0f}원{Colors.ENDC}")
                    except Exception:
                        pass
                send_error_notification("Buy Failed", error_str)
                return False

    except Exception as e:
        print(f"{Colors.RED}[Buy Error] {e}{Colors.ENDC}")
        traceback.print_exc()
        return False


def execute_sell(ticker, signal):
    """[복원] 매도 실행 - 수동매도 감지 + 상세 경고"""
    global daily_trade_count, total_trades, winning_trades, losing_trades, total_profit
    global consecutive_losses, last_loss_time
    global daily_sell_count, daily_winning_trades, daily_losing_trades

    try:
        with trade_lock:
            with held_coins_lock:
                if ticker not in held_coins:
                    return False
                hold_info = held_coins[ticker].copy()

            buy_price = hold_info['buy_price']
            buy_time = hold_info['buy_time']
            sell_price = signal['exit_price']
            profit_pct = ((sell_price - buy_price) / buy_price) * 100
            profit_amount = hold_info['buy_amount'] * (profit_pct / 100)
            hold_duration = format_duration(datetime.now() - buy_time)
            coin_name = ticker.replace('KRW-', '')

            # ── TEST MODE ──
            if TEST_MODE:
                print(f"{Colors.GREEN}[TEST] 매도 시뮬레이션: {coin_name} {profit_pct:+.2f}%{Colors.ENDC}")
                with held_coins_lock:
                    if ticker in held_coins:
                        del held_coins[ticker]
                recent_sells[ticker] = {'time': datetime.now(), 'reason': signal['reason']}
                with statistics_lock:
                    total_profit += profit_pct
                    if profit_pct > 0:
                        winning_trades += 1
                        daily_winning_trades += 1
                        consecutive_losses = 0
                    else:
                        losing_trades += 1
                        daily_losing_trades += 1
                        consecutive_losses += 1
                        last_loss_time = datetime.now()
                daily_trade_count += 1
                daily_sell_count += 1
                send_sell_notification(ticker, hold_info, signal, profit_amount, hold_duration)
                return True

            # ── LIVE MODE ──
            try:
                balances = upbit.get_balances()
                coin_balance = None
                for bal in balances:
                    if bal['currency'] == ticker.split('-')[1]:
                        coin_balance = bal
                        break

                # [복원] 잔고 없음 → 수동매도 감지 + 상세 Discord 경고
                if not coin_balance:
                    with held_coins_lock:
                        if ticker in held_coins:
                            del held_coins[ticker]
                    warning_msg = f"""
⚠️ **매도 실패 - 수동 매도 추정**

**코인:** `{coin_name}`
**원인:** 잔고 없음 (Upbit에서 수동 매도한 것으로 추정)

**자동 조치:**
- `held_coins`에서 자동 제거
- 봇 관리 대상에서 제외

⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
"""
                    send_discord_message(warning_msg)
                    print(f"{Colors.YELLOW}[Sync] {coin_name} 잔고 없음 → held_coins 제거{Colors.ENDC}")
                    return False

                coin_amount = float(coin_balance.get('balance', 0))

                # [복원] 잔고 0 처리
                if coin_amount <= 0:
                    with held_coins_lock:
                        if ticker in held_coins:
                            del held_coins[ticker]
                    send_discord_message(f"\n⚠️ **{coin_name} 잔고 0** → 자동 제거\n")
                    return False

                result = upbit.sell_market_order(ticker, coin_amount)
                if result is None:
                    print(f"{Colors.RED}[Sell Failed] {coin_name} 주문 실패{Colors.ENDC}")
                    return False

                sell_uuid = result.get('uuid', '')
                actual_sell_price = sell_price

                # [복원] 체결가/수수료 상세 로그
                if sell_uuid:
                    time.sleep(0.5)
                    order_detail = upbit.wait_order_filled(sell_uuid, timeout_sec=5)
                    if order_detail and order_detail['avg_price'] > 0:
                        actual_sell_price = order_detail['avg_price']
                        paid_fee = order_detail['paid_fee']
                        print(f"{Colors.CYAN}[Sell Detail] 체결가: {actual_sell_price:,.0f}원 | "
                              f"수수료: {paid_fee:,.0f}원{Colors.ENDC}")

                actual_profit_pct = ((actual_sell_price - buy_price) / buy_price) * 100
                actual_profit_amount = hold_info['buy_amount'] * (actual_profit_pct / 100)

                with held_coins_lock:
                    if ticker in held_coins:
                        del held_coins[ticker]

                recent_sells[ticker] = {'time': datetime.now(), 'reason': signal['reason']}

                with statistics_lock:
                    total_profit += actual_profit_pct
                    if actual_profit_pct > 0:
                        winning_trades += 1
                        daily_winning_trades += 1
                        consecutive_losses = 0
                    else:
                        losing_trades += 1
                        daily_losing_trades += 1
                        consecutive_losses += 1
                        last_loss_time = datetime.now()

                daily_trade_count += 1
                daily_sell_count += 1

                print(f"{Colors.GREEN}[Sell Success] {coin_name} {actual_profit_pct:+.2f}%{Colors.ENDC}")
                signal['profit_pct'] = actual_profit_pct
                signal['exit_price'] = actual_sell_price
                send_sell_notification(ticker, hold_info, signal, actual_profit_amount, hold_duration)
                return True

            except Exception as e:
                error_str = str(e)
                print(f"{Colors.RED}[Sell Failed] {coin_name}: {error_str}{Colors.ENDC}")
                # [복원] 잔고 부족 오류별 처리
                if 'insufficient' in error_str.lower() or 'balance' in error_str.lower():
                    print(f"{Colors.YELLOW}[Sync] {coin_name} 잔고 부족 오류 → held_coins 제거{Colors.ENDC}")
                    with held_coins_lock:
                        if ticker in held_coins:
                            del held_coins[ticker]
                    send_discord_message(
                        f"\n⚠️ **매도 실패 - 잔고 부족**\n\n"
                        f"**코인:** `{coin_name}`\n**오류:** `{error_str}`\n"
                        f"**조치:** held_coins 자동 제거\n\n"
                        f"⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
                    )
                    return False
                send_error_notification("Sell Failed", error_str)
                return False

    except Exception as e:
        print(f"{Colors.RED}[Sell Error] {e}{Colors.ENDC}")
        traceback.print_exc()
        return False


# ============================================================================
# SECTION 17: 매수 스레드 (리스크 관리 복원)
# ============================================================================

def buy_thread_worker():
    """[복원] Thread 1: 매수 스레드 - 시장감시 + 시간대차단 + 상세로그"""
    print(f"{Colors.GREEN}[Thread 1] 매수 스레드 시작 ({BUY_THREAD_INTERVAL}초 주기){Colors.ENDC}")
    print(f"{Colors.GREEN}  ├ 매수차단: {BUY_BLOCK_START_HOUR:02d}:{BUY_BLOCK_START_MINUTE:02d}"
          f"~{BUY_BLOCK_END_HOUR:02d}:{BUY_BLOCK_END_MINUTE:02d}{Colors.ENDC}")
    print(f"{Colors.GREEN}  └ BB≤{BUY_BB_MAX}% 폭≥{BUY_BB_WIDTH_MIN}% 반등≥{BUY_BOUNCE_MIN}개{Colors.ENDC}")

    iteration = 0

    while not stop_event.is_set():
        try:
            iteration += 1

            # ① 보유수 체크 (API 호출 0건)
            with held_coins_lock:
                managed_count = sum(1 for info in held_coins.values() if info.get('managed', True))
            if managed_count >= MAX_HOLDINGS:
                if DEBUG_MODE and iteration % 30 == 0:
                    print(f"{Colors.YELLOW}[BUY] 최대 보유 도달 ({managed_count}/{MAX_HOLDINGS}){Colors.ENDC}")
                time.sleep(BUY_SLEEP_WHEN_FULL)
                continue

            # ② [복원] 매수 차단 시간대 (업비트 정산)
            now = datetime.now()
            block_start = now.replace(hour=BUY_BLOCK_START_HOUR, minute=BUY_BLOCK_START_MINUTE, second=0)
            block_end = now.replace(hour=BUY_BLOCK_END_HOUR, minute=BUY_BLOCK_END_MINUTE, second=0)
            if block_start <= now <= block_end:
                if DEBUG_MODE and iteration % 30 == 0:
                    print(f"{Colors.YELLOW}[BUY] 매수 차단 시간대 ({now.strftime('%H:%M')}){Colors.ENDC}")
                time.sleep(BUY_THREAD_INTERVAL)
                continue

            # ③ 연속 손실 쿨다운
            can_trade, loss_msg = check_consecutive_losses()
            if not can_trade:
                if DEBUG_MODE and iteration % 10 == 0:
                    print(f"{Colors.YELLOW}[BUY] {loss_msg}{Colors.ENDC}")
                time.sleep(BUY_THREAD_INTERVAL)
                continue

            # ④ [복원] 시장 급락 감지
            market_ok, market_change = check_market_condition()
            if not market_ok:
                if DEBUG_MODE and iteration % 10 == 0:
                    print(f"{Colors.YELLOW}[BUY] 시장 불안정 ({market_change:.2f}%){Colors.ENDC}")
                time.sleep(BUY_THREAD_INTERVAL)
                continue

            # ⑤ [복원] 일일 거래 한도
            if not check_daily_trade_limit():
                if DEBUG_MODE and iteration % 30 == 0:
                    print(f"{Colors.YELLOW}[BUY] 일일 거래 한도 도달{Colors.ENDC}")
                time.sleep(BUY_THREAD_INTERVAL)
                continue

            reset_daily_counter()

            # ⑥ ★ v25.0: 시장 등급 갱신 (매 스캔마다 BBW 기반 업데이트)
            update_market_grade()
            if DEBUG_MODE and iteration % 6 == 0:  # 약 60초마다 출력
                print(f"{Colors.MAGENTA}[BUY] {get_grade_display_str()}{Colors.ENDC}")

            # ⑦ 코인별 매수 검토
            for ticker in FIXED_STABLE_COINS:
                if stop_event.is_set():
                    return

                with held_coins_lock:
                    if ticker in held_coins:
                        continue

                can_enter, cooldown_reason = check_reentry_cooldown(ticker)
                if not can_enter:
                    continue

                sig = buy_signal(ticker)

                if sig['signal']:
                    coin_name = ticker.replace('KRW-', '')
                    # [복원] 매수 시그널 상세 박스
                    print(f"\n{Colors.CYAN}{'='*50}")
                    print(f"[BUY SIGNAL] {coin_name} 매수!")
                    print(f"{'='*50}{Colors.ENDC}")
                    print(f"  📊 BB 위치: {sig['bb_position']:.1f}%")
                    print(f"  📐 BB 폭: {sig['bb_width_pct']:.1f}%")
                    print(f"  💰 진입가: {sig['entry_price']:,.0f}원")
                    print(f"  📝 사유: {sig['reason']}")
                    print(f"{Colors.CYAN}{'='*50}{Colors.ENDC}\n")

                    success = execute_buy(ticker, sig)
                    if success:
                        print(f"{Colors.GREEN}[BUY] {coin_name} 매수 완료!{Colors.ENDC}")
                    else:
                        print(f"{Colors.RED}[BUY] {coin_name} 매수 실패{Colors.ENDC}")
                    time.sleep(2)

                    # 보유수 재확인
                    with held_coins_lock:
                        mc = sum(1 for v in held_coins.values() if v.get('managed', True))
                        if mc >= MAX_HOLDINGS:
                            break

                time.sleep(0.3)

            time.sleep(BUY_THREAD_INTERVAL)

        except Exception as e:
            error_trace = traceback.format_exc()
            print(f"{Colors.RED}[Buy Thread Error] {e}{Colors.ENDC}")
            if DEBUG_MODE:
                print(error_trace)
            # [복원] 네트워크 오류 30초 대기
            if "RemoteDisconnected" in str(e) or "Connection" in str(e):
                time.sleep(30)
            else:
                time.sleep(BUY_THREAD_INTERVAL)

    print(f"{Colors.GREEN}[Thread 1] 매수 스레드 종료{Colors.ENDC}")


# ============================================================================
# SECTION 18: 매도 스레드 (peak 추적 + 상세 로그 복원)
# ============================================================================

def sell_thread_worker():
    """[복원] Thread 2: 매도 스레드 - peak 추적 + 상세 시그널 박스"""
    print(f"{Colors.YELLOW}[Thread 2] 매도 스레드 시작 ({SELL_THREAD_INTERVAL}초 주기){Colors.ENDC}")

    iteration = 0

    while not stop_event.is_set():
        try:
            iteration += 1

            with held_coins_lock:
                tickers = list(held_coins.keys())

            if not tickers:
                if DEBUG_MODE and iteration % 60 == 0:
                    print(f"{Colors.YELLOW}[SELL] 보유 종목 없음{Colors.ENDC}")
                time.sleep(SELL_THREAD_INTERVAL)
                continue

            for ticker in tickers:
                if stop_event.is_set():
                    return

                # 데이터 수집
                df = get_candles_15m(ticker, count=50)
                if df is None or len(df) < 20:
                    continue

                current_price = df.iloc[-1]['close']

                # [복원] 매도 스레드에서 peak_price 실시간 갱신 + 로그
                with held_coins_lock:
                    if ticker not in held_coins:
                        continue
                    held_info = held_coins[ticker]
                    buy_price = held_info['buy_price']
                    buy_time = held_info.get('buy_time')

                    current_peak = held_info.get('peak_price', buy_price)
                    if current_price > current_peak:
                        held_info['peak_price'] = current_price
                        held_info['peak_time'] = datetime.now()
                        if DEBUG_MODE:
                            coin_name = ticker.replace('KRW-', '')
                            old_pft = ((current_peak - buy_price) / buy_price) * 100
                            new_pft = ((current_price - buy_price) / buy_price) * 100
                            print(f"{Colors.GREEN}[SELL] {coin_name} 신고가 갱신: "
                                  f"{current_price:,.0f}원 ({old_pft:+.1f}%→{new_pft:+.1f}%){Colors.ENDC}")

                    held_info_copy = held_info.copy()

                # 매도 신호 판단
                sig = sell_signal(df, buy_price, buy_time, held_info_copy)

                # peak_price 동기화 (sell_signal 내에서 갱신될 수 있음)
                with held_coins_lock:
                    if ticker in held_coins:
                        for key in ['peak_price', 'peak_time']:
                            if key in held_info_copy:
                                held_coins[ticker][key] = held_info_copy[key]

                if sig['signal']:
                    profit_pct = sig['profit_pct']
                    coin_name = ticker.replace('KRW-', '')
                    color = Colors.GREEN if profit_pct >= 0 else Colors.RED
                    emoji = "📈" if profit_pct >= 0 else "📉"

                    # [복원] 매도 시그널 상세 박스
                    print(f"\n{color}{'='*50}")
                    print(f"[SELL SIGNAL] {coin_name} 매도!")
                    print(f"{'='*50}{Colors.ENDC}")
                    print(f"  {emoji} 수익률: {profit_pct:+.2f}%")
                    print(f"  📊 BB 위치: {sig['bb_position']:.1f}%")
                    print(f"  💰 매도가: {sig['exit_price']:,.0f}원")
                    print(f"  🔍 사유: {sig['reason']}")
                    if buy_time:
                        dur = format_duration(datetime.now() - buy_time)
                        print(f"  ⏱️ 보유시간: {dur}")
                    peak_price = held_info_copy.get('peak_price', buy_price)
                    if peak_price > buy_price:
                        peak_profit = ((peak_price - buy_price) / buy_price) * 100
                        drawdown = ((peak_price - sig['exit_price']) / peak_price) * 100
                        print(f"  🏔️ 고점: {peak_price:,.0f}원 (+{peak_profit:.2f}%), 현재 -{drawdown:.1f}%")
                    print(f"{color}{'='*50}{Colors.ENDC}\n")

                    success = execute_sell(ticker, sig)
                    if success:
                        print(f"{color}[SELL] {coin_name} 매도 완료! ({profit_pct:+.2f}%){Colors.ENDC}")
                    else:
                        print(f"{Colors.RED}[SELL] {coin_name} 매도 실패{Colors.ENDC}")
                    time.sleep(2)

                else:
                    # 주기적 홀드 로그
                    if DEBUG_MODE and iteration % 60 == 0:
                        profit_pct = sig['profit_pct']
                        coin_name = ticker.replace('KRW-', '')
                        print(f"{Colors.CYAN}[SELL] {coin_name}: {profit_pct:+.2f}%,"
                              f" BB:{sig['bb_position']:.0f}%, {sig['reason']}{Colors.ENDC}")

                time.sleep(0.3)

            time.sleep(SELL_THREAD_INTERVAL)

        except Exception as e:
            error_trace = traceback.format_exc()
            print(f"{Colors.RED}[Sell Thread Error] {e}{Colors.ENDC}")
            if DEBUG_MODE:
                print(error_trace)
            # [복원] 크리티컬 에러 Discord
            if 'critical' in str(e).lower() or 'fatal' in str(e).lower():
                send_error_notification("SELL Thread Critical Error", error_trace[:500])
            time.sleep(SELL_THREAD_INTERVAL)

    print(f"{Colors.YELLOW}[Thread 2] 매도 스레드 종료{Colors.ENDC}")


# ============================================================================
# SECTION 19: 모니터 스레드 + 매시간 상세 보고 (복원)
# ============================================================================

def send_enhanced_statistics_report():
    """[복원] 매시각 상세 보고서 - 시장모멘텀+코인미니맵+보유상세+관심코인"""
    try:
        portfolio = get_enhanced_portfolio_status()
        now = datetime.now()

        # ① 자산 요약
        cpft = 0.0
        if portfolio['coins']:
            tb = sum(c.get('buy_price', 0) * c.get('balance', 0)
                     for c in portfolio['coins'] if c.get('buy_price', 0) > 0)
            if tb > 0:
                cpft = ((portfolio['total_coin_value'] - tb) / tb) * 100

        header = (
            f"⏰ **{now.strftime('%H:%M')}** 정시보고\n"
            f"💰 `{portfolio['total_assets']:,.0f}원` "
            f"(코인`{portfolio['total_coin_value']:,.0f}`{cpft:+.1f}% "
            f"현금`{portfolio['krw_balance']:,.0f}`)\n"
            f"{get_grade_display_str()}"
        )

        # ② 시장 모멘텀 + 7코인 미니맵
        mkt_score = 0
        coin_changes = {}
        coin_is_bullish = {}
        coin_bb_widths = []
        ema_up = 0
        valid = 0

        for tk in FIXED_STABLE_COINS:
            try:
                df_d = get_candles_daily(tk, count=5)
                if df_d is None or len(df_d) < 1:
                    continue
                d = df_d.iloc[-1]
                if d['open'] <= 0:
                    continue
                chg = (d['close'] - d['open']) / d['open'] * 100
                coin_changes[tk] = chg
                coin_is_bullish[tk] = d['close'] >= d['open']
                valid += 1
                df_t = get_candles_15m(tk, count=25)
                if df_t is not None and len(df_t) >= 20:
                    coin_bb_widths.append(df_t.iloc[-1].get('bb_width', 2.0))
                    if df_t.iloc[-1]['close'] > df_t.iloc[-1].get('bb_mid', 0) > 0:
                        ema_up += 1
            except Exception:
                continue

        daily_avg = sum(coin_changes.values()) / len(coin_changes) if coin_changes else 0
        pos_count = sum(1 for v in coin_is_bullish.values() if v)
        avg_bbw = sum(coin_bb_widths) / len(coin_bb_widths) if coin_bb_widths else 2.0

        if daily_avg > 1.0: mkt_score += 2
        elif daily_avg > 0: mkt_score += 1
        elif daily_avg > -1.0: pass
        elif daily_avg > -2.0: mkt_score -= 1
        else: mkt_score -= 2
        if pos_count >= 5: mkt_score += 2
        elif pos_count >= 3: mkt_score += 1
        elif pos_count <= 1: mkt_score -= 1
        if avg_bbw > 3.0: mkt_score += 1
        elif avg_bbw < 1.5: mkt_score -= 1
        if valid > 0 and ema_up >= 4: mkt_score += 1

        if mkt_score >= 3: mkt_emoji = '🟢🟢'
        elif mkt_score >= 1: mkt_emoji = '🟢'
        elif mkt_score >= 0: mkt_emoji = '🟡'
        elif mkt_score >= -1: mkt_emoji = '🟠'
        else: mkt_emoji = '🔴'

        mkt_section = (
            f"\n\n🌡️ **시장** [{mkt_score:+d}점{mkt_emoji}] "
            f"평균`{daily_avg:+.1f}%` 양봉`{pos_count}/7` BBW`{avg_bbw:.1f}%`"
        )

        ini_map = {'KRW-ETH': 'E', 'KRW-XRP': 'X', 'KRW-SOL': 'S', 'KRW-ADA': 'A',
                    'KRW-LINK': 'L', 'KRW-BCH': 'B', 'KRW-SUI': 'U'}
        parts = []
        for tk in FIXED_STABLE_COINS:
            i = ini_map.get(tk, '?')
            c = coin_changes.get(tk, 0)
            e = '🟢' if coin_is_bullish.get(tk, False) else '🔴'
            parts.append(f"{e}{i}{c:+.1f}")
        mkt_section += f"\n`{'  '.join(parts)}`"

        # ③ 보유 코인 상세
        hs = set()
        with held_coins_lock:
            hs = set(held_coins.keys())

        hold_section = ""
        if portfolio['coins']:
            hold_section = f"\n\n📦 **보유 {len(portfolio['coins'])}/{MAX_HOLDINGS}**"
            for ci in portfolio['coins']:
                tk = ci['ticker']
                cn = tk.replace('KRW-', '')
                buy_p = ci.get('buy_price', 0)
                cur_p = ci.get('current_price', 0)
                bal = ci.get('balance', 0)
                pft = ci.get('profit_pct', 0)
                pft_amt = (cur_p - buy_p) * bal if buy_p > 0 else 0
                price_str = format_price_compact(cur_p)
                pft_str = format_profit_amount(pft_amt)

                dur = "-"
                peak_drop = 0.0
                with held_coins_lock:
                    if tk in held_coins:
                        bt = held_coins[tk].get('buy_time')
                        if bt:
                            dur = format_duration(now - bt)
                        pk = held_coins[tk].get('peak_price', cur_p)
                        if pk and pk > 0 and cur_p > 0:
                            peak_drop = ((cur_p - pk) / pk) * 100

                st = calculate_coin_status_for_report(tk)
                pe = "📈" if pft >= 0 else "📉"
                pk_str = f"피크{peak_drop:+.1f}%" if peak_drop < -0.1 else "피크유지"

                hold_section += (
                    f"\n┌ **{cn}** `{price_str}` "
                    f"{pe}`{pft:+.2f}%({pft_str})` ⏱{dur}"
                )
                hold_section += (
                    f"\n└ `D{st['d_change']:+.1f}% "
                    f"BB{st['bb15']:.0f} W{st['bw15']:.1f} "
                    f"R{st['rsi15']:.0f} SR{st['srsi_k']:.0f}{st['srsi_direction']} "
                    f"{pk_str}`"
                )
        else:
            hold_section = f"\n\n📦 보유 `0/{MAX_HOLDINGS}` (대기중)"

        # ④ 관심 코인
        watch_fixed = [c for c in FIXED_STABLE_COINS if c not in hs]
        watch_section = ""
        if watch_fixed:
            watch_section = f"\n\n📋 **관심 {len(watch_fixed)}개**"
            watch_section += f"\n`{'코인':>4} {'현재가':>7} {'일봉':>5} {'BB':>2} {'W':>3} {'R':>2} {'SR':>4}`"
            for tk in watch_fixed:
                cn = tk.replace('KRW-', '')
                st = calculate_coin_status_for_report(tk)
                de = '🟢' if st['is_bullish'] else '🔴'
                watch_section += (
                    f"\n{de}`{cn:>4} {st.get('cur_price_str', '-'):>7} "
                    f"{st['d_change']:+.1f}% {st['bb15']:2.0f} "
                    f"{st['bw15']:3.1f} {st['rsi15']:2.0f} "
                    f"{st['srsi_k']:2.0f}{st['srsi_direction']}`"
                )

        msg = f"\n{'─'*25}\n{header}{mkt_section}{hold_section}{watch_section}\n{'─'*25}"
        send_discord_message(msg)

    except Exception as e:
        if DEBUG_MODE:
            print(f"{Colors.RED}[Report Error] {e}{Colors.ENDC}")
            traceback.print_exc()


def monitor_thread_worker():
    """[복원] Thread 3: 모니터 스레드 - 상세 현황 출력 + 매시 보고"""
    print(f"{Colors.MAGENTA}[Thread 3] 모니터 스레드 시작 ({MONITOR_THREAD_INTERVAL}초 주기){Colors.ENDC}")

    iteration = 0
    last_report_time = datetime.now() - timedelta(hours=1)

    while not stop_event.is_set():
        try:
            iteration += 1
            current_time = datetime.now()

            with held_coins_lock:
                current_holdings = len(held_coins)
            with statistics_lock:
                win_rate = (winning_trades / total_trades * 100) if total_trades > 0 else 0
                avg_profit = (total_profit / total_trades) if total_trades > 0 else 0

            # [복원] 상세 모니터 출력
            print(f"\n{Colors.MAGENTA}{'='*10}")
            print(f"[Monitor] 반복 #{iteration} | {current_time.strftime('%H:%M:%S')}")
            print(f"  {get_grade_display_str()}")
            print(f"  보유: {current_holdings}/{MAX_HOLDINGS} | "
                  f"거래: {total_trades}회 (금일 {daily_trade_count}회) | "
                  f"승률: {win_rate:.1f}%")
            print(f"  평균 수익: {avg_profit:+.2f}%")

            with held_coins_lock:
                for ticker, info in held_coins.items():
                    try:
                        price = get_current_price(ticker)
                        if price:
                            profit = ((price - info['buy_price']) / info['buy_price']) * 100
                            duration = format_duration(current_time - info['buy_time'])
                            coin_name = ticker.replace("KRW-", "")
                            print(f"  - {coin_name}: {profit:+.2f}% ({duration})")
                    except Exception:
                        pass

            print(f"{'='*10}{Colors.ENDC}\n")

            # [복원] 매시 정각 상세 Discord 보고
            elapsed = (current_time - last_report_time).total_seconds()
            if elapsed >= 3540 and 0 <= current_time.minute <= 3:
                print(f"{Colors.GREEN}[Monitor] 정시 보고 트리거 ({current_time.strftime('%H:%M')}){Colors.ENDC}")
                send_enhanced_statistics_report()
                last_report_time = current_time

            time.sleep(MONITOR_THREAD_INTERVAL)

        except Exception as e:
            print(f"{Colors.RED}[Monitor Error] {e}{Colors.ENDC}")
            if DEBUG_MODE:
                traceback.print_exc()
            time.sleep(MONITOR_THREAD_INTERVAL)

    print(f"{Colors.MAGENTA}[Thread 3] 모니터 종료{Colors.ENDC}")


# ============================================================================
# SECTION 20: 메인 함수
# ============================================================================

def main():
    global upbit

    # 1. API 초기화
    try:
        upbit = UpbitAPI(ACCESS_KEY, SECRET_KEY)
        print(f"{Colors.GREEN}[Init] Upbit API 연결 완료{Colors.ENDC}\n")
    except Exception as e:
        print(f"{Colors.RED}[Error] API 연결 실패: {e}{Colors.ENDC}")
        return

    # 2. 보유 코인 동기화
    print(f"{Colors.CYAN}[Init] 기존 보유 코인 동기화 중...{Colors.ENDC}")
    sync_success = sync_held_coins_with_exchange()
    if not sync_success:
        print(f"{Colors.YELLOW}[Warning] 동기화 실패 - 계속 진행{Colors.ENDC}\n")

    with held_coins_lock:
        synced_coins = len(held_coins)

    # 3. WebSocket 시작
    ws_thread = threading.Thread(target=websocket_thread_worker, name="WS", daemon=True)
    ws_thread.start()
    print(f"{Colors.CYAN}[Init] WebSocket 연결 대기...{Colors.ENDC}")
    ws_wait = time.time()
    while time.time() - ws_wait < 5.0:
        with ws_status_lock:
            if ws_status['connected']:
                break
        time.sleep(0.2)

    with ws_status_lock:
        ws_ok = ws_status['connected']
        ws_sub = len(ws_status['subscribed_tickers'])

    if ws_ok:
        print(f"{Colors.GREEN}[Init] WebSocket ✅ 연결됨 ({ws_sub}개 구독){Colors.ENDC}\n")
    else:
        print(f"{Colors.YELLOW}[Init] WebSocket ⏳ 연결 중 (REST fallback){Colors.ENDC}\n")

    # 4. Discord 시작 알림
    start_msg = f"""
**🤖 봇 시작**

**버전:** `{VERSION}`
**모드:** `{'TEST MODE' if TEST_MODE else 'LIVE MODE'}`
**관심 코인:** `{len(FIXED_STABLE_COINS)}개`
**최대 보유:** `{MAX_HOLDINGS}개`
**동기화된 기존 보유:** `{synced_coins}개`
**WebSocket:** `{'✅ 연결됨' if ws_ok else '⏳ 연결 중'}`

**★ 시장 등급 시스템:**
🔴 HIGH(BBW≥4%): BB≤30% 손절-2.5% 강제+2.5%
🟡 MID (BBW2~4%): BB≤25% 손절-2.5% 강제+2.5%
🔵 LOW (BBW<2%): BB≤20% 손절-2.0% 강제+2.0%
ETH+XRP 기준 실시간 측정 (폴백: 시간대)

⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
"""
    send_discord_message(start_msg)

    # 5. 스레드 시작
    buy_t = threading.Thread(target=buy_thread_worker, name="Buy", daemon=True)
    sell_t = threading.Thread(target=sell_thread_worker, name="Sell", daemon=True)
    monitor_t = threading.Thread(target=monitor_thread_worker, name="Monitor", daemon=True)

    buy_t.start()
    time.sleep(1)
    sell_t.start()
    time.sleep(1)
    monitor_t.start()

    print(f"{Colors.GREEN}[Main] 모든 스레드 시작 완료 (Thread 1~4){Colors.ENDC}\n")

    # 6. 메인 루프
    try:
        while True:
            time.sleep(1)

    except KeyboardInterrupt:
        print(f"\n{Colors.RED}{'='*10}")
        print(f"[Exit] 사용자 중단 - 안전 종료 시작")
        print(f"{'='*10}{Colors.ENDC}")

        stop_event.set()

        with _ws_app_lock:
            if _ws_app:
                try:
                    _ws_app.close()
                except Exception:
                    pass

        print(f"{Colors.YELLOW}[Exit] 스레드 종료 대기 중...{Colors.ENDC}")
        ws_thread.join(timeout=5)
        buy_t.join(timeout=10)
        sell_t.join(timeout=10)
        monitor_t.join(timeout=10)

        runtime = format_duration(datetime.now() - start_time)
        with statistics_lock:
            final_wr = (winning_trades / total_trades * 100) if total_trades > 0 else 0

        ws_stat = get_ws_status_summary()

        # [복원] 종료 메시지에 WS 재연결 횟수 포함
        end_msg = f"""
**🛑 봇 종료**

**가동 시간:** `{runtime}`
**총 거래:** `{total_trades}회`
**승:** `{winning_trades}` | **패:** `{losing_trades}`
**승률:** `{final_wr:.1f}%`
**WS 재연결:** `{ws_stat['reconnect_count']}회`

⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
"""
        send_discord_message(end_msg)
        print(f"{Colors.GREEN}[Exit] 모든 스레드 종료 완료{Colors.ENDC}")


# ============================================================================
# SECTION 21: 프로그램 진입점
# ============================================================================

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        error_trace = traceback.format_exc()
        print(f"{Colors.RED}[Fatal Error] {error_trace}{Colors.ENDC}")
        send_error_notification("Fatal Error", error_trace)
