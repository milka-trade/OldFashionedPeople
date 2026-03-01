#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
BB Bounce Hunter v26.0 — 듀얼 타임프레임 + 실시간 데이터 혁신판

v25.2 전략 기반 + 전면 개선:

★ 데이터 인프라 혁신:
  - WebSocket 5분봉 실시간 빌더 (REST 호출 0회)
  - 스마트 캐시 TTL (15분봉 경계 인식, REST ~80% 감소)
  - 3단계 데이터 폴백 (WS→REST캐시→REST직접)

★ 매수 전략 혁신 (듀얼 타임프레임):
  Phase A: 자격 검증 (15분봉 BB 하단 + BB 폭 + 일봉)
  Phase B: 반등 확인 (15분봉 점수 + 5분봉 점수 듀얼 판단)
    - 15분봉: RSI 2봉연속↑, SRSI 골든크로스, 양봉+종가↑, 저가돌파확인
    - 5분봉: 3봉중2봉양봉, RSI 3봉중2봉↑, BB상승추세, 거래량급증
    - 매수: 15m≥2 AND 5m≥2 또는 합산≥5
  Phase C: 크래시 리커버리 (폭락→반등 전환점 감지, 별도 경로)

★ 매도 전략 혁신:
  - 동적 손절: BB Width 연동 (-3%~-5% 범위)
  - 가속 손절: 5분봉 3연속 음봉+RSI<25 패턴 즉시 탈출
  - 5분봉 트레일링: 더 정밀한 고점 추적
  - 5분봉 안전 익절: 5분봉 RSI 과매수 후 하락 전환 감지

★ 시장 등급 시스템 유지:
  HIGH(BBW≥4%), MID(2~4%), LOW(<2%) 동적 파라미터
