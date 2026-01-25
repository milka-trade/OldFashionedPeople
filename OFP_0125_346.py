#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
================================================================================
EVOLUTION v8.0 "MOMENTUM WAVE" - THREADED EDITION
================================================================================
Strategy: Slope-based momentum trading | Adaptive wave targeting | Dynamic exits
Target: 1-3% profit per trade, 55-65% win rate, 3-8 trades per day

[v8.0 패러다임 전환]
- 기존: BB 절대 위치 기반 (BB ≤20% 매수) → 거래 0건
- 신규: 가격 기울기(Slope) 기반 → 하루 3-8건 거래

[매수 시그널]
1. REVERSAL: 하락→상승 기울기 전환 (V자 반전)
2. PULLBACK: 상승 추세 중 눌림목 매수
3. EXPLOSION: 거래량 폭발 + 강한 상승

[매도 시그널]
- 모멘텀 스코어 기반 동적 판단
- 파동 크기 적응형 목표 수익
- 트레일링 스탑 + 급락 감지
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
    HEADER = '\033[95m'
    BLUE = '\033[94m'
    CYAN = '\033[96m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'
    MAGENTA = '\033[35m'


# ================================================================================
# SECTION 2: System Settings
# ================================================================================

DEBUG_MODE = True
TEST_MODE = False
VERSION = "8.0 MOMENTUM_WAVE"

FIXED_STABLE_COINS = [
    "KRW-ETH", "KRW-XRP", "KRW-SOL",
    "KRW-ADA", "KRW-LINK", "KRW-BCH", "KRW-SUI"
]

POSITION_SIZE_RATIO = 1
MAX_HOLDINGS = 3
MAX_DAILY_TRADES = 999

BUY_THREAD_INTERVAL = 10
SELL_THREAD_INTERVAL = 5
MONITOR_THREAD_INTERVAL = 60

CACHE_TTL_NORMAL = 20
DAILY_BB_CACHE_TTL = 60


# ================================================================================
# SECTION 3: v8.0 MOMENTUM WAVE Parameters
# ================================================================================

# 기울기(Slope) 설정
SLOPE_PERIOD_SHORT = 3
SLOPE_PERIOD_MID = 6
SLOPE_PERIOD_LONG = 12

SLOPE_STRONG_UP = 1.5
SLOPE_WEAK_UP = 0.3
SLOPE_NEUTRAL = 0.3

# 매수 시그널 설정
REVERSAL_PREV_SLOPE_MIN = -0.5
REVERSAL_CURR_SLOPE_MIN = 0.2
REVERSAL_VOLUME_RATIO = 0.8
REVERSAL_MIN_SCORE = 60

PULLBACK_LONG_SLOPE_MIN = 0.8
PULLBACK_SHORT_SLOPE_MAX = 0.3
PULLBACK_RSI_MAX = 55
PULLBACK_BB_MAX = 55
PULLBACK_MIN_SCORE = 55

EXPLOSION_SLOPE_MIN = 1.0
EXPLOSION_VOLUME_RATIO = 1.5
EXPLOSION_BB_MIN = 40
EXPLOSION_BB_MAX = 75
EXPLOSION_MIN_SCORE = 65

BUY_MIN_SCORE = 55
BUY_VOLUME_MIN = 0.5

# 매도 시그널 설정
MOMENTUM_WEAK = 20
MOMENTUM_NEUTRAL = 0
MOMENTUM_STRONG_BEAR = -40

STOP_LOSS_DEFAULT = -2.0
STOP_LOSS_TIGHT = -1.2
STOP_LOSS_WIDE = -3.0

TARGET_PROFIT_SMALL = 1.0
TARGET_PROFIT_MID = 2.0
TARGET_PROFIT_LARGE = 3.5

TRAILING_START = 1.5
TRAILING_DISTANCE = 0.5

WAVE_SIZE_SMALL = 1.5
WAVE_SIZE_MID = 3.0

MAX_HOLD_MINUTES_SMALL = 60
MAX_HOLD_MINUTES_MID = 120
MAX_HOLD_MINUTES_LARGE = 240

# 기술적 지표
BB_PERIOD = 20
BB_STD_DEV = 2.0
RSI_PERIOD = 14
VOLUME_MA_PERIOD = 20

# 재진입 쿨다운
REENTRY_COOLDOWN_CONFIG = {
    'STOP_LOSS': 15, 'TARGET_REACHED': 3, 'TRAILING_STOP': 5,
    'MOMENTUM_EXIT': 5, 'TIME_EXIT': 10, 'DEFAULT': 5
}

# 리스크 관리
MARKET_BREAKER_THRESHOLD = -3.0
CONSECUTIVE_LOSS_LIMIT = 5
COOLDOWN_AFTER_LOSS = 30


# ================================================================================
# SECTION 4: Global State
# ================================================================================

DISCORD_WEBHOOK_URL = os.getenv("discord_webhook")
ACCESS_KEY = os.getenv("UPBIT_ACCESS_KEY")
SECRET_KEY = os.getenv("UPBIT_SECRET_KEY")

stop_event = Event()
held_coins_lock = Lock()
trade_lock = Lock()
statistics_lock = Lock()
cache_lock = Lock()

upbit = None
held_coins = {}
recent_sells = {}
daily_trade_count = 0
last_reset_date = datetime.now().date()
data_cache = {}
cache_timestamps = {}

start_time = datetime.now()
total_trades = 0
winning_trades = 0
losing_trades = 0
total_profit = 0.0
consecutive_losses = 0
last_loss_time = None

daily_buy_count = 0
daily_sell_count = 0
daily_winning_trades = 0
daily_losing_trades = 0


# ================================================================================
# SECTION 5: Startup Message
# ================================================================================

print(f"\n{Colors.BOLD}{Colors.CYAN}{'='*60}")
print(f"EVOLUTION {VERSION}")
print(f"{'='*60}")
print(f"{Colors.GREEN}🚀 MOMENTUM WAVE TRADING{Colors.ENDC}")
print(f"{Colors.YELLOW}[BUY] REVERSAL | PULLBACK | EXPLOSION (Min {BUY_MIN_SCORE}점){Colors.ENDC}")
print(f"{Colors.YELLOW}[SELL] 모멘텀 스코어 + 적응형 목표 + 트레일링{Colors.ENDC}")
print(f"{'='*60}{Colors.ENDC}\n")


