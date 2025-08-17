import time
import threading
import pyupbit
import numpy as np
from datetime import datetime, timedelta
import os
from dotenv import load_dotenv
import requests
import ta
import pandas as pd
from scipy import stats
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_curve, auc

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

min5 = "minute5"
min15 = "minute15"

rsi_buy_s = 25
rsi_buy_e = 45

# band_diff_margin = 0.03
UpRsiRate = 80

def get_user_input():
    while True:
        try:
            min_rate = float(input("최소 수익률 (예: 0.4): "))
            max_rate = float(input("최대 수익률 (예: 2.6): "))
            sell_time = int(input("매도감시횟수 (예: 30): "))
            rsi_sell_s =int(input("RSI 매도 감시 시작 (예: 60): "))
            rsi_sell_e =int(input("RSI 매도 감시 종료 (예: 75): "))
            # band_diff_margin = float(input("BD Margin (예: 0.025): "))
            break  # 모든 입력이 성공적으로 완료되면 루프 종료
        except ValueError:
            print("잘못된 입력입니다. 다시 시도하세요.")

    return min_rate, sell_time, rsi_sell_s, rsi_sell_e, max_rate

# 함수 호출 및 결과 저장
min_rate, sell_time, rsi_sell_s, rsi_sell_e, max_rate = get_user_input()

second = 1.0
min_krw = 50_000
cut_rate = -5.0

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

def get_ema(ticker, interval = min5):
    df = pyupbit.get_ohlcv(ticker, interval=interval, count=count_200)
    time.sleep(0.3)

    if df is not None and not df.empty:
        df['ema'] = ta.trend.EMAIndicator(close=df['close'], window=20).ema_indicator()
        return df['ema'].tail(2)  # EMA의 마지막 값 반환
    
    else:
        return 0  # 데이터가 없으면 0 반환
    
def get_rsi(ticker, period, interval=min5):
    df_rsi = pyupbit.get_ohlcv(ticker, interval=interval, count=200) 
    time.sleep(0.3)
    if df_rsi is None or df_rsi.empty:
        return None  # 데이터가 없으면 None 반환

    # TA 라이브러리를 사용하여 RSI 계산
    rsi = ta.momentum.RSIIndicator(df_rsi['close'], window=period).rsi()

    return rsi.tail(3) if not rsi.empty else None 

def get_rsi_bul_diver(ticker, period=14, interval=min5, lookback=20, min_data_points=50):
    """
    RSI Bullish Divergence 신호를 감지하는 함수
    
    Args:
        ticker: 암호화폐 티커 (예: 'KRW-BTC')
        period: RSI 계산 기간 (기본값: 14)
        interval: 캔들 간격 (기본값: 5분)
        lookback: 다이버전스 검색 범위 (기본값: 20)
        min_data_points: 최소 데이터 포인트 수 (기본값: 50)
    
    Returns:
        dict: {
            'is_bullish_divergence': bool,  # 불리쉬 다이버전스 발생 여부
            'current_price': float,         # 현재 가격
            'current_rsi': float,          # 현재 RSI
            'price_low': float,            # 가격 저점
            'rsi_low': float,             # RSI 저점
            'divergence_bars': int         # 다이버전스 발생 구간
        }
    """
    try:
        # 충분한 데이터 확보를 위해 더 많은 캔들 가져오기
        df = pyupbit.get_ohlcv(ticker, interval=interval, count=max(200, min_data_points + lookback))
        time.sleep(0.3)
        
        if df is None or df.empty or len(df) < min_data_points:
            return None
        
        # RSI 계산
        rsi = ta.momentum.RSIIndicator(df['close'], window=period).rsi()
        df['rsi'] = rsi
        
        # NaN 값 제거
        df = df.dropna()
        
        if len(df) < lookback:
            return None
        
        # 현재 정보
        current_price = pyupbit.get_current_price(ticker)    
        current_rsi = df['rsi'].iloc[-1]

        # 불리쉬 다이버전스 검사 초기화
        is_divergence = False
        price_low = current_price
        rsi_low = current_rsi
        divergence_bars = 0
        
        # 최근 lookback 구간에서 다이버전스 패턴 검사
        for i in range(lookback, min(len(df), lookback + 10)):  # 최대 10개 구간 검사
            # 검사 구간 설정
            end_idx = len(df) - 1
            start_idx = end_idx - i
            
            if start_idx < 0:
                continue
            
            # 구간 내 가격과 RSI 데이터 추출
            price_window = df['close'].iloc[start_idx:end_idx + 1]
            rsi_window = df['rsi'].iloc[start_idx:end_idx + 1]
            
            # 가격과 RSI의 최저점 찾기
            price_min = price_window.min()
            rsi_min = rsi_window.min()
            
            # 불리쉬 다이버전스 조건 확인
            # 1. 현재 가격이 이전 저점보다 낮거나 비슷함
            # 2. 현재 RSI가 이전 RSI 저점보다 높음
            # 3. 현재 RSI가 과매도 구간에서 벗어나고 있음 (30 이상)
            
            price_condition = current_price <= price_min * 1.015 #1.5% 허용 오차
            rsi_condition = current_rsi > rsi_min + 2  # RSI 2포인트 이상 상승
            oversold_recovery = current_rsi > 25  # 과매도 구간 탈출
            
            # RSI 상승 추세 확인 (최근 3개 캔들)
            if len(df) >= 3:
                recent_rsi = df['rsi'].tail(3).values
                rsi_rising = recent_rsi[-3] <= recent_rsi[-2] <= recent_rsi[-1]
            else:
                rsi_rising = True
            
            if price_condition and rsi_condition and oversold_recovery and rsi_rising:
                is_divergence = True
                price_low = price_min
                rsi_low = rsi_min
                divergence_bars = i
                break
                
        return {
            'is_bullish_divergence': is_divergence,
            'current_price': current_price,
            'current_rsi': current_rsi,
            'price_low': price_low,
            'rsi_low': rsi_low,
            'divergence_bars': divergence_bars,
        }
    
    except Exception as e:
        print(f"Error in get_rsi_bul_diver for {ticker}: {e}")
        return None

def get_rsi_bear_diver(ticker, period=14, interval=min5, lookback=20, min_data_points=50):
    """
    RSI Bearish Divergence 신호를 감지하는 함수 (매도 시점)
    
    Args:
        ticker: 암호화폐 티커 (예: 'KRW-BTC')
        period: RSI 계산 기간 (기본값: 14)
        interval: 캔들 간격 (기본값: 5분)
        lookback: 다이버전스 검색 범위 (기본값: 20)
        min_data_points: 최소 데이터 포인트 수 (기본값: 50)
    
    Returns:
        dict: {
            'is_bearish_divergence': bool,  # 베어리쉬 다이버전스 발생 여부
            'current_price': float,         # 현재 가격
            'current_rsi': float,          # 현재 RSI
            'price_high': float,           # 가격 고점
            'rsi_high': float,            # RSI 고점
            'divergence_bars': int        # 다이버전스 발생 구간
        }
    """
    try:
        # 충분한 데이터 확보를 위해 더 많은 캔들 가져오기
        df = pyupbit.get_ohlcv(ticker, interval=interval, count=max(200, min_data_points + lookback))
        time.sleep(0.3)
        
        if df is None or df.empty or len(df) < min_data_points:
            return None
        
        # RSI 계산
        rsi = ta.momentum.RSIIndicator(df['close'], window=period).rsi()
        df['rsi'] = rsi
        
        # NaN 값 제거
        df = df.dropna()
        
        if len(df) < lookback:
            return None
        
        # 현재 정보
        current_price = pyupbit.get_current_price(ticker)    
        current_rsi = df['rsi'].iloc[-1]

        # 베어리쉬 다이버전스 검사 초기화
        is_divergence = False
        price_high = current_price
        rsi_high = current_rsi
        divergence_bars = 0
        
        # 최근 lookback 구간에서 다이버전스 패턴 검사
        for i in range(lookback, min(len(df), lookback + 10)):  # 최대 10개 구간 검사
            # 검사 구간 설정
            end_idx = len(df) - 1
            start_idx = end_idx - i
            
            if start_idx < 0:
                continue
            
            # 구간 내 가격과 RSI 데이터 추출
            price_window = df['close'].iloc[start_idx:end_idx + 1]
            rsi_window = df['rsi'].iloc[start_idx:end_idx + 1]
            
            # 가격과 RSI의 최고점 찾기
            price_max = price_window.max()
            rsi_max = rsi_window.max()
            
            # 베어리쉬 다이버전스 조건 확인
            # 1. 현재 가격이 이전 고점보다 높거나 비슷함
            # 2. 현재 RSI가 이전 RSI 고점보다 낮음
            # 3. 현재 RSI가 과매수 구간에서 하락하고 있음 (70 이하)
            
            price_condition = current_price >= price_max * 0.985  # 1.5% 허용 오차
            rsi_condition = current_rsi < rsi_max - 2  # RSI 2포인트 이상 하락
            overbought_decline = current_rsi < 75  # 과매수 구간 진입/하락
            
            # RSI 하락 추세 확인 (최근 3개 캔들)
            if len(df) >= 3:
                recent_rsi = df['rsi'].tail(3).values
                rsi_falling = recent_rsi[-3] >= recent_rsi[-2] >= recent_rsi[-1]
            else:
                rsi_falling = True
            
            if price_condition and rsi_condition and overbought_decline and rsi_falling:
                is_divergence = True
                price_high = price_max
                rsi_high = rsi_max
                divergence_bars = i
                break
                
        return {
            'is_bearish_divergence': is_divergence,
            'current_price': current_price,
            'current_rsi': current_rsi,
            'price_high': price_high,
            'rsi_high': rsi_high,
            'divergence_bars': divergence_bars,
        }
    
    except Exception as e:
        print(f"Error in get_rsi_bear_diver for {ticker}: {e}")
        return None