"""

import os
from dotenv import load_dotenv
load_dotenv()       # pip install python-dotenv PyJWT websocket-client pandas requests numpy

import jwt
# pip uninstall jwt PyJWT python-jwt -y
# pip install PyJWT==2.8.0
import uuid
import hashlib
import urllib.parse
from urllib.parse import urlencode
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
VERSION = "27.0 BB_BOUNCE_HUNTER"

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
# ★ 시장 등급별 파라미터 테이블 (v26.0 — 동적 손절 적용)
# ============================================================================
# SELL_STOP_LOSS → 제거됨, 동적 손절 공식으로 대체:
#   stop_loss = -min(max(BB_Width × 0.8, 3.0), 5.0)
#   STOP_LOSS_FLOOR / STOP_LOSS_CEIL로 범위 제한

MARKET_GRADE_PARAMS = {
    'HIGH': {
        'BUY_BB_MAX':            30,
        'BUY_BB_WIDTH_MIN':     1.5,
        'SELL_SAFE_PROFIT':     1.2,
        'SELL_SAFE_BB_MIN':      75,
        'SELL_TRAIL_ACTIVATION': 1.5,
        'SELL_TRAIL_DISTANCE':   0.8,
        'SELL_FORCE_PROFIT':     2.5,
        'BUY_MIN_HOLD_SEC':      120,
        # v26.0: 동적 손절 범위
        'STOP_LOSS_FLOOR':      -3.5,   # 최소 손절 (가장 좁은)
        'STOP_LOSS_CEIL':       -5.0,   # 최대 손절 (가장 넓은)
        'STOP_LOSS_BBW_MULT':    0.8,   # BBW 곱수
    },
    'MID': {
        'BUY_BB_MAX':            25,
        'BUY_BB_WIDTH_MIN':     1.0,
        'SELL_SAFE_PROFIT':     1.2,
        'SELL_SAFE_BB_MIN':      70,
        'SELL_TRAIL_ACTIVATION': 1.2,
        'SELL_TRAIL_DISTANCE':   0.6,
        'SELL_FORCE_PROFIT':     2.5,
        'BUY_MIN_HOLD_SEC':      180,
        'STOP_LOSS_FLOOR':      -3.0,
        'STOP_LOSS_CEIL':       -4.5,
        'STOP_LOSS_BBW_MULT':    0.8,
    },
    'LOW': {
        'BUY_BB_MAX':            20,
        'BUY_BB_WIDTH_MIN':     0.8,
        'SELL_SAFE_PROFIT':     1.0,
        'SELL_SAFE_BB_MIN':      65,
        'SELL_TRAIL_ACTIVATION': 1.0,
        'SELL_TRAIL_DISTANCE':   0.5,
        'SELL_FORCE_PROFIT':     2.0,
        'BUY_MIN_HOLD_SEC':      240,
        'STOP_LOSS_FLOOR':      -2.5,
        'STOP_LOSS_CEIL':       -4.0,
        'STOP_LOSS_BBW_MULT':    0.8,
    },
}

# BBW 등급 임계값
GRADE_BBW_HIGH = 4.0
GRADE_BBW_LOW  = 2.0

# 시간대 → 기본 등급 매핑 (BBW 측정 실패 시 폴백)
HOUR_TO_GRADE = {}
for _h in range(24):
    if _h <= 5 or _h >= 22:
        HOUR_TO_GRADE[_h] = 'HIGH'
    elif (6 <= _h <= 10) or (20 <= _h <= 21):
        HOUR_TO_GRADE[_h] = 'MID'
    else:
        HOUR_TO_GRADE[_h] = 'LOW'

GRADE_REFERENCE_COINS = ['KRW-ETH', 'KRW-XRP']

# ── 스레드 주기 (초) ──
BUY_THREAD_INTERVAL = 10
SELL_THREAD_INTERVAL = 5
MONITOR_THREAD_INTERVAL = 60
BUY_SLEEP_WHEN_FULL = 30

# ── 캐시 TTL (초) — v26.0: 스마트 TTL로 대체, 이 값은 폴백 ──
CACHE_TTL_CANDLE = 30
CACHE_TTL_DAILY = 300        # v26.0: 일봉 캐시 5분으로 연장 (변동 적음)

# ── 매수 파라미터 (MID 등급 기본값 — 폴백용) ──
BUY_BB_MAX = 25
BUY_BB_WIDTH_MIN = 1.0
BUY_BOUNCE_MIN_15M = 2      # v26.0: 15분봉 반등 최소 점수
BUY_BOUNCE_MIN_5M = 2       # v26.0: 5분봉 반등 최소 점수
BUY_BOUNCE_TOTAL_MIN = 5    # v26.0: 합산 최소 점수 (한쪽 강할 때)
BUY_MIN_HOLD_SEC = 180

# ── 매도 파라미터 (MID 등급 기본값 — 폴백용) ──
SELL_FORCE_PROFIT = 2.5
SELL_SAFE_PROFIT = 1.2
SELL_SAFE_BB_MIN = 70
SELL_TRAIL_ACTIVATION = 1.2
SELL_TRAIL_DISTANCE = 0.6
# v26.0: 동적 손절 기본값
STOP_LOSS_FLOOR = -3.0
STOP_LOSS_CEIL = -4.5
STOP_LOSS_BBW_MULT = 0.8

# ── v26.0: 가속 손절 파라미터 (5분봉 패턴 기반) ──
ACCEL_STOP_CONSECUTIVE_BEAR = 3    # 연속 음봉 수
ACCEL_STOP_RSI_THRESHOLD = 25      # RSI 임계값
ACCEL_STOP_DROP_PCT = 1.0          # 직전봉 대비 하락률

# ── v26.0: 크래시 리커버리 파라미터 ──
CRASH_LOOKBACK_BARS_15M = 6        # 15분봉 6봉 = 1.5시간
CRASH_DROP_THRESHOLD = -5.0        # 폭락 기준 -5%
CRASH_RECOVERY_RISE_BARS = 3       # 5분봉 연속 상승 봉 수
CRASH_RECOVERY_RSI_FROM = 20       # RSI 저점 기준
CRASH_RECOVERY_RSI_TO = 35         # RSI 회복 기준
CRASH_RECOVERY_VOLUME_MULT = 1.5   # 거래량 배수
CRASH_RECOVERY_MIN_RISE = 1.5      # 최저가 대비 최소 반등%

# ── 리스크 관리 ──
REENTRY_COOLDOWN_MIN = 10
CONSECUTIVE_LOSS_LIMIT = 3
COOLDOWN_AFTER_LOSS = 30
MARKET_BREAKER_THRESHOLD = -3.0

# ── 매수 차단 시간대 (업비트 정산) ──
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

# ── v26.0: 5분봉 빌더 설정 ──
WS_CANDLE_HISTORY_SIZE = 40        # 완성봉 보관 수 (40봉 = 약 3.3시간)
WS_CANDLE_MIN_FOR_INDICATOR = 22   # 지표 계산 최소 봉 수

# ── v27.0: 급락 스캐너 파라미터 ──────────────────────────────────────
# 급락도(PlungeScore) 임계값: 90일 실데이터 기반 하루 약 1~2회/코인 발생
PLUNGE_STAGE1_THRESHOLD  = 4.5    # 이 점수 이상 → Watchlist 등록
PLUNGE_WATCH_WINDOW_MIN  = 120    # Watchlist 유효 시간 (분)
PLUNGE_SNAPSHOT_INTERVAL = 900    # 스캐너 실행 주기 (초, = 15분)
PLUNGE_MAX_RECOVERY_PCT  = 2.0    # 감지 후 이 % 이상 회복 시 진입 차단

# 코인별 급락 임계값 — 90일 15분봉 하락 분포 p10 기준
# cum4: 최근 4봉(1시간) 누적 낙폭 / daily: 당일 시가 대비 낙폭
COIN_DROP_THRESHOLDS = {
    'KRW-XRP':  {'cum4': -1.1, 'daily': -3.9},
    'KRW-SOL':  {'cum4': -1.2, 'daily': -4.5},
    'KRW-ADA':  {'cum4': -1.3, 'daily': -4.4},
    'KRW-ETH':  {'cum4': -1.0, 'daily': -4.1},
    'KRW-LINK': {'cum4': -1.1, 'daily': -4.0},
    'KRW-BCH':  {'cum4': -1.1, 'daily': -3.8},
    'KRW-SUI':  {'cum4': -1.4, 'daily': -4.9},
}


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

# ★ 현재 시장 등급 상태
current_market_grade = 'MID'
current_grade_source = 'init'
current_grade_bbw = 0.0
last_grade_check_time = None
grade_lock = Lock()

# ★ v27.0: 급락 스캐너 상태
# {ticker: {'detected_at':dt, 'detected_price':float, 'stage1_score':float, 'expires_at':dt}}
sharp_drop_watchlist: dict = {}
watchlist_lock = Lock()
last_snapshot_time: float = 0.0

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
print(f"  ★ 듀얼 타임프레임: 15분봉(위치) + 5분봉(타이밍)")
print(f"  ★ WS 5분봉 실시간 빌더 (REST 호출 최소화)")
print(f"  ★ 동적 손절: BB Width 연동 + 가속 손절 패턴")
print(f"  ★ 크래시 리커버리: 폭락→반등 전환점 감지")
print(f"  ★ 급락 스캐너: PlungeScore + 감속 패턴 (v27.0 신규)")
print(f"  시장등급: HIGH(BBW≥4%) MID(2~4%) LOW(<2%)")
print(f"{'='*60}")
print(f"  Thread 1: 매수 ({BUY_THREAD_INTERVAL}초) │ 급락스캐너: 15분주기")
print(f"  Thread 2: 매도 ({SELL_THREAD_INTERVAL}초)")
print(f"  Thread 3: 모니터 ({MONITOR_THREAD_INTERVAL}초)")
print(f"  Thread 4: WebSocket + 5분봉 빌더")
print(f"  MAX: {MAX_HOLDINGS}개 | 1차:{FIRST_BUY_RATIO:.0%} 2차:전량")
print(f"{'='*60}{Colors.ENDC}\n")


# ============================================================================
# SECTION 5: Upbit REST API 클라이언트 (v25.2 동일)
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
        for attempt in range(1, 4):
            try:
                headers = self._auth_headers()
                resp = requests.get(f"{UPBIT_API_BASE}/v1/accounts", headers=headers, timeout=10)
                if resp.status_code == 200:
                    return resp.json()
                try:
                    err_body = resp.json()
                    err_msg = err_body.get('error', {}).get('message', resp.text[:200])
                    err_name = err_body.get('error', {}).get('name', '')
                except Exception:
                    err_msg = resp.text[:200]
                    err_name = ''
                print(f"{Colors.RED}[API] get_balances 실패 (시도 {attempt}/3)"
                      f" HTTP {resp.status_code} | {err_name}: {err_msg}{Colors.ENDC}")
                if resp.status_code == 401:
                    return None
                if resp.status_code == 429:
                    time.sleep(5 * attempt)
                    continue
                time.sleep(2 * attempt)
            except requests.exceptions.ConnectionError as e:
                print(f"{Colors.YELLOW}[API] get_balances 연결 오류 (시도 {attempt}/3): {e}{Colors.ENDC}")
                time.sleep(3 * attempt)
            except Exception as e:
                print(f"{Colors.RED}[API] get_balances 예외 (시도 {attempt}/3): {e}{Colors.ENDC}")
                time.sleep(2)
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
# SECTION 6: WebSocket + ★ 5분봉 실시간 빌더 (v26.0 핵심 신규)
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

# ── ★ v26.0: 5분봉 실시간 빌더 글로벌 상태 ──
# 구조: {ticker: {'current': {봉 데이터}, 'history': deque([완성봉...]), 'indicators_ready': bool}}
ws_candles_5m = {}
ws_candles_5m_lock = threading.Lock()
_ws_candle_initialized = {}   # {ticker: bool} — REST 초기화 완료 여부


def _rate_limit_wait(min_interval=0.12):
    global _api_last_call_time
    with _api_call_lock:
        now = time.time()
        elapsed = now - _api_last_call_time
        if elapsed < min_interval:
            time.sleep(min_interval - elapsed)
        _api_last_call_time = time.time()


def _get_5m_slot(ts=None):
    """Unix timestamp → 5분 슬롯 시작 시각 (초 단위)"""
    if ts is None:
        ts = time.time()
    return int(ts) // 300 * 300


def _init_ws_candle_from_rest(ticker):
    """봇 시작 시 REST로 5분봉 히스토리 로드 → WS 빌더 초기화"""
    try:
        df = get_ohlcv(ticker, interval="minute5", count=WS_CANDLE_HISTORY_SIZE)
        if df is None or len(df) < WS_CANDLE_MIN_FOR_INDICATOR:
            return False

        history = deque(maxlen=WS_CANDLE_HISTORY_SIZE)
        for idx in range(len(df)):
            row = df.iloc[idx]
            history.append({
                'open': float(row['open']),
                'high': float(row['high']),
                'low': float(row['low']),
                'close': float(row['close']),
                'volume': float(row['volume']),
                'timestamp': row.name.timestamp() if hasattr(row.name, 'timestamp') else time.time(),
            })

        with ws_candles_5m_lock:
            ws_candles_5m[ticker] = {
                'current': None,
                'history': history,
                'indicators_ready': len(history) >= WS_CANDLE_MIN_FOR_INDICATOR,
            }
        _ws_candle_initialized[ticker] = True
        return True
    except Exception as e:
        if DEBUG_MODE:
            print(f"{Colors.RED}[5m Init] {ticker} REST 초기화 실패: {e}{Colors.ENDC}")
        return False


def _update_ws_candle(ticker, price, volume_delta=0.0, ts=None):
    """
    ★ WebSocket 틱 → 5분봉 실시간 갱신.
    매 틱마다 호출. 5분 경계에서 봉 확정.
    """
    try:
        if ts is None:
            ts = time.time()
        current_slot = _get_5m_slot(ts)

        with ws_candles_5m_lock:
            if ticker not in ws_candles_5m:
                # 아직 REST 초기화 안 됨 → 스킵
                return

            candle_data = ws_candles_5m[ticker]
            current = candle_data['current']

            if current is None:
                # 첫 틱 — 새 봉 시작
                candle_data['current'] = {
                    'open': price, 'high': price, 'low': price, 'close': price,
                    'volume': volume_delta, 'slot': current_slot, 'timestamp': ts,
                }
                return

            if current['slot'] == current_slot:
                # 같은 5분 구간 — 봉 갱신
                current['high'] = max(current['high'], price)
                current['low'] = min(current['low'], price)
                current['close'] = price
                current['volume'] += volume_delta
                current['timestamp'] = ts
            else:
                # 새 5분 구간 진입 — 이전 봉 확정 → 히스토리 push
                completed_candle = {
                    'open': current['open'],
                    'high': current['high'],
                    'low': current['low'],
                    'close': current['close'],
                    'volume': current['volume'],
                    'timestamp': current['slot'],
                }
                candle_data['history'].append(completed_candle)
                candle_data['indicators_ready'] = len(candle_data['history']) >= WS_CANDLE_MIN_FOR_INDICATOR

                # 새 봉 시작
                candle_data['current'] = {
                    'open': price, 'high': price, 'low': price, 'close': price,
                    'volume': volume_delta, 'slot': current_slot, 'timestamp': ts,
                }
    except Exception:
        pass  # 틱 처리 실패는 무시 (다음 틱에서 복구)


def get_ws_candles_5m(ticker, include_current=True):
    """
    ★ 5분봉 DataFrame 반환 (WS 빌더 데이터).
    매수/매도 스레드에서 호출. REST 호출 0회!

    Args:
        ticker: 코인 티커
        include_current: True면 미완성 현재 봉도 포함

    Returns:
        pd.DataFrame with indicators, or None
    """
    try:
        with ws_candles_5m_lock:
            if ticker not in ws_candles_5m:
                return None
            cd = ws_candles_5m[ticker]
            if not cd['indicators_ready']:
                return None
            candles = list(cd['history'])
            if include_current and cd['current'] is not None:
                candles.append({
                    'open': cd['current']['open'],
                    'high': cd['current']['high'],
                    'low': cd['current']['low'],
                    'close': cd['current']['close'],
                    'volume': cd['current']['volume'],
                    'timestamp': cd['current']['timestamp'],
                })

        if len(candles) < WS_CANDLE_MIN_FOR_INDICATOR:
            return None

        rows = []
        for c in candles:
            ts_val = c['timestamp']
            if isinstance(ts_val, (int, float)):
                dt = datetime.fromtimestamp(ts_val)
            else:
                dt = ts_val
            rows.append({
                'datetime': dt,
                'open': c['open'], 'high': c['high'],
                'low': c['low'], 'close': c['close'],
                'volume': c['volume'],
            })

        df = pd.DataFrame(rows)
        df['datetime'] = pd.to_datetime(df['datetime'])
        df = df.set_index('datetime').sort_index(ascending=True)
        df = df[~df.index.duplicated(keep='last')]

        if len(df) < 20:
            return None

        # 지표 계산
        df = add_indicators(df)
        return df

    except Exception as e:
        if DEBUG_MODE:
            print(f"{Colors.RED}[5m WS] get_ws_candles_5m({ticker}) 오류: {e}{Colors.ENDC}")
        return None


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
    """★ v26.0: 가격 캐시 + 5분봉 빌더 동시 갱신"""
    try:
        data = json.loads(message)
        code = data.get('code', '')
        price = data.get('trade_price', 0)
        ts = time.time()
        if code and price > 0:
            # 1. 가격 캐시 갱신 (기존)
            with ws_price_lock:
                ws_price_cache[code] = {'price': price, 'ts': ts}
            with ws_status_lock:
                ws_status['last_received'] = ts

            # 2. ★ 5분봉 빌더 갱신 (v26.0 신규)
            vol_delta = float(data.get('acc_trade_volume', 0)) * 0.001  # 추정 틱 볼륨
            _update_ws_candle(code, price, vol_delta, ts)

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
    print(f"{Colors.BLUE}[Thread 4] WebSocket + 5분봉 빌더 스레드 시작{Colors.ENDC}")
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
# SECTION 9: ★ 스마트 캐시 시스템 (v26.0 개선)
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


def get_smart_cache_ttl_15m():
    """
    ★ v26.0: 15분봉 경계 인식 스마트 TTL.
    - 봉 시작 직후 (0~30초): 10초 (새 봉 확정 직후)
    - 봉 마감 임박 (마지막 1분): 10초 (최종 종가 확인)
    - 봉 중간: 120초 (완성봉 변하지 않음, REST 절약)
    """
    now = datetime.now()
    minutes_in_period = now.minute % 15
    seconds_in_period = minutes_in_period * 60 + now.second

    if seconds_in_period < 30:
        return 10       # 봉 시작 직후
    elif seconds_in_period > 840:
        return 10       # 봉 마감 임박 (14분+)
    else:
        return 120      # 봉 중간 — 2분 캐시


def get_candles_15m(ticker, count=50):
    try:
        cache_key = f"{ticker}_15m_{count}"
        smart_ttl = get_smart_cache_ttl_15m()
        cached = get_cached_data(cache_key, smart_ttl)
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


def get_candles_5m_rest(ticker, count=40):
    """5분봉 REST 폴백 (WS 빌더 실패 시)"""
    try:
        cache_key = f"{ticker}_5m_{count}"
        cached = get_cached_data(cache_key, 15)  # 5분봉 REST 캐시 15초
        if cached is not None:
            return cached
        df = get_ohlcv(ticker, interval="minute5", count=count)
        if df is not None and len(df) >= 20:
            df = add_indicators(df)
            if df is not None:
                set_cached_data(cache_key, df)
                return df
        return None
    except Exception:
        return None


def get_candles_5m(ticker, count=40):
    """
    ★ v26.0: 5분봉 통합 조회 — WS 빌더 우선, REST 폴백.
    3단계: WS빌더 → REST캐시 → REST직접
    """
    # Level 1: WS 빌더 (API 호출 0회)
    df = get_ws_candles_5m(ticker, include_current=True)
    if df is not None and len(df) >= 20:
        return df

    # Level 2~3: REST 폴백
    return get_candles_5m_rest(ticker, count)


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
    try:
        portfolio = get_enhanced_portfolio_status()
        coin_name = ticker.replace('KRW-', '')
        asset_line = (f"💰 **자산** `총 {portfolio['total_assets']:,.0f}원` | "
                      f"`코인 {portfolio['total_coin_value']:,.0f}원` | "
                      f"`현금 {portfolio['krw_balance']:,.0f}원`")
        bb_w = f" [폭{signal.get('bb_width_pct', 0):.1f}%]"
        entry_type = signal.get('entry_type', 'normal')
        type_tag = "🔄" if entry_type == 'crash_recovery' else "📈"
        buy_info = (f"{type_tag} **{coin_name} 매수완료**\n"
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
    try:
        message = (f"\n**오류 발생**\n\n**유형:** `{error_type}`\n\n"
                   f"**상세 내용:**\n```\n{error_details[:500]}\n```\n\n"
                   f"**시각:** `{datetime.now().strftime('%H:%M:%S')}`\n")
        send_discord_message(message, is_critical=True)
    except Exception:
        pass


# ============================================================================
# SECTION 12: 유틸리티 + 리스크 관리 함수
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
    if price >= 10_000_000:
        return f"{price/10000:.0f}만"
    elif price >= 10_000:
        return f"{price/10000:.1f}만"
    elif price >= 1_000:
        return f"{price:,.0f}"
    else:
        return f"{price:.1f}"


def format_profit_amount(amount):
    if abs(amount) >= 10_000:
        return f"{amount/10000:+.1f}만"
    else:
        return f"{amount:+,.0f}"


def get_portfolio_status():
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
    portfolio = get_portfolio_status()
    return portfolio['total_assets']


def calculate_coin_status_for_report(ticker):
    """
    v27.0: 일봉 API 호출 제거 → ticker snapshot(당일 등락률) + 15분봉으로 대체.
    모니터 보고서·watch_section 에서 사용.
    """
    try:
        cur_price  = get_current_price(ticker) or 0
        d_change   = 0.0
        is_bullish = False

        # 당일 등락률 — ticker snapshot 에서 직접 취득 (API 1회)
        try:
            url  = f"https://api.upbit.com/v1/ticker?markets={ticker}"
            resp = requests.get(url, timeout=3)
            if resp.status_code == 200:
                item       = resp.json()[0]
                d_change   = item.get('signed_change_rate', 0) * 100
                is_bullish = d_change >= 0
                if cur_price == 0:
                    cur_price = item.get('trade_price', 0)
        except Exception:
            pass

        # 15분봉 지표 (BB, RSI, StochRSI)
        bb15 = 50.0; bw15 = 0.0; rsi15 = 50.0; srsi_k = 50.0; srsi_direction = '→'
        df_15m = get_candles_15m(ticker, count=30)
        if df_15m is not None and len(df_15m) >= 20:
            c = df_15m.iloc[-1]
            bb15  = c.get('bb_position', 50)
            bw15  = c.get('bb_width', 0)
            rsi15 = c.get('rsi', 50)
            srsi_k = c.get('srsi_k', 50)
            srsi_d = c.get('srsi_d', 50)
            srsi_direction = '↗' if srsi_k > srsi_d else ('↘' if srsi_k < srsi_d else '→')
            if cur_price == 0:
                cur_price = c.get('close', 0)

        # Watchlist 상태 반영
        in_watch, wl_info = is_in_watchlist(ticker)
        wl_score = wl_info.get('stage1_score', 0) if wl_info else 0

        return {
            'cur_price':      cur_price,
            'cur_price_str':  format_price_compact(cur_price) if cur_price > 0 else '-',
            'd_change':       d_change,
            'is_bullish':     is_bullish,
            'bb15':           bb15,
            'bw15':           bw15,
            'rsi15':          rsi15,
            'srsi_k':         srsi_k,
            'srsi_direction': srsi_direction,
            'in_watchlist':   in_watch,
            'wl_score':       wl_score,
        }
    except Exception:
        return {
            'cur_price': 0, 'cur_price_str': '-',
            'd_change': 0, 'is_bullish': False,
            'bb15': 50, 'bw15': 0, 'rsi15': 50,
            'srsi_k': 50, 'srsi_direction': '→',
            'in_watchlist': False, 'wl_score': 0,
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
    global daily_trade_count, last_reset_date
    today = datetime.now().date()
    if today != last_reset_date:
        daily_trade_count = 0
        last_reset_date = today
    return daily_trade_count < MAX_DAILY_TRADES


# ============================================================================
# SECTION 12-B: 시장 등급 시스템 (v25.0 유지)
# ============================================================================

def get_time_based_grade():
    hour = datetime.now().hour
    return HOUR_TO_GRADE.get(hour, 'MID')


def measure_reference_bbw():
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


def update_market_grade():
    global current_market_grade, current_grade_source, current_grade_bbw
    global last_grade_check_time

    try:
        with grade_lock:
            bbw = measure_reference_bbw()
            if bbw is not None:
                if bbw >= GRADE_BBW_HIGH:
                    grade = 'HIGH'
                elif bbw < GRADE_BBW_LOW:
                    grade = 'LOW'
                else:
                    grade = 'MID'
                source = 'bbw'
            else:
                grade = get_time_based_grade()
                source = 'time'
                bbw = 0.0
            prev_grade = current_market_grade
            current_market_grade = grade
            current_grade_source = source
            current_grade_bbw = bbw
            last_grade_check_time = datetime.now()
            if prev_grade != grade and DEBUG_MODE:
                src_str = f"BBW {bbw:.1f}%" if source == 'bbw' else f"시간대 {datetime.now().hour}시"
                print(f"{Colors.MAGENTA}[Grade] {prev_grade} → {grade} ({src_str}){Colors.ENDC}")
            return grade
    except Exception as e:
        if DEBUG_MODE:
            print(f"{Colors.RED}[Grade] 등급 갱신 오류: {e}{Colors.ENDC}")
        return current_market_grade


def get_grade_params(grade=None):
    if grade is None:
        grade = current_market_grade
    return MARKET_GRADE_PARAMS.get(grade, MARKET_GRADE_PARAMS['MID'])


def get_grade_display_str():
    grade = current_market_grade
    bbw = current_grade_bbw
    source = current_grade_source
    emoji = {'HIGH': '🔴', 'MID': '🟡', 'LOW': '🔵'}.get(grade, '⬜')
    src_str = f"BBW {bbw:.1f}%" if source == 'bbw' else f"시간대{datetime.now().hour}시"
    p = get_grade_params(grade)
    sl_f = p.get('STOP_LOSS_FLOOR', -3.0)
    sl_c = p.get('STOP_LOSS_CEIL', -5.0)
    return (f"{emoji} [{grade}] {src_str} | "
            f"BB≤{p['BUY_BB_MAX']}% 폭≥{p['BUY_BB_WIDTH_MIN']}% "
            f"손절{sl_f}~{sl_c}% 강제+{p['SELL_FORCE_PROFIT']}%")


def calculate_dynamic_stop_loss(bb_width, grade=None):
    """
    ★ v26.0: BB Width 연동 동적 손절 계산.
    공식: stop_loss = -min(max(BB_Width × mult, floor), ceil)
    """
    p = get_grade_params(grade)
    mult = p.get('STOP_LOSS_BBW_MULT', STOP_LOSS_BBW_MULT)
    floor = p.get('STOP_LOSS_FLOOR', STOP_LOSS_FLOOR)
    ceil = p.get('STOP_LOSS_CEIL', STOP_LOSS_CEIL)

    # floor, ceil은 음수 (예: -3.0, -5.0)
    raw = -(bb_width * mult)
    stop = max(raw, ceil)     # ceil이 더 넓으므로 max (예: max(-4.8, -5.0) = -4.8)
    stop = min(stop, floor)   # floor이 더 좁으므로 min (예: min(-4.8, -3.0) = -4.8)

    # 재확인: stop은 floor와 ceil 사이
    stop = max(stop, ceil)    # 하한 (가장 넓은 손절)
    stop = min(stop, floor)   # 상한 (가장 좁은 손절)
    return stop


# ============================================================================
# SECTION 13: ★★★ 매수 신호 v27.0 — 급락 스캐너 + 듀얼 타임프레임 + 크래시 리커버리
# ============================================================================

def check_daily_bullish(ticker):
    """
    일봉 상승장 확인 — v27.0부터 buy_signal 에서 직접 호출하지 않음.
    모니터 보고서·외부 참조용으로 유지.
    """
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


# ─────────────────────────────────────────────────────────────────────────────
# ★ v27.0 신규: 급락 스캐너 (SECTION 13.5)
#   fetch_ticker_snapshot → calc_plunge_score → detect_decel_pattern
#   → run_sharp_drop_scanner → is_in_watchlist
# ─────────────────────────────────────────────────────────────────────────────

def fetch_ticker_snapshot():
    """
    Upbit ticker API 1회 호출로 7개 코인 현재가·당일시가 동시 수집.

    API가 직접 제공하는 opening_price(당일 09:00 시가)를 활용하므로
    별도 일봉 API 호출 불필요.

    반환: {ticker: {'price', 'opening_price', 'drop_from_open', 'change_rate'}}
    """
    markets = ','.join(FIXED_STABLE_COINS)
    url = f"https://api.upbit.com/v1/ticker?markets={markets}"
    try:
        resp = requests.get(url, timeout=5)
        resp.raise_for_status()
        result = {}
        for item in resp.json():
            ticker  = item['market']
            opening = item.get('opening_price', 0)
            current = item.get('trade_price', 0)
            drop    = (current - opening) / opening * 100 if opening else 0
            result[ticker] = {
                'price':         current,
                'opening_price': opening,
                'drop_from_open': drop,
                'change_rate':   item.get('signed_change_rate', 0) * 100,
            }
        return result
    except Exception as e:
        if DEBUG_MODE:
            print(f"{Colors.RED}[SNAPSHOT] API 오류: {e}{Colors.ENDC}")
        return {}


def calc_plunge_score(df_15m, ticker):
    """
    15분봉 데이터에서 급락도 점수(0~10) 계산.

    구성 (가중 합산):
      A. 4봉(1h) 누적 낙폭   — 낙하 속도 (40%)
      B. Range Spike         — 봉내 이상 변동 감지 (30%)  ← 신규
      C. 당일 시가 대비 낙폭  — 낙하 깊이 (30%)

    Range Spike = 현재봉 (고-저) / 최근 20봉 평균 (고-저)
    하락봉이 아니면 Spike 점수 0 처리 (상승 이상 제외).

    반환: (score: float, reason: str)
    """
    if df_15m is None or len(df_15m) < 6:
        return 0.0, "데이터부족"

    thresh = COIN_DROP_THRESHOLDS.get(ticker, {'cum4': -1.2, 'daily': -4.0})
    curr   = df_15m.iloc[-1]

    # ── A. 4봉 누적 낙폭 ──
    cum_drop_4 = (df_15m['close'].iloc[-1] - df_15m['close'].iloc[-5]) / df_15m['close'].iloc[-5] * 100 \
                 if len(df_15m) >= 5 else 0.0
    # p10 기준 2배 이상이면 만점(1.0)
    cum4_norm = min(max(cum_drop_4 / thresh['cum4'], 0), 1) if cum_drop_4 < 0 else 0.0

    # ── B. Range Spike ──
    range_now = curr['high'] - curr['low']
    range_col = df_15m['high'] - df_15m['low']
    range_ma  = range_col.iloc[-21:-1].mean() if len(df_15m) >= 21 else range_now
    spike     = range_now / range_ma if range_ma > 0 else 1.0
    # 1배→0, 4배→1 정규화. 하락봉에서만 유효
    is_bear   = curr['close'] < curr['open']
    spike_norm = min(max((spike - 1) / 3, 0), 1) if is_bear else 0.0

    # ── C. 당일 시가 대비 낙폭 ──
    # 당일 첫봉 open을 시가 근사치로 사용
    daily_open   = df_15m['open'].iloc[0]
    drop_d_open  = (curr['close'] - daily_open) / daily_open * 100 if daily_open > 0 else 0.0
    daily_norm   = min(max(drop_d_open / thresh['daily'], 0), 1) if drop_d_open < 0 else 0.0

    score = cum4_norm * 4.0 + spike_norm * 3.0 + daily_norm * 3.0

    parts = []
    if cum4_norm  > 0.3: parts.append(f"4봉{cum_drop_4:.1f}%")
    if spike_norm > 0.3: parts.append(f"Spike{spike:.1f}x")
    if daily_norm > 0.3: parts.append(f"시가{drop_d_open:.1f}%")

    return round(score, 2), ('+'.join(parts) if parts else "정상")


def detect_decel_pattern(df_15m):
    """
    하락 모멘텀 감속 패턴 감지 (15분봉).

    패턴 정의:
      봉T-2 : 하락봉 (기준)
      봉T-1 : 하락봉, T-2 보다 ≥10% 더 크게 하락 (가속)
      봉T   : 하락봉, T-1 보다 ≥10% 작게 하락   (감속) ← 감지 시점

    의미: 매도 에너지가 T-1 에서 정점을 찍고 소진되기 시작.
    반환: (decel_ok: bool, decel_strength: float 0~1, reason: str)
    """
    if df_15m is None or len(df_15m) < 4:
        return False, 0.0, "데이터부족"

    c0 = df_15m.iloc[-3]   # 2봉 전
    c1 = df_15m.iloc[-2]   # 1봉 전
    c2 = df_15m.iloc[-1]   # 현재봉

    body0 = abs(c0['close'] - c0['open']) / c0['open'] * 100 if c0['open'] > 0 else 0
    body1 = abs(c1['close'] - c1['open']) / c1['open'] * 100 if c1['open'] > 0 else 0
    body2 = abs(c2['close'] - c2['open']) / c2['open'] * 100 if c2['open'] > 0 else 0

    all_bear   = c0['close'] < c0['open'] and c1['close'] < c1['open'] and c2['close'] < c2['open']
    meaningful = body1 >= 0.05 and body0 >= 0.03   # 노이즈 제거
    was_accel  = body1 > body0 * 1.1               # T-2→T-1: ≥10% 가속
    now_decel  = body2 < body1 * 0.9               # T-1→T  : ≥10% 감속

    if all_bear and meaningful and was_accel and now_decel:
        strength = min(max(1.0 - (body2 / body1), 0.0), 1.0)
        return True, round(strength, 2), f"{strength*100:.0f}%(T-1:{body1:.2f}%→T:{body2:.2f}%)"

    return False, 0.0, f"감속없음(T-2:{body0:.2f}%,T-1:{body1:.2f}%,T:{body2:.2f}%)"


def _cleanup_watchlist():
    """만료된 Watchlist 항목 제거 (watchlist_lock 외부에서 호출)."""
    now = datetime.now()
    with watchlist_lock:
        expired = [t for t, v in sharp_drop_watchlist.items() if now > v['expires_at']]
        for t in expired:
            if DEBUG_MODE:
                print(f"{Colors.YELLOW}  [WATCHLIST] {t.replace('KRW-','')} 만료 제거{Colors.ENDC}")
            del sharp_drop_watchlist[t]


def is_in_watchlist(ticker):
    """
    Watchlist 등록 여부 및 진입 가능 여부 확인.

    반환:
      (True, info_dict)  — 감시 중 + 아직 너무 많이 회복 안 됨
      (False, None)      — 미등록·만료·이미 회복
    """
    with watchlist_lock:
        if ticker not in sharp_drop_watchlist:
            return False, None
        info = sharp_drop_watchlist[ticker]
        if datetime.now() > info['expires_at']:
            return False, None
        return True, info


def run_sharp_drop_scanner():
    """
    ★ 15분마다 실행 — 7개 코인 급락도 스캔 + Watchlist 관리.

    실행 흐름:
      1. ticker API 1회 호출 → 당일 낙폭 빠른 파악
      2. 빠른 사전 필터 통과 코인만 15분봉 조회 (API 절약)
      3. calc_plunge_score() → 급락도 점수 계산
      4. 임계값 초과 시 Watchlist 등록 (120분 유효)
      5. 만료 항목 자동 정리
      6. 전체 시장 급락(≥4개 동시) 시 Discord 경보만 발령
    """
    global last_snapshot_time
    now_ts = time.time()
    if now_ts - last_snapshot_time < PLUNGE_SNAPSHOT_INTERVAL:
        return
    last_snapshot_time = now_ts

    now_str = datetime.now().strftime('%H:%M')
    print(f"\n{Colors.CYAN}{'─'*54}")
    print(f"[DROP SCAN] 🔍 급락 스캐너 실행 ({now_str})")
    print(f"{'─'*54}{Colors.ENDC}")

    # Step 1: 전체 스냅샷 (API 1회)
    snapshot = fetch_ticker_snapshot()
    if not snapshot:
        print(f"{Colors.RED}[DROP SCAN] 스냅샷 실패 — 다음 주기에 재시도{Colors.ENDC}")
        return

    newly_added   = []
    drop_detected = 0   # 동시 급락 코인 수 카운트

    for ticker in FIXED_STABLE_COINS:
        coin = ticker.replace('KRW-', '')
        snap = snapshot.get(ticker)
        if not snap:
            continue

        thresh    = COIN_DROP_THRESHOLDS.get(ticker, {'cum4': -1.2, 'daily': -4.0})
        drop_open = snap['drop_from_open']

        # Step 2: 사전 필터 — 당일 낙폭이 p10 기준 50% 이상일 때만 캔들 조회
        quick_flag = drop_open <= (thresh['daily'] * 0.5)

        if quick_flag:
            df_15m = get_candles_15m(ticker, count=25)   # 캐시 활용
            score, score_reason = calc_plunge_score(df_15m, ticker)
        else:
            # 사전 필터 미통과 → 경량 계산 (캔들 6봉만)
            df_15m = get_candles_15m(ticker, count=6)
            score, score_reason = calc_plunge_score(df_15m, ticker)

        in_watch  = ticker in sharp_drop_watchlist
        over_thr  = score >= PLUNGE_STAGE1_THRESHOLD
        icon      = "🔴" if over_thr else ("🟡" if score >= 2.5 else "  ")

        print(f"  {coin:<5} 급락도:{score:4.1f}{icon} | "
              f"시가대비:{drop_open:+.1f}% | {score_reason[:22]:<22}"
              f"{'[감시중]' if in_watch else ''}")

        if over_thr:
            drop_detected += 1
            if not in_watch:
                with watchlist_lock:
                    sharp_drop_watchlist[ticker] = {
                        'detected_at':    datetime.now(),
                        'detected_price': snap['price'],
                        'stage1_score':   score,
                        'score_reason':   score_reason,
                        'expires_at':     datetime.now() + timedelta(minutes=PLUNGE_WATCH_WINDOW_MIN),
                    }
                newly_added.append(f"{coin}({score:.1f}점)")

    # Step 5: 만료 정리
    _cleanup_watchlist()

    # 전체 시장 동시 급락 경보
    if drop_detected >= 4:
        msg = (f"⚠️ **전체 시장 급락 경보**\n"
               f"{drop_detected}/7 코인 동시 급락 감지 — 매수 자제\n"
               f"{datetime.now().strftime('%H:%M:%S')}")
        send_discord_message(msg)
        print(f"{Colors.RED}  ⚠️ 전체 시장 급락 경보: {drop_detected}/7코인{Colors.ENDC}")

    # 결과 요약
    if newly_added:
        print(f"{Colors.RED}  🚨 신규 감시 등록: {', '.join(newly_added)}{Colors.ENDC}")
    with watchlist_lock:
        active = [f"{t.replace('KRW-','')}({v['stage1_score']:.1f}점)"
                  for t, v in sharp_drop_watchlist.items()]
    print(f"  📋 감시 중: {active if active else ['없음']}")
    print(f"{Colors.CYAN}{'─'*54}{Colors.ENDC}\n")


def score_15m_bounce(df):
    """
    ★ v26.0: 15분봉 반등 점수 (최대 4점)
    +1: RSI 2봉 연속 상승
    +1: SRSI K 상향돌파 D (골든크로스)
    +1: 양봉 + 종가 > 직전 종가
    +1: 현재가 > 3봉전 저가 (하락 멈춤 확인)
    """
    try:
        score = 0
        details = []

        if df is None or len(df) < 4:
            return 0, []

        c = df.iloc[-1]    # 현재
        p1 = df.iloc[-2]   # 1봉 전
        p2 = df.iloc[-3]   # 2봉 전
        p3 = df.iloc[-4]   # 3봉 전

        # 1) RSI 2봉 연속 상승
        if c['rsi'] > p1['rsi'] and p1['rsi'] > p2['rsi']:
            score += 1
            details.append(f"RSI↑↑{c['rsi']:.0f}")
        elif c['rsi'] > p1['rsi']:
            # 1봉만 상승 — 0.5점 가치이지만 정수 스코어이므로 부분 점수 없음
            pass

        # 2) SRSI K 상향돌파 D (골든크로스)
        if c['srsi_k'] > c['srsi_d'] and p1['srsi_k'] <= p1['srsi_d']:
            score += 1
            details.append(f"SRSI골든{c['srsi_k']:.0f}")
        elif c['srsi_k'] > c['srsi_d'] and c['srsi_k'] > p1['srsi_k']:
            score += 1
            details.append(f"SRSI↑{c['srsi_k']:.0f}>D{c['srsi_d']:.0f}")

        # 3) 양봉 + 종가 > 직전 종가
        if c['is_bull'] and c['close'] > p1['close']:
            score += 1
            details.append("양봉+종가↑")

        # 4) 현재가 > 3봉전 저가 (하락 멈춤)
        if c['close'] > p3['low']:
            score += 1
            details.append(f">{p3['low']:.0f}")

        return score, details
    except Exception:
        return 0, []


def score_5m_bounce(df_5m):
    """
    ★ v26.0: 5분봉 반등 점수 (최대 4점)
    +1: 최근 3봉 중 2봉+ 양봉
    +1: 5분봉 RSI 3봉 중 2봉+ 상승
    +1: 5분봉 BB Position 상승 추세 (현재 > 2봉 전)
    +1: 5분봉 거래량 > 직전 10봉 평균 × 1.3
    """
    try:
        score = 0
        details = []

        if df_5m is None or len(df_5m) < 10:
            return 0, []

        c = df_5m.iloc[-1]
        p1 = df_5m.iloc[-2]
        p2 = df_5m.iloc[-3]

        # 1) 최근 3봉 중 2봉+ 양봉
        recent_3_bulls = sum(1 for i in range(-3, 0) if df_5m.iloc[i]['is_bull'])
        if recent_3_bulls >= 2:
            score += 1
            details.append(f"양봉{recent_3_bulls}/3")

        # 2) RSI 3봉 중 2봉+ 상승
        rsi_rises = 0
        if c['rsi'] > p1['rsi']:
            rsi_rises += 1
        if p1['rsi'] > p2['rsi']:
            rsi_rises += 1
        if c['rsi'] > p2['rsi']:
            rsi_rises += 1
        if rsi_rises >= 2:
            score += 1
            details.append(f"5mRSI↑{c['rsi']:.0f}")

        # 3) BB Position 상승 추세 (현재 > 2봉 전)
        if c['bb_position'] > p2['bb_position']:
            score += 1
            details.append(f"5mBB{c['bb_position']:.0f}↑")

        # 4) 거래량 급증
        if len(df_5m) >= 10:
            avg_vol = df_5m.iloc[-11:-1]['volume'].mean()
            if avg_vol > 0 and c['volume'] > avg_vol * 1.3:
                score += 1
                details.append(f"거래량{c['volume']/avg_vol:.1f}x")

        return score, details
    except Exception:
        return 0, []


def check_crash_recovery(ticker, df_15m, df_5m):
    """
    ★ v26.0: 크래시 리커버리 — 폭락→반등 전환점 감지.
    일봉 조건 면제하고 매수 허용하는 별도 경로.

    조건 (모두 충족):
    1. 15분봉 6봉 내 -5% 이상 하락 이력
    2. 최저점 후 5분봉 3봉+ 연속 상승
    3. 5분봉 RSI: 20 이하 → 35 이상 회복
    4. 거래량 급증 (10봉 평균 1.5배+)
    5. 현재가 > 최저가 +1.5%

    Returns: (bool, str reason)
    """
    try:
        if df_15m is None or len(df_15m) < CRASH_LOOKBACK_BARS_15M:
            return False, "데이터부족"
        if df_5m is None or len(df_5m) < 10:
            return False, "5분봉부족"

        # 1. 15분봉 최근 6봉 내 폭락 확인
        recent_15m = df_15m.iloc[-CRASH_LOOKBACK_BARS_15M:]
        high_in_range = recent_15m['high'].max()
        low_in_range = recent_15m['low'].min()
        if high_in_range <= 0:
            return False, "가격오류"
        drop_pct = ((low_in_range - high_in_range) / high_in_range) * 100
        if drop_pct > CRASH_DROP_THRESHOLD:
            return False, f"폭락없음({drop_pct:.1f}%>{CRASH_DROP_THRESHOLD}%)"

        # 2. 5분봉에서 연속 상승 확인
        consecutive_rise = 0
        for i in range(-1, -min(8, len(df_5m)), -1):
            if df_5m.iloc[i]['close'] > df_5m.iloc[i-1]['close']:
                consecutive_rise += 1
            else:
                break
        if consecutive_rise < CRASH_RECOVERY_RISE_BARS:
            return False, f"연속상승부족({consecutive_rise}<{CRASH_RECOVERY_RISE_BARS})"

        # 3. RSI 회복 확인 (5분봉)
        recent_5m_rsi = df_5m['rsi'].iloc[-10:]
        min_rsi = recent_5m_rsi.min()
        current_rsi = df_5m.iloc[-1]['rsi']
        if min_rsi > CRASH_RECOVERY_RSI_FROM or current_rsi < CRASH_RECOVERY_RSI_TO:
            return False, f"RSI회복부족(저점{min_rsi:.0f} 현재{current_rsi:.0f})"

        # 4. 거래량 급증
        avg_vol = df_5m.iloc[-11:-1]['volume'].mean()
        cur_vol = df_5m.iloc[-1]['volume']
        if avg_vol > 0 and cur_vol < avg_vol * CRASH_RECOVERY_VOLUME_MULT:
            return False, f"거래량부족({cur_vol/avg_vol:.1f}x<{CRASH_RECOVERY_VOLUME_MULT}x)"

        # 5. 현재가 > 최저가 + 1.5%
        current_price = df_5m.iloc[-1]['close']
        recovery_pct = ((current_price - low_in_range) / low_in_range) * 100
        if recovery_pct < CRASH_RECOVERY_MIN_RISE:
            return False, f"반등폭부족({recovery_pct:.1f}%<{CRASH_RECOVERY_MIN_RISE}%)"

        reason = (f"크래시리커버리! 폭락{drop_pct:.1f}% → 반등{recovery_pct:.1f}% "
                  f"연속{consecutive_rise}봉↑ RSI{min_rsi:.0f}→{current_rsi:.0f} "
                  f"거래량{cur_vol/avg_vol:.1f}x")
        return True, reason

    except Exception as e:
        return False, f"오류: {e}"


def buy_signal(ticker):
    """
    ★★★ v27.0 매수 신호 — 급락 스캐너 + 듀얼 타임프레임 + 크래시 리커버리

    Phase A: 자격 검증 (15분봉 BB 하단 + BB 폭)
             ※ v27.0: 일봉 조건 제거 — Watchlist가 시장 컨텍스트 역할
    Phase B: 반등 확인 (15분봉 점수 + 5분봉 점수 + 감속 보너스)
      - 15분봉: RSI 2봉연속↑, SRSI 골든크로스, 양봉+종가↑, 저가돌파확인
      - 5분봉: 3봉중2봉양봉, RSI 3봉중2봉↑, BB상승추세, 거래량급증
      - 감속 보너스: 하락 모멘텀 감속 패턴 감지 시 +1점 (신규)
      - 매수: 15m≥2 AND 5m≥2 또는 합산≥5
    Phase C: 크래시 리커버리 (Phase A 실패 시 별도 경로)
    """
    try:
        # ── 데이터 수집 ──
        df_15m = get_candles_15m(ticker, count=50)
        if df_15m is None or len(df_15m) < 25:
            return {'signal': False, 'reason': '15분봉 데이터 부족',
                    'entry_price': 0, 'bb_position': 50, 'bb_width_pct': 0}

        df_5m = get_candles_5m(ticker)

        current = df_15m.iloc[-1]
        grade = current_market_grade
        p = get_grade_params(grade)
        _bb_max = p['BUY_BB_MAX']
        _bbw_min = p['BUY_BB_WIDTH_MIN']

        bb_pos = current['bb_position']
        bb_width = current['bb_width']

        base = {
            'signal': False, 'reason': '',
            'entry_price': current['close'],
            'bb_position': bb_pos,
            'bb_width_pct': bb_width,
            'market_grade': grade,
            'entry_type': 'normal',
        }

        # ════════════════════════════════════════
        # Phase A: 자격 검증 (15분봉 BB 위치·폭)
        # ※ 일봉 조건 제거 — Watchlist 필터가 대체
        # ════════════════════════════════════════

        phase_a_passed = True
        phase_a_fail_reason = ""

        # A-1: BB 하단 위치
        if bb_pos > _bb_max:
            phase_a_passed = False
            phase_a_fail_reason = f"BB{bb_pos:.0f}%>{_bb_max}%[{grade}]"

        # A-2: BB 폭
        if phase_a_passed and bb_width < _bbw_min:
            phase_a_passed = False
            phase_a_fail_reason = f"BB폭{bb_width:.1f}%<{_bbw_min}%(횡보)[{grade}]"

        # ════════════════════════════════════════
        # Phase A 실패 → Phase C 크래시 리커버리 확인
        # ════════════════════════════════════════

        if not phase_a_passed:
            if df_5m is not None and len(df_5m) >= 10:
                cr_ok, cr_reason = check_crash_recovery(ticker, df_15m, df_5m)
                if cr_ok:
                    score_5m, details_5m = score_5m_bounce(df_5m)
                    if score_5m >= 2:
                        detail_str = '+'.join(details_5m)
                        return {
                            'signal': True,
                            'reason': f"[CR][{grade}] {cr_reason} | 5m({score_5m}점:{detail_str})",
                            'entry_price': current['close'],
                            'bb_position': bb_pos,
                            'bb_width_pct': bb_width,
                            'market_grade': grade,
                            'entry_type': 'crash_recovery',
                        }

            base['reason'] = phase_a_fail_reason
            return base

        # ════════════════════════════════════════
        # Phase B: 듀얼 타임프레임 반등 확인
        # ════════════════════════════════════════

        # B-1: 15분봉 반등 점수
        score_15m, details_15m = score_15m_bounce(df_15m)

        # B-2: 5분봉 반등 점수
        score_5m = 0
        details_5m = []
        if df_5m is not None and len(df_5m) >= 10:
            score_5m, details_5m = score_5m_bounce(df_5m)

        total_score = score_15m + score_5m

        # B-3: 하락 감속 패턴 보너스 (+1점) ← v27.0 신규
        decel_ok, decel_strength, _ = detect_decel_pattern(df_15m)
        if decel_ok:
            total_score += 1
            details_15m.append(f"감속{decel_strength*100:.0f}%")

        # B-4: 매수 판정
        buy_confirmed = False
        if score_15m >= BUY_BOUNCE_MIN_15M and score_5m >= BUY_BOUNCE_MIN_5M:
            buy_confirmed = True
        elif total_score >= BUY_BOUNCE_TOTAL_MIN:
            buy_confirmed = True

        if not buy_confirmed:
            d15 = '+'.join(details_15m) if details_15m else '없음'
            d5  = '+'.join(details_5m)  if details_5m  else '없음'
            base['reason'] = (f"반등부족 15m({score_15m}점:{d15}) "
                              f"5m({score_5m}점:{d5}) 합산{total_score}[{grade}]")
            return base

        # ═════ 매수 확정 ═════
        d15 = '+'.join(details_15m)
        d5  = '+'.join(details_5m) if details_5m else 'N/A'
        decel_tag = f" 감속{decel_strength*100:.0f}%" if decel_ok else ""
        return {
            'signal': True,
            'reason': (f"[{grade}]BB{bb_pos:.0f}% 폭{bb_width:.1f}%{decel_tag} | "
                       f"15m({score_15m}점:{d15}) 5m({score_5m}점:{d5}) 합{total_score}"),
            'entry_price': current['close'],
            'bb_position': bb_pos,
            'bb_width_pct': bb_width,
            'market_grade': grade,
            'entry_type': 'normal',
        }

    except Exception as e:
        if DEBUG_MODE:
            print(f"{Colors.RED}[Buy Signal] {ticker} 오류: {e}{Colors.ENDC}")
            traceback.print_exc()
        return {'signal': False, 'reason': f'오류: {e}',
                'entry_price': 0, 'bb_position': 50, 'bb_width_pct': 0}


# ============================================================================
# SECTION 14: ★★★ 매도 신호 v26.0 — 동적 손절 + 가속 손절 + 5분봉
# ============================================================================

def check_accel_stop(df_5m):
    """
    ★ v26.0: 가속 손절 패턴 감지 (5분봉 기반).
    3봉 연속 음봉 + RSI < 25 + 직전봉 대비 급락
    → 자연 등락이 아닌 가속 폭락으로 판단

    Returns: (bool triggered, str reason)
    """
    try:
        if df_5m is None or len(df_5m) < 5:
            return False, ""

        # 최근 N봉 연속 음봉 확인
        consecutive_bear = 0
        for i in range(-1, -min(ACCEL_STOP_CONSECUTIVE_BEAR + 1, len(df_5m)), -1):
            if not df_5m.iloc[i]['is_bull']:
                consecutive_bear += 1
            else:
                break

        if consecutive_bear < ACCEL_STOP_CONSECUTIVE_BEAR:
            return False, ""

        current = df_5m.iloc[-1]
        prev = df_5m.iloc[-2]

        # RSI 급락 확인
        if current['rsi'] > ACCEL_STOP_RSI_THRESHOLD:
            return False, ""

        # 직전봉 대비 급락 확인
        if prev['close'] > 0:
            drop = ((current['close'] - prev['close']) / prev['close']) * 100
            if drop > -ACCEL_STOP_DROP_PCT:
                return False, ""
        else:
            return False, ""

        reason = (f"가속폭락감지! {consecutive_bear}연속음봉 "
                  f"RSI{current['rsi']:.0f}<{ACCEL_STOP_RSI_THRESHOLD} "
                  f"직전대비{drop:.1f}%")
        return True, reason

    except Exception:
        return False, ""


def sell_signal(df, buy_price, buy_time=None, held_info=None):
    """
    ★★★ v26.0 매도 신호 — 5단계

    Step 0: 가속 손절 (5분봉 패턴 — 최우선, 보유시간 무시)
    Step 1: 동적 손절 (BB Width 연동 — 보유시간 무시)
    Step 2: 강제 익절
    Step 3: 안전 익절 (RSI↓ + BB 위치 — 5분봉 보조)
    Step 4: 트레일링 (5분봉 보조)

    ★ 매수 당시 파라미터 스냅샷 우선 사용
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

        # ★ 파라미터 결정: 매수 당시 스냅샷 우선
        if held_info and 'param_snapshot' in held_info:
            p = held_info['param_snapshot']
            grade_str = held_info.get('market_grade', '?')
        else:
            grade_str = current_market_grade
            p = get_grade_params(grade_str)

        _force_profit     = p.get('SELL_FORCE_PROFIT',     SELL_FORCE_PROFIT)
        _safe_profit      = p.get('SELL_SAFE_PROFIT',      SELL_SAFE_PROFIT)
        _safe_bb_min      = p.get('SELL_SAFE_BB_MIN',      SELL_SAFE_BB_MIN)
        _trail_activation = p.get('SELL_TRAIL_ACTIVATION', SELL_TRAIL_ACTIVATION)
        _trail_distance   = p.get('SELL_TRAIL_DISTANCE',   SELL_TRAIL_DISTANCE)
        _min_hold_sec     = p.get('BUY_MIN_HOLD_SEC',      BUY_MIN_HOLD_SEC)

        # ★ v26.0: 동적 손절 계산 (매수 당시 BB Width 기준)
        entry_bb_width = held_info.get('entry_bb_width', bb_width) if held_info else bb_width
        _dynamic_stop = calculate_dynamic_stop_loss(entry_bb_width, grade_str)

        base = {
            'signal': False, 'exit_price': current_price,
            'profit_pct': profit_pct, 'bb_position': bb_pos,
            'bb_width_pct': bb_width, 'reason': ''
        }

        # 최소 보유 시간 (손절 계열은 무시)
        min_hold_active = False
        elapsed_sec = 0
        if buy_time:
            elapsed_sec = (datetime.now() - buy_time).total_seconds()
            if elapsed_sec < _min_hold_sec:
                min_hold_active = True

        # ── 5분봉 데이터 (매도 스레드에서 전달됨) ──
        ticker = held_info.get('ticker', '') if held_info else ''
        df_5m = None
        if ticker:
            df_5m = get_candles_5m(ticker)

        # ════════════════════════════════════════
        # Step 0: ★ 가속 손절 (5분봉 패턴 — 최우선, 보유시간 무시)
        # ════════════════════════════════════════
        if df_5m is not None:
            accel_triggered, accel_reason = check_accel_stop(df_5m)
            if accel_triggered and profit_pct < 0:
                return {**base, 'signal': True,
                        'reason': f'{accel_reason} 수익{profit_pct:.2f}%[{grade_str}]'}

        # ════════════════════════════════════════
        # Step 1: 동적 손절 (보유시간 무시)
        # ════════════════════════════════════════
        if profit_pct <= _dynamic_stop:
            return {**base, 'signal': True,
                    'reason': f'동적손절({profit_pct:.2f}%≤{_dynamic_stop:.1f}% '
                              f'BBW{entry_bb_width:.1f}%)[{grade_str}]'}

        # 최소 보유 시간 중 나머지 스킵
        if min_hold_active:
            remaining = int((_min_hold_sec - elapsed_sec) / 60) + 1
            base['reason'] = f'최소보유 대기({remaining}분, 수익{profit_pct:.2f}%)'
            return base

        # ════════════════════════════════════════
        # Step 2: 강제 익절
        # ════════════════════════════════════════
        if profit_pct >= _force_profit:
            return {**base, 'signal': True,
                    'reason': f'강제익절({profit_pct:.2f}%≥{_force_profit}%)[{grade_str}]'}

        # ════════════════════════════════════════
        # Step 3: 안전 익절 (5분봉 보조)
        # ════════════════════════════════════════
        if profit_pct >= _safe_profit:
            rsi_dropping = current['rsi'] < prev['rsi']
            bb_high = bb_pos >= _safe_bb_min

            # 5분봉 보조: 5분봉 RSI도 하락 전환이면 더 확실
            _5m_confirm = False
            if df_5m is not None and len(df_5m) >= 3:
                if df_5m.iloc[-1]['rsi'] < df_5m.iloc[-2]['rsi']:
                    _5m_confirm = True

            if rsi_dropping and bb_high:
                reasons = [f"RSI↓{current['rsi']:.0f}", f"BB{bb_pos:.0f}%≥{_safe_bb_min}%"]
                if _5m_confirm:
                    reasons.append("5mRSI↓확인")
                return {**base, 'signal': True,
                        'reason': f'안전익절({profit_pct:.2f}%, {"+".join(reasons)})[{grade_str}]'}

            # 5분봉만으로 안전익절 (15분봉 아직 미확인이지만 5분봉 과매수 후 하락)
            if _5m_confirm and profit_pct >= _safe_profit * 1.2:
                if df_5m is not None and len(df_5m) >= 2:
                    _5m_bb = df_5m.iloc[-1].get('bb_position', 50)
                    if _5m_bb >= 75:
                        return {**base, 'signal': True,
                                'reason': f'5m안전익절({profit_pct:.2f}%, '
                                          f'5mBB{_5m_bb:.0f}% 5mRSI↓)[{grade_str}]'}

        # ════════════════════════════════════════
        # Step 4: 트레일링 (5분봉 보조 — 더 정밀한 고점 추적)
        # ════════════════════════════════════════
        if profit_pct >= _trail_activation and held_info:
            peak_price = held_info.get('peak_price', buy_price)
            if peak_price > 0:
                drawdown = (peak_price - current_price) / peak_price * 100
                if drawdown >= _trail_distance:
                    # 5분봉 추가 확인: 5분봉도 하락 추세이면 확신 매도
                    _5m_declining = False
                    if df_5m is not None and len(df_5m) >= 3:
                        if (df_5m.iloc[-1]['close'] < df_5m.iloc[-2]['close'] and
                                df_5m.iloc[-2]['close'] < df_5m.iloc[-3]['close']):
                            _5m_declining = True

                    peak_profit = ((peak_price - buy_price) / buy_price) * 100
                    _5m_tag = " 5m↓확인" if _5m_declining else ""
                    return {**base, 'signal': True,
                            'reason': (f'트레일링(고점{peak_profit:.1f}%→{profit_pct:.1f}%, '
                                       f'-{drawdown:.1f}%≥{_trail_distance}%{_5m_tag})[{grade_str}]')}

        # 홀드
        trail_info = ""
        if profit_pct > 0 and held_info:
            peak_price = held_info.get('peak_price', buy_price)
            peak_profit = ((peak_price - buy_price) / buy_price) * 100
            trail_info = f" | 고점{peak_profit:.1f}%"
        stop_info = f" | 손절{_dynamic_stop:.1f}%"
        base['reason'] = f'홀드(수익{profit_pct:.2f}%, BB{bb_pos:.0f}%{trail_info}{stop_info})[{grade_str}]'
        return base

    except Exception as e:
        if DEBUG_MODE:
            print(f"{Colors.RED}[Sell Signal] 오류: {e}{Colors.ENDC}")
            traceback.print_exc()
        return {'signal': False, 'reason': f'오류: {e}',
                'exit_price': 0, 'profit_pct': 0, 'bb_position': 50, 'bb_width_pct': 0}


