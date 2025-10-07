import time
import pyupbit
import numpy as np
from datetime import datetime, timedelta
import os
from dotenv import load_dotenv
import requests
# import ta
# import pandas as pd
import threading
# from concurrent.futures import ThreadPoolExecutor

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
    # for i, ticker in enumerate(STRATEGIC_COINS, 1):
    #     print(f"  {i:2}. {ticker}")
    # print("=" * 70 + "\n")
    
    return STRATEGIC_COINS
    
def trade_buy(ticker=None):
    """
    🚀 초단기 복리 매수 시스템 v4.0 - 2% 수익 특화 설계
    
    목표: 2~3시간 내 2% 수익 → 10만원→10억 복리 달성
    
    혁신 요소:
    1. 켈리 기준 기반 복리 최적화 포지션 사이징 (별도 함수)
    2. 2% 목표 역산 진입점 (초단기 반등 확률 극대화)
    3. 1분봉 추가 분석 (미시적 모멘텀 포착)
    4. 변동성 적응형 임계값 (BB 폭 기반 동적 조정)
    5. 손실 방지 다층 필터
    
    Args:
        ticker: 특정 종목 지정 시 해당 종목만 분석 (예: "KRW-BTC")
                None이면 자동으로 최적 종목 선정
    
    Returns:
        성공 시: 매수 주문 객체 (upbit API 응답)
        실패 시: (실패 사유 문자열, None) 튜플
    """
    
    # ==================== 내부 유틸리티 ====================
    # 이 함수들은 trade_buy 내부에서만 사용되며, 기술적 지표를 계산합니다
    
    def calculate_rsi(closes, period=14):
        """
        RSI (Relative Strength Index) 계산 함수
        
        RSI는 0~100 사이 값으로, 과매수/과매도 판단에 사용
        - RSI < 30: 과매도 (매수 기회)
        - RSI > 70: 과매수 (매도 고려)
        
        Args:
            closes: 종가 배열 (numpy array)
            period: RSI 계산 기간 (기본 14)
        
        Returns:
            RSI 값 (0~100)
        """
        # 데이터가 충분하지 않으면 중립값 50 반환

        if len(closes) < period + 1:
            return 50.0
        
        # 가격 변화량 계산 (오늘 종가 - 어제 종가)
        deltas = np.diff(closes)

        # 상승분만 추출 (양수만)
        gains = np.where(deltas > 0, deltas, 0)

        # 하락분만 추출 (음수를 양수로 변환)
        losses = np.where(deltas < 0, -deltas, 0)

        # 초기 평균 계산 (첫 14개 데이터)
        avg_gain = np.mean(gains[:period])
        avg_loss = np.mean(losses[:period])

        # 이후 데이터는 지수이동평균 방식으로 계산 (최근 데이터에 더 가중치)
        for i in range(period, len(closes)-1):
            avg_gain = (avg_gain * (period-1) + gains[i]) / period
            avg_loss = (avg_loss * (period-1) + losses[i]) / period

        # RS (Relative Strength) = 평균 상승 / 평균 하락
        # 1e-8은 0으로 나누기 방지용 아주 작은 수    
        rs = avg_gain / (avg_loss + 1e-8)

        # RSI 공식: 100 - (100 / (1 + RS))
        return 100 - (100 / (1 + rs))
    
    def calculate_ema(closes, period=12):
        """
        EMA (Exponential Moving Average) 계산 함수
        
        EMA는 최근 데이터에 더 많은 가중치를 부여하는 이동평균
        단순 이동평균보다 가격 변화에 더 민감하게 반응
        
        Args:
            closes: 종가 배열
            period: EMA 계산 기간
        
        Returns:
            최종 EMA 값
        """
        # 데이터가 부족하면 마지막 종가 반환
        if len(closes) < period:
            return closes[-1]
        # EMA 계산 시작 (첫 값은 첫 종가로 설정)
        ema = [closes[0]]

        # 평활 계수 계산 (최근 데이터 가중치)
        # period가 작을수록 최근 데이터 영향 커짐
        alpha = 2 / (period + 1)

        # 순차적으로 EMA 계산
        # EMA(오늘) = alpha * 오늘종가 + (1-alpha) * EMA(어제)
        for close in closes[1:]:
            ema.append(alpha * close + (1 - alpha) * ema[-1])

        # 최종 EMA 값 반환    
        return ema[-1]
    
    def calculate_bb(closes, window=20, std_dev=2.0):
        """
        볼린저 밴드 (Bollinger Bands) 계산 함수
        
        볼린저 밴드는 가격 변동성을 시각화하는 지표
        - 하단 밴드: 평균 - (표준편차 * 2)
        - 중간 밴드: 이동평균
        - 상단 밴드: 평균 + (표준편차 * 2)
        
        가격이 하단 밴드에 가까우면 과매도 → 매수 기회
        가격이 상단 밴드에 가까우면 과매수 → 매도 고려
        
        Args:
            closes: 종가 배열
            window: 이동평균 기간 (기본 20)
            std_dev: 표준편차 승수 (기본 2.0)
        
        Returns:
            (하단, 중간, 상단, 위치비율, 밴드폭%)
            - 위치비율: 0(하단) ~ 1(상단)
            - 밴드폭%: 변동성 지표 (클수록 변동성 높음)
        """
        # 데이터가 부족하면 사용 가능한 만큼만 사용

        if len(closes) < window:
            window = len(closes)
        
        # 중간 밴드: 단순 이동평균 (SMA)
        sma = np.mean(closes[-window:])
        
        # 표준편차 계산 (가격 변동성 측정)
        std = np.std(closes[-window:])
        
        # 하단 밴드 = 평균 - (표준편차 * 2)
        lower = sma - (std * std_dev)

        # 상단 밴드 = 평균 + (표준편차 * 2)
        upper = sma + (std * std_dev)

        # 현재 가격이 밴드 내 어디에 위치하는지 계산
        # 0 = 하단 밴드, 0.5 = 중간, 1 = 상단 밴드
        position = (closes[-1] - lower) / (upper - lower + 1e-8)

        # 밴드 폭 계산 (변동성 지표)
        # 밴드 폭이 클수록 변동성이 크다는 의미 
        width = (upper - lower) / sma * 100

        # 위치는 0~1 범위로 제한 (음수나 1 초과 방지)
        return lower, sma, upper, max(0, min(1, position)), width
    
    def get_krw_balance():
        """
        현재 KRW(원화) 잔고 조회
        
        Returns:
            KRW 잔고 (float), 오류 시 0.0 반환
        """
        try:
            # Upbit API로 전체 잔고 조회
            balances = upbit.get_balances()

            # KRW 통화 찾기
            for b in balances:
                if b['currency'] == "KRW":
                    return float(b['balance'])
        except:     # API 오류 시 0 반환
            pass
        return 0.0
    
    def get_total_crypto_value():
        """
        보유 중인 모든 암호화폐의 총 평가액 계산 (KRW 제외)
        
        각 코인의 수량 * 현재가를 합산하여 총 평가액 산출
        
        Returns:
            총 암호화폐 평가액 (KRW), 오류 시 0.0 반환
        """
        try:
            balances = upbit.get_balances()     # 전체 잔고 조회
            total = 0.0
            for balance in balances:
                if balance['currency'] == 'KRW':        # KRW는 제외 (암호화폐만 계산)
                    continue
                amount = float(balance['balance'])      # 보유 수량
                if amount > 0:
                    ticker_name = f"KRW-{balance['currency']}"      # 티커 이름 생성 (예: KRW-BTC)
                    try:
                        price = pyupbit.get_current_price(ticker_name)  # 현재가 조회
                        if price:   
                            total += amount * price         # 평가액 계산   
                    except:                     # 개별 코인 조회 실패 시 무시하고 계속
                        continue
            return total
        except:
            return 0.0              # 전체 조회 실패 시 0 반환
    
    def get_held_coins():
        """
        현재 보유 중인 코인 목록 조회
        
        중복 매수 방지를 위해 사용
        이미 보유한 코인은 추가 매수하지 않음
        
        Returns:
            보유 코인 티커 집합 (set), 예: {'KRW-BTC', 'KRW-ETH'}
        """
        try:
            balances = upbit.get_balances()
            return {f"KRW-{b['currency']}" for b in balances        # 잔고가 있는 코인만 추출 (KRW 제외)
                   if float(b.get('balance', 0)) > 0 and b['currency'] != 'KRW'}
        except:         # 오류 시 빈 집합 반환
            return set()
    
    def calculate_absolute_volume_krw(df, current_price):
        """
        절대 거래대금 계산 (단위: KRW)
        
        상대 거래량(배수)만으로는 저거래량 코인의 fake 급등을 구분 못함
        절대 거래대금을 함께 체크하여 실질적인 거래량 확인
        
        Args:
            df: OHLCV 데이터프레임
            current_price: 현재가
        
        Returns:
            최근 5분봉 평균 거래대금 (KRW)
        """
        try:
            recent_volumes = df['volume'].values[-5:]       # 최근 5개 봉의 거래량 추출
            avg_volume = np.mean(recent_volumes)            # 평균 거래량 (코인 개수)
            return avg_volume * current_price               # 거래대금 = 거래량 * 현재가    
        except:
            return 0.0
    
    def analyze_multi_timeframe(ticker_symbol):
        """
        🎯 다중 시간프레임 통합 분석 + 1분봉 추가
        
        핵심 아이디어:
        - 단일 시간프레임만 보면 속임수(fake) 신호에 당할 수 있음
        - 여러 시간프레임을 동시에 확인하여 진짜 신호 포착
        - 1분봉 추가: 2% 초단기 목표 달성을 위해 미시적 모멘텀 전환 포착 필수
        
        시간프레임별 역할:
        - 1분봉: 초단기 진입 타이밍 (반등 시작 감지)
        - 5분봉: 주 진입 신호 (과매도 + 모멘텀)
        - 15분봉: 중기 트렌드 확인 (하락 추세인지 검증)
        - 1시간봉: 장기 방향성 (상승 여력 있는지)
        - 일봉: 전체 시장 포지션 (고점 근처인지 저점 근처인지)
        
        Args:
            ticker_symbol: 분석할 코인 티커 (예: "KRW-BTC")
        
        Returns:
            분석 결과 딕셔너리:
            {
                'valid': bool,  # 데이터 유효성
                'data_1m': DataFrame,  # 1분봉 데이터
                'data_5m': DataFrame,  # 5분봉 데이터
                'data_15m': DataFrame,  # 15분봉 데이터
                'data_1h': DataFrame,  # 1시간봉 데이터
                'data_1d': DataFrame,  # 일봉 데이터
                'current_price': float,  # 현재가
                'indicators': dict  # 계산된 모든 지표들
            }
        """
        try:
            # ===== 데이터 수집 (API 호출) =====
            # 각 시간프레임별로 충분한 데이터 수집
            # count: 과거 몇 개의 캔들을 가져올지
            
            # 1분봉: 30개 (최근 30분 데이터)
            # 1분봉을 추가한 이유: 2~3시간 내 2% 수익 목표
            # → 초단기 진입이므로 1분 단위 모멘텀 전환 포착 필수

            df_1m = pyupbit.get_ohlcv(ticker_symbol, interval="minute1", count=30)
            time.sleep(0.1)
            df_5m = pyupbit.get_ohlcv(ticker_symbol, interval="minute5", count=50)
            time.sleep(0.1)
            df_15m = pyupbit.get_ohlcv(ticker_symbol, interval="minute15", count=50)
            time.sleep(0.1)
            df_1h = pyupbit.get_ohlcv(ticker_symbol, interval="minute60", count=50)
            time.sleep(0.1)
            df_1d = pyupbit.get_ohlcv(ticker_symbol, interval="day", count=5)
            time.sleep(0.1)
            
            current_price = pyupbit.get_current_price(ticker_symbol)
            
            # ===== 데이터 유효성 검증 =====
            # 모든 데이터가 정상적으로 조회되었는지 확인
            # 하나라도 None이거나 데이터가 부족하면 분석 불가
            if (df_1m is None or len(df_1m) < 15 or
                df_5m is None or len(df_5m) < 30 or
                df_15m is None or len(df_15m) < 30 or
                df_1h is None or len(df_1h) < 30 or
                df_1d is None or len(df_1d) < 2 or
                current_price is None):
                return {'valid': False}
            
            # ===== 종가 데이터 추출 =====
            # 각 시간프레임별 종가 배열 (기술적 지표 계산에 사용)
            closes_1m = df_1m['close'].values
            closes_5m = df_5m['close'].values
            closes_15m = df_15m['close'].values
            closes_1h = df_1h['close'].values
            
            # 거래량 데이터 추출
            volumes_1m = df_1m['volume'].values
            volumes_5m = df_5m['volume'].values
            
            # ===== [지표 1] RSI 계산 (각 시간프레임) =====
            # RSI가 낮을수록 과매도 → 매수 기회
            # 1분봉 RSI 추가: 초단기 진입 타이밍 포착용
            rsi_1m = calculate_rsi(closes_1m, 14)
            rsi_5m = calculate_rsi(closes_5m, 14)
            rsi_15m = calculate_rsi(closes_15m, 14)
            rsi_1h = calculate_rsi(closes_1h, 14)
            
            # ===== [지표 2] 볼린저 밴드 계산 (각 시간프레임) =====
            # BB 하단에 가까울수록 매수 기회
            # 1분봉 BB 추가: 초단기 저점 확인용
            bb_1m_lower, bb_1m_mid, bb_1m_upper, bb_1m_pos, bb_1m_width = calculate_bb(closes_1m, 20)
            bb_5m_lower, bb_5m_mid, bb_5m_upper, bb_5m_pos, bb_5m_width = calculate_bb(closes_5m, 20)
            bb_15m_lower, bb_15m_mid, bb_15m_upper, bb_15m_pos, bb_15m_width = calculate_bb(closes_15m, 20)
            bb_1h_lower, bb_1h_mid, bb_1h_upper, bb_1h_pos, bb_1h_width = calculate_bb(closes_1h, 20)
            
            # ===== [지표 3] EMA 계산 (5분봉 기준) =====
            # EMA는 가격 지지선 역할
            # 현재가가 EMA 위에 있으면 상승 추세
            ema_12 = calculate_ema(closes_5m, 12)
            ema_26 = calculate_ema(closes_5m, 26)
            
            # ===== [지표 4] 거래량 분석 =====
            # 1분봉 거래량 급증 여부 (초단기 모멘텀 확인)
            vol_recent_1m = np.mean(volumes_1m[-3:])
            vol_normal_1m = np.mean(volumes_1m[-15:-3])
            vol_ratio_1m = vol_recent_1m / (vol_normal_1m + 1e-8)
            
            # 5분봉 거래량 급증 여부 (주 신호)
            vol_recent = np.mean(volumes_5m[-5:])
            vol_normal = np.mean(volumes_5m[-20:-5])
            vol_ratio = vol_recent / (vol_normal + 1e-8)

            # 절대 거래대금 (fake 필터링용)
            # 예: 거래량이 10배 증가해도 절대 금액이 1억원 미만이면 신뢰도 낮음
            vol_absolute_krw = calculate_absolute_volume_krw(df_5m, current_price)
            
            # ===== [지표 5] 모멘텀 분석 =====
            # 1분봉 모멘텀 (초단기 전환 감지)
            # 최근 3개 봉 동안의 가격 변화율
            
            price_momentum_1m = (closes_1m[-1] - closes_1m[-3]) / closes_1m[-3]
            
            # 1분봉 RSI 모멘텀 (RSI가 상승 중인지)
            # 현재 RSI - 1분 전 RSI
            rsi_momentum_1m = rsi_1m - calculate_rsi(closes_1m[:-1], 14)
            
            # 5분봉 모멘텀 (주 신호)
            price_momentum = (closes_5m[-1] - closes_5m[-3]) / closes_5m[-3]
            rsi_momentum = rsi_5m - calculate_rsi(closes_5m[:-1], 14)
            
            # ===== [지표 6] 일봉 분석 =====
            # 일봉 기준으로 현재 저점인지 고점인지 판단
            daily_open = df_1d['open'].iloc[-1]
            daily_prev_close = df_1d['close'].iloc[-2]

            # 오늘 시가 대비 현재가 변화율 / 음수 = 시가보다 낮음 (저점 매수 기회) / 양수 = 시가보다 높음 (고점, 매수 주의)
            daily_change_from_open = (current_price - daily_open) / daily_open * 100
            
            # 어제 종가 대비 현재가 변화율 / 전일 대비 급락했다면 매수 기회
            daily_change_from_prev = (current_price - daily_prev_close) / daily_prev_close * 100
            
            # ===== [지표 7] 지지선 근접도 =====
            # 최근 20개 봉의 최저가 = 지지선
            recent_low = np.min(df_5m['low'].values[-20:])
            
            # 현재가가 지지선에서 얼마나 떨어져 있는지 / 0%에 가까울수록 지지선 근처 (반등 가능성 높음)
            support_proximity = (current_price - recent_low) / recent_low * 100
            
            # ===== [지표 8] 🆕 2% 목표 달성 가능성 분석 =====
            # 현재 매수 후 2% 상승 시 저항선에 막힐지 미리 계산

            # 2% 상승 시 목표가
            target_price_2pct = current_price * 1.02

            # 최근 20개 봉의 최고가 = 저항선
            resistance_5m = np.max(df_5m['high'].values[-20:])

            # 2% 목표가와 저항선 사이 여유 공간
            # 양수 = 저항선까지 여유 있음 (목표 달성 가능)
            # 음수 = 저항선이 2% 목표가보다 낮음 (목표 달성 어려움)
            resistance_clearance = (resistance_5m - target_price_2pct) / target_price_2pct * 100
            
            # ===== [지표 9] 🆕 변동성 점수 =====
            # BB 폭이 클수록 변동성 높음
            # 변동성이 높으면 2% 목표 달성 쉽지만 손실 위험도 큼
            # → 변동성에 따라 포지션 크기 조절 필요
            volatility_score = bb_5m_width  # 폭이 클수록 변동성 높음
            
            # ===== 최종 결과 반환 =====
            return {
                'valid': True,
                'data_1m': df_1m,
                'data_5m': df_5m,
                'data_15m': df_15m,
                'data_1h': df_1h,
                'data_1d': df_1d,
                'current_price': current_price,
                'indicators': {
                    
                    # ===== RSI 지표 =====
                    'rsi_1m': rsi_1m,  # 1분봉 RSI (초단기 진입용)
                    'rsi_5m': rsi_5m,  # 5분봉 RSI (주 신호)
                    'rsi_15m': rsi_15m,  # 15분봉 RSI (중기 확인)
                    'rsi_1h': rsi_1h,  # 1시간봉 RSI (장기 확인)
                    'rsi_momentum_1m': rsi_momentum_1m,  # 1분 RSI 모멘텀
                    'rsi_momentum': rsi_momentum,  # 5분 RSI 모멘텀
                    
                    # ===== 볼린저 밴드 지표 =====
                    'bb_1m_pos': bb_1m_pos,  # 1분봉 BB 위치 (0~1)
                    'bb_1m_width': bb_1m_width,  # 1분봉 BB 폭 (변동성)
                    'bb_5m_pos': bb_5m_pos,  # 5분봉 BB 위치
                    'bb_5m_width': bb_5m_width,  # 5분봉 BB 폭
                    'bb_15m_pos': bb_15m_pos,  # 15분봉 BB 위치
                    'bb_15m_width': bb_15m_width,  # 15분봉 BB 폭
                    'bb_1h_pos': bb_1h_pos,  # 1시간봉 BB 위치
                    'bb_1h_width': bb_1h_width,  # 1시간봉 BB 폭

                    # ===== EMA 지표 =====
                    'ema_12': ema_12,  # 단기 EMA (지지선)
                    'ema_26': ema_26,  # 장기 EMA (지지선)
                    
                    # ===== 거래량 지표 =====
                    'vol_ratio_1m': vol_ratio_1m,  # 1분 거래량 급증 배수
                    'vol_ratio': vol_ratio,  # 5분 거래량 급증 배수
                    'vol_absolute_krw': vol_absolute_krw,  # 절대 거래대금 (fake 필터)
                    
                    # ===== 모멘텀 지표 =====
                    'price_momentum_1m': price_momentum_1m,  # 1분 가격 모멘텀
                    'price_momentum': price_momentum,  # 5분 가격 모멘텀
                    
                    # ===== 일봉 지표 =====
                    'daily_change_from_open': daily_change_from_open,  # 오늘 시가 대비 %
                    'daily_change_from_prev': daily_change_from_prev,  # 어제 종가 대비 %
                    
                    # ===== 지지/저항 지표 =====
                    'support_proximity': support_proximity,  # 지지선 근접도
                    
                    # ===== 🆕 2% 목표 관련 지표 =====
                    'resistance_clearance': resistance_clearance,  # 2% 목표 저항 여유
                    'volatility_score': volatility_score  # 변동성 점수 (BB 폭)
                }
            }
            
        except Exception as e:
            return {'valid': False}
    
    def calculate_signal_score(indicators):
        """
        💪 2% 목표 특화 신호 강도 계산 (0~100점)
        
        핵심 전략:
        - 2~3시간 내 2% 수익을 목표로 하므로 초단기 반등 신호에 집중
        - 1분봉 모멘텀 전환을 가장 중요하게 평가 (25점 배정)
        - 변동성에 따라 임계값을 동적으로 조정 (고변동성 시 완화)
        
        점수 구성:
        - 일봉 포지션: 20점 (저점 매수 확정성)
        - 1분봉 모멘텀: 25점 (초단기 진입 타이밍) ← 핵심!
        - 다중 RSI: 15점 (과매도 확인)
        - 다중 BB: 20점 (밴드 하단 확인)
        - 거래량: 15점 (거래 활성도)
        - 2% 저항: 5점 (목표 달성 가능성)
        
        Args:
            indicators: analyze_multi_timeframe()에서 계산된 지표 딕셔너리
        
        Returns:
            (총점, 신호 목록)
            - 총점: 0~100점
            - 신호 목록: 주요 매수 근거 문자열 리스트
        """
        score = 0  # 총점 초기화
        signals = []  # 매수 근거 목록
        
        # ===== [변동성 기반 동적 조정] =====
        # BB 폭(변동성)에 따라 RSI/BB 임계값을 조정
        # 이유: 변동성 장에서는 RSI 30 도달이 어려우므로 기준 완화 필요
        
        vol_score = indicators['volatility_score']  # BB 폭
        
        if vol_score > 5.0:  # 고변동성 (BB 폭 5% 이상)
            bb_relax = 0.10  # BB 임계값 10% 완화
            rsi_relax = 5  # RSI 임계값 5 완화 (예: 30 → 35)
        elif vol_score > 3.0:  # 중변동성 (BB 폭 3~5%)
            bb_relax = 0.05  # BB 임계값 5% 완화
            rsi_relax = 3  # RSI 임계값 3 완화
        else:  # 저변동성 (BB 폭 3% 미만)
            bb_relax = 0.0  # 완화 없음 (기본 임계값 사용)
            rsi_relax = 0
        
        # ===== [1] 일봉 포지션 분석 (20점) =====
        # 목적: 일봉 기준으로 저점인지 고점인지 판단
        # 전략: 오늘 시가보다 낮을수록 좋음 (저점 매수)
        
        daily_open_chg = indicators['daily_change_from_open']  # 오늘 시가 대비 %
        daily_prev_chg = indicators['daily_change_from_prev']  # 어제 종가 대비 %
        
        # 오늘 시가 대비 변화율에 따른 점수 부여
        if daily_open_chg < -2.0:  # 시가 대비 -2% 이상 하락
            score += 20  # 만점 (저점 확정)
            signals.append(f"일봉↓{daily_open_chg:.1f}%")
        elif daily_open_chg < -1.0:  # 시가 대비 -1~-2% 하락
            score += 15  # 15점 (저점 가능성 높음)
            signals.append(f"일봉↓{daily_open_chg:.1f}%")
        elif daily_open_chg < 0:  # 시가 대비 0~-1% 하락
            score += 10  # 10점 (저점 가능성 있음)
            signals.append(f"일봉{daily_open_chg:+.1f}%")
        elif daily_open_chg <= 0.5:  # 시가 대비 0~+0.5% 상승
            score += 5  # 5점 (아직 저점권)
            signals.append("일봉제한")
        # 0.5% 초과 상승 시 점수 없음 (고점 가능성)
        
        # 전일 급락 보너스 (추가 점수)
        if daily_prev_chg < -5.0:  # 어제 -5% 이상 폭락
            score += 5  # 보너스 5점 (과매도 반등 기대)
            signals.append(f"전일↓{daily_prev_chg:.1f}%")
        
        # ===== [2] 🆕 1분봉 초단기 모멘텀 분석 (25점) - 핵심! =====
        # 목적: 2% 목표 달성을 위한 초단기 진입 타이밍 포착
        # 전략: 1분 과매도 + 모멘텀 전환 + BB 하단 + 거래량 급증 조합
        
        rsi_1m = indicators['rsi_1m']  # 1분봉 RSI
        rsi_mom_1m = indicators['rsi_momentum_1m']  # 1분 RSI 모멘텀 (상승 중?)
        price_mom_1m = indicators['price_momentum_1m']  # 1분 가격 모멘텀
        bb_1m_pos = indicators['bb_1m_pos']  # 1분봉 BB 위치
        vol_ratio_1m = indicators['vol_ratio_1m']  # 1분 거래량 급증 배수
        
        # 최고 조건: 4가지 조건 모두 만족 (이상적 진입점)
        # 1. RSI < 35 (과매도)
        # 2. RSI 모멘텀 > 0 (RSI 상승 전환)
        # 3. BB 위치 < 0.30 (하단 30% 이내)
        # 4. 거래량 1.5배 이상 급증

        if (rsi_1m < 35 and rsi_mom_1m > 0 and 
            bb_1m_pos < 0.30 and vol_ratio_1m > 1.5):
            score += 25  # 만점 (완벽한 진입 타이밍)
            signals.append(f"1분반등확인({rsi_1m:.0f})")
        
        # 좋은 조건: 과매도 + 모멘텀 전환 (2가지 조건)
        # RSI가 낮고 상승 전환 시작 = 반등 시작
        elif rsi_1m < 40 and (rsi_mom_1m > 0 or price_mom_1m > 0):
            score += 20  # 20점 (좋은 진입점)
            signals.append(f"1분전환({rsi_1m:.0f})")
        
        # 보통 조건: 과매도만 확인 (1가지 조건)
        # 아직 반등은 시작 안했지만 과매도 상태
        elif rsi_1m < 45:
            score += 10  # 10점 (진입 고려 가능)
            signals.append(f"1분과매도({rsi_1m:.0f})")
        # RSI > 45 시 점수 없음 (아직 과매도 아님)
        
        # ===== [3] 다중 시간프레임 RSI 분석 (15점) =====
        # 목적: 여러 시간프레임에서 동시에 과매도 확인
        # 전략: 짧은 시간프레임(5분)부터 긴 시간프레임(1시간)까지 과매도면 신뢰도 높음
        
        rsi_5m = indicators['rsi_5m']
        rsi_15m = indicators['rsi_15m']
        rsi_1h = indicators['rsi_1h']
        
        # 변동성에 따라 조정된 임계값 적용
        # 예: 고변동성 시 RSI 30 → 35로 완화
        
        # 최고 조건: 5분 + 15분 모두 과매도
        # 두 시간프레임이 모두 과매도 = 강력한 매수 신호
        if rsi_5m <= (30+rsi_relax) and rsi_15m <= (35+rsi_relax):
            score += 15  # 만점
            signals.append(f"RSI과매도({rsi_5m:.0f}/{rsi_15m:.0f})")
        
        # 좋은 조건: 5분만 과매도
        elif rsi_5m <= (35+rsi_relax):
            score += 10  # 10점
            signals.append(f"5분RSI({rsi_5m:.0f})")
        
        # 보통 조건: 5분 중립~약과매도
        elif rsi_5m <= (40+rsi_relax):
            score += 5  # 5점
        # RSI > 40+완화값 시 점수 없음
        
        # ===== [4] 다중 시간프레임 볼린저 밴드 분석 (20점) =====
        # 목적: 여러 시간프레임에서 BB 하단 근접 확인
        # 전략: 5분 하단 + 15분 중하단 = 강력한 반등 가능성
        
        bb_5m_pos = indicators['bb_5m_pos']  # 5분봉 BB 위치 (0~1)
        bb_15m_pos = indicators['bb_15m_pos']  # 15분봉 BB 위치
        bb_1h_pos = indicators['bb_1h_pos']  # 1시간봉 BB 위치
        
        # 변동성에 따라 조정된 임계값 적용
        
        # 최고 조건: 5분 하단 + 15분 중하단
        # 5분은 극단적 하단(20%), 15분은 중하단(50%)
        # → 단기 급락 후 중기 트렌드는 아직 여유 있음
        if bb_5m_pos < (0.20+bb_relax) and bb_15m_pos < (0.50+bb_relax):
            score += 20  # 만점 (이상적 진입점)
            signals.append(f"BB하단({bb_5m_pos*100:.0f}/{bb_15m_pos*100:.0f})")
        
        # 좋은 조건: 5분 하단 + 15분 중간
        elif bb_5m_pos < (0.25+bb_relax) and bb_15m_pos < (0.60+bb_relax):
            score += 15  # 15점
            signals.append(f"BB중하단({bb_5m_pos*100:.0f})")
        
        # 보통 조건: 5분 하단
        elif bb_5m_pos < (0.30+bb_relax):
            score += 10  # 10점
        
        # 주의 조건: 5분 약간 하단
        # 15분이 높아도 5분이 하단이면 일부 점수
        elif bb_5m_pos < (0.35+bb_relax):
            score += 5  # 5점
        # BB 위치 > 35%+완화값 시 점수 없음 (하단 아님)
        
        # ===== [5] 거래량 분석 (15점) =====
        # 목적: 진짜 매수세가 유입되는지 확인 (fake 필터링)
        # 전략: 절대 거래대금과 상대 급증률을 조합하여 판단
        
        vol_ratio = indicators['vol_ratio']  # 5분 거래량 급증 배수
        vol_krw = indicators['vol_absolute_krw']  # 절대 거래대금 (KRW)
        
        # 거래대금 기준선 설정
        MIN_VOL = 100_000_000  # 1억원 (최소 신뢰 기준)
        GOOD_VOL = 500_000_000  # 5억원 (충분한 거래량)
        
        # [경우 1] 거래대금 충분 (5억원 이상)
        # → 상대 급증률을 정상적으로 신뢰 가능
        if vol_krw >= GOOD_VOL:
            if vol_ratio >= 2.0:  # 2배 이상 급증
                score += 15  # 만점 (강력한 매수세)
                signals.append(f"거래량급증({vol_ratio:.1f}x)")
            elif vol_ratio >= 1.5:  # 1.5배 이상 급증
                score += 10  # 10점 (괜찮은 매수세)
            elif vol_ratio >= 1.2:  # 1.2배 이상 증가
                score += 5  # 5점 (약한 매수세)
        
        # [경우 2] 거래대금 보통 (1억~5억원)
        # → 더 높은 급증률 필요 (fake 가능성 있음)
        elif vol_krw >= MIN_VOL:
            if vol_ratio >= 3.0:  # 3배 이상 급증 필요
                score += 15  # 만점
                signals.append(f"거래량급증({vol_ratio:.1f}x,{vol_krw/100000000:.1f}억)")
            elif vol_ratio >= 2.0:  # 2배 이상 급증
                score += 10  # 10점
            elif vol_ratio >= 1.5:  # 1.5배 이상 증가
                score += 5  # 5점
        
        # [경우 3] 거래대금 부족 (1억원 미만)
        # → 매우 높은 급증률 필요 (fake 가능성 높음)
        else:
            if vol_ratio >= 5.0:  # 5배 이상 급증 필요
                score += 10  # 10점 (조심스럽게 인정)
            elif vol_ratio >= 3.0:  # 3배 이상 급증
                score += 5  # 5점 (매우 조심스럽게)
            # 그 외는 점수 없음 (fake 가능성 높아 무시)
        
        # ===== [6] 🆕 2% 목표 저항선 여유 체크 (5점) =====
        # 목적: 매수 후 2% 상승 시 저항선에 막히지 않는지 확인
        # 전략: 저항선까지 여유가 있어야 목표 달성 가능
        
        resistance_clear = indicators['resistance_clearance']  # 저항 여유 %
        
        if resistance_clear > 1.0:  # 2% 상승해도 저항선까지 1% 이상 여유
            score += 5  # 만점 (목표 달성 가능성 높음)
            signals.append("저항여유")
        elif resistance_clear > 0:  # 2% 상승해도 저항선 넘지 않음
            score += 3  # 3점 (목표 달성 가능)
        # 저항 여유 < 0 시 점수 없음 (저항선이 2% 목표가보다 낮음)
        
        # ===== 최종 반환 =====
        return score, signals
    
    def calculate_signal_score(indicators):
        """
        💪 2% 목표 특화 신호 강도 계산 (0~100점)
        
        핵심 전략:
        - 2~3시간 내 2% 수익을 목표로 하므로 초단기 반등 신호에 집중
        - 1분봉 모멘텀 전환을 가장 중요하게 평가 (25점 배정)
        - 변동성에 따라 임계값을 동적으로 조정 (고변동성 시 완화)
        
        점수 구성:
        - 일봉 포지션: 20점 (저점 매수 확정성)
        - 1분봉 모멘텀: 25점 (초단기 진입 타이밍) ← 핵심!
        - 다중 RSI: 15점 (과매도 확인)
        - 다중 BB: 20점 (밴드 하단 확인)
        - 거래량: 15점 (거래 활성도)
        - 2% 저항: 5점 (목표 달성 가능성)
        
        Args:
            indicators: analyze_multi_timeframe()에서 계산된 지표 딕셔너리
        
        Returns:
            (총점, 신호 목록)
            - 총점: 0~100점
            - 신호 목록: 주요 매수 근거 문자열 리스트
        """
        score = 0  # 총점 초기화
        signals = []  # 매수 근거 목록
        
        # ===== [변동성 기반 동적 조정] =====
        # BB 폭(변동성)에 따라 RSI/BB 임계값을 조정
        # 이유: 변동성 장에서는 RSI 30 도달이 어려우므로 기준 완화 필요
        
        vol_score = indicators['volatility_score']  # BB 폭
        
        if vol_score > 5.0:  # 고변동성 (BB 폭 5% 이상)
            bb_relax = 0.10  # BB 임계값 10% 완화
            rsi_relax = 5  # RSI 임계값 5 완화 (예: 30 → 35)
        elif vol_score > 3.0:  # 중변동성 (BB 폭 3~5%)
            bb_relax = 0.05  # BB 임계값 5% 완화
            rsi_relax = 3  # RSI 임계값 3 완화
        else:  # 저변동성 (BB 폭 3% 미만)
            bb_relax = 0.0  # 완화 없음 (기본 임계값 사용)
            rsi_relax = 0
        
        # ===== [1] 일봉 포지션 분석 (20점) =====
        # 목적: 일봉 기준으로 저점인지 고점인지 판단
        # 전략: 오늘 시가보다 낮을수록 좋음 (저점 매수)
        
        daily_open_chg = indicators['daily_change_from_open']  # 오늘 시가 대비 %
        daily_prev_chg = indicators['daily_change_from_prev']  # 어제 종가 대비 %
        
        # 오늘 시가 대비 변화율에 따른 점수 부여
        if daily_open_chg < -2.0:  # 시가 대비 -2% 이상 하락
            score += 20  # 만점 (저점 확정)
            signals.append(f"일봉↓{daily_open_chg:.1f}%")
        elif daily_open_chg < -1.0:  # 시가 대비 -1~-2% 하락
            score += 15  # 15점 (저점 가능성 높음)
            signals.append(f"일봉↓{daily_open_chg:.1f}%")
        elif daily_open_chg < 0:  # 시가 대비 0~-1% 하락
            score += 10  # 10점 (저점 가능성 있음)
            signals.append(f"일봉{daily_open_chg:+.1f}%")
        elif daily_open_chg <= 0.5:  # 시가 대비 0~+0.5% 상승
            score += 5  # 5점 (아직 저점권)
            signals.append("일봉제한")
        # 0.5% 초과 상승 시 점수 없음 (고점 가능성)
        
        # 전일 급락 보너스 (추가 점수)
        if daily_prev_chg < -5.0:  # 어제 -5% 이상 폭락
            score += 5  # 보너스 5점 (과매도 반등 기대)
            signals.append(f"전일↓{daily_prev_chg:.1f}%")
        
        # ===== [2] 🆕 1분봉 초단기 모멘텀 분석 (25점) - 핵심! =====
        # 목적: 2% 목표 달성을 위한 초단기 진입 타이밍 포착
        # 전략: 1분 과매도 + 모멘텀 전환 + BB 하단 + 거래량 급증 조합
        
        rsi_1m = indicators['rsi_1m']  # 1분봉 RSI
        rsi_mom_1m = indicators['rsi_momentum_1m']  # 1분 RSI 모멘텀 (상승 중?)
        price_mom_1m = indicators['price_momentum_1m']  # 1분 가격 모멘텀
        bb_1m_pos = indicators['bb_1m_pos']  # 1분봉 BB 위치
        vol_ratio_1m = indicators['vol_ratio_1m']  # 1분 거래량 급증 배수
        
        # 최고 조건: 4가지 조건 모두 만족 (이상적 진입점)
        # 1. RSI < 35 (과매도)
        # 2. RSI 모멘텀 > 0 (RSI 상승 전환)
        # 3. BB 위치 < 0.30 (하단 30% 이내)
        # 4. 거래량 1.5배 이상 급증
        if (rsi_1m < 35 and rsi_mom_1m > 0 and 
            bb_1m_pos < 0.30 and vol_ratio_1m > 1.5):
            score += 25  # 만점 (완벽한 진입 타이밍)
            signals.append(f"1분반등확인({rsi_1m:.0f})")
        
        # 좋은 조건: 과매도 + 모멘텀 전환 (2가지 조건)
        # RSI가 낮고 상승 전환 시작 = 반등 시작
        elif rsi_1m < 40 and (rsi_mom_1m > 0 or price_mom_1m > 0):
            score += 20  # 20점 (좋은 진입점)
            signals.append(f"1분전환({rsi_1m:.0f})")
        
        # 보통 조건: 과매도만 확인 (1가지 조건)
        # 아직 반등은 시작 안했지만 과매도 상태
        elif rsi_1m < 45:
            score += 10  # 10점 (진입 고려 가능)
            signals.append(f"1분과매도({rsi_1m:.0f})")
        # RSI > 45 시 점수 없음 (아직 과매도 아님)
        
        # ===== [3] 다중 시간프레임 RSI 분석 (15점) =====
        # 목적: 여러 시간프레임에서 동시에 과매도 확인
        # 전략: 짧은 시간프레임(5분)부터 긴 시간프레임(1시간)까지 과매도면 신뢰도 높음
        
        rsi_5m = indicators['rsi_5m']
        rsi_15m = indicators['rsi_15m']
        rsi_1h = indicators['rsi_1h']
        
        # 변동성에 따라 조정된 임계값 적용
        # 예: 고변동성 시 RSI 30 → 35로 완화
        
        # 최고 조건: 5분 + 15분 모두 과매도
        # 두 시간프레임이 모두 과매도 = 강력한 매수 신호
        if rsi_5m <= (30+rsi_relax) and rsi_15m <= (35+rsi_relax):
            score += 15  # 만점
            signals.append(f"RSI과매도({rsi_5m:.0f}/{rsi_15m:.0f})")
        
        # 좋은 조건: 5분만 과매도
        elif rsi_5m <= (35+rsi_relax):
            score += 10  # 10점
            signals.append(f"5분RSI({rsi_5m:.0f})")
        
        # 보통 조건: 5분 중립~약과매도
        elif rsi_5m <= (40+rsi_relax):
            score += 5  # 5점
        # RSI > 40+완화값 시 점수 없음
        
        # ===== [4] 다중 시간프레임 볼린저 밴드 분석 (20점) =====
        # 목적: 여러 시간프레임에서 BB 하단 근접 확인
        # 전략: 5분 하단 + 15분 중하단 = 강력한 반등 가능성
        
        bb_5m_pos = indicators['bb_5m_pos']  # 5분봉 BB 위치 (0~1)
        bb_15m_pos = indicators['bb_15m_pos']  # 15분봉 BB 위치
        bb_1h_pos = indicators['bb_1h_pos']  # 1시간봉 BB 위치
        
        # 변동성에 따라 조정된 임계값 적용
        
        # 최고 조건: 5분 하단 + 15분 중하단
        # 5분은 극단적 하단(20%), 15분은 중하단(50%)
        # → 단기 급락 후 중기 트렌드는 아직 여유 있음
        if bb_5m_pos < (0.20+bb_relax) and bb_15m_pos < (0.50+bb_relax):
            score += 20  # 만점 (이상적 진입점)
            signals.append(f"BB하단({bb_5m_pos*100:.0f}/{bb_15m_pos*100:.0f})")
        
        # 좋은 조건: 5분 하단 + 15분 중간
        elif bb_5m_pos < (0.25+bb_relax) and bb_15m_pos < (0.60+bb_relax):
            score += 15  # 15점
            signals.append(f"BB중하단({bb_5m_pos*100:.0f})")
        
        # 보통 조건: 5분 하단
        elif bb_5m_pos < (0.30+bb_relax):
            score += 10  # 10점
        
        # 주의 조건: 5분 약간 하단
        # 15분이 높아도 5분이 하단이면 일부 점수
        elif bb_5m_pos < (0.35+bb_relax):
            score += 5  # 5점
        # BB 위치 > 35%+완화값 시 점수 없음 (하단 아님)
        
        # ===== [5] 거래량 분석 (15점) =====
        # 목적: 진짜 매수세가 유입되는지 확인 (fake 필터링)
        # 전략: 절대 거래대금과 상대 급증률을 조합하여 판단
        
        vol_ratio = indicators['vol_ratio']  # 5분 거래량 급증 배수
        vol_krw = indicators['vol_absolute_krw']  # 절대 거래대금 (KRW)
        
        # 거래대금 기준선 설정
        MIN_VOL = 100_000_000  # 1억원 (최소 신뢰 기준)
        GOOD_VOL = 500_000_000  # 5억원 (충분한 거래량)
        
        # [경우 1] 거래대금 충분 (5억원 이상)
        # → 상대 급증률을 정상적으로 신뢰 가능
        if vol_krw >= GOOD_VOL:
            if vol_ratio >= 2.0:  # 2배 이상 급증
                score += 15  # 만점 (강력한 매수세)
                signals.append(f"거래량급증({vol_ratio:.1f}x)")
            elif vol_ratio >= 1.5:  # 1.5배 이상 급증
                score += 10  # 10점 (괜찮은 매수세)
            elif vol_ratio >= 1.2:  # 1.2배 이상 증가
                score += 5  # 5점 (약한 매수세)
        
        # [경우 2] 거래대금 보통 (1억~5억원)
        # → 더 높은 급증률 필요 (fake 가능성 있음)
        elif vol_krw >= MIN_VOL:
            if vol_ratio >= 3.0:  # 3배 이상 급증 필요
                score += 15  # 만점
                signals.append(f"거래량급증({vol_ratio:.1f}x,{vol_krw/100000000:.1f}억)")
            elif vol_ratio >= 2.0:  # 2배 이상 급증
                score += 10  # 10점
            elif vol_ratio >= 1.5:  # 1.5배 이상 증가
                score += 5  # 5점
        
        # [경우 3] 거래대금 부족 (1억원 미만)
        # → 매우 높은 급증률 필요 (fake 가능성 높음)
        else:
            if vol_ratio >= 5.0:  # 5배 이상 급증 필요
                score += 10  # 10점 (조심스럽게 인정)
            elif vol_ratio >= 3.0:  # 3배 이상 급증
                score += 5  # 5점 (매우 조심스럽게)
            # 그 외는 점수 없음 (fake 가능성 높아 무시)
        
        # ===== [6] 🆕 2% 목표 저항선 여유 체크 (5점) =====
        # 목적: 매수 후 2% 상승 시 저항선에 막히지 않는지 확인
        # 전략: 저항선까지 여유가 있어야 목표 달성 가능
        
        resistance_clear = indicators['resistance_clearance']  # 저항 여유 %
        
        if resistance_clear > 1.0:  # 2% 상승해도 저항선까지 1% 이상 여유
            score += 5  # 만점 (목표 달성 가능성 높음)
            signals.append("저항여유")
        elif resistance_clear > 0:  # 2% 상승해도 저항선 넘지 않음
            score += 3  # 3점 (목표 달성 가능)
        # 저항 여유 < 0 시 점수 없음 (저항선이 2% 목표가보다 낮음)
        
        # ===== 최종 반환 =====
        return score, signals
    
    # ==================== 메인 로직 시작 ====================
    
    print("\n[START] 복리 매수 시스템 v4.0")
    
    # ===== STEP 1: 자산 현황 파악 =====
    # 목적: 현재 포트폴리오 상태 확인 및 매수 가능 여부 판단
    
    krw_balance = get_krw_balance()  # KRW 잔고
    crypto_value = get_total_crypto_value()  # 암호화폐 평가액
    total_asset = crypto_value + krw_balance  # 총 자산
    
    # 자산 현황 출력 (간결하게)
    print(f"자산: {total_asset:,.0f}원 (암호화폐 {crypto_value/total_asset*100:.0f}%)")
    
    # 최소 주문 금액 체크
    MIN_ORDER = 5000  # Upbit 최소 주문 5,000원
    if krw_balance < MIN_ORDER:
        # KRW 잔고가 부족하면 매수 불가
        return "Insufficient balance", None
    
    # 포지션 상한 체크 (리스크 관리)
    # 총 자산의 80%까지만 암호화폐 보유 허용
    # 이유: 급락 시 추가 매수 여력 확보 및 리스크 분산
    crypto_limit = total_asset * 0.80
    
    if crypto_value >= crypto_limit:
        # 이미 80% 달성 시 추가 매수 중단
        print(f"포지션 상한 도달")
        return "Position limit reached", None
    
    # ===== STEP 2: 종목 선정 또는 검증 =====
    # ticker 파라미터에 따라 두 가지 모드로 작동
    
    if ticker is None:
        # ===== [모드 1] 자동 종목 선정 모드 =====
        # 거래량 상위 종목들을 분석하여 최적 종목 자동 선정
        
        print("종목 자동 선정 중...")
        
        try:
            # 현재 보유 중인 코인 조회 (중복 매수 방지)
            held_coins = get_held_coins()
            
            # 거래량 상위 종목 조회 (예: 상위 50개)
            all_tickers = get_top_volume_tickers()
            
            # 보유하지 않은 종목만 선별 (중복 매수 방지)
            # 이유: 이미 보유한 코인은 평단가 관리가 복잡해짐
            candidates = [t for t in all_tickers if t not in held_coins]
            
            print(f"분석 대상: {len(candidates)}개")
            
        except Exception as e:
            # 종목 목록 조회 실패 시 종료
            return "Ticker fetch failed", None
        
        if not candidates:
            # 분석 가능한 종목이 없으면 종료
            return "No tickers available", None
        
        # ===== 1차 스크리닝 (빠른 필터링) =====
        # 목적: 명백히 부적합한 종목은 빠르게 제외하여 API 호출 절약
        
        primary = []  # 1차 통과 종목 리스트
        
        for t in candidates:
            # 다중 시간프레임 분석 수행
            analysis = analyze_multi_timeframe(t)
            
            # 데이터 조회 실패 시 다음 종목으로
            if not analysis['valid']:
                continue
            
            ind = analysis['indicators']
            
            # ===== [필터 1] 일봉 급등 제외 =====
            # 오늘 시가 대비 0.5% 초과 상승 시 제외
            # 이유: 이미 고점이므로 추가 상승 여력 부족
            if ind['daily_change_from_open'] > 0.5:
                continue
            
            # ===== [필터 2] 전일 급등 제외 =====
            # 어제 대비 8% 이상 상승 시 제외
            # 이유: 과열 가능성, 조정 위험
            if ind['daily_change_from_prev'] > 8.0:
                continue
            
            # ===== [필터 3] 가격 범위 제한 =====
            # 50원 ~ 200,000원 범위만 거래
            # 이유: 너무 싼 코인 = fake 가능성, 너무 비싼 코인 = 변동폭 작음
            if not (50 <= analysis['current_price'] <= 200000):
                continue
            
            # ===== [필터 4] 🆕 2% 목표 저항선 체크 =====
            # 저항선이 2% 목표가보다 1% 이상 낮으면 제외
            # 이유: 목표 달성 불가능
            if ind['resistance_clearance'] < -1.0:
                continue
            
            # ===== 기본 신호 체크 (완화된 조건) =====
            # 1차 스크리닝이므로 완화된 조건 사용
            # 정밀한 평가는 신호 점수 계산에서 수행
            
            has_signal = (
                # RSI: 1분 또는 5분 중 하나라도 과매도
                (ind['rsi_1m'] < 50 or ind['rsi_5m'] < 45) and
                # BB: 1분 또는 5분 중 하나라도 하단
                (ind['bb_1m_pos'] < 0.40 or ind['bb_5m_pos'] < 0.35) and
                # 거래량: 최소한의 활성도
                ind['vol_ratio'] > 0.8
            )
            
            if has_signal:
                # 신호 점수 계산 (정밀 평가)
                score, signals = calculate_signal_score(ind)
                
                # 45점 이상만 1차 통과
                # 이유: 최종 매수 조건은 55점이므로 여유 두고 선별
                if score >= 45:
                    primary.append({
                        'ticker': t,
                        'score': score,
                        'signals': signals,
                        'analysis': analysis
                    })
                    # 1차 통과 종목 간단히 출력
                    print(f"✓ {t}: {score:.0f}점")
            
            # API 호출 제한 방지 (짧은 대기)
            time.sleep(0.02)
        
        print(f"선별: {len(primary)}개")
        
        if not primary:
            # 매수 조건 만족 종목 없음
            return "No candidates found", None
        
        # ===== 최고 점수 종목 선택 =====
        # 점수 기준 내림차순 정렬
        primary.sort(key=lambda x: x['score'], reverse=True)
        best = primary[0]  # 1등 종목
        
        # 선정된 종목 정보 추출
        selected_ticker = best['ticker']
        selected_analysis = best['analysis']
        selected_score = best['score']
        selected_signals = best['signals']
        
        print(f"최종: {selected_ticker} ({selected_score:.0f}점)")
        
    else:
        # ===== [모드 2] 특정 종목 검증 모드 =====
        # 사용자가 지정한 종목의 매수 적정성만 검증
        
        print(f"{ticker} 검증 중...")
        
        # 지정된 종목 분석
        selected_analysis = analyze_multi_timeframe(ticker)
        
        if not selected_analysis['valid']:
            # 데이터 조회 실패
            return "Data fetch failed", None
        
        # 신호 점수 계산
        selected_score, selected_signals = calculate_signal_score(selected_analysis['indicators'])
        selected_ticker = ticker
        
        print(f"신호: {selected_score:.0f}점")
    
    # ===== STEP 3: 최종 매수 검증 =====
    # 선정된 종목이 실제로 매수할 만한지 엄격하게 검증
    
    ind = selected_analysis['indicators']
    current_price = selected_analysis['current_price']
    
    # 핵심 지표 간단히 출력
    print(f"분석: RSI 1m{ind['rsi_1m']:.0f} 5m{ind['rsi_5m']:.0f} | "
          f"BB 5m{ind['bb_5m_pos']*100:.0f}% | Vol {ind['vol_ratio']:.1f}x")
    
    # ===== 안전 검증 (5가지 체크) =====
    # 목적: 극단적 상황에서 매수하지 않도록 안전장치
    
    safety_checks = {
        # [1] RSI 극단 회피: RSI가 10 미만이나 90 초과는 비정상
        'RSI 극단': 10 < ind['rsi_5m'] < 90,
        
        # [2] BB 범위: BB 위치가 -20% 미만이나 120% 초과는 비정상
        # (정상 범위: 0~100%)
        'BB 범위': -0.2 < ind['bb_5m_pos'] < 1.2,
        
        # [3] EMA 지지: 현재가가 장기 EMA의 70% 이상
        # 이유: 너무 멀리 하락하면 추가 하락 위험
        'EMA 지지': current_price > ind['ema_26'] * 0.70,
        
        # [4] 급등락 방지: 최근 가격 변동이 ±20% 이내
        # 이유: 급등락 중에는 진입 타이밍 잡기 어려움
        '급등락 방지': abs(ind['price_momentum']) < 0.20,
        
        # [5] 🆕 2% 저항: 목표가까지 저항선 여유 확인
        # 2% 목표가가 저항선보다 0.5% 이상 낮아야 함
        '🆕 2% 저항': ind['resistance_clearance'] > -0.5
    }
    
    # 통과한 항목 개수 계산
    passed = sum(safety_checks.values())
    
    print(f"안전: {passed}/5")
    
    # ===== 최종 매수 조건 (모두 만족해야 매수) =====
    can_buy = (
        # [조건 1] 신호 강도: 55점 이상
        # 이유: 45~54점은 관망, 55점 이상은 실행
        selected_score >= 55 and
        
        # [조건 2] 안전 검증: 5개 중 4개 이상 통과
        # 이유: 1개 정도는 허용하되 2개 이상 실패 시 위험
        passed >= 4 and
        
        # [조건 3] 일봉 필터: 오늘 시가 대비 0.5% 이하
        # 이유: 저점 매수 원칙
        ind['daily_change_from_open'] <= 0.5 and
        
        # [조건 4] RSI 범위: 10 < RSI < 50
        # 이유: 과매도이되 극단적이지 않은 수준
        10 < ind['rsi_5m'] < 50 and
        
        # [조건 5] BB 위치: 하단 35% 이내
        # 이유: BB 하단 근처가 반등 확률 높음
        ind['bb_5m_pos'] < 0.35 and
        
        # [조건 6] 🆕 1분봉 조건: RSI 45 미만 또는 모멘텀 전환
        # 이유: 초단기 진입 타이밍 확보
        (ind['rsi_1m'] < 45 or ind['rsi_momentum_1m'] > 0)
    )
    
    # 매수 가능 여부 출력
    print(f"매수: {'가능' if can_buy else '불가'} (점수{selected_score}/55, 안전{passed}/4)")
    
    if not can_buy:
        # 매수 조건 미충족 시 종료
        return "Conditions not met", None
    
    # ===== STEP 4: 포지션 사이징 =====
    # 매수 금액 계산 (별도 함수 호출)
    # 켈리 기준 기반 복리 최적화 로직 적용
    
    buy_size = calculate_position_size(
        total_asset=total_asset,  # 총 자산
        crypto_value=crypto_value,  # 현재 암호화폐 평가액
        crypto_limit=crypto_limit,  # 암호화폐 상한 (80%)
        krw_balance=krw_balance,  # KRW 잔고
        signal_score=selected_score,  # 신호 강도
        indicators=ind  # 기술적 지표들
    )
    
    # 최소 주문 금액 체크
    if buy_size < MIN_ORDER:
        return "Buy size too small", None
    
    print(f"매수액: {buy_size:,.0f}원")
    
    # ===== STEP 5: 매수 실행 =====
    # 실제 주문 체결 (최대 2회 시도)
    
    for attempt in range(1, 3):  # 1회, 2회 시도
        try:
            # ===== 가격 재확인 =====
            # 분석 시점과 주문 시점 사이 가격 변동 체크
            verify_price = pyupbit.get_current_price(selected_ticker)
            time.sleep(0.05)  # API 안정성
            
            # 가격 변동률 계산
            price_change = (verify_price - current_price) / current_price
            
            # 급등 시 재확인 (3% 초과 상승)
            if price_change > 0.03:
                print(f"가격 급등, 재확인...")
                time.sleep(2)  # 2초 대기 후 재시도
                continue
            
            # ===== 시장가 매수 주문 =====
            buy_order = upbit.buy_market_order(selected_ticker, buy_size)
            
            # ===== 성공 메시지 생성 =====
            # 신호 점수에 따른 등급 부여
            if selected_score >= 75:
                grade = "PERFECT"  # 완벽한 진입
            elif selected_score >= 65:
                grade = "EXCELLENT"  # 훌륭한 진입
            else:
                grade = "STRONG"  # 강력한 진입
            
            # 간결한 성공 메시지
            success_msg = f"🚀 {grade} 매수 성공\n"
            success_msg += f"{selected_ticker} | {verify_price:,.2f}원 | {buy_size:,.0f}원\n"
            success_msg += f"신호{selected_score:.0f}점 | {', '.join(selected_signals[:2])}\n"
            success_msg += f"총자산: {total_asset:,.0f}원"
            
            # 콘솔 출력
            print(success_msg)
            
            # 디스코드 알림 (설정되어 있다면)
            send_discord_message(success_msg)
            
            # 주문 객체 반환 (성공)
            return buy_order
            
        except Exception as e:
            # 주문 실패 시 처리
            print(f"오류 (시도 {attempt}): {e}")
            
            if attempt < 2:
                # 1회 실패 시 재시도
                time.sleep(2)
            else:
                # 2회 모두 실패 시 에러 메시지
                error_msg = f"매수 실패: {selected_ticker}\n{str(e)}"
                send_discord_message(error_msg)
                return "Order execution failed", None
    
    # 최대 시도 횟수 초과 (여기까지 오면 안됨)
    return "Max attempts exceeded", None

