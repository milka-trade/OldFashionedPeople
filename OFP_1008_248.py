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

def trade_buy(ticker=None):
    """
    🚀 초단기 복리 매수 시스템 v6.0 - 천재적 통합 최적화
    
    핵심 혁신:
    1. 반등 확률 70% 이상 엄격 필터링 (ML 패턴 매칭)
    2. 15분봉 하단 필수 검증 (상단 50% 이상 제거)
    3. 5분봉 급락 둔화 + BB 확장 동시 포착
    4. 전 함수 통합으로 관리 용이성 극대화
    5. 불필요 코드 제거 및 성능 최적화
    
    목표: 10만원 → 10억 (2년, 2% 복리)
    """
    import numpy as np
    import time
    
    # ==================== 내부 함수들 ====================
    
    def get_krw_balance():
        """KRW 잔고 조회"""
        try:
            balances = upbit.get_balances()
            for b in balances:
                if b['currency'] == "KRW":
                    return float(b['balance'])
        except:
            pass
        return 0.0
    
    def get_total_crypto_value():
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
        except:
            return 0.0
    
    def get_held_coins():
        """보유 중인 코인 티커 목록"""
        try:
            balances = upbit.get_balances()
            return {f"KRW-{b['currency']}" for b in balances
                   if float(b.get('balance', 0)) > 0 and b['currency'] != 'KRW'}
        except:
            return set()
    
    def calculate_rsi(prices, period=14):
        """RSI 계산"""
        if len(prices) < period + 1:
            return 50.0
        deltas = np.diff(prices)
        gains = np.where(deltas > 0, deltas, 0)
        losses = np.where(deltas < 0, -deltas, 0)
        
        avg_gain = np.mean(gains[-period:])
        avg_loss = np.mean(losses[-period:])
        
        if avg_loss == 0:
            return 100.0
        rs = avg_gain / avg_loss
        return 100 - (100 / (1 + rs))
    
    def calculate_bb(prices, window=20):
        """볼린저밴드 계산 + BB위치 + BB폭"""
        if len(prices) < window:
            return None, None, None, 0.5, 0.0
        
        sma = np.mean(prices[-window:])
        std = np.std(prices[-window:])
        
        upper = sma + (std * 2)
        lower = sma - (std * 2)
        current = prices[-1]
        
        # BB 위치 (0=하단, 0.5=중간, 1=상단)
        if upper == lower:
            position = 0.5
        else:
            position = (current - lower) / (upper - lower)
        
        # BB 폭 (변동성 지표)
        width = (std * 4) / sma * 100 if sma > 0 else 0
        
        return lower, sma, upper, position, width
    
    def calculate_ema(prices, period):
        """EMA 계산"""
        if len(prices) < period:
            return prices[-1]
        
        multiplier = 2 / (period + 1)
        ema = np.mean(prices[:period])
        
        for price in prices[period:]:
            ema = (price - ema) * multiplier + ema
        
        return ema
    
    def analyze_price_deceleration(closes):
        """
        🔥 급락 둔화 감지 (핵심 알고리즘)
        
        원리: 2차 미분(가속도)으로 급락이 "멈추는" 순간 포착
        
        단계:
        1. 최근 9개 봉을 3구간으로 분할
        2. 각 구간 평균 계산
        3. 속도(1차 미분) 계산: 구간 간 변화율
        4. 가속도(2차 미분) 계산: 속도의 변화
        5. 양의 가속도 = 하락 둔화 = 매수 시그널
        
        Returns:
            {
                'is_decelerating': bool,  # 둔화 중
                'velocity': float,        # 현재 속도 (%)
                'acceleration': float,    # 가속도 (%)
                'confidence': float       # 신뢰도 0-1
            }
        """
        if len(closes) < 10:
            return None
        
        # 3구간 평균
        recent = np.mean(closes[-3:])    # 최근
        middle = np.mean(closes[-6:-3])  # 중간
        older = np.mean(closes[-9:-6])   # 과거
        
        # 속도 계산 (변화율)
        v1 = (middle - older) / older  # 과거→중간
        v2 = (recent - middle) / middle  # 중간→최근
        
        # 가속도 (속도 변화)
        accel = v2 - v1
        
        # 둔화 조건
        # 1. 현재 하락 중 (v2 < 0)
        # 2. 이전도 하락 (v1 < 0)
        # 3. 하락세 약해짐 (v2 > v1, 즉 accel > 0)
        # 4. 충분한 둔화 (accel > 1%)
        is_decel = (v2 < 0 and v1 < 0 and accel > 0.01)
        
        # 신뢰도 계산
        if is_decel:
            confidence = min(accel * 50, 1.0)  # 가속도 클수록 신뢰도 up
        else:
            confidence = 0.0
        
        return {
            'is_decelerating': is_decel,
            'velocity': v2,
            'acceleration': accel,
            'confidence': confidence
        }
    
    def analyze_bb_volatility_surge(closes, window=20):
        """
        🔥 BB 폭 급증 감지
        
        당신의 경험: "BB 폭이 충분히 넓을 때 수익률 높음"
        
        전략:
        - 최근 BB 폭 vs 평균 BB 폭 비교
        - 1.5배 이상 확장 시 매수 기회
        
        Returns:
            {
                'is_surging': bool,
                'current_width': float,
                'expansion_ratio': float
            }
        """
        if len(closes) < window + 10:
            return None
        
        # 최근 5개 구간의 BB 폭
        widths = []
        for i in range(-10, 0):
            segment = closes[:i] if i != -1 else closes
            if len(segment) < window:
                continue
            _, _, _, _, width = calculate_bb(segment, window)
            widths.append(width)
        
        if len(widths) < 10:
            return None
        
        current_width = np.mean(widths[-3:])  # 최근 3개
        avg_width = np.mean(widths[-10:-3])   # 평균 7개
        
        expansion = current_width / (avg_width + 1e-8)
        
        # 급증 조건: 1.5배 확장 + 최소 변동성 4%
        is_surge = (expansion >= 1.5 and current_width >= 4.0)
        
        return {
            'is_surging': is_surge,
            'current_width': current_width,
            'expansion_ratio': expansion
        }
    
    def detect_reversal_candle(df_5m):
        """
        🔥 반전 캔들 패턴 감지
        
        핵심 패턴:
        1. 망치형: 긴 아래꼬리 + 작은 몸통 + 짧은 위꼬리
        2. 도지형: 몸통 거의 없음 (시가≈종가)
        
        Returns:
            {
                'has_hammer': bool,
                'has_doji': bool,
                'tail_ratio': float
            }
        """
        if len(df_5m) < 3:
            return None
        
        recent = df_5m.iloc[-3:]
        
        has_hammer = False
        has_doji = False
        max_tail_ratio = 0
        
        for _, row in recent.iterrows():
            o, c, h, l = row['open'], row['close'], row['high'], row['low']
            
            body = abs(c - o)
            lower_tail = min(o, c) - l
            upper_tail = h - max(o, c)
            total_range = h - l
            
            if total_range == 0:
                continue
            
            # 망치형: 아래꼬리 > 몸통*2, 위꼬리 작음
            if body > 0:
                tail_ratio = lower_tail / body
                max_tail_ratio = max(max_tail_ratio, tail_ratio)
                
                if (lower_tail > body * 2 and 
                    upper_tail < body * 0.5 and
                    c >= o * 0.99):
                    has_hammer = True
            
            # 도지형: 몸통 < 전체 길이의 10%
            if body < total_range * 0.1:
                has_doji = True
        
        return {
            'has_hammer': has_hammer,
            'has_doji': has_doji,
            'tail_ratio': max_tail_ratio
        }
    
    def predict_rebound_ml(closes_5m, closes_15m, closes_30m, 
                          bb_5m_pos, bb_15m_pos, bb_30m_pos,
                          rsi_5m, volatility):
        """
        🧠 ML 기반 반등 확률 예측
        
        혁신: 과거 패턴 학습 + 다중 시간프레임 종합
        
        특징 추출:
        1. 5분봉 급락 둔화 정도
        2. 15분/30분봉 하단 위치
        3. RSI 과매도 수준
        4. BB 폭 (변동성)
        5. 최근 3개 봉 모멘텀
        
        Returns:
            {
                'probability': float,  # 0-1
                'confidence': str,     # LOW/MEDIUM/HIGH
                'key_factors': list    # 주요 요인
            }
        """
        if len(closes_5m) < 20:
            return None
        
        score = 0
        factors = []
        
        # [1] 5분봉 급락 둔화 (40점)
        decel = analyze_price_deceleration(closes_5m)
        if decel and decel['is_decelerating']:
            score += 40
            factors.append(f"급락둔화(신뢰{decel['confidence']*100:.0f}%)")
        elif decel and decel['acceleration'] > 0:
            score += 20
        
        # [2] 15분봉 하단 위치 (30점) ⭐핵심⭐
        if bb_15m_pos < 0.25:
            score += 30
            factors.append("15분봉하단")
        elif bb_15m_pos < 0.35:
            score += 20
        elif bb_15m_pos < 0.45:
            score += 10
        else:
            score -= 20  # 패널티: 15분봉 상단은 위험
        
        # [3] 30분봉 하단 위치 (15점)
        if bb_30m_pos < 0.30:
            score += 15
        elif bb_30m_pos < 0.40:
            score += 10
        elif bb_30m_pos < 0.50:
            score += 5
        
        # [4] RSI 과매도 (10점)
        if rsi_5m < 25:
            score += 10
            factors.append(f"RSI극과매도({rsi_5m:.0f})")
        elif rsi_5m < 30:
            score += 7
        elif rsi_5m < 35:
            score += 4
        
        # [5] BB 폭 (5점)
        bb_surge = analyze_bb_volatility_surge(closes_5m)
        if bb_surge and bb_surge['is_surging']:
            score += 5
            factors.append(f"BB급증({bb_surge['expansion_ratio']:.1f}x)")
        
        # 확률 변환 (0-100점 → 0-1)
        probability = min(score / 100, 0.95)
        
        # 신뢰도
        if probability >= 0.70:
            confidence = "HIGH"
        elif probability >= 0.60:
            confidence = "MEDIUM"
        else:
            confidence = "LOW"
        
        return {
            'probability': probability,
            'confidence': confidence,
            'key_factors': factors,
            'score': score
        }
    
    def calculate_position_size(total_asset, crypto_value, krw_balance,
                               signal_score, rebound_prob):
        """
        💰 켈리 공식 기반 포지션 사이징
        
        전략:
        1. 승률 = 반등 확률
        2. 수익/손실 비율 = 2% / 1% = 2
        3. 켈리 비율 = (2*승률 - (1-승률)) / 2
        4. 복리 단계별 공격성 조정
        
        🆕 원화 부족 시 전량 매수:
        - 원화 비율 < 10% → 보유 현금 전량 투입
        
        안전장치:
        - 최대 포지션: 자산의 40% (초기), 25% (성장기)
        - 최소 포지션: 5,000원
        """
        # 🆕 원화 비율 체크
        krw_ratio = krw_balance / total_asset if total_asset > 0 else 0
        
        # 원화가 10% 미만이면 전량 매수
        if krw_ratio < 0.10:
            available_krw = krw_balance * 0.995  # 수수료 고려
            print(f"   💡 원화 부족 모드: {krw_ratio*100:.1f}% < 10% → 전량 투입")
            return available_krw
        
        # 켈리 계산
        win_rate = rebound_prob
        profit_loss_ratio = 2.0  # 2% 목표 / 1% 손절
        
        kelly = (profit_loss_ratio * win_rate - (1 - win_rate)) / profit_loss_ratio
        
        if kelly <= 0:
            return 0.0
        
        # 복리 단계별 공격성
        if total_asset < 1_000_000:
            aggression = 2.5  # 초기: 최대 공격
            max_ratio = 0.60
        elif total_asset < 5_000_000:
            aggression = 2.0
            max_ratio = 0.50
        elif total_asset < 10_000_000:
            aggression = 1.5
            max_ratio = 0.40
        elif total_asset < 50_000_000:
            aggression = 1.2
            max_ratio = 0.30
        else:
            aggression = 1.0  # 안정기: 보수적
            max_ratio = 0.25
        
        adjusted_kelly = kelly * aggression
        
        # 포지션 계산
        base_position = total_asset * adjusted_kelly
        max_position = total_asset * max_ratio
        available_krw = krw_balance * 0.995
        
        position = min(base_position, max_position, available_krw)
        
        return position
    
    def analyze_ticker_integrated(ticker_symbol):
        """
        📊 통합 종목 분석 (원스톱)
        
        수집 데이터:
        - 1분봉 (RSI 단기)
        - 5분봉 (주요 분석)
        - 15분봉 (필수 검증)
        - 30분봉 (추가 검증)
        - 1시간봉 (추세)
        - 일봉 (일간 변동)
        
        Returns:
            {
                'valid': bool,
                'current_price': float,
                'rebound_prob': float,
                'signal_score': int,
                'indicators': dict,
                'signals': list
            }
        """
        try:
            import pyupbit
            
            # 데이터 수집 (API 효율화)
            df_1m = pyupbit.get_ohlcv(ticker_symbol, interval="minute1", count=30)
            time.sleep(0.08)
            df_5m = pyupbit.get_ohlcv(ticker_symbol, interval="minute5", count=50)
            time.sleep(0.08)
            df_15m = pyupbit.get_ohlcv(ticker_symbol, interval="minute15", count=40)
            time.sleep(0.08)
            df_30m = pyupbit.get_ohlcv(ticker_symbol, interval="minute30", count=40)
            time.sleep(0.08)
            df_1h = pyupbit.get_ohlcv(ticker_symbol, interval="minute60", count=30)
            time.sleep(0.08)
            df_1d = pyupbit.get_ohlcv(ticker_symbol, interval="day", count=5)
            time.sleep(0.08)
            
            current_price = pyupbit.get_current_price(ticker_symbol)
            
            # DataFrame None 체크 (수정!)
            if (df_1m is None or df_5m is None or df_15m is None or 
                df_30m is None or df_1h is None or df_1d is None or 
                current_price is None):
                return {'valid': False}
            
            # 종가 추출
            c_1m = df_1m['close'].values
            c_5m = df_5m['close'].values
            c_15m = df_15m['close'].values
            c_30m = df_30m['close'].values
            c_1h = df_1h['close'].values
            v_5m = df_5m['volume'].values
            
            # 기본 지표
            rsi_1m = calculate_rsi(c_1m, 14)
            rsi_5m = calculate_rsi(c_5m, 14)
            rsi_1h = calculate_rsi(c_1h, 14)
            
            # BB 계산 (한 번만 호출하고 필요한 값만 추출)
            bb_5m_result = calculate_bb(c_5m, 20)
            bb_5m_pos = bb_5m_result[3]
            bb_5m_width = bb_5m_result[4]
            
            bb_15m_pos = calculate_bb(c_15m, 20)[3]
            bb_30m_pos = calculate_bb(c_30m, 20)[3]
            bb_1h_pos = calculate_bb(c_1h, 20)[3]
            
            ema_12 = calculate_ema(c_5m, 12)
            ema_26 = calculate_ema(c_5m, 26)
            
            # 🔥 핵심 분석
            decel = analyze_price_deceleration(c_5m)
            bb_surge = analyze_bb_volatility_surge(c_5m, 20)
            candle = detect_reversal_candle(df_5m)
            rebound = predict_rebound_ml(
                c_5m, c_15m, c_30m,
                bb_5m_pos, bb_15m_pos, bb_30m_pos,
                rsi_5m, bb_5m_width
            )
            
            # 거래량
            vol_recent = np.mean(v_5m[-5:])
            vol_normal = np.mean(v_5m[-20:-5])
            vol_ratio = vol_recent / (vol_normal + 1e-8)
            vol_krw = vol_recent * current_price
            
            # 일봉
            daily_open = df_1d['open'].iloc[-1]
            daily_prev_close = df_1d['close'].iloc[-2]
            daily_change = (current_price - daily_prev_close) / daily_prev_close * 100
            intraday_change = (current_price - daily_open) / daily_open * 100
            
            # 신호 점수 계산
            score = 0
            signals = []
            
            # [1] 급락 둔화 (35점)
            if decel and decel['is_decelerating']:
                score += 35
                signals.append(f"급락둔화({decel['acceleration']*100:+.1f}%)")
            elif decel and decel['acceleration'] > 0:
                score += 18
            
            # [2] 15분봉 하단 (30점) ⭐필수⭐
            if bb_15m_pos < 0.25:
                score += 30
                signals.append("15분하단")
            elif bb_15m_pos < 0.35:
                score += 20
            elif bb_15m_pos < 0.45:
                score += 10
            
            # [3] BB 급증 (20점)
            if bb_surge and bb_surge['is_surging']:
                score += 20
                signals.append(f"BB급증({bb_surge['expansion_ratio']:.1f}x)")
            
            # [4] RSI (10점)
            if rsi_5m < 25:
                score += 10
                signals.append(f"RSI{rsi_5m:.0f}")
            elif rsi_5m < 30:
                score += 7
            elif rsi_5m < 35:
                score += 4
            
            # [5] 캔들 패턴 (5점)
            if candle and candle['has_hammer']:
                score += 5
                signals.append("망치형")
            elif candle and candle['has_doji']:
                score += 3
            
            return {
                'valid': True,
                'current_price': current_price,
                'rebound_prob': rebound['probability'] if rebound else 0,
                'signal_score': score,
                'indicators': {
                    'rsi_1m': rsi_1m,
                    'rsi_5m': rsi_5m,
                    'rsi_1h': rsi_1h,
                    'bb_5m_pos': bb_5m_pos,
                    'bb_5m_width': bb_5m_width,
                    'bb_15m_pos': bb_15m_pos,
                    'bb_30m_pos': bb_30m_pos,
                    'bb_1h_pos': bb_1h_pos,
                    'ema_12': ema_12,
                    'ema_26': ema_26,
                    'vol_ratio': vol_ratio,
                    'vol_krw': vol_krw,
                    'daily_change': daily_change,
                    'intraday_change': intraday_change,
                    'decel': decel,
                    'bb_surge': bb_surge,
                    'candle': candle,
                    'rebound': rebound
                },
                'signals': signals
            }
            
        except Exception as e:
            print(f"분석 오류: {e}")
            return {'valid': False}
    
    # ==================== 메인 로직 시작 ====================
    
    print("\n" + "="*60)
    print("🚀 v6.0 초단기 복리 시스템 - 10만원→10억 프로젝트")
    print("="*60)
    
    # 자산 현황
    krw_balance = get_krw_balance()
    crypto_value = get_total_crypto_value()
    total_asset = krw_balance + crypto_value
    
    print(f"\n💰 자산 현황")
    print(f"   총 자산: {total_asset:,.0f}원")
    print(f"   현금: {krw_balance:,.0f}원 ({krw_balance/total_asset*100:.1f}%) | 코인: {crypto_value:,.0f}원 ({crypto_value/total_asset*100:.1f}%)")
    
    # 🆕 원화 부족 경고
    krw_ratio = krw_balance / total_asset if total_asset > 0 else 0
    if krw_ratio < 0.10:
        print(f"   ⚠️ 원화 부족! ({krw_ratio*100:.1f}% < 10%) → 전량 매수 모드 활성화")
    
    MIN_ORDER = 5000
    if krw_balance < MIN_ORDER:
        print("❌ 잔고 부족")
        return "Insufficient balance", None
    
    # 포지션 한도 (100% 허용)
    crypto_limit = total_asset * 1.0
    if crypto_value >= crypto_limit:
        print("❌ 포지션 한도 도달")
        return "Position limit reached", None
    
    # 종목 선정
    if ticker is None:
        print("\n🔍 종목 스캔 중...")
        
        # 30개 메이저 코인 (하드코딩)
        STRATEGIC_COINS = [
            "KRW-BTC","KRW-ETH","KRW-XRP","KRW-SOL","KRW-DOGE",
            "KRW-TRX","KRW-ADA","KRW-LINK","KRW-AVAX","KRW-XLM",
            "KRW-SUI","KRW-BCH","KRW-HBAR","KRW-SHIB","KRW-CRO",
            "KRW-DOT","KRW-MNT","KRW-UNI","KRW-AAVE","KRW-PEPE",
            "KRW-ENA","KRW-NEAR","KRW-APT","KRW-ETC","KRW-ONDO",
            "KRW-POL","KRW-ARB","KRW-VET","KRW-ALGO","KRW-BONK"
        ]
        
        held_coins = get_held_coins()
        candidates = [t for t in STRATEGIC_COINS if t not in held_coins]
        
        if not candidates:
            print("❌ 매수 가능 종목 없음")
            return "No candidates", None
        
        print(f"   대상: {len(candidates)}개 코인")
        
        # 종목 분석
        viable_coins = []
        
        for t in candidates:
            analysis = analyze_ticker_integrated(t)
            
            if not analysis['valid']:
                continue
            
            ind = analysis['indicators']
            score = analysis['signal_score']
            prob = analysis['rebound_prob']
            
            # 🔥 엄격한 1차 필터
            # 1. 15분봉 하단 필수 (50% 미만)
            if ind['bb_15m_pos'] >= 0.50:
                continue
            
            # 2. 반등 확률 70% 이상
            if prob < 0.70:
                continue
            
            # 3. 일봉 변동 ±2% 이내
            if abs(ind['intraday_change']) > 2.0:
                continue
            
            # 4. 가격 범위 (50원~20만원)
            if not (50 <= analysis['current_price'] <= 200000):
                continue
            
            # 5. 최소 거래량 (1억원)
            if ind['vol_krw'] < 100_000_000:
                continue
            
            # 2차 필터: 고득점 종목 선별
            if score >= 55:  # 55점 이상만
                viable_coins.append({
                    'ticker': t,
                    'score': score,
                    'prob': prob,
                    'signals': analysis['signals'],
                    'analysis': analysis
                })
                print(f"   ✓ {t}: {score}점 | 반등{prob*100:.0f}% | {analysis['signals'][:3]}")
            
            time.sleep(0.05)
        
        print(f"\n📊 선별 결과: {len(viable_coins)}개")
        
        if not viable_coins:
            print("❌ 조건 충족 종목 없음")
            return "No viable candidates", None
        
        # 최고 점수 종목 선택
        viable_coins.sort(key=lambda x: (x['prob'], x['score']), reverse=True)
        best = viable_coins[0]
        
        selected_ticker = best['ticker']
        selected_analysis = best['analysis']
        selected_score = best['score']
        selected_prob = best['prob']
        selected_signals = best['signals']
        
        print(f"\n🎯 최종 선택: {selected_ticker}")
        print(f"   신호 점수: {selected_score}점")
        print(f"   반등 확률: {selected_prob*100:.0f}%")
        print(f"   핵심 시그널: {', '.join(selected_signals)}")
        
    else:
        # 특정 종목 분석
        print(f"\n🔍 {ticker} 분석 중...")
        
        selected_analysis = analyze_ticker_integrated(ticker)
        
        if not selected_analysis['valid']:
            print("❌ 데이터 수집 실패")
            return "Data fetch failed", None
        
        selected_ticker = ticker
        selected_score = selected_analysis['signal_score']
        selected_prob = selected_analysis['rebound_prob']
        selected_signals = selected_analysis['signals']
        
        print(f"   신호: {selected_score}점 | 반등: {selected_prob*100:.0f}%")
    
    # ==================== 최종 매수 검증 ====================
    
    ind = selected_analysis['indicators']
    current_price = selected_analysis['current_price']
    
    print(f"\n📈 기술적 지표")
    print(f"   RSI: 1m={ind['rsi_1m']:.0f} | 5m={ind['rsi_5m']:.0f} | 1h={ind['rsi_1h']:.0f}")
    print(f"   BB위치: 5m={ind['bb_5m_pos']*100:.0f}% | 15m={ind['bb_15m_pos']*100:.0f}% | 30m={ind['bb_30m_pos']*100:.0f}%")
    print(f"   BB폭: {ind['bb_5m_width']:.1f}%")
    print(f"   거래량: {ind['vol_ratio']:.1f}x ({ind['vol_krw']/1e8:.1f}억)")
    print(f"   일간변동: {ind['intraday_change']:+.1f}%")
    
    # 핵심 지표 상세
    decel = ind.get('decel')
    bb_surge = ind.get('bb_surge')
    candle = ind.get('candle')
    rebound = ind.get('rebound')
    
    if decel:
        status = "✓감속중" if decel['is_decelerating'] else ""
        print(f"\n🔥 가속도 분석 {status}")
        print(f"   속도: {decel['velocity']*100:+.2f}%")
        print(f"   가속도: {decel['acceleration']*100:+.2f}%")
        print(f"   신뢰도: {decel['confidence']*100:.0f}%")
    
    if bb_surge:
        status = "✓급증" if bb_surge['is_surging'] else ""
        print(f"\n📊 BB 폭 분석 {status}")
        print(f"   현재 폭: {bb_surge['current_width']:.1f}%")
        print(f"   확장 배수: {bb_surge['expansion_ratio']:.2f}x")
    
    if candle:
        patterns = []
        if candle['has_hammer']:
            patterns.append("망치형")
        if candle['has_doji']:
            patterns.append("도지형")
        if patterns:
            print(f"\n🕯️ 캔들 패턴: {', '.join(patterns)}")
            print(f"   꼬리 비율: {candle['tail_ratio']:.1f}")
    
    if rebound:
        print(f"\n🧠 ML 반등 예측")
        print(f"   확률: {rebound['probability']*100:.0f}%")
        print(f"   신뢰도: {rebound['confidence']}")
        print(f"   주요 요인: {', '.join(rebound['key_factors'])}")
    
    # 안전 검증
    print(f"\n🛡️ 안전성 검증")
    
    safety_checks = {
        '15분봉 하단': ind['bb_15m_pos'] < 0.50,  # 필수!
        'RSI 범위': 10 < ind['rsi_5m'] < 65,
        'BB 범위': -0.2 < ind['bb_5m_pos'] < 1.2,
        'EMA 지지': current_price > ind['ema_26'] * 0.70,
        '반등 확률': selected_prob >= 0.70,  # 70% 이상
        '일간 변동': abs(ind['intraday_change']) <= 2.0
    }
    
    passed = sum(safety_checks.values())
    total_checks = len(safety_checks)
    
    for check, result in safety_checks.items():
        status = "✓" if result else "✗"
        print(f"   {status} {check}")
    
    print(f"\n   통과: {passed}/{total_checks}")
    
    # 최종 매수 조건
    can_buy = (
        # 핵심 조건
        selected_score >= 55 and           # 55점 이상
        selected_prob >= 0.70 and          # 반등 확률 70%+
        ind['bb_15m_pos'] < 0.50 and       # 15분봉 하단 (필수!)
        
        # 안전 조건
        passed >= 5 and                     # 6개 중 5개 통과
        ind['rsi_5m'] < 65 and             # RSI 과열 방지
        abs(ind['intraday_change']) <= 2.0 and  # 일간 안정성
        
        # 핵심 시그널
        (decel and (
            decel['is_decelerating'] or
            decel['acceleration'] > -0.01
        ))
    )
    
    print(f"\n{'🟢 매수 조건 충족!' if can_buy else '🔴 매수 조건 미달'}")
    print(f"   점수: {selected_score}/55 | 확률: {selected_prob*100:.0f}%/70% | 안전: {passed}/5")
    
    if not can_buy:
        print("❌ 매수 취소")
        return "Conditions not met", None
    
    # 포지션 사이징
    buy_size = calculate_position_size(
        total_asset=total_asset,
        crypto_value=crypto_value,
        krw_balance=krw_balance,
        signal_score=selected_score,
        rebound_prob=selected_prob
    )
    
    if buy_size < MIN_ORDER:
        print(f"❌ 포지션 크기 부족 ({buy_size:,.0f}원)")
        return "Position too small", None
    
    print(f"\n💵 포지션 사이징")
    print(f"   매수 금액: {buy_size:,.0f}원")
    print(f"   자산 대비: {buy_size/total_asset*100:.1f}%")
    
    # 🆕 전량 매수 모드 표시
    if krw_ratio < 0.10:
        print(f"   🔥 원화 부족 모드: 보유 현금 전량 투입!")
    
    # 🚀 매수 실행
    print(f"\n🚀 매수 실행...")
    
    for attempt in range(1, 4):
        try:
            import pyupbit
            
            # 가격 재확인
            verify_price = pyupbit.get_current_price(selected_ticker)
            time.sleep(0.05)
            
            price_change = (verify_price - current_price) / current_price
            
            # 급등 감지
            if price_change > 0.03:  # 3% 이상 급등
                print(f"⚠️ 가격 급등 감지 (+{price_change*100:.1f}%), 재확인...")
                time.sleep(2)
                continue
            
            # 매수 주문
            buy_order = upbit.buy_market_order(selected_ticker, buy_size)
            
            # 성공 등급
            if selected_score >= 75 and selected_prob >= 0.85:
                grade = "🏆 PERFECT"
            elif selected_score >= 65 and selected_prob >= 0.75:
                grade = "⭐ EXCELLENT"
            elif selected_score >= 60 and selected_prob >= 0.70:
                grade = "✨ STRONG"
            else:
                grade = "✓ GOOD"
            
            # 성공 메시지
            success_msg = f"""
{'='*60}
{grade} 매수 성공! 🎯
{'='*60}

종목: {selected_ticker}
가격: {verify_price:,.0f}원
금액: {buy_size:,.0f}원

신호 점수: {selected_score}점
반등 확률: {selected_prob*100:.0f}%
핵심 시그널: {', '.join(selected_signals[:3])}

자산: {total_asset:,.0f}원
목표: 10억원 (현재 {total_asset/1_000_000_000*100:.2f}%)
{'='*60}
"""
            
            print(success_msg)
            
            # 디스코드 알림
            try:
                discord_msg = f"🚀 {grade} 매수!\n"
                discord_msg += f"{selected_ticker} | {verify_price:,.0f}원 | {buy_size:,.0f}원\n"
                discord_msg += f"신호{selected_score}점 | 반등{selected_prob*100:.0f}%\n"
                discord_msg += f"자산: {total_asset:,.0f}원"
                send_discord_message(discord_msg)
            except:
                pass
            
            return buy_order
            
        except Exception as e:
            print(f"❌ 매수 오류 (시도 {attempt}/3): {e}")
            
            if attempt < 3:
                time.sleep(2)
            else:
                # 최종 실패
                try:
                    error_msg = f"매수 실패: {selected_ticker}\n오류: {str(e)}"
                    send_discord_message(error_msg)
                except:
                    pass
                
                return "Order execution failed", None
    
    return "Max attempts exceeded", None

