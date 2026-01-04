#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
================================================================================
EVOLUTION v7.6 "UPPER BAND MASTER" - THREADED EDITION (ENHANCED)
================================================================================
Strategy: Buy at BB bottom reversal | Hold until BB upper breakout | Catch big moves
Core: Buy at real bottom, Sell at real top
Target: 2-5% profit per trade, 75%+ win rate

[v7.6 Key Improvements]
- Buy: BB <=20% bottom touch + reversal confirmation (85+ points)
- Sell: Never sell below BB 80% (raised from 75%)
- Sell: BB 80-95% momentum exhaustion check
- Sell: BB >=95% profit securing
- Exception: Don't miss big rallies (volume 2x + 3 bullish candles)
- Stop Loss: -3% quick exit
- REMOVED: Volume drop condition (was causing false signals!)

[v7.6 ENHANCED - 337 Patch]
- NEW: Sync existing positions on startup
- NEW: Enhanced portfolio tracking with held_coins integration
- NEW: Improved hourly reporting with extended time window
- FIX: Portfolio status now shows accurate buy price and hold time
- FIX: Hourly reports now trigger reliably

[v7.6 ENHANCED - 338 Patch]
- NEW: Equal position sizing (1/3 of total assets per trade)
- NEW: Dynamic asset rebalancing on every buy signal
- NEW: Fee-optimized all-in on final position (0.9995x)
- NEW: BB width % display in market analysis reports
- IMPROVED: Compound interest effect through real-time asset evaluation
- REMOVED: Fixed MIN_CASH_RESERVE (was wasting 5,000 KRW)
- OPTIMIZED: Capital efficiency improved from 70% to 99.98%

[THREADED EDITION]
- Thread 1: Buy only (10 sec cycle)
- Thread 2: Sell only (5 sec cycle)  
- Thread 3: Monitoring (60 sec cycle)
- Lock-based thread safety
================================================================================
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
VERSION = "7.6 UPPER_BAND_MASTER [THREADED+ENHANCED+DAILY_BB_FILTER]"

FIXED_STABLE_COINS = [
    "KRW-ETH", "KRW-XRP", "KRW-SOL",
    "KRW-ADA", "KRW-LINK", "KRW-BCH", "KRW-SUI"
]

POSITION_SIZE_RATIO = 0.33
MAX_HOLDINGS = 3
FULL_INVEST_THRESHOLD = 0.35
MIN_CASH_RESERVE = 5000
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
DAILY_BB_HIGH_FILTER = 80            # 일봉 BB 80% 이상에서 복합 조건 적용
DAILY_BB_CACHE_TTL = 60              # 일봉 데이터 1분 캐싱 (실시간성 강화)
DAILY_BB_FILTER_ENABLED = True       # 필터 활성화
DAILY_BB_NEUTRAL_THRESHOLD = 0.3     # 중립 구간: 시가 대비 ±0.3% 이내

# ================================================================================
# SECTION 3: v7.6 Strategy Parameters
# ================================================================================

# [Buy Strategy]
V75_BUY_BB_MAX = 15
V75_BUY_BB_EXTREME = 10
V75_BUY_MIN_SCORE = 85
V75_BUY_CONSECUTIVE_BULL = 2
V75_BUY_MIN_VOLUME_RATIO = 0.8
V75_BUY_MIN_BB_WIDTH = 2.5
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
V76_STOP_LOSS_PCT = -3.0       # -3% stop loss
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

# ================================================================================
# SECTION 8: Startup Message
# ================================================================================

