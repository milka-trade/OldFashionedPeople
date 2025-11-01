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
DEBUG_MODE = True  # 디버깅 모드 (상세 로그 출력)
TEST_MODE = False  # 테스트 모드 (매수 조건 완화)

# 전략 코인 설정
STRATEGIC_COINS = [
    "KRW-BTC", "KRW-ETH", "KRW-XRP", "KRW-SOL",
    "KRW-ADA", "KRW-LINK", "KRW-BCH", "KRW-XLM"
]

# ===========================
# 글로벌 변수 선언
# ===========================
# 환경변수 오타 수정: webhhok → webhook
DISCORD_WEBHOOK_URL = os.getenv("discord_webhook")  # 수정됨!
ACCESS_KEY = os.getenv("UPBIT_ACCESS_KEY")
SECRET_KEY = os.getenv("UPBIT_SECRET_KEY")

upbit = None  # 나중에 초기화

# 보유 중인 코인 정보를 저장하는 딕셔너리
held_coins = {}

# 거래 히스토리 추적
trade_history = {
    'bottom_reversal': {'wins': 0, 'losses': 0, 'total_profit': 0},
    'breakout': {'wins': 0, 'losses': 0, 'total_profit': 0},
    'reentry': {'wins': 0, 'losses': 0, 'total_profit': 0},
    'momentum': {'wins': 0, 'losses': 0, 'total_profit': 0},
    'v_reversal': {'wins': 0, 'losses': 0, 'total_profit': 0}
}

# 최근 거래 결과 추적
recent_trades = deque(maxlen=10)

# 시작 시간 기록
start_time = datetime.now()

# ===========================
# 초기화 및 검증
# ===========================
def initialize_and_validate():
    """프로그램 초기화 및 검증"""
    global upbit
    
    print("\n" + "="*60)
    print("🚀 Fortress Hunter v8.3 초기화 중...")
    print("="*60)
    
    # 1. 환경변수 확인
    print("\n[1단계] 환경변수 확인")
    if not ACCESS_KEY or not SECRET_KEY:
        print("❌ 오류: UPBIT_ACCESS_KEY 또는 UPBIT_SECRET_KEY가 설정되지 않았습니다.")
        print("   .env 파일을 확인하세요:")
        print("   UPBIT_ACCESS_KEY=your_access_key")
        print("   UPBIT_SECRET_KEY=your_secret_key")
        print("   discord_webhook=your_webhook_url")
        return False
    print("✅ API 키 확인 완료")
    
    if not DISCORD_WEBHOOK_URL:
        print("⚠️  경고: discord_webhook이 설정되지 않았습니다. Discord 알림이 비활성화됩니다.")
    else:
        print("✅ Discord 웹훅 확인 완료")
    
    # 2. 업비트 연결 확인
    print("\n[2단계] 업비트 API 연결 확인")
    try:
        upbit = pyupbit.Upbit(ACCESS_KEY, SECRET_KEY)
        balances = upbit.get_balances()
        
        if balances is None:
            print("❌ 오류: 업비트 API 연결 실패. API 키를 확인하세요.")
            return False
        
        # KRW 잔고 확인
        krw_balance = upbit.get_balance("KRW")
        print(f"✅ 업비트 연결 성공")
        print(f"   현재 KRW 잔고: {krw_balance:,.0f}원")
        
        if krw_balance < 5500:
            print(f"⚠️  경고: 잔고가 부족합니다 ({krw_balance:,.0f}원)")
            print("   최소 5,500원 이상 필요합니다.")
        
    except Exception as e:
        print(f"❌ 오류: 업비트 API 연결 실패 - {e}")
        return False
    
    # 3. 시장 데이터 접근 테스트
    print("\n[3단계] 시장 데이터 접근 테스트")
    try:
        test_ticker = "KRW-BTC"
        test_price = pyupbit.get_current_price(test_ticker)
        
        if test_price is None:
            print(f"❌ 오류: {test_ticker} 가격 조회 실패")
            return False
        
        print(f"✅ 시장 데이터 접근 성공")
        print(f"   {test_ticker} 현재가: {test_price:,.0f}원")
        
        # OHLCV 데이터 테스트
        test_df = pyupbit.get_ohlcv(test_ticker, interval="minute5", count=10)
        if test_df is None or len(test_df) == 0:
            print(f"❌ 오류: OHLCV 데이터 조회 실패")
            return False
        
        print(f"✅ OHLCV 데이터 조회 성공 ({len(test_df)}개 캔들)")
        
    except Exception as e:
        print(f"❌ 오류: 시장 데이터 접근 실패 - {e}")
        return False
    
    # 4. 모니터링 코인 확인
    print("\n[4단계] 모니터링 코인 확인")
    print(f"총 {len(STRATEGIC_COINS)}개 코인 모니터링:")
    for ticker in STRATEGIC_COINS:
        try:
            price = pyupbit.get_current_price(ticker)
            if price:
                print(f"   ✅ {ticker}: {price:,.0f}원")
            else:
                print(f"   ⚠️  {ticker}: 가격 조회 실패")
            time.sleep(0.05)
        except Exception as e:
            print(f"   ❌ {ticker}: 오류 - {e}")
    
    # 5. 설정 확인
    print("\n[5단계] 프로그램 설정")
    print(f"   디버그 모드: {'ON' if DEBUG_MODE else 'OFF'}")
    print(f"   테스트 모드: {'ON (매수 조건 완화)' if TEST_MODE else 'OFF'}")
    print(f"   최대 보유 코인: 3개")
    print(f"   매수 기본 금액: 50,000원")
    
    print("\n" + "="*60)
    print("✅ 모든 초기화 완료! 트레이딩 시작합니다.")
    print("="*60 + "\n")
    
    return True

# ===========================
# Discord 알림 함수
# ===========================
def send_discord_message(content):
    """디스코드 웹훅으로 메시지 전송"""
    if not DISCORD_WEBHOOK_URL:
        if DEBUG_MODE:
            print(f"[Discord 알림 비활성화] {content[:100]}...")
        return
    try:
        message = {"content": content}
        response = requests.post(DISCORD_WEBHOOK_URL, json=message, timeout=5)
        if response.status_code != 204:
            print(f"[Discord 알림 실패] 상태 코드: {response.status_code}")
    except Exception as e:
        print(f"[Discord 메시지 전송 오류] {e}")

