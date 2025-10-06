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
            min_rate = float(input("최소 수익률 (예: 0.7): "))
            max_rate = float(input("최대 수익률 (예: 2.5): "))
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
    전략적으로 선별된 10개 메이저 코인 반환 (고정 리스트)
    
    핵심 전략:
    - 시가총액 상위 10개 메이저 코인 고정
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
    
def get_best_ticker():
    """
    🎯 개선된 반등 포착 시스템 v2.0 - 일봉 필터 강화 및 2% 수익 최적화
    
    핵심 개선사항:
    1. 일봉 시가 대비 +1.0% 초과 종목 제외 (진정한 저점 매수)
    2. 변동성 필터 추가 (2% 수익 가능성 검증)
    3. 지지선 근접도 계산 (바닥 확인)
    4. 모멘텀 전환 감지 (반등 확정 신호)
    5. 확신도 계산 재설계 (2% 수익 달성 확률 중심)
    """
    
    # ========== STEP 1: 동적 상위 코인 목록 추출 ==========
    try:
        # 보유 코인 목록 추출
        balances = upbit.get_balances()
        held_coins = {f"KRW-{b['currency']}" for b in balances if float(b.get('balance', 0)) > 0}
        
        # 동적으로 상위 거래대금 코인 추출
        all_tickers = get_top_volume_tickers()
        all_tickers = [t for t in all_tickers if t not in held_coins]
        
        print(f"🎯 반등 포착 시스템 v2.0 시작 - 분석 대상: {len(all_tickers)}개")
        
    except Exception as e:
        print(f"❌ 초기화 실패: {e}")
        return None
    
    if not all_tickers:
        print("💡 분석 대상 코인이 없습니다.")
        return None
        
    # ========== STEP 2: 강화된 1차 스크리닝 - 일봉 필터 추가 ==========
    print("🔍 1차 스크리닝: 일봉 필터 + 반등 신호 감지 중...")
    
    primary_candidates = []
    
    def calculate_rsi_unified(prices, period=14):
        """통일된 RSI 계산 함수"""
        if len(prices) < period + 1:
            return 50.0
        deltas = np.diff(prices)
        gains = np.where(deltas > 0, deltas, 0)
        losses = np.where(deltas < 0, -deltas, 0)
        
        avg_gain = np.mean(gains[:period])
        avg_loss = np.mean(losses[:period])
        
        for i in range(period, len(prices)-1):
            avg_gain = (avg_gain * (period - 1) + gains[i]) / period
            avg_loss = (avg_loss * (period - 1) + losses[i]) / period

        rs = avg_gain / (avg_loss + 1e-8)
        rsi = 100 - (100 / (1 + rs))
        return rsi
    
    for ticker in all_tickers:
        try:
            # === 일봉 데이터 먼저 확인 (필수 필터) ===
            df_1d = pyupbit.get_ohlcv(ticker, interval="day", count=5)
            current_price = pyupbit.get_current_price(ticker)
            
            if df_1d is None or len(df_1d) < 2 or current_price is None:
                time.sleep(0.05)
                continue
            
            # === 🚨 핵심 필터 1: 일봉 시가 대비 +1.0% 초과 제외 ===
            daily_open = df_1d['open'].iloc[-1]
            daily_change_from_open = (current_price - daily_open) / daily_open * 100
            
            if daily_change_from_open > 1.0:
                # 이미 상승한 종목은 반등 타이밍 아님
                time.sleep(0.02)
                continue
            
            # === 추가 필터: 전일 대비 하락 종목 우선 (과매도 반등) ===
            prev_close = df_1d['close'].iloc[-2]
            daily_change_from_prev = (current_price - prev_close) / prev_close * 100
            
            # 전일 대비 -5% 이상 하락 시 우선순위 부여
            is_oversold_daily = daily_change_from_prev < -5.0
            
            # === 5분봉 데이터 로드 ===
            df_5m = pyupbit.get_ohlcv(ticker, interval="minute5", count=50)
            
            if df_5m is None or len(df_5m) < 30:
                time.sleep(0.05)
                continue
            
            closes = df_5m['close'].values
            volumes = df_5m['volume'].values
            highs = df_5m['high'].values
            lows = df_5m['low'].values
            
            # === 볼린저밴드 반등 패턴 감지 ===
            bb_period = 20
            sma20 = np.mean(closes[-bb_period:])
            std20 = np.std(closes[-bb_period:])
            bb_lower = sma20 - (2.0 * std20)
            bb_upper = sma20 + (2.0 * std20)
            bb_width = (bb_upper - bb_lower) / sma20 * 100
            
            bb_position = (current_price - bb_lower) / (bb_upper - bb_lower) * 100
            
            # 🎯 변동성 필터 완화 (2% 수익 가능성은 있되 너무 제한적이지 않게)
            volatility_sufficient = bb_width >= 2.5  # BB 폭 2.5% 이상 (완화)
            
            # 하단 근접 또는 돌파 패턴
            bb_breakthrough = False
            recent_closes = closes[-3:]
            for price in recent_closes:
                if price <= bb_lower * 1.03:  # 하단 3% 이내
                    bb_breakthrough = True
                    break
            
            # === RSI 과매도 반등 감지 ===
            current_rsi = calculate_rsi_unified(closes)
            
            # 🚨 핵심 개선 3: RSI 상승 전환 확인 (모멘텀 전환)
            rsi_uptrend = False
            if len(closes) >= 17:
                prev_rsi = calculate_rsi_unified(closes[:-2])
                rsi_uptrend = current_rsi > prev_rsi and current_rsi > 25
            
            # === 거래량 급증 확인 ===
            recent_volume = np.mean(volumes[-3:])
            avg_volume = np.mean(volumes[-15:-3])
            volume_surge = recent_volume / (avg_volume + 1e-8)
            
            # === 🚨 핵심 개선 4: 지지선 근접도 계산 (바닥 확인) ===
            recent_low = np.min(lows[-20:])  # 최근 20개 캔들 최저가
            support_proximity = (current_price - recent_low) / recent_low * 100
            near_support = support_proximity < 2.0  # 최근 저점 대비 2% 이내
            
            # === 🚨 핵심 개선 5: 모멘텀 전환 감지 (5분봉 상승 패턴) ===
            momentum_reversal = False
            if len(closes) >= 4:
                # 최근 3개 캔들 중 2개 이상 상승
                recent_3_candles = closes[-3:]
                rising_count = sum([recent_3_candles[i] > recent_3_candles[i-1] for i in range(1, 3)])
                momentum_reversal = rising_count >= 2
            
            # === 가격 변화율 확인 ===
            price_change_5m = (closes[-1] - closes[-6]) / closes[-6] * 100 if len(closes) >= 6 else 0
            
            # === 강화된 1차 통과 조건 (기회 포착 중심) ===
            bb_signal = (bb_breakthrough or bb_position < 30) and volatility_sufficient
            rsi_signal = (current_rsi <= 45 and rsi_uptrend) or current_rsi <= 32  # 완화
            volume_signal = volume_surge >= 1.2  # 거래량 1.2배 이상 (완화)
            support_signal = near_support or support_proximity < 3.0  # 지지선 3% 이내 (완화)
            momentum_signal = momentum_reversal or price_change_5m > -2.5  # 완화
            
            # 기본 필터
            price_valid = 50 <= current_price <= 200000
            
            # 일봉 필터 (시가 대비 +1.0% 이하만 통과)
            daily_filter_pass = daily_change_from_open <= 1.0
            
            # 급등 제외 (당일 시가 대비가 아닌 전일 종가 대비)
            not_surged = daily_change_from_prev < 10.0
            
            # 🎯 1차 통과 조건 완화 (5개 신호 중 2개 이상 + 기본 조건)
            # 이유: 2% 기회를 놓치지 않기 위해 조건 완화, 2차에서 정밀 검증
            signals = [bb_signal, rsi_signal, volume_signal, support_signal, momentum_signal]
            signal_count = sum(signals)
            
            if signal_count >= 2 and price_valid and daily_filter_pass and not_surged:
                primary_candidates.append({
                    'ticker': ticker,
                    'current_rsi': current_rsi,
                    'volume_surge': volume_surge,
                    'daily_change_from_open': daily_change_from_open,
                    'daily_change_from_prev': daily_change_from_prev,
                    'current_price': current_price,
                    'bb_position': bb_position,
                    'bb_width': bb_width,
                    'price_change_5m': price_change_5m,
                    'signal_count': signal_count,
                    'support_proximity': support_proximity,
                    'is_oversold_daily': is_oversold_daily,
                    'momentum_reversal': momentum_reversal
                })
                
                oversold_mark = "📉전일급락" if is_oversold_daily else ""
                print(f"✅ 1차 통과: {ticker} {oversold_mark} (시가대비:{daily_change_from_open:+.1f}%, RSI:{current_rsi:.1f}, 신호{signal_count}개)")
            
            time.sleep(0.02)
            
        except Exception as e:
            continue
    
    print(f"🔍 1차 결과: {len(all_tickers)}개 → {len(primary_candidates)}개 선별")
    
    if not primary_candidates:
        print("💡 일봉 필터 통과 + 반등 신호가 감지된 종목이 없습니다.")
        return None
        
    # ========== STEP 3: 재설계된 2차 정밀 분석 - 2% 수익 확률 중심 ==========
    print("🎯 2차 정밀 분석: 2% 수익 달성 확률 검증 중...")
    
    final_candidates = []
    
    for candidate in primary_candidates:
        try:
            ticker = candidate['ticker']
            
            df_1h = pyupbit.get_ohlcv(ticker, interval="minute60", count=30)
            
            if df_1h is None or len(df_1h) < 20:
                time.sleep(0.05)
                continue
            
            closes = df_1h['close'].values
            volumes = df_1h['volume'].values
            current_price = candidate['current_price']
            
            # === 1시간봉 RSI 분석 ===
            current_rsi_1h = calculate_rsi_unified(closes)
            
            # 1시간봉 RSI 상승 전환
            rsi_1h_uptrend = False
            if len(closes) >= 17:
                prev_rsi_1h = calculate_rsi_unified(closes[:-2])
                rsi_1h_uptrend = current_rsi_1h > prev_rsi_1h
            
            # === 1시간봉 볼린저밴드 분석 ===
            bb_period = 20
            sma20_1h = np.mean(closes[-bb_period:])
            std20_1h = np.std(closes[-bb_period:])
            bb_lower_1h = sma20_1h - (2.0 * std20_1h)
            bb_upper_1h = sma20_1h + (2.0 * std20_1h)
            bb_position_1h = (current_price - bb_lower_1h) / (bb_upper_1h - bb_lower_1h) * 100
            bb_width_1h = (bb_upper_1h - bb_lower_1h) / sma20_1h * 100
            
            # 1시간봉 변동성 충분
            volatility_1h_ok = bb_width_1h >= 5.0
            
            # === 1시간봉 거래량 분석 ===
            recent_vol_1h = np.mean(volumes[-3:])
            normal_vol_1h = np.mean(volumes[-12:-3])
            volume_expansion_1h = recent_vol_1h / (normal_vol_1h + 1e-8)
            
            # === 🚨 재설계된 확신도 계산 (0-100점, 2% 수익 달성 확률 중심) ===
            confidence = 0
            signals = []
            
            # [1] 일봉 포지션 (20점 만점) - 저점 매수 확정성
            if candidate['daily_change_from_open'] < -2.0:
                confidence += 20
                signals.append(f"일봉시가대비{candidate['daily_change_from_open']:.1f}%하락")
            elif candidate['daily_change_from_open'] < 0:
                confidence += 15
                signals.append(f"일봉시가대비{candidate['daily_change_from_open']:.1f}%")
            elif candidate['daily_change_from_open'] <= 1.0:
                confidence += 10
                signals.append("일봉상승제한권")
            
            # 전일 급락 보너스 (반등 강도 높음)
            if candidate['is_oversold_daily']:
                confidence += 10
                signals.append("전일급락반등")
            
            # [2] 다중 시간대 RSI (25점 만점) - 과매도 확정성
            rsi_5m = candidate['current_rsi']
            
            # 5분 + 1시간 모두 과매도
            if rsi_5m <= 30 and current_rsi_1h <= 35:
                confidence += 25
                signals.append(f"다중RSI과매도(5m:{rsi_5m:.0f},1h:{current_rsi_1h:.0f})")
            # 5분 과매도 + 1시간 상승 전환
            elif rsi_5m <= 35 and rsi_1h_uptrend:
                confidence += 20
                signals.append(f"RSI반등전환(5m:{rsi_5m:.0f}↑)")
            # 5분만 과매도
            elif rsi_5m <= 40:
                confidence += 15
                signals.append(f"5분RSI과매도({rsi_5m:.0f})")
            
            # [3] 다중 시간대 BB (20점 만점) - 저점 확정성
            bb_5m = candidate['bb_position']
            
            # 5분 + 1시간 모두 하단권
            if bb_5m < 20 and bb_position_1h < 30:
                confidence += 20
                signals.append(f"다중BB하단(5m:{bb_5m:.0f}%,1h:{bb_position_1h:.0f}%)")
            # 5분 하단 + 1시간 중하단
            elif bb_5m < 25 and bb_position_1h < 50:
                confidence += 15
                signals.append(f"BB하단권(5m:{bb_5m:.0f}%)")
            # 5분만 하단
            elif bb_5m < 30:
                confidence += 10
                signals.append(f"5분BB하단({bb_5m:.0f}%)")
            
            # [4] 변동성 충분성 (10점 만점) - 2% 수익 가능성
            if candidate['bb_width'] >= 5.0 and volatility_1h_ok:
                confidence += 10
                signals.append(f"변동성충분(5m:{candidate['bb_width']:.1f}%)")
            elif candidate['bb_width'] >= 3.0:
                confidence += 5
                signals.append("변동성보통")
            
            # [5] 거래량 급증 (15점 만점) - 반등 추진력
            if candidate['volume_surge'] >= 2.0 and volume_expansion_1h >= 1.5:
                confidence += 15
                signals.append(f"다중거래량급증(5m:{candidate['volume_surge']:.1f}x)")
            elif candidate['volume_surge'] >= 1.5:
                confidence += 10
                signals.append(f"5분거래량급증({candidate['volume_surge']:.1f}x)")
            elif candidate['volume_surge'] >= 1.3:
                confidence += 5
                signals.append(f"거래량증가({candidate['volume_surge']:.1f}x)")
            
            # [6] 모멘텀 전환 (10점 만점) - 반등 시작 확정
            if candidate['momentum_reversal']:
                confidence += 10
                signals.append("모멘텀반등전환")
            elif candidate['price_change_5m'] > 0:
                confidence += 5
                signals.append("단기상승중")
            
            # [7] 지지선 근접 보너스 (5점) - 추가 하락 제한
            if candidate['support_proximity'] < 1.0:
                confidence += 5
                signals.append("최근저점밀착")
            
            # === 🎯 확신도 55점 이상만 통과 (기회 포착 vs 리스크 균형) ===
            # 이유: 65점은 너무 보수적. 55점으로 완화하여 진짜 기회 놓치지 않음
            if confidence >= 55:
                final_candidates.append({
                    'ticker': ticker,
                    'confidence': confidence,
                    'current_rsi': candidate['current_rsi'],
                    'current_rsi_1h': current_rsi_1h,
                    'bb_position': candidate['bb_position'],
                    'bb_position_1h': bb_position_1h,
                    'volume_surge': candidate['volume_surge'],
                    'volume_expansion_1h': volume_expansion_1h,
                    'signals': signals,
                    'current_price': current_price,
                    'daily_change_from_open': candidate['daily_change_from_open'],
                    'daily_change_from_prev': candidate['daily_change_from_prev'],
                    'is_oversold_daily': candidate['is_oversold_daily']
                })
                
                grade = "🚀 PERFECT" if confidence >= 85 else "⭐ EXCELLENT" if confidence >= 75 else "✅ STRONG" if confidence >= 65 else "📊 GOOD"
                print(f"{grade}: {ticker} (확신도:{confidence}점)")
                print(f"  └ {', '.join(signals[:3])}")
            
            time.sleep(0.05)
            
        except Exception as e:
            continue
    
    print(f"🎯 2차 결과: {len(primary_candidates)}개 → {len(final_candidates)}개 최종 선별")
    
    # ========== STEP 4: 최고 확신도 종목 선택 ==========
    if not final_candidates:
        print("💡 확신도 55점 이상의 2% 수익 기회가 없습니다.")
        return None
    
    # 확신도 기준 정렬
    final_candidates.sort(key=lambda x: x['confidence'], reverse=True)
    best = final_candidates[0]
    
    # 결과 출력
    confidence_level = "🚀 완벽한 반등" if best['confidence'] >= 85 else "⭐ 강력한 반등" if best['confidence'] >= 75 else "✅ 확실한 반등" if best['confidence'] >= 65 else "📊 양호한 반등"
    
    daily_status = f"전일 {best['daily_change_from_prev']:+.1f}% {'📉급락' if best['is_oversold_daily'] else ''}"
    
    print("=" * 80)
    print(f"🎯 **반등 포착 완료**: {best['ticker']}")
    print(f"📊 **확신도**: {best['confidence']}점 ({confidence_level})")
    print(f"📅 **일봉**: 시가대비 {best['daily_change_from_open']:+.1f}% | {daily_status}")
    print(f"📈 **5분봉**: RSI {best['current_rsi']:.1f} | BB {best['bb_position']:.0f}% | 거래량 {best['volume_surge']:.1f}배")
    print(f"📈 **1시간봉**: RSI {best['current_rsi_1h']:.1f} | BB {best['bb_position_1h']:.0f}% | 거래량 {best['volume_expansion_1h']:.1f}배")
    print(f"🔥 **신호**: {', '.join(best['signals'][:4])}")
    print(f"💰 **가격**: {best['current_price']:,}원")
    print("=" * 80)
    
    # 디스코드 알림
    try:
        filtered_time = datetime.now().strftime('%m/%d %H:%M:%S')
        discord_msg = f"🎯 {filtered_time} {confidence_level}!\n"
        discord_msg += f"{best['ticker']} (확신도 {best['confidence']}점)\n"
        discord_msg += f"일봉: 시가{best['daily_change_from_open']:+.1f}% {daily_status}\n"
        discord_msg += f"5분: RSI{best['current_rsi']:.1f} BB{best['bb_position']:.0f}% V{best['volume_surge']:.1f}x\n"
        discord_msg += f"1시간: RSI{best['current_rsi_1h']:.1f} BB{best['bb_position_1h']:.0f}%\n"
        discord_msg += f"{best['signals'][0] if best['signals'] else '반등신호'}"
        
        # send_discord_message(discord_msg)
        print(discord_msg)
        
    except Exception as e:
        print(f"📱 알림 전송 실패: {e}")
    
    return best['ticker']