def get_bollinger_bands(ticker, interval=min5, window=20, std_dev=2.5):
    """특정 티커의 볼린저 밴드 상단, 중간, 하단값을 가져오는 함수"""
    df = pyupbit.get_ohlcv(ticker, interval=interval, count=50)
    time.sleep(second)
    if df is None or df.empty:
        return None  # 데이터가 없으면 None 반환

    bollinger = ta.volatility.BollingerBands(df['close'], window=window, window_dev=std_dev)

    upper_band = bollinger.bollinger_hband().fillna(0)  
    middle_band = bollinger.bollinger_mavg().fillna(0)  # 중간선(이동평균) 추가
    lower_band = bollinger.bollinger_lband().fillna(0)  
    
    bands_df = pd.DataFrame({   # DataFrame으로 묶기
        'Upper_Band': upper_band,
        'Middle_Band': middle_band,  # 중간선 컬럼 추가
        'Lower_Band': lower_band
    })

    return bands_df.tail(4)

def predict_price_direction(ticker):
    """
    200개 과거 데이터를 기반으로 향후 10개 캔들의 가격 방향성 예측
    
    Returns:
        tuple: (prediction, total_score)
        prediction: 'SURGE'/'UP'/'DOWN'/'CRASH'/'NEUTRAL'
        total_score: 예측 점수 (-5.0 ~ +5.0)
    """
    try:
        # 200개 데이터 수집 (최대치)
        df = pyupbit.get_ohlcv(ticker, interval=min5, count=200)
        if df is None or len(df) < 100:
            return 'NEUTRAL', 0
        
        # 데이터 추출
        closes = df['close'].values
        highs = df['high'].values
        lows = df['low'].values
        volumes = df['volume'].values
        
        # === 1. 추세 분석 (가중치: 25%) ===
        trend_score = 0
        
        # 다중 이동평균 분석
        sma_short = closes[-10:].mean()    # 단기
        sma_mid = closes[-30:].mean()      # 중기  
        sma_long = closes[-60:].mean()     # 장기
        
        # 추세 배열 점수
        if sma_short > sma_mid > sma_long:
            trend_score += 3  # 강한 상승추세
        elif sma_short > sma_mid:
            trend_score += 1  # 약한 상승추세
        elif sma_short < sma_mid < sma_long:
            trend_score -= 3  # 강한 하락추세
        elif sma_short < sma_mid:
            trend_score -= 1  # 약한 하락추세
        
        # 최근 20캔들 기울기 분석
        recent_slope = (closes[-1] - closes[-20]) / closes[-20]
        if recent_slope > 0.03:      # 3% 이상 상승
            trend_score += 2
        elif recent_slope > 0.01:    # 1% 이상 상승
            trend_score += 1
        elif recent_slope < -0.03:   # 3% 이상 하락
            trend_score -= 2
        elif recent_slope < -0.01:   # 1% 이상 하락
            trend_score -= 1
        
        # === 2. 모멘텀 분석 (가중치: 30%) ===
        momentum_score = 0
        
        # RSI 모멘텀 변화
        rsi_data = get_rsi(ticker, 14, interval=min5)
        rsi_values = rsi_data.values
        current_rsi = rsi_values[-1] if len(rsi_values) > 0 else 50
        
        # RSI 추세 (최근 5캔들 평균 변화)
        if len(rsi_values) >= 5:
            rsi_trend = (current_rsi - rsi_values[-5]) / 5
            if rsi_trend > 2:        # RSI 급상승
                momentum_score += 3
            elif rsi_trend > 0.5:    # RSI 상승
                momentum_score += 1
            elif rsi_trend < -2:     # RSI 급하락
                momentum_score -= 3
            elif rsi_trend < -0.5:   # RSI 하락
                momentum_score -= 1
        
        # RSI 절대값 기반 반전 기대
        if current_rsi < 25:         # 극과매도
            momentum_score += 2
        elif current_rsi < 35:       # 과매도
            momentum_score += 1
        elif current_rsi > 75:       # 극과매수
            momentum_score -= 2
        elif current_rsi > 65:       # 과매수
            momentum_score -= 1
        
        # === 3. 거래량 분석 (가중치: 20%) ===
        volume_score = 0
        
        # 거래량 비교 분석
        vol_recent = volumes[-10:].mean()              # 최근 10개 평균
        vol_baseline = volumes[-50:-10].mean()         # 기준선 (40개 평균)
        volume_ratio = vol_recent / vol_baseline if vol_baseline > 0 else 1
        
        if volume_ratio > 2.0:       # 거래량 급증
            # 가격과 거래량의 상관관계 확인
            price_change = (closes[-1] - closes[-10]) / closes[-10]
            if price_change > 0:
                volume_score += 3    # 상승 돌파 신호
            else:
                volume_score -= 2    # 하락 돌파 위험
        elif volume_ratio > 1.3:     # 거래량 증가
            volume_score += 1
        elif volume_ratio < 0.7:     # 거래량 감소
            volume_score -= 1
        
        # === 4. 패턴 및 변동성 분석 (가중치: 25%) ===
        pattern_score = 0
        
        # 볼린저 밴드 패턴 분석
        try:
            bb_data = get_bollinger_bands(ticker, interval=min5, window=20, std_dev=2)
            bb_upper = bb_data['Upper_Band'].values
            bb_lower = bb_data['Lower_Band'].values
            bb_middle = bb_data['Middle_Band'].values
            
            if len(bb_upper) >= 20:
                # 밴드 수축/확장 패턴
                recent_width = (bb_upper[-1] - bb_lower[-1]) / bb_middle[-1]
                past_width = (bb_upper[-10:-5].mean() - bb_lower[-10:-5].mean()) / bb_middle[-10:-5].mean()
                
                if recent_width > past_width * 1.2:  # 밴드 확장
                    # 현재 가격의 밴드 내 위치
                    current_bb_pos = (closes[-1] - bb_lower[-1]) / (bb_upper[-1] - bb_lower[-1])
                    if current_bb_pos > 0.8:      # 상단 돌파
                        pattern_score += 3
                    elif current_bb_pos > 0.6:    # 상단 접근
                        pattern_score += 1
                    elif current_bb_pos < 0.2:    # 하단 돌파
                        pattern_score -= 3
                    elif current_bb_pos < 0.4:    # 하단 접근
                        pattern_score -= 1
        except:
            pass  # 볼린저밴드 계산 실패 시 패스
        
        # 지지/저항 레벨 분석
        recent_high = highs[-20:].max()
        recent_low = lows[-20:].min()
        current_position = (closes[-1] - recent_low) / (recent_high - recent_low) if recent_high != recent_low else 0.5
        
        if current_position > 0.9:       # 저항선 근처 - 하락 위험
            pattern_score -= 2
        elif current_position > 0.7:     # 상단 영역 - 조정 가능
            pattern_score -= 1
        elif current_position < 0.1:     # 지지선 근처 - 반등 기대
            pattern_score += 2
        elif current_position < 0.3:     # 하단 영역 - 반등 가능
            pattern_score += 1
        
        # === 5. 종합 점수 계산 및 예측 ===
        
        # 가중 평균으로 최종 점수 계산
        total_score = (
            trend_score * 0.25 +      # 추세: 25%
            momentum_score * 0.30 +   # 모멘텀: 30%
            volume_score * 0.20 +     # 거래량: 20%
            pattern_score * 0.25      # 패턴: 25%
        )
        
        # 예측 결과 결정 (임계값 기반)
        if total_score >= 2.5:
            prediction = 'SURGE'      # 급상승 예상 (5%+)
        elif total_score >= 1.0:
            prediction = 'UP'         # 상승 예상 (1-5%)
        elif total_score <= -2.5:
            prediction = 'CRASH'      # 폭락 예상 (-5%+)
        elif total_score <= -1.0:
            prediction = 'DOWN'       # 하락 예상 (1-5%)
        else:
            prediction = 'NEUTRAL'    # 중립 (±1%)
        
        return prediction, round(total_score, 2)
    
    except Exception as e:
        print(f"[predict_price_direction] {ticker} 예측 오류: {e}")
        return 'NEUTRAL', 0

