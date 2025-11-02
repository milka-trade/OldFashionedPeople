import os
from dotenv import load_dotenv
load_dotenv()
import pyupbit
import pandas as pd
import json
from datetime import datetime, timedelta
import time
import requests
import threading
import numpy as np
from collections import deque

# ===========================
# 설정
# ===========================
DEBUG_MODE = True
TEST_MODE = False

STRATEGIC_COINS = [
    "KRW-BTC", "KRW-ETH", "KRW-XRP", "KRW-SOL",
    "KRW-ADA", "KRW-LINK", "KRW-BCH", "KRW-XLM"
]

# ===========================
# 글로벌 변수
# ===========================
DISCORD_WEBHOOK_URL = os.getenv("discord_webhook")
ACCESS_KEY = os.getenv("UPBIT_ACCESS_KEY")
SECRET_KEY = os.getenv("UPBIT_SECRET_KEY")

upbit = None
held_coins = {}
trade_history = {
    'bottom_reversal': {'wins': 0, 'losses': 0, 'total_profit': 0},
    'breakout': {'wins': 0, 'losses': 0, 'total_profit': 0},
    'reentry': {'wins': 0, 'losses': 0, 'total_profit': 0},
    'momentum': {'wins': 0, 'losses': 0, 'total_profit': 0},
    'v_reversal': {'wins': 0, 'losses': 0, 'total_profit': 0}
}
recent_trades = deque(maxlen=10)
start_time = datetime.now()
discord_stats = {
    'total_attempts': 0,
    'success': 0,
    'failures': 0,
    'last_success': None,
    'last_failure': None
}

# 매도 실패 추적 (v8.5 신규)
sell_failure_tracker = {}

# ===========================
# Discord 알림 (v8.4와 동일)
# ===========================
def send_discord_message(content, max_retries=3, notify_failure=True):
    """디스코드 웹훅으로 메시지 전송"""
    global discord_stats
    
    discord_stats['total_attempts'] += 1
    
    if not DISCORD_WEBHOOK_URL:
        if discord_stats['total_attempts'] == 1:
            print("\n⚠️  경고: Discord 알림 비활성화")
        return False
    
    for attempt in range(max_retries):
        try:
            message = {"content": content}
            response = requests.post(DISCORD_WEBHOOK_URL, json=message, timeout=10)
            
            if response.status_code == 204:
                discord_stats['success'] += 1
                discord_stats['last_success'] = datetime.now()
                return True
            else:
                if attempt == max_retries - 1:
                    discord_stats['failures'] += 1
                    discord_stats['last_failure'] = datetime.now()
                time.sleep(1 * (attempt + 1))
                
        except Exception as e:
            if attempt == max_retries - 1:
                discord_stats['failures'] += 1
                discord_stats['last_failure'] = datetime.now()
                if DEBUG_MODE:
                    print(f"   ❌ Discord 알림 오류: {e}")
            time.sleep(1 * (attempt + 1))
    
    return False

# ===========================
# 초기화 (v8.4와 동일, 간략화)
# ===========================
def initialize_and_validate():
    """프로그램 초기화 및 검증"""
    global upbit
    
    print("\n" + "="*60)
    print("🚀 Fortress Hunter v8.5 초기화 중...")
    print("="*60)
    
    if not ACCESS_KEY or not SECRET_KEY:
        print("❌ 오류: API 키 미설정")
        return False
    
    try:
        upbit = pyupbit.Upbit(ACCESS_KEY, SECRET_KEY)
        krw_balance = upbit.get_balance("KRW")
        print(f"✅ 업비트 연결 성공 (잔고: {krw_balance:,.0f}원)")
    except Exception as e:
        print(f"❌ 오류: {e}")
        return False
    
    print("✅ 초기화 완료!")
    print("="*60 + "\n")
    return True

# ===========================
# 데이터 가져오기
# ===========================
def get_current_price(ticker):
    """현재 가격 조회"""
    try:
        return pyupbit.get_orderbook(ticker=ticker)["orderbook_units"][0]["ask_price"]
    except:
        return None

def get_ohlcv_with_retry(ticker, interval="minute1", count=200, max_retries=3):
    """OHLCV 데이터 가져오기"""
    for attempt in range(max_retries):
        try:
            df = pyupbit.get_ohlcv(ticker, interval=interval, count=count)
            if df is not None and len(df) > 0:
                return df
            time.sleep(0.1)
        except:
            time.sleep(0.2)
    return None

# ===========================
# 기술적 지표 계산
# ===========================
def calculate_rsi(series, period=14):
    delta = series.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs))

def calculate_ema(series, period):
    return series.ewm(span=period, adjust=False).mean()

def calculate_macd(series, fast=12, slow=26, signal=9):
    ema_fast = calculate_ema(series, fast)
    ema_slow = calculate_ema(series, slow)
    macd = ema_fast - ema_slow
    macd_signal = calculate_ema(macd, signal)
    macd_hist = macd - macd_signal
    return macd, macd_signal, macd_hist

def calculate_bollinger_bands(series, period=20, std=2):
    middle = series.rolling(window=period).mean()
    std_dev = series.rolling(window=period).std()
    upper = middle + (std_dev * std)
    lower = middle - (std_dev * std)
    width = (upper - lower) / middle * 100
    return upper, middle, lower, width

