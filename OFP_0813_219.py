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

band_diff_margin = 0.02
UpRsiRate = 80

def get_user_input():
    while True:
        try:
            min_rate = float(input("최소 수익률 (예: 0.4): "))
            max_rate = float(input("최대 수익률 (예: 3.1): "))
            sell_time = int(input("매도감시횟수 (예: 30): "))
            rsi_sell_s =int(input("RSI 매도 감시 시작 (예: 60): "))
            rsi_sell_e =int(input("RSI 매도 감시 종료 (예: 75): "))
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

def get_bollinger_bands(ticker, interval = min5, window=20, std_dev=2.5):
    """특정 티커의 볼린저 밴드 상단 및 하단값을 가져오는 함수"""
    df = pyupbit.get_ohlcv(ticker, interval=interval, count=50)
    time.sleep(second)
    if df is None or df.empty:
        return None  # 데이터가 없으면 None 반환

    bollinger = ta.volatility.BollingerBands(df['close'], window=window, window_dev=std_dev)

    upper_band = bollinger.bollinger_hband().fillna(0)  
    lower_band = bollinger.bollinger_lband().fillna(0)  
    
    bands_df = pd.DataFrame({   # DataFrame으로 묶기
        'Upper_Band': upper_band,
        'Lower_Band': lower_band
    })

    return bands_df.tail(4)

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

def calculate_simple_sell_signal(ticker, profit_rate):
    """
    간단한 매도 신호 계산 (True/False)
    """
    df = get_enhanced_indicators(ticker)
    if df is None:
        return False, "데이터 없음"
    
    latest = df.iloc[-1]
    prev = df.iloc[-2]
    
    # 매도 신호 조건들
    signals = []
    
    # 1. MACD 하향 전환 (가장 중요)
    macd_bearish = (prev['macd'] > prev['macd_signal']) and (latest['macd'] < latest['macd_signal'])
    if macd_bearish:
        signals.append("MACD하향크로스")
    
    # 2. 볼린저 밴드 상단 근처에서 하락
    bb_sell = latest['bb_position'] > 1.5 and prev['bb_position'] > latest['bb_position']
    if bb_sell:
        signals.append("볼밴상단하락")
    
    # 3. RSI 기존 로직 (70 이상에서 하락)
    ta_rsi = get_rsi(ticker, 14, interval="minute5")
    if ta_rsi is not None and len(ta_rsi) >= 2:
        rsi_current = ta_rsi.iloc[-1]
        rsi_prev = ta_rsi.iloc[-2]
        rsi_sell = rsi_current > 70 and rsi_prev > rsi_current
        if rsi_sell:
            signals.append("RSI과매수하락")
    
    # 4. 다이버전스 (기존 로직 유지)
    divergence_result = get_rsi_bear_diver(ticker)
    diver_bear = divergence_result['is_bearish_divergence'] if divergence_result else False
    if diver_bear:
        signals.append("베어다이버전스")
    
    # 매도 신호 판단 - 수익률에 따라 필요한 신호 개수 조정
    required_signals = 2 if profit_rate < max_rate else 1  # 낮은 수익률일 때는 더 확실한 신호 필요
    
    should_sell = len(signals) >= required_signals
    signal_text = " + ".join(signals) if signals else "신호없음"
    
    return should_sell, signal_text