# ===========================
# 데이터 가져오기 함수들
# ===========================
def get_current_price(ticker):
    """현재 가격 조회"""
    try:
        return pyupbit.get_orderbook(ticker=ticker)["orderbook_units"][0]["ask_price"]
    except:
        return None

def get_ohlcv_with_retry(ticker, interval="minute1", count=200, max_retries=3):
    """OHLCV 데이터를 재시도 로직과 함께 가져오기"""
    for attempt in range(max_retries):
        try:
            df = pyupbit.get_ohlcv(ticker, interval=interval, count=count)
            if df is not None and len(df) > 0:
                return df
            time.sleep(0.1)
        except Exception as e:
            if attempt == max_retries - 1:
                if DEBUG_MODE:
                    print(f"[오류] {ticker} {interval} 데이터 가져오기 실패: {e}")
            time.sleep(0.2)
    return None

# ===========================
# 기술적 지표 계산 함수들
# ===========================
def calculate_rsi(series, period=14):
    """RSI 계산"""
    delta = series.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    rs = gain / loss
    rsi = 100 - (100 / (1 + rs))
    return rsi

def calculate_ema(series, period):
    """EMA 계산"""
    return series.ewm(span=period, adjust=False).mean()

def calculate_macd(series, fast=12, slow=26, signal=9):
    """MACD 계산"""
    ema_fast = calculate_ema(series, fast)
    ema_slow = calculate_ema(series, slow)
    macd = ema_fast - ema_slow
    macd_signal = calculate_ema(macd, signal)
    macd_hist = macd - macd_signal
    return macd, macd_signal, macd_hist

def calculate_bollinger_bands(series, period=20, std=2):
    """볼린저 밴드 계산"""
    middle = series.rolling(window=period).mean()
    std_dev = series.rolling(window=period).std()
    upper = middle + (std_dev * std)
    lower = middle - (std_dev * std)
    width = (upper - lower) / middle * 100
    return upper, middle, lower, width

def calculate_stochastic_rsi(series, period=14, smooth_k=3, smooth_d=3):
    """Stochastic RSI 계산"""
    rsi = calculate_rsi(series, period)
    stoch_rsi = (rsi - rsi.rolling(window=period).min()) / (rsi.rolling(window=period).max() - rsi.rolling(window=period).min())
    stoch_k = stoch_rsi.rolling(window=smooth_k).mean() * 100
    stoch_d = stoch_k.rolling(window=smooth_d).mean()
    return stoch_k, stoch_d

def calculate_indicators(df):
    """기술적 지표 계산"""
    if df is None or len(df) < 20:
        return None
    
    # RSI
    df['rsi'] = calculate_rsi(df['close'], 14)
    
    # MACD
    df['macd'], df['macd_signal'], df['macd_hist'] = calculate_macd(df['close'])
    
    # Bollinger Bands
    df['bb_upper'], df['bb_middle'], df['bb_lower'], df['bb_width'] = calculate_bollinger_bands(df['close'])
    
    # Stochastic RSI
    df['stoch_k'], df['stoch_d'] = calculate_stochastic_rsi(df['close'])
    
    # 거래량 이동평균
    df['volume_ma'] = df['volume'].rolling(window=20).mean()
    
    # EMA
    df['ema_9'] = calculate_ema(df['close'], 9)
    df['ema_21'] = calculate_ema(df['close'], 21)
    
    return df

# ===========================
# 패턴 탐지 함수들 (매수)
# ===========================
def detect_bottom_reversal_pattern(df_1m, df_3m, df_5m, df_15m):
    """패턴 1: 바닥 반등 패턴"""
    score = 0
    reasons = []
    
    if df_15m is None or df_5m is None or len(df_15m) < 3 or len(df_5m) < 3:
        return score, reasons
    
    current_15m = df_15m.iloc[-1]
    prev_15m = df_15m.iloc[-2]
    current_5m = df_5m.iloc[-1]
    prev_5m = df_5m.iloc[-2]
    
    if pd.notna(current_15m['bb_lower']):
        bb_position = (current_15m['close'] - current_15m['bb_lower']) / (current_15m['bb_upper'] - current_15m['bb_lower'])
        
        if bb_position < 0.3:
            score += 15
            reasons.append(f"15분봉 볼린저밴드 하단 근접 (하위 {bb_position*100:.1f}%)")
            
            if current_15m['rsi'] < 35:
                score += 10
                reasons.append(f"15분봉 RSI 과매도 ({current_15m['rsi']:.1f})")
    
    if pd.notna(current_5m['bb_lower']) and pd.notna(prev_5m['close']):
        if prev_5m['close'] <= prev_5m['bb_lower'] and current_5m['close'] > current_5m['bb_lower']:
            score += 15
            reasons.append("5분봉 볼린저밴드 하단 돌파")
        
        if current_5m['close'] > current_5m['open'] and prev_5m['close'] < prev_5m['open']:
            score += 10
            reasons.append("5분봉 음봉→양봉 전환")
        
        if current_5m['rsi'] > prev_5m['rsi'] and current_5m['rsi'] > 30:
            score += 10
            reasons.append(f"5분봉 RSI 상승 전환 ({current_5m['rsi']:.1f})")
    
    if pd.notna(current_5m['stoch_k']) and pd.notna(current_5m['stoch_d']):
        if current_5m['stoch_k'] > current_5m['stoch_d'] and prev_5m['stoch_k'] <= prev_5m['stoch_d']:
            if current_5m['stoch_k'] < 50:
                score += 15
                reasons.append("5분봉 Stochastic RSI 골든크로스")
    
    return score, reasons

