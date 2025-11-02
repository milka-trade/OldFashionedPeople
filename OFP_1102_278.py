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
DISCORD_WEBHOOK_URL = os.getenv("discord_webhook")
ACCESS_KEY = os.getenv("UPBIT_ACCESS_KEY")
SECRET_KEY = os.getenv("UPBIT_SECRET_KEY")

upbit = None

# 보유 중인 코인 정보
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

# 매도 실패 추적
sell_failure_tracker = {}

# ===========================
# 기존 보유 코인 로드 (v8.7)
# ===========================
def load_existing_holdings():
    """프로그램 시작 시 기존 보유 코인을 held_coins에 로드"""
    global held_coins
    
    print("\n[기존 보유 코인 로드 중...]")
    
    try:
        balances = upbit.get_balances()
        if balances is None:
            print("❌ 잔고 조회 실패")
            return
        
        loaded_count = 0
        skipped_count = 0
        skipped_tickers = []
        
        for balance in balances:
            currency = balance['currency']
            
            # KRW는 제외
            if currency == 'KRW':
                continue
            
            ticker = f"KRW-{currency}"
            amount = float(balance['balance'])
            
            # 보유량이 있는 코인만 처리
            if amount > 0:
                avg_buy_price = float(balance['avg_buy_price'])
                
                # 현재가 조회
                current_price = get_current_price(ticker)
                if current_price is None:
                    # 🔥 개선: 가격 조회 실패 시 조용히 스킵
                    skipped_count += 1
                    skipped_tickers.append(ticker)
                    continue
                
                profit_rate = (current_price - avg_buy_price) / avg_buy_price * 100
                
                # held_coins에 추가
                held_coins[ticker] = {
                    'buy_time': datetime.now(),
                    'buy_price': avg_buy_price,
                    'amount': amount,
                    'pattern': 'legacy',
                    'expected_profit': 0,
                    'trend_strength': 50,
                    'peak_price': max(avg_buy_price, current_price),
                    'peak_time': datetime.now(),
                    'stage_1_sold': False,
                    'stage_2_sold': False,
                    'initial_amount': amount,
                    'is_legacy': True
                }
                
                print(f"   ✅ {ticker}: {amount:.8f}개 | 평단 {avg_buy_price:,.0f}원 | {profit_rate:+.2f}%")
                loaded_count += 1
                
                time.sleep(0.1)
        
        # 최종 결과 출력
        if loaded_count > 0:
            print(f"\n✅ {loaded_count}개 기존 보유 코인 로드 완료")

            # 스킵된 코인이 있으면 간단히 요약만 출력
            if skipped_count > 0:
                print(f"⚠️  {skipped_count}개 코인 스킵 (가격조회 불가: {', '.join(skipped_tickers)})")
            
            message = f"""
🔄 **프로그램 재시작**
기존 보유: {loaded_count}개 코인
→ 매도 모니터링 시작
"""
            send_discord_message(message)
        else:
            if skipped_count > 0:
                print(f"⚠️  {skipped_count}개 코인 스킵됨 (가격조회 불가)")
            print("✅ 로드 가능한 기존 보유 코인 없음")
        
    except Exception as e:
        print(f"❌ 기존 보유 로드 오류: {e}")


## 변경 사항:
'''
1. **개별 코인 오류 메시지 제거**: 각 코인마다 "⚠️ KRW-XXX: 가격 조회 실패 - 스킵" 메시지를 출력하지 않습니다.

2. **통합 요약 정보**: 스킵된 코인들을 카운트하고 마지막에 한 줄로 요약합니다.

3. **깔끔한 출력**: 성공적으로 로드된 코인만 개별 출력되고, 실패한 코인은 마지막에 한 번만 언급됩니다.
'''

## 출력 예시:
'''
[기존 보유 코인 로드 중...]
   ✅ KRW-ETH: 0.03757190개 | 평단 5,764,972원 | -0.14%

✅ 1개 기존 보유 코인 로드 완료
⚠️  5개 코인 스킵 (가격조회 불가: KRW-ONX, KRW-QI, KRW-ETHW, KRW-ETHF, KRW-PURSE)
'''

# ===========================
# 초기화 및 검증
# ===========================
def initialize_and_validate():
    """프로그램 초기화 및 검증"""
    global upbit
    
    print("\n" + "="*60)
    print("🚀 Fortress Hunter v8.9 ULTIMATE 초기화 중...")
    print("="*60)
    
    # 1. 환경변수 확인
    print("\n[1단계] 환경변수 확인")
    if not ACCESS_KEY or not SECRET_KEY:
        print("❌ 오류: UPBIT_ACCESS_KEY 또는 UPBIT_SECRET_KEY가 설정되지 않았습니다.")
        return False
    print("✅ API 키 확인 완료")
    
    if not DISCORD_WEBHOOK_URL:
        print("⚠️  경고: discord_webhook이 설정되지 않았습니다.")
    else:
        print("✅ Discord 웹훅 확인 완료")
    
    # 2. 업비트 연결 확인
    print("\n[2단계] 업비트 API 연결 확인")
    try:
        upbit = pyupbit.Upbit(ACCESS_KEY, SECRET_KEY)
        balances = upbit.get_balances()
        
        if balances is None:
            print("❌ 오류: 업비트 API 연결 실패")
            return False
        
        krw_balance = upbit.get_balance("KRW")
        print(f"✅ 업비트 연결 성공")
        print(f"   현재 KRW 잔고: {krw_balance:,.0f}원")
        
        if krw_balance < 5500:
            print(f"⚠️  경고: 잔고 부족 ({krw_balance:,.0f}원)")
        
    except Exception as e:
        print(f"❌ 오류: {e}")
        return False
    
    # 3. 시장 데이터 접근 테스트
    print("\n[3단계] 시장 데이터 접근 테스트")
    try:
        test_ticker = "KRW-BTC"
        test_price = pyupbit.get_current_price(test_ticker)
        
        if test_price is None:
            print(f"❌ 오류: 가격 조회 실패")
            return False
        
        print(f"✅ 시장 데이터 접근 성공")
        print(f"   {test_ticker} 현재가: {test_price:,.0f}원")
        
        test_df = pyupbit.get_ohlcv(test_ticker, interval="minute5", count=10)
        if test_df is None or len(test_df) == 0:
            print(f"❌ 오류: OHLCV 데이터 조회 실패")
            return False
        
        print(f"✅ OHLCV 데이터 조회 성공")
        
    except Exception as e:
        print(f"❌ 오류: {e}")
        return False
    
    # 4. 모니터링 코인 확인
    print("\n[4단계] 모니터링 코인 확인")
    print(f"총 {len(STRATEGIC_COINS)}개 코인:")
    for ticker in STRATEGIC_COINS:
        try:
            price = pyupbit.get_current_price(ticker)
            if price:
                print(f"   ✅ {ticker}: {price:,.0f}원")
            else:
                print(f"   ⚠️  {ticker}: 조회 실패")
            time.sleep(0.05)
        except Exception as e:
            print(f"   ❌ {ticker}: {e}")
    
    # 5. 설정 확인
    print("\n[5단계] 프로그램 설정")
    print(f"   디버그 모드: {'ON' if DEBUG_MODE else 'OFF'}")
    print(f"   테스트 모드: {'ON' if TEST_MODE else 'OFF'}")
    print(f"   최대 보유: 3개")
    print(f"   매수 금액: 50,000원")
    print(f"   🆕 v8.9 ULTIMATE 개선사항:")
    print(f"      - BB 상단 터치 매도 전략")
    print(f"      - RSI 다이버전스 감지")
    print(f"      - 수익률 구간별 동적 임계값")
    print(f"      - 최소 수익률 0.3% 보장")
    
    # 6. 기존 보유 코인 로드
    print("\n[6단계] 기존 보유 코인 로드")
    load_existing_holdings()
    
    print("\n" + "="*60)
    print("✅ 초기화 완료! 트레이딩 시작")
    print("="*60 + "\n")
    
    return True