# ============================================================================
# SECTION 15: 거래소 동기화 (v25.2 로직 유지 + v26.0 entry_bb_width 추가)
# ============================================================================

def sync_held_coins_with_exchange():
    global held_coins

    print(f"\n{Colors.CYAN}{'='*55}")
    print(f"[Init] 기존 보유 코인 동기화 시작...")
    print(f"{'='*55}{Colors.ENDC}")

    balances = None
    for attempt in range(1, 4):
        balances = upbit.get_balances()
        if balances is not None:
            break
        print(f"{Colors.YELLOW}[Init] 잔고 조회 재시도 {attempt}/3...{Colors.ENDC}")
        time.sleep(3)

    if balances is None:
        print(f"{Colors.RED}[Init] 잔고 조회 3회 모두 실패{Colors.ENDC}")
        send_error_notification("Sync Failed", "get_balances() 3회 실패")
        return False

    if len(balances) == 0:
        print(f"{Colors.YELLOW}[Init] 잔고 없음 (빈 계좌){Colors.ENDC}")
        return True

    synced_coins = []
    skipped_coins = []
    unmanaged_coins = []
    managed_tickers = set(FIXED_STABLE_COINS)

    for bal in balances:
        currency = bal.get('currency', '')
        if currency == 'KRW':
            continue
        balance = float(bal.get('balance', 0.0))
        locked = float(bal.get('locked', 0.0))
        total_balance = balance + locked
        if total_balance <= 0:
            continue

        ticker = f"KRW-{currency}"
        is_managed = ticker in managed_tickers
        current_price = get_current_price(ticker)
        if not current_price:
            try:
                current_price = _get_price_rest_single(ticker)
            except Exception:
                current_price = None

        coin_value = total_balance * current_price if current_price else 0.0
        avg_price_raw = float(bal.get('avg_buy_price', 0.0))

        if avg_price_raw > 0:
            avg_price = avg_price_raw
            price_source = "실제매수가"
        elif current_price and current_price > 0:
            avg_price = current_price
            price_source = "현재가대체"
        else:
            if is_managed and total_balance > 0:
                avg_price = 1.0
                price_source = "임시값"
            else:
                skipped_coins.append(f"{currency}(가격조회실패)")
                continue

        should_register = False
        if is_managed and total_balance > 0:
            should_register = True
        elif not is_managed and coin_value >= 5000:
            should_register = True
            unmanaged_coins.append(f"  - {currency}: {total_balance:.6f}개 ({coin_value:,.0f}원)")
        else:
            skipped_coins.append(f"{currency}({coin_value:,.0f}원)")
            continue

        if not should_register:
            continue

        profit_pct = ((current_price - avg_price) / avg_price * 100) if (current_price and avg_price > 0) else 0.0
        peak_price = max(avg_price, current_price) if current_price else avg_price

        # ★ v26.0: entry_bb_width 추가 (동적 손절용)
        entry_bbw = 2.0  # 기본값
        try:
            df_15m = get_candles_15m(ticker, count=25)
            if df_15m is not None and len(df_15m) >= 20:
                entry_bbw = float(df_15m.iloc[-1].get('bb_width', 2.0))
        except Exception:
            pass

        with held_coins_lock:
            held_coins[ticker] = {
                'buy_price': avg_price,
                'buy_time': datetime.now() - timedelta(hours=1),
                'buy_amount': total_balance * avg_price,
                'peak_price': peak_price,
                'peak_time': datetime.now(),
                'buy_reason': f'동기화 ({price_source})',
                'ticker': ticker,
                'buy_order': 1,
                'managed': is_managed,
                'market_grade': current_market_grade,
                'param_snapshot': get_grade_params(),
                'synced': True,
                'entry_bb_width': entry_bbw,
                'entry_type': 'sync',
            }

        managed_tag = "✅ 관리" if is_managed else "⚠️  비관리"
        price_str = f"{current_price:,.0f}원" if current_price else "조회불가"
        synced_coins.append({
            'ticker': ticker, 'currency': currency,
            'balance': total_balance, 'avg_price': avg_price,
            'cur_price': current_price or 0, 'coin_value': coin_value,
            'profit_pct': profit_pct, 'managed': is_managed,
            'price_source': price_source,
        })
        profit_sign = "+" if profit_pct >= 0 else ""
        print(f"  {managed_tag} {currency}: {total_balance:.6f}개 "
              f"@ {avg_price:,.0f}원 [{price_source}]"
              f" → 현재 {price_str} ({profit_sign}{profit_pct:.2f}%)")

    print(f"\n{Colors.GREEN}[Init] 동기화 완료: {len(synced_coins)}개 등록"
          f" | {len(skipped_coins)}개 스킵{Colors.ENDC}")
    if skipped_coins:
        print(f"{Colors.YELLOW}  스킵: {', '.join(skipped_coins)}{Colors.ENDC}")

    _send_sync_discord_report(synced_coins, skipped_coins, unmanaged_coins)
    return True