def analyze_optimal_band_margin(ticker, lookback_periods=150, target_periods=[5, 10], min_gain_threshold=0.01):
    """
    sklearn 없이 작동하는 안전한 밴드마진 최적화 함수
    
    Parameters:
    - ticker: 분석할 티커 (예: 'KRW-BTC')
    - lookback_periods: 분석할 과거 데이터 개수 (기본 150개)
    - target_periods: 미래 수익률 계산 기간들 (5봉 후, 10봉 후)
    - min_gain_threshold: 의미있는 상승으로 간주할 최소 수익률 (기본 1%)
    
    Returns:
    - dict: 최적 임계값들과 통계 정보
    """
    
    try:
        print(f"📊 {ticker} 밴드마진 최적화 분석 시작...")
        
        # 1. 필요한 라이브러리 안전하게 임포트
        import numpy as np
        import pandas as pd
        try:
            from scipy import stats
            scipy_available = True
        except ImportError:
            print("  ⚠️ scipy 없이 진행 (기본 상관관계 계산 사용)")
            scipy_available = False
        
        # 2. 데이터 수집
        total_needed = min(lookback_periods + 50, 200)
        df = pyupbit.get_ohlcv(ticker, interval="minute5", count=total_needed)
        if df is None or len(df) < lookback_periods:
            print(f"❌ {ticker}: 데이터 수집 실패")
            return create_default_result(ticker, 0)
            
        # 3. 분석 데이터 생성
        analysis_data = []
        
        for i in range(30, min(len(df) - max(target_periods), lookback_periods + 30)):
            try:
                current_slice = df.iloc[:i+1]
                current_price = float(current_slice['close'].iloc[-1])
                
                # 볼린저밴드 계산 (numpy 함수 안전하게 사용)
                close_prices = current_slice['close'].values.astype(float)
                if len(close_prices) >= 20:
                    bb_period = 20
                    bb_std = 2.0
                    
                    # numpy 함수들을 안전하게 호출
                    recent_prices = close_prices[-bb_period:]
                    sma = float(recent_prices.mean())  # np.mean() 대신 .mean() 사용
                    std = float(recent_prices.std())   # np.std() 대신 .std() 사용
                    
                    upper_band = sma + (bb_std * std)
                    lower_band = sma - (bb_std * std)
                    
                    band_width_ratio = (upper_band - lower_band) / current_price
                    
                    if upper_band != lower_band:
                        bb_position = (current_price - lower_band) / (upper_band - lower_band)
                    else:
                        bb_position = 0.5
                else:
                    continue
                
                # RSI 계산 (완전 안전 버전)
                try:
                    rsi = calculate_rsi_numpy_free(close_prices.tolist(), 14)
                except:
                    rsi = 50.0
                
                # 거래량 지표 (numpy 없이)
                volumes = current_slice['volume'].values.astype(float)
                if len(volumes) >= 20:
                    vol_recent = volumes[-5:]
                    vol_long = volumes[-20:]
                    vol_sma_5 = float(sum(vol_recent) / len(vol_recent))
                    vol_sma_20 = float(sum(vol_long) / len(vol_long))
                else:
                    vol_sma_5 = float(volumes[-1])
                    vol_sma_20 = float(volumes.mean())
                
                volume_ratio = vol_sma_5 / vol_sma_20 if vol_sma_20 > 0 else 1.0
                
                # 가격 모멘텀
                if len(close_prices) >= 5:
                    price_momentum = (close_prices[-1] / close_prices[-5]) - 1.0
                else:
                    price_momentum = 0.0
                
                # 미래 수익률 계산
                future_returns = {}
                for period in target_periods:
                    if i + period < len(df):
                        future_price = float(df['close'].iloc[i + period])
                        return_rate = (future_price / current_price) - 1.0
                        future_returns[f'return_{period}'] = return_rate
                        future_returns[f'is_profitable_{period}'] = return_rate > 0
                    else:
                        break
                
                if future_returns:
                    data_point = {
                        'timestamp': current_slice.index[-1],
                        'price': current_price,
                        'band_width_ratio': band_width_ratio,
                        'bb_position': bb_position,
                        'rsi': rsi,
                        'volume_ratio': volume_ratio,
                        'price_momentum': price_momentum,
                        **future_returns
                    }
                    analysis_data.append(data_point)
                    
            except Exception as data_error:
                # 개별 데이터 포인트 실패는 무시하고 계속 진행
                continue
                
        # 4. 데이터 검증
        if len(analysis_data) < 30:
            print(f"❌ {ticker}: 분석 데이터 부족 ({len(analysis_data)}개)")
            return create_default_result(ticker, len(analysis_data))
            
        df_analysis = pd.DataFrame(analysis_data)
        print(f"📈 분석 데이터: {len(df_analysis)}개 시점")
        
        # 5. 기간별 분석
        correlation_results = {}
        optimal_thresholds = {}
        
        for period in target_periods:
            profit_col = f'is_profitable_{period}'
            return_col = f'return_{period}'
            
            if profit_col not in df_analysis.columns:
                continue
            
            print(f"\n🎯 {period}봉 후 분석:")
            
            # 클래스 분포 확인
            try:
                profit_mask = df_analysis[profit_col] == True
                profit_true = int(profit_mask.sum())
                profit_false = int(len(df_analysis) - profit_true)
                print(f"  📊 클래스 분포 - 수익: {profit_true}개, 손실: {profit_false}개")
            except Exception as class_error:
                print(f"  ❌ 클래스 분포 계산 실패: {str(class_error)}")
                continue
            
            # 클래스 불균형 처리 (numpy percentile 안전하게 사용)
            if profit_true == 0 or profit_false == 0:
                print(f"  ⚠️ 단일 클래스 감지 - 동적 조정 중...")
                try:
                    returns_list = df_analysis[return_col].tolist()
                    returns_sorted = sorted(returns_list)
                    percentile_70_idx = int(len(returns_sorted) * 0.7)
                    percentile_70 = returns_sorted[percentile_70_idx]
                    
                    df_analysis[profit_col] = df_analysis[return_col] > percentile_70
                    
                    profit_mask = df_analysis[profit_col] == True
                    profit_true = int(profit_mask.sum())
                    profit_false = int(len(df_analysis) - profit_true)
                    print(f"  🔄 조정된 임계값: {percentile_70:.4f}")
                    print(f"  📊 새 클래스 분포 - 수익: {profit_true}개, 손실: {profit_false}개")
                except Exception as adjust_error:
                    print(f"  ❌ 클래스 조정 실패: {str(adjust_error)}")
                    continue
            
            # 상관관계 계산 (numpy 없이 또는 안전하게)
            try:
                correlations = {}
                feature_cols = ['band_width_ratio', 'bb_position', 'rsi', 'volume_ratio', 'price_momentum']
                
                for feature in feature_cols:
                    try:
                        if scipy_available:
                            x_values = df_analysis[feature].values.astype(float)
                            y_values = df_analysis[return_col].values.astype(float)
                            corr_result = stats.pearsonr(x_values, y_values)
                            correlations[feature] = float(corr_result[0])
                        else:
                            # scipy 없이 상관관계 계산
                            corr = calculate_correlation_manual(
                                df_analysis[feature].tolist(),
                                df_analysis[return_col].tolist()
                            )
                            correlations[feature] = corr
                    except Exception as corr_error:
                        print(f"    ⚠️ {feature} 상관관계 계산 실패: {str(corr_error)}")
                        correlations[feature] = 0.0
                
                correlation_results[period] = correlations
                
                # 상관관계 출력
                for factor, corr in correlations.items():
                    print(f"  {factor}: {corr:.3f}")
                    
            except Exception as corr_error:
                print(f"  ❌ 상관관계 분석 실패: {str(corr_error)}")
                continue
            
            # 6. 순수 통계적 임계값 계산 (ML 없이)
            try:
                successful_trades = df_analysis[df_analysis[profit_col] == True]
                failed_trades = df_analysis[df_analysis[profit_col] == False]
                
                if len(successful_trades) >= 3 and len(failed_trades) >= 3:
                    # 성공 그룹 통계 (pandas 메서드 사용)
                    success_band_values = successful_trades['band_width_ratio'].tolist()
                    fail_band_values = failed_trades['band_width_ratio'].tolist()
                    
                    success_mean = sum(success_band_values) / len(success_band_values)
                    success_sorted = sorted(success_band_values)
                    success_median_idx = len(success_sorted) // 2
                    success_median = success_sorted[success_median_idx]
                    success_q30_idx = int(len(success_sorted) * 0.3)
                    success_q30 = success_sorted[success_q30_idx]
                    
                    fail_mean = sum(fail_band_values) / len(fail_band_values)
                    fail_sorted = sorted(fail_band_values)
                    fail_median_idx = len(fail_sorted) // 2
                    fail_median = fail_sorted[fail_median_idx]
                    
                    # 최적 임계값: 성공 그룹의 30th percentile
                    optimal_threshold = success_q30
                    
                    # 성공률 계산
                    success_rate = len(successful_trades) / len(df_analysis)
                    
                    optimal_thresholds[period] = {
                        'band_width_threshold': max(0.005, optimal_threshold),
                        'success_rate': success_rate,
                        'method': 'pure_statistical',
                        'success_stats': {
                            'mean': success_mean,
                            'median': success_median,
                            'q30': success_q30
                        },
                        'fail_stats': {
                            'mean': fail_mean,
                            'median': fail_median
                        },
                        'class_balance': f"{len(successful_trades)}:{len(failed_trades)}"
                    }
                    
                    print(f"  ✅ 통계 기반 임계값: {optimal_threshold:.4f}")
                    print(f"  📊 성공률: {success_rate*100:.1f}%")
                    print(f"  📈 성공그룹 평균: {success_mean:.4f}, 실패그룹 평균: {fail_mean:.4f}")
                    
                else:
                    print(f"  ⚠️ 데이터 부족 (성공:{len(successful_trades)}, 실패:{len(failed_trades)}) - 기본값 사용")
                    
            except Exception as stat_error:
                print(f"  ❌ 통계 분석 실패: {str(stat_error)}")
                continue
        
        # 7. 최종 결과 생성
        if not optimal_thresholds:
            print(f"  ⚠️ 모든 분석 실패 - 기본값 반환")
            return create_default_result(ticker, len(df_analysis))
        
        # 가중 평균으로 최종 임계값 계산
        try:
            weights = {5: 0.7, 10: 0.3}
            weighted_sum = 0.0
            weight_sum = 0.0
            
            for period in optimal_thresholds.keys():
                if period in weights:
                    threshold = optimal_thresholds[period]['band_width_threshold']
                    weight = weights[period]
                    weighted_sum += threshold * weight
                    weight_sum += weight
            
            final_threshold = weighted_sum / weight_sum if weight_sum > 0 else 0.015
            
            result = {
                'ticker': ticker,
                'optimal_band_margin': final_threshold,
                'analysis_periods': optimal_thresholds,
                'correlations': correlation_results,
                'data_points': len(df_analysis),
                'analysis_timestamp': datetime.now(),
                'method': 'numpy_safe_statistical'
            }
            
            print(f"✅ {ticker} 분석 완료 - 최적 밴드마진: {final_threshold:.4f}")
            return result
            
        except Exception as final_error:
            print(f"❌ 최종 계산 실패: {str(final_error)}")
            return create_default_result(ticker, len(df_analysis))
        
    except Exception as main_error:
        print(f"❌ {ticker} 메인 분석 오류: {str(main_error)}")
        import traceback
        print(f"상세 오류: {traceback.format_exc()}")
        return create_default_result(ticker, 0)