def calculate_stochastic_rsi(series, period=14, smooth_k=3, smooth_d=3):
    rsi = calculate_rsi(series, period)
    stoch_rsi = (rsi - rsi.rolling(window=period).min()) / (rsi.rolling(window=period).max() - rsi.rolling(window=period).min())
    stoch_k = stoch_rsi.rolling(window=smooth_k).mean() * 100
    stoch_d = stoch_k.rolling(window=smooth_d).mean()
    return stoch_k, stoch_d

def calculate_indicators(df):
    if df is None or len(df) < 20:
        return None
    
    df['rsi'] = calculate_rsi(df['close'], 14)
    df['macd'], df['macd_signal'], df['macd_hist'] = calculate_macd(df['close'])
    df['bb_upper'], df['bb_middle'], df['bb_lower'], df['bb_width'] = calculate_bollinger_bands(df['close'])
    df['stoch_k'], df['stoch_d'] = calculate_stochastic_rsi(df['close'])
    df['volume_ma'] = df['volume'].rolling(window=20).mean()
    df['ema_9'] = calculate_ema(df['close'], 9)
    df['ema_21'] = calculate_ema(df['close'], 21)
    
    return df

# ===========================
# 매수 관련 함수들 (v8.4와 동일, 간략화)
# ===========================
def detect_bottom_reversal_pattern(df_1m, df_3m, df_5m, df_15m):
    score = 0
    reasons = []
    if df_15m is None or df_5m is None or len(df_15m) < 3 or len(df_5m) < 3:
        return score, reasons
    
    current_15m = df_15m.iloc[-1]
    current_5m = df_5m.iloc[-1]
    prev_5m = df_5m.iloc[-2]
    
    if pd.notna(current_15m['bb_lower']):
        bb_position = (current_15m['close'] - current_15m['bb_lower']) / (current_15m['bb_upper'] - current_15m['bb_lower'])
        if bb_position < 0.3:
            score += 15
            reasons.append(f"15분봉 BB하단 ({bb_position*100:.1f}%)")
            if current_15m['rsi'] < 35:
                score += 10
                reasons.append(f"RSI과매도 ({current_15m['rsi']:.1f})")
    
    if pd.notna(current_5m['bb_lower']):
        if prev_5m['close'] <= prev_5m['bb_lower'] and current_5m['close'] > current_5m['bb_lower']:
            score += 15
            reasons.append("BB하단 돌파")
    
    return score, reasons

def detect_breakout_pattern(df_1m, df_3m, df_5m, df_15m):
    score = 0
    reasons = []
    if df_5m is None or len(df_5m) < 20:
        return score, reasons
    
    current = df_5m.iloc[-1]
    recent_high = df_5m['high'].iloc[-10:].max()
    recent_low = df_5m['low'].iloc[-10:].min()
    range_pct = (recent_high - recent_low) / recent_low * 100
    
    if range_pct < 3.0 and current['close'] > recent_high:
        score += 20
        reasons.append(f"횡보돌파 ({range_pct:.2f}%)")
        if pd.notna(current['volume_ma']):
            volume_ratio = current['volume'] / current['volume_ma']
            if volume_ratio > 1.5:
                score += 15
                reasons.append(f"거래량급증 ({volume_ratio:.1f}배)")
    
    return score, reasons

def detect_reentry_pattern(df_1m, df_3m, df_5m, df_15m):
    score = 0
    reasons = []
    if df_15m is None or df_5m is None or len(df_15m) < 20:
        return score, reasons
    
    current_15m = df_15m.iloc[-1]
    current_5m = df_5m.iloc[-1]
    recent_high_15m = df_15m['high'].iloc[-10:-5].max()
    
    if recent_high_15m > 0:
        pullback_pct = (recent_high_15m - current_15m['close']) / recent_high_15m * 100
        if 3.0 < pullback_pct < 7.0:
            score += 15
            reasons.append(f"재진입 (-{pullback_pct:.2f}%)")
    
    return score, reasons

def detect_momentum_pattern(df_1m, df_3m, df_5m, df_15m):
    score = 0
    reasons = []
    if df_5m is None or len(df_5m) < 10:
        return score, reasons
    
    last_3 = df_5m.iloc[-3:]
    if all(last_3['close'] > last_3['open']):
        score += 15
        reasons.append("3연속 양봉")
    
    return score, reasons

def detect_v_reversal_pattern(df_1m, df_3m, df_5m, df_15m):
    score = 0
    reasons = []
    if df_1m is None or len(df_1m) < 10:
        return score, reasons
    
    current_1m = df_1m.iloc[-1]
    recent_5 = df_1m.iloc[-5:]
    max_drop = 0
    
    for i in range(len(recent_5) - 1):
        drop = (recent_5.iloc[i]['close'] - recent_5.iloc[i+1]['low']) / recent_5.iloc[i]['close'] * 100
        max_drop = max(max_drop, drop)
    
    if 1.0 < max_drop < 3.0 and current_1m['close'] > current_1m['open']:
        score += 20
        reasons.append(f"V자반등 ({max_drop:.2f}%)")
    
    return score, reasons

