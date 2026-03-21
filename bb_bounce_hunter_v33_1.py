#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
BB Bounce Hunter v33.1 — Price Predictor v5.1 연동
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
v33.0 기반 + 가격예측 모듈 연동 (매수 필터)
 
★ 적용 방법:
  1. SECTION 2 파라미터: v31의 77~333행을 아래 파라미터 전체로 교체
  2. 신규 함수: 지정된 위치에 삽입
  3. 수정 함수: 기존 함수를 아래 함수로 교체
  4. 삭제 대상: 명시된 함수/파라미터 제거
 
★ v32.0 핵심 개선 (3코인 7일 실증데이터 기반):
  [매수]
  1. BBW 최소값 강화 (0.8→1.0%): BBW<1.0 구간 반등 불가 실증 확인
  2. 시간대별 전략 분기: 오후→적극, 저녁→표준, 새벽→BB<25한정, 오전→보수적
  3. 5분봉 확인 3점 체크리스트: RSI↑+BB↑+양봉 중 2/3 필수
  4. 볼륨 필터 의무화: vol_ratio > 1.0 필수
  5. 보유기간 확장: 8~16시간 스윗스팟 (기존 2.5시간→최대 16시간)
 
  [매도]
  6. ★★★ 탄력 트레일링 시스템: 1.0%→0.3%T / 1.5%→0.5%T / 2%→0.7%T / 3%→1.0%T
  7. 동적 목표수익률: BBW 연동 (BBW<1.5→0.8% / 1.5~3%→1.2% / 3%+→1.5%)
  8. 시간 제한 완화: 16시간 후+수익>0→청산, 24시간→무조건 청산
  9. 기존 강제익절 2.5% → 탄력 트레일로 대체 (큰 수익 포착)
 
실증 근거:
  - 보유기간 8h: 1%승률 56%, 2%승률 27%
  - 보유기간 12h: 1%승률 65%, 2%승률 40%
  - 1.5%고정: 총수익 +80.4% / 탄력트레일: 총수익 +58.4% + 2%+달성 4건
  - 오후진입→8h보유: 1%승률 88.6%
  - 새벽진입→16h보유: 1%승률 54.8%
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

# ★ v33.1: 가격 예측 모듈 연동
try:
    from price_predictor_v5_1 import get_prediction as _raw_get_prediction
    PREDICTOR_AVAILABLE = True
    print(f"\033[92m[Init] 가격 예측 모듈 v5.1 로드 완료\033[0m")
except ImportError:
    PREDICTOR_AVAILABLE = False
    _raw_get_prediction = None
    print(f"\033[93m[Init] 가격 예측 모듈 미설치 — 예측 필터 비활성\033[0m")


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
VERSION = "33.1 BB_BOUNCE_HUNTER"
 
# 거래 대상 (고정 7개)
FIXED_STABLE_COINS = [
    "KRW-ETH", "KRW-XRP", "KRW-SOL"
    # "KRW-ADA", "KRW-LINK", "KRW-BCH", "KRW-SUI"
]
 
# 포지션 관리
MAX_HOLDINGS = 2
FIRST_BUY_RATIO = 0.5
BUY_FEE_BUFFER = 0.995
MIN_BUY_PRICE = 500
MAX_DAILY_TRADES = 999
 