# ================================================================================
# SECTION 6: Discord Functions
# ================================================================================

def send_discord_message(message, is_critical=False):
    if not DISCORD_WEBHOOK_URL:
        return False
    try:
        header = f"EVOLUTION {VERSION}"
        full_message = f"@everyone\n**{header}**\n{message}" if is_critical else f"**{header}**\n{message}"
        response = requests.post(DISCORD_WEBHOOK_URL, json={"content": full_message}, timeout=5)
        return response.status_code == 204
    except:
        return False


def send_buy_notification(ticker, signal, buy_amount, total_balance):
    try:
        portfolio = get_enhanced_portfolio_status()
        coin_name = ticker.replace('KRW-', '')
        mode = signal.get('mode', 'NORMAL')
        mode_emoji = {'REVERSAL': '🔄', 'PULLBACK': '📉', 'EXPLOSION': '💥'}.get(mode, '✅')
        
        slope_str = f" | 기울기`{signal['slope']:+.2f}%`" if signal.get('slope') else ""
        
        holdings_text = ""
        if portfolio['coins']:
            holdings_text = f"\n📦 **보유 {len(portfolio['coins'])}/{MAX_HOLDINGS}**"
            for c in portfolio['coins']:
                holdings_text += f"\n├ **{c['ticker'].replace('KRW-','')}** `{c['profit_pct']:+.2f}%`"
        
        message = f"""
{'━'*10}
💰 `총 {portfolio['total_assets']:,.0f}원` | `현금 {portfolio['krw_balance']:,.0f}원`
{'━'*10}

{mode_emoji} **{coin_name} 매수** [{mode}]
├ `{buy_amount:,.0f}원` @ `{signal['entry_price']:,.0f}원`
└ BB`{signal['bb_position']:.0f}%` | 신뢰`{signal['confidence']:.0f}%`{slope_str}
{holdings_text}

⏱ {datetime.now().strftime('%H:%M:%S')}
"""
        send_discord_message(message)
    except Exception as e:
        if DEBUG_MODE:
            print(f"{Colors.RED}[Buy Noti Error] {e}{Colors.ENDC}")


def send_sell_notification(ticker, holding_info, signal, profit_amount, holding_duration):
    try:
        portfolio = get_enhanced_portfolio_status()
        coin_name = ticker.replace('KRW-', '')
        profit_emoji = "📈" if signal['profit_pct'] > 0 else "📉"
        
        holdings_text = ""
        if portfolio['coins']:
            holdings_text = f"\n📦 **보유 {len(portfolio['coins'])}/{MAX_HOLDINGS}**"
            for c in portfolio['coins']:
                holdings_text += f"\n├ **{c['ticker'].replace('KRW-','')}** `{c['profit_pct']:+.2f}%`"
        else:
            holdings_text = f"\n📦 **보유** `0/{MAX_HOLDINGS}`"
        
        win_rate = (daily_winning_trades / daily_sell_count * 100) if daily_sell_count > 0 else 0
        
        message = f"""
{'━'*10}
💰 `총 {portfolio['total_assets']:,.0f}원` | `현금 {portfolio['krw_balance']:,.0f}원`
{'━'*10}

{profit_emoji} **{coin_name} 매도** `({holding_duration})`
├ `{holding_info['buy_price']:,.0f}` → `{signal['exit_price']:,.0f}원`
├ 💵 **{signal['profit_pct']:+.2f}%** `({profit_amount:+,.0f}원)`
└ {signal['reason'][:40]}
{holdings_text}
🎯 금일 매수`{daily_buy_count}` 매도`{daily_sell_count}` 승률`{win_rate:.0f}%`

⏰ {datetime.now().strftime('%H:%M:%S')}
"""
        send_discord_message(message)
    except Exception as e:
        if DEBUG_MODE:
            print(f"{Colors.RED}[Sell Noti Error] {e}{Colors.ENDC}")


def send_error_notification(error_type, error_details):
    try:
        send_discord_message(f"**오류:** `{error_type}`\n`{error_details[:300]}`", is_critical=True)
    except:
        pass


# ================================================================================
# SECTION 7: Utility Functions
# ================================================================================

def format_duration(td):
    try:
        total_seconds = int(td.total_seconds())
        hours, remainder = divmod(total_seconds, 3600)
        minutes = remainder // 60
        return f"{hours}시간 {minutes}분" if hours > 0 else f"{minutes}분"
    except:
        return "0분"


def get_cached_data(cache_key, ttl):
    try:
        with cache_lock:
            if cache_key in data_cache and cache_key in cache_timestamps:
                if (datetime.now() - cache_timestamps[cache_key]).total_seconds() < ttl:
                    return data_cache[cache_key]
        return None
    except:
        return None


def set_cached_data(cache_key, data):
    try:
        with cache_lock:
            data_cache[cache_key] = data
            cache_timestamps[cache_key] = datetime.now()
    except:
        pass


def check_reentry_cooldown(ticker):
    try:
        if ticker not in recent_sells:
            return True, "OK"
        
        sell_info = recent_sells[ticker]
        sell_time = sell_info['time']
        sell_reason = sell_info.get('reason', 'DEFAULT')
        
        cooldown_key = 'DEFAULT'
        for key in ['STOP_LOSS', 'TARGET', 'TRAILING', 'MOMENTUM', 'TIME']:
            if key in sell_reason:
                cooldown_key = key + ('_REACHED' if key == 'TARGET' else '_STOP' if key == 'TRAILING' else '_EXIT' if key in ['MOMENTUM', 'TIME'] else '')
                break
        
        cooldown_minutes = REENTRY_COOLDOWN_CONFIG.get(cooldown_key, REENTRY_COOLDOWN_CONFIG['DEFAULT'])
        elapsed = (datetime.now() - sell_time).total_seconds() / 60
        
        if elapsed < cooldown_minutes:
            return False, f"Cooldown ({int(cooldown_minutes - elapsed)}분)"
        return True, "OK"
    except:
        return True, "OK"


