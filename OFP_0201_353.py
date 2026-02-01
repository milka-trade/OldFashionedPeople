#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
================================================================================
EVOLUTION v7.8 "ADAPTIVE MARKET HUNTER" - 매수 로직 개선안
================================================================================

[v7.8 핵심 개선사항]
1. 시장 상황 자동 감지: SURGE(급등) / CRASH(급락) / NORMAL(평균)
2. 상황별 최적화된 4가지 매수 모드:
   - SURGE_PULLBACK: 급등장 눌림목 매수
   - CRASH_REVERSAL: 급락장 반등 포착
   - NORMAL_BOTTOM: 평균장 하단 반등
   - MOMENTUM_BREAK: 돌파 모멘텀 매수
3. 적응형 점수 시스템: 시장 상황에 따른 가중치 조정
4. 기존 안전장치 100% 유지

[예상 효과]
- 매수 빈도: 기존 대비 3~4배 증가
- 승률 목표: 55~65% 유지
- 평균 수익: 1.5~2.5%
"""

import os
from dotenv import load_dotenv
load_dotenv()

import pyupbit
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
VERSION = "7.6 UPPER_BAND_MASTER"

FIXED_STABLE_COINS = [
    "KRW-ETH", "KRW-XRP", "KRW-SOL",
    "KRW-ADA", "KRW-LINK", "KRW-BCH", "KRW-SUI"
]

POSITION_SIZE_RATIO = 1
MAX_HOLDINGS = 1
# FULL_INVEST_THRESHOLD = 0.55
# MIN_CASH_RESERVE = 1000
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
# [v7.6+] Daily BB Filter Settings - ENHANCED
# ========================================
# 기존 95% 단순 차단 → 80%+ AND 음봉 복합 조건으로 개선
# - 상승 모멘텀 유지 시 매수 허용 (양봉)
# - 하락 전환 시에만 매수 차단 (음봉)
DAILY_BB_HIGH_FILTER = 60            # 일봉 BB 60% 이상에서 복합 조건 적용
DAILY_BB_CACHE_TTL = 60              # 일봉 데이터 1분 캐싱 (실시간성 강화)
DAILY_BB_FILTER_ENABLED = True       # 필터 활성화
DAILY_BB_NEUTRAL_THRESHOLD = 0.3     # 중립 구간: 시가 대비 ±0.3% 이내

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

# [v7.6 Sell Strategy - UPPER BAND MASTER]
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

# ========================================
# [v7.7] SURGE MODE (급등 모드) Settings
# ========================================
# 급등 모드 진입 조건
SURGE_MODE_DAILY_BB_MIN = 65          # 일봉 BB 최소 위치 (%)
SURGE_MODE_DAILY_CHANGE_MIN = 1.0     # 당일 최소 등락률 (%)
SURGE_MODE_BULLISH_COUNT = 2          # 최소 양봉 개수 (최근 3봉 중)

# 급등 모드 긴급 탈출 조건
SURGE_EXIT_BB_DROP = 80               # BB 이 값 아래로 하락 시 탈출
SURGE_EXIT_PROFIT_DRAWDOWN = 1.5      # 진입 대비 수익률 하락폭 (%)
SURGE_EXIT_RSI_DROP = 5               # RSI 하락폭 (포인트)
SURGE_EXIT_CONSECUTIVE_BEAR = 2       # 연속 음봉 수
SURGE_MAX_HOLD_MINUTES = 45           # 최대 관찰 시간 (분)

# 급등 모드 트레일링 스탑
SURGE_TRAILING_PROFIT = 5.0           # 트레일링 시작 수익률 (%)
SURGE_TRAILING_DRAWDOWN = 0.5         # 트레일링 드로다운 허용폭 (%)

# Legacy Compatibility
V70_BB_HIGH_EXIT = V76_BB_SAFE_ZONE
V70_MAX_RSI = V76_MAX_RSI
V70_CONSECUTIVE_BEAR = V76_CONSECUTIVE_BEAR
V70_STOP_LOSS_PCT = V76_STOP_LOSS_PCT
V70_STOP_LOSS_BB = V76_STOP_LOSS_BB
V70_MIN_PROFIT_TARGET = V76_MIN_PROFIT_TARGET


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
    'DEFAULT': 10
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
# [v7.7] BOTTOM REVERSAL Settings (🆕 추가)
# ========================================

# Zone 1: EXTREME_BOTTOM (일봉 BB ≤15%)
EXTREME_BOTTOM_DAILY_BB_MAX = 15         # 일봉 BB 상한
EXTREME_BOTTOM_15M_BB_MAX = 30           # 15분봉 BB 상한
EXTREME_BOTTOM_MIN_SCORE = 68            # 최소 점수
EXTREME_BOTTOM_BONUS = 20                # 보너스 점수
EXTREME_BOTTOM_MIN_CHANGE = 0.5          # 최소 등락률 (%)

# Zone 2: BOTTOM (일봉 BB 16~30%)
BOTTOM_DAILY_BB_MIN = 16                 # 일봉 BB 하한
BOTTOM_DAILY_BB_MAX = 30                 # 일봉 BB 상한
BOTTOM_15M_BB_MAX = 25                   # 15분봉 BB 상한
BOTTOM_MIN_SCORE = 73                    # 최소 점수
BOTTOM_BONUS = 10                        # 보너스 점수
BOTTOM_MIN_CHANGE = 1.0                  # 최소 등락률 (%)

# 공통 안전장치
BOTTOM_MA5_THRESHOLD = 0.95              # 5일 평균 대비 최소 비율
BOTTOM_MAX_RSI_15M = 65                  # 15분봉 최대 RSI
BOTTOM_MIN_VOLUME_RATIO = 0.5            # 최소 거래량 비율

# RSI 보너스
BOTTOM_RSI_BONUS_MIN = 30                # RSI 보너스 하한
BOTTOM_RSI_BONUS_MAX = 40                # RSI 보너스 상한
BOTTOM_RSI_BONUS_SCORE = 5               # RSI 보너스 점수

# # ================================================================================
# # SECTION A: 새로운 파라미터 (기존 파라미터 섹션에 추가)
# # ================================================================================

# # ========================================
# # [v7.8] ADAPTIVE MARKET DETECTION Settings
# # ========================================

# # 시장 상황 감지 임계값
# MARKET_SURGE_DAILY_BB_MIN = 65           # 급등장: 일봉 BB 65% 이상
# MARKET_SURGE_DAILY_CHANGE_MIN = 2.0      # 급등장: 당일 +2% 이상
# MARKET_SURGE_RSI_15M_MIN = 58            # 급등장: 15분 RSI 58 이상

# MARKET_CRASH_DAILY_BB_MAX = 25           # 급락장: 일봉 BB 25% 이하
# MARKET_CRASH_DAILY_CHANGE_MAX = -2.0     # 급락장: 당일 -2% 이하
# MARKET_CRASH_RSI_15M_MAX = 38            # 급락장: 15분 RSI 38 이하

# # ========================================
# # [v7.9] DAILY MOMENTUM GATE 설정 (신규)
# # ========================================
# # 핵심 원칙: 일봉 양봉 확인 없이는 절대 매수 안함

# DAILY_MOMENTUM_GATE_ENABLED = True       # 게이트 활성화

# # BB 위치 구간 정의 (%)
# DAILY_GATE_BB_EXTREME_LOW = 15           # 극저점 상한
# DAILY_GATE_BB_LOW = 30                   # 저점 상한
# DAILY_GATE_BB_MID = 50                   # 하단 상한
# DAILY_GATE_BB_NEUTRAL = 70               # 중립 상한

# # BB 위치별 최소 등락률 요구치 (%)
# DAILY_GATE_MIN_CHANGE_EXTREME = 1.5      # 극저점: 강한 반등 필요
# DAILY_GATE_MIN_CHANGE_LOW = 1.0          # 저점: 반등 확인
# DAILY_GATE_MIN_CHANGE_MID = 0.5          # 하단: 최소 회복
# DAILY_GATE_MIN_CHANGE_NEUTRAL = 0.3      # 중립: 양봉이면 거의 OK
# DAILY_GATE_MIN_CHANGE_HIGH = 0.0         # 상단: 양봉이면 OK

# # 연속 음봉 제한
# DAILY_GATE_MAX_CONSECUTIVE_BEAR = 2      # 연속 음봉 N개 이상이면 매수 금지

# # 게이트 캐시 TTL (초)
# DAILY_GATE_CACHE_TTL = 30                # 30초 캐싱

# # ========================================
# # [v7.8] 모드별 매수 조건
# # ========================================

# # SURGE_PULLBACK (급등장 눌림목)
# SURGE_PULLBACK_BB_MIN = 25               # 15분 BB 하한
# SURGE_PULLBACK_BB_MAX = 50               # 15분 BB 상한
# SURGE_PULLBACK_RSI_MIN = 35              # RSI 하한
# SURGE_PULLBACK_RSI_MAX = 58              # RSI 상한
# SURGE_PULLBACK_MIN_SCORE = 70            # 최소 점수
# SURGE_PULLBACK_CORRECTION_PCT = 1.5      # 최소 조정폭 (%)

# # CRASH_REVERSAL (급락장 반등)
# CRASH_REVERSAL_BB_MIN = 0                # 15분 BB 하한
# CRASH_REVERSAL_BB_MAX = 28               # 15분 BB 상한 (기존 25 → 28 완화)
# CRASH_REVERSAL_RSI_MIN = 15              # RSI 하한
# CRASH_REVERSAL_RSI_MAX = 45              # RSI 상한
# CRASH_REVERSAL_MIN_SCORE = 65            # 최소 점수 (기존 68 → 65 완화)
# CRASH_REVERSAL_MIN_BULLISH = 1           # 최소 양봉 수 (기존 2 → 1 완화)

# # NORMAL_BOTTOM (평균장 하단 반등)
# NORMAL_BOTTOM_BB_MIN = 5                 # 15분 BB 하한
# NORMAL_BOTTOM_BB_MAX = 35                # 15분 BB 상한 (기존 20 → 35 완화)
# NORMAL_BOTTOM_RSI_MIN = 25               # RSI 하한
# NORMAL_BOTTOM_RSI_MAX = 50               # RSI 상한
# NORMAL_BOTTOM_MIN_SCORE = 72             # 최소 점수 (기존 85 → 72 완화)

# # MOMENTUM_BREAK (돌파 모멘텀)
# MOMENTUM_BREAK_BB_MIN = 55               # 15분 BB 하한
# MOMENTUM_BREAK_BB_MAX = 85               # 15분 BB 상한
# MOMENTUM_BREAK_RSI_MIN = 55              # RSI 하한
# MOMENTUM_BREAK_RSI_MAX = 75              # RSI 상한 (과매수 방지)
# MOMENTUM_BREAK_MIN_SCORE = 75            # 최소 점수
# MOMENTUM_BREAK_VOLUME_MIN = 1.8          # 최소 거래량 배수

# # ========================================
# # [v7.8] 적응형 점수 가중치
# # ========================================

# # 기본 점수 배분 (총 100점)
# SCORE_BB_POSITION = 25                   # BB 위치 점수 (기존 30 → 25)
# SCORE_REVERSAL = 25                      # 반전 신호 점수 (기존 30 → 25)
# SCORE_MOMENTUM = 20                      # 모멘텀 점수 (기존 20 유지)
# SCORE_VOLUME = 15                        # 거래량 점수 (기존 10 → 15)
# SCORE_VOLATILITY = 15                    # 변동성 점수 (기존 10 → 15)

# # 시장 상황별 보너스 점수
# SURGE_MODE_BONUS = 10                    # 급등장 보너스
# CRASH_MODE_BONUS = 15                    # 급락장 보너스 (더 높음 - 기회)
# NORMAL_MODE_BONUS = 5                    # 평균장 보너스

# # ========================================
# # [v7.8] 일봉 필터 완화
# # ========================================
# DAILY_BB_HIGH_FILTER_V78 = 70            # 기존 60 → 70 완화
# DAILY_BEARISH_LIMIT = -1.5               # 일봉 음봉 허용 한도 (기존 -0.3% → -1.5%)

# ================================================================================
# [v8.0] MOMENTUM PREDICTION SYSTEM Parameters
# ================================================================================

# ========================================
# [v8.0] 일봉 모멘텀 확인 조건
# ========================================
V80_DAILY_BULLISH_REQUIRED = True      # 일봉 양봉 필수
V80_DAILY_RSI_MIN = 30                 # 일봉 RSI 하한 (과매도 탈출)
V80_DAILY_RSI_MAX = 60                 # 일봉 RSI 상한 (상승 여력)
V80_DAILY_BULLISH_DAYS_MIN = 2         # 최근 3일 중 최소 양봉 수
V80_DAILY_MA20_THRESHOLD = 0.97        # 20일선 대비 최소 비율

# ========================================
# [v8.0] 15분봉 모멘텀 측정 (100점 만점)
# ========================================
V80_MOMENTUM_RSI_WEIGHT = 30           # RSI 모멘텀 배점
V80_MOMENTUM_VOLUME_WEIGHT = 25        # 거래량 모멘텀 배점
V80_MOMENTUM_PRICE_WEIGHT = 25         # 가격 모멘텀 배점
V80_MOMENTUM_VOLATILITY_WEIGHT = 20    # 변동성 모멘텀 배점

# BB 위치별 최소 모멘텀 점수
V80_MOMENTUM_MIN_SCORE_LOW = 60        # BB 30% 이하: 60점 이상
V80_MOMENTUM_MIN_SCORE_MID = 70        # BB 30-45%: 70점 이상
V80_MOMENTUM_MIN_SCORE_HIGH = 80       # BB 45% 이상: 80점 이상

# ========================================
# [v8.0] 매수 가격 위치 조건 (BB 기준)
# ========================================
V80_BUY_BB_MIN = 12                    # BB 하한 (아직 하락 중 제외)
V80_BUY_BB_MAX = 45                    # BB 상한 (이미 상승 제외)
V80_BUY_BB_EXTENDED = 55               # 강한 모멘텀 시 확장 허용
V80_BUY_RSI_MIN = 25                   # RSI 하한
V80_BUY_RSI_MAX = 65                   # RSI 상한

# ========================================
# [v8.0] 진입 트리거 조건
# ========================================
V80_TRIGGER_ENABLED = True             # 트리거 확인 활성화
V80_TRIGGER_MIN_STRENGTH = 70          # 트리거 최소 강도
V80_TRIGGER_VOLUME_SPIKE = 2.0         # 거래량 폭발 배수
V80_TRIGGER_VOLUME_INCREASE = 1.5      # 거래량 증가 배수
V80_TRIGGER_PULLBACK_CONFIRM = True    # 눌림목 확인 활성화
V80_TRIGGER_BREAKOUT_CONFIRM = True    # 돌파 확인 활성화

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



# ================================================================================
# SECTION 8: Startup Message
# ================================================================================

VERSION = "8.0 MOMENTUM_PREDICTION"  # 버전 변경

print(f"\n{Colors.BOLD}{Colors.CYAN}{'='*60}")
print(f"EVOLUTION {VERSION}")
print(f"{'='*60}")
print(f"{Colors.GREEN}[v8.0] MOMENTUM PREDICTION SYSTEM{Colors.ENDC}")
print(f"   [매수] 모멘텀 확인 (60-80점) + BB 12-45% + 트리거")
print(f"   [매도] 상승중 홀드 | 소진 5점 이상 | 트레일링 2%")
print(f"   [손절] -2.5% 빠른 손절")
print(f"")
print(f"{Colors.YELLOW}핵심 철학{Colors.ENDC}")
print(f"   '오르고 있어서'가 아니라 '오를 힘이 있어서' 매수")
print(f"   '상승 중에는 절대 팔지 않는다'")
print(f"")
print(f"{Colors.MAGENTA}THREADED EDITION{Colors.ENDC}")
print(f"   Thread 1: 매수 ({BUY_THREAD_INTERVAL}초)")
print(f"   Thread 2: 매도 ({SELL_THREAD_INTERVAL}초)")
print(f"   Thread 3: 모니터 ({MONITOR_THREAD_INTERVAL}초)")
print(f"{'='*60}{Colors.ENDC}\n")

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
        
        # ========================================
        # [v7.7] buy_mode 표시 추가
        # ========================================
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
    """
    단일 코인 기술적 분석 (일봉 BB 추가)
    [v7.7] BOTTOM REVERSAL 모드 반영
    
    Args:
        ticker: 코인 티커 (예: "KRW-BTC")
    
    Returns:
        dict: 분석 결과 (daily_bb_position 추가)
    """
    try:
        # 15분봉 데이터 조회
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
        
        # BB 폭% 계산
        if bb_lower > 0:
            bb_width_pct = ((bb_upper - bb_lower) / bb_lower) * 100
        else:
            bb_width_pct = 0.0
        
        current_rsi = df.iloc[-1]['RSI']
        
        # ========================================
        # 일봉 BB 위치 조회
        # ========================================
        daily_bb_position = None
        try:
            df_daily = get_candles_daily(ticker, count=50)
            if df_daily is not None and len(df_daily) >= 20:
                df_daily = add_indicators(df_daily)
                if df_daily is not None:
                    daily_bb_position = df_daily.iloc[-1]['bb_position']
        except:
            daily_bb_position = None
        
        # 보유 수익률 확인
        holding_profit = None
        buy_mode = None
        with held_coins_lock:
            if ticker in held_coins:
                buy_price = held_coins[ticker]['buy_price']
                holding_profit = ((current_price - buy_price) / buy_price) * 100
                buy_mode = held_coins[ticker].get('buy_mode', 'NORMAL')
        
        # ========================================
        # [v7.7] 신호 판단 (BOTTOM REVERSAL 반영)
        # ========================================
        signal = "HOLD"
        reason = ""
        
        # BOTTOM REVERSAL 구간 체크
        if daily_bb_position is not None and daily_bb_position <= 30:
            if bb_position <= 25 and current_rsi <= 40:
                signal = "BUY"
                reason = "🔥일봉바닥+15분저점"
            elif bb_position <= 20:
                signal = "BUY"
                reason = "📈일봉하단반전"
        # 일봉 고점 경고
        elif daily_bb_position is not None and daily_bb_position >= DAILY_BB_HIGH_FILTER:
            if bb_position <= 25 and current_rsi <= 35:
                signal = "HOLD"
                reason = "⚠️일봉고점"
            else:
                signal = "HOLD"
                reason = "일봉고점대기"
        # 일반 구간
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
            elif current_rsi <= 30:
                signal = "BUY"
                reason = "과매도구간"
            elif current_rsi >= 75:
                signal = "SELL"
                reason = "과매수구간"
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
            'buy_mode': buy_mode  # ✅ 신규 추가
        }
        
    except Exception as e:
        if DEBUG_MODE:
            print(f"{Colors.RED}[Coin Analysis Error] {ticker}: {e}{Colors.ENDC}")
        return None


def generate_market_summary():
    """
    시장 분석 요약 - 개선된 가독성 (일봉BB 추가, 보유코인 정보 완전화)
    [v7.7] buy_mode 표시 추가
    
    [보유코인] 가격 | 수익 | BB(15분/일봉) | RSI | 신호 | 보유시간
    [관심코인] 가격 | BB(15분/일봉) | RSI | 신호
    """
    try:
        target_coins = set()
        
        with held_coins_lock:
            for ticker in held_coins.keys():
                target_coins.add(ticker)
        
        for coin in FIXED_STABLE_COINS:
            target_coins.add(coin)
        
        held_tickers = []
        fixed_tickers = []
        
        with held_coins_lock:
            for ticker in target_coins:
                if ticker in held_coins:
                    held_tickers.append(ticker)
                else:
                    fixed_tickers.append(ticker)
        
        held_analysis = []
        fixed_analysis = []
        
        for ticker in held_tickers:
            analysis = get_coin_analysis(ticker)
            if analysis:
                # 보유코인 추가 정보: 매수금액, 보유시간
                with held_coins_lock:
                    if ticker in held_coins:
                        hold_info = held_coins[ticker]
                        analysis['buy_amount'] = hold_info.get('buy_amount', 0)
                        analysis['buy_time'] = hold_info.get('buy_time')
                        analysis['buy_price'] = hold_info.get('buy_price', 0)
                held_analysis.append(analysis)
        
        for ticker in fixed_tickers:
            analysis = get_coin_analysis(ticker)
            if analysis:
                fixed_analysis.append(analysis)
        
        message = f"\n{'━'*10}\n📊 **시장현황**\n{'━'*10}"
        
        # 신호별 이모지 매핑
        signal_emoji = {'BUY': '🟢', 'SELL': '🔴', 'HOLD': '🟡'}
        
        # ========================================
        # 보유 코인 분석 (정보 완전화)
        # ========================================
        if held_analysis:
            message += "\n\n**[보유중]**"
            for coin in held_analysis:
                coin_name = coin['ticker'].replace('KRW-', '')
                emoji = signal_emoji.get(coin['signal'], '⚪')
                
                # 일봉 BB 표시
                daily_bb_str = "-"
                daily_warning = ""
                if coin.get('daily_bb_position') is not None:
                    daily_bb = coin['daily_bb_position']
                    daily_bb_str = f"{daily_bb:.0f}%"
                    if daily_bb >= DAILY_BB_HIGH_FILTER:
                        daily_warning = "⚠️"
                    elif daily_bb <= 30:
                        daily_warning = "🔥"
                
                # BB 폭% 표시
                bb_width_str = ""
                if coin.get('bb_width_pct') is not None:
                    bb_width_str = f" [폭{coin['bb_width_pct']:.1f}%]"
                
                # 수익률 및 수익금 계산
                profit_pct = coin.get('holding_profit', 0) or 0
                profit_emoji = "📈" if profit_pct >= 0 else "📉"
                
                # 수익금 계산
                buy_amount = coin.get('buy_amount', 0)
                if buy_amount > 0 and coin.get('buy_price', 0) > 0:
                    current_value = (buy_amount / coin['buy_price']) * coin['price']
                    profit_amount = current_value - buy_amount
                else:
                    profit_amount = 0
                
                # 보유시간 계산
                hold_duration = "-"
                if coin.get('buy_time'):
                    hold_duration = format_duration(datetime.now() - coin['buy_time'])
                
                # ========================================
                # [v7.7] buy_mode 표시 추가
                # ========================================
                mode_emoji = ""
                if coin.get('buy_mode') == 'EXTREME_BOTTOM':
                    mode_emoji = "🔥"
                elif coin.get('buy_mode') == 'BOTTOM':
                    mode_emoji = "📈"
                
                # 2줄 포맷 (정보량 유지 + 가독성)
                # 1줄: 코인명 | 현재가 | 수익률+수익금 | 보유시간
                message += f"\n{profit_emoji} **{coin_name}** {mode_emoji} `{coin['price']:,.0f}원`"
                message += f" | `{profit_pct:+.2f}%` `({profit_amount:+,.0f}원)` | ⏱`{hold_duration}`"
                
                # 2줄: BB(15분/일봉) [폭] | RSI | 매매신호
                message += f"\n└ {emoji} BB `{coin['bb_position']:.0f}%`/D`{daily_warning}{daily_bb_str}`{bb_width_str}"
                message += f" | RSI `{coin['rsi']:.0f}` | {coin['signal']} {coin['reason']}"
        
        # ========================================
        # 관심 코인 분석 (1줄/코인)
        # ========================================
        if fixed_analysis:
            message += "\n\n**[관심코인]**"
            for coin in fixed_analysis:
                coin_name = coin['ticker'].replace('KRW-', '')
                emoji = signal_emoji.get(coin['signal'], '⚪')
                
                # 일봉 BB 표시
                daily_bb_str = "-"
                daily_warning = ""
                if coin.get('daily_bb_position') is not None:
                    daily_bb = coin['daily_bb_position']
                    daily_bb_str = f"{daily_bb:.0f}%"
                    if daily_bb >= DAILY_BB_HIGH_FILTER:
                        emoji = "⚠️"
                        daily_warning = "⚠️"
                    elif daily_bb <= 30:
                        emoji = "🔥"
                        daily_warning = "🔥"
                
                # BB 폭% 표시
                bb_width_str = ""
                if coin.get('bb_width_pct') is not None:
                    bb_width_str = f" [폭{coin['bb_width_pct']:.1f}%]"
                
                # 1줄 포맷
                message += f"\n{emoji} **{coin_name}** `{coin['price']:,.0f}원`"
                message += f" | BB `{coin['bb_position']:.0f}%`/D`{daily_warning}{daily_bb_str}`{bb_width_str}"
                message += f" | RSI `{coin['rsi']:.0f}` | {coin['reason']}"
        
        if not held_analysis and not fixed_analysis:
            message += "\n\n⚠️ 데이터 수집 오류"
        
        return message
        
    except Exception as e:
        if DEBUG_MODE:
            print(f"{Colors.RED}[Market Summary Error] {e}{Colors.ENDC}")
        return f"\n{'━'*10}\n📊 **시장현황**\n{'━'*10}\n\n⚠️ 데이터 수집 오류"


def send_enhanced_statistics_report():
    """
    정시 보고서 - 개선된 가독성 (중복 제거, 시장현황에 통합)
    """
    global total_trades, winning_trades, losing_trades, total_profit
    global daily_buy_count, daily_sell_count, daily_winning_trades, daily_losing_trades
    
    try:
        portfolio = get_enhanced_portfolio_status()
        
        # ━━━━ 자산 요약 (1줄) ━━━━
        asset_line = f"💰 **자산** `총 {portfolio['total_assets']:,.0f}원` | `코인 {portfolio['total_coin_value']:,.0f}원` | `현금 {portfolio['krw_balance']:,.0f}원`"
        
        # ━━━━ 가동시간 + 보유현황 ━━━━
        uptime = datetime.now() - start_time
        hours = int(uptime.total_seconds() / 3600)
        minutes = int((uptime.total_seconds() % 3600) / 60)
        uptime_text = f"⏱ **가동** `{hours}시간 {minutes}분` | 📦 **보유** `{len(portfolio['coins'])}/{MAX_HOLDINGS}`"
        
        # ━━━━ 금일 성과 ━━━━
        if daily_sell_count == 0:
            trade_summary = f"\n🎯 **금일** 매수 `{daily_buy_count}건` | 매도 `0건`"
        else:
            daily_win_rate = (daily_winning_trades / daily_sell_count * 100)
            trade_summary = f"\n🎯 **금일** 매수 `{daily_buy_count}건` | 매도 `{daily_sell_count}건` | 승률 `{daily_win_rate:.0f}%`"
        
        # ━━━━ 누적 성과 ━━━━
        if total_trades == 0:
            stats_text = "\n📈 **누적** 거래없음"
        else:
            with statistics_lock:
                win_rate = (winning_trades / total_trades * 100) if total_trades > 0 else 0
                avg_profit = (total_profit / total_trades) if total_trades > 0 else 0
            stats_text = f"\n📈 **누적** `{total_trades}거래` | 승률 `{win_rate:.0f}%` | 평균 `{avg_profit:+.2f}%`"
        
        # ━━━━ 시장 분석 (보유코인+관심코인 통합) ━━━━
        market_summary = generate_market_summary()
        
        # ━━━━ 최종 메시지 조합 ━━━━
        message = f"""
{'━'*1}
{asset_line}
{'━'*10}

