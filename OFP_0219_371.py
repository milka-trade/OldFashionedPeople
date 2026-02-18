#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
from dotenv import load_dotenv
load_dotenv()

# ================================================================================
# [공식 API 전환] pyupbit → Upbit 공식 REST API
# pyupbit 의존성 완전 제거, JWT 인증 직접 구현
# ================================================================================

import jwt              #pip install requests PyJWT  (이미 requests는 설치된 상태)
import uuid
import hashlib
import urllib.parse
import json
import websocket          # pip install websocket-client
import pandas as pd
from datetime import datetime, timedelta
import time
import requests
import numpy as np
from collections import deque
import traceback
import threading
from threading import Lock, Event

# ================================================================================
# SECTION 1: Terminal Colors
# ================================================================================

class Colors:
    """Terminal output color codes"""
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


# ================================================================================
# SECTION 2: System Settings
# ================================================================================

DEBUG_MODE = True
TEST_MODE = False
VERSION = "19.0 BOUNCE_NIGHT_WS"

FIXED_STABLE_COINS = [
    "KRW-ETH", "KRW-XRP", "KRW-SOL",
    "KRW-ADA", "KRW-LINK", "KRW-BCH", "KRW-SUI"
]

POSITION_SIZE_RATIO = 0.5
MAX_HOLDINGS = 2
FIRST_BUY_RATIO = 0.5             # 1차 매수 비율 (가용현금의 50%)
BUY_FEE_BUFFER = 0.995
MIN_BUY_PRICE = 500
MAX_DAILY_TRADES = 999

# Thread intervals
BUY_THREAD_INTERVAL = 10
SELL_THREAD_INTERVAL = 5
MONITOR_THREAD_INTERVAL = 60

# API Cache
CACHE_TTL_FAST = 10
CACHE_TTL_NORMAL = 20
CACHE_TTL_SLOW = 30

# ========================================
# [v14.0] 동적 코인 스크리닝 파라미터
# ========================================
DYNAMIC_COIN_ENABLED = True                # 동적 코인 스크리닝 활성화 (False면 고정 7개만)
DYNAMIC_COIN_COUNT = 5                     # 동적 선별 코인 수 (파라미터 N)
DYNAMIC_MIN_CHANGE_PCT = 0.5               # 일봉 최소 등락률 (%) - 양봉+이 값 이상
DYNAMIC_MIN_VOLUME_KRW = 5_000_000_000     # 최소 24시간 거래대금 (원) = 50억
DYNAMIC_SCREEN_INTERVAL = 300              # 스크리닝 주기 (초) = 5분마다 갱신
DYNAMIC_PRECHECK_BOUNCE = True             # BOUNCE 사전 적합성 체크 (BB≤42%)


DAILY_BB_HIGH_FILTER = 60            # 일봉 BB 60% 이상에서 복합 조건 적용
DAILY_BB_CACHE_TTL = 60              # 일봉 데이터 1분 캐싱 (실시간성 강화)
DAILY_BB_FILTER_ENABLED = True       # 필터 활성화
DAILY_BB_NEUTRAL_THRESHOLD = 0.5     # 중립 구간: 시가 대비 ±0.3% 이내

# --- Phase 1: 일봉 등락률 범위 필터 (HL Position 대체) ---
V19_DAY_BULL_CHANGE_MIN = -1.5      # BULLISH 주간 하한 (%)
V19_DAY_BULL_CHANGE_MAX = 3.5       # BULLISH 주간 상한 (%)
V19_DAY_NEUT_CHANGE_MIN = -1.0      # NEUTRAL 주간 하한 (%)
V19_DAY_NEUT_CHANGE_MAX = 3.0       # NEUTRAL 주간 상한 (%)
V19_DAY_BEAR_CHANGE_MIN = -0.5      # BEARISH 주간 하한 (%)
V19_DAY_BEAR_CHANGE_MAX = 2.0       # BEARISH 주간 상한 (%)
V19_NIGHT_CHANGE_MIN = -3.0         # 야간 하한 (대폭 완화)
V19_NIGHT_CHANGE_MAX = 5.0          # 야간 상한 (대폭 완화)

# --- Phase 2: 15분봉 BB 터치 이력 확인 ---
V19_BB_TOUCH_LOOKBACK = 4           # 탐색 범위 (15분봉 4개 = 1시간)
V19_BB_TOUCH_THRESHOLD = 15         # "터치" 판정 BB Position (%)
V19_15M_RSI_MAX = 50                # 15분봉 RSI 상한

# --- Phase 2: 15분봉 BB Position 상한 (레짐별) ---
V19_BULL_BB_MAX = 40
V19_NEUT_BB_MAX = 35
V19_BEAR_BB_MAX = 25
V19_NIGHT_BB_MAX = 30               # v18.0(25%)→v19.0(30%) 완화

# --- Phase 3: 5분봉 반등 신호 기준 ---
V19_5M_BOUNCE_MIN_BULL = 3          # BULLISH: 7개 중 3개
V19_5M_BOUNCE_MIN_NEUT = 3          # NEUTRAL: 7개 중 3개
V19_5M_BOUNCE_MIN_BEAR = 4          # BEARISH: 7개 중 4개
V19_5M_BOUNCE_MIN_NIGHT = 2         # NIGHT: 9개 중 2개
V19_5M_MANDATORY_ONE = True         # 필수 조건 1개 이상 체크

# ================================================================================
# SECTION 3: v7.6 Strategy Parameters
# ================================================================================

# [Buy Strategy]
V75_BUY_BB_MAX = 20
V75_BUY_BB_EXTREME = 10
V75_BUY_MIN_SCORE = 85
V75_BUY_CONSECUTIVE_BULL = 2
V75_BUY_MIN_VOLUME_RATIO = 0.5
V75_BUY_MIN_BB_WIDTH = 2.0
V75_BUY_MAX_CONSECUTIVE_RED = 3

# BB Zone Definition
V76_BB_SAFE_ZONE = 70          # Below 70%: Never sell
V76_BB_MOMENTUM_ZONE = 70      # 70-90%: Check momentum exhaustion
V76_BB_BREAKOUT_ZONE = 90      # 90%+: Upper band breakout zone

# Momentum Exhaustion Conditions
V76_MAX_RSI = 70               # Overbought RSI threshold
V76_EXTREME_RSI = 75           # Extreme overbought RSI
V76_CONSECUTIVE_BEAR = 2       # Consecutive bearish candles
V76_RSI_CONSECUTIVE_DROP = 2   # RSI consecutive drop count
V76_RSI_DROP_THRESHOLD = 3     # RSI drop threshold (points)
V76_BB_UPPER_TOUCH_COUNT = 3   # BB upper (85%+) consecutive touches

# Stop Loss
V76_STOP_LOSS_PCT = -3.0       # -5% stop loss
V76_STOP_LOSS_BB = 10          # Stop loss only active below BB 10%

# Profit Targets
V76_MIN_PROFIT_TARGET = 1.2    # Minimum target profit 1.2%
V76_BREAKOUT_PROFIT = 0.8      # BB 95%+ zone minimum profit 0.8%
V76_OVERBOUGHT_PROFIT = 3.0    # Overbought exit profit 2%

# Exception Observation - Score System from v331
V76_EXCEPTION_SCORE_THRESHOLD = 60 
V76_EXCEPTION_PROFIT_WEIGHT = 30
V76_EXCEPTION_PROFIT_MIN = 4.0
V76_EXCEPTION_VOLUME_WEIGHT = 25
V76_EXCEPTION_VOLUME_MIN = 2.0
V76_EXCEPTION_BULLISH_WEIGHT = 25
V76_EXCEPTION_BULLISH_COUNT = 3
V76_EXCEPTION_BB_WEIGHT = 20
V76_EXCEPTION_MAX_MINUTES = 30

# Legacy Compatibility
V70_BB_HIGH_EXIT = V76_BB_SAFE_ZONE
V70_MAX_RSI = V76_MAX_RSI
V70_CONSECUTIVE_BEAR = V76_CONSECUTIVE_BEAR
V70_STOP_LOSS_PCT = V76_STOP_LOSS_PCT
V70_STOP_LOSS_BB = V76_STOP_LOSS_BB
V70_MIN_PROFIT_TARGET = V76_MIN_PROFIT_TARGET

# ========================================
# [v12.0] 시장 레짐 판별 파라미터
# ========================================
REGIME_ENABLED = True                  # 레짐 시스템 활성화 (False면 기존 v11.1 로직)
REGIME_ADX_THRESHOLD = 25              # 추세 존재 판단 ADX 기준
REGIME_BULLISH_SCORE = 4               # BULLISH 판정 최소 점수
REGIME_NEUTRAL_MIN_SCORE = 1           # NEUTRAL 판정 최소 점수

# BULLISH 레짐 매수 조건 (공격적)
REGIME_BULL_BB_MIN = 5                 # BB 하한 (%)
REGIME_BULL_BB_MAX = 42                # BB 상한 (%) - 현행 35→42 확대
REGIME_BULL_BB_WIDTH = 1.3             # BB 폭 최소 (%) - 현행 1.5→1.3 완화
REGIME_BULL_RSI_MIN = 20               # RSI 최소
REGIME_BULL_REVERSAL_MIN = 2           # 반등 신호 최소 (현행 3→2 완화)
REGIME_BULL_CONSECUTIVE_BEAR_MAX = 3   # 연속 음봉 허용
REGIME_BULL_BULLISH_DAYS_MIN = 1       # 최근 3일 중 최소 양봉 수 (현행 2→1)

# NEUTRAL 레짐 매수 조건 (기본 = 현행과 유사)
REGIME_NEUT_BB_MIN = 5
REGIME_NEUT_BB_MAX = 35
REGIME_NEUT_BB_WIDTH = 1.8             # 현행 양봉1.5/비양봉2.5 → 통합 1.8
REGIME_NEUT_RSI_MIN = 20
REGIME_NEUT_REVERSAL_MIN = 3
REGIME_NEUT_CONSECUTIVE_BEAR_MAX = 3
REGIME_NEUT_BULLISH_DAYS_MIN = 2

# BEARISH 레짐 매수 조건 (보수적)
REGIME_BEAR_BB_MIN = 3
REGIME_BEAR_BB_MAX = 25                # 현행 35→25 축소
REGIME_BEAR_BB_WIDTH = 2.5             # 현행 2.5 유지
REGIME_BEAR_RSI_MIN = 22               # 현행 20→22 강화
REGIME_BEAR_REVERSAL_MIN = 3
REGIME_BEAR_CONSECUTIVE_BEAR_MAX = 2   # 현행 3→2 강화
REGIME_BEAR_BULLISH_DAYS_MIN = 3       # 당일 양봉 필수 (3일중 3일)
REGIME_BEAR_ADX_FILTER = True          # ADX+OBV 이중 필터 활성화
REGIME_BEAR_ADX_STRONG = 30            # 강한 하락 추세 ADX 기준
REGIME_BEAR_DI_RATIO = 1.3             # DI- > DI+ × 이 비율이면 차단

# 레짐 판별 - 일봉 점수 기준
REGIME_DAILY_STRONG_BULL = 1.0         # 강한 양봉 등락률 (%)
REGIME_DAILY_WEAK_BULL = 0.3           # 약한 양봉 등락률 (%)
REGIME_DAILY_WEAK_BEAR = -0.3          # 약한 음봉 등락률 (%)
REGIME_DAILY_STRONG_BEAR = -1.0        # 강한 음봉 등락률 (%)
REGIME_3DAY_STRONG_BULL = 2.0          # 3일 누적 강한 상승 (%)
REGIME_3DAY_WEAK_BEAR = -2.0           # 3일 누적 약한 하락 (%)

MORNING_CLEANUP_ENABLED = True
MORNING_CLEANUP_HOUR = 9
MORNING_CLEANUP_MINUTE = 15
MORNING_CLEANUP_WINDOW = 2           # ±2분 윈도우 (09:13~09:17)
MORNING_CLEANUP_MIN_PROFIT = 0.3     # 최소 수익률 (%)
MORNING_BUY_BLOCK_START_HOUR = 8     # 매수 차단 시작 (08:00)
MORNING_BUY_BLOCK_START_MINUTE = 0
MORNING_BUY_BLOCK_END_HOUR = 9       # 매수 차단 종료 (09:15)
MORNING_BUY_BLOCK_END_MINUTE = 15

BUY_SLEEP_WHEN_FULL = 30             # 보유 꽉 찼을 때 sleep (초)

# [v15.0] 모닝 정리매매 플래그
morning_cleanup_done = False
morning_cleanup_date = None

# ================================================================================
# SECTION 4: Technical Indicator Parameters
# ================================================================================

BB_PERIOD = 20
BB_STD_DEV = 2.0
RSI_PERIOD = 14
ATR_PERIOD = 14
VOLUME_MA_PERIOD = 20


# ================================================================================
# SECTION 5: Reentry Cooldown
# ================================================================================

REENTRY_COOLDOWN_CONFIG = {
    'STOP_LOSS': 30,
    'TARGET_REACHED': 5,
    'HIGH_EXIT': 5,
    'EARLY_EXIT': 15,
    'EMERGENCY': 60,
    'DEFAULT': 10,
    'MOMENTUM_EXIT': 15,
    'EXHAUSTION_EXIT': 10,
    'PPF_EMERGENCY': 8,            # [v20.0] 급락 방어 매도
    'PPF_CONFIRMED': 8,            # [v20.0] 확인된 수익 보호 매도
    'BUAE_TREND_EXIT': 10,         # [v20.0] 추세 약화 매도
}


# ================================================================================
# SECTION 6: Risk Management
# ================================================================================

EMERGENCY_STOP_LOSS = -5.0
MARKET_BREAKER_THRESHOLD = -3.0
CONSECUTIVE_LOSS_LIMIT = 3
COOLDOWN_AFTER_LOSS = 60


# ================================================================================
# SECTION 7: Environment Variables and Global State
# ================================================================================

DISCORD_WEBHOOK_URL = os.getenv("discord_webhook")
ACCESS_KEY = os.getenv("UPBIT_ACCESS_KEY")
SECRET_KEY = os.getenv("UPBIT_SECRET_KEY")

# Thread control
stop_event = Event()
held_coins_lock = Lock()
trade_lock = Lock()
statistics_lock = Lock()
cache_lock = Lock()

# Global state
upbit = None
held_coins = {}
recent_sells = {}
daily_trade_count = 0
last_reset_date = datetime.now().date()
data_cache = {}
cache_timestamps = {}

# Statistics
start_time = datetime.now()
total_trades = 0
winning_trades = 0
losing_trades = 0
total_profit = 0.0
trade_history = deque(maxlen=100)
last_statistics_report = datetime.now()
consecutive_losses = 0
last_loss_time = None

# ============================================================
# 🆕 NEW: Daily Statistics (여기서부터 4줄 추가)
# ============================================================
daily_buy_count = 0
daily_sell_count = 0
daily_winning_trades = 0
daily_losing_trades = 0

# ========================================
# [v8.0] 매도 조건 - 상승 중 홀드
# ========================================
V80_SELL_NEVER_IF_RISING = True        # 상승 중 매도 금지
V80_SELL_RISING_SIGNALS_MIN = 2        # 상승 신호 N개 이상이면 홀드
V80_SELL_MIN_PROFIT = 1.2              # 최소 수익률 (이하면 홀드)

# ========================================
# [v8.0] 매도 조건 - 모멘텀 소진
# ========================================
V80_EXHAUSTION_THRESHOLD = 5           # 소진 판단 점수 (5점 이상이면 소진)
V80_EXHAUSTION_RSI_DIVERGENCE = 2      # RSI 다이버전스 점수
V80_EXHAUSTION_VOLUME_DROP = 2         # 거래량 급감 점수
V80_EXHAUSTION_CONSECUTIVE_BEAR = 3    # 연속 음봉 3개 점수
V80_EXHAUSTION_BB_REJECTION = 2        # BB 상단 이탈 후 복귀 점수
V80_EXHAUSTION_DRAWDOWN = 2            # 고점 대비 하락 점수

# ========================================
# [v8.0] 트레일링 스탑
# ========================================
V80_TRAILING_ENABLED = True            # 트레일링 활성화
V80_TRAILING_ACTIVATION = 2.5          # 트레일링 활성화 수익률 (%)
V80_TRAILING_DISTANCE = 2.0            # 고점 대비 하락률 (%)

# ========================================
# [v8.0] 손절
# ========================================
V80_STOP_LOSS_PCT = -2.5               # 손절률 (%)
V80_STOP_LOSS_BB_MAX = 30              # 손절 적용 BB 상한 (%)

# ========================================
# [v8.0] 극과매수 익절
# ========================================
V80_OVERBOUGHT_BB = 98                 # 극과매수 BB 기준
V80_OVERBOUGHT_MIN_PROFIT = 2.0        # 극과매수 최소 수익

# ========================================
# [v8.0] 데이터 수집
# ========================================
V80_CANDLES_15M_COUNT = 200            # 15분봉 수집 개수
V80_CANDLES_5M_COUNT = 100             # 5분봉 수집 개수
V80_CANDLES_DAILY_COUNT = 50           # 일봉 수집 개수
V80_CACHE_TTL_15M = 45                 # 15분봉 캐시 TTL (초)
V80_CACHE_TTL_5M = 20                  # 5분봉 캐시 TTL (초)


# === v13.0 15분봉 BB 하단 반등 설정 ===
BB_LOWER_APPROACH_PCT = 1.5            # BB 하단 접근 판정 기준 (%)
BB_PERCENT_B_THRESHOLD = 0.15          # %B 하단 영역 기준
BB_LOWER_BOUNCE_RSI_MAX = 35           # 반등 구간 RSI 상한
BB_LOWER_BOUNCE_SRSI_CROSS = True      # Stochastic RSI 골든크로스 체크

# === v13.0 반등 지표 설정 ===
MIN_REVERSAL_SIGNALS = 2               # 최소 반등 신호 개수 (4개 중 2개 이상)
RSI_REVERSAL_THRESHOLD = 35            # RSI 반등 기준선
MACD_HIST_CONVERGE_CHECK = True        # MACD 히스토그램 수렴 확인
CANDLE_REVERSAL_LOOKBACK = 3           # 캔들 반등 확인 기간

# ----------------------------------------
# Phase 1: 일봉 양봉 필터 (대세 상승 확인)
# ----------------------------------------
V10_DAILY_BULLISH_DAYS_MIN = 2         # 최근 3일 중 최소 양봉 수 (3일 중)
V10_DAILY_CONSECUTIVE_BEAR_MAX = 3     # 최대 연속 음봉 허용
V10_DAILY_CHANGE_MAX = 5.0             # 당일 최대 등락률 (%) - 급등 차단
V10_DAILY_CHANGE_MIN = -5.0            # 당일 최소 등락률 (%) - 급락 차단

# ----------------------------------------
# Phase 2: 15분봉 위치 필터 (조정 구간 포착)
# ----------------------------------------
V10_15M_BB_MIN = 5                     # BB 위치 하한 (%) - 극단 제외
V10_15M_BB_MAX = 35                    # BB 위치 상한 (%) - 이미 반등 제외

V10_BB_WIDTH_BULLISH = 1.5             # 양봉일(≥0.5%) BB폭 최소 (%) - 적극적 진입
V10_BB_WIDTH_BEARISH = 2.5             # 비양봉일 BB폭 최소 (%) - 보수적 진입
V10_BB_WIDTH_BULLISH_MIN_CHANGE = 0.5  # 양봉 판정 최소 등락률 (%) - 시가 대비
V10_15M_RSI_MIN = 20                   # 15분봉 RSI 하한 (극단 과매도 회피)

V10_SWING_LOOKBACK = 80                # Swing Low 탐색 범위 (15분봉 개수)
V10_SWING_SIZE = 3                     # 좌우 N개보다 낮아야 저점 인정
V10_HIGHER_LOW_ENABLED = True          # Higher Low 필터 활성화
V10_HIGHER_LOW_TOLERANCE = 0.3         # 허용 오차 (%) - 0.3% 이내면 동일 저점으로 간주

# ----------------------------------------
# Phase 3: 반등 신호 (다중 지표 교차 확인)
# ----------------------------------------
V10_BOUNCE_MIN_SIGNALS = 3             # 5개 중 최소 충족 수
V10_BOUNCE_MANDATORY_ONE = True        # RSI상승 or 양봉 중 1개 필수

# ========================================
# [v11.0] 매도 모멘텀 소진 점수 시스템
# ========================================

# --- 모멘텀 소진 개별 지표 ---
V11_SELL_RSI_DROP_SCORE = 1            # ① RSI 하락 전환 점수
V11_SELL_SRSI_OVERBOUGHT = 75          # ② SRSI 과매수 기준 (%K)
V11_SELL_SRSI_SCORE = 1                # ② SRSI 과매수/데드크로스 점수
V11_SELL_MACD_SCORE = 1                # ③ MACD 음전환/축소 점수
V11_SELL_BEARISH_SCORE = 1             # ④ 음봉 출현 점수
V11_SELL_VOLUME_DECLINE_SCORE = 1      # ⑤ 거래량 감소 추세 점수
V11_SELL_HIGH_DECLINING_SCORE = 1      # ⑥ 고점 연속 하락 점수 (3봉)
V11_SELL_LOWER_HIGH_SCORE = 1          # ⑦ Lower High 확정 점수

# --- BB 구간별 기본 임계치 ---
V11_SELL_THRESHOLD_BB_HIGH = 3         # BB 85%+: 적극 매도 (3점)
V11_SELL_THRESHOLD_BB_MID = 4          # BB 70-85%: 중립 (4점)
V11_SELL_THRESHOLD_BB_LOW = 5          # BB 55-70%: 보수적 (5점)
V11_SELL_BB_NO_SELL_BELOW = 55         # BB 55% 미만: 소진매도 안 함

# --- 수익률 보너스 (임계치 하향) ---
V11_SELL_PROFIT_BONUS_HIGH = 2         # 수익 3%+: 임계치 -2
V11_SELL_PROFIT_BONUS_MID = 1          # 수익 2%+: 임계치 -1
V11_SELL_PROFIT_HIGH_THRESHOLD = 3.0   # 높은 수익 기준 (%)
V11_SELL_PROFIT_MID_THRESHOLD = 2.0    # 중간 수익 기준 (%)

# --- 동적 최소 수익 (모멘텀 소진 연동) ---
V11_SELL_MIN_PROFIT_DEFAULT = 1.2      # 기본 최소 익절 수익 (%)
V11_SELL_MIN_PROFIT_EXHAUSTED = 0.5    # 소진점수 높을 때 최소 익절 (%)
V11_SELL_EXHAUSTION_HIGH = 6           # "높은 소진" 기준 (7점 중 6+)
V11_SELL_EXHAUSTION_MID = 5            # "중간 소진" 기준

# --- 극과매수 긴급 익절 ---
V11_SELL_EXTREME_BB = 95               # 극과매수 BB 기준
V11_SELL_EXTREME_MIN_PROFIT = 1.0      # 극과매수 최소 수익 (1.5→1.0 하향)

# --- Swing High 파라미터 ---
V11_SELL_SWING_LOOKBACK = 60           # Swing High 탐색 범위 (15분봉)
V11_SELL_SWING_SIZE = 2                # 좌우 비교 캔들 수
V11_SELL_LOWER_HIGH_TOLERANCE = 0.3    # Lower High 허용 오차 (%)

# --- 동적 트레일링 스탑 ---
V11_TRAILING_AGGRESSIVE_BB = 85        # 적극 구간 BB 기준
V11_TRAILING_AGGRESSIVE_PROFIT = 3.0   # 적극 구간 수익 기준 (%)
V11_TRAILING_AGGRESSIVE_DISTANCE = 0.5 # 적극 구간 거리 (%)
V11_TRAILING_AGGRESSIVE_ACTIVATION = 1.0  # 적극 구간 활성화 수익 (%)

V11_TRAILING_NORMAL_BB_MIN = 65        # 기본 구간 BB 하한
V11_TRAILING_NORMAL_BB_MAX = 85        # 기본 구간 BB 상한
V11_TRAILING_NORMAL_PROFIT = 1.5       # 기본 구간 수익 기준 (%)
V11_TRAILING_NORMAL_DISTANCE = 0.8     # 기본 구간 거리 (%)
V11_TRAILING_NORMAL_ACTIVATION = 1.5   # 기본 구간 활성화 수익 (%)

V11_TRAILING_CONSERVATIVE_DISTANCE = 1.2  # 보수 구간 거리 (%)
V11_TRAILING_CONSERVATIVE_ACTIVATION = 2.0  # 보수 구간 활성화 수익 (%)

# --- 고점 연속 하락 감지 ---
V11_HIGH_DECLINE_LOOKBACK = 3          # 최근 N봉의 high 비교

# ========================================
# [v17.0] Quick Profit Lock (빠른 수익 확보)
# ========================================
# 핵심 인사이트: 대부분의 암호화폐 움직임은 +2% 부근에서 피크
# 소진점수제(5-7점)를 기다리다가 수익 반납하는 문제 해결
QPL_ENABLED = True                     # Quick Profit Lock 활성화
QPL_TIER1_PROFIT = 1.5                 # Tier1: 수익 1.5%+ → 약세 신호 2개면 즉시 매도
QPL_TIER1_SIGNALS = 2                  # Tier1 필요 약세 신호 수
QPL_TIER2_PROFIT = 2.0                 # Tier2: 수익 2.0%+ → 음봉+RSI하락 단독으로 매도
QPL_TIER3_PROFIT = 3.0                 # Tier3: 수익 3.0%+ → BB 70%+ 도달만으로 매도

# ========================================
# [v17.0] ATR 기반 동적 손절
# ========================================
ATR_STOPLOSS_ENABLED = True            # ATR 손절 활성화
ATR_STOPLOSS_MULTIPLIER = 1.5          # ATR × 이 값 = 손절폭
ATR_STOPLOSS_MIN = -1.5               # 최소 손절률 (%)
ATR_STOPLOSS_MAX = -4.0               # 최대 손절률 (%)

# ========================================
# [v20.0] 이익 보호선 (Profit Protection Floor)
# ========================================
# --- Layer 1: 급락 방어선 ---
PPF_EMERGENCY_ENABLED = True               # 급락 방어선 활성화
PPF_EMERGENCY_PEAK_MIN = 0.5               # 급락 방어 최소 피크 수익 (%)
PPF_RAPID_DROP_PCT = 0.5                   # 급락 판정: 1캔들 내 하락률 (%)
PPF_RAPID_DROP_PCT_BEAR = 0.3              # BEARISH 레짐 급락 판정 (%)
PPF_RAPID_BB_DROP = 10                     # 급락 판정: BB 1캔들 내 하락폭 (%p)
PPF_RAPID_BELOW_MA = True                  # 급락 판정: BB 중단선(MA20) 이탈

# --- Layer 2: 확인된 수익 보호선 ---
PPF_CONFIRMED_ENABLED = True               # 확인된 수익 보호선 활성화

# Tier A: 소폭 수익 (BB 상단 도달 이력 필요)
PPF_TIER_A_PEAK = 0.8                      # 피크 수익 기준 (%)
PPF_TIER_A_BB_REQUIRED = 70                # BB 도달 이력 필요 (%)
PPF_TIER_A_CANDLES = 2                     # 유지 필요 5분봉 캔들 수
PPF_TIER_A_FLOOR = 0.1                     # 보호선 (%)
PPF_TIER_A_FLOOR_BULL = -0.1               # BULLISH 보호선 (%)
PPF_TIER_A_FLOOR_BEAR = 0.3                # BEARISH 보호선 (%)

# Tier B: 중간 수익
PPF_TIER_B_PEAK = 1.5                      # 피크 수익 기준 (%)
PPF_TIER_B_CANDLES = 3                     # 유지 필요 5분봉 캔들 수 (~15분)
PPF_TIER_B_FLOOR = 0.5                     # 보호선 (%)
PPF_TIER_B_FLOOR_BULL = 0.3                # BULLISH 보호선 (%)
PPF_TIER_B_FLOOR_BEAR = 0.8                # BEARISH 보호선 (%)

# Tier C: 대형 수익 (시간 면제)
PPF_TIER_C_PEAK = 2.5                      # 피크 수익 기준 (%)
PPF_TIER_C_FLOOR = 1.0                     # 보호선 (%)
PPF_TIER_C_FLOOR_BULL = 0.7                # BULLISH 보호선 (%)
PPF_TIER_C_FLOOR_BEAR = 1.2                # BEARISH 보호선 (%)

# Tier D: 초대형 수익 (시간 면제)
PPF_TIER_D_PEAK = 4.0                      # 피크 수익 기준 (%)
PPF_TIER_D_FLOOR = 2.0                     # 보호선 (%)
PPF_TIER_D_FLOOR_BULL = 1.5                # BULLISH 보호선 (%)
PPF_TIER_D_FLOOR_BEAR = 2.5                # BEARISH 보호선 (%)

# --- 보호선 냉각기 ---
PPF_COOLDOWN_CYCLES = 2                    # 보호선 하회 후 연속 확인 횟수 (×5초)
PPF_BULLISH_CANDLE_DEFER = True            # 현재 5분봉 양봉이면 발동 유예

# ========================================
# [v20.0] BB 상단 추세 강도 판정
# ========================================
TREND_STRENGTH_BB_ACTIVATE = 70            # 추세 강도 판정 활성 BB 기준 (%)
TREND_STRENGTH_BANDWALK_LEN = 3            # 밴드워크 판정 캔들 수
TREND_STRENGTH_BANDWALK_BB = 70            # 밴드워크 최소 BB (%)
TREND_STRENGTH_STRONG = 4                  # STRONG 판정 최소 점수 (5점 만점)
TREND_STRENGTH_MODERATE_MIN = 2            # MODERATE 하한
TREND_STRENGTH_MODERATE_MAX = 3            # MODERATE 상한

# ========================================
# [v20.0] 5분봉 미세 모멘텀 분석
# ========================================
MICRO_5M_ACTIVATE_BB = 70                  # 5분봉 분석 활성 BB 기준 (%)
MICRO_5M_BEARISH_CANDLES = 2               # BB상단 터치 후 연속 음봉 수
MICRO_5M_VOL_DECLINE_LEN = 3              # 거래량 감소 추세 판정 캔들 수
MICRO_5M_SRSI_DEAD_THRESHOLD = 80          # SRSI 데드크로스 기준 (%K)
MICRO_5M_WEAK_THRESHOLD = 2               # 약세 판정 최소 점수 (4점 만점)

# ========================================
# [v20.0] 통합 매도 판정 매트릭스 수익 기준
# ========================================
BUAE_SELL_MODERATE_WEAK_PROFIT = 1.0       # MODERATE+5분약세: 매도 최소 수익 (%)
BUAE_SELL_WEAK_STRONG_PROFIT = 1.5         # WEAK+5분강세: 매도 최소 수익 (%)
BUAE_SELL_WEAK_WEAK_PROFIT = 0.5           # WEAK+5분약세: 매도 최소 수익 (%)
BUAE_SELL_STRONG_WEAK_PROFIT = 2.0         # STRONG+5분약세: 경계 매도 수익 (%)


# ========================================
# [v17.0] RSI Bullish Divergence (매수 강화)
# ========================================
RSI_DIVERGENCE_ENABLED = True          # RSI 다이버전스 활성화
RSI_DIVERGENCE_LOOKBACK = 30           # 다이버전스 탐색 범위 (15분봉)

# ========================================
# [v18.0] 시간대별 매수 로직 파라미터
# ========================================
TIMEZONE_MODE_ENABLED = True               # 시간대 모드 활성화 (False면 항상 DAY)