def reset_daily_counter():
    global daily_trade_count, last_reset_date, daily_buy_count, daily_sell_count, daily_winning_trades, daily_losing_trades
    try:
        today = datetime.now().date()
        if today != last_reset_date:
            daily_trade_count = daily_buy_count = daily_sell_count = daily_winning_trades = daily_losing_trades = 0
            last_reset_date = today
            print(f"{Colors.CYAN}[Reset] 일일 통계 초기화{Colors.ENDC}")
    except:
        pass


def update_peak_tracking(ticker, current_price):
    try:
        with held_coins_lock:
            if ticker in held_coins and current_price > held_coins[ticker].get('peak_price', 0):
                held_coins[ticker]['peak_price'] = current_price
                held_coins[ticker]['peak_time'] = datetime.now()
    except:
        pass


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
                    current_price = pyupbit.get_current_price(ticker)
                    if not current_price:
                        continue
                    balance = upbit.get_balance(ticker)
                    if balance <= 0:
                        continue
                    
                    coin_value = balance * current_price
                    total_coin_value += coin_value
                    profit_pct = ((current_price - hold_info['buy_price']) / hold_info['buy_price']) * 100
                    
                    coins_info.append({
                        'ticker': ticker, 'balance': balance, 'buy_price': hold_info['buy_price'],
                        'current_price': current_price, 'value': coin_value, 'profit_pct': profit_pct,
                        'buy_time': hold_info.get('buy_time')
                    })
                except:
                    continue
        
        return {'krw_balance': krw_balance, 'total_coin_value': total_coin_value,
                'total_assets': krw_balance + total_coin_value, 'coins': coins_info}
    except:
        return {'krw_balance': 0.0, 'total_coin_value': 0.0, 'total_assets': 0.0, 'coins': []}


def get_total_balance():
    return get_enhanced_portfolio_status()['total_assets']


# ================================================================================
# SECTION 8: Data Collection
# ================================================================================

def get_candles(ticker, interval='15', count=50):
    try:
        cache_key = f"{ticker}_{interval}_{count}"
        cached = get_cached_data(cache_key, CACHE_TTL_NORMAL)
        if cached is not None:
            return cached
        
        interval_map = {'5': 'minute5', '15': 'minute15', '60': 'minute60'}
        df = pyupbit.get_ohlcv(ticker, interval=interval_map.get(interval, 'minute15'), count=count)
        
        if df is not None and len(df) >= 20:
            set_cached_data(cache_key, df)
            return df
        return None
    except:
        return None


# ================================================================================
# SECTION 9: Technical Indicators
# ================================================================================

def calculate_rsi(series, period=RSI_PERIOD):
    try:
        delta = series.diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
        rs = gain / loss
        return 100 - (100 / (1 + rs))
    except:
        return pd.Series([50] * len(series), index=series.index)


def calculate_bollinger_bands(df):
    try:
        close = df['close']
        bb_middle = close.rolling(window=BB_PERIOD).mean()
        bb_std = close.rolling(window=BB_PERIOD).std()
        bb_upper = bb_middle + (bb_std * BB_STD_DEV)
        bb_lower = bb_middle - (bb_std * BB_STD_DEV)
        bb_position = ((close - bb_lower) / (bb_upper - bb_lower) * 100).clip(0, 120)
        bb_width = ((bb_upper - bb_lower) / bb_middle * 100)
        return bb_upper, bb_middle, bb_lower, bb_position, bb_width
    except:
        return None, None, None, None, None


def calculate_slope(df, period=6):
    try:
        if len(df) < period + 1:
            return 0.0
        current_price = df.iloc[-1]['close']
        past_price = df.iloc[-period-1]['close']
        return ((current_price - past_price) / past_price) * 100 if past_price > 0 else 0.0
    except:
        return 0.0


def calculate_slopes(df):
    return {
        'short': calculate_slope(df, SLOPE_PERIOD_SHORT),
        'mid': calculate_slope(df, SLOPE_PERIOD_MID),
        'long': calculate_slope(df, SLOPE_PERIOD_LONG)
    }


def detect_wave_size(df, lookback=20):
    try:
        recent = df.tail(min(lookback, len(df)))
        high, low = recent['high'].max(), recent['low'].min()
        wave_size = ((high - low) / low) * 100 if low > 0 else 0
        
        if wave_size <= WAVE_SIZE_SMALL:
            category = 'SMALL'
        elif wave_size <= WAVE_SIZE_MID:
            category = 'MID'
        else:
            category = 'LARGE'
        return {'size': wave_size, 'category': category}
    except:
        return {'size': 2.0, 'category': 'MID'}


def add_indicators(df):
    try:
        if df is None or len(df) < BB_PERIOD:
            return None
        
        df = df.copy()
        df['rsi'] = calculate_rsi(df['close'])
        
        bb_upper, bb_middle, bb_lower, bb_position, bb_width = calculate_bollinger_bands(df)
        if bb_upper is None:
            return None
        
        df['bb_upper'] = bb_upper
        df['bb_middle'] = bb_middle
        df['bb_lower'] = bb_lower
        df['bb_position'] = bb_position
        df['bb_width'] = bb_width
        
        df['volume_ma'] = df['volume'].rolling(window=VOLUME_MA_PERIOD).mean()
        df['volume_ratio'] = df['volume'] / df['volume_ma']
        
        df['is_bull'] = (df['close'] > df['open']).astype(int)
        df['is_bear'] = (df['close'] < df['open']).astype(int)
        
        return df
    except:
        return None


# ================================================================================
# SECTION 10: Buy Logic
# ================================================================================