def detect_breakout_pattern(df_1m, df_3m, df_5m, df_15m):
    """패턴 2: 돌파 패턴"""
    score = 0
    reasons = []
    
    if df_5m is None or len(df_5m) < 20:
        return score, reasons
    
    current = df_5m.iloc[-1]
    prev = df_5m.iloc[-2]
    
    recent_high = df_5m['high'].iloc[-10:].max()
    recent_low = df_5m['low'].iloc[-10:].min()
    range_pct = (recent_high - recent_low) / recent_low * 100
    
    if range_pct < 3.0:
        if current['close'] > recent_high:
            score += 20
            reasons.append(f"횡보 상단 돌파 (변동폭 {range_pct:.2f}%)")
            
            if pd.notna(current['volume_ma']):
                volume_ratio = current['volume'] / current['volume_ma']
                if volume_ratio > 1.5:
                    score += 15
                    reasons.append(f"거래량 급증 (평균 대비 {volume_ratio:.1f}배)")
                    
                    if volume_ratio > 2.0:
                        score += 10
                        reasons.append("거래량 폭발적 증가")
    
    if pd.notna(current['bb_upper']):
        if prev['close'] < prev['bb_upper'] and current['close'] > current['bb_upper']:
            score += 15
            reasons.append("볼린저밴드 상단 돌파")
    
    if current['close'] > prev['close']:
        price_change = (current['close'] - prev['close']) / prev['close'] * 100
        if price_change > 1.0:
            score += 15
            reasons.append(f"강한 상승 모멘텀 (+{price_change:.2f}%)")
    
    return score, reasons

def detect_reentry_pattern(df_1m, df_3m, df_5m, df_15m):
    """패턴 3: 재진입 패턴"""
    score = 0
    reasons = []
    
    if df_15m is None or df_5m is None or len(df_15m) < 20 or len(df_5m) < 20:
        return score, reasons
    
    current_15m = df_15m.iloc[-1]
    current_5m = df_5m.iloc[-1]
    
    recent_high_15m = df_15m['high'].iloc[-10:-5].max()
    current_price = current_15m['close']
    
    if recent_high_15m > 0:
        pullback_pct = (recent_high_15m - current_price) / recent_high_15m * 100
        
        if 3.0 < pullback_pct < 7.0:
            score += 15
            reasons.append(f"건강한 조정 후 재진입 기회 (-{pullback_pct:.2f}%)")
            
            if current_5m['rsi'] > 45 and current_5m['rsi'] < 65:
                score += 10
                reasons.append(f"적정 RSI 구간 ({current_5m['rsi']:.1f})")
            
            if pd.notna(current_5m['macd']) and pd.notna(current_5m['macd_signal']):
                if current_5m['macd'] > current_5m['macd_signal']:
                    score += 15
                    reasons.append("MACD 상승 추세")
            
            if pd.notna(current_5m['bb_middle']):
                if current_5m['low'] <= current_5m['bb_middle'] <= current_5m['close']:
                    score += 15
                    reasons.append("볼린저밴드 중간선 지지")
    
    return score, reasons

def detect_momentum_pattern(df_1m, df_3m, df_5m, df_15m):
    """패턴 4: 모멘텀 패턴"""
    score = 0
    reasons = []
    
    if df_5m is None or df_15m is None or len(df_5m) < 10 or len(df_15m) < 10:
        return score, reasons
    
    current_5m = df_5m.iloc[-1]
    current_15m = df_15m.iloc[-1]
    
    last_3_candles_5m = df_5m.iloc[-3:]
    consecutive_up = all(last_3_candles_5m['close'] > last_3_candles_5m['open'])
    
    if consecutive_up:
        score += 15
        reasons.append("5분봉 연속 3개 양봉")
        
        volume_increasing = all(last_3_candles_5m['volume'].diff().dropna() > 0)
        if volume_increasing:
            score += 10
            reasons.append("거래량 동반 상승")
    
    if 55 < current_5m['rsi'] < 70:
        score += 10
        reasons.append(f"RSI 강세 구간 ({current_5m['rsi']:.1f})")
    
    if pd.notna(current_5m['macd_hist']):
        last_3_hist = df_5m['macd_hist'].iloc[-3:]
        if len(last_3_hist) >= 3 and all(last_3_hist.diff().dropna() > 0):
            score += 15
            reasons.append("MACD 히스토그램 증가 추세")
    
    if current_15m['close'] > current_15m['bb_middle']:
        score += 10
        reasons.append("15분봉 상승 추세")
    
    return score, reasons

def detect_v_reversal_pattern(df_1m, df_3m, df_5m, df_15m):
    """패턴 5: V자 반등 패턴"""
    score = 0
    reasons = []
    
    if df_1m is None or df_3m is None or len(df_1m) < 10 or len(df_3m) < 5:
        return score, reasons
    
    current_1m = df_1m.iloc[-1]
    current_3m = df_3m.iloc[-1]
    
    recent_5_1m = df_1m.iloc[-5:]
    max_drop = 0
    
    for i in range(len(recent_5_1m) - 1):
        drop = (recent_5_1m.iloc[i]['close'] - recent_5_1m.iloc[i+1]['low']) / recent_5_1m.iloc[i]['close'] * 100
        max_drop = max(max_drop, drop)
    
    if 1.0 < max_drop < 3.0:
        if current_1m['close'] > current_1m['open']:
            score += 20
            reasons.append(f"V자 반등 패턴 (급락 {max_drop:.2f}% 후 반등)")
            
            if 25 < current_1m['rsi'] < 45:
                score += 15
                reasons.append(f"과매도 구간 회복 (RSI {current_1m['rsi']:.1f})")
            
            if current_3m['close'] > current_3m['open']:
                score += 10
                reasons.append("3분봉 반등 확인")
            
            if pd.notna(current_1m['volume_ma']):
                if current_1m['volume'] > current_1m['volume_ma'] * 1.5:
                    score += 10
                    reasons.append("거래량 급증 (저점 매수 유입)")
    
    return score, reasons

