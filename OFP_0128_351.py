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

# ================================================================================
# SECTION A: 새로운 파라미터 (기존 파라미터 섹션에 추가)
# ================================================================================

# ========================================
# [v7.8] ADAPTIVE MARKET DETECTION Settings
# ========================================

# 시장 상황 감지 임계값
MARKET_SURGE_DAILY_BB_MIN = 65           # 급등장: 일봉 BB 65% 이상
MARKET_SURGE_DAILY_CHANGE_MIN = 2.0      # 급등장: 당일 +2% 이상
MARKET_SURGE_RSI_15M_MIN = 58            # 급등장: 15분 RSI 58 이상

MARKET_CRASH_DAILY_BB_MAX = 25           # 급락장: 일봉 BB 25% 이하
MARKET_CRASH_DAILY_CHANGE_MAX = -2.0     # 급락장: 당일 -2% 이하
MARKET_CRASH_RSI_15M_MAX = 38            # 급락장: 15분 RSI 38 이하

# ========================================
# [v7.8] 모드별 매수 조건
# ========================================

# SURGE_PULLBACK (급등장 눌림목)
SURGE_PULLBACK_BB_MIN = 25               # 15분 BB 하한
SURGE_PULLBACK_BB_MAX = 50               # 15분 BB 상한
SURGE_PULLBACK_RSI_MIN = 35              # RSI 하한
SURGE_PULLBACK_RSI_MAX = 58              # RSI 상한
SURGE_PULLBACK_MIN_SCORE = 70            # 최소 점수
SURGE_PULLBACK_CORRECTION_PCT = 1.5      # 최소 조정폭 (%)

# CRASH_REVERSAL (급락장 반등)
CRASH_REVERSAL_BB_MIN = 0                # 15분 BB 하한
CRASH_REVERSAL_BB_MAX = 28               # 15분 BB 상한 (기존 25 → 28 완화)
CRASH_REVERSAL_RSI_MIN = 15              # RSI 하한
CRASH_REVERSAL_RSI_MAX = 45              # RSI 상한
CRASH_REVERSAL_MIN_SCORE = 65            # 최소 점수 (기존 68 → 65 완화)
CRASH_REVERSAL_MIN_BULLISH = 1           # 최소 양봉 수 (기존 2 → 1 완화)

# NORMAL_BOTTOM (평균장 하단 반등)
NORMAL_BOTTOM_BB_MIN = 5                 # 15분 BB 하한
NORMAL_BOTTOM_BB_MAX = 35                # 15분 BB 상한 (기존 20 → 35 완화)
NORMAL_BOTTOM_RSI_MIN = 25               # RSI 하한
NORMAL_BOTTOM_RSI_MAX = 50               # RSI 상한
NORMAL_BOTTOM_MIN_SCORE = 72             # 최소 점수 (기존 85 → 72 완화)

# MOMENTUM_BREAK (돌파 모멘텀)
MOMENTUM_BREAK_BB_MIN = 55               # 15분 BB 하한
MOMENTUM_BREAK_BB_MAX = 85               # 15분 BB 상한
MOMENTUM_BREAK_RSI_MIN = 55              # RSI 하한
MOMENTUM_BREAK_RSI_MAX = 75              # RSI 상한 (과매수 방지)
MOMENTUM_BREAK_MIN_SCORE = 75            # 최소 점수
MOMENTUM_BREAK_VOLUME_MIN = 1.8          # 최소 거래량 배수

# ========================================
# [v7.8] 적응형 점수 가중치
# ========================================

# 기본 점수 배분 (총 100점)
SCORE_BB_POSITION = 25                   # BB 위치 점수 (기존 30 → 25)
SCORE_REVERSAL = 25                      # 반전 신호 점수 (기존 30 → 25)
SCORE_MOMENTUM = 20                      # 모멘텀 점수 (기존 20 유지)
SCORE_VOLUME = 15                        # 거래량 점수 (기존 10 → 15)
SCORE_VOLATILITY = 15                    # 변동성 점수 (기존 10 → 15)

# 시장 상황별 보너스 점수
SURGE_MODE_BONUS = 10                    # 급등장 보너스
CRASH_MODE_BONUS = 15                    # 급락장 보너스 (더 높음 - 기회)
NORMAL_MODE_BONUS = 5                    # 평균장 보너스

# ========================================
# [v7.8] 일봉 필터 완화
# ========================================
DAILY_BB_HIGH_FILTER_V78 = 70            # 기존 60 → 70 완화
DAILY_BEARISH_LIMIT = -1.5               # 일봉 음봉 허용 한도 (기존 -0.3% → -1.5%)

# ================================================================================
# SECTION 8: Startup Message
# ================================================================================

print(f"\n{Colors.BOLD}{Colors.CYAN}{'='*10}")
print(f"EVOLUTION {VERSION}")
print(f"{'='*10}")
print(f"{Colors.GREEN}Strategy{Colors.ENDC}")
print(f"   [Buy Priority 1] BOTTOM REVERSAL (Daily BB ≤30% + Bullish)")
print(f"   [Buy Priority 2] NORMAL (BB <=20% reversal, 85+ points)")
print(f"   [Buy Filter] Daily BB < {DAILY_BB_HIGH_FILTER}% (NORMAL mode only)")
print(f"   [Sell] BB <80% hold | 80-95% momentum check | 95%+ profit secure")
print(f"   [Exception] Don't miss big rallies (volume 2x + 3 bullish)")
print(f"   [Stop] -3% quick exit")
print(f"")
print(f"{Colors.MAGENTA}THREADED EDITION{Colors.ENDC}")
print(f"   Thread 1: Buy ({BUY_THREAD_INTERVAL}s)")
print(f"   Thread 2: Sell ({SELL_THREAD_INTERVAL}s)")
print(f"   Thread 3: Monitor ({MONITOR_THREAD_INTERVAL}s)")
print(f"")
print(f"{Colors.YELLOW}ENHANCED FEATURES{Colors.ENDC}")
print(f"   - Auto-sync existing positions on startup")
print(f"   - Enhanced portfolio tracking")
print(f"   - Improved hourly reporting")
print(f"{10}{Colors.ENDC}\n")


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
# SECTION B: 시장 상황 감지 함수 (신규)
# ================================================================================