def calculate_momentum_score_buy(df):
    try:
        score = 0
        reasons = []
        
        current = df.iloc[-1]
        prev = df.iloc[-2]
        
        slopes = calculate_slopes(df)
        slope_short, slope_mid, slope_long = slopes['short'], slopes['mid'], slopes['long']
        
        # 기울기 점수 (0~35)
        slope_score = 0
        if slope_short > SLOPE_STRONG_UP:
            slope_score += 15
            reasons.append(f"단기강상승{slope_short:+.1f}%")
        elif slope_short > SLOPE_WEAK_UP:
            slope_score += 10
            reasons.append(f"단기상승{slope_short:+.1f}%")
        elif slope_short > 0:
            slope_score += 5
        
        if slope_mid > SLOPE_WEAK_UP:
            slope_score += 10
        elif slope_mid > -SLOPE_NEUTRAL:
            slope_score += 5
        
        if slope_long < 0 and slope_short > 0:
            slope_score += 10
            reasons.append("반전!")
        
        score += slope_score
        
        # RSI 점수 (0~20)
        rsi = current['rsi']
        rsi_score = 0
        if 30 <= rsi <= 50:
            rsi_score += 10
            reasons.append(f"RSI{rsi:.0f}")
        elif rsi < 30:
            rsi_score += 15
            reasons.append(f"과매도{rsi:.0f}")
        elif 50 < rsi <= 60:
            rsi_score += 5
        
        if rsi > prev['rsi']:
            rsi_score += 5
        score += min(rsi_score, 20)
        
        # 거래량 점수 (0~20)
        vol_ratio = current['volume_ratio']
        if vol_ratio >= 2.0:
            score += 20
            reasons.append(f"거래량{vol_ratio:.1f}x")
        elif vol_ratio >= 1.5:
            score += 15
        elif vol_ratio >= 1.0:
            score += 10
        elif vol_ratio >= 0.7:
            score += 5
        
        # 캔들 패턴 점수 (0~25)
        pattern_score = 0
        if current['is_bull'] == 1:
            pattern_score += 10
            reasons.append("양봉")
        if prev['is_bull'] == 1:
            pattern_score += 5
        if current['close'] > prev['close']:
            pattern_score += 5
        if current['low'] > prev['low']:
            pattern_score += 5
        score += min(pattern_score, 25)
        
        return {'score': score, 'slopes': slopes, 'reasons': reasons}
    except:
        return {'score': 0, 'slopes': {'short': 0, 'mid': 0, 'long': 0}, 'reasons': []}


def detect_buy_signal_reversal(df, momentum_info):
    try:
        slopes = momentum_info['slopes']
        current = df.iloc[-1]
        
        was_falling = slopes['mid'] < REVERSAL_PREV_SLOPE_MIN
        now_rising = slopes['short'] > REVERSAL_CURR_SLOPE_MIN
        has_volume = current['volume_ratio'] >= REVERSAL_VOLUME_RATIO
        
        if was_falling and now_rising and has_volume:
            return True, 15, f"V반전({slopes['mid']:+.1f}%→{slopes['short']:+.1f}%)"
        return False, 0, ""
    except:
        return False, 0, ""


def detect_buy_signal_pullback(df, momentum_info):
    try:
        slopes = momentum_info['slopes']
        current = df.iloc[-1]
        
        uptrend = slopes['long'] > PULLBACK_LONG_SLOPE_MIN
        pullback = slopes['short'] < PULLBACK_SHORT_SLOPE_MAX
        rsi_ok = current['rsi'] < PULLBACK_RSI_MAX
        bb_ok = current['bb_position'] < PULLBACK_BB_MAX
        is_bull = current['is_bull'] == 1
        
        if uptrend and pullback and rsi_ok and bb_ok and is_bull:
            return True, 10, f"눌림목(장기{slopes['long']:+.1f}%)"
        return False, 0, ""
    except:
        return False, 0, ""


def detect_buy_signal_explosion(df, momentum_info):
    try:
        slopes = momentum_info['slopes']
        current = df.iloc[-1]
        
        strong = slopes['short'] > EXPLOSION_SLOPE_MIN
        volume = current['volume_ratio'] >= EXPLOSION_VOLUME_RATIO
        bb_ok = EXPLOSION_BB_MIN < current['bb_position'] < EXPLOSION_BB_MAX
        
        if strong and volume and bb_ok:
            return True, 12, f"폭발({slopes['short']:+.1f}%,{current['volume_ratio']:.1f}x)"
        return False, 0, ""
    except:
        return False, 0, ""


def momentum_wave_buy_signal(df_15m, ticker):
    try:
        if df_15m is None or len(df_15m) < 20:
            return {'signal': False, 'reason': '데이터부족', 'confidence': 0, 'entry_price': 0,
                    'bb_position': 0, 'bb_width_pct': 0, 'mode': 'ERROR', 'score': 0}
        
        current = df_15m.iloc[-1]
        current_price = current['close']
        bb_position = current['bb_position']
        bb_width = current['bb_width']
        vol_ratio = current['volume_ratio']
        
        if vol_ratio < BUY_VOLUME_MIN:
            return {'signal': False, 'reason': f'거래량부족({vol_ratio:.2f}x)', 'confidence': 0,
                    'entry_price': current_price, 'bb_position': bb_position, 'bb_width_pct': bb_width,
                    'mode': 'LOW_VOLUME', 'score': 0}
        
        momentum_info = calculate_momentum_score_buy(df_15m)
        base_score = momentum_info['score']
        slopes = momentum_info['slopes']
        
        signal_detected, mode, bonus, signal_reason = False, 'NORMAL', 0, ""
        
        # REVERSAL
        rev_sig, rev_bonus, rev_reason = detect_buy_signal_reversal(df_15m, momentum_info)
        if rev_sig:
            signal_detected, mode, bonus, signal_reason = True, 'REVERSAL', rev_bonus, rev_reason
        
        # PULLBACK
        if not signal_detected:
            pb_sig, pb_bonus, pb_reason = detect_buy_signal_pullback(df_15m, momentum_info)
            if pb_sig:
                signal_detected, mode, bonus, signal_reason = True, 'PULLBACK', pb_bonus, pb_reason
        
        # EXPLOSION
        if not signal_detected:
            exp_sig, exp_bonus, exp_reason = detect_buy_signal_explosion(df_15m, momentum_info)
            if exp_sig:
                signal_detected, mode, bonus, signal_reason = True, 'EXPLOSION', exp_bonus, exp_reason
        
        total_score = base_score + bonus
        
        min_score = {
            'REVERSAL': REVERSAL_MIN_SCORE, 'PULLBACK': PULLBACK_MIN_SCORE,
            'EXPLOSION': EXPLOSION_MIN_SCORE
        }.get(mode, BUY_MIN_SCORE)
        
        if signal_detected and total_score >= min_score:
            reason = f"{signal_reason} | {' | '.join(momentum_info['reasons'][:3])}"
            return {'signal': True, 'reason': reason, 'confidence': min(total_score, 100),
                    'entry_price': current_price, 'bb_position': bb_position, 'bb_width_pct': bb_width,
                    'mode': mode, 'score': total_score, 'slope': slopes['short']}
        
        return {'signal': False, 'reason': f'점수부족({total_score:.0f}/{min_score})', 'confidence': total_score,
                'entry_price': current_price, 'bb_position': bb_position, 'bb_width_pct': bb_width,
                'mode': mode if signal_detected else 'NO_SIGNAL', 'score': total_score, 'slope': slopes['short']}
    except Exception as e:
        return {'signal': False, 'reason': str(e), 'confidence': 0, 'entry_price': 0,
                'bb_position': 50, 'bb_width_pct': 0, 'mode': 'ERROR', 'score': 0}