def calculate_trend_strength(df_5m, df_15m, pattern_scores):
    strength = 0
    if df_5m is None or df_15m is None:
        return 50
    
    current_5m = df_5m.iloc[-1]
    if pd.notna(current_5m['volume_ma']) and current_5m['volume_ma'] > 0:
        volume_ratio = current_5m['volume'] / current_5m['volume_ma']
        strength += min(volume_ratio * 10, 25)
    
    recent_5 = df_5m.iloc[-5:]
    price_change = (recent_5.iloc[-1]['close'] - recent_5.iloc[0]['close']) / recent_5.iloc[0]['close'] * 100
    strength += min(abs(price_change) * 5, 25)
    
    return min(strength, 100)

def calculate_win_rate(pattern_name):
    if pattern_name not in trade_history:
        return 0.5
    data = trade_history[pattern_name]
    total = data['wins'] + data['losses']
    if total == 0:
        return 0.5
    return data['wins'] / total

def calculate_expected_value(pattern_scores, current_price, volatility):
    best_pattern = max(pattern_scores, key=pattern_scores.get)
    best_score = pattern_scores[best_pattern]
    
    if best_score < 50:
        return 0, best_pattern, 0
    
    win_rate = calculate_win_rate(best_pattern)
    expected_profit = 1.5 * (best_score / 70)
    expected_loss = 0.7
    expected_value = (win_rate * expected_profit) - ((1 - win_rate) * expected_loss)
    
    return expected_value, best_pattern, win_rate

def analyze_buy_signal(ticker):
    """매수 신호 분석 (간략화)"""
    try:
        df_1m = get_ohlcv_with_retry(ticker, "minute1", 200)
        time.sleep(0.1)
        df_3m = get_ohlcv_with_retry(ticker, "minute3", 200)
        time.sleep(0.1)
        df_5m = get_ohlcv_with_retry(ticker, "minute5", 200)
        time.sleep(0.1)
        df_15m = get_ohlcv_with_retry(ticker, "minute15", 200)
        
        if df_1m is None or df_5m is None:
            return None
        
        df_1m = calculate_indicators(df_1m)
        df_3m = calculate_indicators(df_3m) if df_3m is not None else None
        df_5m = calculate_indicators(df_5m)
        df_15m = calculate_indicators(df_15m) if df_15m is not None else None
        
        if df_1m is None or df_5m is None:
            return None
        
        pattern_scores = {}
        all_reasons = []
        
        score1, reasons1 = detect_bottom_reversal_pattern(df_1m, df_3m, df_5m, df_15m)
        pattern_scores['bottom_reversal'] = score1
        if score1 > 0:
            all_reasons.append(f"[바닥반등 {score1}점] " + ", ".join(reasons1))
        
        score2, reasons2 = detect_breakout_pattern(df_1m, df_3m, df_5m, df_15m)
        pattern_scores['breakout'] = score2
        if score2 > 0:
            all_reasons.append(f"[돌파 {score2}점] " + ", ".join(reasons2))
        
        score3, reasons3 = detect_reentry_pattern(df_1m, df_3m, df_5m, df_15m)
        pattern_scores['reentry'] = score3
        if score3 > 0:
            all_reasons.append(f"[재진입 {score3}점] " + ", ".join(reasons3))
        
        score4, reasons4 = detect_momentum_pattern(df_1m, df_3m, df_5m, df_15m)
        pattern_scores['momentum'] = score4
        if score4 > 0:
            all_reasons.append(f"[모멘텀 {score4}점] " + ", ".join(reasons4))
        
        score5, reasons5 = detect_v_reversal_pattern(df_1m, df_3m, df_5m, df_15m)
        pattern_scores['v_reversal'] = score5
        if score5 > 0:
            all_reasons.append(f"[V자반등 {score5}점] " + ", ".join(reasons5))
        
        total_score = sum(pattern_scores.values())
        current_price = df_5m.iloc[-1]['close']
        bb_width = df_5m.iloc[-1]['bb_width'] if pd.notna(df_5m.iloc[-1]['bb_width']) else 5.0
        
        trend_strength = calculate_trend_strength(df_5m, df_15m, pattern_scores)
        expected_value, best_pattern, win_rate = calculate_expected_value(pattern_scores, current_price, bb_width)
        
        base_threshold = 40 if TEST_MODE else 60
        should_buy = total_score >= base_threshold and expected_value >= (0.5 if TEST_MODE else 0.8)
        
        result = {
            'ticker': ticker,
            'total_score': total_score,
            'best_pattern': best_pattern,
            'expected_value': expected_value,
            'win_rate': win_rate,
            'trend_strength': trend_strength,
            'threshold': base_threshold,
            'current_price': current_price,
            'reasons': all_reasons,
            'should_buy': should_buy
        }
        
        if DEBUG_MODE and should_buy:
            print(f"   🟢 {ticker}: {total_score}점 | EV {expected_value:.2f}")
        
        return result
        
    except Exception as e:
        if DEBUG_MODE:
            print(f"   ❌ {ticker}: {e}")
        return None