# ============================================================================
# ★ 시장 등급별 파라미터 테이블 (v32.0: 매도 탄력트레일 반영)
# ============================================================================
MARKET_GRADE_PARAMS = {
    'HIGH': {
        'BUY_BB_MAX':            35,
        'BUY_BB_WIDTH_MIN':     1.5,     # v32: 1.5→1.5 유지
        'SELL_SAFE_PROFIT':     1.0,     # v32: 1.2→1.0 (탄력트레일이 대체)
        'SELL_SAFE_BB_MIN':      70,
        'SELL_TRAIL_ACTIVATION': 1.0,    # v32: 1.5→1.0 (탄력트레일 활성 기준)
        'SELL_TRAIL_DISTANCE':   0.3,    # v32: 0.8→0.3 (Phase2 초기)
        'SELL_FORCE_PROFIT':     5.0,    # v32: 2.5→5.0 (긴급 안전밸브만)
        'BUY_MIN_HOLD_SEC':      120,
        'STOP_LOSS_FLOOR':      -3.5,
        'STOP_LOSS_CEIL':       -5.0,
        'STOP_LOSS_BBW_MULT':    0.8,
    },
    'MID': {
        'BUY_BB_MAX':            30,
        'BUY_BB_WIDTH_MIN':     1.0,     # v32: 1.0 유지
        'SELL_SAFE_PROFIT':     1.0,     # v32: 1.2→1.0
        'SELL_SAFE_BB_MIN':      68,
        'SELL_TRAIL_ACTIVATION': 1.0,    # v32: 1.2→1.0
        'SELL_TRAIL_DISTANCE':   0.3,    # v32: 0.6→0.3
        'SELL_FORCE_PROFIT':     5.0,    # v32: 2.5→5.0
        'BUY_MIN_HOLD_SEC':      180,
        'STOP_LOSS_FLOOR':      -3.0,
        'STOP_LOSS_CEIL':       -4.5,
        'STOP_LOSS_BBW_MULT':    0.8,
    },
    'LOW': {
        'BUY_BB_MAX':            25,
        'BUY_BB_WIDTH_MIN':     1.0,     # v32: 0.8→1.0 (LOW도 최소 1.0% 요구)
        'SELL_SAFE_PROFIT':     0.8,     # v32: 1.0→0.8 (LOW는 목표 낮춤)
        'SELL_SAFE_BB_MIN':      65,
        'SELL_TRAIL_ACTIVATION': 0.8,    # v32: 1.0→0.8
        'SELL_TRAIL_DISTANCE':   0.3,    # v32: 0.5→0.3
        'SELL_FORCE_PROFIT':     4.0,    # v32: 2.0→4.0
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
 
# ── 캐시 TTL (초) ──
CACHE_TTL_CANDLE = 30
CACHE_TTL_DAILY = 300
 
# ── 매수 파라미터 (MID 등급 기본값 — 폴백용) ──
BUY_BB_MAX = 30
BUY_BB_WIDTH_MIN = 1.0               # v32: 유지
BUY_BOUNCE_MIN_15M = 2
BUY_BOUNCE_MIN_5M = 2
BUY_BOUNCE_TOTAL_MIN = 5
BUY_MIN_HOLD_SEC = 180
 
# ── 매도 파라미터 (MID 등급 기본값 — 폴백용) ──
SELL_FORCE_PROFIT = 5.0               # v32: 2.5→5.0 (탄력트레일이 주 매도)
SELL_SAFE_PROFIT = 1.0                # v32: 1.2→1.0
SELL_SAFE_BB_MIN = 68
SELL_TRAIL_ACTIVATION = 1.0           # v32: 1.2→1.0
SELL_TRAIL_DISTANCE = 0.3             # v32: 0.6→0.3
STOP_LOSS_FLOOR = -3.0
STOP_LOSS_CEIL = -4.5
STOP_LOSS_BBW_MULT = 0.8
 
# ── v32.0 신규: 탄력 트레일링 파라미터 ────────────────────────────────────
# 수익 구간별 트레일 간격 (고점 대비 하락 허용폭)
ELASTIC_TRAIL_TIERS = [
    # (수익률 기준, 트레일 간격)  — 수익이 클수록 여유있게
    (3.0, -1.0),    # 3%+ 수익 → 고점 대비 -1.0%에서 매도
    (2.0, -0.7),    # 2%+ 수익 → 고점 대비 -0.7%
    (1.5, -0.5),    # 1.5%+ 수익 → 고점 대비 -0.5%
    (1.0, -0.3),    # 1.0%+ 수익 → 고점 대비 -0.3% (안전 모드)
]
ELASTIC_TRAIL_ACTIVATE = 1.0          # 트레일링 활성화 최소 수익률
 
# ── v32.0 신규: 시간 기반 청산 ────────────────────────────────────────────
HOLD_PROFIT_EXIT_HOURS = 16           # 16시간 후 + 수익>0 → 시장가 청산
HOLD_MAX_EXIT_HOURS = 24              # 24시간 → 무조건 청산
 
# ── v32.0 신규: 동적 목표수익률 (BBW 연동) ────────────────────────────────
# BBW 구간별 안전익절 기준 (sell_signal에서 사용)
DYNAMIC_TARGET_BY_BBW = [
    # (BBW 하한, BBW 상한, 안전익절 기준)
    (0.0, 1.5, 0.8),     # 극저변동성 → 0.8% 목표
    (1.5, 3.0, 1.2),     # 표준 변동성 → 1.2% 목표
    (3.0, 99.0, 1.5),    # 고변동성 → 1.5% 목표
]
 
# ── 변경: 시간대별 공격도 파라미터 (v33: 새벽 적극, 낮 보수적) ──
# 사용자 전략: 새벽 = 적극 매수, 낮 = 확실한 시그널만
TIMEZONE_AGGRESSION = {
    'dawn':      {'start':  0, 'end':  6, 'bb_adjust': +5, 'score_adjust': -1, 'label': '새벽적극'},
    'morning':   {'start':  6, 'end':  9, 'bb_adjust': -5, 'score_adjust': +1, 'label': '오전방어'},
    'daytime':   {'start':  9, 'end': 15, 'bb_adjust': -5, 'score_adjust': +2, 'label': '낮보수적'},
    'afternoon': {'start': 15, 'end': 18, 'bb_adjust':  0, 'score_adjust': +1, 'label': '오후표준'},
    'evening':   {'start': 18, 'end': 22, 'bb_adjust':  0, 'score_adjust':  0, 'label': '저녁표준'},
    'night':     {'start': 22, 'end': 24, 'bb_adjust': +3, 'score_adjust':  0, 'label': '야간적극'},
}
 
# ── v32.0 신규: 5분봉 3점 체크리스트 ──────────────────────────────────────
CONFIRM_5M_MIN_SCORE = 2              # 3점 중 2점 이상 필수
CONFIRM_5M_ENABLED = True             # 5분봉 확인 활성화

# ── v33.0 신규: 일봉 양봉/음봉에 따른 동적 보정 ──
# 당일 양봉 → 시장 우호적 → 매수 조건 완화
# 당일 음봉 → 시장 비우호적 → 매수 조건 강화 (확실한 시그널만)
DAILY_CANDLE_AGGRESSION = {
    'strong_bull': {'threshold': +2.0, 'bb_adjust': +5, 'score_adjust': -1, 'label': '강한양봉'},
    'bull':        {'threshold':  0.0, 'bb_adjust': +3, 'score_adjust':  0, 'label': '양봉'},
    'weak_bear':   {'threshold': -2.0, 'bb_adjust':  0, 'score_adjust': +1, 'label': '약한음봉'},
    'bear':        {'threshold': -99,  'bb_adjust': -5, 'score_adjust': +2, 'label': '강한음봉'},
}

# ── 가속 손절 파라미터 (v26.0 유지) ──
ACCEL_STOP_CONSECUTIVE_BEAR = 3
ACCEL_STOP_RSI_THRESHOLD = 25
ACCEL_STOP_DROP_PCT = 1.0
 
# ── 크래시 리커버리 파라미터 (유지) ──
CRASH_LOOKBACK_BARS_15M = 6
CRASH_DROP_THRESHOLD = -5.0
CRASH_RECOVERY_RISE_BARS = 3
CRASH_RECOVERY_RSI_FROM = 20
CRASH_RECOVERY_RSI_TO = 35
CRASH_RECOVERY_VOLUME_MULT = 1.5
CRASH_RECOVERY_MIN_RISE = 1.5
 
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
 
# ── 5분봉 빌더 설정 (유지) ──
WS_CANDLE_HISTORY_SIZE = 40
WS_CANDLE_MIN_FOR_INDICATOR = 22
 
# ── 급락 스캐너 파라미터 (유지) ──
PLUNGE_STAGE1_THRESHOLD  = 4.5
PLUNGE_WATCH_WINDOW_MIN  = 120
PLUNGE_SNAPSHOT_INTERVAL = 900
PLUNGE_MAX_RECOVERY_PCT  = 2.0
 
# 코인별 급락 임계값 (유지)
COIN_DROP_THRESHOLDS = {
    'KRW-XRP':  {'cum4': -2.0, 'daily': -4.5},
    'KRW-SOL':  {'cum4': -2.0, 'daily': -5.0},
    'KRW-ADA':  {'cum4': -2.0, 'daily': -5.0},
    'KRW-ETH':  {'cum4': -2.0, 'daily': -4.5},
    'KRW-LINK': {'cum4': -2.0, 'daily': -4.5},
    'KRW-BCH':  {'cum4': -2.0, 'daily': -4.5},
    'KRW-SUI':  {'cum4': -2.5, 'daily': -5.5},
}
 
# ── 추세 모멘텀 진입 (TME) 파라미터 (유지) ──
TREND_BULL_SCORE_MIN     = 0.52
TREND_BB_POS_MIN         = 22
TREND_BB_POS_MAX         = 58
TREND_RSI_MIN            = 42
TREND_RSI_MAX            = 72
TREND_BBW_MIN            = 1.0       # v32: 0.8→1.0 (통일)
TREND_SCORE_MIN          = 3
TREND_WATCH_WINDOW_MIN   = 45
TREND_SNAPSHOT_INTERVAL  = 900
TREND_MAX_ADVANCE_PCT    = 3.0
TREND_ACCEL_STOP_RSI     = 40
 
# ── ★ v32.0: 직접 스캔 진입 파라미터 (v31 기반 + 강화) ──────────────────
# Tier-A: 고승률 경로 (BB 하단 깊은 진입)
DIRECT_TIER_A_BB_MAX   = 25
DIRECT_TIER_A_RSI_MAX  = 45
DIRECT_TIER_A_RSI_MIN  = 15
 
# Tier-B: 표준 경로 (BB 중하단 복합 확인)
DIRECT_TIER_B_BB_MAX   = 35
DIRECT_TIER_B_BBW_MIN  = 1.0         # v32: 0.8→1.0 (BBW<1.0 무의미 실증)
DIRECT_TIER_B_RSI_MAX  = 50
DIRECT_TIER_B_RSI_MIN  = 15
 
# Tier-C: 반전 포인트
DIRECT_TIER_C_ENABLED  = True
 
# 5분봉 확인 (v32: 3점 체크리스트로 강화)
DIRECT_5M_CONFIRM      = True
 
# 급락 보너스 (유지)
PLUNGE_BONUS_THRESHOLD = 3.0
PLUNGE_BONUS_SCORE     = 1
 
# TME 상승장 보너스 (유지)
TME_BONUS_THRESHOLD    = 0.55
TME_BONUS_BB_EXTEND    = 5
 
# 매수 차단 쿨다운 (유지)
SAME_COIN_COOLDOWN_MIN = 15
 
# ── 3-Tier 낙폭 진입 파라미터 (보조 참고용, 유지) ──
TIER_DROP_T1_MIN  = -4.0
TIER_DROP_T1_MAX  = -2.0
TIER_DROP_T2      = -4.0
TIER1_BB_MAX      = 22
TIER1_RSI_MIN     = 20
TIER1_RSI_MAX     = 45
TIER1_VOL_MIN     = 1.0
TIER1_SCORE_MIN   = 4
TIER2_BB_MAX      = 30
TIER2_RSI_MAX     = 50
TIER2_SCORE_MIN   = 3
TIER3_RSI_MAX     = 32
TIER3_DROP_MIN    = -3.0
TIER3_VOL_MIN     = 1.5
TIER3_SCORE_MIN   = 3
 
# ── 야간 모멘텀 진입 파라미터 (유지) ──
NIGHT_HOUR_START  = 22
NIGHT_HOUR_END    = 6
NIGHT_MOM_RISE_PCT    = 0.5
NIGHT_MOM_RSI_MIN     = 30
NIGHT_MOM_RSI_MAX     = 70
NIGHT_MOM_BB_MAX      = 65
NIGHT_MOM_VOL_MIN     = 0.8
NIGHT_MOM_CONFIRM     = True
NIGHT_FORCE_PROFIT    = 1.8
 
# ── 일봉 컨텍스트 보너스 (유지) ──
DAY_CONTEXT_RSI_LOW   = 32
DAY_CONTEXT_BB_LOW    = 25
DAY_CONTEXT_SCORE_BONUS = 1
 
# ── 매도 강화 파라미터 (유지) ──
SELL_OVERBOUGHT_BB    = 75
SELL_OVERBOUGHT_RSI   = 70
SELL_FAST_RSI_THRESH  = 70
SELL_FAST_BB_MIN      = 70
 
# ── v32.0 신규: 볼륨 필터 (매수 시 의무) ──
BUY_VOL_RATIO_MIN     = 1.0          # 10봉 평균 대비 최소 거래량

# ── v33.1 신규: 가격 예측 연동 파라미터 ──────────────────────────────────
PREDICTOR_ENABLED        = True       # 예측 필터 ON/OFF (마스터 스위치)
PREDICTOR_CACHE_TTL_SEC  = 180        # 예측 결과 캐시 유효시간 (초) — 3분
PREDICTOR_TIMEOUT_SEC    = 30         # get_prediction() 호출 타임아웃 (초)
PREDICTOR_VETO_ON_SELL   = True       # SELL 신호 시 매수 차단 (veto)
PREDICTOR_BONUS_ON_BUY   = True       # BUY 신호 시 점수 보너스 부여
PREDICTOR_BUY_SCORE_BONUS = 1         # BUY 신호 보너스 점수 (+1)
PREDICTOR_FAIL_PASS      = True       # 오류/타임아웃 시 매수 허용 (fail-safe)
PREDICTOR_LOG_DISCORD     = True      # Discord에 예측 결과 포함 여부

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

# ★ v28.0: 추세 모멘텀 감시 목록
# {ticker: {'detected_at':dt, 'detected_price':float, 'trend_score':int,
#           'bull_market_score':float, 'expires_at':dt, 'score_reason':str}}
trend_watchlist: dict = {}
trend_watchlist_lock = Lock()
last_trend_scan_time: float = 0.0
# 스냅샷 캐시 (급락/추세 스캐너 공유용)
_cached_snapshot: dict = {}
_cached_snapshot_ts: float = 0.0

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

# ★ v33.1: 가격 예측 캐시 상태
# {ticker: {'signal': 'BUY'/'SELL'/'NEUTRAL', 'confidence': 'HIGH'/'MID'/'LOW',
#           'timestamp': float, 'ok': bool, 'detail': dict}}
prediction_cache = {}
prediction_cache_lock = Lock()

# 예측 통계 (모니터링용)
predictor_stats = {
    'total_calls': 0,
    'cache_hits': 0,
    'veto_count': 0,      # SELL로 매수 차단된 횟수
    'boost_count': 0,     # BUY로 보너스 부여된 횟수
    'error_count': 0,     # 오류/타임아웃 발생 횟수
    'pass_count': 0,      # NEUTRAL 또는 fail-safe 통과 횟수
}
predictor_stats_lock = Lock()


# ============================================================================
# SECTION 4: 시작 메시지
# ============================================================================

# print(f"\n{Colors.BOLD}{Colors.CYAN}{'='*60}")
# print(f"  BB BOUNCE HUNTER {VERSION}")
# print(f"  ★★★ v31.0: 직접 스캔 방식 (감시목록 게이트 제거)")
# print(f"  ★ 3-Tier 직접 진입: A(BB<25) B(BB<35) C(반전포인트)")
# print(f"  ★ 듀얼 타임프레임: 15분봉(위치) + 5분봉(확인)")
# print(f"  ★ 동적 손절: BB Width 연동 + 가속 손절 패턴")
# print(f"  ★ 보조 보너스: 급락스코어 + 상승장스코어 + 일봉")
# print(f"  시장등급: HIGH(BBW≥4%) MID(2~4%) LOW(<2%)")
# print(f"{'='*60}")
# print(f"  Thread 1: 매수 ({BUY_THREAD_INTERVAL}초) │ 직접스캔 + 보너스스캐너")
# print(f"  Thread 2: 매도 ({SELL_THREAD_INTERVAL}초)")
# print(f"  Thread 3: 모니터 ({MONITOR_THREAD_INTERVAL}초)")
# print(f"  Thread 4: WebSocket + 5분봉 빌더")
# print(f"  MAX: {MAX_HOLDINGS}개 | 1차:{FIRST_BUY_RATIO:.0%} 2차:전량")
# print(f"{'='*60}{Colors.ENDC}\n")

_STARTUP_BANNER = f"""
{Colors.BOLD}{Colors.CYAN}{'='*60}
  BB BOUNCE HUNTER {VERSION}
  ★★★ v33.1: 가격예측 v5.1 연동 + 시간대+일봉 동적전략
  ★ 3코인: ETH, XRP, SOL
  ★ 예측기: SELL→매수차단 / BUY→적극매수 / 오류→안전통과
  ★ 새벽 적극 / 낮 보수적 / 양봉→완화 / 음봉→강화
  ★ 탄력 트레일: 1%→0.3%T / 1.5%→0.5%T / 2%→0.7%T / 3%→1.0%T
  ★ 동적 목표: BBW<1.5→0.8% / 1.5~3→1.2% / 3+→1.5%
  ★ 시간청산: 16h+수익>0 / 24h 무조건
  시장등급: HIGH(BBW≥4%) MID(2~4%) LOW(<2%)
{'='*60}
  Thread 1: 매수 ({BUY_THREAD_INTERVAL}초) │ 예측필터+시간대+일봉
  Thread 2: 매도 ({SELL_THREAD_INTERVAL}초) │ 탄력트레일링
  Thread 3: 모니터 ({MONITOR_THREAD_INTERVAL}초)
  Thread 4: WebSocket + 5분봉 빌더
  MAX: {MAX_HOLDINGS}개 | 1차:{FIRST_BUY_RATIO:.0%} 2차:전량
{'='*60}{Colors.ENDC}
"""

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
    v28.0: trend_watchlist 상태 추가 반영.
    모니터 보고서·watch_section 에서 사용.
    """
    try:
        cur_price  = get_current_price(ticker) or 0
        d_change   = 0.0
        is_bullish = False

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

        # 급락 Watchlist 상태
        in_watch, wl_info = is_in_watchlist(ticker)
        wl_score = wl_info.get('stage1_score', 0) if wl_info else 0

        # ★ v28.0: 추세 Watchlist 상태
        in_trend_wl, trend_wl_info = is_in_trend_watchlist(ticker)

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
            # v28.0 추가
            'in_trend_watchlist': in_trend_wl,
            'trend_bull_score':   trend_wl_info.get('bull_market_score', 0.0) if trend_wl_info else 0.0,
        }
    except Exception:
        return {
            'cur_price': 0, 'cur_price_str': '-',
            'd_change': 0, 'is_bullish': False,
            'bb15': 50, 'bw15': 0, 'rsi15': 50,
            'srsi_k': 50, 'srsi_direction': '→',
            'in_watchlist': False, 'wl_score': 0,
            'in_trend_watchlist': False, 'trend_bull_score': 0.0,
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
            # ★ v33.1: 예측기 일일 통계 리셋 + 만료 캐시 정리
            if PREDICTOR_ENABLED:
                with predictor_stats_lock:
                    for key in predictor_stats:
                        predictor_stats[key] = 0
                with prediction_cache_lock:
                    now_ts = time.time()
                    expired = [k for k, v in prediction_cache.items()
                               if (now_ts - v.get('timestamp', 0)) > PREDICTOR_CACHE_TTL_SEC * 10]
                    for k in expired:
                        del prediction_cache[k]
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
    ★ v33.0: 15분마다 실행 — 3코인 급락도 스캔 + Watchlist 관리.

    v32 대비 변경:
      - 7코인 → 3코인(FIXED_STABLE_COINS) 순회
      - 전체 시장 급락 경보 기준: 4/7 → 2/3 동시 급락 시 경보
    """
    global last_snapshot_time, _cached_snapshot, _cached_snapshot_ts
    now_ts = time.time()
    if now_ts - last_snapshot_time < PLUNGE_SNAPSHOT_INTERVAL:
        return
    last_snapshot_time = now_ts

    now_str = datetime.now().strftime('%H:%M')
    num_coins = len(FIXED_STABLE_COINS)
    print(f"\n{Colors.CYAN}{'─'*54}")
    print(f"[DROP SCAN] 🔍 급락 스캐너 실행 ({now_str}) [{num_coins}코인]")
    print(f"{'─'*54}{Colors.ENDC}")

    # Step 1: 스냅샷
    snapshot = fetch_ticker_snapshot()
    if snapshot:
        _cached_snapshot    = snapshot
        _cached_snapshot_ts = now_ts

    if not snapshot:
        print(f"{Colors.RED}[DROP SCAN] 스냅샷 실패 — 다음 주기에 재시도{Colors.ENDC}")
        return

    newly_added   = []
    drop_detected = 0

    for ticker in FIXED_STABLE_COINS:
        coin = ticker.replace('KRW-', '')
        snap = snapshot.get(ticker)
        if not snap:
            continue

        thresh    = COIN_DROP_THRESHOLDS.get(ticker, {'cum4': -1.2, 'daily': -4.0})
        drop_open = snap['drop_from_open']

        quick_flag = drop_open <= (thresh['daily'] * 0.5)

        if quick_flag:
            df_15m = get_candles_15m(ticker, count=25)
            score, score_reason = calc_plunge_score(df_15m, ticker)
        else:
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

    _cleanup_watchlist()

    # ★ v33.0: 경보 기준 = 코인 수의 과반 이상 동시 급락
    alert_threshold = max(2, (num_coins + 1) // 2)  # 3코인→2, 7코인→4
    if drop_detected >= alert_threshold:
        msg = (f"⚠️ **전체 시장 급락 경보**\n"
               f"{drop_detected}/{num_coins} 코인 동시 급락 감지 — 매수 자제\n"
               f"{datetime.now().strftime('%H:%M:%S')}")
        send_discord_message(msg)
        print(f"{Colors.RED}  ⚠️ 전체 시장 급락 경보: {drop_detected}/{num_coins}코인{Colors.ENDC}")

    if newly_added:
        print(f"{Colors.RED}  🚨 신규 감시 등록: {', '.join(newly_added)}{Colors.ENDC}")
    with watchlist_lock:
        active = [f"{t.replace('KRW-','')}({v['stage1_score']:.1f}점)"
                  for t, v in sharp_drop_watchlist.items()]
    print(f"  📋 감시 중: {active if active else ['없음']}")
    print(f"{Colors.CYAN}{'─'*54}{Colors.ENDC}\n")


# ─────────────────────────────────────────────────────────────────────────────
# ★ v28.0 신규: 추세 모멘텀 스캐너 (SECTION 13.6)
#   calc_bull_market_score → score_trend_entry → buy_signal_trend
#   → run_trend_momentum_scanner → is_in_trend_watchlist
# ─────────────────────────────────────────────────────────────────────────────

def calc_bull_market_score(snapshot):
    """
    ★ v28.0: 전체 시장 상승 강도 스코어 (0.0~1.0).

    구성:
      A. 양봉 비율   — 7코인 중 시가 대비 양봉 코인 수 / 7  (가중 50%)
      B. 평균 등락률 — 전체 코인 평균 change_rate 정규화  (가중 50%)
         정규화 기준: +5% = 만점(1.0), 0% = 0.5, -5% = 0.0

    반환: (score: float, detail: str)
    """
    try:
        if not snapshot:
            return 0.0, "스냅샷없음"

        bull_count = 0
        total_change = 0.0
        valid = 0

        for ticker in FIXED_STABLE_COINS:
            snap = snapshot.get(ticker)
            if not snap:
                continue
            valid += 1
            if snap['drop_from_open'] >= 0:
                bull_count += 1
            total_change += snap['change_rate']

        if valid == 0:
            return 0.0, "유효코인없음"

        bull_ratio = bull_count / valid
        avg_change = total_change / valid

        # change_rate 정규화: -5%→0, 0%→0.5, +5%→1.0
        change_norm = min(max((avg_change + 5.0) / 10.0, 0.0), 1.0)

        score = bull_ratio * 0.5 + change_norm * 0.5
        detail = (f"양봉{bull_count}/{valid} | 평균{avg_change:+.2f}% | "
                  f"스코어{score:.2f}")
        return round(score, 3), detail

    except Exception as e:
        return 0.0, f"오류:{e}"


def score_trend_entry(df_15m):
    """
    ★ v28.0: 추세 모멘텀 진입 점수 (0~5점).

    반등 진입(score_15m_bounce)과 달리 하락 확인이 아닌 '상승 지속 확인' 로직.

    +1: RSI 42~72 범위 + 2봉 연속 상승 (추세 유지)
    +1: SRSI K > D (골든 상태) + K 50 이상 (과매도 탈출 완료)
    +1: 3봉 연속 양봉 OR (2봉 양봉 + 종가 연속 상승)
    +1: BB Position 상승 기울기 (현재 > 2봉 전 > 4봉 전)
    +1: 5분봉 BB Position > 50 + 5분봉 RSI > 50 (단기 모멘텀 확인)
         ※ df_15m 인자만 받음 — 5분봉은 buy_signal_trend에서 별도 전달
    """
    try:
        score = 0
        details = []

        if df_15m is None or len(df_15m) < 6:
            return 0, []

        c  = df_15m.iloc[-1]
        p1 = df_15m.iloc[-2]
        p2 = df_15m.iloc[-3]
        p4 = df_15m.iloc[-5] if len(df_15m) >= 6 else p2

        # 1) RSI 추세 유지 (42~72 범위 + 2봉 연속 상승)
        rsi_in_range = TREND_RSI_MIN <= c['rsi'] <= TREND_RSI_MAX
        rsi_rising   = c['rsi'] > p1['rsi'] and p1['rsi'] > p2['rsi']
        if rsi_in_range and rsi_rising:
            score += 1
            details.append(f"RSI↑↑{c['rsi']:.0f}")
        elif rsi_in_range and c['rsi'] > p1['rsi']:
            # 1봉 상승만 — 0.5점 상당이지만 조건 완화 (추세 초입 포착)
            score += 1
            details.append(f"RSI↑{c['rsi']:.0f}")

        # 2) SRSI 골든 상태 + K≥50
        srsi_golden = c['srsi_k'] > c['srsi_d'] and c['srsi_k'] >= 50
        if srsi_golden:
            score += 1
            details.append(f"SRSI골든K{c['srsi_k']:.0f}")

        # 3) 연속 양봉 패턴
        three_bull = (c['is_bull'] and p1['is_bull'] and p2['is_bull'])
        two_bull_rising = (c['is_bull'] and p1['is_bull'] and
                           c['close'] > p1['close'] and p1['close'] > p2['close'])
        if three_bull or two_bull_rising:
            score += 1
            tag = "3연속양봉" if three_bull else "2양봉+종가↑↑"
            details.append(tag)

        # 4) BB Position 상승 기울기 (현재 > 2봉 전 > 4봉 전)
        bb_slope = (c['bb_position'] > p2['bb_position'] > p4['bb_position'])
        if bb_slope:
            score += 1
            details.append(f"BB↑기울기{p4['bb_position']:.0f}→{c['bb_position']:.0f}")

        return score, details

    except Exception:
        return 0, []


def buy_signal_trend(ticker, trend_info):
    """
    ★ v28.0: 추세 모멘텀 진입 신호.

    Phase A: 자격 검증
      - BB Position: TREND_BB_POS_MIN ~ TREND_BB_POS_MAX
      - BB Width >= TREND_BBW_MIN
      - RSI: TREND_RSI_MIN ~ TREND_RSI_MAX
    Phase B: 추세 점수 (score_trend_entry) + 5분봉 모멘텀 보너스
      - 합산 >= TREND_SCORE_MIN (3점) 시 매수 확정
    """
    try:
        df_15m = get_candles_15m(ticker, count=50)
        if df_15m is None or len(df_15m) < 25:
            return {'signal': False, 'reason': '데이터부족',
                    'entry_price': 0, 'bb_position': 50, 'bb_width_pct': 0}

        df_5m = get_candles_5m(ticker)

        current   = df_15m.iloc[-1]
        grade     = current_market_grade
        bb_pos    = current['bb_position']
        bb_width  = current['bb_width']
        rsi       = current['rsi']

        base = {
            'signal': False, 'reason': '',
            'entry_price': current['close'],
            'bb_position': bb_pos,
            'bb_width_pct': bb_width,
            'market_grade': grade,
            'entry_type': 'trend_momentum',
        }

        # ── Phase A: 자격 검증 ──
        if not (TREND_BB_POS_MIN <= bb_pos <= TREND_BB_POS_MAX):
            base['reason'] = (f"TME BB위치부적합 {bb_pos:.0f}%"
                              f"(허용:{TREND_BB_POS_MIN}~{TREND_BB_POS_MAX}%)")
            return base

        if bb_width < TREND_BBW_MIN:
            base['reason'] = f"TME BB폭부족 {bb_width:.1f}%<{TREND_BBW_MIN}%"
            return base

        if not (TREND_RSI_MIN <= rsi <= TREND_RSI_MAX):
            base['reason'] = f"TME RSI범위외 {rsi:.0f}(허용:{TREND_RSI_MIN}~{TREND_RSI_MAX})"
            return base

        # ── Phase B: 추세 점수 ──
        score, details = score_trend_entry(df_15m)

        # 5분봉 모멘텀 보너스 (+1점) — BB>50 + RSI>50
        bonus_5m = False
        if df_5m is not None and len(df_5m) >= 5:
            c5 = df_5m.iloc[-1]
            if c5.get('bb_position', 0) > 50 and c5.get('rsi', 0) > 50:
                score += 1
                details.append(f"5m모멘텀(BB{c5['bb_position']:.0f}RSI{c5['rsi']:.0f})")
                bonus_5m = True

        if score < TREND_SCORE_MIN:
            d = '+'.join(details) if details else '없음'
            base['reason'] = f"TME 점수부족 {score}점<{TREND_SCORE_MIN}({d})[{grade}]"
            return base

        # ── 매수 확정 ──
        bull_score = trend_info.get('bull_market_score', 0.0)
        d_str = '+'.join(details)
        return {
            'signal': True,
            'reason': (f"[TME][{grade}] BB{bb_pos:.0f}% 폭{bb_width:.1f}% "
                       f"RSI{rsi:.0f} | {score}점:{d_str} | 시장스코어{bull_score:.2f}"),
            'entry_price': current['close'],
            'bb_position': bb_pos,
            'bb_width_pct': bb_width,
            'market_grade': grade,
            'entry_type': 'trend_momentum',
        }

    except Exception as e:
        if DEBUG_MODE:
            print(f"{Colors.RED}[TME Signal] {ticker} 오류: {e}{Colors.ENDC}")
        return {'signal': False, 'reason': f'오류:{e}',
                'entry_price': 0, 'bb_position': 50, 'bb_width_pct': 0}


def is_in_trend_watchlist(ticker):
    """
    추세 모멘텀 Watchlist 등록 여부 확인.

    반환:
      (True, info_dict)  — 감시 중 + 유효
      (False, None)      — 미등록 또는 만료
    """
    with trend_watchlist_lock:
        if ticker not in trend_watchlist:
            return False, None
        info = trend_watchlist[ticker]
        if datetime.now() > info['expires_at']:
            return False, None
        return True, info


def _cleanup_trend_watchlist():
    """만료된 trend_watchlist 항목 제거."""
    now = datetime.now()
    with trend_watchlist_lock:
        expired = [t for t, v in trend_watchlist.items() if now > v['expires_at']]
        for t in expired:
            if DEBUG_MODE:
                print(f"{Colors.YELLOW}  [TME-WL] {t.replace('KRW-','')} 만료 제거{Colors.ENDC}")
            del trend_watchlist[t]


def run_trend_momentum_scanner():
    """
    ★ v28.0: 15분마다 실행 — 상승장 모멘텀 감지 + Trend Watchlist 관리.

    실행 흐름:
      1. fetch_ticker_snapshot() 캐시 재사용 (급락 스캐너와 공유)
      2. calc_bull_market_score() — 전체 시장 상승 강도 측정
      3. bull_score < TREND_BULL_SCORE_MIN 이면 스캔 중단 (상승장 아님)
      4. 개별 코인 BB 위치·RSI 사전 필터
      5. 통과 코인 → trend_watchlist 등록 (45분 유효)
      6. 만료 항목 자동 정리
    """
    global last_trend_scan_time, _cached_snapshot, _cached_snapshot_ts

    now_ts = time.time()
    if now_ts - last_trend_scan_time < TREND_SNAPSHOT_INTERVAL:
        return
    last_trend_scan_time = now_ts

    now_str = datetime.now().strftime('%H:%M')
    print(f"\n{Colors.BLUE}{'─'*54}")
    print(f"[TME SCAN] 📈 추세 스캐너 실행 ({now_str})")
    print(f"{'─'*54}{Colors.ENDC}")

    # Step 1: 스냅샷 캐시 재사용 (60초 이내면 재사용)
    if now_ts - _cached_snapshot_ts < 60 and _cached_snapshot:
        snapshot = _cached_snapshot
    else:
        snapshot = fetch_ticker_snapshot()
        if snapshot:
            _cached_snapshot    = snapshot
            _cached_snapshot_ts = now_ts

    if not snapshot:
        print(f"{Colors.RED}[TME SCAN] 스냅샷 실패{Colors.ENDC}")
        return

    # Step 2: 전체 시장 상승 강도 측정
    bull_score, bull_detail = calc_bull_market_score(snapshot)
    print(f"  📊 시장스코어: {bull_score:.2f} ({bull_detail})")

    if bull_score < TREND_BULL_SCORE_MIN:
        print(f"  ⏸️  상승장 미충족 ({bull_score:.2f} < {TREND_BULL_SCORE_MIN}) — 스캔 중단")
        _cleanup_trend_watchlist()
        print(f"{Colors.BLUE}{'─'*54}{Colors.ENDC}\n")
        return

    # Step 3: 개별 코인 사전 필터 + watchlist 등록
    newly_added = []

    for ticker in FIXED_STABLE_COINS:
        coin = ticker.replace('KRW-', '')
        snap = snapshot.get(ticker)
        if not snap:
            continue

        change = snap['change_rate']
        drop_open = snap['drop_from_open']

        # 사전 필터: 당일 양봉이거나 소폭 하락(0.5% 이내) 코인만 추세 후보
        if drop_open < -0.5:
            print(f"  {coin:<5} 제외 (당일{drop_open:+.1f}% 하락)")
            continue

        # BB 위치·RSI 빠른 확인 (6봉 캔들로)
        df_quick = get_candles_15m(ticker, count=6)
        if df_quick is None or len(df_quick) < 2:
            continue

        curr_candle = df_quick.iloc[-1]
        bb_pos  = curr_candle.get('bb_position', 50)
        rsi_val = curr_candle.get('rsi', 50)

        in_trend_wl = ticker in trend_watchlist
        eligible = (TREND_BB_POS_MIN <= bb_pos <= TREND_BB_POS_MAX and
                    TREND_RSI_MIN    <= rsi_val <= TREND_RSI_MAX)

        icon = "🟢" if eligible else "  "
        print(f"  {icon}{coin:<5} 등락{change:+.1f}% | BB{bb_pos:.0f}% RSI{rsi_val:.0f}"
              f"{' [감시중]' if in_trend_wl else ''}")

        if eligible and not in_trend_wl:
            with trend_watchlist_lock:
                trend_watchlist[ticker] = {
                    'detected_at':       datetime.now(),
                    'detected_price':    snap['price'],
                    'bull_market_score': bull_score,
                    'trend_score':       0,       # buy_signal_trend 에서 확정
                    'score_reason':      f"BB{bb_pos:.0f}% RSI{rsi_val:.0f}",
                    'expires_at':        datetime.now() + timedelta(minutes=TREND_WATCH_WINDOW_MIN),
                }
            newly_added.append(f"{coin}(BB{bb_pos:.0f}%,RSI{rsi_val:.0f})")

    # Step 4: 만료 정리
    _cleanup_trend_watchlist()

    if newly_added:
        print(f"{Colors.GREEN}  📈 신규 추세감시: {', '.join(newly_added)}{Colors.ENDC}")
    with trend_watchlist_lock:
        active = [f"{t.replace('KRW-','')}(BB{v['score_reason']})"
                  for t, v in trend_watchlist.items()]
    print(f"  📋 추세감시 중: {active if active else ['없음']}")
    print(f"{Colors.BLUE}{'─'*54}{Colors.ENDC}\n")

def get_timezone_aggression():
    """
    ★ v33.0: 시간대 + 일봉 결합형 공격도 파라미터 반환.
 
    v32 대비 변경:
      - 새벽(00-06): 보수적 → 적극적 (bb_adjust +5, score -1)
      - 낮(09-15): 표준 → 보수적 (bb_adjust -5, score +2)
      - 야간(22-24): 표준 → 적극적 (bb_adjust +3)
      - 일봉 양봉/음봉에 따른 추가 보정 결합
      - 시간대 겹침 버그 수정 (0~5시가 '야간'으로 잘못 분류되던 문제)
 
    반환: {
        'bb_adjust': int,        # BB 상한 보정값 (시간대 + 일봉 합산)
        'score_adjust': int,     # 최소점수 보정값 (시간대 + 일봉 합산)
        'label': str,            # 표시용 라벨
        'hold_hours_hint': int,  # 권장 보유 시간
        'daily_label': str,      # 일봉 상태 라벨
    }
    """
    kst_hour = datetime.now().hour
 
    # ── 시간대 매칭 (겹침 없는 순차 판별) ──
    if 0 <= kst_hour < 6:
        tz_bb = 5
        tz_score = -1
        tz_label = '새벽적극'
        hold_hint = 16
    elif 6 <= kst_hour < 9:
        tz_bb = -5
        tz_score = 1
        tz_label = '오전방어'
        hold_hint = 8
    elif 9 <= kst_hour < 15:
        tz_bb = -5
        tz_score = 2
        tz_label = '낮보수적'
        hold_hint = 8
    elif 15 <= kst_hour < 18:
        tz_bb = 0
        tz_score = 1
        tz_label = '오후표준'
        hold_hint = 12
    elif 18 <= kst_hour < 22:
        tz_bb = 0
        tz_score = 0
        tz_label = '저녁표준'
        hold_hint = 8
    else:  # 22~23
        tz_bb = 3
        tz_score = 0
        tz_label = '야간적극'
        hold_hint = 16
 
    # ── 일봉 양봉/음봉 보정 (스냅샷 캐시 활용) ──
    daily_bb = 0
    daily_score = 0
    daily_label = '미확인'
    try:
        snapshot = _cached_snapshot if _cached_snapshot else {}
        if snapshot:
            # 3코인 평균 당일 시가 대비 등락률
            changes = []
            for ticker in FIXED_STABLE_COINS:
                snap = snapshot.get(ticker)
                if snap:
                    changes.append(snap['drop_from_open'])
            if changes:
                avg_change = sum(changes) / len(changes)
                if avg_change >= 2.0:
                    daily_bb = 5
                    daily_score = -1
                    daily_label = '강한양봉'
                elif avg_change >= 0.0:
                    daily_bb = 3
                    daily_score = 0
                    daily_label = '양봉'
                elif avg_change >= -2.0:
                    daily_bb = 0
                    daily_score = 1
                    daily_label = '약한음봉'
                else:
                    daily_bb = -5
                    daily_score = 2
                    daily_label = '강한음봉'
    except Exception:
        pass
 
    return {
        'bb_adjust': tz_bb + daily_bb,
        'score_adjust': tz_score + daily_score,
        'label': f"{tz_label}+{daily_label}",
        'hold_hours_hint': hold_hint,
        'daily_label': daily_label,
    }

def check_5m_checklist(df_5m):
    """
    ★ v32.0 신규: 5분봉 3점 체크리스트 (2/3 필수).
 
    실증 근거 (성공 vs 실패 5분봉 특성 차이):
      - RSI 상승: 성공 50% vs 실패 32% (★ +18%)
      - BB Position 상승: 성공 63% vs 실패 47% (★ +16%)
      - 양봉: 성공 47% vs 실패 37% (★ +10%)
 
    반환: (bool 통과, int 점수, str 상세)
    """
    if not CONFIRM_5M_ENABLED:
        return True, 3, "5m확인비활성"
 
    if df_5m is None or len(df_5m) < 3:
        return True, 0, "5m데이터없음(통과)"
 
    c5 = df_5m.iloc[-1]
    p5 = df_5m.iloc[-2]
 
    score = 0
    details = []
 
    # 체크 1: RSI 상승
    if c5['rsi'] > p5['rsi']:
        score += 1
        details.append(f"RSI↑{c5['rsi']:.0f}")
 
    # 체크 2: BB Position 상승
    if c5['bb_position'] > p5['bb_position']:
        score += 1
        details.append(f"BB↑{c5['bb_position']:.0f}")
 
    # 체크 3: 양봉
    if c5['is_bull']:
        score += 1
        details.append("양봉")
 
    passed = score >= CONFIRM_5M_MIN_SCORE
    detail_str = '+'.join(details) if details else '없음'
    return passed, score, f"5m({score}/3:{detail_str})"

def get_dynamic_target_by_bbw(bbw):
    """
    ★ v32.0 신규: BBW(변동성)에 따른 동적 목표수익률 결정.
 
    실증 근거:
      - BBW < 1.5%: 1%승률 12~29% → 목표 0.8%가 현실적
      - BBW 1.5~3%: 1%승률 23~50% → 목표 1.2%
      - BBW 3%+: 변동성 함정, 예측 불가 → 목표 1.5%
 
    반환: float (안전익절 기준 수익률)
    """
    for lo, hi, target in DYNAMIC_TARGET_BY_BBW:
        if lo <= bbw < hi:
            return target
    return 1.0  # 기본값

def calc_elastic_trail_gap(peak_profit_pct):
    """
    ★ v32.0 신규: 수익 크기별 탄력 트레일링 간격 계산.
 
    원리: 수익이 클수록 트레일 간격을 넓혀 "끝까지 타기"
    수익이 작으면 간격을 좁혀 안전하게 확보
 
    실증 근거:
      - 탄력트레일: 승률 91%, 2%+ 4건 달성
      - 1.5%고정: 승률 84%, 2%+ 0건 → 큰 수익 놓침
 
    반환: float (음수, 고점 대비 허용 하락폭) or None (미활성)
    """
    if peak_profit_pct < ELASTIC_TRAIL_ACTIVATE:
        return None  # 아직 미활성
 
    for threshold, gap in ELASTIC_TRAIL_TIERS:
        if peak_profit_pct >= threshold:
            return gap
 
    return -0.3  # 기본 최소 간격

def score_15m_bounce(df):
    """
    ★ v30.0: 15분봉 반등 점수 (최대 7점)
 
    기본 5점 (v27.1 유지):
    +1: RSI 2봉 연속 상승 (1봉도 가능 — 낙폭 클 때 빠른 반응)
    +1: SRSI K 상향돌파 D (골든크로스)
    +1: 양봉 + 종가 > 직전 종가
    +1: 현재가 > 3봉전 저가 (하락 멈춤 확인)
    +1: 2연속 양봉 반등 확인 (현재봉 양봉 + 직전봉 양봉 + 종가↑)
 
    ★ v30.0 신규 보너스 2점:
    +1: RSI 스윗스팟 (20~45) — 진짜 반등 구간
    +1: 낙폭 보너스 — 4봉 누적 낙폭 -2% 이하 (충분한 하락 후 반등)
    """
    try:
        score = 0
        details = []
 
        if df is None or len(df) < 5:
            return 0, []
 
        c  = df.iloc[-1]    # 현재
        p1 = df.iloc[-2]    # 1봉 전
        p2 = df.iloc[-3]    # 2봉 전
        p3 = df.iloc[-4]    # 3봉 전
        p4 = df.iloc[-5] if len(df) >= 5 else p3  # 4봉 전
 
        # 1) RSI 상승 (2봉 연속 or 1봉 — 낙폭 클 때 빠른 전환 허용)
        if c['rsi'] > p1['rsi'] and p1['rsi'] > p2['rsi']:
            score += 1
            details.append(f"RSI↑↑{c['rsi']:.0f}")
        elif c['rsi'] > p1['rsi']:
            score += 1
            details.append(f"RSI↑{c['rsi']:.0f}")
 
        # 2) SRSI K 상향돌파 D (골든크로스) or K 상승 중
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
            details.append(f"저가돌파({p3['low']:.0f})")
 
        # 5) 2연속 양봉 반등 확인
        if c['is_bull'] and p1['is_bull'] and c['close'] > p1['close']:
            score += 1
            details.append(f"2연속양봉↑")
 
        # ★ 6) v30.0: RSI 스윗스팟 보너스 (20~45 = 실제 반등 최적 구간)
        if 20 <= c['rsi'] <= 45:
            score += 1
            details.append(f"RSI스윗스팟{c['rsi']:.0f}")
 
        # ★ 7) v30.0: 낙폭 보너스 — 4봉 누적 하락 -2% 이하
        if p4['close'] > 0:
            drop_4 = (c['close'] - p4['close']) / p4['close'] * 100
            if drop_4 <= -2.0:
                score += 1
                details.append(f"낙폭보너스{drop_4:.1f}%")
 
        return score, details
 
    except Exception:
        return 0, []

def check_night_momentum(df_15m, df_5m):
    """
    ★ v30.0 신규: 야간 모멘텀 진입 판단
 
    야간(22:00-06:00 KST)에는 BB 하단 반등보다 모멘텀 지속이 효과적.
    (데이터 근거: 야간 단순모멘텀 2%승률 18% > 야간BB하단반등 6%)
 
    조건 (모두 충족):
    1. 단일봉 0.5%+ 상승 발생 (급등 감지)
    2. RSI 30~70 범위 (극단 제외 — 과매도/과매수 패닉 제외)
    3. BB Position < 65 (고점 진입 방지)
    4. 볼륨 > 평균 0.8배 (노이즈 제거)
    5. (선택) 연속 2봉 상승 확인 — NIGHT_MOM_CONFIRM=True 시
 
    Returns: (bool, str reason)
    """
    try:
        if df_15m is None or len(df_15m) < 5:
            return False, "데이터부족"
 
        c  = df_15m.iloc[-1]
        p1 = df_15m.iloc[-2]
 
        # 조건 1: 단일봉 상승
        candle_rise = (c['close'] - p1['close']) / p1['close'] * 100 if p1['close'] > 0 else 0
        if candle_rise < NIGHT_MOM_RISE_PCT:
            return False, f"야간상승부족({candle_rise:.2f}%<{NIGHT_MOM_RISE_PCT}%)"
 
        # 조건 2: RSI 범위
        if not (NIGHT_MOM_RSI_MIN <= c['rsi'] <= NIGHT_MOM_RSI_MAX):
            return False, f"야간RSI범위외({c['rsi']:.0f})"
 
        # 조건 3: BB Position 상한
        if c['bb_position'] > NIGHT_MOM_BB_MAX:
            return False, f"야간BB고점({c['bb_position']:.0f}%>{NIGHT_MOM_BB_MAX}%)"
 
        # 조건 4: 볼륨
        if c.get('vol_ratio', 1.0) < NIGHT_MOM_VOL_MIN:
            return False, f"야간볼륨부족({c.get('vol_ratio',0):.1f}x)"
 
        # 조건 5: 연속 2봉 상승 확인 (선택)
        if NIGHT_MOM_CONFIRM:
            if len(df_15m) >= 3:
                p2 = df_15m.iloc[-3]
                two_up = (c['close'] > p1['close']) and (p1['close'] > p2['close'])
                if not two_up:
                    return False, f"야간2봉연속미확인(p1:{p1['close']:.0f}→c:{c['close']:.0f})"
            # 5분봉으로 보조 확인
            if df_5m is not None and len(df_5m) >= 3:
                c5  = df_5m.iloc[-1]
                p1_5 = df_5m.iloc[-2]
                if not (c5['close'] > p1_5['close']):
                    return False, "5분봉연속미확인"
 
        reason = (f"야간모멘텀! 상승{candle_rise:.2f}% "
                  f"RSI{c['rsi']:.0f} BB{c['bb_position']:.0f}% "
                  f"볼륨{c.get('vol_ratio',0):.1f}x")
        return True, reason
 
    except Exception as e:
        return False, f"오류:{e}"
    
def get_daily_context(ticker):
    """
    ★ v30.0 신규: 일봉 컨텍스트 조회
 
    반환:
      {
        'rsi': float,           일봉 RSI
        'bb_position': float,   일봉 BB Position
        'is_oversold': bool,    일봉 RSI < DAY_CONTEXT_RSI_LOW
        'is_low_bb': bool,      일봉 BB < DAY_CONTEXT_BB_LOW
        'pct_from_20d_high': float,  20일 고점 대비 낙폭
        'bonus': int,           보너스 점수 합계
        'reason': str,
      }
    """
    try:
        df_d = get_candles_daily(ticker, count=25)
        if df_d is None or len(df_d) < 5:
            return {'rsi': 50, 'bb_position': 50, 'is_oversold': False,
                    'is_low_bb': False, 'pct_from_20d_high': 0, 'bonus': 0, 'reason': '일봉없음'}
 
        # RSI 계산
        delta = df_d['close'].diff()
        gain = delta.clip(lower=0)
        loss = -delta.clip(upper=0)
        avg_gain = gain.ewm(span=14, adjust=False).mean()
        avg_loss = loss.ewm(span=14, adjust=False).mean()
        rs = avg_gain / avg_loss.replace(0, float('nan'))
        df_d['rsi_d'] = 100 - (100 / (1 + rs))
 
        # BB 계산
        df_d['bb_mid'] = df_d['close'].rolling(20).mean()
        df_d['bb_std'] = df_d['close'].rolling(20).std()
        df_d['bb_upper'] = df_d['bb_mid'] + 2 * df_d['bb_std']
        df_d['bb_lower'] = df_d['bb_mid'] - 2 * df_d['bb_std']
        df_d['bb_pos'] = ((df_d['close'] - df_d['bb_lower']) /
                          (df_d['bb_upper'] - df_d['bb_lower']) * 100)
 
        c = df_d.iloc[-1]
        rsi_d      = float(c.get('rsi_d', 50))
        bb_pos_d   = float(c.get('bb_pos', 50))
 
        # 20일 고점 대비 낙폭
        high_20d = df_d['high'].iloc[-20:].max() if len(df_d) >= 20 else df_d['high'].max()
        pct_from_hi = (c['close'] - high_20d) / high_20d * 100 if high_20d > 0 else 0
 
        is_oversold = rsi_d < DAY_CONTEXT_RSI_LOW
        is_low_bb   = bb_pos_d < DAY_CONTEXT_BB_LOW
        is_deep_dd  = pct_from_hi < -30  # 20일 고점 대비 -30%+ 하락
 
        bonus = 0
        bonus_reasons = []
        if is_oversold:
            bonus += DAY_CONTEXT_SCORE_BONUS
            bonus_reasons.append(f"일봉RSI{rsi_d:.0f}↓")
        if is_low_bb:
            bonus += DAY_CONTEXT_SCORE_BONUS
            bonus_reasons.append(f"일봉BB{bb_pos_d:.0f}↓")
        if is_deep_dd:
            bonus += 1
            bonus_reasons.append(f"20일고점-{abs(pct_from_hi):.0f}%")
 
        return {
            'rsi': rsi_d,
            'bb_position': bb_pos_d,
            'is_oversold': is_oversold,
            'is_low_bb': is_low_bb,
            'pct_from_20d_high': pct_from_hi,
            'bonus': bonus,
            'reason': '+'.join(bonus_reasons) if bonus_reasons else '일반장',
        }
 
    except Exception as e:
        return {'rsi': 50, 'bb_position': 50, 'is_oversold': False,
                'is_low_bb': False, 'pct_from_20d_high': 0, 'bonus': 0, 'reason': f'오류:{e}'}
    
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
    ★★★ v33.0 매수 신호 — 시간대+일봉 결합형 동적 임계치 + 3코인 집중

    v32 대비 변경:
    ① 시간대+일봉 결합형 공격도 (새벽 적극, 낮 보수적, 양봉 완화, 음봉 강화)
    ② 3코인(ETH, XRP, SOL) 전용 최적화
    ③ 기존 5분봉 3점 체크리스트 + 볼륨 필터 유지

    ════════════════════════════════════════════════════════
    흐름도:
    ① 시간대+일봉 확인 → 동적 공격도 파라미터 결정
    ② 야간(22-06시)이면 야간 모멘텀 트랙 분기
    ③ 데이터 수집 + 기본 지표 계산
    ④ 직접 진입 조건 평가 (3-Tier) + 동적 BB상한/점수기준
    ⑤ 보너스 가산: 급락/일봉/볼륨
    ⑥ 크래시 리커버리 (기존 유지)
    ════════════════════════════════════════════════════════
    """
    try:
        # ── 데이터 수집 ──
        df_15m = get_candles_15m(ticker, count=50)
        if df_15m is None or len(df_15m) < 25:
            return {'signal': False, 'reason': '15분봉 데이터 부족',
                    'entry_price': 0, 'bb_position': 50, 'bb_width_pct': 0}

        df_5m = get_candles_5m(ticker)

        current = df_15m.iloc[-1]
        prev    = df_15m.iloc[-2]
        grade   = current_market_grade
        p       = get_grade_params(grade)

        bb_pos   = current['bb_position']
        bb_width = current['bb_width']
        rsi      = current['rsi']
        srsi_k   = current['srsi_k']
        srsi_d   = current['srsi_d']

        base = {
            'signal': False, 'reason': '',
            'entry_price': current['close'],
            'bb_position': bb_pos,
            'bb_width_pct': bb_width,
            'market_grade': grade,
            'entry_type': 'normal',
        }

        # ════════════════════════════════════════
        # ★ v33.0: 시간대 + 일봉 결합형 공격도
        # ════════════════════════════════════════
        tz = get_timezone_aggression()
        tz_bb_adjust = tz['bb_adjust']
        tz_score_adjust = tz['score_adjust']
        tz_label = tz['label']

        # ════════════════════════════════════════
        # 야간 모멘텀 트랙 (v30 유지)
        # ════════════════════════════════════════
        kst_hour = datetime.now().hour
        is_night = (kst_hour >= NIGHT_HOUR_START) or (kst_hour < NIGHT_HOUR_END)

        if is_night:
            night_ok, night_reason = check_night_momentum(df_15m, df_5m)
            if night_ok:
                return {
                    'signal': True,
                    'reason': f"[야간모멘텀][{grade}][{tz_label}] {night_reason}",
                    'entry_price': current['close'],
                    'bb_position': bb_pos,
                    'bb_width_pct': bb_width,
                    'market_grade': grade,
                    'entry_type': 'night_momentum',
                }

        # ════════════════════════════════════════
        # 보너스 점수 수집 (일봉 + 급락 + TME)
        # ════════════════════════════════════════
        day_ctx = get_daily_context(ticker)
        day_bonus = day_ctx['bonus']

        plunge_bonus = 0
        plunge_tag = ""
        try:
            df_plunge = get_candles_15m(ticker, count=25)
            if df_plunge is not None and len(df_plunge) >= 6:
                p_score, p_reason = calc_plunge_score(df_plunge, ticker)
                if p_score >= PLUNGE_BONUS_THRESHOLD:
                    plunge_bonus = PLUNGE_BONUS_SCORE
                    plunge_tag = f" 급락보너스({p_score:.1f})"
        except Exception:
            pass

        tme_bb_extend = 0
        tme_tag = ""
        try:
            snapshot = _cached_snapshot if _cached_snapshot else {}
            if snapshot:
                bull_score, bull_detail = calc_bull_market_score(snapshot)
                if bull_score >= TME_BONUS_THRESHOLD:
                    tme_bb_extend = TME_BONUS_BB_EXTEND
                    tme_tag = f" 상승장+{tme_bb_extend}BB({bull_score:.2f})"
        except Exception:
            pass

        total_bonus = day_bonus + plunge_bonus

        # ════════════════════════════════════════
        # ★★★ v33.0: 직접 진입 조건 평가 (3-Tier)
        #             + 시간대+일봉 동적 보정 + 5분봉 3점 + 볼륨
        # ════════════════════════════════════════

        # ── 공통 사전 필터 ──
        is_bull_candle = current['is_bull']
        rsi_rising = rsi > prev['rsi']
        srsi_golden = srsi_k > srsi_d

        # ── ★ v32.0 유지: 볼륨 필터 (의무) ──
        vol_ratio = current.get('vol_ratio', 1.0)
        vol_ok = vol_ratio >= BUY_VOL_RATIO_MIN
        vol_tag = f" 볼륨{vol_ratio:.1f}x" if vol_ok else ""

        # ── ★ v32.0 유지: 5분봉 3점 체크리스트 ──
        confirm_5m_pass, confirm_5m_score, confirm_5m_tag = check_5m_checklist(df_5m)

        # ────────────────────────────────────────
        # Tier-A: 고승률 경로 (BB < 25%)
        # v33: 시간대+일봉 보정 적용
        # ────────────────────────────────────────
        tier_a_bb_max = DIRECT_TIER_A_BB_MAX + tme_bb_extend + tz_bb_adjust
        if (bb_pos <= tier_a_bb_max and
            is_bull_candle and
            rsi_rising and
            DIRECT_TIER_A_RSI_MIN <= rsi <= DIRECT_TIER_A_RSI_MAX):

            bonus_str = ""
            if day_bonus > 0:
                bonus_str += f" 일봉+{day_bonus}({day_ctx['reason']})"
            if plunge_bonus > 0:
                bonus_str += plunge_tag
            if tme_bb_extend > 0:
                bonus_str += tme_tag

            return {
                'signal': True,
                'reason': (f"[Tier-A고승률][{grade}][{tz_label}] BB{bb_pos:.0f}% RSI{rsi:.0f}↑ "
                           f"BBW{bb_width:.1f}%{vol_tag}{bonus_str} {confirm_5m_tag}"),
                'entry_price': current['close'],
                'bb_position': bb_pos,
                'bb_width_pct': bb_width,
                'market_grade': grade,
                'entry_type': 'tier_a',
            }

        # ────────────────────────────────────────
        # Tier-C: 반전 포인트 (BB < 35% + 직전봉 음봉)
        # v33: 시간대+일봉 보정 적용
        # ────────────────────────────────────────
        tier_b_bb_max = DIRECT_TIER_B_BB_MAX + tme_bb_extend + tz_bb_adjust + (5 if day_ctx['is_low_bb'] else 0)

        if (DIRECT_TIER_C_ENABLED and
            bb_pos <= tier_b_bb_max and
            bb_width >= DIRECT_TIER_B_BBW_MIN and
            is_bull_candle and
            rsi_rising and
            srsi_golden and
            DIRECT_TIER_B_RSI_MIN <= rsi <= DIRECT_TIER_B_RSI_MAX and
            not prev['is_bull'] and
            vol_ok):

            if not confirm_5m_pass:
                score_15m, details_15m = score_15m_bounce(df_15m)
                if score_15m + total_bonus < max(3 + tz_score_adjust, 2):
                    pass  # 크래시 리커버리로 폴스루
                else:
                    bonus_str = ""
                    if day_bonus > 0: bonus_str += f" 일봉+{day_bonus}"
                    if plunge_bonus > 0: bonus_str += plunge_tag
                    return {
                        'signal': True,
                        'reason': (f"[Tier-C반전][{grade}][{tz_label}] BB{bb_pos:.0f}% RSI{rsi:.0f}↑ "
                                   f"SRSI{srsi_k:.0f}>D BBW{bb_width:.1f}% "
                                   f"직전음봉→양봉 15m보완{score_15m}점{vol_tag}{bonus_str}"),
                        'entry_price': current['close'],
                        'bb_position': bb_pos,
                        'bb_width_pct': bb_width,
                        'market_grade': grade,
                        'entry_type': 'tier_c',
                    }
            else:
                bonus_str = ""
                if day_bonus > 0: bonus_str += f" 일봉+{day_bonus}"
                if plunge_bonus > 0: bonus_str += plunge_tag
                if tme_bb_extend > 0: bonus_str += tme_tag
                return {
                    'signal': True,
                    'reason': (f"[Tier-C반전][{grade}][{tz_label}] BB{bb_pos:.0f}% RSI{rsi:.0f}↑ "
                               f"SRSI{srsi_k:.0f}>D BBW{bb_width:.1f}% "
                               f"직전음봉→양봉{vol_tag}{bonus_str} {confirm_5m_tag}"),
                    'entry_price': current['close'],
                    'bb_position': bb_pos,
                    'bb_width_pct': bb_width,
                    'market_grade': grade,
                    'entry_type': 'tier_c',
                }

        # ────────────────────────────────────────
        # Tier-B: 표준 경로 (BB < 35%)
        # v33: 시간대+일봉 보정 적용
        # ────────────────────────────────────────
        if (bb_pos <= tier_b_bb_max and
            bb_width >= DIRECT_TIER_B_BBW_MIN and
            is_bull_candle and
            rsi_rising and
            srsi_golden and
            DIRECT_TIER_B_RSI_MIN <= rsi <= DIRECT_TIER_B_RSI_MAX and
            vol_ok):

            if not confirm_5m_pass and DIRECT_5M_CONFIRM:
                score_15m, details_15m = score_15m_bounce(df_15m)
                min_score = max(3 + tz_score_adjust, 2)
                if score_15m + total_bonus < min_score:
                    base['reason'] = (f"Tier-B 5m미통과+15m점수부족 "
                                      f"BB{bb_pos:.0f}% RSI{rsi:.0f} "
                                      f"15m:{score_15m}점<{min_score}[{grade}][{tz_label}]")
                    pass
                else:
                    bonus_str = ""
                    if day_bonus > 0: bonus_str += f" 일봉+{day_bonus}"
                    if plunge_bonus > 0: bonus_str += plunge_tag
                    if tme_bb_extend > 0: bonus_str += tme_tag
                    d15 = '+'.join([str(d) for d in details_15m]) if details_15m else 'N/A'
                    return {
                        'signal': True,
                        'reason': (f"[Tier-B표준][{grade}][{tz_label}] BB{bb_pos:.0f}% RSI{rsi:.0f}↑ "
                                   f"SRSI{srsi_k:.0f}>D BBW{bb_width:.1f}% "
                                   f"15m보완({score_15m}점:{d15}){vol_tag}{bonus_str}"),
                        'entry_price': current['close'],
                        'bb_position': bb_pos,
                        'bb_width_pct': bb_width,
                        'market_grade': grade,
                        'entry_type': 'tier_b',
                    }
            else:
                bonus_str = ""
                if day_bonus > 0: bonus_str += f" 일봉+{day_bonus}"
                if plunge_bonus > 0: bonus_str += plunge_tag
                if tme_bb_extend > 0: bonus_str += tme_tag
                return {
                    'signal': True,
                    'reason': (f"[Tier-B표준][{grade}][{tz_label}] BB{bb_pos:.0f}% RSI{rsi:.0f}↑ "
                               f"SRSI{srsi_k:.0f}>D BBW{bb_width:.1f}%"
                               f"{vol_tag}{bonus_str} {confirm_5m_tag}"),
                    'entry_price': current['close'],
                    'bb_position': bb_pos,
                    'bb_width_pct': bb_width,
                    'market_grade': grade,
                    'entry_type': 'tier_b',
                }

        # ════════════════════════════════════════
        # 크래시 리커버리 (기존 유지)
        # ════════════════════════════════════════
        if df_5m is not None and len(df_5m) >= 10:
            cr_ok, cr_reason = check_crash_recovery(ticker, df_15m, df_5m)
            if cr_ok:
                score_5m, details_5m = score_5m_bounce(df_5m)
                if score_5m >= 2:
                    detail_str = '+'.join(details_5m)
                    return {
                        'signal': True,
                        'reason': f"[CR][{grade}][{tz_label}] {cr_reason} | 5m({score_5m}점:{detail_str})",
                        'entry_price': current['close'],
                        'bb_position': bb_pos,
                        'bb_width_pct': bb_width,
                        'market_grade': grade,
                        'entry_type': 'crash_recovery',
                    }

        # ════════════════════════════════════════
        # 미충족 — 거절 사유 기록
        # ════════════════════════════════════════
        fail_parts = []
        if bb_pos > tier_b_bb_max:
            fail_parts.append(f"BB{bb_pos:.0f}%>{tier_b_bb_max}%")
        elif bb_width < DIRECT_TIER_B_BBW_MIN:
            fail_parts.append(f"BBW{bb_width:.1f}%<{DIRECT_TIER_B_BBW_MIN}%")
        if not is_bull_candle:
            fail_parts.append("음봉")
        if not rsi_rising:
            fail_parts.append(f"RSI↓{rsi:.0f}")
        elif rsi > DIRECT_TIER_B_RSI_MAX:
            fail_parts.append(f"RSI{rsi:.0f}>{DIRECT_TIER_B_RSI_MAX}")
        if not srsi_golden:
            fail_parts.append(f"SRSI{srsi_k:.0f}<D{srsi_d:.0f}")
        if not vol_ok:
            fail_parts.append(f"볼륨{vol_ratio:.1f}x<{BUY_VOL_RATIO_MIN}")

        base['reason'] = f"조건미충족[{grade}][{tz_label}] {' '.join(fail_parts)}"
        return base

    except Exception as e:
        if DEBUG_MODE:
            print(f"{Colors.RED}[Buy Signal] {ticker} 오류: {e}{Colors.ENDC}")
            traceback.print_exc()
        return {'signal': False, 'reason': f'오류: {e}',
                'entry_price': 0, 'bb_position': 50, 'bb_width_pct': 0}


# ============================================================================
# SECTION 14: ★★★ 매도 신호 v26.0 — 동적 손절 + 가속 손절 + 5분봉
# ============================================================================

def check_accel_stop(df_5m, entry_type='normal'):
    """
    ★ v26.0: 가속 손절 패턴 감지 (5분봉 기반).
    3봉 연속 음봉 + RSI < 임계값 + 직전봉 대비 급락
    → 자연 등락이 아닌 가속 폭락으로 판단

    ★ v28.0: entry_type='trend_momentum' 시 RSI 임계값 높임
             (추세 진입은 모멘텀 소진이 더 빠르므로 민감도 상향)

    Returns: (bool triggered, str reason)
    """
    try:
        if df_5m is None or len(df_5m) < 5:
            return False, ""

        # v28.0: 진입 유형에 따라 RSI 임계값 분기
        rsi_threshold = (TREND_ACCEL_STOP_RSI if entry_type == 'trend_momentum'
                         else ACCEL_STOP_RSI_THRESHOLD)

        consecutive_bear = 0
        for i in range(-1, -min(ACCEL_STOP_CONSECUTIVE_BEAR + 1, len(df_5m)), -1):
            if not df_5m.iloc[i]['is_bull']:
                consecutive_bear += 1
            else:
                break

        if consecutive_bear < ACCEL_STOP_CONSECUTIVE_BEAR:
            return False, ""

        current = df_5m.iloc[-1]
        prev    = df_5m.iloc[-2]

        if current['rsi'] > rsi_threshold:
            return False, ""

        if prev['close'] > 0:
            drop = ((current['close'] - prev['close']) / prev['close']) * 100
            if drop > -ACCEL_STOP_DROP_PCT:
                return False, ""
        else:
            return False, ""

        reason = (f"가속폭락감지! {consecutive_bear}연속음봉 "
                  f"RSI{current['rsi']:.0f}<{rsi_threshold} "
                  f"직전대비{drop:.1f}%")
        return True, reason

    except Exception:
        return False, ""

def sell_signal(df, buy_price, buy_time=None, held_info=None):
    """
    ★★★ v32.0 매도 신호 — 탄력 트레일링 + 동적 목표 + 시간 기반 청산
 
    v31 대비 변경사항:
    ① Step 2: 강제익절 2.5%→5.0% (안전밸브만, 탄력트레일이 주 매도)
    ② Step 2.5: 과매수 조기익절 (유지)
    ③ Step 3: 안전익절 기준 = BBW 연동 동적 목표 (0.8~1.5%)
    ④ Step 4: ★★★ 탄력 트레일링 (구간별 간격 자동 조정)
    ⑤ Step 5: ★ 시간 기반 청산 (16h+수익>0, 24h 무조건)
 
    ════════════════════════════════════════════════════════
    Step 0: 가속 손절 (5분봉 — 최우선)
    Step 1: 동적 손절 (BB Width 연동)
    Step 2: 강제 익절 (5.0% — 긴급 안전밸브)
    Step 2.5: 과매수 조기 익절 (RSI>70+BB>70)
    Step 3: 안전 익절 (BBW 연동 동적 목표)
    Step 4: ★ 탄력 트레일링 (구간별 자동 조정)
    Step 5: ★ 시간 기반 청산
    ════════════════════════════════════════════════════════
    """
    try:
        if df is None or len(df) < 5:
            return {'signal': False, 'reason': '데이터 부족',
                    'exit_price': 0, 'profit_pct': 0, 'bb_position': 50, 'bb_width_pct': 0}
 
        current = df.iloc[-1]
        prev    = df.iloc[-2]
        current_price = current['close']
        profit_pct    = ((current_price - buy_price) / buy_price) * 100
        bb_pos  = current['bb_position']
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
        _min_hold_sec     = p.get('BUY_MIN_HOLD_SEC',      BUY_MIN_HOLD_SEC)
 
        # ★ v32.0: 동적 목표수익률 (BBW 연동)
        entry_bbw = held_info.get('entry_bb_width', bb_width) if held_info else bb_width
        _dynamic_safe_profit = get_dynamic_target_by_bbw(entry_bbw)
        _safe_profit = min(_safe_profit, _dynamic_safe_profit)
 
        _entry_type = held_info.get('entry_type', 'normal') if held_info else 'normal'
        if _entry_type == 'night_momentum':
            _force_profit = min(_force_profit, NIGHT_FORCE_PROFIT)
 
        # 동적 손절
        _dynamic_stop = calculate_dynamic_stop_loss(entry_bbw, grade_str)
 
        base = {
            'signal': False, 'exit_price': current_price,
            'profit_pct': profit_pct, 'bb_position': bb_pos,
            'bb_width_pct': bb_width, 'reason': ''
        }
 
        # 보유 시간 계산
        elapsed_sec = 0
        elapsed_hours = 0
        min_hold_active = False
        if buy_time:
            elapsed_sec = (datetime.now() - buy_time).total_seconds()
            elapsed_hours = elapsed_sec / 3600
            if elapsed_sec < _min_hold_sec:
                min_hold_active = True
 
        # ── 5분봉 데이터 ──
        ticker = held_info.get('ticker', '') if held_info else ''
        df_5m = None
        if ticker:
            df_5m = get_candles_5m(ticker)
 
        # ════════════════════════════════════════
        # Step 0: 가속 손절 (최우선)
        # ════════════════════════════════════════
        if df_5m is not None:
            accel_triggered, accel_reason = check_accel_stop(df_5m, _entry_type)
            if accel_triggered and profit_pct < 0:
                return {**base, 'signal': True,
                        'reason': f'{accel_reason} 수익{profit_pct:.2f}%[{grade_str}]'}
 
        # ════════════════════════════════════════
        # Step 1: 동적 손절 (보유시간 무시)
        # ════════════════════════════════════════
        if profit_pct <= _dynamic_stop:
            return {**base, 'signal': True,
                    'reason': f'동적손절({profit_pct:.2f}%≤{_dynamic_stop:.1f}% '
                              f'BBW{entry_bbw:.1f}%)[{grade_str}]'}
 
        # 최소 보유 시간 중 나머지 스킵
        if min_hold_active:
            remaining = int((_min_hold_sec - elapsed_sec) / 60) + 1
            base['reason'] = f'최소보유 대기({remaining}분, 수익{profit_pct:.2f}%)'
            return base
 
        # ════════════════════════════════════════
        # Step 2: 강제 익절 (v32: 5.0% — 긴급 안전밸브만)
        # ════════════════════════════════════════
        if profit_pct >= _force_profit:
            return {**base, 'signal': True,
                    'reason': f'강제익절({profit_pct:.2f}%≥{_force_profit}%)[{grade_str}]'}
 
        # ════════════════════════════════════════
        # Step 2.5: 과매수 조기 익절 (RSI>70+BB>70)
        # ════════════════════════════════════════
        if (profit_pct >= _safe_profit and
            current['rsi'] >= SELL_FAST_RSI_THRESH and
            bb_pos >= SELL_FAST_BB_MIN):
            return {**base, 'signal': True,
                    'reason': (f'과매수조기익절({profit_pct:.2f}% '
                               f'RSI{current["rsi"]:.0f}≥{SELL_FAST_RSI_THRESH} '
                               f'BB{bb_pos:.0f}%≥{SELL_FAST_BB_MIN}%)[{grade_str}]')}
 
        # ════════════════════════════════════════
        # Step 3: 안전 익절 (v32: BBW 연동 동적 목표)
        # ════════════════════════════════════════
        if profit_pct >= _safe_profit:
            rsi_dropping = current['rsi'] < prev['rsi']
            bb_high      = bb_pos >= _safe_bb_min
 
            _5m_confirm = False
            _5m_srsi_dead = False
            if df_5m is not None and len(df_5m) >= 3:
                c5  = df_5m.iloc[-1]
                p1_5 = df_5m.iloc[-2]
                if c5['rsi'] < p1_5['rsi']:
                    _5m_confirm = True
                if (c5.get('srsi_k', 50) < c5.get('srsi_d', 50) and
                    p1_5.get('srsi_k', 50) >= p1_5.get('srsi_d', 50)):
                    _5m_srsi_dead = True
 
            if rsi_dropping and bb_high:
                reasons = [f"RSI↓{current['rsi']:.0f}", f"BB{bb_pos:.0f}%≥{_safe_bb_min}%"]
                if _5m_confirm:
                    reasons.append("5mRSI↓")
                if _5m_srsi_dead:
                    reasons.append("5mSRSI데드")
                return {**base, 'signal': True,
                        'reason': f'안전익절({profit_pct:.2f}%≥{_safe_profit:.1f}% {"+".join(reasons)})[{grade_str}]'}
 
            if _5m_srsi_dead and profit_pct >= _safe_profit * 1.1:
                if df_5m is not None:
                    _5m_bb = df_5m.iloc[-1].get('bb_position', 50)
                    if _5m_bb >= 70:
                        return {**base, 'signal': True,
                                'reason': (f'SRSI데드익절({profit_pct:.2f}% '
                                           f'5mSRSI데드 5mBB{_5m_bb:.0f}%)[{grade_str}]')}
 
            if _5m_confirm and profit_pct >= _safe_profit * 1.2:
                if df_5m is not None:
                    _5m_bb = df_5m.iloc[-1].get('bb_position', 50)
                    if _5m_bb >= 75:
                        return {**base, 'signal': True,
                                'reason': (f'5m안전익절({profit_pct:.2f}%, '
                                           f'5mBB{_5m_bb:.0f}% 5mRSI↓)[{grade_str}]')}
 
        # ════════════════════════════════════════
        # ★ Step 4: v32.0 탄력 트레일링
        # 수익 구간별 간격 자동 조정 — 큰 수익 끝까지 타기
        # ════════════════════════════════════════
        if held_info:
            peak_price = held_info.get('peak_price', buy_price)
            if peak_price > buy_price:
                peak_profit = ((peak_price - buy_price) / buy_price) * 100
                drawdown_from_peak = ((peak_price - current_price) / peak_price) * 100
 
                trail_gap = calc_elastic_trail_gap(peak_profit)
 
                if trail_gap is not None:
                    # trail_gap은 음수 (-0.3, -0.5 등), drawdown은 양수
                    if drawdown_from_peak >= abs(trail_gap):
                        _5m_declining = False
                        if df_5m is not None and len(df_5m) >= 3:
                            if (df_5m.iloc[-1]['close'] < df_5m.iloc[-2]['close'] and
                                    df_5m.iloc[-2]['close'] < df_5m.iloc[-3]['close']):
                                _5m_declining = True
 
                        _5m_tag = " 5m↓확인" if _5m_declining else ""
                        return {**base, 'signal': True,
                                'reason': (f'탄력트레일(고점{peak_profit:.1f}%→{profit_pct:.1f}%, '
                                           f'-{drawdown_from_peak:.1f}%≥{abs(trail_gap):.1f}%{_5m_tag})[{grade_str}]')}
 
        # ════════════════════════════════════════
        # ★ Step 5: v32.0 시간 기반 청산
        # ════════════════════════════════════════
        if buy_time:
            # 16시간 후 + 수익 > 0 → 시장가 청산
            if elapsed_hours >= HOLD_PROFIT_EXIT_HOURS and profit_pct > 0:
                return {**base, 'signal': True,
                        'reason': (f'시간청산({elapsed_hours:.1f}h≥{HOLD_PROFIT_EXIT_HOURS}h '
                                   f'수익{profit_pct:.2f}%>0)[{grade_str}]')}
 
            # 24시간 후 → 무조건 청산
            if elapsed_hours >= HOLD_MAX_EXIT_HOURS:
                return {**base, 'signal': True,
                        'reason': (f'만료청산({elapsed_hours:.1f}h≥{HOLD_MAX_EXIT_HOURS}h '
                                   f'수익{profit_pct:.2f}%)[{grade_str}]')}
 
        # 홀드
        trail_info = ""
        if profit_pct > 0 and held_info:
            peak_price = held_info.get('peak_price', buy_price)
            peak_profit = ((peak_price - buy_price) / buy_price) * 100
            trail_gap = calc_elastic_trail_gap(peak_profit)
            trail_gap_str = f"T{abs(trail_gap):.1f}%" if trail_gap else "미활성"
            trail_info = f" | 고점{peak_profit:.1f}% 트레일{trail_gap_str}"
 
        stop_info = f" | 손절{_dynamic_stop:.1f}%"
        night_tag = " [야간]" if _entry_type == 'night_momentum' else ""
        time_tag = f" | {elapsed_hours:.1f}h" if buy_time else ""
        target_tag = f" | 목표{_safe_profit:.1f}%"
        base['reason'] = (f'홀드(수익{profit_pct:.2f}%, BB{bb_pos:.0f}%'
                          f'{trail_info}{stop_info}{target_tag}{time_tag}{night_tag})[{grade_str}]')
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
# SECTION 16-B: ★ v33.1 가격 예측 필터 함수
# ============================================================================

def get_cached_prediction(ticker):
    """
    ★ v33.1: 가격 예측 결과 조회 (캐시 + 타임아웃 + fail-safe)

    Returns:
        {
          'signal': 'BUY' / 'SELL' / 'NEUTRAL',
          'confidence': 'HIGH' / 'MID' / 'LOW',
          'ok': True/False,
          'source': 'cache' / 'live' / 'error',
          'detail': { t+1 ~ t+5 상세 }
        }
    """
    # 마스터 스위치 체크
    if not PREDICTOR_ENABLED or not PREDICTOR_AVAILABLE:
        return {'signal': 'NEUTRAL', 'confidence': 'LOW', 'ok': False,
                'source': 'disabled', 'detail': {}}

    now = time.time()

    # 캐시 확인
    with prediction_cache_lock:
        cached = prediction_cache.get(ticker)
        if cached and (now - cached['timestamp']) < PREDICTOR_CACHE_TTL_SEC:
            with predictor_stats_lock:
                predictor_stats['cache_hits'] += 1
            return {
                'signal': cached['signal'],
                'confidence': cached['confidence'],
                'ok': cached['ok'],
                'source': 'cache',
                'detail': cached.get('detail', {}),
            }

    # 라이브 호출 (타임아웃 적용)
    with predictor_stats_lock:
        predictor_stats['total_calls'] += 1

    result = {'signal': 'NEUTRAL', 'confidence': 'LOW', 'ok': False,
              'source': 'error', 'detail': {}}

    try:
        pred_result = [None]
        pred_error  = [None]

        def _call_prediction():
            try:
                pred_result[0] = _raw_get_prediction(ticker)
            except Exception as e:
                pred_error[0] = str(e)

        t = threading.Thread(target=_call_prediction, daemon=True)
        t.start()
        t.join(timeout=PREDICTOR_TIMEOUT_SEC)

        if t.is_alive():
            if DEBUG_MODE:
                coin_nm = ticker.replace('KRW-', '')
                print(f"{Colors.YELLOW}[Predictor] {coin_nm} 타임아웃 ({PREDICTOR_TIMEOUT_SEC}초){Colors.ENDC}")
            with predictor_stats_lock:
                predictor_stats['error_count'] += 1
            result['source'] = 'timeout'

        elif pred_error[0]:
            if DEBUG_MODE:
                coin_nm = ticker.replace('KRW-', '')
                print(f"{Colors.YELLOW}[Predictor] {coin_nm} 오류: {pred_error[0]}{Colors.ENDC}")
            with predictor_stats_lock:
                predictor_stats['error_count'] += 1
            result['source'] = 'error'

        elif pred_result[0] and pred_result[0].get('ok'):
            pr = pred_result[0]
            result = {
                'signal': pr.get('signal', 'NEUTRAL'),
                'confidence': pr.get('confidence', 'LOW'),
                'ok': True,
                'source': 'live',
                'detail': {k: v for k, v in pr.items() if k.startswith('t+')},
            }
        else:
            if DEBUG_MODE:
                coin_nm = ticker.replace('KRW-', '')
                print(f"{Colors.YELLOW}[Predictor] {coin_nm} 예측 실패 (ok=False){Colors.ENDC}")
            with predictor_stats_lock:
                predictor_stats['error_count'] += 1
            result['source'] = 'model_fail'

    except Exception as e:
        if DEBUG_MODE:
            coin_nm = ticker.replace('KRW-', '')
            print(f"{Colors.RED}[Predictor] {coin_nm} 예외: {e}{Colors.ENDC}")
        with predictor_stats_lock:
            predictor_stats['error_count'] += 1

    # 캐시 저장 (성공/실패 모두 — 실패도 캐싱하여 반복 호출 방지)
    with prediction_cache_lock:
        prediction_cache[ticker] = {
            'signal': result['signal'],
            'confidence': result['confidence'],
            'ok': result['ok'],
            'timestamp': now,
            'detail': result.get('detail', {}),
        }

    return result


def check_prediction_filter(ticker, entry_type='normal'):
    """
    ★ v33.1: 매수 전 예측 필터 적용

    Returns:
        (should_buy: bool, prediction_tag: str, score_bonus: int)
    """
    if not PREDICTOR_ENABLED or not PREDICTOR_AVAILABLE:
        return True, "", 0

    coin_name = ticker.replace('KRW-', '')
    pred = get_cached_prediction(ticker)

    signal     = pred['signal']
    confidence = pred['confidence']
    ok         = pred['ok']
    source     = pred['source']

    # ── 오류/타임아웃: fail-safe 통과 ──
    if not ok:
        with predictor_stats_lock:
            predictor_stats['pass_count'] += 1
        tag = f"[예측:N/A({source})]"
        if DEBUG_MODE:
            print(f"{Colors.YELLOW}[Predictor] {coin_name} {tag} → fail-safe 통과{Colors.ENDC}")
        return True, tag, 0

    # ── SELL 신호: 매수 차단 (veto) ──
    if signal == 'SELL' and PREDICTOR_VETO_ON_SELL:
        with predictor_stats_lock:
            predictor_stats['veto_count'] += 1
        tag = f"[예측:SELL🔴 {confidence}]"
        if DEBUG_MODE:
            print(f"{Colors.RED}[Predictor] {coin_name} {tag} → ★매수 차단 (veto){Colors.ENDC}")
        return False, tag, 0

    # ── BUY 신호: 점수 보너스 부여 ──
    if signal == 'BUY' and PREDICTOR_BONUS_ON_BUY:
        with predictor_stats_lock:
            predictor_stats['boost_count'] += 1
        bonus = PREDICTOR_BUY_SCORE_BONUS
        tag = f"[예측:BUY🟢 {confidence} +{bonus}점]"
        if DEBUG_MODE:
            print(f"{Colors.GREEN}[Predictor] {coin_name} {tag} → 적극 매수{Colors.ENDC}")
        return True, tag, bonus

    # ── NEUTRAL 신호: 기존 로직 유지 ──
    with predictor_stats_lock:
        predictor_stats['pass_count'] += 1
    tag = f"[예측:NEUTRAL⚪ {confidence}]"
    if DEBUG_MODE:
        print(f"{Colors.BLUE}[Predictor] {coin_name} {tag} → 기존 로직 유지{Colors.ENDC}")
    return True, tag, 0


def get_predictor_status_str():
    """모니터 스레드/Discord 보고용 예측기 상태 문자열"""
    if not PREDICTOR_ENABLED:
        return "예측기: OFF"
    if not PREDICTOR_AVAILABLE:
        return "예측기: 미설치"

    with predictor_stats_lock:
        st = predictor_stats.copy()

    total = st['total_calls']
    if total == 0:
        return "예측기: ON (호출 0회)"

    hit_rate = (st['cache_hits'] / (total + st['cache_hits'])) * 100 if (total + st['cache_hits']) > 0 else 0
    return (
        f"예측기: ON | "
        f"호출:{total} 캐시:{hit_rate:.0f}% | "
        f"차단:{st['veto_count']} 부스트:{st['boost_count']} "
        f"패스:{st['pass_count']} 오류:{st['error_count']}"
    )



# ============================================================================
# SECTION 17: 매수 스레드 (v33.1: 가격예측 필터 연동)
# ============================================================================

def buy_thread_worker():
    """
    ★ v33.1: 가격 예측 필터 연동
    변경점:
      ① 직접 스캔 경로: buy_signal() → 예측 필터 → execute_buy()
      ② TME 경로: buy_signal_trend() → 예측 필터 → execute_buy()
      ③ 예측 SELL → 매수 차단 (veto), BUY → 사유 태그 반영
    """
    print(f"{Colors.GREEN}[Thread 1] 매수 스레드 시작 ({BUY_THREAD_INTERVAL}초 주기){Colors.ENDC}")
    print(f"{Colors.GREEN}  ├ 급락 스캐너: PlungeScore + 감속 패턴 (v27.0){Colors.ENDC}")
    print(f"{Colors.GREEN}  ├ 추세 스캐너: Trend Momentum Entry (v28.0 신규){Colors.ENDC}")
    print(f"{Colors.GREEN}  ├ 듀얼 타임프레임: 15m(위치) + 5m(타이밍){Colors.ENDC}")
    print(f"{Colors.GREEN}  ├ 크래시 리커버리: 폭락→반등 전환 감지{Colors.ENDC}")
    pred_on = 'ON' if PREDICTOR_ENABLED and PREDICTOR_AVAILABLE else 'OFF'
    print(f"{Colors.GREEN}  ├ ★ 가격예측 필터: v5.1 연동 ({pred_on}){Colors.ENDC}")
    print(f"{Colors.GREEN}  └ KRW < 5,000원 시 매수 스캔 자동 차단{Colors.ENDC}")

    iteration = 0
    last_no_cash_log = 0

    while not stop_event.is_set():
        try:
            iteration += 1

            # ★ 급락/추세 스캐너 (보조 보너스용으로 유지)
            run_sharp_drop_scanner()
            run_trend_momentum_scanner()

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

            now = datetime.now()
            block_start = now.replace(hour=BUY_BLOCK_START_HOUR, minute=BUY_BLOCK_START_MINUTE, second=0)
            block_end   = now.replace(hour=BUY_BLOCK_END_HOUR,   minute=BUY_BLOCK_END_MINUTE,   second=0)
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
            update_market_grade()

            if DEBUG_MODE and iteration % 6 == 0:
                with watchlist_lock:
                    wl_count = len(sharp_drop_watchlist)
                with trend_watchlist_lock:
                    tme_count = len(trend_watchlist)
                pred_status = get_predictor_status_str()
                print(f"{Colors.MAGENTA}[BUY] KRW:{krw_balance_now:,.0f}원 | "
                      f"{get_grade_display_str()} | "
                      f"급락보너스:{wl_count}종 추세보너스:{tme_count}종 | "
                      f"{pred_status}{Colors.ENDC}")

            # ══════════════════════════════════════════════
            # ★★★ v31.0: 직접 스캔 방식 — 코인 순차 검토
            # ★★★ v33.1: 가격 예측 필터 추가
            # ══════════════════════════════════════════════
            for ticker in FIXED_STABLE_COINS:
                if stop_event.is_set():
                    return

                with held_coins_lock:
                    if ticker in held_coins:
                        continue

                # 쿨다운 체크 (재진입 방지)
                can_enter, cooldown_reason = check_reentry_cooldown(ticker)
                if not can_enter:
                    continue

                # ★ v31.0: buy_signal() 직접 호출 (감시목록 게이트 제거!)
                sig = buy_signal(ticker)

                if sig['signal']:
                    coin_name  = ticker.replace('KRW-', '')
                    entry_type = sig.get('entry_type', 'normal')

                    # ════════════════════════════════════
                    # ★ v33.1: 가격 예측 필터 적용
                    # ════════════════════════════════════
                    pred_ok, pred_tag, pred_bonus = check_prediction_filter(ticker, entry_type)

                    if not pred_ok:
                        # SELL veto → 매수 차단
                        print(f"{Colors.RED}[BUY] {coin_name} 매수 차단 — {pred_tag}{Colors.ENDC}")
                        if PREDICTOR_LOG_DISCORD:
                            send_discord_message(
                                f"🔴 **{coin_name} 매수 차단** {pred_tag}\n"
                                f"  원래 신호: {sig.get('reason', '')[:60]}"
                            )
                        continue
                    # ════════════════════════════════════

                    # 예측 태그를 매수 사유에 추가
                    if pred_tag:
                        sig['reason'] = f"{pred_tag} {sig['reason']}"

                    # 진입 유형별 태그
                    type_tags = {
                        'tier_a': '🎯Tier-A',
                        'tier_b': '📊Tier-B',
                        'tier_c': '🔄Tier-C',
                        'crash_recovery': '💥CR',
                        'night_momentum': '🌙야간',
                    }
                    entry_tag = type_tags.get(entry_type, f'📈{entry_type}')

                    print(f"\n{Colors.CYAN}{'='*55}")
                    print(f"[BUY SIGNAL] {entry_tag} {coin_name} 매수!")
                    print(f"{'='*55}{Colors.ENDC}")
                    print(f"  📊 BB: {sig['bb_position']:.1f}% | 폭: {sig['bb_width_pct']:.1f}%")
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

            # ══════════════════════════════════════════════
            # ★ v31.0: TME 추세 경로 + v33.1 예측 필터
            # ══════════════════════════════════════════════
            with held_coins_lock:
                managed_count = sum(1 for info in held_coins.values() if info.get('managed', True))
            if managed_count >= MAX_HOLDINGS:
                time.sleep(BUY_THREAD_INTERVAL)
                continue

            # TME 경로: bull_score 높은 경우에만 활성화
            try:
                snapshot = _cached_snapshot if _cached_snapshot else {}
                if snapshot:
                    bull_score, _ = calc_bull_market_score(snapshot)
                else:
                    bull_score = 0.0
            except Exception:
                bull_score = 0.0

            if bull_score >= TREND_BULL_SCORE_MIN:
                for ticker in FIXED_STABLE_COINS:
                    if stop_event.is_set():
                        return

                    with held_coins_lock:
                        if ticker in held_coins:
                            continue

                    # TME는 기존 buy_signal_trend() 호출
                    in_trend, trend_info = is_in_trend_watchlist(ticker)
                    if not in_trend:
                        continue

                    # 늦은 진입 차단
                    if trend_info:
                        detected_price = trend_info.get('detected_price', 0)
                        cur_price_now  = get_current_price(ticker) or 0
                        if detected_price > 0 and cur_price_now > 0:
                            advance = (cur_price_now - detected_price) / detected_price * 100
                            if advance > TREND_MAX_ADVANCE_PCT:
                                continue

                    can_enter, cooldown_reason = check_reentry_cooldown(ticker)
                    if not can_enter:
                        continue

                    sig = buy_signal_trend(ticker, trend_info)

                    if sig['signal']:
                        coin_name = ticker.replace('KRW-', '')

                        # ════════════════════════════════════
                        # ★ v33.1: TME 경로에도 예측 필터 적용
                        # ════════════════════════════════════
                        pred_ok, pred_tag, pred_bonus = check_prediction_filter(ticker, 'tme')

                        if not pred_ok:
                            print(f"{Colors.RED}[BUY] TME {coin_name} 매수 차단 — {pred_tag}{Colors.ENDC}")
                            if PREDICTOR_LOG_DISCORD:
                                send_discord_message(
                                    f"🔴 **TME {coin_name} 매수 차단** {pred_tag}\n"
                                    f"  원래 신호: {sig.get('reason', '')[:60]}"
                                )
                            continue
                        # ════════════════════════════════════

                        if pred_tag:
                            sig['reason'] = f"{pred_tag} {sig['reason']}"

                        print(f"\n{Colors.GREEN}{'='*55}")
                        print(f"[BUY SIGNAL] 📈TME {coin_name} 추세진입!")
                        print(f"{'='*55}{Colors.ENDC}")
                        print(f"  📊 BB: {sig['bb_position']:.1f}% | 폭: {sig['bb_width_pct']:.1f}%")
                        print(f"  💰 진입가: {sig['entry_price']:,.0f}원")
                        print(f"  📝 사유: {sig['reason']}")
                        print(f"{Colors.GREEN}{'='*55}{Colors.ENDC}\n")

                        success = execute_buy(ticker, sig)
                        if success:
                            print(f"{Colors.GREEN}[BUY] {coin_name} 추세 매수 완료!{Colors.ENDC}")
                            with trend_watchlist_lock:
                                trend_watchlist.pop(ticker, None)
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

        num_coins = len(FIXED_STABLE_COINS)
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
        # ★ v33.0: 코인 수에 맞게 동적 기준 적용
        bull_majority = (num_coins + 1) // 2 + 1   # 과반+1: 3코인→3, 7코인→5
        bull_minority = max(1, num_coins // 3)       # 소수: 3코인→1, 7코인→2
        if pos_count >= bull_majority: mkt_score += 2
        elif pos_count >= (num_coins + 1) // 2: mkt_score += 1
        elif pos_count <= bull_minority: mkt_score -= 1
        if avg_bbw > 3.0: mkt_score += 1
        elif avg_bbw < 1.5: mkt_score -= 1
        if valid > 0 and ema_up >= max(2, (num_coins + 1) // 2): mkt_score += 1

        mkt_emoji = {True: '🟢🟢'}.get(mkt_score >= 3,
                     {True: '🟢'}.get(mkt_score >= 1,
                     {True: '🟡'}.get(mkt_score >= 0,
                     {True: '🟠'}.get(mkt_score >= -1, '🔴'))))

        mkt_section = (
            f"\n\n🌡️ **시장** [{mkt_score:+d}점{mkt_emoji}] "
            f"평균`{daily_avg:+.1f}%` 양봉`{pos_count}/{num_coins}` BBW`{avg_bbw:.1f}%`"
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
                if st['in_watchlist']:
                    de = f"🔍{st['wl_score']:.0f}"
                elif st.get('in_trend_watchlist', False):
                    de = f"📈{st.get('trend_bull_score', 0.0):.1f}"
                else:
                    de = '🟢' if st['is_bullish'] else '🔴'
                watch_section += (
                    f"\n{de}`{cn:>4} {st.get('cur_price_str', '-'):>7} "
                    f"{st['d_change']:+.1f}% {st['bb15']:2.0f} "
                    f"{st['bw15']:3.1f} {st['rsi15']:2.0f} "
                    f"{st['srsi_k']:2.0f}{st['srsi_direction']}`"
                )

        # ★ v33.1: 예측기 통계 섹션
        pred_section = ""
        if PREDICTOR_ENABLED and PREDICTOR_AVAILABLE:
            with predictor_stats_lock:
                ps = predictor_stats.copy()
            total_pred = ps['total_calls']
            if total_pred > 0:
                cache_total = total_pred + ps['cache_hits']
                cache_pct = (ps['cache_hits'] / cache_total * 100) if cache_total > 0 else 0
                pred_section = (
                    f"\n\n🔮 **예측기 v5.1**"
                    f"\n`호출:{total_pred} 캐시:{cache_pct:.0f}% "
                    f"차단:{ps['veto_count']} 부스트:{ps['boost_count']} "
                    f"패스:{ps['pass_count']} 오류:{ps['error_count']}`"
                )
                # 캐시에 있는 최근 예측 결과 표시
                with prediction_cache_lock:
                    pc = prediction_cache.copy()
                if pc:
                    pred_lines = []
                    for tk in FIXED_STABLE_COINS:
                        if tk in pc and pc[tk].get('ok'):
                            cn = tk.replace('KRW-', '')
                            sig_str = pc[tk]['signal']
                            conf_str = pc[tk]['confidence']
                            sig_icon = {'BUY': '🟢', 'SELL': '🔴', 'NEUTRAL': '⚪'}.get(sig_str, '⚪')
                            age = int(time.time() - pc[tk]['timestamp'])
                            pred_lines.append(f"{sig_icon}{cn}:{sig_str}({conf_str}) {age}초전")
                    if pred_lines:
                        pred_section += f"\n`{'  '.join(pred_lines)}`"
            else:
                pred_section = f"\n\n🔮 **예측기 v5.1** `대기중 (호출 0회)`"

        msg = f"\n{'─'*25}\n{header}{mkt_section}{hold_section}{watch_section}{pred_section}\n{'─'*25}"
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

            # ★ v33.1: 가격 예측기 상태 표시
            print(f"  {get_predictor_status_str()}")

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
        f"**WebSocket:** `{'✅ 연결됨' if ws_ok else '⏳ 연결 중'}`\n"
        f"**가격예측:** `{'✅ v5.1 연동' if PREDICTOR_ENABLED and PREDICTOR_AVAILABLE else '❌ 비활성'}`\n\n"
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