# ================================================================================
# SECTION 11: Sell Logic
# ================================================================================

def calculate_momentum_score_sell(df):
    try:
        score = 0
        reasons = []
        
        current = df.iloc[-1]
        prev = df.iloc[-2]
        
        slopes = calculate_slopes(df)
        slope_short = slopes['short']
        
        # 기울기 (±40)
        slope_score = max(-40, min(40, slope_short * 20))
        score += slope_score
        if abs(slope_short) > 0.5:
            reasons.append(f"기울기{slope_short:+.1f}%")
        
        # RSI (±20)
        rsi = current['rsi']
        rsi_change = rsi - prev['rsi']
        score += max(-20, min(20, rsi_change * 3))
        if rsi > 70:
            score -= 15
            reasons.append(f"과매수RSI{rsi:.0f}")
        
        # 거래량 (±15)
        vol_ratio = current['volume_ratio']
        if vol_ratio >= 1.5:
            if current['is_bull'] == 1:
                score += 15
            else:
                score -= 15
                reasons.append(f"매도세{vol_ratio:.1f}x")
        
        # 캔들 (±25)
        if current['is_bull'] == 1:
            score += 10
        else:
            score -= 10
            reasons.append("음봉")
        
        bear_count = sum(1 for i in range(-3, 0) if len(df) + i >= 0 and df.iloc[i]['is_bear'] == 1)
        if bear_count >= 2:
            score -= 15
            reasons.append(f"연속음봉{bear_count}")
        
        return {'score': max(-100, min(100, score)), 'slope': slope_short, 'reasons': reasons}
    except:
        return {'score': 0, 'slope': 0, 'reasons': []}


def get_adaptive_targets(df, buy_mode):
    try:
        wave_category = detect_wave_size(df)['category']
        
        targets = {
            'SMALL': (TARGET_PROFIT_SMALL, STOP_LOSS_TIGHT, 0.8, MAX_HOLD_MINUTES_SMALL),
            'MID': (TARGET_PROFIT_MID, STOP_LOSS_DEFAULT, TRAILING_START, MAX_HOLD_MINUTES_MID),
            'LARGE': (TARGET_PROFIT_LARGE, STOP_LOSS_WIDE, 2.0, MAX_HOLD_MINUTES_LARGE)
        }
        target, stop, trailing, max_hold = targets.get(wave_category, targets['MID'])
        
        # 모드별 조정
        if buy_mode == 'REVERSAL':
            target *= 1.2
            max_hold *= 1.5
        elif buy_mode == 'PULLBACK':
            target *= 0.9
            stop *= 0.8
        elif buy_mode == 'EXPLOSION':
            target *= 0.8
            max_hold *= 0.7
        
        return {'target_profit': target, 'stop_loss': stop, 'trailing_start': trailing, 'max_hold_minutes': max_hold}
    except:
        return {'target_profit': TARGET_PROFIT_MID, 'stop_loss': STOP_LOSS_DEFAULT,
                'trailing_start': TRAILING_START, 'max_hold_minutes': MAX_HOLD_MINUTES_MID}


def momentum_wave_sell_signal(df, buy_price, buy_time=None, held_info=None):
    try:
        if len(df) < 5:
            return {'signal': False, 'reason': 'Data insufficient', 'exit_price': 0.0,
                    'profit_pct': 0.0, 'bb_position': 0.0, 'bb_width_pct': 0.0}
        
        current = df.iloc[-1]
        current_price = current['close']
        bb_position = current['bb_position']
        bb_width = current['bb_width']
        
        profit_pct = ((current_price - buy_price) / buy_price) * 100
        
        base = {'exit_price': current_price, 'profit_pct': profit_pct,
                'bb_position': bb_position, 'bb_width_pct': bb_width}
        
        buy_mode = held_info.get('buy_mode', 'NORMAL') if held_info else 'NORMAL'
        targets = get_adaptive_targets(df, buy_mode)
        
        target_profit = targets['target_profit']
        stop_loss = targets['stop_loss']
        trailing_start = targets['trailing_start']
        max_hold = targets['max_hold_minutes']
        
        peak_price = held_info.get('peak_price', buy_price) if held_info else buy_price
        peak_profit = ((peak_price - buy_price) / buy_price) * 100
        
        hold_minutes = (datetime.now() - buy_time).total_seconds() / 60 if buy_time else 0
        
        momentum_info = calculate_momentum_score_sell(df)
        momentum_score = momentum_info['score']
        slope = momentum_info['slope']
        
        # 1. 손절
        if profit_pct <= stop_loss:
            return {**base, 'signal': True, 'reason': f'STOP_LOSS({profit_pct:.2f}%<={stop_loss}%)'}
        
        # 2. 목표 + 모멘텀 약화
        if profit_pct >= target_profit and momentum_score < MOMENTUM_WEAK:
            return {**base, 'signal': True, 'reason': f'TARGET({profit_pct:.2f}%>={target_profit:.1f}%)'}
        
        # 3. 트레일링
        if peak_profit >= trailing_start:
            drawdown = peak_profit - profit_pct
            if drawdown >= TRAILING_DISTANCE:
                return {**base, 'signal': True, 'reason': f'TRAILING(고점{peak_profit:.1f}%→{profit_pct:.1f}%)'}
        
        # 4. 모멘텀 급락
        if momentum_score <= MOMENTUM_STRONG_BEAR and profit_pct > 0.3:
            return {**base, 'signal': True, 'reason': f'MOMENTUM_CRASH({momentum_score})'}
        
        # 5. 시간 초과
        if hold_minutes >= max_hold and (momentum_score < MOMENTUM_NEUTRAL or profit_pct < 0.5):
            return {**base, 'signal': True, 'reason': f'TIME_EXIT({hold_minutes:.0f}분>={max_hold:.0f}분)'}
        
        # 6. 급락 감지
        if slope < -2.0 and profit_pct > -1.0:
            return {**base, 'signal': True, 'reason': f'SLOPE_CRASH({slope:.1f}%)'}
        
        return {**base, 'signal': False, 'reason': f'HOLD(수익{profit_pct:.2f}%,모멘텀{momentum_score})'}
    except Exception as e:
        return {'signal': False, 'reason': str(e), 'exit_price': 0, 'profit_pct': 0,
                'bb_position': 50, 'bb_width_pct': 0}