def execute_buy(ticker, analysis_result):
    """매수 실행"""
    try:
        krw_balance = upbit.get_balance("KRW")
        if krw_balance < 5500:
            return False
        
        position_size = min(50000, krw_balance - 5000, 200000)
        result = upbit.buy_market_order(ticker, position_size)
        
        if result:
            time.sleep(0.5)
            coin_symbol = ticker.split('-')[1]
            coin_balance = upbit.get_balance(coin_symbol)
            
            if coin_balance > 0:
                avg_price = upbit.get_avg_buy_price(coin_symbol)
                
                held_coins[ticker] = {
                    'buy_time': datetime.now(),
                    'buy_price': avg_price,
                    'amount': coin_balance,
                    'pattern': analysis_result['best_pattern'],
                    'expected_profit': analysis_result['expected_value'],
                    'trend_strength': analysis_result['trend_strength'],
                    'peak_price': avg_price,
                    'peak_time': datetime.now(),
                    'stage_1_sold': False,
                    'stage_2_sold': False,
                    'initial_amount': coin_balance,
                    'last_check_time': datetime.now()  # v8.5 신규
                }
                
                message = f"""
🔵 **매수 체결** 
{ticker} | {avg_price:,.0f}원 | {coin_balance:.8f}
패턴: {analysis_result['best_pattern']} | {analysis_result['total_score']}점
"""
                send_discord_message(message)
                print(f"✅ [매수] {ticker} {avg_price:,.0f}원")
                return True
        
        return False
        
    except Exception as e:
        print(f"❌ [매수 오류] {ticker}: {e}")
        return False

# ===========================
# 🔥 개선된 매도 로직 (v8.5)
# ===========================

def update_peak_price_continuously(ticker, hold_info):
    """
    v8.5 신규: 고점 가격을 지속적으로 갱신
    메인 루프 대기 시간 동안에도 고점을 추적
    """
    try:
        current_price = get_current_price(ticker)
        if current_price and current_price > hold_info['peak_price']:
            hold_info['peak_price'] = current_price
            hold_info['peak_time'] = datetime.now()
            
            if DEBUG_MODE:
                profit_rate = (current_price - hold_info['buy_price']) / hold_info['buy_price'] * 100
                print(f"   📈 {ticker} 신고점: {profit_rate:+.2f}%")
            
            return True
        return False
    except:
        return False

def calculate_bearish_score(df_1m, df_5m, df_15m, profit_rate, hold_info):
    """약세 전환 점수 계산"""
    bearish_score = 0
    bearish_reasons = []
    
    if df_1m is None or df_5m is None:
        return 0, []
    
    current_1m = df_1m.iloc[-1]
    prev_1m = df_1m.iloc[-2]
    current_5m = df_5m.iloc[-1]
    prev_5m = df_5m.iloc[-2]
    
    # 손실 점수
    if profit_rate <= -2.0:
        bearish_score += 5
        bearish_reasons.append(f"큰손실 ({profit_rate:.2f}%)")
    elif profit_rate <= -1.5:
        bearish_score += 3
        bearish_reasons.append(f"손실 ({profit_rate:.2f}%)")
    
    # 거래량 + 하락
    if pd.notna(current_5m['volume_ma']) and current_5m['volume_ma'] > 0:
        volume_ratio = current_5m['volume'] / current_5m['volume_ma']
        if volume_ratio > 1.5 and current_5m['close'] < current_5m['open']:
            bearish_score += 2
            bearish_reasons.append("공포매도")
    
    # RSI 급락
    if pd.notna(current_5m['rsi']) and pd.notna(prev_5m['rsi']):
        rsi_drop = prev_5m['rsi'] - current_5m['rsi']
        if rsi_drop > 10 and current_5m['rsi'] < 40:
            bearish_score += 2
            bearish_reasons.append(f"RSI급락 ({current_5m['rsi']:.1f})")
    
    # MACD 데드크로스
    if pd.notna(current_5m['macd']) and pd.notna(current_5m['macd_signal']):
        if current_5m['macd'] < current_5m['macd_signal'] and prev_5m['macd'] >= prev_5m['macd_signal']:
            bearish_score += 2
            bearish_reasons.append("MACD데드크로스")
    
    # 연속 음봉
    last_2_5m = df_5m.iloc[-2:]
    if all(last_2_5m['close'] < last_2_5m['open']):
        bearish_score += 2
        bearish_reasons.append("연속음봉")
    
    # BB 하단 이탈
    if pd.notna(current_5m['bb_lower']):
        if current_5m['close'] < current_5m['bb_lower'] and prev_5m['close'] < prev_5m['bb_lower']:
            bearish_score += 2
            bearish_reasons.append("BB하단이탈")
    
    return bearish_score, bearish_reasons

def should_stop_loss(ticker, hold_info, df_1m, df_5m, df_15m, profit_rate):
    """지능형 손절 판단"""
    
    # 절대 한계선: -2.5%
    if profit_rate <= -2.5:
        return True, f"절대한계선 손절 ({profit_rate:.2f}%)"
    
    bearish_score, bearish_reasons = calculate_bearish_score(
        df_1m, df_5m, df_15m, profit_rate, hold_info
    )
    
    trend_strength = hold_info.get('trend_strength', 50)
    
    if trend_strength >= 80:
        threshold = 10
    elif trend_strength >= 65:
        threshold = 8
    else:
        threshold = 6
    
    hold_minutes = (datetime.now() - hold_info['buy_time']).total_seconds() / 60
    
    if hold_minutes < 5:
        bearish_score -= 2
    elif hold_minutes > 30:
        bearish_score += 1
    
    if bearish_score >= threshold:
        reason = f"추세전환 (약세 {bearish_score}/{threshold}점: {', '.join(bearish_reasons[:2])}, {profit_rate:.2f}%)"
        return True, reason
    
    return False, None