# ===========================
# 추세 강도 및 기댓값 계산
# ===========================
def calculate_trend_strength(df_5m, df_15m, pattern_scores):
    """추세 강도를 0-100점으로 계산"""
    strength = 0
    
    if df_5m is None or df_15m is None:
        return 50
    
    current_5m = df_5m.iloc[-1]
    current_15m = df_15m.iloc[-1]
    
    # 거래량 강도
    if pd.notna(current_5m['volume_ma']) and current_5m['volume_ma'] > 0:
        volume_ratio = current_5m['volume'] / current_5m['volume_ma']
        volume_score = min(volume_ratio * 10, 25)
        strength += volume_score
    
    # 가격 모멘텀
    recent_5_candles = df_5m.iloc[-5:]
    price_change = (recent_5_candles.iloc[-1]['close'] - recent_5_candles.iloc[0]['close']) / recent_5_candles.iloc[0]['close'] * 100
    momentum_score = min(abs(price_change) * 5, 25)
    strength += momentum_score
    
    # 다중 타임프레임 정렬
    alignment_score = 0
    if pd.notna(current_5m['ema_9']) and pd.notna(current_5m['ema_21']):
        if current_5m['ema_9'] > current_5m['ema_21']:
            alignment_score += 10
    if pd.notna(current_15m['ema_9']) and pd.notna(current_15m['ema_21']):
        if current_15m['ema_9'] > current_15m['ema_21']:
            alignment_score += 15
    strength += alignment_score
    
    # 패턴 강도
    best_pattern_score = max(pattern_scores.values()) if pattern_scores else 0
    pattern_strength = min(best_pattern_score / 4, 25)
    strength += pattern_strength
    
    return min(strength, 100)

def calculate_win_rate(pattern_name):
    """특정 패턴의 승률 계산"""
    if pattern_name not in trade_history:
        return 0.5
    
    pattern_data = trade_history[pattern_name]
    total_trades = pattern_data['wins'] + pattern_data['losses']
    
    if total_trades == 0:
        return 0.5
    
    win_rate = pattern_data['wins'] / total_trades
    
    if total_trades < 5:
        win_rate = win_rate * 0.8 + 0.5 * 0.2
    
    return win_rate

def calculate_expected_value(pattern_scores, current_price, volatility):
    """기댓값 계산"""
    best_pattern = max(pattern_scores, key=pattern_scores.get)
    best_score = pattern_scores[best_pattern]
    
    if best_score < 50:
        return 0, best_pattern, 0
    
    win_rate = calculate_win_rate(best_pattern)
    
    base_profit = 1.5
    score_multiplier = best_score / 70
    expected_profit = base_profit * score_multiplier * (1 + volatility / 100)
    
    expected_loss = 0.7
    
    expected_value = (win_rate * expected_profit) - ((1 - win_rate) * expected_loss)
    
    return expected_value, best_pattern, win_rate

# ===========================
# 종합 매수 신호 분석 (개선됨)
# ===========================
def analyze_buy_signal(ticker):
    """종합 매수 신호 분석 (디버깅 강화)"""
    try:
        # 데이터 가져오기
        df_1m = get_ohlcv_with_retry(ticker, "minute1", 200)
        time.sleep(0.1)
        df_3m = get_ohlcv_with_retry(ticker, "minute3", 200)
        time.sleep(0.1)
        df_5m = get_ohlcv_with_retry(ticker, "minute5", 200)
        time.sleep(0.1)
        df_15m = get_ohlcv_with_retry(ticker, "minute15", 200)
        
        if df_1m is None or df_5m is None:
            if DEBUG_MODE:
                print(f"   ⚠️  {ticker}: 데이터 조회 실패")
            return None
        
        # 지표 계산
        df_1m = calculate_indicators(df_1m)
        df_3m = calculate_indicators(df_3m) if df_3m is not None else None
        df_5m = calculate_indicators(df_5m)
        df_15m = calculate_indicators(df_15m) if df_15m is not None else None
        
        if df_1m is None or df_5m is None:
            if DEBUG_MODE:
                print(f"   ⚠️  {ticker}: 지표 계산 실패")
            return None
        
        # 패턴 점수 계산
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
        
        expected_value, best_pattern, win_rate = calculate_expected_value(
            pattern_scores, current_price, bb_width
        )
        
        # 매수 임계값 결정 (테스트 모드 고려)
        base_threshold = 60
        
        if TEST_MODE:
            base_threshold = 40  # 테스트 모드: 조건 완화
        
        if len(recent_trades) >= 5:
            recent_wins = sum(1 for result in recent_trades if result > 0)
            recent_win_rate = recent_wins / len(recent_trades)
            
            if recent_win_rate > 0.7:
                base_threshold -= 5
            elif recent_win_rate < 0.4:
                base_threshold += 10
        
        if bb_width > 8.0:
            base_threshold += 5
        elif bb_width < 3.0:
            base_threshold -= 5
        
        should_buy = total_score >= base_threshold and expected_value >= (0.5 if TEST_MODE else 0.8)
        
        result = {
            'ticker': ticker,
            'total_score': total_score,
            'pattern_scores': pattern_scores,
            'best_pattern': best_pattern,
            'expected_value': expected_value,
            'win_rate': win_rate,
            'trend_strength': trend_strength,
            'threshold': base_threshold,
            'current_price': current_price,
            'volatility': bb_width,
            'reasons': all_reasons,
            'should_buy': should_buy
        }
        
        # 디버깅 출력
        if DEBUG_MODE:
            if should_buy:
                print(f"   🟢 {ticker}: {total_score}점 (임계값 {base_threshold}) | EV {expected_value:.2f} | 추세 {trend_strength:.0f}")
            elif total_score >= base_threshold * 0.7:  # 임계값의 70% 이상이면 출력
                print(f"   🟡 {ticker}: {total_score}점 (임계값 {base_threshold}) | EV {expected_value:.2f} | 추세 {trend_strength:.0f}")
            else:
                print(f"   ⚪ {ticker}: {total_score}점 (약함)")
        
        return result
        
    except Exception as e:
        if DEBUG_MODE:
            print(f"   ❌ {ticker} 분석 오류: {e}")
        return None