# ===========================
# Discord 알림
# ===========================
def send_discord_message(content, max_retries=3):
    """Discord 웹훅 전송 (3회 재시도)"""
    if not DISCORD_WEBHOOK_URL:
        return False
    
    for attempt in range(max_retries):
        try:
            message = {"content": content}
            response = requests.post(DISCORD_WEBHOOK_URL, json=message, timeout=10)
            
            if response.status_code == 204:
                return True
            
            time.sleep(1 * (attempt + 1))
        except:
            if attempt < max_retries - 1:
                time.sleep(1)
    
    return False

# ===========================
# 데이터 가져오기
# ===========================
def get_current_price(ticker, max_retries=3):
    """현재 가격 조회 (재시도 포함)"""
    for attempt in range(max_retries):
        try:
            return pyupbit.get_orderbook(ticker=ticker)["orderbook_units"][0]["ask_price"]
        except:
            if attempt < max_retries - 1:
                time.sleep(0.2)
    return None

def get_ohlcv_with_retry(ticker, interval="minute1", count=200, max_retries=3):
    """OHLCV 데이터 가져오기 (재시도)"""
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
# 패턴 탐지 (매수) - v8.7과 동일
# ===========================
def detect_bottom_reversal_pattern(df_1m, df_3m, df_5m, df_15m):
    score = 0
    reasons = []
    
    if df_15m is None or df_5m is None or len(df_15m) < 3 or len(df_5m) < 3:
        return score, reasons
    
    current_15m = df_15m.iloc[-1]
    current_5m = df_5m.iloc[-1]
    prev_5m = df_5m.iloc[-2]
    prev_15m = df_15m.iloc[-2]
    
    # 🔥 개선 1: BB 하단 위치 점수 강화
    if pd.notna(current_15m['bb_lower']):
        bb_position = (current_15m['close'] - current_15m['bb_lower']) / (current_15m['bb_upper'] - current_15m['bb_lower'])
        
        if bb_position < 0.3:
            score += 35  # 기존 30 → 35
            reasons.append(f"🎯15분BB하단({bb_position*100:.1f}%)")
            
            # 추가: BB 하단을 크게 이탈한 경우 추가 점수
            if bb_position < 0.1:
                score += 10
                reasons.append("🔥극한BB이탈")
            
            if current_15m['rsi'] < 35:
                score += 20  # 기존 15 → 20
                reasons.append(f"RSI과매도({current_15m['rsi']:.1f})")
    
    # 🔥 개선 2: BB 하단 돌파 점수 강화 및 연속 감지
    if pd.notna(current_5m['bb_lower']) and pd.notna(prev_5m['close']):
        # 5분봉에서 BB 하단 돌파
        if prev_5m['close'] <= prev_5m['bb_lower'] and current_5m['close'] > current_5m['bb_lower']:
            score += 25  # 기존 20 → 25
            reasons.append("🔥BB하단돌파")
            
            # 추가: 15분봉에서도 동시에 돌파 시 추가 점수
            if pd.notna(prev_15m['close']) and prev_15m['close'] <= prev_15m['bb_lower'] and current_15m['close'] > current_15m['bb_lower']:
                score += 15
                reasons.append("🚀멀티프레임돌파")
        
        # 추가: 2개 이상의 연속 캔들이 BB 하단 이하였다가 현재 복귀한 경우
        if len(df_5m) >= 3:
            last_3_candles = df_5m.iloc[-3:]
            below_bb_count = sum(last_3_candles['close'] < last_3_candles['bb_lower'])
            if below_bb_count >= 2 and current_5m['close'] > current_5m['bb_lower']:
                score += 10
                reasons.append(f"지속이탈후복귀({below_bb_count}봉)")
        
        # 기존 코드
        if current_5m['close'] > current_5m['open'] and prev_5m['close'] < prev_5m['open']:
            score += 15  # 기존 10 → 15
            reasons.append("음→양봉")
        
        if current_5m['rsi'] > prev_5m['rsi'] and current_5m['rsi'] > 30:
            score += 10
            reasons.append(f"RSI상승({current_5m['rsi']:.1f})")
    
    if pd.notna(current_5m['stoch_k']) and pd.notna(current_5m['stoch_d']):
        if current_5m['stoch_k'] > current_5m['stoch_d'] and prev_5m['stoch_k'] <= prev_5m['stoch_d']:
            if current_5m['stoch_k'] < 50:
                score += 15
                reasons.append("SRSI골든크로스")
    
    return score, reasons

def detect_breakout_pattern(df_1m, df_3m, df_5m, df_15m):
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
            reasons.append(f"횡보돌파({range_pct:.2f}%)")
            
            if pd.notna(current['volume_ma']):
                volume_ratio = current['volume'] / current['volume_ma']
                if volume_ratio > 1.5:
                    score += 15
                    reasons.append(f"거래량{volume_ratio:.1f}배")
    
    if pd.notna(current['bb_upper']):
        if prev['close'] < prev['bb_upper'] and current['close'] > current['bb_upper']:
            score += 15
            reasons.append("BB상단돌파")
    
    if current['close'] > prev['close']:
        price_change = (current['close'] - prev['close']) / prev['close'] * 100
        if price_change > 1.0:
            score += 15
            reasons.append(f"강한모멘텀(+{price_change:.2f}%)")
    
    return score, reasons

def detect_reentry_pattern(df_1m, df_3m, df_5m, df_15m):
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
            reasons.append(f"재진입(-{pullback_pct:.2f}%)")
            
            if current_5m['rsi'] > 45 and current_5m['rsi'] < 65:
                score += 10
                reasons.append(f"적정RSI({current_5m['rsi']:.1f})")
            
            if pd.notna(current_5m['macd']) and pd.notna(current_5m['macd_signal']):
                if current_5m['macd'] > current_5m['macd_signal']:
                    score += 15
                    reasons.append("MACD상승")
    
    return score, reasons

def detect_momentum_pattern(df_1m, df_3m, df_5m, df_15m):
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
        reasons.append("3연속양봉")
        
        volume_increasing = all(last_3_candles_5m['volume'].diff().dropna() > 0)
        if volume_increasing:
            score += 10
            reasons.append("거래량상승")
    
    if 55 < current_5m['rsi'] < 70:
        score += 10
        reasons.append(f"RSI강세({current_5m['rsi']:.1f})")
    
    if pd.notna(current_5m['macd_hist']):
        last_3_hist = df_5m['macd_hist'].iloc[-3:]
        if len(last_3_hist) >= 3 and all(last_3_hist.diff().dropna() > 0):
            score += 15
            reasons.append("MACD증가")
    
    if current_15m['close'] > current_15m['bb_middle']:
        score += 10
        reasons.append("15분상승")
    
    return score, reasons