def trade_buy(ticker):
    """
    🚀 혁신적 복리 기반 매수 시스템 v2.0
    
    핵심 혁신:
    1. 총자산 10% 기반 동적 복리 포지션 사이징
    2. 신호 강도 기반 승수 시스템 (0.5x ~ 2.0x)
    3. 승률 추적 기반 적응형 리스크 관리
    4. 스마트 자산 한도 (총자산 80% 상한)
    5. 균형잡힌 진입 조건 (기회 vs 안전성)
    
    목표: 10만원 → 10억 (일평균 1% 복리)
    """
    
    # ==================== 내부 함수 정의 ====================
    
    def calculate_rsi_unified(closes, period=14):
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
        rsi = 100 - (100 / (1 + rs))
        return rsi

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
        """볼린저밴드 계산"""
        if len(closes) < window:
            window = len(closes)
        sma = np.mean(closes[-window:])
        std = np.std(closes[-window:])
        lower_band = sma - (std * std_dev)
        upper_band = sma + (std * std_dev)
        return lower_band, upper_band

    def get_krw_balance():
        """KRW 잔고 조회"""
        try:
            balances = upbit.get_balances()
            for b in balances:
                if b['currency'] == "KRW":
                    return float(b['balance'])
            return 0.0
        except Exception:
            return 0.0
    
    def get_total_crypto_value():
        """전체 암호화폐 평가액 계산 (KRW 제외)"""
        try:
            balances = upbit.get_balances()
            total_value = 0.0
            
            for balance in balances:
                currency = balance['currency']
                if currency == 'KRW':
                    continue
                
                amount = float(balance['balance'])
                if amount > 0:
                    ticker_name = f"KRW-{currency}"
                    try:
                        current_price = pyupbit.get_current_price(ticker_name)
                        if current_price:
                            total_value += amount * current_price
                    except:
                        continue
            
            return total_value
        except Exception as e:
            print(f"⚠️ 자산 평가 오류: {e}")
            return 0.0
    
    def get_win_rate_stats():
        """
        🎯 승률 통계 조회 (최근 10거래 기준)
        실제 구현 시 DB나 파일에서 거래 이력 로드
        여기서는 간소화
        """
        try:
            # TODO: 실제로는 거래 이력 DB/파일에서 로드
            # 임시로 50% 기본값 반환
            return {
                'win_rate': 0.50,
                'recent_wins': 5,
                'recent_losses': 5,
                'consecutive_wins': 0,
                'consecutive_losses': 0
            }
        except:
            return {
                'win_rate': 0.50,
                'recent_wins': 0,
                'recent_losses': 0,
                'consecutive_wins': 0,
                'consecutive_losses': 0
            }
    
    def calculate_market_volatility(closes, window=20):
        """시장 변동성 계산 (표준편차 기반, %)"""
        if len(closes) < window:
            window = len(closes)
        returns = np.diff(closes) / closes[:-1]
        volatility = np.std(returns[-window:]) * 100
        return volatility
    
    def detect_market_regime(closes_1h):
        """시장 국면 판단: bull / bear / neutral"""
        if len(closes_1h) < 50:
            return "neutral"
        
        ema_short = calculate_ema(closes_1h, period=12)
        ema_long = calculate_ema(closes_1h, period=26)
        
        trend_strength = (ema_short - ema_long) / ema_long
        
        if trend_strength > 0.02:
            return "bull"
        elif trend_strength < -0.02:
            return "bear"
        return "neutral"
    
    def calculate_dynamic_thresholds(volatility, regime, win_rate):
        """
        🎯 동적 임계값 계산 (완화된 기준)
        
        핵심: 거래 기회 증가 + 승률 기반 적응
        """
        # 기본값 (완화)
        base_rsi_lower = 30
        base_rsi_upper = 55
        base_bb_threshold = 0.5
        
        # 변동성 조정 (0.8~1.3배로 완화)
        vol_factor = np.clip(volatility / 3.0, 0.8, 1.3)
        
        # 시장 국면 조정 (완화)
        if regime == "bull":
            regime_factor = 0.90  # 상승장: 10% 완화
        elif regime == "bear":
            regime_factor = 1.10  # 하락장: 10% 강화
        else:
            regime_factor = 1.0
        
        # 승률 기반 조정 (혁신!)
        if win_rate > 0.60:  # 승률 60% 이상
            win_factor = 0.85  # 더 공격적
        elif win_rate < 0.40:  # 승률 40% 미만
            win_factor = 1.15  # 더 보수적
        else:
            win_factor = 1.0
        
        combined_factor = vol_factor * regime_factor * win_factor
        
        return {
            'rsi_lower': max(20, base_rsi_lower * combined_factor),
            'rsi_upper': min(70, base_rsi_upper * (2 - combined_factor)),
            'bb_threshold': min(0.6, base_bb_threshold / combined_factor),
            'min_safety_score': max(2, int(3 * combined_factor))
        }
    
    def calculate_signal_strength(indicators, thresholds):
        """
        💪 신호 강도 계산 (0~100점)
        
        개선: 더 관대한 점수 부여
        """
        score = 0
        
        # 1. RSI 점수 (0~30점)
        rsi = indicators['rsi']
        rsi_lower = thresholds['rsi_lower']
        rsi_upper = thresholds['rsi_upper']
        
        if rsi_lower < rsi < rsi_upper:
            rsi_normalized = (rsi - rsi_lower) / (rsi_upper - rsi_lower)
            rsi_score = 30 * (1 - rsi_normalized)
            score += rsi_score
        
        # 2. RSI 모멘텀 점수 (0~20점) - 완화
        rsi_momentum = indicators['rsi_momentum']
        if rsi_momentum > -1:  # 약간의 하락도 허용
            score += min(20, (rsi_momentum + 1) * 100)
        
        # 3. 볼린저밴드 점수 (0~25점)
        bb_pos = indicators['bb_position']
        bb_threshold = thresholds['bb_threshold']
        if 0 <= bb_pos < bb_threshold:
            score += 25 * (1 - bb_pos / bb_threshold)
        elif bb_threshold <= bb_pos < bb_threshold * 1.2:
            # 약간 넘어도 부분 점수
            score += 10
        
        # 4. 거래량 점수 (0~15점) - 완화
        vol_ratio = indicators['volume_ratio']
        if vol_ratio > 0.8:  # 0.8배만 넘어도 점수
            score += min(15, (vol_ratio - 0.8) * 50)
        
        # 5. 가격 모멘텀 점수 (0~10점) - 완화
        price_momentum = indicators['price_momentum']
        if -0.03 < price_momentum < 0.08:
            # 3% 하락 ~ 8% 상승까지 허용
            normalized = (price_momentum + 0.03) / 0.11
            score += 10 * normalized
        
        return min(100, max(0, score))
    
    def calculate_position_multiplier(signal_strength, win_rate, consecutive_wins, consecutive_losses):
        """
        🚀 포지션 승수 계산 (0.5x ~ 2.0x)
        
        혁신적 승수 시스템:
        - 신호 강도 기반 베이스 승수
        - 승률 기반 조정
        - 연승/연패 모멘텀 반영
        """
        # 1. 신호 강도 기반 베이스 승수 (0.7x ~ 1.5x)
        if signal_strength >= 80:
            base_mult = 1.5
        elif signal_strength >= 60:
            base_mult = 1.2
        elif signal_strength >= 40:
            base_mult = 1.0
        elif signal_strength >= 25:
            base_mult = 0.8
        else:
            base_mult = 0.7
        
        # 2. 승률 기반 조정 (±0.2)
        if win_rate > 0.60:
            win_adj = 0.2
        elif win_rate < 0.40:
            win_adj = -0.2
        else:
            win_adj = 0.0
        
        # 3. 연승/연패 모멘텀 (±0.3)
        if consecutive_wins >= 3:
            momentum_adj = 0.3  # 연승 시 공격적
        elif consecutive_losses >= 3:
            momentum_adj = -0.3  # 연패 시 보수적
        elif consecutive_wins >= 2:
            momentum_adj = 0.15
        elif consecutive_losses >= 2:
            momentum_adj = -0.15
        else:
            momentum_adj = 0.0
        
        final_mult = base_mult + win_adj + momentum_adj
        
        # 최종 범위 제한 (0.5x ~ 2.0x)
        return np.clip(final_mult, 0.5, 2.0)
    
    def calculate_smart_position_size(signal_strength, total_asset, available_krw, 
                                     crypto_value, win_stats):
        """
        💎 스마트 복리 포지션 사이징
        
        혁신 공식:
        포지션 = 총자산 × 10% × 포지션승수 × 리스크조정
        """
        MIN_ORDER = 5000
        
        # 신호 강도 최소 기준 (25점으로 완화)
        if signal_strength < 25:
            return 0, 0
        
        # 포지션 승수 계산
        position_mult = calculate_position_multiplier(
            signal_strength,
            win_stats['win_rate'],
            win_stats['consecutive_wins'],
            win_stats['consecutive_losses']
        )
        
        # 기본 포지션 = 총자산의 10%
        base_position = total_asset * 0.10
        
        # 승수 적용
        target_position = base_position * position_mult
        
        # 스마트 상한선: 총자산의 80% (유동성 확보)
        crypto_limit = total_asset * 0.80
        available_space = max(0, crypto_limit - crypto_value)
        
        # 제약 조건 적용
        final_position = min(
            target_position,
            available_krw * 0.995,  # 수수료 고려
            available_space
        )
        
        if final_position < MIN_ORDER:
            return 0, position_mult
        
        return final_position, position_mult
    
    # ==================== 메인 로직 시작 ====================
    
    print("\n" + "="*70)
    print(f"🚀 복리 매수 시스템 v2.0: {ticker}")
    print("="*70)
    
    # ========== STEP 1: 자산 현황 파악 ==========
    krw_balance = get_krw_balance()
    crypto_value = get_total_crypto_value()
    total_asset = crypto_value + krw_balance
    
    print(f"\n📊 자산 현황:")
    print(f"   💎 암호화폐: {crypto_value:,.0f}원 ({crypto_value/total_asset*100:.1f}%)")
    print(f"   💰 KRW 잔고: {krw_balance:,.0f}원 ({krw_balance/total_asset*100:.1f}%)")
    print(f"   📈 총 자산: {total_asset:,.0f}원")
    
    MIN_ORDER_AMOUNT = 5000
    
    if krw_balance < MIN_ORDER_AMOUNT:
        print(f"❌ 원화 잔고 부족: {krw_balance:,.0f}원")
        return "Insufficient balance", None
    
    # ========== STEP 2: 승률 통계 조회 ==========
    win_stats = get_win_rate_stats()
    
    print(f"\n🎯 승률 통계:")
    print(f"   승률: {win_stats['win_rate']*100:.1f}%")
    print(f"   연승: {win_stats['consecutive_wins']}회")
    print(f"   연패: {win_stats['consecutive_losses']}회")
    
    # ========== STEP 3: 스마트 상한선 체크 ==========
    crypto_limit = total_asset * 0.80
    crypto_ratio = crypto_value / total_asset
    
    print(f"\n💼 포지션 관리:")
    print(f"   암호화폐 비중: {crypto_ratio*100:.1f}%")
    print(f"   상한선: {crypto_limit:,.0f}원 (총자산의 80%)")
    
    if crypto_value >= crypto_limit:
        limit_msg = f"⏸️ 포지션 상한 도달!\n"
        limit_msg += f"   현재: {crypto_value:,.0f}원 ({crypto_ratio*100:.1f}%)\n"
        limit_msg += f"   상한: {crypto_limit:,.0f}원 (80%)\n"
        limit_msg += f"   → 일부 매도 후 재진입 권장"
        print(limit_msg)
        send_discord_message(f"[매수대기] {ticker}\n{limit_msg}")
        return "Position limit reached", None
    
    available_space = crypto_limit - crypto_value
    print(f"   여유 공간: {available_space:,.0f}원")
    
    # ========== STEP 4: 다중 시간프레임 데이터 수집 ==========
    try:
        df_5m = pyupbit.get_ohlcv(ticker, interval="minute5", count=40)
        time.sleep(0.1)
        df_1h = pyupbit.get_ohlcv(ticker, interval="minute60", count=50)
        time.sleep(0.1)
        
        if df_5m is None or len(df_5m) < 20:
            send_discord_message(f"[매수실패] {ticker} 데이터 부족")
            return "Data fetch failed", None
        
        if df_1h is None or len(df_1h) < 20:
            df_1h = df_5m
            
    except Exception as e:
        print(f"❌ 데이터 조회 실패: {e}")
        return "Data fetch failed", None
    
    # ========== STEP 5: 시장 환경 분석 ==========
    closes_5m = df_5m['close'].values
    closes_1h = df_1h['close'].values
    volumes_5m = df_5m['volume'].values
    
    market_regime = detect_market_regime(closes_1h)
    volatility = calculate_market_volatility(closes_5m)
    
    print(f"\n🌐 시장 환경:")
    print(f"   국면: {market_regime.upper()}")
    print(f"   변동성: {volatility:.2f}%")
    
    # 동적 임계값 (승률 반영)
    thresholds = calculate_dynamic_thresholds(volatility, market_regime, win_stats['win_rate'])
    
    print(f"\n🎯 동적 임계값:")
    print(f"   RSI: {thresholds['rsi_lower']:.1f} ~ {thresholds['rsi_upper']:.1f}")
    print(f"   BB: {thresholds['bb_threshold']:.1%}")
    print(f"   안전점수: {thresholds['min_safety_score']}")
    
    # ========== STEP 6: 기술적 지표 계산 ==========
    current_rsi = calculate_rsi_unified(closes_5m, period=14)
    prev_rsi = calculate_rsi_unified(closes_5m[:-1], period=14)
    rsi_momentum = current_rsi - prev_rsi
    
    ema_12 = calculate_ema(closes_5m, period=12)
    ema_26 = calculate_ema(closes_5m, period=26)
    lower_band, upper_band = calculate_bb(closes_5m, window=20, std_dev=2.0)
    
    bb_position = (closes_5m[-1] - lower_band) / (upper_band - lower_band + 1e-8)
    bb_position = max(0, min(1, bb_position))
    
    volume_ma5 = volumes_5m[-5:].mean()
    volume_ma20 = volumes_5m[-20:].mean()
    volume_ratio = volume_ma5 / (volume_ma20 + 1e-8)
    
    price_momentum = (closes_5m[-1] - closes_5m[-3]) / closes_5m[-3]
    
    indicators = {
        'rsi': current_rsi,
        'rsi_momentum': rsi_momentum,
        'bb_position': bb_position,
        'volume_ratio': volume_ratio,
        'price_momentum': price_momentum
    }
    
    print(f"\n📈 기술적 지표:")
    print(f"   RSI: {current_rsi:.1f} (모멘텀: {rsi_momentum:+.1f})")
    print(f"   BB 위치: {bb_position:.1%}")
    print(f"   거래량: {volume_ratio:.2f}x")
    print(f"   가격 모멘텀: {price_momentum:+.2%}")
    
    # ========== STEP 7: 신호 강도 계산 ==========
    signal_strength = calculate_signal_strength(indicators, thresholds)
    print(f"\n💪 신호 강도: {signal_strength:.1f}/100")
    
    # ========== STEP 8: 안전 검증 (완화) ==========
    safety_checks = {
        'RSI 극단 회피': 10 < current_rsi < 90,
        'BB 범위 내': -0.2 < bb_position < 1.2,
        'EMA 지지': closes_5m[-1] > ema_26 * 0.75,
        '급등락 방지': abs(price_momentum) < 0.25
    }
    
    passed_checks = sum(safety_checks.values())
    required_checks = 3  # 4개 중 3개만 통과하면 OK
    
    print(f"\n🛡️ 안전 검증: {passed_checks}/{len(safety_checks)}")
    for check_name, passed in safety_checks.items():
        status = "✅" if passed else "❌"
        print(f"   {status} {check_name}")
    
    # ========== STEP 9: 매수 조건 종합 판단 ==========
    # 완화된 기본 조건
    basic_condition = (
        thresholds['rsi_lower'] < current_rsi < thresholds['rsi_upper'] and
        rsi_momentum > -3
    )
    
    # 신호 강도 조건 (25점으로 완화)
    signal_condition = signal_strength >= 25
    
    # 안전 조건 (3/4만 통과하면 OK)
    safety_condition = passed_checks >= required_checks
    
    can_buy = basic_condition and signal_condition and safety_condition
    
    print(f"\n🔍 매수 조건:")
    print(f"   기본: {'✅' if basic_condition else '❌'}")
    print(f"   신호: {'✅' if signal_condition else '❌'} ({signal_strength:.1f}점)")
    print(f"   안전: {'✅' if safety_condition else '❌'} ({passed_checks}/{required_checks})")
    
    if not can_buy:
        fail_msg = f"⏭️ 매수 조건 미충족: {ticker}\n"
        if not basic_condition:
            fail_msg += f"   RSI 범위 벗어남 ({current_rsi:.1f})\n"
        if not signal_condition:
            fail_msg += f"   신호 강도 부족 ({signal_strength:.1f}/25)\n"
        if not safety_condition:
            fail_msg += f"   안전 검증 미달 ({passed_checks}/{required_checks})\n"
        print(fail_msg)
        return "Conditions not met", None
    
    # ========== STEP 10: 스마트 포지션 사이징 ==========
    buy_size, position_mult = calculate_smart_position_size(
        signal_strength,
        total_asset,
        krw_balance,
        crypto_value,
        win_stats
    )
    
    if buy_size < MIN_ORDER_AMOUNT:
        print(f"❌ 매수 금액 부족: {buy_size:.0f}원")
        return "Buy size too small", None
    
    # 포지션 크기 계산 과정
    base_position = total_asset * 0.10
    target_position = base_position * position_mult
    
    print(f"\n💰 포지션 계산:")
    print(f"   1️⃣ 기본 (총자산 10%): {base_position:,.0f}원")
    print(f"   2️⃣ 포지션 승수: {position_mult:.2f}x")
    print(f"      ├ 신호강도: {signal_strength:.1f}점")
    print(f"      ├ 승률: {win_stats['win_rate']*100:.0f}%")
    print(f"      └ 연승/연패: +{win_stats['consecutive_wins']}/-{win_stats['consecutive_losses']}")
    print(f"   3️⃣ 목표: {target_position:,.0f}원")
    print(f"   4️⃣ 최종 (제약 반영): {buy_size:,.0f}원")
    
    # 매수 후 예상
    expected_crypto = crypto_value + buy_size
    expected_total = total_asset
    expected_ratio = expected_crypto / expected_total
    
    print(f"\n📊 매수 후 예상:")
    print(f"   암호화폐: {expected_crypto:,.0f}원 ({expected_ratio*100:.1f}%)")
    print(f"   여유 공간: {crypto_limit - expected_crypto:,.0f}원")
    
    # ========== STEP 11: 매수 실행 ==========
    max_attempts = 2
    
    for attempt in range(1, max_attempts + 1):
        try:
            print(f"\n🚀 매수 실행 {attempt}/{max_attempts}...")
            
            current_price = pyupbit.get_current_price(ticker)
            time.sleep(0.05)
            
            # 가격 급등 체크
            price_change = (current_price - closes_5m[-1]) / closes_5m[-1]
            if price_change > 0.05:
                print(f"⚠️ 가격 급등 ({price_change:+.2%}), 재확인...")
                time.sleep(2)
                continue
            
            # 매수 주문
            buy_order = upbit.buy_market_order(ticker, buy_size)
            
            # 성공 메시지
            success_msg = f"✅ ★★★ 복리 매수 성공 ★★★\n"
            success_msg += f"━━━━━━━━━━━━━━━━━━━━\n"
            success_msg += f"🪙 {ticker}\n"
            success_msg += f"💰 가격: {current_price:,.2f}원\n"
            success_msg += f"💵 금액: {buy_size:,.0f}원\n"
            success_msg += f"━━━━━━━━━━━━━━━━━━━━\n"
            success_msg += f"🚀 포지션: {base_position:,.0f}원 × {position_mult:.2f} = {target_position:,.0f}원\n"
            success_msg += f"💪 신호: {signal_strength:.0f}점 | 승률: {win_stats['win_rate']*100:.0f}%\n"
            success_msg += f"📊 RSI: {current_rsi:.0f} | BB: {bb_position:.0%} | Vol: {volume_ratio:.1f}x\n"
            success_msg += f"🌐 {market_regime.upper()} | 변동성: {volatility:.1f}%\n"
            success_msg += f"━━━━━━━━━━━━━━━━━━━━\n"
            success_msg += f"💎 총자산: {total_asset:,.0f}원\n"
            success_msg += f"📈 예상 암호화폐: {expected_crypto:,.0f}원 ({expected_ratio*100:.0f}%)\n"
            success_msg += f"🎯 여유: {crypto_limit - expected_crypto:,.0f}원"
            
            print(success_msg)
            send_discord_message(success_msg)
            
            return buy_order
            
        except Exception as e:
            print(f"⚠️ 매수 오류 (시도 {attempt}): {e}")
            if attempt < max_attempts:
                time.sleep(2)
            else:
                error_msg = f"❌ 매수 실패: {ticker}\n에러: {str(e)}"
                print(error_msg)
                send_discord_message(error_msg)
                return "Order execution failed", None
    
    print(f"❌ 매수 실패: 최대 시도 초과")
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
    개선된 수익률 보고서 - 매시간 정시에 실행
    
    주요 개선사항:
    1. 전체 보유 자산 표시 (개수 제한 없음)
    2. 자산평가액 정확도 향상 (재시도 + locked 잔고 포함)
    3. 불필요한 정보 제거 (전시간 대비, 목표 달성도)
    4. 견고한 에러 처리
    """
    global profit_report_running
    
    # 중복 실행 방지
    if profit_report_running:
        return
    
    profit_report_running = True
    
    try:
        while True:
            try:
                now = datetime.now()
                
                # ========== STEP 1: 정시까지 대기 ==========
                if now.minute == 0:
                    # 정시라면 즉시 실행
                    pass
                else:
                    # 다음 정시까지 대기
                    next_hour = (now + timedelta(hours=1)).replace(
                        minute=0, second=0, microsecond=0
                    )
                    wait_seconds = (next_hour - now).total_seconds()
                    
                    if wait_seconds > 60:  # 1분 이상이면 대기
                        time.sleep(wait_seconds - 30)  # 30초 전에 준비
                        continue

                # ========== STEP 2: 보고서 헤더 생성 ==========
                report_message = f"📈 **[{now.strftime('%m/%d %H시')} 정시 보고서]** 📈\n"
                report_message += "━━━━━━━━━━━━━━━━━━━━\n\n"
                
                # ========== STEP 3: 잔고 정보 조회 (재시도 로직) ==========
                balances = None
                max_retries = 3  # 최대 3번 재시도
                
                for attempt in range(max_retries):
                    try:
                        balances = upbit.get_balances()
                        if balances and isinstance(balances, list):
                            break  # 성공
                    except Exception as e:
                        print(f"⚠️ 잔고 조회 실패 (시도 {attempt+1}/{max_retries}): {e}")
                        if attempt < max_retries - 1:
                            time.sleep(2)  # 2초 대기 후 재시도
                        else:
                            raise  # 마지막 시도 실패 시 에러 발생
                
                if not balances or not isinstance(balances, list):
                    raise Exception("잔고 정보를 가져올 수 없습니다")
                
                # ========== STEP 4: 자산 계산 ==========
                total_krw = 0.0  # 총 자산 (KRW + 암호화폐 평가액)
                total_crypto_value = 0.0  # 암호화폐 평가액만
                krw_balance = 0.0  # 보유 원화
                holding_assets = []  # 보유 코인 리스트
                
                # 4-1. KRW 잔고 먼저 계산
                for b in balances:
                    if not isinstance(b, dict) or 'currency' not in b:
                        continue
                    
                    if b['currency'] == "KRW":
                        # balance: 사용 가능한 금액
                        # locked: 주문 중인 금액
                        balance_amount = float(b.get('balance', 0))
                        locked_amount = float(b.get('locked', 0))
                        krw_balance = balance_amount + locked_amount
                        total_krw += krw_balance
                        break
                
                # 4-2. 암호화폐 자산 계산
                # 평가 불가능한 코인 리스트 (거래 정지, 상장 폐지 등)
                EXCLUDED_COINS = {'QI', 'ONK', 'ETHF', 'ETHW', 'PURSE'}
                
                for b in balances:
                    if not isinstance(b, dict) or 'currency' not in b:
                        continue
                    
                    currency = b['currency']
                    
                    # KRW는 이미 처리했으므로 스킵
                    if currency == "KRW":
                        continue
                    
                    # 평가 불가능한 코인 즉시 제외 (API 호출 절약)
                    if currency in EXCLUDED_COINS:
                        print(f"⚠️ {currency}: 평가 불가 코인으로 제외됨")
                        continue
                    
                    # balance: 사용 가능한 코인
                    # locked: 주문 중인 코인
                    balance_amount = float(b.get('balance', 0))
                    locked_amount = float(b.get('locked', 0))
                    total_amount = balance_amount + locked_amount
                    
                    # 보유량이 0이면 스킵
                    if total_amount <= 0:
                        continue
                    
                    ticker = f"KRW-{currency}"
                    
                    # 현재가 조회 (재시도 로직)
                    current_price = None
                    for price_attempt in range(3):
                        try:
                            current_price = pyupbit.get_current_price(ticker)
                            if current_price:
                                break
                            time.sleep(0.5)
                        except:
                            if price_attempt < 2:
                                time.sleep(0.5)
                            else:
                                print(f"⚠️ {ticker} 가격 조회 실패 (3회 시도)")
                    
                    # 가격 조회 실패 시 해당 코인은 스킵
                    # (거래 정지, 네트워크 오류 등 자동 대응)
                    if not current_price:
                        print(f"⚠️ {ticker}: 가격 조회 실패로 제외됨")
                        continue
                    
                    # 평균 매수가
                    avg_buy_price = float(b.get('avg_buy_price', 0))
                    
                    # 수익률 계산
                    if avg_buy_price > 0:
                        profit_rate = ((current_price - avg_buy_price) / avg_buy_price) * 100
                    else:
                        profit_rate = 0.0
                    
                    # 평가액 계산 (소수점 정밀도 유지)
                    asset_value = total_amount * current_price
                    
                    # 총 자산에 추가
                    total_crypto_value += asset_value
                    total_krw += asset_value
                    
                    # 보유 자산 리스트에 추가
                    holding_assets.append({
                        "ticker": currency,
                        "amount": total_amount,
                        "avg_buy_price": avg_buy_price,
                        "current_price": current_price,
                        "profit_rate": profit_rate,
                        "asset_value": asset_value
                    })
                    
                    # API 호출 간격 (Rate Limit 방지)
                    time.sleep(0.1)
                
                # ========== STEP 5: 보유 자산 정렬 (평가액 높은 순) ==========
                holding_assets.sort(key=lambda x: x['asset_value'], reverse=True)
                
                # ========== STEP 6: 보고서 본문 생성 ==========
                
                # 6-1. 총 자산 표시
                report_message += f"💰 **총 자산: {total_krw:,.0f}원**\n"
                report_message += f"   ├─ 💵 KRW: {krw_balance:,.0f}원\n"
                report_message += f"   └─ 💎 암호화폐: {total_crypto_value:,.0f}원\n\n"
                
                # 6-2. 보유 자산 상세 (전체 표시 - 한 줄 압축)
                if holding_assets:
                    report_message += f"📋 **보유 자산 ({len(holding_assets)}개)**\n"
                    report_message += "━━━━━━━━━━━━━━━━━━━━\n"
                    
                    for idx, asset in enumerate(holding_assets, 1):
                        # 수익률에 따른 이모지
                        if asset['profit_rate'] > 5:
                            emoji = "🔥"
                        elif asset['profit_rate'] > 0:
                            emoji = "📈"
                        elif asset['profit_rate'] > -5:
                            emoji = "➡️"
                        else:
                            emoji = "📉"
                        
                        # 코인명을 4자로 고정 (정렬 효과)
                        ticker_display = f"{asset['ticker']:<4}"
                        
                        # 한 줄로 압축: 코인명 이모지 수익률 | 평가액 (현재가)
                        report_message += (
                            f"{idx}. {ticker_display} {emoji} "
                            f"{asset['profit_rate']:+6.2f}% | "
                            f"평가 {asset['asset_value']:>10,.0f}원 "
                            f"(현 {asset['current_price']:>12,.0f}원)\n"
                        )
                    
                else:
                    report_message += "📋 **보유 자산**\n"
                    report_message += "━━━━━━━━━━━━━━━━━━━━\n"
                    report_message += "현재 보유 코인 없음 (매수 기회 탐색 중)\n"
                
                # ========== STEP 7: 보고서 전송 ==========
                send_discord_message(report_message)
                print(f"✅ {now.strftime('%H시')} 정시 보고서 전송 완료")
                print(f"   총 자산: {total_krw:,.0f}원 (KRW: {krw_balance:,.0f}원 + 암호화폐: {total_crypto_value:,.0f}원)")
                
                # ========== STEP 8: 1시간 대기 ==========
                time.sleep(3600)  # 3600초 = 1시간
                
            except Exception as e:
                # 오류 발생 시 로그 및 알림
                error_msg = f"❌ 수익률 보고서 생성 오류\n"
                error_msg += f"시간: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
                error_msg += f"에러: {str(e)}"
                
                print(error_msg)
                send_discord_message(error_msg)
                
                # 5분 후 재시도
                print("⏳ 5분 후 재시도합니다...")
                time.sleep(300)
    
    finally:
        # 스레드 종료 시 플래그 해제
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
    """개선된 메인 매매 로직 - 병렬 처리 구현"""
    
    # 수익률 보고 스레드 시작
    profit_thread = threading.Thread(target=send_profit_report, daemon=True)
    profit_thread.start()
    print("📊 수익률 보고 스레드 시작됨")
    
    while True:
        try:
            # ========== 1. 매도 로직 우선 실행 ==========
            has_holdings = selling_logic()
            
            # ========== 2. 매수 제한 시간 확인 ==========
            now = datetime.now()
            restricted_start = now.replace(hour=8, minute=50, second=0, microsecond=0)
            restricted_end = now.replace(hour=9, minute=10, second=0, microsecond=0)
            
            if restricted_start <= now <= restricted_end:
                print("⏰ 매수 제한 시간 (08:50~09:10). 60초 대기...")
                time.sleep(60)
                continue
            
            # ========== 3. 원화 잔고 확인 ==========
            try:
                krw_balance = get_balance("KRW")
            except Exception as e:
                print(f"KRW 잔고 조회 오류: {e}")
                time.sleep(10)
                continue
            
            # ========== 4. 매수 로직 실행 ==========
            if krw_balance > min_krw:
                print(f"💰 매수 가능 잔고: {krw_balance:,.0f}원")
                
                try:
                    best_ticker = get_best_ticker()
                    
                    if best_ticker:
                        buy_time = datetime.now().strftime('%m/%d %H:%M:%S')
                        print(f"[{buy_time}] 선정 코인: {best_ticker}")
                        
                        result = trade_buy(best_ticker)
                        
                        if result and isinstance(result, dict):
                            success_msg = f"🎉 매수 성공! 다음 기회까지 "
                            wait_time = 15 if has_holdings else 30
                            print(f"{success_msg}{wait_time}초 대기")
                            time.sleep(wait_time)
                        else:
                            print("❌ 매수 실패. 20초 후 재시도...")
                            time.sleep(20)
                    else:
                        wait_time = 10 if has_holdings else 30
                        print(f"💡 매수할 코인 없음. {wait_time}초 후 재탐색...")
                        time.sleep(wait_time)
                        
                except Exception as e:
                    print(f"매수 로직 실행 오류: {e}")
                    send_discord_message(f"매수 로직 오류: {e}")
                    time.sleep(30)
            else:
                wait_time = 60 if has_holdings else 120
                print(f"💸 매수 자금 부족: {krw_balance:,.0f}원. {wait_time}초 대기...")
                time.sleep(wait_time)
                
        except KeyboardInterrupt:
            print("프로그램 종료...")
            break
        except Exception as e:
            print(f"메인 루프 오류: {e}")
            send_discord_message(f"메인 루프 오류: {e}")
            time.sleep(30)

# ========== 프로그램 시작 ==========
if __name__ == "__main__":
    trade_start = datetime.now().strftime('%m/%d %H시%M분%S초')
    trade_msg = f'🚀 {trade_start} 트레이딩 봇 시작!\n'
    trade_msg += f'📊 설정: 수익률 {min_rate}%~{max_rate}% | 매도시도 {sell_time}회 | 손절 {cut_rate}%\n'
    trade_msg += f'📈 RSI 매수: {rsi_buy_s}~{rsi_buy_e} | RSI 매도: {rsi_sell_s}~{rsi_sell_e}\n'
    trade_msg += f'💡 개선사항: 조건완화, 병렬처리, 자동보고'
    
    print(trade_msg)
    send_discord_message(trade_msg)
    
    # 메인 매매 로직 실행
    buying_logic()