{uptime_text}{trade_summary}{stats_text}
{market_summary}

⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
"""
        
        send_discord_message(message)
        
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
    """Reset daily trade counter"""
    # ============================================================
    # 🆕 MODIFIED: 일일 통계 변수 추가 (1줄 추가)
    # ============================================================
    global daily_trade_count, last_reset_date
    global daily_buy_count, daily_sell_count, daily_winning_trades, daily_losing_trades
    # ============================================================
    
    try:
        today = datetime.now().date()
        if today != last_reset_date:
            daily_trade_count = 0
            # ============================================================
            # 🆕 NEW: 일일 통계 초기화 (4줄 추가)
            # ============================================================
            daily_buy_count = 0
            daily_sell_count = 0
            daily_winning_trades = 0
            daily_losing_trades = 0
            # ============================================================
            last_reset_date = today
            
            # ============================================================
            # 🆕 NEW: 초기화 로그 출력 (1줄 추가)
            # ============================================================
            print(f"{Colors.CYAN}[Reset] 일일 통계 초기화 완료 ({today}){Colors.ENDC}")
            # ============================================================
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
                current_price = pyupbit.get_current_price(ticker)
                
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
                    current_price = pyupbit.get_current_price(ticker)
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
    """Get total balance"""
    portfolio = get_enhanced_portfolio_status()
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
            df = pyupbit.get_ohlcv(ticker, interval="minute5", count=count)
        elif interval == '15':
            df = pyupbit.get_ohlcv(ticker, interval="minute15", count=count)
        elif interval == '60':
            df = pyupbit.get_ohlcv(ticker, interval="minute60", count=count)
        else:
            df = pyupbit.get_ohlcv(ticker, interval="minute15", count=count)
        
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
    """
    일봉 데이터 조회 (캐싱 포함)
    
    백테스팅 검증:
    - 일봉 BB 75% 이상에서 15분봉 하단터치 → 평균 -1.14% 손실
    - 필터 적용 시 +26.64%p 누적 수익 개선
    
    Args:
        ticker: 코인 티커 (예: "KRW-BTC")
        count: 조회할 일봉 개수 (기본 50일)
    
    Returns:
        DataFrame: 일봉 OHLCV 데이터 or None
    """
    try:
        # 캐싱 체크 (일봉은 5분간 캐싱)
        cache_key = f"{ticker}_daily_{count}"
        cached = get_cached_data(cache_key, DAILY_BB_CACHE_TTL)
        
        if cached is not None:
            return cached
        
        # API 호출
        df = pyupbit.get_ohlcv(ticker, interval="day", count=count)
        
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
        
        df = pyupbit.get_ohlcv(ticker, interval="minute15", count=count)
        
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
    [v8.0] 5분봉 100개 수집 (트리거 감지용)
    
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
        
        df = pyupbit.get_ohlcv(ticker, interval="minute5", count=count)
        
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
    """Add all technical indicators"""
    try:
        if df is None or len(df) < BB_PERIOD:
            return None
        
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
        
        # Add uppercase aliases for compatibility
        df['RSI'] = df['rsi']
        df['BB_UPPER'] = df['bb_upper']
        df['BB_LOWER'] = df['bb_lower']
        
        return df
        
    except Exception as e:
        if DEBUG_MODE:
            print(f"{Colors.RED}[Indicator Error] {e}{Colors.ENDC}")
        return None

# ================================================================================
# SECTION 12-A: [v8.0] Momentum Strength Calculation
# ================================================================================

def calculate_momentum_strength(df_15m, df_daily=None):
    """
    [v8.0] 복합 모멘텀 강도 측정 (0-100점)
    
    핵심: "오르고 있다"가 아니라 "오를 힘이 있다"를 측정
    
    구성요소:
    1. RSI 모멘텀 (30점): RSI가 상승 방향인가?
    2. 거래량 모멘텀 (25점): 거래량이 증가하는가?
    3. 가격 모멘텀 (25점): 저점이 높아지는가?
    4. 변동성 모멘텀 (20점): BB가 확장 준비 중인가?
    
    Args:
        df_15m: 15분봉 DataFrame (지표 포함)
        df_daily: 일봉 DataFrame (선택적)
    
    Returns:
        dict: {
            'score': 총점 (0-100),
            'details': 점수 획득 사유 리스트,
            'rsi': 현재 RSI,
            'volume_ratio': 거래량 비율,
            'bb_width': BB 폭
        }
    """
    try:
        score = 0
        details = []
        
        if df_15m is None or len(df_15m) < 20:
            return {'score': 0, 'details': ['데이터 부족'], 'rsi': 50, 'volume_ratio': 1.0, 'bb_width': 2.0}
        
        current = df_15m.iloc[-1]
        prev = df_15m.iloc[-2]
        prev2 = df_15m.iloc[-3] if len(df_15m) >= 3 else prev
        
        # ========================================
        # 1. RSI 모멘텀 (30점)
        # ========================================
        rsi_now = current['rsi']
        rsi_prev = prev['rsi']
        rsi_prev2 = prev2['rsi']
        
        # RSI 연속 상승 체크
        rsi_rising_2 = rsi_now > rsi_prev > rsi_prev2
        rsi_rising_1 = rsi_now > rsi_prev
        rsi_in_recovery = 30 <= rsi_now <= 55  # 회복 구간
        
        if rsi_rising_2 and rsi_in_recovery:
            score += 30
            details.append(f"RSI연속상승+회복구간 {rsi_now:.0f} (+30)")
        elif rsi_rising_2:
            score += 25
            details.append(f"RSI연속상승 {rsi_now:.0f} (+25)")
        elif rsi_rising_1 and rsi_in_recovery:
            score += 20
            details.append(f"RSI상승+회복구간 {rsi_now:.0f} (+20)")
        elif rsi_rising_1:
            score += 12
            details.append(f"RSI상승 {rsi_now:.0f} (+12)")
        elif rsi_in_recovery:
            score += 8
            details.append(f"RSI회복구간 {rsi_now:.0f} (+8)")
        
        # ========================================
        # 2. 거래량 모멘텀 (25점)
        # ========================================
        vol_now = current['volume']
        vol_ma = df_15m['volume'].rolling(20).mean().iloc[-1]
        vol_ratio = vol_now / vol_ma if vol_ma > 0 else 1.0
        
        is_bullish = current['close'] > current['open']
        
        if vol_ratio >= 2.0 and is_bullish:
            score += 25
            details.append(f"거래량폭발+양봉 {vol_ratio:.1f}x (+25)")
        elif vol_ratio >= 1.5 and is_bullish:
            score += 20
            details.append(f"거래량급증+양봉 {vol_ratio:.1f}x (+20)")
        elif vol_ratio >= 1.2 and is_bullish:
            score += 15
            details.append(f"거래량증가+양봉 {vol_ratio:.1f}x (+15)")
        elif vol_ratio >= 1.0:
            score += 8
            details.append(f"거래량양호 {vol_ratio:.1f}x (+8)")
        elif vol_ratio >= 0.7:
            score += 4
            details.append(f"거래량보통 {vol_ratio:.1f}x (+4)")
        
        # ========================================
        # 3. 가격 모멘텀 (25점)
        # ========================================
        # 저점 상승 패턴 (Higher Low)
        low_now = current['low']
        low_prev = prev['low']
        low_prev2 = prev2['low']
        higher_lows = low_now > low_prev and low_prev > low_prev2
        
        # 고점 상승 패턴 (Higher High)
        high_now = current['high']
        high_prev = prev['high']
        higher_highs = high_now > high_prev
        
        # 종가 상승
        close_rising = current['close'] > prev['close'] > prev2['close']
        
        if higher_lows and higher_highs:
            score += 25
            details.append("저고점동시상승 (+25)")
        elif higher_lows and close_rising:
            score += 22
            details.append("저점상승+종가상승 (+22)")
        elif higher_lows:
            score += 18
            details.append("저점상승 (+18)")
        elif higher_highs:
            score += 12
            details.append("고점상승 (+12)")
        elif close_rising:
            score += 10
            details.append("종가연속상승 (+10)")
        elif current['close'] > prev['close']:
            score += 5
            details.append("종가상승 (+5)")
        
        # ========================================
        # 4. 변동성 모멘텀 (20점)
        # ========================================
        bb_width_now = current['bb_width']
        bb_width_prev = prev['bb_width']
        bb_width_avg = df_15m['bb_width'].rolling(20).mean().iloc[-1]
        
        # BB 수렴 후 확장 시작 = 폭발 임박
        was_compressed = bb_width_prev < bb_width_avg * 0.85
        is_expanding = bb_width_now > bb_width_prev
        still_compressed = bb_width_now < bb_width_avg * 0.75
        
        if was_compressed and is_expanding:
            score += 20
            details.append(f"BB확장시작 {bb_width_now:.1f}% (+20)")
        elif is_expanding and bb_width_now > bb_width_avg:
            score += 15
            details.append(f"BB확장중 {bb_width_now:.1f}% (+15)")
        elif still_compressed:
            score += 12
            details.append(f"BB수렴중(폭발대기) {bb_width_now:.1f}% (+12)")
        elif is_expanding:
            score += 8
            details.append(f"BB소폭확장 {bb_width_now:.1f}% (+8)")
        
        return {
            'score': score,
            'details': details,
            'rsi': rsi_now,
            'volume_ratio': vol_ratio,
            'bb_width': bb_width_now,
            'is_bullish': is_bullish
        }
        
    except Exception as e:
        if DEBUG_MODE:
            print(f"{Colors.RED}[Momentum Calc Error] {e}{Colors.ENDC}")
        return {
            'score': 0,
            'details': [f'계산오류: {e}'],
            'rsi': 50,
            'volume_ratio': 1.0,
            'bb_width': 2.0
        }


def check_daily_momentum_confirmed(df_daily):
    """
    [v8.0] 일봉 상승 모멘텀 확인
    
    조건 (모두 충족):
    1. 오늘 양봉 (상승 중)
    2. RSI 30-60 (과매수 아님, 상승 여력)
    3. 20일선 위 또는 근접 (97% 이상)
    4. 최근 3일 중 2일 이상 양봉
    
    Args:
        df_daily: 일봉 DataFrame (지표 포함)
    
    Returns:
        dict: {
            'confirmed': 모멘텀 확인 여부,
            'daily_change': 당일 등락률,
            'rsi': RSI,
            'reason': 판단 사유
        }
    """
    try:
        if df_daily is None or len(df_daily) < 20:
            return {
                'confirmed': False,
                'daily_change': 0,
                'rsi': 50,
                'daily_bb': 50,
                'reason': '일봉 데이터 부족'
            }
        
        current = df_daily.iloc[-1]
        
        # 기본 정보 추출
        daily_open = current['open']
        daily_close = current['close']
        daily_bb = current['bb_position']
        rsi = current['rsi']
        
        # 당일 등락률
        if daily_open > 0:
            daily_change = ((daily_close - daily_open) / daily_open) * 100
        else:
            daily_change = 0.0
        
        # 조건 1: 오늘 양봉
        is_today_bullish = daily_close > daily_open
        
        # 조건 2: RSI 적정 구간
        rsi_ok = V80_DAILY_RSI_MIN <= rsi <= V80_DAILY_RSI_MAX
        
        # 조건 3: 20일선 체크
        ma20 = df_daily['close'].rolling(20).mean().iloc[-1]
        near_ma20 = daily_close >= ma20 * V80_DAILY_MA20_THRESHOLD
        
        # 조건 4: 최근 3일 양봉 비율
        recent_3 = df_daily.tail(3)
        bullish_days = sum(1 for _, c in recent_3.iterrows() if c['close'] > c['open'])
        bullish_ok = bullish_days >= V80_DAILY_BULLISH_DAYS_MIN
        
        # 종합 판단
        confirmed = is_today_bullish and rsi_ok and near_ma20 and bullish_ok
        
        # 상세 사유
        reasons = []
        if not is_today_bullish:
            reasons.append(f"일봉음봉({daily_change:+.1f}%)")
        if not rsi_ok:
            reasons.append(f"RSI범위벗어남({rsi:.0f})")
        if not near_ma20:
            reasons.append(f"MA20하회({daily_close/ma20*100:.1f}%)")
        if not bullish_ok:
            reasons.append(f"양봉부족({bullish_days}/3)")
        
        if confirmed:
            reason = f"양봉+{daily_change:.1f}%, RSI:{rsi:.0f}, 양봉일:{bullish_days}/3"
        else:
            reason = ", ".join(reasons) if reasons else "조건미충족"
        
        return {
            'confirmed': confirmed,
            'daily_change': daily_change,
            'rsi': rsi,
            'daily_bb': daily_bb,
            'is_bullish': is_today_bullish,
            'bullish_days': bullish_days,
            'reason': reason
        }
        
    except Exception as e:
        if DEBUG_MODE:
            print(f"{Colors.RED}[Daily Momentum Error] {e}{Colors.ENDC}")
        return {
            'confirmed': False,
            'daily_change': 0,
            'rsi': 50,
            'daily_bb': 50,
            'reason': f'오류: {e}'
        }
    

# ================================================================================
# SECTION B: 시장 상황 감지 함수 (신규)
# ================================================================================

# ================================================================================
# SECTION C: 적응형 점수 계산 함수 (신규)
# ================================================================================


# ================================================================================
# SECTION 13: Buy Logic
# ================================================================================

def check_bb_bottom_touch(df, lookback=3):
    """Check BB bottom touch"""
    if len(df) < lookback:
        return False
    
    recent_candles = df.tail(lookback)
    
    for _, candle in recent_candles.iterrows():
        if candle['low'] <= candle['bb_lower'] * 1.002:
            return True
    
    return False


def detect_bullish_reversal(df):
    """Detect bullish reversal"""
    if len(df) < 2:
        return False
    
    current = df.iloc[-1]
    previous = df.iloc[-2]
    
    is_bullish_candle = current['close'] > current['open']
    is_price_rising = current['close'] > previous['close']
    is_rsi_rising = current['rsi'] > previous['rsi']
    
    return is_bullish_candle and is_price_rising and is_rsi_rising


def detect_bearish_reversal(df):
    """Detect bearish reversal"""
    if len(df) < 2:
        return False
    
    current = df.iloc[-1]
    previous = df.iloc[-2]
    
    is_bearish_candle = current['close'] < current['open']
    is_price_falling = current['close'] < previous['close']
    is_rsi_falling = current['rsi'] < previous['rsi']
    
    return is_bearish_candle and is_price_falling and is_rsi_falling


def count_consecutive_candles(df, candle_type='bear', count=2):
    """Count consecutive candles"""
    if len(df) < count:
        return False
    
    recent_candles = df.tail(count)
    
    if candle_type == 'bear':
        return all(candle['close'] < candle['open'] for _, candle in recent_candles.iterrows())
    elif candle_type == 'bull':
        return all(candle['close'] > candle['open'] for _, candle in recent_candles.iterrows())
    
    return False


def calculate_buy_score_v75(df_15m):
    """
    v7.5 Buy score calculation (100 points max)
    [ENHANCED] V75_BUY_CONSECUTIVE_BULL 로직 추가
    """
    try:
        score = 0
        reasons = []
        
        current = df_15m.iloc[-1]
        prev1 = df_15m.iloc[-2]
        prev2 = df_15m.iloc[-3]
        
        recent_3 = df_15m.iloc[-3:]
        
        # 1. BB Bottom Touch (30 points)
        bb_now = current['bb_position']
        bb_min_recent = recent_3['bb_position'].min()
        
        if bb_now <= V75_BUY_BB_MAX:
            score += 20
            reasons.append(f"OK Current BB {bb_now:.1f}%")
        
        if bb_min_recent <= V75_BUY_BB_EXTREME:
            score += 10
            reasons.append(f"OK Recent extreme low BB {bb_min_recent:.1f}%")
        
        # 2. Reversal Confirmation (30 points) - ENHANCED
        if current['is_bull'] == 1:
            score += 10  # 15 → 10으로 조정
            reasons.append("OK Current bullish")
        
        if prev1['is_bull'] == 1:
            score += 10  # 15 → 10으로 조정
            reasons.append("OK Previous bullish")
        
        # [NEW] 연속 양봉 체크 (10 points)
        consecutive_bulls = 0
        for i in range(-1, -V75_BUY_CONSECUTIVE_BULL-1, -1):
            if len(df_15m) + i < 0:
                break
            if df_15m.iloc[i]['is_bull'] == 1:
                consecutive_bulls += 1
            else:
                break
        
        if consecutive_bulls >= V75_BUY_CONSECUTIVE_BULL:
            score += 10
            reasons.append(f"OK Consecutive {consecutive_bulls} bulls")
        
        # 3. Indicator Rising (20 points)
        rsi_now = current['rsi']
        rsi_prev = prev1['rsi']
        
        if rsi_now > rsi_prev:
            score += 10
            reasons.append(f"OK RSI rising ({rsi_prev:.1f}->{rsi_now:.1f})")
        
        price_now = current['close']
        price_prev = prev1['close']
        
        if price_now > price_prev:
            score += 10
            reasons.append("OK Price rising")
        
        # 4. Volume Check (10 points)
        volume_ratio = current['volume_ratio']
        
        if volume_ratio >= V75_BUY_MIN_VOLUME_RATIO:
            score += 10
            reasons.append(f"OK Volume {volume_ratio:.2f}x")
        
        # 5. Volatility Check (10 points)
        bb_width = current['bb_width']
        
        if bb_width >= V75_BUY_MIN_BB_WIDTH:
            score += 10
            reasons.append(f"OK BB Width {bb_width:.2f}%")
        
        # Deductions
        consecutive_bears = 0
        for i in range(-1, -4, -1):
            if df_15m.iloc[i]['is_bear'] == 1:
                consecutive_bears += 1
            else:
                break
        
        if consecutive_bears >= V75_BUY_MAX_CONSECUTIVE_RED:
            score -= 20
            reasons.append(f"X Consecutive bearish {consecutive_bears}")
        
        if rsi_now < 25:
            score -= 10
            reasons.append(f"X RSI too low ({rsi_now:.1f})")
        
        return {
            'score': score,
            'reasons': reasons,
            'bb_position': bb_now,
            'rsi': rsi_now,
            'volume_ratio': volume_ratio,
            'bb_width': bb_width
        }
        
    except Exception as e:
        if DEBUG_MODE:
            print(f"{Colors.RED}[Buy Score Error] {e}{Colors.ENDC}")
        return {
            'score': 0,
            'reasons': ['Calculation error'],
            'bb_position': 50,
            'rsi': 50,
            'volume_ratio': 1.0,
            'bb_width': 2.0
        }

# ================================================================================
# SECTION 13-A: [v8.0] Entry Trigger Detection
# ================================================================================

def detect_entry_trigger(df_15m, df_5m=None):
    """
    [v8.0] 최적 매수 타이밍 트리거 감지
    
    모멘텀이 확인된 상태에서 "지금이 진입 시점"인지 판단
    
    트리거 조건 (택일):
    1. 눌림목 완료: 소폭 조정 후 재상승 시작
    2. 돌파 확인: 최근 고점 돌파 직후
    3. 거래량 폭발: 평균 2배 이상 거래량 + 양봉
    
    Args:
        df_15m: 15분봉 DataFrame
        df_5m: 5분봉 DataFrame (선택적, 추가 확인용)
    
    Returns:
        dict: {
            'triggered': 트리거 발생 여부,
            'type': 트리거 유형,
            'strength': 트리거 강도 (0-100),
            'reason': 설명
        }
    """
    try:
        if df_15m is None or len(df_15m) < 10:
            return {
                'triggered': False,
                'type': None,
                'strength': 0,
                'reason': '데이터 부족'
            }
        
        triggers = []
        
        current = df_15m.iloc[-1]
        prev = df_15m.iloc[-2]
        prev2 = df_15m.iloc[-3] if len(df_15m) >= 3 else prev
        
        is_current_bullish = current['close'] > current['open']
        
        # ========================================
        # 트리거 1: 눌림목 완료 (Pullback Complete)
        # ========================================
        if V80_TRIGGER_PULLBACK_CONFIRM:
            # 이전 캔들들이 조정(하락/횡보)이었고, 현재 반등
            was_pullback = (prev['close'] <= prev['open'] or 
                           prev2['close'] <= prev2['open'])
            bounce_strong = current['close'] > prev['high']  # 이전 고점 돌파
            bounce_weak = is_current_bullish and current['close'] > prev['close']
            
            if was_pullback and bounce_strong:
                triggers.append({
                    'type': 'PULLBACK_COMPLETE',
                    'strength': 88,
                    'reason': '눌림목 후 강한반등(이전고점돌파)'
                })
            elif was_pullback and bounce_weak:
                triggers.append({
                    'type': 'PULLBACK_BOUNCE',
                    'strength': 72,
                    'reason': '눌림목 후 반등시작'
                })
        
        # ========================================
        # 트리거 2: 저항 돌파 (Breakout)
        # ========================================
        if V80_TRIGGER_BREAKOUT_CONFIRM:
            # 최근 10개 캔들의 고점 돌파
            recent_high = df_15m['high'].tail(10).max()
            recent_high_excluding_current = df_15m['high'].iloc[-10:-1].max()
            
            is_breakout = current['close'] > recent_high_excluding_current
            
            if is_breakout and is_current_bullish:
                triggers.append({
                    'type': 'BREAKOUT',
                    'strength': 82,
                    'reason': f'최근고점 {recent_high_excluding_current:.0f} 돌파'
                })
        
        # ========================================
        # 트리거 3: 거래량 폭발 (Volume Spike)
        # ========================================
        vol_ma = df_15m['volume'].rolling(20).mean().iloc[-1]
        vol_ratio = current['volume'] / vol_ma if vol_ma > 0 else 1.0
        
        if vol_ratio >= V80_TRIGGER_VOLUME_SPIKE and is_current_bullish:
            triggers.append({
                'type': 'VOLUME_SPIKE',
                'strength': 92,
                'reason': f'거래량폭발 {vol_ratio:.1f}배 + 양봉'
            })
        elif vol_ratio >= V80_TRIGGER_VOLUME_INCREASE and is_current_bullish:
            triggers.append({
                'type': 'VOLUME_INCREASE',
                'strength': 75,
                'reason': f'거래량증가 {vol_ratio:.1f}배 + 양봉'
            })
        
        # ========================================
        # 트리거 4: 연속 양봉 (Consecutive Bullish)
        # ========================================
        bullish_count = 0
        for i in range(-1, -5, -1):
            if len(df_15m) + i >= 0:
                if df_15m.iloc[i]['close'] > df_15m.iloc[i]['open']:
                    bullish_count += 1
                else:
                    break
        
        if bullish_count >= 3:
            triggers.append({
                'type': 'CONSECUTIVE_BULLISH',
                'strength': 78,
                'reason': f'연속양봉 {bullish_count}개'
            })
        
        # ========================================
        # 5분봉 추가 확인 (보너스)
        # ========================================
        if df_5m is not None and len(df_5m) >= 6:
            recent_5m = df_5m.tail(4)
            bullish_5m = sum(1 for _, c in recent_5m.iterrows() 
                           if c['close'] > c['open'])
            
            if bullish_5m >= 3:
                for trigger in triggers:
                    trigger['strength'] = min(100, trigger['strength'] + 8)
                    trigger['reason'] += ' +5분봉확인'
        
        # ========================================
        # 최종 트리거 선택
        # ========================================
        if triggers:
            # 가장 강한 트리거 선택
            best_trigger = max(triggers, key=lambda x: x['strength'])
            
            if best_trigger['strength'] >= V80_TRIGGER_MIN_STRENGTH:
                return {
                    'triggered': True,
                    'type': best_trigger['type'],
                    'strength': best_trigger['strength'],
                    'reason': best_trigger['reason'],
                    'all_triggers': triggers
                }
        
        return {
            'triggered': False,
            'type': None,
            'strength': 0,
            'reason': '트리거 조건 미충족',
            'all_triggers': triggers
        }
        
    except Exception as e:
        if DEBUG_MODE:
            print(f"{Colors.RED}[Trigger Detection Error] {e}{Colors.ENDC}")
        return {
            'triggered': False,
            'type': None,
            'strength': 0,
            'reason': f'오류: {e}'
        }
    
   
    
def evolution_80_buy_signal(df_15m, df_5m, ticker):
    """
    [v8.0] 모멘텀 기반 최적 매수 신호
    
    3단계 검증:
    1단계: 일봉 모멘텀 확인 (큰 그림)
    2단계: 15분봉 모멘텀 강도 측정 (힘 확인)
    3단계: 진입 트리거 감지 (타이밍)
    
    핵심 철학:
    - "오르고 있어서"가 아니라 "오를 힘이 있어서" 매수
    - 가격이 아직 낮을 때 (BB 12-45%) 진입
    - 트리거 확인 후 진입 (확률 최대화)
    
    Args:
        df_15m: 15분봉 DataFrame (200개, 지표 포함)
        df_5m: 5분봉 DataFrame (100개, 지표 포함) - 선택적
        ticker: 코인 티커
    
    Returns:
        dict: 매수 신호 정보
    """
    try:
        # 기본 응답 템플릿
        current = df_15m.iloc[-1] if df_15m is not None and len(df_15m) > 0 else None
        
        base_response = {
            'signal': False,
            'reason': '',
            'confidence': 0,
            'entry_price': current['close'] if current is not None else 0,
            'bb_position': current['bb_position'] if current is not None else 50,
            'bb_width_pct': current['bb_width'] if current is not None else 2.0,
            'mode': 'MOMENTUM_V80',
            'market_condition': 'NORMAL',
            'score': 0,
            'daily_bb': 50,
            'momentum_score': 0,
            'trigger_type': None
        }
        
        # 데이터 검증
        if df_15m is None or len(df_15m) < 50:
            base_response['reason'] = '15분봉 데이터 부족'
            return base_response
        
        # ========================================
        # Step 1: 일봉 모멘텀 확인
        # ========================================
        df_daily = get_candles_daily(ticker, count=V80_CANDLES_DAILY_COUNT)
        if df_daily is not None and len(df_daily) >= 20:
            df_daily = add_indicators(df_daily)
        
        if df_daily is None:
            base_response['reason'] = '일봉 데이터 부족'
            return base_response
        
        daily_momentum = check_daily_momentum_confirmed(df_daily)
        base_response['daily_bb'] = daily_momentum.get('daily_bb', 50)
        
        if not daily_momentum['confirmed']:
            base_response['reason'] = f"일봉모멘텀미확인: {daily_momentum['reason']}"
            return base_response
        
        # ========================================
        # Step 2: 가격 위치 확인 (아직 덜 올랐는가?)
        # ========================================
        bb_position = current['bb_position']
        rsi = current['rsi']
        
        # BB 위치 체크
        if bb_position < V80_BUY_BB_MIN:
            base_response['reason'] = f"아직하락중 (BB {bb_position:.1f}% < {V80_BUY_BB_MIN}%)"
            return base_response
        
        if bb_position > V80_BUY_BB_MAX:
            # 모멘텀이 매우 강하면 BB 55%까지 허용
            base_response['reason'] = f"이미상승 (BB {bb_position:.1f}% > {V80_BUY_BB_MAX}%)"
            # 아직 반환하지 않고, 모멘텀 체크 후 판단
        
        # RSI 체크
        if not (V80_BUY_RSI_MIN <= rsi <= V80_BUY_RSI_MAX):
            base_response['reason'] = f"RSI범위벗어남 ({rsi:.1f}, 허용: {V80_BUY_RSI_MIN}-{V80_BUY_RSI_MAX})"
            return base_response
        
        # ========================================
        # Step 3: 15분봉 모멘텀 강도 측정
        # ========================================
        momentum = calculate_momentum_strength(df_15m, df_daily)
        base_response['momentum_score'] = momentum['score']
        
        # BB 위치에 따른 최소 모멘텀 요구치
        if bb_position <= 30:
            min_momentum = V80_MOMENTUM_MIN_SCORE_LOW   # 60점
        elif bb_position <= 45:
            min_momentum = V80_MOMENTUM_MIN_SCORE_MID   # 70점
        else:
            min_momentum = V80_MOMENTUM_MIN_SCORE_HIGH  # 80점
            # BB 45% 초과 시, 모멘텀 80점 이상이면 55%까지 허용
            if momentum['score'] >= V80_MOMENTUM_MIN_SCORE_HIGH and bb_position <= V80_BUY_BB_EXTENDED:
                pass  # 허용
            elif bb_position > V80_BUY_BB_MAX:
                base_response['reason'] = f"이미상승 (BB {bb_position:.1f}%, 모멘텀 {momentum['score']}점 부족)"
                return base_response
        
        if momentum['score'] < min_momentum:
            base_response['reason'] = f"모멘텀부족 ({momentum['score']}점 < {min_momentum}점, BB:{bb_position:.0f}%)"
            return base_response
        
        # ========================================
        # Step 4: 진입 트리거 확인
        # ========================================
        if V80_TRIGGER_ENABLED:
            trigger = detect_entry_trigger(df_15m, df_5m)
            base_response['trigger_type'] = trigger.get('type')
            
            if not trigger['triggered']:
                base_response['reason'] = f"트리거대기 (모멘텀{momentum['score']}점OK, {trigger['reason']})"
                base_response['score'] = momentum['score']
                return base_response
        else:
            trigger = {'triggered': True, 'type': 'DISABLED', 'strength': 75, 'reason': '트리거비활성화'}
        
        # ========================================
        # 모든 조건 충족 → 매수 신호!
        # ========================================
        confidence = min(100, (momentum['score'] + trigger['strength']) // 2)
        
        reason_parts = [
            f"모멘텀{momentum['score']}점",
            f"BB{bb_position:.0f}%",
            f"트리거:{trigger['type']}",
            f"일봉+{daily_momentum['daily_change']:.1f}%"
        ]
        
        # 모멘텀 상세 사유 추가 (최대 2개)
        if momentum['details']:
            reason_parts.append(f"({momentum['details'][0].split('+')[0]})")
        
        return {
            'signal': True,
            'reason': ' | '.join(reason_parts),
            'confidence': confidence,
            'entry_price': current['close'],
            'bb_position': bb_position,
            'bb_width_pct': current['bb_width'],
            'mode': 'MOMENTUM_V80',
            'market_condition': 'CONFIRMED',
            'score': momentum['score'],
            'daily_bb': daily_momentum.get('daily_bb', 50),
            'momentum_score': momentum['score'],
            'trigger_type': trigger['type']
        }
        
    except Exception as e:
        if DEBUG_MODE:
            print(f"{Colors.RED}[v8.0 Buy Signal Error] {e}{Colors.ENDC}")
            traceback.print_exc()
        
        return {
            'signal': False,
            'reason': f'오류: {str(e)}',
            'confidence': 0,
            'entry_price': 0,
            'bb_position': 50,
            'bb_width_pct': 2.0,
            'mode': 'ERROR',
            'market_condition': 'UNKNOWN',
            'score': 0,
            'daily_bb': 50,
            'momentum_score': 0,
            'trigger_type': None
        }
    

    
# ================================================================================
# SECTION 14: v7.6 Sell Logic - UPPER BAND MASTER
# ================================================================================

# ================================================================================
# SECTION 14-A: [v8.0] Momentum Exhaustion Detection
# ================================================================================

def detect_momentum_exhaustion(df_15m, held_info=None):
    """
    [v8.0] 모멘텀 소진 감지 (엄격한 기준)
    
    소진 = 상승 추세가 "확실히" 끝났다는 증거
    단순 조정과 소진을 구분
    
    소진 신호 (점수제, 5점 이상이면 소진):
    1. RSI 다이버전스 (2점): 가격↑ but RSI↓
    2. 거래량 급감 (2점): 평균의 70% 미만 + 캔들 약화
    3. 연속 음봉 (1-3점): 2개=1점, 3개=3점
    4. BB 상단 이탈 후 복귀 (2점): 95%→85%
    5. 고점 대비 하락 (1-2점): 1.5%=1점, 2%=2점
    
    Args:
        df_15m: 15분봉 DataFrame
        held_info: 보유 정보 dict (peak_price, peak_bb_position 등)
    
    Returns:
        dict: {
            'exhausted': 소진 여부,
            'score': 소진 점수,
            'details': 상세 사유 리스트,
            'threshold': 기준 점수
        }
    """
    try:
        if df_15m is None or len(df_15m) < 5:
            return {
                'exhausted': False,
                'score': 0,
                'details': ['데이터 부족'],
                'threshold': V80_EXHAUSTION_THRESHOLD
            }
        
        exhaustion_score = 0
        details = []
        
        current = df_15m.iloc[-1]
        prev = df_15m.iloc[-2]
        prev2 = df_15m.iloc[-3] if len(df_15m) >= 3 else prev
        
        # ========================================
        # 소진 신호 1: RSI 다이버전스 (2점)
        # 가격은 오르는데 RSI는 내림 → 힘 빠짐
        # ========================================
        price_higher = current['high'] >= prev['high']
        rsi_lower = current['rsi'] < prev['rsi'] - 2  # 2포인트 이상 하락
        
        if price_higher and rsi_lower:
            exhaustion_score += V80_EXHAUSTION_RSI_DIVERGENCE
            details.append(f"RSI다이버전스(가격↑RSI↓) +{V80_EXHAUSTION_RSI_DIVERGENCE}")
        
        # ========================================
        # 소진 신호 2: 거래량 급감 + 캔들 약화 (2점)
        # ========================================
        vol_ma = df_15m['volume'].rolling(10).mean().iloc[-1]
        vol_ratio = current['volume'] / vol_ma if vol_ma > 0 else 1.0
        
        candle_body = abs(current['close'] - current['open'])
        prev_body = abs(prev['close'] - prev['open'])
        body_weakening = candle_body < prev_body * 0.5 if prev_body > 0 else False
        
        if vol_ratio < 0.7 and body_weakening:
            exhaustion_score += V80_EXHAUSTION_VOLUME_DROP
            details.append(f"거래량급감+캔들약화({vol_ratio:.1f}x) +{V80_EXHAUSTION_VOLUME_DROP}")
        elif vol_ratio < 0.5:
            exhaustion_score += 1
            details.append(f"거래량급감({vol_ratio:.1f}x) +1")
        
        # ========================================
        # 소진 신호 3: 연속 음봉 (1-3점)
        # ========================================
        bearish_count = 0
        for i in range(-1, -6, -1):
            if len(df_15m) + i >= 0:
                if df_15m.iloc[i]['close'] < df_15m.iloc[i]['open']:
                    bearish_count += 1
                else:
                    break
        
        if bearish_count >= 4:
            exhaustion_score += V80_EXHAUSTION_CONSECUTIVE_BEAR + 1
            details.append(f"연속음봉{bearish_count}개 +{V80_EXHAUSTION_CONSECUTIVE_BEAR + 1}")
        elif bearish_count >= 3:
            exhaustion_score += V80_EXHAUSTION_CONSECUTIVE_BEAR
            details.append(f"연속음봉{bearish_count}개 +{V80_EXHAUSTION_CONSECUTIVE_BEAR}")
        elif bearish_count >= 2:
            exhaustion_score += 1
            details.append(f"연속음봉{bearish_count}개 +1")
        
        # ========================================
        # 소진 신호 4: BB 상단 이탈 후 복귀 (2점)
        # 95% 이상 갔다가 85% 이하로 복귀 = 페이크 브레이크아웃
        # ========================================
        if held_info:
            peak_bb = held_info.get('peak_bb_position', 0)
            current_bb = current['bb_position']
            
            if peak_bb >= 95 and current_bb < 85:
                exhaustion_score += V80_EXHAUSTION_BB_REJECTION
                details.append(f"BB상단이탈후복귀({peak_bb:.0f}%→{current_bb:.0f}%) +{V80_EXHAUSTION_BB_REJECTION}")
        
        # ========================================
        # 소진 신호 5: 고점 대비 하락 (1-2점)
        # ========================================
        if held_info:
            peak_price = held_info.get('peak_price', current['close'])
            if peak_price > 0:
                drawdown = (peak_price - current['close']) / peak_price * 100
                
                if drawdown >= 2.5:
                    exhaustion_score += V80_EXHAUSTION_DRAWDOWN
                    details.append(f"고점대비-{drawdown:.1f}% +{V80_EXHAUSTION_DRAWDOWN}")
                elif drawdown >= 1.5:
                    exhaustion_score += 1
                    details.append(f"고점대비-{drawdown:.1f}% +1")
        
        # ========================================
        # 종합 판단
        # ========================================
        is_exhausted = exhaustion_score >= V80_EXHAUSTION_THRESHOLD
        
        return {
            'exhausted': is_exhausted,
            'score': exhaustion_score,
            'details': details,
            'threshold': V80_EXHAUSTION_THRESHOLD
        }
        
    except Exception as e:
        if DEBUG_MODE:
            print(f"{Colors.RED}[Exhaustion Detection Error] {e}{Colors.ENDC}")
        return {
            'exhausted': False,
            'score': 0,
            'details': [f'오류: {e}'],
            'threshold': V80_EXHAUSTION_THRESHOLD
        }
    
def evolution_80_sell_signal(df, buy_price, buy_time=None, held_info=None):
    """
    [v8.0] 모멘텀 기반 최적 매도 신호
    
    핵심 철학:
    1. 상승 중에는 절대 팔지 않음
    2. 모멘텀이 "확실히" 소진되었을 때만 매도
    3. 손절은 빠르게, 익절은 천천히
    
    매도 트리거:
    1. 손절: -2.5% (빠른 손절)
    2. 모멘텀 소진: 5개 이상 소진 신호
    3. 트레일링 스탑: 고점 대비 -2% (수익 2.5% 이상일 때만)
    4. 극과매수 익절: BB 98%+ & 음봉 & 수익 2%+
    
    Args:
        df: 15분봉 DataFrame
        buy_price: 매수가
        buy_time: 매수 시각 (datetime)
        held_info: 보유 정보 dict
    
    Returns:
        dict: 매도 신호 정보
    """
    try:
        if df is None or len(df) < 5:
            return {
                'signal': False,
                'reason': '데이터 부족',
                'exit_price': 0,
                'profit_pct': 0,
                'bb_position': 50,
                'bb_width_pct': 2.0
            }
        
        current = df.iloc[-1]
        prev = df.iloc[-2]
        current_price = current['close']
        profit_pct = ((current_price - buy_price) / buy_price) * 100
        bb_position = current['bb_position']
        
        base_response = {
            'signal': False,
            'exit_price': current_price,
            'profit_pct': profit_pct,
            'bb_position': bb_position,
            'bb_width_pct': current['bb_width'],
            'reason': ''
        }
        
        # ========================================
        # 피크 가격/BB 업데이트 (held_info에 기록)
        # ========================================
        if held_info is not None:
            current_peak = held_info.get('peak_price', buy_price)
            if current_price > current_peak:
                held_info['peak_price'] = current_price
                held_info['peak_time'] = datetime.now()
            
            current_peak_bb = held_info.get('peak_bb_position', 0)
            if bb_position > current_peak_bb:
                held_info['peak_bb_position'] = bb_position
        
        # ========================================
        # Step 0: 손절 체크 (무조건 실행)
        # ========================================
        if profit_pct <= V80_STOP_LOSS_PCT:
            return {
                **base_response,
                'signal': True,
                'reason': f'STOP_LOSS ({profit_pct:.2f}% <= {V80_STOP_LOSS_PCT}%)'
            }
        
        # ========================================
        # Step 1: 상승 중 매도 금지
        # ========================================
        if V80_SELL_NEVER_IF_RISING:
            price_rising = current['close'] > prev['close']
            rsi_rising = current['rsi'] > prev['rsi']
            is_bullish = current['close'] > current['open']
            
            # 3가지 중 N개 이상 상승 신호면 홀드
            rising_signals = sum([price_rising, rsi_rising, is_bullish])
            
            if rising_signals >= V80_SELL_RISING_SIGNALS_MIN:
                base_response['reason'] = f'상승중홀드 (신호{rising_signals}/3, 수익{profit_pct:.2f}%)'
                return base_response
        
        # ========================================
        # Step 2: 최소 수익 미달 시 홀드
        # ========================================
        if profit_pct < V80_SELL_MIN_PROFIT:
            base_response['reason'] = f'수익미달홀드 ({profit_pct:.2f}% < {V80_SELL_MIN_PROFIT}%)'
            return base_response
        
        # ========================================
        # Step 3: 모멘텀 소진 체크
        # ========================================
        exhaustion = detect_momentum_exhaustion(df, held_info)
        
        if exhaustion['exhausted']:
            detail_str = ', '.join(exhaustion['details'][:2]) if exhaustion['details'] else ''
            return {
                **base_response,
                'signal': True,
                'reason': f'모멘텀소진 (점수{exhaustion["score"]}/{exhaustion["threshold"]}: {detail_str})'
            }
        
        # ========================================
        # Step 4: 트레일링 스탑 (고수익 시에만)
        # ========================================
        if V80_TRAILING_ENABLED and profit_pct >= V80_TRAILING_ACTIVATION and held_info:
            peak_price = held_info.get('peak_price', buy_price)
            
            if peak_price > 0:
                drawdown_from_peak = (peak_price - current_price) / peak_price * 100
                
                if drawdown_from_peak >= V80_TRAILING_DISTANCE:
                    peak_profit = ((peak_price - buy_price) / buy_price) * 100
                    return {
                        **base_response,
                        'signal': True,
                        'reason': f'트레일링스탑 (고점{peak_profit:.1f}%→현재{profit_pct:.1f}%, -{drawdown_from_peak:.1f}%)'
                    }
        
        # ========================================
        # Step 5: 극과매수 + 음봉 (BB 98%+)
        # ========================================
        is_bearish = current['close'] < current['open']
        
        if bb_position >= V80_OVERBOUGHT_BB and is_bearish and profit_pct >= V80_OVERBOUGHT_MIN_PROFIT:
            return {
                **base_response,
                'signal': True,
                'reason': f'극과매수익절 (BB{bb_position:.0f}%+음봉, 수익{profit_pct:.2f}%)'
            }
        
        # ========================================
        # 조건 미충족 → 계속 홀드
        # ========================================
        exhaustion_info = f"소진{exhaustion['score']}/{exhaustion['threshold']}"
        base_response['reason'] = f'홀드 (수익{profit_pct:.2f}%, {exhaustion_info})'
        return base_response
        
    except Exception as e:
        if DEBUG_MODE:
            print(f"{Colors.RED}[v8.0 Sell Signal Error] {e}{Colors.ENDC}")
            traceback.print_exc()
        
        return {
            'signal': False,
            'reason': f'오류: {str(e)}',
            'exit_price': 0,
            'profit_pct': 0,
            'bb_position': 50,
            'bb_width_pct': 2.0
        }

def evolution_76_sell_signal(df, buy_price, buy_time=None, held_info=None):
    """레거시 wrapper - v8.0으로 리다이렉트"""
    return evolution_80_sell_signal(df, buy_price, buy_time, held_info)

def evolution_70_sell_signal(df, buy_price):
    """레거시 wrapper - v8.0으로 리다이렉트"""
    return evolution_80_sell_signal(df, buy_price)


# ================================================================================
# SECTION 15: Initialization Functions (NEW)
# ================================================================================

def sync_held_coins_with_exchange():
    """
    거래소 실제 보유량과 held_coins 동기화
    ⚠️ FIXED_STABLE_COINS에 있는 코인만 동기화 (v343.1 수정)
    
    [v343.1 개선사항]
    - FIXED_STABLE_COINS 화이트리스트 검증 추가
    - 관리 대상 외 코인 스킵 및 로그 출력
    - Discord 알림에 스킵 정보 포함
    - 수동 매수 코인에 대한 경고 메시지
    
    봇 시작 시 1회 실행
    """
    global held_coins
    
    print(f"\n{Colors.CYAN}{'='*10}")
    print(f"[Init] 기존 보유 코인 동기화 시작...")
    print(f"{'='*10}{Colors.ENDC}")
    
    try:
        balances = upbit.get_balances()
        synced_count = 0
        skipped_count = 0
        total_value = 0.0
        skipped_coins = []
        
        for bal in balances:
            currency = bal.get('currency', '')
            if currency == 'KRW':
                continue
            
            balance = float(bal.get('balance', 0))
            if balance <= 0:
                continue
            
            ticker = f"KRW-{currency}"
            
            # ========================================
            # ✅ [v343.1 핵심 수정] FIXED_STABLE_COINS 검증
            # ========================================
            # 봇 관리 대상 코인만 동기화
            # - FIXED_STABLE_COINS에 없는 코인은 사용자 수동 관리 자산으로 간주
            # - held_coins 오염 방지 및 자산 계산 정확성 확보
            # - BTC, DOGE 등 관리 대상 외 코인의 유령 보유 문제 해결
            if ticker not in FIXED_STABLE_COINS:
                skipped_count += 1
                
                # 현재가 조회 (평가액 계산용)
                try:
                    current_price = pyupbit.get_current_price(ticker)
                    if current_price:
                        skip_value = balance * current_price
                    else:
                        skip_value = 0
                except:
                    skip_value = 0
                
                skipped_coins.append(f"{ticker} ({balance:.4f}개, {skip_value:,.0f}원)")
                
                print(f"{Colors.YELLOW}  ⚠️  {ticker}: {balance:.4f}개 @ {skip_value:,.0f}원")
                print(f"      → 관리 대상 외 코인 (동기화 스킵){Colors.ENDC}")
                continue
            # ========================================
            
            avg_buy_price = float(bal.get('avg_buy_price', 0))
            
            if avg_buy_price <= 0:
                print(f"{Colors.YELLOW}  ⚠️  {ticker}: 평균 매수가 없음 (스킵){Colors.ENDC}")
                continue
            
            # 현재가 조회
            try:
                current_price = pyupbit.get_current_price(ticker)
                if current_price:
                    coin_value = balance * current_price
                    profit_pct = ((current_price - avg_buy_price) / avg_buy_price) * 100
                    total_value += coin_value
                else:
                    coin_value = balance * avg_buy_price
                    profit_pct = 0.0
            except:
                coin_value = balance * avg_buy_price
                profit_pct = 0.0
            
            # held_coins에 추가
            with held_coins_lock:
                held_coins[ticker] = {
                    'buy_price': avg_buy_price,
                    'buy_time': datetime.now(),  # ⚠️ 정확한 시간 불명 (봇 시작 시각으로 기록)
                    'buy_amount': balance * avg_buy_price,
                    'peak_price': avg_buy_price,
                    'peak_time': datetime.now(),
                    'buy_reason': 'EXISTING_POSITION (봇 시작 시 동기화)'
                }
            
            synced_count += 1
            print(f"{Colors.GREEN}  ✓ {ticker}: {balance:.4f}개 @ {avg_buy_price:,.0f}원")
            print(f"    평가액: {coin_value:,.0f}원 ({profit_pct:+.2f}%){Colors.ENDC}")
        
        krw_balance = upbit.get_balance("KRW")
        
        print(f"\n{Colors.GREEN}{'='*10}")
        print(f"[Init] 동기화 완료")
        print(f"  - 동기화된 코인: {synced_count}개")
        print(f"  - 스킵된 코인: {skipped_count}개")
        if skipped_coins:
            print(f"  - 스킵 목록:")
            for coin in skipped_coins:
                print(f"    • {coin}")
        print(f"  - 코인 총 평가액: {total_value:,.0f}원 (관리 대상만)")
        print(f"  - 보유 현금: {krw_balance:,.0f}원")
        print(f"  - 총 자산: {total_value + krw_balance:,.0f}원")
        print(f"{'='*10}{Colors.ENDC}\n")
        
        # Discord 알림
        if synced_count > 0 or skipped_count > 0:
            sync_message = f"""