def detect_market_condition(df_daily, df_15m):
    """
    [v7.8 신규] 시장 상황 자동 감지
    
    시장 상황을 3가지로 분류:
    - SURGE (급등장): 강한 상승 모멘텀
    - CRASH (급락장): 강한 하락 모멘텀  
    - NORMAL (평균장): 횡보 또는 약한 추세
    
    Args:
        df_daily: 일봉 DataFrame (지표 포함)
        df_15m: 15분봉 DataFrame (지표 포함)
    
    Returns:
        dict: {
            'condition': 'SURGE' / 'CRASH' / 'NORMAL',
            'daily_bb': 일봉 BB 위치,
            'daily_change': 당일 등락률,
            'rsi_15m': 15분봉 RSI,
            'confidence': 판단 신뢰도 (0~100),
            'reason': 판단 근거
        }
    """
    try:
        result = {
            'condition': 'NORMAL',
            'daily_bb': 50.0,
            'daily_change': 0.0,
            'rsi_15m': 50.0,
            'confidence': 50,
            'reason': '기본값'
        }
        
        # 데이터 검증
        if df_daily is None or len(df_daily) < 20:
            result['reason'] = '일봉 데이터 부족'
            return result
            
        if df_15m is None or len(df_15m) < 20:
            result['reason'] = '15분봉 데이터 부족'
            return result
        
        # 일봉 데이터 추출
        current_daily = df_daily.iloc[-1]
        prev_daily = df_daily.iloc[-2]
        
        daily_bb = current_daily['bb_position']
        daily_open = current_daily['open']
        daily_close = current_daily['close']
        daily_high = current_daily['high']
        daily_low = current_daily['low']
        
        # 당일 등락률 (시가 대비)
        if daily_open > 0:
            daily_change = ((daily_close - daily_open) / daily_open) * 100
        else:
            daily_change = 0.0
        
        # 15분봉 데이터 추출
        current_15m = df_15m.iloc[-1]
        rsi_15m = current_15m['rsi']
        
        # 연속 양봉/음봉 카운트 (15분봉)
        bullish_count = 0
        bearish_count = 0
        for i in range(-1, -6, -1):
            if len(df_15m) + i < 0:
                break
            candle = df_15m.iloc[i]
            if candle['close'] > candle['open']:
                bullish_count += 1
            elif candle['close'] < candle['open']:
                bearish_count += 1
        
        result['daily_bb'] = daily_bb
        result['daily_change'] = daily_change
        result['rsi_15m'] = rsi_15m
        
        # ========================================
        # SURGE (급등장) 판단
        # ========================================
        surge_score = 0
        surge_reasons = []
        
        # 조건 1: 일봉 BB 고점권
        if daily_bb >= MARKET_SURGE_DAILY_BB_MIN:
            surge_score += 35
            surge_reasons.append(f"일봉BB {daily_bb:.0f}%↑")
        
        # 조건 2: 당일 큰 상승
        if daily_change >= MARKET_SURGE_DAILY_CHANGE_MIN:
            surge_score += 35
            surge_reasons.append(f"당일 +{daily_change:.1f}%")
        elif daily_change >= 1.0:
            surge_score += 20
            surge_reasons.append(f"당일 +{daily_change:.1f}%")
        
        # 조건 3: 15분 RSI 상승세
        if rsi_15m >= MARKET_SURGE_RSI_15M_MIN:
            surge_score += 20
            surge_reasons.append(f"RSI {rsi_15m:.0f}")
        
        # 조건 4: 연속 양봉
        if bullish_count >= 3:
            surge_score += 10
            surge_reasons.append(f"연속양봉 {bullish_count}개")
        
        # ========================================
        # CRASH (급락장) 판단
        # ========================================
        crash_score = 0
        crash_reasons = []
        
        # 조건 1: 일봉 BB 저점권
        if daily_bb <= MARKET_CRASH_DAILY_BB_MAX:
            crash_score += 35
            crash_reasons.append(f"일봉BB {daily_bb:.0f}%↓")
        
        # 조건 2: 당일 큰 하락
        if daily_change <= MARKET_CRASH_DAILY_CHANGE_MAX:
            crash_score += 35
            crash_reasons.append(f"당일 {daily_change:.1f}%")
        elif daily_change <= -1.0:
            crash_score += 20
            crash_reasons.append(f"당일 {daily_change:.1f}%")
        
        # 조건 3: 15분 RSI 하락세
        if rsi_15m <= MARKET_CRASH_RSI_15M_MAX:
            crash_score += 20
            crash_reasons.append(f"RSI {rsi_15m:.0f}")
        
        # 조건 4: 연속 음봉
        if bearish_count >= 3:
            crash_score += 10
            crash_reasons.append(f"연속음봉 {bearish_count}개")
        
        # ========================================
        # 최종 시장 상황 결정
        # ========================================
        
        # SURGE 판정 (60점 이상)
        if surge_score >= 60:
            result['condition'] = 'SURGE'
            result['confidence'] = min(surge_score, 100)
            result['reason'] = f"급등장: {', '.join(surge_reasons)}"
            return result
        
        # CRASH 판정 (60점 이상)
        if crash_score >= 60:
            result['condition'] = 'CRASH'
            result['confidence'] = min(crash_score, 100)
            result['reason'] = f"급락장: {', '.join(crash_reasons)}"
            return result
        
        # NORMAL 판정
        result['condition'] = 'NORMAL'
        result['confidence'] = 100 - max(surge_score, crash_score)
        
        if surge_score > crash_score:
            result['reason'] = f"평균장 (상승 편향): 급등점수 {surge_score}"
        elif crash_score > surge_score:
            result['reason'] = f"평균장 (하락 편향): 급락점수 {crash_score}"
        else:
            result['reason'] = f"평균장 (중립)"
        
        return result
        
    except Exception as e:
        return {
            'condition': 'NORMAL',
            'daily_bb': 50.0,
            'daily_change': 0.0,
            'rsi_15m': 50.0,
            'confidence': 30,
            'reason': f'판단 오류: {e}'
        }


# ================================================================================
# SECTION C: 적응형 점수 계산 함수 (신규)
# ================================================================================