def filtered_tickers(tickers):
    """개선된 조건에 맞는 티커 필터링 - 전문가 매수 로직 (시장심리 통합)"""
    filtered_tickers = []
    
    # === 시장 전체 심리 분석 ===
    market_rsi_total = 0
    market_valid_count = 0

    # 업비트 거래량 상위 10개 코인으로 시장 심리 측정 (하드코딩)
    market_tickers = [
        'KRW-BTC',   # 비트코인
        'KRW-ETH',   # 이더리움  
        'KRW-XRP',   # 리플
        'KRW-ADA',   # 카르다노
        'KRW-DOGE',  # 도지코인
        'KRW-SOL',   # 솔라나
        'KRW-AVAX',  # 아발란체
        'KRW-DOT',   # 폴카닷
        'KRW-MATIC', # 폴리곤
        'KRW-LINK'   # 체인링크
    ]
    
    # 상위 10개 코인으로 시장 심리 측정
    for ticker in market_tickers:
        try:
            market_df = pyupbit.get_ohlcv(ticker, interval=min5, count=20)
            time.sleep(0.3)
            if market_df is not None:
                market_rsi_data = get_rsi(ticker, 14, interval=min5)
                if len(market_rsi_data.values) > 0:
                    market_rsi_total += market_rsi_data.values[-1]
                    market_valid_count += 1
        except:
            continue
    
    # 시장 RSI 계산 및 조건 조정
    market_rsi = market_rsi_total / market_valid_count if market_valid_count > 0 else 50
    
    # 시장 상황에 따른 조건 동적 조정
    adjusted_band_margin = band_diff_margin
    adjusted_rsi_s = rsi_buy_s
    adjusted_rsi_e = rsi_buy_e
    
    if market_rsi < 35:  # 과매도 시장
        adjusted_band_margin *= 0.8  # 조건 완화
        adjusted_rsi_e *= 1.1
        market_status = "과매도(적극매수)"
    elif market_rsi > 65:  # 과매수 시장
        adjusted_band_margin *= 1.2  # 조건 강화
        adjusted_rsi_s *= 0.9
        market_status = "과매수(보수매수)"
    else:
        market_status = "중립"
    
    # send_discord_message(f"🌍 시장심리: RSI {market_rsi:.1f} ({market_status}) | 조정된 조건 적용")
    
    for t in tickers:
        try:
            # 기본 데이터 가져오기 (더 많은 데이터로 정확도 향상)
            df = pyupbit.get_ohlcv(t, interval=min5, count=100)  # 더 많은 데이터로 정확성 향상
            time.sleep(0.3)
            if df is None:
                print(f"[filter_tickers] 데이터를 가져올 수 없습니다. {t}")
                send_discord_message(f"[filter_tickers] 데이터를 가져올 수 없습니다: {t}")
                continue
            time.sleep(second)
            
            # 기존 데이터 추출
            df_close = df['close'].values
            df_low = df['low'].values
            df_high = df['high'].values
            df_volume = df['volume'].values
            
            # 볼린저 밴드 계산
            # 시장 상황에 따른 볼린저 밴드 설정 최적화
            if market_rsi < 35:  # 과매도 시장
                bb_window, bb_std = 25, 2.3  # 더 민감하게
            elif market_rsi > 65:  # 과매수 시장
                bb_window, bb_std = 35, 2.4  # 더 보수적으로
            else:  # 중립 시장
                bb_window, bb_std = 30, 2.2  # 최적 균형점
            
            bands_df = get_bollinger_bands(t, interval=min5, window=bb_window, std_dev=bb_std)
            upper_band = bands_df['Upper_Band'].values
            lower_band = bands_df['Lower_Band'].values
            band_diff = (upper_band - lower_band) / lower_band
            
            # 기존 조건들 (동적 조정된 값 사용)
            is_increasing = band_diff[-1] > adjusted_band_margin
            
            ta_rsi = get_rsi(t, 14, interval=min5)
            rsi = ta_rsi.values
            rsi_range = adjusted_rsi_s < rsi[-1] < adjusted_rsi_e
            
            divergence_result = get_rsi_bul_diver(t)
            
            # === 새로운 개선 조건들 ===
            
            # 1. 가격 위치 조건 (볼린저 밴드 하단 30% 구간에서 매수)
            current_price = pyupbit.get_current_price(t)
            bb_position = (current_price - lower_band[-1]) / (upper_band[-1] - lower_band[-1])
            is_near_lower_band = bb_position < 0.3  # 하단 30% 구간
            
            # 2. RSI 상승 전환 확인 (최근 3개 캔들에서 RSI 상승 추세)
            rsi_momentum = rsi[-1] > rsi[-2] and rsi[-2] >= rsi[-3]
            
            # 3. 거래량 조건 (최근 거래량이 평균 대비 증가)
            volume_ma5 = df_volume[-5:].mean()
            volume_ma20 = df_volume[-20:].mean()
            volume_surge = df_volume[-1] > volume_ma5 * 1.2  # 최근 거래량이 5일 평균 대비 20% 증가
            volume_above_avg = volume_ma5 > volume_ma20  # 단기 거래량이 장기 평균보다 높음
            
            # 4. 추세 확인 (중기 이동평균선 위치)
            price_ma20 = df_close[-20:].mean()
            price_above_ma = current_price > price_ma20 * 0.95  # 중기 이평선 근처 또는 위
            
            # 5. 변동성 확인 (적절한 변동성 범위)
            volatility = (df_high[-5:].max() - df_low[-5:].min()) / df_close[-5:].mean()
            good_volatility = 0.02 < volatility < 0.15  # 2%~15% 변동성 범위
            
            # 6. 연속 하락 후 반등 신호
            recent_lows = df_low[-3:]
            bounce_signal = current_price > recent_lows.min() * 1.01  # 최근 저점 대비 1% 이상 반등
            
            # === 종합 조건 평가 ===
            
            # 필수 조건 (기존 + 개선)
            essential_conditions = (
                is_increasing and 
                rsi_range and 
                divergence_result['is_bullish_divergence'] and
                is_near_lower_band  # 새로운 필수 조건
            )
            
            # 추가 점수 시스템 (3개 이상 충족시 매수)
            bonus_score = sum([
                rsi_momentum,           # RSI 상승 전환
                volume_surge,           # 거래량 증가
                volume_above_avg,       # 거래량 평균 이상
                price_above_ma,         # 중기 추세 양호
                good_volatility,        # 적절한 변동성
                bounce_signal           # 반등 신호
            ])
            
            bonus_conditions = bonus_score >= 3  # 6개 중 3개 이상 충족
            
            # 로깅 메시지 생성
            filteringTime = datetime.now().strftime('%m/%d %H시%M분%S초')
            filtering_message = f"<<[{filteringTime}] {t}>>\n"
            filtering_message += f"[cond1: {is_increasing}] band_diff: {band_diff[-1]:,.4f} > BD_Margin: {adjusted_band_margin}\n"
            filtering_message += f"[cond2: {rsi_range}] {adjusted_rsi_s} < rsi: {rsi[-2]:,.2f} > {rsi[-1]:,.2f} < {adjusted_rsi_e}\n"
            filtering_message += f"[cond3: bullish_diver: {divergence_result['is_bullish_divergence']}] 구간: {divergence_result['divergence_bars']}개 캔들\n"
            filtering_message += f"[cond4: price_pos: {is_near_lower_band}] BB위치: {bb_position:.2%}\n"
            filtering_message += f"[bonus: {bonus_score}/6] RSI모멘텀: {rsi_momentum} | 거래량: {volume_surge}/{volume_above_avg} | 추세: {price_above_ma} | 변동성: {good_volatility} | 반등: {bounce_signal}\n"
            
            # 최종 매수 조건
            if essential_conditions and bonus_conditions:
                send_discord_message(filtering_message + "✅ **매수 신호 발생! 매수후보 추가**")
                filtered_tickers.append(t)
            elif essential_conditions:
                send_discord_message(filtering_message + "⚠️ 필수조건 충족, 추가조건 부족 하지만 매수 후보에 추가")
                filtered_tickers.append(t)

        except (KeyError, ValueError) as e:
            send_discord_message(f"filtered_tickers/Error processing ticker {t}: {e}")
            time.sleep(5)

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
    max_retries = 5
    attempt = 0
    
    # === 시장 상황 분석 ===
    market_tickers = ['KRW-BTC', 'KRW-ETH', 'KRW-XRP', 'KRW-ADA', 'KRW-DOGE']
    market_rsi_total = 0
    market_valid_count = 0
    
    for market_ticker in market_tickers:
        try:
            market_rsi_data = get_rsi(market_ticker, 14, interval=min5)
            if len(market_rsi_data.values) > 0:
                market_rsi_total += market_rsi_data.values[-1]
                market_valid_count += 1
        except:
            continue
    
    market_rsi = market_rsi_total / market_valid_count if market_valid_count > 0 else 50
    
    # # KRW 보유금액이 15만원 이하인 경우 전액 매수
    # if krw <= 150000:
    #     buy_ratio = 0.9995  # 전액 매수 (수수료 고려)
    #     risk_level = "FULL"
    #     buy_size = krw * buy_ratio
    # else:
    #     # 시장 상황에 따른 매수 비율 조정 (15만원 초과시)
    #     if market_rsi < 30:      # 극도 과매도
    #         buy_ratio = 0.9995   # 적극 매수
    #         risk_level = "LOW"
    #     elif market_rsi < 50:    # 과매도
    #         buy_ratio = 0.5      # 보통 매수
    #         risk_level = "MEDIUM"
    #     else:                    # 과매수
    #         buy_ratio = 0.2      # 최소 매수
    #         risk_level = "HIGH"
    
    # buy_size = krw * buy_ratio
    # 시장 상황에 따른 매수 비율 조정
    if market_rsi < 30:      # 극도 과매도
        buy_ratio = 0.9995   # 적극 매수
        risk_level = "LOW"
    elif market_rsi < 50:    # 과매도
        buy_ratio = 0.5      # 보통 매수
        risk_level = "MEDIUM"
    else:                    # 과매수
        buy_ratio = 0.2      # 최소 매수
        risk_level = "HIGH"

    # 보유원화가 10만원 미만이면 시장상황과 관계없이 전량 매수
    if krw < 100000:
        buy_ratio = 0.9995  # 전액 매수 (수수료 고려)
        risk_level = "FULL"

    buy_size = krw * buy_ratio

    
    # === 개별 코인 분석 ===
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
    # price_ma10 = df_close[-10:].mean()
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
                        buyedmsg = f"✅ **매수 성공**: {ticker}\n"
                        buyedmsg += f"💰 매수가: {final_price:,.2f} | 금액: {buy_size:,.0f}원\n"
                        buyedmsg += f"📊 RSI: {rsi[-2]:,.1f} → {rsi[-1]:,.1f} | BB위치: {bb_position:.1%}\n"
                        buyedmsg += f"🎯 시장RSI: {market_rsi:.1f} | 리스크: {risk_level} | 안전점수: {safety_score}/6\n"
                        buyedmsg += f"📈 매수비율: {buy_ratio:.1%} | EMA대비: {((final_price/last_ema-1)*100):+.2f}%"
                        
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
                condition_msg += f"RSI: {rsi[-1]:,.1f} | BB위치: {bb_position:.1%} | 안전점수: {safety_score}/6\n"
                condition_msg += f"기본조건: {basic_condition} | 시장RSI: {market_rsi:.1f}"
                
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
    should_sell_technical, signal_details = calculate_simple_sell_signal(ticker, profit_rate)
        
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
                should_sell_technical, signal_details = calculate_simple_sell_signal(ticker, profit_rate)
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
                # middleFailmsg = f"[매도대기]: [{ticker}] / 수익률: {profit_rate:.2f}% / 현재가: {cur_price:,.1f}\n"
                # middleFailmsg += f"신호상태: {signal_details}\n"  # 기존 변수 재사용
                # middleFailmsg += f"RSI하락: {rsi_downing} / RSI: {rsi[-2]:.1f} → {rsi[-1]:.1f}\n"
                # print(middleFailmsg)
                # send_discord_message(middleFailmsg)
                # time.sleep(2)
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
trade_msg += f'매도: {min_rate}% ~ {max_rate}% / 시도: {sell_time}회 / RsiBuy: {rsi_buy_s} ~ {rsi_buy_e} / RsiSell: {rsi_sell_s} ~ {rsi_sell_e} / BD_margin: {band_diff_margin} / 손절: {cut_rate}% \n'

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
                            time.sleep(1)
                    else:
                        time.sleep(1)

                else:
                    time.sleep(60)

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