# --- 시간대 구분 (KST 기준) ---
NIGHT_MODE_START_HOUR = 23                 # 야간 모드 시작 (23:00)
NIGHT_MODE_START_MINUTE = 0
NIGHT_MODE_END_HOUR = 8                    # 야간 모드 종료 (08:00)
NIGHT_MODE_END_MINUTE = 0                  # → 08:00~09:15는 기존 매수금지 구간

# --- [NIGHT] Phase 1 완화 파라미터 (문을 넓게) ---
NIGHT_SKIP_TODAY_BULLISH = True            # 당일 양봉 체크 스킵 (핵심 변경)
NIGHT_CONSECUTIVE_BEAR_MAX = 3             # 연속 음봉 3일 이상만 차단 (DAY: 레짐별 2~3)
NIGHT_BULLISH_DAYS_MIN = 1                 # 최근 3일 중 1일만 양봉이면 OK (DAY: 레짐별 1~3)

# --- [NIGHT] Phase 2 강화 파라미터 (진입 위치는 정확하게) ---
NIGHT_BB_MIN = 3                           # BB 하한 (극단 하단 보호)
NIGHT_BB_MAX = 25                          # ★ BB 상한 25% (핵심! BB 하단 근처에서만 매수)
NIGHT_BB_WIDTH_MIN = 1.2                   # BB 폭 최소 (DAY 1.3~2.5 대비 소폭 완화)
NIGHT_RSI_MIN = 20                         # RSI 하한 (DAY와 동일, 과매도 보호)
NIGHT_HIGHER_LOW_ENABLED = False           # Higher Low 비활성 (V자 반등은 HL 불필요)
NIGHT_BEAR_ADX_FILTER = False              # BEARISH ADX 필터 비활성

# --- [NIGHT] Phase 3 완화 파라미터 (반등 확인 기준 낮춤) ---
NIGHT_REVERSAL_MIN_SIGNALS = 2             # 최소 신호수 2개 (DAY: 레짐별 2~3)
NIGHT_V_REVERSAL_ENABLED = True            # V-Reversal 전용 신호 활성화
NIGHT_V_REVERSAL_MIN_BEARS = 2             # 직전 최소 연속 음봉 수
NIGHT_LOWER_SHADOW_ENABLED = True          # 하단꼬리 신호 활성화
NIGHT_LOWER_SHADOW_RATIO = 2.0             # 하단꼬리 / 실체 비율 기준

# Stochastic RSI
V10_STOCH_RSI_PERIOD = 14              # Stochastic RSI 기간
V10_STOCH_RSI_K_PERIOD = 3             # %K 스무딩
V10_STOCH_RSI_D_PERIOD = 3             # %D 스무딩
V10_STOCH_RSI_OVERSOLD = 25            # 과매도 기준

# MACD
V10_MACD_FAST = 12                     # 단기 EMA
V10_MACD_SLOW = 26                     # 장기 EMA
V10_MACD_SIGNAL = 9                    # 시그널 EMA

# 거래량
V10_VOLUME_MIN_RATIO = 0.8             # MA20 대비 최소 거래량 비율

# ----------------------------------------
# 매도 파라미터 (v9.1에서 이관, 매도 로직 불변)
# ----------------------------------------
V10_STOP_LOSS_PCT = -2.5               # 손절률 (%)
V10_TARGET_PROFIT = 2.0                # 기본 목표 수익률 (%)
V10_MIN_PROFIT = 1.2                   # 최소 익절 수익률 (%)
V10_TRAILING_ACTIVATION = 1.5          # 트레일링 활성화 수익률 (%)
V10_TRAILING_DISTANCE = 1.0            # 트레일링 고점 대비 하락률 (%)

# 하락 선행 감지 (매도용, 기존 V91 값 유지)
V10_DECLINE_RSI_DIVERGENCE = 2         # RSI 다이버전스 점수
V10_DECLINE_VOLUME_DROP = 2            # 거래량 급감 + 음봉 점수
V10_DECLINE_CONSECUTIVE_BEAR_5M = 2    # 5분봉 연속 음봉 점수
V10_DECLINE_BB_REJECTION = 2           # BB 상단 이탈 후 복귀 점수
V10_DECLINE_DRAWDOWN = 1               # 고점 대비 하락 점수
V10_DECLINE_THRESHOLD = 4              # 익절 권장 임계값

# ========================================
# [v14.0] 동적 코인 스크리닝 글로벌 변수
# ========================================
dynamic_coins_cache = []                   # 동적 선별 코인 캐시
dynamic_coins_last_update = None           # 마지막 스크리닝 시각
dynamic_coins_lock = Lock()                # 스레드 안전 접근용 Lock

# ================================================================================
# SECTION 8: Startup Message
# ================================================================================

VERSION = "19.0 BOUNCE_NIGHT_WS"

print(f"\\n{Colors.BOLD}{Colors.CYAN}{'='*60}")
print(f"EVOLUTION {VERSION}")
print(f"{'='*60}")
print(f"   Thread 1: 매수 ({BUY_THREAD_INTERVAL}초)")
print(f"   Thread 2: 매도 ({SELL_THREAD_INTERVAL}초)")
print(f"   Thread 3: 모니터 ({MONITOR_THREAD_INTERVAL}초)")
print(f"   Thread 4: WebSocket 실시간 현재가 수신")
print(f"   MAX_HOLDINGS: {MAX_HOLDINGS} | 1차:{FIRST_BUY_RATIO:.0%} 2차:전량")
print(f"{'='*60}{Colors.ENDC}\\n")

# ================================================================================
# SECTION 8-B: Upbit 공식 REST API 클라이언트
# [pyupbit 완전 대체] JWT 인증 직접 구현
# ================================================================================

UPBIT_API_BASE = "https://api.upbit.com"

class UpbitAPI:
    """
    Upbit 공식 REST API 클라이언트
    pyupbit.Upbit 클래스를 완전히 대체하며 동일한 인터페이스를 유지합니다.
    
    지원 메서드:
      - get_balance(currency)       : 단일 통화 잔고 조회
      - get_balances()              : 전체 잔고 목록 조회
      - buy_market_order(ticker, amount)  : 시장가 매수
      - sell_market_order(ticker, volume) : 시장가 매도
    """
    
    def __init__(self, access_key, secret_key):
        self.access_key = access_key
        self.secret_key = secret_key
    
    def _make_jwt_token(self, query_params=None):
        """
        JWT 인증 토큰 생성
        
        query_params가 있으면 쿼리 파라미터 해시를 payload에 포함합니다.
        (주문 API처럼 요청 body/params를 검증해야 하는 엔드포인트용)
        """
        payload = {
            'access_key': self.access_key,
            'nonce': str(uuid.uuid4()),
        }
        
        if query_params:
            query_string = urllib.parse.urlencode(query_params).encode()
            m = hashlib.sha512()
            m.update(query_string)
            query_hash = m.hexdigest()
            payload['query_hash'] = query_hash
            payload['query_hash_alg'] = 'SHA512'
        
        token = jwt.encode(payload, self.secret_key, algorithm='HS256')
        # PyJWT 버전에 따라 str 또는 bytes 반환
        if isinstance(token, bytes):
            token = token.decode('utf-8')
        return token
    
    def _auth_headers(self, query_params=None):
        """인증 헤더 반환"""
        token = self._make_jwt_token(query_params)
        return {
            'Authorization': f'Bearer {token}',
            'Content-Type': 'application/json'
        }
    
    def get_balances(self):
        """
        전체 잔고 조회
        
        Returns:
            list: pyupbit와 동일한 형식
                  [{'currency': 'KRW', 'balance': '...', 'locked': '...', 'avg_buy_price': '...', ...}, ...]
            None: 오류 발생 시
        """
        try:
            headers = self._auth_headers()
            resp = requests.get(
                f"{UPBIT_API_BASE}/v1/accounts",
                headers=headers,
                timeout=10
            )
            if resp.status_code == 200:
                return resp.json()
            else:
                if DEBUG_MODE:
                    print(f"{Colors.RED}[API] get_balances 오류: {resp.status_code} {resp.text[:200]}{Colors.ENDC}")
                return None
        except Exception as e:
            if DEBUG_MODE:
                print(f"{Colors.RED}[API] get_balances 예외: {e}{Colors.ENDC}")
            return None
    
    def get_balance(self, currency):
        """
        단일 통화 잔고 조회 (float 반환)
        
        Args:
            currency: 'KRW' 또는 'KRW-ETH' 형식 또는 'ETH' 형식 모두 지원
        
        Returns:
            float: 잔고 수량 (없으면 0.0)
        """
        try:
            # 'KRW-ETH' → 'ETH', 'KRW' → 'KRW' 정규화
            if '-' in str(currency):
                currency = currency.split('-')[1]
            
            balances = self.get_balances()
            if not balances:
                return 0.0
            
            for bal in balances:
                if bal.get('currency') == currency:
                    return float(bal.get('balance', 0.0))
            return 0.0
            
        except Exception as e:
            if DEBUG_MODE:
                print(f"{Colors.RED}[API] get_balance({currency}) 예외: {e}{Colors.ENDC}")
            return 0.0
    
    def buy_market_order(self, ticker, price):
        """
        시장가 매수 (KRW 금액 기준)
        
        Args:
            ticker: 'KRW-ETH' 형식
            price: 매수할 KRW 금액 (float)
        
        Returns:
            dict: 주문 결과 (pyupbit 동일 형식)
            None: 오류 발생 시
        """
        try:
            params = {
                'market': ticker,
                'side': 'bid',
                'price': str(round(price, 0)),
                'ord_type': 'price',
            }
            headers = self._auth_headers(params)
            resp = requests.post(
                f"{UPBIT_API_BASE}/v1/orders",
                json=params,
                headers=headers,
                timeout=10
            )
            result = resp.json()
            if DEBUG_MODE:
                print(f"{Colors.CYAN}[API] buy_market_order {ticker} {price:,.0f}원 → {resp.status_code}{Colors.ENDC}")
            return result
        except Exception as e:
            if DEBUG_MODE:
                print(f"{Colors.RED}[API] buy_market_order 예외: {e}{Colors.ENDC}")
            return None
    
    def sell_market_order(self, ticker, volume):
        """
        시장가 매도 (코인 수량 기준)
        
        Args:
            ticker: 'KRW-ETH' 형식
            volume: 매도할 코인 수량 (float)
        
        Returns:
            dict: 주문 결과 (pyupbit 동일 형식)
            None: 오류 발생 시
        """
        try:
            params = {
                'market': ticker,
                'side': 'ask',
                'volume': str(volume),
                'ord_type': 'market',
            }
            headers = self._auth_headers(params)
            resp = requests.post(
                f"{UPBIT_API_BASE}/v1/orders",
                json=params,
                headers=headers,
                timeout=10
            )
            result = resp.json()
            if DEBUG_MODE:
                print(f"{Colors.CYAN}[API] sell_market_order {ticker} {volume} → {resp.status_code}{Colors.ENDC}")
            return result
        except Exception as e:
            if DEBUG_MODE:
                print(f"{Colors.RED}[API] sell_market_order 예외: {e}{Colors.ENDC}")
            return None
        
    def get_order(self, uuid_str):
        """주문 UUID로 주문 상세 조회"""
        try:
            params = {'uuid': uuid_str}
            headers = self._auth_headers(params)
            resp = requests.get(
                f"{UPBIT_API_BASE}/v1/order",
                params=params,
                headers=headers,
                timeout=10
            )
            if resp.status_code == 200:
                return resp.json()
            else:
                if DEBUG_MODE:
                    print(f"{Colors.RED}[API] get_order 오류: {resp.status_code} {resp.text[:200]}{Colors.ENDC}")
                return None
        except Exception as e:
            if DEBUG_MODE:
                print(f"{Colors.RED}[API] get_order 예외: {e}{Colors.ENDC}")
            return None
    
    def wait_order_filled(self, uuid_str, timeout_sec=5):
        """주문 체결 대기 후 체결 상세 반환 (0.5초 간격 폴링)"""
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
                        'avg_price': avg_price,
                        'paid_fee': total_fee,
                        'executed_volume': total_volume,
                        'state': state
                    }
                
                time.sleep(interval)
                elapsed += interval
            
            # 타임아웃: 마지막 조회 결과라도 반환
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


# ================================================================================
# ================================================================================
# SECTION 8-C: 공개 API 함수 + WebSocket 실시간 가격 시스템
# ================================================================================
#
# 아키텍처:
#   Thread 4 (WebSocket) → ws_price_cache 딕셔너리 업데이트
#   Thread 1,2,3 → get_current_price() → ws_price_cache 우선 조회
#                                       → 캐시 만료/미연결 시 REST fallback
#
# Rate Limit 현황 (공식 Upbit 기준):
#   REST 공개 API  : 초당 10회 (그룹별 각각)
#   WebSocket 연결 : 초당 5회 (연결 요청만 제한, 데이터 수신은 무제한)

UPBIT_WS_URL = "wss://api.upbit.com/websocket/v1"

# ── WebSocket 전역 상태 ────────────────────────────────────────────────────────

# 실시간 현재가 캐시 {ticker: {'price': float, 'ts': float}}
ws_price_cache = {}
ws_price_lock = threading.Lock()

# WebSocket 연결 상태 모니터링
ws_status = {
    'connected': False,       # 현재 연결 여부
    'last_received': 0.0,     # 마지막 메시지 수신 시각 (time.time())
    'reconnect_count': 0,     # 총 재연결 횟수
    'subscribed_tickers': [], # 현재 구독 중인 티커 목록
    'error_count': 0,         # 누적 오류 횟수
}
ws_status_lock = threading.Lock()

# WebSocket 인스턴스 (재연결 시 재사용)
_ws_app = None
_ws_app_lock = threading.Lock()

# WS 캐시 만료 기준: 이 시간 이상 업데이트 없으면 REST fallback
WS_CACHE_STALE_SEC = 30.0    # 30초 이상 수신 없으면 stale 판정

# REST fallback용 Rate Limit 보호
_api_last_call_time = 0.0
_api_call_lock = threading.Lock()

def _rate_limit_wait(min_interval=0.12):
    """REST API Rate Limit 보호 (초당 10회 → 120ms 간격)"""
    global _api_last_call_time
    with _api_call_lock:
        now = time.time()
        elapsed = now - _api_last_call_time
        if elapsed < min_interval:
            time.sleep(min_interval - elapsed)
        _api_last_call_time = time.time()


# ── WebSocket 핵심 함수 ────────────────────────────────────────────────────────

def _get_ws_subscribe_tickers():
    """
    구독할 티커 목록 동적 구성
    고정 코인 7개 + 동적 코인 + held_coins 보유 코인
    (매도 모니터링 누락 방지)
    """
    tickers = set(FIXED_STABLE_COINS)

    # 동적 코인 추가
    try:
        with dynamic_coins_lock:
            for c in dynamic_coins_cache:
                t = c.get('ticker', '')
                if t:
                    tickers.add(t)
    except Exception:
        pass

    # 보유 코인 추가 (매도 모니터링 누락 방지)
    try:
        with held_coins_lock:
            tickers.update(held_coins.keys())
    except Exception:
        pass

    return sorted(tickers)


def _build_subscribe_message(tickers):
    """
    Upbit WebSocket 구독 메시지 생성
    형식: [{"ticket": UUID}, {"type": "ticker", "codes": [...]}]
    """
    return json.dumps([
        {"ticket": str(uuid.uuid4())},
        {
            "type": "ticker",
            "codes": tickers,
            "isOnlyRealtime": False   # 스냅샷 + 실시간 모두 수신
        }
    ])


def _ws_on_open(ws):
    """WebSocket 연결 성공 콜백"""
    tickers = _get_ws_subscribe_tickers()

    with ws_status_lock:
        ws_status['connected'] = True
        ws_status['subscribed_tickers'] = tickers
        ws_status['last_received'] = time.time()

    msg = _build_subscribe_message(tickers)
    ws.send(msg)

    print(f"{Colors.GREEN}[WS] 연결 성공 | 구독 {len(tickers)}개 코인{Colors.ENDC}")
    if DEBUG_MODE:
        names = [t.replace('KRW-', '') for t in tickers]
        print(f"{Colors.GREEN}[WS] 구독 목록: {', '.join(names)}{Colors.ENDC}")


def _ws_on_message(ws, message):
    """
    WebSocket 메시지 수신 콜백
    
    Upbit 응답 필드 (SIMPLE 포맷 미사용 시):
      market      → 티커 ('KRW-ETH')
      trade_price → 현재가 (float)
    """
    try:
        if isinstance(message, bytes):
            message = message.decode('utf-8')

        data = json.loads(message)

        # 에러 응답 처리
        if 'error' in data:
            err = data['error']
            print(f"{Colors.YELLOW}[WS] 서버 오류: {err.get('message', err)}{Colors.ENDC}")
            with ws_status_lock:
                ws_status['error_count'] += 1
            return

        ticker = data.get('cd') or data.get('market')
        price  = data.get('tp') or data.get('trade_price')

        if ticker and price:
            now = time.time()
            with ws_price_lock:
                ws_price_cache[ticker] = {'price': float(price), 'ts': now}
            with ws_status_lock:
                ws_status['last_received'] = now

    except json.JSONDecodeError:
        pass   # 바이너리 PING 프레임 등 무시
    except Exception as e:
        if DEBUG_MODE:
            print(f"{Colors.RED}[WS] on_message 예외: {e}{Colors.ENDC}")


def _ws_on_error(ws, error):
    """WebSocket 오류 콜백"""
    with ws_status_lock:
        ws_status['connected'] = False
        ws_status['error_count'] += 1

    # 정상 종료(stop_event) 시 오류 로그 생략
    if not stop_event.is_set():
        print(f"{Colors.YELLOW}[WS] 오류 발생: {error}{Colors.ENDC}")


def _ws_on_close(ws, close_status_code, close_msg):
    """WebSocket 연결 종료 콜백"""
    with ws_status_lock:
        ws_status['connected'] = False

    if not stop_event.is_set():
        print(f"{Colors.YELLOW}[WS] 연결 종료 "
              f"(code={close_status_code}, msg={close_msg}){Colors.ENDC}")


def _ws_on_ping(ws, message):
    """Upbit 서버 PING 수신 → PONG 자동 전송 (websocket-client 자동 처리)"""
    with ws_status_lock:
        ws_status['last_received'] = time.time()


def _create_ws_app():
    """WebSocketApp 인스턴스 생성"""
    return websocket.WebSocketApp(
        UPBIT_WS_URL,
        on_open    = _ws_on_open,
        on_message = _ws_on_message,
        on_error   = _ws_on_error,
        on_close   = _ws_on_close,
        on_ping    = _ws_on_ping,
    )


def websocket_thread_worker():
    """
    Thread 4: WebSocket 실시간 현재가 수신 스레드
    
    동작 흐름:
      1. WebSocketApp 생성 및 연결 시작 (run_forever)
      2. 연결 끊김 감지 시 재연결 (지수 백오프: 3→6→12→최대30초)
      3. stop_event 수신 시 안전 종료
    
    재연결 전략:
      - 정상 연결 후 갑작스러운 끊김: 3초 후 즉시 재연결
      - 반복 실패: 최대 30초까지 대기 시간 증가
      - stop_event: 즉시 종료
    """
    global _ws_app

    print(f"{Colors.BLUE}[Thread 4] WebSocket 스레드 시작{Colors.ENDC}")

    reconnect_delay = 3      # 초기 재연결 대기 (초)
    max_delay       = 30     # 최대 재연결 대기 (초)

    while not stop_event.is_set():
        try:
            with ws_status_lock:
                ws_status['reconnect_count'] += 1
                cnt = ws_status['reconnect_count']

            if cnt > 1:
                print(f"{Colors.YELLOW}[WS] 재연결 시도 #{cnt} "
                      f"({reconnect_delay}초 대기){Colors.ENDC}")

            with _ws_app_lock:
                _ws_app = _create_ws_app()

            # run_forever: 내부적으로 PING/PONG 자동 관리
            # ping_interval=20: 20초마다 PING 전송 (연결 유지)
            # ping_timeout=10:  10초 내 PONG 없으면 재연결
            _ws_app.run_forever(
                ping_interval = 20,
                ping_timeout  = 10,
                reconnect     = 0,    # 내장 재연결 비활성 (외부에서 제어)
            )

            if stop_event.is_set():
                break

            # 연결 종료 후 재연결 대기
            with ws_status_lock:
                ws_status['connected'] = False

            # 정상 연결 후 끊김이면 짧은 대기, 반복 실패면 지수 증가
            for _ in range(reconnect_delay):
                if stop_event.is_set():
                    break
                time.sleep(1)

            reconnect_delay = min(reconnect_delay * 2, max_delay)

        except Exception as e:
            if not stop_event.is_set():
                print(f"{Colors.RED}[WS] 스레드 예외: {e}{Colors.ENDC}")
                if DEBUG_MODE:
                    traceback.print_exc()

            for _ in range(reconnect_delay):
                if stop_event.is_set():
                    break
                time.sleep(1)

            reconnect_delay = min(reconnect_delay * 2, max_delay)

    # 종료 시 WS 연결 닫기
    with _ws_app_lock:
        if _ws_app:
            try:
                _ws_app.close()
            except Exception:
                pass

    print(f"{Colors.BLUE}[Thread 4] WebSocket 스레드 종료{Colors.ENDC}")


def ws_resubscribe():
    """
    구독 코인 목록 변경 시 재구독 (동적 코인 업데이트 등)
    
    기존 연결을 유지한 채 새 구독 메시지만 전송합니다.
    (연결 끊김 없이 구독 목록만 갱신)
    """
    try:
        with ws_status_lock:
            connected = ws_status['connected']

        if not connected:
            return False

        tickers = _get_ws_subscribe_tickers()
        msg = _build_subscribe_message(tickers)

        with _ws_app_lock:
            if _ws_app and _ws_app.sock:
                _ws_app.send(msg)
                with ws_status_lock:
                    ws_status['subscribed_tickers'] = tickers

                if DEBUG_MODE:
                    print(f"{Colors.CYAN}[WS] 재구독 완료: {len(tickers)}개{Colors.ENDC}")
                return True

    except Exception as e:
        if DEBUG_MODE:
            print(f"{Colors.RED}[WS] 재구독 오류: {e}{Colors.ENDC}")
    return False


def get_ws_status_summary():
    """
    WebSocket 상태 요약 (Discord 보고용)
    
    Returns:
        dict: 상태 정보
    """
    with ws_status_lock:
        connected = ws_status['connected']
        last_rx   = ws_status['last_received']
        reconn    = ws_status['reconnect_count']
        err_cnt   = ws_status['error_count']
        sub_cnt   = len(ws_status['subscribed_tickers'])

    with ws_price_lock:
        cache_cnt = len(ws_price_cache)

    age = time.time() - last_rx if last_rx > 0 else -1

    return {
        'connected':       connected,
        'cache_count':     cache_cnt,
        'subscribed':      sub_cnt,
        'last_rx_sec_ago': round(age, 1),
        'reconnect_count': reconn,
        'error_count':     err_cnt,
    }


# ── 현재가 조회 함수 (WS 우선, REST fallback) ─────────────────────────────────

def get_current_price(ticker):
    """
    현재가 조회 — WebSocket 캐시 우선, REST API fallback
    
    우선순위:
      1. WebSocket 캐시 (연결 중 + 30초 이내 데이터) → 즉시 반환 (0ms)
      2. REST API fallback → HTTP 요청 (~200ms)
    
    기존 코드와 100% 동일한 인터페이스 유지:
      - 단일 티커 → float 반환
      - 리스트    → {ticker: price} 딕셔너리 반환
    
    Args:
        ticker: 'KRW-ETH' 또는 ['KRW-ETH', 'KRW-XRP', ...]
    
    Returns:
        float | dict | None
    """
    try:
        now = time.time()

        # ── 리스트 입력: 배치 처리 ─────────────────────────────────
        if isinstance(ticker, list):
            result = {}
            need_rest = []

            with ws_price_lock:
                for t in ticker:
                    cached = ws_price_cache.get(t)
                    if cached and (now - cached['ts']) < WS_CACHE_STALE_SEC:
                        result[t] = cached['price']
                    else:
                        need_rest.append(t)

            if need_rest:
                rest_prices = _get_price_rest_batch(need_rest)
                if rest_prices:
                    result.update(rest_prices)

            return result if result else None

        # ── 단일 티커: WS 캐시 우선 ────────────────────────────────
        with ws_price_lock:
            cached = ws_price_cache.get(ticker)

        if cached and (now - cached['ts']) < WS_CACHE_STALE_SEC:
            return cached['price']  # WS 캐시 히트 → 즉시 반환

        # WS 캐시 미스 또는 만료 → REST fallback
        return _get_price_rest_single(ticker)

    except Exception as e:
        if DEBUG_MODE:
            print(f"{Colors.RED}[Price] get_current_price({ticker}) 예외: {e}{Colors.ENDC}")
        return None


def _get_price_rest_single(ticker):
    """REST API 단일 현재가 조회 (WS fallback용 내부 함수)"""
    try:
        _rate_limit_wait()
        resp = requests.get(
            f"{UPBIT_API_BASE}/v1/ticker",
            params={'markets': ticker},
            timeout=5
        )
        if resp.status_code != 200:
            return None
        data = resp.json()
        if data:
            price = float(data[0]['trade_price'])
            # REST 조회 결과도 캐시에 저장 (WS 연결 전 초기화 기간 대비)
            with ws_price_lock:
                ws_price_cache[ticker] = {'price': price, 'ts': time.time()}
            return price
        return None
    except Exception as e:
        if DEBUG_MODE:
            print(f"{Colors.RED}[Price] REST single 오류({ticker}): {e}{Colors.ENDC}")
        return None


def _get_price_rest_batch(tickers):
    """REST API 배치 현재가 조회 (WS fallback용 내부 함수)"""
    try:
        _rate_limit_wait()
        resp = requests.get(
            f"{UPBIT_API_BASE}/v1/ticker",
            params={'markets': ','.join(tickers)},
            timeout=5
        )
        if resp.status_code != 200:
            return {}
        now = time.time()
        result = {}
        with ws_price_lock:
            for item in resp.json():
                t = item['market']
                p = float(item['trade_price'])
                result[t] = p
                ws_price_cache[t] = {'price': p, 'ts': now}
        return result
    except Exception as e:
        if DEBUG_MODE:
            print(f"{Colors.RED}[Price] REST batch 오류: {e}{Colors.ENDC}")
        return {}


# ── OHLCV 및 티커 목록 함수 ──────────────────────────────────────────────────