def _send_sync_discord_report(synced_coins, skipped_coins, unmanaged_coins):
    try:
        krw_balance = upbit.get_balance("KRW") or 0.0
        total_coin_value = sum(c['coin_value'] for c in synced_coins)
        total_assets = krw_balance + total_coin_value
        can_buy = krw_balance >= 5000
        coin_lines = ""
        for c in synced_coins:
            managed_tag = "✅" if c['managed'] else "⚠️"
            pft = c['profit_pct']
            coin_lines += (f"\n  {managed_tag} **{c['currency']}** "
                          f"`{c['balance']:.4f}개` @ `{c['avg_price']:,.0f}원`"
                          f" → `{c['cur_price']:,.0f}원` **{pft:+.2f}%**")
        buy_status = f"✅ 매수 가능 (`{krw_balance:,.0f}원`)" if can_buy else f"🚫 매수 불가"
        msg = (f"\n⚙️ **보유 코인 동기화 완료**\n\n💰 **자산 현황**\n"
               f"├ 총자산: `{total_assets:,.0f}원`\n├ 코인: `{total_coin_value:,.0f}원`\n"
               f"├ 현금: `{krw_balance:,.0f}원`\n└ 매수상태: {buy_status}\n")
        if coin_lines:
            msg += f"\n📦 **동기화 코인 ({len(synced_coins)}개)**{coin_lines}\n"
        msg += f"\n⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
        send_discord_message(msg)
    except Exception as e:
        if DEBUG_MODE:
            print(f"{Colors.RED}[Sync Discord Error] {e}{Colors.ENDC}")


