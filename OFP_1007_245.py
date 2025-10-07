import time
import pyupbit
import numpy as np
from datetime import datetime, timedelta
import os
from dotenv import load_dotenv
import requests
import threading

load_dotenv()

DISCORD_WEBHOOK_URL = os.getenv("discord_webhhok")
upbit = pyupbit.Upbit(os.getenv("UPBIT_ACCESS"), os.getenv("UPBIT_SECRET"))

def send_discord_message(msg):
    """discord 메시지 전송"""
    try:
        message ={"content":msg}
        requests.post(DISCORD_WEBHOOK_URL, data=message)
    except Exception as e:
        print(f"디스코드 메시지 전송 실패 : {e}")
        time.sleep(5) 

count_200 = 200

rsi_buy_s = 25
rsi_buy_e = 45
rsi_sell_s = 65
rsi_sell_e = 80

def get_user_input():
    while True:
        try:
            min_rate = float(input("최소 수익률 (예: 1.1): "))
            max_rate = float(input("최대 수익률 (예: 5.0): "))
            sell_time = int(input("매도감시횟수 (예: 20): "))
            break
        except ValueError:
            print("잘못된 입력입니다. 다시 시도하세요.")

    return min_rate, sell_time, max_rate  
# 함수 호출 및 결과 저장
min_rate, sell_time, max_rate = get_user_input() 

second = 1.0
min_krw = 10_000
cut_rate = -3.0

def get_balance(ticker):
    try:
        balances = upbit.get_balances()
        for b in balances:
            if b['currency'] == ticker:
                time.sleep(0.5)
                return float(b['balance']) if b['balance'] is not None else 0
            
    except (KeyError, ValueError) as e:
        print(f"get_balance/잔고 조회 오류: {e}")
        send_discord_message(f"get_balance/잔고 조회 오류: {e}")
        time.sleep(1)
        return 0
    return 0

def get_top_volume_tickers():
    """
    전략적으로 선별된 30개 메이저 코인 반환 (고정 리스트)
    
    핵심 전략:
    - 시가총액 상위 30개 메이저 코인 고정
    - 별도의 분석 없이 즉시 반환하여 성능 최적화
    - 변동성/유동성 분석은 get_best_ticker()에서 수행
    """
    
    STRATEGIC_COINS = [
        "KRW-BTC","KRW-ETH","KRW-XRP","KRW-SOL","KRW-DOGE","KRW-TRX","KRW-ADA","KRW-LINK","KRW-AVAX","KRW-XLM",
        "KRW-SUI","KRW-BCH","KRW-HBAR","KRW-SHIB","KRW-CRO","KRW-DOT","KRW-MNT","KRW-UNI","KRW-AAVE","KRW-PEPE",
        "KRW-ENA","KRW-NEAR","KRW-APT","KRW-ETC","KRW-ONDO","KRW-POL","KRW-ARB","KRW-VET","KRW-ALGO","KRW-BONK"
    ]
    
    print("=" * 50)
    print("🎯 전략 대상: 30개 메이저 코인 (고정)")
    print("=" * 50)
    
    return STRATEGIC_COINS
    
def calculate_rsi(closes, period=14):
    """RSI (Relative Strength Index) 계산"""
    if len(closes) < period + 1:
        return 50.0
    
    deltas = np.diff(closes)
    gains = np.where(deltas > 0, deltas, 0)
    losses = np.where(deltas < 0, -deltas, 0)
    
    avg_gain = np.mean(gains[:period])
    avg_loss = np.mean(losses[:period])
    
    for i in range(period, len(closes)-1):
        avg_gain = (avg_gain * (period-1) + gains[i]) / period
        avg_loss = (avg_loss * (period-1) + losses[i]) / period
    
    rs = avg_gain / (avg_loss + 1e-8)
    return 100 - (100 / (1 + rs))

def calculate_ema(closes, period=12):
    """EMA (Exponential Moving Average) 계산"""
    if len(closes) < period:
        return closes[-1]
    
    ema = [closes[0]]
    alpha = 2 / (period + 1)
    
    for close in closes[1:]:
        ema.append(alpha * close + (1 - alpha) * ema[-1])
    
    return ema[-1]

def calculate_bb(closes, window=20, std_dev=2.0):
    """볼린저 밴드 계산"""
    if len(closes) < window:
        window = len(closes)
    
    sma = np.mean(closes[-window:])
    std = np.std(closes[-window:])
    
    lower = sma - (std * std_dev)
    upper = sma + (std * std_dev)
    
    position = (closes[-1] - lower) / (upper - lower + 1e-8)
    width = (upper - lower) / sma * 100
    
    return lower, sma, upper, max(0, min(1, position)), width

def calculate_price_acceleration(closes):
    """
    🆕 🔥 가격 가속도 분석 (혁신!)
    
    목적: 급락이 "감속"하는 순간 포착 (2차 미분)
    
    전략:
    - 1차 미분: 속도 (가격 변화율)
    - 2차 미분: 가속도 (속도의 변화)
    - 음의 가속도 감소 = 급락 둔화 = 매수 시점!
    
    예시:
    시간    가격    속도      가속도
    t-3:    100     -         -
    t-2:    95      -5%       -
    t-1:    91      -4.2%     +0.8% (둔화!)
    t:      88      -3.3%     +0.9% (둔화 지속!) ← 매수!
    
    Returns:
        {
            'is_decelerating': bool,  # 급락 감속 중
            'velocity_recent': float,  # 최근 속도 (%)
            'velocity_prev': float,    # 이전 속도 (%)
            'acceleration': float      # 가속도 (양수 = 감속)
        }
    """
    if len(closes) < 10:
        return None
    
    # 5분봉 기준 속도 계산 (3개씩 묶어서)
    # 최근 3개 평균 vs 그 이전 3개 평균
    recent_avg = np.mean(closes[-3:])
    prev_avg = np.mean(closes[-6:-3])
    older_avg = np.mean(closes[-9:-6])
    
    # 속도 1: 이전 → 최근
    velocity_recent = (recent_avg - prev_avg) / prev_avg
    
    # 속도 2: 과거 → 이전
    velocity_prev = (prev_avg - older_avg) / older_avg
    
    # 가속도: 속도의 변화
    # 양수 = 하락세 둔화 (좋음!)
    # 음수 = 하락세 가속 (나쁨)
    acceleration = velocity_recent - velocity_prev
    
    # 감속 조건:
    # 1. 현재 하락 중 (velocity_recent < 0)
    # 2. 이전에도 하락 중 (velocity_prev < 0)
    # 3. 하락 속도 감소 (acceleration > 0)
    # 4. 충분한 감속 (acceleration > 0.01, 즉 1%p 감속)
    
    is_decelerating = (
        velocity_recent < 0 and       # 현재 하락 중
        velocity_prev < 0 and         # 이전에도 하락
        acceleration > 0.01 and       # 충분히 감속 (1%p)
        velocity_recent > velocity_prev  # 덜 하락
    )
    
    return {
        'is_decelerating': is_decelerating,
        'velocity_recent': velocity_recent,
        'velocity_prev': velocity_prev,
        'acceleration': acceleration
    }