def detect_v_reversal_pattern(df_1m, df_3m, df_5m, df_15m):
    score = 0
    reasons = []
    
    if df_1m is None or df_3m is None or len(df_1m) < 10 or len(df_3m) < 5:
        return score, reasons
    
    current_1m = df_1m.iloc[-1]
    current_3m = df_3m.iloc[-1]
    
    # 🔥 개선: 더 긴 기간의 급락 후 반등 감지
    recent_10_1m = df_1m.iloc[-10:]
    max_drop = 0
    drop_duration = 0
    
    for i in range(len(recent_10_1m) - 1):
        drop = (recent_10_1m.iloc[i]['close'] - recent_10_1m.iloc[i+1]['low']) / recent_10_1m.iloc[i]['close'] * 100
        if drop > max_drop:
            max_drop = drop
            drop_duration = i + 1
    
    # 🔥 개선: 급락 범위 확대 및 점수 강화
    if 0.8 < max_drop < 5.0:  # 기존 1.0~3.0 → 0.8~5.0
        if current_1m['close'] > current_1m['open']:
            base_score = 25  # 기존 20 → 25
            
            # 추가: 급락 폭에 비례한 추가 점수
            if max_drop > 2.5:
                base_score += 10
                reasons.append(f"🔥강한V반등({max_drop:.2f}%)")
            else:
                reasons.append(f"V자반등({max_drop:.2f}%)")
            
            score += base_score
            
            # 🔥 개선: RSI 범위 확대
            if 20 < current_1m['rsi'] < 50:  # 기존 25~45 → 20~50
                score += 20  # 기존 15 → 20
                reasons.append(f"RSI회복({current_1m['rsi']:.1f})")
            
            # 추가: 3분봉에서도 동일한 패턴 확인
            if pd.notna(current_3m['close']) and current_3m['close'] > current_3m['open']:
                score += 10
                reasons.append("3분봉동시반등")
    
    # 🔥 추가: 5분봉 레벨의 V자 반등도 감지
    if df_5m is not None and len(df_5m) >= 5:
        recent_5_5m = df_5m.iloc[-5:]
        max_drop_5m = 0
        
        for i in range(len(recent_5_5m) - 1):
            drop = (recent_5_5m.iloc[i]['close'] - recent_5_5m.iloc[i+1]['low']) / recent_5_5m.iloc[i]['close'] * 100
            max_drop_5m = max(max_drop_5m, drop)
        
        current_5m = df_5m.iloc[-1]
        if 1.5 < max_drop_5m < 6.0 and current_5m['close'] > current_5m['open']:
            score += 20
            reasons.append(f"5분V반등({max_drop_5m:.2f}%)")
    
    return score, reasons

# ===========================
# 추세 강도 및 기댓값
# ===========================
def calculate_trend_strength(df_5m, df_15m, pattern_scores):
    strength = 0
    
    if df_5m is None or df_15m is None:
        return 50
    
    current_5m = df_5m.iloc[-1]
    current_15m = df_15m.iloc[-1]
    
    if pd.notna(current_5m['volume_ma']) and current_5m['volume_ma'] > 0:
        volume_ratio = current_5m['volume'] / current_5m['volume_ma']
        strength += min(volume_ratio * 10, 25)
    
    recent_5_candles = df_5m.iloc[-5:]
    price_change = (recent_5_candles.iloc[-1]['close'] - recent_5_candles.iloc[0]['close']) / recent_5_candles.iloc[0]['close'] * 100
    strength += min(abs(price_change) * 5, 25)
    
    alignment_score = 0
    if pd.notna(current_5m['ema_9']) and pd.notna(current_5m['ema_21']):
        if current_5m['ema_9'] > current_5m['ema_21']:
            alignment_score += 10
    if pd.notna(current_15m['ema_9']) and pd.notna(current_15m['ema_21']):
        if current_15m['ema_9'] > current_15m['ema_21']:
            alignment_score += 15
    strength += alignment_score
    
    best_pattern_score = max(pattern_scores.values()) if pattern_scores else 0
    strength += min(best_pattern_score / 4, 25)
    
    return min(strength, 100)

def calculate_win_rate(pattern_name):
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
# 매수 신호 분석 (v8.7과 동일)
# ===========================
def analyze_buy_signal(ticker):
    """매수 신호 분석"""
    try:
        # ... 기존 코드 동일 ...
        
        total_score = sum(pattern_scores.values())
        
        current_price = df_5m.iloc[-1]['close']
        bb_width = df_5m.iloc[-1]['bb_width'] if pd.notna(df_5m.iloc[-1]['bb_width']) else 5.0
        
        trend_strength = calculate_trend_strength(df_5m, df_15m, pattern_scores)
        
        expected_value, best_pattern, win_rate = calculate_expected_value(
            pattern_scores, current_price, bb_width
        )
        
        # 동적 기본 임계값
        if bb_width > 8.0:
            base_threshold = 40
        elif bb_width > 5.0:
            base_threshold = 45
        else:
            base_threshold = 50
        
        if TEST_MODE:
            base_threshold = 35
        
        # BB 하단 할인
        current_15m = df_15m.iloc[-1] if df_15m is not None else None
        bb_discount = 0
        if current_15m is not None and pd.notna(current_15m['bb_lower']):
            bb_position = (current_15m['close'] - current_15m['bb_lower']) / (current_15m['bb_upper'] - current_15m['bb_lower'])
            if bb_position < 0.3:
                bb_discount = 10
            if bb_position < 0.1:
                bb_discount = 15
        
        # 최근 거래 성과 반영
        if len(recent_trades) >= 5:
            recent_wins = sum(1 for result in recent_trades if result > 0)
            recent_win_rate = recent_wins / len(recent_trades)
            
            if recent_win_rate > 0.7:
                base_threshold -= 8
            elif recent_win_rate < 0.4:
                base_threshold += 8
        
        base_threshold -= bb_discount
        
        # 🔥 핵심 개선: 거래 이력에 따른 기댓값 요구 완화
        total_trades = sum(trade_history[p]['wins'] + trade_history[p]['losses'] for p in trade_history)
        
        if total_trades == 0:
            # 첫 거래: 기댓값 요구 사실상 제거
            ev_threshold = -0.5  # 음수 허용
        elif total_trades < 5:
            # 초기 5건: 매우 관대
            ev_threshold = 0.0
        elif total_trades < 10:
            # 10건까지: 관대
            ev_threshold = 0.2
        elif total_trades < 20:
            ev_threshold = 0.35
        else:
            ev_threshold = 0.6 if not TEST_MODE else 0.4
        
        # 🔥 추가: 강한 패턴은 기댓값 무시
        strong_pattern_detected = False
        if pattern_scores.get('bottom_reversal', 0) >= 60:
            ev_threshold = -0.5
            strong_pattern_detected = True
        elif pattern_scores.get('v_reversal', 0) >= 45:
            ev_threshold = -0.5
            strong_pattern_detected = True
        
        should_buy = total_score >= base_threshold and expected_value >= ev_threshold
        
        result = {
            'ticker': ticker,
            'total_score': total_score,
            'pattern_scores': pattern_scores,
            'best_pattern': best_pattern,
            'expected_value': expected_value,
            'win_rate': win_rate,
            'trend_strength': trend_strength,
            'threshold': base_threshold,
            'ev_threshold': ev_threshold,
            'current_price': current_price,
            'volatility': bb_width,
            'reasons': all_reasons,
            'should_buy': should_buy,
            'bb_discount': bb_discount,
            'total_trades': total_trades,
            'strong_pattern': strong_pattern_detected
        }
        
        if DEBUG_MODE:
            discount_str = f" (BB할인 -{bb_discount})" if bb_discount > 0 else ""
            ev_str = f" | EV {expected_value:.2f} (요구{ev_threshold:.2f})"
            
            if should_buy:
                if strong_pattern_detected:
                    print(f"   🟢 {ticker}: {total_score}점 (임계값 {base_threshold}{discount_str}){ev_str} | 추세 {trend_strength:.0f} | ⭐강한패턴")
                else:
                    print(f"   🟢 {ticker}: {total_score}점 (임계값 {base_threshold}{discount_str}){ev_str} | 추세 {trend_strength:.0f}")
            elif total_score >= base_threshold * 0.7:
                print(f"   🟡 {ticker}: {total_score}점 (임계값 {base_threshold}{discount_str}){ev_str} | 추세 {trend_strength:.0f}")
                
                # 매수 실패 이유 상세 출력
                if total_score >= base_threshold and expected_value < ev_threshold:
                    if total_trades == 0:
                        print(f"      ⚠️ 기댓값 {expected_value:.2f} < {ev_threshold:.2f} (첫 거래, 패턴점수 {pattern_scores[best_pattern]}점)")
                    else:
                        print(f"      ⚠️ 기댓값 부족 (거래이력 {total_trades}건, 패턴점수 {pattern_scores[best_pattern]}점)")
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
    """매수 실행 (자산 비례 방식)"""
    try:
        krw_balance = upbit.get_balance("KRW")
        
        if krw_balance < 5500:
            print(f"[매수 불가] 잔액 부족 ({krw_balance:,.0f}원)")
            return False
        
        # 🔥 개선: 총 자산 기반 매수 금액 계산
        total_asset = krw_balance
        
        # 보유 코인 평가액 추가
        for hold_ticker, hold_info in held_coins.items():
            current_price = get_current_price(hold_ticker)
            if current_price:
                total_asset += current_price * hold_info['amount']
        
        # 기본 매수 금액: 총 자산의 20% (3개 분산 투자 가정)
        base_position_size = total_asset * 0.20
        
        # 기댓값과 승률에 따른 조정 (0.8배 ~ 1.3배)
        ev_multiplier = min(max(analysis_result['expected_value'] / 0.6, 0.8), 1.3)
        wr_multiplier = min(max(analysis_result['win_rate'] / 0.5, 0.9), 1.2)
        
        position_size = base_position_size * ev_multiplier * wr_multiplier
        
        # 최소/최대 제한
        position_size = max(position_size, 50000)  # 최소 5만원
        position_size = min(position_size, krw_balance - 5000)  # KRW 여유금 확보
        position_size = min(position_size, total_asset * 0.30)  # 최대 총자산의 30%
        
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
                    'is_legacy': False
                }
                
                bb_info = f" (BB할인 -{analysis_result['bb_discount']}점)" if analysis_result.get('bb_discount', 0) > 0 else ""
                
                message = f"""
🔵 **매수 체결** 
코인: {ticker}
패턴: {analysis_result['best_pattern']}
매수가: {avg_price:,.0f}원
수량: {coin_balance:.8f}
투자금액: {position_size:,.0f}원 (총자산의 {position_size/total_asset*100:.1f}%)
총점: {analysis_result['total_score']}점{bb_info}
기댓값: {analysis_result['expected_value']:.2f}%
승률: {analysis_result['win_rate']*100:.1f}%
추세강도: {analysis_result['trend_strength']:.0f}점

분석:
{chr(10).join(analysis_result['reasons'][:3])}
"""
                send_discord_message(message)
                print(f"✅ [매수 성공] {ticker} | {avg_price:,.0f}원 | {coin_balance:.8f}개 | {position_size:,.0f}원 ({position_size/total_asset*100:.1f}%)")
                return True
        
        return False
        
    except Exception as e:
        print(f"❌ [매수 실행 오류] {ticker}: {e}")
        return False