def get_ohlcv(ticker, interval="minute15", count=200, to=None):
    """
    OHLCV 캔들 데이터 조회 (pyupbit.get_ohlcv 완전 대체)

    반환 형식: pyupbit와 동일한 pandas DataFrame
    컬럼: open, high, low, close, volume, value
    인덱스: datetime (KST 기준)

    Args:
        ticker  : 'KRW-ETH'
        interval: 'minute5'|'minute15'|'minute60'|'day' 등
        count   : 조회할 캔들 수 (200 초과 시 자동 분할)
        to      : 특정 시각 이전 데이터 (ISO 8601, None=최신)
    """
    try:
        if interval.startswith('minute'):
            unit = interval.replace('minute', '')
            endpoint = f"{UPBIT_API_BASE}/v1/candles/minutes/{unit}"
        elif interval == 'day':
            endpoint = f"{UPBIT_API_BASE}/v1/candles/days"
        elif interval == 'week':
            endpoint = f"{UPBIT_API_BASE}/v1/candles/weeks"
        elif interval == 'month':
            endpoint = f"{UPBIT_API_BASE}/v1/candles/months"
        else:
            endpoint = f"{UPBIT_API_BASE}/v1/candles/minutes/15"

        all_candles = []
        remaining   = count
        cursor_to   = to

        while remaining > 0:
            fetch_count = min(remaining, 200)
            params = {'market': ticker, 'count': fetch_count}
            if cursor_to:
                params['to'] = cursor_to

            _rate_limit_wait()
            resp = requests.get(endpoint, params=params, timeout=10)

            if resp.status_code != 200:
                if DEBUG_MODE:
                    print(f"{Colors.RED}[API] get_ohlcv {ticker} {interval} "
                          f"오류: {resp.status_code}{Colors.ENDC}")
                break

            candles = resp.json()
            if not candles:
                break

            all_candles.extend(candles)
            remaining -= len(candles)

            if len(candles) < fetch_count:
                break

            oldest    = candles[-1]
            cursor_to = oldest.get('candle_date_time_utc')
            if not cursor_to:
                break

        if not all_candles:
            return None

        rows = [{
            'datetime': c.get('candle_date_time_kst', ''),
            'open':     c.get('opening_price', 0.0),
            'high':     c.get('high_price', 0.0),
            'low':      c.get('low_price', 0.0),
            'close':    c.get('trade_price', 0.0),
            'volume':   c.get('candle_acc_trade_volume', 0.0),
            'value':    c.get('candle_acc_trade_price', 0.0),
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


def get_tickers_krw():
    """KRW 마켓 전체 티커 목록 (pyupbit.get_tickers(fiat='KRW') 대체)"""
    try:
        _rate_limit_wait()
        resp = requests.get(
            f"{UPBIT_API_BASE}/v1/market/all",
            params={'isDetails': 'false'},
            timeout=10
        )
        if resp.status_code != 200:
            return []
        return [m['market'] for m in resp.json() if m['market'].startswith('KRW-')]
    except Exception as e:
        if DEBUG_MODE:
            print(f"{Colors.RED}[API] get_tickers_krw 예외: {e}{Colors.ENDC}")
        return []


# ================================================================================
# SECTION 9: Discord Notification Functions
# ================================================================================

def send_discord_message(message, is_critical=False):
    """Send Discord notification"""
    if not DISCORD_WEBHOOK_URL:
        return False
    
    try:
        header = f"EVOLUTION {VERSION}"
        
        if is_critical:
            full_message = f"@everyone\n**{header}**\n{message}"
        else:
            full_message = f"**{header}**\n{message}"
        
        data = {"content": full_message}
        response = requests.post(DISCORD_WEBHOOK_URL, json=data, timeout=5)
        
        return response.status_code == 204
            
    except Exception as e:
        if DEBUG_MODE:
            print(f"{Colors.RED}[Discord Error] {e}{Colors.ENDC}")
        return False


def send_buy_notification(ticker, signal, buy_amount, total_balance):
    """
    매수 알림 - 개선된 가독성
    [v7.7] buy_mode 표시 추가
    """
    try:
        portfolio = get_enhanced_portfolio_status()
        coin_name = ticker.replace('KRW-', '')
        
        # 한 줄 자산 요약
        asset_line = f"💰 **자산** `총 {portfolio['total_assets']:,.0f}원` | `코인 {portfolio['total_coin_value']:,.0f}원` | `현금 {portfolio['krw_balance']:,.0f}원`"
        
        # BB 폭% 정보 추가
        bb_width_str = ""
        if signal.get('bb_width_pct') is not None:
            bb_width_str = f" [폭{signal['bb_width_pct']:.1f}%]"
        
        mode = signal.get('mode', 'NORMAL')
        mode_emoji = {
            'EXTREME_BOTTOM': '🔥',
            'BOTTOM': '📈',
            'NORMAL': '✅'
        }.get(mode, '✅')
        
        # 매수 정보
        buy_info = f"""{mode_emoji} **{coin_name} 매수완료** [{mode}]
├ **거래** `{buy_amount:,.0f}원` @ `{signal['entry_price']:,.0f}원`
└ 📊 `BB {signal['bb_position']:.0f}%{bb_width_str}` | `신뢰 {signal['confidence']:.0f}%` | **사유:** {signal['reason'].split('(')[0]}"""
        
        # 일봉 BB 정보 추가 (BOTTOM REVERSAL 모드일 때)
        if mode in ['EXTREME_BOTTOM', 'BOTTOM'] and signal.get('daily_bb') is not None:
            buy_info += f"\n├ 🌐 **일봉 BB** `{signal['daily_bb']:.0f}%`"
        
        # 보유 코인 목록 (간결화)
        holdings_text = ""
        if portfolio['coins']:
            holdings_text = f"\n\n📦 **보유 {len(portfolio['coins'])}/{MAX_HOLDINGS}**"
            for coin_info in portfolio['coins']:
                c_name = coin_info['ticker'].replace('KRW-', '')
                holdings_text += f"\n├ **{c_name}** `{coin_info['balance']:.4f}개`"
                holdings_text += f"\n│ └ 💵 `{coin_info['profit_pct']:+.2f}%` `({coin_info['value']:,.0f}원)`"
        
        message = f"""
{'━'*10}
{asset_line}
{'━'*10}

{buy_info}{holdings_text}

⏱ {datetime.now().strftime('%H:%M:%S')}
"""
        send_discord_message(message)
    except Exception as e:
        if DEBUG_MODE:
            print(f"{Colors.RED}[Buy Notification Error] {e}{Colors.ENDC}")


def send_sell_notification(ticker, holding_info, signal, profit_amount, holding_duration):
    """매도 알림 - 개선된 가독성"""
    try:
        portfolio = get_enhanced_portfolio_status()
        coin_name = ticker.replace('KRW-', '')
        
        # 수익/손실 판단
        profit_emoji = "📈" if signal['profit_pct'] > 0 else "📉"
        
        # 한 줄 자산 요약
        asset_line = f"💰 **자산** `총 {portfolio['total_assets']:,.0f}원` | `코인 {portfolio['total_coin_value']:,.0f}원` | `현금 {portfolio['krw_balance']:,.0f}원`"
        
        # BB 폭% 정보 추가
        bb_width_str = ""
        if signal.get('bb_width_pct') is not None:
            bb_width_str = f" [폭{signal['bb_width_pct']:.1f}%]"
        
        # 매도 정보
        sell_info = f"""{profit_emoji} **{coin_name} 매도완료** `({holding_duration} 보유)`
├ **거래** `{holding_info['buy_price']:,.0f}원` → `{signal['exit_price']:,.0f}원`
├ 💵 **{signal['profit_pct']:+.2f}%** `({profit_amount:+,.0f}원)`
└ 📊 `BB {signal['bb_position']:.0f}%{bb_width_str}` | **사유:** {signal['reason'].split('(')[0]}"""
        
        # 남은 보유 코인 (간결화)
        holdings_text = ""
        if portfolio['coins']:
            holdings_text = f"\n\n📦 **보유 {len(portfolio['coins'])}/{MAX_HOLDINGS}**"
            for coin_info in portfolio['coins']:
                c_name = coin_info['ticker'].replace('KRW-', '')
                holdings_text += f"\n├ **{c_name}** `{coin_info['balance']:.4f}개`"
                holdings_text += f"\n│ └ 💵 `{coin_info['profit_pct']:+.2f}%` `({coin_info['value']:,.0f}원)`"
        else:
            holdings_text = f"\n\n📦 **보유** `0/{MAX_HOLDINGS}` (전량 청산)"
        
        # ============================================================
        # 🆕 MODIFIED: 오늘 거래 성과 개선 (전체 블록 교체)
        # ============================================================
        if daily_sell_count == 0:
            trade_summary = f"\n🎯 **금일** 매수 `{daily_buy_count}건` | 매도 `1건` (이번 거래)"
        else:
            daily_win_rate = (daily_winning_trades / daily_sell_count * 100) if daily_sell_count > 0 else 0
            trade_summary = f"\n🎯 **금일** 매수 `{daily_buy_count}건` | 매도 `{daily_sell_count}건` | 승률 `{daily_win_rate:.1f}%`"
        # ============================================================
        
        message = f"""
{'━'*10}
{asset_line}
{'━'*10}

{sell_info}{holdings_text}{trade_summary}

⏰ {datetime.now().strftime('%H:%M:%S')}
"""
        send_discord_message(message)
    except Exception as e:
        if DEBUG_MODE:
            print(f"{Colors.RED}[Sell Notification Error] {e}{Colors.ENDC}")


def send_error_notification(error_type, error_details):
    """Error notification"""
    try:
        message = f"""
**오류 발생**

**유형:** `{error_type}`

**상세 내용:**
```
{error_details[:500]}
```

**시각:** `{datetime.now().strftime('%H:%M:%S')}`
"""
        send_discord_message(message, is_critical=True)
        
    except Exception as e:
        if DEBUG_MODE:
            print(f"{Colors.RED}[Error Notification Failed] {e}{Colors.ENDC}")


def get_coin_analysis(ticker):

    try:
        df = get_candles(ticker, interval='15', count=50)
        
        if df is None or len(df) < 20:
            return None
        
        df = add_indicators(df)
        
        if df is None:
            return None
        
        current_price = df.iloc[-1]['close']
        bb_upper = df.iloc[-1]['BB_UPPER']
        bb_lower = df.iloc[-1]['BB_LOWER']
        bb_range = bb_upper - bb_lower
        
        if bb_range > 0:
            bb_position = ((current_price - bb_lower) / bb_range) * 100
            bb_position = max(0, min(100, bb_position))
        else:
            bb_position = 50
        
        if bb_lower > 0:
            bb_width_pct = ((bb_upper - bb_lower) / bb_lower) * 100
        else:
            bb_width_pct = 0.0
        
        current_rsi = df.iloc[-1]['RSI']
        
        daily_bb_position = None
        try:
            df_daily = get_candles_daily(ticker, count=50)
            if df_daily is not None and len(df_daily) >= 20:
                df_daily = add_indicators(df_daily)
                if df_daily is not None:
                    daily_bb_position = df_daily.iloc[-1]['bb_position']
        except:
            daily_bb_position = None
        

        holding_profit = None
        buy_mode = None
        buy_price = None
        with held_coins_lock:
            if ticker in held_coins:
                buy_price = held_coins[ticker]['buy_price']
                holding_profit = ((current_price - buy_price) / buy_price) * 100
                buy_mode = held_coins[ticker].get('buy_mode', 'NORMAL')
        
        signal = "HOLD"
        reason = ""
        
        if daily_bb_position is not None and daily_bb_position <= 30:
            if bb_position <= 25 and current_rsi <= 40:
                signal = "BUY"
                reason = "🔥일봉바닥+15분저점"
            elif bb_position <= 20:
                signal = "BUY"
                reason = "📈일봉하단반전"
        elif daily_bb_position is not None and daily_bb_position >= DAILY_BB_HIGH_FILTER:
            signal = "HOLD"
            reason = "⚠️일봉고점대기"
        else:
            if bb_position <= 25 and current_rsi <= 35:
                signal = "BUY"
                reason = "저점매수기회"
            elif bb_position >= 80 and current_rsi >= 70:
                signal = "SELL"
                reason = "고점매도시점"
            elif bb_position <= 20:
                signal = "BUY"
                reason = "BB하단근접"
            elif bb_position >= 85:
                signal = "SELL"
                reason = "BB상단돌파"
            else:
                signal = "HOLD"
                reason = "중립구간"
        
        return {
            'ticker': ticker,
            'price': current_price,
            'bb_position': bb_position,
            'bb_width_pct': bb_width_pct,
            'daily_bb_position': daily_bb_position,
            'rsi': current_rsi,
            'signal': signal,
            'reason': reason,
            'holding_profit': holding_profit,
            'buy_mode': buy_mode,
            'buy_price': buy_price
        }
        
    except Exception as e:
        if DEBUG_MODE:
            print(f"{Colors.RED}[Coin Analysis Error] {ticker}: {e}{Colors.ENDC}")
        return None

def format_reversal_detail(reversal):
    """
    [v10.2 신규] Phase 3 반등지표 압축 기호 생성
    
    각 지표의 충족/미충족을 기호로 표시:
    R=RSI상승, S=SRSI, M=MACD, B=양봉(Bullish), V=거래량(Volume)
    
    예시 출력: "R✅S❌M✅B✅V❌(3/5)"
    
    Args:
        reversal: calculate_reversal_score() 반환값
    
    Returns:
        str: 압축된 지표 상태 문자열
    """
    try:
        signals = reversal.get('signals', {})
        score = reversal.get('score', 0)
        
        r = '✅' if signals.get('rsi_rising', False) else '❌'
        s = '✅' if signals.get('stoch_rsi', False) else '❌'
        m = '✅' if signals.get('macd', False) else '❌'
        b = '✅' if signals.get('bullish', False) else '❌'
        v = '✅' if signals.get('volume', False) else '❌'
        
        return f"R{r}S{s}M{m}B{b}V{v}({score}/5)"
    except:
        return f"({reversal.get('score', 0)}/5)"
    
def screen_dynamic_coins():
    """
    [v14.0 신규] 동적 코인 스크리닝
    
    고정 7개 제외, 전체 KRW 마켓에서:
    1차: 일봉 양봉 + 등락률 DYNAMIC_MIN_CHANGE_PCT% 이상
    2차: BOUNCE 또는 SURGE 매수 조건 사전 체크 (BB위치/등락률)
    3차: 거래대금 순 정렬 → 상위 DYNAMIC_COIN_COUNT개 선정
    
    캐시: DYNAMIC_SCREEN_INTERVAL초 간격으로만 갱신
    
    Returns:
        list: [{'ticker': 'KRW-XXX', 'change': float, 'volume_krw': float, 
                'bb_pos': float, 'match_type': str}, ...]
    """
    global dynamic_coins_cache, dynamic_coins_last_update
    
    # 캐시 유효성 체크
    now = datetime.now()
    with dynamic_coins_lock:
        if (dynamic_coins_last_update is not None and 
            (now - dynamic_coins_last_update).total_seconds() < DYNAMIC_SCREEN_INTERVAL):
            return list(dynamic_coins_cache)
    
    if not DYNAMIC_COIN_ENABLED:
        return []
    
    try:
        all_tickers = get_tickers_krw()
        if not all_tickers:
            return list(dynamic_coins_cache) if dynamic_coins_cache else []
        
        fixed_set = set(FIXED_STABLE_COINS)
        candidates = []
        
        for ticker in all_tickers:
            if ticker in fixed_set:
                continue
            
            try:
                df_d = get_candles_daily(ticker, count=25)
                if df_d is None or len(df_d) < 2:
                    continue
                
                latest = df_d.iloc[-1]
                d_open = latest['open']
                d_close = latest['close']
                d_high = latest['high']
                d_low = latest['low']
                
                if d_close <= d_open:
                    continue
                
                change_pct = ((d_close - d_open) / d_open * 100) if d_open > 0 else 0
                if change_pct < DYNAMIC_MIN_CHANGE_PCT:
                    continue
                
                vol_krw = latest.get('value', latest['volume'] * d_close)
                if vol_krw < DYNAMIC_MIN_VOLUME_KRW:
                    continue
                
                df_d_ind = add_indicators(df_d)
                if df_d_ind is None or len(df_d_ind) < 1:
                    continue
                
                bb_pos = df_d_ind.iloc[-1].get('bb_position', 50)
                bb_width = df_d_ind.iloc[-1].get('bb_width', 0)
                
                match_type = None
                
                if DYNAMIC_PRECHECK_BOUNCE:
                    # BOUNCE 가능: BB 하단(≤42%) + BB폭 최소 1.3%
                    if bb_pos <= REGIME_BULL_BB_MAX and bb_width >= REGIME_BULL_BB_WIDTH:
                        match_type = 'BOUNCE'
                
                # [v16.0] SURGE 분기 제거 - BOUNCE만 남김
                
                # 사전 체크 통과한 코인만 후보에 추가
                if match_type is None:
                    continue
                
                candidates.append({
                    'ticker': ticker,
                    'coin': ticker.replace('KRW-', ''),
                    'change': change_pct,
                    'volume_krw': vol_krw,
                    'bb_pos': bb_pos,
                    'bb_width': bb_width,
                    'match_type': match_type
                })
                
                time.sleep(0.05)  # API 부하 제어
                
            except Exception:
                continue
        
        # 거래대금 순 정렬 → 상위 N개
        candidates.sort(key=lambda x: x['volume_krw'], reverse=True)
        selected = candidates[:DYNAMIC_COIN_COUNT]
        
        # 캐시 갱신
        with dynamic_coins_lock:
            dynamic_coins_cache = selected
            dynamic_coins_last_update = now
        
        # 로그 출력
        if selected and DEBUG_MODE:
            coins_str = ", ".join([f"{c['coin']}({c['match_type']}{c['change']:+.1f}%)" for c in selected])
            print(f"{Colors.MAGENTA}[DYNAMIC] 선별 {len(selected)}개: {coins_str}{Colors.ENDC}")
        
        return selected
        
    except Exception as e:
        if DEBUG_MODE:
            print(f"{Colors.RED}[DYNAMIC Screen Error] {e}{Colors.ENDC}")
        return list(dynamic_coins_cache) if dynamic_coins_cache else []

    
def get_active_coin_list():
    """
    [v14.0 신규] 매수 대상 코인 통합 리스트 반환
    
    고정 7개 + 동적 N개를 합쳐서 반환
    중복 제거 보장
    
    Returns:
        list: ['KRW-ETH', 'KRW-XRP', ..., 'KRW-DYNAMIC1', ...]
    """
    active_list = list(FIXED_STABLE_COINS)  # 고정 7개 복사
    
    if DYNAMIC_COIN_ENABLED:
        dynamic = screen_dynamic_coins()
        fixed_set = set(FIXED_STABLE_COINS)
        
        for coin_info in dynamic:
            ticker = coin_info['ticker']
            if ticker not in fixed_set and ticker not in active_list:
                active_list.append(ticker)
    
    return active_list


def calculate_coin_status_for_report(ticker):
    """
    [v14.0] 보고서용 코인 상태 - 객관적 지표 중심으로 간소화
    
    API 효율성: 일봉 1회 + 15분봉 1회 (캐시 활용)
    BOUNCE/SURGE 판정 로직 제거 → 객관적 수치만 반환
    """
    try:
        coin = ticker.replace('KRW-', '')
        
        # === 일봉 데이터 ===
        df_daily = get_candles_daily(ticker, count=50)
        d_change = 0.0
        d_rsi = 50.0
        d_high = 0.0
        d_low = 0.0
        d_open = 0.0
        d_close = 0.0
        d_bb_pos = 50.0
        is_bullish = False
        
        if df_daily is not None and len(df_daily) >= 1:
            df_di = add_indicators(df_daily)
            td = df_daily.iloc[-1]
            d_open = td['open']
            d_close = td['close']
            d_high = td['high']
            d_low = td['low']
            
            is_bullish = d_close >= d_open
            d_change = ((d_close - d_open) / d_open * 100) if d_open > 0 else 0
            
            if df_di is not None and len(df_di) > 0:
                d_rsi = df_di.iloc[-1].get('rsi', 50)
                d_bb_pos = df_di.iloc[-1].get('bb_position', 50)
        
        # 현재가의 일봉 고/저 대비 위치 (%)
        day_range = d_high - d_low
        if day_range > 0:
            hl_position = ((d_close - d_low) / day_range) * 100  # 0%=저점, 100%=고점
        else:
            hl_position = 50.0
        
        # === 15분봉 데이터 ===
        df_15m = get_extended_candles_15m(ticker, count=50)
        bb15 = 50.0
        bw15 = 0.0
        rsi15 = 50.0
        srsi_k = 50.0
        srsi_d = 50.0
        cur_price = d_close
        
        if df_15m is not None and len(df_15m) >= 20:
            c = df_15m.iloc[-1]
            bb15 = c.get('bb_position', 50)
            bw15 = c.get('bb_width', 0)
            rsi15 = c.get('rsi', 50)
            srsi_k = c.get('stoch_rsi_k', 50)
            srsi_d = c.get('stoch_rsi_d', 50)
            cur_price = c.get('close', d_close)
        
        # 동적 코인 여부 확인
        is_dynamic = ticker not in FIXED_STABLE_COINS
        match_type = ''
        if is_dynamic:
            with dynamic_coins_lock:
                for dc in dynamic_coins_cache:
                    if dc['ticker'] == ticker:
                        match_type = dc.get('match_type', '')
                        break
        
        return {
            # 일봉 지표
            'd_change': d_change,
            'd_rsi': d_rsi,
            'd_bb_pos': d_bb_pos,
            'is_bullish': is_bullish,
            'hl_position': hl_position,     # 일봉 고저 대비 현재가 위치
            'd_high': d_high,
            'd_low': d_low,
            
            # 15분봉 지표
            'bb15': bb15,
            'bw15': bw15,
            'rsi15': rsi15,
            'srsi_k': srsi_k,
            'srsi_d': srsi_d,
            'cur_price': cur_price,
            
            # 메타 정보
            'is_dynamic': is_dynamic,
            'match_type': match_type,
            
            # 레거시 호환 필드 (기존 코드 참조용)
            'd_emoji': '🟢' if is_bullish else '🔴',
            'regime': 'N/A', 'r_emo': '⚪', 'r_scr': 0,
            'vol15': 1.0,
            'b_res': '-', 'b_dtl': '', 's_res': '-', 's_dtl': '',
            'final': '대기',
            'daily_status': '양봉' if is_bullish else '음봉',
            'daily_emoji': '🟢' if is_bullish else '🔴',
            'daily_change': d_change,
            'rise_from_low': 0, 'drop_from_high': 0,
            'power_emoji': '➡️', 'power_label': '',
            'p1_pass': False, 'p1_reason': '', 'p2_pass': False, 'p2_reason': '',
            'p3_pass': False, 'p3_reason': '',
            'final_signal': '대기', 'phase_str': '',
            'reject_phase': None, 'reject_detail': None, 'hl_info': ''
        }
        
    except Exception as e:
        if DEBUG_MODE:
            print(f"{Colors.RED}[Status Error] {ticker}: {e}{Colors.ENDC}")
        return {
            'd_change': 0, 'd_rsi': 50, 'd_bb_pos': 50,
            'is_bullish': False, 'hl_position': 50,
            'd_high': 0, 'd_low': 0,
            'bb15': 50, 'bw15': 0, 'rsi15': 50,
            'srsi_k': 50, 'srsi_d': 50, 'cur_price': 0,
            'is_dynamic': False, 'match_type': '',
            # 레거시 호환
            'd_emoji': '⚪', 'regime': 'NEUTRAL', 'r_emo': '⚪', 'r_scr': 0,
            'vol15': 1.0, 'b_res': '오류', 'b_dtl': str(e)[:15],
            's_res': '-', 's_dtl': '', 'final': '오류',
            'daily_status': '?', 'daily_emoji': '⚪', 'daily_change': 0,
            'rise_from_low': 0, 'drop_from_high': 0,
            'power_emoji': '❓', 'power_label': '오류',
            'p1_pass': False, 'p1_reason': '오류',
            'p2_pass': False, 'p2_reason': '-',
            'p3_pass': False, 'p3_reason': '-',
            'final_signal': '오류', 'phase_str': '❓',
            'reject_phase': 'ERR', 'reject_detail': str(e)[:15], 'hl_info': ''
        }


def send_enhanced_statistics_report():
    """
    [v14.0] 매시각 보고서 - 객관적 지표 + 동적 코인 정보
    
    개선 사항:
    ① 자산+성과 (기존 유지)
    ② 보유 코인 (간결 유지)
    ③ 관심 코인: 객관적 지표만 (일봉수익률, BB위치, BB폭, RSI, SRSI, 고저위치)
    ④ 동적 선별 코인 정보 추가
    
    API 효율성: BOUNCE/SURGE 판정 로직 제거 → 지표 조회만
    """
    try:
        portfolio = get_enhanced_portfolio_status()
        now = datetime.now()
        
        # ① 자산+성과
        cpft = 0.0
        if portfolio['coins']:
            tb = sum(c.get('buy_price', 0) * c.get('balance', 0)
                     for c in portfolio['coins'] if c.get('buy_price', 0) > 0)
            if tb > 0:
                cpft = ((portfolio['total_coin_value'] - tb) / tb) * 100
        
        with statistics_lock:
            wr = (winning_trades / total_trades * 100) if total_trades > 0 else 0
            ap = (total_profit / total_trades) if total_trades > 0 else 0
        
        header = (
            f"⏰ **{now.strftime('%H:%M')}** 정시보고\n"
            f"💰 `{portfolio['total_assets']:,.0f}원` "
            f"(코인`{portfolio['total_coin_value']:,.0f}`{cpft:+.1f}% "
            f"현금`{portfolio['krw_balance']:,.0f}`)\n"
            f"🎯 거래`{total_trades}회` 승률`{wr:.0f}%` 평균`{ap:+.2f}%`"
        )
        
        # ② 보유 코인
        ht = ""
        if portfolio['coins']:
            ht = f"\n\n📦 **보유 {len(portfolio['coins'])}/{MAX_HOLDINGS}**"
            for ci in portfolio['coins']:
                tk = ci['ticker']
                cn = tk.replace('KRW-', '')
                pft = ci.get('profit_pct', 0)
                
                ana = get_coin_analysis(tk)
                bb = ana['bb_position'] if ana else 50
                rsi = ana['rsi'] if ana else 50
                
                dur = "-"
                mtag = "📈B"
                with held_coins_lock:
                    if tk in held_coins:
                        bt = held_coins[tk].get('buy_time')
                        if bt:
                            dur = format_duration(now - bt)
                        mtag = "📈B"
                
                pe = "📈" if pft >= 0 else "📉"
                ht += f"\n├ **{cn}** {pe}`{pft:+.2f}%` BB`{bb:.0f}` RSI`{rsi:.0f}` ⏱{dur} [{mtag}]"
        else:
            ht = f"\n\n📦 보유 `0/{MAX_HOLDINGS}` (대기중)"
        
        # ③ 관심 코인 - 객관적 지표만
        hs = set()
        with held_coins_lock:
            hs = set(held_coins.keys())
        watch_fixed = [c for c in FIXED_STABLE_COINS if c not in hs]
        
        wt = ""
        if watch_fixed:
            wt = "\n\n📋 **고정코인**"
            wt += f"\n`{'코인':>5}|{'일봉':>5}|{'BB':>3}|{'폭':>4}|{'RSI':>3}|{'SR':>3}|{'고저':>3}`"
            
            for tk in watch_fixed:
                cn = tk.replace('KRW-', '')
                st = calculate_coin_status_for_report(tk)
                
                de = '🟢' if st['is_bullish'] else '🔴'
                
                # 1줄: 코인 + 객관적 지표
                wt += (
                    f"\n{de}`{cn:>4}"
                    f"|{st['d_change']:+.1f}%"
                    f"|{st['bb15']:2.0f}"
                    f"|{st['bw15']:3.1f}"
                    f"|{st['rsi15']:2.0f}"
                    f"|{st['srsi_k']:2.0f}"
                    f"|{st['hl_position']:2.0f}%`"
                )
        
        # ④ 동적 선별 코인 정보
        dt = ""
        if DYNAMIC_COIN_ENABLED:
            with dynamic_coins_lock:
                dyn_list = list(dynamic_coins_cache)
            
            watch_dynamic = [d for d in dyn_list if d['ticker'] not in hs]
            
            if watch_dynamic:
                dt = f"\n\n🔄 **동적{len(watch_dynamic)}개**"
                dt += f"\n`{'코인':>5}|{'일봉':>5}|{'BB':>3}|{'폭':>4}|{'RSI':>3}|{'SR':>3}|{'고저':>3}|{'타입':>3}`"
                
                for dc in watch_dynamic:
                    tk = dc['ticker']
                    cn = dc['coin']
                    st = calculate_coin_status_for_report(tk)
                    
                    mtype = dc.get('match_type', '?')[:1]  # B or S
                    
                    dt += (
                        f"\n🟢`{cn:>4}"
                        f"|{st['d_change']:+.1f}%"
                        f"|{st['bb15']:2.0f}"
                        f"|{st['bw15']:3.1f}"
                        f"|{st['rsi15']:2.0f}"
                        f"|{st['srsi_k']:2.0f}"
                        f"|{st['hl_position']:2.0f}%"
                        f"|{mtype}`"
                    )
            else:
                dt = f"\n\n🔄 동적 `0개` 선별됨"
        
        msg = f"""
{'─'*25}
{header}{ht}{wt}{dt}
{'─'*25}"""
        
        send_discord_message(msg)
        
    except Exception as e:
        if DEBUG_MODE:
            print(f"{Colors.RED}[Report Error] {e}{Colors.ENDC}")
        traceback.print_exc()

# ================================================================================
# SECTION 10: Utility Functions
# ================================================================================

def format_duration(td):
    """Format timedelta to readable string"""
    try:
        total_seconds = int(td.total_seconds())
        hours = total_seconds // 3600
        minutes = (total_seconds % 3600) // 60
        
        if hours > 0:
            return f"{hours}시간 {minutes}분"
        else:
            return f"{minutes}분"
    except:
        return "0분"


def get_cached_data(cache_key, ttl):
    """Get data from cache"""
    try:
        with cache_lock:
            if cache_key in data_cache and cache_key in cache_timestamps:
                age = (datetime.now() - cache_timestamps[cache_key]).total_seconds()
                if age < ttl:
                    return data_cache[cache_key]
        return None
    except:
        return None


def set_cached_data(cache_key, data):
    """Set data to cache"""
    try:
        with cache_lock:
            data_cache[cache_key] = data
            cache_timestamps[cache_key] = datetime.now()
    except:
        pass


def check_reentry_cooldown(ticker):
    """Check reentry cooldown"""
    try:
        if ticker not in recent_sells:
            return True, "OK"
        
        sell_info = recent_sells[ticker]
        sell_time = sell_info['time']
        sell_reason = sell_info.get('reason', 'DEFAULT')
        
        cooldown_minutes = REENTRY_COOLDOWN_CONFIG.get(sell_reason, 
                                                       REENTRY_COOLDOWN_CONFIG['DEFAULT'])
        
        elapsed = (datetime.now() - sell_time).total_seconds() / 60
        
        if elapsed < cooldown_minutes:
            remaining = int(cooldown_minutes - elapsed)
            return False, f"Cooldown ({remaining}분 남음)"
        
        return True, "OK"
        
    except Exception as e:
        if DEBUG_MODE:
            print(f"{Colors.RED}[Cooldown Check Error] {e}{Colors.ENDC}")
        return True, "OK"


def reset_daily_counter():
    """Reset daily trade counter + morning cleanup flag"""
    global daily_trade_count, last_reset_date
    global daily_buy_count, daily_sell_count, daily_winning_trades, daily_losing_trades
    global morning_cleanup_done, morning_cleanup_date  # [v15.0]
    
    try:
        today = datetime.now().date()
        if today != last_reset_date:
            daily_trade_count = 0
            daily_buy_count = 0
            daily_sell_count = 0
            daily_winning_trades = 0
            daily_losing_trades = 0
            morning_cleanup_done = False       # [v15.0] 날짜 변경 시 리셋
            morning_cleanup_date = today        # [v15.0]
            last_reset_date = today
            print(f"{Colors.CYAN}[Reset] 일일 통계 초기화 완료 ({today}){Colors.ENDC}")
    except:
        pass

def update_peak_tracking(ticker, current_price):
    """Update peak price tracking"""
    try:
        with held_coins_lock:
            if ticker in held_coins:
                if current_price > held_coins[ticker].get('peak_price', 0):
                    held_coins[ticker]['peak_price'] = current_price
                    held_coins[ticker]['peak_time'] = datetime.now()
    except:
        pass


def get_portfolio_status():
    """Get current portfolio status (Legacy - kept for compatibility)"""
    try:
        if not upbit:
            return {
                'krw_balance': 0.0,
                'total_coin_value': 0.0,
                'total_assets': 0.0,
                'coins': []
            }
        
        krw_balance = upbit.get_balance("KRW")
        balances = upbit.get_balances()
        
        coins_info = []
        total_coin_value = 0.0
        
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
                    
                    profit_pct = 0.0
                    if avg_buy_price > 0:
                        profit_pct = ((current_price - avg_buy_price) / avg_buy_price) * 100
                    
                    coins_info.append({
                        'ticker': ticker,
                        'balance': balance,
                        'avg_buy_price': avg_buy_price,
                        'current_price': current_price,
                        'value': coin_value,
                        'profit_pct': profit_pct
                    })
        
        total_assets = krw_balance + total_coin_value
        
        return {
            'krw_balance': krw_balance,
            'total_coin_value': total_coin_value,
            'total_assets': total_assets,
            'coins': coins_info
        }
        
    except Exception as e:
        if DEBUG_MODE:
            print(f"{Colors.RED}[Portfolio Error] {e}{Colors.ENDC}")
        return {
            'krw_balance': 0.0,
            'total_coin_value': 0.0,
            'total_assets': 0.0,
            'coins': []
        }


def get_enhanced_portfolio_status():
    """
    향상된 포트폴리오 상태 조회
    held_coins + Upbit API 통합
    """
    try:
        if not upbit:
            return {
                'krw_balance': 0.0,
                'total_coin_value': 0.0,
                'total_assets': 0.0,
                'coins': []
            }
        
        krw_balance = upbit.get_balance("KRW")
        
        coins_info = []
        total_coin_value = 0.0
        
        with held_coins_lock:
            for ticker, hold_info in held_coins.items():
                try:
                    current_price = get_current_price(ticker)
                    if not current_price:
                        continue
                    
                    currency = ticker.split('-')[1]
                    balance = upbit.get_balance(ticker)
                    
                    if balance <= 0:
                        continue
                    
                    coin_value = balance * current_price
                    total_coin_value += coin_value
                    
                    buy_price = hold_info['buy_price']
                    profit_pct = ((current_price - buy_price) / buy_price) * 100
                    
                    coins_info.append({
                        'ticker': ticker,
                        'balance': balance,
                        'buy_price': buy_price,
                        'current_price': current_price,
                        'value': coin_value,
                        'profit_pct': profit_pct,
                        'buy_time': hold_info.get('buy_time'),
                        'buy_reason': hold_info.get('buy_reason', '알 수 없음')
                    })
                    
                except Exception as e:
                    if DEBUG_MODE:
                        print(f"{Colors.RED}[Portfolio] {ticker} error: {e}{Colors.ENDC}")
                    continue
        
        total_assets = krw_balance + total_coin_value
        
        return {
            'krw_balance': krw_balance,
            'total_coin_value': total_coin_value,
            'total_assets': total_assets,
            'coins': coins_info
        }
        
    except Exception as e:
        if DEBUG_MODE:
            print(f"{Colors.RED}[Enhanced Portfolio Error] {e}{Colors.ENDC}")
        return {
            'krw_balance': 0.0,
            'total_coin_value': 0.0,
            'total_assets': 0.0,
            'coins': []
        }


def get_total_balance():
    """
    [v366.1] 총 자산 조회 - 실제 거래소 API 기반
    
    기존 문제: get_enhanced_portfolio_status()는 held_coins만 순회
    → 동기화 안 된 코인의 평가액이 0으로 계산됨
    
    수정: get_portfolio_status()로 변경 (거래소 실제 잔고 조회)
    → 모든 보유 코인 + KRW 잔고 = 정확한 총자산
    """
    portfolio = get_portfolio_status()
    return portfolio['total_assets']


# ================================================================================
# SECTION 11: Data Collection Functions
# ================================================================================

def get_candles(ticker, interval='15', count=50):
    """Get candle data with cache"""
    try:
        cache_key = f"{ticker}_{interval}_{count}"
        cached = get_cached_data(cache_key, CACHE_TTL_NORMAL)
        
        if cached is not None:
            return cached
        
        if interval == '5':
            df = get_ohlcv(ticker, interval="minute5", count=count)
        elif interval == '15':
            df = get_ohlcv(ticker, interval="minute15", count=count)
        elif interval == '60':
            df = get_ohlcv(ticker, interval="minute60", count=count)
        else:
            df = get_ohlcv(ticker, interval="minute15", count=count)
        
        if df is not None and len(df) >= 20:
            set_cached_data(cache_key, df)
            return df
        
        return None
        
    except Exception as e:
        if DEBUG_MODE:
            print(f"{Colors.RED}[Candle Error] {ticker} {e}{Colors.ENDC}")
        return None

# ========================================
# [NEW] Daily Timeframe Data Collection
# ========================================

def get_candles_daily(ticker, count=50):

    try:
        # 캐싱 체크 (일봉은 5분간 캐싱)
        cache_key = f"{ticker}_daily_{count}"
        cached = get_cached_data(cache_key, DAILY_BB_CACHE_TTL)
        
        if cached is not None:
            return cached
        
        # API 호출
        df = get_ohlcv(ticker, interval="day", count=count)
        
        if df is not None and len(df) >= 20:
            set_cached_data(cache_key, df)
            return df
        
        return None
        
    except Exception as e:
        if DEBUG_MODE:
            print(f"{Colors.RED}[Daily Candle Error] {ticker} {e}{Colors.ENDC}")
        return None
    
# ================================================================================
# SECTION 11-A: [v8.0] Extended Data Collection (200개 캔들)
# ================================================================================

def get_extended_candles_15m(ticker, count=200):
    """
    [v8.0] 15분봉 200개 수집 (모멘텀 분석용)
    
    Args:
        ticker: 코인 티커 (예: "KRW-XRP")
        count: 수집할 캔들 개수 (기본 200개)
    
    Returns:
        DataFrame: 지표 포함된 15분봉 데이터 or None
    """
    try:
        cache_key = f"{ticker}_15m_ext_{count}"
        cached = get_cached_data(cache_key, V80_CACHE_TTL_15M)
        
        if cached is not None:
            return cached
        
        df = get_ohlcv(ticker, interval="minute15", count=count)
        
        if df is not None and len(df) >= 50:
            df = add_indicators(df)
            if df is not None:
                set_cached_data(cache_key, df)
                return df
        
        return None
        
    except Exception as e:
        if DEBUG_MODE:
            print(f"{Colors.RED}[Extended 15m Error] {ticker}: {e}{Colors.ENDC}")
        return None


def get_extended_candles_5m(ticker, count=100):
    """
    Args:
        ticker: 코인 티커
        count: 수집할 캔들 개수 (기본 100개)
    
    Returns:
        DataFrame: 지표 포함된 5분봉 데이터 or None
    """
    try:
        cache_key = f"{ticker}_5m_ext_{count}"
        cached = get_cached_data(cache_key, V80_CACHE_TTL_5M)
        
        if cached is not None:
            return cached
        
        df = get_ohlcv(ticker, interval="minute5", count=count)
        
        if df is not None and len(df) >= 30:
            df = add_indicators(df)
            if df is not None:
                set_cached_data(cache_key, df)
                return df
        
        return None
        
    except Exception as e:
        if DEBUG_MODE:
            print(f"{Colors.RED}[Extended 5m Error] {ticker}: {e}{Colors.ENDC}")
        return None
    
# ================================================================================
# SECTION 12: Technical Indicator Calculation
# ================================================================================

def calculate_rsi(series, period=RSI_PERIOD):
    """Calculate RSI"""
    try:
        delta = series.diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
        
        rs = gain / loss
        rsi = 100 - (100 / (1 + rs))
        
        return rsi
    except:
        return pd.Series([50] * len(series), index=series.index)

def calculate_stochastic_rsi(series, rsi_period=14, stoch_period=14, k_period=3, d_period=3):
    """
    [v10.0] Stochastic RSI 계산
    
    RSI에 Stochastic 오실레이터를 적용하여
    과매도/과매수를 더 민감하게 감지
    
    Args:
        series: 종가 시리즈
        rsi_period: RSI 기간 (기본 14)
        stoch_period: Stochastic 기간 (기본 14)
        k_period: %K 스무딩 (기본 3)
        d_period: %D 스무딩 (기본 3)
    
    Returns:
        tuple: (stoch_rsi_k, stoch_rsi_d) 두 시리즈
    """
    try:
        # RSI 계산
        delta = series.diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=rsi_period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=rsi_period).mean()
        rs = gain / loss
        rsi = 100 - (100 / (1 + rs))
        
        # Stochastic RSI = (RSI - RSI_lowest) / (RSI_highest - RSI_lowest)
        rsi_min = rsi.rolling(window=stoch_period).min()
        rsi_max = rsi.rolling(window=stoch_period).max()
        
        rsi_range = rsi_max - rsi_min
        # 0으로 나누기 방지
        rsi_range = rsi_range.replace(0, np.nan)
        
        stoch_rsi = ((rsi - rsi_min) / rsi_range) * 100
        stoch_rsi = stoch_rsi.fillna(50)  # NaN은 중립값
        
        # %K = Stoch RSI의 SMA
        stoch_rsi_k = stoch_rsi.rolling(window=k_period).mean()
        # %D = %K의 SMA
        stoch_rsi_d = stoch_rsi_k.rolling(window=d_period).mean()
        
        return stoch_rsi_k.fillna(50), stoch_rsi_d.fillna(50)
        
    except Exception:
        length = len(series)
        neutral = pd.Series([50] * length, index=series.index)
        return neutral, neutral


def calculate_macd(series, fast=12, slow=26, signal=9):
    """
    [v10.0] MACD 계산
    
    Moving Average Convergence Divergence
    모멘텀 전환 감지용
    
    Args:
        series: 종가 시리즈
        fast: 단기 EMA 기간 (기본 12)
        slow: 장기 EMA 기간 (기본 26)
        signal: 시그널 EMA 기간 (기본 9)
    
    Returns:
        tuple: (macd_line, signal_line, histogram) 세 시리즈
    """
    try:
        ema_fast = series.ewm(span=fast, adjust=False).mean()
        ema_slow = series.ewm(span=slow, adjust=False).mean()
        
        macd_line = ema_fast - ema_slow
        signal_line = macd_line.ewm(span=signal, adjust=False).mean()
        histogram = macd_line - signal_line
        
        return macd_line, signal_line, histogram
        
    except Exception:
        length = len(series)
        zero = pd.Series([0] * length, index=series.index)
        return zero, zero, zero


def calculate_bollinger_bands(df, period=BB_PERIOD, std_dev=BB_STD_DEV):
    """Calculate Bollinger Bands"""
    try:
        close = df['close']
        
        bb_middle = close.rolling(window=period).mean()
        bb_std = close.rolling(window=period).std()
        
        bb_upper = bb_middle + (bb_std * std_dev)
        bb_lower = bb_middle - (bb_std * std_dev)
        
        bb_position = ((close - bb_lower) / (bb_upper - bb_lower) * 100).clip(0, 120)
        bb_width = ((bb_upper - bb_lower) / bb_middle * 100)
        
        return bb_upper, bb_middle, bb_lower, bb_position, bb_width
        
    except Exception as e:
        if DEBUG_MODE:
            print(f"{Colors.RED}[BB Calculation Error] {e}{Colors.ENDC}")
        return None, None, None, None, None


def add_indicators(df):
    """
    [v10.0] 기술 지표 추가 - Stochastic RSI, MACD 추가
    
    추가된 컬럼:
    - stoch_rsi_k, stoch_rsi_d: Stochastic RSI
    - macd, macd_signal, macd_hist: MACD
    """
    try:
        if df is None or len(df) < BB_PERIOD:
            return None
        
        # 기존 지표 (변경 없음)
        df['rsi'] = calculate_rsi(df['close'])
        
        bb_upper, bb_middle, bb_lower, bb_position, bb_width = calculate_bollinger_bands(df)
        
        if bb_upper is None:
            return None
        
        df['bb_upper'] = bb_upper
        df['bb_middle'] = bb_middle
        df['bb_lower'] = bb_lower
        df['bb_high'] = bb_upper
        df['bb_low'] = bb_lower
        df['bb_position'] = bb_position
        df['bb_width'] = bb_width
        
        df['volume_ma'] = df['volume'].rolling(window=VOLUME_MA_PERIOD).mean()
        df['volume_ratio'] = df['volume'] / df['volume_ma']
        
        df['is_bull'] = (df['close'] > df['open']).astype(int)
        df['is_bear'] = (df['close'] < df['open']).astype(int)
        
        df['price_change_pct'] = df['close'].pct_change() * 100
        
        # Uppercase aliases
        df['RSI'] = df['rsi']
        df['BB_UPPER'] = df['bb_upper']
        df['BB_LOWER'] = df['bb_lower']
        
        # ========================================
        # [v10.0 신규] Stochastic RSI
        # ========================================
        stoch_k, stoch_d = calculate_stochastic_rsi(
            df['close'],
            rsi_period=V10_STOCH_RSI_PERIOD,
            stoch_period=V10_STOCH_RSI_PERIOD,
            k_period=V10_STOCH_RSI_K_PERIOD,
            d_period=V10_STOCH_RSI_D_PERIOD
        )
        df['stoch_rsi_k'] = stoch_k
        df['stoch_rsi_d'] = stoch_d
        
        # ========================================
        # [v10.0 신규] MACD
        # ========================================
        macd_line, signal_line, histogram = calculate_macd(
            df['close'],
            fast=V10_MACD_FAST,
            slow=V10_MACD_SLOW,
            signal=V10_MACD_SIGNAL
        )
        df['macd'] = macd_line
        df['macd_signal'] = signal_line
        df['macd_hist'] = histogram
        
        return df
        
    except Exception as e:
        if DEBUG_MODE:
            print(f"{Colors.RED}[Indicator Error] {e}{Colors.ENDC}")
        return None
    
def calculate_adx(df, period=14):
    """
    [v12.0 신규] ADX (Average Directional Index) 계산
    
    추세 강도와 방향성 측정:
    - ADX > 25: 추세 존재
    - DI+ > DI-: 상승 추세 / DI- > DI+: 하락 추세
    
    Args:
        df: OHLCV DataFrame (add_indicators 적용 완료)
        period: ADX 기간 (기본 14)
    
    Returns:
        dict: {'adx': float, 'plus_di': float, 'minus_di': float}
    """
    try:
        if df is None or len(df) < period * 3:
            return {'adx': 20, 'plus_di': 25, 'minus_di': 25}
        
        high = df['high']
        low = df['low']
        close = df['close']
        
        # Directional Movement 계산
        plus_dm = high.diff()
        minus_dm = -low.diff()
        plus_dm = plus_dm.where((plus_dm > minus_dm) & (plus_dm > 0), 0)
        minus_dm = minus_dm.where((minus_dm > plus_dm) & (minus_dm > 0), 0)
        
        # True Range
        tr1 = high - low
        tr2 = abs(high - close.shift(1))
        tr3 = abs(low - close.shift(1))
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        
        # ATR
        atr = tr.rolling(window=period).mean()
        
        # DI+ / DI-
        plus_di = 100 * (plus_dm.rolling(window=period).mean() / atr.replace(0, np.nan))
        minus_di = 100 * (minus_dm.rolling(window=period).mean() / atr.replace(0, np.nan))
        
        # DX → ADX
        di_sum = plus_di + minus_di
        di_sum = di_sum.replace(0, np.nan)
        dx = 100 * abs(plus_di - minus_di) / di_sum
        adx = dx.rolling(window=period).mean()
        
        # 최신값 반환
        latest_adx = adx.iloc[-1] if not pd.isna(adx.iloc[-1]) else 20
        latest_pdi = plus_di.iloc[-1] if not pd.isna(plus_di.iloc[-1]) else 25
        latest_mdi = minus_di.iloc[-1] if not pd.isna(minus_di.iloc[-1]) else 25
        
        return {
            'adx': float(latest_adx),
            'plus_di': float(latest_pdi),
            'minus_di': float(latest_mdi)
        }
        
    except Exception as e:
        if DEBUG_MODE:
            print(f"{Colors.RED}[ADX Calc Error] {e}{Colors.ENDC}")
        return {'adx': 20, 'plus_di': 25, 'minus_di': 25}
    
def get_time_mode():
    """
    [v18.0 신규] 현재 시간 기준 매수 모드 판별
    
    Returns:
        str: 'NIGHT' (23:00~08:00) 또는 'DAY' (그 외)
        
    시간대 구분 (KST):
        [23:00 ~ 08:00) → NIGHT: V자 반등 특화, 일봉 필터 완화 + BB 하단 강화
        [08:00 ~ 09:15) → 매수 금지 (기존 buy_thread_worker에서 처리)
        [09:15 ~ 23:00) → DAY: 기존 로직 유지, 일봉 모멘텀 중시
    """
    if not TIMEZONE_MODE_ENABLED:
        return 'DAY'
    
    now = datetime.now()
    current_hour = now.hour
    current_minute = now.minute
    
    # 야간 판별: 23:00 ~ 다음날 08:00
    night_start = NIGHT_MODE_START_HOUR * 60 + NIGHT_MODE_START_MINUTE   # 23:00 = 1380
    night_end = NIGHT_MODE_END_HOUR * 60 + NIGHT_MODE_END_MINUTE         # 08:00 = 480
    current_time = current_hour * 60 + current_minute
    
    # 자정을 넘기는 구간 처리
    if night_start > night_end:
        # 23:00~23:59 또는 00:00~07:59
        if current_time >= night_start or current_time < night_end:
            return 'NIGHT'
    else:
        # 시작 < 종료인 경우 (일반적이지 않지만 안전 처리)
        if night_start <= current_time < night_end:
            return 'NIGHT'
    
    return 'DAY'

    
def determine_market_regime(ticker, df_15m=None):
    """
    [v12.0 신규] 시장 레짐 판별 - 복합 점수 시스템
    
    4가지 지표를 종합하여 BULLISH / NEUTRAL / BEARISH 판정:
    ① 일봉 등락률 (가중치 40%): +2 ~ -2점
    ② 3일 누적 추세 (가중치 30%): +2 ~ -1점
    ③ ADX + DI 방향 (가중치 20%): +1 ~ -1점
    ④ 양봉 빈도 (가중치 10%): +1 ~ -1점
    
    점수 합산: ≥4 → BULLISH / 1~3 → NEUTRAL / ≤0 → BEARISH
    
    Args:
        ticker: 코인 티커 (예: "KRW-XRP")
        df_15m: 15분봉 DataFrame (ADX 계산용, None이면 기본값)
    
    Returns:
        dict: {regime, score, details, daily_change, three_day_change, adx, adx_data, bullish_days}
    """
    try:
        if not REGIME_ENABLED:
            return {
                'regime': 'NEUTRAL', 'score': 2, 'details': '레짐비활성',
                'daily_change': 0, 'three_day_change': 0, 'adx': 20
            }
        
        # ========================================
        # ① 일봉 데이터 분석
        # ========================================
        df_daily = get_candles_daily(ticker, count=50)
        
        if df_daily is None or len(df_daily) < 3:
            return {
                'regime': 'NEUTRAL', 'score': 2, 'details': '일봉부족',
                'daily_change': 0, 'three_day_change': 0, 'adx': 20
            }
        
        latest = df_daily.iloc[-1]
        daily_change = ((latest['close'] - latest['open']) / latest['open'] * 100) if latest['open'] > 0 else 0
        
        # 3일 누적 등락률
        if len(df_daily) >= 3:
            three_day_change = ((df_daily.iloc[-1]['close'] - df_daily.iloc[-3]['open']) / df_daily.iloc[-3]['open'] * 100)
        else:
            three_day_change = daily_change
        
        # 최근 3일 양봉 수
        recent_3 = df_daily.tail(3)
        bullish_days = sum(1 for _, c in recent_3.iterrows() if c['close'] > c['open'])
        
        score = 0
        details_parts = []
        
        # ① 일봉 등락률 점수 (+2 ~ -2)
        if daily_change >= REGIME_DAILY_STRONG_BULL:
            score += 2
            details_parts.append(f"일봉강양{daily_change:+.1f}%")
        elif daily_change >= REGIME_DAILY_WEAK_BULL:
            score += 1
            details_parts.append(f"일봉약양{daily_change:+.1f}%")
        elif daily_change >= REGIME_DAILY_WEAK_BEAR:
            details_parts.append(f"일봉보합{daily_change:+.1f}%")
        elif daily_change >= REGIME_DAILY_STRONG_BEAR:
            score -= 1
            details_parts.append(f"일봉약음{daily_change:+.1f}%")
        else:
            score -= 2
            details_parts.append(f"일봉강음{daily_change:+.1f}%")
        
        # ② 3일 추세 점수 (+2 ~ -1)
        if three_day_change >= REGIME_3DAY_STRONG_BULL:
            score += 2
            details_parts.append(f"3일강↑{three_day_change:+.1f}%")
        elif three_day_change >= 0:
            score += 1
            details_parts.append(f"3일약↑{three_day_change:+.1f}%")
        elif three_day_change >= REGIME_3DAY_WEAK_BEAR:
            details_parts.append(f"3일보합{three_day_change:+.1f}%")
        else:
            score -= 1
            details_parts.append(f"3일↓{three_day_change:+.1f}%")
        
        # ③ ADX + DI 방향 점수 (+1 ~ -1)
        adx_data = calculate_adx(df_15m) if df_15m is not None else {'adx': 20, 'plus_di': 25, 'minus_di': 25}
        adx_val = adx_data['adx']
        
        if adx_val > REGIME_ADX_THRESHOLD:
            if adx_data['plus_di'] > adx_data['minus_di']:
                score += 1
                details_parts.append(f"ADX{adx_val:.0f}↑")
            else:
                score -= 1
                details_parts.append(f"ADX{adx_val:.0f}↓")
        else:
            details_parts.append(f"ADX{adx_val:.0f}약")
        
        # ④ 양봉 빈도 점수 (+1 ~ -1)
        if bullish_days >= 2:
            score += 1
            details_parts.append(f"양{bullish_days}/3")
        elif bullish_days == 0:
            score -= 1
            details_parts.append(f"양0/3")
        else:
            details_parts.append(f"양{bullish_days}/3")
        
        # ========================================
        # 레짐 판정
        # ========================================
        if score >= REGIME_BULLISH_SCORE:
            regime = 'BULLISH'
        elif score >= REGIME_NEUTRAL_MIN_SCORE:
            regime = 'NEUTRAL'
        else:
            regime = 'BEARISH'
        
        details = f"{regime}({score}점) [{', '.join(details_parts)}]"
        
        return {
            'regime': regime,
            'score': score,
            'details': details,
            'daily_change': daily_change,
            'three_day_change': three_day_change,
            'adx': adx_val,
            'adx_data': adx_data,
            'bullish_days': bullish_days
        }
        
    except Exception as e:
        if DEBUG_MODE:
            print(f"{Colors.RED}[Regime Detection Error] {ticker}: {e}{Colors.ENDC}")
        return {
            'regime': 'NEUTRAL', 'score': 2, 'details': f'오류:{e}',
            'daily_change': 0, 'three_day_change': 0, 'adx': 20
        }

def check_daily_safety_filter(ticker, regime='NEUTRAL', time_mode='DAY'):
    """
    [v19.0] Phase 1: 일봉 안전 필터
    
    v19.0 변경사항:
    - HL Position 필터 완전 제거
    - 일봉 등락률 범위 필터 추가 (레짐별/시간대별 차등)
    - 기존 양봉 조건, 연속 음봉 차단 유지
    
    Returns:
        dict: {safe, daily_change, reason, is_bullish, daily_bb, daily_rsi, daily_candle_type}
    """
    try:
        # 일봉 데이터 수집
        df_daily = get_candles_daily(ticker, count=50)
        
        if df_daily is None or len(df_daily) < 20:
            return {
                'safe': False, 'daily_change': 0,
                'reason': '일봉 데이터 부족',
                'is_bullish': False, 'daily_bb': 50,
                'daily_rsi': 50, 'daily_candle_type': 'unknown'
            }
        
        df_daily = add_indicators(df_daily)
        if df_daily is None:
            return {
                'safe': False, 'daily_change': 0,
                'reason': '일봉 지표 계산 실패',
                'is_bullish': False, 'daily_bb': 50,
                'daily_rsi': 50, 'daily_candle_type': 'unknown'
            }
        
        current = df_daily.iloc[-1]
        daily_open = current['open']
        daily_close = current['close']
        daily_rsi = current['rsi']
        daily_bb = current['bb_position']
        
        # 당일 등락률
        daily_change = ((daily_close - daily_open) / daily_open * 100) if daily_open > 0 else 0
        
        base_info = {
            'daily_change': daily_change,
            'daily_bb': daily_bb,
            'daily_rsi': daily_rsi,
        }
        
        # ========================================
        # 체크 1: 급등/급락 차단 (DAY/NIGHT 동일 - 극단 위험)
        # ========================================
        if daily_change > V10_DAILY_CHANGE_MAX:
            return {**base_info, 'safe': False, 'is_bullish': True,
                    'reason': f'당일 급등 {daily_change:+.1f}%',
                    'daily_candle_type': 'extreme'}
        
        if daily_change < V10_DAILY_CHANGE_MIN:
            return {**base_info, 'safe': False, 'is_bullish': False,
                    'reason': f'당일 급락 {daily_change:+.1f}%',
                    'daily_candle_type': 'extreme'}
        
        # ========================================
        # 체크 1.5: [v19.0] 등락률 범위 필터 (HL Position 대체)
        # ========================================
        if time_mode == 'NIGHT':
            change_min = V19_NIGHT_CHANGE_MIN       # -3.0%
            change_max = V19_NIGHT_CHANGE_MAX       # +5.0%
            range_label = 'NIGHT'
        elif REGIME_ENABLED and regime == 'BULLISH':
            change_min = V19_DAY_BULL_CHANGE_MIN    # -1.5%
            change_max = V19_DAY_BULL_CHANGE_MAX    # +3.5%
            range_label = 'BULL'
        elif REGIME_ENABLED and regime == 'BEARISH':
            change_min = V19_DAY_BEAR_CHANGE_MIN    # -0.5%
            change_max = V19_DAY_BEAR_CHANGE_MAX    # +2.0%
            range_label = 'BEAR'
        else:
            change_min = V19_DAY_NEUT_CHANGE_MIN    # -1.0%
            change_max = V19_DAY_NEUT_CHANGE_MAX    # +3.0%
            range_label = 'NEUT'
        
        if daily_change < change_min:
            return {**base_info, 'safe': False, 'is_bullish': False,
                    'reason': f'등락범위초과: {daily_change:+.1f}%<{change_min}%({range_label})',
                    'daily_candle_type': 'range_filtered'}
        
        if daily_change > change_max:
            return {**base_info, 'safe': False, 'is_bullish': True,
                    'reason': f'등락범위초과: {daily_change:+.1f}%>{change_max}%({range_label})',
                    'daily_candle_type': 'range_filtered'}
        
        # ========================================
        # 체크 2: 연속 음봉 체크
        # ========================================
        consecutive_bear = 0
        for i in range(-1, -4, -1):
            if len(df_daily) + i >= 0:
                candle = df_daily.iloc[i]
                if candle['close'] < candle['open']:
                    consecutive_bear += 1
                else:
                    break
        
        if time_mode == 'NIGHT':
            max_consecutive_bear = NIGHT_CONSECUTIVE_BEAR_MAX
        elif REGIME_ENABLED:
            if regime == 'BEARISH':
                max_consecutive_bear = REGIME_BEAR_CONSECUTIVE_BEAR_MAX
            elif regime == 'BULLISH':
                max_consecutive_bear = REGIME_BULL_CONSECUTIVE_BEAR_MAX
            else:
                max_consecutive_bear = REGIME_NEUT_CONSECUTIVE_BEAR_MAX
        else:
            max_consecutive_bear = V10_DAILY_CONSECUTIVE_BEAR_MAX
        
        if consecutive_bear >= max_consecutive_bear:
            return {**base_info, 'safe': False, 'is_bullish': False,
                    'reason': f'{consecutive_bear}일 연속 음봉(기준{max_consecutive_bear})',
                    'daily_candle_type': 'bearish'}
        
        # ========================================
        # 체크 3: 양봉 조건
        # ========================================
        is_today_bullish = daily_close > daily_open
        
        recent_3 = df_daily.tail(3)
        bullish_days = sum(1 for _, c in recent_3.iterrows() if c['close'] > c['open'])
        
        if time_mode == 'NIGHT':
            if NIGHT_SKIP_TODAY_BULLISH:
                if bullish_days < NIGHT_BULLISH_DAYS_MIN:
                    return {**base_info, 'safe': False, 'is_bullish': False,
                            'reason': f'NIGHT:양봉부족(최근{bullish_days}/3, 기준{NIGHT_BULLISH_DAYS_MIN})',
                            'daily_candle_type': 'bearish'}
            else:
                if not is_today_bullish and bullish_days < NIGHT_BULLISH_DAYS_MIN:
                    return {**base_info, 'safe': False, 'is_bullish': False,
                            'reason': f'NIGHT:양봉부족(음봉, 최근{bullish_days}/3)',
                            'daily_candle_type': 'bearish'}
        elif REGIME_ENABLED:
            if regime == 'BEARISH':
                if not is_today_bullish:
                    return {**base_info, 'safe': False, 'is_bullish': False,
                            'reason': f'BEAR:당일양봉필수(음봉)',
                            'daily_candle_type': 'bearish'}
            elif regime == 'BULLISH':
                if not is_today_bullish and bullish_days < REGIME_BULL_BULLISH_DAYS_MIN:
                    return {**base_info, 'safe': False, 'is_bullish': False,
                            'reason': f'양봉부족({bullish_days}/3, 기준{REGIME_BULL_BULLISH_DAYS_MIN})',
                            'daily_candle_type': 'bearish'}
            else:
                if not is_today_bullish and bullish_days < REGIME_NEUT_BULLISH_DAYS_MIN:
                    return {**base_info, 'safe': False, 'is_bullish': False,
                            'reason': f'양봉부족(음봉, 최근{bullish_days}/3)',
                            'daily_candle_type': 'bearish'}
        else:
            recent_bullish_ok = bullish_days >= V10_DAILY_BULLISH_DAYS_MIN
            if not is_today_bullish and not recent_bullish_ok:
                return {**base_info, 'safe': False, 'is_bullish': False,
                        'reason': f'양봉부족 (음봉, 최근{bullish_days}/3)',
                        'daily_candle_type': 'bearish'}
        
        # ========================================
        # [v19.0] HL Position 체크 완전 제거
        # ========================================
        
        # ========================================
        # 모든 체크 통과 → daily_candle_type 결정
        # ========================================
        if time_mode == 'NIGHT':
            if is_today_bullish:
                daily_candle_type = 'night_bullish'
                bullish_reason = f"🌙NIGHT양봉{daily_change:+.1f}%"
            else:
                daily_candle_type = 'night_permissive'
                bullish_reason = f"🌙NIGHT음봉허용{daily_change:+.1f}%(최근양봉{bullish_days}/3)"
        elif is_today_bullish and daily_change >= V10_BB_WIDTH_BULLISH_MIN_CHANGE:
            daily_candle_type = 'bullish'
            bullish_reason = f"양봉{daily_change:+.1f}%"
        elif is_today_bullish:
            daily_candle_type = 'weak_bullish'
            bullish_reason = f"약양봉{daily_change:+.1f}%"
        else:
            daily_candle_type = 'recent_bullish'
            bullish_reason = f"최근양봉{bullish_days}/3"
        
        return {
            **base_info,
            'safe': True,
            'is_bullish': is_today_bullish,
            'reason': f'일봉OK ({bullish_reason} 범위{change_min:+.1f}~{change_max:+.1f}%)',
            'daily_candle_type': daily_candle_type
        }
        
    except Exception as e:
        if DEBUG_MODE:
            print(f"{Colors.RED}[Daily Safety Error] {ticker}: {e}{Colors.ENDC}")
        return {
            'safe': True, 'daily_change': 0,
            'reason': f'체크 오류: {e}',
            'is_bullish': False, 'daily_bb': 50,
            'daily_rsi': 50, 'daily_candle_type': 'unknown'
        }


def find_recent_swing_lows(df, lookback=80, swing_size=3):
    """
    [v10.1] 15분봉 데이터에서 Swing Low(파동 저점) 탐지
    
    Swing Low 정의: 
    좌우 swing_size개 캔들의 low보다 현재 캔들의 low가 낮은 지점
    
    Args:
        df: 15분봉 DataFrame (add_indicators 적용 완료)
        lookback: 최근 N개 캔들에서 탐색 (기본 80개 = 약 20시간)
        swing_size: 좌우 비교 캔들 수 (기본 3 = 좌3 우3)
    
    Returns:
        list: [{'index': int, 'price': float, 'time': datetime}, ...]
              최근 순서대로 정렬 (마지막이 가장 최근)
    """
    try:
        if df is None or len(df) < lookback:
            # 데이터 부족 시 가용 범위로 축소
            lookback = len(df)
        
        if lookback < swing_size * 2 + 1:
            return []
        
        # 탐색 시작 인덱스 (최근 lookback개만)
        start_idx = max(swing_size, len(df) - lookback)
        # 마지막 swing_size개는 우측 비교 불가하므로 제외
        end_idx = len(df) - swing_size
        
        lows = []
        
        for i in range(start_idx, end_idx):
            current_low = df.iloc[i]['low']
            is_swing_low = True
            
            # 좌측 swing_size개와 비교
            for j in range(1, swing_size + 1):
                if current_low >= df.iloc[i - j]['low']:
                    is_swing_low = False
                    break
            
            if not is_swing_low:
                continue
            
            # 우측 swing_size개와 비교
            for j in range(1, swing_size + 1):
                if current_low >= df.iloc[i + j]['low']:
                    is_swing_low = False
                    break
            
            if is_swing_low:
                lows.append({
                    'index': i,
                    'price': current_low,
                    'time': df.index[i] if hasattr(df.index[i], 'strftime') else None
                })
        
        return lows
        
    except Exception as e:
        if DEBUG_MODE:
            print(f"{Colors.RED}[Swing Low Error] {e}{Colors.ENDC}")
        return []


def find_recent_swing_highs(df, lookback=60, swing_size=2):
    """
    [v11.0] 15분봉 데이터에서 Swing High(파동 고점) 탐지
    
    find_recent_swing_lows의 미러 함수.
    매도 시 Lower High(고점 하락 추세) 감지에 사용.
    
    Swing High 정의: 
    좌우 swing_size개 캔들의 high보다 현재 캔들의 high가 높은 지점
    
    Args:
        df: 15분봉 DataFrame (add_indicators 적용 완료)
        lookback: 최근 N개 캔들에서 탐색 (기본 60개 = 약 15시간)
        swing_size: 좌우 비교 캔들 수 (기본 2, 상승 파동이 짧으므로)
    
    Returns:
        list: [{'index': int, 'price': float, 'time': datetime}, ...]
    """
    try:
        if df is None or len(df) < lookback:
            lookback = len(df)
        
        if lookback < swing_size * 2 + 1:
            return []
        
        start_idx = max(swing_size, len(df) - lookback)
        end_idx = len(df) - swing_size
        
        highs = []
        
        for i in range(start_idx, end_idx):
            current_high = df.iloc[i]['high']
            is_swing_high = True
            
            for j in range(1, swing_size + 1):
                if current_high <= df.iloc[i - j]['high']:
                    is_swing_high = False
                    break
            
            if not is_swing_high:
                continue
            
            for j in range(1, swing_size + 1):
                if current_high <= df.iloc[i + j]['high']:
                    is_swing_high = False
                    break
            
            if is_swing_high:
                highs.append({
                    'index': i,
                    'price': current_high,
                    'time': df.index[i] if hasattr(df.index[i], 'strftime') else None
                })
        
        return highs
        
    except Exception as e:
        if DEBUG_MODE:
            print(f"{Colors.RED}[Swing High Error] {e}{Colors.ENDC}")
        return []
    
def detect_downtrend_15m(df_15m, daily_candle_type='unknown', regime='NEUTRAL', time_mode='DAY'):
    """
    [v19.0] Phase 2: 15분봉 BB 하단 존 확인 (듀얼 타임프레임)
    
    v19.0 변경사항:
    - BB 터치 이력 확인 추가 (최근 4캔들 중 BB≤15% 터치 1회 이상)
    - RSI 상한 추가 (RSI≤50, 바닥 구간 집중)
    - Higher Low 완전 제거
    - BEARISH ADX+OBV 이중 필터 제거
    - BB Position 상한 레짐별 조정 (V19 파라미터)
    """
    try:
        if df_15m is None or len(df_15m) < 5:
            return {
                'is_downtrend': True,
                'reason': '데이터 부족',
                'bb_position': 50, 'bb_width': 0, 'rsi': 50,
                'bb_touched': False
            }
        
        current = df_15m.iloc[-1]
        bb_position = current['bb_position']
        bb_width = current['bb_width']
        rsi = current['rsi']
        
        base = {
            'bb_position': bb_position,
            'bb_width': bb_width,
            'rsi': rsi,
            'bb_touched': False
        }
        
        # ========================================
        # [v19.0] 시간대 + 레짐별 기준 결정
        # ========================================
        if time_mode == 'NIGHT':
            bb_min = NIGHT_BB_MIN                    # 3%
            bb_max = V19_NIGHT_BB_MAX                # 30% (v18.0 25%→30% 완화)
            required_bb_width = NIGHT_BB_WIDTH_MIN   # 1.2%
            rsi_min = NIGHT_RSI_MIN                  # 20
            width_label = 'NIGHT'
        elif REGIME_ENABLED and regime == 'BULLISH':
            bb_min = REGIME_BULL_BB_MIN              # 5%
            bb_max = V19_BULL_BB_MAX                 # 40% (기존 42%→40%)
            required_bb_width = REGIME_BULL_BB_WIDTH # 1.3%
            rsi_min = REGIME_BULL_RSI_MIN            # 20
            width_label = 'BULL'
        elif REGIME_ENABLED and regime == 'BEARISH':
            bb_min = REGIME_BEAR_BB_MIN              # 3%
            bb_max = V19_BEAR_BB_MAX                 # 25%
            required_bb_width = REGIME_BEAR_BB_WIDTH # 2.5%
            rsi_min = REGIME_BEAR_RSI_MIN            # 22
            width_label = 'BEAR'
        elif REGIME_ENABLED and regime == 'NEUTRAL':
            bb_min = REGIME_NEUT_BB_MIN              # 5%
            bb_max = V19_NEUT_BB_MAX                 # 35%
            required_bb_width = REGIME_NEUT_BB_WIDTH # 1.8%
            rsi_min = REGIME_NEUT_RSI_MIN            # 20
            width_label = 'NEUT'
        else:
            if daily_candle_type == 'bullish':
                required_bb_width = V10_BB_WIDTH_BULLISH
                width_label = '양봉'
            else:
                required_bb_width = V10_BB_WIDTH_BEARISH
                width_label = '비양봉'
            bb_min = V10_15M_BB_MIN
            bb_max = V10_15M_BB_MAX
            rsi_min = V10_15M_RSI_MIN
        
        # 체크 1: BB 폭 최소 기준
        if bb_width < required_bb_width:
            return {
                **base, 'is_downtrend': True,
                'reason': f'BB폭 부족 {bb_width:.1f}% < {required_bb_width}% ({width_label}기준)'
            }
        
        # 체크 2: BB 위치 하한 (극단 하단 보호)
        if bb_position < bb_min:
            return {
                **base, 'is_downtrend': True,
                'reason': f'BB {bb_position:.0f}% < {bb_min}% (극단 하단, 추가 하락 위험)'
            }
        
        # 체크 3: BB 위치 상한
        if bb_position > bb_max:
            return {
                **base, 'is_downtrend': True,
                'reason': f'BB {bb_position:.0f}% > {bb_max}% (하단 아닌 구간, {width_label})'
            }
        
        # 체크 4: RSI 극단 과매도 회피
        if rsi < rsi_min:
            return {
                **base, 'is_downtrend': True,
                'reason': f'RSI {rsi:.0f} < {rsi_min} (극단 과매도, 바닥 미확인)'
            }
        
        # ========================================
        # [v19.0 신규] 체크 4.5: RSI 상한 (바닥 구간 집중)
        # ========================================
        if rsi > V19_15M_RSI_MAX:
            return {
                **base, 'is_downtrend': True,
                'reason': f'RSI {rsi:.0f} > {V19_15M_RSI_MAX} (이미 중립 이상, 바닥 반등 아님)'
            }
        
        # ========================================
        # [v19.0 신규] 체크 5: BB 하단 터치 이력 확인
        # 최근 4개 15분봉(1시간) 중 BB Position ≤ 15% 터치 1회 이상
        # ========================================
        lookback = min(V19_BB_TOUCH_LOOKBACK, len(df_15m) - 1)
        touch_found = False
        touch_min_bb = bb_position  # 현재값으로 초기화
        
        for i in range(1, lookback + 1):
            past_bb = df_15m.iloc[-i]['bb_position']
            touch_min_bb = min(touch_min_bb, past_bb)
            if past_bb <= V19_BB_TOUCH_THRESHOLD:
                touch_found = True
                break
        
        # 현재 캔들이 터치 중이면 바로 충족
        if bb_position <= V19_BB_TOUCH_THRESHOLD:
            touch_found = True
        
        base['bb_touched'] = touch_found
        base['touch_min_bb'] = touch_min_bb
        
        if not touch_found:
            return {
                **base, 'is_downtrend': True,
                'reason': f'BB터치이력없음 (최근{lookback}봉 최저BB:{touch_min_bb:.0f}%>{V19_BB_TOUCH_THRESHOLD}%)'
            }
        
        # ========================================
        # 모든 체크 통과 → 매수 가능 구간
        # ========================================
        touch_str = f", 터치✅(최저BB:{touch_min_bb:.0f}%)"
        
        return {
            **base,
            'is_downtrend': False,
            'reason': f'BB하단존 OK (BB:{bb_position:.0f}%, 폭:{bb_width:.1f}%≥{required_bb_width}%({width_label}), RSI:{rsi:.0f}{touch_str})'
        }
        
    except Exception as e:
        if DEBUG_MODE:
            print(f"{Colors.RED}[Position Filter Error] {e}{Colors.ENDC}")
        return {
            'is_downtrend': True,
            'reason': f'체크 오류: {e}',
            'bb_position': 50, 'bb_width': 0, 'rsi': 50,
            'bb_touched': False
        }

def calculate_reversal_score(df_5m, df_15m=None, time_mode='DAY'):
    """
    [v19.0] Phase 3: 5분봉 기반 반등 트리거 (듀얼 타임프레임)
    
    v19.0 핵심 변경: 반등 신호 평가를 15분봉 → 5분봉으로 전환
    → 3배 빠른 반등 감지 (15분 지연 → 5분 지연)
    
    5분봉 반등 신호 (7+2개):
    ① RSI 상승 전환
    ② Stochastic RSI 골든크로스
    ③ MACD 히스토그램 개선
    ④ 양봉 확인
    ⑤ 거래량 확인
    ⑥ BB Position 상승 전환 (★ v19.0 신규)
    ⑦ RSI Bullish Divergence (15분봉 기반 보너스)
    +(NIGHT) ⑧V-Reversal ⑨하단꼬리
    """
    try:
        if df_5m is None or len(df_5m) < 3:
            return {
                'score': 0, 'items_met': 0, 'details': ['5분봉 데이터 부족'],
                'signals': {}, 'bounce_confirmed': False,
                'rsi_rising': False, 'is_bullish': False,
                'volume_up': False,
                'mandatory_met': False
            }
        
        current = df_5m.iloc[-1]
        prev = df_5m.iloc[-2]
        
        signals_met = 0
        details = []
        signals = {}
        
        # ========================================
        # ① RSI 상승 전환 (5분봉)
        # ========================================
        rsi_now = current['rsi']
        rsi_prev = prev['rsi']
        rsi_rising = rsi_now > rsi_prev
        signals['rsi_rising'] = rsi_rising
        
        if rsi_rising:
            signals_met += 1
            details.append(f"①RSI↑ {rsi_prev:.0f}→{rsi_now:.0f}")
        
        # ========================================
        # ② Stochastic RSI 골든크로스 (5분봉)
        # ========================================
        stoch_k = current.get('stoch_rsi_k', 50)
        stoch_d = current.get('stoch_rsi_d', 50)
        stoch_k_prev = prev.get('stoch_rsi_k', 50)
        stoch_d_prev = prev.get('stoch_rsi_d', 50)
        
        stoch_oversold_bounce = (stoch_k_prev <= V10_STOCH_RSI_OVERSOLD and stoch_k > stoch_k_prev)
        stoch_golden_cross = (stoch_k > stoch_d and stoch_k_prev <= stoch_d_prev)
        stoch_signal = stoch_oversold_bounce or stoch_golden_cross
        signals['stoch_rsi'] = stoch_signal
        
        if stoch_signal:
            signals_met += 1
            if stoch_oversold_bounce:
                details.append(f"②SRSI과매도탈출 K:{stoch_k:.0f}")
            else:
                details.append(f"②SRSI골든크로스 K:{stoch_k:.0f}>D:{stoch_d:.0f}")
        
        # ========================================
        # ③ MACD 히스토그램 개선 (5분봉)
        # ========================================
        macd_hist = current.get('macd_hist', 0)
        macd_hist_prev = prev.get('macd_hist', 0)
        
        macd_crossover = (macd_hist_prev < 0 and macd_hist >= 0)
        macd_improving = (macd_hist_prev < 0 and macd_hist > macd_hist_prev)
        macd_signal = macd_crossover or macd_improving
        signals['macd'] = macd_signal
        
        if macd_signal:
            signals_met += 1
            if macd_crossover:
                details.append(f"③MACD양전환")
            else:
                details.append(f"③MACD축소(개선)")
        
        # ========================================
        # ④ 양봉 확인 (5분봉)
        # ========================================
        is_bullish = current['close'] > current['open']
        signals['bullish'] = is_bullish
        
        if is_bullish:
            signals_met += 1
            change_pct = ((current['close'] - current['open']) / current['open']) * 100
            details.append(f"④양봉 +{change_pct:.2f}%")
        
        # ========================================
        # ⑤ 거래량 확인 (5분봉 MA20 × 0.8 이상)
        # ========================================
        vol_ratio = current.get('volume_ratio', 1.0)
        volume_ok = vol_ratio >= V10_VOLUME_MIN_RATIO
        signals['volume'] = volume_ok
        
        if volume_ok:
            signals_met += 1
            details.append(f"⑤거래량 {vol_ratio:.1f}x")
        
        # ========================================
        # ⑥ [v19.0 신규] BB Position 상승 전환 (5분봉)
        # ========================================
        bb_pos_now = current.get('bb_position', 50)
        bb_pos_prev = prev.get('bb_position', 50)
        bb_pos_rising = bb_pos_now > bb_pos_prev
        signals['bb_pos_rising'] = bb_pos_rising
        
        if bb_pos_rising:
            signals_met += 1
            details.append(f"⑥BB↑ {bb_pos_prev:.0f}→{bb_pos_now:.0f}%")
        
        # ========================================
        # ⑦ RSI Bullish Divergence (15분봉 기반 보너스)
        # ========================================
        rsi_divergence_detected = False
        check_df = df_15m if (df_15m is not None and len(df_15m) >= RSI_DIVERGENCE_LOOKBACK) else None
        if RSI_DIVERGENCE_ENABLED and check_df is not None:
            try:
                lookback_df = check_df.tail(RSI_DIVERGENCE_LOOKBACK)
                price_lows = []
                rsi_at_lows = []
                for i in range(2, len(lookback_df) - 2):
                    row = lookback_df.iloc[i]
                    prev1 = lookback_df.iloc[i-1]
                    prev2 = lookback_df.iloc[i-2]
                    next1 = lookback_df.iloc[i+1]
                    next2 = lookback_df.iloc[i+2]
                    if (row['low'] < prev1['low'] and row['low'] < prev2['low'] and 
                        row['low'] < next1['low'] and row['low'] < next2['low']):
                        price_lows.append(row['low'])
                        rsi_at_lows.append(row['rsi'])
                
                if len(price_lows) >= 2:
                    if price_lows[-1] < price_lows[-2] and rsi_at_lows[-1] > rsi_at_lows[-2]:
                        rsi_divergence_detected = True
                        signals_met += 1
                        details.append("⑦RSI다이버전스(15m)")
            except:
                pass
        signals['rsi_divergence'] = rsi_divergence_detected
        
        # ========================================
        # [NIGHT 전용] ⑧ V-Reversal 감지 (5분봉 기준)
        # ========================================
        v_reversal_detected = False
        if time_mode == 'NIGHT' and NIGHT_V_REVERSAL_ENABLED and len(df_5m) >= NIGHT_V_REVERSAL_MIN_BEARS + 1:
            try:
                consecutive_bears = 0
                for i in range(2, min(8, len(df_5m))):    # 5분봉이므로 더 넓게 탐색
                    prev_candle = df_5m.iloc[-i]
                    if prev_candle['close'] < prev_candle['open']:
                        consecutive_bears += 1
                    else:
                        break
                
                current_bullish_or_turning = (
                    is_bullish or
                    (current['close'] > prev['close'])
                )
                
                if consecutive_bears >= NIGHT_V_REVERSAL_MIN_BEARS and current_bullish_or_turning:
                    v_reversal_detected = True
                    signals_met += 1
                    details.append(f"⑧V반등({consecutive_bears}음봉후양전환)")
            except:
                pass
        signals['v_reversal'] = v_reversal_detected
        
        # ========================================
        # [NIGHT 전용] ⑨ 하단꼬리(Lower Shadow) 감지 (5분봉)
        # ========================================
        lower_shadow_detected = False
        if time_mode == 'NIGHT' and NIGHT_LOWER_SHADOW_ENABLED:
            try:
                body = abs(current['close'] - current['open'])
                lower_shadow = min(current['close'], current['open']) - current['low']
                
                if body > 0:
                    shadow_ratio = lower_shadow / body
                else:
                    candle_range = current['high'] - current['low']
                    shadow_ratio = (lower_shadow / candle_range * NIGHT_LOWER_SHADOW_RATIO) if candle_range > 0 else 0
                
                if shadow_ratio >= NIGHT_LOWER_SHADOW_RATIO and lower_shadow > 0:
                    lower_shadow_detected = True
                    signals_met += 1
                    details.append(f"⑨하단꼬리({shadow_ratio:.1f}x)")
            except:
                pass
        signals['lower_shadow'] = lower_shadow_detected
        
        # ========================================
        # 필수 조건 체크
        # ========================================
        if time_mode == 'NIGHT':
            mandatory_met = rsi_rising or is_bullish or stoch_golden_cross or v_reversal_detected
        else:
            mandatory_met = rsi_rising or is_bullish or stoch_golden_cross
        
        # ========================================
        # 최종 판정
        # ========================================
        bounce_confirmed = (
            signals_met >= V10_BOUNCE_MIN_SIGNALS and
            (mandatory_met or not V19_5M_MANDATORY_ONE)
        )
        
        return {
            'score': signals_met,
            'items_met': signals_met,
            'details': details,
            'signals': signals,
            'bounce_confirmed': bounce_confirmed,
            'mandatory_met': mandatory_met,
            'rsi_rising': rsi_rising,
            'is_bullish': is_bullish,
            'volume_up': volume_ok,
            'bb_pos_rising': bb_pos_rising,
            'v_reversal': v_reversal_detected,
            'lower_shadow': lower_shadow_detected
        }
        
    except Exception as e:
        if DEBUG_MODE:
            print(f"{Colors.RED}[v19.0 Bounce Score Error] {e}{Colors.ENDC}")
        return {
            'score': 0, 'items_met': 0, 'details': [f'오류: {e}'],
            'signals': {}, 'bounce_confirmed': False,
            'rsi_rising': False, 'is_bullish': False,
            'volume_up': False,
            'mandatory_met': False,
            'v_reversal': False, 'lower_shadow': False
        }

# ==========================================================================
# [v11.0] 매도 모멘텀 소진 점수 시스템
# ==========================================================================

def detect_rapid_decline(df_15m, df_5m=None, regime='NEUTRAL'):
    """
    [v20.0] 급락 감지 (Layer 1 급락 방어선용)
    
    3가지 조건 중 하나라도 충족 시 급락으로 판정:
    ① 1캔들 내 하락률 > 기준 (BEAR: 0.3%, 기본: 0.5%)
    ② BB 위치 1캔들 내 10%p 이상 하락
    ③ 현재가가 15분봉 BB 중단선(MA20) 아래로 이탈
    
    Returns:
        dict: {'is_rapid': bool, 'triggers': list, 'severity': float}
    """
    result = {'is_rapid': False, 'triggers': [], 'severity': 0.0}
    
    try:
        # --- 기본 데이터 준비 ---
        if df_15m is None or len(df_15m) < 3:
            return result
        
        current = df_15m.iloc[-1]
        prev = df_15m.iloc[-2]
        
        # 레짐별 급락 기준
        drop_threshold = PPF_RAPID_DROP_PCT_BEAR if regime == 'BEARISH' else PPF_RAPID_DROP_PCT
        
        severity = 0.0
        
        # ① 1캔들 내 가격 하락률
        if prev['close'] > 0:
            candle_drop = ((prev['close'] - current['close']) / prev['close']) * 100
            if candle_drop > drop_threshold:
                result['triggers'].append(f'15분봉하락{candle_drop:.2f}%>{drop_threshold}%')
                severity += candle_drop
        
        # 5분봉이 있으면 더 민감하게 감지
        if df_5m is not None and len(df_5m) >= 2:
            curr_5m = df_5m.iloc[-1]
            prev_5m = df_5m.iloc[-2]
            if prev_5m['close'] > 0:
                drop_5m = ((prev_5m['close'] - curr_5m['close']) / prev_5m['close']) * 100
                if drop_5m > drop_threshold:
                    result['triggers'].append(f'5분봉하락{drop_5m:.2f}%')
                    severity += drop_5m
        
        # ② BB 위치 급락 (1캔들 내)
        bb_drop = prev['bb_position'] - current['bb_position']
        if bb_drop >= PPF_RAPID_BB_DROP:
            result['triggers'].append(f'BB급락{prev["bb_position"]:.0f}→{current["bb_position"]:.0f}')
            severity += bb_drop / 10.0
        
        # ③ MA20 이탈 확인
        if PPF_RAPID_BELOW_MA:
            bb_middle = current.get('bb_middle', None)
            if bb_middle is not None and current['close'] < bb_middle:
                # 직전에는 MA20 위에 있었는데 지금 아래로 이탈
                prev_bb_middle = prev.get('bb_middle', None)
                if prev_bb_middle is not None and prev['close'] >= prev_bb_middle:
                    result['triggers'].append(f'MA20이탈({current["close"]:,.0f}<{bb_middle:,.0f})')
                    severity += 1.0
        
        result['is_rapid'] = len(result['triggers']) > 0
        result['severity'] = severity
        
    except Exception as e:
        if DEBUG_MODE:
            print(f"{Colors.RED}[v20.0 RapidDecline Error] {e}{Colors.ENDC}")
    
    return result


def calculate_profit_protection_floor(held_info, current_price, df_5m=None, regime='NEUTRAL'):
    """
    [v20.0] 이익 보호선 계산 (Layer 2 확인된 수익 보호선)
    
    피크 수익과 유지 시간에 따라 동적 보호선 결정.
    
    Args:
        held_info: 보유 코인 정보 (peak_profit_pct, peak_bb_above_70, candles_at_peak 포함)
        current_price: 현재가
        df_5m: 5분봉 데이터 (양봉 유예 판단용)
        regime: 시장 레짐 ('BULLISH', 'NEUTRAL', 'BEARISH')
    
    Returns:
        dict: {
            'active_tier': str or None,
            'floor_pct': float,       # 보호선 수익률 (%)
            'floor_price': float,     # 보호선 가격
            'should_sell': bool,
            'reason': str,
            'deferred': bool          # 양봉 유예 여부
        }
    """
    result = {
        'active_tier': None,
        'floor_pct': -999.0,
        'floor_price': 0,
        'should_sell': False,
        'reason': '',
        'deferred': False
    }
    
    try:
        if not PPF_CONFIRMED_ENABLED:
            return result
        
        buy_price = held_info.get('buy_price', 0)
        if buy_price <= 0:
            return result
        
        peak_profit = held_info.get('peak_profit_pct', 0)
        peak_bb_above_70 = held_info.get('peak_bb_above_70', False)
        candles_at_peak = held_info.get('candles_at_peak', 0)
        current_profit = ((current_price - buy_price) / buy_price) * 100
        
        # --- 레짐별 보호선 선택 함수 ---
        def get_floor(neutral, bull, bear):
            if regime == 'BULLISH':
                return bull
            elif regime == 'BEARISH':
                return bear
            return neutral
        
        # --- 티어 판정 (높은 티어 우선) ---
        active_tier = None
        floor_pct = -999.0
        
        # Tier D: 초대형 수익 (시간 면제)
        if peak_profit >= PPF_TIER_D_PEAK:
            active_tier = 'D'
            floor_pct = get_floor(PPF_TIER_D_FLOOR, PPF_TIER_D_FLOOR_BULL, PPF_TIER_D_FLOOR_BEAR)
        
        # Tier C: 대형 수익 (시간 면제)
        elif peak_profit >= PPF_TIER_C_PEAK:
            active_tier = 'C'
            floor_pct = get_floor(PPF_TIER_C_FLOOR, PPF_TIER_C_FLOOR_BULL, PPF_TIER_C_FLOOR_BEAR)
        
        # Tier B: 중간 수익 (캔들 유지 필요)
        elif peak_profit >= PPF_TIER_B_PEAK and candles_at_peak >= PPF_TIER_B_CANDLES:
            active_tier = 'B'
            floor_pct = get_floor(PPF_TIER_B_FLOOR, PPF_TIER_B_FLOOR_BULL, PPF_TIER_B_FLOOR_BEAR)
        
        # Tier A: 소폭 수익 (BB 도달 + 캔들 유지 필요)
        elif (peak_profit >= PPF_TIER_A_PEAK and 
              peak_bb_above_70 and 
              candles_at_peak >= PPF_TIER_A_CANDLES):
            active_tier = 'A'
            floor_pct = get_floor(PPF_TIER_A_FLOOR, PPF_TIER_A_FLOOR_BULL, PPF_TIER_A_FLOOR_BEAR)
        
        if active_tier is None:
            return result
        
        floor_price = buy_price * (1 + floor_pct / 100)
        
        result['active_tier'] = active_tier
        result['floor_pct'] = floor_pct
        result['floor_price'] = floor_price
        
        # --- 보호선 하회 판정 ---
        if current_profit <= floor_pct:
            # 양봉 유예: 현재 5분봉이 양봉이면 발동 유예
            if PPF_BULLISH_CANDLE_DEFER and df_5m is not None and len(df_5m) >= 1:
                curr_5m = df_5m.iloc[-1]
                if curr_5m['close'] > curr_5m['open']:
                    result['deferred'] = True
                    result['reason'] = (
                        f'보호선Tier{active_tier}하회유예 '
                        f'(현재{current_profit:.2f}%≤보호{floor_pct:.1f}%, '
                        f'5분양봉유예)')
                    return result
            
            # 냉각기 확인 (held_info의 floor_breach_count로 관리)
            breach_count = held_info.get('floor_breach_count', 0) + 1
            held_info['floor_breach_count'] = breach_count
            
            if breach_count >= PPF_COOLDOWN_CYCLES:
                result['should_sell'] = True
                result['reason'] = (
                    f'보호선Tier{active_tier} '
                    f'(피크{peak_profit:.2f}%→현재{current_profit:.2f}%, '
                    f'보호선{floor_pct:.1f}%, {regime}, '
                    f'{breach_count}회연속하회)')
            else:
                result['reason'] = (
                    f'보호선Tier{active_tier}냉각중 '
                    f'({breach_count}/{PPF_COOLDOWN_CYCLES}회, '
                    f'현재{current_profit:.2f}%≤{floor_pct:.1f}%)')
        else:
            # 보호선 위에 있으면 breach count 리셋
            held_info['floor_breach_count'] = 0
            result['reason'] = (
                f'보호선Tier{active_tier}안전 '
                f'(현재{current_profit:.2f}%>{floor_pct:.1f}%)')
        
    except Exception as e:
        if DEBUG_MODE:
            print(f"{Colors.RED}[v20.0 PPF Error] {e}{Colors.ENDC}")
    
    return result


def assess_trend_strength_15m(df_15m):
    """
    [v20.0] BB 상단 추세 강도 판정 (15분봉)
    
    5개 축으로 상승 추세 지속력 평가:
    ① RSI 상승 유지 (방향 + 50 이상)
    ② SRSI K>D 골든크로스 상태 유지
    ③ MACD 히스토그램 확장 (양수 & 증가)
    ④ 밴드워크 패턴 (N봉 연속 BB 70%+)
    ⑤ 거래량 증가 추세
    
    Returns:
        dict: {
            'grade': 'STRONG'|'MODERATE'|'WEAK',
            'score': int (0~5),
            'signals': dict,
            'detail': str
        }
    """
    default = {'grade': 'WEAK', 'score': 0, 'signals': {}, 'detail': '데이터부족'}
    
    try:
        if df_15m is None or len(df_15m) < TREND_STRENGTH_BANDWALK_LEN + 1:
            return default
        
        current = df_15m.iloc[-1]
        prev = df_15m.iloc[-2]
        
        score = 0
        signals = {}
        details = []
        
        # ① RSI 상승 유지
        rsi_now = current['rsi']
        rsi_prev = prev['rsi']
        rsi_rising = (rsi_now > rsi_prev) and (rsi_now >= 50)
        signals['rsi_rising'] = rsi_rising
        if rsi_rising:
            score += 1
            details.append(f'RSI↑{rsi_now:.0f}')
        
        # ② SRSI K > D (골든크로스 상태)
        stoch_k = current.get('stoch_rsi_k', 50)
        stoch_d = current.get('stoch_rsi_d', 50)
        srsi_golden = stoch_k > stoch_d
        signals['srsi_golden'] = srsi_golden
        if srsi_golden:
            score += 1
            details.append(f'SRSI골든K{stoch_k:.0f}>D{stoch_d:.0f}')
        
        # ③ MACD 히스토그램 확장 (양수 & 전봉 대비 증가)
        macd_hist = current.get('macd_hist', 0)
        macd_hist_prev = prev.get('macd_hist', 0)
        macd_expanding = (macd_hist > 0) and (macd_hist > macd_hist_prev)
        signals['macd_expanding'] = macd_expanding
        if macd_expanding:
            score += 1
            details.append(f'MACD확장{macd_hist:.4f}')
        
        # ④ 밴드워크 (N봉 연속 BB 70%+, 종가 상승세)
        bandwalk = True
        bw_len = TREND_STRENGTH_BANDWALK_LEN
        if len(df_15m) >= bw_len + 1:
            for i in range(bw_len):
                idx = -(bw_len - i)
                if df_15m.iloc[idx]['bb_position'] < TREND_STRENGTH_BANDWALK_BB:
                    bandwalk = False
                    break
            # 추가: 첫 봉 대비 마지막 봉 종가 상승
            if bandwalk:
                first_close = df_15m.iloc[-bw_len]['close']
                last_close = current['close']
                if last_close < first_close:
                    bandwalk = False
        else:
            bandwalk = False
        
        signals['bandwalk'] = bandwalk
        if bandwalk:
            score += 1
            details.append(f'밴드워크{bw_len}봉')
        
        # ⑤ 거래량 증가 추세 (최근 3봉 중 2봉 이상 전봉 대비 증가)
        vol_rising = False
        if len(df_15m) >= 4:
            vol_increases = 0
            for i in range(-3, 0):
                if df_15m.iloc[i]['volume'] > df_15m.iloc[i-1]['volume']:
                    vol_increases += 1
            vol_rising = vol_increases >= 2
        
        signals['volume_rising'] = vol_rising
        if vol_rising:
            score += 1
            details.append('거래량↑')
        
        # --- 등급 판정 ---
        if score >= TREND_STRENGTH_STRONG:
            grade = 'STRONG'
        elif TREND_STRENGTH_MODERATE_MIN <= score <= TREND_STRENGTH_MODERATE_MAX:
            grade = 'MODERATE'
        else:
            grade = 'WEAK'
        
        detail_str = ','.join(details) if details else '신호없음'
        
        return {
            'grade': grade,
            'score': score,
            'signals': signals,
            'detail': f'{grade}({score}/5:{detail_str})'
        }
        
    except Exception as e:
        if DEBUG_MODE:
            print(f"{Colors.RED}[v20.0 TrendStrength Error] {e}{Colors.ENDC}")
        return default


def analyze_5m_micro_momentum(df_5m, df_15m=None):
    """
    [v20.0] 5분봉 미세 모멘텀 분석
    
    4가지 단기 약세 신호 감지:
    ① BB 상단 터치 후 연속 음봉
    ② 거래량 3봉 연속 감소
    ③ RSI 약세 다이버전스 (가격↑ but RSI↓)
    ④ SRSI K/D 데드크로스 (과매수권에서)
    
    Returns:
        dict: {
            'bearish_score': int (0~4),
            'is_weak': bool,
            'signals': dict,
            'detail': str
        }
    """
    default = {'bearish_score': 0, 'is_weak': False, 'signals': {}, 'detail': '5분봉없음'}
    
    try:
        if df_5m is None or len(df_5m) < 5:
            return default
        
        current = df_5m.iloc[-1]
        prev = df_5m.iloc[-2]
        
        bearish_score = 0
        signals = {}
        details = []
        
        # ① BB 상단 터치 후 연속 음봉
        bb_upper_touched = False
        consecutive_bearish = 0
        
        # 최근 5개 5분봉에서 BB 상단 터치 이력 확인
        for i in range(-5, 0):
            if abs(i) <= len(df_5m):
                candle = df_5m.iloc[i]
                if candle['bb_position'] >= 90:
                    bb_upper_touched = True
                    break
        
        if bb_upper_touched:
            # 터치 이후 연속 음봉 카운트
            for i in range(-1, -MICRO_5M_BEARISH_CANDLES - 1, -1):
                if abs(i) <= len(df_5m):
                    c = df_5m.iloc[i]
                    if c['close'] < c['open']:
                        consecutive_bearish += 1
                    else:
                        break
        
        sig_bb_bearish = (bb_upper_touched and consecutive_bearish >= MICRO_5M_BEARISH_CANDLES)
        signals['bb_upper_then_bearish'] = sig_bb_bearish
        if sig_bb_bearish:
            bearish_score += 1
            details.append(f'BB상단후음봉{consecutive_bearish}개')
        
        # ② 거래량 감소 추세
        vol_declining = False
        if len(df_5m) >= MICRO_5M_VOL_DECLINE_LEN + 1:
            vol_declining = True
            for i in range(-MICRO_5M_VOL_DECLINE_LEN, 0):
                if df_5m.iloc[i]['volume'] >= df_5m.iloc[i-1]['volume']:
                    vol_declining = False
                    break
        
        signals['volume_declining'] = vol_declining
        if vol_declining:
            bearish_score += 1
            details.append(f'거래량{MICRO_5M_VOL_DECLINE_LEN}봉↓')
        
        # ③ RSI 약세 다이버전스 (최근 5봉 내 가격 고점은 높아졌는데 RSI 고점은 낮아짐)
        rsi_divergence = False
        if len(df_5m) >= 5:
            # 최근 5봉에서 가격 최고점과 RSI 최고점 비교
            recent_5 = df_5m.iloc[-5:]
            prev_5 = df_5m.iloc[-10:-5] if len(df_5m) >= 10 else None
            
            if prev_5 is not None and len(prev_5) >= 3:
                recent_price_high = recent_5['high'].max()
                prev_price_high = prev_5['high'].max()
                recent_rsi_high = recent_5['rsi'].max()
                prev_rsi_high = prev_5['rsi'].max()
                
                if recent_price_high > prev_price_high and recent_rsi_high < prev_rsi_high:
                    rsi_divergence = True
        
        signals['rsi_divergence'] = rsi_divergence
        if rsi_divergence:
            bearish_score += 1
            details.append('RSI약세다이버전스')
        
        # ④ SRSI 데드크로스 (과매수권에서)
        stoch_k = current.get('stoch_rsi_k', 50)
        stoch_d = current.get('stoch_rsi_d', 50)
        stoch_k_prev = prev.get('stoch_rsi_k', 50)
        stoch_d_prev = prev.get('stoch_rsi_d', 50)
        
        srsi_dead = (
            stoch_k_prev >= MICRO_5M_SRSI_DEAD_THRESHOLD and
            stoch_k < stoch_d and
            stoch_k_prev >= stoch_d_prev
        )
        signals['srsi_dead_cross'] = srsi_dead
        if srsi_dead:
            bearish_score += 1
            details.append(f'SRSI데드K{stoch_k:.0f}<D{stoch_d:.0f}')
        
        is_weak = bearish_score >= MICRO_5M_WEAK_THRESHOLD
        detail_str = ','.join(details) if details else '약세신호없음'
        
        return {
            'bearish_score': bearish_score,
            'is_weak': is_weak,
            'signals': signals,
            'detail': f'{bearish_score}/4({detail_str})'
        }
        
    except Exception as e:
        if DEBUG_MODE:
            print(f"{Colors.RED}[v20.0 Micro5m Error] {e}{Colors.ENDC}")
        return default


def calculate_sell_exhaustion_score(df_15m, held_info=None):
    """
    [v11.0] 매도 모멘텀 소진 점수 계산
    
    매수 Phase 3 (calculate_reversal_score)의 "반대" 로직.
    7개 지표 (7점 만점):
    ① RSI 하락 전환 (1점)
    ② SRSI 과매수/데드크로스 (1점)
    ③ MACD 히스토그램 음전환/축소 (1점)
    ④ 음봉 출현 (1점)
    ⑤ 거래량 감소 추세 (1점)
    ⑥ 고점 연속 하락 3봉 (1점)
    ⑦ Lower High 확정 (1점)
    """
    try:
        if df_15m is None or len(df_15m) < 5:
            return {
                'score': 0, 'signals': {}, 'details': ['데이터 부족'],
                'bb_position': 50, 'dynamic_threshold': 99,
                'should_sell': False
            }
        
        current = df_15m.iloc[-1]
        prev = df_15m.iloc[-2]
        
        score = 0
        details = []
        signals = {}
        
        # ① RSI 하락 전환
        rsi_now = current['rsi']
        rsi_prev = prev['rsi']
        rsi_dropping = rsi_now < rsi_prev
        signals['rsi_dropping'] = rsi_dropping
        
        if rsi_dropping:
            score += V11_SELL_RSI_DROP_SCORE
            details.append(f"①RSI↓ {rsi_prev:.0f}→{rsi_now:.0f}")
        
        # ② SRSI 과매수/데드크로스
        stoch_k = current.get('stoch_rsi_k', 50)
        stoch_d = current.get('stoch_rsi_d', 50)
        stoch_k_prev = prev.get('stoch_rsi_k', 50)
        stoch_d_prev = prev.get('stoch_rsi_d', 50)
        
        srsi_overbought_drop = (stoch_k_prev >= V11_SELL_SRSI_OVERBOUGHT and stoch_k < stoch_k_prev)
        srsi_dead_cross = (stoch_k < stoch_d and stoch_k_prev >= stoch_d_prev)
        srsi_signal = srsi_overbought_drop or srsi_dead_cross
        signals['srsi_exhaustion'] = srsi_signal
        
        if srsi_signal:
            score += V11_SELL_SRSI_SCORE
            if srsi_overbought_drop:
                details.append(f"②SRSI과매수↓ K:{stoch_k:.0f}")
            else:
                details.append(f"②SRSI데드크로스 K:{stoch_k:.0f}<D:{stoch_d:.0f}")
        
        # ③ MACD 히스토그램 음전환/축소
        macd_hist = current.get('macd_hist', 0)
        macd_hist_prev = prev.get('macd_hist', 0)
        
        macd_negative_cross = (macd_hist_prev > 0 and macd_hist <= 0)
        macd_weakening = (macd_hist_prev > 0 and macd_hist > 0 and macd_hist < macd_hist_prev)
        macd_signal = macd_negative_cross or macd_weakening
        signals['macd_exhaustion'] = macd_signal
        
        if macd_signal:
            score += V11_SELL_MACD_SCORE
            if macd_negative_cross:
                details.append(f"③MACD음전환")
            else:
                details.append(f"③MACD약화(감소)")
        
        # ④ 음봉 출현
        is_bearish = current['close'] < current['open']
        signals['bearish_candle'] = is_bearish
        
        if is_bearish:
            score += V11_SELL_BEARISH_SCORE
            change_pct = ((current['close'] - current['open']) / current['open']) * 100
            details.append(f"④음봉 {change_pct:.2f}%")
        
        # ⑤ 거래량 감소 추세 (최근 3봉 연속 감소)
        if len(df_15m) >= 4:
            vol_3 = df_15m.iloc[-4]['volume']
            vol_2 = df_15m.iloc[-3]['volume']
            vol_1 = prev['volume']
            vol_0 = current['volume']
            volume_declining = (vol_3 > vol_2 > vol_1 > vol_0) and (vol_0 > 0)
        else:
            volume_declining = False
        
        signals['volume_declining'] = volume_declining
        
        if volume_declining:
            score += V11_SELL_VOLUME_DECLINE_SCORE
            details.append(f"⑤거래량3봉↓")
        
        # ⑥ 고점 연속 하락 (최근 3봉 high 감소)
        if len(df_15m) >= V11_HIGH_DECLINE_LOOKBACK + 1:
            highs_declining = True
            for i in range(1, V11_HIGH_DECLINE_LOOKBACK):
                idx_curr = -(i)
                idx_prev = -(i + 1)
                if df_15m.iloc[idx_curr]['high'] >= df_15m.iloc[idx_prev]['high']:
                    highs_declining = False
                    break
        else:
            highs_declining = False
        
        signals['highs_declining'] = highs_declining
        
        if highs_declining:
            score += V11_SELL_HIGH_DECLINING_SCORE
            h_prev = df_15m.iloc[-3]['high']
            h_curr = current['high']
            details.append(f"⑥고점3봉↓ {h_prev:,.0f}→{h_curr:,.0f}")
        
        # ⑦ Lower High 확정 (Swing High 기반)
        lower_high_detected = False
        prev_high_price = 0
        recent_high_price = 0
        swing_highs = find_recent_swing_highs(
            df_15m,
            lookback=V11_SELL_SWING_LOOKBACK,
            swing_size=V11_SELL_SWING_SIZE
        )
        
        if len(swing_highs) >= 2:
            prev_high_price = swing_highs[-2]['price']
            recent_high_price = swing_highs[-1]['price']
            tolerance = prev_high_price * (V11_SELL_LOWER_HIGH_TOLERANCE / 100)
            lower_high_detected = recent_high_price < (prev_high_price - tolerance)
        
        signals['lower_high'] = lower_high_detected
        
        if lower_high_detected:
            score += V11_SELL_LOWER_HIGH_SCORE
            details.append(f"⑦LowerHigh {prev_high_price:,.0f}→{recent_high_price:,.0f}")
        
        # 동적 임계치 계산
        bb_position = current['bb_position']
        
        if bb_position >= 85:
            base_threshold = V11_SELL_THRESHOLD_BB_HIGH
        elif bb_position >= 70:
            base_threshold = V11_SELL_THRESHOLD_BB_MID
        elif bb_position >= V11_SELL_BB_NO_SELL_BELOW:
            base_threshold = V11_SELL_THRESHOLD_BB_LOW
        else:
            base_threshold = 99
        
        # 수익률 보너스
        profit_bonus = 0
        current_profit = 0.0
        if held_info:
            buy_price = held_info.get('buy_price', 0)
            if buy_price > 0:
                current_profit = ((current['close'] - buy_price) / buy_price) * 100
                if current_profit >= V11_SELL_PROFIT_HIGH_THRESHOLD:
                    profit_bonus = V11_SELL_PROFIT_BONUS_HIGH
                elif current_profit >= V11_SELL_PROFIT_MID_THRESHOLD:
                    profit_bonus = V11_SELL_PROFIT_BONUS_MID
        
        dynamic_threshold = max(1, base_threshold - profit_bonus)
        should_sell = (score >= dynamic_threshold) and (bb_position >= V11_SELL_BB_NO_SELL_BELOW)
        
        return {
            'score': score,
            'signals': signals,
            'details': details,
            'bb_position': bb_position,
            'base_threshold': base_threshold,
            'profit_bonus': profit_bonus,
            'dynamic_threshold': dynamic_threshold,
            'current_profit': current_profit,
            'should_sell': should_sell,
            'swing_highs_count': len(swing_highs),
            'lower_high': lower_high_detected
        }
        
    except Exception as e:
        if DEBUG_MODE:
            print(f"{Colors.RED}[Sell Exhaustion Error] {e}{Colors.ENDC}")
            traceback.print_exc()
        return {
            'score': 0, 'signals': {}, 'details': [f'오류: {e}'],
            'bb_position': 50, 'dynamic_threshold': 99,
            'should_sell': False
        }


def format_sell_exhaustion_detail(exhaustion):
    """
    [v11.0] 매도 모멘텀 소진 지표 압축 기호 생성
    R=RSI↓, S=SRSI, M=MACD, B=음봉, V=거래량, H=고점↓, L=LowerHigh
    """
    try:
        signals = exhaustion.get('signals', {})
        score = exhaustion.get('score', 0)
        threshold = exhaustion.get('dynamic_threshold', 99)
        
        r = '✅' if signals.get('rsi_dropping', False) else '❌'
        s = '✅' if signals.get('srsi_exhaustion', False) else '❌'
        m = '✅' if signals.get('macd_exhaustion', False) else '❌'
        b = '✅' if signals.get('bearish_candle', False) else '❌'
        v = '✅' if signals.get('volume_declining', False) else '❌'
        h = '✅' if signals.get('highs_declining', False) else '❌'
        l = '✅' if signals.get('lower_high', False) else '❌'
        
        return f"R{r}S{s}M{m}B{b}V{v}H{h}L{l}({score}/7→임계{threshold})"
    except:
        return f"({exhaustion.get('score', 0)}/7)"


def calculate_dynamic_trailing(bb_position, profit_pct, held_info=None):
    """
    [v11.0] 동적 트레일링 스탑 계산
    
    3구간:
    - 적극 (BB 85%+ OR 수익 3%+): 활성화 1.0%, 거리 0.5%
    - 기본 (BB 65-85% AND 수익 1.5%+): 활성화 1.5%, 거리 0.8%
    - 보수 (기타): 활성화 2.0%, 거리 1.2%
    """
    try:
        if bb_position >= V11_TRAILING_AGGRESSIVE_BB or profit_pct >= V11_TRAILING_AGGRESSIVE_PROFIT:
            zone = 'AGGRESSIVE'
            activation = V11_TRAILING_AGGRESSIVE_ACTIVATION
            distance = V11_TRAILING_AGGRESSIVE_DISTANCE
        elif (V11_TRAILING_NORMAL_BB_MIN <= bb_position < V11_TRAILING_NORMAL_BB_MAX and 
              profit_pct >= V11_TRAILING_NORMAL_PROFIT):
            zone = 'NORMAL'
            activation = V11_TRAILING_NORMAL_ACTIVATION
            distance = V11_TRAILING_NORMAL_DISTANCE
        else:
            zone = 'CONSERVATIVE'
            activation = V11_TRAILING_CONSERVATIVE_ACTIVATION
            distance = V11_TRAILING_CONSERVATIVE_DISTANCE
        
        is_active = profit_pct >= activation
        should_sell = False
        drawdown_from_peak = 0.0
        peak_profit = 0.0
        
        if is_active and held_info:
            buy_price = held_info.get('buy_price', 0)
            peak_price = held_info.get('peak_price', buy_price)
            current_price = held_info.get('_current_price', 0)
            
            if peak_price > 0 and current_price > 0:
                drawdown_from_peak = (peak_price - current_price) / peak_price * 100
                peak_profit = ((peak_price - buy_price) / buy_price) * 100
                should_sell = drawdown_from_peak >= distance
        
        return {
            'zone': zone,
            'activation': activation,
            'distance': distance,
            'is_active': is_active,
            'should_sell': should_sell,
            'drawdown_from_peak': drawdown_from_peak,
            'peak_profit': peak_profit
        }
        
    except Exception as e:
        if DEBUG_MODE:
            print(f"{Colors.RED}[Dynamic Trailing Error] {e}{Colors.ENDC}")
        return {
            'zone': 'CONSERVATIVE',
            'activation': 2.0, 'distance': 1.2,
            'is_active': False, 'should_sell': False,
            'drawdown_from_peak': 0, 'peak_profit': 0
        }


def detect_decline_signals(df_15m, df_5m=None, held_info=None):
    """
    [v11.0] 레거시 호환 래퍼
    calculate_sell_exhaustion_score를 호출하여 기존 인터페이스 유지
    """
    try:
        exhaustion = calculate_sell_exhaustion_score(df_15m, held_info)
        return {
            'score': exhaustion['score'],
            'should_exit': exhaustion['should_sell'],
            'details': exhaustion['details'],
            'threshold': exhaustion['dynamic_threshold'],
            'exhaustion_detail': exhaustion
        }
    except Exception as e:
        return {'score': 0, 'should_exit': False, 'details': [f'오류: {e}'], 'threshold': 5}


def evolution_80_buy_signal(df_15m, df_5m, ticker):
    """
    [v19.0] DUAL TIMEFRAME BOUNCE HUNTER - 시간대별 다중 지표 반등 매수 신호
    [v18.0] BOUNCE HUNTER - 시간대별 다중 지표 반등 매수 신호
    
    v18.0 설계 철학:
    - DAY: 일봉 모멘텀 중시 (기존 v17.0 100% 유지)
    - NIGHT: "문은 넓게, 진입은 정확하게"
      Phase 1 완화(음봉허용) + Phase 2 강화(BB≤25%) + Phase 3 V신호
    
    3-Phase 구조:
    Phase 0: 시간대 모드 + 시장 레짐 판별
    Phase 1: 일봉 양봉 필터 (NIGHT: 완화 → 음봉도 통과)
    Phase 2: 15분봉 BB 하단 위치 (NIGHT: 강화 → BB 25% 이하만)
    Phase 3: 다중 지표 반등 신호 (NIGHT: V-Reversal 추가)
    """
    try:
        current = df_15m.iloc[-1] if df_15m is not None and len(df_15m) > 0 else None
        
        # [v18.0] 시간대 모드 판별
        time_mode = get_time_mode()
        
        base_response = {
            'signal': False,
            'reason': '',
            'confidence': 0,
            'entry_price': current['close'] if current is not None else 0,
            'bb_position': current['bb_position'] if current is not None else 50,
            'bb_width_pct': current['bb_width'] if current is not None else 2.0,
            'mode': 'BOUNCE_V19',
            'market_condition': 'NORMAL',
            'score': 0,
            'daily_change': 0,
            'reversal_score': 0,
            'bb_width_zone': 'UNKNOWN',
            'regime': 'NEUTRAL',
            'regime_score': 0,
            'regime_details': '',
            'time_mode': time_mode              # [v18.0 신규]
        }
        
        if df_15m is None or len(df_15m) < 20:
            base_response['reason'] = '15분봉 데이터 부족'
            return base_response
        
        # [v19.0] 5분봉 데이터 체크 (반등 트리거 필수)
        if df_5m is None or len(df_5m) < 20:
            base_response['reason'] = '5분봉 데이터 부족 (v19.0 필수)'
            return base_response
        
        # ========================================
        # Phase 0: 시장 레짐 판별 (기존 동일)
        # ========================================
        regime_info = determine_market_regime(ticker, df_15m)
        regime = regime_info['regime']
        
        base_response['regime'] = regime
        base_response['regime_score'] = regime_info['score']
        base_response['regime_details'] = regime_info['details']
        
        if DEBUG_MODE:
            coin_name = ticker.replace('KRW-', '')
            regime_emoji = {'BULLISH': '🟢', 'NEUTRAL': '🟡', 'BEARISH': '🔴'}.get(regime, '⚪')
            time_emoji = '🌙' if time_mode == 'NIGHT' else '☀️'
            print(f"  {regime_emoji}{time_emoji} [{coin_name}] 레짐: {regime_info['details']} | 모드: {time_mode}")
        
        # ========================================
        # Phase 1: 일봉 양봉 필터 [v18.0 time_mode 전달]
        # NIGHT: 문을 넓게 (음봉 허용)
        # ========================================
        daily_safety = check_daily_safety_filter(ticker, regime=regime, time_mode=time_mode)

        base_response['daily_change'] = daily_safety.get('daily_change', 0)
        
        if not daily_safety['safe']:
            base_response['reason'] = f"P1거부: {daily_safety['reason']}"
            base_response['market_condition'] = 'DAILY_UNSAFE'
            return base_response
        
        # ========================================
        # Phase 2: 15분봉 BB 하단 위치 확인 [v18.0 time_mode 전달]
        # NIGHT: 진입은 정확하게 (BB 25% 이하만)
        # ========================================
        daily_candle_type = daily_safety.get('daily_candle_type', 'unknown')
        position_check = detect_downtrend_15m(df_15m, daily_candle_type=daily_candle_type, 
                                               regime=regime, time_mode=time_mode)
        
        if position_check['is_downtrend']:
            base_response['reason'] = f"P2거부: {position_check['reason']}"
            base_response['market_condition'] = 'POSITION_UNSUITABLE'
            return base_response
        
        bb_position = position_check['bb_position']
        bb_width = position_check['bb_width']
        
        # ========================================
        # Phase 3: 다중 지표 반등 신호 확인 [v18.0 time_mode 전달]
        # NIGHT: V-Reversal + 하단꼬리 추가, 최소 2개
        # ========================================
        reversal = calculate_reversal_score(df_15m, time_mode=time_mode)
        base_response['reversal_score'] = reversal['score']
        
        # [v18.0] 시간대 + 레짐별 최소 신호수 결정
        if time_mode == 'NIGHT':
            required_signals = V19_5M_BOUNCE_MIN_NIGHT          # 2 (통일 완화)
        elif REGIME_ENABLED:
            if regime == 'BULLISH':
                required_signals = V19_5M_BOUNCE_MIN_BULL       # 3 (v19.0)
            elif regime == 'BEARISH':
                required_signals = V19_5M_BOUNCE_MIN_BEAR       # 4 (v19.0)
            else:
                required_signals = V19_5M_BOUNCE_MIN_NEUT       # 3 (v19.0)
        else:
            required_signals = V10_BOUNCE_MIN_SIGNALS             # 3
        
        if not reversal['bounce_confirmed'] or reversal['score'] < required_signals:
            met = reversal['score']
            mandatory = reversal.get('mandatory_met', False)
            detail_str = ', '.join(reversal['details']) if reversal['details'] else '신호없음'
            
            reason_parts = [f"P3거부: 반등{met}/{required_signals}개"]
            if not mandatory and V10_BOUNCE_MANDATORY_ONE:
                if time_mode == 'NIGHT':
                    reason_parts.append("필수(RSI↑or양봉orV반등)미충족")
                else:
                    reason_parts.append("필수(RSI↑or양봉)미충족")
            reason_parts.append(f"[{detail_str}]")
            
            base_response['reason'] = ' '.join(reason_parts)
            base_response['market_condition'] = 'NO_BOUNCE'
            return base_response
        
        # 필수 조건 별도 체크
        mandatory_met = reversal.get('mandatory_met', False)
        if V19_5M_MANDATORY_ONE and not mandatory_met:
            base_response['reason'] = f"P3거부: 필수미충족 [{', '.join(reversal['details'])}]"
            base_response['market_condition'] = 'NO_BOUNCE'
            return base_response
        
        # ========================================
        # 모든 Phase 통과 → 매수 신호!
        # ========================================
        confidence = min(100, 40 + reversal['score'] * 12 + int(bb_width * 3))
        
        # 레짐별 신뢰도 보정
        if regime == 'BULLISH':
            confidence = min(100, confidence + 5)
        elif regime == 'BEARISH':
            confidence = max(30, confidence - 5)
        
        # [v18.0] NIGHT 모드 보정: V-Reversal 감지 시 +3
        if time_mode == 'NIGHT' and reversal.get('v_reversal', False):
            confidence = min(100, confidence + 3)
        
        daily_info = daily_safety['reason']
        bounce_detail = ', '.join(reversal['details'][:4]) if reversal['details'] else ''
        
        # [v18.0] 시간대 + 레짐 태그
        time_tag = '🌙' if time_mode == 'NIGHT' else ''
        regime_tag = f"[{regime}]"
        
        return {
            'signal': True,
            'reason': f"{regime_tag}{time_tag} BOUNCE! BB{bb_position:.0f}% 폭{bb_width:.1f}% | {bounce_detail} | {daily_info}",
            'confidence': confidence,
            'entry_price': current['close'],
            'bb_position': bb_position,
            'bb_width_pct': bb_width,
            'mode': 'BOUNCE_V19',
            'market_condition': 'BOUNCE_CONFIRMED',
            'score': reversal['score'],
            'daily_change': daily_safety.get('daily_change', 0),
            'reversal_score': reversal['score'],
            'bb_width_zone': 'BOUNCE',
            'target_profit': V10_TARGET_PROFIT,
            'reversal_details': reversal['details'],
            'daily_bb': daily_safety.get('daily_bb', 50),
            'daily_rsi': daily_safety.get('daily_rsi', 50),
            'regime': regime,
            'regime_score': regime_info['score'],
            'regime_details': regime_info['details'],
            'time_mode': time_mode               # [v18.0 신규]
        }
        
    except Exception as e:
        if DEBUG_MODE:
            print(f"{Colors.RED}[v18.0 Buy Signal Error] {e}{Colors.ENDC}")
            traceback.print_exc()
        
        return {
            'signal': False, 'reason': f'오류: {str(e)}', 'confidence': 0,
            'entry_price': 0, 'bb_position': 50, 'bb_width_pct': 2.0,
            'mode': 'ERROR', 'market_condition': 'UNKNOWN', 'score': 0,
            'daily_change': 0, 'reversal_score': 0, 'bb_width_zone': 'ERROR',
            'regime': 'NEUTRAL', 'regime_score': 0, 'regime_details': '',
            'time_mode': 'DAY'
        }
    

def evolution_80_sell_signal(df, buy_price, buy_time=None, held_info=None, df_5m=None, regime='NEUTRAL'):
    """
    [v20.0] BUAE (BB Upper Adaptive Exit) 매도 시그널
    
    6단계 매도 의사결정:
    Step 1: 절대 손절 (ATR 기반 동적 손절)
    Step 2: 급락 방어선 (Emergency Floor) — 수익>0 보호
    Step 3: 확인된 수익 보호선 (Confirmed Profit Lock)
    Step 4: 극과매수 긴급 익절 (BB 95%+)
    Step 5: BB 상단 추세강도 + 5분봉 통합 판정 (BUAE 핵심)
    Step 6: 기존 소진점수제 + 트레일링 (안전망)
    
    v20.0 변경사항:
    - df_5m을 실제로 활용하여 미세 모멘텀 분석
    - regime 파라미터 추가로 시장 레짐별 차등 적용
    - 이익 보호선으로 "수익→손절" 전환 방지
    - 추세 강도 판정으로 QPL 동적 조절
    """
    try:
        if df is None or len(df) < 5:
            return {'signal': False, 'reason': '데이터 부족',
                    'exit_price': 0, 'profit_pct': 0,
                    'bb_position': 50, 'bb_width_pct': 2.0}
        
        current = df.iloc[-1]
        prev = df.iloc[-2]
        current_price = current['close']
        profit_pct = ((current_price - buy_price) / buy_price) * 100
        bb_position = current['bb_position']
        bb_width = current['bb_width']
        
        base_response = {
            'signal': False, 'exit_price': current_price,
            'profit_pct': profit_pct, 'bb_position': bb_position,
            'bb_width_pct': bb_width, 'reason': ''
        }
        
        # --- 피크 추적 (기존 유지 + v20.0 확장) ---
        if held_info is not None:
            if current_price > held_info.get('peak_price', buy_price):
                held_info['peak_price'] = current_price
                held_info['peak_time'] = datetime.now()
            if bb_position > held_info.get('peak_bb_position', 0):
                held_info['peak_bb_position'] = bb_position
            held_info['_current_price'] = current_price
            
            # [v20.0] 피크 수익률 추적
            peak_profit = ((held_info.get('peak_price', buy_price) - buy_price) / buy_price) * 100
            held_info['peak_profit_pct'] = peak_profit
            
            # [v20.0] BB 70%+ 도달 이력 추적
            if bb_position >= PPF_TIER_A_BB_REQUIRED:
                held_info['peak_bb_above_70'] = True
            
            # [v20.0] 피크 근처 유지 캔들 수 추적 (피크 대비 -0.3% 이내)
            if peak_profit > 0 and profit_pct >= peak_profit * 0.7:
                held_info['candles_at_peak'] = held_info.get('candles_at_peak', 0) + 1
            
            # [v20.0] 보호 티어 기록
            if 'protection_tier' not in held_info:
                held_info['protection_tier'] = None
                held_info['floor_breach_count'] = 0
        
        
        # ===== Step 1: 절대 손절 (ATR 기반 — 기존 100% 동일) =====
        if ATR_STOPLOSS_ENABLED and len(df) >= ATR_PERIOD + 1:
            try:
                atr_values = []
                for _i in range(-ATR_PERIOD, 0):
                    h = df.iloc[_i]['high']
                    l = df.iloc[_i]['low']
                    c_prev = df.iloc[_i-1]['close']
                    tr = max(h - l, abs(h - c_prev), abs(l - c_prev))
                    atr_values.append(tr)
                atr = np.mean(atr_values)
                atr_pct = (atr / current_price) * 100 if current_price > 0 else 2.0
                dynamic_stop = max(ATR_STOPLOSS_MAX, -(atr_pct * ATR_STOPLOSS_MULTIPLIER))
                dynamic_stop = min(ATR_STOPLOSS_MIN, dynamic_stop)
            except:
                dynamic_stop = V10_STOP_LOSS_PCT
        else:
            dynamic_stop = V10_STOP_LOSS_PCT
        
        if profit_pct <= dynamic_stop:
            return {**base_response, 'signal': True,
                    'reason': f'STOP_LOSS ({profit_pct:.2f}% <= 동적{dynamic_stop:.1f}%)'}
        
        
        # ===== Step 2: [v20.0] 급락 방어선 (Emergency Floor) =====
        if PPF_EMERGENCY_ENABLED and held_info is not None:
            peak_profit_pct = held_info.get('peak_profit_pct', 0)
            
            if peak_profit_pct >= PPF_EMERGENCY_PEAK_MIN:
                rapid = detect_rapid_decline(df, df_5m, regime)
                
                if rapid['is_rapid'] and profit_pct > 0:
                    triggers_str = '+'.join(rapid['triggers'][:2])
                    return {**base_response, 'signal': True,
                            'reason': (f'PPF_EMERGENCY 급락방어 '
                                       f'(피크{peak_profit_pct:.2f}%→현재{profit_pct:.2f}%, '
                                       f'{triggers_str})')}
        
        
        # ===== Step 3: [v20.0] 확인된 수익 보호선 (Confirmed Profit Lock) =====
        ppf_result = {'should_sell': False, 'active_tier': None, 'reason': ''}
        if PPF_CONFIRMED_ENABLED and held_info is not None:
            ppf_result = calculate_profit_protection_floor(
                held_info, current_price, df_5m, regime)
            
            if ppf_result['should_sell']:
                return {**base_response, 'signal': True,
                        'reason': f'PPF_CONFIRMED {ppf_result["reason"]}'}
            
            # 보호 티어 기록
            if ppf_result['active_tier']:
                held_info['protection_tier'] = ppf_result['active_tier']
        
        
        # ===== Step 4: 극과매수 긴급 익절 (기존 유지) =====
        is_bearish = current['close'] < current['open']
        if bb_position >= V11_SELL_EXTREME_BB and is_bearish and profit_pct >= V11_SELL_EXTREME_MIN_PROFIT:
            return {**base_response, 'signal': True,
                    'reason': f'극과매수익절 (BB{bb_position:.0f}%+음봉, 수익{profit_pct:.2f}%)'}
        
        
        # ===== Step 5: [v20.0] BUAE 핵심 — BB 상단 추세강도 + 5분봉 통합 판정 =====
        if bb_position >= TREND_STRENGTH_BB_ACTIVATE:
            
            # 15분봉 추세 강도 판정
            trend = assess_trend_strength_15m(df)
            trend_grade = trend['grade']
            
            # 5분봉 미세 모멘텀 분석
            micro = analyze_5m_micro_momentum(df_5m, df)
            micro_weak = micro['is_weak']
            
            # --- 통합 매도 판정 매트릭스 ---
            
            # STRONG + 5분봉 강세 = 절대 홀드 (보호선만 작동)
            if trend_grade == 'STRONG' and not micro_weak:
                base_response['reason'] = (
                    f'BUAE홀드_추세강함 ({trend["detail"]}, '
                    f'5분봉{micro["detail"]}, BB{bb_position:.0f}%, '
                    f'수익{profit_pct:.2f}%)')
                return base_response
            
            # STRONG + 5분봉 약세 = 경계 홀드 (높은 수익이면 매도 준비)
            if trend_grade == 'STRONG' and micro_weak:
                if profit_pct >= BUAE_SELL_STRONG_WEAK_PROFIT:
                    return {**base_response, 'signal': True,
                            'reason': (f'BUAE_TREND_EXIT 추세강+5분약세 '
                                       f'({trend["detail"]}, 5분봉{micro["detail"]}, '
                                       f'수익{profit_pct:.2f}%≥{BUAE_SELL_STRONG_WEAK_PROFIT}%)')}
                else:
                    base_response['reason'] = (
                        f'BUAE경계홀드 ({trend["detail"]}, '
                        f'5분봉{micro["detail"]}, 수익{profit_pct:.2f}%)')
                    return base_response
            
            # MODERATE + 5분봉 강세 = 홀드 (기존 QPL 유지)
            if trend_grade == 'MODERATE' and not micro_weak:
                # 기존 QPL을 그대로 적용 (조건 강화: 신호 3개 필요)
                if QPL_ENABLED and profit_pct > 0:
                    is_bearish_qpl = current['close'] < current['open']
                    rsi_dropping_qpl = current['rsi'] < prev['rsi']
                    stoch_k_qpl = current.get('stoch_rsi_k', 50)
                    stoch_d_qpl = current.get('stoch_rsi_d', 50)
                    stoch_k_prev_qpl = prev.get('stoch_rsi_k', 50)
                    srsi_dead_qpl = (stoch_k_qpl < stoch_d_qpl and 
                                     stoch_k_prev_qpl >= prev.get('stoch_rsi_d', 50))
                    qpl_count = sum([is_bearish_qpl, rsi_dropping_qpl, srsi_dead_qpl])
                    
                    # Tier3 유지 (수익 3%+ & BB 70%+)
                    if profit_pct >= QPL_TIER3_PROFIT and bb_position >= 70:
                        return {**base_response, 'signal': True,
                                'reason': (f'QPL_T3 (수익{profit_pct:.2f}%≥{QPL_TIER3_PROFIT}%, '
                                           f'BB{bb_position:.0f}%, MODERATE+5분강세)')}
                    
                    # MODERATE에서는 QPL 조건 강화: 약세 신호 3개 필요
                    if profit_pct >= QPL_TIER1_PROFIT and qpl_count >= 3:
                        sigs = '+'.join(filter(None, [
                            '음봉' if is_bearish_qpl else '',
                            'RSI↓' if rsi_dropping_qpl else '',
                            'SRSI✗' if srsi_dead_qpl else ''
                        ]))
                        return {**base_response, 'signal': True,
                                'reason': (f'QPL강화 (수익{profit_pct:.2f}%, '
                                           f'{sigs}, MODERATE+5분강세)')}
                
                # QPL 미발동 시 홀드
                pass  # Step 6으로 이동
            
            # MODERATE + 5분봉 약세 = 매도 (수익 1%+)
            if trend_grade == 'MODERATE' and micro_weak:
                if profit_pct >= BUAE_SELL_MODERATE_WEAK_PROFIT:
                    return {**base_response, 'signal': True,
                            'reason': (f'BUAE_TREND_EXIT 추세보통+5분약세 '
                                       f'({trend["detail"]}, 5분봉{micro["detail"]}, '
                                       f'수익{profit_pct:.2f}%≥{BUAE_SELL_MODERATE_WEAK_PROFIT}%)')}
            
            # WEAK + 5분봉 강세 = 경계 매도 (수익 1.5%+)
            if trend_grade == 'WEAK' and not micro_weak:
                if profit_pct >= BUAE_SELL_WEAK_STRONG_PROFIT:
                    return {**base_response, 'signal': True,
                            'reason': (f'BUAE_TREND_EXIT 추세약+5분강세 '
                                       f'({trend["detail"]}, 5분봉{micro["detail"]}, '
                                       f'수익{profit_pct:.2f}%≥{BUAE_SELL_WEAK_STRONG_PROFIT}%)')}
            
            # WEAK + 5분봉 약세 = 즉시 매도 (수익 0.5%+)
            if trend_grade == 'WEAK' and micro_weak:
                if profit_pct >= BUAE_SELL_WEAK_WEAK_PROFIT:
                    return {**base_response, 'signal': True,
                            'reason': (f'BUAE_TREND_EXIT 추세약+5분약세 '
                                       f'({trend["detail"]}, 5분봉{micro["detail"]}, '
                                       f'수익{profit_pct:.2f}%≥{BUAE_SELL_WEAK_WEAK_PROFIT}%)')}
        
        else:
            # BB 70% 미만: 기존 QPL 적용 (변경 없음)
            if QPL_ENABLED and profit_pct > 0:
                is_bearish_qpl = current['close'] < current['open']
                rsi_dropping_qpl = current['rsi'] < prev['rsi']
                stoch_k_qpl = current.get('stoch_rsi_k', 50)
                stoch_d_qpl = current.get('stoch_rsi_d', 50)
                stoch_k_prev_qpl = prev.get('stoch_rsi_k', 50)
                srsi_dead_qpl = (stoch_k_qpl < stoch_d_qpl and 
                                 stoch_k_prev_qpl >= prev.get('stoch_rsi_d', 50))
                qpl_count = sum([is_bearish_qpl, rsi_dropping_qpl, srsi_dead_qpl])
                
                # Tier3: 수익 3%+ → BB 70%+ 도달만으로 매도 (BB 미달이므로 해당없음)
                
                # Tier2: 수익 2%+ → 음봉+RSI하락이면 매도
                if profit_pct >= QPL_TIER2_PROFIT and is_bearish_qpl and rsi_dropping_qpl:
                    return {**base_response, 'signal': True,
                            'reason': f'QPL_T2 (수익{profit_pct:.2f}%≥{QPL_TIER2_PROFIT}%, 음봉+RSI↓)'}
                
                # Tier1: 수익 1.5%+ → 약세 신호 2개 이상
                if profit_pct >= QPL_TIER1_PROFIT and qpl_count >= QPL_TIER1_SIGNALS:
                    sigs = '+'.join(filter(None, [
                        '음봉' if is_bearish_qpl else '',
                        'RSI↓' if rsi_dropping_qpl else '',
                        'SRSI✗' if srsi_dead_qpl else ''
                    ]))
                    return {**base_response, 'signal': True,
                            'reason': f'QPL_T1 (수익{profit_pct:.2f}%≥{QPL_TIER1_PROFIT}%, {sigs})'}
        
        
        # ===== Step 6: 기존 소진점수제 + 트레일링 (안전망) =====
        
        # 모멘텀 소진 점수제
        exhaustion = calculate_sell_exhaustion_score(df, held_info)
        ex_score = exhaustion['score']
        ex_threshold = exhaustion['dynamic_threshold']
        ex_detail = format_sell_exhaustion_detail(exhaustion)
        
        if ex_score >= V11_SELL_EXHAUSTION_HIGH:
            dyn_min = V11_SELL_MIN_PROFIT_EXHAUSTED
        elif ex_score >= V11_SELL_EXHAUSTION_MID:
            dyn_min = (V11_SELL_MIN_PROFIT_DEFAULT + V11_SELL_MIN_PROFIT_EXHAUSTED) / 2
        else:
            dyn_min = V11_SELL_MIN_PROFIT_DEFAULT
        
        if exhaustion['should_sell'] and profit_pct >= dyn_min:
            return {**base_response, 'signal': True,
                    'reason': f'모멘텀소진 ({ex_detail}, 수익{profit_pct:.2f}%, 최소{dyn_min:.1f}%)'}
        
        # 동적 트레일링 스탑
        trailing = calculate_dynamic_trailing(bb_position, profit_pct, held_info)
        if trailing['should_sell']:
            return {**base_response, 'signal': True,
                    'reason': (f'트레일링스탑[{trailing["zone"]}] '
                              f'(고점{trailing["peak_profit"]:.1f}%→현재{profit_pct:.1f}%, '
                              f'-{trailing["drawdown_from_peak"]:.1f}% >= {trailing["distance"]:.1f}%)')}
        
        # ===== 홀드 =====
        t_info = f'트레일링[{trailing["zone"]}:{trailing["distance"]:.1f}%]'
        ppf_info = f'보호선Tier{ppf_result.get("active_tier", "-")}'
        
        if profit_pct < dyn_min:
            base_response['reason'] = (
                f'수익미달홀드 ({profit_pct:.2f}% < 동적최소{dyn_min:.1f}%, '
                f'소진{ex_score}/{ex_threshold}, {t_info}, {ppf_info})')
        else:
            base_response['reason'] = (
                f'홀드 (수익{profit_pct:.2f}%, '
                f'소진{ex_score}/{ex_threshold}, {t_info}, {ppf_info})')
        return base_response
        
    except Exception as e:
        if DEBUG_MODE:
            print(f"{Colors.RED}[v20.0 BUAE Sell Error] {e}{Colors.ENDC}")
            traceback.print_exc()
        return {'signal': False, 'reason': f'오류: {e}',
                'exit_price': 0, 'profit_pct': 0,
                'bb_position': 50, 'bb_width_pct': 2.0}


def evolution_76_sell_signal(df, buy_price, buy_time=None, held_info=None):
    """레거시 wrapper - v16.0으로 리다이렉트"""
    return evolution_80_sell_signal(df, buy_price, buy_time, held_info)

def evolution_70_sell_signal(df, buy_price):
    """레거시 wrapper - v16.0으로 리다이렉트"""
    return evolution_80_sell_signal(df, buy_price)


# ================================================================================
# SECTION 15: Initialization Functions (NEW)
# ================================================================================

def sync_held_coins_with_exchange():
    """
    거래소 실제 보유량과 held_coins 동기화
    
    [v366.1 개선사항] - 보유코인 조회 오류 수정
    - 기존: FIXED_STABLE_COINS만 동기화 → 동적 매수/수동 매수 코인 누락!
    - 수정: 모든 KRW 코인 동기화 (실제 거래소 보유량 100% 반영)
    - peak_price를 max(매수가, 현재가)로 초기화 (트레일링 스탑 정확성)
    - 관리 대상 여부를 'managed' 플래그로 구분 (동기화는 하되 매도 관리 분리)
    
    봇 시작 시 1회 실행
    """
    global held_coins
    
    print(f"\n{Colors.CYAN}{'='*10}")
    print(f"[Init] 기존 보유 코인 동기화 시작...")
    print(f"{'='*10}{Colors.ENDC}")
    
    try:
        balances = upbit.get_balances()
        synced_count = 0
        unmanaged_count = 0
        total_value = 0.0
        unmanaged_coins = []
        
        # ========================================
        # [v366.1] 동적 스크리닝 코인도 관리 대상에 포함
        # ========================================
        dynamic_coins_list = []
        try:
            if DYNAMIC_COIN_ENABLED:
                dynamic_coins_list = [c.get('ticker', '') for c in dynamic_coins_cache if c.get('ticker')] if dynamic_coins_cache else []
        except:
            dynamic_coins_list = []
        
        # 관리 대상 = 고정 코인 + 동적 코인
        managed_tickers = set(FIXED_STABLE_COINS) | set(dynamic_coins_list)
        
        for bal in balances:
            currency = bal.get('currency', '')
            if currency == 'KRW':
                continue
            
            balance = float(bal.get('balance', 0))
            if balance <= 0:
                continue
            
            ticker = f"KRW-{currency}"
            
            avg_buy_price = float(bal.get('avg_buy_price', 0))
            
            if avg_buy_price <= 0:
                print(f"{Colors.YELLOW}  ⚠️  {ticker}: 평균 매수가 없음 (스킵){Colors.ENDC}")
                continue
            
            # 현재가 조회
            try:
                current_price = get_current_price(ticker)
                if current_price:
                    coin_value = balance * current_price
                    profit_pct = ((current_price - avg_buy_price) / avg_buy_price) * 100
                    total_value += coin_value
                else:
                    current_price = avg_buy_price
                    coin_value = balance * avg_buy_price
                    profit_pct = 0.0
            except:
                current_price = avg_buy_price
                coin_value = balance * avg_buy_price
                profit_pct = 0.0
            
            # ========================================
            # [v366.1 핵심] 모든 코인을 held_coins에 동기화
            # ========================================
            is_managed = ticker in managed_tickers
            
            # peak_price: 현재가와 매수가 중 높은 값으로 초기화
            initial_peak = max(avg_buy_price, current_price) if current_price else avg_buy_price
            
            with held_coins_lock:
                held_coins[ticker] = {
                    'buy_price': avg_buy_price,
                    'buy_time': datetime.now(),
                    'buy_amount': balance * avg_buy_price,
                    'peak_price': initial_peak,          # ✅ max(매수가, 현재가)
                    'peak_time': datetime.now(),
                    'buy_reason': 'EXISTING_POSITION (봇 시작 시 동기화)',
                    'managed': is_managed                # ✅ 관리 대상 여부 플래그
                }
            
            synced_count += 1
            
            if is_managed:
                tag = "관리대상"
                color = Colors.GREEN
            else:
                tag = "비관리 (매도만 관리)"
                color = Colors.YELLOW
                unmanaged_count += 1
                unmanaged_coins.append(f"{ticker} ({balance:.4f}개, {coin_value:,.0f}원)")
            
            print(f"{color}  ✔ {ticker}: {balance:.4f}개 @ {avg_buy_price:,.0f}원 [{tag}]")
            print(f"    평가액: {coin_value:,.0f}원 ({profit_pct:+.2f}%) | peak: {initial_peak:,.0f}원{Colors.ENDC}")
        
        krw_balance = upbit.get_balance("KRW")
        
        managed_count_final = synced_count - unmanaged_count
        print(f"\n{Colors.GREEN}{'='*10}")
        print(f"[Init] 동기화 완료")
        print(f"  - 동기화 총 코인: {synced_count}개 (관리: {managed_count_final}, 비관리: {unmanaged_count})")
        if unmanaged_coins:
            print(f"  - 비관리 목록:")
            for coin in unmanaged_coins:
                print(f"    • {coin}")
        print(f"  - 코인 총 평가액: {total_value:,.0f}원 (전체)")
        print(f"  - 보유 현금: {krw_balance:,.0f}원")
        print(f"  - 총 자산: {total_value + krw_balance:,.0f}원")
        print(f"{'='*10}{Colors.ENDC}\n")
        
        # Discord 알림
        if synced_count > 0:
            sync_message = f"""
**🔄 기존 보유 코인 동기화 완료**

**✅ 관리 대상 코인:** `{managed_count_final}개` (매수/매도 자동관리)
**📌 비관리 코인:** `{unmanaged_count}개` (매도만 자동관리)
"""
            if unmanaged_coins:
                sync_message += f"\n**📋 비관리 코인:**\n"
                for coin in unmanaged_coins:
                    sync_message += f"`{coin}`\n"
            
            sync_message += f"""
**💰 자산 현황:**
- 코인 평가액: `{total_value:,.0f}원`
- 보유 현금: `{krw_balance:,.0f}원`
- 총 자산: `{total_value + krw_balance:,.0f}원`

⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
"""
            send_discord_message(sync_message)
        
        if synced_count > 0:
            warning_message = f"""
⚠️ **중요 안내**

동기화된 {synced_count}개 코인은 봇 시작 **이전**에 매수된 코인입니다.

**주의사항:**
1. 보유 시간이 부정확할 수 있습니다.
2. 시간 기반 매도 조건 (30분 제한 등)이 정확하지 않을 수 있습니다.
3. 가능하면 수동으로 매도 후 봇이 새로 매수하도록 권장합니다.

**또는:**
현재 상태를 유지하고 봇이 자동으로 관리하도록 할 수 있습니다.
(매도 신호 발생 시 자동 매도됩니다)
"""
            send_discord_message(warning_message)
        
        return True
        
    except Exception as e:
        print(f"{Colors.RED}[Init Error] 동기화 실패: {e}{Colors.ENDC}")
        traceback.print_exc()
        send_error_notification("Sync Failed", str(e))
        return False

def get_managed_holdings_count():
    """
    [v366.1] 관리 대상 보유 코인 수만 카운트
    
    held_coins에 모든 코인이 포함되므로 (비관리 포함),
    MAX_HOLDINGS 체크 시에는 관리 대상만 카운트해야 함
    """
    with held_coins_lock:
        return sum(1 for info in held_coins.values() if info.get('managed', True))
    
# ================================================================================
# SECTION 16: Trade Execution Functions
# ================================================================================

def execute_buy(ticker, signal):
    """
    [v10.2] 2단계 매수 실행 (thread safe)
    """
    global daily_trade_count, total_trades, daily_buy_count
    
    try:
        with trade_lock:
            
            reset_daily_counter()
            if daily_trade_count >= MAX_DAILY_TRADES:
                print(f"{Colors.YELLOW}[Buy Limit] 일일 거래 한도 도달{Colors.ENDC}")
                return False
            
            can_enter, cooldown_msg = check_reentry_cooldown(ticker)
            if not can_enter:
                print(f"{Colors.YELLOW}[Buy Limit] {cooldown_msg}{Colors.ENDC}")
                return False
            
            # ========================================
            # ✅ [v366.1] 최소 가격 필터 - 저가 코인 매수 차단
            # 500원 미만 코인은 변동률이 과대하여 손절 확률 급증
            # ========================================
            entry_price = signal.get('entry_price', 0)
            if entry_price < MIN_BUY_PRICE:
                coin_name = ticker.replace('KRW-', '')
                print(f"{Colors.YELLOW}[Buy Block] {coin_name}: 현재가 {entry_price:,.0f}원 < 최소 {MIN_BUY_PRICE:,}원 (저가 코인 매수 차단){Colors.ENDC}")
                return False
            
            with held_coins_lock:
                if ticker in held_coins:
                    print(f"{Colors.YELLOW}[Buy Limit] 이미 보유 중{Colors.ENDC}")
                    return False
                
                # ✅ [v366.1] 관리 대상 코인만 카운트 (비관리 코인 제외)
                managed_count = sum(1 for info in held_coins.values() if info.get('managed', True))
                if managed_count >= MAX_HOLDINGS:
                    print(f"{Colors.YELLOW}[Buy Limit] 최대 보유 종목 도달 ({managed_count}/{MAX_HOLDINGS}){Colors.ENDC}")
                    return False
                
                current_holding_count = managed_count   # ✅ 관리 대상만 카운트
            
            # ========================================
            # Step 1: 가용 현금(KRW) 우선 체크
            # ========================================
            try:
                krw_balance = upbit.get_balance("KRW")
                if krw_balance is None:
                    krw_balance = 0
            except Exception as e:
                print(f"{Colors.RED}[Buy Failed] KRW 잔고 조회 실패: {e}{Colors.ENDC}")
                return False
            
            if krw_balance < 5000:
                print(f"{Colors.YELLOW}[Buy Skip] 가용 현금 부족{Colors.ENDC}")
                print(f"  └ 가용현금: {krw_balance:,.0f}원 < 최소주문금액 5,000원")
                return False
            
            # ========================================
            # Step 2: 총 자산 계산 (로그용)
            # ========================================
            try:
                total_assets = get_total_balance()
                if total_assets is None or total_assets <= 0:
                    total_assets = krw_balance
            except Exception as e:
                print(f"{Colors.RED}[Buy Failed] 총 자산 조회 실패: {e}{Colors.ENDC}")
                return False
            
            # ========================================
            # Step 3: [v10.2 핵심] 포지션 사이징 - 보유 수 기반
            # ========================================
            if current_holding_count == 0:
                # 1차 매수: 가용현금의 FIRST_BUY_RATIO(50%) × 수수료버퍼
                buy_amount = krw_balance * FIRST_BUY_RATIO * BUY_FEE_BUFFER
                buy_order = '1차'
                buy_order_num = 1
            else:
                # 2차 매수: 잔여현금 전량 × 수수료버퍼
                buy_amount = krw_balance * BUY_FEE_BUFFER
                buy_order = '2차'
                buy_order_num = 2
            
            # ========================================
            # Step 4: 최소 주문 금액 체크 (5,000원)
            # ========================================
            if buy_amount < 5000:
                print(f"{Colors.YELLOW}[Buy Limit] 매수 금액 부족{Colors.ENDC}")
                print(f"  └ 총자산: {total_assets:,.0f}원 | 가용현금: {krw_balance:,.0f}원")
                print(f"  └ {buy_order}매수 계산: {buy_amount:,.0f}원 < 5,000원")
                return False
            
            # ========================================
            # 매수 정보 로그
            # ========================================
            coin_value = total_assets - krw_balance
            print(f"{Colors.CYAN}[Buy Info] 총자산: {total_assets:,.0f}원 "
                  f"(코인: {coin_value:,.0f}원 + 현금: {krw_balance:,.0f}원){Colors.ENDC}")
            
            if current_holding_count == 0:
                print(f"{Colors.CYAN}[Buy Info] {buy_order}매수 | "
                      f"현금{krw_balance:,.0f} × {FIRST_BUY_RATIO:.0%} × {BUY_FEE_BUFFER} = "
                      f"{buy_amount:,.0f}원{Colors.ENDC}")
            else:
                print(f"{Colors.CYAN}[Buy Info] {buy_order}매수 | "
                      f"잔여현금{krw_balance:,.0f} × {BUY_FEE_BUFFER} = "
                      f"{buy_amount:,.0f}원{Colors.ENDC}")
            
            # ========================================
            # TEST MODE: 시뮬레이션
            # ========================================
            if TEST_MODE:
                print(f"{Colors.GREEN}[TEST] {buy_order}매수 시뮬레이션: {ticker} {buy_amount:,.0f}원{Colors.ENDC}")
                
                with held_coins_lock:
                    held_coins[ticker] = {
                        'buy_price': signal['entry_price'],
                        'buy_time': datetime.now(),
                        'buy_amount': buy_amount,
                        'peak_price': signal['entry_price'],
                        'peak_time': datetime.now(),
                        'peak_bb_position': signal.get('bb_position', 50),
                        'buy_reason': signal['reason'],
                        'buy_mode': signal.get('mode', 'BOUNCE_V10'),
                        'entry_bb_width': signal.get('bb_width_pct', 2.0),
                        'bb_width_zone': signal.get('bb_width_zone', 'UNKNOWN'),
                        'target_profit': signal.get('target_profit', 2.0),
                        'ticker': ticker,
                        'buy_order': buy_order_num,    # [v10.2] 몇 차 매수인지
                        'managed': True                # ✅ [v366.1] 신규 매수는 항상 관리 대상
                    }
                
                daily_trade_count += 1
                daily_buy_count += 1
                total_trades += 1
                
                send_buy_notification(ticker, signal, buy_amount, total_assets)
                return True
            
            # ========================================
            # LIVE MODE: 실제 매수 실행
            # ========================================
            try:
                final_krw = upbit.get_balance("KRW")
                if final_krw is None or final_krw < buy_amount:
                    print(f"{Colors.RED}[Buy Failed] 매수 직전 잔고 부족{Colors.ENDC}")
                    if final_krw and final_krw >= 5000:
                        buy_amount = final_krw * BUY_FEE_BUFFER
                        print(f"{Colors.CYAN}[Buy Info] 잔고에 맞춰 재조정: {buy_amount:,.0f}원{Colors.ENDC}")
                    else:
                        return False
                
                result = upbit.buy_market_order(ticker, buy_amount)
                
                if result is None:
                    print(f"{Colors.RED}[Buy Failed] 주문 실패 (API 응답 없음){Colors.ENDC}")
                    return False
                
                if isinstance(result, dict) and 'error' in result:
                    error_info = result.get('error', {})
                    print(f"{Colors.RED}[Buy Failed] API 오류: {error_info.get('name')} - {error_info.get('message')}{Colors.ENDC}")
                    return False
                
                order_uuid = result.get('uuid', '')
                
                # ========================================
                # [개선 3] UUID로 실제 체결가 조회
                # 기존: time.sleep(1) 후 get_balances로 추정
                # 개선: 주문 UUID로 정확한 체결가/수수료 확인
                # ========================================
                actual_buy_price = signal['entry_price']  # 기본값 (fallback)
                
                if order_uuid:
                    time.sleep(0.5)  # 짧은 대기 후 체결 확인
                    order_detail = upbit.wait_order_filled(order_uuid, timeout_sec=5)
                    
                    if order_detail and order_detail['avg_price'] > 0:
                        actual_buy_price = order_detail['avg_price']
                        paid_fee = order_detail['paid_fee']
                        print(f"{Colors.CYAN}[Buy Detail] 체결가: {actual_buy_price:,.0f}원 | "
                              f"수수료: {paid_fee:,.0f}원{Colors.ENDC}")
                    else:
                        # UUID 조회 실패 시 기존 방식 (get_balances) 으로 fallback
                        time.sleep(0.5)
                        balances = upbit.get_balances()
                        if balances:
                            for bal in balances:
                                if bal['currency'] == ticker.split('-')[1]:
                                    actual_buy_price = float(bal['avg_buy_price'])
                                    break
                else:
                    # UUID 없는 경우 기존 방식 fallback
                    time.sleep(1)
                    balances = upbit.get_balances()
                    if balances:
                        for bal in balances:
                            if bal['currency'] == ticker.split('-')[1]:
                                actual_buy_price = float(bal['avg_buy_price'])
                                break
                
                with held_coins_lock:
                    held_coins[ticker] = {
                        'buy_price':        actual_buy_price,
                        'buy_time':         datetime.now(),
                        'buy_amount':       buy_amount,
                        'peak_price':       actual_buy_price,
                        'peak_time':        datetime.now(),
                        'peak_bb_position': signal.get('bb_position', 50),
                        'buy_reason':       signal['reason'],
                        'buy_mode':         signal.get('mode', 'BOUNCE_V10'),
                        'entry_bb_width':   signal.get('bb_width_pct', 2.0),
                        'bb_width_zone':    signal.get('bb_width_zone', 'UNKNOWN'),
                        'target_profit':    signal.get('target_profit', 2.0),
                        'ticker':           ticker,
                        'buy_order':        buy_order_num,
                        'order_uuid':       order_uuid,   # ← UUID 저장 (나중에 조회 가능)
                        'managed':          True
                    }
                
                daily_trade_count += 1
                daily_buy_count += 1
                total_trades += 1
                
                print(f"{Colors.GREEN}[Buy Success] {buy_order}매수 {ticker} @ {actual_buy_price:,.0f}원 "
                      f"(투자액: {buy_amount:,.0f}원){Colors.ENDC}")
                
                send_buy_notification(ticker, signal, buy_amount, total_assets)
                return True
                
            except Exception as e:
                error_str = str(e)
                print(f"{Colors.RED}[Buy Failed] 주문 실행 오류: {error_str}{Colors.ENDC}")
                
                if 'InsufficientFunds' in error_str or 'insufficient' in error_str.lower():
                    print(f"{Colors.YELLOW}  └ 원인: 주문 금액이 가용 잔고를 초과{Colors.ENDC}")
                    print(f"{Colors.YELLOW}  └ 시도 금액: {buy_amount:,.0f}원{Colors.ENDC}")
                    try:
                        current_krw = upbit.get_balance("KRW")
                        print(f"{Colors.YELLOW}  └ 현재 잔고: {current_krw:,.0f}원{Colors.ENDC}")
                    except:
                        pass
                
                send_error_notification("Buy Failed", error_str)
                return False

    except Exception as e:
        print(f"{Colors.RED}[Buy Error] 예외 발생: {e}{Colors.ENDC}")
        traceback.print_exc()
        return False

    
def execute_sell(ticker, signal):
    """
    Execute sell order (thread safe)
    
    [v343.1 개선사항]
    - 잔고 부족 오류 처리 (수동 매도 감지)
    - held_coins 자동 정리 기능 추가
    - Discord 경고 알림 추가
    """
    # ============================================================
    # 🆕 MODIFIED: 일일 통계 변수 추가 (1줄 추가)
    # ============================================================
    global daily_trade_count, total_trades, winning_trades, losing_trades, total_profit
    global consecutive_losses, last_loss_time
    global daily_sell_count, daily_winning_trades, daily_losing_trades
    # ============================================================
    
    try:
        with trade_lock:
            
            with held_coins_lock:
                if ticker not in held_coins:
                    print(f"{Colors.YELLOW}[Sell Limit] 보유하지 않음{Colors.ENDC}")
                    return False
                
                hold_info = held_coins[ticker].copy()
            
            buy_price = hold_info['buy_price']
            buy_time = hold_info['buy_time']
            sell_price = signal['exit_price']
            
            profit_pct = ((sell_price - buy_price) / buy_price) * 100
            profit_amount = hold_info['buy_amount'] * (profit_pct / 100)
            hold_duration = format_duration(datetime.now() - buy_time)
            
            if TEST_MODE:
                print(f"{Colors.GREEN}[TEST] 매도 시뮬레이션: {ticker} {profit_pct:+.2f}%{Colors.ENDC}")
                
                with held_coins_lock:
                    if ticker in held_coins:
                        del held_coins[ticker]
                
                recent_sells[ticker] = {
                    'time': datetime.now(),
                    'reason': signal['reason']
                }
                
                # ============================================================
                # 🆕 MODIFIED: 일일 통계 업데이트 (2줄 추가)
                # ============================================================
                with statistics_lock:
                    total_profit += profit_pct
                    if profit_pct > 0:
                        winning_trades += 1
                        daily_winning_trades += 1  # 추가
                        consecutive_losses = 0
                    else:
                        losing_trades += 1
                        daily_losing_trades += 1  # 추가
                        consecutive_losses += 1
                        last_loss_time = datetime.now()
                
                daily_trade_count += 1
                daily_sell_count += 1  # 추가
                # ============================================================
                
                send_sell_notification(ticker, hold_info, signal, profit_amount, hold_duration)
                return True
            
            # ========================================
            # 실제 매도 실행
            # ========================================
            try:
                balances = upbit.get_balances()
                coin_balance = None
                
                for bal in balances:
                    if bal['currency'] == ticker.split('-')[1]:
                        coin_balance = bal
                        break
                
                # ========================================
                # ✅ [v343.1 핵심 추가] 잔고 부족 감지
                # ========================================
                if not coin_balance:
                    print(f"{Colors.RED}[Sell Failed] {ticker} 잔고 조회 실패{Colors.ENDC}")
                    
                    # 수동 매도 추정 → held_coins에서 제거
                    with held_coins_lock:
                        if ticker in held_coins:
                            del held_coins[ticker]
                    
                    # Discord 경고 알림
                    warning_message = f"""
⚠️ **매도 실패 - 수동 매도 추정**

**코인:** `{ticker.replace('KRW-', '')}`
**원인:** 잔고 없음 (Upbit에서 수동 매도한 것으로 추정)

**자동 조치:**
- `held_coins`에서 자동 제거
- 봇 관리 대상에서 제외

**안내:**
향후 이 코인을 다시 거래하려면 봇이 자동으로 매수합니다.
수동 개입은 불필요합니다.

⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
"""
                    send_discord_message(warning_message)
                    
                    print(f"{Colors.YELLOW}[Sync] {ticker} removed from held_coins (insufficient balance){Colors.ENDC}")
                    return False
                # ========================================
                
                coin_amount = float(coin_balance['balance'])
                
                # 잔고가 0이거나 너무 적은 경우도 처리
                if coin_amount <= 0:
                    print(f"{Colors.RED}[Sell Failed] {ticker} 잔고 부족: {coin_amount}{Colors.ENDC}")
                    
                    # 수동 매도 추정 → held_coins에서 제거
                    with held_coins_lock:
                        if ticker in held_coins:
                            del held_coins[ticker]
                    
                    # Discord 경고 알림
                    warning_message = f"""
⚠️ **매도 실패 - 잔고 부족**

**코인:** `{ticker.replace('KRW-', '')}`
**잔고:** `{coin_amount}`
**원인:** 수동 매도 추정

**자동 조치:**
- `held_coins`에서 자동 제거

⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
"""
                    send_discord_message(warning_message)
                    
                    print(f"{Colors.YELLOW}[Sync] {ticker} removed from held_coins (zero balance){Colors.ENDC}")
                    return False
                
                # 실제 매도 주문 실행
                result = upbit.sell_market_order(ticker, coin_amount)
                
                if result is None:
                    print(f"{Colors.RED}[Sell Failed] {ticker} 주문 실패{Colors.ENDC}")
                    return False
                
                sell_uuid = result.get('uuid', '')
                
                # [개선 3] 실제 체결가 조회
                actual_sell_price = sell_price  # fallback
                
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
                
                # held_coins에서 제거
                with held_coins_lock:
                    if ticker in held_coins:
                        del held_coins[ticker]
                
                # 재진입 쿨다운 기록
                recent_sells[ticker] = {
                    'time': datetime.now(),
                    'reason': signal['reason']
                }
                
                # ============================================================
                # 🆕 MODIFIED: 일일 통계 업데이트 (2줄 추가)
                # ============================================================
                with statistics_lock:
                    total_profit += actual_profit_pct
                    if actual_profit_pct > 0:
                        winning_trades += 1
                        daily_winning_trades += 1  # 추가
                        consecutive_losses = 0
                    else:
                        losing_trades += 1
                        daily_losing_trades += 1  # 추가
                        consecutive_losses += 1
                        last_loss_time = datetime.now()
                
                daily_trade_count += 1
                daily_sell_count += 1  # 추가
                # ============================================================
                
                print(f"{Colors.GREEN}[Sell Success] {ticker} {actual_profit_pct:+.2f}%{Colors.ENDC}")
                
                # Discord 알림에 실제 체결 정보 반영
                signal['profit_pct'] = actual_profit_pct
                signal['exit_price'] = actual_sell_price
                send_sell_notification(ticker, hold_info, signal, actual_profit_amount, hold_duration)
                return True
                
            except Exception as e:
                error_str = str(e)
                print(f"{Colors.RED}[Sell Failed] {ticker}: {error_str}{Colors.ENDC}")
                
                # ========================================
                # ✅ [v343.1 핵심 추가] 오류 타입별 처리
                # ========================================
                # Upbit API 잔고 부족 오류 감지
                if 'insufficient' in error_str.lower() or 'balance' in error_str.lower():
                    print(f"{Colors.YELLOW}[Sync] {ticker} 잔고 부족 오류 감지 - held_coins 제거{Colors.ENDC}")
                    
                    with held_coins_lock:
                        if ticker in held_coins:
                            del held_coins[ticker]
                    
                    # Discord 경고
                    warning_message = f"""
⚠️ **매도 실패 - 잔고 부족 오류**

**코인:** `{ticker.replace('KRW-', '')}`
**오류:** `{error_str}`
**원인:** 수동 매도 추정

**자동 조치:**
- `held_coins`에서 자동 제거

⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
"""
                    send_discord_message(warning_message)
                    return False
                # ========================================
                
                send_error_notification("Sell Failed", error_str)
                return False
    
    except Exception as e:
        print(f"{Colors.RED}[Sell Error] {e}{Colors.ENDC}")
        traceback.print_exc()
        return False

# ================================================================================
# SECTION 17: Risk Management Functions
# ================================================================================

def check_market_condition():
    """Check market condition"""
    try:
        total_change = 0.0
        valid_count = 0
        
        for ticker in FIXED_STABLE_COINS:
            df = get_candles(ticker, interval='15', count=2)
            
            if df is not None and len(df) >= 2:
                change_pct = ((df.iloc[-1]['close'] - df.iloc[-2]['close']) / df.iloc[-2]['close']) * 100
                total_change += change_pct
                valid_count += 1
        
        if valid_count == 0:
            return True, 0.0
        
        avg_change = total_change / valid_count
        
        if avg_change <= MARKET_BREAKER_THRESHOLD:
            return False, avg_change
        
        return True, avg_change
        
    except Exception as e:
        if DEBUG_MODE:
            print(f"{Colors.RED}[Market Check Error] {e}{Colors.ENDC}")
        return True, 0.0


def check_daily_trade_limit():
    """Check daily trade limit"""
    global daily_trade_count, last_reset_date
    
    today = datetime.now().date()
    
    if today != last_reset_date:
        daily_trade_count = 0
        last_reset_date = today
    
    return daily_trade_count < MAX_DAILY_TRADES


def check_consecutive_losses():
    """Check consecutive losses"""
    global consecutive_losses, last_loss_time
    
    if consecutive_losses >= CONSECUTIVE_LOSS_LIMIT:
        if last_loss_time:
            elapsed = datetime.now() - last_loss_time
            elapsed_minutes = elapsed.total_seconds() / 60
            
            if elapsed_minutes < COOLDOWN_AFTER_LOSS:
                return False
            else:
                consecutive_losses = 0
                last_loss_time = None
    
    return True


# ================================================================================
# SECTION 18: Thread Worker Functions
# ================================================================================

def buy_thread_worker():
    """
    [Thread 1] v19.0 BOUNCE+NIGHT 매수 스레드

    동작 흐름:
      ① 보유수 체크 (MAX_HOLDINGS 도달 시 즉시 스킵)
      ② 매수 차단 시간대 체크 (08:00~09:15)
      ③ 연속 손실 / 시장 상황 / 일일 거래 한도 사전 필터
      ④ 활성 코인 목록 순회 → BOUNCE 매수 시그널 검사
      ⑤ 시그널 발생 시 execute_buy() 실행
    """
    print(f"{Colors.CYAN}[Thread 1] v19.0 BOUNCE+NIGHT 매수 스레드 시작 ({BUY_THREAD_INTERVAL}초 주기){Colors.ENDC}")
    if DYNAMIC_COIN_ENABLED:
        print(f"{Colors.CYAN}  └ 동적 코인: 활성 (N={DYNAMIC_COIN_COUNT}, 주기={DYNAMIC_SCREEN_INTERVAL}초){Colors.ENDC}")
    if MORNING_CLEANUP_ENABLED:
        print(f"{Colors.CYAN}  └ 매수차단: {MORNING_BUY_BLOCK_START_HOUR:02d}:{MORNING_BUY_BLOCK_START_MINUTE:02d}"
              f"~{MORNING_BUY_BLOCK_END_HOUR:02d}:{MORNING_BUY_BLOCK_END_MINUTE:02d}{Colors.ENDC}")
    # [v19.0] 등락률 범위 필터 정보
    print(f"{Colors.CYAN}  ├ 등락범위: BULL{V19_DAY_BULL_CHANGE_MIN:+.1f}~{V19_DAY_BULL_CHANGE_MAX:+.1f}%"
          f" NEUT{V19_DAY_NEUT_CHANGE_MIN:+.1f}~{V19_DAY_NEUT_CHANGE_MAX:+.1f}%"
          f" BEAR{V19_DAY_BEAR_CHANGE_MIN:+.1f}~{V19_DAY_BEAR_CHANGE_MAX:+.1f}%{Colors.ENDC}")
    if TIMEZONE_MODE_ENABLED:
        print(f"{Colors.CYAN}  └ 🌙NIGHT: {NIGHT_MODE_START_HOUR:02d}:{NIGHT_MODE_START_MINUTE:02d}"
              f"~{NIGHT_MODE_END_HOUR:02d}:{NIGHT_MODE_END_MINUTE:02d}"
              f" | BB≤{NIGHT_BB_MAX}% 폭≥{NIGHT_BB_WIDTH_MIN}%"
              f" RSI≥{NIGHT_RSI_MIN} 신호≥{NIGHT_REVERSAL_MIN_SIGNALS}{Colors.ENDC}")

    iteration = 0

    while not stop_event.is_set():
        try:
            iteration += 1

            # ── ① 보유수 체크 (API 호출 0건) ──────────────────────────────
            with held_coins_lock:
                current_holdings = len(held_coins)

            if current_holdings >= MAX_HOLDINGS:
                if DEBUG_MODE and iteration % 30 == 0:
                    print(f"{Colors.YELLOW}[BUY] 최대 보유 종목 도달"
                          f" ({current_holdings}/{MAX_HOLDINGS}) - 매수 스킵{Colors.ENDC}")
                time.sleep(BUY_SLEEP_WHEN_FULL)
                continue

            # ── ② 매수 차단 시간대 (08:00~09:15 업비트 정산 구간) ─────────
            if MORNING_CLEANUP_ENABLED:
                now = datetime.now()
                block_start = now.replace(
                    hour=MORNING_BUY_BLOCK_START_HOUR,
                    minute=MORNING_BUY_BLOCK_START_MINUTE,
                    second=0, microsecond=0
                )
                block_end = now.replace(
                    hour=MORNING_BUY_BLOCK_END_HOUR,
                    minute=MORNING_BUY_BLOCK_END_MINUTE,
                    second=0, microsecond=0
                )
                if block_start <= now <= block_end:
                    if DEBUG_MODE and iteration % 30 == 0:
                        print(f"{Colors.YELLOW}[BUY] 매수 차단 시간대"
                              f" ({now.strftime('%H:%M')}){Colors.ENDC}")
                    time.sleep(BUY_THREAD_INTERVAL)
                    continue

            # ── ③ 사전 필터 ───────────────────────────────────────────────
            if not check_consecutive_losses():
                if DEBUG_MODE and iteration % 10 == 0:
                    print(f"{Colors.YELLOW}[BUY] 연속 손실 쿨다운 중...{Colors.ENDC}")
                time.sleep(BUY_THREAD_INTERVAL)
                continue

            market_ok, market_change = check_market_condition()
            if not market_ok:
                if DEBUG_MODE and iteration % 10 == 0:
                    print(f"{Colors.YELLOW}[BUY] 시장 불안정"
                          f" ({market_change:.2f}%){Colors.ENDC}")
                time.sleep(BUY_THREAD_INTERVAL)
                continue

            if not check_daily_trade_limit():
                if DEBUG_MODE and iteration % 30 == 0:
                    print(f"{Colors.YELLOW}[BUY] 일일 거래 한도 도달{Colors.ENDC}")
                time.sleep(BUY_THREAD_INTERVAL)
                continue

            reset_daily_counter()

            # ── ④ 현재 시간대 모드 확인 (로그용) ─────────────────────────
            current_time_mode = get_time_mode()

            # ── ⑤ 코인별 매수 검토 ────────────────────────────────────────
            active_coins = get_active_coin_list()

            for ticker in active_coins:
                if stop_event.is_set():
                    print(f"{Colors.CYAN}[Thread 1] 종료 신호 수신{Colors.ENDC}")
                    return

                # 이미 보유 중인 코인 스킵
                with held_coins_lock:
                    if ticker in held_coins:
                        continue

                # 재진입 쿨다운 체크
                can_enter, cooldown_reason = check_reentry_cooldown(ticker)
                if not can_enter:
                    continue

                # 15분봉 데이터 조회
                df_15m = get_extended_candles_15m(ticker, count=V80_CANDLES_15M_COUNT)
                if df_15m is None or len(df_15m) < 50:
                    if DEBUG_MODE:
                        print(f"{Colors.RED}[BUY] {ticker} 15분봉 데이터 부족{Colors.ENDC}")
                    continue
                
                # [v19.0] 5분봉 데이터 조회 (반등 트리거용)
                df_5m = get_extended_candles_5m(ticker, count=V80_CANDLES_5M_COUNT)
                if df_5m is not None and len(df_5m) >= 20:
                    df_5m = add_indicators(df_5m)

                # BOUNCE 매수 시그널 검사
                buy_signal = evolution_80_buy_signal(df_15m, None, ticker)

                if buy_signal['signal']:
                    coin_name = ticker.replace('KRW-', '')
                    dyn_tag  = " [동적]" if ticker not in FIXED_STABLE_COINS else ""
                    time_tag = " 🌙NIGHT" if buy_signal.get('time_mode') == 'NIGHT' else " ☀️DAY"

                    print(f"\n{Colors.CYAN}{'='*50}")
                    print(f"[BUY SIGNAL] {coin_name} 반등 매수!{time_tag}{dyn_tag}")
                    print(f"{'='*50}{Colors.ENDC}")
                    print(f"  📊 반등 신호: {buy_signal.get('reversal_score', 0)}개")
                    print(f"  🎯 모드: {buy_signal.get('mode', 'BOUNCE_V19')}")
                    print(f"  📈 BB 위치: {buy_signal['bb_position']:.1f}%")
                    print(f"  💰 진입가: {buy_signal['entry_price']:,.0f}원")
                    print(f"  🔒 신뢰도: {buy_signal['confidence']}%")
                    print(f"  📝 사유: {buy_signal['reason']}")
                    print(f"{Colors.CYAN}{'='*50}{Colors.ENDC}\n")

                    success = execute_buy(ticker, buy_signal)
                    if success:
                        print(f"{Colors.GREEN}[BUY] {coin_name} 매수 완료!{time_tag}{dyn_tag}{Colors.ENDC}")
                    else:
                        print(f"{Colors.RED}[BUY] {coin_name} 매수 실패{Colors.ENDC}")

                    time.sleep(2)

                    # 매수 후 보유수 재확인
                    with held_coins_lock:
                        managed_cnt = sum(
                            1 for v in held_coins.values() if v.get('managed', True)
                        )
                        if managed_cnt >= MAX_HOLDINGS:
                            print(f"{Colors.YELLOW}[BUY] 최대 보유 종목 도달, 매수 중단{Colors.ENDC}")
                            break

                time.sleep(0.5)

            time.sleep(BUY_THREAD_INTERVAL)

        except Exception as e:
            error_trace = traceback.format_exc()
            print(f"{Colors.RED}[Buy Thread Error] {e}{Colors.ENDC}")
            if DEBUG_MODE:
                print(error_trace)

            # 네트워크 오류는 30초 대기, 그 외는 일반 대기
            if "RemoteDisconnected" in str(e) or "Connection" in str(e):
                time.sleep(30)
            else:
                time.sleep(BUY_THREAD_INTERVAL)

    print(f"{Colors.CYAN}[Thread 1] 매수 스레드 종료{Colors.ENDC}")


def sell_thread_worker():
    """
    [Thread 2] v20.0 BUAE 매도 스레드

    동작 흐름:
      Step 0: 09:15 모닝 정리매매 (수익 0.3%+ 코인 일괄 매도)
      Step 1: 보유 코인 순회 → evolution_80_sell_signal() 검사
              [v20.0] 5분봉 수집 + 레짐 판정 + BUAE 통합 판정
      Step 2: 매도 시그널 발생 시 execute_sell() 실행
    """
    global morning_cleanup_done, morning_cleanup_date

    print(f"{Colors.YELLOW}[Thread 2] v20.0 BUAE 매도 스레드 시작 ({SELL_THREAD_INTERVAL}초 주기){Colors.ENDC}")
    if MORNING_CLEANUP_ENABLED:
        print(f"{Colors.YELLOW}  └ 모닝정리: {MORNING_CLEANUP_HOUR:02d}:{MORNING_CLEANUP_MINUTE:02d}"
              f" 수익>={MORNING_CLEANUP_MIN_PROFIT}%{Colors.ENDC}")

    iteration = 0

    while not stop_event.is_set():
        try:
            iteration += 1

            # ── Step 0: 09:15 모닝 정리매매 ─────────────────────────────
            if MORNING_CLEANUP_ENABLED:
                now = datetime.now()
                today = now.date()

                # 날짜 변경 감지 → 플래그 초기화
                if morning_cleanup_date != today:
                    morning_cleanup_done = False
                    morning_cleanup_date = today

                if not morning_cleanup_done:
                    target_time = now.replace(
                        hour=MORNING_CLEANUP_HOUR,
                        minute=MORNING_CLEANUP_MINUTE, second=0, microsecond=0
                    )
                    window_start = target_time - timedelta(minutes=MORNING_CLEANUP_WINDOW)
                    window_end   = target_time + timedelta(minutes=MORNING_CLEANUP_WINDOW)

                    if window_start <= now <= window_end:
                        morning_cleanup_done = True

                        with held_coins_lock:
                            cleanup_tickers = list(held_coins.keys())

                        if cleanup_tickers:
                            print(f"\n{Colors.GREEN}{'='*50}")
                            print(f"[MORNING CLEANUP] {now.strftime('%H:%M')} 모닝 정리매매 시작")
                            print(f"{'='*50}{Colors.ENDC}")

                            cleanup_count = 0
                            for ticker in cleanup_tickers:
                                try:
                                    current_price = get_current_price(ticker)
                                    if current_price is None:
                                        continue

                                    with held_coins_lock:
                                        if ticker not in held_coins:
                                            continue
                                        buy_price = held_coins[ticker]['buy_price']

                                    profit_pct = ((current_price - buy_price) / buy_price) * 100
                                    coin_name  = ticker.replace('KRW-', '')

                                    if profit_pct >= MORNING_CLEANUP_MIN_PROFIT:
                                        sell_signal = {
                                            'signal':       True,
                                            'exit_price':   current_price,
                                            'profit_pct':   profit_pct,
                                            'bb_position':  50,
                                            'bb_width_pct': 2.0,
                                            'reason': (
                                                f'모닝정리({now.strftime("%H:%M")}'
                                                f' 수익{profit_pct:.2f}%'
                                                f'>={MORNING_CLEANUP_MIN_PROFIT}%)'
                                            )
                                        }
                                        print(f"  📌 {coin_name}: 수익 {profit_pct:+.2f}% → 매도 진행")
                                        success = execute_sell(ticker, sell_signal)
                                        if success:
                                            cleanup_count += 1
                                            print(f"  ✅ {coin_name} 모닝 정리 완료")
                                        time.sleep(1)
                                    else:
                                        print(f"  ⏳ {coin_name}: 수익 {profit_pct:+.2f}%"
                                              f" < {MORNING_CLEANUP_MIN_PROFIT}% → 유지")

                                except Exception as e:
                                    print(f"{Colors.RED}  [Cleanup Error] {ticker}: {e}{Colors.ENDC}")

                            if cleanup_count > 0:
                                cleanup_msg = f"""
☀️ **모닝 정리매매 완료**

**시간:** `{now.strftime('%H:%M:%S')}`
**정리:** `{cleanup_count}개 코인 매도`
**기준:** 수익 ≥ `{MORNING_CLEANUP_MIN_PROFIT}%`

⏰ {now.strftime('%Y-%m-%d %H:%M:%S')}
"""
                                send_discord_message(cleanup_msg)

                            print(f"{Colors.GREEN}[MORNING CLEANUP] 완료: {cleanup_count}개 매도{Colors.ENDC}\n")

            # ── Step 1: 매도 로직 ───────────────────────────────────────
            with held_coins_lock:
                tickers = list(held_coins.keys())

            if not tickers:
                if DEBUG_MODE and iteration % 60 == 0:
                    print(f"{Colors.YELLOW}[SELL] 보유 종목 없음{Colors.ENDC}")
                time.sleep(SELL_THREAD_INTERVAL)
                continue

            for ticker in tickers:

                if stop_event.is_set():
                    print(f"{Colors.YELLOW}[Thread 2] 종료 신호 수신{Colors.ENDC}")
                    return

                df_15m = get_extended_candles_15m(ticker, count=V80_CANDLES_15M_COUNT)

                if df_15m is None or len(df_15m) < 20:
                    if DEBUG_MODE:
                        print(f"{Colors.RED}[SELL] {ticker} 데이터 부족{Colors.ENDC}")
                    continue

                # ============================================================
                # [v20.0 추가] 5분봉 데이터 수집 + 시장 레짐 판정
                # ============================================================
                df_5m = get_extended_candles_5m(ticker, count=V80_CANDLES_5M_COUNT)

                regime_info = determine_market_regime(ticker, df_15m)
                regime = regime_info['regime']
                # ============================================================

                current_price = df_15m.iloc[-1]['close']
                current_bb    = df_15m.iloc[-1]['bb_position']

                # 피크가 갱신 추적
                with held_coins_lock:
                    if ticker not in held_coins:
                        continue

                    held_info = held_coins[ticker]

                    current_peak_price = held_info.get('peak_price', held_info['buy_price'])
                    if current_price > current_peak_price:
                        held_info['peak_price'] = current_price
                        held_info['peak_time']  = datetime.now()
                        if DEBUG_MODE:
                            coin_name = ticker.replace('KRW-', '')
                            print(f"{Colors.GREEN}[SELL] {coin_name} 신고가 갱신:"
                                  f" {current_price:,.0f}원{Colors.ENDC}")

                    current_peak_bb = held_info.get('peak_bb_position', 0)
                    if current_bb > current_peak_bb:
                        held_info['peak_bb_position'] = current_bb

                    buy_price  = held_info['buy_price']
                    buy_time   = held_info.get('buy_time', datetime.now())
                    buy_amount = held_info.get('buy_amount', 0)
                    buy_reason = held_info.get('buy_reason', '')

                    # ============================================================
                    # [v20.0 수정] held_info_copy에 보호선 관련 필드 5개 추가
                    # ============================================================
                    held_info_copy = {
                        'ticker':            ticker,
                        'buy_price':         buy_price,
                        'buy_time':          buy_time,
                        'buy_amount':        buy_amount,
                        'buy_reason':        buy_reason,
                        'peak_price':        held_info.get('peak_price', buy_price),
                        'peak_time':         held_info.get('peak_time', buy_time),
                        'peak_bb_position':  held_info.get('peak_bb_position', 0),
                        'buy_mode':          held_info.get('buy_mode', 'MOMENTUM_V80'),
                        # [v20.0 추가 필드]
                        'peak_profit_pct':    held_info.get('peak_profit_pct', 0),
                        'peak_bb_above_70':   held_info.get('peak_bb_above_70', False),
                        'candles_at_peak':    held_info.get('candles_at_peak', 0),
                        'protection_tier':    held_info.get('protection_tier', None),
                        'floor_breach_count': held_info.get('floor_breach_count', 0),
                    }
                    # ============================================================

                # ============================================================
                # [v20.0 수정] 매도 시그널 판단 — df_5m, regime 전달
                # ============================================================
                sell_signal = evolution_80_sell_signal(
                    df_15m, buy_price, buy_time, held_info_copy, df_5m, regime)
                # ============================================================

                # ============================================================
                # [v20.0 수정] 피크 + 보호선 정보 일괄 동기화
                # ============================================================
                with held_coins_lock:
                    if ticker in held_coins:
                        for key in ['peak_price', 'peak_time', 'peak_bb_position',
                                    'peak_profit_pct', 'peak_bb_above_70',
                                    'candles_at_peak', 'protection_tier',
                                    'floor_breach_count']:
                            if key in held_info_copy:
                                held_coins[ticker][key] = held_info_copy[key]
                # ============================================================

                if sell_signal['signal']:
                    profit_pct = sell_signal['profit_pct']
                    coin_name  = ticker.replace('KRW-', '')

                    color = Colors.GREEN if profit_pct >= 0 else Colors.RED
                    emoji = "📈" if profit_pct >= 0 else "📉"

                    print(f"\n{color}{'='*50}")
                    print(f"[SELL SIGNAL] {coin_name} 매도!")
                    print(f"{'='*50}{Colors.ENDC}")
                    print(f"  {emoji} 수익률: {profit_pct:+.2f}%")
                    print(f"  📊 BB 위치: {sell_signal['bb_position']:.1f}%")
                    print(f"  💰 매도가: {sell_signal['exit_price']:,.0f}원")
                    print(f"  🔍 사유: {sell_signal['reason']}")

                    if buy_time:
                        hold_duration = format_duration(datetime.now() - buy_time)
                        print(f"  ⏱️ 보유시간: {hold_duration}")

                    peak_price = held_info_copy.get('peak_price', buy_price)
                    if peak_price > buy_price:
                        peak_profit = ((peak_price - buy_price) / buy_price) * 100
                        drawdown = ((peak_price - sell_signal['exit_price']) / peak_price) * 100
                        print(f"  🏔️ 고점: {peak_price:,.0f}원 (+{peak_profit:.2f}%),"
                              f" 현재 -{drawdown:.1f}%")

                    print(f"{color}{'='*50}{Colors.ENDC}\n")

                    success = execute_sell(ticker, sell_signal)

                    if success:
                        print(f"{color}[SELL] {coin_name} 매도 완료! ({profit_pct:+.2f}%){Colors.ENDC}")
                    else:
                        print(f"{Colors.RED}[SELL] {coin_name} 매도 실패{Colors.ENDC}")

                    time.sleep(2)

                else:
                    if DEBUG_MODE and iteration % 60 == 0:
                        profit_pct = sell_signal['profit_pct']
                        coin_name  = ticker.replace('KRW-', '')
                        print(f"{Colors.CYAN}[SELL] {coin_name}: {profit_pct:+.2f}%,"
                              f" BB:{sell_signal['bb_position']:.0f}%,"
                              f" {sell_signal['reason']}{Colors.ENDC}")

                time.sleep(0.3)

            time.sleep(SELL_THREAD_INTERVAL)

        except Exception as e:
            error_trace = traceback.format_exc()
            print(f"{Colors.RED}[SELL Thread Error] {e}{Colors.ENDC}")
            if DEBUG_MODE:
                print(error_trace)

            if 'critical' in str(e).lower() or 'fatal' in str(e).lower():
                send_error_notification("SELL Thread Critical Error", error_trace[:500])

            time.sleep(SELL_THREAD_INTERVAL)

    print(f"{Colors.YELLOW}[Thread 2] v20.0 BUAE 매도 스레드 종료{Colors.ENDC}")


def monitor_thread_worker():
    """
    [Thread 3] 모니터 스레드 (60초 주기)

    동작:
      - 보유 현황 / 승률 / 평균 수익 주기 출력
      - 매시 정각(0~3분) 시 Discord 상세 통계 보고
    """
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
                current_win_rate   = (winning_trades / total_trades * 100) if total_trades > 0 else 0
                current_avg_profit = (total_profit / total_trades) if total_trades > 0 else 0

            # ── 주기 현황 출력 ────────────────────────────────────────
            print(f"\n{Colors.MAGENTA}{'='*10}")
            print(f"[Monitor] 반복 #{iteration} | {current_time.strftime('%H:%M:%S')}")
            print(f"  보유: {current_holdings}/{MAX_HOLDINGS} | "
                  f"거래: {total_trades}회 (금일 {daily_trade_count}회) | "
                  f"승률: {current_win_rate:.1f}%")
            print(f"  평균 수익: {current_avg_profit:+.2f}%")

            with held_coins_lock:
                for ticker, info in held_coins.items():
                    try:
                        current_price = get_current_price(ticker)
                        if current_price:
                            profit   = ((current_price - info['buy_price']) / info['buy_price']) * 100
                            duration = format_duration(current_time - info['buy_time'])
                            coin_name = ticker.replace("KRW-", "")
                            print(f"  - {coin_name}: {profit:+.2f}% ({duration})")
                    except Exception:
                        pass

            print(f"{'='*10}{Colors.ENDC}\n")

            # ── 매시 정각 Discord 보고 (59분 이상 경과 + 0~3분 윈도우) ──
            elapsed_since_report = (current_time - last_report_time).total_seconds()
            current_minute = current_time.minute

            if elapsed_since_report >= 3540 and 0 <= current_minute <= 3:
                print(f"{Colors.GREEN}[Monitor] 매시각 정시 보고 트리거"
                      f" ({current_time.strftime('%H:%M')}){Colors.ENDC}")
                send_enhanced_statistics_report()
                last_report_time = current_time

            time.sleep(MONITOR_THREAD_INTERVAL)

        except Exception as e:
            error_trace = traceback.format_exc()
            print(f"{Colors.RED}[Monitor Thread Error] {e}{Colors.ENDC}")
            if DEBUG_MODE:
                print(error_trace)
            time.sleep(MONITOR_THREAD_INTERVAL)

    print(f"{Colors.MAGENTA}[Thread 3] 모니터 스레드 종료{Colors.ENDC}")


# SECTION 19: Main Function
# ================================================================================

def main():
    """
    메인 함수 - 4개 스레드 오케스트레이션
    
    시작 순서:
      1. Upbit API 초기화 (인증 확인)
      2. 기존 보유 코인 동기화
      3. Thread 4 (WebSocket) 먼저 시작 → 가격 캐시 워밍업
      4. Thread 1,2,3 순차 시작
    """
    global upbit

    # ── 1. Upbit REST API 초기화 ──────────────────────────────────────────
    try:
        upbit = UpbitAPI(ACCESS_KEY, SECRET_KEY)
        print(f"{Colors.GREEN}[Init] Upbit API 연결 완료{Colors.ENDC}\n")
    except Exception as e:
        print(f"{Colors.RED}[Error] Upbit API 연결 실패: {e}{Colors.ENDC}")
        return

    # ── 2. 기존 보유 코인 동기화 ─────────────────────────────────────────
    print(f"{Colors.CYAN}[Init] 기존 보유 코인 동기화 중...{Colors.ENDC}")
    sync_success = sync_held_coins_with_exchange()
    if not sync_success:
        print(f"{Colors.YELLOW}[Warning] 동기화 실패했지만 계속 진행합니다.{Colors.ENDC}\n")

    with held_coins_lock:
        synced_coins = len(held_coins)

    # ── 3. Thread 4: WebSocket 먼저 시작 (가격 캐시 워밍업) ──────────────
    ws_thread = threading.Thread(
        target=websocket_thread_worker,
        name="WebSocketThread",
        daemon=True
    )
    ws_thread.start()

    # WebSocket 초기 연결 대기 (최대 5초)
    print(f"{Colors.CYAN}[Init] WebSocket 연결 대기 중...{Colors.ENDC}")
    ws_wait_start = time.time()
    while time.time() - ws_wait_start < 5.0:
        with ws_status_lock:
            if ws_status['connected']:
                break
        time.sleep(0.2)

    with ws_status_lock:
        ws_connected = ws_status['connected']
        ws_sub_count = len(ws_status['subscribed_tickers'])

    if ws_connected:
        print(f"{Colors.GREEN}[Init] WebSocket 연결 성공 ({ws_sub_count}개 코인 구독){Colors.ENDC}\n")
    else:
        print(f"{Colors.YELLOW}[Init] WebSocket 연결 대기 중 (REST fallback 활성화됨){Colors.ENDC}\n")

    # ── 4. Discord 시작 알림 ─────────────────────────────────────────────
    start_message = f"""
**🤖 봇 시작**

**버전:** `{VERSION}`
**모드:** `{'TEST MODE' if TEST_MODE else 'LIVE MODE'}`
**관심 코인:** `{len(FIXED_STABLE_COINS)}개`
**최대 보유:** `{MAX_HOLDINGS}개`
**동기화된 기존 보유:** `{synced_coins}개`
**WebSocket:** `{'✅ 연결됨' if ws_connected else '⏳ 연결 중'}`

⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
"""
    send_discord_message(start_message)

    # ── 5. Thread 1,2,3 순차 시작 ───────────────────────────────────────
    buy_thread     = threading.Thread(target=buy_thread_worker,     name="BuyThread",     daemon=True)
    sell_thread    = threading.Thread(target=sell_thread_worker,    name="SellThread",    daemon=True)
    monitor_thread = threading.Thread(target=monitor_thread_worker, name="MonitorThread", daemon=True)

    buy_thread.start()
    time.sleep(1)
    sell_thread.start()
    time.sleep(1)
    monitor_thread.start()

    print(f"{Colors.GREEN}[Main] 모든 스레드 시작 완료 (Thread 1~4){Colors.ENDC}\n")

    # ── 6. 메인 루프 (Ctrl+C 대기) ──────────────────────────────────────
    try:
        while True:
            time.sleep(1)

    except KeyboardInterrupt:
        print(f"\n{Colors.RED}{'='*10}")
        print(f"[Exit] 사용자 중단 - 안전 종료 시작")
        print(f"{'='*10}{Colors.ENDC}")

        stop_event.set()

        # WebSocket 연결 즉시 닫기
        with _ws_app_lock:
            if _ws_app:
                try:
                    _ws_app.close()
                except Exception:
                    pass

        print(f"{Colors.YELLOW}[Exit] 스레드 종료 대기 중...{Colors.ENDC}")
        ws_thread.join(timeout=5)
        buy_thread.join(timeout=10)
        sell_thread.join(timeout=10)
        monitor_thread.join(timeout=10)

        runtime = format_duration(datetime.now() - start_time)
        with statistics_lock:
            final_win_rate = (winning_trades / total_trades * 100) if total_trades > 0 else 0

        ws_stat = get_ws_status_summary()

        end_message = f"""
**🛑 봇 종료**

**가동 시간:** `{runtime}`
**총 거래:** `{total_trades}회`
**승:** `{winning_trades}` | **패:** `{losing_trades}`
**승률:** `{final_win_rate:.1f}%`
**WS 재연결:** `{ws_stat['reconnect_count']}회`

⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
"""
        send_discord_message(end_message)
        print(f"{Colors.GREEN}[Exit] 모든 스레드 종료 완료{Colors.ENDC}")


# SECTION 20: Program Entry Point
# ================================================================================

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        error_trace = traceback.format_exc()
        print(f"{Colors.RED}[Fatal Error] {error_trace}{Colors.ENDC}")
        send_error_notification("Fatal Error", error_trace)