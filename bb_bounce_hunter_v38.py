#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
═══════════════════════════════════════════════════════════════════════
BB Bounce Hunter v38.0 — Volatility-Spike Aware + Laddered Exit Edition
"변동성 폭발 시간대를 인식하고, 분할 매도로 양쪽 다 잡는다"
═══════════════════════════════════════════════════════════════════════

v37 → v38 핵심 변경 (TOKAMAK 매도 사건 학습 반영):

  [TOKAMAK 사건 진단]
  - 2026-05-02 08:47 매수 @ 818원 (BB 26%, 정상 진입)
  - 2026-05-02 09:00봉 변동성 폭발: high 855(+4.52%), low 813(-0.61%) 봉 내 4.91% 변동
  - v37 RALLY_GUARD_2H 발화: peak +4.52% 직후 drawdown 1.5%
  - 2026-05-02 09:17 매도 @ 817원, -0.24% 손실
  - 09:30봉 다시 +2.93% 회복 → 광현님 "3% 수익 기회 놓침" 판단

  [30일 통계 발견]
  - KST 09:00 = TOKAMAK 일중 최고 변동성(1.121%) + 최고 거래량(평균 184,928)
  - KST 09시 4H봉 평균 변동폭 3.288% (전체 시간대 1위)
  - 30일 중 09시 폭락 후 +1.5% 이상 반등 4건, +3% 이상 반등 4건

  [v38 신규 사양]

  [1] VOLATILITY_SPIKE_KOREA 시간대 신설 (KST 09:00~10:00)
      - FRESH 유예 60분 (다른 시간대 30분)
      - RALLY_GUARD 비활성 (V자 반등 함정 회피)
      - 트레일링 갭 1.5x 확대
      - 변동성 폭발봉 보호 활성

  [2] 분할 매도 (Laddered Exit) 도입
      - TIER1: +2.5% 도달 시 30% 분할 익절
      - TIER2: +5.0% 도달 시 추가 30% 분할 익절
      - 잔여 40%는 트레일링으로 끝까지 운영
      - 분할 매도는 쿨다운 0 (잔여 보유 중)

  [3] Ratchet Stop (RALLY_GUARD 대체)
      - peak +3% → stop +0.5% (본전 보호)
      - peak +5% → stop +1.5%
      - peak +8% → stop +3.5%
      - peak +12% → stop +6.5%
      - 한 번 올라가면 절대 내려가지 않음 (Milestone 기반)

  [4] 변동성 폭발봉 감지 + 매도 유예
      - 현재 15분봉 (high-low)/close > 2 × ATR_pct → Spike Bar
      - 매도 신호 5분 유예 (단, 절대손절 -5%는 즉시)

  [5] BB Squeeze Breakout 감지
      - 매수 시 BB Width < 15% AND 매도 시 BB Position > 90%
      - 트레일링 갭 2배 확대 (변동성에 길 열어줌)

  [6] 시간대별 매수 게이트
      - KST 08:30~09:30: 매수 BLOCK (변동성 폭발 직전)
      - KST 09:30~10:30: 매수 BONUS (폭락 후 반등 진입, BB 임계 완화)
      - KST 12:00~14:00: 매수 CAUTION (저거래량 슬리피지)

  [7] FRESH 유예 시간 차등
      - VOLATILITY_SPIKE_KOREA: 60분
      - GLOBAL_PEAK: 45분
      - 그 외: 30분 (기존)

  [8] 매도 사유 카테고리 추가
      - PARTIAL_TAKE (쿨다운 0)
      - RATCHET_STOP (쿨다운 60분)
      - SPIKE_RECOVERY (쿨다운 30분)

설계 철학:
  v37 = "고점에서 팔고, 시간대 가려서" (단일 매도)
  v38 = "변동성 폭발 시간대 인식 + 분할 매도로 양쪽 다 잡기"

학술/통계 근거:
  - Tradewink (2026) — Ratchet trailing stop이 연속 트레일링보다 변동성장에서 우월
  - Altrady (2025) — 25%/50%/100% 단계별 익절이 일괄 매도보다 우월
  - LuxAlgo (2025) — 변동성 큰 자산은 트레일링 갭을 ATR 1-2배 이상으로
  - TOKAMAK 30일 자체 데이터 분석 (KST 09시 변동성 1위 입증)

═══════════════════════════════════════════════════════════════════════
"""

import os
from dotenv import load_dotenv
load_dotenv()       # pip install python-dotenv PyJWT websocket-client pandas requests numpy

import jwt          # pip install PyJWT==2.8.0
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
from dataclasses import dataclass, field
from typing import Dict, List, Set, Optional, Tuple

# ★ v36: price_predictor 임포트 완전 제거 (사용자 핵심 지시 #5)
# v35의 'from price_predictor_v5_1 import get_prediction' 라인 삭제됨
# PREDICTOR_AVAILABLE 글로벌 플래그도 제거됨


# ═══════════════════════════════════════════════════════════════════════
# SECTION 1: 터미널 색상
# ═══════════════════════════════════════════════════════════════════════

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


# ═══════════════════════════════════════════════════════════════════════
# SECTION 2: 시스템 설정 (v36 단순화 — 등급 시스템 폐기)
# ═══════════════════════════════════════════════════════════════════════

DEBUG_MODE = True
TEST_MODE = False
VERSION = "38.0 VOLATILITY_SPIKE_AWARE — Laddered Exit + Ratchet Stop + Buy Time Gates"

# ── 거래 대상 (v36: 동적 — 마켓 와이드 스크리너가 결정) ──
QUOTE_CURRENCY = "KRW"

# 항상 모니터링하는 코인 (보유/관심 — 비어 있으면 100% 동적)
# v35의 FIXED_STABLE_COINS은 폐기 — 더 이상 4코인 고정 안 함
ALWAYS_MONITOR = []   # 빈 리스트 = 100% 동적 스크리너 결과

# ── 포지션 관리 ──
MAX_HOLDINGS = 3                    # v35: 2 → v36: 3 (스크리너가 더 많은 후보 제공)
FIRST_BUY_RATIO = 0.4               # 1차 매수 비율 (현금 잔고의 40%)
BUY_FEE_BUFFER = 0.995              # 수수료 버퍼
MIN_BUY_PRICE = 500                 # 최소 매수 가격
MIN_BUY_AMOUNT_KRW = 50000          # 코인당 최소 매수 5만원
MAX_DAILY_TRADES = 999

# ── 스레드 주기 ──
BUY_THREAD_INTERVAL = 30            # 매수 스레드 주기 (초)
SELL_THREAD_INTERVAL = 30           # 매도 스레드 주기 (초)
MONITOR_THREAD_INTERVAL = 600       # 모니터 주기 (10분)
BUY_SLEEP_WHEN_FULL = 60            # 보유 만석 시 대기 (초)

# ── BB/RSI 지표 (v35 동일) ──
BB_PERIOD = 20
BB_STD_DEV = 2.0
RSI_PERIOD = 14
STOCH_RSI_PERIOD = 14
STOCH_K_PERIOD = 3
STOCH_D_PERIOD = 3

# ── 5분봉 빌더 ──
WS_CANDLE_HISTORY_SIZE = 40
WS_CANDLE_MIN_FOR_INDICATOR = 22


# ═══════════════════════════════════════════════════════════════════════
# ★ v36 핵심: 마켓 와이드 스크리너 파라미터 (사용자 핵심 지시 #7,8)
# ═══════════════════════════════════════════════════════════════════════

# Tier 1: 빠른 필터 (Ticker API)
SCREENING_MIN_TRADING_VALUE_KRW = 1_000_000_000   # 24h 거래대금 ≥ 10억원
SCREENING_MAX_CHANGE_PCT = 20.0                   # 등락률 +20% 이하 (펌프 제외)
SCREENING_MIN_CHANGE_PCT = -10.0                  # 등락률 -10% 이상 (폭락 제외)

# 블랙리스트 (스테이블 / 잡코인)
SCREENING_BLACKLIST = [
    "KRW-USDT", "KRW-USDC", "KRW-DAI",   # 스테이블
]

# Tier 2: 정밀 분석
SCREENING_TOP_N_FROM_TIER1 = 30   # Tier1 통과 → Tier2 진입 최대 수
SCREENING_FINAL_TOP_N = 8         # 최종 후보 수

SCREENING_WEIGHTS = {
    "volume_rank":        0.35,   # 거래량
    "change_rate_rank":   0.25,   # 등락률
    "trading_value_rank": 0.40,   # 거래대금 (시총 가중치 흡수)
}

# 스크리닝 주기
SCREENING_INTERVAL_MIN = 60       # 매시 정각 (1H봉 동기화)


# ═══════════════════════════════════════════════════════════════════════
# ★ v36 핵심: EMA 추세 매수 파라미터 (사용자 핵심 지시 #1,4)
# ═══════════════════════════════════════════════════════════════════════

# 4H EMA (추세 자격 판정용)
EMA_4H_SHORT = 10
EMA_4H_MID = 20
EMA_4H_LONG = 50
EMA_4H_HISTORY_COUNT = 100    # 4H 캔들 100개 = 약 16일

# 매수 자격: 최근 N봉 중 종가<EMA20 봉 1개 이상 (눌림 발생)
EMA_PULLBACK_LOOKBACK = 5

# 매수 타이밍 (1H봉)
BUY_BB_MAX_POSITION = 30.0    # BB Position ≤ 30%
BUY_RSI_MIN = 25.0            # RSI ≥ 25 (극단 과매도 제외)
BUY_RSI_MAX = 55.0            # RSI ≤ 55 (반등 여력)
BUY_VOL_RATIO_MIN = 0.8       # 거래량 ≥ 10봉 평균 × 0.8

# 15분봉 3점 체크리스트 (RSI↑ + BB↑ + 양봉)
CONFIRM_15M_ENABLED = True
CONFIRM_15M_MIN_SCORE = 2

# 매수 차단 시간대 (업비트 정산기)
BUY_BLOCK_START_HM = (8, 50)
BUY_BLOCK_END_HM = (9, 30)

# 일일 매수 건수 제한
DAILY_BUY_COUNT_LIMIT = 5

# 재진입 쿨다운
REENTRY_COOLDOWN_MIN = 240    # 4시간


# ═══════════════════════════════════════════════════════════════════════
# ★ v38 핵심: 변동성 폭발 시간대 인식 + 분할 매도 + Ratchet Stop
# ═══════════════════════════════════════════════════════════════════════

# ── [v38 변경] KST 시간대 정책 (6개 세션, VOLATILITY_SPIKE_KOREA 신설) ──
TIME_ZONE_POLICY = {
    # ★ v38 신설: KST 09:00~10:00 변동성 폭발 시간대
    # TOKAMAK 30일 분석: 평균 변동폭 1.121%, 거래량 184,928 (일중 1위)
    "VOLATILITY_SPIKE_KOREA": {"start": (9, 0), "end": (10, 0),
                                "trail_mult": 1.5, "rsi_exit_th": 80.0,
                                "rally_guard_enabled": False,  # ★ V자 반등 함정 회피
                                "fresh_grace_min": 60,         # ★ 60분 유예
                                "spike_bar_protect": True},
    "GLOBAL_PEAK":    {"start": (22, 0), "end": (2, 0),
                       "trail_mult": 1.3, "rsi_exit_th": 78.0,
                       "rally_guard_enabled": True,
                       "fresh_grace_min": 45,
                       "spike_bar_protect": True},
    "KOREA_MORNING_LATE": {"start": (10, 0), "end": (12, 0),  # ★ v38: 9시 분리
                           "trail_mult": 0.9, "rsi_exit_th": 73.0,
                           "rally_guard_enabled": True,
                           "fresh_grace_min": 30,
                           "spike_bar_protect": True},
    "LOW_LIQUIDITY":  {"start": (12, 0), "end": (17, 0),
                       "trail_mult": 0.8, "rsi_exit_th": 73.0,
                       "rally_guard_enabled": False,
                       "fresh_grace_min": 30,
                       "spike_bar_protect": False},
    "EU_RAMP":        {"start": (17, 0), "end": (22, 0),
                       "trail_mult": 1.0, "rsi_exit_th": 75.0,
                       "rally_guard_enabled": True,
                       "fresh_grace_min": 30,
                       "spike_bar_protect": True},
    "OVERNIGHT_LATE": {"start": (2, 0),  "end": (9, 0),
                       "trail_mult": 1.0, "rsi_exit_th": 75.0,
                       "rally_guard_enabled": False,
                       "fresh_grace_min": 30,
                       "spike_bar_protect": False},
}

# ── [v38 NEW] 매수 시간대 게이트 ──
BUY_TIME_GATES = {
    "PRE_SPIKE_BLOCK": {
        # KST 08:30~09:30 매수 차단 (변동성 폭발 직전, V자 함정 위험)
        "start": (8, 30), "end": (9, 30),
        "action": "BLOCK",
    },
    "POST_SPIKE_BONUS": {
        # KST 09:30~10:30 매수 보너스 (폭락 후 반등 진입)
        "start": (9, 30), "end": (10, 30),
        "action": "BONUS",
        "bb_position_max_relax": 10,  # BB 임계 30→40% 완화
    },
    "LOW_LIQ_CAUTION": {
        # KST 12:00~14:00 슬리피지 신중
        "start": (12, 0), "end": (14, 0),
        "action": "CAUTION",
        "vol_ratio_min_extra": 0.3,  # 거래량 임계 +0.3
    },
}

# ── [v38 NEW] 분할 매도 (Laddered Exit) ──
LADDERED_EXIT_ENABLED = True
LADDERED_TIER1_PROFIT = 2.5    # +2.5% 도달 시
LADDERED_TIER1_RATIO  = 0.30   # 보유량의 30% 분할 익절
LADDERED_TIER2_PROFIT = 5.0    # +5.0% 도달 시
LADDERED_TIER2_RATIO  = 0.30   # 추가 30% (총 60% 익절)
# 잔여 40%는 Ratchet Stop / 동적 트레일링 / 추세종료로 운영

# ── [v38 NEW] Ratchet Stop (RALLY_GUARD 대체, 비후퇴 stop) ──
RATCHET_STOP_TIERS = [
    # (peak_pnl_threshold, stop_to_pnl) — 한 번 활성화되면 절대 내려가지 않음
    (12.0, 6.5),    # peak +12% → stop +6.5%
    (8.0,  3.5),    # peak +8%  → stop +3.5%
    (5.0,  1.5),    # peak +5%  → stop +1.5%
    (3.0,  0.5),    # peak +3%  → stop +0.5% (본전 보호)
]

# ── [v38 NEW] 변동성 폭발봉 (Spike Bar) 감지 ──
SPIKE_BAR_ATR_MULTIPLE = 2.0     # high-low 범위가 ATR_pct의 2배 이상이면 Spike
SPIKE_BAR_DELAY_SEC = 300        # 매도 5분 유예
SPIKE_BAR_RECOVERY_PCT = 1.0     # 5분 후 매수가 +1% 이상 회복 시 매도 취소

# ── [v38 NEW] BB Squeeze Breakout 감지 ──
SQUEEZE_BREAK_BB_WIDTH_TH = 15.0  # 매수 시점 BB Width < 15%
SQUEEZE_BREAK_BB_POS_TH = 90.0    # 현재 BB Position > 90%
SQUEEZE_BREAK_TRAIL_MULT = 2.0    # 트레일링 갭 2배 확대

# ── [v37 호환 유지] ATR 기반 변동성 정규화 트레일링 ──
ATR_TRAIL_K_MULT = 3.0          # trail_pct = k × ATR_pct
ATR_TRAIL_MIN_PCT = 2.0         # 최소 트레일 갭 (%)
ATR_TRAIL_MAX_PCT = 8.0         # 최대 트레일 갭 (%)
ATR_PERIOD = 14                 # ATR 계산 기간

# ── [v37 호환 유지] 보유 단계 정의 (FRESH는 시간대별 차등으로 변경) ──
# v38: PHASE_FRESH_MAX_HOURS는 fallback (시간대 정책의 fresh_grace_min이 우선)
PHASE_FRESH_MAX_HOURS  = 0.5    # 기본 0~30분 (시간대 정책으로 override)
PHASE_EARLY_MAX_HOURS  = 6.0    # 30분~6h
PHASE_MID_MAX_HOURS    = 24.0   # 6h~24h

# ── [v37 호환 유지] 단기 천장 다중 신호 합의 ──
TOP_SIGNAL_BB_TH = 90.0
TOP_SIGNAL_RSI_TH = 75.0
TOP_SIGNAL_STOCH_K_TH = 90.0
TOP_SIGNAL_UPPER_WICK_RATIO = 0.60
TOP_SIGNAL_MIN_AGREE = 3
TOP_SIGNAL_MIN_PROFIT = 2.0

# ── [v37 호환 유지, v38에서는 Ratchet Stop이 우선] Rally Guard ──
RALLY_GUARD_2H_PROFIT_TH = 3.0
RALLY_GUARD_2H_DRAWDOWN = 1.5
RALLY_GUARD_6H_PROFIT_TH = 5.0
RALLY_GUARD_6H_DRAWDOWN = 2.0

# ── [v37 유지] 2-Bar 확정 손절 ──
TWO_BAR_CONFIRM_LOSS_PCT = -3.0

# ── [v37 유지] BTC 시스템 리스크 감지 ──
BTC_CRASH_1H_PCT = -3.0
BTC_CRASH_5M_CONSECUTIVE = 3

# ── [v38 변경] 매도 사유별 재진입 쿨다운 (PARTIAL_TAKE, RATCHET_STOP, SPIKE_RECOVERY 추가) ──
COOLDOWN_PARTIAL_TAKE  = 0       # ★ v38 NEW: 분할 매도 (잔여 보유 중이므로 쿨다운 없음)
COOLDOWN_PROFIT_TAKE   = 30
COOLDOWN_TRAILING      = 60
COOLDOWN_RSI_REVERT    = 45
COOLDOWN_TOP_SIGNAL    = 45
COOLDOWN_RALLY_GUARD   = 60      # 레거시
COOLDOWN_RATCHET_STOP  = 60      # ★ v38 NEW
COOLDOWN_SPIKE_RECOVERY = 30     # ★ v38 NEW
COOLDOWN_STOPLOSS      = 240
COOLDOWN_TREND_END     = 1440
COOLDOWN_BTC_CRASH     = 360

# ── D+0 안전장치 (v36 유지) ──
INTRADAY_STOP_LOSS_PCT = -3.0
INTRADAY_STOP_GRACE_SEC = 1800
ACCEL_STOP_5M_BEAR_COUNT = 3
ACCEL_STOP_RSI_THRESHOLD = 25.0
ACCEL_STOP_DROP_PCT = 0.8

# ── D+1 추세 이탈 매도 (v36 유지, MATURE 단계에서 적용) ──
EMA_TREND_BREAK_BARS = 2
DEADCROSS_MIN_HOLD_HOURS = 24


# ── 기존 v36 호환 트레일링 (레거시 보존) ──
ELASTIC_TRAIL_TIERS = [
    (20.0, -6.0), (10.0, -5.0), (5.0, -4.0), (2.0, -3.0),
]
TRAILING_DEFAULT_PCT = -3.0
TRAILING_MIN_HOLD_HOURS = 12

# ④ RSI 과매수 반전 (v37: D+0 활성화 + 시간대 차등)
RSI_OVERBOUGHT_EXIT = 75.0     # 기본 임계 (시간대 정책으로 override)
RSI_OVERBOUGHT_COOL = 65.0
RSI_EXIT_MIN_PROFIT = 2.0

# ⑤ 절대 손절
ABSOLUTE_STOP_LOSS_PCT = -5.0

# ★ v37 변경 요약:
#   [신규 추가]
#   + TIME_ZONE_POLICY (5개 세션 차등)
#   + ATR_TRAIL_* (변동성 정규화)
#   + PHASE_*_MAX_HOURS (4단계 분류)
#   + TOP_SIGNAL_* (단기 천장 합의)
#   + RALLY_GUARD_* (급등 보호 부활)
#   + TWO_BAR_CONFIRM_* (2-Bar 손절)
#   + BTC_CRASH_* (시스템 위기 감지)
#   + COOLDOWN_* (사유별 쿨다운)
#   [v36에서 유지]
#   - 절대손절 -5%, EMA50 하회, 데드크로스, 가속손절
#   [v34에서 부활]
#   - RSI 과매수 반전 (D+0 활성)


# ═══════════════════════════════════════════════════════════════════════
# SECTION 3: 환경 변수 및 글로벌 상태
# ═══════════════════════════════════════════════════════════════════════

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
recent_sells = {}        # 재진입 쿨다운용
daily_trade_count = 0
last_reset_date = datetime.now().date()
data_cache = {}
cache_timestamps = {}

# ★ v36 핵심 인스턴스 (main()에서 생성)
ema_tracker = None       # EMA4HTracker
screener = None          # MarketWideScreener
buy_engine = None        # EMATrendBuyEngine
sell_engine = None       # TrendSellEngine

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


# ═══════════════════════════════════════════════════════════════════════
# SECTION 4: 시작 메시지 (v36 — 등급/예측기 표시 제거)
# ═══════════════════════════════════════════════════════════════════════

_STARTUP_BANNER = f"""
{Colors.BOLD}{Colors.CYAN}{'='*68}
  CRYPTO VOLATILITY-SPIKE AWARE HUNTER {VERSION}
  ★★★ v38.0: 변동성 폭발 시간대 인식 + 분할 매도로 양쪽 다 잡기

  ★ 마켓 와이드 스크리너: 업비트 KRW 200+ 코인 매시 정각 스크리닝

  ★★ v38 매수 시간대 게이트:
     [BLOCK]   KST 08:30~09:30 (변동성 폭발 직전)
     [BONUS]   KST 09:30~10:30 (BB 임계 30→40% 완화, 폭락 후 진입)
     [CAUTION] KST 12:00~14:00 (거래량 임계 +0.3, 슬리피지 회피)

  ★★ v38 매도 로직 (TOKAMAK 사건 학습 반영):
     [1] VOLATILITY_SPIKE_KOREA 시간대 신설 (KST 09:00~10:00)
         → FRESH 60분 유예, RALLY_GUARD 비활성, 트레일링 1.5x
     [2] 분할 매도 (Laddered Exit)
         → +2.5% 30%, +5.0% 30%, 잔여 40% 트레일링
     [3] Ratchet Stop (RALLY_GUARD 대체, 비후퇴 stop)
         → peak +3% → stop +0.5%, peak +5% → +1.5% 등
     [4] 변동성 폭발봉 (Spike Bar) 감지
         → 매도 5분 유예, 회복 시 취소
     [5] BB Squeeze Breakout 감지 → 트레일링 2배 확대
     [6] 시간대 정책 6분류 + FRESH 유예 차등
     [7] 매도 사유별 차등 재진입 쿨다운 (PARTIAL_TAKE 0분)

