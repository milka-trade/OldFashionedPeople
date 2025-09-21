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
            max_rate = float(input("최대 수익률 (예: 2.1):"))
            sell_time = int(input("매도감시횟수 (예: 10): "))
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
min_krw = 10_000
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
    적응형 학습 기반 가격 방향성 예측 및 최적 매수 타이밍 포착
    과거 데이터 백테스팅을 통한 동적 가중치 조정 및 시장 적응형 알고리즘
    
    개선사항:
    - 급락 위험 조기 감지 및 강제 하향 조정
    - 상승 신호 민감도 향상 및 확신도 기반 조정
    - 시장 노이즈 필터링 및 가짜 신호 제거
    - 1-2% 수익 최적화를 위한 세밀한 임계값 조정
    
    Returns:
        tuple: (prediction, total_score)
        prediction: 'SURGE'/'UP'/'DOWN'/'CRASH'/'NEUTRAL'
        total_score: 예측 점수 (-5.0 ~ +5.0)
    """
    try:
        # 확장된 데이터 수집 (백테스팅용)
        df = pyupbit.get_ohlcv(ticker, interval=min5, count=200)
        if df is None or len(df) < 150:
            return 'NEUTRAL', 0
        
        # 데이터 추출
        closes = df['close'].values
        highs = df['high'].values
        lows = df['low'].values
        volumes = df['volume'].values
        opens = df['open'].values
        
        # === 백테스팅 및 성능 평가 시스템 ===
        
        # 과거 50개 구간에서 각 지표의 예측 성공률 계산
        backtest_periods = min(50, len(closes) - 20)  # 최대 50개 구간 백테스트
        
        # 지표별 성공률 추적을 위한 변수들
        trend_success_rate = 0.5
        momentum_success_rate = 0.5
        volume_success_rate = 0.5
        volatility_success_rate = 0.5
        pattern_success_rate = 0.5
        
        # 시장 상황 분석 (최근 100 캔들)
        market_trend = 0  # -1: 하락장, 0: 횡보장, 1: 상승장
        market_volatility = 0  # 0: 저변동성, 1: 중변동성, 2: 고변동성
        
        if len(closes) >= 100:
            # 시장 트렌드 판단
            long_term_change = (closes[-1] - closes[-100]) / closes[-100]
            mid_term_change = (closes[-1] - closes[-50]) / closes[-50]
            
            if long_term_change > 0.1 and mid_term_change > 0.05:
                market_trend = 1  # 상승장
            elif long_term_change < -0.1 and mid_term_change < -0.05:
                market_trend = -1  # 하락장
            else:
                market_trend = 0  # 횡보장
            
            # 변동성 수준 판단
            recent_volatility = []
            for i in range(len(closes)-20, len(closes)-1):
                vol = abs(closes[i+1] - closes[i]) / closes[i]
                recent_volatility.append(vol)
            
            avg_volatility = sum(recent_volatility) / len(recent_volatility)
            if avg_volatility > 0.025:
                market_volatility = 2  # 고변동성
            elif avg_volatility > 0.015:
                market_volatility = 1  # 중변동성
            else:
                market_volatility = 0  # 저변동성
        
        # 백테스트 기반 지표별 성능 평가
        if backtest_periods >= 30:
            trend_correct = 0
            momentum_correct = 0
            volume_correct = 0
            volatility_correct = 0
            pattern_correct = 0
            total_tests = 0
            
            for i in range(len(closes) - backtest_periods - 10, len(closes) - 10, 2):
                if i < 50:  # 충분한 데이터 확보
                    continue
                    
                # 각 시점에서의 지표값 계산
                test_closes = closes[:i+1]
                test_volumes = volumes[:i+1]
                test_highs = highs[:i+1]
                test_lows = lows[:i+1]
                test_opens = opens[:i+1]
                
                # 실제 결과 (다음 10캔들 평균 변화)
                if i + 10 < len(closes):
                    actual_change = (closes[i+10] - closes[i]) / closes[i]
                    actual_direction = 1 if actual_change > 0.01 else (-1 if actual_change < -0.01 else 0)
                    
                    # === 트렌드 지표 테스트 ===
                    if len(test_closes) >= 50:
                        sma_10 = test_closes[-10:].mean()
                        sma_20 = test_closes[-20:].mean()
                        sma_50 = test_closes[-50:].mean()
                        
                        trend_signal = 0
                        if sma_10 > sma_20 > sma_50:
                            trend_signal = 1
                        elif sma_10 < sma_20 < sma_50:
                            trend_signal = -1
                        
                        if (trend_signal == 1 and actual_direction >= 0) or \
                           (trend_signal == -1 and actual_direction <= 0) or \
                           (trend_signal == 0 and actual_direction == 0):
                            trend_correct += 1
                    
                    # === 모멘텀 지표 테스트 ===
                    try:
                        rsi_data = get_rsi(ticker, 14, interval=min5)
                        if len(rsi_data.values) > i:
                            rsi_val = rsi_data.values[min(i, len(rsi_data.values)-1)]
                            momentum_signal = 0
                            if rsi_val < 30:
                                momentum_signal = 1
                            elif rsi_val > 70:
                                momentum_signal = -1
                            
                            if (momentum_signal == 1 and actual_direction >= 0) or \
                               (momentum_signal == -1 and actual_direction <= 0) or \
                               (momentum_signal == 0 and actual_direction == 0):
                                momentum_correct += 1
                    except:
                        momentum_correct += 0.5  # 중립 처리
                    
                    # === 거래량 지표 테스트 ===
                    if len(test_volumes) >= 20:
                        vol_recent = test_volumes[-5:].mean()
                        vol_baseline = test_volumes[-20:-5].mean()
                        vol_ratio = vol_recent / vol_baseline if vol_baseline > 0 else 1
                        
                        price_change = (test_closes[-1] - test_closes[-5]) / test_closes[-5]
                        volume_signal = 0
                        if vol_ratio > 1.5 and price_change > 0:
                            volume_signal = 1
                        elif vol_ratio > 1.5 and price_change < 0:
                            volume_signal = -1
                        
                        if (volume_signal == 1 and actual_direction >= 0) or \
                           (volume_signal == -1 and actual_direction <= 0) or \
                           (volume_signal == 0 and actual_direction == 0):
                            volume_correct += 1
                    
                    total_tests += 1
            
            # 성공률 계산 (최소 0.2, 최대 0.8로 제한)
            if total_tests > 0:
                trend_success_rate = max(0.2, min(0.8, trend_correct / total_tests))
                momentum_success_rate = max(0.2, min(0.8, momentum_correct / total_tests))
                volume_success_rate = max(0.2, min(0.8, volume_correct / total_tests))
                volatility_success_rate = 0.5  # 신규 지표는 기본값
                pattern_success_rate = 0.5  # 신규 지표는 기본값
        
        # === 급락 위험 조기 감지 시스템 ===
        crash_risk_detected = False
        crash_risk_score = 0
        
        # 1. 대량 매도 패턴 감지
        if len(volumes) >= 10 and len(closes) >= 10:
            recent_volume_surge = False
            volume_price_divergence = False
            
            # 최근 거래량 급증 + 가격 하락
            vol_recent_3 = volumes[-3:].mean()
            vol_baseline_10 = volumes[-13:-3].mean()
            if vol_baseline_10 > 0:
                vol_surge_ratio = vol_recent_3 / vol_baseline_10
                price_change_3 = (closes[-1] - closes[-3]) / closes[-3]
                
                if vol_surge_ratio > 2.0 and price_change_3 < -0.01:
                    recent_volume_surge = True
                    crash_risk_score -= 2.0
                
                # 거래량과 가격의 다이버전스 (거래량 증가 + 가격 하락)
                if vol_surge_ratio > 1.8 and price_change_3 < -0.008:
                    volume_price_divergence = True
                    crash_risk_score -= 1.5
        
        # 2. 연속 음봉 + 저점 갱신 패턴
        consecutive_red_with_new_low = 0
        recent_lowest = lows[-10:].min()
        for i in range(max(0, len(closes)-5), len(closes)):
            if closes[i] < opens[i]:  # 음봉
                consecutive_red_with_new_low += 1
                if lows[i] <= recent_lowest * 1.001:  # 새로운 저점 근처
                    crash_risk_score -= 0.8
        
        if consecutive_red_with_new_low >= 3:
            crash_risk_detected = True
            crash_risk_score -= 2.5
        
        # 3. 기술적 지지선 붕괴 감지
        support_broken = False
        if len(closes) >= 20 and len(volumes) >= 20:
            # 최근 20캔들 중 하위 25% 가격을 지지선으로 간주
            support_level = sorted(lows[-20:])[:5]  # 하위 5개
            avg_support = sum(support_level) / len(support_level)
            
            current_price = closes[-1]
            recent_volume = volumes[-3:].mean()
            baseline_volume = volumes[-20:-3].mean()
            
            if current_price < avg_support * 0.995:  # 지지선 0.5% 하향 이탈
                if baseline_volume > 0 and recent_volume / baseline_volume > 1.3:  # 거래량도 증가
                    support_broken = True
                    crash_risk_score -= 3.0
        
        # === 시장 상황별 가중치 조정 ===
        
        # 기본 가중치
        base_weights = {
            'crash_surge': 0.25,  # 급락감지 강화로 인한 비중 축소
            'volatility': 0.18,
            'volume': 0.22,  # 거래량 분석 비중 증가
            'technical': 0.25,  # 기술적 분석 비중 증가
            'support_resistance': 0.10
        }
        
        # 시장 상황별 조정
        if market_trend == 1:  # 상승장
            base_weights['technical'] += 0.08
            base_weights['volume'] += 0.05
            base_weights['crash_surge'] -= 0.10
            base_weights['volatility'] -= 0.03
        elif market_trend == -1:  # 하락장
            base_weights['crash_surge'] += 0.12
            base_weights['volatility'] += 0.08
            base_weights['technical'] -= 0.12
            base_weights['volume'] -= 0.08
        
        # 변동성별 조정
        if market_volatility == 2:  # 고변동성
            base_weights['volatility'] += 0.08
            base_weights['crash_surge'] += 0.05
            base_weights['technical'] -= 0.10
            base_weights['support_resistance'] -= 0.03
        elif market_volatility == 0:  # 저변동성
            base_weights['technical'] += 0.12
            base_weights['support_resistance'] += 0.05
            base_weights['volatility'] -= 0.12
            base_weights['crash_surge'] -= 0.05
        
        # 성공률 기반 추가 조정
        success_multipliers = {
            'trend': trend_success_rate,
            'momentum': momentum_success_rate,
            'volume': volume_success_rate,
            'volatility': volatility_success_rate,
            'pattern': pattern_success_rate
        }
        
        # === 적응형 지표 계산 ===
        
        # 1. 강화된 급락/급등 감지
        crash_surge_score = 0
        
        # 연속 캔들 분석 (적응형 임계값)
        consecutive_threshold = 4 if market_volatility >= 1 else 3
        consecutive_red = 0
        consecutive_green = 0
        
        for i in range(max(0, len(closes)-10), len(closes)):
            if closes[i] < opens[i]:
                consecutive_red += 1
                consecutive_green = 0
            elif closes[i] > opens[i]:
                consecutive_green += 1
                consecutive_red = 0
        
        if consecutive_red >= consecutive_threshold:
            intensity = min(3.0, consecutive_red * 0.8)
            crash_surge_score -= intensity * (1 + market_volatility * 0.2)
        elif consecutive_green >= consecutive_threshold:
            intensity = min(3.0, consecutive_green * 0.8)
            crash_surge_score += intensity * (1 + market_volatility * 0.2)
        
        # 급격한 변화 감지 (적응형)
        change_threshold = 0.025 if market_volatility >= 1 else 0.02
        recent_changes = []
        for i in range(max(0, len(closes)-5), len(closes)-1):
            change = (closes[i+1] - closes[i]) / closes[i]
            recent_changes.append(change)
        
        if recent_changes:
            max_drop = min(recent_changes)
            max_surge = max(recent_changes)
            
            if max_drop < -change_threshold:
                crash_surge_score -= min(3.0, abs(max_drop) * 100)
            if max_surge > change_threshold:
                crash_surge_score += min(3.0, max_surge * 100)
        
        # 급락 위험 감지 시 추가 페널티
        crash_surge_score += crash_risk_score
        
        # 2. 적응형 변동성 분석
        volatility_score = 0
        
        recent_vol = []
        past_vol = []
        vol_window = 15 if market_volatility >= 1 else 10
        
        for i in range(max(0, len(closes)-vol_window*2), len(closes)):
            if i > 0:
                vol = abs(closes[i] - closes[i-1]) / closes[i-1]
                if i >= len(closes) - vol_window:
                    recent_vol.append(vol)
                else:
                    past_vol.append(vol)
        
        if recent_vol and past_vol:
            recent_avg = sum(recent_vol) / len(recent_vol)
            past_avg = sum(past_vol) / len(past_vol)
            vol_ratio = recent_avg / past_avg if past_avg > 0 else 1
            
            # 시장 상황별 임계값 조정
            vol_threshold = 1.8 if market_volatility >= 1 else 1.5
            
            if vol_ratio > vol_threshold:
                price_trend = (closes[-1] - closes[-vol_window]) / closes[-vol_window]
                if price_trend < -0.01:
                    volatility_score -= min(3.0, vol_ratio * 1.5)
                else:
                    volatility_score += min(2.0, vol_ratio * 0.8)
        
        # 3. 개선된 거래량 분석
        volume_score = 0
        
        vol_recent = volumes[-7:].mean()
        vol_baseline = volumes[-30:-7].mean()
        volume_ratio = vol_recent / vol_baseline if vol_baseline > 0 else 1
        
        price_change_recent = (closes[-1] - closes[-7]) / closes[-7]
        
        # 시장별 거래량 민감도 조정
        vol_multiplier = 1.2 if market_trend == -1 else (0.9 if market_trend == 1 else 1.0)
        
        # 거래량 패턴별 세분화된 점수 체계
        if volume_ratio > 3.0 * vol_multiplier:  # 극대 거래량
            if price_change_recent > 0.025:  # 강한 상승과 함께
                volume_score += min(4.5, volume_ratio * vol_multiplier * 0.9)
            elif price_change_recent < -0.025:  # 강한 하락과 함께
                volume_score -= min(5.0, volume_ratio * vol_multiplier)
            else:  # 횡보 중 대량 거래
                volume_score += min(1.5, volume_ratio * vol_multiplier * 0.3)
        elif volume_ratio > 2.5 * vol_multiplier:
            if price_change_recent > 0.02:
                volume_score += min(3.5, volume_ratio * vol_multiplier * 0.8)
            elif price_change_recent < -0.02:
                volume_score -= min(4.0, volume_ratio * vol_multiplier)
        elif volume_ratio > 1.5 * vol_multiplier:
            if price_change_recent > 0.015:
                volume_score += min(2.5, volume_ratio * vol_multiplier * 0.6)
            elif price_change_recent < -0.015:
                volume_score -= min(2.5, volume_ratio * vol_multiplier * 0.7)
        elif volume_ratio > 1.2 * vol_multiplier:  # 미세한 거래량 증가도 포착
            if price_change_recent > 0.01:
                volume_score += min(1.5, volume_ratio * vol_multiplier * 0.5)
            elif price_change_recent < -0.01:
                volume_score -= min(1.5, volume_ratio * vol_multiplier * 0.6)
        
        # 4. 강화된 기술적 지표
        technical_score = 0
        
        # 이동평균 (성공률 반영 + 세밀한 구간 분석)
        if len(closes) >= 50:
            sma_3 = closes[-3:].mean()
            sma_5 = closes[-5:].mean()
            sma_10 = closes[-10:].mean()
            sma_20 = closes[-20:].mean()
            sma_50 = closes[-50:].mean()
            
            ma_score = 0
            current_price = closes[-1]
            
            # 완전 상승 배열
            if sma_3 > sma_5 > sma_10 > sma_20 > sma_50 and current_price > sma_3:
                ma_score = 3.5
            # 강한 상승 배열
            elif sma_5 > sma_10 > sma_20 > sma_50 and current_price > sma_5:
                ma_score = 2.8
            # 중간 상승 배열
            elif sma_5 > sma_10 > sma_20 and current_price > sma_10:
                ma_score = 2.0
            # 약한 상승 배열
            elif sma_5 > sma_10 and current_price > sma_10:
                ma_score = 1.2
            # 미세한 상승 신호 (기존에 놓쳤던 부분)
            elif current_price > sma_5 and sma_5 > sma_10:
                ma_score = 0.8
            # 완전 하락 배열
            elif sma_3 < sma_5 < sma_10 < sma_20 < sma_50 and current_price < sma_3:
                ma_score = -3.5
            # 강한 하락 배열
            elif sma_5 < sma_10 < sma_20 < sma_50 and current_price < sma_5:
                ma_score = -2.8
            # 중간 하락 배열
            elif sma_5 < sma_10 < sma_20 and current_price < sma_10:
                ma_score = -2.0
            # 약한 하락 배열
            elif sma_5 < sma_10 and current_price < sma_10:
                ma_score = -1.2
            # 미세한 하락 신호
            elif current_price < sma_5 and sma_5 < sma_10:
                ma_score = -0.8
            
            technical_score += ma_score * trend_success_rate * 1.8
        
        # RSI (성공률 반영 + 세밀한 구간)
        try:
            rsi_data = get_rsi(ticker, 14, interval=min5)
            if len(rsi_data.values) > 0:
                current_rsi = rsi_data.values[-1]
                
                rsi_score = 0
                # 극과매도 구간
                if current_rsi < 20:
                    rsi_score = 3.5
                elif current_rsi < 28:
                    rsi_score = 2.8
                elif current_rsi < 35:
                    rsi_score = 2.0
                elif current_rsi < 42:  # 중립 하단 (기존에 놓쳤던 구간)
                    rsi_score = 1.2
                elif current_rsi < 48:  # 약한 매수 구간
                    rsi_score = 0.6
                # 극과매수 구간
                elif current_rsi > 80:
                    rsi_score = -3.5
                elif current_rsi > 72:
                    rsi_score = -2.8
                elif current_rsi > 65:
                    rsi_score = -2.0
                elif current_rsi > 58:  # 중립 상단
                    rsi_score = -1.2
                elif current_rsi > 52:  # 약한 매도 구간
                    rsi_score = -0.6
                
                technical_score += rsi_score * momentum_success_rate * 1.8
        except:
            pass
        
        # 5. 향상된 지지/저항 분석
        support_resistance_score = 0
        
        if len(highs) >= 20 and len(lows) >= 20:
            recent_high = highs[-20:].max()
            recent_low = lows[-20:].min()
            current_price = closes[-1]
            
            # 저항선 돌파
            if current_price > recent_high * 1.002:  # 0.2% 돌파
                if volume_ratio > 1.2:
                    support_resistance_score += 2.5
                else:
                    support_resistance_score += 1.0  # 거래량 없어도 일부 점수
            elif current_price > recent_high * 1.001:  # 0.1% 돌파
                if volume_ratio > 1.1:
                    support_resistance_score += 1.5
            
            # 지지선 이탈
            elif current_price < recent_low * 0.998:  # 0.2% 이탈
                if volume_ratio > 1.2:
                    support_resistance_score -= 3.0
                else:
                    support_resistance_score -= 1.5
            elif current_price < recent_low * 0.999:  # 0.1% 이탈
                if volume_ratio > 1.1:
                    support_resistance_score -= 2.0
            
            # 지지/저항 근처에서의 반등/반락 패턴
            high_distance = abs(current_price - recent_high) / recent_high
            low_distance = abs(current_price - recent_low) / recent_low
            
            if high_distance < 0.005:  # 저항선 근처
                price_momentum = (closes[-1] - closes[-3]) / closes[-3]
                if price_momentum > 0.008:  # 상승 모멘텀
                    support_resistance_score += 1.2
            elif low_distance < 0.005:  # 지지선 근처
                price_momentum = (closes[-1] - closes[-3]) / closes[-3]
                if price_momentum > 0.008:  # 반등 모멘텀
                    support_resistance_score += 1.8
        
        # === 확신도 기반 신호 강도 조정 ===
        
        # 여러 지표 일치도 계산
        positive_signals = 0
        negative_signals = 0
        signal_strength = 1.0
        
        if crash_surge_score > 0.5:
            positive_signals += 1
        elif crash_surge_score < -0.5:
            negative_signals += 1
            
        if volume_score > 0.5:
            positive_signals += 1
        elif volume_score < -0.5:
            negative_signals += 1
            
        if technical_score > 0.5:
            positive_signals += 1
        elif technical_score < -0.5:
            negative_signals += 1
            
        if support_resistance_score > 0.5:
            positive_signals += 1
        elif support_resistance_score < -0.5:
            negative_signals += 1
        
        # 확신도에 따른 신호 강도 조정
        total_signals = positive_signals + negative_signals
        if total_signals >= 3:
            if positive_signals >= 3:  # 강한 매수 신호
                signal_strength = 1.3
            elif negative_signals >= 3:  # 강한 매도 신호
                signal_strength = 1.2
        elif total_signals == 2:
            signal_strength = 1.1
        elif total_signals <= 1:  # 신호 부족
            signal_strength = 0.8
        
        # === 최종 점수 계산 (적응형 가중치 + 확신도 적용) ===
        raw_score = (
            crash_surge_score * base_weights['crash_surge'] +
            volatility_score * base_weights['volatility'] +
            volume_score * base_weights['volume'] +
            technical_score * base_weights['technical'] +
            support_resistance_score * base_weights['support_resistance']
        )
        
        total_score = raw_score * signal_strength
        
        # 급락 위험 감지 시 강제 하향 조정
        if crash_risk_detected or support_broken:
            total_score = min(total_score, -1.5)  # 최소 DOWN 이하로 강제 조정
        
        # === 1-2% 수익 최적화를 위한 세밀한 임계값 조정 ===
        
        # 시장 상황별 기본 임계값
        if market_trend == 1:  # 상승장 - 더 민감하게
            surge_threshold = 2.2
            up_threshold = 0.8
            crash_threshold = -2.8
            down_threshold = -1.2
        elif market_trend == -1:  # 하락장 - 더 보수적으로
            surge_threshold = 3.2
            up_threshold = 1.5
            crash_threshold = -2.2
            down_threshold = -0.8
        else:  # 횡보장 - 중간값
            surge_threshold = 2.7
            up_threshold = 1.1
            crash_threshold = -2.7
            down_threshold = -1.1
        
        # 변동성별 추가 조정
        if market_volatility == 2:  # 고변동성 - 더 보수적
            surge_threshold += 0.4
            up_threshold += 0.2
            crash_threshold -= 0.4
            down_threshold -= 0.2
        elif market_volatility == 0:  # 저변동성 - 더 민감하게
            surge_threshold -= 0.3
            up_threshold -= 0.2
            crash_threshold += 0.3
            down_threshold += 0.2
        
        # 성공률 기반 동적 임계값 조정
        avg_success_rate = (trend_success_rate + momentum_success_rate + volume_success_rate) / 3
        
        if avg_success_rate > 0.65:  # 높은 성공률 - 더 공격적
            surge_threshold -= 0.2
            up_threshold -= 0.15
        elif avg_success_rate < 0.35:  # 낮은 성공률 - 더 보수적
            surge_threshold += 0.3
            up_threshold += 0.2
        
        # 최근 시장 패턴 기반 미세 조정
        recent_success_pattern = 0  # 최근 패턴 분석용
        
        if len(closes) >= 30:
            # 최근 30캔들에서 1-2% 수익 구간 분석
            profitable_patterns = 0
            total_patterns = 0
            
            for i in range(len(closes)-30, len(closes)-5, 3):
                if i >= 0:
                    start_price = closes[i]
                    max_profit = 0
                    
                    # 다음 5캔들에서 최대 수익률 확인
                    for j in range(i+1, min(i+6, len(closes))):
                        profit = (closes[j] - start_price) / start_price
                        max_profit = max(max_profit, profit)
                    
                    total_patterns += 1
                    if 0.01 <= max_profit <= 0.03:  # 1-3% 수익 구간
                        profitable_patterns += 1
            
            if total_patterns > 0:
                pattern_success_rate = profitable_patterns / total_patterns
                if pattern_success_rate > 0.6:  # 좋은 패턴
                    recent_success_pattern = 1
                    surge_threshold -= 0.15
                    up_threshold -= 0.1
                elif pattern_success_rate < 0.3:  # 나쁜 패턴
                    recent_success_pattern = -1
                    surge_threshold += 0.2
                    up_threshold += 0.15
        
        # === 노이즈 필터링 및 가짜 신호 제거 ===
        
        # 1. 거래량 검증
        volume_validation = True
        if len(volumes) >= 10:
            recent_vol_avg = volumes[-3:].mean()
            baseline_vol_avg = volumes[-15:-3].mean()
            
            # 상승 신호인데 거래량이 너무 적으면 신뢰도 하락
            if total_score > 0 and baseline_vol_avg > 0:
                vol_ratio_check = recent_vol_avg / baseline_vol_avg
                if vol_ratio_check < 0.7:  # 거래량 감소
                    total_score *= 0.7  # 신호 강도 약화
                    volume_validation = False
        
        # 2. 가격 패턴 일관성 검증
        pattern_consistency = True
        if len(closes) >= 10:
            # 최근 추세와 신호 방향 일치 여부
            short_trend = (closes[-1] - closes[-5]) / closes[-5]
            medium_trend = (closes[-1] - closes[-10]) / closes[-10]
            
            # 상승 신호인데 실제로는 하락 추세
            if total_score > up_threshold and short_trend < -0.01 and medium_trend < -0.015:
                total_score *= 0.6  # 강한 페널티
                pattern_consistency = False
            
            # 하락 신호인데 실제로는 상승 추세
            elif total_score < down_threshold and short_trend > 0.01 and medium_trend > 0.015:
                total_score *= 1.4  # 신호 강화 (급락 위험 높음)
        
        # 3. 시장 시간대별 신뢰도 조정 (한국 시간 기준)
        import datetime
        current_hour = datetime.datetime.now().hour
        
        time_reliability = 1.0
        # 새벽 시간대 (변동성 높지만 신뢰도 낮음)
        if 2 <= current_hour <= 6:
            time_reliability = 0.85
        # 오전 시간대 (높은 신뢰도)
        elif 9 <= current_hour <= 11:
            time_reliability = 1.15
        # 오후 시간대 (보통 신뢰도)
        elif 14 <= current_hour <= 16:
            time_reliability = 1.05
        # 저녁 시간대 (높은 변동성)
        elif 20 <= current_hour <= 23:
            time_reliability = 0.95
        
        total_score *= time_reliability
        
        # === 최종 신호 강도 보정 ===
        
        # 확신도가 높은 경우 추가 보정
        if signal_strength >= 1.3 and volume_validation and pattern_consistency:
            if total_score > 0:
                total_score *= 1.1  # 강한 매수 신호 더 강화
            else:
                total_score *= 1.2  # 강한 매도 신호 더 강화
        
        # 확신도가 낮거나 검증 실패 시 보정
        elif signal_strength <= 0.8 or not volume_validation or not pattern_consistency:
            total_score *= 0.75  # 신호 약화
        
        # === 예측 결과 결정 (최적화된 임계값) ===
        
        # 점수 범위 제한
        total_score = max(-5.0, min(5.0, total_score))
        
        if total_score >= surge_threshold:
            prediction = 'SURGE'
        elif total_score >= up_threshold:
            prediction = 'UP'
        elif total_score <= crash_threshold:
            prediction = 'CRASH'
        elif total_score <= down_threshold:
            prediction = 'DOWN'
        else:
            prediction = 'NEUTRAL'
        
        # === 추가 안전장치 ===
        
        # 급락 위험이나 지지선 붕괴 시 강제 하향 조정
        if crash_risk_detected or support_broken:
            if prediction in ['SURGE', 'UP']:
                prediction = 'DOWN'
                total_score = min(total_score, down_threshold - 0.1)
        
        # 극단적 거래량 감소 시 중립화
        if len(volumes) >= 5:
            recent_vol = volumes[-2:].mean()
            baseline_vol = volumes[-10:-2].mean()
            if baseline_vol > 0 and recent_vol / baseline_vol < 0.3:  # 70% 거래량 감소
                if prediction in ['SURGE', 'UP']:
                    prediction = 'NEUTRAL'
                    total_score = 0
        
        return prediction, round(total_score, 2)
    
    except Exception as e:
        print(f"[predict_price_direction] {ticker} 예측 오류: {e}")
        return 'NEUTRAL', 0

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

def get_smart_band_margin(ticker, market_rsi):
    """
    기회 포착 우선 스마트 밴드마진 계산 (실제 매수 실행 최적화)
    
    핵심 철학 변경:
    1. 완벽한 신호 대기 → 괜찮은 기회 즉시 포착
    2. 과도한 필터링 → 적응형 조건 완화
    3. 실패 회피 중심 → 기회 창출 중심
    4. 2% 수익 목표에 맞는 현실적 접근
    
    Parameters:
    - ticker: 대상 티커
    - market_rsi: 현재 시장 RSI
    
    Returns:
    - float: 실행 가능한 최적 밴드마진 값
    """
    
    default_margin = 0.02
    
    try:
        print(f"🎯 {ticker} 기회포착 우선 분석...")
        
        # 데이터 수집 (분석 속도 vs 정확도 균형)
        total_needed = 200
        df = pyupbit.get_ohlcv(ticker, interval="minute5", count=total_needed)
        if df is None or len(df) < 50:
            print(f"❌ {ticker}: 데이터 부족 - 기본 마진 사용")
            return default_margin * 0.8  # 데이터 부족시에도 기회 제공
            
        close_prices = df['close'].values.astype(float)
        high_prices = df['high'].values.astype(float)
        low_prices = df['low'].values.astype(float)
        volumes = df['volume'].values.astype(float)
        
        # === 1. 시장 상황 사전 분석 (조건 완화 수준 결정) ===
        def assess_market_opportunity_level(market_rsi, prices):
            """시장 상황에 따른 기회 포착 적극성 결정"""
            opportunity_level = "normal"  # normal, aggressive, conservative
            
            # 극도 침체 시장 → 적극적 기회 포착
            if market_rsi < 30:
                opportunity_level = "aggressive"
            # 과매수 시장 → 보수적 접근
            elif market_rsi > 70:
                opportunity_level = "conservative" 
            
            # 가격 추세 확인 (추가 조정)
            if len(prices) >= 50:
                recent_trend = (prices[-1] - prices[-50]) / prices[-50]
                if recent_trend < -0.1:  # 10% 이상 하락 추세
                    if opportunity_level == "normal":
                        opportunity_level = "aggressive"
                elif recent_trend > 0.1:  # 10% 이상 상승 추세
                    if opportunity_level == "normal":
                        opportunity_level = "conservative"
            
            return opportunity_level
        
        market_opportunity = assess_market_opportunity_level(market_rsi, close_prices)
        
        # === 2. 간소화된 볼린저 밴드 분석 ===
        band_data = []
        for i in range(20, len(close_prices)):
            recent_prices = close_prices[i-19:i+1]
            current_price = close_prices[i]
            
            sma = float(recent_prices.mean())
            std = float(recent_prices.std())
            
            upper_band = sma + (2.0 * std)
            lower_band = sma - (2.0 * std)
            
            band_width = (upper_band - lower_band) / current_price
            bb_position = (current_price - lower_band) / (upper_band - lower_band) if upper_band != lower_band else 0.5
            
            # 진짜 변동성 (실제 고저 범위)
            recent_high = max(high_prices[i-19:i+1])
            recent_low = min(low_prices[i-19:i+1])
            true_volatility = (recent_high - recent_low) / current_price
            
            band_data.append({
                'width': band_width,
                'position': bb_position,
                'true_vol': true_volatility,
                'price': current_price
            })
        
        if len(band_data) < 30:
            print(f"⚠️ {ticker}: 밴드 데이터 부족 - 기본값 적용")
            return default_margin
        
        # === 3. 기회 포착 신호 점수 (기존 대비 단순화) ===
        opportunity_score = 0
        signal_factors = []
        
        current_data = band_data[-1]
        recent_data = band_data[-20:]  # 최근 20개
        
        # A. 볼린저 밴드 포지션 (가장 중요, 관대한 기준)
        if current_data['position'] < 0.4:  # 기존 0.3 → 0.4로 완화
            if current_data['position'] < 0.2:
                opportunity_score += 4  # 매우 좋은 위치
                signal_factors.append(f"극하단{current_data['position']:.2f}")
            else:
                opportunity_score += 3  # 좋은 위치
                signal_factors.append(f"하단{current_data['position']:.2f}")
        elif current_data['position'] < 0.6:  # 중간 위치도 일부 허용
            opportunity_score += 1
            signal_factors.append(f"중하단{current_data['position']:.2f}")
        
        # B. 밴드 폭 적정성 (기준 완화)
        current_width = current_data['width']
        if current_width > 0.01:  # 기존 0.015 → 0.01로 완화
            if current_width > 0.02:
                opportunity_score += 2
                signal_factors.append(f"넓은폭{current_width:.3f}")
            else:
                opportunity_score += 1
                signal_factors.append(f"적정폭{current_width:.3f}")
        
        # C. 변동성 추세 (단순화)
        if len(recent_data) >= 15:
            old_widths = [d['width'] for d in recent_data[:10]]
            new_widths = [d['width'] for d in recent_data[-10:]]
            
            old_avg = sum(old_widths) / len(old_widths)
            new_avg = sum(new_widths) / len(new_widths)
            
            width_trend = (new_avg - old_avg) / old_avg if old_avg > 0 else 0
            
            # 확장 또는 안정화 둘 다 허용
            if width_trend > 0.05:  # 확장 중
                opportunity_score += 2
                signal_factors.append("확장중")
            elif abs(width_trend) < 0.05:  # 안정화
                opportunity_score += 1
                signal_factors.append("안정화")
        
        # D. RSI 조건 (관대하게)
        def calculate_simple_rsi(prices, period=14):
            if len(prices) < period + 1:
                return 50.0
            
            gains = []
            losses = []
            for i in range(1, len(prices)):
                diff = prices[i] - prices[i-1]
                gains.append(max(diff, 0))
                losses.append(max(-diff, 0))
            
            if len(gains) < period:
                return 50.0
            
            avg_gain = sum(gains[-period:]) / period
            avg_loss = sum(losses[-period:]) / period
            
            if avg_loss == 0:
                return 100.0
            
            rs = avg_gain / avg_loss
            return 100 - (100 / (1 + rs))
        
        rsi = calculate_simple_rsi(close_prices.tolist())
        
        if rsi < 35:  # 기존 30 → 35로 완화
            opportunity_score += 3
            signal_factors.append(f"과매도{rsi:.0f}")
        elif rsi < 50:  # 중립도 일부 점수
            opportunity_score += 1
            signal_factors.append(f"약세{rsi:.0f}")
        
        # E. 거래량 (선택적 보너스)
        if len(volumes) >= 20:
            recent_vol = sum(volumes[-10:]) / 10
            old_vol = sum(volumes[-20:-10]) / 10
            vol_ratio = recent_vol / old_vol if old_vol > 0 else 1
            
            if vol_ratio > 1.2:  # 거래량 증가
                opportunity_score += 1
                signal_factors.append(f"거래량{vol_ratio:.1f}")
        
        # === 4. 시장 기회 수준별 점수 조정 ===
        if market_opportunity == "aggressive":
            # 적극적 시장에서는 낮은 점수도 허용
            opportunity_score = int(opportunity_score * 1.5)  # 점수 증폭
            bonus_msg = "적극모드"
        elif market_opportunity == "conservative":
            # 보수적 시장에서는 높은 점수만 허용  
            opportunity_score = int(opportunity_score * 0.7)  # 점수 감소
            bonus_msg = "보수모드"
        else:
            bonus_msg = "일반모드"
        
        signal_factors.append(bonus_msg)
        
        # === 5. 과거 성공 패턴 간소 분석 ===
        success_margin_candidates = []
        
        # 최근 60개 구간에서 성공 사례 찾기 (기간 단축)
        for i in range(30, len(band_data) - 10):
            if i + 10 < len(close_prices):
                past_width = band_data[i]['width']
                past_position = band_data[i]['position']
                
                # 10캔들 후 수익률
                future_return = (close_prices[i + 30] - close_prices[i + 20]) / close_prices[i + 20]
                
                # 성공 조건 완화: 1% 이상 수익 (기존 2%)
                if future_return > 0.01:
                    # 현재와 유사한 조건
                    width_similar = abs(past_width - current_width) / current_width < 0.5
                    position_similar = abs(past_position - current_data['position']) < 0.3
                    
                    if width_similar and position_similar:
                        success_margin_candidates.append(past_width)
        
        # 베이스 마진 결정
        if success_margin_candidates:
            success_margin_candidates.sort()
            # 더 공격적: 40 percentile 사용 (기존 25 percentile)
            idx = min(int(len(success_margin_candidates) * 0.4), len(success_margin_candidates) - 1)
            base_margin = success_margin_candidates[idx]
            base_margin = max(0.008, min(base_margin, 0.035))  # 범위 확대
        else:
            base_margin = 0.018  # 기존 0.015 → 0.018 (더 관대)
        
        # === 6. 점수별 마진 배수 (기회 중심으로 재조정) ===
        if opportunity_score >= 8:
            margin_multiplier = 0.7  # 매우 공격적
            signal_strength = "매우강함"
        elif opportunity_score >= 6:
            margin_multiplier = 0.85  # 공격적
            signal_strength = "강함"
        elif opportunity_score >= 4:
            margin_multiplier = 1.0   # 표준
            signal_strength = "보통"
        elif opportunity_score >= 2:
            margin_multiplier = 1.2   # 약간 보수적 (기존 1.7에서 완화)
            signal_strength = "약함"
        else:
            margin_multiplier = 1.5   # 보수적 (기존 2.5에서 대폭 완화)
            signal_strength = "최약"
        
        # === 7. 시장 환경 조정 (완화) ===
        if market_rsi < 30:
            market_multiplier = 1.3  # 기존 1.5 → 1.3
        elif market_rsi < 40:
            market_multiplier = 1.1  # 기존 1.3 → 1.1  
        elif market_rsi > 75:
            market_multiplier = 0.8  # 기존 0.7 → 0.8
        elif market_rsi > 65:
            market_multiplier = 0.9  # 기존 0.85 → 0.9
        else:
            market_multiplier = 1.0
        
        # === 8. 최종 계산 및 기회 보장 시스템 ===
        calculated_margin = base_margin * margin_multiplier * market_multiplier
        
        # 절대 최소값 보장 (매수 기회 확보)
        if calculated_margin > 0.06:  # 너무 큰 마진은 제한
            calculated_margin = 0.06
        elif calculated_margin < 0.01:  # 너무 작은 마진도 제한  
            calculated_margin = 0.01
        
        # === 9. 긴급 기회 포착 모드 ===
        # 매우 좋은 조건이면 추가 완화
        emergency_conditions = (
            current_data['position'] < 0.15 and  # 극하단
            rsi < 25 and  # 극과매도
            current_width > 0.015  # 적정 밴드폭
        )
        
        if emergency_conditions:
            calculated_margin *= 0.8  # 20% 추가 할인
            signal_factors.append("긴급포착")
        
        # === 10. 결과 출력 및 반환 ===
        print(f"🎯 {ticker} 기회포착 결과:")
        print(f"  🌍 시장기회: {market_opportunity} (시장RSI: {market_rsi})")
        print(f"  🎪 BB포지션: {current_data['position']:.3f}")
        print(f"  📏 밴드폭: {current_width:.4f}")
        print(f"  📊 RSI: {rsi:.1f}")
        print(f"  🏆 기회점수: {opportunity_score}/12 ({', '.join(signal_factors)})")
        print(f"  💡 신호강도: {signal_strength}")
        print(f"  📐 베이스마진: {base_margin:.4f}")
        print(f"  ⚖️ 신호배수: {margin_multiplier:.2f}")
        print(f"  🌍 시장배수: {market_multiplier:.2f}")
        print(f"  💰 최종마진: {calculated_margin:.4f}")
        
        # 매수 가능성 표시
        if opportunity_score >= 2:
            print(f"  ✅ 매수 가능 (점수 {opportunity_score})")
        else:
            print(f"  ⚠️ 매수 주의 (점수 {opportunity_score})")
        
        return calculated_margin
        
    except Exception as e:
        print(f"❌ {ticker} 기회포착 분석 오류: {str(e)}")
        import traceback
        print(f"상세: {traceback.format_exc()}")
        # 에러 시에도 기회 제공
        return default_margin * 0.9
    
def filtered_tickers(tickers):
    """개선된 조건에 맞는 티커 필터링 - 계층적 기회 포착 시스템"""
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
    
    # ✨ 새로운 적응형 시장 상태 분석 ✨
    # 시장 변동성 측정 (RSI 표준편차로 시장 불안정도 측정)
    market_volatility = np.std(market_rsi_data) if len(market_rsi_data) > 5 else 10
    
    # 🎯 계층적 기준점 시스템 - 3단계 기회 포착
    if market_rsi < 25:
        market_status = "극과매도(황금기회)"
        strategy_note = "패닉셀링-적극포착"
        buy_aggression = 1.0
        opportunity_multiplier = 2.0
        # 3단계 기준점
        perfect_threshold = 130    # 완벽한 기회
        good_threshold = 110       # 우수한 기회  
        decent_threshold = 90      # 괜찮은 기회
        
    elif market_rsi < 35:
        market_status = "과매도(프리미엄기회)"  
        strategy_note = "하락끝-다단계포착"
        buy_aggression = 0.9
        opportunity_multiplier = 1.7
        perfect_threshold = 140
        good_threshold = 120
        decent_threshold = 100
        
    elif market_rsi < 45:
        market_status = "약과매도(선별기회)"
        strategy_note = "조정구간-균형포착"
        buy_aggression = 0.7
        opportunity_multiplier = 1.3
        perfect_threshold = 150
        good_threshold = 130
        decent_threshold = 110
        
    elif market_rsi > 75:
        market_status = "극과매수(최고급만)"
        strategy_note = "과열-완벽조건만"
        buy_aggression = 0.3
        opportunity_multiplier = 0.6
        perfect_threshold = 180
        good_threshold = 160  # 여전히 높음
        decent_threshold = 140
        
    elif market_rsi > 65:
        market_status = "과매수(엄선매수)"
        strategy_note = "상승중-신중포착"
        buy_aggression = 0.5
        opportunity_multiplier = 0.8
        perfect_threshold = 160
        good_threshold = 140
        decent_threshold = 120
        
    elif market_rsi > 55:
        market_status = "강세중립(균형매수)"
        strategy_note = "상승추세-균형포착"
        buy_aggression = 0.7
        opportunity_multiplier = 1.1
        perfect_threshold = 150
        good_threshold = 130
        decent_threshold = 110
        
    else:
        market_status = "중립(표준매수)"
        strategy_note = "안정구간-표준포착"
        buy_aggression = 0.6
        opportunity_multiplier = 1.0
        perfect_threshold = 155
        good_threshold = 135
        decent_threshold = 115
    
    # 변동성에 따른 조정
    if market_volatility > 15:  # 고변동성 시장
        buy_aggression *= 0.9
        volatility_note = "고변동성-신중"
        # 기회는 더 많지만 기준은 약간 높여서 안전성 확보
        perfect_threshold += 5
        good_threshold += 5
        decent_threshold += 5
    elif market_volatility < 5:  # 저변동성 시장  
        buy_aggression *= 1.1
        volatility_note = "저변동성-적극"
        # 기회가 적으니 기준을 낮춰서 기회 확보
        perfect_threshold -= 10
        good_threshold -= 10  
        decent_threshold -= 10
    else:
        volatility_note = "정상변동성"
    
    print(f"🌍 시장심리: RSI {market_rsi:.1f} ({market_status}) | {strategy_note}")
    print(f"📊 변동성: {market_volatility:.1f} ({volatility_note})")
    print(f"🎯 기준점: 완벽{perfect_threshold} | 우수{good_threshold} | 괜찮음{decent_threshold}")
    
    # === 개별 코인 분석 ===
    prediction_summary = {'SURGE': 0, 'UP': 0, 'DOWN': 0, 'CRASH': 0, 'NEUTRAL': 0}
    all_candidates = []  # 모든 후보를 저장해서 나중에 분석
    
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
            
            # ✨ 시장 상황별 볼린저 밴드 최적화 ✨
            if market_rsi < 30:
                bb_window, bb_std = 12, 1.6
            elif market_rsi > 70:
                bb_window, bb_std = 30, 2.2
            else:
                bb_window, bb_std = 20, 2.0
            
            bands_df = get_bollinger_bands(t, interval=min5, window=bb_window, std_dev=bb_std)
            upper_band = bands_df['Upper_Band'].values[-1]
            lower_band = bands_df['Lower_Band'].values[-1]
            middle_band = (upper_band + lower_band) / 2
            band_diff_ratio = (upper_band - lower_band) / lower_band
            
            # RSI 계산
            ta_rsi = get_rsi(t, 14, interval=min5)
            rsi_values = ta_rsi.values
            current_rsi = rsi_values[-1]
            
            # 🎯 **계층적 조건 체계** 🎯
            
            # === 기본 지표 계산 (3단계에서 공통 사용) ===
            
            # 1. 밴드 조건들
            base_margin = optimized_band_margin * (1.5 - buy_aggression * 0.2)
            is_band_expanding = band_diff_ratio > base_margin
            is_near_middle_band = abs(current_price - middle_band) / middle_band < 0.02
            is_perfect_band_position = abs(current_price - middle_band) / middle_band < 0.015
            
            # 2. RSI 조건들  
            base_rsi_s, base_rsi_e = rsi_buy_s, rsi_buy_e
            if market_rsi < 35:
                adjusted_rsi_s = base_rsi_s * 0.9
                adjusted_rsi_e = base_rsi_e * 1.1
            elif market_rsi > 65:
                adjusted_rsi_s = base_rsi_s * 1.05
                adjusted_rsi_e = base_rsi_e * 0.95
            else:
                adjusted_rsi_s = base_rsi_s * 0.95
                adjusted_rsi_e = base_rsi_e * 1.05
                
            is_rsi_good = adjusted_rsi_s < current_rsi < adjusted_rsi_e
            is_rsi_perfect = adjusted_rsi_s * 1.05 < current_rsi < adjusted_rsi_e * 0.95  # 더 엄격
            
            rsi_momentum = len(rsi_values) >= 3 and rsi_values[-1] > rsi_values[-2] >= rsi_values[-3]
            rsi_momentum_strong = len(rsi_values) >= 5 and all(rsi_values[-i] >= rsi_values[-i-1] for i in range(1, 4))
            
            # 3. 다이버전스
            divergence_result = get_rsi_bul_diver(t)
            has_divergence = divergence_result['is_bullish_divergence']
            
            # 4. 볼린저 밴드 위치
            bb_position = (current_price - lower_band) / (upper_band - lower_band)
            is_good_position = bb_position < 0.4 + (0.15 * buy_aggression)
            is_perfect_position = bb_position < 0.25 + (0.1 * buy_aggression)
            is_near_lower_band = bb_position < 0.2
            
            # 5. 모멘텀 지표들
            price_change_5min = (current_price - closes[-2]) / closes[-2]
            price_change_15min = (current_price - closes[-4]) / closes[-4]
            
            is_momentum_ok = price_change_5min > -0.01
            is_momentum_good = price_change_5min > -0.005 and price_change_15min > -0.01
            is_momentum_perfect = price_change_5min > -0.003 and price_change_15min > -0.005
            
            # 6. 캔들 패턴
            recent_3_candles = closes[-3:]
            recent_5_candles = closes[-5:]
            is_pattern_ok = recent_3_candles[-1] >= recent_3_candles[-3] * 0.995
            is_pattern_good = (recent_5_candles[-1] >= recent_5_candles[-3] and 
                              recent_5_candles[-2] >= recent_5_candles[-4])
            is_pattern_perfect = (recent_5_candles[-1] >= recent_5_candles[-3] and 
                                recent_5_candles[-2] >= recent_5_candles[-4] and
                                recent_5_candles[-1] >= recent_5_candles[-5] * 0.998)
            
            # 7. 거래량 지표들
            vol_ma3 = volumes[-3:].mean()
            vol_ma10 = volumes[-10:].mean()
            vol_ma20 = volumes[-20:].mean()
            
            is_volume_ok = vol_ma3 > vol_ma10 * 1.03
            is_volume_good = vol_ma3 > vol_ma10 * (1.08 + buy_aggression * 0.05) and vol_ma10 > vol_ma20 * 1.02
            is_volume_perfect = vol_ma3 > vol_ma10 * (1.15 + buy_aggression * 0.1) and vol_ma10 > vol_ma20 * 1.05
            
            # 8. 트렌드 지표들
            price_sma5 = closes[-5:].mean()
            price_sma10 = closes[-10:].mean()
            price_sma20 = closes[-20:].mean()
            
            trend_ok = current_price > price_sma5 * (0.98 - buy_aggression * 0.01)
            trend_good = (current_price > price_sma5 * (0.99 - buy_aggression * 0.005) and 
                         price_sma5 > price_sma10 * (0.98 - buy_aggression * 0.01))
            trend_perfect = (current_price > price_sma5 * (0.995 - buy_aggression * 0.005) and
                           price_sma5 > price_sma10 * (0.995 - buy_aggression * 0.005) and
                           price_sma10 > price_sma20 * 0.998)
            
            # 9. 변동성과 바운스
            recent_range = (highs[-5:].max() - lows[-5:].min()) / closes[-5:].mean()
            recent_low = lows[-10:].min()
            
            volatility_ok = 0.01 < recent_range < (0.2 + buy_aggression * 0.05)
            volatility_good = 0.015 < recent_range < (0.12 + buy_aggression * 0.03)
            volatility_perfect = 0.015 < recent_range < (0.08 + buy_aggression * 0.03)
            
            bounce_ok = current_price > recent_low * (1.003 - buy_aggression * 0.001)
            bounce_good = current_price > recent_low * (1.007 - buy_aggression * 0.002)
            bounce_perfect = current_price > recent_low * (1.01 - buy_aggression * 0.002)
            
            # === 예측 시스템 ===
            prediction, prediction_score = predict_price_direction(t)
            prediction_summary[prediction] += 1
            
            # 🎯 **3단계 점수 계산 시스템** 🎯
            
            # === 레벨 1: 완벽한 기회 점수 (0~300점) ===
            perfect_core_score = 0
            if is_band_expanding and is_perfect_band_position: perfect_core_score += 50
            if is_rsi_perfect and rsi_momentum_strong: perfect_core_score += 40
            if is_perfect_position and is_near_lower_band: perfect_core_score += 35
            if has_divergence: perfect_core_score += 75
            
            perfect_tech_score = 0
            if is_momentum_perfect: perfect_tech_score += 25
            if is_pattern_perfect: perfect_tech_score += 20
            if is_volume_perfect: perfect_tech_score += 30
            if trend_perfect: perfect_tech_score += 35
            if volatility_perfect and bounce_perfect: perfect_tech_score += 40
            
            # === 레벨 2: 우수한 기회 점수 (0~250점) ===
            good_core_score = 0
            if is_band_expanding and (is_perfect_band_position or is_near_middle_band): good_core_score += 45
            if is_rsi_good and (rsi_momentum_strong or rsi_momentum): good_core_score += 35
            if is_good_position: good_core_score += 30
            if has_divergence: good_core_score += 60
            
            good_tech_score = 0
            if is_momentum_good: good_tech_score += 20
            if is_pattern_good: good_tech_score += 15
            if is_volume_good: good_tech_score += 25
            if trend_good: good_tech_score += 30
            if volatility_good and bounce_good: good_tech_score += 30
            
            # === 레벨 3: 괜찮은 기회 점수 (0~200점) ===
            decent_core_score = 0
            if (is_band_expanding or is_near_middle_band): decent_core_score += 35
            if is_rsi_good or (rsi_momentum and 25 < current_rsi < 75): decent_core_score += 30
            if is_good_position or is_near_lower_band: decent_core_score += 25
            if has_divergence: decent_core_score += 50  # 다이버전스는 항상 중요
            
            decent_tech_score = 0
            if is_momentum_ok: decent_tech_score += 15
            if is_pattern_ok: decent_tech_score += 12
            if is_volume_ok: decent_tech_score += 18
            if trend_ok: decent_tech_score += 20
            if volatility_ok and bounce_ok: decent_tech_score += 25
            
            # === 예측 점수 (공통) ===
            prediction_bonus = 0
            if prediction == 'SURGE': prediction_bonus = 40
            elif prediction == 'UP': prediction_bonus = 20
            elif prediction == 'NEUTRAL': prediction_bonus = 5
            elif prediction == 'DOWN': prediction_bonus = -15
            elif prediction == 'CRASH': prediction_bonus = -30
            
            # === 시장 보정 (공통) ===
            market_bonus = 0
            if market_rsi < 30 and prediction in ['SURGE', 'UP']:
                market_bonus = 25
            elif market_rsi < 35 and prediction == 'SURGE':
                market_bonus = 15
            elif market_rsi > 70 and prediction not in ['SURGE', 'UP']:
                market_bonus = -15
            
            # 최종 점수 계산
            perfect_final_score = (perfect_core_score + perfect_tech_score + prediction_bonus + market_bonus) * opportunity_multiplier
            good_final_score = (good_core_score + good_tech_score + prediction_bonus + market_bonus) * opportunity_multiplier  
            decent_final_score = (decent_core_score + decent_tech_score + prediction_bonus + market_bonus) * opportunity_multiplier
            
            # 🎯 **계층적 기회 판정** 🎯
            filteringTime = datetime.now().strftime('%m/%d %H시%M분%S초')
            
            buy_decision = False
            buy_tier = ""
            buy_reason = ""
            final_score = 0
            
            # 🏆 1순위: 완벽한 기회 검증
            if perfect_final_score >= perfect_threshold:
                # 추가 완벽성 검증
                perfect_conditions = [
                    is_band_expanding and is_perfect_band_position,
                    is_rsi_perfect or (is_rsi_good and rsi_momentum_strong),
                    is_perfect_position,
                    prediction in ['SURGE', 'UP']
                ]
                
                if sum(perfect_conditions) >= 3:  # 4개 중 3개 이상
                    buy_decision = True
                    buy_tier = "🏆 PERFECT"
                    buy_reason = "완벽한 조건 충족"
                    final_score = perfect_final_score
            
            # 🥇 2순위: 우수한 기회 검증 (완벽한 기회가 없을 때)
            if not buy_decision and good_final_score >= good_threshold:
                good_conditions = [
                    is_band_expanding,
                    is_rsi_good,
                    is_good_position or is_near_lower_band,
                    has_divergence,
                    prediction != 'CRASH',
                    is_volume_good or trend_good
                ]
                
                if sum(good_conditions) >= 4:  # 6개 중 4개 이상
                    buy_decision = True
                    buy_tier = "🥇 GOOD"
                    buy_reason = "우수한 조건 충족" 
                    final_score = good_final_score
            
            # 🥈 3순위: 괜찮은 기회 검증 (앞의 두 기회가 없고, 공격적 시장일 때)
            if not buy_decision and decent_final_score >= decent_threshold and buy_aggression >= 0.6:
                decent_conditions = [
                    is_band_expanding or is_near_middle_band,
                    is_rsi_good or rsi_momentum,
                    is_good_position or bb_position < 0.5,
                    prediction not in ['DOWN', 'CRASH'],
                    is_momentum_ok,
                    trend_ok
                ]
                
                if sum(decent_conditions) >= 4:  # 6개 중 4개 이상
                    buy_decision = True
                    buy_tier = "🥈 DECENT"
                    buy_reason = "괜찮은 조건 충족"
                    final_score = decent_final_score
            
            # 🔥 보너스: 특수 상황 (극과매도 + 다이버전스)
            if (not buy_decision and market_rsi < 25 and has_divergence and 
                prediction != 'CRASH' and bounce_good):
                buy_decision = True
                buy_tier = "🔥 SPECIAL"
                buy_reason = "극과매도+다이버전스 특수조건"
                final_score = max(perfect_final_score, good_final_score, decent_final_score)
            
            # 결과 저장
            candidate_info = {
                'ticker': t,
                'perfect_score': perfect_final_score,
                'good_score': good_final_score,
                'decent_score': decent_final_score,
                'final_score': final_score,
                'buy_decision': buy_decision,
                'buy_tier': buy_tier,
                'buy_reason': buy_reason,
                'prediction': prediction,
                'has_divergence': has_divergence,
                'current_rsi': current_rsi,
                'bb_position': bb_position,
                'market_rsi': market_rsi
            }
            
            all_candidates.append(candidate_info)
            
            # 매수 결정 처리
            if buy_decision:
                # 상세 정보는 터미널에만 출력
                filtering_message = f"<<[{filteringTime}] {t}>>\n"
                filtering_message += f"[등급] {buy_tier} | {buy_reason}\n"
                filtering_message += f"[점수] 완벽:{perfect_final_score:.0f} | 우수:{good_final_score:.0f} | 괜찮음:{decent_final_score:.0f}\n"
                filtering_message += f"[조건] RSI:{current_rsi:.1f} | 위치:{bb_position:.1%} | 예측:{prediction} | 다이버전스:{has_divergence}\n"
                filtering_message += f"[기준] 완벽{perfect_threshold} | 우수{good_threshold} | 괜찮음{decent_threshold}"
                
                # 터미널 출력
                print(f"✅ **{buy_tier} 기회 선정**: {t} - {buy_reason} (점수: {final_score:.0f})")
                print(filtering_message)
                print("-" * 80)
                
                # 디스코드는 나중에 한번에 전송
                emergency_selected += 1
            else:
                # 높은 점수지만 매수하지 않은 경우
                max_score = max(perfect_final_score, good_final_score, decent_final_score)
                if max_score >= decent_threshold * 0.8:
                    print(f"⏳ 아쉬운 기회: {t} (최고점수:{max_score:.0f}) - 조건 부족")

        except Exception as e:
            send_discord_message(f"[ERROR] {t}: {str(e)[:100]}")
            print(f"❌ 분석 오류: {t} - {str(e)[:100]}")
            time.sleep(2)

    # === 🎯 적응형 기회 확보 시스템 ===
    
    total_analyzed = len(tickers)
    total_selected = len(filtered_tickers)
    
    # 매수 기회가 너무 적을 때 기준 완화
    if total_selected == 0 and total_analyzed >= 10:
        print("🔄 **기회 부족 감지** - 기준 재조정 중...")
        
        # 가장 높은 점수들 재검토
        all_candidates.sort(key=lambda x: max(x['perfect_score'], x['good_score'], x['decent_score']), reverse=True)
        
        emergency_threshold = decent_threshold * 0.85  # 15% 완화
        emergency_selected = 0
        
        for candidate in all_candidates[:3]:  # 상위 3개만 재검토
            if emergency_selected >= 1:  # 최대 1개까지만
                break
                
            t = candidate['ticker']
            max_score = max(candidate['perfect_score'], candidate['good_score'], candidate['decent_score'])
            
            if (max_score >= emergency_threshold and 
                candidate['prediction'] not in ['DOWN', 'CRASH'] and
                candidate['current_rsi'] < 70):
                
                emergency_message = f"🚨 **긴급 기회 포착**: {t}\n"
                emergency_message += f"[점수] {max_score:.0f} (완화기준: {emergency_threshold:.0f})\n"
                emergency_message += f"[조건] RSI:{candidate['current_rsi']:.1f} | 예측:{candidate['prediction']}"
                emergency_message += f" | 다이버전스:{candidate['has_divergence']}\n"
                emergency_message += f"[사유] 기회부족으로 기준 15% 완화 적용"
                
                # 터미널 출력
                print(f"🚨 긴급 기회 확보: {t} (점수: {max_score:.0f})")
                print(emergency_message)
                print("-" * 80)
                
                # 디스코드는 나중에 한번에 전송
                filtered_tickers.append(t)
        
        total_selected = len(filtered_tickers)
    
    # === 결과 요약 ===
    selection_rate = (total_selected / total_analyzed * 100) if total_analyzed > 0 else 0
    
    # 등급별 분포 계산 및 상세 정보 수집
    tier_distribution = {'PERFECT': 0, 'GOOD': 0, 'DECENT': 0, 'SPECIAL': 0}
    selected_details = []  # 선정된 코인들의 상세 정보
    
    for candidate in all_candidates:
        if candidate['buy_decision']:
            tier = candidate['buy_tier'].split()[1] if ' ' in candidate['buy_tier'] else 'OTHER'
            if tier in tier_distribution:
                tier_distribution[tier] += 1
            
            # 선정된 코인의 상세 정보 저장
            detail_info = {
                'ticker': candidate['ticker'],
                'tier': candidate['buy_tier'],
                'reason': candidate['buy_reason'],
                'final_score': candidate['final_score'],
                'prediction': candidate['prediction'],
                'rsi': candidate['current_rsi'],
                'bb_position': candidate['bb_position'],
                'has_divergence': candidate['has_divergence']
            }
            selected_details.append(detail_info)
    
    # 터미널 요약 출력
    summary_msg = f"🎯 **계층적 기회 분석 완료**: {total_analyzed}개 → {total_selected}개 선정 ({selection_rate:.1f}%)"
    summary_msg += f"\n📊 **등급별 선정**: 완벽{tier_distribution['PERFECT']} | 우수{tier_distribution['GOOD']} | 괜찮음{tier_distribution['DECENT']} | 특수{tier_distribution['SPECIAL']}"
    summary_msg += f"\n🔮 **예측 분포**: 급상승{prediction_summary['SURGE']} | 상승{prediction_summary['UP']} | 중립{prediction_summary['NEUTRAL']} | 하락{prediction_summary['DOWN']} | 폭락{prediction_summary['CRASH']}"
    summary_msg += f"\n⚡ **시장환경**: {market_status} | 기준점: 완벽{perfect_threshold}/우수{good_threshold}/괜찮음{decent_threshold}"
    
    print("=" * 100)
    print(summary_msg)
    
    if total_selected > 0:
        # 🎯 디스코드에는 최종 선정 결과만 간단하게 전송
        discord_msg = f"🎉 **매수 기회 {total_selected}개 발견!**\n"
        discord_msg += f"📊 시장: {market_status} | 분석: {total_analyzed}개\n\n"
        
        for detail in selected_details:
            discord_msg += f"**{detail['ticker']}** {detail['tier']}\n"
            discord_msg += f"├ 점수: {detail['final_score']:.0f}점 | 예측: {detail['prediction']}\n"
            discord_msg += f"├ RSI: {detail['rsi']:.1f} | 위치: {detail['bb_position']:.1%}\n"
            discord_msg += f"└ 다이버전스: {'✅' if detail['has_divergence'] else '❌'}\n\n"
        
        discord_msg += f"⏰ {datetime.now().strftime('%m/%d %H:%M:%S')} 분석완료"
        
        send_discord_message(discord_msg)
        print(f"🎉 계층적 기회 확보 성공!")
        print("📱 디스코드 최종 결과 전송 완료")
        
    else:
        # 최고 점수라도 보고
        if all_candidates:
            all_candidates.sort(key=lambda x: max(x['perfect_score'], x['good_score'], x['decent_score']), reverse=True)
            best_candidate = all_candidates[0]
            max_score = max(best_candidate['perfect_score'], best_candidate['good_score'], best_candidate['decent_score'])
            print(f"🥈 **최고점수**: {best_candidate['ticker']}({max_score:.0f}점) - 조건 미달")
        
        print(f"🔍 매수 기회 없음")
        
        # 시장 상황별 조언
        if perfect_threshold >= 160:
            print("💡 현재 높은 기준이 적용중입니다. 시장 상황이 개선되면 기회가 늘어날 것입니다.")
        elif buy_aggression < 0.5:
            print("💡 시장이 과열상태입니다. 조정 후 더 좋은 기회를 기다려보세요.")
        else:
            print("💡 계층적 시스템이 가동중입니다. 조건이 맞는 기회를 찾는 중입니다.")
        
        # 기회가 없을 때는 디스코드 메시지를 보내지 않음 (스팸 방지)
        print("📱 디스코드 메시지 생략 (기회 없음)")

    return filtered_tickers

def get_best_ticker():
    """
    Chain of Thought 기반 최적화된 암호화폐 매수 대상 선정 함수
    
    사고 흐름:
    1. 보유 코인 빠른 식별 → 2. 기준 거래량 안정적 설정 → 3. 병렬 데이터 수집
    4. 다층 필터링 (급등/저변동성 제외 강화) → 5. 기술적 분석 기반 최종 선별 → 6. 위험도 검증
    """
    
    # ========== STEP 1: 보유 코인 식별 및 초기 설정 ==========
    try:
        balances = upbit.get_balances()
        held_coins = set()  # set 사용으로 O(1) 검색 성능
        
        for b in balances:
            if float(b.get('balance', 0)) > 0:
                held_coins.add(f"KRW-{b['currency']}")
        
        print(f"[INFO] 보유 종목 {len(held_coins)}개 제외")
        
    except Exception as e:
        send_discord_message(f"잔고 조회 실패: {e}")
        return None
    
    # ========== STEP 2: 기준 거래량 설정 (평균값 기반, 실패시 최소값 적용) ==========
    reference_tickers = ["KRW-XLM", "KRW-HBAR", "KRW-ADA"]  # 안정적 거래량 기준
    reference_values = []
    
    for ref_ticker in reference_tickers:
        try:
            cri_df = pyupbit.get_ohlcv(ref_ticker, interval="day", count=1)
            if cri_df is not None and 'value' in cri_df.columns and not cri_df.empty:
                ref_value = cri_df['value'].iloc[-1]
                reference_values.append(ref_value)
                print(f"[INFO] {ref_ticker} 거래량: {ref_value:,.0f}")
            else:
                print(f"[경고] {ref_ticker} 데이터 없음")
        except Exception as e:
            print(f"[경고] {ref_ticker} 거래량 조회 실패: {e}")
            continue
    
    if len(reference_values) == 3:
        # 3개 모두 조회 성공 시 평균값 사용 (정상 케이스)
        cri_value = sum(reference_values) / len(reference_values)
        print(f"[INFO] 기준 거래량 (평균): {cri_value:,.0f} (3개 코인 기준)")
    elif len(reference_values) > 0:
        # 일부만 조회 성공 시 가장 작은 거래량 사용 (보수적 접근)
        cri_value = min(reference_values)
        print(f"[INFO] 기준 거래량 (최소값): {cri_value:,.0f} ({len(reference_values)}개 중 최소)")
    else:
        # 모두 실패 시 매우 보수적 기준값
        print("[경고] 모든 기준 코인 조회 실패 - 보수적 기준값 적용")
        cri_value = 1_500_000_000  # 15억 (매우 보수적 최소 기준)
    
    # ========== STEP 3: 전체 티커 수집 및 1차 필터링 ==========
    try:
        all_tickers = pyupbit.get_tickers(fiat="KRW")
        candidate_tickers = [t for t in all_tickers if t not in held_coins]
        
        print(f"[INFO] 분석 대상: {len(candidate_tickers)}개 종목")
        
        if len(candidate_tickers) == 0:
            print("[INFO] 분석 가능한 종목이 없습니다")
            return None
            
    except Exception as e:
        print(f"[오류] 티커 목록 조회 실패: {e}")
        send_discord_message(f"❌ 시스템 오류: 티커 목록 조회 실패")
        return None
    
    # ========== STEP 4: 배치 데이터 수집 및 강화된 다층 필터링 ==========
    filtering_tickers = []
    failed_tickers = []
    excluded_surge = []  # 급등 제외 종목
    excluded_low_vol = []  # 저변동성 제외 종목
    batch_size = 10  # API 부하 분산
    
    for i in range(0, len(candidate_tickers), batch_size):
        batch = candidate_tickers[i:i + batch_size]
        
        for ticker in batch:
            try:
                # 병렬 데이터 수집 (3일 데이터로 전일 분석 강화)
                df = pyupbit.get_ohlcv(ticker, interval="day", count=3)
                cur_price = pyupbit.get_current_price(ticker)

                time.sleep(second)

                # 데이터 검증
                if (df is None or df.empty or len(df) < 2 or cur_price is None or 
                    'open' not in df.columns or 'value' not in df.columns or
                    'high' not in df.columns or 'low' not in df.columns or
                    'close' not in df.columns):
                    failed_tickers.append(ticker)
                    continue
                
                # 데이터 추출 (최신순)
                today = df.iloc[-1]      # 오늘 (당일)
                yesterday = df.iloc[-2]  # 어제 (전일)
                prev = df.iloc[-3] if len(df) > 2 else yesterday  # 전전일
                
                today_open = today['open']
                today_high = today['high']
                today_low = today['low']
                current_value = today['value']
                
                yesterday_high = yesterday['high']
                yesterday_low = yesterday['low']
                yesterday_close = yesterday['close']
                
                # ========== 신규 필터 1: 급등 방지 (당일 시가 대비 3% 이상 상승 제외) ==========
                daily_surge_rate = ((cur_price - today_open) / today_open) * 100
                if daily_surge_rate >= 4.0:
                    excluded_surge.append(f"{ticker}({daily_surge_rate:.1f}%)")
                    print(f"[EXCLUDE-SURGE] {ticker}: 당일 급등 {daily_surge_rate:.1f}% (>5%)")
                    continue
                
                # ========== 신규 필터 2: 최소 변동성 보장 (전일 고저가 변동폭 1% 미만 제외) ==========
                if yesterday_high > 0 and yesterday_low > 0:
                    yesterday_volatility = ((yesterday_high - yesterday_low) / yesterday_low) * 100
                    if yesterday_volatility < 1.0:
                        excluded_low_vol.append(f"{ticker}({yesterday_volatility:.2f}%)")
                        print(f"[EXCLUDE-LOWVOL] {ticker}: 전일 변동폭 {yesterday_volatility:.2f}% (<1%)")
                        continue
                else:
                    # 데이터 이상 시 제외
                    failed_tickers.append(ticker)
                    continue
                
                # ========== 기존 다층 필터링 시스템 (개선) ==========
                
                # 1) 가격 범위 필터 (급등 방지 정책과 일관성 유지)
                today_volatility = (today_high - today_low) / today_open if today_open > 0 else 0
                
                # 급등 방지(3% 상한)와 일관된 범위 설정
                if today_volatility > 0.10:  # 고변동성: 하락 여유는 주되 상승은 제한
                    price_range = (0.85, 1.039)  # -15% ~ +4.9%
                elif today_volatility < 0.03:  # 저변동성: 안정적 범위
                    price_range = (0.98, 1.035)  # -2% ~ +4.5%
                else:  # 일반 변동성: 균형잡힌 범위
                    price_range = (0.92, 1.038)  # -8% ~ +4.8%
                
                price_ratio = cur_price / today_open
                price_cond = price_range[0] < price_ratio < price_range[1]
                
                # 2) 거래량 필터 (변동성 고려 동적 기준)
                volume_multiplier = 1.2 if today_volatility > 0.10 else 1.0
                value_cond = current_value > (cri_value * volume_multiplier)
                
                # 3) 추세 필터 (전일 대비 건전한 상승률 확인)
                trend_strength = (today['close'] - yesterday_close) / yesterday_close
                # 급등 제외 후 건전한 상승 범위 확장
                trend_cond = -0.08 < trend_strength < 0.08  # 건전한 변동 범위
                
                # 4) 유동성 필터 (개선)
                liquidity_score = current_value / (today_high - today_low + 0.001)
                liquidity_cond = liquidity_score > 1000000000
                
                # 5) 연속성 필터 (신규 추가 - 급격한 변동 패턴 제외)
                if len(df) > 2:
                    prev_change = (yesterday_close - prev['close']) / prev['close']
                    today_change = trend_strength
                    # 연속 급등/급락 패턴 제외
                    continuity_cond = not (abs(prev_change) > 0.05 and abs(today_change) > 0.05)
                else:
                    continuity_cond = True
                
                # ========== 통합 조건 검사 (강화) ==========
                if (price_cond and value_cond and trend_cond and 
                    liquidity_cond and continuity_cond):
                    
                    filtering_tickers.append({
                        'ticker': ticker,
                        'price_ratio': price_ratio,
                        'volume': current_value,
                        'today_volatility': today_volatility,
                        'yesterday_volatility': yesterday_volatility,
                        'trend': trend_strength,
                        'liquidity': liquidity_score,
                        'daily_surge': daily_surge_rate
                    })
                    print(f"[PASS] {ticker}: P{price_ratio:.3f}, V{current_value/1e9:.1f}B, "
                          f"당일{daily_surge_rate:+.1f}%, 전일변동{yesterday_volatility:.1f}%")
                
            except Exception as e:
                print(f"[경고] {ticker} 처리 중 오류: {e}")
                failed_tickers.append(ticker)
                continue
        
        # 배치 간 대기
        if i + batch_size < len(candidate_tickers):
            time.sleep(second * 2)
    
    # ========== 필터링 통계 출력 (개선) ==========
    print(f"\n[필터링 결과]")
    print(f"├─ 총 분석 대상: {len(candidate_tickers)}개")
    print(f"├─ 급등 제외(≥3%): {len(excluded_surge)}개")
    print(f"├─ 저변동 제외(<1%): {len(excluded_low_vol)}개")
    print(f"├─ 데이터 오류: {len(failed_tickers)}개")
    print(f"└─ 통과: {len(filtering_tickers)}개")
    
    if excluded_surge:
        print(f"[급등 제외 종목] {', '.join(excluded_surge[:5])}" + 
              (f" 외 {len(excluded_surge)-5}개" if len(excluded_surge) > 5 else ""))
    
    if excluded_low_vol:
        print(f"[저변동 제외 종목] {', '.join(excluded_low_vol[:5])}" + 
              (f" 외 {len(excluded_low_vol)-5}개" if len(excluded_low_vol) > 5 else ""))
    
    # ========== STEP 5: 필터링 결과 후처리 ==========
    if not filtering_tickers:
        print("[INFO] 조건을 만족하는 종목이 없습니다")
        return None
    
    # 추가 필터링 함수 적용 (기존 로직 유지)
    ticker_list = [item['ticker'] for item in filtering_tickers]
    filtered_list = filtered_tickers(ticker_list)
    filtered_time = datetime.now().strftime('%m/%d %H시%M분%S초')
    
    if len(filtered_list) == 0:
        print("[INFO] 최종 필터링 후 대상 종목 없음")
        return None
    
    elif len(filtered_list) == 1:
        selected_ticker = filtered_list[0]
        filtered_time = datetime.now().strftime('%m/%d %H시%M분%S초')
        send_discord_message(f"{filtered_time} [단일 선택: {selected_ticker}]")
        print(f"[SUCCESS] 단일 매수 대상: {selected_ticker}")
        return selected_ticker
    
    # ========== STEP 6: 다중 종목 중 최적 선택 (더욱 고도화된 알고리즘) ==========
    print(f"[INFO] 최종 후보: {len(filtered_list)}개 종목")
    
    best_ticker = None
    best_score = float('-inf')
    
    scoring_data = []
    
    for ticker in filtered_list:
        try:
            # RSI 계산
            ta_rsi = get_rsi(ticker, 14, interval=min5)
            if ta_rsi is None or len(ta_rsi.values) == 0:
                continue
            
            current_rsi = ta_rsi.values[-1]
            
            # 해당 ticker의 메타데이터 찾기
            ticker_meta = next((item for item in filtering_tickers if item['ticker'] == ticker), None)
            if ticker_meta is None:
                continue
            
            # ========== 강화된 복합 스코어링 시스템 ==========
            
            # 1) RSI 점수 (더 세밀한 구간 분할)
            if current_rsi < 25:
                rsi_score = 12  # 강한 과매도 보너스
            elif current_rsi < 35:
                rsi_score = 10  # 과매도 보너스
            elif current_rsi < 50:
                rsi_score = 8 - (current_rsi - 35) * 0.133
            elif current_rsi < 65:
                rsi_score = 6 - (current_rsi - 50) * 0.133
            elif current_rsi < 75:
                rsi_score = 2 - (current_rsi - 65) * 0.2
            else:
                rsi_score = -2  # 과매수 패널티
            
            # 2) 가격 위치 점수 (급등 회피 강화, 1.01 타겟)
            price_pos_score = 8 - abs(ticker_meta['price_ratio'] - 1.01) * 20  # 1% 상승 타겟
            price_pos_score = max(0, min(8, price_pos_score))
            
            # 3) 거래량 점수 (로그 스케일, 더 정교함)
            import math
            volume_score = min(5, math.log10(ticker_meta['volume'] / 1e9) * 1.2)
            volume_score = max(0, volume_score)
            
            # 4) 변동성 점수 (최적 구간 조정)
            today_vol = ticker_meta['today_volatility']
            yesterday_vol = ticker_meta['yesterday_volatility']
            
            # 오늘 변동성 점수
            if 0.04 <= today_vol <= 0.10:
                today_vol_score = 5
            elif 0.02 <= today_vol <= 0.15:
                today_vol_score = 3
            else:
                today_vol_score = 1
            
            # 어제 변동성 점수 (최소 1% 보장된 상태)
            if 0.01 <= yesterday_vol <= 0.08:
                yesterday_vol_score = 3
            elif 0.008 <= yesterday_vol <= 0.12:
                yesterday_vol_score = 2
            else:
                yesterday_vol_score = 1
            
            volatility_score = (today_vol_score * 0.7 + yesterday_vol_score * 0.3)
            
            # 5) 추세 점수 (더 보수적 접근)
            trend = ticker_meta.get('trend', 0)
            if -0.01 <= trend <= 0.03:  # 완만한 상승 선호
                trend_score = 4
            elif -0.03 <= trend <= 0.05:
                trend_score = 2
            elif -0.05 <= trend <= -0.01:  # 약간의 하락도 기회로
                trend_score = 3
            else:
                trend_score = 0
            
            # 6) 신규: 급등 방지 보너스 점수 (당일 상승률이 낮을수록 보너스)
            surge_rate = ticker_meta.get('daily_surge', 0)
            if surge_rate < -1:  # 하락 중
                surge_bonus = 2
            elif surge_rate < 0.5:  # 소폭 상승
                surge_bonus = 3
            elif surge_rate < 1.5:  # 적당한 상승
                surge_bonus = 1
            else:  # 2-3% 구간 (이미 3% 이상은 제외됨)
                surge_bonus = 0
            
            # 7) 신규: 변동성 일관성 보너스
            vol_consistency = abs(today_vol - yesterday_vol)
            if vol_consistency < 0.02:  # 일관된 변동성
                consistency_bonus = 2
            elif vol_consistency < 0.05:
                consistency_bonus = 1
            else:
                consistency_bonus = 0
            
            # ========== 가중 종합 점수 (조정) ==========
            composite_score = (
                rsi_score * 0.30 +           # RSI 가중치 30%
                price_pos_score * 0.20 +     # 가격 위치 20%
                volume_score * 0.15 +        # 거래량 15%
                volatility_score * 0.15 +    # 변동성 15%
                trend_score * 0.10 +         # 추세 10%
                surge_bonus * 0.06 +         # 급등방지 보너스 6%
                consistency_bonus * 0.04     # 일관성 보너스 4%
            )
            
            scoring_data.append({
                'ticker': ticker,
                'rsi': current_rsi,
                'composite_score': composite_score,
                'rsi_score': rsi_score,
                'price_pos_score': price_pos_score,
                'volume_score': volume_score,
                'volatility_score': volatility_score,
                'trend_score': trend_score,
                'surge_bonus': surge_bonus,
                'consistency_bonus': consistency_bonus,
                'daily_surge': surge_rate
            })
            
            # 최고 점수 갱신
            if composite_score > best_score:
                best_ticker = ticker
                best_score = composite_score
            
            print(f"[SCORE] {ticker}: RSI{current_rsi:.1f}, 당일{surge_rate:+.1f}%, 종합{composite_score:.2f}")
            
        except Exception as e:
            print(f"[경고] {ticker} 스코어링 오류: {e}")
            continue
        
        time.sleep(second)
    
    # ========== STEP 7: 최종 검증 및 리스크 체크 (강화) ==========
    if best_ticker is None:
        print("[INFO] 스코어링 완료된 종목이 없습니다")
        return None
    
    # 최고 점수 종목 상세 정보 출력
    best_data = next(item for item in scoring_data if item['ticker'] == best_ticker)
    
    # 위험도 최종 검증 (다중 조건)
    risk_flags = []
    
    if best_data['rsi'] > 75:
        risk_flags.append(f"RSI과매수({best_data['rsi']:.1f})")
    
    if best_data['daily_surge'] > 2.5:  # 3% 미만이지만 높은 상승률
        risk_flags.append(f"높은당일상승({best_data['daily_surge']:.1f}%)")
    
    # 위험 요소가 있으면 차선책 검토
    if risk_flags:
        print(f"[위험요소] {best_ticker}: {', '.join(risk_flags)}")
        
        # 차선책 선택
        sorted_candidates = sorted(scoring_data, key=lambda x: x['composite_score'], reverse=True)
        for alt in sorted_candidates[1:]:  # 2번째부터 확인
            if alt['rsi'] < 70 and alt['daily_surge'] < 2.0:
                print(f"[대안선택] {alt['ticker']} (원래 {best_ticker} 대신)")
                best_ticker = alt['ticker']
                best_data = alt
                break
    
    # 성공 메시지 (최종 결과만 디스코드 전송)
    filtered_time = datetime.now().strftime('%m/%d %H시%M분%S초')
    success_msg = (f"🎯 {filtered_time} 최종 선택: {best_ticker}\n"
                  f"📊 RSI: {best_data['rsi']:.1f} | 당일: {best_data['daily_surge']:+.1f}% | "
                  f"점수: {best_data['composite_score']:.2f}")
    
    send_discord_message(success_msg)
    
    print(f"[SUCCESS] 최적 매수 대상: {best_ticker}")
    print(f"         종합 점수: {best_data['composite_score']:.2f}")
    print(f"         RSI: {best_data['rsi']:.1f}")
    print(f"         당일 변동: {best_data['daily_surge']:+.1f}%")
    
    return best_ticker

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

    # === 2. 새로운 매수 전략: 10만원 단위 매수 + 10만원 미만 시 전액 매수 ===
    buy_size = 0
    MIN_ORDER_AMOUNT = min_krw  # 업비트 최소 주문 금액
    STANDARD_BUY_AMOUNT = 100000  # 표준 매수 금액 (10만원)

    print(f"\n🎯 매수 전략 결정 중...")

    # 잔고가 최소 주문 금액 미만인 경우
    if krw < MIN_ORDER_AMOUNT:
        print(f"❌ 원화 잔고가 최소 주문 금액({MIN_ORDER_AMOUNT:,}원) 미만입니다.")
        print("💡 추가 입금 후 거래를 진행해주세요.")
        buy_size = 0

    # 잔고가 10만원 미만인 경우 → 전액 매수
    elif krw < STANDARD_BUY_AMOUNT:
        buy_size = krw * 0.9995  # 수수료 고려하여 99.95% 매수
        print(f"💡 원화 잔고가 10만원 미만 → 전액 매수 전략 적용")
        print(f"💵 전액 매수 금액: {buy_size:,.0f}원 (원화의 99.95%)")
        
        # 수수료 제외 후에도 최소 주문 금액 이상인지 확인
        if buy_size < MIN_ORDER_AMOUNT:
            print(f"⚠️ 수수료 제외 후 금액이 최소 주문 금액({MIN_ORDER_AMOUNT:,}원) 미만입니다.")
            buy_size = 0

    # 잔고가 10만원 이상인 경우 → 10만원 단위 매수
    else:
        buy_size = STANDARD_BUY_AMOUNT
        print(f"🚀 10만원 단위 DCA 매수 전략 적용")
        print(f"💵 표준 매수 금액: {buy_size:,.0f}원")
        print(f"💰 매수 후 잔여 원화: {krw - buy_size:,.0f}원")

    print(f"🔥 최종 매수 예정 금액: {buy_size:,.0f}원")

    # === 3. 매수 전략 요약 출력 ===
    if buy_size > 0:
        print(f"\n✅ 매수 전략 확정!")
        print(f"📊 현재 포트폴리오: {significant_assets_count}개 유의미 자산")
        print(f"💎 총 자산 가치: {total_asset_value:,.0f}원")
        print(f"🎯 이번 매수 금액: {buy_size:,.0f}원")
        
        # DCA 전략 정보 출력
        if krw >= STANDARD_BUY_AMOUNT:
            remaining_krw = krw - buy_size
            possible_additional_buys = remaining_krw // STANDARD_BUY_AMOUNT
            print(f"🔄 추가 매수 가능 횟수: {possible_additional_buys}회 (잔여 {remaining_krw % STANDARD_BUY_AMOUNT:,.0f}원)")
    else:
        print(f"\n❌ 매수 조건을 만족하지 않습니다.")
        if krw > 0:
            print(f"💡 현재 잔고 {krw:,.0f}원으로는 매수가 불가능합니다.")
            print(f"📝 최소 {MIN_ORDER_AMOUNT:,}원 이상 입금 후 재시도해주세요.")

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