def calculate_buy_score_adaptive(df_15m, market_condition, buy_mode):
    """
    [v7.8 신규] 시장 상황 적응형 매수 점수 계산
    
    시장 상황과 매수 모드에 따라 가중치를 조정하여
    더 적절한 매수 타이밍을 포착
    
    Args:
        df_15m: 15분봉 DataFrame (지표 포함)
        market_condition: detect_market_condition() 반환값
        buy_mode: 'SURGE_PULLBACK' / 'CRASH_REVERSAL' / 'NORMAL_BOTTOM' / 'MOMENTUM_BREAK'
    
    Returns:
        dict: {
            'score': 최종 점수,
            'base_score': 기본 점수,
            'mode_bonus': 모드 보너스,
            'reasons': 점수 획득 사유 리스트,
            'bb_position': BB 위치,
            'rsi': RSI,
            'volume_ratio': 거래량 비율,
            'bb_width': BB 폭
        }
    """
    try:
        base_score = 0
        mode_bonus = 0
        reasons = []
        
        current = df_15m.iloc[-1]
        prev = df_15m.iloc[-2]
        prev2 = df_15m.iloc[-3] if len(df_15m) >= 3 else prev
        
        bb_position = current['bb_position']
        rsi_now = current['rsi']
        rsi_prev = prev['rsi']
        price_now = current['close']
        price_prev = prev['close']
        volume_ratio = current['volume_ratio']
        bb_width = current['bb_width']
        
        is_bullish = current['close'] > current['open']
        is_prev_bullish = prev['close'] > prev['open']
        
        # ========================================
        # 1. BB 위치 점수 (25점)
        # ========================================
        if buy_mode == 'SURGE_PULLBACK':
            # 급등장: BB 30~45%가 최적
            if 30 <= bb_position <= 45:
                base_score += 25
                reasons.append(f"BB최적구간 {bb_position:.0f}% (+25)")
            elif 25 <= bb_position < 30 or 45 < bb_position <= 50:
                base_score += 18
                reasons.append(f"BB양호구간 {bb_position:.0f}% (+18)")
            elif SURGE_PULLBACK_BB_MIN <= bb_position <= SURGE_PULLBACK_BB_MAX:
                base_score += 12
                reasons.append(f"BB허용구간 {bb_position:.0f}% (+12)")
                
        elif buy_mode == 'CRASH_REVERSAL':
            # 급락장: BB 0~15%가 최적
            if bb_position <= 15:
                base_score += 25
                reasons.append(f"BB극저점 {bb_position:.0f}% (+25)")
            elif bb_position <= 20:
                base_score += 20
                reasons.append(f"BB저점 {bb_position:.0f}% (+20)")
            elif bb_position <= CRASH_REVERSAL_BB_MAX:
                base_score += 15
                reasons.append(f"BB하단 {bb_position:.0f}% (+15)")
                
        elif buy_mode == 'NORMAL_BOTTOM':
            # 평균장: BB 15~25%가 최적
            if 15 <= bb_position <= 25:
                base_score += 25
                reasons.append(f"BB최적구간 {bb_position:.0f}% (+25)")
            elif 10 <= bb_position < 15:
                base_score += 22
                reasons.append(f"BB저점 {bb_position:.0f}% (+22)")
            elif 25 < bb_position <= 35:
                base_score += 18
                reasons.append(f"BB양호구간 {bb_position:.0f}% (+18)")
            elif NORMAL_BOTTOM_BB_MIN <= bb_position <= NORMAL_BOTTOM_BB_MAX:
                base_score += 12
                reasons.append(f"BB허용구간 {bb_position:.0f}% (+12)")
                
        elif buy_mode == 'MOMENTUM_BREAK':
            # 돌파: BB 60~75%가 최적
            if 60 <= bb_position <= 75:
                base_score += 25
                reasons.append(f"BB돌파구간 {bb_position:.0f}% (+25)")
            elif 55 <= bb_position < 60 or 75 < bb_position <= 80:
                base_score += 18
                reasons.append(f"BB양호구간 {bb_position:.0f}% (+18)")
            elif MOMENTUM_BREAK_BB_MIN <= bb_position <= MOMENTUM_BREAK_BB_MAX:
                base_score += 10
                reasons.append(f"BB허용구간 {bb_position:.0f}% (+10)")
        
        # ========================================
        # 2. 반전/모멘텀 신호 점수 (25점)
        # ========================================
        if buy_mode in ['CRASH_REVERSAL', 'NORMAL_BOTTOM']:
            # 반전 신호 중시
            if is_bullish:
                base_score += 10
                reasons.append("현재양봉 (+10)")
            if is_prev_bullish:
                base_score += 8
                reasons.append("이전양봉 (+8)")
            if rsi_now > rsi_prev:
                base_score += 7
                reasons.append(f"RSI상승 {rsi_prev:.0f}→{rsi_now:.0f} (+7)")
                
        elif buy_mode in ['SURGE_PULLBACK', 'MOMENTUM_BREAK']:
            # 모멘텀 유지 확인
            if is_bullish:
                base_score += 12
                reasons.append("현재양봉 (+12)")
            if price_now > price_prev:
                base_score += 8
                reasons.append("가격상승 (+8)")
            if rsi_now > 45:  # 모멘텀 유지 확인
                base_score += 5
                reasons.append(f"RSI양호 {rsi_now:.0f} (+5)")
        
        # ========================================
        # 3. 모멘텀 점수 (20점)
        # ========================================
        # 가격 변화율
        price_change = ((price_now - price_prev) / price_prev) * 100 if price_prev > 0 else 0
        
        if buy_mode == 'MOMENTUM_BREAK':
            # 돌파 모드: 강한 상승 필요
            if price_change >= 0.5:
                base_score += 12
                reasons.append(f"강한상승 +{price_change:.2f}% (+12)")
            elif price_change >= 0.2:
                base_score += 8
                reasons.append(f"상승중 +{price_change:.2f}% (+8)")
        else:
            # 반등 모드: 상승 전환 확인
            if price_change > 0:
                base_score += 10
                reasons.append(f"상승전환 +{price_change:.2f}% (+10)")
        
        # RSI 모멘텀
        rsi_change = rsi_now - rsi_prev
        if rsi_change > 3:
            base_score += 8
            reasons.append(f"RSI급상승 +{rsi_change:.1f}p (+8)")
        elif rsi_change > 0:
            base_score += 4
            reasons.append(f"RSI상승 +{rsi_change:.1f}p (+4)")
        
        # ========================================
        # 4. 거래량 점수 (15점)
        # ========================================
        if buy_mode == 'MOMENTUM_BREAK':
            # 돌파 모드: 높은 거래량 필수
            if volume_ratio >= 2.5:
                base_score += 15
                reasons.append(f"거래량폭발 {volume_ratio:.1f}x (+15)")
            elif volume_ratio >= MOMENTUM_BREAK_VOLUME_MIN:
                base_score += 12
                reasons.append(f"거래량급증 {volume_ratio:.1f}x (+12)")
            elif volume_ratio >= 1.2:
                base_score += 6
                reasons.append(f"거래량증가 {volume_ratio:.1f}x (+6)")
        else:
            # 반등 모드: 거래량 확인
            if volume_ratio >= 1.5:
                base_score += 15
                reasons.append(f"거래량급증 {volume_ratio:.1f}x (+15)")
            elif volume_ratio >= 1.0:
                base_score += 10
                reasons.append(f"거래량양호 {volume_ratio:.1f}x (+10)")
            elif volume_ratio >= 0.6:
                base_score += 5
                reasons.append(f"거래량확인 {volume_ratio:.1f}x (+5)")
        
        # ========================================
        # 5. 변동성 점수 (15점)
        # ========================================
        if bb_width >= 3.0:
            base_score += 15
            reasons.append(f"변동성충분 {bb_width:.1f}% (+15)")
        elif bb_width >= 2.0:
            base_score += 12
            reasons.append(f"변동성양호 {bb_width:.1f}% (+12)")
        elif bb_width >= 1.5:
            base_score += 8
            reasons.append(f"변동성확인 {bb_width:.1f}% (+8)")
        elif bb_width >= 1.0:
            base_score += 4
            reasons.append(f"변동성낮음 {bb_width:.1f}% (+4)")
        
        # ========================================
        # 6. 모드별 보너스 점수
        # ========================================
        condition = market_condition.get('condition', 'NORMAL')
        
        if condition == 'SURGE':
            mode_bonus = SURGE_MODE_BONUS
            reasons.append(f"[급등장보너스 +{SURGE_MODE_BONUS}]")
        elif condition == 'CRASH':
            mode_bonus = CRASH_MODE_BONUS
            reasons.append(f"[급락장보너스 +{CRASH_MODE_BONUS}]")
        else:
            mode_bonus = NORMAL_MODE_BONUS
            reasons.append(f"[평균장보너스 +{NORMAL_MODE_BONUS}]")
        
        # ========================================
        # 7. 감점 요인
        # ========================================
        # 연속 음봉 (3개 이상)
        bearish_count = 0
        for i in range(-1, -5, -1):
            if len(df_15m) + i < 0:
                break
            if df_15m.iloc[i]['close'] < df_15m.iloc[i]['open']:
                bearish_count += 1
            else:
                break
        
        if bearish_count >= 4:
            base_score -= 15
            reasons.append(f"연속음봉 {bearish_count}개 (-15)")
        elif bearish_count >= 3:
            base_score -= 10
            reasons.append(f"연속음봉 {bearish_count}개 (-10)")
        
        # RSI 극단값 (과매수/과매도 경고)
        if buy_mode != 'MOMENTUM_BREAK' and rsi_now > 70:
            base_score -= 10
            reasons.append(f"RSI과매수 {rsi_now:.0f} (-10)")
        
        if rsi_now < 20 and not is_bullish:
            base_score -= 5
            reasons.append(f"RSI극저+하락중 (-5)")
        
        # ========================================
        # 최종 점수
        # ========================================
        total_score = base_score + mode_bonus
        
        return {
            'score': total_score,
            'base_score': base_score,
            'mode_bonus': mode_bonus,
            'reasons': reasons,
            'bb_position': bb_position,
            'rsi': rsi_now,
            'volume_ratio': volume_ratio,
            'bb_width': bb_width
        }
        
    except Exception as e:
        return {
            'score': 0,
            'base_score': 0,
            'mode_bonus': 0,
            'reasons': [f'계산 오류: {e}'],
            'bb_position': 50,
            'rsi': 50,
            'volume_ratio': 1.0,
            'bb_width': 2.0
        }


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

def get_bottom_reversal_zone(df_daily, df_15m):
    """
    일봉 하단 반전 구간 판단
    
    Args:
        df_daily: 일봉 DataFrame
        df_15m: 15분봉 DataFrame
    
    Returns:
        dict or None: {
            'zone': 'EXTREME_BOTTOM' or 'BOTTOM',
            'daily_bb': 일봉 BB 위치,
            'max_15m_bb': 15분봉 BB 상한,
            'min_score': 최소 점수,
            'bonus': 보너스 점수,
            'min_change': 최소 등락률
        }
    """
    try:
        if df_daily is None or len(df_daily) < 20:
            return None
        
        if df_15m is None or len(df_15m) < 20:
            return None
        
        current_daily = df_daily.iloc[-1]
        daily_bb = current_daily['bb_position']
        daily_open = current_daily['open']
        daily_close = current_daily['close']
        
        # 양봉 체크
        if daily_close <= daily_open:
            return None
        
        # 등락률 계산
        daily_change = ((daily_close - daily_open) / daily_open) * 100
        
        # Zone 1: EXTREME_BOTTOM (일봉 BB ≤15%)
        if daily_bb <= EXTREME_BOTTOM_DAILY_BB_MAX:
            if daily_change >= EXTREME_BOTTOM_MIN_CHANGE:
                return {
                    'zone': 'EXTREME_BOTTOM',
                    'daily_bb': daily_bb,
                    'max_15m_bb': EXTREME_BOTTOM_15M_BB_MAX,
                    'min_score': EXTREME_BOTTOM_MIN_SCORE,
                    'bonus': EXTREME_BOTTOM_BONUS,
                    'min_change': EXTREME_BOTTOM_MIN_CHANGE
                }
        
        # Zone 2: BOTTOM (일봉 BB 16~30%)
        if BOTTOM_DAILY_BB_MIN <= daily_bb <= BOTTOM_DAILY_BB_MAX:
            if daily_change >= BOTTOM_MIN_CHANGE:
                return {
                    'zone': 'BOTTOM',
                    'daily_bb': daily_bb,
                    'max_15m_bb': BOTTOM_15M_BB_MAX,
                    'min_score': BOTTOM_MIN_SCORE,
                    'bonus': BOTTOM_BONUS,
                    'min_change': BOTTOM_MIN_CHANGE
                }
        
        return None
        
    except Exception as e:
        if DEBUG_MODE:
            print(f"{Colors.RED}[Bottom Zone Error] {e}{Colors.ENDC}")
        return None