# ===========================
# 매수 실행
# ===========================
def execute_buy(ticker, analysis_result):
    """매수 실행"""
    try:
        krw_balance = upbit.get_balance("KRW")
        
        if krw_balance < 5500:
            print(f"[매수 불가] 잔액 부족 ({krw_balance:,.0f}원)")
            return False
        
        base_position_size = 50000
        
        ev_multiplier = min(analysis_result['expected_value'] / 0.8, 2.0)
        wr_multiplier = min(analysis_result['win_rate'] / 0.5, 1.5)
        
        position_size = base_position_size * ev_multiplier * wr_multiplier
        position_size = min(position_size, krw_balance - 5000, 200000)
        
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
                    'initial_amount': coin_balance
                }
                
                message = f"""
🔵 **매수 체결** 
코인: {ticker}
패턴: {analysis_result['best_pattern']}
매수가: {avg_price:,.0f}원
수량: {coin_balance:.8f}
투자금액: {position_size:,.0f}원
총점: {analysis_result['total_score']}점
기댓값: {analysis_result['expected_value']:.2f}%
승률: {analysis_result['win_rate']*100:.1f}%
추세강도: {analysis_result['trend_strength']:.0f}점

분석:
{chr(10).join(analysis_result['reasons'][:3])}
"""
                send_discord_message(message)
                print(f"✅ [매수 성공] {ticker} | {avg_price:,.0f}원 | {coin_balance:.8f}개")
                return True
        
        return False
        
    except Exception as e:
        print(f"❌ [매수 실행 오류] {ticker}: {e}")
        return False

# ===========================
# 지능형 손절 시스템
# ===========================
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
    
    # 가격 하락 점수
    if profit_rate <= -2.0:
        bearish_score += 5
        bearish_reasons.append(f"큰 손실 ({profit_rate:.2f}%)")
    elif profit_rate <= -1.5:
        bearish_score += 3
        bearish_reasons.append(f"상당한 손실 ({profit_rate:.2f}%)")
    elif profit_rate <= -1.0:
        bearish_score += 2
        bearish_reasons.append(f"손실 ({profit_rate:.2f}%)")
    
    # 거래량 급증 + 하락
    if pd.notna(current_5m['volume_ma']) and current_5m['volume_ma'] > 0:
        volume_ratio = current_5m['volume'] / current_5m['volume_ma']
        if volume_ratio > 1.5 and current_5m['close'] < current_5m['open']:
            bearish_score += 2
            bearish_reasons.append(f"공포 매도 (거래량 {volume_ratio:.1f}배)")
    
    # RSI 급락
    if pd.notna(current_1m['rsi']) and pd.notna(prev_1m['rsi']):
        rsi_drop_1m = prev_1m['rsi'] - current_1m['rsi']
        if rsi_drop_1m > 10 and current_1m['rsi'] < 40:
            bearish_score += 1
            bearish_reasons.append(f"1분봉 RSI 급락 ({current_1m['rsi']:.1f})")
    
    if pd.notna(current_5m['rsi']) and pd.notna(prev_5m['rsi']):
        rsi_drop_5m = prev_5m['rsi'] - current_5m['rsi']
        if rsi_drop_5m > 10 and current_5m['rsi'] < 40:
            bearish_score += 2
            bearish_reasons.append(f"5분봉 RSI 급락 ({current_5m['rsi']:.1f})")
    
    # MACD 데드크로스
    if pd.notna(current_1m['macd']) and pd.notna(current_1m['macd_signal']):
        if current_1m['macd'] < current_1m['macd_signal'] and prev_1m['macd'] >= prev_1m['macd_signal']:
            bearish_score += 1
            bearish_reasons.append("1분봉 MACD 데드크로스")
    
    if pd.notna(current_5m['macd']) and pd.notna(current_5m['macd_signal']):
        if current_5m['macd'] < current_5m['macd_signal'] and prev_5m['macd'] >= prev_5m['macd_signal']:
            bearish_score += 2
            bearish_reasons.append("5분봉 MACD 데드크로스")
    
    if df_15m is not None and len(df_15m) >= 2:
        current_15m = df_15m.iloc[-1]
        prev_15m = df_15m.iloc[-2]
        if pd.notna(current_15m['macd']) and pd.notna(current_15m['macd_signal']):
            if current_15m['macd'] < current_15m['macd_signal'] and prev_15m['macd'] >= prev_15m['macd_signal']:
                bearish_score += 3
                bearish_reasons.append("15분봉 MACD 데드크로스")
    
    # 연속 음봉
    last_3_1m = df_1m.iloc[-3:]
    consecutive_down_1m = all(last_3_1m['close'] < last_3_1m['open'])
    if consecutive_down_1m:
        bearish_score += 1
        bearish_reasons.append("1분봉 연속 음봉")
    
    last_2_5m = df_5m.iloc[-2:]
    consecutive_down_5m = all(last_2_5m['close'] < last_2_5m['open'])
    if consecutive_down_5m:
        bearish_score += 2
        bearish_reasons.append("5분봉 연속 음봉")
    
    # 볼린저밴드 하단 이탈 지속
    if pd.notna(current_5m['bb_lower']):
        if current_5m['close'] < current_5m['bb_lower'] and prev_5m['close'] < prev_5m['bb_lower']:
            bearish_score += 2
            bearish_reasons.append("볼밴 하단 지속 이탈")
    
    # EMA 데드크로스
    if pd.notna(current_5m['ema_9']) and pd.notna(current_5m['ema_21']):
        if current_5m['ema_9'] < current_5m['ema_21'] and prev_5m['ema_9'] >= prev_5m['ema_21']:
            bearish_score += 2
            bearish_reasons.append("5분봉 EMA 데드크로스")
    
    return bearish_score, bearish_reasons

