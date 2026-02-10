#!/usr/bin/env python3
# -*- coding: utf-8 -*-

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
VERSION = "11.0 BOUNCE_HUNTER"

FIXED_STABLE_COINS = [
    "KRW-ETH", "KRW-XRP", "KRW-SOL",
    "KRW-ADA", "KRW-LINK", "KRW-BCH", "KRW-SUI"
]

POSITION_SIZE_RATIO = 0.5
MAX_HOLDINGS = 2
FIRST_BUY_RATIO = 0.5             # 1차 매수 비율 (가용현금의 50%)
BUY_FEE_BUFFER = 0.995
MAX_DAILY_TRADES = 999

# Thread intervals
BUY_THREAD_INTERVAL = 10
SELL_THREAD_INTERVAL = 5
MONITOR_THREAD_INTERVAL = 60

# API Cache
CACHE_TTL_FAST = 10
CACHE_TTL_NORMAL = 20
CACHE_TTL_SLOW = 30


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
    'DEFAULT': 10,
    'MOMENTUM_EXIT': 15,       # [v11.0] 모멘텀 소진 매도
    'EXHAUSTION_EXIT': 10,     # [v11.0] 소진 익절
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
# V10_DAILY_RSI_MIN = 30                 # 일봉 RSI 하한
# V10_DAILY_RSI_MAX = 70                 # 일봉 RSI 상한
V10_DAILY_BULLISH_DAYS_MIN = 2         # 최근 3일 중 최소 양봉 수 (3일 중)
V10_DAILY_CONSECUTIVE_BEAR_MAX = 3     # 최대 연속 음봉 허용
V10_DAILY_CHANGE_MAX = 5.0             # 당일 최대 등락률 (%) - 급등 차단
V10_DAILY_CHANGE_MIN = -5.0            # 당일 최소 등락률 (%) - 급락 차단

# ----------------------------------------
# Phase 2: 15분봉 위치 필터 (조정 구간 포착)
# ----------------------------------------
V10_15M_BB_MIN = 5                     # BB 위치 하한 (%) - 극단 제외
V10_15M_BB_MAX = 35                    # BB 위치 상한 (%) - 이미 반등 제외
V10_15M_BB_WIDTH_MIN = 2.5             # BB 폭 최소 (%) - 횡보장 제외
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

# ================================================================================
# SECTION 8: Startup Message
# ================================================================================

VERSION = "11.0 BOUNCE_HUNTER"

