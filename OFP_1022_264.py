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

# rsi_buy_s = 25
# rsi_buy_e = 45
# rsi_sell_s = 65
# rsi_sell_e = 80
max_position_ratio = 0.25

def get_user_input():
    while True:
        try:
            min_rate = float(input("최소 수익률 (예: 1.0): "))
            max_rate = float(input("최대 수익률 (예: 5.0): "))
            sell_time = int(input("매도감시횟수 (예: 10): "))
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
    전략적으로 선별된 메이저 코인 반환 (고정 리스트)
    
    핵심 전략:
    - 시가총액 상위 메이저 코인 고정
    - 별도의 분석 없이 즉시 반환하여 성능 최적화
    - 변동성/유동성 분석은 get_best_ticker()에서 수행
    """
    
    STRATEGIC_COINS = [
        "KRW-BTC","KRW-ETH","KRW-XRP","KRW-SOL","KRW-ADA","KRW-LINK","KRW-BCH","KRW-XLM"  #
        # "KRW-AVAX","KRW-SUI","KRW-MNT","KRW-DOT","KRW-UNI","KRW-AAVE","KRW-NEAR",  #,"KRW-SHIB", "KRW-HBAR","KRW-CRO",
        # "KRW-ENA","KRW-APT","KRW-ETC","KRW-ONDO","KRW-POL"  #"KRW-PEPE","KRW-VET","KRW-BONK","KRW-ALGO",,"KRW-ARB"
    ]
    
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
    
    # BB 내 위치 (0~1, 하단=0, 상단=1)
    position = (closes[-1] - lower) / (upper - lower + 1e-8)
    
    # BB 폭 (변동성 지표)
    width = (upper - lower) / sma * 100
    
    return lower, sma, upper, max(0, min(1, position)), width

def calculate_bb_series(closes, window=20, std_dev=2.0):
    """
    🆕 BB 시계열 계산 (하단 기울기 분석용)
    
    Returns:
        lower_series: BB 하단 시계열 (최근 10개)
        upper_series: BB 상단 시계열
        width_series: BB 폭 시계열
    """
    if len(closes) < window + 10:
        return None, None, None
    
    lower_series = []
    upper_series = []
    width_series = []
    
    # 최근 10개 봉에 대해 각각 BB 계산
    for i in range(-10, 0):
        segment = closes[:i] if i != -1 else closes
        if len(segment) < window:
            continue
            
        sma = np.mean(segment[-window:])
        std = np.std(segment[-window:])
        
        lower = sma - (std * std_dev)
        upper = sma + (std * std_dev)
        width = (upper - lower) / sma * 100
        
        lower_series.append(lower)
        upper_series.append(upper)
        width_series.append(width)
    
    return (np.array(lower_series), 
            np.array(upper_series), 
            np.array(width_series))

def analyze_bb_slope(bb_lower_series):
    """
    🆕 🔥 BB 하단 기울기 분석 (핵심 혁신!)
    
    목적: 폭락이 멈추고 바닥을 다지는 순간 포착
    
    전략:
    1. 최근 3개 봉의 BB 하단 기울기 계산
    2. 이전 3개 봉의 기울기와 비교
    3. 급락(큰 음수 기울기) → 완만(작은 음수/0) 전환 감지
    
    Returns:
        {
            'is_flattening': bool,  # 기울기 완만해지는 중
            'recent_slope': float,  # 최근 기울기
            'prev_slope': float,    # 이전 기울기
            'slope_change': float   # 기울기 변화량 (양수 = 완만해짐)
        }
    """
    if bb_lower_series is None or len(bb_lower_series) < 6:
        return None
    
    # 최근 3개 봉의 기울기 (선형 회귀)
    recent_x = np.arange(3)
    recent_slope = np.polyfit(recent_x, bb_lower_series[-3:], 1)[0]
    
    # 이전 3개 봉의 기울기
    prev_slope = np.polyfit(recent_x, bb_lower_series[-6:-3], 1)[0]
    
    # 기울기 변화량 (양수 = 완만해짐)
    slope_change = recent_slope - prev_slope
    
    # 완만해지는 조건:
    # 1. 이전에는 급락 (prev_slope < -일정값)
    # 2. 최근은 완만 (recent_slope > prev_slope)
    # 3. 기울기 변화 충분히 큼 (slope_change > 임계값)
    
    is_flattening = (
        prev_slope < -0.5 and  # 이전에 급락 중이었고
        slope_change > 0.3 and  # 기울기가 충분히 완만해졌고
        recent_slope > prev_slope  # 최근이 이전보다 덜 급락
    )
    
    return {
        'is_flattening': is_flattening,
        'recent_slope': recent_slope,
        'prev_slope': prev_slope,
        'slope_change': slope_change
    }

def analyze_price_reversal(closes, volumes):
    """
    🆕 가격 반등 조기 감지
    
    목적: 종가가 폭락을 멈추고 반등하는 순간 포착
    
    전략:
    1. 최근 3개 봉의 가격 모멘텀
    2. 이전 5개 봉과 비교하여 전환 확인
    3. 거래량 증가 동반 여부 확인
    
    Returns:
        {
            'is_reversing': bool,  # 반등 시작
            'price_momentum': float,  # 가격 모멘텀
            'volume_surge': float  # 거래량 증가율
        }
    """
    if len(closes) < 8 or len(volumes) < 8:
        return None
    
    # 최근 3개 봉 평균 vs 이전 5개 봉 평균
    recent_avg = np.mean(closes[-3:])
    prev_avg = np.mean(closes[-8:-3])
    
    # 가격 모멘텀 (양수 = 반등)
    price_momentum = (recent_avg - prev_avg) / prev_avg
    
    # 거래량 급증 여부
    recent_vol = np.mean(volumes[-3:])
    normal_vol = np.mean(volumes[-8:-3])
    volume_surge = recent_vol / (normal_vol + 1e-8)
    
    # 반등 조건:
    # 1. 가격이 상승 전환 (모멘텀 > 0)
    # 2. 거래량 1.2배 이상 증가
    is_reversing = (
        price_momentum > 0 and
        volume_surge > 1.2
    )
    
    return {
        'is_reversing': is_reversing,
        'price_momentum': price_momentum,
        'volume_surge': volume_surge
    }

def predict_rebound_potential(closes, bb_lower_series, bb_width_series):
    """🔥 2% 반등 가능성 예측 (보수적 확률 모델)"""
    if bb_lower_series is None or len(closes) < 20:
        return None
    
    current_price = closes[-1]
    bb_lower = bb_lower_series[-1]
    
    # [1] BB 하단 대비 거리
    distance_from_lower = (current_price - bb_lower) / bb_lower * 100
    
    # [2] BB 폭
    avg_width = np.mean(bb_width_series[-5:])
    
    # [3] 최근 하락 폭
    recent_high = np.max(closes[-20:])
    drop_from_high = (current_price - recent_high) / recent_high * 100
    
    # 🆕 [4] 가격 안정성 (변동 계수) - 가중치 하향
    recent_std = np.std(closes[-5:])
    price_stability = 1 - min(recent_std / current_price, 0.5)
    
    # 🆕 [5] 추세 전환 강도 - 가중치 하향
    short_ma = np.mean(closes[-3:])
    long_ma = np.mean(closes[-10:])
    trend_shift = (short_ma - long_ma) / long_ma
    
    # 반등 점수 계산 (기존과 동일)
    score = 0
    
    # BB 하단 근접도 (30점)
    if distance_from_lower < -2:
        score += 30
    elif distance_from_lower < 0:
        score += 25
    elif distance_from_lower < 2:
        score += 20
    else:
        score += 10
    
    # BB 폭 (25점) - 기존 30점에서 하향
    if avg_width > 6:
        score += 25
    elif avg_width > 4:
        score += 20
    else:
        score += 10
    
    # 하락 폭 (25점) - 기존 30점에서 하향
    if drop_from_high < -10:
        score += 25
    elif drop_from_high < -7:
        score += 20
    elif drop_from_high < -5:
        score += 15
    else:
        score += 8
    
    # 🔧 가격 안정성 (10점) - 기존 15점에서 하향
    score += price_stability * 10
    
    # 🔧 추세 전환 (10점) - 기존과 동일하지만 조건 강화
    if trend_shift > 0:
        score += min(trend_shift * 150, 10)  # 기존 200에서 150으로 하향
    
    # 예상 수익률 (기존과 동일)
    expected_gain = min(avg_width * 0.4, 5.0)
    
    # 🔥 보수적 확률 계산 (선형 스케일 복구 + 더 엄격한 기준)
    # 85점 이상 = 85%
    # 75점 = 75%
    # 65점 = 65%
    # 55점 = 55%
    # 50점 이하 = 50%
    if score >= 85:
        probability = 0.85
    elif score >= 50:
        probability = score / 100  # 선형 스케일
    else:
        probability = 0.50  # 최소 50%
    
    return {
        'rebound_score': score,
        'expected_gain': expected_gain,
        'probability': probability
    }

def analyze_multi_timeframe_bb_alignment(ticker_symbol):
    """다중 시간프레임 BB 정렬 분석 (API 호출 최소화)"""
    try:
        # 🆕 5분봉만 가져와서 모든 시간프레임 계산
        df_5m = pyupbit.get_ohlcv(ticker_symbol, interval="minute5", count=100)
        time.sleep(0.5)  # API 안전 간격
        
        if df_5m is None or len(df_5m) < 100:
            return None
        
        closes_5m = df_5m['close'].values
        
        # 5분봉 BB
        _, _, _, pos_5m, _ = calculate_bb(closes_5m, 20)
        
        # 🆕 15분봉 시뮬레이션 (5분봉 3개씩 묶기)
        closes_15m = []
        for i in range(2, len(closes_5m), 3):
            closes_15m.append(np.mean(closes_5m[i-2:i+1]))
        closes_15m = np.array(closes_15m[-50:])
        _, _, _, pos_15m, _ = calculate_bb(closes_15m, 20)
        
        # 🆕 30분봉 시뮬레이션 (5분봉 6개씩 묶기)
        closes_30m = []
        for i in range(5, len(closes_5m), 6):
            closes_30m.append(np.mean(closes_5m[i-5:i+1]))
        closes_30m = np.array(closes_30m[-50:])
        _, _, _, pos_30m, _ = calculate_bb(closes_30m, 20)
        
        # 정렬 점수 계산
        score = 0
        
        if pos_5m < 0.30:
            score += 40
        elif pos_5m < 0.35:
            score += 30
        
        if pos_15m < 0.35:
            score += 30
        elif pos_15m < 0.40:
            score += 20
        
        if pos_30m < 0.40:
            score += 30
        elif pos_30m < 0.45:
            score += 20
        
        is_aligned = (pos_5m < 0.30 and pos_15m < 0.35 and pos_30m < 0.40)
        
        return {
            'is_aligned': is_aligned,
            'alignment_score': score,
            'tf_positions': {
                '5m': pos_5m,
                '15m': pos_15m,
                '30m': pos_30m
            }
        }
        
    except Exception as e:
        print(f"⚠️ BB정렬 분석 실패: {e}")
        return None
# ==================== 외부 함수: 자산/잔고 관리 ====================

def get_krw_balance(upbit):
    """KRW 잔고 조회"""
    try:
        balances = upbit.get_balances()
        for b in balances:
            if b['currency'] == "KRW":
                return float(b['balance'])
    except Exception as e:
        print(f"⚠️ 잔고 조회 실패: {e}")
    return 0.0


def get_total_crypto_value(upbit):
    """암호화폐 총 평가액"""
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
    except Exception as e:
        print(f"⚠️ 평가액 조회 실패: {e}")
        return 0.0


def get_held_coins(upbit):
    """보유 코인 목록"""
    try:
        balances = upbit.get_balances()
        return {f"KRW-{b['currency']}" for b in balances
               if float(b.get('balance', 0)) > 0 and b['currency'] != 'KRW'}
    except Exception as e:
        print(f"⚠️ 보유 코인 조회 실패: {e}")
        return set()


def calculate_position_size(total_asset, crypto_value, crypto_limit, krw_balance, 
                           signal_score, indicators):
    """💰 켈리 기준 기반 복리 최적화 포지션 사이징"""
    
    # 승률 추정
    if signal_score >= 80:
        win_rate = 0.75
    elif signal_score >= 70:
        win_rate = 0.70
    elif signal_score >= 60:
        win_rate = 0.60
    else:
        win_rate = 0.50
    
    # 🆕 반등 가능성 기반 승률 보정
    rebound = indicators.get('rebound_potential')
    if rebound:
        win_rate = min(win_rate + rebound['probability'] * 0.10, 0.85)
    
    # RSI/BB 보정
    rsi_5m = indicators['rsi_5m']
    bb_5m_pos = indicators['bb_5m_pos']
    
    if rsi_5m < 25:
        win_rate += 0.05
    elif rsi_5m < 30:
        win_rate += 0.03
    
    if bb_5m_pos < 0.15:
        win_rate += 0.05
    elif bb_5m_pos < 0.20:
        win_rate += 0.03
    
    # 🆕 BB 전환 확인 시 보정
    slope = indicators.get('bb_slope')
    reversal = indicators.get('price_reversal')
    
    if slope and slope['is_flattening']:
        win_rate += 0.05
    
    if reversal and reversal['is_reversing']:
        win_rate += 0.05
    
    win_rate = min(win_rate, 0.85)
    
    # 켈리 계산
    target_profit = 0.02
    stop_loss = 0.01
    profit_loss_ratio = target_profit / stop_loss
    lose_rate = 1 - win_rate
    
    kelly_fraction = (profit_loss_ratio * win_rate - lose_rate) / profit_loss_ratio
    
    if kelly_fraction <= 0:
        return 0.0
    
    # 복리 단계별 조정
    if total_asset < 1_000_000:
        aggression_multiplier = 2.0
        stage = "초기공격"
    elif total_asset < 10_000_000:
        ratio = (total_asset - 1_000_000) / 9_000_000
        aggression_multiplier = 2.0 - ratio * 1.0
        stage = "중기"
    elif total_asset < 100_000_000:
        aggression_multiplier = 1.0
        stage = "성장기"
    else:
        aggression_multiplier = 0.6
        stage = "보수기"
    
    adjusted_kelly = kelly_fraction * aggression_multiplier
    
    # 변동성 조정
    volatility = indicators['volatility_score']
    
    if volatility > 6.0:
        vol_multiplier = 0.7
    elif volatility > 4.0:
        vol_multiplier = 0.85
    else:
        vol_multiplier = 1.0
    
    final_kelly = adjusted_kelly * vol_multiplier
    
    # 최종 포지션
    base_position = total_asset * final_kelly
    
    available_space = crypto_limit - crypto_value
    max_krw = krw_balance * 0.995
    
    # if total_asset < 1_000_000:
        # max_position_ratio = 0.80
    # elif total_asset >= 1_000_000:
    # max_position_ratio = max_pos
    # else:
    #     max_position_ratio = 0.20
    
    max_position = total_asset * max_position_ratio
    
    buy_size = min(base_position, available_space, max_krw, max_position)
    
    # 🆕 BB 전환 확인 시 부스트
    if (signal_score >= 75 and win_rate >= 0.70 and
        slope and slope['is_flattening'] and
        reversal and reversal['is_reversing']):
        boost_multiplier = 1.4
        buy_size = min(buy_size * boost_multiplier, max_position)
        print(f"🔥 BB전환 확인 부스트: +40%")
    
    print(f"포지션 계산: 승률{win_rate*100:.0f}% | 켈리{kelly_fraction*100:.1f}% | "
          f"조정{final_kelly*100:.1f}% | {stage} | 최종{buy_size:,.0f}원")
    
    return buy_size

def analyze_ticker_enhanced(ticker_symbol):
    """🆕 강화된 종목 분석 (멀티타임프레임 기대값 계산 추가)"""
    try:
        # print(f"  └─ {ticker_symbol} 분석 중...", end=" ")
        
        # 🆕 [핵심 개선] 5분봉 1회만 호출
        df_5m = pyupbit.get_ohlcv(ticker_symbol, interval="minute5", count=100)
        time.sleep(0.5)  # API 안전 간격
        
        # 🆕 15분봉 추가 (기대값 계산용)
        df_15m = pyupbit.get_ohlcv(ticker_symbol, interval="minute15", count=50)
        time.sleep(0.5)
        
        # 🆕 1시간봉 1회 호출 (추가)
        df_1h = pyupbit.get_ohlcv(ticker_symbol, interval="minute60", count=50)
        time.sleep(0.5)
        
        current_price = pyupbit.get_current_price(ticker_symbol)
        
        if df_5m is None or df_15m is None or df_1h is None or current_price is None:
            print("❌ 데이터 없음")
            return {'valid': False}
        
        # 종가/거래량 추출
        closes_5m = df_5m['close'].values
        volumes_5m = df_5m['volume'].values
        closes_15m = df_15m['close'].values
        closes_1h = df_1h['close'].values
        
        # 🆕 1분봉 시뮬레이션 (5분봉 마지막 30개)
        closes_1m = closes_5m[-30:]
        
        # 기본 지표 계산
        rsi_1m = calculate_rsi(closes_1m, 14)
        rsi_5m = calculate_rsi(closes_5m, 14)
        rsi_1h = calculate_rsi(closes_1h, 14)
        
        # 🔥 [핵심 개선] 실제 15분봉 RSI 사용
        rsi_15m = calculate_rsi(closes_15m, 14)
        
        bb_5m_lower, bb_5m_mid, bb_5m_upper, bb_5m_pos, bb_5m_width = calculate_bb(closes_5m, 20)
        bb_1h_lower, bb_1h_mid, bb_1h_upper, bb_1h_pos, bb_1h_width = calculate_bb(closes_1h, 20)
        
        # 🔥 [핵심 개선] 실제 15분봉 BB 사용 (기대값 계산의 핵심)
        bb_15m_lower, bb_15m_mid, bb_15m_upper, bb_15m_pos, bb_15m_width = calculate_bb(closes_15m, 20)
        
        ema_12 = calculate_ema(closes_5m, 12)
        ema_26 = calculate_ema(closes_5m, 26)
        
        # 혁신 지표 (5분봉 유지)
        bb_lower_series, bb_upper_series, bb_width_series = calculate_bb_series(closes_5m, 20)
        slope_analysis = analyze_bb_slope(bb_lower_series)
        reversal = analyze_price_reversal(closes_5m, volumes_5m)
        
        # 🔥 [혁신 1] 멀티타임프레임 반등 예측
        rebound_5m = predict_rebound_potential(closes_5m, bb_lower_series, bb_width_series)
        
        # 🔥 15분봉 기반 반등 예측 (더 큰 수익 잠재력)
        bb_15m_lower_series, bb_15m_upper_series, bb_15m_width_series = calculate_bb_series(closes_15m, 20)
        rebound_15m = predict_rebound_potential(closes_15m, bb_15m_lower_series, bb_15m_width_series)
        
        alignment = analyze_multi_timeframe_bb_alignment(ticker_symbol)
        
        # 거래량 분석
        vol_recent = np.mean(volumes_5m[-5:])
        vol_normal = np.mean(volumes_5m[-20:-5])
        vol_ratio = vol_recent / (vol_normal + 1e-8)
        vol_absolute_krw = vol_recent * current_price
        
        # 일봉 분석 (5분봉에서 추정)
        daily_open = closes_5m[0]  # 100개 전 = 약 8시간 전
        daily_prev_close = closes_5m[-20]  # 20개 전 = 약 1.5시간 전
        daily_change_from_open = (current_price - daily_open) / daily_open * 100
        daily_change_from_prev = (current_price - daily_prev_close) / daily_prev_close * 100
        
        # 지지선/저항선
        recent_low = np.min(df_5m['low'].values[-20:])
        support_proximity = (current_price - recent_low) / recent_low * 100
        
        target_price_2pct = current_price * 1.02
        resistance_5m = np.max(df_5m['high'].values[-20:])
        resistance_clearance = (resistance_5m - target_price_2pct) / target_price_2pct * 100
        
        # 🔥 [혁신 2] 15분봉 저항선 (더 현실적)
        resistance_15m = np.max(df_15m['high'].values[-20:])
        resistance_clearance_15m = (resistance_15m - target_price_2pct) / target_price_2pct * 100
        
        # print("✓")
        
        return {
            'valid': True,
            'current_price': current_price,
            'indicators': {
                'rsi_1m': rsi_1m,
                'rsi_5m': rsi_5m,
                'rsi_15m': rsi_15m,
                'rsi_1h': rsi_1h,
                'bb_5m_pos': bb_5m_pos,
                'bb_5m_width': bb_5m_width,
                'bb_15m_pos': bb_15m_pos,
                'bb_15m_width': bb_15m_width,  # 🔥 추가
                'bb_1h_pos': bb_1h_pos,
                'ema_12': ema_12,
                'ema_26': ema_26,
                'vol_ratio': vol_ratio,
                'vol_absolute_krw': vol_absolute_krw,
                'daily_change_from_open': daily_change_from_open,
                'daily_change_from_prev': daily_change_from_prev,
                'support_proximity': support_proximity,
                'resistance_clearance': resistance_clearance,
                'resistance_clearance_15m': resistance_clearance_15m,  # 🔥 추가
                'volatility_score': bb_5m_width,
                'bb_slope': slope_analysis,
                'price_reversal': reversal,
                'rebound_potential': rebound_5m,  # 5분봉 반등 (진입용)
                'rebound_potential_15m': rebound_15m,  # 🔥 15분봉 반등 (수익계산용)
                'bb_alignment': alignment
            }
        }
        
    except Exception as e:
        print(f"❌ 오류: {e}")
        return {'valid': False}

def trade_buy(ticker=None):
    """
    🚀 적응형 매수 시스템 v8.5 - 딜레마 해결 및 최적화
    
    🔥 핵심 개선 (v8.4 → v8.5):
    1. 5분봉 기준 완화: 30% → 40% (타이밍 포착력 향상)
    2. 폭락 감지 개선: 절대값 → 방향성 기반
    3. 반등 징후 완화: 70점 → 65점 (현실적)
    4. 15분봉 중심 유지 + 5분봉 보조 최적화
    5. 이중 제약 해소: 실전 매수 기회 증가
    """
    
    # ==================== STEP 1: 자산 현황 확인 ====================
    krw_balance = get_krw_balance(upbit)
    crypto_value = get_total_crypto_value(upbit)
    total_asset = crypto_value + krw_balance
    
    MIN_ORDER = 5000
    MIN_VOLUME_5M_KRW = 3_00_000_000  # 3억원
    MIN_VOL_RATIO = 0.8
    
    if krw_balance < MIN_ORDER:
        print(f"❌ 잔고 부족")
        return "Insufficient balance", None
    
    crypto_limit = total_asset
    if crypto_value >= crypto_limit:
        print(f"❌ 포지션 상한")
        return "Position limit reached", None
    
    # ==================== STEP 2: 종목 선정 (최적화) ====================
    
    if ticker is None:
        try:
            held_coins = get_held_coins(upbit)
            all_tickers = get_top_volume_tickers()
            candidates = [t for t in all_tickers if t not in held_coins]
        except Exception as e:
            print(f"❌ 종목 조회 실패: {e}")
            return "Ticker fetch failed", None
        
        if not candidates:
            return "No tickers available", None
        
        qualified = []
        
        for t in candidates:
            analysis = analyze_ticker_enhanced(t)
            
            if not analysis['valid']:
                continue
            
            ind = analysis['indicators']
            
            # ──────────────────────────────────────────────────────
            # [필수 조건 1] 가격 범위
            # ──────────────────────────────────────────────────────
            if not (500 <= analysis['current_price']):
                continue
            
            # ──────────────────────────────────────────────────────
            # [필수 조건 2] 거래량 필터
            # ──────────────────────────────────────────────────────
            vol_absolute_krw = ind['vol_absolute_krw']
            vol_ratio = ind['vol_ratio']
            
            if vol_absolute_krw < MIN_VOLUME_5M_KRW:
                continue
            
            if vol_ratio < MIN_VOL_RATIO:
                continue
            
            # ══════════════════════════════════════════════════════
            # 🔥 [핵심 1] 15분봉 기준 저점 확인 (엄격 유지)
            # ══════════════════════════════════════════════════════
            """
            목적: 중기 관점에서 저점 확인
            15분봉 = 큰 흐름 파악
            """
            bb_15m_pos = ind['bb_15m_pos']
            rsi_15m = ind['rsi_15m']
            
            # 15분봉 BB 위치 (핵심 기준)
            if bb_15m_pos > 0.30:  # 30% 초과 제외
                continue
            
            # 15분봉 RSI
            if rsi_15m > 35:
                continue
            
            # ══════════════════════════════════════════════════════
            # 🔥 [핵심 2] 폭락 방향성 감지 (개선)
            # ══════════════════════════════════════════════════════
            """
            기존: 절대값 기준 (BB < 5% 차단)
            개선: 방향성 기준 (하락 중 vs 반등 중)
            
            폭락 진행 = BB/RSI 계속 하락
            폭락 완료 = BB/RSI 상승 전환
            """
            crash_in_progress = False
            crash_reasons = []
            
            # 신호 1: 15분봉 RSI 극단 + 계속 하락
            if rsi_15m < 18:  # 5 → 18로 완화 (극단만)
                # RSI 방향 확인 (이전 대비)
                # 이전 데이터가 없으면 보수적 판단
                crash_in_progress = True
                crash_reasons.append(f"RSI15m극단({rsi_15m:.0f})")
            
            # 신호 2: 5분봉 강한 하락 모멘텀 (유지)
            reversal = ind.get('price_reversal')
            if reversal:
                momentum = reversal.get('price_momentum', 0)
                if momentum < -0.04:  # -3% → -4%로 강화 (극단만)
                    crash_in_progress = True
                    crash_reasons.append(f"모멘텀급락({momentum*100:.1f}%)")
            
            # 신호 3: 거래량 극심한 폭발 (완화)
            if vol_ratio >= 3.5:  # 3.0 → 3.5로 완화
                crash_in_progress = True
                crash_reasons.append(f"극단공포({vol_ratio:.1f}x)")
            
            # 폭락 진행 중이면 제외
            if crash_in_progress:
                continue
            
            # ══════════════════════════════════════════════════════
            # 🔥 [핵심 3] 5분봉 타이밍 확인 (완화)
            # ══════════════════════════════════════════════════════
            """
            목적: 반등 시작 타이밍 포착
            5분봉 = 단기 진입 시점
            
            기존: 5분봉 ≤ 30% (엄격)
            개선: 5분봉 ≤ 40% (완화) ✅
            
            이유:
            - 15분봉 25%일 때 5분봉은 이미 반등 시작
            - 5분봉 35~40%도 충분히 저점
            """
            bb_5m_pos = ind['bb_5m_pos']
            rsi_5m = ind['rsi_5m']
            
            if bb_5m_pos > 0.40:  # 30% → 40% 완화 ✅
                continue
            
            if rsi_5m > 42:  # 40 → 42 약간 완화
                continue
            
            # ─────────── 반등 데이터 확인 ───────────
            rebound_5m = ind.get('rebound_potential')
            rebound_15m = ind.get('rebound_potential_15m')
            
            if not rebound_5m or not rebound_15m:
                continue
            
            # 반등 확률: 15분봉 우선 유지
            rebound_prob = rebound_15m['probability'] * 0.8 + rebound_5m['probability'] * 0.2
            expected_gain = rebound_15m['expected_gain']
            
            if rebound_prob < 0.48:  # 50% → 48% 약간 완화
                continue
            
            # ══════════════════════════════════════════════════════
            # 📈 반등 징후 점수 시스템 (완화)
            # ══════════════════════════════════════════════════════
            """
            기존: 70점 이상 (너무 엄격)
            개선: 65점 이상 (현실적)
            
            이유:
            - 15분봉 BB + RSI만으로 65점 가능
            - 나머지는 보조 지표
            """
            rebound_score = 0
            
            # ─────────── 지표 1: 15분봉 BB 안착 (35점) ───────────
            if bb_15m_pos < 0.10:
                rebound_score += 35
            elif bb_15m_pos < 0.20:
                rebound_score += 28
            elif bb_15m_pos < 0.30:
                rebound_score += 22  # 20 → 22로 상향
            
            # ─────────── 지표 2: 15분봉 RSI 바닥 (30점) ───────────
            if rsi_15m < 25:
                rebound_score += 30
            elif rsi_15m < 30:
                rebound_score += 24  # 22 → 24로 상향
            elif rsi_15m < 35:
                rebound_score += 18  # 15 → 18로 상향
            
            # ─────────── 지표 3: 5분봉 반등 시작 (20점) ───────────
            if reversal and reversal.get('is_reversing'):
                rebound_score += 20
            elif bb_5m_pos < 0.15:
                rebound_score += 15  # 12 → 15로 상향
            elif bb_5m_pos < 0.25:
                rebound_score += 10  # 신규 추가
            
            # ─────────── 지표 4: 거래량 (15점) ───────────
            if 0.8 <= vol_ratio < 2.5:  # 범위 확대
                rebound_score += 15
            elif vol_ratio >= 2.5:
                rebound_score += 8  # 5 → 8로 상향
            
            # ─────────── 지표 5: BB 전환점 (15점) ───────────
            slope = ind.get('bb_slope')
            if slope and slope['is_flattening']:
                rebound_score += 15
            
            # ─────────── 지표 6: 일봉 하락 (10점) ───────────
            daily_chg = ind['daily_change_from_open']
            if daily_chg < -2.0:
                rebound_score += 10
            elif daily_chg < -1.0:
                rebound_score += 6  # 5 → 6으로 상향
            
            # ─────────── 지표 7: TF 정렬 (10점) ───────────
            alignment = ind.get('bb_alignment')
            if alignment and alignment.get('is_aligned'):
                rebound_score += 10
            
            # ──────────────────────────────────────────────────────
            # 🔥 반등 징후 최소 기준: 65점 (완화)
            # ──────────────────────────────────────────────────────
            if rebound_score < 65:  # 70 → 65 완화 ✅
                continue
            
            # ══════════════════════════════════════════════════════
            # 💰 기대값 계산 (15분봉 기준 유지)
            # ══════════════════════════════════════════════════════
            
            # BB 보너스
            if bb_15m_pos < 0:
                bb_bonus = abs(bb_15m_pos) * 4.0
            elif bb_15m_pos < 0.10:
                bb_bonus = (0.10 - bb_15m_pos) * 3.0 + 0.40
            elif bb_15m_pos < 0.20:
                bb_bonus = (0.20 - bb_15m_pos) * 2.5 + 0.25
            else:
                bb_bonus = (0.30 - bb_15m_pos) * 1.5
            
            # 손실 계산
            if bb_15m_pos < 0.10:
                volatility_factor = 0.30
            elif bb_15m_pos < 0.20:
                volatility_factor = 0.45
            else:
                volatility_factor = 0.60
            
            expected_loss = max(bb_15m_pos, 0.08) * 5 * volatility_factor
            loss_prob = 1 - rebound_prob
            
            expected_value = (expected_gain * rebound_prob) - (expected_loss * loss_prob) + bb_bonus
            
            if expected_value < 0.28:  # 0.30 → 0.28 약간 완화
                continue
            
            profit_loss_ratio = expected_gain / expected_loss if expected_loss > 0 else 10
            
            if profit_loss_ratio < 2.3:  # 2.5 → 2.3 약간 완화
                continue
            
            # ✅ 조건 통과
            qualified.append({
                'ticker': t,
                'analysis': analysis,
                'bb_5m_pos': bb_5m_pos,
                'bb_15m_pos': bb_15m_pos,
                'rsi_5m': rsi_5m,
                'rsi_15m': rsi_15m,
                'rebound_prob': rebound_prob,
                'rebound_score': rebound_score,
                'expected_gain': expected_gain,
                'expected_loss': expected_loss,
                'expected_value': expected_value,
                'profit_loss_ratio': profit_loss_ratio,
                'bb_bonus': bb_bonus,
                'vol_ratio': vol_ratio
            })
            
            time.sleep(0.05)
        
        if not qualified:
            print(f"⏳ 조건 충족 종목 없음 (분석: {len(candidates)}개)")
            return "No qualified candidates", None
        
        # 기대값 기준 정렬
        qualified.sort(key=lambda x: x['expected_value'], reverse=True)
        best = qualified[0]
        
        selected_ticker = best['ticker']
        selected_analysis = best['analysis']
        
        # 출력
        print(f"\n🎯 [{selected_ticker}] BB15m:{best['bb_15m_pos']*100:.0f}% (5m:{best['bb_5m_pos']*100:.0f}%) RSI15m:{best['rsi_15m']:.0f} (5m:{best['rsi_5m']:.0f}) 반등:{best['rebound_prob']*100:.0f}%")
        print(f"   기대값:+{best['expected_value']:.2f}% 손익비:{best['profit_loss_ratio']:.1f}:1 징후:{best['rebound_score']}점 거래량:{best['vol_ratio']:.1f}x")
        
    else:  # 수동 선택
        selected_analysis = analyze_ticker_enhanced(ticker)
        
        if not selected_analysis['valid']:
            print("❌ 데이터 조회 실패")
            return "Data fetch failed", None
        
        ind = selected_analysis['indicators']
        selected_ticker = ticker
        
        bb_5m_pos = ind['bb_5m_pos']
        bb_15m_pos = ind['bb_15m_pos']
        rsi_5m = ind['rsi_5m']
        rsi_15m = ind['rsi_15m']
        
        # 경고 출력
        reversal = ind.get('price_reversal')
        momentum = reversal.get('price_momentum', 0) if reversal else 0
        vol_ratio = ind['vol_ratio']
        
        if rsi_15m < 18 or momentum < -0.04 or vol_ratio >= 3.5:
            print(f"⚠️ [{ticker}] 폭락 진행 중 가능성")
        
        rebound_5m = ind.get('rebound_potential')
        rebound_15m = ind.get('rebound_potential_15m')
        
        if not rebound_5m or not rebound_15m:
            print("❌ 반등 데이터 없음")
            return "No rebound data", None
        
        rebound_prob = rebound_15m['probability'] * 0.8 + rebound_5m['probability'] * 0.2
        expected_gain = rebound_15m['expected_gain']
        
        if bb_15m_pos < 0:
            bb_bonus = abs(bb_15m_pos) * 4.0
        elif bb_15m_pos < 0.10:
            bb_bonus = (0.10 - bb_15m_pos) * 3.0 + 0.40
        elif bb_15m_pos < 0.20:
            bb_bonus = (0.20 - bb_15m_pos) * 2.5 + 0.25
        else:
            bb_bonus = (0.30 - bb_15m_pos) * 1.5
        
        volatility_factor = 0.30 if bb_15m_pos < 0.10 else (0.45 if bb_15m_pos < 0.20 else 0.60)
        expected_loss = max(bb_15m_pos, 0.08) * 5 * volatility_factor
        loss_prob = 1 - rebound_prob
        
        expected_value = (expected_gain * rebound_prob) - (expected_loss * loss_prob) + bb_bonus
        profit_loss_ratio = expected_gain / expected_loss if expected_loss > 0 else 10
        
        print(f"🎯 [{ticker}] 반등:{rebound_prob*100:.0f}% 기대값:+{expected_value:.2f}% 손익비:{profit_loss_ratio:.1f}:1")
    
    # ==================== STEP 3: 최종 검증 ====================
    
    ind = selected_analysis['indicators']
    current_price = selected_analysis['current_price']
    
    bb_5m_pos = ind['bb_5m_pos']
    bb_15m_pos = ind['bb_15m_pos']
    rsi_5m = ind['rsi_5m']
    rsi_15m = ind['rsi_15m']
    
    if ticker is None:
        rebound_prob = best['rebound_prob']
        expected_value = best['expected_value']
        expected_gain = best['expected_gain']
        expected_loss = best['expected_loss']
        profit_loss_ratio = best['profit_loss_ratio']
    
    # 최종 검증
    if expected_value < 0.25:
        print(f"❌ 기대값 부족: {expected_value:.2f}%")
        return "Expected value too low", None
    
    if rebound_prob < 0.45:  # 48% → 45% 완화
        print(f"❌ 반등확률 부족: {rebound_prob*100:.0f}%")
        return "Rebound probability too low", None
    
    if bb_15m_pos > 0.35:
        print(f"❌ BB 15분 위치 높음: {bb_15m_pos*100:.0f}%")
        return "BB 15m position too high", None
    
    # ==================== STEP 4: 포지션 사이징 ====================
    
    risk_score = 0
    
    # 15분봉 RSI
    if rsi_15m < 25:
        risk_score += 35
    elif rsi_15m < 30:
        risk_score += 28
    else:
        risk_score += 20  # 18 → 20으로 상향
    
    # 15분봉 BB
    if bb_15m_pos < 0.10:
        risk_score += 35
    elif bb_15m_pos < 0.20:
        risk_score += 28
    else:
        risk_score += 20  # 18 → 20으로 상향
    
    # 반등 확률
    if rebound_prob >= 0.65:
        risk_score += 30
    elif rebound_prob >= 0.55:
        risk_score += 24  # 22 → 24로 상향
    else:
        risk_score += 15  # 12 → 15로 상향
    
    if risk_score >= 85:
        stop_loss_pct = 2.0
        path_name = "🟢초안전"
    elif risk_score >= 70:
        stop_loss_pct = 2.5
        path_name = "🟡안전"
    elif risk_score >= 55:
        stop_loss_pct = 3.0
        path_name = "🟠균형"
    else:
        stop_loss_pct = 3.5
        path_name = "🔴공격"
    
    buy_size = calculate_position_size(
        total_asset=total_asset,
        crypto_value=crypto_value,
        crypto_limit=crypto_limit,
        krw_balance=krw_balance,
        signal_score=75,
        indicators=ind
    )
    
    if buy_size < MIN_ORDER:
        print(f"❌ 매수액 부족")
        return "Buy size too small", None
    
    stop_loss_price = current_price * (1 - stop_loss_pct / 100)
    
    # ==================== STEP 5: 매수 실행 ====================
    
    for attempt in range(1, 3):
        try:
            verify_price = pyupbit.get_current_price(selected_ticker)
            time.sleep(0.1)
            
            price_change = (verify_price - current_price) / current_price
            
            if price_change > 0.04:
                print(f"⚠️ 가격 급등 {price_change*100:.1f}%")
                time.sleep(2)
                continue
            
            buy_order = upbit.buy_market_order(selected_ticker, buy_size)
            
            print(f"✅ 매수완료 {buy_size:,.0f}원 손절:{stop_loss_price:,.0f}원(-{stop_loss_pct:.1f}%) {path_name}")
            
            success_msg = f"🎯 매수: {selected_ticker}\n"
            success_msg += f"금액: {buy_size:,.0f}원 | 가격: {verify_price:,.0f}원\n"
            success_msg += f"BB15m:{bb_15m_pos*100:.0f}% (5m:{bb_5m_pos*100:.0f}%) RSI15m:{rsi_15m:.0f} 반등:{rebound_prob*100:.0f}%\n"
            success_msg += f"기대값:+{expected_value:.2f}% 손익비:{profit_loss_ratio:.1f}:1\n"
            success_msg += f"손절:{stop_loss_price:,.0f}원(-{stop_loss_pct:.1f}%)"
            
            if send_discord_message:
                send_discord_message(success_msg)
            
            return buy_order
            
        except Exception as e:
            print(f"❌ 오류: {e}")
            
            if attempt < 2:
                time.sleep(2)
            else:
                if send_discord_message:
                    send_discord_message(f"❌ 매수실패: {selected_ticker}")
                return "Order execution failed", None
    
    return "Max attempts exceeded", None
    
# ==================== 내부 함수 ====================

def analyze_crash_acceleration(closes, volumes):
    """
    🚨 폭락 가속도 정밀 분석
    
    Returns:
        {
            'is_crashing': bool,        # 폭락 중
            'acceleration': float,       # 가속도
            'severity': str,            # LOW/MEDIUM/HIGH/CRITICAL
            'suggested_cut': float      # 권장 손절선 (%)
        }
    """
    if len(closes) < 10:
        return None
    
    # 3구간 속도 계산
    recent = np.mean(closes[-3:])
    middle = np.mean(closes[-6:-3])
    older = np.mean(closes[-9:-6])
    
    v1 = (middle - older) / older
    v2 = (recent - middle) / middle
    accel = v2 - v1
    
    # 거래량 급증
    vol_recent = np.mean(volumes[-3:])
    vol_normal = np.mean(volumes[-10:-3])
    vol_surge = vol_recent / (vol_normal + 1e-8)
    
    # 폭락 판단
    is_crashing = v2 < -0.02 and accel < -0.01
    
    # 심각도 평가
    if accel < -0.03 and vol_surge > 2.0:
        severity = 'CRITICAL'
        suggested_cut = -2.0  # -2%에서 즉시 손절
    elif accel < -0.02 and vol_surge > 1.5:
        severity = 'HIGH'
        suggested_cut = -3.0
    elif accel < -0.01:
        severity = 'MEDIUM'
        suggested_cut = -4.0
    else:
        severity = 'LOW'
        suggested_cut = -5.0  # 일반 손절선
    
    return {
        'is_crashing': is_crashing,
        'acceleration': accel,
        'velocity': v2,
        'vol_surge': vol_surge,
        'severity': severity,
        'suggested_cut': suggested_cut
    }

def analyze_uptrend_strength(closes, volumes, current_price):
    """
    📈 상승 추세 강도 분석 (홀딩 판단)
    
    Returns:
        {
            'should_hold': bool,         # 홀딩 권장
            'strength': float,           # 강도 0-10
            'reason': str                # 이유
        }
    """
    if len(closes) < 20:
        return None
    
    strength = 0
    reasons = []
    
    # [1] EMA 골든크로스
    ema_5 = calculate_ema(closes, 5)
    ema_20 = calculate_ema(closes, 20)
    
    if current_price > ema_5 > ema_20:
        strength += 3
        reasons.append("EMA상승")
    elif current_price > ema_5:
        strength += 1
    
    # [2] 상승 모멘텀
    momentum = (closes[-1] - closes[-5]) / closes[-5]
    if momentum > 0.01:
        strength += 3
        reasons.append("강한모멘텀")
    elif momentum > 0:
        strength += 1
    
    # [3] 거래량 증가 + 상승
    vol_recent = np.mean(volumes[-3:])
    vol_normal = np.mean(volumes[-10:-3])
    vol_ratio = vol_recent / (vol_normal + 1e-8)
    
    if vol_ratio > 1.3 and momentum > 0:
        strength += 2
        reasons.append("매수세유입")
    
    # [4] BB 중하단 (상승 여력)
    _, _, _, bb_pos, _ = calculate_bb(closes, 20)
    if bb_pos < 0.40:
        strength += 2
        reasons.append("BB하단")
    elif bb_pos < 0.60:
        strength += 1
    
    should_hold = strength >= 5
    reason = "+".join(reasons) if reasons else "없음"
    
    return {
        'should_hold': should_hold,
        'strength': strength,
        'reason': reason,
        'bb_position': bb_pos,
        'momentum': momentum
    }

def should_sell_now(profit_rate, closes, volumes, current_price, min_rate):
    """
    🎯 즉시 매도 여부 종합 판단
    
    Returns:
        {
            'sell': bool,
            'reason': str,
            'urgency': str  # LOW/MEDIUM/HIGH
        }
    """
    # BB 분석
    _, bb_mid, _, bb_pos, bb_width = calculate_bb(closes, 20)
    
    # 상승세 분석
    uptrend = analyze_uptrend_strength(closes, volumes, current_price)
    
    # RSI
    rsi = calculate_rsi(closes, 14)
    
    # ========== 즉시 매도 조건 ==========
    
    # [1] BB 상단 과열 (70% 이상)
    if bb_pos >= 0.70:
        if rsi > 70:
            return {'sell': True, 'reason': 'BB상단+RSI과열', 'urgency': 'HIGH'}
        elif profit_rate >= min_rate * 1.2:
            return {'sell': True, 'reason': 'BB상단+충분수익', 'urgency': 'MEDIUM'}
    
    # [2] RSI 극과열 + 하락 시작
    if rsi > 75 and closes[-1] < closes[-2]:
        return {'sell': True, 'reason': 'RSI극과열+하락', 'urgency': 'HIGH'}
    
    # [3] EMA 데드크로스
    ema_5 = calculate_ema(closes, 5)
    ema_20 = calculate_ema(closes, 20)
    if current_price < ema_5 < ema_20:
        if profit_rate >= min_rate:
            return {'sell': True, 'reason': 'EMA데드크로스', 'urgency': 'MEDIUM'}
    
    # [4] 최소수익률 달성 + 상승세 약화
    if profit_rate >= min_rate:
        if uptrend and uptrend['strength'] < 3:
            return {'sell': True, 'reason': '수익달성+약화', 'urgency': 'LOW'}
    
    # ========== 홀딩 조건 ==========
    
    # 상승세 강함
    if uptrend and uptrend['should_hold']:
        return {'sell': False, 'reason': uptrend['reason'], 'urgency': 'NONE'}
    
    # BB 하단 (상승 여력)
    if bb_pos < 0.30 and profit_rate >= min_rate * 0.8:
        return {'sell': False, 'reason': 'BB하단+상승여력', 'urgency': 'NONE'}
    
    # 기본: 최소수익률 미달이면 홀딩
    if profit_rate < min_rate:
        return {'sell': False, 'reason': '수익률부족', 'urgency': 'NONE'}
    
    # 애매한 구간: 시간에 맡김
    return {'sell': False, 'reason': '관망', 'urgency': 'NONE'}

def trade_sell(ticker):
    """
    🎯 지능형 매도 시스템 v3.0 - 동적 최적화
    
    혁신 포인트:
    1. 동적 매도: EMA/볼륨/모멘텀 종합 분석으로 최적 시점 포착
    2. 지능형 손절: 폭락 가속도 기반 -2%~-7% 동적 손절
    3. BB 기반 홀딩: 하단이면 추가 대기, 상단이면 즉시 매도
    4. 간결한 출력: 1줄 요약 출력
    5. 최소수익률만 사용: 최대수익률 개념 제거
    """
    
    
    # ==================== 메인 로직 ====================
    
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
        return None
    
    # 데이터 수집
    df_5m = pyupbit.get_ohlcv(ticker, interval="minute5", count=50)
    time.sleep(0.5)
    
    if df_5m is None or len(df_5m) < 20:
        return None
    
    closes = df_5m['close'].values
    volumes = df_5m['volume'].values
    
    # ========== 지능형 손절 (최우선) ==========
    
    if profit_rate < 0:
        crash = analyze_crash_acceleration(closes, volumes)
        
        if crash:
            # 동적 손절선
            if profit_rate <= crash['suggested_cut']:
                # BB 하단 예외: 반등 가능성 체크
                _, _, _, bb_pos, _ = calculate_bb(closes, 20)
                
                # BB 극하단(15% 미만)이고 RSI 극과매도면 손절 보류
                rsi = calculate_rsi(closes, 14)
                if bb_pos < 0.15 and rsi < 20:
                    print(f"[{ticker}] 손절 보류: BB극하단+RSI극과매도 (반등대기)")
                else:
                    sell_order = upbit.sell_market_order(ticker, buyed_amount)
                    msg = f"🛑 **[지능형손절]** {ticker}\n"
                    msg += f"수익: {profit_rate:.2f}% | 손절선: {crash['suggested_cut']:.1f}%\n"
                    msg += f"사유: {crash['severity']} 폭락 (가속도{crash['acceleration']*100:.1f}%)"
                    print(msg)
                    send_discord_message(msg)
                    return sell_order
    
    # 기존 긴급 손절 백업
    if profit_rate <= -4.0:
        sell_order = upbit.sell_market_order(ticker, buyed_amount)
        msg = f"🚨 **[긴급손절]** {ticker} | {profit_rate:.2f}%"
        print(msg)
        send_discord_message(msg)
        return sell_order
    
    # ========== 최소수익률 미달 시 대기 ==========
    
    if profit_rate < min_rate * 0.5:  # 최소수익률의 50% 미만
        return None
    
    # ========== 매도 감시 루프 ==========
    
    max_attempts = min(sell_time, 100)
    
    for attempt in range(max_attempts):
        cur_price = pyupbit.get_current_price(ticker)
        profit_rate = (cur_price - avg_buy_price) / avg_buy_price * 100 if avg_buy_price > 0 else 0
        
        # 실시간 데이터 업데이트 (5회마다)
        if attempt % 5 == 0:
            df_5m_live = pyupbit.get_ohlcv(ticker, interval="minute5", count=50)
            time.sleep(0.5)
            if df_5m_live is not None and len(df_5m_live) >= 20:
                closes = df_5m_live['close'].values
                volumes = df_5m_live['volume'].values
        
        # 즉시 매도 판단
        decision = should_sell_now(profit_rate, closes, volumes, cur_price, min_rate)
        
        # 간결한 출력 (1줄)
        _, _, _, bb_pos, _ = calculate_bb(closes, 20)
        print(f"[매도감시] {ticker} {attempt+1}/{max_attempts} | "
              f"{profit_rate:+.2f}% | BB:{bb_pos*100:.0f}% | "
              f"{'매도!' if decision['sell'] else '홀딩'}")
        time.sleep(0.5)
        
        # 즉시 매도
        if decision['sell']:
            sell_order = upbit.sell_market_order(ticker, buyed_amount)
            
            if decision['urgency'] == 'HIGH':
                emoji = "🚨"
            elif decision['urgency'] == 'MEDIUM':
                emoji = "📊"
            else:
                emoji = "✅"
            
            msg = f"{emoji} **[매도]** {ticker}\n"
            msg += f"수익: {profit_rate:.2f}% | 가격: {cur_price:,.0f}원\n"
            msg += f"사유: {decision['reason']}"
            
            print(msg)
            send_discord_message(msg)
            return sell_order
        
        time.sleep(0.1)
    
    # ========== 시간 종료 처리 ==========
    
    # 최종 데이터
    df_final = pyupbit.get_ohlcv(ticker, interval="minute5", count=50)
    time.sleep(0.5)
    
    if df_final is not None and len(df_final) >= 20:
        closes_final = df_final['close'].values
        volumes_final = df_final['volume'].values
        
        _, _, _, bb_pos_final, _ = calculate_bb(closes_final, 20)
        uptrend_final = analyze_uptrend_strength(closes_final, volumes_final, cur_price)
        
        # 최소수익률 달성 여부
        if profit_rate >= min_rate:
            # BB 하단 + 강한 상승세 → 홀딩
            if bb_pos_final < 0.30 and uptrend_final and uptrend_final['strength'] >= 6:
                msg = f"🤝 **[시간종료-홀딩]** {ticker}\n"
                msg += f"수익: {profit_rate:.2f}% | BB:{bb_pos_final*100:.0f}%\n"
                msg += f"사유: {uptrend_final['reason']} (추가상승대기)"
                print(msg)
                send_discord_message(msg)
                return None
            
            # 일반 상황 → 매도
            else:
                sell_order = upbit.sell_market_order(ticker, buyed_amount)
                msg = f"⏰ **[시간종료-매도]** {ticker}\n"
                msg += f"수익: {profit_rate:.2f}% | BB:{bb_pos_final*100:.0f}%"
                print(msg)
                send_discord_message(msg)
                return sell_order
        
        # 최소수익률 미달 → 홀딩
        else:
            msg = f"🤝 **[홀딩]** {ticker} | {profit_rate:.2f}% (미달)"
            print(msg)
            return None
    
    return None


# 누적 자산 기록용 변수
last_total_krw = 0.0
profit_report_running = False

def send_profit_report():
    """
    개선된 수익률 보고서 - 시작 시 즉시 실행 + 매시간 정시 실행
    
    핵심 개선:
    1. 프로그램 시작 시 즉시 보고서 1회 실행
    2. 이후 매시간 정시마다 자동 실행
    3. 시간 출력 정확도 보장
    """
    global profit_report_running
    
    if profit_report_running:
        return
    
    profit_report_running = True
    
    try:
        # 🔥 시작 시 즉시 1회 실행
        print(f"[{datetime.now().strftime('%H:%M:%S')}] 프로그램 시작 - 초기 보고서 생성 중...")
        generate_and_send_report(is_startup=True)
        
        # 이후 정시 루프
        while True:
            try:
                now = datetime.now()
                
                # 정시가 아니면 대기
                if now.minute != 0 or now.second > 30:
                    # 다음 정시까지 대기
                    next_hour = (now + timedelta(hours=1)).replace(minute=0, second=0, microsecond=0)
                    wait_seconds = (next_hour - now).total_seconds()
                    
                    if wait_seconds > 60:
                        # 정시 30초 전까지 대기
                        time.sleep(wait_seconds - 30)
                        continue
                    elif now.minute != 0:
                        # 정시가 아니면 30초 대기 후 재확인
                        time.sleep(30)
                        continue
                
                # 정시 확인 후 보고서 생성
                print(f"[{now.strftime('%H:%M:%S')}] 정시 보고서 생성 시작...")
                generate_and_send_report(is_startup=False)
                
                # 다음 정시까지 대기
                time.sleep(3600)
                
            except Exception as e:
                error_time = datetime.now()
                error_msg = f"수익률 보고서 오류\n{error_time.strftime('%Y-%m-%d %H:%M:%S')}\n{str(e)}"
                print(error_msg)
                send_discord_message(error_msg)
                # 오류 시 5분 후 재시도
                time.sleep(300)
    
    finally:
        profit_report_running = False


def generate_and_send_report(is_startup=False):
    """
    보고서 생성 및 전송 (공통 로직)
    
    Args:
        is_startup: 시작 시 실행 여부 (True면 "시작 보고서", False면 "정시 보고서")
    """
    try:
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
            
            # 현재가 조회
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
        
        # 보고서 생성 직전 시간 가져오기
        report_time = datetime.now()
        
        # 🔥 헤더 구분 (시작 vs 정시)
        if is_startup:
            header = f"[{report_time.strftime('%m/%d %H:%M')} 시작 보고서]"
        else:
            header = f"[{report_time.strftime('%m/%d %H시')} 정시 보고서]"
        
        # 보고서 생성
        msg = f"{header}\n"
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
        print(f"[{report_time.strftime('%H:%M:%S')}] 보고서 전송 완료 (총자산: {total_value:,.0f}원)")
        
    except Exception as e:
        raise  # 상위로 예외 전달

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
                # print(f"매수 가능 잔고: {krw_balance:,.0f}원")
                
                try:
                    # trade_buy()가 종목 선정부터 매수까지 모두 처리
                    # buy_time = datetime.now().strftime('%m/%d %H:%M:%S')
                    # print(f"[{buy_time}] 최적 종목 자동 선정 + 매수 시작...")
                    
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
                            print(f"매수할 코인 없음. {wait_time}초 후 재탐색...\n")
                            time.sleep(wait_time)
                            
                        elif reason == "Conditions not met":
                            print("매수 조건 미충족. 20초 후 재시도...\n")
                            time.sleep(20)
                            
                        elif reason == "Position limit reached":
                            wait_time = 60 if has_holdings else 120
                            print(f"포지션 상한 도달. {wait_time}초 대기...\n")
                            time.sleep(wait_time)
                            
                        elif reason == "Insufficient balance":
                            wait_time = 60 if has_holdings else 120
                            print(f"잔고 부족. {wait_time}초 대기...\n")
                            time.sleep(wait_time)
                            
                        else:
                            # 기타 실패 사유
                            # print(f"매수 실패: {reason}. 30초 후 재시도...\n")
                            time.sleep(30)
                    else:
                        # 예상치 못한 결과
                        print("알 수 없는 결과. 30초 후 재시도...\n")
                        time.sleep(30)
                        
                except Exception as e:
                    print(f"매수 로직 실행 오류: {e}")
                    send_discord_message(f"매수 로직 오류: {e}")
                    time.sleep(30)
                    
            else:
                wait_time = 60 if has_holdings else 120
                print(f"매수 자금 부족: {krw_balance:,.0f}원. {wait_time}초 대기...\n")
                time.sleep(wait_time)
                
        except KeyboardInterrupt:
            print("\n프로그램 종료 요청...\n")
            break
            
        except Exception as e:
            print(f"메인 루프 오류: {e}")
            send_discord_message(f"메인 루프 오류: {e}")
            time.sleep(30)

# ========== 프로그램 시작 ==========
if __name__ == "__main__":

    trade_msg = f'📊 설정: MAX 포지션: {max_position_ratio} | 수익률 {min_rate}%~{max_rate}% | 매도시도 {sell_time}회 | 손절 {cut_rate}%\n'
    
    print(trade_msg)
    send_discord_message(trade_msg)
    
    # 메인 매매 로직 실행
    buying_logic()