def should_stop_loss(ticker, hold_info, df_1m, df_5m, df_15m, profit_rate):
    """지능형 손절 판단"""
    
    # 절대 한계선: -2.5% 이상 손실 시 무조건 손절
    if profit_rate <= -2.5:
        return True, f"절대 한계선 손절 ({profit_rate:.2f}%)"
    
    # 약세 전환 점수 계산
    bearish_score, bearish_reasons = calculate_bearish_score(
        df_1m, df_5m, df_15m, profit_rate, hold_info
    )
    
    # 추세 강도에 따른 손절 임계값 조정
    trend_strength = hold_info.get('trend_strength', 50)
    
    if trend_strength >= 80:
        threshold = 10
    elif trend_strength >= 65:
        threshold = 8
    else:
        threshold = 6
    
    # 시간 팩터
    hold_minutes = (datetime.now() - hold_info['buy_time']).total_seconds() / 60
    
    if hold_minutes < 5:
        bearish_score -= 2
    elif hold_minutes > 30:
        bearish_score += 1
    
    # 최근 거래 성과에 따른 적응
    if len(recent_trades) >= 5:
        recent_losses = sum(1 for result in recent_trades if result < 0)
        
        if recent_losses >= 4:
            threshold -= 1
        elif recent_losses == 0:
            threshold += 1
    
    # 손절 판단
    if bearish_score >= threshold:
        reason = f"추세 전환 감지 (약세점수 {bearish_score}/{threshold}점: {', '.join(bearish_reasons[:3])}, {profit_rate:.2f}%)"
        return True, reason
    
    return False, None

# ===========================
# 횡보/에너지 소진 감지
# ===========================
def detect_sideways_exhaustion(df_5m, df_15m):
    """횡보 및 에너지 소진 패턴 감지"""
    if df_5m is None or len(df_5m) < 20:
        return False, []
    
    current_5m = df_5m.iloc[-1]
    recent_10_candles = df_5m.iloc[-10:]
    
    exhaustion_signals = []
    
    # 가격 횡보
    recent_high = recent_10_candles['high'].max()
    recent_low = recent_10_candles['low'].min()
    price_range = (recent_high - recent_low) / recent_low * 100
    
    if price_range < 0.5:
        exhaustion_signals.append(f"가격 횡보 (변동폭 {price_range:.2f}%)")
    
    # 거래량 지속 감소
    recent_volumes = recent_10_candles['volume'].iloc[-5:]
    volume_decreasing = all(recent_volumes.diff().dropna() < 0)
    
    if volume_decreasing and pd.notna(current_5m['volume_ma']):
        if current_5m['volume'] < current_5m['volume_ma'] * 0.6:
            exhaustion_signals.append("거래량 지속 감소")
    
    # 볼린저밴드 수축
    if pd.notna(current_5m['bb_width']):
        if current_5m['bb_width'] < 2.5:
            exhaustion_signals.append(f"변동성 소멸 (BB폭 {current_5m['bb_width']:.2f}%)")
    
    # RSI 중립 구간 정체
    recent_rsi = recent_10_candles['rsi'].iloc[-5:]
    if all((recent_rsi > 45) & (recent_rsi < 55)):
        exhaustion_signals.append("RSI 중립 구간 정체")
    
    is_exhausted = len(exhaustion_signals) >= 3
    
    return is_exhausted, exhaustion_signals