def calculate_position_size(total_asset, crypto_value, crypto_limit, krw_balance, 
                           signal_score, indicators):
    """
    💰 켈리 기준 기반 복리 최적화 포지션 사이징
    
    핵심 아이디어:
    - 단순히 "총자산의 10%씩 매수"가 아니라
    - 승률, 손익비, 자산 규모, 변동성을 모두 고려한 최적 배팅
    - 복리 효과 극대화를 위한 단계별 공격성 조절
    
    켈리 공식 (Kelly Criterion):
        f* = (bp - q) / b
        여기서:
        - f*: 최적 배팅 비율 (자산의 몇 %를 베팅할지)
        - p: 승률 (이길 확률)
        - q: 패율 (질 확률 = 1-p)
        - b: 손익비 (이길 때 수익 / 질 때 손실)
    
    예시:
        승률 60%, 손익비 2.0 (2% 수익 / 1% 손실)
        → f* = (2.0 * 0.6 - 0.4) / 2.0 = 0.4 (40% 배팅)
    
    복리 가속 전략:
        초기 자산 작을 때: 공격적 배팅 (켈리 * 2.0)
        → 빠른 복리 증식 우선
        
        자산 커질수록: 보수적 배팅 (켈리 * 0.6)
        → 자산 보존 우선
    
    Args:
        total_asset: 총 자산 (KRW)
        crypto_value: 현재 암호화폐 평가액 (KRW)
        crypto_limit: 암호화폐 상한 (총자산의 80%)
        krw_balance: KRW 잔고
        signal_score: 신호 강도 점수 (0~100)
        indicators: 기술적 지표 딕셔너리
    
    Returns:
        최적 매수 금액 (KRW)
    """
    
    # ========== [1] 승률 추정 (신호 점수 기반) ==========
    # 신호 점수를 승률로 변환
    # 주의: 실제 승률은 백테스팅으로 검증 필요
    # 여기서는 보수적으로 추정
    
    # 기본 승률 계산 (신호 점수 기반)
    if signal_score >= 75:
        win_rate = 0.70  # 75점 이상: 70% 승률 추정
    elif signal_score >= 65:
        win_rate = 0.65  # 65~74점: 65% 승률 추정
    elif signal_score >= 55:
        win_rate = 0.55  # 55~64점: 55% 승률 추정
    else:
        win_rate = 0.50  # 55점 미만: 50% 승률 (최소)
    
    # ===== 승률 보정 (세부 지표 기반) =====
    # 특정 강력한 신호가 있으면 승률 상향 조정
    
    rsi_5m = indicators['rsi_5m']
    
    # [보정 1] RSI 극단적 과매도
    if rsi_5m < 25:  # RSI 25 미만 (극단적)
        win_rate += 0.05  # 승률 +5%p
    elif rsi_5m < 30:  # RSI 30 미만
        win_rate += 0.03  # 승률 +3%p
    
    # [보정 2] BB 극단적 하단
    bb_5m_pos = indicators['bb_5m_pos']
    
    if bb_5m_pos < 0.15:  # BB 하단 15% 이내 (극단적)
        win_rate += 0.05  # 승률 +5%p
    elif bb_5m_pos < 0.20:  # BB 하단 20% 이내
        win_rate += 0.03  # 승률 +3%p
    
    # [보정 3] 1분봉 모멘텀 전환 확인
    # RSI와 가격이 모두 상승 전환 = 반등 시작 확정
    if indicators['rsi_momentum_1m'] > 0 and indicators['price_momentum_1m'] > 0:
        win_rate += 0.05  # 승률 +5%p
    
    # 승률 상한 제한 (과신 방지)
    # 이론적으로 80% 이상 승률은 불가능
    win_rate = min(win_rate, 0.80)
    
    # ========== [2] 켈리 기준 계산 ==========
    
    # 손익비 설정
    target_profit = 0.02  # 목표 수익 2%
    stop_loss = 0.01  # 손절 기준 1% (안전장치)
    profit_loss_ratio = target_profit / stop_loss  # b = 2.0
    
    # 패율 계산
    lose_rate = 1 - win_rate  # q = 1 - p
    
    # 켈리 공식 적용
    # f* = (bp - q) / b
    # = (2.0 * p - (1-p)) / 2.0
    # = (2.0*p - 1 + p) / 2.0
    # = (3.0*p - 1) / 2.0
    kelly_fraction = (profit_loss_ratio * win_rate - lose_rate) / profit_loss_ratio
    
    # 켈리가 음수면 배팅 안함 (이론적으로 승률 50% 이하)
    if kelly_fraction <= 0:
        return 0.0
    
    # ========== [3] 복리 단계별 공격성 조정 ==========
    # 목표: 10만원 → 10억원
    # 자산 규모에 따라 배팅 공격성 조절
    
    # [단계 1] 초기 자산 (100만원 미만)
    # 목표: 빠른 복리 증식
    # 전략: 공격적 배팅 (켈리 * 2.0)
    # 이유: 손실 절대 금액이 작으므로 공격적 베팅 가능
    if total_asset < 1_000_000:
        aggression_multiplier = 2.0
        stage = "초기공격"
    
    # [단계 2] 중기 자산 (100만원 ~ 1000만원)
    # 목표: 복리 유지하되 점진적 보수화
    # 전략: 선형 감소 (2.0 → 1.0)
    # 이유: 손실 절대 금액이 커지므로 점진적 보수화
    elif total_asset < 10_000_000:
        # 100만원일 때 2.0, 1000만원일 때 1.0
        ratio = (total_asset - 1_000_000) / 9_000_000
        aggression_multiplier = 2.0 - ratio * 1.0
        stage = "중기"
    
    # [단계 3] 성장기 (1000만원 ~ 1억원)
    # 목표: 안정적 복리
    # 전략: 표준 켈리 (1.0)
    # 이유: 적절한 리스크-수익 균형
    elif total_asset < 100_000_000:
        aggression_multiplier = 1.0
        stage = "성장기"
    
    # [단계 4] 보수기 (1억원 이상)
    # 목표: 자산 보존
    # 전략: 보수적 배팅 (켈리 * 0.6)
    # 이유: 큰 자산 손실 방지 우선
    else:
        aggression_multiplier = 0.6
        stage = "보수기"
    
    # 조정된 켈리 비율 계산
    adjusted_kelly = kelly_fraction * aggression_multiplier
    
    # ========== [4] 변동성 기반 조정 ==========
    # 변동성이 클수록 포지션 축소 (리스크 관리)
    
    volatility = indicators['volatility_score']  # BB 폭 (%)
    
    if volatility > 6.0:  # 고변동성 (BB 폭 6% 이상)
        vol_multiplier = 0.7  # 포지션 30% 축소
        # 이유: 변동성 클 때 손실 확대 가능
    elif volatility > 4.0:  # 중변동성 (BB 폭 4~6%)
        vol_multiplier = 0.85  # 포지션 15% 축소
    else:  # 저변동성 (BB 폭 4% 미만)
        vol_multiplier = 1.0  # 조정 없음
        # 이유: 변동성 낮으면 안정적 수익 가능
    
    # 최종 켈리 비율 (변동성 조정 반영)
    final_kelly = adjusted_kelly * vol_multiplier
    
    # ========== [5] 최종 포지션 계산 ==========
    
    # 기본 포지션 = 총자산 * 최종 켈리 비율
    base_position = total_asset * final_kelly
    
    # ===== 상한 제한들 적용 =====
    
    # [제한 1] 80% 상한까지 여유 공간
    # 이미 보유한 암호화폐 + 새로 매수할 금액 ≤ 총자산의 80%
    available_space = crypto_limit - crypto_value
    
    # [제한 2] KRW 잔고 (수수료 0.5% 고려)
    max_krw = krw_balance * 0.995
    
    # [제한 3] 단계별 최대 포지션 비율
    # 한 번에 너무 많이 배팅하는 것 방지
    if total_asset < 1_000_000:
        max_position_ratio = 0.50  # 초기: 최대 50%까지
    elif total_asset < 10_000_000:
        max_position_ratio = 0.30  # 중기: 최대 30%까지
    else:
        max_position_ratio = 0.20  # 성장기 이후: 최대 20%까지
    
    max_position = total_asset * max_position_ratio
    
    # 모든 제한 중 최소값 선택 (가장 보수적인 값)
    buy_size = min(
        base_position,  # 켈리 기준 계산값
        available_space,  # 80% 상한 여유
        max_krw,  # KRW 잔고
        max_position  # 단계별 최대치
    )
    
    # ========== [6] 신호 강도 부스트 (선택적) ==========
    # 매우 강력한 신호일 때 추가 배팅
    
    # 조건: 신호 80점 이상 + 승률 75% 이상
    # → 거의 확실한 기회로 판단
    if signal_score >= 80 and win_rate >= 0.75:
        boost_multiplier = 1.3  # 30% 추가 배팅
        buy_size = min(buy_size * boost_multiplier, max_position)
        # 주의: 여전히 max_position 이하로 제한
    
    # ========== 디버그 로깅 ==========
    # 포지션 계산 과정 간단히 출력
    print(f"포지션 계산: 승률{win_rate*100:.0f}% | 켈리{kelly_fraction*100:.1f}% | "
          f"조정{final_kelly*100:.1f}% | {stage} | 최종{buy_size:,.0f}원")
    
    # 최종 매수 금액 반환
    return buy_size

    
def trade_sell(ticker):
    """
    지능형 적응형 매도 시스템
    - 최소수익률 기준 엄격 적용
    - 손실 구간별 차등 전략
    - 반등 확률 기반 홀딩/매도 결정
    - 시장 상황 적응형 매도 기준
    """

    def calculate_rsi_unified(closes, period=14):
        if len(closes) < period + 1:
            return 50.0
        deltas = np.diff(closes)
        gains = np.where(deltas > 0, deltas, 0)
        losses = np.where(deltas < 0, -deltas, 0)
        
        avg_gain = np.mean(gains[:period])
        avg_loss = np.mean(losses[:period])
        
        for i in range(period, len(closes)-1):
            avg_gain = (avg_gain * (period - 1) + gains[i]) / period
            avg_loss = (avg_loss * (period - 1) + losses[i]) / period
        
        rs = avg_gain / (avg_loss + 1e-8)
        rsi = 100 - (100 / (1 + rs))
        return rsi

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
    current_rsi = calculate_rsi_unified(closes)
    
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
        prev_rsi = calculate_rsi_unified(closes[:-5])
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