def check_bottom_reversal_safety(df_daily, df_15m):
    """
    BOTTOM REVERSAL 안전장치 체크
    
    Args:
        df_daily: 일봉 DataFrame
        df_15m: 15분봉 DataFrame
    
    Returns:
        tuple: (통과여부, 사유)
    """
    try:
        if df_daily is None or len(df_daily) < 5:
            return (False, "일봉 데이터 부족")
        
        if df_15m is None or len(df_15m) < 20:
            return (False, "15분봉 데이터 부족")
        
        current_daily = df_daily.iloc[-1]
        current_15m = df_15m.iloc[-1]
        
        # 안전장치 1: 5일 평균 대비 체크
        ma5 = df_daily['close'].tail(5).mean()
        current_price = current_daily['close']
        
        if current_price < ma5 * BOTTOM_MA5_THRESHOLD:
            return (False, f"5일 평균 대비 과도한 하락 ({current_price/ma5*100:.1f}%)")
        
        # 안전장치 2: 15분봉 RSI 과매수 체크
        rsi_15m = current_15m['rsi']
        
        if rsi_15m > BOTTOM_MAX_RSI_15M:
            return (False, f"15분봉 과매수 (RSI {rsi_15m:.0f} > {BOTTOM_MAX_RSI_15M})")
        
        # 안전장치 3: 거래량 체크
        volume_ratio = current_15m['volume_ratio']
        
        if volume_ratio < BOTTOM_MIN_VOLUME_RATIO:
            return (False, f"거래량 부족 ({volume_ratio:.2f}x < {BOTTOM_MIN_VOLUME_RATIO}x)")
        
        return (True, "안전장치 통과")
        
    except Exception as e:
        if DEBUG_MODE:
            print(f"{Colors.RED}[Safety Check Error] {e}{Colors.ENDC}")
        return (False, f"체크 오류: {e}")
    
def calculate_buy_score_bottom(df_15m, zone_info):
    """
    BOTTOM REVERSAL 매수 점수 계산
    
    Args:
        df_15m: 15분봉 DataFrame
        zone_info: get_bottom_reversal_zone() 반환값
    
    Returns:
        dict: {
            'score': 최종 점수,
            'base_score': 기본 점수,
            'bonus_score': 보너스 점수,
            'reasons': 점수 획득 사유 리스트,
            'bb_position': BB 위치,
            'rsi': RSI,
            'volume_ratio': 거래량 비율
        }
    """
    try:
        base_score = 0
        bonus_score = 0
        reasons = []
        
        current = df_15m.iloc[-1]
        prev = df_15m.iloc[-2]
        
        bb_now = current['bb_position']
        rsi_now = current['rsi']
        rsi_prev = prev['rsi']
        price_now = current['close']
        price_prev = prev['close']
        volume_ratio = current['volume_ratio']
        bb_width = current['bb_width']
        
        # ========================================
        # 기본 점수 (100점 만점)
        # ========================================
        
        # 1. BB 하단 터치 (30점)
        if bb_now <= 20:
            base_score += 30
            reasons.append(f"BB극저점 {bb_now:.0f}% (+30)")
        elif bb_now <= 25:
            base_score += 20
            reasons.append(f"BB저점 {bb_now:.0f}% (+20)")
        elif bb_now <= 30:
            base_score += 10
            reasons.append(f"BB하단 {bb_now:.0f}% (+10)")
        
        # 2. 반전 확인 (20점) - 완화
        if current['is_bull'] == 1:
            base_score += 10
            reasons.append("현재 양봉 (+10)")
        
        if prev['is_bull'] == 1:
            base_score += 10
            reasons.append("전봉 양봉 (+10)")
        
        # 3. 지표 상승 (20점)
        if rsi_now > rsi_prev:
            base_score += 10
            reasons.append(f"RSI상승 ({rsi_prev:.0f}→{rsi_now:.0f}) (+10)")
        
        if price_now > price_prev:
            base_score += 10
            reasons.append("가격상승 (+10)")
        
        # 4. 거래량 (15점) - 강화
        if volume_ratio >= 1.5:
            base_score += 15
            reasons.append(f"거래량폭증 {volume_ratio:.1f}x (+15)")
        elif volume_ratio >= 1.0:
            base_score += 10
            reasons.append(f"거래량증가 {volume_ratio:.1f}x (+10)")
        elif volume_ratio >= 0.8:
            base_score += 5
            reasons.append(f"거래량양호 {volume_ratio:.1f}x (+5)")
        
        # 5. 변동성 (15점)
        if bb_width >= 2.0:
            base_score += 15
            reasons.append(f"변동성충분 {bb_width:.1f}% (+15)")
        
        # ========================================
        # 보너스 점수
        # ========================================
        
        # Zone 보너스 (일봉 BB)
        zone_bonus = zone_info['bonus']
        bonus_score += zone_bonus
        reasons.append(f"[{zone_info['zone']}] 일봉BB {zone_info['daily_bb']:.0f}% (+{zone_bonus})")
        
        # RSI 보너스 (15분봉 RSI 30~40)
        if BOTTOM_RSI_BONUS_MIN <= rsi_now <= BOTTOM_RSI_BONUS_MAX:
            bonus_score += BOTTOM_RSI_BONUS_SCORE
            reasons.append(f"RSI반등구간 {rsi_now:.0f} (+{BOTTOM_RSI_BONUS_SCORE})")
        
        # ========================================
        # 최종 점수
        # ========================================
        
        total_score = base_score + bonus_score
        
        return {
            'score': total_score,
            'base_score': base_score,
            'bonus_score': bonus_score,
            'reasons': reasons,
            'bb_position': bb_now,
            'rsi': rsi_now,
            'volume_ratio': volume_ratio,
            'bb_width': bb_width,
            'zone': zone_info['zone'],
            'daily_bb': zone_info['daily_bb']
        }
        
    except Exception as e:
        if DEBUG_MODE:
            print(f"{Colors.RED}[Bottom Score Error] {e}{Colors.ENDC}")
        return {
            'score': 0,
            'base_score': 0,
            'bonus_score': 0,
            'reasons': [f'계산 오류: {e}'],
            'bb_position': 50,
            'rsi': 50,
            'volume_ratio': 1.0,
            'bb_width': 2.0,
            'zone': 'ERROR',
            'daily_bb': 50
        }
    
    