# ================================================================================
# SECTION 12: Market Analysis
# ================================================================================

def send_enhanced_statistics_report():
    try:
        portfolio = get_enhanced_portfolio_status()
        
        uptime = datetime.now() - start_time
        hours = int(uptime.total_seconds() / 3600)
        minutes = int((uptime.total_seconds() % 3600) / 60)
        
        with statistics_lock:
            win_rate = (winning_trades / total_trades * 100) if total_trades > 0 else 0
            avg_profit = (total_profit / total_trades) if total_trades > 0 else 0
        
        message = f"""
{'━'*10}
💰 `총 {portfolio['total_assets']:,.0f}원` | `현금 {portfolio['krw_balance']:,.0f}원`
{'━'*10}

⏱ 가동`{hours}시간 {minutes}분` | 보유`{len(portfolio['coins'])}/{MAX_HOLDINGS}`
🎯 금일 매수`{daily_buy_count}` 매도`{daily_sell_count}`
📈 누적`{total_trades}거래` 승률`{win_rate:.0f}%` 평균`{avg_profit:+.2f}%`

⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
"""
        send_discord_message(message)
    except:
        pass


# ================================================================================
# SECTION 13: Risk Management
# ================================================================================

def check_market_condition():
    try:
        total_change, valid_count = 0.0, 0
        for ticker in FIXED_STABLE_COINS[:3]:
            df = get_candles(ticker, interval='15', count=2)
            if df is not None and len(df) >= 2:
                change = ((df.iloc[-1]['close'] - df.iloc[-2]['close']) / df.iloc[-2]['close']) * 100
                total_change += change
                valid_count += 1
        
        avg_change = total_change / valid_count if valid_count > 0 else 0
        return (avg_change > MARKET_BREAKER_THRESHOLD, avg_change)
    except:
        return True, 0.0


def check_daily_trade_limit():
    global daily_trade_count, last_reset_date
    today = datetime.now().date()
    if today != last_reset_date:
        daily_trade_count = 0
        last_reset_date = today
    return daily_trade_count < MAX_DAILY_TRADES


def check_consecutive_losses():
    global consecutive_losses, last_loss_time
    if consecutive_losses >= CONSECUTIVE_LOSS_LIMIT and last_loss_time:
        elapsed = (datetime.now() - last_loss_time).total_seconds() / 60
        if elapsed < COOLDOWN_AFTER_LOSS:
            return False
        consecutive_losses = 0
        last_loss_time = None
    return True


# ================================================================================
# SECTION 14: Trade Execution
# ================================================================================

def execute_buy(ticker, signal):
    global daily_trade_count, total_trades, daily_buy_count
    
    try:
        with trade_lock:
            reset_daily_counter()
            if daily_trade_count >= MAX_DAILY_TRADES:
                return False
            
            can_enter, _ = check_reentry_cooldown(ticker)
            if not can_enter:
                return False
            
            with held_coins_lock:
                if ticker in held_coins or len(held_coins) >= MAX_HOLDINGS:
                    return False
            
            try:
                total_assets = get_total_balance()
                krw_balance = upbit.get_balance("KRW")
            except:
                return False
            
            buy_amount = min(total_assets * POSITION_SIZE_RATIO, krw_balance * 0.9995)
            if buy_amount < 5000:
                return False
            
            print(f"{Colors.CYAN}[Buy] {ticker} 매수금액: {buy_amount:,.0f}원{Colors.ENDC}")
            
            if TEST_MODE:
                with held_coins_lock:
                    held_coins[ticker] = {
                        'buy_price': signal['entry_price'], 'buy_time': datetime.now(),
                        'buy_amount': buy_amount, 'peak_price': signal['entry_price'],
                        'peak_time': datetime.now(), 'buy_reason': signal['reason'],
                        'buy_mode': signal.get('mode', 'NORMAL')
                    }
                daily_trade_count += 1
                daily_buy_count += 1
                total_trades += 1
                send_buy_notification(ticker, signal, buy_amount, total_assets)
                return True
            
            result = upbit.buy_market_order(ticker, buy_amount)
            if result is None:
                return False
            
            time.sleep(1)
            
            balances = upbit.get_balances()
            coin_balance = next((b for b in balances if b['currency'] == ticker.split('-')[1]), None)
            if not coin_balance:
                return False
            
            actual_buy_price = float(coin_balance['avg_buy_price'])
            
            with held_coins_lock:
                held_coins[ticker] = {
                    'buy_price': actual_buy_price, 'buy_time': datetime.now(),
                    'buy_amount': buy_amount, 'peak_price': actual_buy_price,
                    'peak_time': datetime.now(), 'buy_reason': signal['reason'],
                    'buy_mode': signal.get('mode', 'NORMAL')
                }
            
            daily_trade_count += 1
            daily_buy_count += 1
            total_trades += 1
            
            print(f"{Colors.GREEN}[Buy Success] {ticker} {actual_buy_price:,.0f}원{Colors.ENDC}")
            send_buy_notification(ticker, signal, buy_amount, total_assets)
            return True
    except Exception as e:
        print(f"{Colors.RED}[Buy Error] {e}{Colors.ENDC}")
        return False