def detect_sideways_exhaustion(df_5m, df_15m):
    """횡보/에너지 소진 감지"""
    if df_5m is None or len(df_5m) < 20:
        return False, []
    
    current_5m = df_5m.iloc[-1]
    recent_10 = df_5m.iloc[-10:]
    exhaustion_signals = []
    
    # 가격 횡보
    recent_high = recent_10['high'].max()
    recent_low = recent_10['low'].min()
    price_range = (recent_high - recent_low) / recent_low * 100
    
    if price_range < 0.5:
        exhaustion_signals.append(f"횡보 ({price_range:.2f}%)")
    
    # 거래량 감소
    recent_volumes = recent_10['volume'].iloc[-5:]
    if all(recent_volumes.diff().dropna() < 0) and pd.notna(current_5m['volume_ma']):
        if current_5m['volume'] < current_5m['volume_ma'] * 0.6:
            exhaustion_signals.append("거래량감소")
    
    # BB 수축
    if pd.notna(current_5m['bb_width']) and current_5m['bb_width'] < 2.5:
        exhaustion_signals.append(f"변동성소멸 ({current_5m['bb_width']:.2f}%)")
    
    return len(exhaustion_signals) >= 2, exhaustion_signals

def analyze_sell_signal_advanced(ticker, hold_info):
    """
    v8.5 개선된 매도 신호 분석
    
    개선사항:
    1. 실시간 가격 체크 강화
    2. 매도 우선순위 명확화
    3. 잔고 검증 추가
    4. 오류 처리 강화
    """
    try:
        # 1. 현재 가격 조회 (재시도 로직 포함)
        current_price = None
        for attempt in range(3):
            current_price = get_current_price(ticker)
            if current_price:
                break
            time.sleep(0.2)
        
        if current_price is None:
            print(f"   ⚠️  {ticker}: 가격 조회 실패 (매도 보류)")
            return False, "가격 조회 실패 (안전)", 0.0
        
        buy_price = hold_info['buy_price']
        profit_rate = (current_price - buy_price) / buy_price * 100
        hold_minutes = (datetime.now() - hold_info['buy_time']).total_seconds() / 60
        
        # 2. 고점 갱신 (실시간)
        if current_price > hold_info['peak_price']:
            hold_info['peak_price'] = current_price
            hold_info['peak_time'] = datetime.now()
        
        peak_profit = (hold_info['peak_price'] - buy_price) / buy_price * 100
        drawdown_from_peak = (hold_info['peak_price'] - current_price) / hold_info['peak_price'] * 100
        
        # 3. 데이터 가져오기 (재시도 로직)
        df_1m = get_ohlcv_with_retry(ticker, "minute1", 100)
        df_5m = get_ohlcv_with_retry(ticker, "minute5", 100)
        df_15m = get_ohlcv_with_retry(ticker, "minute15", 100)
        
        if df_1m is None or df_5m is None:
            print(f"   ⚠️  {ticker}: 데이터 조회 실패 (매도 보류)")
            return False, "데이터 조회 실패 (안전)", 0.0
        
        df_1m = calculate_indicators(df_1m)
        df_5m = calculate_indicators(df_5m)
        df_15m = calculate_indicators(df_15m) if df_15m is not None else None
        
        if df_1m is None or df_5m is None:
            return False, "지표 계산 실패 (안전)", 0.0
        
        current_1m = df_1m.iloc[-1]
        current_5m = df_5m.iloc[-1]
        prev_1m = df_1m.iloc[-2]
        prev_5m = df_5m.iloc[-2]
        
        # ===========================
        # 매도 결정 로직 (우선순위 순서)
        # ===========================
        
        # 📍 우선순위 1: 긴급 손절 (최우선)
        if profit_rate <= -2.5:
            return True, f"🚨 긴급손절 ({profit_rate:.2f}%)", 1.0
        
        # 📍 우선순위 2: 지능형 손절
        should_cut, cut_reason = should_stop_loss(ticker, hold_info, df_1m, df_5m, df_15m, profit_rate)
        if should_cut:
            return True, f"🔴 {cut_reason}", 1.0
        
        # 📍 우선순위 3: 수익 실현 목표 (분할 매도)
        trend_strength = hold_info.get('trend_strength', 50)
        
        if trend_strength >= 80:
            stage_1_target = 3.0
            stage_2_target = 5.0
        elif trend_strength >= 65:
            stage_1_target = 2.5
            stage_2_target = 4.0
        elif trend_strength >= 50:
            stage_1_target = 2.0
            stage_2_target = 3.0
        else:
            stage_1_target = 1.5
            stage_2_target = 2.5
        
        # 1단계 목표
        if not hold_info['stage_1_sold'] and profit_rate >= stage_1_target:
            return True, f"🎯 1단계 목표 (+{profit_rate:.2f}%, 30%매도)", 0.3
        
        # 2단계 목표
        if hold_info['stage_1_sold'] and not hold_info['stage_2_sold'] and profit_rate >= stage_2_target:
            return True, f"🎯 2단계 목표 (+{profit_rate:.2f}%, 40%매도)", 0.4
        
        # 📍 우선순위 4: 적응형 추적 손절
        if hold_info['stage_1_sold'] and hold_info['stage_2_sold']:
            time_since_peak = (datetime.now() - hold_info['peak_time']).total_seconds() / 60
            
            if time_since_peak < 5:
                trailing_stop = 2.0
            elif time_since_peak < 15:
                trailing_stop = 1.5
            else:
                trailing_stop = 1.0
            
            if drawdown_from_peak >= trailing_stop:
                return True, f"📉 추적손절 (고점대비 -{drawdown_from_peak:.2f}%, +{profit_rate:.2f}%)", 1.0
        
        # 📍 우선순위 5: 고점 대비 급락 (v8.5 신규)
        # 고점 대비 3% 이상 급락 시 즉시 매도
        if peak_profit > 1.0 and drawdown_from_peak >= 3.0:
            return True, f"⚡ 고점급락 (고점 {peak_profit:.2f}% → 현재 {profit_rate:.2f}%)", 1.0
        
        # 📍 우선순위 6: 다중 약세 전환 감지
        if profit_rate > 0.5:
            bearish_signals = 0
            bearish_reasons = []
            
            if current_1m['rsi'] > 70 and current_1m['close'] < current_1m['open']:
                bearish_signals += 1
                bearish_reasons.append("1분과매수음봉")
            
            if pd.notna(current_1m['macd']) and pd.notna(current_1m['macd_signal']):
                if current_1m['macd'] < current_1m['macd_signal'] and prev_1m['macd'] >= prev_1m['macd_signal']:
                    bearish_signals += 1
                    bearish_reasons.append("1분MACD데드크로스")
            
            if current_5m['rsi'] > 70:
                bearish_signals += 1
                bearish_reasons.append("5분과매수")
            
            if pd.notna(current_5m['stoch_k']) and pd.notna(current_5m['stoch_d']):
                if current_5m['stoch_k'] < current_5m['stoch_d'] and prev_5m['stoch_k'] >= prev_5m['stoch_d']:
                    if current_5m['stoch_k'] > 70:
                        bearish_signals += 2
                        bearish_reasons.append("5분Stoch데드크로스")
            
            if pd.notna(current_5m['bb_upper']):
                if prev_5m['close'] > prev_5m['bb_upper'] and current_5m['close'] < current_5m['bb_upper']:
                    bearish_signals += 1
                    bearish_reasons.append("BB상단이탈")
            
            if bearish_signals >= 3:
                sell_ratio = 1.0 if not hold_info['stage_1_sold'] else 1.0
                return True, f"📊 다중약세 ({', '.join(bearish_reasons[:2])}, +{profit_rate:.2f}%)", sell_ratio
        
        # 📍 우선순위 7: 에너지 소진
        if profit_rate > 0.3:
            is_exhausted, exhaustion_signals = detect_sideways_exhaustion(df_5m, df_15m)
            
            if is_exhausted:
                return True, f"💤 에너지소진 ({', '.join(exhaustion_signals[:2])}, +{profit_rate:.2f}%)", 1.0
        
        # 📍 우선순위 8: 거래량 급감 경고
        if profit_rate > stage_2_target:
            if pd.notna(current_5m['volume_ma']):
                if current_5m['volume'] < current_5m['volume_ma'] * 0.5:
                    return True, f"📉 급등후거래량급감 (+{profit_rate:.2f}%)", 1.0
        
        # 📍 우선순위 9: 장시간 보유 + 미미한 수익 (v8.5 신규)
        if hold_minutes > 120 and 0 < profit_rate < 0.5:
            return True, f"⏰ 장시간보유청산 ({hold_minutes:.0f}분, +{profit_rate:.2f}%)", 1.0
        
        # 보유 계속
        status_parts = [f"{profit_rate:+.2f}%"]
        if hold_info['stage_1_sold']:
            status_parts.append("1단계✓")
        if hold_info['stage_2_sold']:
            status_parts.append("2단계✓")
        if peak_profit > profit_rate:
            status_parts.append(f"고점{peak_profit:.2f}%")
        status_parts.append(f"{hold_minutes:.0f}분")
        
        # 마지막 체크 시간 업데이트
        hold_info['last_check_time'] = datetime.now()
        
        return False, f"⏳ 보유 ({' | '.join(status_parts)})", 0.0
        
    except Exception as e:
        print(f"❌ [매도분석 오류] {ticker}: {e}")
        # 오류 발생 시 안전하게 보유 유지
        return False, f"오류 발생 (안전보유): {str(e)[:30]}", 0.0