def evolution_77_buy_signal(df_15m, ticker):
    """
    [v7.8] ADAPTIVE MARKET HUNTER - 시장 적응형 통합 매수 신호
    
    4가지 매수 모드를 시장 상황에 따라 자동 선택:
    1. SURGE_PULLBACK: 급등장에서 눌림목 매수
    2. CRASH_REVERSAL: 급락장에서 반등 포착
    3. NORMAL_BOTTOM: 평균장에서 하단 반등
    4. MOMENTUM_BREAK: 돌파 모멘텀 매수
    
    Args:
        df_15m: 15분봉 DataFrame (지표 포함)
        ticker: 코인 티커 (예: "KRW-BTC")
    
    Returns:
        dict: {
            'signal': True/False,
            'reason': 매수 사유,
            'confidence': 신뢰도 (점수),
            'entry_price': 진입가,
            'bb_position': BB 위치,
            'bb_width_pct': BB 폭,
            'mode': 매수 모드,
            'market_condition': 시장 상황,
            'score': 점수,
            'daily_bb': 일봉 BB 위치
        }
    """
    try:
        # 기본 응답 템플릿
        base_response = {
            'signal': False,
            'reason': '',
            'confidence': 0,
            'entry_price': 0,
            'bb_position': 0,
            'bb_width_pct': 0,
            'mode': 'NONE',
            'market_condition': 'NORMAL',
            'score': 0,
            'daily_bb': 50
        }
        
        # 데이터 검증
        if len(df_15m) < 20:
            base_response['reason'] = '데이터 부족'
            return base_response
        
        current_price = df_15m.iloc[-1]['close']
        bb_position_15m = df_15m.iloc[-1]['bb_position']
        bb_width_pct = df_15m.iloc[-1]['bb_width']
        rsi_15m = df_15m.iloc[-1]['rsi']
        
        base_response['entry_price'] = current_price
        base_response['bb_position'] = bb_position_15m
        base_response['bb_width_pct'] = bb_width_pct
        
        # ========================================
        # Step 1: 일봉 데이터 조회 및 시장 상황 판단
        # ========================================
        df_daily = get_candles_daily(ticker, count=50)
        
        if df_daily is not None and len(df_daily) >= 20:
            df_daily = add_indicators(df_daily)
        
        # 시장 상황 감지
        market_condition = detect_market_condition(df_daily, df_15m)
        condition = market_condition['condition']
        base_response['market_condition'] = condition
        base_response['daily_bb'] = market_condition['daily_bb']
        
        # ========================================
        # Step 2: 일봉 필터 체크 (완화 버전)
        # ========================================
        filter_pass, filter_reason, _, _ = check_daily_bb_filter(ticker, market_condition)
        
        if not filter_pass:
            base_response['reason'] = filter_reason
            base_response['mode'] = 'FILTERED'
            return base_response
        
        # ========================================
        # Step 3: 시장 상황별 매수 모드 결정 및 조건 체크
        # ========================================
        buy_mode = None
        mode_conditions_met = False
        
        # --- SURGE (급등장) ---
        if condition == 'SURGE':
            # 모드 1: SURGE_PULLBACK (눌림목)
            if (SURGE_PULLBACK_BB_MIN <= bb_position_15m <= SURGE_PULLBACK_BB_MAX and
                SURGE_PULLBACK_RSI_MIN <= rsi_15m <= SURGE_PULLBACK_RSI_MAX):
                
                # 조정폭 확인 (최근 고점 대비)
                recent_high = df_15m['high'].tail(12).max()  # 최근 3시간 고점
                correction_pct = ((recent_high - current_price) / recent_high) * 100
                
                if correction_pct >= SURGE_PULLBACK_CORRECTION_PCT:
                    buy_mode = 'SURGE_PULLBACK'
                    mode_conditions_met = True
            
            # 모드 2: MOMENTUM_BREAK (돌파)
            if not mode_conditions_met:
                volume_ratio = df_15m.iloc[-1]['volume_ratio']
                if (MOMENTUM_BREAK_BB_MIN <= bb_position_15m <= MOMENTUM_BREAK_BB_MAX and
                    MOMENTUM_BREAK_RSI_MIN <= rsi_15m <= MOMENTUM_BREAK_RSI_MAX and
                    volume_ratio >= MOMENTUM_BREAK_VOLUME_MIN):
                    buy_mode = 'MOMENTUM_BREAK'
                    mode_conditions_met = True
        
        # --- CRASH (급락장) ---
        elif condition == 'CRASH':
            # 모드: CRASH_REVERSAL (반등)
            if (CRASH_REVERSAL_BB_MIN <= bb_position_15m <= CRASH_REVERSAL_BB_MAX and
                CRASH_REVERSAL_RSI_MIN <= rsi_15m <= CRASH_REVERSAL_RSI_MAX):
                
                # 양봉 확인 (최소 1개 - 완화됨)
                recent_bullish = 0
                for i in range(-1, -4, -1):
                    if df_15m.iloc[i]['close'] > df_15m.iloc[i]['open']:
                        recent_bullish += 1
                
                # RSI 상승 추세 확인
                rsi_rising = df_15m.iloc[-1]['rsi'] > df_15m.iloc[-2]['rsi']
                
                if recent_bullish >= CRASH_REVERSAL_MIN_BULLISH or rsi_rising:
                    buy_mode = 'CRASH_REVERSAL'
                    mode_conditions_met = True
        
        # --- NORMAL (평균장) ---
        else:
            # 모드 1: NORMAL_BOTTOM (하단 반등) - 우선
            if (NORMAL_BOTTOM_BB_MIN <= bb_position_15m <= NORMAL_BOTTOM_BB_MAX and
                NORMAL_BOTTOM_RSI_MIN <= rsi_15m <= NORMAL_BOTTOM_RSI_MAX):
                buy_mode = 'NORMAL_BOTTOM'
                mode_conditions_met = True
            
            # 모드 2: MOMENTUM_BREAK (돌파) - 보조
            if not mode_conditions_met:
                volume_ratio = df_15m.iloc[-1]['volume_ratio']
                if (MOMENTUM_BREAK_BB_MIN <= bb_position_15m <= MOMENTUM_BREAK_BB_MAX and
                    MOMENTUM_BREAK_RSI_MIN <= rsi_15m <= MOMENTUM_BREAK_RSI_MAX and
                    volume_ratio >= MOMENTUM_BREAK_VOLUME_MIN):
                    buy_mode = 'MOMENTUM_BREAK'
                    mode_conditions_met = True
        
        # ========================================
        # Step 4: 조건 미충족 시 반환
        # ========================================
        if not mode_conditions_met:
            base_response['reason'] = f'[{condition}] 매수 조건 미충족 (BB:{bb_position_15m:.0f}%, RSI:{rsi_15m:.0f})'
            return base_response
        
        # ========================================
        # Step 5: 점수 계산
        # ========================================
        score_result = calculate_buy_score_adaptive(df_15m, market_condition, buy_mode)
        score = score_result['score']
        
        # 모드별 최소 점수 체크
        min_scores = {
            'SURGE_PULLBACK': SURGE_PULLBACK_MIN_SCORE,
            'CRASH_REVERSAL': CRASH_REVERSAL_MIN_SCORE,
            'NORMAL_BOTTOM': NORMAL_BOTTOM_MIN_SCORE,
            'MOMENTUM_BREAK': MOMENTUM_BREAK_MIN_SCORE
        }
        
        min_score = min_scores.get(buy_mode, 75)
        
        if score < min_score:
            base_response['reason'] = f'[{buy_mode}] 점수 부족 ({score:.0f}/{min_score})'
            base_response['mode'] = buy_mode
            base_response['score'] = score
            return base_response
        
        # ========================================
        # Step 6: 매수 신호 발생!
        # ========================================
        reason_lines = [f"[{buy_mode}] {score:.0f}점"]
        reason_lines.extend(score_result['reasons'][:5])
        
        return {
            'signal': True,
            'reason': "\n".join(reason_lines),
            'confidence': min(score, 100),
            'entry_price': current_price,
            'bb_position': bb_position_15m,
            'bb_width_pct': bb_width_pct,
            'mode': buy_mode,
            'market_condition': condition,
            'score': score,
            'daily_bb': market_condition['daily_bb']
        }
        
    except Exception as e:
        import traceback
        if DEBUG_MODE:
            print(f"[v78 Buy Signal Error] {e}")
            traceback.print_exc()
        
        return {
            'signal': False,
            'reason': f'오류: {str(e)}',
            'confidence': 0,
            'entry_price': 0,
            'bb_position': 50,
            'bb_width_pct': 0,
            'mode': 'ERROR',
            'market_condition': 'UNKNOWN',
            'score': 0,
            'daily_bb': 50
        }

    


def check_daily_bb_filter(ticker, market_condition):
    """
    [v7.8 개선] 일봉 BB 기반 고가매수 방지 필터 - 완화 버전
    
    [v7.8 변경사항]
    - 필터 기준: 60% → 70% 완화
    - 음봉 허용: -0.3% → -1.5% 완화
    - 시장 상황 고려: 급락장에서는 필터 완화
    
    Args:
        ticker: 코인 티커
        market_condition: detect_market_condition() 반환값
    
    Returns:
        tuple: (매수가능여부, 사유)
    """
    try:
        # 급락장에서는 필터 완화 (반등 기회 포착)
        condition = market_condition.get('condition', 'NORMAL')
        if condition == 'CRASH':
            return (True, "급락장 필터 완화", 0, 0)
        
        # 캐시 체크
        cache_key = f"{ticker}_daily_bb_check_v78"
        cached = get_cached_data(cache_key, DAILY_BB_CACHE_TTL)
        
        if cached is not None:
            return cached
        
        # 일봉 데이터 조회
        df_daily = get_candles_daily(ticker, count=50)
        
        if df_daily is None or len(df_daily) < 20:
            result = (True, "일봉 데이터 없음 (필터 스킵)", 50.0, 0.0)
            set_cached_data(cache_key, result)
            return result
        
        df_daily = add_indicators(df_daily)
        
        if df_daily is None:
            result = (True, "일봉 지표 계산 실패 (필터 스킵)", 50.0, 0.0)
            set_cached_data(cache_key, result)
            return result
        
        current_daily = df_daily.iloc[-1]
        current_daily_bb = current_daily['bb_position']
        daily_open = current_daily['open']
        daily_close = current_daily['close']
        
        if daily_open > 0:
            daily_change_pct = ((daily_close - daily_open) / daily_open) * 100
        else:
            daily_change_pct = 0.0
        
        # ========================================
        # v7.8 완화된 필터 로직
        # ========================================
        
        # Case 1: 일봉 BB 70% 미만 → 무조건 통과
        if current_daily_bb < DAILY_BB_HIGH_FILTER_V78:
            result = (
                True,
                f"일봉 BB {current_daily_bb:.1f}% < {DAILY_BB_HIGH_FILTER_V78}% (안전구간)",
                current_daily_bb,
                daily_change_pct
            )
            set_cached_data(cache_key, result)
            return result
        
        # Case 2: 일봉 BB 70%+ 구간
        
        # 양봉 또는 약한 음봉 (-1.5% 이내) → 허용
        if daily_change_pct >= DAILY_BEARISH_LIMIT:
            result = (
                True,
                f"일봉 BB {current_daily_bb:.1f}% | 등락 {daily_change_pct:+.2f}% (허용)",
                current_daily_bb,
                daily_change_pct
            )
            set_cached_data(cache_key, result)
            return result
        
        # 강한 음봉 (-1.5% 초과) → 차단
        result = (
            False,
            f"고가매수 방지: 일봉 BB {current_daily_bb:.1f}% + 강한음봉 {daily_change_pct:.2f}%",
            current_daily_bb,
            daily_change_pct
        )
        set_cached_data(cache_key, result)
        return result
        
    except Exception as e:
        return (True, f"일봉 필터 오류 (스킵): {e}", 50.0, 0.0)

    