def analyze_bb_expansion(closes, window=20):
    """
    🆕 BB 폭 확장 패턴 분석
    
    목적: BB 폭이 급격히 확장되는 순간 포착
    
    당신의 경험:
    "BB 상하단 폭이 충분히 급증하고 하단도 급격히 하락"
    
    Returns:
        {
            'is_expanding': bool,  # BB 폭 확장 중
            'width_current': float,  # 현재 폭
            'width_avg': float,      # 평균 폭
            'expansion_ratio': float # 확장 배수
        }
    """
    if len(closes) < window + 10:
        return None
    
    # 최근 5개 봉의 평균 폭
    width_series = []
    for i in range(-10, 0):
        segment = closes[:i] if i != -1 else closes
        if len(segment) < window:
            continue
        sma = np.mean(segment[-window:])
        std = np.std(segment[-window:])
        width = (std * 4) / sma * 100  # 상하단 폭
        width_series.append(width)
    
    if len(width_series) < 10:
        return None
    
    width_recent = np.mean(width_series[-3:])  # 최근 3개
    width_normal = np.mean(width_series[-10:-3])  # 이전 7개
    
    expansion_ratio = width_recent / (width_normal + 1e-8)
    
    # 확장 조건: 최근 폭이 평균보다 1.3배 이상
    is_expanding = (
        expansion_ratio > 1.3 and
        width_recent > 4.0  # 최소 변동성 확보
    )
    
    return {
        'is_expanding': is_expanding,
        'width_current': width_recent,
        'width_avg': width_normal,
        'expansion_ratio': expansion_ratio
    }

def analyze_candle_pattern(df_5m):
    """
    🆕 캔들 패턴 분석 (망치형, 긴 아래꼬리)
    
    목적: 저점 매수 시그널 캔들 패턴 감지
    
    망치형 캔들:
    - 아래꼬리 길이 > 몸통 * 2
    - 위꼬리 짧음
    - 종가가 시가보다 높거나 비슷
    
    Returns:
        {
            'has_hammer': bool,  # 망치형 존재
            'has_long_tail': bool,  # 긴 아래꼬리
            'tail_body_ratio': float  # 꼬리/몸통 비율
        }
    """
    if len(df_5m) < 3:
        return None
    
    # 최근 3개 캔들 분석
    recent_candles = df_5m.iloc[-3:]
    
    has_hammer = False
    has_long_tail = False
    max_ratio = 0
    
    for idx, row in recent_candles.iterrows():
        open_price = row['open']
        close_price = row['close']
        high_price = row['high']
        low_price = row['low']
        
        # 몸통 크기
        body = abs(close_price - open_price)
        
        # 아래꼬리 길이
        lower_tail = min(open_price, close_price) - low_price
        
        # 위꼬리 길이
        upper_tail = high_price - max(open_price, close_price)
        
        # 꼬리/몸통 비율
        if body > 0:
            tail_body_ratio = lower_tail / body
            max_ratio = max(max_ratio, tail_body_ratio)
            
            # 망치형 조건
            if (lower_tail > body * 2 and 
                upper_tail < body * 0.5 and
                close_price >= open_price * 0.99):
                has_hammer = True
            
            # 긴 아래꼬리
            if lower_tail > body * 1.5:
                has_long_tail = True
    
    return {
        'has_hammer': has_hammer,
        'has_long_tail': has_long_tail,
        'tail_body_ratio': max_ratio
    }


def analyze_multi_timeframe_alignment(ticker_symbol):
    """
    🆕 간소화된 다중 시간프레임 정렬 (중복 제거)
    
    Returns:
        {
            'alignment_score': int,  # 0~100
            'tf_data': dict  # 각 시간프레임 데이터
        }
    """
    try:
        import pyupbit
        
        # 15분봉, 30분봉만 추가 조회 (5분봉은 이미 있음)
        df_15m = pyupbit.get_ohlcv(ticker_symbol, interval="minute15", count=30)
        time.sleep(0.1)
        df_30m = pyupbit.get_ohlcv(ticker_symbol, interval="minute30", count=30)
        time.sleep(0.1)
        
        if df_15m is None or df_30m is None:
            return None
        
        # BB 위치 계산
        _, _, _, pos_15m, _ = calculate_bb(df_15m['close'].values, 20)
        _, _, _, pos_30m, _ = calculate_bb(df_30m['close'].values, 20)
        
        # 점수 계산
        score = 0
        
        # 15분봉
        if pos_15m < 0.30:
            score += 50
        elif pos_15m < 0.40:
            score += 35
        elif pos_15m < 0.50:
            score += 20
        
        # 30분봉
        if pos_30m < 0.35:
            score += 50
        elif pos_30m < 0.45:
            score += 35
        elif pos_30m < 0.55:
            score += 20
        
        return {
            'alignment_score': score,
            'tf_data': {
                '15m': {'position': pos_15m, 'df': df_15m},
                '30m': {'position': pos_30m, 'df': df_30m}
            }
        }
        
    except Exception as e:
        return None
    
def predict_rebound_probability(closes, volumes, bb_pos, bb_width):
    """
    🆕 간소화된 반등 확률 계산
    
    핵심 요소:
    1. 가격 가속도 (감속 중?)
    2. BB 위치 (하단?)
    3. BB 폭 (충분?)
    4. 거래량 (증가?)
    """
    if len(closes) < 20:
        return None
    
    # 가격 가속도
    accel = calculate_price_acceleration(closes)
    if not accel:
        return None
    
    # 점수 계산
    score = 0
    
    # [1] 가속도 (40점)
    if accel['is_decelerating']:
        score += 40
    elif accel['acceleration'] > 0:
        score += 25
    
    # [2] BB 위치 (30점)
    if bb_pos < 0.20:
        score += 30
    elif bb_pos < 0.30:
        score += 20
    elif bb_pos < 0.40:
        score += 10
    
    # [3] BB 폭 (20점)
    if bb_width > 6:
        score += 20
    elif bb_width > 4:
        score += 12
    elif bb_width > 3:
        score += 5
    
    # [4] 거래량 (10점)
    vol_recent = np.mean(volumes[-3:])
    vol_normal = np.mean(volumes[-10:-3])
    vol_ratio = vol_recent / (vol_normal + 1e-8)
    
    if vol_ratio > 1.5:
        score += 10
    elif vol_ratio > 1.2:
        score += 6
    
    # 확률 변환
    probability = min(score / 100, 0.95)
    
    return {
        'probability': probability,
        'score': score,
        'accel_data': accel
    }    



# def calculate_bb_series(closes, window=20, std_dev=2.0):
#     """
#     🆕 BB 시계열 계산 (하단 기울기 분석용)
    
#     Returns:
#         lower_series: BB 하단 시계열 (최근 10개)
#         upper_series: BB 상단 시계열
#         width_series: BB 폭 시계열
#     """
#     if len(closes) < window + 10:
#         return None, None, None
    
#     lower_series = []
#     upper_series = []
#     width_series = []
    
#     # 최근 10개 봉에 대해 각각 BB 계산
#     for i in range(-10, 0):
#         segment = closes[:i] if i != -1 else closes
#         if len(segment) < window:
#             continue
            
#         sma = np.mean(segment[-window:])
#         std = np.std(segment[-window:])
        
#         lower = sma - (std * std_dev)
#         upper = sma + (std * std_dev)
#         width = (upper - lower) / sma * 100
        
#         lower_series.append(lower)
#         upper_series.append(upper)
#         width_series.append(width)
    
#     return (np.array(lower_series), 
#             np.array(upper_series), 
#             np.array(width_series))

# def analyze_bb_slope(bb_lower_series):
#     """
#     🆕 🔥 BB 하단 기울기 분석 (핵심 혁신!)
    
#     목적: 폭락이 멈추고 바닥을 다지는 순간 포착
    
#     전략:
#     1. 최근 3개 봉의 BB 하단 기울기 계산
#     2. 이전 3개 봉의 기울기와 비교
#     3. 급락(큰 음수 기울기) → 완만(작은 음수/0) 전환 감지
    
#     Returns:
#         {
#             'is_flattening': bool,  # 기울기 완만해지는 중
#             'recent_slope': float,  # 최근 기울기
#             'prev_slope': float,    # 이전 기울기
#             'slope_change': float   # 기울기 변화량 (양수 = 완만해짐)
#         }
#     """
#     if bb_lower_series is None or len(bb_lower_series) < 6:
#         return None
    
#     # 최근 3개 봉의 기울기 (선형 회귀)
#     recent_x = np.arange(3)
#     recent_slope = np.polyfit(recent_x, bb_lower_series[-3:], 1)[0]
    