print(f"\n{Colors.BOLD}{Colors.CYAN}{'='*80}")
print(f"EVOLUTION {VERSION}")
print(f"{'='*80}")
print(f"{Colors.GREEN}Strategy{Colors.ENDC}")
print(f"   [Buy] BB <=20% bottom touch -> reversal entry (85+ points)")
print(f"   [Buy Filter] Daily BB < {DAILY_BB_HIGH_FILTER}% (high price prevention)")
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
print(f"{'='*80}{Colors.ENDC}\n")


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
    """매수 알림 - 개선된 가독성"""
    try:
        portfolio = get_enhanced_portfolio_status()
        coin_name = ticker.replace('KRW-', '')
        
        # 한 줄 자산 요약
        asset_line = f"💰 **자산** `총 {portfolio['total_assets']:,.0f}원` | `코인 {portfolio['total_coin_value']:,.0f}원` | `현금 {portfolio['krw_balance']:,.0f}원`"
        
        # BB 폭% 정보 추가
        bb_width_str = ""
        if signal.get('bb_width_pct') is not None:
            bb_width_str = f" [폭{signal['bb_width_pct']:.1f}%]"
        
        # 매수 정보
        buy_info = f"""✅ **{coin_name} 매수완료**
├ **거래** `{buy_amount:,.0f}원` @ `{signal['entry_price']:,.0f}원`
└ 📊 `BB {signal['bb_position']:.0f}%{bb_width_str}` | `신뢰 {signal['confidence']:.0f}%` | **사유:** {signal['reason'].split('(')[0]}"""
        
        # 보유 코인 목록 (간결화)
        holdings_text = ""
        if portfolio['coins']:
            holdings_text = f"\n\n📦 **보유 {len(portfolio['coins'])}/{MAX_HOLDINGS}**"
            for coin_info in portfolio['coins']:
                c_name = coin_info['ticker'].replace('KRW-', '')
                holdings_text += f"\n├ **{c_name}** `{coin_info['balance']:.4f}개`"
                holdings_text += f"\n│ └ 💵 `{coin_info['profit_pct']:+.2f}%` `({coin_info['value']:,.0f}원)`"
        
        message = f"""
{'━'*40}
{asset_line}
{'━'*40}

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
{'━'*40}
{asset_line}
{'━'*40}

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
        # [NEW] 일봉 BB 위치 조회
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
        # ========================================
        
        # 보유 수익률 확인
        holding_profit = None
        with held_coins_lock:
            if ticker in held_coins:
                buy_price = held_coins[ticker]['buy_price']
                holding_profit = ((current_price - buy_price) / buy_price) * 100
        
        # 신호 판단 (일봉 BB 반영)
        signal = "HOLD"
        reason = ""
        
        # 일봉 70%+ 경고
        daily_warning = daily_bb_position is not None and daily_bb_position >= DAILY_BB_HIGH_FILTER
        
        if bb_position <= 25 and current_rsi <= 35:
            if daily_warning:
                signal = "HOLD"
                reason = "⚠️일봉고점"
            else:
                signal = "BUY"
                reason = "저점 매수기회"
        elif bb_position >= 80 and current_rsi >= 70:
            signal = "SELL"
            reason = "고점 매도시점"
        elif bb_position <= 20:
            if daily_warning:
                signal = "HOLD"
                reason = "⚠️일봉고점"
            else:
                signal = "BUY"
                reason = "BB 하단근접"
        elif bb_position >= 85:
            signal = "SELL"
            reason = "BB 상단돌파"
        elif current_rsi <= 30:
            if daily_warning:
                signal = "HOLD"
                reason = "⚠️일봉고점"
            else:
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
            'daily_bb_position': daily_bb_position,  # [NEW] 일봉 BB
            'rsi': current_rsi,
            'signal': signal,
            'reason': reason,
            'holding_profit': holding_profit
        }
        
    except Exception as e:
        if DEBUG_MODE:
            print(f"{Colors.RED}[Coin Analysis Error] {ticker}: {e}{Colors.ENDC}")
        return None


def generate_market_summary():
    """
    시장 분석 요약 - 개선된 가독성 (일봉BB 추가, 보유코인 정보 완전화)
    
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
        
        message = f"\n{'━'*40}\n📊 **시장현황**\n{'━'*40}"
        
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
                
                # BB 폭% 표시 (복원)
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
                
                # 2줄 포맷 (정보량 유지 + 가독성)
                # 1줄: 코인명 | 현재가 | 수익률+수익금 | 보유시간
                message += f"\n{profit_emoji} **{coin_name}** `{coin['price']:,.0f}원`"
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
                        emoji = "⚠️"  # 일봉 고점 시 경고 이모지로 변경
                        daily_warning = "⚠️"
                
                # BB 폭% 표시 (복원)
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
        return f"\n{'━'*40}\n📊 **시장현황**\n{'━'*40}\n\n⚠️ 데이터 수집 오류"


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
{'━'*40}
{asset_line}
{'━'*40}

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
    """v7.5 Buy score calculation (100 points max)"""
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
        
        # 2. Reversal Confirmation (30 points)
        if current['is_bull'] == 1:
            score += 15
            reasons.append("OK Current bullish")
        
        if prev1['is_bull'] == 1:
            score += 15
            reasons.append("OK Previous bullish")
        
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