# ================================================================================
# SECTION 14: v7.6 Sell Logic - UPPER BAND MASTER
# ================================================================================

def get_sell_mode(df_15m, df_daily):
    """
    [v7.7] 매도 모드 판단: SURGE(급등) vs NORMAL(일반)
    
    SURGE 모드 진입 조건 (모두 충족):
    1. 일봉 BB >= 65%
    2. 당일 등락률 >= +1.0%
    3. 최근 3개 15분봉 중 양봉 2개 이상
    4. RSI 상승 추세
    
    Returns:
        dict: {
            'mode': 'SURGE' or 'NORMAL',
            'daily_bb': 일봉 BB 위치,
            'daily_change': 당일 등락률,
            'reason': 판단 사유
        }
    """
    try:
        # 기본값 (NORMAL 모드)
        result = {
            'mode': 'NORMAL',
            'daily_bb': 50.0,
            'daily_change': 0.0,
            'reason': '일반 모드'
        }
        
        # 일봉 데이터 검증
        if df_daily is None or len(df_daily) < 20:
            result['reason'] = '일봉 데이터 부족 → 일반모드'
            return result
        
        # 일봉 BB 위치
        current_daily = df_daily.iloc[-1]
        daily_bb = current_daily['bb_position']
        result['daily_bb'] = daily_bb
        
        # 당일 등락률 (시가 대비)
        daily_open = current_daily['open']
        daily_close = current_daily['close']
        
        if daily_open > 0:
            daily_change = ((daily_close - daily_open) / daily_open) * 100
        else:
            daily_change = 0.0
        result['daily_change'] = daily_change
        
        # 조건 1: 일봉 BB 위치
        if daily_bb < SURGE_MODE_DAILY_BB_MIN:
            result['reason'] = f'일봉BB {daily_bb:.1f}% < {SURGE_MODE_DAILY_BB_MIN}% → 일반모드'
            return result
        
        # 조건 2: 당일 등락률
        if daily_change < SURGE_MODE_DAILY_CHANGE_MIN:
            result['reason'] = f'당일 {daily_change:+.2f}% < +{SURGE_MODE_DAILY_CHANGE_MIN}% → 일반모드'
            return result
        
        # 조건 3: 양봉 추세 (최근 3봉)
        if len(df_15m) < 3:
            result['reason'] = '15분봉 데이터 부족 → 일반모드'
            return result
        
        bullish_count = 0
        for i in range(-3, 0):
            if df_15m.iloc[i]['close'] > df_15m.iloc[i]['open']:
                bullish_count += 1
        
        if bullish_count < SURGE_MODE_BULLISH_COUNT:
            result['reason'] = f'양봉 {bullish_count}개 < {SURGE_MODE_BULLISH_COUNT}개 → 일반모드'
            return result
        
        # 조건 4: RSI 상승 추세
        rsi_current = df_15m.iloc[-1]['rsi']
        rsi_prev = df_15m.iloc[-2]['rsi']
        
        if rsi_current <= rsi_prev:
            result['reason'] = f'RSI 하락 ({rsi_prev:.1f}→{rsi_current:.1f}) → 일반모드'
            return result
        
        # 모든 조건 충족 → SURGE 모드
        result['mode'] = 'SURGE'
        result['reason'] = f'급등모드: 일봉BB {daily_bb:.1f}%, 당일 +{daily_change:.2f}%, 양봉 {bullish_count}개, RSI↑'
        
        return result
        
    except Exception as e:
        if DEBUG_MODE:
            print(f"{Colors.RED}[Sell Mode Error] {e}{Colors.ENDC}")
        return {
            'mode': 'NORMAL',
            'daily_bb': 50.0,
            'daily_change': 0.0,
            'reason': f'오류 발생 → 일반모드: {e}'
        }