def execute_sell(ticker, hold_info, reason, sell_ratio=1.0):
    """
    v8.5 개선된 매도 실행
    
    개선사항:
    1. 재시도 로직 추가
    2. 잔고 검증 강화
    3. 실패 추적
    4. 롤백 처리
    """
    global sell_failure_tracker
    
    try:
        coin_symbol = ticker.split('-')[1]
        
        # 1. 실제 잔고 확인 (재시도 포함)
        current_balance = None
        for attempt in range(3):
            current_balance = upbit.get_balance(coin_symbol)
            if current_balance is not None:
                break
            time.sleep(0.2)
        
        if current_balance is None or current_balance <= 0:
            print(f"❌ [매도불가] {ticker}: 잔고 없음")
            if ticker in held_coins:
                del held_coins[ticker]
            return False
        
        # 2. held_coins와 실제 잔고 불일치 확인
        if abs(current_balance - hold_info['amount']) / hold_info['amount'] > 0.1:
            print(f"⚠️  {ticker}: 잔고 불일치 (예상 {hold_info['amount']:.8f}, 실제 {current_balance:.8f})")
            hold_info['amount'] = current_balance
        
        # 3. 매도 수량 계산
        sell_amount = current_balance * sell_ratio
        
        # 4. 매도 실행 (재시도 포함)
        result = None
        last_error = None
        
        for attempt in range(3):
            try:
                result = upbit.sell_market_order(ticker, sell_amount)
                if result:
                    break
                time.sleep(0.5)
            except Exception as e:
                last_error = e
                if attempt < 2:
                    time.sleep(1)
                    print(f"   ⚠️  {ticker} 매도 재시도 {attempt + 1}/3")
        
        if not result:
            # 매도 실패 추적
            if ticker not in sell_failure_tracker:
                sell_failure_tracker[ticker] = []
            sell_failure_tracker[ticker].append({
                'time': datetime.now(),
                'reason': reason,
                'error': str(last_error),
                'price': get_current_price(ticker)
            })
            
            print(f"❌ [매도실패] {ticker}: {last_error}")
            
            # Discord 긴급 알림
            alert_message = f"""
🚨 **매도 실패 경고**
코인: {ticker}
사유: {reason}
오류: {last_error}
시도: 3회 모두 실패

⚠️ 수동 확인 필요!
"""
            send_discord_message(alert_message, max_retries=5)
            
            return False
        
        # 5. 매도 성공 처리
        time.sleep(0.5)
        current_price = get_current_price(ticker)
        if current_price is None:
            current_price = hold_info['buy_price']
        
        profit_rate = (current_price - hold_info['buy_price']) / hold_info['buy_price'] * 100
        profit_amount = (current_price - hold_info['buy_price']) * sell_amount
        
        # 6. 매도 단계 처리
        if sell_ratio <= 0.35:
            hold_info['stage_1_sold'] = True
            hold_info['amount'] = current_balance - sell_amount
            stage_label = "1단계 (30%)"
        elif sell_ratio <= 0.45:
            hold_info['stage_2_sold'] = True
            hold_info['amount'] = current_balance - sell_amount
            stage_label = "2단계 (40%)"
        else:
            stage_label = "전량" if sell_ratio >= 0.99 else f"{sell_ratio*100:.0f}%"
            
            # 거래 이력 업데이트
            pattern = hold_info['pattern']
            if pattern in trade_history:
                if profit_rate > 0:
                    trade_history[pattern]['wins'] += 1
                    trade_history[pattern]['total_profit'] += profit_rate
                else:
                    trade_history[pattern]['losses'] += 1
                    trade_history[pattern]['total_profit'] += profit_rate
            
            recent_trades.append(profit_rate)
            
            # held_coins에서 제거
            del held_coins[ticker]
            
            # 매도 실패 기록 제거
            if ticker in sell_failure_tracker:
                del sell_failure_tracker[ticker]
        
        # 7. Discord 알림
        emoji = "🟢" if profit_rate > 0 else "🔴"
        message = f"""
{emoji} **매도 체결 - {stage_label}**
{ticker} | {current_price:,.0f}원
수익률: {profit_rate:+.2f}% | {profit_amount:+,.0f}원
사유: {reason}
보유: {hold_minutes:.0f}분
"""
        send_discord_message(message)
        
        print(f"✅ [매도성공] {ticker} | {profit_rate:+.2f}% | {stage_label}")
        
        return True
        
    except Exception as e:
        print(f"❌ [매도실행 오류] {ticker}: {e}")
        
        # 치명적 오류 알림
        alert_message = f"""
🚨 **매도 실행 치명적 오류**
코인: {ticker}
오류: {e}

⚠️ 즉시 수동 확인 필요!
"""
        send_discord_message(alert_message, max_retries=5)
        
        return False