def send_startup_asset_report():
    try:
        balances = upbit.get_balances()
        krw_balance = 0.0
        exchange_coin_balances = {}
        if balances:
            for bal in balances:
                currency = bal.get('currency', '')
                if currency == 'KRW':
                    krw_balance = float(bal.get('balance', 0.0))
                else:
                    b = float(bal.get('balance', 0.0))
                    lk = float(bal.get('locked', 0.0))
                    if b + lk > 0:
                        exchange_coin_balances[currency] = b + lk

        with held_coins_lock:
            held_snapshot = dict(held_coins)

        total_coin_value = 0.0
        for ticker, info in held_snapshot.items():
            try:
                cur_price = get_current_price(ticker)
                if not cur_price:
                    cur_price = info.get('buy_price', 0)
                currency = ticker.replace('KRW-', '')
                bal_amount = exchange_coin_balances.get(currency, 0.0)
                if bal_amount > 0 and cur_price > 0:
                    total_coin_value += bal_amount * cur_price
            except Exception:
                pass

        total_assets = krw_balance + total_coin_value
        can_buy = krw_balance >= 5000

        print(f"\n{Colors.BOLD}{Colors.CYAN}{'━'*55}")
        print(f"  📊 초기 자산 현황")
        print(f"{'━'*55}{Colors.ENDC}")
        print(f"  총 자산:    {total_assets:>15,.0f} 원")
        print(f"  코인 평가:  {total_coin_value:>15,.0f} 원")
        print(f"  현금(KRW): {krw_balance:>15,.0f} 원")
        print(f"  보유 코인:  {len(held_snapshot):>15} 개")

        if held_snapshot:
            print(f"\n  {Colors.BOLD}보유 상세:{Colors.ENDC}")
            for ticker, info in held_snapshot.items():
                coin = ticker.replace('KRW-', '')
                cur_price = get_current_price(ticker) or info.get('buy_price', 0)
                pft = ((cur_price - info['buy_price']) / info['buy_price'] * 100) if info['buy_price'] > 0 else 0
                print(f"    - {coin}: 매수가 {info['buy_price']:,.0f}원 → 현재 {cur_price:,.0f}원 ({pft:+.2f}%)")

        if can_buy:
            print(f"\n  {Colors.GREEN}✅ 매수 가능 상태{Colors.ENDC}")
        else:
            print(f"\n  {Colors.YELLOW}🚫 현금 부족 ({krw_balance:,.0f}원 < 5,000원){Colors.ENDC}")
        print(f"{Colors.CYAN}{'━'*55}{Colors.ENDC}\n")
    except Exception as e:
        print(f"{Colors.RED}[Startup Report Error] {e}{Colors.ENDC}")
        traceback.print_exc()