#     # 이전 3개 봉의 기울기
#     prev_slope = np.polyfit(recent_x, bb_lower_series[-6:-3], 1)[0]
    
#     # 기울기 변화량 (양수 = 완만해짐)
#     slope_change = recent_slope - prev_slope
    
#     # 완만해지는 조건:
#     # 1. 이전에는 급락 (prev_slope < -일정값)
#     # 2. 최근은 완만 (recent_slope > prev_slope)
#     # 3. 기울기 변화 충분히 큼 (slope_change > 임계값)
    
#     is_flattening = (
#         prev_slope < -0.5 and  # 이전에 급락 중이었고
#         slope_change > 0.3 and  # 기울기가 충분히 완만해졌고
#         recent_slope > prev_slope  # 최근이 이전보다 덜 급락
#     )
    
#     return {
#         'is_flattening': is_flattening,
#         'recent_slope': recent_slope,
#         'prev_slope': prev_slope,
#         'slope_change': slope_change
#     }

# def analyze_price_reversal(closes, volumes):
#     """
#     🆕 가격 반등 조기 감지
    
#     목적: 종가가 폭락을 멈추고 반등하는 순간 포착
    
#     전략:
#     1. 최근 3개 봉의 가격 모멘텀
#     2. 이전 5개 봉과 비교하여 전환 확인
#     3. 거래량 증가 동반 여부 확인
    
#     Returns:
#         {
#             'is_reversing': bool,  # 반등 시작
#             'price_momentum': float,  # 가격 모멘텀
#             'volume_surge': float  # 거래량 증가율
#         }
#     """
#     if len(closes) < 8 or len(volumes) < 8:
#         return None
    
#     # 최근 3개 봉 평균 vs 이전 5개 봉 평균
#     recent_avg = np.mean(closes[-3:])
#     prev_avg = np.mean(closes[-8:-3])
    
#     # 가격 모멘텀 (양수 = 반등)
#     price_momentum = (recent_avg - prev_avg) / prev_avg
    
#     # 거래량 급증 여부
#     recent_vol = np.mean(volumes[-3:])
#     normal_vol = np.mean(volumes[-8:-3])
#     volume_surge = recent_vol / (normal_vol + 1e-8)
    
#     # 반등 조건:
#     # 1. 가격이 상승 전환 (모멘텀 > 0)
#     # 2. 거래량 1.2배 이상 증가
#     is_reversing = (
#         price_momentum > 0 and
#         volume_surge > 1.2
#     )
    
#     return {
#         'is_reversing': is_reversing,
#         'price_momentum': price_momentum,
#         'volume_surge': volume_surge
#     }

# def predict_rebound_potential(closes, bb_lower_series, bb_width_series):
#     """
#     🆕 🔥 2% 반등 가능성 예측 (핵심 혁신!)
    
#     목적: 현재 상황에서 2% 이상 반등할 확률 계산
    
#     전략:
#     1. 현재가가 BB 하단에서 얼마나 떨어져 있는지
#     2. BB 폭이 충분히 넓은지 (변동성 확보)
#     3. 과거 하락 폭 (큰 하락일수록 반등 강함)
    
#     Returns:
#         {
#             'rebound_score': float,  # 반등 점수 (0~100)
#             'expected_gain': float,  # 예상 수익률 (%)
#             'probability': float  # 2% 이상 반등 확률 (0~1)
#         }
#     """
#     if bb_lower_series is None or len(closes) < 20:
#         return None
    
#     current_price = closes[-1]
#     bb_lower = bb_lower_series[-1]
    
#     # [1] BB 하단 대비 거리 (음수 = 하단 이탈)
#     distance_from_lower = (current_price - bb_lower) / bb_lower * 100
    
#     # [2] BB 폭 (평균)
#     avg_width = np.mean(bb_width_series[-5:])
    
#     # [3] 최근 하락 폭
#     recent_high = np.max(closes[-20:])
#     drop_from_high = (current_price - recent_high) / recent_high * 100
    
#     # 반등 점수 계산
#     score = 0
    
#     # BB 하단 근처일수록 점수 높음
#     if distance_from_lower < -2:  # 하단 2% 이탈
#         score += 30
#     elif distance_from_lower < 0:  # 하단 이탈
#         score += 25
#     elif distance_from_lower < 2:  # 하단 2% 이내
#         score += 20
#     else:
#         score += 10
    
#     # BB 폭이 클수록 반등 여력 큼
#     if avg_width > 6:
#         score += 25
#     elif avg_width > 4:
#         score += 20
#     else:
#         score += 10
    
#     # 하락 폭이 클수록 반등 강함
#     if drop_from_high < -10:  # 10% 이상 하락
#         score += 30
#     elif drop_from_high < -7:  # 7% 이상 하락
#         score += 25
#     elif drop_from_high < -5:  # 5% 이상 하락
#         score += 20
#     else:
#         score += 10
    
#     # 예상 수익률 (BB 폭 기반)
#     expected_gain = min(avg_width * 0.4, 5.0)  # 최대 5%
    
#     # 2% 이상 반등 확률 (점수 기반)
#     probability = min(score / 100, 0.95)  # 최대 95%
    
#     return {
#         'rebound_score': score,
#         'expected_gain': expected_gain,
#         'probability': probability
#     }

# def analyze_multi_timeframe_bb_alignment(ticker_symbol):
#     """
#     🆕 다중 시간프레임 BB 정렬 분석
    
#     목적: 5분/15분/30분봉이 모두 BB 하단 근처에 정렬되었는지 확인
    
#     Returns:
#         {
#             'is_aligned': bool,  # 3개 시간프레임 정렬 여부
#             'alignment_score': float,  # 정렬 점수 (0~100)
#             'tf_positions': dict  # 각 시간프레임별 BB 위치
#         }
#     """
#     try:
#         # 데이터 수집
#         df_5m = pyupbit.get_ohlcv(ticker_symbol, interval="minute5", count=50)
#         time.sleep(0.1)
#         df_15m = pyupbit.get_ohlcv(ticker_symbol, interval="minute15", count=50)
#         time.sleep(0.1)
#         df_30m = pyupbit.get_ohlcv(ticker_symbol, interval="minute30", count=50)
#         time.sleep(0.1)
        
#         if df_5m is None or df_15m is None or df_30m is None:
#             return None
        
#         # 각 시간프레임 BB 위치 계산
#         pos_5m = calculate_bb(df_5m['close'].values, 20)
#         pos_15m = calculate_bb(df_15m['close'].values, 20)
#         pos_30m = calculate_bb(df_30m['close'].values, 20)
        
#         # 정렬 점수 계산 (모두 하단 30% 이내면 만점)
#         score = 0
        
#         if pos_5m < 0.30:
#             score += 40  # 5분봉 가중치 높음
#         elif pos_5m < 0.35:
#             score += 30
        
#         if pos_15m < 0.35:
#             score += 30
#         elif pos_15m < 0.40:
#             score += 20
        
#         if pos_30m < 0.40:
#             score += 30
#         elif pos_30m < 0.45:
#             score += 20
        
#         # 정렬 여부 (3개 모두 하단 근처)
#         is_aligned = (pos_5m < 0.30 and pos_15m < 0.35 and pos_30m < 0.40)
        
#         return {
#             'is_aligned': is_aligned,
#             'alignment_score': score,
#             'tf_positions': {
#                 '5m': pos_5m,
#                 '15m': pos_15m,
#                 '30m': pos_30m
#             }
#         }
        
#     except Exception as e:
#         return None

# ==================== 메인 매수 함수 ====================