# ===========================
# 고점 추적 스레드 (v8.5 신규)
# ===========================
def peak_tracker():
    """
    보유 코인의 고점을 5초마다 추적
    메인 루프의 30초 대기 시간 동안에도 고점을 놓치지 않음
    """
    print("✅ 고점 추적 스레드 시작")
    
    while True:
        try:
            if held_coins:
                for ticker in list(held_coins.keys()):
                    if ticker in held_coins:  # 재확인 (중간에 매도될 수 있음)
                        update_peak_price_continuously(ticker, held_coins[ticker])
            
            time.sleep(5)  # 5초마다 체크
            
        except Exception as e:
            if DEBUG_MODE:
                print(f"[고점추적 오류] {e}")
            time.sleep(10)

# ===========================
# 자산 리포터 (간략화)
# ===========================
def send_initial_report():
    """초기 리포트"""
    try:
        krw_balance = upbit.get_balance("KRW")
        message = f"""
🚀 **Fortress Hunter v8.5 시작**
시작: {start_time.strftime('%H:%M:%S')}
잔고: {krw_balance:,.0f}원

🔥 v8.5 개선사항:
- 매도 로직 전면 강화
- 고점 추적 실시간화
- 재시도 로직 추가
- 매도 실패 알림
"""
        send_discord_message(message, max_retries=5)
    except Exception as e:
        print(f"[초기리포트 오류] {e}")