# ============================================================================
# SECTION 16: 거래 실행 함수 (v26.0: entry_bb_width 기록)
# ============================================================================

def execute_buy(ticker, signal):
    global daily_trade_count, total_trades, daily_buy_count

    try:
        with trade_lock:
            reset_daily_counter()
            if daily_trade_count >= MAX_DAILY_TRADES:
                return False
            can_enter, msg = check_reentry_cooldown(ticker)
            if not can_enter:
                print(f"{Colors.YELLOW}[Buy Limit] {msg}{Colors.ENDC}")
                return False

            entry_price = signal.get('entry_price', 0)
            if entry_price < MIN_BUY_PRICE:
                return False

            with held_coins_lock:
                if ticker in held_coins:
                    return False
                managed_count = sum(1 for info in held_coins.values() if info.get('managed', True))
                if managed_count >= MAX_HOLDINGS:
                    return False
                current_holding_count = managed_count

            try:
                krw_balance = upbit.get_balance("KRW") or 0
            except Exception:
                return False

            if krw_balance < 5000:
                return False

            total_assets = get_total_balance() or krw_balance
            if current_holding_count == 0:
                buy_amount = krw_balance * FIRST_BUY_RATIO * BUY_FEE_BUFFER
                buy_order = '1차'
                buy_order_num = 1
            else:
                buy_amount = krw_balance * BUY_FEE_BUFFER
                buy_order = '2차'
                buy_order_num = 2

            if buy_amount < 5000:
                return False

            coin_name = ticker.replace('KRW-', '')
            print(f"{Colors.CYAN}[Buy Info] {buy_order}매수 {coin_name} | {buy_amount:,.0f}원{Colors.ENDC}")

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
                        'market_grade': signal.get('market_grade', current_market_grade),
                        'param_snapshot': get_grade_params(),
                        'entry_bb_width': signal.get('bb_width_pct', 2.0),
                        'entry_type': signal.get('entry_type', 'normal'),
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
                    else:
                        return False

                result = upbit.buy_market_order(ticker, buy_amount)
                if result is None:
                    return False
                if isinstance(result, dict) and 'error' in result:
                    error_info = result.get('error', {})
                    print(f"{Colors.RED}[Buy Failed] {error_info.get('name')} - {error_info.get('message')}{Colors.ENDC}")
                    return False

                order_uuid = result.get('uuid', '')
                actual_buy_price = signal['entry_price']

                if order_uuid:
                    time.sleep(0.5)
                    order_detail = upbit.wait_order_filled(order_uuid, timeout_sec=5)
                    if order_detail and order_detail['avg_price'] > 0:
                        actual_buy_price = order_detail['avg_price']
                        print(f"{Colors.CYAN}[Buy Detail] 체결가: {actual_buy_price:,.0f}원{Colors.ENDC}")
                    else:
                        time.sleep(0.5)
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
                        'market_grade': signal.get('market_grade', current_market_grade),
                        'param_snapshot': get_grade_params(),
                        'entry_bb_width': signal.get('bb_width_pct', 2.0),
                        'entry_type': signal.get('entry_type', 'normal'),
                    }

                daily_trade_count += 1
                daily_buy_count += 1
                total_trades += 1
                print(f"{Colors.GREEN}[Buy Success] {buy_order}매수 {coin_name} @ {actual_buy_price:,.0f}원{Colors.ENDC}")
                send_buy_notification(ticker, signal, buy_amount, total_assets)
                return True

            except Exception as e:
                error_str = str(e)
                print(f"{Colors.RED}[Buy Failed] {error_str}{Colors.ENDC}")
                send_error_notification("Buy Failed", error_str)
                return False

    except Exception as e:
        print(f"{Colors.RED}[Buy Error] {e}{Colors.ENDC}")
        traceback.print_exc()
        return False