def evolution_70_buy_signal(df):
    """v7.0 Buy signal"""
    try:
        if len(df) < 20:
            return {
                'signal': False, 
                'reason': 'Data insufficient', 
                'confidence': 0.0, 
                'entry_price': 0.0, 
                'bb_position': 0.0,
                'bb_width_pct': 0.0
            }
        
        score_info = calculate_buy_score_v75(df)
        score = score_info['score']
        
        current = df.iloc[-1]
        entry_price = current['close']
        bb_position = current['bb_position']
        bb_width_pct = current['bb_width']  # BB 폭% 추가
        
        if score >= V75_BUY_MIN_SCORE:
            reason = f"Buy Signal ({score:.0f} points)\n"
            reason += "\n".join(score_info['reasons'])
            
            return {
                'signal': True,
                'reason': reason,
                'confidence': min(score, 100.0),
                'entry_price': entry_price,
                'bb_position': bb_position,
                'bb_width_pct': bb_width_pct,  # 추가
                'score': score
            }
        
        return {
            'signal': False,
            'reason': f'Score insufficient ({score:.0f}/{V75_BUY_MIN_SCORE})',
            'confidence': score,
            'entry_price': entry_price,
            'bb_position': bb_position,
            'bb_width_pct': bb_width_pct,  # 추가
            'score': score
        }
        
    except Exception as e:
        if DEBUG_MODE:
            print(f"{Colors.RED}[Buy Signal Error] {e}{Colors.ENDC}")
        
        return {
            'signal': False,
            'reason': f'Error: {str(e)}',
            'confidence': 0,
            'entry_price': 0,
            'bb_position': 50,
            'bb_width_pct': 0.0,  # 추가
            'score': 0
        }

# ========================================
# [NEW] Daily BB Filter Function
# ========================================

# ========================================
# [v7.6+] Daily BB Filter Function - ENHANCED
# ========================================

def check_daily_bb_filter(ticker):
    """
    일봉 BB 기반 고가매수 방지 필터 (v7.6+ ENHANCED)
    
    [v7.6+ 개선사항]
    - 기존: 일봉 BB ≥ 95% → 무조건 차단
    - 개선: 일봉 BB ≥ 80% AND 당일 음봉 → 차단
    
    원리:
    - 일봉 BB 80%+ = 일봉 레벨 상단권 (주의 구간)
    - 당일 양봉 = 상승 모멘텀 유지 → 매수 허용
    - 당일 음봉 = 하락 전환 신호 → 매수 차단
    - 중립 구간 (±0.3%) = 방향 미확정 → 매수 허용
    
    장점:
    - 상승 추세 중 건강한 조정은 매수 허용
    - Dead Cat Bounce (하락 중 일시 반등) 방지
    - 기존 95% 필터보다 유연하면서 핵심 위험 차단
    
    Args:
        ticker: 코인 티커 (예: "KRW-BTC")
    
    Returns:
        tuple: (매수가능여부, 사유, 일봉BB위치, 당일등락률)
            - (True, "필터 통과", 50.0, 1.5)
            - (False, "고가매수 방지", 85.0, -1.2)
    """
    try:
        # 필터 비활성화 체크
        if not DAILY_BB_FILTER_ENABLED:
            return (True, "필터 비활성화", 50.0, 0.0)
        
        # 캐시 체크 (TTL: 60초)
        cache_key = f"{ticker}_daily_bb_check_v2"
        cached = get_cached_data(cache_key, DAILY_BB_CACHE_TTL)
        
        if cached is not None:
            return cached
        
        # 일봉 데이터 조회
        df_daily = get_candles_daily(ticker, count=50)
        
        if df_daily is None or len(df_daily) < 20:
            # 일봉 조회 실패 시: 필터 스킵 (안전)
            result = (True, "일봉 데이터 없음 (필터 스킵)", 50.0, 0.0)
            set_cached_data(cache_key, result)
            return result
        
        # 볼린저밴드 지표 계산
        df_daily = add_indicators(df_daily)
        
        if df_daily is None:
            result = (True, "일봉 지표 계산 실패 (필터 스킵)", 50.0, 0.0)
            set_cached_data(cache_key, result)
            return result
        
        # 현재 일봉 데이터 추출
        current_daily = df_daily.iloc[-1]
        current_daily_bb = current_daily['bb_position']
        daily_open = current_daily['open']
        daily_close = current_daily['close']
        
        # 당일 등락률 계산 (시가 대비)
        if daily_open > 0:
            daily_change_pct = ((daily_close - daily_open) / daily_open) * 100
        else:
            daily_change_pct = 0.0
        
        # ========================================
        # 필터 로직 (v7.6+ ENHANCED)
        # ========================================
        
        # Case 1: 일봉 BB 80% 미만 → 무조건 통과
        if current_daily_bb < DAILY_BB_HIGH_FILTER:
            result = (
                True,
                f"일봉 BB {current_daily_bb:.1f}% < {DAILY_BB_HIGH_FILTER}% (안전구간)",
                current_daily_bb,
                daily_change_pct
            )
            set_cached_data(cache_key, result)
            return result
        
        # Case 2: 일봉 BB 80%+ 구간 → 양봉/음봉 판단
        
        # 중립 구간 체크: 시가 대비 ±0.3% 이내
        if abs(daily_change_pct) <= DAILY_BB_NEUTRAL_THRESHOLD:
            result = (
                True,
                f"일봉 BB {current_daily_bb:.1f}% | 등락 {daily_change_pct:+.2f}% (중립구간, 허용)",
                current_daily_bb,
                daily_change_pct
            )
            set_cached_data(cache_key, result)
            return result
        
        # 양봉 (상승) → 매수 허용
        if daily_change_pct > DAILY_BB_NEUTRAL_THRESHOLD:
            result = (
                True,
                f"일봉 BB {current_daily_bb:.1f}% | 당일 양봉 +{daily_change_pct:.2f}% (상승모멘텀, 허용)",
                current_daily_bb,
                daily_change_pct
            )
            set_cached_data(cache_key, result)
            return result
        
        # 음봉 (하락) → 매수 차단
        if daily_change_pct < -DAILY_BB_NEUTRAL_THRESHOLD:
            result = (
                False,
                f"고가매수 방지: 일봉 BB {current_daily_bb:.1f}% + 당일 음봉 {daily_change_pct:.2f}%",
                current_daily_bb,
                daily_change_pct
            )
            set_cached_data(cache_key, result)
            
            # 디버그 로그
            if DEBUG_MODE:
                coin_name = ticker.replace('KRW-', '')
                print(f"{Colors.YELLOW}[Daily Filter] {coin_name}: BB {current_daily_bb:.1f}% + 음봉 {daily_change_pct:.2f}% → 차단{Colors.ENDC}")
            
            return result
        
        # Fallback (논리적으로 도달 불가)
        result = (True, "필터 조건 미충족 (허용)", current_daily_bb, daily_change_pct)
        set_cached_data(cache_key, result)
        return result
        
    except Exception as e:
        if DEBUG_MODE:
            print(f"{Colors.RED}[Daily BB Filter Error] {ticker}: {e}{Colors.ENDC}")
        # 예외 발생 시: 필터 스킵 (안전한 방향)
        return (True, "일봉 필터 오류 (스킵)", 50.0, 0.0)
    