def evolution_76_sell_signal(df, buy_price, buy_time=None, held_info=None):
    """
    [v7.7] UPPER BAND MASTER - 이원화 매도 시스템
    
    SURGE 모드 (급등): 일봉 고점 + 모멘텀 강할 때 → 매도 기준 완화
    NORMAL 모드 (일반): 기존 v7.6 로직 유지
    
    [ENHANCED - VERIFIED]
    - V76_RSI_CONSECUTIVE_DROP: RSI 연속 하락 체크 추가
    - V76_EXCEPTION_MAX_MINUTES: 시간 제한 추가 (30분)
    
    Args:
        df: 15분봉 DataFrame (지표 포함)
        buy_price: 매수가
        buy_time: 매수 시각 (선택)
        held_info: 보유 정보 dict (선택, surge_entry_profit 등)
    
    Returns:
        dict: 매도 신호 정보
    """
    
    if len(df) < 5:
        return {
            'signal': False, 
            'reason': 'Data insufficient', 
            'exit_price': 0.0, 
            'profit_pct': 0.0, 
            'bb_position': 0.0,
            'bb_width_pct': 0.0,
            'sell_mode': 'NORMAL'
        }
    
    current = df.iloc[-1]
    prev = df.iloc[-2]
    current_price = current['close']
    profit_pct = ((current_price - buy_price) / buy_price) * 100
    bb_position = current['bb_position']
    bb_width_pct = current['bb_width']
    rsi = current['rsi']
    rsi_prev = prev['rsi']
    
    # 기본 응답 템플릿
    base_response = {
        'exit_price': current_price,
        'profit_pct': profit_pct,
        'bb_position': bb_position,
        'bb_width_pct': bb_width_pct
    }
    
    # ========================================
    # Step 0: 손절 체크 (-5%) - 모든 모드 공통
    # ========================================
    if profit_pct <= V76_STOP_LOSS_PCT and bb_position < V76_STOP_LOSS_BB:
        return {
            **base_response,
            'signal': True,
            'reason': f'STOP_LOSS ({profit_pct:.2f}%)',
            'sell_mode': 'STOP_LOSS'
        }
    
    # ========================================
    # Step 1: 매도 모드 판단 (일봉 데이터 필요)
    # ========================================
    try:
        # 현재 티커 추출 시도 (df에서 직접 얻기 어려우므로 캐시 활용)
        # 일봉 데이터는 sell_thread에서 전달받거나 여기서 조회
        df_daily = None
        
        # held_info에 ticker 정보가 있으면 일봉 조회
        if held_info and 'ticker' in held_info:
            ticker = held_info['ticker']
            df_daily = get_candles_daily(ticker, count=50)
            if df_daily is not None and len(df_daily) >= 20:
                df_daily = add_indicators(df_daily)
        
        sell_mode_info = get_sell_mode(df, df_daily)
        sell_mode = sell_mode_info['mode']
        
    except Exception as e:
        sell_mode = 'NORMAL'
        sell_mode_info = {'mode': 'NORMAL', 'reason': f'모드 판단 오류: {e}'}
    
    # ========================================
    # Step 2: BB < 70% → 절대 홀드 (양 모드 공통)
    # ========================================
    if bb_position < V76_BB_SAFE_ZONE:
        return {
            **base_response,
            'signal': False,
            'reason': f'HOLD (BB {bb_position:.1f}% < {V76_BB_SAFE_ZONE}%)',
            'sell_mode': sell_mode
        }
    
    # ========================================
    # SURGE 모드: 급등 시 매도 기준 완화
    # ========================================
    if sell_mode == 'SURGE':
        
        # 급등 모드 진입 시점 수익률 저장/조회
        surge_entry_profit = profit_pct
        if held_info and 'surge_entry_profit' in held_info:
            surge_entry_profit = held_info['surge_entry_profit']
        
        # === 긴급 탈출 조건 ===
        
        # 탈출 1: BB 급락 (80% 아래)
        if bb_position < SURGE_EXIT_BB_DROP:
            return {
                **base_response,
                'signal': True,
                'reason': f'SURGE_EXIT: BB급락 {bb_position:.1f}% < {SURGE_EXIT_BB_DROP}%',
                'sell_mode': 'SURGE_EXIT'
            }
        
        # 탈출 2: 수익률 급락 (진입 대비 -1.5%p)
        profit_drawdown = surge_entry_profit - profit_pct
        if profit_drawdown >= SURGE_EXIT_PROFIT_DRAWDOWN:
            return {
                **base_response,
                'signal': True,
                'reason': f'SURGE_EXIT: 수익급락 {profit_pct:.2f}% (진입 {surge_entry_profit:.2f}%, -{profit_drawdown:.2f}%p)',
                'sell_mode': 'SURGE_EXIT'
            }
        
        # 탈출 3: 시간 초과 (45분) + 신고가 미갱신
        if buy_time and held_info:
            elapsed_minutes = (datetime.now() - buy_time).total_seconds() / 60
            peak_price = held_info.get('peak_price', buy_price)
            
            if elapsed_minutes >= SURGE_MAX_HOLD_MINUTES:
                # 신고가 대비 현재가 체크
                if peak_price > 0 and current_price < peak_price * 0.99:
                    return {
                        **base_response,
                        'signal': True,
                        'reason': f'SURGE_EXIT: {elapsed_minutes:.0f}분 경과 + 고점대비 하락',
                        'sell_mode': 'SURGE_TIMEOUT'
                    }
        
        # === 익절 조건 ===
        
        # 익절 1: RSI 과열 후 하락
        if rsi_prev >= 75 and (rsi_prev - rsi) >= SURGE_EXIT_RSI_DROP:
            return {
                **base_response,
                'signal': True,
                'reason': f'SURGE_PROFIT: RSI과열후하락 ({rsi_prev:.0f}→{rsi:.0f})',
                'sell_mode': 'SURGE_PROFIT'
            }
        
        # 익절 2: 연속 음봉 + 거래량 감소
        bearish_count = 0
        for i in range(-SURGE_EXIT_CONSECUTIVE_BEAR, 0):
            if df.iloc[i]['close'] < df.iloc[i]['open']:
                bearish_count += 1
        
        volume_dropping = current['volume'] < prev['volume']
        
        if bearish_count >= SURGE_EXIT_CONSECUTIVE_BEAR and volume_dropping:
            return {
                **base_response,
                'signal': True,
                'reason': f'SURGE_PROFIT: 음봉{bearish_count}연속 + 거래량감소',
                'sell_mode': 'SURGE_PROFIT'
            }
        
        # 익절 3: 트레일링 스탑 (+5% 후 -0.5% 드로다운)
        if profit_pct >= SURGE_TRAILING_PROFIT:
            if held_info and 'peak_price' in held_info:
                peak_price = held_info['peak_price']
                peak_profit = ((peak_price - buy_price) / buy_price) * 100
                trailing_drawdown = peak_profit - profit_pct
                
                if trailing_drawdown >= SURGE_TRAILING_DRAWDOWN:
                    return {
                        **base_response,
                        'signal': True,
                        'reason': f'SURGE_TRAILING: 고점{peak_profit:.2f}%→현재{profit_pct:.2f}% (-{trailing_drawdown:.2f}%p)',
                        'sell_mode': 'SURGE_TRAILING'
                    }
        
        # 급등 모드 홀드 지속
        return {
            **base_response,
            'signal': False,
            'reason': f'SURGE_HOLD: BB{bb_position:.1f}%, 수익{profit_pct:.2f}%, RSI{rsi:.0f}',
            'sell_mode': 'SURGE'
        }
    
    # ========================================
    # NORMAL 모드: 기존 v7.6 로직
    # ========================================
    
    # ========================================
    # Step 3: 예외관찰 (Score 60+) - ENHANCED
    # [NEW] V76_EXCEPTION_MAX_MINUTES 시간 제한 추가
    # ========================================
    exception_score = 0
    exception_details = []
    
    # [NEW] 시간 제한 체크 (30분 초과 시 예외 관찰 비활성화)
    holding_minutes = 0
    if buy_time:
        holding_minutes = (datetime.now() - buy_time).total_seconds() / 60
    
    if holding_minutes > V76_EXCEPTION_MAX_MINUTES:
        # 30분 초과 시 예외 관찰 스킵 (정상 로직으로 진행)
        pass
    else:
        # 30분 이내일 때만 예외 관찰 활성화
        if profit_pct >= V76_EXCEPTION_PROFIT_MIN:
            exception_score += V76_EXCEPTION_PROFIT_WEIGHT
            exception_details.append(f"Profit{profit_pct:.1f}%")
        
        avg_volume = df['volume'].tail(20).mean()
        volume_ratio = current['volume'] / avg_volume if avg_volume > 0 else 0
        if volume_ratio >= V76_EXCEPTION_VOLUME_MIN:
            exception_score += V76_EXCEPTION_VOLUME_WEIGHT
            exception_details.append(f"Vol{volume_ratio:.1f}x")
        
        bullish_count = 0
        for i in range(-3, 0):
            if df.iloc[i]['close'] > df.iloc[i]['open']:
                bullish_count += 1
        if bullish_count >= V76_EXCEPTION_BULLISH_COUNT:
            exception_score += V76_EXCEPTION_BULLISH_WEIGHT
            exception_details.append(f"Bull{bullish_count}")
        
        if bb_position >= 100:
            exception_score += V76_EXCEPTION_BB_WEIGHT
            exception_details.append(f"BB{bb_position:.0f}%")
        
        if exception_score >= V76_EXCEPTION_SCORE_THRESHOLD:
            is_bearish = current['close'] < current['open']
            if is_bearish:
                return {
                    **base_response,
                    'signal': True,
                    'reason': f"EXCEPTION_EXIT (Bearish, Profit{profit_pct:.2f}%, Score{exception_score})",
                    'sell_mode': 'NORMAL'
                }
            else:
                return {
                    **base_response,
                    'signal': False,
                    'reason': f"EXCEPTION_HOLD ({'+'.join(exception_details)}, Score{exception_score}/60, {holding_minutes:.0f}분)",
                    'sell_mode': 'NORMAL'
                }
    
    # ========================================
    # Step 4: BB 70-90% → 모멘텀 소진 체크 - ENHANCED
    # [NEW] V76_RSI_CONSECUTIVE_DROP RSI 연속 하락 체크 추가
    # ========================================
    if bb_position < V76_BB_BREAKOUT_ZONE:
        
        if profit_pct < V76_MIN_PROFIT_TARGET:
            return {
                **base_response,
                'signal': False,
                'reason': f'TARGET_WAIT (Profit{profit_pct:.2f}% < {V76_MIN_PROFIT_TARGET}%)',
                'sell_mode': 'NORMAL'
            }
        
        momentum_exhausted = False
        exhaustion_reasons = []
        
        bb_upper_touches = 0
        for i in range(-3, 0):
            if df.iloc[i]['bb_position'] >= 85:
                bb_upper_touches += 1
        
        if bb_upper_touches >= V76_BB_UPPER_TOUCH_COUNT and rsi < rsi_prev:
            momentum_exhausted = True
            exhaustion_reasons.append(f"BB_UPPER{bb_upper_touches}+RSI_DROP")
        
        bearish_count = 0
        for i in range(-2, 0):
            if df.iloc[i]['close'] < df.iloc[i]['open']:
                bearish_count += 1
        
        # [ENHANCED] RSI 연속 하락 체크 추가
        rsi_consecutive_drop = 0
        for i in range(-1, -V76_RSI_CONSECUTIVE_DROP-1, -1):
            if len(df) + i - 1 < 0:
                break
            if df.iloc[i]['rsi'] < df.iloc[i-1]['rsi']:
                rsi_consecutive_drop += 1
            else:
                break
        
        rsi_drop = rsi_prev - rsi
        
        # [ENHANCED] 연속 하락 조건 추가
        if bearish_count >= V76_CONSECUTIVE_BEAR and rsi_drop >= V76_RSI_DROP_THRESHOLD and rsi_consecutive_drop >= V76_RSI_CONSECUTIVE_DROP:
            momentum_exhausted = True
            exhaustion_reasons.append(f"Bear{bearish_count}+RSI-{rsi_drop:.1f}p+RSI{rsi_consecutive_drop}연속하락")
        
        is_bearish = current['close'] < current['open']
        if profit_pct >= V76_BREAKOUT_PROFIT and rsi >= V76_MAX_RSI and is_bearish:
            momentum_exhausted = True
            exhaustion_reasons.append(f"OVERBOUGHT_EXIT(RSI{rsi:.0f})")
        
        if momentum_exhausted:
            return {
                **base_response,
                'signal': True,
                'reason': f'MOMENTUM_EXHAUSTED ({", ".join(exhaustion_reasons)}, Profit{profit_pct:.2f}%)',
                'sell_mode': 'NORMAL'
            }
        
        return {
            **base_response,
            'signal': False,
            'reason': f'MOMENTUM_OK (BB{bb_position:.1f}%, Profit{profit_pct:.2f}%)',
            'sell_mode': 'NORMAL'
        }
    
    # ========================================
    # Step 5: BB >= 90% → 상단 돌파 구간
    # ========================================
    is_bearish = current['close'] < current['open']
    if is_bearish and profit_pct >= V76_BREAKOUT_PROFIT:
        return {
            **base_response,
            'signal': True,
            'reason': f'BREAKOUT_EXIT (BB{bb_position:.1f}%, Profit{profit_pct:.2f}%)',
            'sell_mode': 'NORMAL'
        }
    
    if profit_pct >= V76_OVERBOUGHT_PROFIT and rsi >= V76_EXTREME_RSI:
        return {
            **base_response,
            'signal': True,
            'reason': f'OVERBOUGHT_PROFIT (RSI{rsi:.0f}, Profit{profit_pct:.2f}%)',
            'sell_mode': 'NORMAL'
        }
    
    return {
        **base_response,
        'signal': False,
        'reason': f'BREAKOUT_HOLD (BB{bb_position:.1f}%, Profit{profit_pct:.2f}%)',
        'sell_mode': 'NORMAL'
    }