def calculate_rsi_numpy_free(prices, period=14):
    """numpy 없이 RSI 계산"""
    if len(prices) < period + 1:
        return 50.0
    
    # 가격 변화 계산
    deltas = []
    for i in range(1, len(prices)):
        deltas.append(prices[i] - prices[i-1])
    
    # 상승과 하락 분리
    gains = [max(0, delta) for delta in deltas]
    losses = [max(0, -delta) for delta in deltas]
    
    # 최근 period개의 평균 계산
    recent_gains = gains[-period:]
    recent_losses = losses[-period:]
    
    avg_gain = sum(recent_gains) / len(recent_gains)
    avg_loss = sum(recent_losses) / len(recent_losses)
    
    if avg_loss == 0:
        return 100.0
    
    rs = avg_gain / avg_loss
    rsi = 100.0 - (100.0 / (1.0 + rs))
    
    return rsi


def calculate_correlation_manual(x_list, y_list):
    """수동으로 상관관계 계산"""
    if len(x_list) != len(y_list) or len(x_list) < 2:
        return 0.0
    
    n = len(x_list)
    
    # 평균 계산
    x_mean = sum(x_list) / n
    y_mean = sum(y_list) / n
    
    # 분자와 분모 계산
    numerator = sum((x_list[i] - x_mean) * (y_list[i] - y_mean) for i in range(n))
    x_var = sum((x_list[i] - x_mean) ** 2 for i in range(n))
    y_var = sum((y_list[i] - y_mean) ** 2 for i in range(n))
    
    denominator = (x_var * y_var) ** 0.5
    
    if denominator == 0:
        return 0.0
    
    return numerator / denominator


def create_default_result(ticker, data_points):
    """기본값 결과 생성 함수"""
    from datetime import datetime
    
    return {
        'ticker': ticker,
        'optimal_band_margin': 0.015,  # 1.5% 기본값
        'method': 'default_fallback',
        'data_points': data_points,
        'analysis_timestamp': datetime.now(),
        'warning': 'Analysis failed, using conservative default value',
        'reason': 'Calculation errors or insufficient data'
    }

def calculate_rsi_for_analysis(prices, period=14):
    """분석용 RSI 계산 함수 (기존 get_rsi 함수와 충돌 방지)"""
    if len(prices) < period + 1:
        return 50  # 데이터 부족시 중성값 반환
        
    deltas = np.diff(prices)
    gains = np.where(deltas > 0, deltas, 0)
    losses = np.where(deltas < 0, -deltas, 0)
    
    # 최근 period 구간의 평균 계산
    avg_gain = np.mean(gains[-(period):]) if len(gains) >= period else np.mean(gains)
    avg_loss = np.mean(losses[-(period):]) if len(losses) >= period else np.mean(losses)
    
    if avg_loss == 0:
        return 100
    
    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    return rsi

def get_smart_band_margin(ticker, market_rsi):
    """
    현재 시점의 스마트 밴드마진 계산
    
    Parameters:
    - ticker: 대상 티커
    - market_rsi: 현재 시장 RSI
    - cache_hours: 캐시 유지 시간
    
    Returns:
    - float: 최적화된 밴드마진 값
    """
    
    # 기본값 (백업용)
    default_margin = 0.02
    
    try:
        # 최적화 분석 수행
        optimization_result = analyze_optimal_band_margin(ticker, lookback_periods=150)
        
        if optimization_result is None:
            print(f"⚠️ {ticker}: 최적화 실패, 기본값 사용 ({default_margin})")
            return default_margin
            
        base_margin = optimization_result['optimal_band_margin']
        
        # 시장 상황에 따른 조정 (기존 로직 유지)
        if market_rsi < 30:
            market_multiplier = 1.4
        elif market_rsi < 40:
            market_multiplier = 1.2
        elif market_rsi > 70:
            market_multiplier = 0.8
        elif market_rsi > 60:
            market_multiplier = 0.9
        else:
            market_multiplier = 1.0
            
        optimized_margin = base_margin * market_multiplier
        
        print(f"🧠 {ticker} 스마트마진: {optimized_margin:.4f} (기본: {base_margin:.4f} x 시장배수: {market_multiplier})")
        return optimized_margin
        
    except Exception as e:
        print(f"❌ {ticker} 스마트마진 계산 오류: {str(e)}, 기본값 사용")
        return default_margin