{'='*68}
  Thread 1: 매수 ({BUY_THREAD_INTERVAL}초) │ EMA자격 + v38 시간대 게이트
  Thread 2: 매도 ({SELL_THREAD_INTERVAL}초) │ v38 Sell-Side Specialist (8단계)
  Thread 3: 모니터 ({MONITOR_THREAD_INTERVAL}초) │ 매시 정각 재스크리닝
  Thread 4: WebSocket │ 보유+후보 코인 실시간 가격
  MAX 보유: {MAX_HOLDINGS}개 | 1차:{FIRST_BUY_RATIO:.0%} 2차:전량
{'='*68}{Colors.ENDC}
"""
# ═══════════════════════════════════════════════════════════════════════
# SECTION 5: Upbit REST API 클라이언트 (v35 그대로 유지)
# ═══════════════════════════════════════════════════════════════════════

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
                if resp.status_code == 401:
                    return None
                if resp.status_code == 429:
                    time.sleep(5 * attempt)
                    continue
                time.sleep(2 * attempt)
            except requests.exceptions.ConnectionError:
                time.sleep(3 * attempt)
            except Exception:
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
            return resp.json()
        except Exception:
            return None

    def sell_market_order(self, ticker, volume):
        try:
            params = {
                'market': ticker, 'side': 'ask',
                'volume': str(volume), 'ord_type': 'market',
            }
            headers = self._auth_headers(params)
            resp = requests.post(f"{UPBIT_API_BASE}/v1/orders", json=params, headers=headers, timeout=10)
            return resp.json()
        except Exception:
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
                        'executed_volume': total_volume, 'state': state,
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
                    'state': order.get('state', 'timeout'),
                }
            return None
        except Exception:
            return None


# ═══════════════════════════════════════════════════════════════════════
# SECTION 6: WebSocket + 5분봉 실시간 빌더 (v35 동일 + 동적 구독)
# ═══════════════════════════════════════════════════════════════════════

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
CACHE_TTL_DAILY = 300

_api_last_call_time = 0.0
_api_call_lock = threading.Lock()

# 5분봉 실시간 빌더
ws_candles_5m = {}
ws_candles_5m_lock = threading.Lock()
_ws_candle_initialized = {}


def _rate_limit_wait(min_interval=0.12):
    global _api_last_call_time
    with _api_call_lock:
        now = time.time()
        elapsed = now - _api_last_call_time
        if elapsed < min_interval:
            time.sleep(min_interval - elapsed)
        _api_last_call_time = time.time()


def _get_5m_slot(ts=None):
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
    except Exception:
        return False


def _update_ws_candle(ticker, price, volume_delta=0.0, ts=None):
    """WebSocket 틱 → 5분봉 실시간 갱신"""
    try:
        if ts is None:
            ts = time.time()
        current_slot = _get_5m_slot(ts)

        with ws_candles_5m_lock:
            if ticker not in ws_candles_5m:
                return

            candle_data = ws_candles_5m[ticker]
            current = candle_data['current']

            if current is None:
                candle_data['current'] = {
                    'open': price, 'high': price, 'low': price, 'close': price,
                    'volume': volume_delta, 'slot': current_slot, 'timestamp': ts,
                }
                return

            if current['slot'] == current_slot:
                current['high'] = max(current['high'], price)
                current['low'] = min(current['low'], price)
                current['close'] = price
                current['volume'] += volume_delta
                current['timestamp'] = ts
            else:
                completed_candle = {
                    'open': current['open'],
                    'high': current['high'],
                    'low': current['low'],
                    'close': current['close'],
                    'volume': current['volume'],
                    'timestamp': current['slot'],
                }
                candle_data['history'].append(completed_candle)
                candle_data['indicators_ready'] = (
                    len(candle_data['history']) >= WS_CANDLE_MIN_FOR_INDICATOR
                )
                candle_data['current'] = {
                    'open': price, 'high': price, 'low': price, 'close': price,
                    'volume': volume_delta, 'slot': current_slot, 'timestamp': ts,
                }
    except Exception:
        pass


def get_ws_candles_5m(ticker, include_current=True):
    """WS 빌더에서 5분봉 DataFrame 반환"""
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

        df = add_indicators(df)
        return df

    except Exception:
        return None


def _get_ws_subscribe_tickers():
    """★ v36 변경: 보유 코인 + 스크리너 후보 동적 구독"""
    tickers = set(ALWAYS_MONITOR)
    try:
        with held_coins_lock:
            tickers.update(held_coins.keys())
    except Exception:
        pass
    # ★ v36 신규: 스크리너 후보 추가
    try:
        if screener is not None:
            for c in screener.get_last_results():
                tickers.add(c.ticker)
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
    if not tickers:
        # v36: 스크리닝 전이면 빈 구독 (스크리닝 후 재연결로 적용됨)
        tickers = []
    msg = _build_subscribe_message(tickers) if tickers else json.dumps([{"ticket": str(uuid.uuid4())}])
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
        ts = time.time()
        if code and price > 0:
            with ws_price_lock:
                ws_price_cache[code] = {'price': price, 'ts': ts}
            with ws_status_lock:
                ws_status['last_received'] = ts

            vol_delta = float(data.get('acc_trade_volume', 0)) * 0.001
            _update_ws_candle(code, price, vol_delta, ts)

            # ★ v36: EMA 트래커 현재가 갱신
            if ema_tracker is not None:
                ema_tracker.update_current_price(code, price)

    except Exception:
        pass


def _ws_on_error(ws, error):
    with ws_status_lock:
        ws_status['error_count'] += 1


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
    print(f"{Colors.BLUE}[Thread 4] WebSocket 빌더 스레드 시작{Colors.ENDC}")
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


def reconnect_websocket():
    """★ v36 신규: 스크리닝 후 WS 재구독 트리거"""
    global _ws_app
    try:
        with _ws_app_lock:
            if _ws_app is not None:
                _ws_app.close()  # run_forever 루프가 자동으로 재연결
    except Exception:
        pass


def get_ws_status_summary():
    with ws_status_lock:
        return {
            'connected': ws_status['connected'],
            'reconnect_count': ws_status['reconnect_count'],
            'subscribed': len(ws_status['subscribed_tickers']),
            'error_count': ws_status['error_count'],
        }


# ═══════════════════════════════════════════════════════════════════════
# SECTION 7: 현재가 조회 (v35 동일)
# ═══════════════════════════════════════════════════════════════════════

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


# ═══════════════════════════════════════════════════════════════════════
# SECTION 8: OHLCV 데이터 수집 (v35 + 1H/4H 추가)
# ═══════════════════════════════════════════════════════════════════════

def get_ohlcv(ticker, interval="minute15", count=200, to=None):
    """★ v36 변경: minute60 (1H), minute240 (4H) 인터벌 추가"""
    try:
        _rate_limit_wait()
        interval_map = {
            'minute1':   '/v1/candles/minutes/1',
            'minute5':   '/v1/candles/minutes/5',
            'minute15':  '/v1/candles/minutes/15',
            'minute60':  '/v1/candles/minutes/60',    # ★ v36 신규: 1H
            'minute240': '/v1/candles/minutes/240',   # ★ v36 신규: 4H
            'day':       '/v1/candles/days',
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


# ═══════════════════════════════════════════════════════════════════════
# SECTION 9: 스마트 캐시 시스템 (v35 동일 + 1H/4H 추가)
# ═══════════════════════════════════════════════════════════════════════

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
    """15분봉 경계 인식 스마트 TTL"""
    now = datetime.now()
    minutes_in_period = now.minute % 15
    seconds_in_period = minutes_in_period * 60 + now.second
    if seconds_in_period < 30:
        return 10
    elif seconds_in_period > 840:
        return 10
    else:
        return 120


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
    try:
        cache_key = f"{ticker}_5m_{count}"
        cached = get_cached_data(cache_key, 15)
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
    """5분봉 통합 — WS 빌더 우선, REST 폴백"""
    df = get_ws_candles_5m(ticker, include_current=True)
    if df is not None and len(df) >= 20:
        return df
    return get_candles_5m_rest(ticker, count)


def get_candles_1h(ticker, count=50):
    """★ v36 신규: 1시간봉 조회 (매수 타이밍 판정용)"""
    try:
        cache_key = f"{ticker}_1h_{count}"
        # 1H봉은 5분 캐시 (현재 봉 갱신 빈도)
        cached = get_cached_data(cache_key, 300)
        if cached is not None:
            return cached
        df = get_ohlcv(ticker, interval="minute60", count=count)
        if df is not None and len(df) >= 20:
            df = add_indicators(df)
            if df is not None:
                # 1H봉용 거래량 비율 추가
                df['vol_ratio'] = df['volume'] / df['volume'].rolling(window=10).mean().fillna(df['volume'])
                set_cached_data(cache_key, df)
                return df
        return None
    except Exception:
        return None


def get_candles_4h(ticker, count=100):
    """★ v36 신규: 4시간봉 조회 (EMA 추세 판정용)"""
    try:
        cache_key = f"{ticker}_4h_{count}"
        # 4H봉은 15분 캐시 (현재 봉 갱신 빈도)
        cached = get_cached_data(cache_key, 900)
        if cached is not None:
            return cached
        df = get_ohlcv(ticker, interval="minute240", count=count)
        if df is not None and len(df) >= 20:
            df = add_indicators(df)
            if df is not None:
                set_cached_data(cache_key, df)
                return df
        return None
    except Exception:
        return None


# ═══════════════════════════════════════════════════════════════════════
# SECTION 10: 기술 지표 계산 (v35 동일 — EMA5/10 제거)
# ═══════════════════════════════════════════════════════════════════════

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
    """★ v36 변경: v34의 EMA5/10 제거 (TrendSell EMA 매도 폐기됨)"""
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
    except Exception:
        return None


# ═══════════════════════════════════════════════════════════════════════
# ★ [v37 NEW] 매도 보조 함수 그룹 — 시간대/단계/ATR/천장/BTC위기/2-Bar
# ═══════════════════════════════════════════════════════════════════════

def _classify_kst_session(now=None):
    """★ v38 변경: KST 시간을 6개 세션 중 하나로 분류 (VOLATILITY_SPIKE_KOREA 신설)

    Returns:
        (session_name, policy_dict)
    """
    if now is None:
        now = datetime.now()
    hm = now.hour * 60 + now.minute

    # GLOBAL_PEAK: 22:00~익일 02:00 (자정 넘어감)
    if hm >= 22 * 60 or hm < 2 * 60:
        return "GLOBAL_PEAK", TIME_ZONE_POLICY["GLOBAL_PEAK"]
    # OVERNIGHT_LATE: 02:00~09:00
    if 2 * 60 <= hm < 9 * 60:
        return "OVERNIGHT_LATE", TIME_ZONE_POLICY["OVERNIGHT_LATE"]
    # ★ v38 신설: VOLATILITY_SPIKE_KOREA: 09:00~10:00 (TOKAMAK 사건 학습)
    if 9 * 60 <= hm < 10 * 60:
        return "VOLATILITY_SPIKE_KOREA", TIME_ZONE_POLICY["VOLATILITY_SPIKE_KOREA"]
    # KOREA_MORNING_LATE: 10:00~12:00 (구 KOREA_MORNING 후반)
    if 10 * 60 <= hm < 12 * 60:
        return "KOREA_MORNING_LATE", TIME_ZONE_POLICY["KOREA_MORNING_LATE"]
    # LOW_LIQUIDITY: 12:00~17:00
    if 12 * 60 <= hm < 17 * 60:
        return "LOW_LIQUIDITY", TIME_ZONE_POLICY["LOW_LIQUIDITY"]
    # EU_RAMP: 17:00~22:00
    return "EU_RAMP", TIME_ZONE_POLICY["EU_RAMP"]


def _classify_holding_phase(elapsed_hours, fresh_grace_min=None):
    """★ v38 변경: FRESH 임계 시간을 시간대별로 차등 적용

    Args:
        elapsed_hours: 보유 경과 시간(시간 단위)
        fresh_grace_min: 시간대 정책의 fresh_grace_min (분 단위, None이면 기본 사용)

    Returns:
        'FRESH' | 'EARLY' | 'MID' | 'MATURE'
    """
    # 시간대 정책의 FRESH 유예 시간 적용 (기본 30분)
    if fresh_grace_min is not None:
        fresh_max = fresh_grace_min / 60.0  # 분 → 시간 변환
    else:
        fresh_max = PHASE_FRESH_MAX_HOURS

    if elapsed_hours < fresh_max:
        return "FRESH"
    elif elapsed_hours < PHASE_EARLY_MAX_HOURS:
        return "EARLY"
    elif elapsed_hours < PHASE_MID_MAX_HOURS:
        return "MID"
    else:
        return "MATURE"


def _calc_atr_pct(df_15m, period=ATR_PERIOD):
    """ATR을 종가 대비 % 단위로 반환

    Returns:
        ATR_pct (float, 예: 1.5 = 1.5%) 또는 None (계산 실패)
    """
    if df_15m is None or len(df_15m) < period + 1:
        return None
    try:
        high = df_15m["high"].astype(float)
        low = df_15m["low"].astype(float)
        close = df_15m["close"].astype(float)
        prev_close = close.shift(1)

        tr1 = high - low
        tr2 = (high - prev_close).abs()
        tr3 = (low - prev_close).abs()
        tr = tr1.combine(tr2, max).combine(tr3, max)
        atr = tr.rolling(window=period).mean().iloc[-1]

        last_close = close.iloc[-1]
        if last_close <= 0 or atr is None or atr != atr:  # NaN 체크
            return None

        atr_pct = (atr / last_close) * 100.0
        return float(atr_pct)
    except Exception:
        return None


def _calc_dynamic_trail_pct(atr_pct, session_policy, phase):
    """ATR + 시간대 + 단계 → 동적 트레일링 갭 계산

    Returns:
        trail_pct (양수, 예: 3.5 = peak 대비 3.5% 하락 시 매도)
    """
    if atr_pct is None or atr_pct <= 0:
        base = 3.0  # ATR 계산 실패 시 기본값
    else:
        base = ATR_TRAIL_K_MULT * atr_pct

    # 시간대 가중치
    base *= session_policy.get("trail_mult", 1.0)

    # 단계 가중치 (EARLY는 빠르게 보호, MATURE는 느슨하게)
    phase_mult = {"FRESH": 0.6, "EARLY": 0.7, "MID": 0.9, "MATURE": 1.0}.get(phase, 1.0)
    base *= phase_mult

    return max(ATR_TRAIL_MIN_PCT, min(ATR_TRAIL_MAX_PCT, base))


def _check_short_term_top_signal(ticker, profit_pct):
    """단기 천장 식별: BB + RSI + StochRSI + 윗꼬리 다중 합의

    Returns:
        (is_top, agree_count, signal_tags)
    """
    if profit_pct < TOP_SIGNAL_MIN_PROFIT:
        return False, 0, []

    agree = 0
    tags = []

    # 1H봉 점검 (BB Position, RSI, 윗꼬리)
    df_1h = get_candles_1h(ticker, count=5)
    if df_1h is not None and len(df_1h) >= 2:
        c = df_1h.iloc[-1]
        bb_pos = c.get("bb_position", 50.0)
        rsi_1h = c.get("rsi", 50.0)

        if bb_pos > TOP_SIGNAL_BB_TH:
            agree += 1
            tags.append(f"BB{bb_pos:.0f}%")

        if rsi_1h > TOP_SIGNAL_RSI_TH:
            agree += 1
            tags.append(f"RSI{rsi_1h:.0f}")

        # 1H 음봉 + 윗꼬리 비율
        try:
            o = float(c["open"])
            h = float(c["high"])
            l = float(c["low"])
            cl = float(c["close"])
            full_range = h - l
            if full_range > 0:
                upper_wick = h - max(o, cl)
                wick_ratio = upper_wick / full_range
                is_bear = cl < o
                if is_bear and wick_ratio >= TOP_SIGNAL_UPPER_WICK_RATIO:
                    agree += 1
                    tags.append(f"윗꼬리{wick_ratio:.0%}")
        except Exception:
            pass

    # 15분 StochRSI %K 데드크로스 (90+ 영역에서)
    df_15m = get_candles_15m(ticker, count=5)
    if df_15m is not None and len(df_15m) >= 2:
        try:
            # v36의 add_indicators는 srsi_k/srsi_d 컬럼 사용
            k_now = float(df_15m.iloc[-1].get("srsi_k", 50.0))
            d_now = float(df_15m.iloc[-1].get("srsi_d", 50.0))
            k_prev = float(df_15m.iloc[-2].get("srsi_k", 50.0))
            d_prev = float(df_15m.iloc[-2].get("srsi_d", 50.0))

            if k_prev >= TOP_SIGNAL_STOCH_K_TH and k_prev > d_prev and k_now < d_now:
                agree += 1
                tags.append("StochDX")
        except Exception:
            pass

    is_top = agree >= TOP_SIGNAL_MIN_AGREE
    return is_top, agree, tags


def _check_btc_system_risk():
    """BTC 1H -3%+ 또는 5분봉 N연속 -1%+ 하락 시 시스템 위기 감지

    Returns:
        (is_crash, reason)
    """
    try:
        # 1H봉 점검
        df_btc_1h = get_candles_1h("KRW-BTC", count=2)
        if df_btc_1h is not None and len(df_btc_1h) >= 1:
            c = df_btc_1h.iloc[-1]
            o = float(c["open"])
            cl = float(c["close"])
            if o > 0:
                change = (cl - o) / o * 100
                if change <= BTC_CRASH_1H_PCT:
                    return True, f"BTC1H급락({change:+.2f}%)"

        # 5분봉 N연속 -1%+ 점검
        df_btc_5m = get_candles_5m(
            "KRW-BTC",
            count=BTC_CRASH_5M_CONSECUTIVE + 1,
        )
        if df_btc_5m is not None and len(df_btc_5m) >= BTC_CRASH_5M_CONSECUTIVE:
            consecutive = 0
            for i in range(-1, -(BTC_CRASH_5M_CONSECUTIVE + 1), -1):
                bar = df_btc_5m.iloc[i]
                o = float(bar["open"])
                cl = float(bar["close"])
                if o > 0 and (cl - o) / o * 100 <= -1.0:
                    consecutive += 1
                else:
                    break
            if consecutive >= BTC_CRASH_5M_CONSECUTIVE:
                return True, f"BTC5분{consecutive}연속급락"
    except Exception:
        pass

    return False, ""


def _check_two_bar_stoploss(df_5m, buy_price, threshold_pct=TWO_BAR_CONFIRM_LOSS_PCT):
    """5분봉 2봉 연속 종가가 매수가 대비 임계값 이하인지 확인

    Returns:
        bool (True = 2봉 확정 손절 발화)
    """
    if df_5m is None or len(df_5m) < 2 or buy_price <= 0:
        return False
    try:
        c1 = float(df_5m.iloc[-1]["close"])
        c2 = float(df_5m.iloc[-2]["close"])
        pct1 = (c1 - buy_price) / buy_price * 100
        pct2 = (c2 - buy_price) / buy_price * 100
        return pct1 <= threshold_pct and pct2 <= threshold_pct
    except Exception:
        return False


def get_cooldown_for_category(sell_category):
    """★ v38 변경: PARTIAL_TAKE, RATCHET_STOP, SPIKE_RECOVERY 추가"""
    return {
        "PARTIAL_TAKE":   COOLDOWN_PARTIAL_TAKE,    # ★ v38 NEW: 분할 매도 (잔여 보유 중)
        "PROFIT_TAKE":    COOLDOWN_PROFIT_TAKE,
        "TOP_SIGNAL":     COOLDOWN_TOP_SIGNAL,
        "RSI_REVERT":     COOLDOWN_RSI_REVERT,
        "RALLY_GUARD":    COOLDOWN_RALLY_GUARD,     # 레거시 (v38은 Ratchet 사용)
        "RATCHET_STOP":   COOLDOWN_RATCHET_STOP,    # ★ v38 NEW
        "SPIKE_RECOVERY": COOLDOWN_SPIKE_RECOVERY,  # ★ v38 NEW
        "TRAILING":       COOLDOWN_TRAILING,
        "STOPLOSS":       COOLDOWN_STOPLOSS,
        "TREND_END":      COOLDOWN_TREND_END,
        "BTC_CRASH":      COOLDOWN_BTC_CRASH,
    }.get(sell_category, 60)


# ═══════════════════════════════════════════════════════════════════════
# ★ [v38 NEW] 매도 보조 함수 그룹 — 매수 게이트/Ratchet/Spike/Squeeze/분할매도
# ═══════════════════════════════════════════════════════════════════════

def _get_buy_time_gate(now=None):
    """v38 매수 시간대 게이트 평가

    Returns:
        (gate_name, action, params)
        - action: 'BLOCK' (매수 차단) | 'BONUS' (BB 임계 완화) | 'CAUTION' (거래량 임계 강화) | 'ALLOW'
    """
    if now is None:
        now = datetime.now()
    hm = now.hour * 60 + now.minute

    for name, cfg in BUY_TIME_GATES.items():
        sh, sm = cfg["start"]
        eh, em = cfg["end"]
        start_min = sh * 60 + sm
        end_min = eh * 60 + em
        if start_min <= hm < end_min:
            return name, cfg["action"], cfg

    return None, "ALLOW", {}


def _calc_ratchet_stop_pnl(peak_pnl):
    """Ratchet Stop: peak_pnl에 해당하는 stop의 pnl 임계값 반환

    Returns:
        stop_pnl (float, %) 또는 None (해당 tier 없음)
    """
    for threshold, stop_to in RATCHET_STOP_TIERS:
        if peak_pnl >= threshold:
            return stop_to
    return None


def _check_spike_bar(df_15m, atr_pct):
    """현재 15분봉이 변동성 폭발봉(Spike Bar)인지 판정

    Args:
        df_15m: 15분봉 DataFrame
        atr_pct: ATR_pct (%)

    Returns:
        (is_spike: bool, bar_range_pct: float)
    """
    if df_15m is None or len(df_15m) < 1 or atr_pct is None or atr_pct <= 0:
        return False, 0.0
    try:
        c = df_15m.iloc[-1]
        h = float(c["high"])
        l = float(c["low"])
        cl = float(c["close"])
        if cl <= 0:
            return False, 0.0
        bar_range_pct = (h - l) / cl * 100
        is_spike = bar_range_pct >= SPIKE_BAR_ATR_MULTIPLE * atr_pct
        return is_spike, bar_range_pct
    except Exception:
        return False, 0.0


def _check_squeeze_breakout(buy_bb_width, current_bb_position):
    """BB Squeeze Breakout 패턴 감지

    Args:
        buy_bb_width: 매수 시점 BB Width (%)
        current_bb_position: 현재 1H BB Position (%)

    Returns:
        bool
    """
    if buy_bb_width is None or current_bb_position is None:
        return False
    try:
        bw = float(buy_bb_width)
        bp = float(current_bb_position)
        return bw < SQUEEZE_BREAK_BB_WIDTH_TH and bp > SQUEEZE_BREAK_BB_POS_TH
    except (TypeError, ValueError):
        return False


def _calc_dynamic_trail_pct_v38(atr_pct, session_policy, phase, is_squeeze=False):
    """v38 동적 트레일링 갭 계산 — Squeeze 감지 시 2배 확대

    Args:
        atr_pct: ATR_pct (%)
        session_policy: 시간대 정책 dict
        phase: 보유 단계
        is_squeeze: BB Squeeze Breakout 감지 여부

    Returns:
        trail_pct (양수, 예: 3.5 = peak 대비 3.5% 하락 시 매도)
    """
    if atr_pct is None or atr_pct <= 0:
        base = 3.0
    else:
        base = ATR_TRAIL_K_MULT * atr_pct

    base *= session_policy.get("trail_mult", 1.0)

    phase_mult = {"FRESH": 0.6, "EARLY": 0.7, "MID": 0.9, "MATURE": 1.0}.get(phase, 1.0)
    base *= phase_mult

    # ★ Squeeze Breakout 감지 시 2배 확대
    if is_squeeze:
        base *= SQUEEZE_BREAK_TRAIL_MULT

    return max(ATR_TRAIL_MIN_PCT, min(ATR_TRAIL_MAX_PCT, base))


def get_partial_exit_signal(profit_pct, partial_exit_state):
    """분할 매도 신호 평가 (Laddered Exit)

    Args:
        profit_pct: 현재 수익률 (%)
        partial_exit_state: dict {'tier1_done': bool, 'tier2_done': bool}

    Returns:
        (signal: bool, tier: str, ratio: float, reason: str)
    """
    if not LADDERED_EXIT_ENABLED:
        return False, "", 0.0, ""

    if not partial_exit_state.get("tier1_done") and profit_pct >= LADDERED_TIER1_PROFIT:
        return (True, "TIER1", LADDERED_TIER1_RATIO,
                f"분할익절TIER1({profit_pct:+.2f}%≥{LADDERED_TIER1_PROFIT}%, "
                f"{LADDERED_TIER1_RATIO:.0%})")

    if (partial_exit_state.get("tier1_done") and
        not partial_exit_state.get("tier2_done") and
        profit_pct >= LADDERED_TIER2_PROFIT):
        return (True, "TIER2", LADDERED_TIER2_RATIO,
                f"분할익절TIER2({profit_pct:+.2f}%≥{LADDERED_TIER2_PROFIT}%, "
                f"{LADDERED_TIER2_RATIO:.0%})")

    return False, "", 0.0, ""


# ═══════════════════════════════════════════════════════════════════════
# SECTION 11: Discord 알림 (v35 동일)
# ═══════════════════════════════════════════════════════════════════════

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
    except Exception:
        return False


def send_buy_notification(ticker, signal, buy_amount, total_balance):
    try:
        portfolio = get_enhanced_portfolio_status()
        coin_name = ticker.replace('KRW-', '')
        asset_line = (f"💰 **자산** `총 {portfolio['total_assets']:,.0f}원` | "
                      f"`코인 {portfolio['total_coin_value']:,.0f}원` | "
                      f"`현금 {portfolio['krw_balance']:,.0f}원`")
        bb_w = f" [폭{signal.get('bb_width_pct', 0):.1f}%]"
        # ★ v36: entry_type은 'ema_trend' 단일
        type_tag = "📈"
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
    except Exception:
        pass


def send_sell_notification(ticker, holding_info, signal, profit_amount, holding_duration):
    try:
        portfolio = get_enhanced_portfolio_status()
        coin_name = ticker.replace('KRW-', '')
        emoji = "📈" if signal['profit_pct'] > 0 else "📉"
        asset_line = (f"💰 **자산** `총 {portfolio['total_assets']:,.0f}원` | "
                      f"`코인 {portfolio['total_coin_value']:,.0f}원` | "
                      f"`현금 {portfolio['krw_balance']:,.0f}원`")
        pft_str = format_profit_amount(profit_amount)
        sell_info = (f"{emoji} **{coin_name} 매도완료** `({holding_duration} 보유)`\n"
                     f"├ **거래** `{holding_info['buy_price']:,.0f}원` → `{signal['exit_price']:,.0f}원`\n"
                     f"├ 💵 **{signal['profit_pct']:+.2f}%** `({pft_str})`\n"
                     f"└ **사유:** {signal['reason']}")

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
    except Exception:
        pass


def send_error_notification(error_type, error_details):
    try:
        message = (f"\n**오류 발생**\n\n**유형:** `{error_type}`\n\n"
                   f"**상세 내용:**\n```\n{error_details[:500]}\n```\n\n"
                   f"**시각:** `{datetime.now().strftime('%H:%M:%S')}`\n")
        send_discord_message(message, is_critical=True)
    except Exception:
        pass


# ═══════════════════════════════════════════════════════════════════════
# SECTION 12: 유틸리티 + 리스크 관리 (v35 핵심 유지)
# ═══════════════════════════════════════════════════════════════════════

# 리스크 관리 상수 (v35 동일)
CONSECUTIVE_LOSS_LIMIT = 3
COOLDOWN_AFTER_LOSS = 30
MARKET_BREAKER_THRESHOLD = -3.0


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
                            'value': coin_value, 'profit_pct': profit_pct,
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
                        'buy_reason': hold_info.get('buy_reason', '알 수 없음'),
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
    """★ v36 변경: 등급/Watchlist 관련 정보 제거, EMA 상태 추가"""
    try:
        cur_price = get_current_price(ticker) or 0
        d_change = 0.0

        try:
            url = f"https://api.upbit.com/v1/ticker?markets={ticker}"
            resp = requests.get(url, timeout=3)
            if resp.status_code == 200:
                item = resp.json()[0]
                d_change = item.get('signed_change_rate', 0) * 100
                if cur_price == 0:
                    cur_price = item.get('trade_price', 0)
        except Exception:
            pass

        bb15 = 50.0; bw15 = 0.0; rsi15 = 50.0
        df_15m = get_candles_15m(ticker, count=30)
        if df_15m is not None and len(df_15m) >= 20:
            c = df_15m.iloc[-1]
            bb15 = c.get('bb_position', 50)
            bw15 = c.get('bb_width', 0)
            rsi15 = c.get('rsi', 50)
            if cur_price == 0:
                cur_price = c.get('close', 0)

        # ★ v36 신규: EMA 상태 (있는 경우)
        ema_status = {'ready': False}
        if ema_tracker is not None and ema_tracker.is_ready(ticker):
            ema_status = ema_tracker.get_ema_status(ticker)

        return {
            'cur_price':      cur_price,
            'cur_price_str':  format_price_compact(cur_price) if cur_price > 0 else '-',
            'd_change':       d_change,
            'is_bullish':     d_change >= 0,
            'bb15':           bb15,
            'bw15':           bw15,
            'rsi15':          rsi15,
            'ema_ready':      ema_status.get('ready', False),
            'ema_uptrend':    ema_status.get('uptrend', False),
            'ema_above_50':   ema_status.get('above_ema50', False),
        }
    except Exception:
        return {
            'cur_price': 0, 'cur_price_str': '-',
            'd_change': 0, 'is_bullish': False,
            'bb15': 50, 'bw15': 0, 'rsi15': 50,
            'ema_ready': False, 'ema_uptrend': False, 'ema_above_50': False,
        }


def check_reentry_cooldown(ticker):
    """★ v37 변경: 매도 사유별 차등 쿨다운

    recent_sells[ticker] = {'time': datetime, 'reason': str, 'category': str}
    카테고리별 쿨다운: 익절(30) / 천장(45) / RSI(45) / 트레일(60) / 손절(240) / 추세종료(1440)
    """
    try:
        if ticker not in recent_sells:
            return True, "OK"
        sell_info = recent_sells[ticker]
        sell_time = sell_info.get('time')
        # v36 호환: category 없으면 PROFIT_TAKE로 fallback
        category = sell_info.get('category', 'PROFIT_TAKE')

        if sell_time is None:
            return True, "OK"

        cooldown_min = get_cooldown_for_category(category)
        elapsed = (datetime.now() - sell_time).total_seconds() / 60

        if elapsed < cooldown_min:
            remaining = int(cooldown_min - elapsed)
            return False, f"{category}_쿨다운 {remaining}분 남음 ({cooldown_min}분 정책)"
        return True, "OK"
    except Exception:
        return True, "OK"


def reset_daily_counter():
    """★ v36 변경: 예측기 통계 리셋 코드 제거"""
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
            # ★ v36: PREDICTOR_ENABLED, predictor_stats 리셋 코드 모두 제거
            # ★ v36: buy_engine 일일 카운터 리셋
            if buy_engine is not None:
                buy_engine._reset_daily_count_if_needed()
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
    """★ v36 변경: FIXED_STABLE_COINS 대신 보유 코인 + 후보로 시장 안정성 평가
    보유 코인이 없으면 BTC를 기준으로 시장 안정성 판단"""
    try:
        # v36: 시장 안정성 측정 대상
        targets = list(held_coins.keys())
        if not targets:
            targets = ['KRW-BTC']  # 보유 없으면 BTC 기준

        total_change = 0.0
        valid_count = 0
        for ticker in targets[:5]:   # 최대 5개만
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


# ★ v36에서 폐기된 함수들 (참고용 명시):
# - get_time_based_grade        (등급 시스템 폐기)
# - measure_reference_bbw       (등급 시스템 폐기)
# - update_market_grade         (등급 시스템 폐기)
# - get_grade_params            (등급 시스템 폐기)
# - get_grade_display_str       (등급 시스템 폐기)
# - calculate_dynamic_stop_loss (BBW 동적 손절 폐기, 단일 -5% 사용)
# - get_cached_prediction       (price_predictor 폐기)
# - check_prediction_filter     (price_predictor 폐기)
# - get_sell_prediction_context (price_predictor 폐기)
# - get_predictor_status_str    (price_predictor 폐기)
# ═══════════════════════════════════════════════════════════════════════
# SECTION 13: ★ v36 핵심 — CoinCandidate / MarketWideScreener
#                          EMA4HTracker / EMATrendBuyEngine / TrendSellEngine
# ═══════════════════════════════════════════════════════════════════════

@dataclass
class CoinCandidate:
    """스크리닝 후보 코인"""
    ticker: str
    price: float = 0.0
    change_rate: float = 0.0          # 24h 등락률 (%)
    trade_volume_24h: float = 0.0
    trade_value_24h: float = 0.0      # 24h 거래대금 (KRW)
    score: float = 0.0
    ema_qualified: bool = False
    ema_status: dict = field(default_factory=dict)


# ───────────────────────────────────────────────────────────────────────
# ★ MarketWideScreener — 마켓 와이드 스크리너 (사용자 핵심 지시 #7,8)
# ───────────────────────────────────────────────────────────────────────

class MarketWideScreener:
    """
    업비트 KRW 마켓 200+ 코인 매시 정각 스크리닝.
    
    [동작]
      Tier 1 (5초): GET /v1/ticker 일괄 → 거래대금/등락률 필터 → 200→30개
      Tier 2 (60초): 30개 코인 4H EMA 자격 평가 → 5~8개 최종 후보
    
    [성능]
      매시 정각 1회 약 60초 소요 → 1H봉 갱신과 동기화
    """

    def __init__(self, ema_tracker_ref):
        self.ema_tracker = ema_tracker_ref
        self.exclude_coins: Set[str] = set()
        self._all_markets: List[str] = []
        self._markets_loaded_at: float = 0
        self._last_results: List[CoinCandidate] = []
        self._screening_in_progress: bool = False
        self._lock = threading.Lock()

    def _load_all_krw_markets(self, force: bool = False) -> List[str]:
        """업비트 KRW 마켓 목록 로드 (1일 1회 캐시)"""
        if not force and self._all_markets and (time.time() - self._markets_loaded_at < 86400):
            return self._all_markets
        try:
            resp = requests.get(f"{UPBIT_API_BASE}/v1/market/all",
                                params={"isDetails": "false"}, timeout=10)
            resp.raise_for_status()
            markets = resp.json()
            self._all_markets = [m["market"] for m in markets if m["market"].startswith("KRW-")]
            self._markets_loaded_at = time.time()
            print(f"{Colors.CYAN}[스크리너] KRW 마켓 로드: {len(self._all_markets)}개{Colors.ENDC}")
            return self._all_markets
        except Exception as e:
            if DEBUG_MODE:
                print(f"{Colors.RED}[스크리너] 마켓 목록 로드 실패: {e}{Colors.ENDC}")
            return self._all_markets

    def _fetch_tickers_batch(self, markets: List[str]) -> List[dict]:
        """Ticker API 일괄 조회 (최대 100개씩)"""
        results = []
        BATCH_SIZE = 100
        for i in range(0, len(markets), BATCH_SIZE):
            batch = markets[i:i + BATCH_SIZE]
            try:
                _rate_limit_wait()
                resp = requests.get(
                    f"{UPBIT_API_BASE}/v1/ticker",
                    params={"markets": ",".join(batch)},
                    timeout=10,
                )
                resp.raise_for_status()
                results.extend(resp.json())
            except Exception as e:
                if DEBUG_MODE:
                    print(f"{Colors.YELLOW}[스크리너] Ticker 조회 실패 (배치 {i}): {e}{Colors.ENDC}")
        return results

    def _tier1_fast_filter(self, tickers: List[dict]) -> List[CoinCandidate]:
        """Tier 1: 거래대금/등락률 빠른 필터"""
        candidates = []
        for t in tickers:
            ticker = t.get("market", "")
            if not ticker.startswith("KRW-"):
                continue
            if ticker in self.exclude_coins:
                continue
            if ticker in SCREENING_BLACKLIST:
                continue

            try:
                price = float(t.get("trade_price", 0))
                change_rate = float(t.get("signed_change_rate", 0)) * 100
                trade_value_24h = float(t.get("acc_trade_price_24h", 0))
                trade_volume_24h = float(t.get("acc_trade_volume_24h", 0))
            except (TypeError, ValueError):
                continue

            if trade_value_24h < SCREENING_MIN_TRADING_VALUE_KRW:
                continue
            if change_rate > SCREENING_MAX_CHANGE_PCT or change_rate < SCREENING_MIN_CHANGE_PCT:
                continue
            if price <= 0:
                continue

            candidates.append(CoinCandidate(
                ticker=ticker, price=price, change_rate=change_rate,
                trade_value_24h=trade_value_24h, trade_volume_24h=trade_volume_24h,
            ))

        candidates.sort(key=lambda c: c.trade_value_24h, reverse=True)
        candidates = candidates[:SCREENING_TOP_N_FROM_TIER1]
        print(f"{Colors.CYAN}[스크리너 Tier1] {len(tickers)}개 → {len(candidates)}개 통과{Colors.ENDC}")
        return candidates

    def _tier2_ema_qualification(self, candidates: List[CoinCandidate]) -> List[CoinCandidate]:
        """Tier 2: 4H EMA 자격 평가 (정배열+눌림+EMA10/50 위치)"""
        qualified = []
        for cand in candidates:
            df_4h = get_candles_4h(cand.ticker, count=EMA_4H_HISTORY_COUNT)
            if df_4h is None or len(df_4h) < 60:
                cand.ema_qualified = False
                continue

            success = self.ema_tracker.init_from_df(cand.ticker, df_4h)
            if not success:
                cand.ema_qualified = False
                continue

            status = self.ema_tracker.get_ema_status(cand.ticker)
            uptrend = status.get("uptrend", False)
            above_ema50 = status.get("above_ema50", False)
            above_ema10 = status.get("above_ema10", False)
            pullback = status.get("pullback", False)

            if uptrend and above_ema50 and above_ema10 and pullback:
                cand.ema_qualified = True
                cand.ema_status = status
                qualified.append(cand)
                if DEBUG_MODE:
                    print(f"{Colors.GREEN}  [EMA적격] {cand.ticker} ✅ "
                          f"등락:{cand.change_rate:+.1f}% "
                          f"EMA10/20/50={status['ema10']:,.2f}/"
                          f"{status['ema20']:,.2f}/{status['ema50']:,.2f}{Colors.ENDC}")
            else:
                cand.ema_qualified = False
                cand.ema_status = status
        return qualified

    def _score_candidates(self, candidates: List[CoinCandidate]) -> List[CoinCandidate]:
        """가중 점수 (거래량 35% + 등락률 25% + 거래대금 40%)"""
        if not candidates:
            return []
        n = len(candidates)
        vols = sorted([c.trade_volume_24h for c in candidates], reverse=True)
        changes = sorted([c.change_rate for c in candidates], reverse=True)
        tvals = sorted([c.trade_value_24h for c in candidates], reverse=True)

        for c in candidates:
            score = 0.0
            if c.trade_volume_24h in vols:
                rank = vols.index(c.trade_volume_24h) + 1
                score += SCREENING_WEIGHTS["volume_rank"] * (1 - rank / n)
            if c.change_rate in changes:
                rank = changes.index(c.change_rate) + 1
                score += SCREENING_WEIGHTS["change_rate_rank"] * (1 - rank / n)
            if c.trade_value_24h in tvals:
                rank = tvals.index(c.trade_value_24h) + 1
                score += SCREENING_WEIGHTS["trading_value_rank"] * (1 - rank / n)
            c.score = round(score, 4)

        candidates.sort(key=lambda c: c.score, reverse=True)
        return candidates

    def run_full_screening(self, max_select: int = None) -> List[CoinCandidate]:
        """매시 정각 호출 — 전체 스크리닝 실행"""
        if max_select is None:
            max_select = SCREENING_FINAL_TOP_N

        with self._lock:
            if self._screening_in_progress:
                print(f"{Colors.YELLOW}[스크리너] 진행 중 — 중복 호출 무시{Colors.ENDC}")
                return self._last_results
            self._screening_in_progress = True

        try:
            start_time_local = time.time()
            print(f"{Colors.CYAN}[스크리너] === 전체 스크리닝 시작 ==={Colors.ENDC}")

            markets = self._load_all_krw_markets()
            if not markets:
                return []

            exclude = self.exclude_coins | set(SCREENING_BLACKLIST)
            target_markets = [m for m in markets if m not in exclude]

            tickers = self._fetch_tickers_batch(target_markets)
            if not tickers:
                return []

            tier1 = self._tier1_fast_filter(tickers)
            if not tier1:
                print(f"{Colors.YELLOW}[스크리너] Tier 1 통과 0개{Colors.ENDC}")
                return []

            qualified = self._tier2_ema_qualification(tier1)
            if not qualified:
                print(f"{Colors.YELLOW}[스크리너] Tier 2 (EMA자격) 통과 0개{Colors.ENDC}")
                self._last_results = []
                return []

            scored = self._score_candidates(qualified)
            final = scored[:max_select]

            elapsed = time.time() - start_time_local
            print(f"{Colors.GREEN}[스크리너] === 완료: {len(final)}개 선정 (소요 {elapsed:.1f}초) ==={Colors.ENDC}")
            for i, c in enumerate(final, 1):
                print(f"{Colors.GREEN}  {i}. {c.ticker:<12s} "
                      f"가격:{c.price:>12,.2f} 등락:{c.change_rate:+5.1f}% "
                      f"점수:{c.score:.3f}{Colors.ENDC}")

            self._last_results = final
            return final
        finally:
            with self._lock:
                self._screening_in_progress = False

    def update_exclude_coins(self, held_coins_set: Set[str]):
        self.exclude_coins = held_coins_set

    def get_last_results(self) -> List[CoinCandidate]:
        return list(self._last_results)


# ───────────────────────────────────────────────────────────────────────
# ★ EMA4HTracker — 4시간봉 EMA 추적 (사용자 핵심 지시 #4,5 — v25 벤치마크)
# ───────────────────────────────────────────────────────────────────────

class EMA4HTracker:
    """
    4시간봉 EMA(10/20/50) 추적기.
    trading_system_v25 DailyEMATracker의 코인 4H 버전.
    """

    def __init__(self):
        self._data: Dict[str, dict] = {}
        self._lock = threading.Lock()

    def init_from_df(self, ticker: str, df_4h: pd.DataFrame) -> bool:
        if df_4h is None or len(df_4h) < 60:
            return False
        try:
            closes = df_4h["close"].astype(float).tolist()
            ema10 = self._calc_ema(closes, EMA_4H_SHORT)
            ema20 = self._calc_ema(closes, EMA_4H_MID)
            ema50 = self._calc_ema(closes, EMA_4H_LONG)
            with self._lock:
                self._data[ticker] = {
                    "closes": closes,
                    "ema10": ema10, "ema20": ema20, "ema50": ema50,
                    "ready": True, "current_price": closes[-1],
                    "last_finalize_ts": time.time(),
                }
            return True
        except Exception as e:
            if DEBUG_MODE:
                print(f"{Colors.RED}[EMA4H] {ticker} 초기화 실패: {e}{Colors.ENDC}")
            return False

    def update_current_price(self, ticker: str, price: float):
        with self._lock:
            if ticker in self._data and price > 0:
                self._data[ticker]["current_price"] = price

    def finalize_4h_bar(self, ticker: str, close_price: float):
        """4H봉 확정 시 호출 (스케줄러)"""
        with self._lock:
            if ticker not in self._data:
                return
            d = self._data[ticker]
            d["closes"].append(close_price)
            for period, key in [(EMA_4H_SHORT, "ema10"), (EMA_4H_MID, "ema20"),
                                (EMA_4H_LONG, "ema50")]:
                mult = 2.0 / (period + 1)
                new_ema = (close_price - d[key][-1]) * mult + d[key][-1]
                d[key].append(new_ema)
            if len(d["closes"]) > 300:
                d["closes"] = d["closes"][-300:]
                for key in ["ema10", "ema20", "ema50"]:
                    d[key] = d[key][-300:]
            d["current_price"] = close_price
            d["last_finalize_ts"] = time.time()

    def is_uptrend(self, ticker: str) -> bool:
        with self._lock:
            if ticker not in self._data or not self._data[ticker]["ready"]:
                return False
            d = self._data[ticker]
            return d["ema10"][-1] > d["ema20"][-1] > d["ema50"][-1]

    def had_pullback(self, ticker: str, lookback: int = 5) -> bool:
        with self._lock:
            if ticker not in self._data or not self._data[ticker]["ready"]:
                return False
            d = self._data[ticker]
            if len(d["closes"]) < lookback + 1:
                return False
            for i in range(-lookback - 1, -1):
                if d["closes"][i] < d["ema20"][i]:
                    return True
            return False

    def price_above_ema10(self, ticker: str) -> bool:
        with self._lock:
            if ticker not in self._data or not self._data[ticker]["ready"]:
                return False
            d = self._data[ticker]
            return d["current_price"] > d["ema10"][-1]

    def price_above_ema50(self, ticker: str) -> bool:
        with self._lock:
            if ticker not in self._data or not self._data[ticker]["ready"]:
                return False
            d = self._data[ticker]
            return d["current_price"] > d["ema50"][-1]

    def is_deadcross(self, ticker: str) -> bool:
        with self._lock:
            if ticker not in self._data or not self._data[ticker]["ready"]:
                return False
            d = self._data[ticker]
            return d["ema10"][-1] < d["ema20"][-1]

    def below_ema50_bars(self, ticker: str) -> int:
        with self._lock:
            if ticker not in self._data or not self._data[ticker]["ready"]:
                return 0
            d = self._data[ticker]
            count = 0
            for i in range(-1, -min(20, len(d["closes"]) + 1), -1):
                if d["closes"][i] < d["ema50"][i]:
                    count += 1
                else:
                    break
            return count

    def get_ema_status(self, ticker: str) -> dict:
        with self._lock:
            if ticker not in self._data or not self._data[ticker]["ready"]:
                return {"ready": False}
            d = self._data[ticker]
            uptrend = d["ema10"][-1] > d["ema20"][-1] > d["ema50"][-1]
            pullback = False
            lookback = EMA_PULLBACK_LOOKBACK
            if len(d["closes"]) >= lookback + 1:
                for i in range(-lookback - 1, -1):
                    if d["closes"][i] < d["ema20"][i]:
                        pullback = True
                        break
            return {
                "ready": True,
                "ema10": d["ema10"][-1], "ema20": d["ema20"][-1], "ema50": d["ema50"][-1],
                "current_price": d["current_price"],
                "uptrend": uptrend, "pullback": pullback,
                "above_ema10": d["current_price"] > d["ema10"][-1],
                "above_ema50": d["current_price"] > d["ema50"][-1],
                "deadcross": d["ema10"][-1] < d["ema20"][-1],
            }

    def is_ready(self, ticker: str) -> bool:
        with self._lock:
            return ticker in self._data and self._data[ticker]["ready"]

    def get_tracked_tickers(self) -> List[str]:
        with self._lock:
            return list(self._data.keys())

    @staticmethod
    def _calc_ema(closes: List[float], period: int) -> List[float]:
        if not closes:
            return []
        ema = []
        mult = 2.0 / (period + 1)
        for i, price in enumerate(closes):
            if i == 0:
                ema.append(float(price))
            elif i < period:
                ema.append(float(np.mean(closes[: i + 1])))
            else:
                ema.append((float(price) - ema[-1]) * mult + ema[-1])
        return ema


# ───────────────────────────────────────────────────────────────────────
# ★ EMATrendBuyEngine — EMA 추세 매수 (사용자 핵심 지시 #1,4)
# ───────────────────────────────────────────────────────────────────────

class EMATrendBuyEngine:
    """
    매수 자격 (4H EMA, 스크리너 1차 통과):
      ① EMA 정배열 (10>20>50)
      ② 종가 > EMA50, 종가 > EMA10
      ③ 최근 5봉 중 종가<EMA20 봉 1개 이상 (눌림)
    
    매수 타이밍 (1H봉 실시간):
      ④ BB Position ≤ 30%
      ⑤ RSI: 25 ≤ x ≤ 55
      ⑥ 거래량 ≥ 10봉 평균 × 0.8
      ⑦ 15분봉 3점 체크리스트 (RSI↑+BB↑+양봉) 2/3 이상
    """

    def __init__(self, ema_tracker_ref):
        self.ema_tracker = ema_tracker_ref
        self._watch_list: Dict[str, CoinCandidate] = {}
        self._last_buy_ts: Dict[str, float] = {}
        self._daily_buy_count = 0
        self._daily_buy_count_date = ""
        self._lock = threading.Lock()

    def register_candidates(self, candidates: List[CoinCandidate]):
        with self._lock:
            self._watch_list.clear()
            for c in candidates:
                if c.ema_qualified:
                    self._watch_list[c.ticker] = c
        if self._watch_list:
            print(f"{Colors.GREEN}[매수엔진] 후보 {len(self._watch_list)}개: "
                  f"{', '.join(self._watch_list.keys())}{Colors.ENDC}")
        else:
            print(f"{Colors.YELLOW}[매수엔진] 자격 통과 코인 없음{Colors.ENDC}")

    def _reset_daily_count_if_needed(self):
        today = datetime.now().strftime("%Y-%m-%d")
        if self._daily_buy_count_date != today:
            self._daily_buy_count = 0
            self._daily_buy_count_date = today

    def get_watch_list(self) -> List[str]:
        with self._lock:
            return list(self._watch_list.keys())

    def _check_15m_score(self, ticker: str) -> Tuple[int, str]:
        """15분봉 3점 체크리스트"""
        df_15m = get_candles_15m(ticker, count=10)
        if df_15m is None or len(df_15m) < 3:
            return 3, "15m없음(통과)"

        c = df_15m.iloc[-1]
        p = df_15m.iloc[-2]
        score = 0
        tags = []

        if c["rsi"] > p["rsi"]:
            score += 1
            tags.append(f"RSI↑{c['rsi']:.0f}")
        if c.get("bb_position", 50) > p.get("bb_position", 50):
            score += 1
            tags.append("BB↑")
        if c["close"] >= c["open"]:
            score += 1
            tags.append("양봉")

        return score, f"15m({score}/3:{'+'.join(tags) if tags else '없음'})"

    def check_buy_signal(self, ticker: str) -> dict:
        """매수 신호 평가"""
        base = {
            "signal": False, "reason": "",
            "entry_price": 0.0, "bb_position": 50.0,
            "bb_width_pct": 0.0, "rsi": 50.0,
            "ticker": ticker, "entry_type": "ema_trend",
        }

        # ── 0. 사전 필터 ──
        self._reset_daily_count_if_needed()

        with self._lock:
            if ticker not in self._watch_list:
                base["reason"] = "후보아님"
                return base

        if self._daily_buy_count >= DAILY_BUY_COUNT_LIMIT:
            base["reason"] = f"일일매수한도({self._daily_buy_count}/{DAILY_BUY_COUNT_LIMIT})"
            return base

        # 매수 차단 시간대 (기존 v36 정산기)
        now = datetime.now()
        now_hm = (now.hour, now.minute)
        if BUY_BLOCK_START_HM <= now_hm < BUY_BLOCK_END_HM:
            base["reason"] = f"매수차단시간({BUY_BLOCK_START_HM[0]:02d}:{BUY_BLOCK_START_HM[1]:02d}~)"
            return base

        # ★ v38 NEW: 매수 시간대 게이트 평가
        gate_name, gate_action, gate_params = _get_buy_time_gate(now)

        # BLOCK: 매수 자체 차단
        if gate_action == "BLOCK":
            base["reason"] = (f"v38_매수게이트_{gate_name}_차단"
                              f"({gate_params['start'][0]:02d}:{gate_params['start'][1]:02d}~"
                              f"{gate_params['end'][0]:02d}:{gate_params['end'][1]:02d})")
            return base

        # BONUS/CAUTION에 따른 임계값 조정
        bb_max_position_eff = BUY_BB_MAX_POSITION
        vol_ratio_min_eff = BUY_VOL_RATIO_MIN

        if gate_action == "BONUS":
            # ★ KST 09:30~10:30: BB Position 임계 완화 (폭락 후 반등 진입)
            relax = gate_params.get("bb_position_max_relax", 0)
            bb_max_position_eff = BUY_BB_MAX_POSITION + relax  # 30 → 40
        elif gate_action == "CAUTION":
            # ★ KST 12:00~14:00: 거래량 임계 강화 (저거래량 슬리피지 회피)
            extra = gate_params.get("vol_ratio_min_extra", 0)
            vol_ratio_min_eff = BUY_VOL_RATIO_MIN + extra

        # 재진입 쿨다운 (recent_sells와 통합)
        last_ts = self._last_buy_ts.get(ticker, 0)
        if time.time() - last_ts < REENTRY_COOLDOWN_MIN * 60:
            mins_left = int((REENTRY_COOLDOWN_MIN * 60 - (time.time() - last_ts)) / 60)
            base["reason"] = f"재진입쿨다운({mins_left}분)"
            return base

        # ── 1. EMA 자격 재확인 (실시간) ──
        if not self.ema_tracker.is_uptrend(ticker):
            base["reason"] = "EMA정배열 깨짐"
            return base
        if not self.ema_tracker.price_above_ema50(ticker):
            base["reason"] = "EMA50 하회"
            return base
        if not self.ema_tracker.price_above_ema10(ticker):
            base["reason"] = "EMA10 하회"
            return base

        ema_status = self.ema_tracker.get_ema_status(ticker)

        # ── 2. 1H봉 매수 타이밍 ──
        df_1h = get_candles_1h(ticker, count=50)
        if df_1h is None or len(df_1h) < 25:
            base["reason"] = "1H봉 데이터 부족"
            return base

        c = df_1h.iloc[-1]
        p = df_1h.iloc[-2]

        bb_pos = c.get("bb_position", 50.0)
        rsi = c.get("rsi", 50.0)
        bb_width = c.get("bb_width", 0.0)
        vol_ratio = c.get("vol_ratio", 1.0)
        is_bull = c.get("is_bull", c["close"] >= c["open"])
        rsi_rising = c["rsi"] > p["rsi"]

        base["entry_price"] = float(c["close"])
        base["bb_position"] = bb_pos
        base["bb_width_pct"] = bb_width
        base["rsi"] = rsi

        # 조건 ④: BB Position (★ v38: 시간대 BONUS 시 완화된 임계값 사용)
        if bb_pos > bb_max_position_eff:
            base["reason"] = (f"BB과매도아님(BB={bb_pos:.0f}%>{bb_max_position_eff:.0f}%)"
                              + (f"[{gate_name}_BONUS]" if gate_action == "BONUS" else ""))
            return base

        # 조건 ⑤: RSI 범위
        if rsi > BUY_RSI_MAX:
            base["reason"] = f"RSI높음({rsi:.0f}>{BUY_RSI_MAX:.0f})"
            return base
        if rsi < BUY_RSI_MIN:
            base["reason"] = f"RSI극단과매도({rsi:.0f}<{BUY_RSI_MIN:.0f})"
            return base

        # 조건 ⑥: 거래량 (★ v38: 시간대 CAUTION 시 강화된 임계값 사용)
        if vol_ratio < vol_ratio_min_eff:
            base["reason"] = (f"거래량저조({vol_ratio:.2f}<{vol_ratio_min_eff:.2f})"
                              + (f"[{gate_name}_CAUTION]" if gate_action == "CAUTION" else ""))
            return base

        # 조건 ⑦: 15분봉 3점 체크리스트
        if CONFIRM_15M_ENABLED:
            score_15m, tag_15m = self._check_15m_score(ticker)
            if score_15m < CONFIRM_15M_MIN_SCORE:
                base["reason"] = f"15m체크리스트({score_15m}/3)"
                return base
        else:
            tag_15m = "15m비활성"

        # ── 3. 매수 신호 발화 ──
        # ★ v38: 게이트 컨텍스트 표시
        gate_tag = ""
        if gate_action == "BONUS":
            gate_tag = f" [{gate_name}_BONUS]"
        elif gate_action == "CAUTION":
            gate_tag = f" [{gate_name}_CAUTION]"

        return {
            "signal": True,
            "reason": (f"EMA정배열+BB{bb_pos:.0f}% RSI{rsi:.0f}"
                       f"{'↑' if rsi_rising else '→'} "
                       f"{'양봉' if is_bull else '음봉'} vol{vol_ratio:.1f}x {tag_15m}{gate_tag}"),
            "entry_price": float(c["close"]),
            "bb_position": bb_pos, "bb_width_pct": bb_width, "rsi": rsi,
            "ticker": ticker, "ema_status": ema_status,
            "entry_type": "ema_trend",
            "market_grade": "TREND",   # v36: 등급 시스템 폐기 → 단일 'TREND'
            "buy_gate": gate_name,     # ★ v38 NEW: 매수 게이트 정보
        }

    def record_buy(self, ticker: str):
        with self._lock:
            self._last_buy_ts[ticker] = time.time()
            self._reset_daily_count_if_needed()
            self._daily_buy_count += 1
            self._watch_list.pop(ticker, None)


# ───────────────────────────────────────────────────────────────────────
# ★ TrendSellEngine — 추세 이탈 매도 (사용자 핵심 지시 #2,3 — 시간청산 0건)
# ───────────────────────────────────────────────────────────────────────

class TrendSellEngine:
    """
    [v38 매도 의사결정 체계 — TOKAMAK 사건 학습 반영]

    STEP 1: 시간대 분류 (★ v38: 6 sessions)
      - VOLATILITY_SPIKE_KOREA (09:00~10:00): FRESH 60분, RALLY_GUARD 비활성
      - GLOBAL_PEAK (22:00~02:00): trail 1.3x
      - KOREA_MORNING_LATE (10:00~12:00)
      - LOW_LIQUIDITY (12:00~17:00)
      - EU_RAMP (17:00~22:00)
      - OVERNIGHT_LATE (02:00~09:00)

    STEP 2: 보유 단계 분류 (★ v38: FRESH 유예 시간대별 차등)
      - FRESH  (시간대별 30~60분): 절대손절만
      - EARLY  (~6h):   가속손절 + 2-Bar 손절 + Ratchet Stop
      - MID    (~24h):  + 동적 트레일링 + RSI 반전
      - MATURE (24h+):  + EMA50 하회 + 데드크로스

    STEP 3: 시장 컨텍스트 (★ v38: Squeeze + Spike Bar)
      - BB Squeeze Breakout 감지 → 트레일링 2배 확대
      - 변동성 폭발봉 (Spike Bar) 감지 → 매도 5분 유예

    STEP 4: 손절 트리 (최우선)
      ① 절대 손절 -5% (모든 PHASE, Spike 무시)
      ② BTC 시스템 위기 (FRESH 제외)
      ③ 가속 손절 (EARLY)
      ④ -3% 2-Bar 확정 손절 (EARLY/MID)

    STEP 5: ★ v38 NEW — 분할 매도 (Laddered Exit, 익절 최우선)
      ⑤ TIER1: +2.5% 도달 → 30% 분할 익절
      ⑥ TIER2: +5.0% 도달 → 추가 30% 분할 익절
      → 잔여 40%는 트레일링/Ratchet으로 운영

    STEP 6: ★ v38 NEW — Spike Bar 유예 검사
      - Spike Bar 감지 시 익절류 신호 5분간 미발화

    STEP 7: 익절 트리
      ⑦ ★ v38: Ratchet Stop (RALLY_GUARD 대체)
         - peak +3% → stop +0.5% / peak +5% → +1.5% / peak +8% → +3.5% / peak +12% → +6.5%
         - 한 번 올라가면 절대 내려가지 않음
      ⑧ 단기 천장 다중 신호 합의 (BB+RSI+StochDX+윗꼬리)
      ⑨ RSI 과매수 반전 (시간대별 임계 차등)
      ⑩ 동적 트레일링 (MID/MATURE, ATR 정규화 + Squeeze 보너스)
      ⑪ EMA 추세 종료 (MATURE만)

    STEP 8: 매도 사유 카테고리 + 매도 비율
      - PARTIAL_TAKE (sell_ratio 0.30, 쿨다운 0)
      - RATCHET_STOP (sell_ratio 1.0, 쿨다운 60)
      - STOPLOSS / TREND_END / 기타 (전량 매도)

    ★ 시간 청산 코드 0건 (광현님 핵심 지시 유지)
    ★ 모든 매도 신호에 [세션|단계|ATR|TR|SQUEEZE|SPIKE] 컨텍스트 로깅
    """

    def __init__(self, ema_tracker_ref):
        self.ema_tracker = ema_tracker_ref
        self.targets: Dict[str, dict] = {}
        self._lock = threading.Lock()

    def register(self, ticker: str, buy_price: float, buy_time: float = None,
                 buy_bb_width: float = None):
        """★ v38 변경: buy_bb_width 추가 (Squeeze Breakout 감지용)
                       partial_exit_state, last_spike_time 추가
        """
        if buy_time is None:
            buy_time = time.time()
        with self._lock:
            self.targets[ticker] = {
                "buy_price": buy_price,
                "buy_time": buy_time,
                "peak_price": buy_price,
                "was_overbought": False,
                "sold": False,
                # ★ v38 신규 필드
                "buy_bb_width": buy_bb_width,            # Squeeze Breakout 감지용
                "partial_exit_state": {                   # 분할 매도 상태
                    "tier1_done": False,
                    "tier2_done": False,
                },
                "last_spike_time": 0,                    # 변동성 폭발봉 마지막 시각
            }
        print(f"{Colors.CYAN}[매도등록] {ticker} 매수가:{buy_price:,.2f}"
              f"{f' BBwidth:{buy_bb_width:.1f}%' if buy_bb_width is not None else ''}{Colors.ENDC}")

    def update_buy_price(self, ticker: str, actual_price: float):
        with self._lock:
            if ticker in self.targets and not self.targets[ticker]["sold"]:
                old = self.targets[ticker]["buy_price"]
                self.targets[ticker]["buy_price"] = actual_price
                if old != actual_price:
                    print(f"{Colors.CYAN}[매도] {ticker} 매수가: {old:,.2f}→{actual_price:,.2f}{Colors.ENDC}")

    def remove(self, ticker: str):
        with self._lock:
            self.targets.pop(ticker, None)

    def _check_accel_stop(self, df_5m) -> bool:
        """5분봉 3연속음봉 + RSI<25 가속 손절"""
        if df_5m is None or len(df_5m) < 5:
            return False

        consecutive_bear = 0
        for i in range(-1, -min(ACCEL_STOP_5M_BEAR_COUNT + 1, len(df_5m) + 1), -1):
            if df_5m.iloc[i]["close"] < df_5m.iloc[i]["open"]:
                consecutive_bear += 1
            else:
                break

        if consecutive_bear < ACCEL_STOP_5M_BEAR_COUNT:
            return False

        c = df_5m.iloc[-1]
        p = df_5m.iloc[-2]

        if c.get("rsi", 50) > ACCEL_STOP_RSI_THRESHOLD:
            return False

        if p["close"] > 0:
            drop = (c["close"] - p["close"]) / p["close"] * 100
            if drop > -ACCEL_STOP_DROP_PCT:
                return False

        return True

    def check_sell_signal(self, ticker: str, current_price: float) -> dict:
        """★ v38 매도 신호 평가 — TOKAMAK 사건 교훈 반영

        의사결정 흐름:
          STEP 1: 시간대 분류 (6 sessions, VOLATILITY_SPIKE_KOREA 포함)
          STEP 2: 보유 단계 분류 (FRESH 유예 시간대별 차등)
          STEP 3: 시장 컨텍스트 (ATR + Squeeze + Spike Bar)
          STEP 4: 손절 트리 (최우선, 변경 없음)
          STEP 5: 분할 매도 평가 (★ v38 NEW, 익절 최우선)
          STEP 6: Spike Bar 매도 유예 검사 (★ v38 NEW)
          STEP 7: 익절 트리 (Ratchet Stop / 천장합의 / RSI반전 / 트레일링 / 추세종료)
          STEP 8: 매도 사유 카테고리 + 매도 비율 라벨링
        """
        with self._lock:
            if ticker not in self.targets or self.targets[ticker]["sold"]:
                return {"signal": False, "reason": "감시중아님",
                        "profit_pct": 0, "exit_price": current_price,
                        "bb_position": 50, "bb_width_pct": 0,
                        "sell_category": "NONE", "sell_ratio": 0.0}
            info = dict(self.targets[ticker])

        buy_price = info["buy_price"]
        buy_time = info["buy_time"]

        if buy_price <= 0 or current_price <= 0:
            return {"signal": False, "reason": "가격오류",
                    "profit_pct": 0, "exit_price": current_price,
                    "bb_position": 50, "bb_width_pct": 0,
                    "sell_category": "NONE", "sell_ratio": 0.0}

        profit_pct = (current_price - buy_price) / buy_price * 100

        # peak 갱신
        if current_price > info["peak_price"]:
            with self._lock:
                if ticker in self.targets:
                    self.targets[ticker]["peak_price"] = current_price
                    info["peak_price"] = current_price

        peak_pnl = (info["peak_price"] - buy_price) / buy_price * 100 if buy_price > 0 else 0
        drawdown = (info["peak_price"] - current_price) / info["peak_price"] * 100 if info["peak_price"] > 0 else 0

        elapsed_sec = time.time() - buy_time
        elapsed_hours = elapsed_sec / 3600

        # ════════════════════════════════════════════════════════════
        # STEP 1: 시간대 분류 (v38: 6 sessions)
        # ════════════════════════════════════════════════════════════
        session_name, session_policy = _classify_kst_session()

        # ATR 계산용 15분봉
        df_15m_for_atr = get_candles_15m(ticker, count=ATR_PERIOD + 5)
        atr_pct = _calc_atr_pct(df_15m_for_atr, period=ATR_PERIOD)

        # 1H봉 BB 위치
        df_1h_for_bb = get_candles_1h(ticker, count=3)
        bb_pos_1h = 50.0
        bb_width_1h = 0.0
        if df_1h_for_bb is not None and len(df_1h_for_bb) >= 1:
            bb_pos_1h = df_1h_for_bb.iloc[-1].get('bb_position', 50)
            bb_width_1h = df_1h_for_bb.iloc[-1].get('bb_width', 0)

        # ════════════════════════════════════════════════════════════
        # STEP 2: 보유 단계 분류 (★ v38: FRESH 유예 시간대별 차등)
        # ════════════════════════════════════════════════════════════
        fresh_grace_min = session_policy.get("fresh_grace_min", 30)
        phase = _classify_holding_phase(elapsed_hours, fresh_grace_min=fresh_grace_min)

        # ════════════════════════════════════════════════════════════
        # STEP 3: 시장 컨텍스트 (Squeeze + Spike Bar)
        # ════════════════════════════════════════════════════════════
        # Squeeze Breakout 감지
        buy_bb_width = info.get("buy_bb_width")
        is_squeeze = _check_squeeze_breakout(buy_bb_width, bb_pos_1h)

        # 동적 트레일링 갭 (Squeeze 시 2배 확대)
        dynamic_trail = _calc_dynamic_trail_pct_v38(atr_pct, session_policy, phase, is_squeeze)

        # Spike Bar 감지 (시간대 정책에서 활성화된 경우만)
        is_spike_bar = False
        spike_bar_range = 0.0
        if session_policy.get("spike_bar_protect", False):
            is_spike_bar, spike_bar_range = _check_spike_bar(df_15m_for_atr, atr_pct)
            # Spike Bar 발견 시 시각 기록 (10분 이상 지난 새 spike만)
            if is_spike_bar:
                last_spike_time_existing = info.get("last_spike_time", 0)
                if time.time() - last_spike_time_existing > 600:
                    with self._lock:
                        if ticker in self.targets:
                            self.targets[ticker]["last_spike_time"] = time.time()
                            info["last_spike_time"] = time.time()

        # spike grace 활성 여부 (마지막 spike로부터 5분 이내)
        last_spike = info.get("last_spike_time", 0)
        in_spike_grace = (time.time() - last_spike) < SPIKE_BAR_DELAY_SEC if last_spike > 0 else False

        # 컨텍스트 문자열
        ctx_parts = [session_name, phase]
        if atr_pct is not None:
            ctx_parts.append(f"ATR{atr_pct:.2f}%")
            ctx_parts.append(f"TR{dynamic_trail:.1f}%")
        if is_squeeze:
            ctx_parts.append("SQUEEZE")
        if is_spike_bar:
            ctx_parts.append(f"SPIKE{spike_bar_range:.1f}%")
        ctx_str = "[" + "|".join(ctx_parts) + "]"

        base = {
            "signal": False,
            "reason": f"홀딩({profit_pct:+.2f}%,고점{peak_pnl:+.1f}%) {ctx_str}",
            "profit_pct": round(profit_pct, 3),
            "peak_pnl_pct": round(peak_pnl, 3),
            "drawdown_pct": round(drawdown, 3),
            "elapsed_hours": round(elapsed_hours, 2),
            "ticker": ticker,
            "exit_price": current_price,
            "bb_position": bb_pos_1h,
            "bb_width_pct": bb_width_1h,
            "session": session_name,
            "phase": phase,
            "atr_pct": atr_pct,
            "dynamic_trail_pct": round(dynamic_trail, 2),
            "is_squeeze": is_squeeze,
            "is_spike_bar": is_spike_bar,
            "sell_category": "NONE",
            "sell_ratio": 1.0,  # 기본 100% 매도 (분할 매도 시 0.30/0.30로 override)
        }

        # ════════════════════════════════════════════════════════════
        # STEP 4: 손절 트리 (최우선)
        # ════════════════════════════════════════════════════════════

        # ── 4-1. 절대 손절 -5% (모든 PHASE, Spike Bar 무시) ──
        if profit_pct <= ABSOLUTE_STOP_LOSS_PCT:
            return {**base, "signal": True, "sell_ratio": 1.0,
                    "reason": f"절대손절({profit_pct:+.2f}%≤{ABSOLUTE_STOP_LOSS_PCT}%) {ctx_str}",
                    "sell_category": "STOPLOSS"}

        # ── 4-2. BTC 시스템 리스크 (FRESH 제외) ──
        if phase != "FRESH":
            is_btc_crash, btc_reason = _check_btc_system_risk()
            if is_btc_crash:
                return {**base, "signal": True, "sell_ratio": 1.0,
                        "reason": f"BTC시스템위기_{btc_reason}({profit_pct:+.2f}%) {ctx_str}",
                        "sell_category": "BTC_CRASH"}

        # ── 4-3. FRESH: 안정화 유예 (시간대별 차등 적용됨) ──
        if phase == "FRESH":
            return base

        # ── 4-4. 가속 손절 (EARLY) ──
        if phase == "EARLY" and profit_pct < 0:
            df_5m = get_candles_5m(ticker, count=10)
            if self._check_accel_stop(df_5m):
                return {**base, "signal": True, "sell_ratio": 1.0,
                        "reason": f"가속손절({profit_pct:+.2f}%) {ctx_str}",
                        "sell_category": "STOPLOSS"}

        # ── 4-5. -3% 2-Bar 확정 손절 ──
        if phase in ("EARLY", "MID") and profit_pct <= TWO_BAR_CONFIRM_LOSS_PCT:
            df_5m_2bar = get_candles_5m(ticker, count=5)
            if _check_two_bar_stoploss(df_5m_2bar, buy_price, TWO_BAR_CONFIRM_LOSS_PCT):
                return {**base, "signal": True, "sell_ratio": 1.0,
                        "reason": f"2Bar확정손절({profit_pct:+.2f}%) {ctx_str}",
                        "sell_category": "STOPLOSS"}

        # ════════════════════════════════════════════════════════════
        # STEP 5: ★ v38 NEW — 분할 매도 (Laddered Exit) — 익절 최우선
        # ════════════════════════════════════════════════════════════
        partial_state = info.get("partial_exit_state",
                                  {"tier1_done": False, "tier2_done": False})
        p_signal, p_tier, p_ratio, p_reason = get_partial_exit_signal(profit_pct, partial_state)
        if p_signal:
            return {**base, "signal": True, "sell_ratio": p_ratio,
                    "reason": f"{p_reason} {ctx_str}",
                    "sell_category": "PARTIAL_TAKE",
                    "partial_tier": p_tier}

        # ════════════════════════════════════════════════════════════
        # STEP 6: ★ v38 NEW — Spike Bar grace 검사
        # (Spike Bar에서는 익절류 신호 발화 안 함, 단 손절은 위에서 이미 처리됨)
        # ════════════════════════════════════════════════════════════

        # ════════════════════════════════════════════════════════════
        # STEP 7: 익절 트리
        # ════════════════════════════════════════════════════════════

        # ── 7-1. ★ v38: Ratchet Stop (RALLY_GUARD 대체) — Spike grace 중 미발화 ──
        if not in_spike_grace and phase in ("EARLY", "MID", "MATURE"):
            ratchet_stop_pnl = _calc_ratchet_stop_pnl(peak_pnl)
            if ratchet_stop_pnl is not None and profit_pct <= ratchet_stop_pnl:
                return {**base, "signal": True, "sell_ratio": 1.0,
                        "reason": (f"래칫스탑(고점{peak_pnl:+.1f}%→stop{ratchet_stop_pnl:+.1f}%, "
                                   f"현재{profit_pct:+.2f}%) {ctx_str}"),
                        "sell_category": "RATCHET_STOP"}

        # ── 7-2. 단기 천장 다중 신호 합의 (Spike grace 중 미발화) ──
        if not in_spike_grace and profit_pct >= TOP_SIGNAL_MIN_PROFIT:
            is_top, agree_cnt, top_tags = _check_short_term_top_signal(ticker, profit_pct)
            if is_top:
                tag_str = "+".join(top_tags) if top_tags else f"{agree_cnt}signals"
                return {**base, "signal": True, "sell_ratio": 1.0,
                        "reason": f"단기천장합의({tag_str},{profit_pct:+.2f}%) {ctx_str}",
                        "sell_category": "TOP_SIGNAL"}

        # ── 7-3. RSI 과매수 반전 (시간대별 임계값) ──
        rsi_exit_th = session_policy.get("rsi_exit_th", RSI_OVERBOUGHT_EXIT)
        if profit_pct >= RSI_EXIT_MIN_PROFIT:
            df_1h = get_candles_1h(ticker, count=5)
            if df_1h is not None and len(df_1h) >= 2:
                rsi_1h = float(df_1h.iloc[-1].get("rsi", 50))
                if rsi_1h > rsi_exit_th:
                    with self._lock:
                        if ticker in self.targets:
                            self.targets[ticker]["was_overbought"] = True

                if info.get("was_overbought") and rsi_1h < RSI_OVERBOUGHT_COOL:
                    with self._lock:
                        if ticker in self.targets:
                            self.targets[ticker]["was_overbought"] = False
                    if not in_spike_grace:
                        return {**base, "signal": True, "sell_ratio": 1.0,
                                "reason": f"RSI과매수반전(RSI{rsi_1h:.0f}↓,{profit_pct:+.2f}%) {ctx_str}",
                                "sell_category": "RSI_REVERT"}

        # ── 7-4. ★ v38: 동적 트레일링 (MID/MATURE, Spike grace 중 미발화) ──
        if phase in ("MID", "MATURE") and peak_pnl >= 2.0 and not in_spike_grace:
            if drawdown >= dynamic_trail:
                return {**base, "signal": True, "sell_ratio": 1.0,
                        "reason": (f"동적트레일(고점{peak_pnl:+.1f}%→{profit_pct:+.1f}% "
                                   f"낙{drawdown:.1f}%≥{dynamic_trail:.1f}%) {ctx_str}"),
                        "sell_category": "TRAILING"}

        # ── 7-5. EMA 추세 종료 (MATURE만) ──
        if phase == "MATURE":
            below50_bars = self.ema_tracker.below_ema50_bars(ticker)
            if below50_bars >= EMA_TREND_BREAK_BARS:
                return {**base, "signal": True, "sell_ratio": 1.0,
                        "reason": (f"추세종료_EMA50하회{below50_bars}봉"
                                   f"({profit_pct:+.2f}%,{elapsed_hours:.1f}h)"),
                        "sell_category": "TREND_END"}

            if elapsed_hours >= DEADCROSS_MIN_HOLD_HOURS and self.ema_tracker.is_deadcross(ticker):
                return {**base, "signal": True, "sell_ratio": 1.0,
                        "reason": (f"데드크로스_EMA10<20"
                                   f"({profit_pct:+.2f}%,{elapsed_hours:.1f}h)"),
                        "sell_category": "TREND_END"}

        return base

    def mark_partial_done(self, ticker: str, tier: str):
        """★ v38 NEW: 분할 매도 완료 표시 (execute_sell에서 호출)

        Args:
            ticker: 코인 티커
            tier: 'TIER1' 또는 'TIER2'
        """
        with self._lock:
            if ticker in self.targets:
                state = self.targets[ticker].setdefault(
                    "partial_exit_state", {"tier1_done": False, "tier2_done": False}
                )
                if tier == "TIER1":
                    state["tier1_done"] = True
                elif tier == "TIER2":
                    state["tier2_done"] = True
                print(f"{Colors.CYAN}[분할매도] {ticker} {tier} 완료 표시{Colors.ENDC}")

    def get_active_count(self) -> int:
        with self._lock:
            return sum(1 for t in self.targets.values() if not t["sold"])

    def get_target_info(self, ticker: str) -> Optional[dict]:
        with self._lock:
            if ticker in self.targets:
                return dict(self.targets[ticker])
            return None
# ═══════════════════════════════════════════════════════════════════════
# SECTION 14: 거래소 동기화 (v35 + v36 매도엔진/EMA트래커 등록)
# ═══════════════════════════════════════════════════════════════════════

def sync_held_coins_with_exchange():
    """★ v36 변경: 등록 후 sell_engine + ema_tracker에 자동 이관"""
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
    # ★ v36: FIXED_STABLE_COINS 폐기 → 5,000원 이상 모든 코인 관리 대상
    # 사용자가 가진 모든 코인을 v36 매도엔진에 등록하여 추세 매도 적용

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
            skipped_coins.append(f"{currency}(가격조회실패)")
            continue

        # ★ v36: 5,000원 미만은 의미 없는 잔여 → 스킵
        if coin_value < 5000:
            skipped_coins.append(f"{currency}({coin_value:,.0f}원)")
            continue

        # 모든 5,000원 이상 코인은 v36에서 관리 (managed=True)
        is_managed = True

        profit_pct = ((current_price - avg_price) / avg_price * 100) if (current_price and avg_price > 0) else 0.0
        peak_price = max(avg_price, current_price) if current_price else avg_price

        # ★ v36: buy_time을 1시간 전으로 설정 (D+0 그레이스 시간을 우회)
        buy_time = datetime.now() - timedelta(hours=1)

        with held_coins_lock:
            held_coins[ticker] = {
                'buy_price': avg_price,
                'buy_time': buy_time,
                'buy_amount': total_balance * avg_price,
                'peak_price': peak_price,
                'peak_time': datetime.now(),
                'buy_reason': f'동기화 ({price_source})',
                'ticker': ticker,
                'buy_order': 1,
                'managed': is_managed,
                'market_grade': 'TREND',          # v36: 단일 등급
                'param_snapshot': {},              # v36: 등급 시스템 폐기
                'synced': True,
                'entry_type': 'sync',
                'was_overbought': False,
            }

        # ★ v36 핵심: 매도엔진 + EMA 트래커 자동 등록
        if sell_engine is not None:
            sell_engine.register(ticker, avg_price, buy_time.timestamp())

        if ema_tracker is not None and not ema_tracker.is_ready(ticker):
            df_4h = get_candles_4h(ticker, count=EMA_4H_HISTORY_COUNT)
            if df_4h is not None:
                ema_tracker.init_from_df(ticker, df_4h)
                if DEBUG_MODE:
                    print(f"{Colors.CYAN}  [EMA4H 로드] {ticker}{Colors.ENDC}")

        price_str = f"{current_price:,.0f}원" if current_price else "조회불가"
        synced_coins.append({
            'ticker': ticker, 'currency': currency,
            'balance': total_balance, 'avg_price': avg_price,
            'cur_price': current_price or 0, 'coin_value': coin_value,
            'profit_pct': profit_pct, 'managed': is_managed,
            'price_source': price_source,
        })
        profit_sign = "+" if profit_pct >= 0 else ""
        print(f"  ✅ {currency}: {total_balance:.6f}개 "
              f"@ {avg_price:,.0f}원 [{price_source}]"
              f" → 현재 {price_str} ({profit_sign}{profit_pct:.2f}%)")

    print(f"\n{Colors.GREEN}[Init] 동기화 완료: {len(synced_coins)}개 등록"
          f" | {len(skipped_coins)}개 스킵{Colors.ENDC}")
    if skipped_coins:
        print(f"{Colors.YELLOW}  스킵: {', '.join(skipped_coins)}{Colors.ENDC}")

    _send_sync_discord_report(synced_coins, skipped_coins, unmanaged_coins)

    # ★ v36: 스크리너에 보유 코인 알림 (제외 처리용)
    if screener is not None:
        screener.update_exclude_coins(set(held_coins.keys()))

    return True


def _send_sync_discord_report(synced_coins, skipped_coins, unmanaged_coins):
    try:
        krw_balance = upbit.get_balance("KRW") or 0.0
        total_coin_value = sum(c['coin_value'] for c in synced_coins)
        total_assets = krw_balance + total_coin_value
        can_buy = krw_balance >= 5000
        coin_lines = ""
        for c in synced_coins:
            pft = c['profit_pct']
            coin_lines += (f"\n  ✅ **{c['currency']}** "
                           f"`{c['balance']:.4f}개` @ `{c['avg_price']:,.0f}원`"
                           f" → `{c['cur_price']:,.0f}원` **{pft:+.2f}%**")
        buy_status = f"✅ 매수 가능 (`{krw_balance:,.0f}원`)" if can_buy else f"🚫 매수 불가"
        msg = (f"\n⚙️ **v36 보유 코인 동기화 완료**\n\n💰 **자산 현황**\n"
               f"├ 총자산: `{total_assets:,.0f}원`\n├ 코인: `{total_coin_value:,.0f}원`\n"
               f"├ 현금: `{krw_balance:,.0f}원`\n└ 매수상태: {buy_status}\n")
        if coin_lines:
            msg += f"\n📦 **동기화 코인 ({len(synced_coins)}개)**{coin_lines}\n"
        msg += f"\n⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
        send_discord_message(msg)
    except Exception:
        pass


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
        print(f"  📊 v36 초기 자산 현황")
        print(f"{'━'*55}{Colors.ENDC}")
        print(f"  총 자산:    {total_assets:>15,.0f} 원")
        print(f"  코인 평가:  {total_coin_value:>15,.0f} 원")
        print(f"  현금(KRW): {krw_balance:>15,.0f} 원")
        print(f"  보유 코인:  {len(held_snapshot):>15} 개 / 최대 {MAX_HOLDINGS}")

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
    except Exception:
        traceback.print_exc()


# ═══════════════════════════════════════════════════════════════════════
# SECTION 15: 거래 실행 (v35 + v36 매도엔진 자동 등록/제거)
# ═══════════════════════════════════════════════════════════════════════

def execute_buy(ticker, signal):
    """★ v36 변경: 매수 후 sell_engine.register(), buy_engine.record_buy() 자동 호출"""
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

            if krw_balance < MIN_BUY_AMOUNT_KRW:
                return False

            total_assets = get_total_balance() or krw_balance

            # 1차/2차 분할 매수
            if current_holding_count == 0:
                buy_amount = krw_balance * FIRST_BUY_RATIO * BUY_FEE_BUFFER
                buy_order_num = 1
            else:
                buy_amount = krw_balance * BUY_FEE_BUFFER
                buy_order_num = 2

            if buy_amount < MIN_BUY_AMOUNT_KRW:
                return False

            coin_name = ticker.replace('KRW-', '')
            print(f"{Colors.CYAN}[Buy Info] {buy_order_num}차 {coin_name} | {buy_amount:,.0f}원{Colors.ENDC}")

            actual_buy_price = signal['entry_price']

            if TEST_MODE:
                print(f"{Colors.GREEN}[TEST] {coin_name} {buy_amount:,.0f}원 시뮬레이션{Colors.ENDC}")
            else:
                # LIVE MODE
                try:
                    final_krw = upbit.get_balance("KRW")
                    if final_krw is None or final_krw < buy_amount:
                        if final_krw and final_krw >= MIN_BUY_AMOUNT_KRW:
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
                except Exception as e:
                    print(f"{Colors.RED}[Buy Failed] {e}{Colors.ENDC}")
                    send_error_notification("Buy Failed", str(e))
                    return False

            # held_coins 등록
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
                    'order_uuid': result.get('uuid', '') if not TEST_MODE else '',
                    'managed': True,
                    'market_grade': 'TREND',          # v36: 단일 등급
                    'param_snapshot': {},
                    'entry_type': signal.get('entry_type', 'ema_trend'),
                    'was_overbought': False,
                }

            # ★ v36: 매도엔진 + 매수엔진 카운터 자동 갱신
            # ★ v38: signal에서 buy_bb_width 추출하여 전달 (Squeeze Breakout 감지용)
            if sell_engine is not None:
                buy_bb_width_val = signal.get('bb_width_pct')  # 매수 시점 1H BB Width
                sell_engine.register(ticker, actual_buy_price, time.time(),
                                     buy_bb_width=buy_bb_width_val)
            if buy_engine is not None:
                buy_engine.record_buy(ticker)
            if screener is not None:
                screener.update_exclude_coins(set(held_coins.keys()))

            daily_trade_count += 1
            daily_buy_count += 1
            total_trades += 1
            print(f"{Colors.GREEN}[Buy Success] {coin_name} @ {actual_buy_price:,.0f}원{Colors.ENDC}")
            send_buy_notification(ticker, signal, buy_amount, total_assets)
            return True

    except Exception as e:
        print(f"{Colors.RED}[Buy Error] {e}{Colors.ENDC}")
        traceback.print_exc()
        return False


def execute_sell(ticker, signal):
    """★ v38 변경: 분할 매도(PARTIAL_TAKE) 지원
       - sell_ratio < 1.0이면 보유량의 일부만 매도, held_coins/sell_engine 유지
       - sell_ratio == 1.0이면 기존 v37 동작 (전량 매도)
    """
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
            hold_duration = format_duration(datetime.now() - buy_time)
            coin_name = ticker.replace('KRW-', '')

            # ★ v38: 매도 비율 (분할 매도 시 0.30 등, 전량 매도 시 1.0)
            sell_ratio = float(signal.get('sell_ratio', 1.0))
            sell_ratio = max(0.0, min(1.0, sell_ratio))
            is_partial = (sell_ratio < 1.0 and signal.get('sell_category') == 'PARTIAL_TAKE')
            partial_tier = signal.get('partial_tier', '')

            profit_amount = hold_info['buy_amount'] * sell_ratio * (profit_pct / 100)

            actual_profit_pct = profit_pct
            actual_profit_amount = profit_amount

            if TEST_MODE:
                tag = f"분할({partial_tier})" if is_partial else "전량"
                print(f"{Colors.GREEN}[TEST] {coin_name} 매도 시뮬 ({tag}, {sell_ratio*100:.0f}%): "
                      f"{profit_pct:+.2f}%{Colors.ENDC}")
            else:
                # LIVE MODE
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
                        if sell_engine is not None:
                            sell_engine.remove(ticker)
                        send_discord_message(f"\n⚠️ **{coin_name} 수동매도 추정** → 자동제거\n")
                        return False

                    coin_amount_total = float(coin_balance.get('balance', 0))
                    if coin_amount_total <= 0:
                        with held_coins_lock:
                            if ticker in held_coins:
                                del held_coins[ticker]
                        if sell_engine is not None:
                            sell_engine.remove(ticker)
                        return False

                    # ★ v38: 분할 매도 시 보유량의 일부만 매도
                    coin_amount_to_sell = coin_amount_total * sell_ratio
                    if coin_amount_to_sell <= 0:
                        return False

                    result = upbit.sell_market_order(ticker, coin_amount_to_sell)
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
                    # ★ v38: 분할 매도 시 매도 비율만큼 손익 계산
                    actual_profit_amount = hold_info['buy_amount'] * sell_ratio * (actual_profit_pct / 100)
                    signal['profit_pct'] = actual_profit_pct
                    signal['exit_price'] = actual_sell_price

                except Exception as e:
                    error_str = str(e)
                    print(f"{Colors.RED}[Sell Failed] {coin_name}: {error_str}{Colors.ENDC}")
                    if 'insufficient' in error_str.lower() or 'balance' in error_str.lower():
                        with held_coins_lock:
                            if ticker in held_coins:
                                del held_coins[ticker]
                        if sell_engine is not None:
                            sell_engine.remove(ticker)
                    send_error_notification("Sell Failed", error_str)
                    return False

            # ════════════════════════════════════════════════════════════
            # ★ v38: 분할 매도 vs 전량 매도 분기 처리
            # ════════════════════════════════════════════════════════════
            if is_partial:
                # ── 분할 매도: held_coins/sell_engine 유지, 잔여 보유량 갱신 ──
                with held_coins_lock:
                    if ticker in held_coins:
                        # buy_amount를 매도 비율만큼 차감
                        held_coins[ticker]['buy_amount'] *= (1.0 - sell_ratio)
                        # ★ 중요: buy_price는 그대로 유지 (잔여분의 평균 매수가는 변하지 않음)

                # sell_engine의 분할 매도 상태 마킹
                if sell_engine is not None:
                    sell_engine.mark_partial_done(ticker, partial_tier)

                # recent_sells에는 기록하지 않음 (재진입 쿨다운 0이므로 무의미)
                # 단, 통계 업데이트는 진행
                with statistics_lock:
                    total_profit += actual_profit_pct * sell_ratio  # 가중 손익 누적
                    if actual_profit_pct > 0:
                        # 분할 익절은 항상 "수익 매도"
                        daily_winning_trades += 1

                daily_trade_count += 1
                daily_sell_count += 1
                tag = f"PARTIAL_{partial_tier}"
                print(f"{Colors.GREEN}[{tag}] {coin_name} {sell_ratio*100:.0f}% 분할익절 "
                      f"({actual_profit_pct:+.2f}%, 잔여 {(1-sell_ratio)*100:.0f}% 보유){Colors.ENDC}")
                send_sell_notification(ticker, hold_info, signal, actual_profit_amount, hold_duration)
                return True
            else:
                # ── 전량 매도 (기존 v37 동작) ──
                with held_coins_lock:
                    if ticker in held_coins:
                        del held_coins[ticker]
                # ★ v37: 매도 사유 카테고리 추가
                recent_sells[ticker] = {
                    'time': datetime.now(),
                    'reason': signal['reason'],
                    'category': signal.get('sell_category', 'PROFIT_TAKE'),
                }

                if sell_engine is not None:
                    sell_engine.remove(ticker)
                if screener is not None:
                    screener.update_exclude_coins(set(held_coins.keys()))

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
                send_sell_notification(ticker, hold_info, signal, actual_profit_amount, hold_duration)
                return True

    except Exception as e:
        print(f"{Colors.RED}[Sell Error] {e}{Colors.ENDC}")
        traceback.print_exc()
        return False


# ═══════════════════════════════════════════════════════════════════════
# SECTION 16: 매수 스레드 (★ v36 — 후보 코인 순회, 예측기 호출 0)
# ═══════════════════════════════════════════════════════════════════════

def buy_thread_worker():
    """★ v36 핵심: 스크리너 후보 → buy_engine.check_buy_signal → execute_buy
    
    v35 대비 변경:
      - 고정 4코인 순회 → buy_engine 후보 순회
      - check_prediction_filter() 호출 제거 (예측기 폐기)
      - update_market_grade() 호출 제거 (등급 시스템 폐기)
      - run_sharp_drop_scanner / run_trend_momentum_scanner 호출 제거
        (메인 스케줄러가 매시 정각 통합 스크리닝)
      - TME 분기 제거 (단일 트랙)
    """
    print(f"{Colors.GREEN}[Thread 1] v36 매수 스레드 시작 ({BUY_THREAD_INTERVAL}초 주기){Colors.ENDC}")
    print(f"{Colors.GREEN}  ├ 마켓와이드 스크리너: 매시 정각 200+ 코인 평가{Colors.ENDC}")
    print(f"{Colors.GREEN}  ├ EMA 추세 매수: 4H EMA 정배열 + 1H BB과매도{Colors.ENDC}")
    print(f"{Colors.GREEN}  ├ 15분봉 3점 체크리스트{Colors.ENDC}")
    print(f"{Colors.GREEN}  └ 가격 예측기 폐기 (v36){Colors.ENDC}")

    iteration = 0
    last_no_cash_log = 0

    while not stop_event.is_set():
        try:
            iteration += 1

            # ──── 사전 체크 ────
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

            if krw_balance_now < MIN_BUY_AMOUNT_KRW:
                if DEBUG_MODE and iteration % 6 == 0:
                    print(f"{Colors.YELLOW}[BUY] 🚫 매수불가 — 현금 {krw_balance_now:,.0f}원{Colors.ENDC}")
                now_ts = time.time()
                if now_ts - last_no_cash_log >= 600:
                    last_no_cash_log = now_ts
                    with held_coins_lock:
                        num_held = len(held_coins)
                    _send_no_cash_discord_alert(krw_balance_now, num_held, managed_count)
                time.sleep(BUY_SLEEP_WHEN_FULL)
                continue

            # ── 매수 차단 시간대 ──
            now = datetime.now()
            now_hm = (now.hour, now.minute)
            if BUY_BLOCK_START_HM <= now_hm < BUY_BLOCK_END_HM:
                if DEBUG_MODE and iteration % 30 == 0:
                    print(f"{Colors.YELLOW}[BUY] 매수 차단 시간대{Colors.ENDC}")
                time.sleep(BUY_THREAD_INTERVAL)
                continue

            # ── 리스크 체크 ──
            can_trade, _ = check_consecutive_losses()
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

            # ──── 후보 코인 순회 ────
            if buy_engine is None:
                time.sleep(BUY_THREAD_INTERVAL)
                continue

            watch_list = buy_engine.get_watch_list()
            if not watch_list:
                if DEBUG_MODE and iteration % 6 == 0:
                    print(f"{Colors.YELLOW}[BUY] 후보 코인 없음 — 다음 스크리닝 대기{Colors.ENDC}")
                time.sleep(BUY_THREAD_INTERVAL)
                continue

            if DEBUG_MODE and iteration % 6 == 0:
                daily_count = buy_engine._daily_buy_count
                print(f"{Colors.MAGENTA}[BUY] KRW:{krw_balance_now:,.0f}원 | "
                      f"후보:{len(watch_list)}종 | "
                      f"오늘매수:{daily_count}/{DAILY_BUY_COUNT_LIMIT}건{Colors.ENDC}")

            for ticker in watch_list:
                if stop_event.is_set():
                    return

                with held_coins_lock:
                    if ticker in held_coins:
                        continue

                # 매수 신호 평가 (★ v36 — 예측기 호출 없음)
                sig = buy_engine.check_buy_signal(ticker)

                if sig['signal']:
                    coin_name = ticker.replace('KRW-', '')

                    print(f"\n{Colors.CYAN}{'='*55}")
                    print(f"[BUY SIGNAL] 📈 {coin_name} EMA추세 매수!")
                    print(f"{'='*55}{Colors.ENDC}")
                    print(f"  📊 BB: {sig['bb_position']:.1f}%")
                    print(f"  💰 진입가: {sig['entry_price']:,.0f}원")
                    print(f"  📝 사유: {sig['reason']}")
                    print(f"{Colors.CYAN}{'='*55}{Colors.ENDC}\n")

                    success = execute_buy(ticker, sig)
                    if success:
                        print(f"{Colors.GREEN}[BUY] {coin_name} 매수 완료!{Colors.ENDC}")
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

    print(f"{Colors.GREEN}[Thread 1] v36 매수 스레드 종료{Colors.ENDC}")


def _send_no_cash_discord_alert(krw_balance, num_held, managed_count):
    try:
        msg = (f"\n🚫 **현금 부족 알림**\n"
               f"├ 현금: `{krw_balance:,.0f}원` (최소 5만원)\n"
               f"├ 보유: `{num_held}개` (관리 `{managed_count}/{MAX_HOLDINGS}`)\n"
               f"└ 매수 스캔 자동 차단 중\n\n"
               f"⏰ {datetime.now().strftime('%H:%M:%S')}\n")
        send_discord_message(msg)
    except Exception:
        pass


# ═══════════════════════════════════════════════════════════════════════
# SECTION 17: 매도 스레드 (★ v36 — TrendSellEngine 단일 진입점)
# ═══════════════════════════════════════════════════════════════════════

def sell_thread_worker():
    """★ v36 핵심: TrendSellEngine.check_sell_signal → execute_sell
    
    v35 대비 변경:
      - sell_signal(df, buy_price, ...) 호출 → sell_engine.check_sell_signal(ticker, price)
      - 시간 청산 사전 체크 코드 모두 제거 (사용자 핵심 지시 #2,3)
      - 등급 파라미터 가져오기 제거
      - peak_price 갱신 → sell_engine 내부에서 처리
    """
    print(f"{Colors.YELLOW}[Thread 2] v38 매도 스레드 시작 ({SELL_THREAD_INTERVAL}초 주기){Colors.ENDC}")
    print(f"{Colors.YELLOW}  ├ Sell-Side Specialist (8단계 + 분할매도 + Ratchet){Colors.ENDC}")
    print(f"{Colors.YELLOW}  ├ D+0 안전장치: 가속손절 + 당일-3% + 절대-5%{Colors.ENDC}")
    print(f"{Colors.YELLOW}  └ 시간 청산 0건 (사용자 핵심 지시 #2,3){Colors.ENDC}")

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

                # 현재가 조회
                current_price = get_current_price(ticker)
                if not current_price or current_price <= 0:
                    continue

                # held_info 가져오기
                with held_coins_lock:
                    if ticker not in held_coins:
                        continue
                    held_info = held_coins[ticker].copy()
                    buy_price = held_info['buy_price']
                    buy_time = held_info.get('buy_time')

                # ★ v36: TrendSellEngine 단일 진입점
                if sell_engine is None:
                    continue

                # 매도 엔진에 등록되어 있지 않으면 자동 등록 (안전장치)
                target_info = sell_engine.get_target_info(ticker)
                if target_info is None:
                    buy_time_ts = buy_time.timestamp() if isinstance(buy_time, datetime) else time.time() - 3600
                    sell_engine.register(ticker, buy_price, buy_time_ts)

                sig = sell_engine.check_sell_signal(ticker, current_price)

                if sig['signal']:
                    profit_pct = sig['profit_pct']
                    coin_name = ticker.replace('KRW-', '')
                    color = Colors.GREEN if profit_pct >= 0 else Colors.RED
                    emoji = "📈" if profit_pct >= 0 else "📉"

                    print(f"\n{color}{'='*55}")
                    print(f"[SELL SIGNAL] {coin_name} 매도!")
                    print(f"{'='*55}{Colors.ENDC}")
                    print(f"  {emoji} 수익률: {profit_pct:+.2f}%")
                    print(f"  💰 매도가: {sig['exit_price']:,.0f}원")
                    print(f"  🔍 사유: {sig['reason']}")
                    if buy_time:
                        if isinstance(buy_time, datetime):
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

    print(f"{Colors.YELLOW}[Thread 2] v38 매도 스레드 종료{Colors.ENDC}")
# ═══════════════════════════════════════════════════════════════════════
# SECTION 18: 정시 통계 리포트 (★ v36 — 등급/예측기 표시 제거, EMA 추가)
# ═══════════════════════════════════════════════════════════════════════

def send_enhanced_statistics_report():
    """★ v36 변경: 시장 등급, 예측기, watchlist 모든 코드 제거. EMA 상태 추가"""
    try:
        portfolio = get_enhanced_portfolio_status()
        now = datetime.now()

        # 코인 평균 수익률
        cpft = 0.0
        if portfolio['coins']:
            tb = sum(c.get('buy_price', 0) * c.get('balance', 0)
                     for c in portfolio['coins'] if c.get('buy_price', 0) > 0)
            if tb > 0:
                cpft = ((portfolio['total_coin_value'] - tb) / tb) * 100

        header = (
            f"⏰ **{now.strftime('%H:%M')}** v36 정시보고\n"
            f"💰 `{portfolio['total_assets']:,.0f}원` "
            f"(코인`{portfolio['total_coin_value']:,.0f}`{cpft:+.1f}% "
            f"현금`{portfolio['krw_balance']:,.0f}`)"
        )

        # ★ v36: 시장 점수 — 보유 코인 + 후보 코인 평균
        all_targets = list(set(list(held_coins.keys()) + 
                               (buy_engine.get_watch_list() if buy_engine else [])))
        if not all_targets:
            all_targets = ['KRW-BTC']  # 기본 BTC

        coin_changes = {}
        coin_is_bullish = {}
        ema_qualified_count = 0

        for tk in all_targets[:10]:   # 최대 10개
            try:
                df_d = get_candles_4h(tk, count=2)   # ★ v36: 일봉 → 4H봉
                if df_d is None or len(df_d) < 1:
                    continue
                d = df_d.iloc[-1]
                if d['open'] <= 0:
                    continue
                chg = (d['close'] - d['open']) / d['open'] * 100
                coin_changes[tk] = chg
                coin_is_bullish[tk] = d['close'] >= d['open']

                if ema_tracker is not None and ema_tracker.is_uptrend(tk):
                    ema_qualified_count += 1
            except Exception:
                continue

        daily_avg = sum(coin_changes.values()) / len(coin_changes) if coin_changes else 0
        pos_count = sum(1 for v in coin_is_bullish.values() if v)

        mkt_section = (
            f"\n\n🌡️ **시장** 평균`{daily_avg:+.1f}%` "
            f"양봉`{pos_count}/{len(coin_changes)}` "
            f"EMA추세코인`{ema_qualified_count}개`"
        )

        # 보유 코인 섹션
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
                        if bt and isinstance(bt, datetime):
                            dur = format_duration(datetime.now() - bt)
                        pk = held_coins[tk].get('peak_price', cur_p)
                        if pk and pk > 0 and cur_p > 0:
                            peak_drop = ((cur_p - pk) / pk) * 100

                pe = "📈" if pft >= 0 else "📉"
                pk_str = f"피크{peak_drop:+.1f}%" if peak_drop < -0.1 else "피크유지"

                # ★ v36: EMA 상태 표시
                ema_tag = ""
                if ema_tracker is not None and ema_tracker.is_ready(tk):
                    es = ema_tracker.get_ema_status(tk)
                    ut = "↗" if es.get('uptrend') else "↘"
                    e50 = "↑" if es.get('above_ema50') else "↓"
                    ema_tag = f"EMA{ut}50{e50}"

                hold_section += (
                    f"\n┌ **{cn}** `{price_str}` "
                    f"{pe}`{pft:+.2f}%({pft_str})` ⏱{dur}"
                )
                hold_section += (
                    f"\n└ `{ema_tag} {pk_str} 손절{ABSOLUTE_STOP_LOSS_PCT:.1f}%`"
                )
        else:
            hold_section = f"\n\n📦 보유 `0/{MAX_HOLDINGS}` (대기중)"

        # ★ v36: 후보 코인 섹션 (버즈 워치리스트 대체)
        candidate_section = ""
        if buy_engine is not None:
            watch = buy_engine.get_watch_list()
            held_set = set(held_coins.keys())
            watch = [t for t in watch if t not in held_set]

            if watch:
                candidate_section = f"\n\n📋 **EMA자격 후보 {len(watch)}개**"
                for tk in watch[:5]:
                    cn = tk.replace('KRW-', '')
                    cur_p = get_current_price(tk) or 0
                    chg = coin_changes.get(tk, 0.0)

                    # 1H BB/RSI
                    bb_str = "-"
                    rsi_str = "-"
                    df_1h = get_candles_1h(tk, count=2)
                    if df_1h is not None and len(df_1h) >= 1:
                        bb_str = f"BB{df_1h.iloc[-1].get('bb_position', 50):.0f}"
                        rsi_str = f"R{df_1h.iloc[-1].get('rsi', 50):.0f}"

                    candidate_section += (
                        f"\n  🟢 `{cn:<5s} {format_price_compact(cur_p):>8} "
                        f"{chg:+.1f}% {bb_str} {rsi_str}`"
                    )

        msg = f"\n{'─'*25}\n{header}{mkt_section}{hold_section}{candidate_section}\n{'─'*25}"
        send_discord_message(msg)

    except Exception as e:
        if DEBUG_MODE:
            print(f"{Colors.RED}[Report Error] {e}{Colors.ENDC}")
            traceback.print_exc()


# ═══════════════════════════════════════════════════════════════════════
# SECTION 19: 모니터 스레드 (★ v36 — 매시 정각 스크리닝 통합)
# ═══════════════════════════════════════════════════════════════════════

def monitor_thread_worker():
    """★ v36 핵심: 매시 정각에 마켓 와이드 스크리닝 자동 수행
    
    v35 대비 변경:
      - get_grade_display_str(), get_predictor_status_str() 호출 제거
      - calculate_dynamic_stop_loss 호출 제거
      - 매시 정각에 screener.run_full_screening() 자동 실행 신규 추가
    """
    print(f"{Colors.MAGENTA}[Thread 3] v36 모니터 스레드 시작 ({MONITOR_THREAD_INTERVAL}초 주기){Colors.ENDC}")
    print(f"{Colors.MAGENTA}  └ 매시 정각: 마켓 와이드 스크리닝 자동 실행{Colors.ENDC}")

    iteration = 0
    last_report_time = datetime.now() - timedelta(hours=1)
    last_screening_hour = -1   # 마지막 스크리닝 시간 (정각 1회 보장)

    while not stop_event.is_set():
        try:
            iteration += 1
            current_time = datetime.now()

            # ──── 매시 정각 스크리닝 ────
            if (current_time.minute < 5 and current_time.hour != last_screening_hour
                    and screener is not None and buy_engine is not None):
                last_screening_hour = current_time.hour
                print(f"{Colors.MAGENTA}[Monitor] 매시 정각 스크리닝 실행 ({current_time.strftime('%H:%M')}){Colors.ENDC}")

                # 보유 코인 제외 갱신
                screener.update_exclude_coins(set(held_coins.keys()))
                # 스크리닝 실행
                results = screener.run_full_screening()
                # 매수엔진에 후보 등록
                buy_engine.register_candidates(results)
                # WS 재구독 (후보 변경 반영)
                if results:
                    reconnect_websocket()

            with held_coins_lock:
                current_holdings = len(held_coins)
            with statistics_lock:
                win_rate = (winning_trades / total_trades * 100) if total_trades > 0 else 0

            print(f"\n{Colors.MAGENTA}{'='*10}")
            print(f"[Monitor] #{iteration} | {current_time.strftime('%H:%M:%S')}")
            print(f"  보유: {current_holdings}/{MAX_HOLDINGS} | "
                  f"거래: {total_trades}회 (금일 {daily_trade_count}회) | "
                  f"승률: {win_rate:.1f}%")

            # ★ v36: 5분봉 빌더 + 4H EMA 트래커 상태
            with ws_candles_5m_lock:
                _5m_ready = sum(1 for v in ws_candles_5m.values() if v.get('indicators_ready'))
                _5m_total = len(ws_candles_5m)
            ema_count = len(ema_tracker.get_tracked_tickers()) if ema_tracker else 0
            print(f"  5m빌더: {_5m_ready}/{_5m_total}코인 | "
                  f"EMA4H 추적: {ema_count}코인 | "
                  f"매수후보: {buy_engine.get_watch_list() if buy_engine else []}")

            with held_coins_lock:
                for ticker, info in held_coins.items():
                    try:
                        price = get_current_price(ticker)
                        if price:
                            profit = ((price - info['buy_price']) / info['buy_price']) * 100
                            duration = format_duration(current_time - info['buy_time']) if isinstance(info.get('buy_time'), datetime) else "-"
                            coin_name = ticker.replace("KRW-", "")
                            ema_tag = ""
                            if ema_tracker and ema_tracker.is_ready(ticker):
                                es = ema_tracker.get_ema_status(ticker)
                                ema_tag = " [EMA정배열]" if es.get('uptrend') else " [EMA추세이탈]"
                            print(f"  - {coin_name}: {profit:+.2f}% ({duration}){ema_tag}")
                    except Exception:
                        pass

            print(f"{'='*10}{Colors.ENDC}\n")

            # 정시 디스코드 보고 (매시 정각)
            elapsed = (current_time - last_report_time).total_seconds()
            if elapsed >= 3540 and 0 <= current_time.minute <= 3:
                print(f"{Colors.GREEN}[Monitor] 정시 디스코드 보고{Colors.ENDC}")
                send_enhanced_statistics_report()
                last_report_time = current_time

            time.sleep(MONITOR_THREAD_INTERVAL)

        except Exception as e:
            print(f"{Colors.RED}[Monitor Error] {e}{Colors.ENDC}")
            time.sleep(MONITOR_THREAD_INTERVAL)

    print(f"{Colors.MAGENTA}[Thread 3] v36 모니터 종료{Colors.ENDC}")


# ═══════════════════════════════════════════════════════════════════════
# SECTION 20: 메인 함수 (★ v36 — 인스턴스 생성 + 초기 스크리닝)
# ═══════════════════════════════════════════════════════════════════════

def main():
    """★ v36 핵심: 4개 신규 인스턴스 생성 → 동기화 → 초기 스크리닝 → 스레드 시작"""
    global upbit, ema_tracker, screener, buy_engine, sell_engine

    print(_STARTUP_BANNER)

    # ── 1. API 초기화 ──
    try:
        upbit = UpbitAPI(ACCESS_KEY, SECRET_KEY)
        print(f"{Colors.GREEN}[Init] Upbit API 연결 완료{Colors.ENDC}\n")
    except Exception as e:
        print(f"{Colors.RED}[Error] API 연결 실패: {e}{Colors.ENDC}")
        return

    # ── 2. ★ v36 핵심: 신규 인스턴스 4개 생성 ──
    print(f"{Colors.CYAN}[Init] v36 핵심 인스턴스 생성...{Colors.ENDC}")
    ema_tracker = EMA4HTracker()
    screener = MarketWideScreener(ema_tracker)
    buy_engine = EMATrendBuyEngine(ema_tracker)
    sell_engine = TrendSellEngine(ema_tracker)
    print(f"{Colors.GREEN}[Init] EMA4HTracker / MarketWideScreener / "
          f"EMATrendBuyEngine / TrendSellEngine ✅{Colors.ENDC}\n")

    # ── 3. 보유 코인 동기화 (sell_engine + ema_tracker 자동 등록) ──
    print(f"{Colors.CYAN}[Init] 기존 보유 코인 동기화 중...{Colors.ENDC}")
    sync_success = sync_held_coins_with_exchange()
    if not sync_success:
        print(f"{Colors.YELLOW}[Warning] 동기화 실패 - 계속 진행{Colors.ENDC}\n")

    # ── 4. 5분봉 빌더 REST 초기화 (보유 코인 우선) ──
    print(f"{Colors.CYAN}[Init] 5분봉 빌더 REST 초기화 중...{Colors.ENDC}")
    init_count = 0
    init_targets = list(held_coins.keys()) + ALWAYS_MONITOR
    init_targets = list(set(init_targets))
    if not init_targets:
        # 보유 없으면 BTC 하나만 초기화 (시장 안정성 측정용)
        init_targets = ['KRW-BTC']

    for ticker in init_targets:
        if _init_ws_candle_from_rest(ticker):
            init_count += 1
            if DEBUG_MODE:
                print(f"  ✅ {ticker.replace('KRW-', '')} 5분봉 {WS_CANDLE_HISTORY_SIZE}개 로드")
        else:
            print(f"  ❌ {ticker.replace('KRW-', '')} 5분봉 초기화 실패 (REST 폴백 사용)")
        time.sleep(0.2)
    print(f"{Colors.GREEN}[Init] 5분봉 빌더 초기화 완료 ({init_count}/{len(init_targets)}){Colors.ENDC}\n")

    # ── 5. 초기 자산 보고 ──
    send_startup_asset_report()

    with held_coins_lock:
        synced_coins = len(held_coins)

    try:
        init_krw = upbit.get_balance("KRW") or 0.0
    except Exception:
        init_krw = 0.0
    can_buy_now = init_krw >= MIN_BUY_AMOUNT_KRW

    # ── 6. ★ v36 핵심: 초기 스크리닝 (매시 정각 대기 안 함) ──
    print(f"{Colors.CYAN}[Init] 마켓 와이드 초기 스크리닝...{Colors.ENDC}")
    try:
        initial_candidates = screener.run_full_screening()
        if initial_candidates:
            buy_engine.register_candidates(initial_candidates)
        else:
            print(f"{Colors.YELLOW}[Init] 초기 스크리닝 통과 코인 0개 (다음 정각 재시도){Colors.ENDC}")
    except Exception as e:
        print(f"{Colors.RED}[Init] 초기 스크리닝 실패: {e}{Colors.ENDC}")
        if DEBUG_MODE:
            traceback.print_exc()

    # ── 7. WebSocket 시작 ──
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

    # ── 8. Discord 시작 알림 ──
    buy_mode_str = (
        f"✅ 매수 활성 (`{init_krw:,.0f}원`)"
        if can_buy_now
        else f"🚫 매수 차단 (`{init_krw:,.0f}원` < {MIN_BUY_AMOUNT_KRW:,}원)"
    )
    candidate_count = len(buy_engine.get_watch_list()) if buy_engine else 0
    start_msg = (
        f"\n**🚀 v36 봇 시작** `{VERSION}`\n\n"
        f"**모드:** `{'TEST MODE' if TEST_MODE else 'LIVE MODE'}`\n"
        f"**최대 보유:** `{MAX_HOLDINGS}개`\n"
        f"**동기화 코인:** `{synced_coins}개`\n"
        f"**매수 후보:** `{candidate_count}개` (마켓 와이드 스크리닝)\n"
        f"**5분봉 빌더:** `{init_count}/{len(init_targets)}개 준비`\n"
        f"**현금 상태:** {buy_mode_str}\n"
        f"**WebSocket:** `{'✅ 연결됨' if ws_ok else '⏳ 연결 중'}`\n\n"
        f"**v36 핵심 변경:**\n"
        f"├ ✅ 시간 청산 완전 제거\n"
        f"├ ✅ price_predictor 폐기\n"
        f"├ ✅ 마켓 와이드 스크리너 (200+ 코인)\n"
        f"├ ✅ 4H EMA 추세 매수\n"
        f"└ ✅ 추세 이탈 5조건 매도\n\n"
        f"⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
    )
    send_discord_message(start_msg)

    # ── 9. 스레드 시작 ──
    buy_t = threading.Thread(target=buy_thread_worker, name="Buy", daemon=True)
    sell_t = threading.Thread(target=sell_thread_worker, name="Sell", daemon=True)
    monitor_t = threading.Thread(target=monitor_thread_worker, name="Monitor", daemon=True)

    buy_t.start()
    time.sleep(1)
    sell_t.start()
    time.sleep(1)
    monitor_t.start()

    print(f"{Colors.GREEN}[Main] 모든 v36 스레드 시작 완료 (Thread 1~4){Colors.ENDC}\n")

    # ── 10. 메인 루프 ──
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
            f"\n**🛑 v36 봇 종료**\n\n"
            f"**가동 시간:** `{runtime}`\n"
            f"**총 거래:** `{total_trades}회`\n"
            f"**승:** `{winning_trades}` | **패:** `{losing_trades}`\n"
            f"**승률:** `{final_wr:.1f}%`\n"
            f"**WS 재연결:** `{ws_stat['reconnect_count']}회`\n\n"
            f"⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
        )
        send_discord_message(end_msg)
        print(f"{Colors.GREEN}[Exit] 모든 스레드 종료 완료{Colors.ENDC}")


# ═══════════════════════════════════════════════════════════════════════
# SECTION 21: 프로그램 진입점
# ═══════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        error_trace = traceback.format_exc()
        print(f"{Colors.RED}[Fatal Error] {error_trace}{Colors.ENDC}")