# ===========================
# 고급 매도 신호 분석
# ===========================
def analyze_sell_signal_advanced(ticker, hold_info):
    """개선된 매도 신호 분석"""
    try:
        current_price = get_current_price(ticker)
        if current_price is None:
            return False, "가격 조회 실패", 1.0
        
        buy_price = hold_info['buy_price']
        profit_rate = (current_price - buy_price) / buy_price * 100
        hold_time = datetime.now() - hold_info['buy_time']
        hold_minutes = hold_time.total_seconds() / 60
        
        # 최고가 갱신
        if current_price > hold_info['peak_price']:
            hold_info['peak_price'] = current_price
            hold_info['peak_time'] = datetime.now()
        
        peak_profit = (hold_info['peak_price'] - buy_price) / buy_price * 100
        drawdown_from_peak = (hold_info['peak_price'] - current_price) / hold_info['peak_price'] * 100
        
        # 데이터 가져오기
        df_1m = get_ohlcv_with_retry(ticker, "minute1", 100)
        df_5m = get_ohlcv_with_retry(ticker, "minute5", 100)
        df_15m = get_ohlcv_with_retry(ticker, "minute15", 100)
        
        if df_1m is None or df_5m is None:
            return False, "데이터 조회 실패", 1.0
        
        df_1m = calculate_indicators(df_1m)
        df_5m = calculate_indicators(df_5m)
        df_15m = calculate_indicators(df_15m) if df_15m is not None else None
        
        current_1m = df_1m.iloc[-1]
        current_5m = df_5m.iloc[-1]
        prev_1m = df_1m.iloc[-2]
        prev_5m = df_5m.iloc[-2]
        
        # 지능형 손절
        should_cut, cut_reason = should_stop_loss(ticker, hold_info, df_1m, df_5m, df_15m, profit_rate)
        
        if should_cut:
            return True, cut_reason, 1.0
        
        # 추세 강도 기반 동적 목표 설정
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
        
        # 3단계 분할 매도 시스템
        if not hold_info['stage_1_sold'] and profit_rate >= stage_1_target:
            return True, f"1단계 목표 달성 (+{profit_rate:.2f}%, 30% 매도)", 0.3
        
        if hold_info['stage_1_sold'] and not hold_info['stage_2_sold'] and profit_rate >= stage_2_target:
            return True, f"2단계 목표 달성 (+{profit_rate:.2f}%, 40% 매도)", 0.4
        
        # 적응형 추적 손절
        if hold_info['stage_1_sold'] and hold_info['stage_2_sold']:
            time_since_peak = (datetime.now() - hold_info['peak_time']).total_seconds() / 60
            
            if time_since_peak < 5:
                trailing_stop = 2.0
            elif time_since_peak < 15:
                trailing_stop = 1.5
            else:
                trailing_stop = 1.0
            
            if drawdown_from_peak >= trailing_stop:
                return True, f"추적 손절 (고점 대비 -{drawdown_from_peak:.2f}%, +{profit_rate:.2f}% 실현)", 1.0
        
        # 다중 타임프레임 약세 전환 감지
        if profit_rate > 0.5:
            bearish_signals = 0
            bearish_reasons = []
            
            if current_1m['rsi'] > 70 and current_1m['close'] < current_1m['open']:
                bearish_signals += 1
                bearish_reasons.append("1분봉 과매수+음봉")
            
            if pd.notna(current_1m['macd']) and pd.notna(current_1m['macd_signal']):
                if current_1m['macd'] < current_1m['macd_signal'] and prev_1m['macd'] >= prev_1m['macd_signal']:
                    bearish_signals += 1
                    bearish_reasons.append("1분봉 MACD 데드크로스")
            
            if current_5m['rsi'] > 70:
                bearish_signals += 1
                bearish_reasons.append("5분봉 과매수")
            
            if pd.notna(current_5m['stoch_k']) and pd.notna(current_5m['stoch_d']):
                if current_5m['stoch_k'] < current_5m['stoch_d'] and prev_5m['stoch_k'] >= prev_5m['stoch_d']:
                    if current_5m['stoch_k'] > 70:
                        bearish_signals += 2
                        bearish_reasons.append("5분봉 고점 Stoch 데드크로스")
            
            if pd.notna(current_5m['bb_upper']):
                if prev_5m['close'] > prev_5m['bb_upper'] and current_5m['close'] < current_5m['bb_upper']:
                    bearish_signals += 1
                    bearish_reasons.append("5분봉 볼밴 상단 이탈")
            
            if df_15m is not None and len(df_15m) >= 2:
                current_15m = df_15m.iloc[-1]
                prev_15m = df_15m.iloc[-2]
                
                if pd.notna(current_15m['ema_9']) and pd.notna(current_15m['ema_21']):
                    if current_15m['ema_9'] < current_15m['ema_21'] and prev_15m['ema_9'] >= prev_15m['ema_21']:
                        bearish_signals += 2
                        bearish_reasons.append("15분봉 EMA 데드크로스")
            
            if bearish_signals >= 3:
                sell_ratio = 1.0 if not hold_info['stage_1_sold'] else (1.0 if not hold_info['stage_2_sold'] else 1.0)
                return True, f"다중 약세 전환 ({', '.join(bearish_reasons[:2])}, +{profit_rate:.2f}%)", sell_ratio
        
        # 횡보/에너지 소진 감지
        if profit_rate > 0.3:
            is_exhausted, exhaustion_signals = detect_sideways_exhaustion(df_5m, df_15m)
            
            if is_exhausted:
                return True, f"에너지 소진 ({', '.join(exhaustion_signals[:2])}, +{profit_rate:.2f}%)", 1.0
        
        # 거래량 급감 경고
        if profit_rate > stage_2_target:
            if pd.notna(current_5m['volume_ma']):
                if current_5m['volume'] < current_5m['volume_ma'] * 0.5:
                    return True, f"급등 후 거래량 급감 (+{profit_rate:.2f}%)", 1.0
        
        # 보유 계속
        status_parts = [f"{profit_rate:+.2f}%"]
        if hold_info['stage_1_sold']:
            status_parts.append("1단계✓")
        if hold_info['stage_2_sold']:
            status_parts.append("2단계✓")
        if peak_profit > profit_rate:
            status_parts.append(f"고점 {peak_profit:.2f}%")
        status_parts.append(f"{hold_minutes:.0f}분")
        
        return False, f"보유 ({' | '.join(status_parts)})", 0.0
        
    except Exception as e:
        if DEBUG_MODE:
            print(f"❌ [매도 신호 분석 오류] {ticker}: {e}")
        return False, f"분석 오류: {e}", 0.0

# ===========================
# 매도 실행
# ===========================
def execute_sell(ticker, hold_info, reason, sell_ratio=1.0):
    """매도 실행 (분할 매도 지원)"""
    try:
        coin_symbol = ticker.split('-')[1]
        current_balance = upbit.get_balance(coin_symbol)
        
        if current_balance <= 0:
            print(f"[매도 불가] {ticker} 보유 수량 없음")
            if ticker in held_coins:
                del held_coins[ticker]
            return False
        
        sell_amount = current_balance * sell_ratio
        
        result = upbit.sell_market_order(ticker, sell_amount)
        
        if result:
            time.sleep(0.5)
            current_price = get_current_price(ticker)
            profit_rate = (current_price - hold_info['buy_price']) / hold_info['buy_price'] * 100
            profit_amount = (current_price - hold_info['buy_price']) * sell_amount
            
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
                
                pattern = hold_info['pattern']
                if pattern in trade_history:
                    if profit_rate > 0:
                        trade_history[pattern]['wins'] += 1
                        trade_history[pattern]['total_profit'] += profit_rate
                    else:
                        trade_history[pattern]['losses'] += 1
                        trade_history[pattern]['total_profit'] += profit_rate
                
                recent_trades.append(profit_rate)
                del held_coins[ticker]
            
            emoji = "🟢" if profit_rate > 0 else "🔴"
            message = f"""
{emoji} **매도 체결 - {stage_label}**
코인: {ticker}
패턴: {hold_info['pattern']}
매수가: {hold_info['buy_price']:,.0f}원
매도가: {current_price:,.0f}원
수익률: {profit_rate:+.2f}%
수익금: {profit_amount:+,.0f}원
사유: {reason}
보유시간: {(datetime.now() - hold_info['buy_time']).total_seconds() / 60:.0f}분
"""
            send_discord_message(message)
            print(f"✅ [매도 성공] {ticker} | 수익률 {profit_rate:+.2f}% | {reason} | {stage_label}")
            
            return True
        
        return False
        
    except Exception as e:
        print(f"❌ [매도 실행 오류] {ticker}: {e}")
        return False