def filtered_tickers(tickers):
    """개선된 조건에 맞는 티커 필터링 - 동적 밴드마진 최적화 적용"""
    filtered_tickers = []
    
    # === 시장 전체 심리 분석 ===
    market_rsi_data = []
    
    # 업비트 거래량 상위 10개 코인으로 시장 심리 측정
    market_tickers = [
        'KRW-BTC', 'KRW-ETH', 'KRW-XRP', 'KRW-ADA', 'KRW-DOGE',
        'KRW-SOL', 'KRW-AVAX', 'KRW-DOT', 'KRW-MATIC', 'KRW-LINK'
    ]
    
    # 시장 데이터 수집
    for ticker in market_tickers:
        try:
            market_rsi_data_single = get_rsi(ticker, 14, interval=min5)
            if len(market_rsi_data_single.values) > 0:
                market_rsi_data.append(market_rsi_data_single.values[-1])
            time.sleep(0.1)
        except:
            continue
    
    # 시장 RSI 계산
    market_rsi = sum(market_rsi_data) / len(market_rsi_data) if market_rsi_data else 50
    
    # 시장 상태 설정 (기존 로직 유지)
    if market_rsi < 30:
        market_status = "극과매도(바닥대기)"
        strategy_note = "칼떨어지는중-충분히대기"
    elif market_rsi < 40:
        market_status = "과매도(신중대기)"  
        strategy_note = "하락진행중-더기다리기"
    elif market_rsi > 70:
        market_status = "극과매수(조정매수)"
        strategy_note = "건전한조정-적극진입"
    elif market_rsi > 60:
        market_status = "과매수(되돌림매수)"
        strategy_note = "상승중되돌림-기회포착"
    else:
        market_status = "중립"
        strategy_note = "표준조건"
    
    print(f"🌍 시장심리: RSI {market_rsi:.1f} ({market_status}) | {strategy_note}")
    
    # === 개별 코인 분석 ===
    prediction_summary = {'SURGE': 0, 'UP': 0, 'DOWN': 0, 'CRASH': 0, 'NEUTRAL': 0}
    
    for t in tickers:
        try:
            # 기본 데이터 가져오기
            df = pyupbit.get_ohlcv(t, interval=min5, count=50)
            current_price = pyupbit.get_current_price(t)
            time.sleep(0.2)
            
            if df is None or current_price is None:
                print(f"[filter_tickers] 데이터 오류: {t}")
                continue
                
            # 데이터 추출
            closes = df['close'].values
            highs = df['high'].values
            lows = df['low'].values
            volumes = df['volume'].values
            
            # ✨ 핵심 추가: 동적 밴드마진 최적화 적용 ✨
            optimized_band_margin = get_smart_band_margin(t, market_rsi)
            
            # 시장 상황에 따른 볼린저 밴드 설정
            if market_rsi < 35:
                bb_window, bb_std = 20, 2.1
            elif market_rsi > 65:
                bb_window, bb_std = 30, 2.3
            else:
                bb_window, bb_std = 25, 2.2
            
            bands_df = get_bollinger_bands(t, interval=min5, window=bb_window, std_dev=bb_std)
            upper_band = bands_df['Upper_Band'].values[-1]
            lower_band = bands_df['Lower_Band'].values[-1]
            band_diff_ratio = (upper_band - lower_band) / lower_band
            
            # RSI 계산
            ta_rsi = get_rsi(t, 14, interval=min5)
            rsi_values = ta_rsi.values
            current_rsi = rsi_values[-1]
            
            # ✨ 최적화된 밴드 확장 조건 적용 ✨
            is_band_expanding = band_diff_ratio > optimized_band_margin  # 기존 adjusted_band_margin 대신
            
            # 나머지 조건들 (기존과 동일)
            adjusted_rsi_s = rsi_buy_s * (1.05 if market_rsi < 40 else 0.95)
            adjusted_rsi_e = rsi_buy_e * (0.95 if market_rsi < 40 else 1.05)
            is_rsi_good = adjusted_rsi_s < current_rsi < adjusted_rsi_e
            
            divergence_result = get_rsi_bul_diver(t)
            has_divergence = divergence_result['is_bullish_divergence']
            
            bb_position = (current_price - lower_band) / (upper_band - lower_band)
            is_good_position = bb_position < 0.35
            
            # 보조 조건들 (기존과 동일)
            rsi_momentum = len(rsi_values) >= 3 and rsi_values[-1] > rsi_values[-2] >= rsi_values[-3]
            
            vol_sma5 = volumes[-5:].mean()
            vol_sma10 = volumes[-10:].mean()
            recent_vol_surge = volumes[-1] > vol_sma5 * 1.15
            volume_trend_good = vol_sma5 > vol_sma10 * 1.05
            
            price_sma10 = closes[-10:].mean()
            price_trend_ok = current_price > price_sma10 * 0.97
            
            recent_range = (highs[-5:].max() - lows[-5:].min()) / closes[-5:].mean()
            good_volatility = 0.015 < recent_range < 0.12
            
            recent_low = lows[-5:].min()
            bounce_signal = current_price > recent_low * 1.008
            
            support_test = current_price < closes[-10:].mean() * 1.02
            
            # 기존 점수 시스템 (동일)
            essential_conditions = (
                is_band_expanding and 
                is_rsi_good and 
                has_divergence and
                is_good_position
            )
            
            bonus_conditions = [
                (rsi_momentum, 1.2), (recent_vol_surge, 1.0), (volume_trend_good, 0.8),
                (price_trend_ok, 1.0), (good_volatility, 0.8), (bounce_signal, 1.1), (support_test, 0.7)
            ]
            
            bonus_score = sum(weight for condition, weight in bonus_conditions if condition)
            has_enough_bonus = bonus_score >= 3.0
            
            # 가격 예측 시스템 호출 (기존과 동일)
            prediction, prediction_score = predict_price_direction(t)
            prediction_summary[prediction] += 1
            
            # 최종 매수 결정 로직 (기존과 동일하나 최적화된 밴드마진 반영됨)
            filteringTime = datetime.now().strftime('%m/%d %H시%M분%S초')
            filtering_message = f"<<[{filteringTime}] {t}>>\n"
            filtering_message += f"[필수] 밴드확장: {is_band_expanding}({band_diff_ratio:.4f}>{optimized_band_margin:.4f}) | RSI범위: {is_rsi_good}({current_rsi:.1f}) | 다이버전스: {has_divergence} | 위치: {is_good_position}({bb_position:.1%})\n"
            filtering_message += f"[보조] 점수: {bonus_score:.1f}/3.0 | RSI↑: {rsi_momentum} | 거래량: {recent_vol_surge}/{volume_trend_good} | 추세: {price_trend_ok} | 변동성: {good_volatility} | 반등: {bounce_signal} | 지지: {support_test}\n"
            filtering_message += f"[예측] {prediction} (점수: {prediction_score}) | "
            
            # 최종 판단 (매수 대상 추가시만 디스코드 메시지 발송)
            if essential_conditions and has_enough_bonus:
                if prediction in ['SURGE', 'UP']:
                    send_discord_message(filtering_message + "🎯 **완벽한 매수 신호! (최적화된 조건+상승예측)**")
                    filtered_tickers.append(t)
                elif prediction == 'NEUTRAL':
                    send_discord_message(filtering_message + "⚖️ **양호한 매수 신호 (최적화된 조건+중립예측)**")
                    filtered_tickers.append(t)
                # else: 하락 예측으로 제외 - 메시지 없음
                    
            elif essential_conditions and bonus_score >= 2.0:
                if prediction == 'SURGE':
                    send_discord_message(filtering_message + "🚀 **급상승 예측! 조건 완화 매수**")
                    filtered_tickers.append(t)
                elif prediction == 'UP':
                    send_discord_message(filtering_message + "📈 **상승 예측으로 매수**")
                    filtered_tickers.append(t)
                # else: 조건 부족+예측 불분명으로 보류 - 메시지 없음
                    
            elif essential_conditions:
                if prediction == 'SURGE':
                    send_discord_message(filtering_message + "🌟 **급상승 예측! 필수조건만으로도 매수**")
                    filtered_tickers.append(t)
                else:
                    # 과매도 상황에서만 추가 기회
                    if market_rsi < 40:
                        send_discord_message(filtering_message + "🔍📉 **필수조건+과매도 시장 바닥권 매수**")
                        filtered_tickers.append(t)
                    # else: 필수조건만 충족, 관찰 필요 - 메시지 없음

        except Exception as e:
            send_discord_message(f"[ERROR] {t}: {str(e)[:100]}")
            time.sleep(2)

    # 예측 결과 요약 (중립이 아닌 예측이 있는 경우에만 메시지 발송)
    if any(count > 0 for key, count in prediction_summary.items() if key != 'NEUTRAL'):
        summary_msg = f"📊 **예측 결과 요약**: 급상승 {prediction_summary['SURGE']}개 | 상승 {prediction_summary['UP']}개 | 하락 {prediction_summary['DOWN']}개 | 폭락 {prediction_summary['CRASH']}개 | 중립 {prediction_summary['NEUTRAL']}개"
        send_discord_message(summary_msg)

    return filtered_tickers

def get_best_ticker():
    selected_tickers = ["KRW-XRP", "KRW-SOL", "KRW-ADA", "KRW-DOGE", "KRW-ETH", "KRW-BTC"]
    balances = upbit.get_balances()
    held_coins = []

    for b in balances:
        if float(b['balance']) > 0:  # 보유량이 0보다 큰 경우
            ticker = f"KRW-{b['currency']}"  # 현재가 조회를 위한 티커 설정
            held_coins.append(ticker)  # "KRW-코인명" 형태로 추가
    
    try:
        all_tickers = pyupbit.get_tickers(fiat="KRW")
        filtering_tickers = []

        for ticker in all_tickers:
            if ticker in selected_tickers and ticker not in held_coins:

                    df = pyupbit.get_ohlcv(ticker, interval="day", count=1)
                    time.sleep(second)
                    # df가 None이 아닌지, 그리고 필요한 열이 포함되어 있는지 확인
                    if df is not None and 'open' in df.columns and 'value' in df.columns and not df.empty:
                        try:
                            df_open = df['open'].iloc[-1]
                        except Exception as e:
                            print(f"데이터 인덱싱 중 오류 발생: {e}")
                            # 예: 해당 ticker 생략
                            return None  
                    else:
                        print(f"[경고] 데이터 수신 실패 또는 비어 있음: ticker = {ticker}")
                        # 에러 발생 방지를 위해 None 또는 적절한 기본값 반환 혹은 생략
                        return None

                    cur_price = pyupbit.get_current_price(ticker)

                    candle_cond = df_open * 0.95 < cur_price < df_open * 1.03

                    if candle_cond :
                        filtering_tickers.append(ticker)
                                
    except (KeyError, ValueError) as e:
        send_discord_message(f"get_best_ticker/티커 조회 중 오류 발생: {e}")
        time.sleep(second) 
        return None

    filtered_list = filtered_tickers(filtering_tickers)
    filtered_time = datetime.now().strftime('%m/%d %H시%M분%S초')

    if len(filtered_list) == 0 :
        return None
    
    elif len(filtered_list) == 1 :
        send_discord_message(f"{filtered_time} [{filtered_list}]")
        return filtered_list[0]  # 티커가 1개인 경우 해당 티커 반환
        
    else :
        if len(filtered_list) > 1:
    
            bestC = None  # 초기 최고 코인 초기화
            low_rsi = float('inf')  # 가장 낮은 rsi 값 초기화

            for ticker in filtered_list:   # 조회할 코인 필터링
                
                ta_rsi = get_rsi(ticker, 14, interval = min5)
                rsi = ta_rsi.values
                current_rsi = rsi[-1]  # 가장 최근 rsi 값
                    
                if current_rsi < low_rsi:  # 현재 'D' 값이 가장 낮으면 업데이트
                    bestC = ticker
                    low_rsi = current_rsi

                time.sleep(second)  # API 호출 간 대기
            return bestC   # 가장 낮은 rsi 값을 가진 코인 반환