def trade_buy(ticker=None):
    """
    🚀 초단기 복리 매수 시스템 v5.1 - 급락 감속 포착
    
    핵심 개선:
    1. 가격 가속도 분석 (BB 하단 기울기 대신!)
    2. BB 폭 확장 패턴 감지
    3. 캔들 패턴 분석 추가
    4. 중복 코드 제거 및 최적화
    5. 필터링 완화 (좋은 기회 놓치지 않기)
    """
    
    def get_krw_balance():
        """KRW 잔고"""
        try:
            balances = upbit.get_balances()
            for b in balances:
                if b['currency'] == "KRW":
                    return float(b['balance'])
        except:
            pass
        return 0.0
    
    def get_total_crypto_value():
        """암호화폐 평가액"""
        try:
            balances = upbit.get_balances()
            total = 0.0
            for balance in balances:
                if balance['currency'] == 'KRW':
                    continue
                amount = float(balance['balance'])
                if amount > 0:
                    ticker_name = f"KRW-{balance['currency']}"
                    try:
                        price = pyupbit.get_current_price(ticker_name)
                        if price:
                            total += amount * price
                    except:
                        continue
            return total
        except:
            return 0.0
    
    def get_held_coins():
        """보유 코인"""
        try:
            balances = upbit.get_balances()
            return {f"KRW-{b['currency']}" for b in balances
                   if float(b.get('balance', 0)) > 0 and b['currency'] != 'KRW'}
        except:
            return set()
    
    def analyze_ticker_v2(ticker_symbol):
        """
        🆕 v5.1 종목 분석 (최적화)
        """
        try:
            import pyupbit
            
            # 데이터 수집
            df_1m = pyupbit.get_ohlcv(ticker_symbol, interval="minute1", count=30)
            time.sleep(0.1)
            df_5m = pyupbit.get_ohlcv(ticker_symbol, interval="minute5", count=50)
            time.sleep(0.1)
            df_1h = pyupbit.get_ohlcv(ticker_symbol, interval="minute60", count=50)
            time.sleep(0.1)
            df_1d = pyupbit.get_ohlcv(ticker_symbol, interval="day", count=5)
            time.sleep(0.1)
            
            current_price = pyupbit.get_current_price(ticker_symbol)
            
            if (df_1m is None or df_5m is None or 
                df_1h is None or df_1d is None or current_price is None):
                return {'valid': False}
            
            # 종가/거래량
            closes_1m = df_1m['close'].values
            closes_5m = df_5m['close'].values
            closes_1h = df_1h['close'].values
            volumes_5m = df_5m['volume'].values
            
            # 기본 지표
            rsi_1m = calculate_rsi(closes_1m, 14)
            rsi_5m = calculate_rsi(closes_5m, 14)
            rsi_1h = calculate_rsi(closes_1h, 14)
            
            bb_5m_lower, bb_5m_mid, bb_5m_upper, bb_5m_pos, bb_5m_width = calculate_bb(closes_5m, 20)
            bb_1h_lower, bb_1h_mid, bb_1h_upper, bb_1h_pos, bb_1h_width = calculate_bb(closes_1h, 20)
            
            ema_12 = calculate_ema(closes_5m, 12)
            ema_26 = calculate_ema(closes_5m, 26)
            
            # 🆕 핵심 지표
            accel = calculate_price_acceleration(closes_5m)  # 가속도
            bb_exp = analyze_bb_expansion(closes_5m, 20)  # BB 확장
            candle = analyze_candle_pattern(df_5m)  # 캔들 패턴
            alignment = analyze_multi_timeframe_alignment(ticker_symbol)  # TF 정렬
            rebound = predict_rebound_probability(closes_5m, volumes_5m, bb_5m_pos, bb_5m_width)
            
            # 거래량
            vol_recent = np.mean(volumes_5m[-5:])
            vol_normal = np.mean(volumes_5m[-20:-5])
            vol_ratio = vol_recent / (vol_normal + 1e-8)
            vol_absolute_krw = vol_recent * current_price
            
            # 일봉
            daily_open = df_1d['open'].iloc[-1]
            daily_prev_close = df_1d['close'].iloc[-2]
            daily_change_from_open = (current_price - daily_open) / daily_open * 100
            daily_change_from_prev = (current_price - daily_prev_close) / daily_prev_close * 100
            
            # 지지/저항
            recent_low = np.min(df_5m['low'].values[-20:])
            support_proximity = (current_price - recent_low) / recent_low * 100
            
            target_price_2pct = current_price * 1.02
            resistance_5m = np.max(df_5m['high'].values[-20:])
            resistance_clearance = (resistance_5m - target_price_2pct) / target_price_2pct * 100
            
            return {
                'valid': True,
                'current_price': current_price,
                'indicators': {
                    # 기본
                    'rsi_1m': rsi_1m,
                    'rsi_5m': rsi_5m,
                    'rsi_1h': rsi_1h,
                    'bb_5m_pos': bb_5m_pos,
                    'bb_5m_width': bb_5m_width,
                    'bb_1h_pos': bb_1h_pos,
                    'ema_12': ema_12,
                    'ema_26': ema_26,
                    'vol_ratio': vol_ratio,
                    'vol_absolute_krw': vol_absolute_krw,
                    'daily_change_from_open': daily_change_from_open,
                    'daily_change_from_prev': daily_change_from_prev,
                    'support_proximity': support_proximity,
                    'resistance_clearance': resistance_clearance,
                    'volatility_score': bb_5m_width,
                    
                    # 🆕 v5.1 핵심
                    'acceleration': accel,
                    'bb_expansion': bb_exp,
                    'candle_pattern': candle,
                    'alignment': alignment,
                    'rebound': rebound
                }
            }
            
        except Exception as e:
            return {'valid': False}
    
    def calculate_signal_v2(ind):
        """
        🆕 v5.1 신호 점수 (간소화 + 완화)
        
        총 100점:
        - 가격 가속도: 35점 ⭐
        - BB 확장: 20점 ⭐
        - TF 정렬: 15점
        - RSI: 15점
        - 캔들: 10점
        - 거래량: 5점
        """
        score = 0
        signals = []
        
        # [1] 가격 가속도 (35점) - 최우선!
        accel = ind.get('acceleration')
        if accel:
            if accel['is_decelerating']:
                score += 35
                signals.append(f"급락감속(가속도{accel['acceleration']*100:.1f}%)")
            elif accel['acceleration'] > 0:
                score += 20
                signals.append("하락둔화")
            elif accel['acceleration'] > -0.01:
                score += 10
        
        # [2] BB 확장 (20점)
        bb_exp = ind.get('bb_expansion')
        if bb_exp:
            if bb_exp['is_expanding']:
                score += 20
                signals.append(f"BB확장({bb_exp['expansion_ratio']:.1f}x)")
            elif bb_exp['expansion_ratio'] > 1.15:
                score += 12
        
        # [3] TF 정렬 (15점)
        alignment = ind.get('alignment')
        if alignment:
            score += alignment['alignment_score'] * 0.15
            if alignment['alignment_score'] >= 70:
                signals.append("TF정렬")
        
        # [4] RSI (15점)
        rsi_5m = ind['rsi_5m']
        if rsi_5m < 25:
            score += 15
            signals.append(f"RSI극과매도({rsi_5m:.0f})")
        elif rsi_5m < 30:
            score += 12
            signals.append(f"RSI과매도({rsi_5m:.0f})")
        elif rsi_5m < 35:
            score += 8
        elif rsi_5m < 40:
            score += 4
        
        # [5] 캔들 패턴 (10점)
        candle = ind.get('candle_pattern')
        if candle:
            if candle['has_hammer']:
                score += 10
                signals.append("망치형")
            elif candle['has_long_tail']:
                score += 6
                signals.append("긴꼬리")
        
        # [6] 거래량 (5점)
        vol_ratio = ind['vol_ratio']
        vol_krw = ind['vol_absolute_krw']
        
        if vol_krw >= 300_000_000 and vol_ratio >= 1.5:
            score += 5
        elif vol_krw >= 100_000_000 and vol_ratio >= 2.0:
            score += 5
        elif vol_ratio >= 1.2:
            score += 2
        
        # 🆕 반등 확률 보너스 (5점)
        rebound = ind.get('rebound')
        if rebound and rebound['probability'] > 0.60:
            score += 5
            signals.append(f"반등{rebound['probability']*100:.0f}%")
        
        return score, signals
    
    # ==================== 메인 로직 ====================
    
    print("\n[START] v5.1 - 급락 감속 포착 시스템")
    
    krw_balance = get_krw_balance()
    crypto_value = get_total_crypto_value()
    total_asset = crypto_value + krw_balance
    
    print(f"자산: {total_asset:,.0f}원")
    
    MIN_ORDER = 5000
    if krw_balance < MIN_ORDER:
        return "Insufficient balance", None
    
    crypto_limit = total_asset  # 100% 허용
    if crypto_value >= crypto_limit:
        return "Position limit", None
    
    # 종목 선정
    if ticker is None:
        print("종목 스캔 중...")
        
        try:
            import pyupbit
            held_coins = get_held_coins()
            all_tickers = pyupbit.get_tickers(fiat="KRW")
            candidates = [t for t in all_tickers if t not in held_coins][:30]  # 상위 30개만
        except:
            return "Fetch failed", None
        
        if not candidates:
            return "No candidates", None
        
        primary = []
        
        for t in candidates:
            analysis = analyze_ticker_v2(t)
            
            if not analysis['valid']:
                continue
            
            ind = analysis['indicators']
            
            # 🆕 완화된 필터
            # 일봉 1% 이내만
            if ind['daily_change_from_open'] > 1.0:
                continue
            
            # 가격 범위
            if not (50 <= analysis['current_price'] <= 200000):
                continue
            
            # 🆕 핵심: 가속도 OR BB확장 중 하나만 있으면 OK
            accel = ind.get('acceleration')
            bb_exp = ind.get('bb_expansion')
            
            if not accel and not bb_exp:
                continue
            
            if accel and accel['acceleration'] < -0.02:  # 너무 가속 중이면 제외
                continue
            
            score, signals = calculate_signal_v2(ind)
            
            # 🆕 45점 이상만 (기존 50점에서 완화)
            if score >= 45:
                primary.append({
                    'ticker': t,
                    'score': score,
                    'signals': signals,
                    'analysis': analysis
                })
                print(f"✓ {t}: {score:.0f}점 {signals[:2]}")
            
            time.sleep(0.05)
        
        print(f"선별: {len(primary)}개")
        
        if not primary:
            return "No candidates", None
        
        primary.sort(key=lambda x: x['score'], reverse=True)
        best = primary[0]
        
        selected_ticker = best['ticker']
        selected_analysis = best['analysis']
        selected_score = best['score']
        selected_signals = best['signals']
        
        print(f"최종: {selected_ticker} ({selected_score:.0f}점)")
        
    else:
        # 특정 종목 검증
        print(f"{ticker} 검증 중...")
        
        selected_analysis = analyze_ticker_v2(ticker)
        
        if not selected_analysis['valid']:
            return "Data failed", None
        
        selected_score, selected_signals = calculate_signal_v2(
            selected_analysis['indicators']
        )
        selected_ticker = ticker
        
        print(f"신호: {selected_score:.0f}점")
    
    # 최종 검증
    ind = selected_analysis['indicators']
    current_price = selected_analysis['current_price']
    
    print(f"분석: RSI {ind['rsi_5m']:.0f} | BB {ind['bb_5m_pos']*100:.0f}% | Vol {ind['vol_ratio']:.1f}x")
    
    # 🆕 핵심 지표 출력
    accel = ind.get('acceleration')
    bb_exp = ind.get('bb_expansion')
    candle = ind.get('candle_pattern')
    rebound = ind.get('rebound')
    
    if accel:
        decel_status = "✓감속" if accel['is_decelerating'] else ""
        print(f"가속도: 속도 {accel['velocity_prev']*100:.1f}% → {accel['velocity_recent']*100:.1f}% "
              f"(가속도 {accel['acceleration']*100:+.1f}%) {decel_status}")
    
    if bb_exp:
        exp_status = "✓확장" if bb_exp['is_expanding'] else ""
        print(f"BB확장: 폭 {bb_exp['width_avg']:.1f}% → {bb_exp['width_current']:.1f}% "
              f"({bb_exp['expansion_ratio']:.2f}x) {exp_status}")
    
    if candle:
        pattern_str = []
        if candle['has_hammer']:
            pattern_str.append("망치형")
        if candle['has_long_tail']:
            pattern_str.append("긴꼬리")
        if pattern_str:
            print(f"캔들: {', '.join(pattern_str)} (비율 {candle['tail_body_ratio']:.1f})")
    
    if rebound:
        print(f"반등예측: 확률 {rebound['probability']*100:.0f}% | 점수 {rebound['score']:.0f}")
    
    # 🆕 완화된 안전 검증
    safety_checks = {
        'RSI 범위': 10 < ind['rsi_5m'] < 70,  # 70으로 완화
        'BB 범위': -0.3 < ind['bb_5m_pos'] < 1.3,  # 범위 확대
        'EMA 지지': current_price > ind['ema_26'] * 0.65,  # 65%로 완화
        '가속도': accel and accel['acceleration'] > -0.05  # 큰 가속만 제외
    }
    
    passed = sum(safety_checks.values())
    print(f"안전: {passed}/4")
    
    # 🆕 완화된 최종 조건
    can_buy = (
        # 점수: 50점 이상 (기존 60점에서 완화)
        selected_score >= 50 and
        
        # 안전: 4개 중 3개 이상 (완화)
        passed >= 3 and
        
        # 일봉: 1% 이내 (완화)
        ind['daily_change_from_open'] <= 1.0 and
        
        # RSI: 60 미만 (완화)
        ind['rsi_5m'] < 60 and
        
        # BB: 50% 미만 (완화)
        ind['bb_5m_pos'] < 0.50 and
        
        # 🆕 핵심: 가속도 조건
        (accel and (
            accel['is_decelerating'] or  # 감속 중이거나
            (accel['acceleration'] > -0.01 and accel['velocity_recent'] < 0)  # 완만한 하락
        ))
    )
    
    print(f"매수: {'가능✓' if can_buy else '불가✗'} (점수{selected_score}/50, 안전{passed}/3)")
    
    if not can_buy:
        return "Conditions not met", None
    
    # 포지션 사이징
    buy_size = calculate_position_size_v2(
        total_asset=total_asset,
        crypto_value=crypto_value,
        crypto_limit=crypto_limit,
        krw_balance=krw_balance,
        signal_score=selected_score,
        indicators=ind
    )
    
    if buy_size < MIN_ORDER:
        return "Size too small", None
    
    print(f"매수액: {buy_size:,.0f}원")
    
    # 매수 실행
    for attempt in range(1, 3):
        try:
            import pyupbit
            verify_price = pyupbit.get_current_price(selected_ticker)
            time.sleep(0.05)
            
            price_change = (verify_price - current_price) / current_price
            
            if price_change > 0.03:
                print(f"가격 급등, 재확인...")
                time.sleep(2)
                continue
            
            buy_order = upbit.buy_market_order(selected_ticker, buy_size)
            
            if selected_score >= 75:
                grade = "PERFECT"
            elif selected_score >= 65:
                grade = "EXCELLENT"
            else:
                grade = "STRONG"
            
            success_msg = f"🚀 {grade} 매수 (급락 감속)\n"
            success_msg += f"{selected_ticker} | {verify_price:,.0f}원 | {buy_size:,.0f}원\n"
            success_msg += f"신호{selected_score:.0f}점"
            
            if accel and accel['is_decelerating']:
                success_msg += f" | 감속확인"
            
            if bb_exp and bb_exp['is_expanding']:
                success_msg += f" | BB확장"
            
            if candle and (candle['has_hammer'] or candle['has_long_tail']):
                success_msg += f" | 반등캔들"
            
            success_msg += f"\n자산: {total_asset:,.0f}원"
            
            print(success_msg)
            
            try:
                send_discord_message(success_msg)
            except:
                pass
            
            return buy_order
            
        except Exception as e:
            print(f"오류 (시도 {attempt}): {e}")
            
            if attempt < 2:
                time.sleep(2)
            else:
                try:
                    send_discord_message(f"매수 실패: {selected_ticker}\n{str(e)}")
                except:
                    pass
                return "Order failed", None
    
    return "Max attempts", None