print(f"\\n{Colors.BOLD}{Colors.CYAN}{'='*60}")
print(f"EVOLUTION {VERSION}")
print(f"{'='*60}")
print(f"{Colors.GREEN}[v11.0] BOUNCE HUNTER - 매도 심층 개선{Colors.ENDC}")
print(f"   [핵심] 매수3Phase ↔ 매도3Step 대칭 구조")
print(f"   [매수] 일봉양봉 → BB하단 → 반등5지표")
print(f"   [매도] 손절→극과매수→소진7지표(동적임계치)→동적트레일링")
print(f"   [신규] SRSI/MACD/SwingHigh/LowerHigh 매도 활용")
print(f"")
print(f"{Colors.YELLOW}Phase 3 반등 신호 (5개 중 3개+){Colors.ENDC}")
print(f"   ① RSI 상승 전환")
print(f"   ② Stochastic RSI 과매도 탈출 / 골든 크로스")
print(f"   ③ MACD 히스토그램 전환 / 축소")
print(f"   ④ 양봉 출현")
print(f"   ⑤ 거래량 확인 (MA20 × 0.8+)")
print(f"")
print(f"{Colors.MAGENTA}THREADED EDITION{Colors.ENDC}")
print(f"   Thread 1: 매수 ({BUY_THREAD_INTERVAL}초)")
print(f"   Thread 2: 매도 ({SELL_THREAD_INTERVAL}초)")
print(f"   Thread 3: 모니터 ({MONITOR_THREAD_INTERVAL}초)")
print(f"   MAX_HOLDINGS: {MAX_HOLDINGS} | 1차:{FIRST_BUY_RATIO:.0%} 2차:전량")
print(f"{'='*60}{Colors.ENDC}\\n")


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
    """
    [v8.0] 단일 코인 기술적 분석 (모멘텀 정보 포함)
    
    Args:
        ticker: 코인 티커 (예: "KRW-BTC")
    
    Returns:
        dict: 분석 결과 (momentum 정보 포함)
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
        
        # 일봉 BB 위치 조회
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
        buy_price = None
        with held_coins_lock:
            if ticker in held_coins:
                buy_price = held_coins[ticker]['buy_price']
                holding_profit = ((current_price - buy_price) / buy_price) * 100
                buy_mode = held_coins[ticker].get('buy_mode', 'NORMAL')
        
        # 신호 판단
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
    

def calculate_coin_status_for_report(ticker):
    """
    [v10.2] 보고서용 코인 상태 분석
    
    v10.2 변경사항:
    - Phase 1: 일봉 RSI 필터 제거 반영 (check_daily_safety_filter 변경에 따라 자동 적용)
    - Phase 3: 개별 지표 충족/미충족 상세 표시 (R✅S❌M✅B✅V❌ 형태)
    
    표시 정보:
    1. 일봉 양봉/음봉 + 등락률
    2. 일봉 저가/고가 대비 현재가 위치 (캔들파워)
    3. 매수 3-Phase 판정 결과 (Higher Low 정보 포함)
    """
    try:
        # ========================================
        # 일봉 데이터 수집 + 캔들 파워 분석
        # ========================================
        df_daily = get_candles_daily(ticker, count=50)
        
        daily_status = '?'
        daily_emoji = '⚪'
        daily_change = 0.0
        rise_from_low = 0.0
        drop_from_high = 0.0
        power_emoji = '➡️'
        power_label = '중립'
        
        if df_daily is not None and len(df_daily) >= 1:
            today = df_daily.iloc[-1]
            d_open = today['open']
            d_close = today['close']
            d_high = today['high']
            d_low = today['low']
            
            # 양봉/음봉
            if d_close >= d_open:
                daily_status = '양봉'
                daily_emoji = '🟢'
            else:
                daily_status = '음봉'
                daily_emoji = '🔴'
            
            # 등락률 (시가 대비)
            daily_change = ((d_close - d_open) / d_open * 100) if d_open > 0 else 0
            
            # 저가 대비 상승률, 고가 대비 하락률
            if d_low > 0:
                rise_from_low = ((d_close - d_low) / d_low) * 100
            if d_high > 0:
                drop_from_high = ((d_high - d_close) / d_high) * 100
            
            # 캔들 파워 판정
            if rise_from_low > 0.01 or drop_from_high > 0.01:
                if drop_from_high < 0.01:
                    power_emoji = '⚡'
                    power_label = '강세'
                elif rise_from_low < 0.01:
                    power_emoji = '👀'
                    power_label = '약세'
                elif rise_from_low > drop_from_high * 2:
                    power_emoji = '⚡'
                    power_label = '강세'
                elif drop_from_high > rise_from_low * 2:
                    power_emoji = '👀'
                    power_label = '약세'
                else:
                    power_emoji = '➡️'
                    power_label = '중립'
            else:
                power_emoji = '⏸️'
                power_label = '횡보'
        
        # ========================================
        # 매수 3-Phase 판정
        # ========================================
        p1_pass = False
        p1_reason = '미검사'
        p2_pass = False
        p2_reason = '미검사'
        p3_pass = False
        p3_reason = '미검사'
        hl_info = ''  # Higher Low 정보
        
        # Phase 1: 일봉 필터
        daily_safety = check_daily_safety_filter(ticker)
        if daily_safety['safe']:
            p1_pass = True
            p1_reason = '일봉OK'
        else:
            p1_reason = daily_safety['reason']
            short_reason = p1_reason
            if len(short_reason) > 15:
                short_reason = short_reason[:15]
            
            return {
                'daily_status': daily_status, 'daily_emoji': daily_emoji,
                'daily_change': daily_change,
                'rise_from_low': rise_from_low, 'drop_from_high': drop_from_high,
                'power_emoji': power_emoji, 'power_label': power_label,
                'p1_pass': False, 'p1_reason': short_reason,
                'p2_pass': False, 'p2_reason': '-',
                'p3_pass': False, 'p3_reason': '-',
                'final_signal': '대기', 'phase_str': '❌',
                'reject_phase': 'P1', 'reject_detail': short_reason,
                'hl_info': ''
            }
        
        # Phase 2: 15분봉 BB 위치 + Higher Low
        df_15m = get_extended_candles_15m(ticker, count=50)
        if df_15m is not None and len(df_15m) >= 20:
            position_check = detect_downtrend_15m(df_15m)
            
            # Higher Low 정보 추출
            if position_check.get('higher_low') is True:
                hl_info = 'HL✅'
            elif position_check.get('higher_low') is False:
                hl_info = 'LL❌'
            else:
                hl_info = ''
            
            if not position_check['is_downtrend']:
                p2_pass = True
                p2_reason = f"BB{position_check['bb_position']:.0f}%{hl_info}"
            else:
                p2_reason = position_check['reason']
                short_reason = p2_reason
                if len(short_reason) > 20:
                    short_reason = short_reason[:20]
                
                return {
                    'daily_status': daily_status, 'daily_emoji': daily_emoji,
                    'daily_change': daily_change,
                    'rise_from_low': rise_from_low, 'drop_from_high': drop_from_high,
                    'power_emoji': power_emoji, 'power_label': power_label,
                    'p1_pass': True, 'p1_reason': '일봉OK',
                    'p2_pass': False, 'p2_reason': short_reason,
                    'p3_pass': False, 'p3_reason': '-',
                    'final_signal': '대기', 'phase_str': '✅❌',
                    'reject_phase': 'P2', 'reject_detail': short_reason,
                    'hl_info': hl_info
                }
        else:
            return {
                'daily_status': daily_status, 'daily_emoji': daily_emoji,
                'daily_change': daily_change,
                'rise_from_low': rise_from_low, 'drop_from_high': drop_from_high,
                'power_emoji': power_emoji, 'power_label': power_label,
                'p1_pass': True, 'p1_reason': '일봉OK',
                'p2_pass': False, 'p2_reason': '데이터부족',
                'p3_pass': False, 'p3_reason': '-',
                'final_signal': '대기', 'phase_str': '✅❌',
                'reject_phase': 'P2', 'reject_detail': '15분봉부족',
                'hl_info': ''
            }
        
        # Phase 3: 반등 신호
        reversal = calculate_reversal_score(df_15m)
        
        # [v10.2 변경] 상세 지표 기호 생성
        p3_detail = format_reversal_detail(reversal)
        
        if reversal['bounce_confirmed']:
            p3_pass = True
            p3_reason = p3_detail
        else:
            p3_reason = p3_detail
            
            return {
                'daily_status': daily_status, 'daily_emoji': daily_emoji,
                'daily_change': daily_change,
                'rise_from_low': rise_from_low, 'drop_from_high': drop_from_high,
                'power_emoji': power_emoji, 'power_label': power_label,
                'p1_pass': True, 'p1_reason': '일봉OK',
                'p2_pass': True, 'p2_reason': p2_reason,
                'p3_pass': False, 'p3_reason': p3_reason,
                'final_signal': '부족', 'phase_str': '✅✅❌',
                'reject_phase': 'P3', 'reject_detail': p3_reason,
                'hl_info': hl_info
            }
        
        # 모든 Phase 통과 → BUY
        return {
            'daily_status': daily_status, 'daily_emoji': daily_emoji,
            'daily_change': daily_change,
            'rise_from_low': rise_from_low, 'drop_from_high': drop_from_high,
            'power_emoji': power_emoji, 'power_label': power_label,
            'p1_pass': True, 'p1_reason': '일봉OK',
            'p2_pass': True, 'p2_reason': p2_reason,
            'p3_pass': True, 'p3_reason': p3_reason,
            'final_signal': 'BUY', 'phase_str': '✅✅✅',
            'reject_phase': None, 'reject_detail': None,
            'hl_info': hl_info
        }
        
    except Exception as e:
        if DEBUG_MODE:
            print(f"{Colors.RED}[Coin Status Error] {ticker}: {e}{Colors.ENDC}")
        return {
            'daily_status': '?', 'daily_emoji': '⚪',
            'daily_change': 0, 'rise_from_low': 0, 'drop_from_high': 0,
            'power_emoji': '❓', 'power_label': '오류',
            'p1_pass': False, 'p1_reason': '오류',
            'p2_pass': False, 'p2_reason': '-',
            'p3_pass': False, 'p3_reason': '-',
            'final_signal': '오류', 'phase_str': '❓',
            'reject_phase': 'ERR', 'reject_detail': str(e)[:15],
            'hl_info': ''
        }
    

def send_enhanced_statistics_report():
    """
    [v10.0] 정시 보고서 - 캔들파워 + 3Phase 판정 기반
    
    표시 정보:
    - 자산 현황 (총자산/코인가치/현금)
    - 보유코인: 수익률 + BB/RSI + 보유시간
    - 관심코인: 일봉양봉음봉 + 캔들파워 + 3Phase 판정
    """
    try:
        portfolio = get_enhanced_portfolio_status()
        current_time = datetime.now()
        
        # ========================================
        # 1줄: 시각 + 자산 현황
        # ========================================
        if portfolio['coins']:
            total_buy_amount = sum(c.get('buy_price', 0) * c.get('balance', 0) 
                                   for c in portfolio['coins'] if c.get('buy_price', 0) > 0)
            if total_buy_amount > 0:
                coin_profit_pct = ((portfolio['total_coin_value'] - total_buy_amount) / total_buy_amount) * 100
            else:
                coin_profit_pct = 0.0
        else:
            coin_profit_pct = 0.0
        
        header = f"""⏰ {current_time.strftime('%H:%M')} | 💰 {portfolio['total_assets']:,.0f}원
