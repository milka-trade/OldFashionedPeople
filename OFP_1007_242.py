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

def get_user_input():
    while True:
        try:
            min_rate = float(input("최소 수익률 (예: 1.1): "))
            max_rate = float(input("최대 수익률 (예: 5.0): "))
            sell_time = int(input("매도감시횟수 (예: 20): "))
            rsi_sell_s =int(input("RSI 매도 감시 시작 (예: 65): "))
            rsi_sell_e =int(input("RSI 매도 감시 종료 (예: 80): "))
            break
        except ValueError:
            print("잘못된 입력입니다. 다시 시도하세요.")

    return min_rate, sell_time, rsi_sell_s, rsi_sell_e, max_rate

# 함수 호출 및 결과 저장
min_rate, sell_time, rsi_sell_s, rsi_sell_e, max_rate = get_user_input()

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
    🚀 통합 복리 매수 시스템 v3.0 - 종목 선정부터 매수까지 원스톱
    
    혁신적 개선:
    1. 종목 선정 + 매수 검증 통합 (중복 로직 제거)
    2. 다중 시간프레임 볼린저밴드 (5분/15분/1시간 동시 검증)
    3. 거래량 정규화 (절대 거래대금 + 상대 급증률)
    4. 승률 통계 제거 (불필요한 50% 고정값 삭제)
    5. 일봉 필터 강화 (진정한 저점 매수)
    
    Args:
        ticker: 특정 종목 지정 시 해당 종목만 분석, None이면 자동 선정
    
    Returns:
        매수 주문 객체 또는 (실패 사유, None) 튜플
    """
    
    # ==================== 내부 유틸리티 함수 ====================
    
    def calculate_rsi(closes, period=14):
        """RSI 계산"""
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
        return 100 - (100 / (1 + rs))
    
    def calculate_ema(closes, period=12):
        """EMA 계산"""
        if len(closes) < period:
            return closes[-1]
        ema = [closes[0]]
        alpha = 2 / (period + 1)
        for close in closes[1:]:
            ema.append(alpha * close + (1 - alpha) * ema[-1])
        return ema[-1]
    
    def calculate_bb(closes, window=20, std_dev=2.0):
        """볼린저밴드 계산 (하단, 중간, 상단, 위치%, 폭%)"""
        if len(closes) < window:
            window = len(closes)
        sma = np.mean(closes[-window:])
        std = np.std(closes[-window:])
        lower = sma - (std * std_dev)
        upper = sma + (std * std_dev)
        position = (closes[-1] - lower) / (upper - lower + 1e-8)
        width = (upper - lower) / sma * 100
        return lower, sma, upper, max(0, min(1, position)), width
    
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
        """전체 암호화폐 평가액 (KRW 제외)"""
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
        """보유 중인 코인 목록"""
        try:
            balances = upbit.get_balances()
            return {f"KRW-{b['currency']}" for b in balances 
                   if float(b.get('balance', 0)) > 0 and b['currency'] != 'KRW'}
        except:
            return set()
    
    def calculate_absolute_volume_krw(df, current_price):
        """절대 거래대금 계산 (KRW) - 최근 5분봉 평균"""
        try:
            recent_volumes = df['volume'].values[-5:]
            avg_volume = np.mean(recent_volumes)
            return avg_volume * current_price
        except:
            return 0.0
    
    def analyze_multi_timeframe(ticker_symbol):
        """
        🎯 다중 시간프레임 통합 분석
        
        Returns:
            dict: {
                'valid': bool,
                'data_5m': DataFrame,
                'data_15m': DataFrame,
                'data_1h': DataFrame,
                'data_1d': DataFrame,
                'current_price': float,
                'indicators': dict
            }
        """
        try:
            # === 한 번에 모든 데이터 수집 ===
            df_5m = pyupbit.get_ohlcv(ticker_symbol, interval="minute5", count=50)
            time.sleep(0.1)
            df_15m = pyupbit.get_ohlcv(ticker_symbol, interval="minute15", count=50)
            time.sleep(0.1)
            df_1h = pyupbit.get_ohlcv(ticker_symbol, interval="minute60", count=50)
            time.sleep(0.1)
            df_1d = pyupbit.get_ohlcv(ticker_symbol, interval="day", count=5)
            time.sleep(0.1)
            
            current_price = pyupbit.get_current_price(ticker_symbol)
            
            # 데이터 유효성 검증
            if (df_5m is None or len(df_5m) < 30 or
                df_15m is None or len(df_15m) < 30 or
                df_1h is None or len(df_1h) < 30 or
                df_1d is None or len(df_1d) < 2 or
                current_price is None):
                return {'valid': False}
            
            # === 지표 계산 ===
            closes_5m = df_5m['close'].values
            closes_15m = df_15m['close'].values
            closes_1h = df_1h['close'].values
            volumes_5m = df_5m['volume'].values
            
            # RSI
            rsi_5m = calculate_rsi(closes_5m, 14)
            rsi_15m = calculate_rsi(closes_15m, 14)
            rsi_1h = calculate_rsi(closes_1h, 14)
            
            # 볼린저밴드
            bb_5m_lower, bb_5m_mid, bb_5m_upper, bb_5m_pos, bb_5m_width = calculate_bb(closes_5m, 20)
            bb_15m_lower, bb_15m_mid, bb_15m_upper, bb_15m_pos, bb_15m_width = calculate_bb(closes_15m, 20)
            bb_1h_lower, bb_1h_mid, bb_1h_upper, bb_1h_pos, bb_1h_width = calculate_bb(closes_1h, 20)
            
            # EMA
            ema_12 = calculate_ema(closes_5m, 12)
            ema_26 = calculate_ema(closes_5m, 26)
            
            # 거래량
            vol_recent = np.mean(volumes_5m[-5:])
            vol_normal = np.mean(volumes_5m[-20:-5])
            vol_ratio = vol_recent / (vol_normal + 1e-8)
            vol_absolute_krw = calculate_absolute_volume_krw(df_5m, current_price)
            
            # 모멘텀
            price_momentum = (closes_5m[-1] - closes_5m[-3]) / closes_5m[-3]
            rsi_momentum = rsi_5m - calculate_rsi(closes_5m[:-1], 14)
            
            # 일봉 분석
            daily_open = df_1d['open'].iloc[-1]
            daily_prev_close = df_1d['close'].iloc[-2]
            daily_change_from_open = (current_price - daily_open) / daily_open * 100
            daily_change_from_prev = (current_price - daily_prev_close) / daily_prev_close * 100
            
            # 지지선 근접도
            recent_low = np.min(df_5m['low'].values[-20:])
            support_proximity = (current_price - recent_low) / recent_low * 100
            
            return {
                'valid': True,
                'data_5m': df_5m,
                'data_15m': df_15m,
                'data_1h': df_1h,
                'data_1d': df_1d,
                'current_price': current_price,
                'indicators': {
                    # RSI
                    'rsi_5m': rsi_5m,
                    'rsi_15m': rsi_15m,
                    'rsi_1h': rsi_1h,
                    'rsi_momentum': rsi_momentum,
                    # 볼린저밴드
                    'bb_5m_pos': bb_5m_pos,
                    'bb_5m_width': bb_5m_width,
                    'bb_15m_pos': bb_15m_pos,
                    'bb_15m_width': bb_15m_width,
                    'bb_1h_pos': bb_1h_pos,
                    'bb_1h_width': bb_1h_width,
                    # EMA
                    'ema_12': ema_12,
                    'ema_26': ema_26,
                    # 거래량
                    'vol_ratio': vol_ratio,
                    'vol_absolute_krw': vol_absolute_krw,
                    # 모멘텀
                    'price_momentum': price_momentum,
                    # 일봉
                    'daily_change_from_open': daily_change_from_open,
                    'daily_change_from_prev': daily_change_from_prev,
                    # 지지선
                    'support_proximity': support_proximity
                }
            }
            
        except Exception as e:
            print(f"분석 오류 ({ticker_symbol}): {e}")
            return {'valid': False}
    
    def calculate_signal_score(indicators):
        """
        💪 신호 강도 계산 (0~100점) - 승률 통계 제거, 순수 기술 분석
        
        핵심 개선:
        1. 다중 시간프레임 볼린저밴드 (5분 + 15분 동시 검증)
        2. 거래량 정규화 (절대 + 상대)
        3. 일봉 필터 강화
        """
        score = 0
        signals = []
        
        # [1] 일봉 포지션 (25점) - 저점 매수 확정성
        daily_open_chg = indicators['daily_change_from_open']
        daily_prev_chg = indicators['daily_change_from_prev']
        
        if daily_open_chg < -2.0:
            score += 25
            signals.append(f"일봉시가↓{daily_open_chg:.1f}%")
        elif daily_open_chg < -1.0:
            score += 20
            signals.append(f"일봉시가↓{daily_open_chg:.1f}%")
        elif daily_open_chg < 0:
            score += 15
            signals.append(f"일봉시가{daily_open_chg:+.1f}%")
        elif daily_open_chg <= 1.0:
            score += 10
            signals.append("일봉제한권")
        
        # 전일 급락 보너스
        if daily_prev_chg < -5.0:
            score += 10
            signals.append(f"전일급락{daily_prev_chg:.1f}%")
        
        # [2] 다중 시간프레임 RSI (20점)
        rsi_5m = indicators['rsi_5m']
        rsi_15m = indicators['rsi_15m']
        rsi_1h = indicators['rsi_1h']
        
        # 모든 시간프레임 과매도
        if rsi_5m <= 30 and rsi_15m <= 35 and rsi_1h <= 40:
            score += 20
            signals.append(f"다중RSI과매도({rsi_5m:.0f}/{rsi_15m:.0f}/{rsi_1h:.0f})")
        # 5분+15분 과매도
        elif rsi_5m <= 35 and rsi_15m <= 40:
            score += 15
            signals.append(f"RSI과매도({rsi_5m:.0f}/{rsi_15m:.0f})")
        # 5분만 과매도
        elif rsi_5m <= 40:
            score += 10
            signals.append(f"5분RSI과매도({rsi_5m:.0f})")
        
        # [3] 다중 시간프레임 볼린저밴드 (25점) - 핵심 개선!
        bb_5m_pos = indicators['bb_5m_pos']
        bb_15m_pos = indicators['bb_15m_pos']
        bb_1h_pos = indicators['bb_1h_pos']
        
        # 이상적: 5분 하단 + 15분 중하단 이하 + 1시간 중하단 이하
        if bb_5m_pos < 0.20 and bb_15m_pos < 0.50 and bb_1h_pos < 0.50:
            score += 25
            signals.append(f"다중BB하단({bb_5m_pos*100:.0f}/{bb_15m_pos*100:.0f}/{bb_1h_pos*100:.0f})")
        # 좋음: 5분 하단 + 15분 중하단
        elif bb_5m_pos < 0.25 and bb_15m_pos < 0.60:
            score += 20
            signals.append(f"BB하단권({bb_5m_pos*100:.0f}/{bb_15m_pos*100:.0f})")
        # 보통: 5분 하단 + 15분 중간 이하
        elif bb_5m_pos < 0.30 and bb_15m_pos < 0.70:
            score += 15
            signals.append(f"BB중하단({bb_5m_pos*100:.0f}/{bb_15m_pos*100:.0f})")
        # 주의: 5분만 하단 (15분은 높음) - 감점은 안하되 낮은 점수
        elif bb_5m_pos < 0.35:
            score += 8
            signals.append(f"5분BB하단({bb_5m_pos*100:.0f})")
        
        # [4] 거래량 정규화 (20점) - 핵심 개선!
        vol_ratio = indicators['vol_ratio']
        vol_krw = indicators['vol_absolute_krw']
        
        # 절대 거래대금 기준 (1억원 = 100M)
        MIN_VOLUME_KRW = 100_000_000  # 1억원
        GOOD_VOLUME_KRW = 500_000_000  # 5억원
        
        # 거래대금이 충분할 때만 상대 급증률 신뢰
        if vol_krw >= GOOD_VOLUME_KRW:
            # 거래대금 충분: 상대 급증률 정상 적용
            if vol_ratio >= 2.0:
                score += 20
                signals.append(f"거래량급증({vol_ratio:.1f}x,{vol_krw/100000000:.1f}억)")
            elif vol_ratio >= 1.5:
                score += 15
                signals.append(f"거래량증가({vol_ratio:.1f}x,{vol_krw/100000000:.1f}억)")
            elif vol_ratio >= 1.2:
                score += 10
                signals.append(f"거래량보통({vol_ratio:.1f}x)")
        elif vol_krw >= MIN_VOLUME_KRW:
            # 거래대금 보통: 더 높은 급증률 필요
            if vol_ratio >= 3.0:
                score += 15
                signals.append(f"거래량급증({vol_ratio:.1f}x,{vol_krw/100000000:.1f}억)")
            elif vol_ratio >= 2.0:
                score += 10
                signals.append(f"거래량증가({vol_ratio:.1f}x)")
            elif vol_ratio >= 1.5:
                score += 5
                signals.append(f"거래량약증가({vol_ratio:.1f}x)")
        else:
            # 거래대금 부족: 매우 높은 급증률 필요 (fake 필터링)
            if vol_ratio >= 5.0:
                score += 10
                signals.append(f"저거래량급증({vol_ratio:.1f}x)")
            elif vol_ratio >= 3.0:
                score += 5
                signals.append(f"저거래량증가({vol_ratio:.1f}x)")
            # 그 외는 점수 없음 (fake 가능성)
        
        # [5] 모멘텀 (10점)
        if indicators['rsi_momentum'] > 0 and indicators['price_momentum'] > 0:
            score += 10
            signals.append("모멘텀전환")
        elif indicators['price_momentum'] > -0.01:
            score += 5
            signals.append("횡보중")
        
        return score, signals
    
    # ==================== 메인 로직 시작 ====================
    
    print("\n" + "="*80)
    print("통합 복리 매수 시스템 v3.0 시작")
    print("="*80)
    
    # ========== STEP 1: 자산 현황 ==========
    krw_balance = get_krw_balance()
    crypto_value = get_total_crypto_value()
    total_asset = crypto_value + krw_balance
    
    print(f"\n자산 현황:")
    print(f"   암호화폐: {crypto_value:,.0f}원 ({crypto_value/total_asset*100:.1f}%)")
    print(f"   KRW: {krw_balance:,.0f}원")
    print(f"   총자산: {total_asset:,.0f}원")
    
    MIN_ORDER = 5000
    if krw_balance < MIN_ORDER:
        print(f"원화 부족: {krw_balance:,.0f}원")
        return "Insufficient balance", None
    
    # 포지션 상한 체크
    crypto_limit = total_asset * 0.80
    if crypto_value >= crypto_limit:
        print(f"포지션 상한 도달 ({crypto_value/total_asset*100:.0f}%)")
        return "Position limit reached", None
    
    # ========== STEP 2: 종목 선정 또는 검증 ==========
    
    if ticker is None:
        # === 자동 종목 선정 모드 ===
        print("\n최적 종목 자동 선정 중...")
        
        try:
            held_coins = get_held_coins()
            all_tickers = get_top_volume_tickers()
            candidates_tickers = [t for t in all_tickers if t not in held_coins]
            
            print(f"   분석 대상: {len(candidates_tickers)}개")
            
        except Exception as e:
            print(f"종목 목록 조회 실패: {e}")
            return "Ticker fetch failed", None
        
        if not candidates_tickers:
            print("분석 가능한 종목이 없습니다")
            return "No tickers available", None
        
        # 1차 스크리닝
        primary_candidates = []
        
        for t in candidates_tickers:
            analysis = analyze_multi_timeframe(t)
            
            if not analysis['valid']:
                continue
            
            ind = analysis['indicators']
            
            # 빠른 필터링
            if ind['daily_change_from_open'] > 1.0:  # 일봉 시가 대비 1% 초과 제외
                continue
            
            if ind['daily_change_from_prev'] > 10.0:  # 전일 대비 10% 이상 급등 제외
                continue
            
            if not (50 <= analysis['current_price'] <= 200000):  # 가격 범위
                continue
            
            # 기본 신호 체크 (완화된 조건)
            has_signal = (
                (ind['rsi_5m'] < 45 or ind['rsi_15m'] < 50) and
                (ind['bb_5m_pos'] < 0.35 or ind['bb_15m_pos'] < 0.60) and
                ind['vol_ratio'] > 0.8
            )
            
            if has_signal:
                score, signals = calculate_signal_score(ind)
                
                if score >= 40:  # 40점 이상만 1차 통과
                    primary_candidates.append({
                        'ticker': t,
                        'score': score,
                        'signals': signals,
                        'analysis': analysis
                    })
                    print(f"   1차 통과: {t}: {score:.0f}점 - {signals[0] if signals else ''}")
            
            time.sleep(0.02)
        
        print(f"\n1차 결과: {len(primary_candidates)}개 선별")
        
        if not primary_candidates:
            print("매수 조건을 만족하는 종목이 없습니다")
            return "No candidates found", None
        
        # 최고 점수 종목 선택
        primary_candidates.sort(key=lambda x: x['score'], reverse=True)
        best_candidate = primary_candidates[0]
        
        selected_ticker = best_candidate['ticker']
        selected_analysis = best_candidate['analysis']
        selected_score = best_candidate['score']
        selected_signals = best_candidate['signals']
        
        print(f"\n최종 선정: {selected_ticker} ({selected_score:.0f}점)")
        
    else:
        # === 특정 종목 검증 모드 ===
        print(f"\n{ticker} 매수 적정성 검증 중...")
        
        selected_analysis = analyze_multi_timeframe(ticker)
        
        if not selected_analysis['valid']:
            print(f"데이터 조회 실패")
            return "Data fetch failed", None
        
        selected_score, selected_signals = calculate_signal_score(selected_analysis['indicators'])
        selected_ticker = ticker
        
        print(f"   신호 강도: {selected_score:.0f}점")
    
    # ========== STEP 3: 최종 매수 검증 ==========
    
    ind = selected_analysis['indicators']
    current_price = selected_analysis['current_price']
    
    print(f"\n기술적 분석:")
    print(f"   일봉: 시가{ind['daily_change_from_open']:+.1f}% / 전일{ind['daily_change_from_prev']:+.1f}%")
    print(f"   RSI: 5분{ind['rsi_5m']:.0f} / 15분{ind['rsi_15m']:.0f} / 1시간{ind['rsi_1h']:.0f}")
    print(f"   BB위치: 5분{ind['bb_5m_pos']*100:.0f}% / 15분{ind['bb_15m_pos']*100:.0f}% / 1시간{ind['bb_1h_pos']*100:.0f}%")
    print(f"   거래량: {ind['vol_ratio']:.1f}배 ({ind['vol_absolute_krw']/100000000:.1f}억원)")
    print(f"   신호: {', '.join(selected_signals[:3])}")
    
    # 안전 검증
    safety_checks = {
        'RSI 극단 회피': 10 < ind['rsi_5m'] < 90,
        'BB 범위': -0.2 < ind['bb_5m_pos'] < 1.2,
        'EMA 지지': current_price > ind['ema_26'] * 0.75,
        '급등락 방지': abs(ind['price_momentum']) < 0.25
    }
    
    passed = sum(safety_checks.values())
    
    print(f"\n안전 검증: {passed}/4")
    for name, ok in safety_checks.items():
        print(f"   {'[O]' if ok else '[X]'} {name}")
    
    # 최종 조건
    can_buy = (
        selected_score >= 50 and  # 50점 이상
        passed >= 3 and  # 안전 검증 3/4 이상
        ind['daily_change_from_open'] <= 1.0 and  # 일봉 시가 대비 1% 이하
        10 < ind['rsi_5m'] < 55 and  # RSI 범위
        ind['bb_5m_pos'] < 0.40  # BB 하단권
    )
    
    print(f"\n매수 판단:")
    print(f"   신호강도: {'[O]' if selected_score >= 50 else '[X]'} ({selected_score:.0f}점/50)")
    print(f"   안전검증: {'[O]' if passed >= 3 else '[X]'} ({passed}/3)")
    print(f"   일봉필터: {'[O]' if ind['daily_change_from_open'] <= 1.0 else '[X]'}")
    print(f"   BB위치: {'[O]' if ind['bb_5m_pos'] < 0.40 else '[X]'}")
    
    if not can_buy:
        print("\n매수 조건 미충족")
        return "Conditions not met", None
    
    # ========== STEP 4: 포지션 사이징 ==========
    
    # 신호 강도 기반 승수
    if selected_score >= 80:
        position_mult = 1.8
    elif selected_score >= 70:
        position_mult = 1.5
    elif selected_score >= 60:
        position_mult = 1.2
    else:
        position_mult = 1.0
    
    base_position = total_asset * 0.10
    target_position = base_position * position_mult
    
    available_space = crypto_limit - crypto_value
    
    buy_size = min(
        target_position,
        krw_balance * 0.995,
        available_space
    )
    
    if buy_size < MIN_ORDER:
        print(f"매수 금액 부족: {buy_size:.0f}원")
        return "Buy size too small", None
    
    print(f"\n포지션 계산:")
    print(f"   기본 (총자산 10%): {base_position:,.0f}원")
    print(f"   승수: {position_mult:.2f}x (신호 {selected_score:.0f}점)")
    print(f"   목표: {target_position:,.0f}원")
    print(f"   최종: {buy_size:,.0f}원")
    
    expected_crypto = crypto_value + buy_size
    expected_ratio = expected_crypto / total_asset
    
    print(f"\n매수 후 예상:")
    print(f"   암호화폐: {expected_crypto:,.0f}원 ({expected_ratio*100:.1f}%)")
    print(f"   여유: {crypto_limit - expected_crypto:,.0f}원")
    
    # ========== STEP 5: 매수 실행 ==========
    
    for attempt in range(1, 3):
        try:
            print(f"\n매수 실행 {attempt}/2...")
            
            # 가격 재확인
            verify_price = pyupbit.get_current_price(selected_ticker)
            time.sleep(0.05)
            
            price_change = (verify_price - current_price) / current_price
            if price_change > 0.05:
                print(f"가격 급등 ({price_change:+.2%}), 재확인...")
                time.sleep(2)
                continue
            
            # 주문
            buy_order = upbit.buy_market_order(selected_ticker, buy_size)
            
            # 성공 메시지
            grade = "PERFECT" if selected_score >= 80 else "EXCELLENT" if selected_score >= 70 else "STRONG"
            
            success_msg = f"{grade} 복리 매수 성공!\n"
            success_msg += f"━━━━━━━━━━━━━━━━━━━━\n"
            success_msg += f"{selected_ticker}\n"
            success_msg += f"가격: {verify_price:,.2f}원\n"
            success_msg += f"금액: {buy_size:,.0f}원 ({position_mult:.2f}x)\n"
            success_msg += f"━━━━━━━━━━━━━━━━━━━━\n"
            success_msg += f"신호: {selected_score:.0f}점\n"
            success_msg += f"일봉: 시가{ind['daily_change_from_open']:+.1f}% 전일{ind['daily_change_from_prev']:+.1f}%\n"
            success_msg += f"RSI: 5m{ind['rsi_5m']:.0f} 15m{ind['rsi_15m']:.0f} 1h{ind['rsi_1h']:.0f}\n"
            success_msg += f"BB: 5m{ind['bb_5m_pos']*100:.0f}% 15m{ind['bb_15m_pos']*100:.0f}%\n"
            success_msg += f"거래량: {ind['vol_ratio']:.1f}x ({ind['vol_absolute_krw']/100000000:.1f}억)\n"
            success_msg += f"{', '.join(selected_signals[:2])}\n"
            success_msg += f"━━━━━━━━━━━━━━━━━━━━\n"
            success_msg += f"총자산: {total_asset:,.0f}원\n"
            success_msg += f"예상 암호화폐: {expected_crypto:,.0f}원 ({expected_ratio*100:.0f}%)"
            
            print(success_msg)
            send_discord_message(success_msg)
            
            return buy_order
            
        except Exception as e:
            print(f"매수 오류 (시도 {attempt}): {e}")
            if attempt < 2:
                time.sleep(2)
            else:
                error_msg = f"매수 실패: {selected_ticker}\n에러: {str(e)}"
                print(error_msg)
                send_discord_message(error_msg)
                return "Order execution failed", None
    
    return "Max attempts exceeded", None
    
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
    trade_start = datetime.now().strftime('%m/%d %H시%M분%S초')
    trade_msg = f'🚀 {trade_start} 통합 복리 매수 시스템 v3.0\n'
    trade_msg += f'📊 설정: 수익률 {min_rate}%~{max_rate}% | 매도시도 {sell_time}회 | 손절 {cut_rate}%\n'
    trade_msg += f'📈 RSI 매수: {rsi_buy_s}~{rsi_buy_e} | RSI 매도: {rsi_sell_s}~{rsi_sell_e}\n'
    trade_msg += f'💡 개선사항: 조건완화, 병렬처리, 자동보고'
    
    print("="*50)
    print(trade_msg)
    print("="*50)
    send_discord_message(trade_msg)
    
    # # 메인 매매 로직 실행
    # buying_logic()
    try:
        buying_logic()
    except KeyboardInterrupt:
        print("\n\n프로그램이 종료되었습니다.")
    except Exception as e:
        print(f"\n\n치명적 오류: {e}")

        send_discord_message(f"시스템 종료: {e}")