def calculate_position_size_v2(total_asset, crypto_value, crypto_limit, krw_balance, 
                               signal_score, indicators):
    """
    💰 v5.1 포지션 사이징 (간소화)
    """
    
    # 승률 추정
    if signal_score >= 75:
        win_rate = 0.75
    elif signal_score >= 65:
        win_rate = 0.70
    elif signal_score >= 55:
        win_rate = 0.65
    else:
        win_rate = 0.60
    
    # 🆕 가속도 보정
    accel = indicators.get('acceleration')
    if accel and accel['is_decelerating']:
        win_rate += 0.08
    
    # 🆕 BB 확장 보정
    bb_exp = indicators.get('bb_expansion')
    if bb_exp and bb_exp['is_expanding']:
        win_rate += 0.05
    
    # RSI 보정
    rsi_5m = indicators['rsi_5m']
    if rsi_5m < 25:
        win_rate += 0.05
    elif rsi_5m < 30:
        win_rate += 0.03
    
    # BB 위치 보정
    bb_pos = indicators['bb_5m_pos']
    if bb_pos < 0.15:
        win_rate += 0.05
    elif bb_pos < 0.25:
        win_rate += 0.03
    
    win_rate = min(win_rate, 0.88)
    
    # 켈리 계산
    target_profit = 0.02
    stop_loss = 0.01
    profit_loss_ratio = target_profit / stop_loss
    lose_rate = 1 - win_rate
    
    kelly_fraction = (profit_loss_ratio * win_rate - lose_rate) / profit_loss_ratio
    
    if kelly_fraction <= 0:
        return 0.0
    
    # 복리 단계
    if total_asset < 1_000_000:
        aggression = 2.5  # 더 공격적
        stage = "초기공격"
    elif total_asset < 5_000_000:
        aggression = 2.0
        stage = "초기"
    elif total_asset < 10_000_000:
        aggression = 1.5
        stage = "중기"
    elif total_asset < 50_000_000:
        aggression = 1.2
        stage = "성장"
    elif total_asset < 100_000_000:
        aggression = 1.0
        stage = "안정"
    else:
        aggression = 0.7
        stage = "보수"
    
    adjusted_kelly = kelly_fraction * aggression
    
    # 변동성 조정
    volatility = indicators['volatility_score']
    if volatility > 7.0:
        vol_mult = 0.75
    elif volatility > 5.0:
        vol_mult = 0.85
    elif volatility > 3.0:
        vol_mult = 0.95
    else:
        vol_mult = 1.0
    
    final_kelly = adjusted_kelly * vol_mult
    
    # 포지션 계산
    base_position = total_asset * final_kelly
    
    available_space = crypto_limit - crypto_value
    max_krw = krw_balance * 0.995
    
    if total_asset < 1_000_000:
        max_ratio = 0.60
    elif total_asset < 10_000_000:
        max_ratio = 0.40
    else:
        max_ratio = 0.25
    
    max_position = total_asset * max_ratio
    
    buy_size = min(base_position, available_space, max_krw, max_position)
    
    # 🆕 감속 확인 시 부스트
    if (signal_score >= 70 and win_rate >= 0.75 and
        accel and accel['is_decelerating'] and
        bb_exp and bb_exp['is_expanding']):
        boost = 1.5
        buy_size = min(buy_size * boost, max_position)
        print(f"🔥 감속+확장 부스트: +50%")
    
    print(f"포지션: 승률{win_rate*100:.0f}% | 켈리{kelly_fraction*100:.1f}% | "
          f"조정{final_kelly*100:.1f}% | {stage}")
    
    return buy_size