# ===========================
# 🔥 v8.9 ULTIMATE 핵심: RSI 다이버전스 감지
# ===========================

# ===========================
# 🔥 v8.9 궁극의 매도 로직 - 새로운 함수들
# ===========================

def get_bb_position_detailed(df_15m, current_price):
    """BB 15분봉 위치를 6단계로 세분화"""
    
    if df_15m is None or len(df_15m) < 1:
        return None, "N/A"
    
    current_15m = df_15m.iloc[-1]
    
    if pd.notna(current_15m['bb_upper']) and pd.notna(current_15m['bb_lower']):
        bb_range = current_15m['bb_upper'] - current_15m['bb_lower']
        if bb_range > 0:
            position_pct = (current_price - current_15m['bb_lower']) / bb_range * 100
            
            if position_pct < 50:
                zone = "하단~중간"
            elif position_pct < 75:
                zone = "중간"
            elif position_pct < 90:
                zone = "중상단"
            elif position_pct < 100:
                zone = "상단근접"
            elif position_pct < 110:
                zone = "상단돌파"
            else:
                zone = "대폭돌파"
            
            return position_pct, zone
    
    return None, "N/A"

def calculate_upward_momentum(df_1m, df_3m, df_5m, df_15m):
    """상승 모멘텀 점수 계산 (최대 11점)"""
    
    momentum_score = 0
    momentum_reasons = []
    
    if df_5m is None or df_15m is None:
        return 0, []
    
    current_5m = df_5m.iloc[-1]
    current_15m = df_15m.iloc[-1]
    prev_5m = df_5m.iloc[-2]
    
    if pd.notna(current_15m['ema_9']) and pd.notna(current_15m['ema_21']):
        if current_15m['ema_9'] > current_15m['ema_21']:
            momentum_score += 2
            momentum_reasons.append("EMA15↗")
    
    if pd.notna(current_5m['ema_9']) and pd.notna(current_5m['ema_21']):
        if current_5m['ema_9'] > current_5m['ema_21']:
            momentum_score += 1
            momentum_reasons.append("EMA5↗")
    
    if pd.notna(current_5m['macd']) and pd.notna(current_5m['macd_signal']):
        if current_5m['macd'] > current_5m['macd_signal']:
            if pd.notna(prev_5m['macd']):
                if current_5m['macd'] > prev_5m['macd']:
                    momentum_score += 2
                    momentum_reasons.append("MACD↑")
    
    if len(df_5m) >= 3:
        last_3 = df_5m.iloc[-3:]
        if all(last_3['close'] > last_3['open']):
            momentum_score += 2
            momentum_reasons.append("3양봉")
    
    if pd.notna(current_5m['volume_ma']) and current_5m['volume_ma'] > 0:
        volume_ratio = current_5m['volume'] / current_5m['volume_ma']
        if volume_ratio > 1.2 and current_5m['close'] > current_5m['open']:
            momentum_score += 2
            momentum_reasons.append("거래량↑")
    
    if pd.notna(current_5m['rsi']) and pd.notna(prev_5m['rsi']):
        if current_5m['rsi'] > prev_5m['rsi'] and current_5m['rsi'] > 50:
            momentum_score += 1
            momentum_reasons.append("RSI↑")
    
    if len(df_15m) >= 2:
        current_bb_width = current_15m['bb_width']
        prev_bb_width = df_15m.iloc[-2]['bb_width']
        if pd.notna(current_bb_width) and pd.notna(prev_bb_width):
            if current_bb_width > prev_bb_width:
                momentum_score += 1
                momentum_reasons.append("BB확대")
    
    return momentum_score, momentum_reasons

def calculate_downward_signals(df_1m, df_3m, df_5m, df_15m):
    """하락 신호 점수 계산 (최대 16점)"""
    
    downward_score = 0
    downward_reasons = []
    
    if df_5m is None or df_15m is None:
        return 0, []
    
    current_5m = df_5m.iloc[-1]
    current_15m = df_15m.iloc[-1]
    prev_5m = df_5m.iloc[-2]
    
    has_div, div_str, rsi_drop = detect_rsi_divergence(df_5m, df_15m)
    if has_div:
        downward_score += 4
        downward_reasons.append("⚡다이버전스")
    
    if pd.notna(current_5m['stoch_k']) and pd.notna(current_5m['stoch_d']):
        if current_5m['stoch_k'] < current_5m['stoch_d'] and prev_5m['stoch_k'] >= prev_5m['stoch_d']:
            if current_5m['stoch_k'] > 70:
                downward_score += 3
                downward_reasons.append("SRSI데드")
    
    if pd.notna(current_5m['macd']) and pd.notna(current_5m['macd_signal']):
        if current_5m['macd'] < current_5m['macd_signal'] and prev_5m['macd'] >= prev_5m['macd_signal']:
            downward_score += 2
            downward_reasons.append("MACD데드")
    
    if pd.notna(current_5m['volume_ma']) and current_5m['volume_ma'] > 0:
        volume_ratio = current_5m['volume'] / current_5m['volume_ma']
        if volume_ratio < 0.6:
            downward_score += 2
            downward_reasons.append("거래량↓")
    
    if len(df_5m) >= 2:
        last_2 = df_5m.iloc[-2:]
        if all(last_2['close'] < last_2['open']):
            downward_score += 2
            downward_reasons.append("2음봉")
    
    if len(df_15m) >= 2:
        current_bb_width = current_15m['bb_width']
        prev_bb_width = df_15m.iloc[-2]['bb_width']
        if pd.notna(current_bb_width) and pd.notna(prev_bb_width):
            if current_bb_width < prev_bb_width and current_bb_width < 3.0:
                downward_score += 1
                downward_reasons.append("BB축소")
    
    if pd.notna(current_5m['rsi']) and pd.notna(prev_5m['rsi']):
        rsi_drop_rate = prev_5m['rsi'] - current_5m['rsi']
        if rsi_drop_rate > 10:
            downward_score += 2
            downward_reasons.append("RSI급락")
    
    return downward_score, downward_reasons