def evolution_70_sell_signal(df, buy_price):
    """Legacy wrapper - redirects to v7.6"""
    return evolution_76_sell_signal(df, buy_price)


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
    [v7.8] 개선된 매수 스레드 워커
    - evolution_77_buy_signal() 사용
    - 시장 상황 로깅 추가
    """
    print(f"{Colors.CYAN}[Thread 1] v7.8 매수 스레드 시작 ({BUY_THREAD_INTERVAL}초 주기){Colors.ENDC}")
    
    iteration = 0
    
    while not stop_event.is_set():
        try:
            iteration += 1
            
            # 연속 손실 체크
            if not check_consecutive_losses():
                time.sleep(BUY_THREAD_INTERVAL)
                continue
            
            # 시장 상태 체크
            market_ok, _ = check_market_condition()
            if not market_ok:
                time.sleep(BUY_THREAD_INTERVAL)
                continue
            
            # 일일 거래 한도 체크
            if not check_daily_trade_limit():
                time.sleep(BUY_THREAD_INTERVAL)
                continue
            
            # 보유 종목 수 체크
            with held_coins_lock:
                current_holdings = len(held_coins)
            
            if current_holdings >= MAX_HOLDINGS:
                time.sleep(BUY_THREAD_INTERVAL)
                continue
            
            # 각 코인별 매수 검토
            for ticker in FIXED_STABLE_COINS:
                
                if stop_event.is_set():
                    return
                
                # 이미 보유 중인지 체크
                with held_coins_lock:
                    if ticker in held_coins:
                        continue
                
                # 재진입 쿨다운 체크
                can_enter, _ = check_reentry_cooldown(ticker)
                if not can_enter:
                    continue
                
                # 15분봉 데이터 조회
                df_15m = get_candles(ticker, interval='15', count=50)
                
                if df_15m is None or len(df_15m) < 20:
                    continue
                
                # 기술적 지표 계산
                df_15m = add_indicators(df_15m)
                
                if df_15m is None:
                    continue
                
                # ========================================
                # [v7.8] 적응형 매수 신호 체크
                # ========================================
                buy_signal = evolution_77_buy_signal(df_15m, ticker)
                
                if buy_signal['signal']:
                    coin_name = ticker.replace('KRW-', '')
                    mode = buy_signal.get('mode', 'UNKNOWN')
                    market = buy_signal.get('market_condition', 'UNKNOWN')
                    
                    print(f"\n{Colors.CYAN}[BUY Thread] {coin_name} 매수 신호!{Colors.ENDC}")
                    print(f"  시장상황: {market}")
                    print(f"  매수모드: {mode}")
                    print(f"  신뢰도: {buy_signal.get('score', 0):.0f}점")
                    print(f"  15분봉 BB: {buy_signal['bb_position']:.1f}%")
                    print(f"  일봉 BB: {buy_signal['daily_bb']:.1f}%")
                    print(f"  {buy_signal['reason']}")
                    
                    # 매수 실행
                    execute_buy(ticker, buy_signal)
                    time.sleep(2)
                    
                    # 최대 보유 종목 도달 체크
                    with held_coins_lock:
                        if len(held_coins) >= MAX_HOLDINGS:
                            break
            
            time.sleep(BUY_THREAD_INTERVAL)
            
        except Exception as e:
            error_trace = traceback.format_exc()
            print(f"{Colors.RED}[BUY Thread Error] {e}{Colors.ENDC}")
            if DEBUG_MODE:
                print(error_trace)
            time.sleep(BUY_THREAD_INTERVAL)
    
    print(f"{Colors.CYAN}[Thread 1] v7.8 매수 스레드 종료{Colors.ENDC}")


def sell_thread_worker():
    """
    [v7.7] Sell thread worker - 이원화 매도 시스템 적용
    - SURGE 모드 진입 시점 수익률 기록
    - held_info 전달로 모드별 처리
    """
    print(f"{Colors.YELLOW}[Thread 2] 매도 스레드 시작 ({SELL_THREAD_INTERVAL}초 주기){Colors.ENDC}")
    
    iteration = 0
    
    while not stop_event.is_set():
        try:
            iteration += 1
            
            with held_coins_lock:
                tickers = list(held_coins.keys())
            
            if not tickers:
                time.sleep(SELL_THREAD_INTERVAL)
                continue
            
            for ticker in tickers:
                
                if stop_event.is_set():
                    return
                
                # 15분봉 데이터 조회
                df_15m = get_candles(ticker, interval='15', count=50)
                
                if df_15m is None or len(df_15m) < 20:
                    continue
                
                df_15m = add_indicators(df_15m)
                
                if df_15m is None:
                    continue
                
                current_price = df_15m.iloc[-1]['close']
                update_peak_tracking(ticker, current_price)
                
                # 보유 정보 조회
                with held_coins_lock:
                    if ticker not in held_coins:
                        continue
                    
                    held_info = held_coins[ticker].copy()
                    held_info['ticker'] = ticker  # 티커 정보 추가
                    
                    buy_price = held_info['buy_price']
                    buy_time = held_info.get('buy_time', datetime.now())
                    
                    # 현재 수익률 계산
                    current_profit = ((current_price - buy_price) / buy_price) * 100
                    
                    # SURGE 모드 진입 여부 체크 및 진입시점 수익률 기록
                    if 'surge_entry_profit' not in held_coins[ticker]:
                        # 일봉 데이터 조회하여 모드 판단
                        df_daily = get_candles_daily(ticker, count=50)
                        if df_daily is not None and len(df_daily) >= 20:
                            df_daily = add_indicators(df_daily)
                            mode_info = get_sell_mode(df_15m, df_daily)
                            
                            if mode_info['mode'] == 'SURGE':
                                held_coins[ticker]['surge_entry_profit'] = current_profit
                                held_coins[ticker]['surge_entry_time'] = datetime.now()
                                
                                coin_name = ticker.replace('KRW-', '')
                                print(f"{Colors.CYAN}[SURGE] {coin_name} 급등모드 진입! "
                                      f"수익률 {current_profit:.2f}%, "
                                      f"일봉BB {mode_info['daily_bb']:.1f}%, "
                                      f"당일 {mode_info['daily_change']:+.2f}%{Colors.ENDC}")
                    
                    # 업데이트된 held_info 다시 조회
                    held_info = held_coins[ticker].copy()
                    held_info['ticker'] = ticker
                
                # v7.7 매도 신호 체크 (held_info 전달)
                sell_signal = evolution_76_sell_signal(df_15m, buy_price, buy_time, held_info)
                
                if sell_signal['signal']:
                    profit_pct = sell_signal['profit_pct']
                    sell_mode = sell_signal.get('sell_mode', 'NORMAL')
                    
                    print(f"\n{Colors.YELLOW}[SELL Thread] {ticker} 매도 신호! [{sell_mode}]{Colors.ENDC}")
                    print(f"  수익률: {profit_pct:+.2f}%")
                    print(f"  사유: {sell_signal['reason']}")
                    
                    # SURGE 모드 정보 초기화
                    with held_coins_lock:
                        if ticker in held_coins:
                            if 'surge_entry_profit' in held_coins[ticker]:
                                del held_coins[ticker]['surge_entry_profit']
                            if 'surge_entry_time' in held_coins[ticker]:
                                del held_coins[ticker]['surge_entry_time']
                    
                    execute_sell(ticker, sell_signal)
                    time.sleep(2)
            
            time.sleep(SELL_THREAD_INTERVAL)
            
        except Exception as e:
            error_trace = traceback.format_exc()
            print(f"{Colors.RED}[SELL Thread Error] {e}{Colors.ENDC}")
            if DEBUG_MODE:
                print(error_trace)
            time.sleep(SELL_THREAD_INTERVAL)
    
    print(f"{Colors.YELLOW}[Thread 2] 매도 스레드 종료{Colors.ENDC}")


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