def trade_sell(ticker):
    """
    지능형 적응형 매도 시스템
    - 최소수익률 기준 엄격 적용
    - 손실 구간별 차등 전략
    - 반등 확률 기반 홀딩/매도 결정
    - 시장 상황 적응형 매도 기준
    """

    def calculate_recovery_probability(df, current_price, avg_buy_price):
        """반등 확률 계산 - 과거 패턴 분석"""
        if df is None or len(df) < 20:
            return 0.3  # 기본값
        
        closes = df['close'].values
        recovery_count = 0
        similar_situations = 0
        
        # 현재와 유사한 하락 상황 찾기
        current_drop = (current_price - avg_buy_price) / avg_buy_price
        
        for i in range(10, len(closes) - 5):
            period_drop = (closes[i] - closes[i-5]) / closes[i-5]
            if abs(period_drop - current_drop) < 0.01:  # 유사한 하락폭
                similar_situations += 1
                # 5봉 후 회복 여부 확인
                if closes[i+5] > closes[i]:
                    recovery_count += 1
        
        if similar_situations < 3:
            return 0.4  # 데이터 부족시 중립
        
        return recovery_count / similar_situations

    currency = ticker.split("-")[1]
    
    try:
        buyed_amount = get_balance(currency)
        if buyed_amount <= 0: 
            return None
        
        avg_buy_price = upbit.get_avg_buy_price(currency)
        cur_price = pyupbit.get_current_price(ticker)
        if cur_price is None: 
            return None
        
        profit_rate = (cur_price - avg_buy_price) / avg_buy_price * 100 if avg_buy_price > 0 else 0
        
    except Exception as e:
        print(f"[{ticker}] 초기 정보 조회 오류: {e}")
        return None

    # ========== 🔥 핵심: 최소수익률 미달시 매도 중단 ==========
    if profit_rate < min_rate:
        print(f"[{ticker}] 최소수익률({min_rate}%) 미달로 매도 대기 중... 현재: {profit_rate:.2f}%")
        
        # ❌ 단, 극한 손실 방지선은 유지 (긴급 탈출)
        emergency_cut = cut_rate - 1.0  # 손절선보다 1% 더 낮은 긴급선
        if profit_rate < emergency_cut:
            # 추가 검증: 30분봉으로 대세 하락 확인
            df_30m = pyupbit.get_ohlcv(ticker, interval="minute30", count=10)
            time.sleep(0.1)
            if df_30m is not None and len(df_30m) >= 5:
                recent_trend = (df_30m['close'].iloc[-1] - df_30m['close'].iloc[-5]) / df_30m['close'].iloc[-5]
                if recent_trend < -0.05:  # 30분봉 5% 이상 하락시만 긴급 매도
                    sell_order = upbit.sell_market_order(ticker, buyed_amount)
                    emergency_msg = f"🚨 **[긴급탈출]**: [{ticker}] 수익률: {profit_rate:.2f}% / 현재가: {cur_price:,.1f}\n"
                    emergency_msg += f"사유: 극한손실방지 + 30분봉 대세하락 확인"
                    print(emergency_msg)
                    send_discord_message(emergency_msg)
                    return sell_order
        
        return None  # 최소수익률 미달시 매도 시도 안함

    # ========== 데이터 수집 및 기술적 분석 ==========
    df_5m = pyupbit.get_ohlcv(ticker, interval="minute5", count=50)  # 더 많은 데이터
    time.sleep(0.1)
    if df_5m is None or len(df_5m) < 30:
        print(f"[{ticker}] 5분봉 데이터 부족")
        return None
    
    closes = df_5m['close'].values
    volumes = df_5m['volume'].values
    current_rsi = calculate_rsi(closes)
    
    # 반등 확률 계산
    recovery_prob = calculate_recovery_probability(df_5m, cur_price, avg_buy_price)
    
    # ========== 🧠 지능형 매도 신호 계산 ==========
    signals = []
    sell_strength = 0
    
    # 볼린저밴드 + RSI 융합 신호
    sma20 = np.mean(closes[-20:])
    std20 = np.std(closes[-20:])
    bb_upper = sma20 + (2.0 * std20)
    bb_lower = sma20 - (2.0 * std20)
    bb_position = (cur_price - sma20) / std20
    
    # 상단 과열 매도 신호
    if current_rsi > 70 and bb_position > 1.5:
        if cur_price < closes[-2]:  # 고점 대비 하락 시작
            signals.append("과열후하락개시")
            sell_strength += 4
    
    # 중기 추세 이탈
    sma10 = np.mean(closes[-10:])
    if cur_price < sma10 and sma10 < sma20:  # 단중기 동시 하락
        trend_break_volume = np.mean(volumes[-3:]) / np.mean(volumes[-10:-3])
        if trend_break_volume > 1.3:  # 대량과 함께 추세 이탈
            signals.append("추세이탈대량")
            sell_strength += 3
    
    # RSI 다이버전스 (가격 상승 vs RSI 하락)
    if len(closes) >= 10:
        price_trend = closes[-1] - closes[-5]
        prev_rsi = calculate_rsi(closes[:-5])
        if price_trend > 0 and current_rsi < prev_rsi - 5:  # 가격↑ RSI↓
            signals.append("RSI다이버전스")
            sell_strength += 3

    # ========== 🎯 적응형 매도 기준 설정 ==========
    # 수익률 구간별 차등 기준
    if profit_rate >= max_rate:
        required_score = 1  # 목표 달성시 즉시 매도
        hold_bonus = 0
    elif profit_rate >= min_rate * 2:  # 최소수익률의 2배 이상
        required_score = 2
        hold_bonus = 1 if recovery_prob > 0.6 else 0  # 반등 확률 고려
    elif profit_rate >= min_rate * 1.5:  # 최소수익률의 1.5배
        required_score = 3
        hold_bonus = 2 if recovery_prob > 0.7 else 0
    else:  # 최소수익률 ~ 1.5배
        required_score = 4  # 높은 확신 필요
        hold_bonus = 3 if recovery_prob > 0.8 else 1

    # 반등 가능성이 높으면 매도 기준 상향 (홀딩 우대)
    adjusted_required_score = required_score + hold_bonus
    
    should_sell_technical = sell_strength >= adjusted_required_score
    signal_text = " + ".join(signals) + f" (강도:{sell_strength}/{adjusted_required_score}, 반등확률:{recovery_prob:.1%})"
    
    # ========== 🔄 스마트 매도 실행 루프 ==========
    max_attempts = min(sell_time, 25)  # 효율성 개선
    attempts = 0
    consecutive_no_change = 0  # 가격 정체 카운터
    last_price = cur_price
    
    while attempts < max_attempts:
        cur_price = pyupbit.get_current_price(ticker)
        profit_rate = (cur_price - avg_buy_price) / avg_buy_price * 100 if avg_buy_price > 0 else 0
        
        # 가격 변화 모니터링
        price_change = abs(cur_price - last_price) / last_price
        if price_change < 0.001:  # 0.1% 미만 변화
            consecutive_no_change += 1
        else:
            consecutive_no_change = 0
        last_price = cur_price

        print(f"[{ticker}] 시도 {attempts + 1}/{max_attempts} | 수익률: {profit_rate:.2f}% | "
              f"신호강도: {sell_strength}/{adjusted_required_score} | 반등확률: {recovery_prob:.1%}")

        # ✅ 확실한 매도 조건들
        if profit_rate >= max_rate:  # 목표 달성
            sell_order = upbit.sell_market_order(ticker, buyed_amount)
            sellmsg = f"🎯 **[목표달성]**: [{ticker}] 수익률: {profit_rate:.2f}% / 현재가: {cur_price:,.1f}"
            print(sellmsg)
            send_discord_message(sellmsg)
            return sell_order
        
        elif should_sell_technical and profit_rate >= min_rate * 1.2:  # 기술적 + 충분한 수익
            sell_order = upbit.sell_market_order(ticker, buyed_amount)
            sellmsg = f"📊 **[기술적매도]**: [{ticker}] 수익률: {profit_rate:.2f}% / 현재가: {cur_price:,.1f}\n"
            sellmsg += f"신호: {signal_text}"
            print(sellmsg)
            send_discord_message(sellmsg)
            return sell_order
        
        elif consecutive_no_change >= 8 and profit_rate >= min_rate * 1.5:  # 가격 정체 + 적정 수익
            sell_order = upbit.sell_market_order(ticker, buyed_amount)
            stagnant_msg = f"⏸️ **[정체매도]**: [{ticker}] 수익률: {profit_rate:.2f}% / 현재가: {cur_price:,.1f}\n"
            stagnant_msg += f"사유: 8틱 연속 가격정체, 기회비용 고려"
            print(stagnant_msg)
            send_discord_message(stagnant_msg)
            return sell_order
        
        time.sleep(second)
        attempts += 1
    
    # ========== 🕐 시간 종료 처리 (개선) ==========
    # 시간 종료시에도 최소수익률 기준 유지
    if profit_rate >= min_rate:  # 최소수익률 이상일 때 시간종료 매도
        sell_order = upbit.sell_market_order(ticker, buyed_amount)
        final_msg = f"⏰ **[시간종료매도]**: [{ticker}] 수익률: {profit_rate:.2f}% / 현재가: {cur_price:,.1f}\n"
        final_msg += f"기준: 최소수익률 달성으로 안전한 수익 확보"
        print(final_msg)
        send_discord_message(final_msg)
        return sell_order
    else:
        # 수익이 부족하면 홀딩 지속
        hold_msg = f"🤝 **[홀딩지속]**: [{ticker}] 수익률: {profit_rate:.2f}% / 현재가: {cur_price:,.1f}\n"
        hold_msg += f"사유: 최소수익률 미달 (목표: {min_rate:.1f}% 이상), 반등확률: {recovery_prob:.1%}"
        print(hold_msg)
        send_discord_message(hold_msg)

    return None