코인 {portfolio['total_coin_value']:,.0f}({coin_profit_pct:+.1f}%) 현금 {portfolio['krw_balance']:,.0f}"""
        
        # ========================================
        # 보유 코인 섹션
        # ========================================
        holdings_text = ""
        
        if portfolio['coins']:
            holdings_text = f"\n\n📦 보유 {len(portfolio['coins'])}/{MAX_HOLDINGS}"
            
            for coin_info in portfolio['coins']:
                ticker = coin_info['ticker']
                coin_name = ticker.replace('KRW-', '')
                
                profit_pct = coin_info.get('profit_pct', 0)
                buy_price = coin_info.get('buy_price', 0)
                current_price = coin_info.get('current_price', 0)
                
                # BB/RSI 조회
                analysis = get_coin_analysis(ticker)
                bb_pos = analysis['bb_position'] if analysis else 50
                rsi = analysis['rsi'] if analysis else 50
                
                # 보유 시간
                with held_coins_lock:
                    if ticker in held_coins:
                        buy_time = held_coins[ticker].get('buy_time')
                        if buy_time:
                            hold_duration = format_duration(current_time - buy_time)
                        else:
                            hold_duration = "-"
                    else:
                        hold_duration = "-"
                
                profit_emoji = "📈" if profit_pct >= 0 else "📉"
                holdings_text += f"\n├ **{coin_name}** {profit_emoji}`{profit_pct:+.2f}%` {buy_price:,.0f}→{current_price:,.0f} BB`{bb_pos:.0f}` RSI`{rsi:.0f}` ⏱{hold_duration}"
        else:
            holdings_text = f"\n\n📦 보유 0/{MAX_HOLDINGS} (대기중)"
        
        # ========================================
        # 관심 코인 섹션 (캔들파워 + 3Phase)
        # ========================================
        held_tickers = set()
        with held_coins_lock:
            held_tickers = set(held_coins.keys())
        
        watchlist_coins = [c for c in FIXED_STABLE_COINS if c not in held_tickers]
        
        watchlist_text = ""
        if watchlist_coins:
            watchlist_text = "\n"
            
            for ticker in watchlist_coins:
                coin_name = ticker.replace('KRW-', '')
                
                # 코인 상태 분석 (캔들파워 + 3Phase)
                status = calculate_coin_status_for_report(ticker)
                
                # 1줄: 코인명 + 일봉상태 + 캔들파워
                line1 = f"\n{status['daily_emoji']}**{coin_name}** {status['daily_status']}{status['daily_change']:+.1f}%{status['power_emoji']} 저↑{status['rise_from_low']:.1f}%고↓{status['drop_from_high']:.1f}%"
                
                # 2줄: Phase 판정 + 결론 + HL 정보
                hl_tag = f" {status.get('hl_info', '')}" if status.get('hl_info') else ""
                if status['final_signal'] == 'BUY':
                    line2 = f"\n └ {status['phase_str']} **BUY** ({status['p3_reason']}){hl_tag}"
                elif status['reject_phase']:
                    line2 = f"\n └ {status['phase_str']} {status['final_signal']} ({status['reject_phase']}:{status['reject_detail']}){hl_tag}"
                else:
                    line2 = f"\n └ {status['phase_str']} {status['final_signal']}{hl_tag}"
                
                watchlist_text += line1 + line2
        
        # ========================================
        # 최종 메시지 조합
        # ========================================
        message = f"""
{'─'*20}
{header}{holdings_text}{watchlist_text}
{'─'*20}
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