def execute_sell(ticker, signal):
    global daily_trade_count, total_trades, winning_trades, losing_trades, total_profit
    global consecutive_losses, last_loss_time, daily_sell_count, daily_winning_trades, daily_losing_trades
    
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
            
            if TEST_MODE:
                with held_coins_lock:
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
            
            balances = upbit.get_balances()
            coin_balance = next((b for b in balances if b['currency'] == ticker.split('-')[1]), None)
            
            if not coin_balance:
                with held_coins_lock:
                    if ticker in held_coins:
                        del held_coins[ticker]
                return False
            
            coin_amount = float(coin_balance['balance'])
            if coin_amount <= 0:
                with held_coins_lock:
                    if ticker in held_coins:
                        del held_coins[ticker]
                return False
            
            result = upbit.sell_market_order(ticker, coin_amount)
            if result is None:
                return False
            
            time.sleep(1)
            
            try:
                actual_sell_price = pyupbit.get_current_price(ticker) or sell_price
            except:
                actual_sell_price = sell_price
            
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
            
            print(f"{Colors.GREEN}[Sell Success] {ticker} {actual_profit_pct:+.2f}%{Colors.ENDC}")
            
            signal['profit_pct'] = actual_profit_pct
            signal['exit_price'] = actual_sell_price
            send_sell_notification(ticker, hold_info, signal, actual_profit_amount, hold_duration)
            return True
    except Exception as e:
        print(f"{Colors.RED}[Sell Error] {e}{Colors.ENDC}")
        return False


# ================================================================================
# SECTION 15: Initialization
# ================================================================================

def sync_held_coins_with_exchange():
    global held_coins
    
    print(f"{Colors.CYAN}[Init] 보유 코인 동기화 중...{Colors.ENDC}")
    
    try:
        balances = upbit.get_balances()
        synced_count = 0
        
        for bal in balances:
            currency = bal.get('currency', '')
            if currency == 'KRW':
                continue
            
            balance = float(bal.get('balance', 0))
            ticker = f"KRW-{currency}"
            
            if balance <= 0 or ticker not in FIXED_STABLE_COINS:
                continue
            
            avg_buy_price = float(bal.get('avg_buy_price', 0))
            if avg_buy_price <= 0:
                continue
            
            with held_coins_lock:
                held_coins[ticker] = {
                    'buy_price': avg_buy_price, 'buy_time': datetime.now(),
                    'buy_amount': balance * avg_buy_price, 'peak_price': avg_buy_price,
                    'peak_time': datetime.now(), 'buy_reason': 'EXISTING',
                    'buy_mode': 'SYNCED'
                }
            
            synced_count += 1
            print(f"{Colors.GREEN}  ✔ {ticker}: {balance:.4f}개 @ {avg_buy_price:,.0f}원{Colors.ENDC}")
        
        print(f"{Colors.GREEN}[Init] 동기화 완료: {synced_count}개{Colors.ENDC}")
        
        if synced_count > 0:
            send_discord_message(f"**🔄 동기화 완료:** `{synced_count}개` 코인")
        return True
    except Exception as e:
        print(f"{Colors.RED}[Init Error] {e}{Colors.ENDC}")
        return False


# ================================================================================
# SECTION 16: Thread Workers
# ================================================================================

def buy_thread_worker():
    print(f"{Colors.CYAN}[Thread 1] 매수 스레드 시작 ({BUY_THREAD_INTERVAL}초){Colors.ENDC}")
    
    iteration = 0
    
    while not stop_event.is_set():
        try:
            iteration += 1
            
            if not check_consecutive_losses() or not check_market_condition()[0] or not check_daily_trade_limit():
                time.sleep(BUY_THREAD_INTERVAL)
                continue
            
            with held_coins_lock:
                if len(held_coins) >= MAX_HOLDINGS:
                    time.sleep(BUY_THREAD_INTERVAL)
                    continue
            
            for ticker in FIXED_STABLE_COINS:
                if stop_event.is_set():
                    return
                
                with held_coins_lock:
                    if ticker in held_coins:
                        continue
                
                can_enter, _ = check_reentry_cooldown(ticker)
                if not can_enter:
                    continue
                
                df_15m = get_candles(ticker, interval='15', count=50)
                if df_15m is None or len(df_15m) < 20:
                    continue
                
                df_15m = add_indicators(df_15m)
                if df_15m is None:
                    continue
                
                buy_signal = momentum_wave_buy_signal(df_15m, ticker)
                
                if buy_signal['signal']:
                    coin_name = ticker.replace('KRW-', '')
                    mode = buy_signal.get('mode', 'UNKNOWN')
                    score = buy_signal.get('score', 0)
                    
                    print(f"\n{Colors.CYAN}{'='*50}")
                    print(f"[BUY] {coin_name} [{mode}] {score:.0f}점")
                    print(f"  {buy_signal['reason'][:60]}")
                    print(f"{'='*50}{Colors.ENDC}")
                    
                    execute_buy(ticker, buy_signal)
                    time.sleep(2)
                    
                    with held_coins_lock:
                        if len(held_coins) >= MAX_HOLDINGS:
                            break
                
                elif DEBUG_MODE and iteration % 6 == 0 and buy_signal.get('score', 0) >= 40:
                    coin_name = ticker.replace('KRW-', '')
                    print(f"{Colors.YELLOW}[Check] {coin_name}: {buy_signal['score']:.0f}점{Colors.ENDC}")
            
            time.sleep(BUY_THREAD_INTERVAL)
        except Exception as e:
            print(f"{Colors.RED}[BUY Error] {e}{Colors.ENDC}")
            time.sleep(BUY_THREAD_INTERVAL)
    
    print(f"{Colors.CYAN}[Thread 1] 매수 스레드 종료{Colors.ENDC}")