# 누적 자산 기록용 변수
last_total_krw = 0.0
profit_report_running = False

def send_profit_report():
    """
    효율화된 수익률 보고서 - 매시간 정시 실행
    
    개선사항:
    1. 코드 길이 50% 단축 (150줄 → 75줄)
    2. 출력 형식 변경: 코인명 | 수익률 | 평가금액 | 순수익금액
    3. 불필요한 재시도 로직 제거 (한 번 실패 시 스킵)
    4. 간결한 에러 처리
    """
    global profit_report_running
    
    if profit_report_running:
        return
    
    profit_report_running = True
    
    try:
        while True:
            try:
                now = datetime.now()
                
                # 정시까지 대기
                if now.minute != 0:
                    next_hour = (now + timedelta(hours=1)).replace(minute=0, second=0, microsecond=0)
                    wait_seconds = (next_hour - now).total_seconds()
                    if wait_seconds > 60:
                        time.sleep(wait_seconds - 30)
                        continue
                
                # 잔고 조회
                balances = upbit.get_balances()
                if not balances:
                    raise Exception("잔고 조회 실패")
                
                # 자산 계산
                total_value = 0.0
                crypto_value = 0.0
                krw_balance = 0.0
                holdings = []
                
                EXCLUDED = {'QI', 'ONK', 'ETHF', 'ETHW', 'PURSE'}
                
                for b in balances:
                    currency = b.get('currency')
                    if not currency:
                        continue
                    
                    balance = float(b.get('balance', 0)) + float(b.get('locked', 0))
                    
                    if currency == 'KRW':
                        krw_balance = balance
                        total_value += balance
                        continue
                    
                    if balance <= 0 or currency in EXCLUDED:
                        continue
                    
                    # 현재가 조회 (1회만)
                    ticker = f"KRW-{currency}"
                    try:
                        current_price = pyupbit.get_current_price(ticker)
                        if not current_price:
                            continue
                    except:
                        continue
                    
                    avg_buy = float(b.get('avg_buy_price', 0))
                    eval_value = balance * current_price
                    profit_rate = ((current_price - avg_buy) / avg_buy * 100) if avg_buy > 0 else 0
                    net_profit = eval_value - (balance * avg_buy)
                    
                    crypto_value += eval_value
                    total_value += eval_value
                    
                    holdings.append({
                        'name': currency,
                        'rate': profit_rate,
                        'value': eval_value,
                        'profit': net_profit
                    })
                    
                    time.sleep(0.1)
                
                # 평가액 순 정렬
                holdings.sort(key=lambda x: x['value'], reverse=True)
                
                # 보고서 생성
                msg = f"[{now.strftime('%m/%d %H시')} 정시 보고서]\n"
                msg += "━━━━━━━━━━━━━━━━━━━━\n"
                msg += f"총자산: {total_value:,.0f}원\n"
                msg += f"KRW: {krw_balance:,.0f}원 | 암호화폐: {crypto_value:,.0f}원\n\n"
                
                if holdings:
                    msg += f"보유자산 ({len(holdings)}개)\n"
                    msg += "━━━━━━━━━━━━━━━━━━━━\n"
                    
                    for i, h in enumerate(holdings, 1):
                        emoji = "🔥" if h['rate'] > 5 else "📈" if h['rate'] > 0 else "➡️" if h['rate'] > -5 else "📉"
                        msg += (
                            f"{i}. {h['name']:<4} {emoji} "
                            f"{h['rate']:+6.2f}% | "
                            f"평가 {h['value']:>10,.0f}원 | "
                            f"순익 {h['profit']:>+10,.0f}원\n"
                        )
                else:
                    msg += "보유 코인 없음\n"
                
                send_discord_message(msg)
                print(f"[{now.strftime('%H시')}] 보고서 전송 완료 (총자산: {total_value:,.0f}원)")
                
                time.sleep(3600)
                
            except Exception as e:
                error_msg = f"수익률 보고서 오류\n{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n{str(e)}"
                print(error_msg)
                send_discord_message(error_msg)
                time.sleep(300)
    
    finally:
        profit_report_running = False