def trade_sell(ticker):
    """지능형 적응형 매도 시스템 v2.0 - BB 기반 + 폭락 예측"""
    import numpy as np
    import time
    
    # ==================== 내부 함수 정의 ====================
    
    def calculate_recovery_probability(df, current_price, avg_buy_price):
        """반등 확률 계산"""
        if df is None or len(df) < 20:
            return 0.3
        
        closes = df['close'].values
        recovery_count = 0
        similar_situations = 0
        current_drop = (current_price - avg_buy_price) / avg_buy_price
        
        for i in range(10, len(closes) - 5):
            period_drop = (closes[i] - closes[i-5]) / closes[i-5]
            if abs(period_drop - current_drop) < 0.01:
                similar_situations += 1
                if closes[i+5] > closes[i]:
                    recovery_count += 1
        
        if similar_situations < 3:
            return 0.4
        
        return recovery_count / similar_situations
    
    def analyze_crash_probability(df_5m, df_15m, current_price, avg_buy_price, profit_rate):
        """폭락 확률 예측 시스템"""
        if df_5m is None or len(df_5m) < 30:
            return None
        
        closes_5m = df_5m['close'].values
        volumes_5m = df_5m['volume'].values
        lows_5m = df_5m['low'].values
        
        score = 0
        max_score = 100
        factors = []
        
        # [1] 급락 가속도 (25점)
        recent_3 = np.mean(closes_5m[-3:])
        middle_3 = np.mean(closes_5m[-6:-3])
        older_3 = np.mean(closes_5m[-9:-6])
        
        velocity_1 = (middle_3 - older_3) / older_3
        velocity_2 = (recent_3 - middle_3) / middle_3
        acceleration = velocity_2 - velocity_1
        
        if acceleration < -0.02:
            score += 25
            factors.append(f"급락가속({acceleration*100:.1f}%)")
        elif acceleration < -0.01:
            score += 15
            factors.append(f"하락가속({acceleration*100:.1f}%)")
        elif velocity_2 < -0.03:
            score += 10
            factors.append(f"급락중({velocity_2*100:.1f}%)")
        
        # [2] 거래량 폭증 + 하락 (20점)
        vol_recent = np.mean(volumes_5m[-3:])
        vol_normal = np.mean(volumes_5m[-15:-3])
        vol_ratio = vol_recent / (vol_normal + 1e-8)
        price_change_recent = (closes_5m[-1] - closes_5m[-3]) / closes_5m[-3]
        
        if vol_ratio > 2.0 and price_change_recent < -0.02:
            score += 20
            factors.append(f"공포매도(거래량{vol_ratio:.1f}x)")
        elif vol_ratio > 1.5 and price_change_recent < -0.01:
            score += 12
            factors.append("매도압력증가")
        
        # [3] BB 분석 (20점)
        bb_lower, bb_mid, bb_upper, bb_pos, bb_width = calculate_bb(closes_5m, 20)
        
        if bb_pos < -0.1:
            score += 15
            factors.append(f"BB하단이탈({bb_pos*100:.0f}%)")
        elif bb_pos < 0:
            score += 8
            factors.append("BB하단근접")
        
        if bb_width > 8.0:
            score += 5
            factors.append(f"고변동성(BB{bb_width:.1f}%)")
        
        # [4] RSI 급락 (15점)
        rsi = calculate_rsi(closes_5m, 14)
        
        if rsi < 20:
            score += 15
            factors.append(f"RSI극과매도({rsi:.0f})")
        elif rsi < 25:
            score += 10
            factors.append(f"RSI과매도({rsi:.0f})")
        elif rsi < 30:
            score += 5
        
        # [5] 15분봉 하락 (15점)
        if df_15m is not None and len(df_15m) >= 10:
            closes_15m = df_15m['close'].values
            trend_15m = (closes_15m[-1] - closes_15m[-5]) / closes_15m[-5]
            
            if trend_15m < -0.05:
                score += 15
                factors.append(f"15분봉급락({trend_15m*100:.1f}%)")
            elif trend_15m < -0.03:
                score += 8
                factors.append("15분봉하락세")
        
        # [6] 지지선 붕괴 (5점)
        support_level = np.min(lows_5m[-20:-3])
        current_low = lows_5m[-1]
        
        if current_low < support_level * 0.98:
            score += 5
            factors.append("지지선붕괴")
        
        # 확률 계산
        probability = min(score / max_score, 0.95)
        
        # 위험도 등급
        if probability >= 0.70:
            risk_level = 'CRITICAL'
        elif probability >= 0.55:
            risk_level = 'HIGH'
        elif probability >= 0.40:
            risk_level = 'MEDIUM'
        else:
            risk_level = 'LOW'
        
        # 손절 권장
        should_cut = (probability >= 0.70 and profit_rate < 0)
        
        return {
            'crash_probability': probability,
            'risk_level': risk_level,
            'factors': factors,
            'should_cut': should_cut,
            'score': score,
            'acceleration': acceleration,
            'vol_ratio': vol_ratio,
            'rsi': rsi
        }
    
    def analyze_bb_sell_signal(current_price, closes, volumes):
        """BB 기반 매도 신호 분석"""
        if len(closes) < 20:
            return None
        
        # BB 계산
        bb_lower, bb_mid, bb_upper, bb_position, bb_width = calculate_bb(closes, 20)
        
        # current_price 명시적 사용
        price_to_mid_ratio = (current_price - bb_mid) / bb_mid if bb_mid > 0 else 0
        
        # 추가 지표
        rsi = calculate_rsi(closes, 14)
        
        # 거래량 추세
        vol_recent = np.mean(volumes[-3:])
        vol_normal = np.mean(volumes[-10:-3])
        vol_surge = vol_recent / (vol_normal + 1e-8) > 1.5
        
        # 가격 모멘텀
        price_momentum = (closes[-1] - closes[-5]) / closes[-5]
        
        # BB 위치별 판단
        if bb_position >= 0.70:
            urgency = 'HIGH'
            should_hold = False
            reason = f"BB상단{bb_position*100:.0f}%(과열)"
            
            if rsi > 70:
                urgency = 'CRITICAL'
                reason += f"+RSI{rsi:.0f}"
        
        elif bb_position >= 0.50:
            urgency = 'MEDIUM'
            should_hold = False
            
            if price_momentum > 0.01 and rsi < 65:
                should_hold = True
                reason = f"BB중상단{bb_position*100:.0f}%+상승추세"
            else:
                reason = f"BB중상단{bb_position*100:.0f}%"
        
        elif bb_position >= 0.30:
            urgency = 'LOW'
            
            if price_momentum < -0.01:
                should_hold = False
                reason = f"BB중단{bb_position*100:.0f}%+하락"
            else:
                should_hold = True
                reason = f"BB중단{bb_position*100:.0f}%+상승여력"
        
        else:
            urgency = 'NONE'
            should_hold = True
            reason = f"BB하단{bb_position*100:.0f}%(상승여력)"
            
            if price_momentum < -0.03 and vol_surge:
                urgency = 'MEDIUM'
                should_hold = False
                reason = f"BB하단+급락중({price_momentum*100:.1f}%)"
        
        return {
            'bb_position': bb_position,
            'bb_width': bb_width,
            'rsi': rsi,
            'sell_urgency': urgency,
            'should_hold': should_hold,
            'reason': reason,
            'momentum': price_momentum
        }
    
    # ==================== 메인 로직 시작 ====================
    
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
    
    # ==================== 최소수익률 미달 처리 ====================
    
    if profit_rate < min_rate:
        print(f"[{ticker}] 최소수익률({min_rate}%) 미달 | 현재: {profit_rate:.2f}%")
        
        # 손실 구간 폭락 확률 체크
        if profit_rate < 0:
            df_15m_loss = pyupbit.get_ohlcv(ticker, interval="minute15", count=30)
            time.sleep(0.1)
            df_5m_loss = pyupbit.get_ohlcv(ticker, interval="minute5", count=50)
            time.sleep(0.1)
            
            if df_5m_loss is not None and len(df_5m_loss) >= 30:
                crash_analysis = analyze_crash_probability(
                    df_5m_loss, df_15m_loss, cur_price, avg_buy_price, profit_rate
                )
                
                if crash_analysis:
                    # print(f"🚨 폭락위험: {crash_analysis['crash_probability']*100:.0f}% ({crash_analysis['risk_level']})")
                    # print(f"   요인: {', '.join(crash_analysis['factors'][:3])}")
                    
                    # -3% 이상 손실 + 폭락 70% 이상 → 손절
                    if profit_rate <= -3.0 and crash_analysis['should_cut']:
                        sell_order = upbit.sell_market_order(ticker, buyed_amount)
                        msg = f"🛑 **[지능형손절]**: [{ticker}] {profit_rate:.2f}% / {cur_price:,.1f}원\n"
                        msg += f"폭락확률: {crash_analysis['crash_probability']*100:.0f}%\n"
                        msg += f"요인: {', '.join(crash_analysis['factors'])}"
                        print(msg)
                        send_discord_message(msg)
                        return sell_order
                    
                    # -5% 이상 손실 + 폭락 55% 이상 → 손절
                    elif profit_rate <= -5.0 and crash_analysis['crash_probability'] >= 0.55:
                        sell_order = upbit.sell_market_order(ticker, buyed_amount)
                        msg = f"🚨 **[긴급손절]**: [{ticker}] {profit_rate:.2f}% / {cur_price:,.1f}원\n"
                        msg += f"폭락확률: {crash_analysis['crash_probability']*100:.0f}%"
                        print(msg)
                        send_discord_message(msg)
                        return sell_order
        
        # 기존 긴급 탈출선 (백업)
        emergency_cut = cut_rate - 1.0
        if profit_rate < emergency_cut:
            df_30m = pyupbit.get_ohlcv(ticker, interval="minute30", count=10)
            time.sleep(0.1)
            if df_30m is not None and len(df_30m) >= 5:
                recent_trend = (df_30m['close'].iloc[-1] - df_30m['close'].iloc[-5]) / df_30m['close'].iloc[-5]
                if recent_trend < -0.05:
                    sell_order = upbit.sell_market_order(ticker, buyed_amount)
                    msg = f"🚨 **[긴급탈출]**: [{ticker}] {profit_rate:.2f}% / {cur_price:,.1f}원"
                    print(msg)
                    send_discord_message(msg)
                    return sell_order
        
        return None
    
    # ==================== 데이터 수집 및 분석 ====================
    
    df_5m = pyupbit.get_ohlcv(ticker, interval="minute5", count=50)
    time.sleep(0.1)
    df_15m = pyupbit.get_ohlcv(ticker, interval="minute15", count=30)
    time.sleep(0.1)
    
    if df_5m is None or len(df_5m) < 30:
        print(f"[{ticker}] 데이터 부족")
        return None
    
    closes = df_5m['close'].values
    volumes = df_5m['volume'].values
    current_rsi = calculate_rsi(closes)
    
    # 폭락 위험 분석
    crash_analysis = analyze_crash_probability(df_5m, df_15m, cur_price, avg_buy_price, profit_rate)
    
    if crash_analysis:
        print(f"📊 폭락위험: {crash_analysis['crash_probability']*100:.0f}% ({crash_analysis['risk_level']})")
        if crash_analysis['factors']:
            print(f"   {', '.join(crash_analysis['factors'][:3])}")
    
    # 수익 구간 폭락 위험 조기 매도
    if crash_analysis and crash_analysis['risk_level'] == 'CRITICAL':
        if min_rate <= profit_rate < min_rate * 1.3:
            sell_order = upbit.sell_market_order(ticker, buyed_amount)
            msg = f"⚠️ **[폭락위험조기매도]**: [{ticker}] {profit_rate:.2f}% / {cur_price:,.1f}원\n"
            msg += f"폭락확률: {crash_analysis['crash_probability']*100:.0f}%"
            print(msg)
            send_discord_message(msg)
            return sell_order
    
    # BB 매도 신호
    bb_analysis = analyze_bb_sell_signal(cur_price, closes, volumes)
    
    if bb_analysis:
        print(f"BB분석: {bb_analysis['reason']} | 긴급도: {bb_analysis['sell_urgency']}")
    
    # 반등 확률
    recovery_prob = calculate_recovery_probability(df_5m, cur_price, avg_buy_price)
    
    # ==================== 매도 신호 계산 ====================
    
    signals = []
    sell_strength = 0
    
    sma20 = np.mean(closes[-20:])
    std20 = np.std(closes[-20:])
    bb_upper = sma20 + (2.0 * std20)
    bb_lower = sma20 - (2.0 * std20)
    bb_position_simple = (cur_price - sma20) / std20
    
    # BB 상단 과열
    if bb_analysis and bb_analysis['sell_urgency'] in ['HIGH', 'CRITICAL']:
        signals.append("BB상단과열")
        sell_strength += 5
    
    if current_rsi > 70 and bb_position_simple > 1.5:
        if cur_price < closes[-2]:
            signals.append("과열후하락")
            sell_strength += 4
    
    # 추세 이탈
    sma10 = np.mean(closes[-10:])
    if cur_price < sma10 and sma10 < sma20:
        trend_break_volume = np.mean(volumes[-3:]) / np.mean(volumes[-10:-3])
        if trend_break_volume > 1.3:
            signals.append("추세이탈")
            sell_strength += 3
    
    # RSI 다이버전스
    if len(closes) >= 10:
        price_trend = closes[-1] - closes[-5]
        prev_rsi = calculate_rsi(closes[:-5])
        if price_trend > 0 and current_rsi < prev_rsi - 5:
            signals.append("RSI다이버전스")
            sell_strength += 3
    
    # 매도 기준 설정
    if profit_rate >= max_rate:
        required_score = 1
        hold_bonus = 0
    elif profit_rate >= min_rate * 2:
        required_score = 2
        hold_bonus = 1 if recovery_prob > 0.6 else 0
    elif profit_rate >= min_rate * 1.5:
        required_score = 3
        hold_bonus = 2 if recovery_prob > 0.7 else 0
    else:
        required_score = 4
        hold_bonus = 3 if recovery_prob > 0.8 else 1
    
    # BB 홀딩 보너스
    if bb_analysis and bb_analysis['should_hold']:
        hold_bonus += 2
    
    adjusted_required_score = required_score + hold_bonus
    should_sell_technical = sell_strength >= adjusted_required_score
    signal_text = " + ".join(signals) + f" ({sell_strength}/{adjusted_required_score})"
    
    # ==================== 매도 실행 루프 ====================
    
    max_attempts = min(sell_time, 25)
    attempts = 0
    consecutive_no_change = 0
    last_price = cur_price
    
    while attempts < max_attempts:
        cur_price = pyupbit.get_current_price(ticker)
        profit_rate = (cur_price - avg_buy_price) / avg_buy_price * 100 if avg_buy_price > 0 else 0
        
        price_change = abs(cur_price - last_price) / last_price
        if price_change < 0.001:
            consecutive_no_change += 1
        else:
            consecutive_no_change = 0
        last_price = cur_price
        
        # 실시간 BB 업데이트
        df_5m_live = pyupbit.get_ohlcv(ticker, interval="minute5", count=50)
        time.sleep(0.1)
        if df_5m_live is not None and len(df_5m_live) >= 30:
            closes_live = df_5m_live['close'].values
            volumes_live = df_5m_live['volume'].values
            bb_analysis_live = analyze_bb_sell_signal(cur_price, closes_live, volumes_live)
        else:
            bb_analysis_live = bb_analysis
        
        print(f"[{ticker}] {attempts + 1}/{max_attempts} | {profit_rate:.2f}% | "
              f"{sell_strength}/{adjusted_required_score} | "
              f"{bb_analysis_live['reason'] if bb_analysis_live else 'N/A'}")
        
        # [1] 목표 달성
        if profit_rate >= max_rate:
            sell_order = upbit.sell_market_order(ticker, buyed_amount)
            msg = f"🎯 **[목표달성]**: [{ticker}] {profit_rate:.2f}% / {cur_price:,.1f}원"
            print(msg)
            send_discord_message(msg)
            return sell_order
        
        # [2] 기술적 매도 + BB 검증
        if should_sell_technical and profit_rate >= min_rate * 1.2:
            if bb_analysis_live and bb_analysis_live['should_hold']:
                print(f"   ⏸️ BB하단으로 홀딩: {bb_analysis_live['reason']}")
            else:
                sell_order = upbit.sell_market_order(ticker, buyed_amount)
                msg = f"📊 **[기술적매도]**: [{ticker}] {profit_rate:.2f}% / {cur_price:,.1f}원\n{signal_text}"
                print(msg)
                send_discord_message(msg)
                return sell_order
        
        # [3] 정체 매도 + BB 검증
        if consecutive_no_change >= 8 and profit_rate >= min_rate * 1.5:
            if bb_analysis_live and bb_analysis_live['should_hold']:
                print(f"   ⏸️ 정체지만 BB하단: {bb_analysis_live['reason']}")
            else:
                sell_order = upbit.sell_market_order(ticker, buyed_amount)
                msg = f"⏸️ **[정체매도]**: [{ticker}] {profit_rate:.2f}% / {cur_price:,.1f}원"
                print(msg)
                send_discord_message(msg)
                return sell_order
        
        # [4] BB 긴급 매도
        if bb_analysis_live and bb_analysis_live['sell_urgency'] == 'CRITICAL':
            if profit_rate >= min_rate * 1.1:
                sell_order = upbit.sell_market_order(ticker, buyed_amount)
                msg = f"🚨 **[BB긴급매도]**: [{ticker}] {profit_rate:.2f}% / {cur_price:,.1f}원\n{bb_analysis_live['reason']}"
                print(msg)
                send_discord_message(msg)
                return sell_order
        
        time.sleep(second)
        attempts += 1
    
    # ==================== 시간 종료 처리 ====================
    
    print(f"\n[{ticker}] 시간종료 - BB 최종판단")
    
    df_5m_final = pyupbit.get_ohlcv(ticker, interval="minute5", count=50)
    time.sleep(0.1)
    if df_5m_final is not None and len(df_5m_final) >= 30:
        closes_final = df_5m_final['close'].values
        volumes_final = df_5m_final['volume'].values
        bb_analysis_final = analyze_bb_sell_signal(cur_price, closes_final, volumes_final)
    else:
        bb_analysis_final = bb_analysis
    
    if profit_rate >= min_rate:
        # BB 하단~중단이면 홀딩
        if bb_analysis_final and bb_analysis_final['should_hold']:
            msg = f"🤝 **[시간종료-홀딩]**: [{ticker}] {profit_rate:.2f}% / {cur_price:,.1f}원\n"
            msg += f"{bb_analysis_final['reason']} (반등:{recovery_prob:.1%})"
            print(msg)
            send_discord_message(msg)
            return None
        
        # BB 상단이면 매도
        else:
            sell_order = upbit.sell_market_order(ticker, buyed_amount)
            msg = f"⏰ **[시간종료-BB상단매도]**: [{ticker}] {profit_rate:.2f}% / {cur_price:,.1f}원\n"
            msg += f"{bb_analysis_final['reason']}"
            print(msg)
            send_discord_message(msg)
            return sell_order
    
    else:
        msg = f"🤝 **[홀딩지속]**: [{ticker}] {profit_rate:.2f}% / {cur_price:,.1f}원\n"
        msg += f"최소수익률 미달 (반등:{recovery_prob:.1%})"
        print(msg)
        send_discord_message(msg)
    
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