**🔄 기존 보유 코인 동기화 완료**

**✅ 동기화된 코인:** `{synced_count}개`
**⚠️ 스킵된 코인:** `{skipped_count}개`
"""
            if skipped_coins:
                sync_message += f"\n**📋 스킵 목록:**\n"
                for coin in skipped_coins:
                    sync_message += f"`{coin}`\n"
                sync_message += f"""
**💡 안내:**
스킵된 코인은 봇 관리 대상이 아닙니다.
수동으로 매수/매도를 관리하세요.
"""
            
            sync_message += f"""
**💰 자산 현황 (관리 대상만):**
- 코인 평가액: `{total_value:,.0f}원`
- 보유 현금: `{krw_balance:,.0f}원`
- 총 자산: `{total_value + krw_balance:,.0f}원`

⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
"""
            send_discord_message(sync_message)
        
        # ========================================
        # ✅ [v343.1 추가] 수동 매수 코인 경고
        # ========================================
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


# ================================================================================
# SECTION 16: Trade Execution Functions
# ================================================================================

def execute_buy(ticker, signal):
    """
    Execute buy order (thread safe)
    
    [v7.8.1] InsufficientFundsBid 오류 수정
    - 가용 현금(KRW) 우선 체크 로직 추가
    - 로그에 가용현금 정보 명시
    - 매수 금액 계산 로직 개선
    
    - Equal position sizing: POSITION_SIZE_RATIO of total assets per trade
    - Dynamic rebalancing: Asset evaluation on every buy
    - Fee optimization: 0.9995x on final position
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
            
            with held_coins_lock:
                if ticker in held_coins:
                    print(f"{Colors.YELLOW}[Buy Limit] 이미 보유 중{Colors.ENDC}")
                    return False
                
                if len(held_coins) >= MAX_HOLDINGS:
                    print(f"{Colors.YELLOW}[Buy Limit] 최대 보유 종목 도달 ({len(held_coins)}/{MAX_HOLDINGS}){Colors.ENDC}")
                    return False
            
            # ========================================
            # [v7.8.1] Step 1: 가용 현금(KRW) 우선 체크
            # ========================================
            try:
                krw_balance = upbit.get_balance("KRW")
                if krw_balance is None:
                    krw_balance = 0
            except Exception as e:
                print(f"{Colors.RED}[Buy Failed] KRW 잔고 조회 실패: {e}{Colors.ENDC}")
                return False
            
            # [v7.8.1] 가용 현금이 최소 주문 금액(5,000원) 미만이면 즉시 종료
            if krw_balance < 5000:
                print(f"{Colors.YELLOW}[Buy Skip] 가용 현금 부족{Colors.ENDC}")
                print(f"  └ 가용현금: {krw_balance:,.0f}원 < 최소주문금액 5,000원")
                return False
            
            # ========================================
            # Step 2: 총 자산 계산 (현금 + 모든 코인 평가액)
            # ========================================
            try:
                total_assets = get_total_balance()
                if total_assets is None or total_assets <= 0:
                    total_assets = krw_balance  # 폴백: 현금만 사용
            except Exception as e:
                print(f"{Colors.RED}[Buy Failed] 총 자산 조회 실패: {e}{Colors.ENDC}")
                return False
            
            # ========================================
            # Step 3: 목표 포지션 사이즈 계산
            # ========================================
            target_position_size = total_assets * POSITION_SIZE_RATIO
            
            # ========================================
            # [v7.8.1] Step 4: 매수 금액 결정 (안전하게)
            # - 목표 포지션과 가용 현금 중 작은 값 선택
            # - 수수료 고려하여 0.9995 적용
            # ========================================
            available_for_buy = krw_balance * 0.9995  # 수수료 고려
            buy_amount = min(target_position_size, available_for_buy)
            
            # ========================================
            # Step 5: 최소 주문 금액 체크 (5,000원)
            # ========================================
            if buy_amount < 5000:
                print(f"{Colors.YELLOW}[Buy Limit] 매수 금액 부족{Colors.ENDC}")
                print(f"  └ 총자산: {total_assets:,.0f}원 | 가용현금: {krw_balance:,.0f}원")
                print(f"  └ 목표포지션: {target_position_size:,.0f}원 | 실제매수가능: {buy_amount:,.0f}원 < 5,000원")
                return False
            
            # ========================================
            # [v7.8.1] 개선된 매수 정보 로그 (가용현금 포함)
            # ========================================
            coin_value = total_assets - krw_balance  # 보유 코인 평가액
            print(f"{Colors.CYAN}[Buy Info] 총자산: {total_assets:,.0f}원 "
                  f"(코인: {coin_value:,.0f}원 + 현금: {krw_balance:,.0f}원){Colors.ENDC}")
            print(f"{Colors.CYAN}[Buy Info] 목표포지션: {target_position_size:,.0f}원 | "
                  f"실제매수: {buy_amount:,.0f}원{Colors.ENDC}")
            
            # ========================================
            # TEST MODE: 시뮬레이션
            # ========================================
            if TEST_MODE:
                print(f"{Colors.GREEN}[TEST] 매수 시뮬레이션: {ticker} {buy_amount:,.0f}원{Colors.ENDC}")
                
                with held_coins_lock:
                    held_coins[ticker] = {
                        'buy_price': signal['entry_price'],
                        'buy_time': datetime.now(),
                        'buy_amount': buy_amount,
                        'peak_price': signal['entry_price'],
                        'peak_time': datetime.now(),
                        'buy_reason': signal['reason'],
                        'buy_mode': signal.get('mode', 'NORMAL')
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
                # [v7.8.1] 매수 직전 최종 잔고 재확인
                final_krw = upbit.get_balance("KRW")
                if final_krw is None or final_krw < buy_amount:
                    print(f"{Colors.RED}[Buy Failed] 매수 직전 잔고 부족{Colors.ENDC}")
                    print(f"  └ 필요금액: {buy_amount:,.0f}원 | 실제잔고: {final_krw:,.0f}원")
                    # 잔고에 맞춰 재조정
                    if final_krw and final_krw >= 5000:
                        buy_amount = final_krw * 0.9995
                        print(f"{Colors.CYAN}[Buy Info] 잔고에 맞춰 재조정: {buy_amount:,.0f}원{Colors.ENDC}")
                    else:
                        return False
                
                result = upbit.buy_market_order(ticker, buy_amount)
                
                if result is None:
                    print(f"{Colors.RED}[Buy Failed] 주문 실패 (API 응답 없음){Colors.ENDC}")
                    return False
                
                # API 오류 응답 체크
                if isinstance(result, dict) and 'error' in result:
                    error_info = result.get('error', {})
                    error_name = error_info.get('name', 'Unknown')
                    error_msg = error_info.get('message', 'Unknown error')
                    print(f"{Colors.RED}[Buy Failed] API 오류: {error_name} - {error_msg}{Colors.ENDC}")
                    return False
                
                time.sleep(1)
                
                # 체결 확인
                balances = upbit.get_balances()
                coin_balance = None
                
                for bal in balances:
                    if bal['currency'] == ticker.split('-')[1]:
                        coin_balance = bal
                        break
                
                if not coin_balance:
                    print(f"{Colors.RED}[Buy Failed] 체결 후 잔고 확인 실패{Colors.ENDC}")
                    return False
                
                actual_buy_price = float(coin_balance['avg_buy_price'])
                
                with held_coins_lock:
                    held_coins[ticker] = {
                        'buy_price': actual_buy_price,
                        'buy_time': datetime.now(),
                        'buy_amount': buy_amount,
                        'peak_price': actual_buy_price,
                        'peak_time': datetime.now(),
                        'buy_reason': signal['reason'],
                        'buy_mode': signal.get('mode', 'NORMAL')
                    }
                
                daily_trade_count += 1
                daily_buy_count += 1
                total_trades += 1
                
                print(f"{Colors.GREEN}[Buy Success] {ticker} @ {actual_buy_price:,.0f}원 "
                      f"(투자액: {buy_amount:,.0f}원){Colors.ENDC}")
                
                send_buy_notification(ticker, signal, buy_amount, total_assets)
                return True
                
            except Exception as e:
                error_str = str(e)
                print(f"{Colors.RED}[Buy Failed] 주문 실행 오류: {error_str}{Colors.ENDC}")
                
                # InsufficientFundsBid 오류 상세 로깅
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
                
                time.sleep(1)
                
                # 실제 체결 가격 확인
                try:
                    current_price = pyupbit.get_current_price(ticker)
                    actual_sell_price = current_price if current_price else sell_price
                except:
                    actual_sell_price = sell_price
                
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
    [v8.0] 모멘텀 기반 매수 스레드
    
    핵심 변경사항:
    1. get_extended_candles_15m() 사용 (200개)
    2. get_extended_candles_5m() 사용 (100개)
    3. evolution_80_buy_signal() 호출
    """
    print(f"{Colors.CYAN}[Thread 1] v8.0 모멘텀 매수 스레드 시작 ({BUY_THREAD_INTERVAL}초 주기){Colors.ENDC}")
    
    iteration = 0
    
    while not stop_event.is_set():
        try:
            iteration += 1
            
            # 연속 손실 체크
            if not check_consecutive_losses():
                if DEBUG_MODE and iteration % 10 == 0:
                    print(f"{Colors.YELLOW}[BUY] 연속 손실 쿨다운 중...{Colors.ENDC}")
                time.sleep(BUY_THREAD_INTERVAL)
                continue
            
            # 시장 상태 체크
            market_ok, market_change = check_market_condition()
            if not market_ok:
                if DEBUG_MODE and iteration % 10 == 0:
                    print(f"{Colors.YELLOW}[BUY] 시장 불안정 ({market_change:.2f}%){Colors.ENDC}")
                time.sleep(BUY_THREAD_INTERVAL)
                continue
            
            # 일일 거래 한도 체크
            if not check_daily_trade_limit():
                if DEBUG_MODE and iteration % 30 == 0:
                    print(f"{Colors.YELLOW}[BUY] 일일 거래 한도 도달{Colors.ENDC}")
                time.sleep(BUY_THREAD_INTERVAL)
                continue
            
            # 보유 종목 수 체크
            with held_coins_lock:
                current_holdings = len(held_coins)
            
            if current_holdings >= MAX_HOLDINGS:
                if DEBUG_MODE and iteration % 30 == 0:
                    print(f"{Colors.YELLOW}[BUY] 최대 보유 종목 도달 ({current_holdings}/{MAX_HOLDINGS}){Colors.ENDC}")
                time.sleep(BUY_THREAD_INTERVAL)
                continue
            
            # 일일 카운터 리셋 체크
            reset_daily_counter()
            
            # 각 코인별 매수 검토
            for ticker in FIXED_STABLE_COINS:
                
                if stop_event.is_set():
                    print(f"{Colors.CYAN}[Thread 1] 종료 신호 수신{Colors.ENDC}")
                    return
                
                # 이미 보유 중인지 체크
                with held_coins_lock:
                    if ticker in held_coins:
                        continue
                
                # 재진입 쿨다운 체크
                can_enter, cooldown_reason = check_reentry_cooldown(ticker)
                if not can_enter:
                    continue
                
                # ========================================
                # [v8.0] 확장 데이터 수집 (200개/100개)
                # ========================================
                df_15m = get_extended_candles_15m(ticker, count=V80_CANDLES_15M_COUNT)
                
                if df_15m is None or len(df_15m) < 50:
                    if DEBUG_MODE:
                        print(f"{Colors.RED}[BUY] {ticker} 15분봉 데이터 부족{Colors.ENDC}")
                    continue
                
                # 5분봉은 선택적 (없어도 매수 가능)
                df_5m = get_extended_candles_5m(ticker, count=V80_CANDLES_5M_COUNT)
                
                # ========================================
                # [v8.0] 모멘텀 기반 매수 신호 체크
                # ========================================
                buy_signal = evolution_80_buy_signal(df_15m, df_5m, ticker)
                
                if buy_signal['signal']:
                    coin_name = ticker.replace('KRW-', '')
                    
                    # 매수 신호 상세 출력
                    print(f"\n{Colors.CYAN}{'='*50}")
                    print(f"[BUY SIGNAL] {coin_name} 모멘텀 매수!")
                    print(f"{'='*50}{Colors.ENDC}")
                    print(f"  📊 모멘텀 점수: {buy_signal.get('momentum_score', 0)}점")
                    print(f"  🎯 트리거: {buy_signal.get('trigger_type', 'N/A')}")
                    print(f"  📈 BB 위치: {buy_signal['bb_position']:.1f}%")
                    print(f"  💰 진입가: {buy_signal['entry_price']:,.0f}원")
                    print(f"  🔒 신뢰도: {buy_signal['confidence']}%")
                    print(f"  📝 사유: {buy_signal['reason']}")
                    print(f"{Colors.CYAN}{'='*50}{Colors.ENDC}\n")
                    
                    # 매수 실행
                    success = execute_buy(ticker, buy_signal)
                    
                    if success:
                        print(f"{Colors.GREEN}[BUY] {coin_name} 매수 완료!{Colors.ENDC}")
                    else:
                        print(f"{Colors.RED}[BUY] {coin_name} 매수 실패{Colors.ENDC}")
                    
                    time.sleep(2)  # API 호출 간격
                    
                    # 최대 보유 종목 도달 체크
                    with held_coins_lock:
                        if len(held_coins) >= MAX_HOLDINGS:
                            print(f"{Colors.YELLOW}[BUY] 최대 보유 종목 도달, 매수 중단{Colors.ENDC}")
                            break
                
                # API 호출 간격 (코인 간)
                time.sleep(0.5)
            
            time.sleep(BUY_THREAD_INTERVAL)
            
        except Exception as e:
            error_trace = traceback.format_exc()
            print(f"{Colors.RED}[BUY Thread Error] {e}{Colors.ENDC}")
            if DEBUG_MODE:
                print(error_trace)
            
            # 에러 발생 시 Discord 알림 (선택적)
            if 'critical' in str(e).lower() or 'fatal' in str(e).lower():
                send_error_notification("BUY Thread Critical Error", error_trace[:500])
            
            time.sleep(BUY_THREAD_INTERVAL)
    
    print(f"{Colors.CYAN}[Thread 1] v8.0 모멘텀 매수 스레드 종료{Colors.ENDC}")


def sell_thread_worker():
    """
    [v8.0] 모멘텀 기반 매도 스레드
    
    핵심 변경사항:
    1. get_extended_candles_15m() 사용 (200개)
    2. evolution_80_sell_signal() 호출
    3. 피크 가격/BB 추적 강화
    4. held_info에 peak_bb_position 추가
    """
    print(f"{Colors.YELLOW}[Thread 2] v8.0 매도 스레드 시작 ({SELL_THREAD_INTERVAL}초 주기){Colors.ENDC}")
    
    iteration = 0
    
    while not stop_event.is_set():
        try:
            iteration += 1
            
            # 보유 종목 목록 조회
            with held_coins_lock:
                tickers = list(held_coins.keys())
            
            if not tickers:
                if DEBUG_MODE and iteration % 60 == 0:
                    print(f"{Colors.YELLOW}[SELL] 보유 종목 없음{Colors.ENDC}")
                time.sleep(SELL_THREAD_INTERVAL)
                continue
            
            # 각 보유 종목별 매도 검토
            for ticker in tickers:
                
                if stop_event.is_set():
                    print(f"{Colors.YELLOW}[Thread 2] 종료 신호 수신{Colors.ENDC}")
                    return
                
                # ========================================
                # [v8.0] 확장 데이터 수집 (200개)
                # ========================================
                df_15m = get_extended_candles_15m(ticker, count=V80_CANDLES_15M_COUNT)
                
                if df_15m is None or len(df_15m) < 20:
                    if DEBUG_MODE:
                        print(f"{Colors.RED}[SELL] {ticker} 데이터 부족{Colors.ENDC}")
                    continue
                
                current_price = df_15m.iloc[-1]['close']
                current_bb = df_15m.iloc[-1]['bb_position']
                
                # ========================================
                # 보유 정보 조회 및 피크 업데이트
                # ========================================
                with held_coins_lock:
                    if ticker not in held_coins:
                        continue
                    
                    held_info = held_coins[ticker]
                    
                    # 피크 가격 업데이트
                    current_peak_price = held_info.get('peak_price', held_info['buy_price'])
                    if current_price > current_peak_price:
                        held_info['peak_price'] = current_price
                        held_info['peak_time'] = datetime.now()
                        if DEBUG_MODE:
                            coin_name = ticker.replace('KRW-', '')
                            print(f"{Colors.GREEN}[SELL] {coin_name} 신고가 갱신: {current_price:,.0f}원{Colors.ENDC}")
                    
                    # 피크 BB 위치 업데이트
                    current_peak_bb = held_info.get('peak_bb_position', 0)
                    if current_bb > current_peak_bb:
                        held_info['peak_bb_position'] = current_bb
                    
                    # 필요한 정보 복사 (락 밖에서 사용)
                    buy_price = held_info['buy_price']
                    buy_time = held_info.get('buy_time', datetime.now())
                    buy_amount = held_info.get('buy_amount', 0)
                    buy_reason = held_info.get('buy_reason', '')
                    
                    # held_info 전체 복사
                    held_info_copy = {
                        'ticker': ticker,
                        'buy_price': buy_price,
                        'buy_time': buy_time,
                        'buy_amount': buy_amount,
                        'buy_reason': buy_reason,
                        'peak_price': held_info.get('peak_price', buy_price),
                        'peak_time': held_info.get('peak_time', buy_time),
                        'peak_bb_position': held_info.get('peak_bb_position', 0),
                        'buy_mode': held_info.get('buy_mode', 'MOMENTUM_V80')
                    }
                
                # ========================================
                # [v8.0] 모멘텀 기반 매도 신호 체크
                # ========================================
                sell_signal = evolution_80_sell_signal(df_15m, buy_price, buy_time, held_info_copy)
                
                # 피크 정보를 원본에 다시 반영 (sell_signal 함수에서 업데이트될 수 있음)
                with held_coins_lock:
                    if ticker in held_coins:
                        if 'peak_price' in held_info_copy:
                            held_coins[ticker]['peak_price'] = held_info_copy['peak_price']
                        if 'peak_time' in held_info_copy:
                            held_coins[ticker]['peak_time'] = held_info_copy['peak_time']
                        if 'peak_bb_position' in held_info_copy:
                            held_coins[ticker]['peak_bb_position'] = held_info_copy['peak_bb_position']
                
                # ========================================
                # 매도 신호 처리
                # ========================================
                if sell_signal['signal']:
                    profit_pct = sell_signal['profit_pct']
                    coin_name = ticker.replace('KRW-', '')
                    
                    # 수익/손실에 따른 색상
                    if profit_pct >= 0:
                        color = Colors.GREEN
                        emoji = "📈"
                    else:
                        color = Colors.RED
                        emoji = "📉"
                    
                    # 매도 신호 상세 출력
                    print(f"\n{color}{'='*50}")
                    print(f"[SELL SIGNAL] {coin_name} 매도!")
                    print(f"{'='*50}{Colors.ENDC}")
                    print(f"  {emoji} 수익률: {profit_pct:+.2f}%")
                    print(f"  📊 BB 위치: {sell_signal['bb_position']:.1f}%")
                    print(f"  💰 매도가: {sell_signal['exit_price']:,.0f}원")
                    print(f"  📝 사유: {sell_signal['reason']}")
                    
                    # 보유 시간 계산
                    if buy_time:
                        hold_duration = format_duration(datetime.now() - buy_time)
                        print(f"  ⏱️ 보유시간: {hold_duration}")
                    
                    # 피크 대비 현재가
                    peak_price = held_info_copy.get('peak_price', buy_price)
                    if peak_price > buy_price:
                        peak_profit = ((peak_price - buy_price) / buy_price) * 100
                        drawdown = ((peak_price - sell_signal['exit_price']) / peak_price) * 100
                        print(f"  🏔️ 고점: {peak_price:,.0f}원 (+{peak_profit:.2f}%), 현재 -{drawdown:.1f}%")
                    
                    print(f"{color}{'='*50}{Colors.ENDC}\n")
                    
                    # 매도 실행
                    success = execute_sell(ticker, sell_signal)
                    
                    if success:
                        print(f"{color}[SELL] {coin_name} 매도 완료! ({profit_pct:+.2f}%){Colors.ENDC}")
                    else:
                        print(f"{Colors.RED}[SELL] {coin_name} 매도 실패{Colors.ENDC}")
                    
                    time.sleep(2)  # API 호출 간격
                
                else:
                    # 매도 신호 없음 - 상태 로깅 (선택적)
                    if DEBUG_MODE and iteration % 60 == 0:
                        profit_pct = sell_signal['profit_pct']
                        coin_name = ticker.replace('KRW-', '')
                        print(f"{Colors.CYAN}[SELL] {coin_name}: {profit_pct:+.2f}%, BB:{sell_signal['bb_position']:.0f}%, {sell_signal['reason']}{Colors.ENDC}")
                
                # API 호출 간격 (코인 간)
                time.sleep(0.3)
            
            time.sleep(SELL_THREAD_INTERVAL)
            
        except Exception as e:
            error_trace = traceback.format_exc()
            print(f"{Colors.RED}[SELL Thread Error] {e}{Colors.ENDC}")
            if DEBUG_MODE:
                print(error_trace)
            
            # 에러 발생 시 Discord 알림 (선택적)
            if 'critical' in str(e).lower() or 'fatal' in str(e).lower():
                send_error_notification("SELL Thread Critical Error", error_trace[:500])
            
            time.sleep(SELL_THREAD_INTERVAL)
    
    print(f"{Colors.YELLOW}[Thread 2] v8.0 매도 스레드 종료{Colors.ENDC}")


def monitor_thread_worker():
    """Monitor thread worker (60 sec cycle) - Hourly reporting (ENHANCED)"""
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
                current_win_rate = (winning_trades / total_trades * 100) if total_trades > 0 else 0
                current_avg_profit = (total_profit / total_trades) if total_trades > 0 else 0
            
            print(f"\n{Colors.MAGENTA}{'='*10}")
            print(f"[Monitor] 반복 #{iteration} | {current_time.strftime('%H:%M:%S')}")
            print(f"  보유: {current_holdings}/{MAX_HOLDINGS} | "
                  f"거래: {total_trades}회 (금일 {daily_trade_count}회) | "
                  f"승률: {current_win_rate:.1f}%")
            print(f"  평균 수익: {current_avg_profit:+.2f}%")
            
            with held_coins_lock:
                for ticker, info in held_coins.items():
                    try:
                        current_price = pyupbit.get_current_price(ticker)
                        if current_price:
                            profit = ((current_price - info['buy_price']) / info['buy_price']) * 100
                            duration = format_duration(current_time - info['buy_time'])
                            coin_name = ticker.replace("KRW-", "")
                            print(f"  - {coin_name}: {profit:+.2f}% ({duration})")
                    except:
                        pass
            
            print(f"{'='*10}{Colors.ENDC}\n")
            
            # Enhanced hourly reporting logic
            elapsed_since_report = (current_time - last_report_time).total_seconds()
            current_minute = current_time.minute
            
            # 조건: 59분 이상 경과 AND 현재 0-3분 사이 (윈도우 확대)
            if elapsed_since_report >= 3540 and 0 <= current_minute <= 3:
                print(f"{Colors.GREEN}[Monitor] 매시각 정시 보고 트리거 ({current_time.strftime('%H:%M')}){Colors.ENDC}")
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


# ================================================================================
# SECTION 19: Main Function
# ================================================================================

def main():
    """Main function - Thread orchestration"""
    
    global upbit
    
    # Initialize Upbit
    try:
        upbit = pyupbit.Upbit(ACCESS_KEY, SECRET_KEY)
        print(f"{Colors.GREEN}[Init] Upbit API 연결 완료{Colors.ENDC}\n")
    except Exception as e:
        print(f"{Colors.RED}[Error] Upbit API 연결 실패: {e}{Colors.ENDC}")
        return
    
    # Sync existing positions (NEW!)
    print(f"{Colors.CYAN}[Init] 기존 보유 코인 동기화 중...{Colors.ENDC}")
    sync_success = sync_held_coins_with_exchange()
    
    if not sync_success:
        print(f"{Colors.YELLOW}[Warning] 동기화 실패했지만 계속 진행합니다.{Colors.ENDC}\n")
    
    # Start notification
    with held_coins_lock:
        synced_coins = len(held_coins)
    
    start_message = f"""
**🤖 봇 시작**

**버전:** `{VERSION}`
**모드:** `{'TEST MODE' if TEST_MODE else 'LIVE MODE'}`
**관심 코인:** `{len(FIXED_STABLE_COINS)}개`
**최대 보유:** `{MAX_HOLDINGS}개`
**동기화된 기존 보유:** `{synced_coins}개`

**전략:**
- 매수: BB <=20% 하단 반전 (85+ 점수)
- 매도: BB <80% 홀드, 80-95% 모멘텀 체크
- 예외: 대형 랠리 놓치지 않기
- 손절: -3%

**스레드:**
- Thread 1: 매수 ({BUY_THREAD_INTERVAL}초)
- Thread 2: 매도 ({SELL_THREAD_INTERVAL}초)
- Thread 3: 모니터 ({MONITOR_THREAD_INTERVAL}초)

⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
"""
    send_discord_message(start_message)
    
    # Create and start threads
    buy_thread = threading.Thread(target=buy_thread_worker, name="BuyThread", daemon=True)
    sell_thread = threading.Thread(target=sell_thread_worker, name="SellThread", daemon=True)
    monitor_thread = threading.Thread(target=monitor_thread_worker, name="MonitorThread", daemon=True)
    
    buy_thread.start()
    time.sleep(1)
    sell_thread.start()
    time.sleep(1)
    monitor_thread.start()
    
    print(f"{Colors.GREEN}[Main] 모든 스레드 시작 완료{Colors.ENDC}\n")
    
    try:
        while True:
            time.sleep(1)
            
    except KeyboardInterrupt:
        print(f"\n{Colors.RED}{'='*10}")
        print(f"[Exit] 사용자 중단 - 안전 종료 시작")
        print(f"{'='*10}{Colors.ENDC}")
        
        stop_event.set()
        
        print(f"{Colors.YELLOW}[Exit] 스레드 종료 대기 중...{Colors.ENDC}")
        buy_thread.join(timeout=10)
        sell_thread.join(timeout=10)
        monitor_thread.join(timeout=10)
        
        runtime = format_duration(datetime.now() - start_time)
        with statistics_lock:
            final_win_rate = (winning_trades / total_trades * 100) if total_trades > 0 else 0
        
        end_message = f"""
**🛑 봇 종료**

**가동 시간:** `{runtime}`
**총 거래:** `{total_trades}회`
**승:** `{winning_trades}` | **패:** `{losing_trades}`
**승률:** `{final_win_rate:.1f}%`

⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
"""
        send_discord_message(end_message)
        
        print(f"{Colors.GREEN}[Exit] 모든 스레드 종료 완료{Colors.ENDC}")


# ================================================================================
# SECTION 20: Program Entry Point
# ================================================================================

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        error_trace = traceback.format_exc()
        print(f"{Colors.RED}[Fatal Error] {error_trace}{Colors.ENDC}")
        send_error_notification("Fatal Error", error_trace)