def trade_buy(ticker):
    """개선된 매수 로직 - 리스크 관리와 최적 타이밍 포함"""

    krw = get_balance("KRW")
    print(f"💰 보유 원화: {krw:,.0f}원")

    # 1만원 이상 보유한 자산이 몇 개인지 확인
    balances = upbit.get_balances()
    significant_assets_count = 0
    total_asset_value = 0

    # 제외할 코인 목록 (상장폐지, 문제 코인 등)
    excluded_coins = {"KRW", "QI", "ONX", "ETHF", "ETHW", "PURSE"}

    print("📊 보유 자산 분석 시작...")
    for b in balances:
        currency = b['currency']
        balance = float(b['balance'])
        
        # KRW 및 제외 코인 건너뛰기
        if currency in excluded_coins:
            continue
        
        # 보유 수량이 0인 경우 건너뛰기
        if balance <= 0:
            continue
        
        try:
            asset_ticker = f"KRW-{currency}"
            current_price = pyupbit.get_current_price(asset_ticker)
            
            if current_price is None or current_price <= 0:
                print(f"⚠️ {currency}: 가격 조회 결과 None 또는 0")
                continue
                
            asset_value = balance * current_price
            total_asset_value += asset_value
            
            print(f"📈 {currency}: 보유량 {balance:.8f}, 현재가 {current_price:,.0f}원, 평가금액 {asset_value:,.0f}원")
            
            if asset_value >= 10000:
                significant_assets_count += 1
                print(f"✅ {currency}: 1만원 이상 자산으로 카운트 ({significant_assets_count}개째)")
            
        except Exception as e:
            print(f"❌ {currency}: 가격 조회 실패 - {str(e)}")
            continue

    print(f"📋 분석 완료: 총 {significant_assets_count}개 자산이 1만원 이상, 총 평가금액 {total_asset_value:,.0f}원")

    # === 2. 보유 자산 수에 따른 매수 금액 결정 ===
    buy_size = 0

    if significant_assets_count >= 1:
        print(f"🎯 1만원 이상 보유 자산 {significant_assets_count}개 확인 → 보유 원화 전량 매수 로직 적용")
        buy_size = krw * 0.9995  # 수수료 고려하여 99.95% 매수
        print(f"💵 전량 매수 금액: {buy_size:,.0f}원 (원화의 99.95%)")
    else:
        print("⚡ 1만원 이상 보유 자산 없음 → 보유 원화 절반 매수 로직 적용")
        buy_size = krw * 0.5
        print(f"💵 절반 매수 금액: {buy_size:,.0f}원 (원화의 50%)")

    print(f"🔥 최종 매수 예정 금액: {buy_size:,.0f}원")

    # === 3. 기존 기술적 분석 및 매수 실행 로직 ===
    max_retries = 5
    attempt = 0
        
    # 개별 코인 분석
    ta_rsi = get_rsi(ticker, 14, interval=min5)
    rsi = ta_rsi.values
    
    # 추가 데이터 가져오기
    df = pyupbit.get_ohlcv(ticker, interval=min5, count=50)
    time.sleep(0.3)
    if df is None:
        send_discord_message(f"[매수실패] {ticker} 데이터 가져오기 실패")
        return "Data fetch failed", None
    
    cur_price = pyupbit.get_current_price(ticker)
    df_close = df['close'].values
    df_volume = df['volume'].values
    
    last_ema = get_ema(ticker, interval=min5).iloc[-1]
    
    # === 개선된 매수 조건들 ===
    
    # 1. 볼린저 밴드 위치 확인
    bands_df = get_bollinger_bands(ticker, interval=min5, window=30, std_dev=2.2)
    lower_band = bands_df['Lower_Band'].values[-1]
    upper_band = bands_df['Upper_Band'].values[-1]
    bb_position = (cur_price - lower_band) / (upper_band - lower_band)
    
    # 2. 가격 추세 확인
    price_ma20 = df_close[-20:].mean()
    
    # 3. 거래량 확인
    volume_ma5 = df_volume[-5:].mean()
    volume_ma20 = df_volume[-20:].mean()
    
    # 4. 급락 방지 조건
    recent_drop = (df_close[-1] - df_close[-5]) / df_close[-5]  # 최근 5캔들 변화율
    
    if krw >= min_krw:
        while attempt < max_retries:
            attempt += 1
            cur_price = pyupbit.get_current_price(ticker)  # 매번 최신 가격 업데이트
            
            print(f"[매수 조건 확인]: {ticker} 현재가: {cur_price:,.2f} / 시도: {attempt}/{max_retries}")
            
            # === 핵심 매수 조건 체크 ===
            
            # 기본 조건: EMA 하단 + RSI 적정 범위
            basic_condition = (
                cur_price < last_ema and 
                rsi_buy_s < rsi[-1] < rsi_buy_e
            )
            
            # 안전 조건들
            safety_conditions = [
                bb_position < 0.4,                    # 볼린저 밴드 하위 40% 구간
                rsi[-1] > rsi[-2],                    # RSI 상승 전환
                volume_ma5 > volume_ma20 * 0.8,       # 거래량 적정 수준
                recent_drop > -0.05,                  # 최근 5% 이상 급락 아님
                cur_price > price_ma20 * 0.92,        # 20일 이평선 대비 8% 이상 하락 아님
                abs(recent_drop) < 0.15               # 극단적 변동 아님 (±15%)
            ]
            
            safety_score = sum(safety_conditions)
            
            # 매수 실행 조건
            if basic_condition and safety_score >= 4:  # 6개 안전조건 중 4개 이상 충족
                
                # === 스마트 매수 실행 ===
                buy_attempts = 3
                for i in range(buy_attempts):
                    try:
                        # 최종 가격 재확인 (급변동 대비)
                        final_price = pyupbit.get_current_price(ticker)
                        price_change = abs(final_price - cur_price) / cur_price
                        
                        if price_change > 0.02:  # 2% 이상 급변동시 매수 취소
                            send_discord_message(f"[매수취소] {ticker} 급변동 감지: {price_change:.2%}")
                            return "Price volatility too high", None
                        
                        buy_order = upbit.buy_market_order(ticker, buy_size)
                        
                        # 매수 성공 메시지
                        buyedmsg = f"✅ ★★매수 성공★★: {ticker}\n"
                        buyedmsg += f"💰 매수가: {final_price:,.2f} | 금액: {buy_size:,.0f}원\n"
                        buyedmsg += f"📊 RSI: {rsi[-2]:,.1f} → {rsi[-1]:,.1f} | BB위치: {bb_position:.1%}\n"
                        buyedmsg += f"📈 안전점수: {safety_score}/6 | EMA대비: {((final_price/last_ema-1)*100):+.2f}% "
                        
                        print(buyedmsg)
                        send_discord_message(buyedmsg)
                        return buy_order

                    except (KeyError, ValueError) as e:
                        error_msg = f"매수 주문 실행 중 오류: {e}, 재시도 중...({i+1}/{buy_attempts})"
                        print(error_msg)
                        send_discord_message(error_msg)
                        time.sleep(5 * (i + 1))
                
                return "Buy order failed", None
            
            else:
                # 조건 미충족 상세 로그
                condition_msg = f"[매수 대기]: {ticker} ({attempt}/{max_retries})\n"
                condition_msg += f"현재가: {cur_price:,.2f} | EMA: {last_ema:,.2f} ({((cur_price/last_ema-1)*100):+.2f}%)\n"
                condition_msg += f"RSI: {rsi[-1]:,.1f} | BB위치: {bb_position:.1%} | 안전점수: {safety_score}/6 | 기본조건: {basic_condition}\n"
                
                print(condition_msg)
                if attempt == max_retries:  # 마지막 시도시에만 디스코드 전송
                    send_discord_message(condition_msg)
                
                time.sleep(10)  # 10초 대기 후 재시도
        
        # 최대 시도 횟수 초과
        final_fail_msg = f"❌ **매수 실패**: {ticker}\n"
        final_fail_msg += f"최종가: {cur_price:,.2f} | EMA: {last_ema:,.2f}\n"
        final_fail_msg += f"RSI: {rsi[-1]:,.1f} | BB위치: {bb_position:.1%}\n"
        final_fail_msg += f"사유: {max_retries}회 시도 후 조건 미충족"
        
        print(final_fail_msg)
        send_discord_message(final_fail_msg)
        return "Max attempts exceeded", None
    
    else:
        insufficient_msg = f"💸 **잔고 부족**: 현재 {krw:,.0f}원 < 최소 {min_krw:,.0f}원"
        print(insufficient_msg)
        send_discord_message(insufficient_msg)
        return "Insufficient balance", None
    