def detect_rsi_divergence(df_5m, df_15m):
    """RSI 다이버전스 감지 (Bearish Divergence)"""
    
    if df_15m is None or len(df_15m) < 5:
        return False, 0, 0
    
    try:
        recent_5 = df_15m.iloc[-5:]
        
        # 최근 2개의 고점 찾기
        highs = []
        for i in range(1, len(recent_5) - 1):
            if recent_5.iloc[i]['high'] > recent_5.iloc[i-1]['high'] and recent_5.iloc[i]['high'] > recent_5.iloc[i+1]['high']:
                highs.append(i)
        
        if len(highs) < 2:
            return False, 0, 0
        
        # 마지막 2개 고점
        peak_1_idx = highs[-2]
        peak_2_idx = highs[-1]
        
        price_high_1 = recent_5.iloc[peak_1_idx]['high']
        price_high_2 = recent_5.iloc[peak_2_idx]['high']
        
        rsi_high_1 = recent_5.iloc[peak_1_idx]['rsi']
        rsi_high_2 = recent_5.iloc[peak_2_idx]['rsi']
        
        # Bearish Divergence: 가격↑ RSI↓
        if pd.notna(rsi_high_1) and pd.notna(rsi_high_2):
            if price_high_2 > price_high_1 and rsi_high_2 < rsi_high_1:
                divergence_strength = (price_high_2 - price_high_1) / price_high_1 * 100
                rsi_drop = rsi_high_1 - rsi_high_2
                
                # 유의미한 다이버전스 (가격 0.5% 이상, RSI 5 이상 하락)
                if divergence_strength > 0.5 and rsi_drop > 5:
                    return True, divergence_strength, rsi_drop
        
        return False, 0, 0
        
    except Exception as e:
        if DEBUG_MODE:
            print(f"   ⚠️  다이버전스 감지 오류: {e}")
        return False, 0, 0

# ===========================
# 🔥 v8.9 ULTIMATE 핵심: BB 상단 기반 매도 신호 점수 계산
# ===========================