def check_daily_safety_filter(ticker):
    """
    [v10.2] Phase 1: 일봉 양봉 필터 (대세 상승 확인)
    
    ⚠️ v10.2 변경: 일봉 RSI 필터 제거
    - 일봉은 "양봉/음봉" + "등락률" + "연속음봉"만 체크
    - RSI, SRSI, MACD 등 기술지표 분석은 전부 15분봉(Phase 2, 3)에서 수행
    
    조건:
    1. 당일 등락률: -5% ~ +5% (급등/급락 차단)
    2. 3일 연속 음봉 아닐 것
    3. 오늘 양봉 OR 최근 3일 중 2일 양봉 (택1)
    
    Returns:
        dict: {safe, daily_change, reason, is_bullish, daily_bb, daily_rsi}
    """
    try:
        # 일봉 데이터 수집
        df_daily = get_candles_daily(ticker, count=50)
        
        if df_daily is None or len(df_daily) < 20:
            return {
                'safe': False,
                'daily_change': 0,
                'reason': '일봉 데이터 부족',
                'is_bullish': False,
                'daily_bb': 50,
                'daily_rsi': 50
            }
        
        df_daily = add_indicators(df_daily)
        if df_daily is None:
            return {
                'safe': False,
                'daily_change': 0,
                'reason': '일봉 지표 계산 실패',
                'is_bullish': False,
                'daily_bb': 50,
                'daily_rsi': 50
            }
        
        current = df_daily.iloc[-1]
        daily_open = current['open']
        daily_close = current['close']
        daily_rsi = current['rsi']        # 반환용으로만 유지 (필터링에 사용 안 함)
        daily_bb = current['bb_position'] # 반환용으로만 유지
        
        # 당일 등락률
        daily_change = ((daily_close - daily_open) / daily_open * 100) if daily_open > 0 else 0
        
        base_info = {
            'daily_change': daily_change,
            'daily_bb': daily_bb,
            'daily_rsi': daily_rsi
        }
        
        # ========================================
        # 체크 1: 당일 등락률 범위
        # ========================================
        if daily_change > V10_DAILY_CHANGE_MAX:
            return {**base_info, 'safe': False, 'is_bullish': True,
                    'reason': f'당일 급등 {daily_change:+.1f}%'}
        
        if daily_change < V10_DAILY_CHANGE_MIN:
            return {**base_info, 'safe': False, 'is_bullish': False,
                    'reason': f'당일 급락 {daily_change:+.1f}%'}
        
        # ========================================
        # [v10.2 삭제] 체크 2: 일봉 RSI 범위 → 제거
        # RSI/SRSI/MACD 등 기술지표는 15분봉에서만 분석
        # ========================================
        
        # ========================================
        # 체크 2: 연속 음봉 체크 (기존 체크3 → 체크2로 번호 변경)
        # ========================================
        consecutive_bear = 0
        for i in range(-1, -4, -1):
            if len(df_daily) + i >= 0:
                candle = df_daily.iloc[i]
                if candle['close'] < candle['open']:
                    consecutive_bear += 1
                else:
                    break
        
        if consecutive_bear >= V10_DAILY_CONSECUTIVE_BEAR_MAX:
            return {**base_info, 'safe': False, 'is_bullish': False,
                    'reason': f'{consecutive_bear}일 연속 음봉'}
        
        # ========================================
        # 체크 3: 양봉 조건 (핵심) (기존 체크4 → 체크3으로 번호 변경)
        # 오늘 양봉 OR 최근 3일 중 2일 양봉
        # ========================================
        is_today_bullish = daily_close > daily_open
        
        recent_3 = df_daily.tail(3)
        bullish_days = sum(1 for _, c in recent_3.iterrows() if c['close'] > c['open'])
        recent_bullish_ok = bullish_days >= V10_DAILY_BULLISH_DAYS_MIN
        
        if not is_today_bullish and not recent_bullish_ok:
            return {**base_info, 'safe': False, 'is_bullish': False,
                    'reason': f'양봉부족 (음봉, 최근{bullish_days}/3)'}
        
        # ========================================
        # 모든 체크 통과
        # ========================================
        bullish_reason = "오늘양봉" if is_today_bullish else f"최근양봉{bullish_days}/3"
        return {
            **base_info,
            'safe': True,
            'is_bullish': is_today_bullish,
            'reason': f'일봉OK ({bullish_reason}, {daily_change:+.1f}%)'
        }
        
    except Exception as e:
        if DEBUG_MODE:
            print(f"{Colors.RED}[Daily Safety Error] {ticker}: {e}{Colors.ENDC}")
        return {
            'safe': True,  # 에러 시 통과
            'daily_change': 0, 'reason': f'체크 오류: {e}',
            'is_bullish': False, 'daily_bb': 50, 'daily_rsi': 50
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
    
def detect_downtrend_15m(df_15m):
    """
    [v10.1] Phase 2: 15분봉 위치 필터 + Higher Low 검증
    
    ⚠️ 함수명 유지, 역할 확장:
    기존: BB 하단 근처인지 확인
    추가: 직전 파동 저점보다 높은지(Higher Low) 검증
    
    반환 형식은 호환성 유지하되 의미 변경:
    - is_downtrend=True → 매수 불가 (BB 위치 부적합 OR Lower Low)
    - is_downtrend=False → 매수 가능 (BB 하단 근처 + Higher Low 확인)
    
    조건:
    1. BB 위치: 5% ~ 35%
    2. BB 폭: ≥ 1.5%
    3. RSI: ≥ 20
    4. [신규] Higher Low: 직전 파동 저점보다 현재 저점이 높을 것
    """
    try:
        if df_15m is None or len(df_15m) < 5:
            return {
                'is_downtrend': True,
                'reason': '데이터 부족',
                'bb_position': 50,
                'bb_width': 0,
                'rsi': 50,
                'higher_low': None
            }
        
        current = df_15m.iloc[-1]
        bb_position = current['bb_position']
        bb_width = current['bb_width']
        rsi = current['rsi']
        
        # 기본 반환 구조에 higher_low 필드 추가
        base = {
            'bb_position': bb_position,
            'bb_width': bb_width,
            'rsi': rsi,
            'higher_low': None
        }
        
        # ========================================
        # 체크 1: BB 폭 최소 기준
        # ========================================
        if bb_width < V10_15M_BB_WIDTH_MIN:
            return {
                **base,
                'is_downtrend': True,
                'reason': f'BB폭 부족 {bb_width:.1f}% < {V10_15M_BB_WIDTH_MIN}% (횡보)'
            }
        
        # ========================================
        # 체크 2: BB 위치 범위 (하단 근처인가?)
        # ========================================
        if bb_position < V10_15M_BB_MIN:
            return {
                **base,
                'is_downtrend': True,
                'reason': f'BB {bb_position:.0f}% < {V10_15M_BB_MIN}% (극단 하단, 추가 하락 위험)'
            }
        
        if bb_position > V10_15M_BB_MAX:
            return {
                **base,
                'is_downtrend': True,
                'reason': f'BB {bb_position:.0f}% > {V10_15M_BB_MAX}% (이미 반등 진행)'
            }
        
        # ========================================
        # 체크 3: RSI 극단 과매도 회피
        # ========================================
        if rsi < V10_15M_RSI_MIN:
            return {
                **base,
                'is_downtrend': True,
                'reason': f'RSI {rsi:.0f} < {V10_15M_RSI_MIN} (극단 과매도, 바닥 미확인)'
            }
        
        # ========================================
        # 체크 4: [v10.1 신규] Higher Low 검증
        # ========================================
        if V10_HIGHER_LOW_ENABLED:
            swing_lows = find_recent_swing_lows(
                df_15m,
                lookback=V10_SWING_LOOKBACK,
                swing_size=V10_SWING_SIZE
            )
            
            if len(swing_lows) >= 2:
                prev_low = swing_lows[-2]['price']
                recent_low = swing_lows[-1]['price']
                
                # 허용 오차 계산 (현재가 기준 %)
                tolerance = prev_low * (V10_HIGHER_LOW_TOLERANCE / 100)
                
                # Higher Low 판정: 최근 저점 > 직전 저점 - 허용오차
                is_higher_low = recent_low >= (prev_low - tolerance)
                
                base['higher_low'] = is_higher_low
                base['prev_swing_low'] = prev_low
                base['recent_swing_low'] = recent_low
                
                if not is_higher_low:
                    # Lower Low = 하락 추세 지속 → 매수 차단
                    drop_pct = ((prev_low - recent_low) / prev_low) * 100
                    return {
                        **base,
                        'is_downtrend': True,
                        'reason': f'Lower Low 감지 ({prev_low:,.0f}→{recent_low:,.0f}, -{drop_pct:.1f}%)'
                    }
            else:
                # 저점 2개 미만 → 파동 구조 불명확, 통과 허용
                base['higher_low'] = None
                base['swing_count'] = len(swing_lows)
        
        # ========================================
        # 모든 체크 통과 → BB 하단 근처 + Higher Low, 매수 가능 구간
        # ========================================
        hl_str = ""
        if base.get('higher_low') is True:
            hl_str = f", HL✅({base.get('prev_swing_low', 0):,.0f}→{base.get('recent_swing_low', 0):,.0f})"
        elif base.get('higher_low') is None:
            hl_str = ", HL미확인(저점부족)"
        
        return {
            **base,
            'is_downtrend': False,
            'reason': f'BB하단구간 OK (BB:{bb_position:.0f}%, 폭:{bb_width:.1f}%, RSI:{rsi:.0f}{hl_str})'
        }
        
    except Exception as e:
        if DEBUG_MODE:
            print(f"{Colors.RED}[Position Filter Error] {e}{Colors.ENDC}")
        return {
            'is_downtrend': True,
            'reason': f'체크 오류: {e}',
            'bb_position': 50, 'bb_width': 0, 'rsi': 50,
            'higher_low': None
        }

def calculate_reversal_score(df_15m):
    """
    [v10.0] Phase 3: 다중 지표 반등 신호 확인
    
    5개 신호 중 V10_BOUNCE_MIN_SIGNALS개 이상 충족 시 매수:
    
    ① RSI 반등: current RSI > prev RSI
    ② Stochastic RSI 반등: %K ≤ 25에서 상승 OR %K > %D (골든크로스)
    ③ MACD 반등: 히스토그램 음→양 OR 히스토그램 축소(음수이지만 증가)
    ④ 양봉 확인: close > open
    ⑤ 거래량 확인: volume ≥ MA20 × 0.8
    
    필수 조건: ①④ 중 최소 1개 포함 (V10_BOUNCE_MANDATORY_ONE)
    
    Returns:
        dict: {
            score: 충족 신호 수 (0-5),
            items_met: 동일값 (호환용),
            details: 상세 내역,
            signals: 개별 신호 dict,
            bounce_confirmed: 최종 반등 확인 여부
        }
    """
    try:
        if df_15m is None or len(df_15m) < 3:
            return {
                'score': 0, 'items_met': 0, 'details': ['데이터 부족'],
                'signals': {}, 'bounce_confirmed': False,
                'rsi_rising': False, 'is_bullish': False,
                'volume_up': False, 'higher_low': False
            }
        
        current = df_15m.iloc[-1]
        prev = df_15m.iloc[-2]
        
        signals_met = 0
        details = []
        signals = {}
        
        # ========================================
        # ① RSI 반등: RSI 상승 전환
        # ========================================
        rsi_now = current['rsi']
        rsi_prev = prev['rsi']
        rsi_rising = rsi_now > rsi_prev
        signals['rsi_rising'] = rsi_rising
        
        if rsi_rising:
            signals_met += 1
            details.append(f"①RSI상승 {rsi_prev:.0f}→{rsi_now:.0f}")
        
        # ========================================
        # ② Stochastic RSI 반등
        # %K ≤ 25에서 상승 OR %K > %D (골든크로스)
        # ========================================
        stoch_k = current.get('stoch_rsi_k', 50)
        stoch_d = current.get('stoch_rsi_d', 50)
        stoch_k_prev = prev.get('stoch_rsi_k', 50)
        
        stoch_oversold_bounce = (stoch_k_prev <= V10_STOCH_RSI_OVERSOLD and stoch_k > stoch_k_prev)
        stoch_golden_cross = (stoch_k > stoch_d and stoch_k_prev <= prev.get('stoch_rsi_d', 50))
        stoch_signal = stoch_oversold_bounce or stoch_golden_cross
        signals['stoch_rsi'] = stoch_signal
        
        if stoch_signal:
            signals_met += 1
            if stoch_oversold_bounce:
                details.append(f"②S-RSI과매도탈출 K:{stoch_k:.0f}")
            else:
                details.append(f"②S-RSI골든크로스 K:{stoch_k:.0f}>D:{stoch_d:.0f}")
        
        # ========================================
        # ③ MACD 반등
        # 히스토그램 음→양 전환 OR 음수이지만 증가(축소)
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
        # ④ 양봉 확인
        # ========================================
        is_bullish = current['close'] > current['open']
        signals['bullish'] = is_bullish
        
        if is_bullish:
            signals_met += 1
            change_pct = ((current['close'] - current['open']) / current['open']) * 100
            details.append(f"④양봉 +{change_pct:.2f}%")
        
        # ========================================
        # ⑤ 거래량 확인 (MA20 × 0.8 이상)
        # ========================================
        vol_ratio = current.get('volume_ratio', 1.0)
        volume_ok = vol_ratio >= V10_VOLUME_MIN_RATIO
        signals['volume'] = volume_ok
        
        if volume_ok:
            signals_met += 1
            details.append(f"⑤거래량 {vol_ratio:.1f}x")
        
        # ========================================
        # 필수 조건 체크: RSI상승 또는 양봉 중 1개 필수
        # ========================================
        mandatory_met = rsi_rising or is_bullish
        
        # ========================================
        # 최종 판정
        # ========================================
        bounce_confirmed = (
            signals_met >= V10_BOUNCE_MIN_SIGNALS and
            (mandatory_met or not V10_BOUNCE_MANDATORY_ONE)
        )
        
        return {
            'score': signals_met,
            'items_met': signals_met,  # 호환용
            'details': details,
            'signals': signals,
            'bounce_confirmed': bounce_confirmed,
            'mandatory_met': mandatory_met,
            # 레거시 호환 필드
            'rsi_rising': rsi_rising,
            'is_bullish': is_bullish,
            'volume_up': volume_ok,
            'higher_low': False  # 더 이상 사용 안 함
        }
        
    except Exception as e:
        if DEBUG_MODE:
            print(f"{Colors.RED}[Bounce Score Error] {e}{Colors.ENDC}")
        return {
            'score': 0, 'items_met': 0, 'details': [f'오류: {e}'],
            'signals': {}, 'bounce_confirmed': False,
            'rsi_rising': False, 'is_bullish': False,
            'volume_up': False, 'higher_low': False
        }


# ==========================================================================
# [v11.0] 매도 모멘텀 소진 점수 시스템
# ==========================================================================

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
    [v10.0] BOUNCE HUNTER - 다중 지표 반등 매수 신호
    
    3-Phase 구조:
    Phase 1: 일봉 양봉 필터 (check_daily_safety_filter)
    Phase 2: 15분봉 BB 하단 위치 확인 (detect_downtrend_15m)
    Phase 3: 다중 지표 반등 신호 확인 (calculate_reversal_score)
    
    핵심 철학:
    "큰 흐름 상승(일봉) + 단기 조정(BB 하단) + 반등 시작(다중 지표)"
    """
    try:
        current = df_15m.iloc[-1] if df_15m is not None and len(df_15m) > 0 else None
        
        base_response = {
            'signal': False,
            'reason': '',
            'confidence': 0,
            'entry_price': current['close'] if current is not None else 0,
            'bb_position': current['bb_position'] if current is not None else 50,
            'bb_width_pct': current['bb_width'] if current is not None else 2.0,
            'mode': 'BOUNCE_V10',
            'market_condition': 'NORMAL',
            'score': 0,
            'daily_change': 0,
            'reversal_score': 0,
            'bb_width_zone': 'UNKNOWN'
        }
        
        if df_15m is None or len(df_15m) < 20:
            base_response['reason'] = '15분봉 데이터 부족'
            return base_response
        
        # ========================================
        # Phase 1: 일봉 양봉 필터
        # ========================================
        daily_safety = check_daily_safety_filter(ticker)
        base_response['daily_change'] = daily_safety.get('daily_change', 0)
        
        if not daily_safety['safe']:
            base_response['reason'] = f"P1거부: {daily_safety['reason']}"
            base_response['market_condition'] = 'DAILY_UNSAFE'
            return base_response
        
        # ========================================
        # Phase 2: 15분봉 BB 하단 위치 확인
        # ========================================
        position_check = detect_downtrend_15m(df_15m)
        
        if position_check['is_downtrend']:
            base_response['reason'] = f"P2거부: {position_check['reason']}"
            base_response['market_condition'] = 'POSITION_UNSUITABLE'
            return base_response
        
        # Phase 2 통과 → BB 하단 근처 확인됨
        bb_position = position_check['bb_position']
        bb_width = position_check['bb_width']
        
        # ========================================
        # Phase 3: 다중 지표 반등 신호 확인
        # ========================================
        reversal = calculate_reversal_score(df_15m)
        base_response['reversal_score'] = reversal['score']
        
        if not reversal['bounce_confirmed']:
            # 상세한 거부 사유
            met = reversal['score']
            required = V10_BOUNCE_MIN_SIGNALS
            mandatory = reversal.get('mandatory_met', False)
            detail_str = ', '.join(reversal['details']) if reversal['details'] else '신호없음'
            
            reason_parts = [f"P3거부: 반등{met}/{required}개"]
            if not mandatory and V10_BOUNCE_MANDATORY_ONE:
                reason_parts.append("필수(RSI↑or양봉)미충족")
            reason_parts.append(f"[{detail_str}]")
            
            base_response['reason'] = ' '.join(reason_parts)
            base_response['market_condition'] = 'NO_BOUNCE'
            return base_response
        
        # ========================================
        # 모든 Phase 통과 → 매수 신호!
        # ========================================
        # 신뢰도 계산
        confidence = min(100, 40 + reversal['score'] * 12 + int(bb_width * 3))
        
        # 사유 조합
        daily_info = daily_safety['reason']
        bounce_detail = ', '.join(reversal['details'][:3]) if reversal['details'] else ''
        
        return {
            'signal': True,
            'reason': f"BOUNCE! BB{bb_position:.0f}% 폭{bb_width:.1f}% | {bounce_detail} | {daily_info}",
            'confidence': confidence,
            'entry_price': current['close'],
            'bb_position': bb_position,
            'bb_width_pct': bb_width,
            'mode': 'BOUNCE_V10',
            'market_condition': 'BOUNCE_CONFIRMED',
            'score': reversal['score'],
            'daily_change': daily_safety.get('daily_change', 0),
            'reversal_score': reversal['score'],
            'bb_width_zone': 'BOUNCE',
            'target_profit': V10_TARGET_PROFIT,
            'reversal_details': reversal['details'],
            'daily_bb': daily_safety.get('daily_bb', 50),
            'daily_rsi': daily_safety.get('daily_rsi', 50)
        }
        
    except Exception as e:
        if DEBUG_MODE:
            print(f"{Colors.RED}[v10.0 Buy Signal Error] {e}{Colors.ENDC}")
            traceback.print_exc()
        
        return {
            'signal': False, 'reason': f'오류: {str(e)}', 'confidence': 0,
            'entry_price': 0, 'bb_position': 50, 'bb_width_pct': 2.0,
            'mode': 'ERROR', 'market_condition': 'UNKNOWN', 'score': 0,
            'daily_change': 0, 'reversal_score': 0, 'bb_width_zone': 'ERROR'
        }
    

def evolution_80_sell_signal(df, buy_price, buy_time=None, held_info=None):
    """
    [v11.0] BOUNCE HUNTER - 심층 매도 신호
    
    매수 3-Phase의 반대 구조:
    Step 1: 절대 손절 (-2.5%)
    Step 2: 극과매수 긴급 익절 (BB95%+음봉+수익1%+)
    Step 3: 모멘텀 소진 점수제 (7지표+동적임계치)
    Step 4: 동적 트레일링 스탑 (적극/기본/보수)
    Step 5: 홀드 (동적 min_profit)
    
    v11.0 핵심 변경:
    - "상승 중 홀드" 제거 → 모멘텀 소진 점수에 통합
    - SRSI/MACD/SwingHigh/LowerHigh 매도 활용
    - BB 구간별 동적 임계치 + 수익률 보너스
    - 동적 min_profit (소진 점수 연동)
    - 트레일링 3구간 동적 조절
    """
    try:
        if df is None or len(df) < 5:
            return {
                'signal': False, 'reason': '데이터 부족',
                'exit_price': 0, 'profit_pct': 0,
                'bb_position': 50, 'bb_width_pct': 2.0
            }
        
        current = df.iloc[-1]
        prev = df.iloc[-2]
        current_price = current['close']
        profit_pct = ((current_price - buy_price) / buy_price) * 100
        bb_position = current['bb_position']
        bb_width = current['bb_width']
        
        base_response = {
            'signal': False,
            'exit_price': current_price,
            'profit_pct': profit_pct,
            'bb_position': bb_position,
            'bb_width_pct': bb_width,
            'reason': ''
        }
        
        # 피크 추적
        if held_info is not None:
            current_peak = held_info.get('peak_price', buy_price)
            if current_price > current_peak:
                held_info['peak_price'] = current_price
                held_info['peak_time'] = datetime.now()
            
            current_peak_bb = held_info.get('peak_bb_position', 0)
            if bb_position > current_peak_bb:
                held_info['peak_bb_position'] = bb_position
            
            held_info['_current_price'] = current_price
        
        # ============================================================
        # Step 1: 절대 손절 (-2.5%) - 무조건
        # ============================================================
        if profit_pct <= V10_STOP_LOSS_PCT:
            return {
                **base_response, 'signal': True,
                'reason': f'STOP_LOSS ({profit_pct:.2f}% <= {V10_STOP_LOSS_PCT}%)'
            }
        
        # ============================================================
        # Step 2: 극과매수 긴급 익절
        # ============================================================
        is_bearish = current['close'] < current['open']
        
        if bb_position >= V11_SELL_EXTREME_BB and is_bearish and profit_pct >= V11_SELL_EXTREME_MIN_PROFIT:
            return {
                **base_response, 'signal': True,
                'reason': f'극과매수익절 (BB{bb_position:.0f}%+음봉, 수익{profit_pct:.2f}%)'
            }
        
        # ============================================================
        # Step 3: 모멘텀 소진 점수제 (v11.0 핵심)
        # ============================================================
        exhaustion = calculate_sell_exhaustion_score(df, held_info)
        ex_score = exhaustion['score']
        ex_threshold = exhaustion['dynamic_threshold']
        ex_detail = format_sell_exhaustion_detail(exhaustion)
        
        # 동적 min_profit (소진 점수 연동)
        if ex_score >= V11_SELL_EXHAUSTION_HIGH:
            dynamic_min_profit = V11_SELL_MIN_PROFIT_EXHAUSTED
        elif ex_score >= V11_SELL_EXHAUSTION_MID:
            dynamic_min_profit = (V11_SELL_MIN_PROFIT_DEFAULT + V11_SELL_MIN_PROFIT_EXHAUSTED) / 2
        else:
            dynamic_min_profit = V11_SELL_MIN_PROFIT_DEFAULT
        
        if exhaustion['should_sell'] and profit_pct >= dynamic_min_profit:
            return {
                **base_response, 'signal': True,
                'reason': f'모멘텀소진 ({ex_detail}, 수익{profit_pct:.2f}%, 최소{dynamic_min_profit:.1f}%)'
            }
        
        # ============================================================
        # Step 4: 동적 트레일링 스탑
        # ============================================================
        trailing = calculate_dynamic_trailing(bb_position, profit_pct, held_info)
        
        if trailing['should_sell']:
            return {
                **base_response, 'signal': True,
                'reason': (f'트레일링스탑[{trailing["zone"]}] '
                          f'(고점{trailing["peak_profit"]:.1f}%→현재{profit_pct:.1f}%, '
                          f'-{trailing["drawdown_from_peak"]:.1f}% >= {trailing["distance"]:.1f}%)')
            }
        
        # ============================================================
        # Step 5: 홀드 (매도 조건 미충족)
        # ============================================================
        trailing_info = f"트레일링[{trailing['zone']}:{trailing['distance']:.1f}%]"
        
        if profit_pct < dynamic_min_profit:
            base_response['reason'] = (
                f'수익미달홀드 ({profit_pct:.2f}% < 동적최소{dynamic_min_profit:.1f}%, '
                f'소진{ex_score}/{ex_threshold}, {trailing_info})'
            )
        else:
            base_response['reason'] = (
                f'홀드 (수익{profit_pct:.2f}%, '
                f'소진{ex_score}/{ex_threshold}, {trailing_info})'
            )
        
        return base_response
        
    except Exception as e:
        if DEBUG_MODE:
            print(f"{Colors.RED}[v11.0 Sell Signal Error] {e}{Colors.ENDC}")
            traceback.print_exc()
        
        return {
            'signal': False, 'reason': f'오류: {str(e)}',
            'exit_price': 0, 'profit_pct': 0,
            'bb_position': 50, 'bb_width_pct': 2.0
        }

def evolution_76_sell_signal(df, buy_price, buy_time=None, held_info=None):
    """레거시 wrapper - v11.0으로 리다이렉트"""
    return evolution_80_sell_signal(df, buy_price, buy_time, held_info)

def evolution_70_sell_signal(df, buy_price):
    """레거시 wrapper - v11.0으로 리다이렉트"""
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
    [v10.2] 2단계 매수 실행 (thread safe)
    
    포지션 사이징:
    - 보유 0개 (1차 매수): 가용현금 × FIRST_BUY_RATIO(50%) × BUY_FEE_BUFFER(0.995)
    - 보유 1개+ (2차 매수): 가용현금 × BUY_FEE_BUFFER(0.995) (잔여 전량)
    
    수수료 처리:
    - BUY_FEE_BUFFER = 0.995 (Upbit 수수료 0.05% + 슬리피지 여유)
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
                
                # 현재 보유 수 확인 (포지션 사이징용)
                current_holding_count = len(held_coins)
            
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
                        'buy_order': buy_order_num    # [v10.2] 몇 차 매수인지
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
                # 매수 직전 최종 잔고 재확인
                final_krw = upbit.get_balance("KRW")
                if final_krw is None or final_krw < buy_amount:
                    print(f"{Colors.RED}[Buy Failed] 매수 직전 잔고 부족{Colors.ENDC}")
                    print(f"  └ 필요금액: {buy_amount:,.0f}원 | 실제잔고: {final_krw:,.0f}원")
                    if final_krw and final_krw >= 5000:
                        # 잔고에 맞춰 재조정 (수수료 버퍼 적용)
                        buy_amount = final_krw * BUY_FEE_BUFFER
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
                        'peak_bb_position': signal.get('bb_position', 50),
                        'buy_reason': signal['reason'],
                        'buy_mode': signal.get('mode', 'BOUNCE_V10'),
                        'entry_bb_width': signal.get('bb_width_pct', 2.0),
                        'bb_width_zone': signal.get('bb_width_zone', 'UNKNOWN'),
                        'target_profit': signal.get('target_profit', 2.0),
                        'ticker': ticker,
                        'buy_order': buy_order_num    # [v10.2] 몇 차 매수인지
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
                    print(f"  📊 반등 신호: {buy_signal.get('reversal_score', 0)}/{V10_BOUNCE_MIN_SIGNALS}개")
                    print(f"  🎯 모드: {buy_signal.get('mode', 'BOUNCE_V10')}")
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
  - 매수: 일봉양봉→BB하단(5-35%)→다중반등확인(3/5+)
  - 포지션: 1차 현금{FIRST_BUY_RATIO:.0%} → 2차 잔여전량 (버퍼 {BUY_FEE_BUFFER})
  - 매도: 트레일링스탑+선행하락감지+극과매수익절
  - 지표: RSI+S-RSI+MACD+양봉+거래량
  - 손절: -2.5%

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