def get_enhanced_indicators(ticker):
    """
    핵심 지표들만 간단히 계산
    """
    df = pyupbit.get_ohlcv(ticker, interval="minute5", count=50)
    time.sleep(0.3)
    
    if df is None or len(df) < 20:
        return None
    
    # 1. MACD (매도 타이밍의 핵심 지표)
    exp1 = df['close'].ewm(span=12).mean()
    exp2 = df['close'].ewm(span=26).mean()
    df['macd'] = exp1 - exp2
    df['macd_signal'] = df['macd'].ewm(span=9).mean()
    
    # 2. 볼린저 밴드 (과매수/과매도 판단)
    df['bb_mid'] = df['close'].rolling(window=20).mean()
    df['bb_std'] = df['close'].rolling(window=20).std()
    df['bb_upper'] = df['bb_mid'] + (df['bb_std'] * 2)
    df['bb_position'] = (df['close'] - df['bb_mid']) / df['bb_std']
    
    # 3. 거래량 (신호 확인용)
    df['volume_avg'] = df['volume'].rolling(window=10).mean()
    df['volume_spike'] = df['volume'] / df['volume_avg']
    
    return df

def calculate_improved_sell_signal(ticker, profit_rate):
    """
    개선된 매도 신호 계산 - 상승 여력을 고려한 신중한 매도 판단
    실제 get_enhanced_indicators 구조에 맞춤
    """
    df = get_enhanced_indicators(ticker)
    if df is None:
        return False, "데이터 없음"
    
    latest = df.iloc[-1]
    prev = df.iloc[-2]
    prev2 = df.iloc[-3] if len(df) >= 3 else prev
    
    # 매도 신호 및 강도 계산
    signals = []
    sell_strength = 0  # 매도 신호 강도 점수
    
    # === 1. 트렌드 모멘텀 분석 (bb_mid 20일선 활용) ===
    trend_strength = 0
    
    # 20일 이동평균선(bb_mid) 상승/하락 판단
    bb_mid_rising = latest['bb_mid'] > prev['bb_mid'] > prev2['bb_mid']
    price_above_ma20 = latest['close'] > latest['bb_mid']
    
    # 상승 모멘텀이 있으면 매도에 신중
    if price_above_ma20 and bb_mid_rising:
        trend_strength = -2  # 매도 신호 강도 감소
    elif price_above_ma20:  # 가격만 20일선 위
        trend_strength = -1
    
    # === 2. MACD 분석 (기존보다 신중하게) ===
    macd_bearish = (prev['macd'] > prev['macd_signal']) and (latest['macd'] < latest['macd_signal'])
    if macd_bearish:
        # MACD와 시그널이 모두 양수면 여전히 상승 모멘텀
        if latest['macd'] > 0 and latest['macd_signal'] > 0:
            signals.append("MACD약한하향크로스")
            sell_strength += 1
        else:
            signals.append("MACD강한하향크로스")
            sell_strength += 2
    
    # MACD 히스토그램이 연속 감소하는 경우
    macd_hist_curr = latest['macd'] - latest['macd_signal']
    macd_hist_prev = prev['macd'] - prev['macd_signal']
    macd_hist_prev2 = prev2['macd'] - prev2['macd_signal'] if len(df) >= 3 else macd_hist_prev
    
    if macd_hist_prev2 > macd_hist_prev > macd_hist_curr and macd_hist_curr < 0:
        signals.append("MACD모멘텀약화")
        sell_strength += 1
    
    # === 3. 볼린저 밴드 개선된 분석 ===
    bb_position = latest['bb_position']
    bb_prev_position = prev['bb_position']
    
    # 상단 돌파 후 하락하는 경우
    if bb_position > 2.0:  # 상단 크게 돌파
        if bb_prev_position > bb_position:  # 하락 중
            signals.append("볼밴상단급락")
            sell_strength += 3  # 강한 신호
    elif bb_position > 1.8:  # 상단 근처 돌파
        if bb_prev_position > bb_position:
            signals.append("볼밴상단이탈")
            sell_strength += 2
    elif bb_position > 1.5:  # 상단 근처
        # 2틱 연속 하락할 때만
        bb_prev2_position = prev2['bb_position'] if len(df) >= 3 else bb_prev_position
        if bb_prev2_position > bb_prev_position > bb_position:
            signals.append("볼밴상단약화")
            sell_strength += 1
    
    # === 4. RSI 개선된 분석 ===
    ta_rsi = get_rsi(ticker, 14, interval="minute5")
    if ta_rsi is not None and len(ta_rsi) >= 3:
        rsi_current = ta_rsi.iloc[-1]
        rsi_prev = ta_rsi.iloc[-2]
        rsi_prev2 = ta_rsi.iloc[-3]
        
        # RSI 80 이상에서만 극과매수 판단 (더 신중하게)
        if rsi_current > 80:
            if rsi_prev > rsi_current:
                signals.append("RSI극과매수하락")
                sell_strength += 2
        elif rsi_current > 75:
            # 연속 2번 하락할 때만 신호
            if rsi_prev2 > rsi_prev > rsi_current:
                signals.append("RSI과매수연속하락")
                sell_strength += 1
        elif rsi_current > 70:
            # 3번 연속 하락 + 5 이상 하락폭
            if (rsi_prev2 > rsi_prev > rsi_current and 
                rsi_prev2 - rsi_current > 5):
                signals.append("RSI과매수급락")
                sell_strength += 1
    
    # === 5. 거래량 분석 (volume_spike 활용) ===
    volume_spike = latest['volume_spike']
    price_change = (latest['close'] - prev['close']) / prev['close']
    
    # 대량 거래와 함께 하락
    if volume_spike > 1.5 and price_change < -0.01:  # 1% 이상 하락
        signals.append("대량매도")
        sell_strength += 2
    elif volume_spike > 1.2 and price_change < -0.005:  # 0.5% 이상 하락
        signals.append("거래량증가하락")
        sell_strength += 1
    
    # === 6. 다이버전스 (기존 로직 유지) ===
    divergence_result = get_rsi_bear_diver(ticker)
    diver_bear = divergence_result['is_bearish_divergence'] if divergence_result else False
    if diver_bear:
        signals.append("베어다이버전스")
        sell_strength += 1
    
    # === 7. 20일선(bb_mid) 이탈 체크 ===
    if latest['close'] < latest['bb_mid'] and prev['close'] > prev['bb_mid']:
        # 거래량을 동반한 이탈인지 확인
        if volume_spike > 1.1:
            signals.append("20일선대량이탈")
            sell_strength += 2
        else:
            signals.append("20일선이탈")
            sell_strength += 1
    
    # === 8. 가격 모멘텀 체크 ===
    # 연속 하락하는 캔들 수 체크
    consecutive_down = 0
    for i in range(min(5, len(df))):
        if df.iloc[-(i+1)]['close'] < df.iloc[-(i+2)]['close'] if len(df) > i+1 else False:
            consecutive_down += 1
        else:
            break
    
    if consecutive_down >= 3:
        signals.append(f"연속{consecutive_down}틱하락")
        sell_strength += consecutive_down - 2  # 3틱=1점, 4틱=2점, 5틱=3점
    
    # === 최종 매도 판단 로직 ===
    # 트렌드 강도 반영한 최종 점수
    final_score = sell_strength + trend_strength
    
    # 수익률별 차등 적용 (max_rate는 전역변수 가정)
    try:
        if profit_rate >= max_rate:  # 목표 수익률 달성
            required_score = 1  # 낮은 기준
        elif profit_rate >= max_rate * 0.8:  # 80% 이상 달성
            required_score = 2
        elif profit_rate >= max_rate * 0.6:  # 60% 이상 달성
            required_score = 3
        else:  # 낮은 수익률
            required_score = 4  # 높은 기준 (신중하게)
    except:
        # max_rate가 정의되지 않은 경우 기본값 사용
        if profit_rate >= 10:  # 10% 이상
            required_score = 1
        elif profit_rate >= 7:   # 7% 이상
            required_score = 2
        elif profit_rate >= 5:   # 5% 이상
            required_score = 3
        else:
            required_score = 4
    
    # 상승 트렌드에서는 더 높은 기준 적용
    if price_above_ma20 and bb_mid_rising:
        required_score += 1
    
    should_sell = final_score >= required_score
    
    # 신호 텍스트 생성
    if signals:
        signal_text = " + ".join(signals) + f" (점수:{final_score}/{required_score})"
    else:
        signal_text = f"신호없음 (점수:{final_score}/{required_score})"
    
    return should_sell, signal_text