# ================================================================================
# SECTION 14: v7.6 Sell Logic - UPPER BAND MASTER
# ================================================================================

def evolution_76_sell_signal(df, buy_price, buy_time=None):
    """
    v7.6 UPPER BAND MASTER - Sell Signal
    
    Core Changes:
    - Volume drop condition REMOVED (false signal prevention)
    - BB safe zone below 80%: absolute hold
    - Momentum exhaustion confirmation strengthened
    - Exception observation score system from v331
    
    Logic Flow:
    Step 1: Stop loss check (-3%)
    Step 2: BB < 80% -> absolute hold
    Step 3: Exception observation (score 60+)
    Step 4: BB 80-95% -> momentum exhaustion confirmation
    Step 5: BB >= 95% -> upper band breakout zone
    """
    
    if len(df) < 5:
        return {
            'signal': False, 
            'reason': 'Data insufficient', 
            'exit_price': 0.0, 
            'profit_pct': 0.0, 
            'bb_position': 0.0,
            'bb_width_pct': 0.0
        }
    
    current = df.iloc[-1]
    prev = df.iloc[-2]
    current_price = current['close']
    profit_pct = ((current_price - buy_price) / buy_price) * 100
    bb_position = current['bb_position']
    bb_width_pct = current['bb_width']  # BB 폭% 추가
    rsi = current['rsi']
    rsi_prev = prev['rsi']
    
    # ========================================
    # Step 1: Stop Loss Check (-3%)
    # ========================================
    if profit_pct <= V76_STOP_LOSS_PCT and bb_position < V76_STOP_LOSS_BB:
        return {
            'signal': True, 
            'reason': f'STOP_LOSS ({profit_pct:.2f}%)', 
            'exit_price': current_price, 
            'profit_pct': profit_pct, 
            'bb_position': bb_position,
            'bb_width_pct': bb_width_pct  # 추가
        }
    
    # ========================================
    # Step 2: BB < 80% -> Absolute Hold
    # ========================================
    if bb_position < V76_BB_SAFE_ZONE:
        return {
            'signal': False, 
            'reason': f'HOLD (BB {bb_position:.1f}% < 80%)', 
            'exit_price': current_price, 
            'profit_pct': profit_pct, 
            'bb_position': bb_position,
            'bb_width_pct': bb_width_pct  # 추가
        }
    
    # ========================================
    # Step 3: Exception Observation (v331 Score System)
    # ========================================
    exception_score = 0
    exception_details = []
    
    # Profit +4%+: 30 points
    if profit_pct >= V76_EXCEPTION_PROFIT_MIN:
        exception_score += V76_EXCEPTION_PROFIT_WEIGHT
        exception_details.append(f"Profit{profit_pct:.1f}%")
    
    # Volume 2x+: 25 points
    avg_volume = df['volume'].tail(20).mean()
    volume_ratio = current['volume'] / avg_volume if avg_volume > 0 else 0
    if volume_ratio >= V76_EXCEPTION_VOLUME_MIN:
        exception_score += V76_EXCEPTION_VOLUME_WEIGHT
        exception_details.append(f"Vol{volume_ratio:.1f}x")
    
    # 3 consecutive bullish: 25 points
    bullish_count = 0
    for i in range(-3, 0):
        if df.iloc[i]['close'] > df.iloc[i]['open']:
            bullish_count += 1
    if bullish_count >= V76_EXCEPTION_BULLISH_COUNT:
        exception_score += V76_EXCEPTION_BULLISH_WEIGHT
        exception_details.append(f"Bull{bullish_count}")
    
    # BB 100%+ breakout: 20 points
    if bb_position >= 100:
        exception_score += V76_EXCEPTION_BB_WEIGHT
        exception_details.append(f"BB{bb_position:.0f}%")
    
    # 60+ points: Exception observation mode
    if exception_score >= V76_EXCEPTION_SCORE_THRESHOLD:
        is_bearish = current['close'] < current['open']
        if is_bearish:
            return {
                'signal': True,
                'reason': f"EXCEPTION_EXIT (Bearish, Profit{profit_pct:.2f}%, Score{exception_score})",
                'exit_price': current_price,
                'profit_pct': profit_pct,
                'bb_position': bb_position,
                'bb_width_pct': bb_width_pct  # 추가
            }
        else:
            return {
                'signal': False,
                'reason': f"EXCEPTION_HOLD ({'+'.join(exception_details)}, Score{exception_score}/60)",
                'exit_price': current_price,
                'profit_pct': profit_pct,
                'bb_position': bb_position,
                'bb_width_pct': bb_width_pct  # 추가
            }
    
    # ========================================
    # Step 4: BB 80-95% -> Momentum Exhaustion Check
    # ========================================
    if bb_position < V76_BB_BREAKOUT_ZONE:
        
        # Hold if target profit not reached
        if profit_pct < V76_MIN_PROFIT_TARGET:
            return {
                'signal': False,
                'reason': f'TARGET_WAIT (Profit{profit_pct:.2f}% < 2%)',
                'exit_price': current_price,
                'profit_pct': profit_pct,
                'bb_position': bb_position,
                'bb_width_pct': bb_width_pct  # 추가
            }
        
        # Momentum exhaustion conditions
        momentum_exhausted = False
        exhaustion_reasons = []
        
        # Condition A: BB upper (85%+) 3 consecutive touches + RSI drop
        bb_upper_touches = 0
        for i in range(-3, 0):
            if df.iloc[i]['bb_position'] >= 85:
                bb_upper_touches += 1
        
        if bb_upper_touches >= V76_BB_UPPER_TOUCH_COUNT and rsi < rsi_prev:
            momentum_exhausted = True
            exhaustion_reasons.append(f"BB_UPPER{bb_upper_touches}+RSI_DROP")
        
        # Condition B: 2 consecutive bearish + RSI drop 3p+
        bearish_count = 0
        for i in range(-2, 0):
            if df.iloc[i]['close'] < df.iloc[i]['open']:
                bearish_count += 1
        
        rsi_drop = rsi_prev - rsi
        if bearish_count >= V76_CONSECUTIVE_BEAR and rsi_drop >= V76_RSI_DROP_THRESHOLD:
            momentum_exhausted = True
            exhaustion_reasons.append(f"Bear{bearish_count}+RSI-{rsi_drop:.1f}p")
        
        # Condition C: Profit >= 1.5% + RSI 70+ + bearish candle
        is_bearish = current['close'] < current['open']
        if profit_pct >= V76_BREAKOUT_PROFIT and rsi >= V76_MAX_RSI and is_bearish:
            momentum_exhausted = True
            exhaustion_reasons.append(f"OVERBOUGHT_EXIT(RSI{rsi:.0f})")
        
        if momentum_exhausted:
            return {
                'signal': True,
                'reason': f'MOMENTUM_EXHAUSTED ({", ".join(exhaustion_reasons)}, Profit{profit_pct:.2f}%)',
                'exit_price': current_price,
                'profit_pct': profit_pct,
                'bb_position': bb_position,
                'bb_width_pct': bb_width_pct  # 추가
            }
        
        # Momentum maintained
        return {
            'signal': False,
            'reason': f'MOMENTUM_OK (BB{bb_position:.1f}%, Profit{profit_pct:.2f}%)',
            'exit_price': current_price,
            'profit_pct': profit_pct,
            'bb_position': bb_position,
            'bb_width_pct': bb_width_pct  # 추가
        }
    
    # ========================================
    # Step 5: BB >= 95% -> Upper Band Breakout Zone
    # ========================================
    
    # Sell on bearish candle (if profit >= 1.5%)
    is_bearish = current['close'] < current['open']
    if is_bearish and profit_pct >= V76_BREAKOUT_PROFIT:
        return {
            'signal': True,
            'reason': f'BREAKOUT_EXIT (BB{bb_position:.1f}%, Profit{profit_pct:.2f}%)',
            'exit_price': current_price,
            'profit_pct': profit_pct,
            'bb_position': bb_position,
            'bb_width_pct': bb_width_pct  # 추가
        }
    
    # Overbought exit: Profit 3% + RSI 75+
    if profit_pct >= V76_OVERBOUGHT_PROFIT and rsi >= V76_EXTREME_RSI:
        return {
            'signal': True,
            'reason': f'OVERBOUGHT_PROFIT (RSI{rsi:.0f}, Profit{profit_pct:.2f}%)',
            'exit_price': current_price,
            'profit_pct': profit_pct,
            'bb_position': bb_position,
            'bb_width_pct': bb_width_pct  # 추가
        }
    
    # Upper band breakout in progress
    return {
        'signal': False,
        'reason': f'BREAKOUT_HOLD (BB{bb_position:.1f}%, Profit{profit_pct:.2f}%)',
        'exit_price': current_price,
        'profit_pct': profit_pct,
        'bb_position': bb_position,
        'bb_width_pct': bb_width_pct  # 추가
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
    봇 시작 시 1회 실행
    """
    global held_coins
    
    print(f"\n{Colors.CYAN}{'='*70}")
    print(f"[Init] 기존 보유 코인 동기화 시작...")
    print(f"{'='*70}{Colors.ENDC}")
    
    try:
        balances = upbit.get_balances()
        synced_count = 0
        total_value = 0.0
        
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
                    'buy_time': datetime.now(),  # 정확한 시간 불명
                    'buy_amount': balance * avg_buy_price,
                    'peak_price': avg_buy_price,
                    'peak_time': datetime.now(),
                    'buy_reason': 'EXISTING_POSITION (봇 시작 시 동기화)'
                }
            
            synced_count += 1
            print(f"{Colors.GREEN}  ✓ {ticker}: {balance:.4f} @ {avg_buy_price:,.0f}원 (평가액: {coin_value:,.0f}원, {profit_pct:+.2f}%){Colors.ENDC}")
        
        krw_balance = upbit.get_balance("KRW")
        
        print(f"\n{Colors.GREEN}{'='*70}")
        print(f"[Init] 동기화 완료")
        print(f"  - 동기화된 코인: {synced_count}개")
        print(f"  - 코인 총 평가액: {total_value:,.0f}원")
        print(f"  - 보유 현금: {krw_balance:,.0f}원")
        print(f"  - 총 자산: {total_value + krw_balance:,.0f}원")
        print(f"{'='*70}{Colors.ENDC}\n")
        
        # Discord 알림
        if synced_count > 0:
            sync_message = f"""
**🔄 기존 보유 코인 동기화 완료**

**동기화된 코인:** `{synced_count}개`
**코인 총 평가액:** `{total_value:,.0f}원`
**보유 현금:** `{krw_balance:,.0f}원`
**총 자산:** `{total_value + krw_balance:,.0f}원`

⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
"""
            send_discord_message(sync_message)
        
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
    - Equal position sizing: 1/3 of total assets per trade
    - Dynamic rebalancing: Asset evaluation on every buy
    - Fee optimization: 0.9995x on final position
    """
    # ============================================================
    # 🆕 MODIFIED: daily_buy_count 추가 (1줄 수정)
    # ============================================================
    global daily_trade_count, total_trades, daily_buy_count
    # ============================================================
    
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
                    print(f"{Colors.YELLOW}[Buy Limit] 최대 보유 종목 도달{Colors.ENDC}")
                    return False
            
            # Step 1: 총 자산 계산 (현금 + 모든 코인 평가액)
            try:
                total_assets = get_total_balance()
            except:
                print(f"{Colors.RED}[Buy Failed] 총 자산 조회 실패{Colors.ENDC}")
                return False
            
            # Step 2: 목표 포지션 사이즈 (총 자산의 1/3 균등 분할)
            target_position_size = total_assets / MAX_HOLDINGS
            
            # Step 3: 현재 KRW 잔고 조회
            try:
                krw_balance = upbit.get_balance("KRW")
            except:
                print(f"{Colors.RED}[Buy Failed] 잔고 조회 실패{Colors.ENDC}")
                return False
            
            # Step 4: 매수 금액 결정
            buy_amount = target_position_size
            
            # Step 5: 잔고 부족 시 수수료 고려하여 최대 매수
            if buy_amount > krw_balance:
                buy_amount = krw_balance * 0.9995
                print(f"{Colors.CYAN}[Buy Info] 잔고 부족으로 최대 매수: {buy_amount:,.0f}원{Colors.ENDC}")
            
            # Step 6: Upbit 최소 주문 금액 체크 (5,000원)
            if buy_amount < 5000:
                print(f"{Colors.YELLOW}[Buy Limit] 최소 주문 금액 미달 ({buy_amount:,.0f}원 < 5,000원){Colors.ENDC}")
                return False
            
            # 매수 정보 출력
            print(f"{Colors.CYAN}[Buy Info] 총자산: {total_assets:,.0f}원 | 목표포지션: {target_position_size:,.0f}원 | 실제매수: {buy_amount:,.0f}원{Colors.ENDC}")
            
            if TEST_MODE:
                print(f"{Colors.GREEN}[TEST] 매수 시뮬레이션: {ticker} {buy_amount:,.0f}원{Colors.ENDC}")
                
                with held_coins_lock:
                    held_coins[ticker] = {
                        'buy_price': signal['entry_price'],
                        'buy_time': datetime.now(),
                        'buy_amount': buy_amount,
                        'peak_price': signal['entry_price'],
                        'peak_time': datetime.now(),
                        'buy_reason': signal['reason']
                    }
                
                # ============================================================
                # 🆕 MODIFIED: daily_buy_count 추가 (1줄 추가)
                # ============================================================
                daily_trade_count += 1
                daily_buy_count += 1
                # ============================================================
                total_trades += 1
                
                send_buy_notification(ticker, signal, buy_amount, total_assets)
                return True
            
            # 실제 매수 실행
            try:
                result = upbit.buy_market_order(ticker, buy_amount)
                
                if result is None:
                    print(f"{Colors.RED}[Buy Failed] 주문 실패{Colors.ENDC}")
                    return False
                
                time.sleep(1)
                
                balances = upbit.get_balances()
                coin_balance = None
                
                for bal in balances:
                    if bal['currency'] == ticker.split('-')[1]:
                        coin_balance = bal
                        break
                
                if not coin_balance:
                    print(f"{Colors.RED}[Buy Failed] 잔고 확인 실패{Colors.ENDC}")
                    return False
                
                actual_buy_price = float(coin_balance['avg_buy_price'])
                
                with held_coins_lock:
                    held_coins[ticker] = {
                        'buy_price': actual_buy_price,
                        'buy_time': datetime.now(),
                        'buy_amount': buy_amount,
                        'peak_price': actual_buy_price,
                        'peak_time': datetime.now(),
                        'buy_reason': signal['reason']
                    }
                
                # ============================================================
                # 🆕 MODIFIED: daily_buy_count 추가 (1줄 추가)
                # ============================================================
                daily_trade_count += 1
                daily_buy_count += 1
                # ============================================================
                total_trades += 1
                
                print(f"{Colors.GREEN}[Buy Success] {ticker} {actual_buy_price:,.0f}원 (투자액: {buy_amount:,.0f}원){Colors.ENDC}")
                
                send_buy_notification(ticker, signal, buy_amount, total_assets)
                return True
                
            except Exception as e:
                print(f"{Colors.RED}[Buy Failed] {e}{Colors.ENDC}")
                send_error_notification("Buy Failed", str(e))
                return False
    
    except Exception as e:
        print(f"{Colors.RED}[Buy Error] {e}{Colors.ENDC}")
        return False

def execute_sell(ticker, signal):
    """Execute sell order (thread safe)"""
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
            
            try:
                balances = upbit.get_balances()
                coin_balance = None
                
                for bal in balances:
                    if bal['currency'] == ticker.split('-')[1]:
                        coin_balance = bal
                        break
                
                if not coin_balance:
                    print(f"{Colors.RED}[Sell Failed] 잔고 조회 실패{Colors.ENDC}")
                    return False
                
                coin_amount = float(coin_balance['balance'])
                
                result = upbit.sell_market_order(ticker, coin_amount)
                
                if result is None:
                    print(f"{Colors.RED}[Sell Failed] 주문 실패{Colors.ENDC}")
                    return False
                
                time.sleep(1)
                
                try:
                    current_price = pyupbit.get_current_price(ticker)
                    actual_sell_price = current_price if current_price else sell_price
                except:
                    actual_sell_price = sell_price
                
                actual_profit_pct = ((actual_sell_price - buy_price) / buy_price) * 100
                actual_profit_amount = hold_info['buy_amount'] * (actual_profit_pct / 100)
                
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
                
                signal['profit_pct'] = actual_profit_pct
                signal['exit_price'] = actual_sell_price
                send_sell_notification(ticker, hold_info, signal, actual_profit_amount, hold_duration)
                return True
                
            except Exception as e:
                print(f"{Colors.RED}[Sell Failed] {e}{Colors.ENDC}")
                send_error_notification("Sell Failed", str(e))
                return False
    
    except Exception as e:
        print(f"{Colors.RED}[Sell Error] {e}{Colors.ENDC}")
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
    Buy thread worker (10 sec cycle)
    [v7.6+] 일봉 BB 필터 ENHANCED - 고가매수 방지 + 상승모멘텀 포착
    """
    print(f"{Colors.CYAN}[Thread 1] 매수 스레드 시작 ({BUY_THREAD_INTERVAL}초 주기){Colors.ENDC}")
    
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
                
                # ========================================
                # [v7.6+] 일봉 BB 필터 체크 (ENHANCED)
                # ========================================
                filter_result = check_daily_bb_filter(ticker)
                can_buy = filter_result[0]
                filter_reason = filter_result[1]
                daily_bb = filter_result[2]
                daily_change_pct = filter_result[3] if len(filter_result) > 3 else 0.0
                
                if not can_buy:
                    if DEBUG_MODE:
                        coin_name = ticker.replace('KRW-', '')
                        print(f"{Colors.YELLOW}[Filter] {coin_name}: {filter_reason}{Colors.ENDC}")
                    continue
                
                # 15분봉 데이터 조회
                df_15m = get_candles(ticker, interval='15', count=50)
                
                if df_15m is None or len(df_15m) < 20:
                    continue
                
                # 기술적 지표 계산
                df_15m = add_indicators(df_15m)
                
                if df_15m is None:
                    continue
                
                # v7.6 매수 신호 체크
                buy_signal = evolution_70_buy_signal(df_15m)
                
                if buy_signal['signal']:
                    coin_name = ticker.replace('KRW-', '')
                    
                    print(f"\n{Colors.CYAN}[BUY Thread] {coin_name} 매수 신호 발생!{Colors.ENDC}")
                    print(f"  신뢰도: {buy_signal.get('score', 0):.0f}점")
                    print(f"  15분봉 BB: {buy_signal['bb_position']:.1f}%")
                    print(f"  일봉 BB: {daily_bb:.1f}% | 당일 {daily_change_pct:+.2f}% ✓")
                    print(f"  {buy_signal['reason']}")
                    
                    # 매수 신호에 일봉 정보 추가
                    buy_signal['daily_bb_position'] = daily_bb
                    buy_signal['daily_change_pct'] = daily_change_pct
                    buy_signal['reason'] = f"{buy_signal['reason']}\n[일봉 BB {daily_bb:.1f}% | 당일 {daily_change_pct:+.2f}% 필터 통과]"
                    
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
    
    print(f"{Colors.CYAN}[Thread 1] 매수 스레드 종료{Colors.ENDC}")


def sell_thread_worker():
    """Sell thread worker (5 sec cycle)"""
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
                
                df_15m = get_candles(ticker, interval='15', count=50)
                
                if df_15m is None or len(df_15m) < 20:
                    continue
                
                df_15m = add_indicators(df_15m)
                
                if df_15m is None:
                    continue
                
                current_price = df_15m.iloc[-1]['close']
                update_peak_tracking(ticker, current_price)
                
                with held_coins_lock:
                    if ticker not in held_coins:
                        continue
                    buy_price = held_coins[ticker]['buy_price']
                    buy_time = held_coins[ticker].get('buy_time', datetime.now())
                
                sell_signal = evolution_76_sell_signal(df_15m, buy_price, buy_time)
                
                if sell_signal['signal']:
                    profit_pct = sell_signal['profit_pct']
                    
                    print(f"\n{Colors.YELLOW}[SELL Thread] {ticker} 매도 신호!{Colors.ENDC}")
                    print(f"  수익률: {profit_pct:+.2f}%")
                    print(f"  사유: {sell_signal['reason']}")
                    
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
            
            print(f"\n{Colors.MAGENTA}{'='*70}")
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
            
            print(f"{'='*70}{Colors.ENDC}\n")
            
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
        print(f"\n{Colors.RED}{'='*70}")
        print(f"[Exit] 사용자 중단 - 안전 종료 시작")
        print(f"{'='*70}{Colors.ENDC}")
        
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