def send_hourly_report():
    """정기 리포트"""
    try:
        krw_balance = upbit.get_balance("KRW")
        total_asset = krw_balance
        holdings_info = []
        
        for ticker, hold_info in held_coins.items():
            current_price = get_current_price(ticker)
            if current_price:
                profit_rate = (current_price - hold_info['buy_price']) / hold_info['buy_price'] * 100
                hold_minutes = (datetime.now() - hold_info['buy_time']).total_seconds() / 60
                
                stage = ""
                if hold_info['stage_1_sold']:
                    stage += "1✓"
                if hold_info['stage_2_sold']:
                    stage += "2✓"
                
                holdings_info.append(f"{ticker}[{stage}]: {profit_rate:+.2f}% ({hold_minutes:.0f}분)")
        
        pattern_stats = []
        for pattern, data in trade_history.items():
            total = data['wins'] + data['losses']
            if total > 0:
                wr = data['wins'] / total * 100
                pattern_stats.append(f"{pattern}: {wr:.0f}%승률")
        
        message = f"""
📊 **정기 리포트**
시간: {datetime.now().strftime('%H:%M')}
잔고: {krw_balance:,.0f}원
보유: {len(held_coins)}개

{chr(10).join(holdings_info) if holdings_info else '보유 없음'}

{chr(10).join(pattern_stats) if pattern_stats else '거래 없음'}
"""
        send_discord_message(message, max_retries=5)
    except Exception as e:
        print(f"[정기리포트 오류] {e}")

def asset_reporter():
    """자산 리포터 스레드"""
    time.sleep(10)
    send_initial_report()
    
    while True:
        try:
            time.sleep(3600)
            send_hourly_report()
        except Exception as e:
            print(f"[리포터 오류] {e}")
            time.sleep(60)

# ===========================
# 메인 루프
# ===========================
def main():
    """메인 트레이딩 루프"""
    
    if not initialize_and_validate():
        return
    
    # 스레드 시작
    reporter_thread = threading.Thread(target=asset_reporter, daemon=True)
    reporter_thread.start()
    
    # v8.5 신규: 고점 추적 스레드
    peak_thread = threading.Thread(target=peak_tracker, daemon=True)
    peak_thread.start()
    
    print("✅ 모든 스레드 시작 완료\n")
    
    loop_count = 0
    
    while True:
        try:
            loop_count += 1
            print(f"\n{'='*60}")
            print(f"[검색 #{loop_count}] {datetime.now().strftime('%H:%M:%S')}")
            print(f"{'='*60}")
            
            # 보유 코인 매도 신호 확인
            if held_coins:
                print(f"\n📊 보유 확인 ({len(held_coins)}개)")
                for ticker in list(held_coins.keys()):
                    should_sell, reason, sell_ratio = analyze_sell_signal_advanced(
                        ticker, held_coins[ticker]
                    )
                    
                    if should_sell:
                        print(f"   🔔 {ticker} 매도 신호: {reason}")
                        execute_sell(ticker, held_coins[ticker], reason, sell_ratio)
                    else:
                        print(f"   {reason}")
                    
                    time.sleep(0.1)
            else:
                print("\n📊 보유 없음")
            
            # 매수 기회 탐색
            if len(held_coins) < 3:
                print(f"\n🔍 매수 탐색 (여유 {3 - len(held_coins)}개)")
                best_opportunity = None
                best_score = 0
                
                for ticker in STRATEGIC_COINS:
                    if ticker in held_coins:
                        continue
                    
                    analysis = analyze_buy_signal(ticker)
                    
                    if analysis and analysis['should_buy']:
                        if analysis['total_score'] > best_score:
                            best_score = analysis['total_score']
                            best_opportunity = (ticker, analysis)
                    
                    time.sleep(0.1)
                
                if best_opportunity:
                    ticker, analysis = best_opportunity
                    print(f"\n🎯 매수 실행!")
                    execute_buy(ticker, analysis)
                else:
                    print(f"\n⚪ 매수 조건 미충족")
            else:
                print(f"\n⚠️  최대 보유 (3/3)")
            
            # 상태 요약
            print(f"\n{'='*60}")
            krw = upbit.get_balance("KRW")
            print(f"💰 잔고: {krw:,.0f}원 | 보유: {len(held_coins)}개")
            
            # 매도 실패 알림
            if sell_failure_tracker:
                print(f"⚠️  매도실패 추적: {len(sell_failure_tracker)}건")
                for ticker, failures in sell_failure_tracker.items():
                    print(f"   - {ticker}: {len(failures)}회 실패")
            
            print(f"{'='*60}")
            
            print(f"\n⏱️  30초 대기...")
            time.sleep(30)
            
        except Exception as e:
            print(f"\n❌ [메인루프 오류] {e}")
            time.sleep(10)

if __name__ == "__main__":
    main()