def should_stop_loss(ticker, hold_info, df_1m, df_5m, df_15m, profit_rate):
    """지능형 손절 판단"""
    
    if profit_rate <= -2.5:
        return True, f"🚨절대한계선({profit_rate:.2f}%)"
    
    # calculate_bearish_score 대신 calculate_downward_signals 사용
    downward_score, downward_reasons = calculate_downward_signals(
        df_1m, None, df_5m, df_15m
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
        downward_score -= 2
    elif hold_minutes > 30:
        downward_score += 1
    
    if downward_score >= threshold:
        reason = f"🔴추세전환(약세{downward_score}/{threshold}점:{','.join(downward_reasons[:2])})"
        return True, reason
    
    return False, None

def detect_sideways_exhaustion(df_5m, df_15m):
    """횡보/에너지 소진"""
    if df_5m is None or len(df_5m) < 20:
        return False, []
    
    current_5m = df_5m.iloc[-1]
    recent_10 = df_5m.iloc[-10:]
    exhaustion_signals = []
    
    recent_high = recent_10['high'].max()
    recent_low = recent_10['low'].min()
    price_range = (recent_high - recent_low) / recent_low * 100
    
    if price_range < 0.5:
        exhaustion_signals.append(f"횡보({price_range:.2f}%)")
    
    recent_volumes = recent_10['volume'].iloc[-5:]
    if all(recent_volumes.diff().dropna() < 0) and pd.notna(current_5m['volume_ma']):
        if current_5m['volume'] < current_5m['volume_ma'] * 0.6:
            exhaustion_signals.append("거래량감소")
    
    if pd.notna(current_5m['bb_width']) and current_5m['bb_width'] < 2.5:
        exhaustion_signals.append("변동성소멸")
    
    return len(exhaustion_signals) >= 2, exhaustion_signals

# ===========================
# 🔥 v8.9 ULTIMATE 통합 매도 신호 분석
# ===========================
# 🔥 v8.9 ULTIMATE - analyze_sell_signal_ultimate() 함수
# 이 함수로 v8.8의 analyze_sell_signal_ultimate()를 완전히 교체하세요!

def analyze_sell_signal_ultimate(ticker, hold_info):
    """궁극의 매도 신호 분석 - 완전 재설계 v9.0"""
    try:
        # 가격 조회
        current_price = None
        for attempt in range(3):
            current_price = get_current_price(ticker)
            if current_price:
                break
            time.sleep(0.2)
        
        if current_price is None:
            return False, "가격조회실패(안전)", 0.0
        
        buy_price = hold_info['buy_price']
        profit_rate = (current_price - buy_price) / buy_price * 100
        hold_minutes = (datetime.now() - hold_info['buy_time']).total_seconds() / 60
        
        # 고점 갱신
        if current_price > hold_info['peak_price']:
            hold_info['peak_price'] = current_price
            hold_info['peak_time'] = datetime.now()
        
        peak_profit = (hold_info['peak_price'] - buy_price) / buy_price * 100
        drawdown_from_peak = (hold_info['peak_price'] - current_price) / hold_info['peak_price'] * 100
        
        # 데이터 가져오기
        df_1m = get_ohlcv_with_retry(ticker, "minute1", 100)
        df_3m = get_ohlcv_with_retry(ticker, "minute3", 100)
        df_5m = get_ohlcv_with_retry(ticker, "minute5", 100)
        df_15m = get_ohlcv_with_retry(ticker, "minute15", 100)
        
        if df_1m is None or df_5m is None or df_15m is None:
            return False, "데이터실패(안전)", 0.0
        
        df_1m = calculate_indicators(df_1m)
        df_3m = calculate_indicators(df_3m) if df_3m is not None else None
        df_5m = calculate_indicators(df_5m)
        df_15m = calculate_indicators(df_15m)
        
        if df_1m is None or df_5m is None or df_15m is None:
            return False, "지표실패(안전)", 0.0
        
        # ============================================================
        # 🚨 1단계: 긴급 손절 (최우선)
        # ============================================================
        
        # 1-1. 절대 손절선
        if profit_rate <= -2.5:
            return True, f"🚨절대손절선({profit_rate:.2f}%)", 1.0
        
        # 1-2. 급격한 폭락 감지 (1분봉 기반)
        recent_3_candles_1m = df_1m.iloc[-3:]
        sudden_drop = 0
        for i in range(len(recent_3_candles_1m) - 1):
            candle_drop = (recent_3_candles_1m.iloc[i]['close'] - recent_3_candles_1m.iloc[i+1]['low']) / recent_3_candles_1m.iloc[i]['close'] * 100
            sudden_drop = max(sudden_drop, candle_drop)
        
        if sudden_drop > 2.0 and profit_rate < 1.0:
            return True, f"🚨급락감지({sudden_drop:.2f}%,{profit_rate:+.2f}%)", 1.0
        
        # 1-3. 다중 시간프레임 동시 급락
        current_1m = df_1m.iloc[-1]
        current_5m = df_5m.iloc[-1]
        current_15m = df_15m.iloc[-1]
        
        consecutive_red_1m = sum(1 for i in range(-3, 0) if df_1m.iloc[i]['close'] < df_1m.iloc[i]['open'])
        consecutive_red_5m = sum(1 for i in range(-2, 0) if df_5m.iloc[i]['close'] < df_5m.iloc[i]['open'])
        
        if consecutive_red_1m >= 3 and consecutive_red_5m >= 2 and profit_rate < 0.5:
            return True, f"🚨다중프레임급락({profit_rate:+.2f}%)", 1.0
        
        # ============================================================
        # 📊 2단계: BB 15분봉 위치 분석 (핵심)
        # ============================================================
        
        bb_position_15m = None
        bb_zone = "N/A"
        
        if pd.notna(current_15m['bb_upper']) and pd.notna(current_15m['bb_lower']):
            bb_range = current_15m['bb_upper'] - current_15m['bb_lower']
            if bb_range > 0:
                bb_position_15m = (current_price - current_15m['bb_lower']) / bb_range * 100
                
                if bb_position_15m < 30:
                    bb_zone = "하단"
                elif bb_position_15m < 50:
                    bb_zone = "중하단"
                elif bb_position_15m < 70:
                    bb_zone = "중간"
                elif bb_position_15m < 85:
                    bb_zone = "중상단"
                elif bb_position_15m < 95:
                    bb_zone = "상단근접"
                elif bb_position_15m < 105:
                    bb_zone = "상단돌파"
                else:
                    bb_zone = "대폭돌파"
        
        if bb_position_15m is None:
            return False, f"⏳보유({profit_rate:+.2f}%,BB계산실패)", 0.0
        
        # ============================================================
        # 🔍 3단계: 상승/하락 여력 분석
        # ============================================================
        
        momentum_score, momentum_reasons = calculate_upward_momentum(df_1m, df_3m, df_5m, df_15m)
        downward_score, downward_reasons = calculate_downward_signals(df_1m, df_3m, df_5m, df_15m)
        
        # 상승 여력 = BB 위치 + 모멘텀
        upside_potential = (100 - bb_position_15m) / 100 * 50 + momentum_score * 5
        upside_potential = min(upside_potential, 100)
        
        # 하락 여력 = 하락 신호 점수 + BB 위치
        downside_risk = downward_score * 5 + bb_position_15m / 100 * 30
        downside_risk = min(downside_risk, 100)
        
        # ============================================================
        # 🎯 4단계: 수익률 구간별 매도 전략
        # ============================================================
        
        # 🟢 보호 구간: -2.5% ~ 1.0% (손절만 고려, 조기 매도 절대 금지)
        if profit_rate < 1.0:
            # 이 구간에서는 급락이 아니면 절대 매도하지 않음
            # 이미 1단계에서 급락은 처리했으므로 여기서는 무조건 홀딩
            
            status_parts = [f"{profit_rate:+.2f}%", f"BB{bb_zone}{bb_position_15m:.0f}%"]
            status_parts.append(f"상승여력{upside_potential:.0f}")
            status_parts.append("보호구간")
            
            return False, f"⏳보유({' | '.join(status_parts)})", 0.0
        
        # 🟡 관찰 구간: 1.0% ~ 2.5% (신중한 매도)
        elif 1.0 <= profit_rate < 2.5:
            # BB 상단 돌파 (95%+) + 강한 하락 신호
            if bb_position_15m >= 95:
                if downward_score >= 12:
                    reason_str = ','.join(downward_reasons[:2])
                    return True, f"🟡관찰구간상단({bb_position_15m:.0f}%,D{downward_score},{reason_str},+{profit_rate:.2f}%)", 1.0
                elif momentum_score < 5:
                    return True, f"🟡관찰구간상단모멘텀약({bb_position_15m:.0f}%,M{momentum_score},+{profit_rate:.2f}%)", 1.0
            
            # BB 상단 근접 (85~95%) + 매우 강한 하락 신호
            elif bb_position_15m >= 85:
                if downward_score >= 14 and momentum_score < 5:
                    reason_str = ','.join(downward_reasons[:2])
                    return True, f"🟡관찰구간근접강한전환({bb_position_15m:.0f}%,D{downward_score},+{profit_rate:.2f}%)", 1.0
            
            # 그 외의 경우 홀딩 (상승 여력 존재)
            status_parts = [f"{profit_rate:+.2f}%", f"BB{bb_zone}{bb_position_15m:.0f}%"]
            status_parts.append(f"M{momentum_score}/D{downward_score}")
            status_parts.append(f"상승여력{upside_potential:.0f}")
            
            return False, f"⏳보유({' | '.join(status_parts)} | 관찰구간)", 0.0
        
        # 🔴 적극 구간: 2.5% 이상 (적극적 매도)
        else:
            # BB 대폭 돌파 (105%+)
            if bb_position_15m >= 105:
                return True, f"🔴대폭돌파({bb_position_15m:.0f}%,+{profit_rate:.2f}%)", 1.0
            
            # BB 상단 돌파 (95~105%)
            elif bb_position_15m >= 95:
                if momentum_score < 6:
                    return True, f"🔴상단돌파모멘텀약({bb_position_15m:.0f}%,M{momentum_score},+{profit_rate:.2f}%)", 1.0
                elif downward_score >= 10:
                    reason_str = ','.join(downward_reasons[:2])
                    return True, f"🔴상단돌파하락({bb_position_15m:.0f}%,D{downward_score},{reason_str},+{profit_rate:.2f}%)", 1.0
            
            # BB 상단 근접 (85~95%)
            elif bb_position_15m >= 85:
                if downward_score >= 12:
                    reason_str = ','.join(downward_reasons[:2])
                    return True, f"🔴상단근접강한전환({bb_position_15m:.0f}%,D{downward_score},{reason_str},+{profit_rate:.2f}%)", 1.0
                elif downward_score >= 8 and momentum_score < 6:
                    return True, f"🔴상단근접약화({bb_position_15m:.0f}%,D{downward_score}/M{momentum_score},+{profit_rate:.2f}%)", 1.0
            
            # BB 중상단 (70~85%)
            elif bb_position_15m >= 70:
                if downward_score >= 14:
                    reason_str = ','.join(downward_reasons[:2])
                    return True, f"🔴중상단강한전환({bb_position_15m:.0f}%,D{downward_score},{reason_str},+{profit_rate:.2f}%)", 1.0
                elif profit_rate >= 4.0 and downward_score >= 10:
                    return True, f"🔴충분수익+전환({bb_position_15m:.0f}%,D{downward_score},+{profit_rate:.2f}%)", 1.0
            
            # BB 중간~중상단 (50~70%): 강한 모멘텀 유지 시 홀딩
            elif bb_position_15m >= 50:
                if momentum_score >= 8:
                    # 강한 모멘텀 유지 중이면 계속 홀딩
                    status_parts = [f"{profit_rate:+.2f}%", f"BB{bb_zone}{bb_position_15m:.0f}%"]
                    status_parts.append(f"M{momentum_score}(강함)")
                    return False, f"⏳보유({' | '.join(status_parts)} | 추가상승대기)", 0.0
                elif downward_score >= 14:
                    reason_str = ','.join(downward_reasons[:2])
                    return True, f"🟠중간강한전환({bb_position_15m:.0f}%,D{downward_score},{reason_str},+{profit_rate:.2f}%)", 1.0
            
            # BB 하단~중간 (0~50%): 상승 여력 충분, 홀딩
            else:
                status_parts = [f"{profit_rate:+.2f}%", f"BB{bb_zone}{bb_position_15m:.0f}%"]
                status_parts.append(f"상승여력{upside_potential:.0f}")
                return False, f"⏳보유({' | '.join(status_parts)} | 상승여력충분)", 0.0
        
        # ============================================================
        # 🎯 5단계: 단계별 수익 실현 (기존 로직 유지)
        # ============================================================
        
        trend_strength = hold_info.get('trend_strength', 50)
        
        if trend_strength >= 80:
            stage_1_target = 3.5  # 상향 조정
            stage_2_target = 5.5
        elif trend_strength >= 65:
            stage_1_target = 3.0
            stage_2_target = 4.5
        elif trend_strength >= 50:
            stage_1_target = 2.5
            stage_2_target = 3.5
        else:
            stage_1_target = 2.0
            stage_2_target = 3.0
        
        if profit_rate >= 1.0:  # 최소 1% 이상에서만 단계별 매도
            if not hold_info['stage_1_sold'] and profit_rate >= stage_1_target:
                # BB 위치 확인: 상단 근접 이상일 때만 1단계 매도
                if bb_position_15m >= 75:
                    return True, f"🎯1단계(BB{bb_position_15m:.0f}%,+{profit_rate:.2f}%,30%매도)", 0.3
            
            if hold_info['stage_1_sold'] and not hold_info['stage_2_sold'] and profit_rate >= stage_2_target:
                # BB 위치 확인: 상단 이상일 때만 2단계 매도
                if bb_position_15m >= 85:
                    return True, f"🎯2단계(BB{bb_position_15m:.0f}%,+{profit_rate:.2f}%,40%매도)", 0.4
        
        # ============================================================
        # 🛡️ 6단계: 추적 손절 (고점 대비)
        # ============================================================
        
        if hold_info['stage_1_sold'] and hold_info['stage_2_sold']:
            time_since_peak = (datetime.now() - hold_info['peak_time']).total_seconds() / 60
            
            # 수익률에 따른 동적 추적 손절
            if profit_rate >= 5.0:
                trailing_stop = 2.5
            elif profit_rate >= 3.0:
                trailing_stop = 2.0
            elif profit_rate >= 2.0:
                trailing_stop = 1.5
            else:
                trailing_stop = 1.0
            
            if drawdown_from_peak >= trailing_stop:
                return True, f"📉추적손절(고점대비-{drawdown_from_peak:.2f}%,현재+{profit_rate:.2f}%)", 1.0
        
        # ============================================================
        # ⚡ 7단계: 고점 급락
        # ============================================================
        
        if peak_profit >= 2.0 and drawdown_from_peak >= 3.5:  # 임계값 상향
            return True, f"⚡고점급락(고점{peak_profit:.2f}%→현재{profit_rate:.2f}%)", 1.0
        
        # ============================================================
        # ⏰ 8단계: 장시간 보유
        # ============================================================
        
        if hold_minutes > 180 and 0.5 < profit_rate < 1.5:  # 임계값 조정
            return True, f"⏰장시간보유({hold_minutes:.0f}분,+{profit_rate:.2f}%)", 1.0
        
        # ============================================================
        # ✅ 최종: 보유 계속
        # ============================================================
        
        status_parts = [f"{profit_rate:+.2f}%"]
        status_parts.append(f"BB{bb_zone}{bb_position_15m:.0f}%")
        status_parts.append(f"M{momentum_score}/D{downward_score}")
        status_parts.append(f"상승{upside_potential:.0f}/하락{downside_risk:.0f}")
        
        if hold_info.get('is_legacy'):
            status_parts.append("기존")
        if hold_info['stage_1_sold']:
            status_parts.append("1단✓")
        if hold_info['stage_2_sold']:
            status_parts.append("2단✓")
        if peak_profit > profit_rate:
            status_parts.append(f"고점{peak_profit:.2f}%")
        
        status_parts.append(f"{hold_minutes:.0f}분")
        
        # 홀딩 이유 판단
        if profit_rate < 1.0:
            hold_reason = "보호구간"
        elif momentum_score >= 8:
            hold_reason = "강한모멘텀"
        elif bb_position_15m < 70:
            hold_reason = "상승여력충분"
        elif upside_potential > downside_risk:
            hold_reason = "상승우위"
        else:
            hold_reason = "관찰중"
        
        return False, f"⏳보유({' | '.join(status_parts)} | {hold_reason})", 0.0
        
    except Exception as e:
        if DEBUG_MODE:
            print(f"❌ 매도분석오류 {ticker}: {e}")
        return False, "오류(안전보유)", 0.0


def execute_sell(ticker, hold_info, reason, sell_ratio=1.0):
    """매도 실행"""
    global sell_failure_tracker
    
    try:
        coin_symbol = ticker.split('-')[1]
        
        current_balance = None
        for attempt in range(3):
            current_balance = upbit.get_balance(coin_symbol)
            if current_balance is not None:
                break
            time.sleep(0.2)
        
        if current_balance is None or current_balance <= 0:
            print(f"❌ [매도불가] {ticker}: 잔고없음")
            if ticker in held_coins:
                del held_coins[ticker]
            return False
        
        if abs(current_balance - hold_info['amount']) / hold_info['amount'] > 0.1:
            print(f"⚠️  {ticker}: 잔고불일치 (예상{hold_info['amount']:.8f}, 실제{current_balance:.8f})")
            hold_info['amount'] = current_balance
        
        sell_amount = current_balance * sell_ratio
        
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
                    print(f"   ⚠️  {ticker} 매도재시도 {attempt+1}/3")
        
        if not result:
            if ticker not in sell_failure_tracker:
                sell_failure_tracker[ticker] = []
            sell_failure_tracker[ticker].append({
                'time': datetime.now(),
                'reason': reason,
                'error': str(last_error),
                'price': get_current_price(ticker)
            })
            
            print(f"❌ [매도실패] {ticker}: {last_error}")
            
            alert = f"""
🚨 **매도실패경고**
{ticker} | {reason}
오류: {last_error}
시도: 3회 모두 실패
⚠️ 수동확인필요!
"""
            send_discord_message(alert, max_retries=5)
            
            return False
        
        time.sleep(0.5)
        current_price = get_current_price(ticker)
        if current_price is None:
            current_price = hold_info['buy_price']
        
        profit_rate = (current_price - hold_info['buy_price']) / hold_info['buy_price'] * 100
        profit_amount = (current_price - hold_info['buy_price']) * sell_amount
        
        if sell_ratio <= 0.35:
            hold_info['stage_1_sold'] = True
            hold_info['amount'] = current_balance - sell_amount
            stage_label = "1단계(30%)"
        elif sell_ratio <= 0.45:
            hold_info['stage_2_sold'] = True
            hold_info['amount'] = current_balance - sell_amount
            stage_label = "2단계(40%)"
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
            
            if ticker in sell_failure_tracker:
                del sell_failure_tracker[ticker]
        
        emoji = "🟢" if profit_rate > 0 else "🔴"
        legacy_tag = " [기존]" if hold_info.get('is_legacy') else ""
        message = f"""
{emoji} **매도체결-{stage_label}{legacy_tag}**
{ticker} | {current_price:,.0f}원
수익률: {profit_rate:+.2f}% | {profit_amount:+,.0f}원
사유: {reason}
보유: {(datetime.now()-hold_info['buy_time']).total_seconds()/60:.0f}분
"""
        send_discord_message(message)
        
        print(f"✅ [매도성공] {ticker} | {profit_rate:+.2f}% | {stage_label}")
        
        return True
        
    except Exception as e:
        print(f"❌ [매도오류] {ticker}: {e}")
        
        alert = f"""
🚨 **매도치명적오류**
{ticker}
오류: {e}
⚠️ 즉시수동확인!
"""
        send_discord_message(alert, max_retries=5)
        
        return False

# ===========================
# 상세 자산 보고서 (v8.7과 동일)
# ===========================
def generate_detailed_report():
    """상세 자산 보고서 생성"""
    try:
        krw_balance = upbit.get_balance("KRW")
        total_asset = krw_balance
        
        report_lines = []
        report_lines.append("="*70)
        report_lines.append(f"📊 자산 보고서 | {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        report_lines.append("="*70)
        report_lines.append(f"\n💰 KRW 잔고: {krw_balance:,.0f}원")
        report_lines.append(f"📦 보유 코인: {len(held_coins)}개\n")
        
        if held_coins:
            report_lines.append("-"*70)
            
            for ticker, hold_info in held_coins.items():
                current_price = get_current_price(ticker)
                df_5m = get_ohlcv_with_retry(ticker, "minute5", 50)
                
                if current_price is None or df_5m is None:
                    continue
                
                df_5m = calculate_indicators(df_5m)
                if df_5m is None:
                    continue
                
                current_5m = df_5m.iloc[-1]
                
                profit_rate = (current_price - hold_info['buy_price']) / hold_info['buy_price'] * 100
                coin_value = current_price * hold_info['amount']
                total_asset += coin_value
                hold_minutes = (datetime.now() - hold_info['buy_time']).total_seconds() / 60
                
                bb_position = "N/A"
                if pd.notna(current_5m['bb_lower']) and pd.notna(current_5m['bb_upper']):
                    bb_range = current_5m['bb_upper'] - current_5m['bb_lower']
                    if bb_range > 0:
                        position_pct = (current_price - current_5m['bb_lower']) / bb_range * 100
                        bb_position = f"{position_pct:.1f}%"
                
                rsi = f"{current_5m['rsi']:.1f}" if pd.notna(current_5m['rsi']) else "N/A"
                srsi_k = f"{current_5m['stoch_k']:.1f}" if pd.notna(current_5m['stoch_k']) else "N/A"
                srsi_d = f"{current_5m['stoch_d']:.1f}" if pd.notna(current_5m['stoch_d']) else "N/A"
                
                should_sell, sell_reason, _ = analyze_sell_signal_ultimate(ticker, hold_info)
                
                if should_sell:
                    opinion = f"⚠️ 매도신호: {sell_reason}"
                else:
                    if profit_rate > 2.0:
                        opinion = "✅ 우수한 수익 - 목표 근접"
                    elif profit_rate > 1.0:
                        opinion = "🟢 양호한 수익 - 계속 보유"
                    elif profit_rate > 0:
                        opinion = "🟡 소폭 수익 - 추이 관찰"
                    elif profit_rate > -1.0:
                        opinion = "🟠 소폭 손실 - 반등 대기"
                    else:
                        opinion = "🔴 손실 - 손절 검토"
                
                stages = []
                if hold_info.get('stage_1_sold'):
                    stages.append("1단✓")
                if hold_info.get('stage_2_sold'):
                    stages.append("2단✓")
                if hold_info.get('is_legacy'):
                    stages.append("기존")
                stage_str = f"[{','.join(stages)}]" if stages else ""
                
                report_lines.append(f"\n🪙 {ticker} {stage_str}")
                report_lines.append(f"├ 현재가: {current_price:,.0f}원 | 매수가: {hold_info['buy_price']:,.0f}원")
                report_lines.append(f"├ 수익률: {profit_rate:+.2f}% | 평가액: {coin_value:,.0f}원")
                report_lines.append(f"├ BB위치: {bb_position} | RSI: {rsi} | SRSI: K{srsi_k}/D{srsi_d}")
                report_lines.append(f"├ 보유시간: {hold_minutes:.0f}분 | 패턴: {hold_info['pattern']}")
                report_lines.append(f"└ 의견: {opinion}")
            
            report_lines.append("\n" + "-"*70)
        else:
            report_lines.append("보유 코인 없음\n")
        
        report_lines.append(f"\n🎯 패턴별 성과:")
        has_performance = False
        for pattern, data in trade_history.items():
            total_trades = data['wins'] + data['losses']
            if total_trades > 0:
                has_performance = True
                win_rate = data['wins'] / total_trades * 100
                avg_profit = data['total_profit'] / total_trades
                report_lines.append(f"  {pattern}: {win_rate:.1f}% 승률 | {avg_profit:+.2f}% 평균 | {total_trades}회")
        
        if not has_performance:
            report_lines.append("  거래 이력 없음")
        
        report_lines.append(f"\n💎 총 자산: {total_asset:,.0f}원")
        report_lines.append("="*70)
        
        report_text = "\n".join(report_lines)
        print(report_text)
        
        discord_report = f"""
📊 **자산보고서** {datetime.now().strftime('%H:%M')}

💰 KRW: {krw_balance:,.0f}원
📦 보유: {len(held_coins)}개
💎 총자산: {total_asset:,.0f}원
"""
        
        if held_coins:
            for ticker, hold_info in list(held_coins.items())[:3]:
                current_price = get_current_price(ticker)
                if current_price:
                    profit_rate = (current_price - hold_info['buy_price']) / hold_info['buy_price'] * 100
                    legacy_tag = "🔄" if hold_info.get('is_legacy') else ""
                    discord_report += f"\n{legacy_tag}{ticker}: {profit_rate:+.2f}%"
        
        send_discord_message(discord_report)
        
    except Exception as e:
        print(f"[보고서 생성 오류] {e}")

def asset_reporter():
    """정시마다 자산 보고서 출력"""
    print("\n[자산 리포터 시작]")
    time.sleep(5)
    generate_detailed_report()
    
    while True:
        try:
            now = datetime.now()
            next_hour = (now + timedelta(hours=1)).replace(minute=0, second=0, microsecond=0)
            wait_seconds = (next_hour - now).total_seconds()
            
            print(f"\n[다음 보고서: {next_hour.strftime('%H:%M')}]")
            time.sleep(wait_seconds)
            
            generate_detailed_report()
            
        except Exception as e:
            print(f"[리포터 오류] {e}")
            time.sleep(60)

# ===========================
# 고점 추적 스레드
# ===========================
def peak_tracker():
    """5초마다 고점 추적"""
    print("[고점 추적 스레드 시작]")
    
    while True:
        try:
            if held_coins:
                for ticker in list(held_coins.keys()):
                    if ticker in held_coins:
                        current_price = get_current_price(ticker)
                        if current_price and current_price > held_coins[ticker]['peak_price']:
                            held_coins[ticker]['peak_price'] = current_price
                            held_coins[ticker]['peak_time'] = datetime.now()
                            
                            if DEBUG_MODE:
                                profit = (current_price - held_coins[ticker]['buy_price']) / held_coins[ticker]['buy_price'] * 100
                                print(f"   📈 {ticker} 신고점: {profit:+.2f}%")
            
            time.sleep(5)
            
        except Exception as e:
            if DEBUG_MODE:
                print(f"[고점추적 오류] {e}")
            time.sleep(10)

# ===========================
# 메인 루프
# ===========================
def main():
    """메인 트레이딩 루프"""
    
    if not initialize_and_validate():
        return
    
    reporter_thread = threading.Thread(target=asset_reporter, daemon=True)
    reporter_thread.start()
    
    peak_thread = threading.Thread(target=peak_tracker, daemon=True)
    peak_thread.start()
    
    print("✅ 모든 스레드 시작 완료\n")
    
    loop_count = 0
    
    while True:
        try:
            loop_count += 1
            print(f"\n{'='*60}")
            print(f"[검색 #{loop_count}] {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
            print(f"{'='*60}")
            
            if held_coins:
                print(f"\n📊 보유 확인 ({len(held_coins)}개)")
                for ticker in list(held_coins.keys()):
                    should_sell, reason, sell_ratio = analyze_sell_signal_ultimate(
                        ticker, held_coins[ticker]
                    )
                    
                    if should_sell:
                        print(f"   🔔 {ticker} 매도신호: {reason}")
                        execute_sell(ticker, held_coins[ticker], reason, sell_ratio)
                    else:
                        print(f"   {reason}")
                    
                    time.sleep(0.1)
            else:
                print("\n📊 보유 없음")
            
            if len(held_coins) < 3:
                print(f"\n🔍 매수 탐색 (여유 {3-len(held_coins)}개)")
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
                    print(f"\n🎯 최적 기회!")
                    execute_buy(ticker, analysis)
                else:
                    print(f"\n⚪ 매수 조건 미충족")
            else:
                print(f"\n⚠️  최대 보유 (3/3)")
            
            print(f"\n{'='*60}")
            krw = upbit.get_balance("KRW")
            print(f"💰 잔고: {krw:,.0f}원 | 보유: {len(held_coins)}개")
            
            if sell_failure_tracker:
                print(f"⚠️  매도실패: {len(sell_failure_tracker)}건")
                for ticker, failures in sell_failure_tracker.items():
                    print(f"   - {ticker}: {len(failures)}회")
            
            print(f"{'='*60}")
            
            print(f"\n⏱️  30초 대기...")
            time.sleep(30)
            
        except Exception as e:
            print(f"\n❌ [메인루프 오류] {e}")
            time.sleep(10)

if __name__ == "__main__":
    main()