def sell_thread_worker():
    print(f"{Colors.YELLOW}[Thread 2] 매도 스레드 시작 ({SELL_THREAD_INTERVAL}초){Colors.ENDC}")
    
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
                    held_info = held_coins[ticker].copy()
                    held_info['ticker'] = ticker
                    buy_price = held_info['buy_price']
                    buy_time = held_info.get('buy_time', datetime.now())
                
                sell_signal = momentum_wave_sell_signal(df_15m, buy_price, buy_time, held_info)
                
                if sell_signal['signal']:
                    profit_pct = sell_signal['profit_pct']
                    emoji = "📈" if profit_pct > 0 else "📉"
                    
                    print(f"\n{Colors.YELLOW}{'='*50}")
                    print(f"[SELL] {ticker.replace('KRW-', '')} {emoji} {profit_pct:+.2f}%")
                    print(f"  {sell_signal['reason']}")
                    print(f"{'='*50}{Colors.ENDC}")
                    
                    execute_sell(ticker, sell_signal)
                    time.sleep(2)
                
                elif DEBUG_MODE and iteration % 12 == 0:
                    profit_pct = sell_signal['profit_pct']
                    coin_name = ticker.replace('KRW-', '')
                    hold_min = (datetime.now() - buy_time).total_seconds() / 60
                    print(f"{Colors.MAGENTA}[Hold] {coin_name}: {profit_pct:+.2f}% ({hold_min:.0f}분){Colors.ENDC}")
            
            time.sleep(SELL_THREAD_INTERVAL)
        except Exception as e:
            print(f"{Colors.RED}[SELL Error] {e}{Colors.ENDC}")
            time.sleep(SELL_THREAD_INTERVAL)
    
    print(f"{Colors.YELLOW}[Thread 2] 매도 스레드 종료{Colors.ENDC}")


def monitor_thread_worker():
    print(f"{Colors.MAGENTA}[Thread 3] 모니터 스레드 시작 ({MONITOR_THREAD_INTERVAL}초){Colors.ENDC}")
    
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
            
            print(f"\n{Colors.MAGENTA}{'='*50}")
            print(f"[Monitor] #{iteration} | {current_time.strftime('%H:%M:%S')}")
            print(f"  보유: {current_holdings}/{MAX_HOLDINGS} | 거래: {total_trades}회 | 승률: {win_rate:.1f}%")
            
            with held_coins_lock:
                for ticker, info in held_coins.items():
                    try:
                        current_price = pyupbit.get_current_price(ticker)
                        if current_price:
                            profit = ((current_price - info['buy_price']) / info['buy_price']) * 100
                            duration = format_duration(current_time - info['buy_time'])
                            mode = info.get('buy_mode', '-')
                            print(f"  - {ticker.replace('KRW-', '')} [{mode}]: {profit:+.2f}% ({duration})")
                    except:
                        pass
            
            print(f"{'='*50}{Colors.ENDC}\n")
            
            # 매시각 보고
            elapsed = (current_time - last_report_time).total_seconds()
            if elapsed >= 3540 and 0 <= current_time.minute <= 3:
                send_enhanced_statistics_report()
                last_report_time = current_time
            
            time.sleep(MONITOR_THREAD_INTERVAL)
        except Exception as e:
            print(f"{Colors.RED}[Monitor Error] {e}{Colors.ENDC}")
            time.sleep(MONITOR_THREAD_INTERVAL)
    
    print(f"{Colors.MAGENTA}[Thread 3] 모니터 스레드 종료{Colors.ENDC}")


# ================================================================================
# SECTION 17: Main Function
# ================================================================================

def main():
    global upbit
    
    try:
        upbit = pyupbit.Upbit(ACCESS_KEY, SECRET_KEY)
        print(f"{Colors.GREEN}[Init] Upbit API 연결 완료{Colors.ENDC}\n")
    except Exception as e:
        print(f"{Colors.RED}[Error] Upbit 연결 실패: {e}{Colors.ENDC}")
        return
    
    sync_held_coins_with_exchange()
    
    with held_coins_lock:
        synced_coins = len(held_coins)
    
    send_discord_message(f"""
**🚀 봇 시작 - MOMENTUM WAVE v8.0**

모드: `{'TEST' if TEST_MODE else 'LIVE'}`
코인: `{len(FIXED_STABLE_COINS)}개` | 최대보유: `{MAX_HOLDINGS}개`
기존보유: `{synced_coins}개`

**전략:**
- 매수: 기울기 반전 | 눌림목 | 모멘텀 폭발
- 매도: 적응형 목표 + 트레일링
- 손절: {STOP_LOSS_DEFAULT}%

⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
""")
    
    buy_thread = threading.Thread(target=buy_thread_worker, daemon=True)
    sell_thread = threading.Thread(target=sell_thread_worker, daemon=True)
    monitor_thread = threading.Thread(target=monitor_thread_worker, daemon=True)
    
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
        print(f"\n{Colors.RED}[Exit] 종료 중...{Colors.ENDC}")
        stop_event.set()
        
        buy_thread.join(timeout=10)
        sell_thread.join(timeout=10)
        monitor_thread.join(timeout=10)
        
        runtime = format_duration(datetime.now() - start_time)
        with statistics_lock:
            final_win_rate = (winning_trades / total_trades * 100) if total_trades > 0 else 0
        
        send_discord_message(f"**🛑 봇 종료**\n가동: `{runtime}` | 거래: `{total_trades}` | 승률: `{final_win_rate:.1f}%`")
        print(f"{Colors.GREEN}[Exit] 완료{Colors.ENDC}")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"{Colors.RED}[Fatal] {traceback.format_exc()}{Colors.ENDC}")
        send_error_notification("Fatal Error", str(e))