def execute_sell(ticker, signal):
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

            if TEST_MODE:
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

                if not coin_balance:
                    with held_coins_lock:
                        if ticker in held_coins:
                            del held_coins[ticker]
                    send_discord_message(f"\n⚠️ **{coin_name} 수동매도 추정** → 자동제거\n")
                    return False

                coin_amount = float(coin_balance.get('balance', 0))
                if coin_amount <= 0:
                    with held_coins_lock:
                        if ticker in held_coins:
                            del held_coins[ticker]
                    return False

                result = upbit.sell_market_order(ticker, coin_amount)
                if result is None:
                    return False

                sell_uuid = result.get('uuid', '')
                actual_sell_price = sell_price
                if sell_uuid:
                    time.sleep(0.5)
                    order_detail = upbit.wait_order_filled(sell_uuid, timeout_sec=5)
                    if order_detail and order_detail['avg_price'] > 0:
                        actual_sell_price = order_detail['avg_price']

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
                if 'insufficient' in error_str.lower() or 'balance' in error_str.lower():
                    with held_coins_lock:
                        if ticker in held_coins:
                            del held_coins[ticker]
                send_error_notification("Sell Failed", error_str)
                return False

    except Exception as e:
        print(f"{Colors.RED}[Sell Error] {e}{Colors.ENDC}")
        traceback.print_exc()
        return False


# ============================================================================
# SECTION 17: 매수 스레드 (v27.0: 급락 스캐너 + 듀얼 타임프레임)
# ============================================================================

def buy_thread_worker():
    print(f"{Colors.GREEN}[Thread 1] 매수 스레드 시작 ({BUY_THREAD_INTERVAL}초 주기){Colors.ENDC}")
    print(f"{Colors.GREEN}  ├ 급락 스캐너: PlungeScore + 감속 패턴 (v27.0 신규){Colors.ENDC}")
    print(f"{Colors.GREEN}  ├ 듀얼 타임프레임: 15m(위치) + 5m(타이밍){Colors.ENDC}")
    print(f"{Colors.GREEN}  ├ 크래시 리커버리: 폭락→반등 전환 감지{Colors.ENDC}")
    print(f"{Colors.GREEN}  └ KRW < 5,000원 시 매수 스캔 자동 차단{Colors.ENDC}")

    iteration = 0
    last_no_cash_log = 0

    while not stop_event.is_set():
        try:
            iteration += 1

            # ★ v27.0: 15분마다 급락 스캐너 실행 (시간 체크는 함수 내부에서)
            run_sharp_drop_scanner()

            with held_coins_lock:
                managed_count = sum(1 for info in held_coins.values() if info.get('managed', True))
            if managed_count >= MAX_HOLDINGS:
                if DEBUG_MODE and iteration % 30 == 0:
                    print(f"{Colors.YELLOW}[BUY] 최대 보유 도달 ({managed_count}/{MAX_HOLDINGS}){Colors.ENDC}")
                time.sleep(BUY_SLEEP_WHEN_FULL)
                continue

            try:
                krw_balance_now = upbit.get_balance("KRW") or 0.0
            except Exception:
                krw_balance_now = 0.0

            if krw_balance_now < 5000:
                if DEBUG_MODE and iteration % 6 == 0:
                    print(f"{Colors.YELLOW}[BUY] 🚫 매수불가 — 현금 {krw_balance_now:,.0f}원 < 5,000원{Colors.ENDC}")
                now_ts = time.time()
                if now_ts - last_no_cash_log >= 600:
                    last_no_cash_log = now_ts
                    with held_coins_lock:
                        num_held = len(held_coins)
                    _send_no_cash_discord_alert(krw_balance_now, num_held, managed_count)
                time.sleep(BUY_SLEEP_WHEN_FULL)
                continue

            # 매수 차단 시간대
            now = datetime.now()
            block_start = now.replace(hour=BUY_BLOCK_START_HOUR, minute=BUY_BLOCK_START_MINUTE, second=0)
            block_end = now.replace(hour=BUY_BLOCK_END_HOUR, minute=BUY_BLOCK_END_MINUTE, second=0)
            if block_start <= now <= block_end:
                if DEBUG_MODE and iteration % 30 == 0:
                    print(f"{Colors.YELLOW}[BUY] 매수 차단 시간대{Colors.ENDC}")
                time.sleep(BUY_THREAD_INTERVAL)
                continue

            can_trade, loss_msg = check_consecutive_losses()
            if not can_trade:
                time.sleep(BUY_THREAD_INTERVAL)
                continue

            market_ok, market_change = check_market_condition()
            if not market_ok:
                if DEBUG_MODE and iteration % 10 == 0:
                    print(f"{Colors.YELLOW}[BUY] 시장 불안정 ({market_change:.2f}%){Colors.ENDC}")
                time.sleep(BUY_THREAD_INTERVAL)
                continue

            if not check_daily_trade_limit():
                time.sleep(BUY_THREAD_INTERVAL)
                continue

            reset_daily_counter()

            # ★ 시장 등급 갱신
            update_market_grade()
            if DEBUG_MODE and iteration % 6 == 0:
                with watchlist_lock:
                    wl_count = len(sharp_drop_watchlist)
                print(f"{Colors.MAGENTA}[BUY] KRW:{krw_balance_now:,.0f}원 | "
                      f"{get_grade_display_str()} | 급락감시:{wl_count}종{Colors.ENDC}")

            # ★ 코인별 매수 검토
            for ticker in FIXED_STABLE_COINS:
                if stop_event.is_set():
                    return

                with held_coins_lock:
                    if ticker in held_coins:
                        continue

                # ★ v27.0: Watchlist 필터 — 급락 감지된 코인만 진입 검토
                in_watch, watch_info = is_in_watchlist(ticker)
                if not in_watch:
                    continue  # 급락 미감지 코인은 스킵

                # 너무 많이 회복된 경우 제외 (늦은 진입 방지)
                if watch_info:
                    detected_price = watch_info.get('detected_price', 0)
                    cur_price_now  = get_current_price(ticker) or 0
                    if detected_price > 0 and cur_price_now > 0:
                        recovery = (cur_price_now - detected_price) / detected_price * 100
                        if recovery > PLUNGE_MAX_RECOVERY_PCT:
                            coin_name = ticker.replace('KRW-', '')
                            if DEBUG_MODE:
                                print(f"{Colors.YELLOW}[BUY] {coin_name} 이미 {recovery:.1f}% 회복 → 진입 차단{Colors.ENDC}")
                            continue

                can_enter, cooldown_reason = check_reentry_cooldown(ticker)
                if not can_enter:
                    continue

                sig = buy_signal(ticker)

                if sig['signal']:
                    coin_name  = ticker.replace('KRW-', '')
                    entry_type = sig.get('entry_type', 'normal')
                    if entry_type == 'crash_recovery':
                        entry_tag = "🔄CR"
                    elif watch_info:
                        entry_tag = f"📉WL({watch_info.get('stage1_score', 0):.1f})"
                    else:
                        entry_tag = "📈"

                    print(f"\n{Colors.CYAN}{'='*55}")
                    print(f"[BUY SIGNAL] {entry_tag} {coin_name} 매수!")
                    print(f"{'='*55}{Colors.ENDC}")
                    print(f"  📊 BB: {sig['bb_position']:.1f}% | 폭: {sig['bb_width_pct']:.1f}%")
                    print(f"  💰 진입가: {sig['entry_price']:,.0f}원")
                    print(f"  📝 사유: {sig['reason']}")
                    if watch_info:
                        print(f"  🔍 급락도: {watch_info.get('stage1_score',0):.1f}점 "
                              f"({watch_info.get('score_reason','')})")
                    print(f"{Colors.CYAN}{'='*55}{Colors.ENDC}\n")

                    success = execute_buy(ticker, sig)
                    if success:
                        print(f"{Colors.GREEN}[BUY] {coin_name} 매수 완료!{Colors.ENDC}")
                        # 매수 완료 시 Watchlist 에서 제거 (중복 진입 방지)
                        with watchlist_lock:
                            sharp_drop_watchlist.pop(ticker, None)
                    time.sleep(2)

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
            if "RemoteDisconnected" in str(e) or "Connection" in str(e):
                time.sleep(30)
            else:
                time.sleep(BUY_THREAD_INTERVAL)

    print(f"{Colors.GREEN}[Thread 1] 매수 스레드 종료{Colors.ENDC}")