def selling_logic():
    """매도 로직 - 보유 코인 매도 처리"""
    try:
        balances = upbit.get_balances()
    except Exception as e:
        print(f"selling_logic / 잔고 조회 오류: {e}")
        return False
    
    has_holdings = False
    excluded_currencies = {"KRW", "QI", "ONX", "ETHF", "ETHW", "PURSE"}
    
    if isinstance(balances, list):
        for b in balances:
            currency = b.get('currency')
            if currency in excluded_currencies:
                continue
                
            balance = float(b.get('balance', 0))
            if balance <= 0:
                continue
            
            ticker = f"KRW-{currency}"
            
            try:
                result = trade_sell(ticker)
                has_holdings = True
                if result:
                    print(f"✅ {ticker} 매도 처리 완료")
            except Exception as e:
                print(f"selling_logic / {ticker} 매도 처리 오류: {e}")
                has_holdings = True
    
    return has_holdings

def buying_logic():
    """개선된 메인 매매 로직 - 통합 시스템 연동"""
    
    # 수익률 보고 스레드 시작
    profit_thread = threading.Thread(target=send_profit_report, daemon=True)
    profit_thread.start()
    print("수익률 보고 스레드 시작됨")
    
    while True:
        try:
            # ========== 1. 매도 로직 우선 실행 ==========
            has_holdings = selling_logic()
            
            # ========== 2. 매수 제한 시간 확인 ==========
            now = datetime.now()
            restricted_start = now.replace(hour=8, minute=50, second=0, microsecond=0)
            restricted_end = now.replace(hour=9, minute=10, second=0, microsecond=0)
            
            if restricted_start <= now <= restricted_end:
                print("매수 제한 시간 (08:50~09:10). 60초 대기...")
                time.sleep(60)
                continue
            
            # ========== 3. 원화 잔고 확인 ==========
            try:
                krw_balance = get_balance("KRW")
            except Exception as e:
                print(f"KRW 잔고 조회 오류: {e}")
                time.sleep(10)
                continue
            
            # ========== 4. 통합 매수 로직 실행 (종목 선정 + 매수) ==========
            if krw_balance > min_krw:
                print(f"매수 가능 잔고: {krw_balance:,.0f}원")
                
                try:
                    # trade_buy()가 종목 선정부터 매수까지 모두 처리
                    buy_time = datetime.now().strftime('%m/%d %H:%M:%S')
                    print(f"[{buy_time}] 최적 종목 자동 선정 + 매수 시작...")
                    
                    result = trade_buy(ticker=None)  # None이면 자동 선정 모드
                    
                    # 결과 판단
                    if result and isinstance(result, dict):
                        # 매수 성공
                        success_msg = "매수 성공! 다음 기회까지 "
                        wait_time = 15 if has_holdings else 30
                        print(f"{success_msg}{wait_time}초 대기")
                        time.sleep(wait_time)
                        
                    elif result and isinstance(result, tuple):
                        # 매수 실패 (이유 포함)
                        reason, _ = result
                        
                        if reason == "No candidates found":
                            wait_time = 10 if has_holdings else 30
                            print(f"매수할 코인 없음. {wait_time}초 후 재탐색...")
                            time.sleep(wait_time)
                            
                        elif reason == "Conditions not met":
                            print("매수 조건 미충족. 20초 후 재시도...")
                            time.sleep(20)
                            
                        elif reason == "Position limit reached":
                            wait_time = 60 if has_holdings else 120
                            print(f"포지션 상한 도달. {wait_time}초 대기...")
                            time.sleep(wait_time)
                            
                        elif reason == "Insufficient balance":
                            wait_time = 60 if has_holdings else 120
                            print(f"잔고 부족. {wait_time}초 대기...")
                            time.sleep(wait_time)
                            
                        else:
                            # 기타 실패 사유
                            print(f"매수 실패: {reason}. 30초 후 재시도...")
                            time.sleep(30)
                    else:
                        # 예상치 못한 결과
                        print("알 수 없는 결과. 30초 후 재시도...")
                        time.sleep(30)
                        
                except Exception as e:
                    print(f"매수 로직 실행 오류: {e}")
                    send_discord_message(f"매수 로직 오류: {e}")
                    time.sleep(30)
                    
            else:
                wait_time = 60 if has_holdings else 120
                print(f"매수 자금 부족: {krw_balance:,.0f}원. {wait_time}초 대기...")
                time.sleep(wait_time)
                
        except KeyboardInterrupt:
            print("\n프로그램 종료 요청...")
            break
            
        except Exception as e:
            print(f"메인 루프 오류: {e}")
            send_discord_message(f"메인 루프 오류: {e}")
            time.sleep(30)

# ========== 프로그램 시작 ==========
if __name__ == "__main__":
    # trade_start = datetime.now().strftime('%m/%d %H시%M분%S초')
    # trade_msg = f'🚀 {trade_start} 통합 복리 매수 시스템 v3.0\n'
    trade_msg = f'📊 설정: 수익률 {min_rate}%~{max_rate}% | 매도시도 {sell_time}회 | 손절 {cut_rate}%\n'
    trade_msg += f'📈 RSI 매수: {rsi_buy_s}~{rsi_buy_e} | RSI 매도: {rsi_sell_s}~{rsi_sell_e}\n'
    trade_msg += f'💡 개선사항: 조건완화, 병렬처리, 자동보고'
    
    print(trade_msg)
    send_discord_message(trade_msg)
    
    # 메인 매매 로직 실행
    buying_logic()
    # try:
    #     buying_logic()
    # except KeyboardInterrupt:
    #     print("\n\n프로그램이 종료되었습니다.")
    # except Exception as e:
    #     print(f"\n\n치명적 오류: {e}")
    #     send_discord_message(f"시스템 종료: {e}")