# ===========================
# 자산 리포터
# ===========================
def send_initial_report():
    """시작 시 초기 리포트 전송"""
    try:
        krw_balance = upbit.get_balance("KRW")
        
        message = f"""
📊 **Fortress Hunter v8.3 - 초기 자산 리포트**

💰 **시작 자산**
KRW 잔고: {krw_balance:,.0f}원

⚙️ **설정**
모니터링 코인: {len(STRATEGIC_COINS)}개
최대 보유: 3개
디버그 모드: {'ON' if DEBUG_MODE else 'OFF'}
테스트 모드: {'ON' if TEST_MODE else 'OFF'}

🚀 트레이딩 시작!
"""
        send_discord_message(message)
        
    except Exception as e:
        print(f"[초기 리포트 오류] {e}")

def asset_reporter():
    """1시간마다 자산 현황 리포트"""
    # 시작 시 즉시 한 번 실행
    send_initial_report()
    
    while True:
        try:
            time.sleep(3600)  # 1시간 대기
            
            krw_balance = upbit.get_balance("KRW")
            total_asset = krw_balance
            total_profit = 0
            
            holdings_info = []
            
            for ticker, hold_info in held_coins.items():
                current_price = get_current_price(ticker)
                if current_price:
                    coin_value = current_price * hold_info['amount']
                    profit_rate = (current_price - hold_info['buy_price']) / hold_info['buy_price'] * 100
                    profit_amount = coin_value - (hold_info['buy_price'] * hold_info['amount'])
                    
                    total_asset += coin_value
                    total_profit += profit_amount
                    
                    hold_time = datetime.now() - hold_info['buy_time']
                    
                    stage_status = []
                    if hold_info.get('stage_1_sold'):
                        stage_status.append("1단계✓")
                    if hold_info.get('stage_2_sold'):
                        stage_status.append("2단계✓")
                    stage_str = f" [{','.join(stage_status)}]" if stage_status else ""
                    
                    holdings_info.append(f"""
{ticker}{stage_str}: {profit_rate:+.2f}%
- 매수가: {hold_info['buy_price']:,.0f}원
- 현재가: {current_price:,.0f}원
- 평가액: {coin_value:,.0f}원
- 추세강도: {hold_info.get('trend_strength', 0):.0f}점
- 보유시간: {hold_time.total_seconds() / 60:.0f}분
""")
            
            pattern_performance = []
            for pattern, data in trade_history.items():
                total_trades = data['wins'] + data['losses']
                if total_trades > 0:
                    win_rate = data['wins'] / total_trades * 100
                    avg_profit = data['total_profit'] / total_trades
                    pattern_performance.append(
                        f"{pattern}: {win_rate:.1f}% 승률, {avg_profit:+.2f}% 평균"
                    )
            
            runtime = datetime.now() - start_time
            message = f"""
📊 **Fortress Hunter v8.3 - 자산 리포트**

💰 **자산 현황**
KRW 잔고: {krw_balance:,.0f}원
보유 코인: {len(held_coins)}개
총 자산: {total_asset:,.0f}원
총 손익: {total_profit:+,.0f}원

📈 **보유 현황**
{''.join(holdings_info) if holdings_info else '보유 코인 없음'}

🎯 **패턴별 성과**
{chr(10).join(pattern_performance) if pattern_performance else '거래 이력 없음'}

⏱️ 가동 시간: {runtime.total_seconds() / 3600:.1f}시간
"""
            send_discord_message(message)
            
        except Exception as e:
            print(f"[자산 리포터 오류] {e}")

# ===========================
# 메인 트레이딩 루프
# ===========================
def main():
    """메인 트레이딩 루프"""
    
    # 초기화 및 검증
    if not initialize_and_validate():
        print("\n초기화 실패. 프로그램을 종료합니다.")
        return
    
    # 자산 리포터 스레드 시작
    reporter_thread = threading.Thread(target=asset_reporter, daemon=True)
    reporter_thread.start()
    
    loop_count = 0
    
    while True:
        try:
            loop_count += 1
            print(f"\n{'='*60}")
            print(f"[검색 #{loop_count}] {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
            print(f"{'='*60}")
            
            # 전략 코인만 사용
            tickers = STRATEGIC_COINS
            
            # 보유 코인 매도 신호 확인
            if held_coins:
                print(f"\n📊 보유 코인 확인 중... ({len(held_coins)}개)")
                for ticker in list(held_coins.keys()):
                    should_sell, reason, sell_ratio = analyze_sell_signal_advanced(ticker, held_coins[ticker])
                    
                    if should_sell:
                        execute_sell(ticker, held_coins[ticker], reason, sell_ratio)
                    else:
                        print(f"   ⏳ {ticker}: {reason}")
                    
                    time.sleep(0.1)
            else:
                print("\n📊 보유 코인 없음")
            
            # 매수 기회 탐색 (최대 3개 코인까지 보유)
            if len(held_coins) < 3:
                print(f"\n🔍 매수 기회 탐색 중... (여유 {3 - len(held_coins)}개)")
                best_opportunity = None
                best_score = 0
                
                for ticker in tickers:
                    if ticker in held_coins:
                        continue
                    
                    analysis = analyze_buy_signal(ticker)
                    
                    if analysis and analysis['should_buy']:
                        if DEBUG_MODE:
                            print(f"   💡 매수 후보: {ticker}")
                        
                        if analysis['total_score'] > best_score:
                            best_score = analysis['total_score']
                            best_opportunity = (ticker, analysis)
                    
                    time.sleep(0.1)
                
                if best_opportunity:
                    ticker, analysis = best_opportunity
                    print(f"\n🎯 최적 기회 발견!")
                    execute_buy(ticker, analysis)
                else:
                    print(f"\n⚪ 현재 매수 조건 충족 코인 없음")
            else:
                print(f"\n⚠️  최대 보유 수량 도달 (3/3)")
            
            # 현재 상태 요약
            print(f"\n{'='*60}")
            krw = upbit.get_balance("KRW")
            print(f"💰 KRW 잔고: {krw:,.0f}원 | 보유: {len(held_coins)}개")
            print(f"{'='*60}")
            
            # 대기
            print(f"\n⏱️  30초 대기 중...")
            time.sleep(30)
            
        except Exception as e:
            print(f"\n❌ [메인 루프 오류] {e}")
            time.sleep(10)

if __name__ == "__main__":
    main()