def _send_no_cash_discord_alert(krw_balance, num_held, managed_count):
    try:
        total_coin_value = 0.0
        coin_details = ""
        with held_coins_lock:
            for ticker, info in held_coins.items():
                try:
                    cur_price = get_current_price(ticker) or info['buy_price']
                    bal = upbit.get_balance(ticker) or 0.0
                    coin_val = bal * cur_price
                    total_coin_value += coin_val
                    pft = ((cur_price - info['buy_price']) / info['buy_price']) * 100
                    coin_details += f"\n  └ **{ticker.replace('KRW-','')}** `{cur_price:,.0f}원` {pft:+.2f}%"
                except Exception:
                    pass
        msg = (f"\n⏸️ **매수 일시 차단** — 현금 부족\n\n"
               f"💰 현금: `{krw_balance:,.0f}원`\n📦 보유: `{managed_count}/{MAX_HOLDINGS}개`"
               f"{coin_details}\n\n⏰ {datetime.now().strftime('%H:%M:%S')}\n")
        send_discord_message(msg)
    except Exception:
        pass


# ============================================================================
# SECTION 18: 매도 스레드 (v26.0: 5분봉 통합 + peak 추적)
# ============================================================================

def sell_thread_worker():
    print(f"{Colors.YELLOW}[Thread 2] 매도 스레드 시작 ({SELL_THREAD_INTERVAL}초 주기){Colors.ENDC}")
    print(f"{Colors.YELLOW}  ├ 동적 손절: BB Width 연동{Colors.ENDC}")
    print(f"{Colors.YELLOW}  ├ 가속 손절: 5분봉 폭락 패턴 감지{Colors.ENDC}")
    print(f"{Colors.YELLOW}  └ 5분봉 보조: 트레일링/안전익절 정밀화{Colors.ENDC}")

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

                df = get_candles_15m(ticker, count=50)
                if df is None or len(df) < 20:
                    continue

                current_price = df.iloc[-1]['close']

                # peak_price 실시간 갱신
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
                            print(f"{Colors.GREEN}[SELL] {coin_name} 신고가: "
                                  f"{current_price:,.0f}원 ({old_pft:+.1f}%→{new_pft:+.1f}%){Colors.ENDC}")

                    held_info_copy = held_info.copy()

                # ★ 매도 신호 판단 (sell_signal 내부에서 5분봉도 조회)
                sig = sell_signal(df, buy_price, buy_time, held_info_copy)

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

                    print(f"\n{color}{'='*55}")
                    print(f"[SELL SIGNAL] {coin_name} 매도!")
                    print(f"{'='*55}{Colors.ENDC}")
                    print(f"  {emoji} 수익률: {profit_pct:+.2f}%")
                    print(f"  📊 BB: {sig['bb_position']:.1f}%")
                    print(f"  💰 매도가: {sig['exit_price']:,.0f}원")
                    print(f"  🔍 사유: {sig['reason']}")
                    if buy_time:
                        print(f"  ⏱️ 보유: {format_duration(datetime.now() - buy_time)}")
                    print(f"{color}{'='*55}{Colors.ENDC}\n")

                    success = execute_sell(ticker, sig)
                    if success:
                        print(f"{color}[SELL] {coin_name} 매도 완료! ({profit_pct:+.2f}%){Colors.ENDC}")
                    time.sleep(2)

                else:
                    if DEBUG_MODE and iteration % 60 == 0:
                        coin_name = ticker.replace('KRW-', '')
                        print(f"{Colors.CYAN}[SELL] {coin_name}: {sig['profit_pct']:+.2f}%, {sig['reason']}{Colors.ENDC}")

                time.sleep(0.3)

            time.sleep(SELL_THREAD_INTERVAL)

        except Exception as e:
            print(f"{Colors.RED}[Sell Thread Error] {e}{Colors.ENDC}")
            if DEBUG_MODE:
                traceback.print_exc()
            time.sleep(SELL_THREAD_INTERVAL)

    print(f"{Colors.YELLOW}[Thread 2] 매도 스레드 종료{Colors.ENDC}")


# ============================================================================
# SECTION 19: 모니터 스레드 + 매시간 상세 보고
# ============================================================================

def send_enhanced_statistics_report():
    try:
        portfolio = get_enhanced_portfolio_status()
        now = datetime.now()

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

        mkt_emoji = {True: '🟢🟢'}.get(mkt_score >= 3,
                     {True: '🟢'}.get(mkt_score >= 1,
                     {True: '🟡'}.get(mkt_score >= 0,
                     {True: '🟠'}.get(mkt_score >= -1, '🔴'))))

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
                            dur = format_duration(datetime.now() - bt)
                        pk = held_coins[tk].get('peak_price', cur_p)
                        if pk and pk > 0 and cur_p > 0:
                            peak_drop = ((cur_p - pk) / pk) * 100

                st = calculate_coin_status_for_report(tk)
                pe = "📈" if pft >= 0 else "📉"
                pk_str = f"피크{peak_drop:+.1f}%" if peak_drop < -0.1 else "피크유지"

                # ★ v26.0: 동적 손절 정보 추가
                entry_bbw = 2.0
                with held_coins_lock:
                    if tk in held_coins:
                        entry_bbw = held_coins[tk].get('entry_bb_width', 2.0)
                dyn_stop = calculate_dynamic_stop_loss(entry_bbw)

                hold_section += (
                    f"\n┌ **{cn}** `{price_str}` "
                    f"{pe}`{pft:+.2f}%({pft_str})` ⏱{dur}"
                )
                hold_section += (
                    f"\n└ `D{st['d_change']:+.1f}% "
                    f"BB{st['bb15']:.0f} W{st['bw15']:.1f} "
                    f"R{st['rsi15']:.0f} SR{st['srsi_k']:.0f}{st['srsi_direction']} "
                    f"{pk_str} 손절{dyn_stop:.1f}%`"
                )
        else:
            hold_section = f"\n\n📦 보유 `0/{MAX_HOLDINGS}` (대기중)"

        watch_fixed = [c for c in FIXED_STABLE_COINS if c not in hs]
        watch_section = ""
        if watch_fixed:
            watch_section = f"\n\n📋 **관심 {len(watch_fixed)}개**"
            watch_section += f"\n`{'코인':>4} {'현재가':>7} {'등락':>5} {'BB':>2} {'W':>3} {'R':>2} {'SR':>4}`"
            for tk in watch_fixed:
                cn = tk.replace('KRW-', '')
                st = calculate_coin_status_for_report(tk)
                # 급락 감시 중이면 🔍, 당일 양봉이면 🟢, 아니면 🔴
                if st['in_watchlist']:
                    de = f"🔍{st['wl_score']:.0f}"
                else:
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

            print(f"\n{Colors.MAGENTA}{'='*10}")
            print(f"[Monitor] #{iteration} | {current_time.strftime('%H:%M:%S')}")
            print(f"  {get_grade_display_str()}")
            print(f"  보유: {current_holdings}/{MAX_HOLDINGS} | "
                  f"거래: {total_trades}회 (금일 {daily_trade_count}회) | "
                  f"승률: {win_rate:.1f}%")

            # ★ v26.0: 5분봉 빌더 상태 표시
            with ws_candles_5m_lock:
                _5m_ready = sum(1 for v in ws_candles_5m.values() if v.get('indicators_ready'))
                _5m_total = len(ws_candles_5m)
            print(f"  5m빌더: {_5m_ready}/{_5m_total}코인 준비완료")

            with held_coins_lock:
                for ticker, info in held_coins.items():
                    try:
                        price = get_current_price(ticker)
                        if price:
                            profit = ((price - info['buy_price']) / info['buy_price']) * 100
                            duration = format_duration(current_time - info['buy_time'])
                            coin_name = ticker.replace("KRW-", "")
                            entry_bbw = info.get('entry_bb_width', 2.0)
                            dyn_stop = calculate_dynamic_stop_loss(entry_bbw)
                            print(f"  - {coin_name}: {profit:+.2f}% ({duration}) 손절{dyn_stop:.1f}%")
                    except Exception:
                        pass

            print(f"{'='*10}{Colors.ENDC}\n")

            elapsed = (current_time - last_report_time).total_seconds()
            if elapsed >= 3540 and 0 <= current_time.minute <= 3:
                print(f"{Colors.GREEN}[Monitor] 정시 보고{Colors.ENDC}")
                send_enhanced_statistics_report()
                last_report_time = current_time

            time.sleep(MONITOR_THREAD_INTERVAL)

        except Exception as e:
            print(f"{Colors.RED}[Monitor Error] {e}{Colors.ENDC}")
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

    # 3. ★ v26.0: 5분봉 빌더 REST 초기화
    print(f"{Colors.CYAN}[Init] 5분봉 빌더 REST 초기화 중...{Colors.ENDC}")
    init_count = 0
    for ticker in FIXED_STABLE_COINS:
        if _init_ws_candle_from_rest(ticker):
            init_count += 1
            if DEBUG_MODE:
                print(f"  ✅ {ticker.replace('KRW-', '')} 5분봉 {WS_CANDLE_HISTORY_SIZE}개 로드")
        else:
            print(f"  ❌ {ticker.replace('KRW-', '')} 5분봉 초기화 실패 (REST 폴백 사용)")
        time.sleep(0.2)
    print(f"{Colors.GREEN}[Init] 5분봉 빌더 초기화 완료 ({init_count}/{len(FIXED_STABLE_COINS)}){Colors.ENDC}\n")

    # 4. 초기 자산 현황 보고
    send_startup_asset_report()

    with held_coins_lock:
        synced_coins = len(held_coins)

    try:
        init_krw = upbit.get_balance("KRW") or 0.0
    except Exception:
        init_krw = 0.0
    can_buy_now = init_krw >= 5000

    # 5. WebSocket 시작
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

    # 6. Discord 시작 알림
    buy_mode_str = (
        f"✅ 매수 활성 (`{init_krw:,.0f}원`)"
        if can_buy_now
        else f"🚫 매수 차단 (`{init_krw:,.0f}원` < 5,000원)"
    )
    start_msg = (
        f"\n**🤖 봇 시작** `v{VERSION}`\n\n"
        f"**모드:** `{'TEST MODE' if TEST_MODE else 'LIVE MODE'}`\n"
        f"**관심 코인:** `{len(FIXED_STABLE_COINS)}개`\n"
        f"**최대 보유:** `{MAX_HOLDINGS}개`\n"
        f"**동기화 코인:** `{synced_coins}개`\n"
        f"**5분봉 빌더:** `{init_count}/{len(FIXED_STABLE_COINS)}개 준비`\n"
        f"**현금 상태:** {buy_mode_str}\n"
        f"**WebSocket:** `{'✅ 연결됨' if ws_ok else '⏳ 연결 중'}`\n\n"
        f"**★ v26.0 핵심 개선:**\n"
        f"📊 듀얼 타임프레임 (15m위치 + 5m타이밍)\n"
        f"📉 동적 손절 (BB Width 연동 -3%~-5%)\n"
        f"⚡ 가속 손절 (5분봉 폭락 패턴 감지)\n"
        f"🔄 크래시 리커버리 (폭락→반등 전환)\n"
        f"🚀 WS 5분봉 빌더 (REST 80% 감소)\n\n"
        f"⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
    )
    send_discord_message(start_msg)

    # 7. 스레드 시작
    buy_t = threading.Thread(target=buy_thread_worker, name="Buy", daemon=True)
    sell_t = threading.Thread(target=sell_thread_worker, name="Sell", daemon=True)
    monitor_t = threading.Thread(target=monitor_thread_worker, name="Monitor", daemon=True)

    buy_t.start()
    time.sleep(1)
    sell_t.start()
    time.sleep(1)
    monitor_t.start()

    print(f"{Colors.GREEN}[Main] 모든 스레드 시작 완료 (Thread 1~4){Colors.ENDC}\n")

    # 8. 메인 루프
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

        end_msg = (
            f"\n**🛑 봇 종료**\n\n"
            f"**가동 시간:** `{runtime}`\n"
            f"**총 거래:** `{total_trades}회`\n"
            f"**승:** `{winning_trades}` | **패:** `{losing_trades}`\n"
            f"**승률:** `{final_wr:.1f}%`\n"
            f"**WS 재연결:** `{ws_stat['reconnect_count']}회`\n\n"
            f"⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
        )
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