def trade_sell(ticker):
    """
    기존 코드 구조를 유지한 개선된 매도 로직
    """
    currency = ticker.split("-")[1]
    buyed_amount = get_balance(currency)
    
    if buyed_amount <= 0:
        return None
    
    avg_buy_price = upbit.get_avg_buy_price(currency)
    cur_price = pyupbit.get_current_price(ticker)
    profit_rate = (cur_price - avg_buy_price) / avg_buy_price * 100 if avg_buy_price > 0 else 0
    
    # RSI 계산 (기존 방식 유지)
    ta_rsi = get_rsi(ticker, 14, interval="minute5")
    if ta_rsi is None or len(ta_rsi) < 2:
        print(f"[{ticker}] RSI 데이터 없음")
        return None
    
    rsi = ta_rsi.values
    rsi_downing = (rsi_sell_s <= rsi[-1] <= rsi_sell_e) and rsi[-2] > rsi[-1]
    
    # 개선된 매도 신호 계산
    should_sell_technical, signal_details = calculate_improved_sell_signal(ticker, profit_rate)
        
    max_attempts = sell_time
    attempts = 0
        
    if profit_rate >= min_rate:
        while attempts < max_attempts:
            print(f"[{ticker}] / [매도시도 {attempts + 1} / {max_attempts}] / 수익률: {profit_rate:.2f}%")
            
            # 목표 수익률 달성시 즉시 매도
            if profit_rate >= max_rate:
                sell_order = upbit.sell_market_order(ticker, buyed_amount)
                sellmsg = f"[!!목표가달성!!]: [{ticker}] / 수익률: {profit_rate:.2f}% / 현재가: {cur_price:,.1f}\n"
                sellmsg += f"신호: {signal_details}\n"
                print(sellmsg)
                send_discord_message(sellmsg)
                return sell_order
            
            # 기술적 매도 신호 확인
            elif should_sell_technical:
                sell_order = upbit.sell_market_order(ticker, buyed_amount)
                sellmsg = f"[기술적매도]: [{ticker}] / 수익률: {profit_rate:.2f}% / 현재가: {cur_price:,.1f}\n"
                sellmsg += f"신호: {signal_details}\n"
                sellmsg += f"RSI하락: {rsi_downing} / RSI: {rsi[-2]:.1f} → {rsi[-1]:.1f}\n"
                print(sellmsg)
                send_discord_message(sellmsg)
                return sell_order
            
            else:
                # 가격 업데이트
                cur_price = pyupbit.get_current_price(ticker)
                profit_rate = (cur_price - avg_buy_price) / avg_buy_price * 100 if avg_buy_price > 0 else 0
                should_sell_technical, signal_details = calculate_improved_sell_signal(ticker, profit_rate)
                time.sleep(second)
            
            attempts += 1
        
        # 감시 시간 종료 후 다이버전스 기반 매도 고려
        else:
            if should_sell_technical and profit_rate > min_rate:  # 기존 변수 재사용
                sell_order = upbit.sell_market_order(ticker, buyed_amount)
                middlemsg = f"[기술적매도]: [{ticker}] / 수익률: {profit_rate:.2f}% / 현재가: {cur_price:,.1f}\n"
                middlemsg += f"매도신호: {signal_details}\n"  # 기존 변수 재사용
                middlemsg += f"RSI하락: {rsi_downing} / RSI: {rsi[-2]:.1f} → {rsi[-1]:.1f}\n"
                print(middlemsg)
                send_discord_message(middlemsg)
                return sell_order
            else:
                return None
    
    else:
        # 손절 로직 (기존 유지)
        if profit_rate < cut_rate:
            sell_order = upbit.sell_market_order(ticker, buyed_amount)
            cut_message = f"[손절]: [{ticker}] 수익률: {profit_rate:.2f}% / 현재가: {cur_price:,.1f}\n"
            cut_message += f"RSI: {rsi[-1]:.1f} / 신호: {signal_details}\n"
            print(cut_message)
            send_discord_message(cut_message)
            return sell_order
        else:
            return None

def send_profit_report():
    first_run = True  # 처음 실행 여부를 체크하는 변수

    while True:
        try:
            now = datetime.now()  # 현재 시간을 루프 시작 시마다 업데이트
            next_hour = (now + timedelta(hours=1)).replace(minute=0, second=0, microsecond=0)
            time_until_next_hour = (next_hour - now).total_seconds()
            report_message = f" 현재 수익률 보고서:\n"
            balances = upbit.get_balances()

            if isinstance(balances, list):              # balances가 리스트인지 확인
                for b in balances:
                    if isinstance(b, dict) and 'currency' in b:                     # b가 딕셔너리인지 확인
                        if b['currency'] in ["KRW", "QI", "ONX", "ETHF", "ETHW", "PURSE"]:
                            continue

                        ticker = b['currency']  # 티커를 currency로 설정
                        buyed_amount = get_balance(ticker)  # get_balance 함수 사용

                        if buyed_amount > 0:
                            avg_buy_price = float(b['avg_buy_price'])
                            cur_price = pyupbit.get_current_price(f"KRW-{ticker}")
                            profit_rate = (cur_price - avg_buy_price) / avg_buy_price * 100 if avg_buy_price > 0 else 0
                            
                            ta_rsi = get_rsi(f"KRW-{ticker}", 14, interval = min5)
                            rsi = ta_rsi.values

                            report_message += f"[{ticker}] 수익률: {profit_rate:.2f}% / 현재가: {cur_price:,.2f} / 평균 매수 가격: {avg_buy_price:.2f} \n"
                            report_message += f"RSI: {rsi[-3]:,.3f} >> {rsi[-2]:,.3f} >> {rsi[-1]:,.3f} \n"
                                                
                        else:
                            report_message += "RSI 데이터가 충분하지 않습니다.\n"
                send_discord_message(report_message)

                if first_run:                   # 첫 실행 이후 대기
                    first_run = False  # 첫 실행 후 변경
                else:
                    time.sleep(time_until_next_hour)  # 다음 정시까지 대기

            else:
                print("balances는 리스트가 아닙니다.")
                send_discord_message("balances는 리스트가 아닙니다.")
                time.sleep(5)

        except (KeyError, ValueError) as e:
            print(f"send_profit_report/수익률 보고 중 오류 발생: {e}")
            send_discord_message(f"send_profit_report/수익률 보고 중 오류 발생: {e}")
            time.sleep(5)
            
trade_start = datetime.now().strftime('%m/%d %H시%M분%S초')  # 시작시간 기록
trade_msg = f'{trade_start} trading start \n'
trade_msg += f'매도: {min_rate}% ~ {max_rate}% / 시도: {sell_time}회 / RsiBuy: {rsi_buy_s} ~ {rsi_buy_e} / RsiSell: {rsi_sell_s} ~ {rsi_sell_e} / 손절: {cut_rate}% \n'

print(trade_msg)
send_discord_message(trade_msg)

profit_report_thread = threading.Thread(target=send_profit_report)  # 수익률 보고 쓰레드 시작
profit_report_thread.daemon = True  # 메인 프로세스 종료 시 함께 종료되도록 설정
profit_report_thread.start()

def selling_logic():
    while True:
        try:
            balances = upbit.get_balances()
            for b in balances:
                if b['currency'] not in ["KRW", "QI", "ONX", "ETHF", "ETHW", "PURSE"]:
                        ticker = f"KRW-{b['currency']}"
                        trade_sell(ticker)
                time.sleep(second)

        except Exception as e:
            print(f"selling_logic / 에러 발생: {e}")
            send_discord_message(f"selling_logic / 에러 발생: {e}")
            time.sleep(5)

def buying_logic():
    while True:
        try:
            stopbuy_time = datetime.now()
            restricted_start = stopbuy_time.replace(hour=8, minute=50, second=0, microsecond=0)
            restricted_end = stopbuy_time.replace(hour=9, minute=10, second=0, microsecond=0)
            
            if restricted_start <= stopbuy_time <= restricted_end:  # 매수 제한 시간 체크
                time.sleep(60) 
                continue
            
            else:  # 매수 금지 시간이 아닐 때
                krw_balance = get_balance("KRW")  # 현재 KRW 잔고 조회
                if krw_balance > min_krw: 
                    best_ticker = get_best_ticker()

                    if best_ticker:
                        buy_time = datetime.now().strftime('%m/%d %H시%M분%S초')
                        send_discord_message(f"[{buy_time}] 선정코인: [{best_ticker}]")
                        result = trade_buy(best_ticker)
                        
                        if result:
                            time.sleep(60)
                        else:
                            time.sleep(30)
                    else:
                        time.sleep(30)

                else:
                    time.sleep(180)

        except (KeyError, ValueError) as e:
            print(f"buying_logic / 에러 발생: {e}")
            send_discord_message(f"buying_logic / 에러 발생: {e}")
            time.sleep(5)

# 매도 쓰레드 생성
selling_thread = threading.Thread(target = selling_logic)
selling_thread.start()

# 매수 쓰레드 생성
buying_thread = threading.Thread(target = buying_logic)
buying_thread.start()