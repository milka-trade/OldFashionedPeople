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
            max_rate = float(input("최대 수익률 (예: 2.5):"))
            sell_time = int(input("매도감시횟수 (예: 10): "))
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

# 상위 코인 목록 (동적으로 업데이트)
def get_top_volume_tickers():
    """거래대금 기준 상위 20개 코인 동적 추출"""
    try:
        tickers = pyupbit.get_tickers(fiat="KRW")
        ticker_24h = []
        
        for ticker in tickers:
            try:
                ticker_data = pyupbit.get_ohlcv(ticker, interval="day", count=1)
                if ticker_data is not None and len(ticker_data) > 0:
                    volume = ticker_data['volume'].iloc[-1]
                    price = ticker_data['close'].iloc[-1]
                    volume_krw = volume * price
                    ticker_24h.append((ticker, volume_krw))
                time.sleep(0.01)
            except:
                continue
        
        # 거래대금 기준 상위 30개 선택
        ticker_24h.sort(key=lambda x: x[1], reverse=True)
        return [ticker[0] for ticker in ticker_24h[:20]]
    
    except Exception as e:
        print(f"동적 티커 추출 실패: {e}")
        # 실패시 기본 리스트 반환
        return [
            "KRW-BTC", "KRW-ETH", "KRW-SOL", "KRW-XRP", "KRW-ADA", 
            "KRW-LINK", "KRW-SUI", "KRW-ONDO", "KRW-SEI", "KRW-VIRTUAL"
        ]

def get_best_ticker():
    """
    🎯 개선된 반등 포착 시스템 - 매수 조건 완화 및 신호 강도 개선
    """
    
    # ========== STEP 1: 동적 상위 코인 목록 추출 ==========
    try:
        # 보유 코인 목록 추출
        balances = upbit.get_balances()
        held_coins = {f"KRW-{b['currency']}" for b in balances if float(b.get('balance', 0)) > 0}
        
        # 동적으로 상위 거래대금 코인 추출
        all_tickers = get_top_volume_tickers()
        all_tickers = [t for t in all_tickers if t not in held_coins]
        
        print(f"🎯 반등 포착 시스템 시작 - 분석 대상: {len(all_tickers)}개")
        
    except Exception as e:
        print(f"❌ 초기화 실패: {e}")
        return None
    
    if not all_tickers:
        print("💡 분석 대상 코인이 없습니다.")
        return None
        
    # ========== STEP 2: 개선된 1차 스크리닝 - 조건 완화 ==========
    print("🔍 1차 스크리닝: 반등 신호 감지 중...")
    
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
            df_5m = pyupbit.get_ohlcv(ticker, interval="minute5", count=50)
            current_price = pyupbit.get_current_price(ticker)
            
            if df_5m is None or len(df_5m) < 30 or current_price is None:
                time.sleep(0.05)
                continue
            
            closes = df_5m['close'].values
            volumes = df_5m['volume'].values
            
            # === 볼린저밴드 반등 패턴 감지 ===
            bb_period = 20
            sma20 = np.mean(closes[-bb_period:])
            std20 = np.std(closes[-bb_period:])
            bb_lower = sma20 - (2.0 * std20)
            bb_upper = sma20 + (2.0 * std20)
            
            bb_position = (current_price - bb_lower) / (bb_upper - bb_lower) * 100
            
            # 하단 근접 또는 돌파 패턴
            bb_breakthrough = False
            recent_closes = closes[-3:]
            for price in recent_closes:
                if price <= bb_lower * 1.03:  # 하단 3% 이내 (조건 완화)
                    bb_breakthrough = True
                    break
            
            # === RSI 과매도 반등 감지 ===
            current_rsi = calculate_rsi_unified(closes)
            
            # RSI 상승 전환 확인
            rsi_uptrend = False
            if len(closes) >= 17:
                prev_rsi = calculate_rsi_unified(closes[:-2])
                rsi_uptrend = current_rsi > prev_rsi
            
            # === 거래량 급증 확인 ===
            recent_volume = np.mean(volumes[-3:])
            avg_volume = np.mean(volumes[-15:-3])
            volume_surge = recent_volume / (avg_volume + 1e-8)
            
            # === 가격 변화율 확인 ===
            price_change_5m = (closes[-1] - closes[-6]) / closes[-6] * 100 if len(closes) >= 6 else 0
            
            # === 개선된 1차 통과 조건 (조건 완화) ===
            bb_signal = bb_breakthrough or bb_position < 25
            rsi_signal = (current_rsi <= 40 and rsi_uptrend) or current_rsi <= 30  # RSI 조건 완화
            volume_signal = volume_surge >= 1.2  # 거래량 조건 완화
            momentum_signal = price_change_5m > -3.0  # 급락 아님
            
            # 기본 필터
            price_valid = 50 <= current_price <= 200000
            
            # 급등 제외
            df_1d = pyupbit.get_ohlcv(ticker, interval="day", count=1)
            daily_change = 0
            if df_1d is not None and not df_1d.empty:
                daily_open = df_1d['open'].iloc[-1]
                daily_change = (current_price - daily_open) / daily_open * 100
            not_surged = daily_change < 12.0  # 당일 12% 이상 급등 제외 (조건 완화)
            
            # 1차 통과 (4개 조건 중 2개 이상 + 기본 조건) - 조건 완화
            signal_count = sum([bb_signal, rsi_signal, volume_signal, momentum_signal])
            
            if signal_count >= 2 and price_valid and not_surged:
                primary_candidates.append({
                    'ticker': ticker,
                    'current_rsi': current_rsi,
                    'volume_surge': volume_surge,
                    'daily_change': daily_change,
                    'current_price': current_price,
                    'bb_position': bb_position,
                    'price_change_5m': price_change_5m,
                    'signal_count': signal_count
                })
                
                print(f"✅ 1차 통과: {ticker} (RSI:{current_rsi:.1f}, BB:{bb_position:.1f}%, 거래량:{volume_surge:.1f}x)")
            
            time.sleep(0.02)
            
        except Exception as e:
            continue
    
    print(f"🔍 1차 결과: {len(all_tickers)}개 → {len(primary_candidates)}개 선별")
    
    if not primary_candidates:
        print("💡 1차 스크리닝에서 반등 신호가 감지되지 않았습니다.")
        return None
    
    # ========== STEP 3: 개선된 2차 정밀 분석 - 확신도 계산 완화 ==========
    print("🎯 2차 정밀 분석: 확신도 검증 중...")
    
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
            
            # === 1시간봉 볼린저밴드 분석 ===
            bb_period = 20
            sma20_1h = np.mean(closes[-bb_period:])
            std20_1h = np.std(closes[-bb_period:])
            bb_lower_1h = sma20_1h - (2.0 * std20_1h)
            bb_upper_1h = sma20_1h + (2.0 * std20_1h)
            bb_position_1h = (current_price - bb_lower_1h) / (bb_upper_1h - bb_lower_1h) * 100
            
            # === 1시간봉 거래량 분석 ===
            recent_vol_1h = np.mean(volumes[-3:])
            normal_vol_1h = np.mean(volumes[-12:-3])
            volume_expansion_1h = recent_vol_1h / (normal_vol_1h + 1e-8)
            
            # === 완화된 확신도 계산 (0-100점) ===
            confidence = 0
            signals = []
            
            # 5분봉 신호 (30점 만점)
            confidence += candidate['signal_count'] * 7  # 신호당 7점
            signals.append(f"5분신호{candidate['signal_count']}개")
            
            # 1시간봉 RSI (25점 만점) - 조건 완화
            if current_rsi_1h <= 35:
                confidence += 25
                signals.append(f"1H-RSI과매도({current_rsi_1h:.1f})")
            elif current_rsi_1h <= 45:
                confidence += 15
                signals.append(f"1H-RSI매수권({current_rsi_1h:.1f})")
            
            # 1시간봉 볼린저밴드 (20점 만점) - 조건 완화
            if bb_position_1h < 30:
                confidence += 20
                signals.append(f"1H-BB하단권({bb_position_1h:.0f}%)")
            elif bb_position_1h < 50:
                confidence += 10
                signals.append(f"1H-BB중하단({bb_position_1h:.0f}%)")
            
            # 1시간봉 거래량 (15점 만점) - 조건 완화
            if volume_expansion_1h >= 1.5:
                confidence += 15
                signals.append(f"1H-거래량증가({volume_expansion_1h:.1f}x)")
            elif volume_expansion_1h >= 1.2:
                confidence += 8
                signals.append(f"1H-거래량확장({volume_expansion_1h:.1f}x)")
            
            # 가격 모멘텀 보너스 (10점 만점)
            if candidate['price_change_5m'] > -1.0:  # 5분간 1% 이상 하락 아님
                confidence += 10
                signals.append("단기모멘텀양호")
            
            # === 확신도 60점 이상만 통과 (기준 완화) ===
            if confidence >= 60:
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
                    'daily_change': candidate['daily_change']
                })
                
                grade = "🚀 PERFECT" if confidence >= 85 else "⭐ EXCELLENT" if confidence >= 75 else "✅ GOOD"
                print(f"{grade}: {ticker} (확신도:{confidence}점)")
                print(f"  └ {', '.join(signals[:3])}")
            
            time.sleep(0.05)
            
        except Exception as e:
            continue
    
    print(f"🎯 2차 결과: {len(primary_candidates)}개 → {len(final_candidates)}개 최종 선별")
    
    # ========== STEP 4: 최고 확신도 종목 선택 ==========
    if not final_candidates:
        print("💡 확신도 60점 이상의 반등 기회가 없습니다.")
        return None
    
    # 확신도 기준 정렬
    final_candidates.sort(key=lambda x: x['confidence'], reverse=True)
    best = final_candidates[0]
    
    # 결과 출력
    confidence_level = "🚀 완벽한 반등" if best['confidence'] >= 85 else "⭐ 강력한 반등" if best['confidence'] >= 75 else "✅ 확실한 반등"
    
    print("=" * 80)
    print(f"🎯 **반등 포착 완료**: {best['ticker']}")
    print(f"📊 **확신도**: {best['confidence']}점 ({confidence_level})")
    print(f"📈 **5분봉**: RSI {best['current_rsi']:.1f} | BB {best['bb_position']:.0f}% | 거래량 {best['volume_surge']:.1f}배")
    print(f"📈 **1시간봉**: RSI {best['current_rsi_1h']:.1f} | BB {best['bb_position_1h']:.0f}% | 거래량 {best['volume_expansion_1h']:.1f}배")
    print(f"🔥 **신호**: {', '.join(best['signals'])}")
    print(f"💰 **가격**: {best['current_price']:,}원 (당일 {best['daily_change']:+.1f}%)")
    print("=" * 80)
    
    # 디스코드 알림
    try:
        filtered_time = datetime.now().strftime('%m/%d %H:%M:%S')
        discord_msg = f"🎯 {filtered_time} {confidence_level}!\n"
        discord_msg += f"{best['ticker']} (확신도 {best['confidence']}점)\n"
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
    개선된 매수 로직 - 매수 조건 완화 및 안정성 강화
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

    def calculate_ema(closes, period=12):
        ema = [closes[0]]
        alpha = 2 / (period + 1)
        for close in closes[1:]:
            ema.append(alpha * close + (1 - alpha) * ema[-1])
        return ema[-1]

    def calculate_bb(closes, window=20, std_dev=2.0):
        sma = np.mean(closes[-window:])
        std = np.std(closes[-window:])
        lower_band = sma - (std * std_dev)
        upper_band = sma + (std * std_dev)
        return lower_band, upper_band

    def get_krw_balance():
        try:
            balances = upbit.get_balances()
            for b in balances:
                if b['currency'] == "KRW":
                    return float(b['balance'])
            return 0.0
        except Exception:
            return 0.0
            
    # ========== 1. 잔고 및 매수 금액 결정 ==========
    krw = get_krw_balance()
    print(f"💰 보유 원화: {krw:,.0f}원")

    MIN_ORDER_AMOUNT = 5000
    STANDARD_BUY_AMOUNT = 50000  # 매수 금액을 5만원으로 조정 (더 공격적)

    buy_size = 0
    if krw < MIN_ORDER_AMOUNT:
        print(f"❌ 원화 잔고 부족: {krw:,.0f}원")
        return "Insufficient balance", None
    elif krw < STANDARD_BUY_AMOUNT:
        buy_size = krw * 0.999  # 전액 매수
        print(f"💡 소액 전액 매수: {buy_size:,.0f}원")
    else:
        buy_size = STANDARD_BUY_AMOUNT
        print(f"🚀 표준 매수: {buy_size:,.0f}원")

    if buy_size < MIN_ORDER_AMOUNT:
        return "Buy size too small", None

    # ========== 2. 기술적 분석 및 매수 실행 ==========
    max_retries = 3  # 재시도 횟수 감소
    attempt = 0
    
    df = pyupbit.get_ohlcv(ticker, interval="minute5", count=40)
    time.sleep(0.1)
    if df is None or len(df) < 20:
        send_discord_message(f"[매수실패] {ticker} 데이터 부족")
        return "Data fetch failed", None
    
    df_close = df['close'].values
    df_volume = df['volume'].values
    
    # 기본 지표 계산
    current_rsi = calculate_rsi_unified(df_close, period=14)
    last_ema = calculate_ema(df_close, period=12)
    lower_band, upper_band = calculate_bb(df_close, window=20, std_dev=2.0)
    
    bb_position = (df_close[-1] - lower_band) / (upper_band - lower_band)
    volume_ma5 = df_volume[-5:].mean()
    volume_ma20 = df_volume[-20:].mean()
    recent_drop = (df_close[-1] - df_close[-3]) / df_close[-3]
    
    while attempt < max_retries:
        attempt += 1
        cur_price = pyupbit.get_current_price(ticker)
        time.sleep(0.05)
        
        print(f"[매수 조건 확인]: {ticker} 현재가: {cur_price:,.2f} / 시도: {attempt}/{max_retries}")
        
        # === 완화된 매수 조건 ===
        basic_condition = (
            current_rsi > 20 and current_rsi < 50 and  # RSI 조건 완화
            current_rsi > calculate_rsi_unified(df_close[:-1], period=14)  # RSI 상승 전환
        )
        
        # 안전 조건들 (완화)
        safety_conditions = [
            bb_position < 0.4,                    # BB 하위 40% (완화)
            volume_ma5 > volume_ma20 * 1.05,      # 거래량 5% 증가 (완화)
            recent_drop > -0.08,                  # 3봉간 8% 이상 하락 아님 (완화)
            cur_price > last_ema * 0.85,          # EMA 대비 15% 이상 하락 아님 (완화)
            abs(recent_drop) < 0.2                # 극단적 변동 아님
        ]
        
        safety_score = sum(safety_conditions)
        
        # 매수 실행 조건 (3개 이상으로 완화)
        if basic_condition and safety_score >= 3:
            try:
                final_price = pyupbit.get_current_price(ticker)
                buy_order = upbit.buy_market_order(ticker, buy_size)
                
                buyedmsg = f"✅ ★★매수 성공★★: {ticker}\n"
                buyedmsg += f"💰 매수가: {final_price:,.2f} | 금액: {buy_size:,.0f}원\n"
                buyedmsg += f"📊 RSI: {current_rsi:.1f} | BB위치: {bb_position:.1%} | 안전점수: {safety_score}/5"
                
                print(buyedmsg)
                send_discord_message(buyedmsg)
                return buy_order

            except Exception as e:
                print(f"매수 주문 실행 오류: {e}")
                time.sleep(3)
        else:
            condition_msg = f"[매수 대기]: {ticker} ({attempt}/{max_retries}) "
            condition_msg += f"RSI: {current_rsi:.1f} | BB: {bb_position:.1%} | 안전점수: {safety_score}/5"
            print(condition_msg)
            time.sleep(5)
    
    print(f"❌ 매수 실패: {ticker} (조건 미충족)")
    return "Max attempts exceeded", None
    
def trade_sell(ticker):
    """
    개선된 매도 로직 - 수익 확보 및 손절 최적화
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

    # ========== 즉시 손절 조건 강화 ==========
    if profit_rate < cut_rate:
        # 추가 확인: 1분봉 급락 검증
        df_1m = pyupbit.get_ohlcv(ticker, interval="minute1", count=3)
        time.sleep(0.05)
        if df_1m is not None and len(df_1m) >= 3:
            recent_drop_1m = (df_1m['close'].iloc[-1] - df_1m['open'].iloc[-3]) / df_1m['open'].iloc[-3]
            if recent_drop_1m < -0.015:  # 1.5% 이상 급락시 즉시 손절
                sell_order = upbit.sell_market_order(ticker, buyed_amount)
                cut_message = f"❌ **[긴급 손절]**: [{ticker}] 수익률: {profit_rate:.2f}% / 현재가: {cur_price:,.1f}\n"
                cut_message += f"사유: 1분봉 급락 감지! RSI: {calculate_rsi_unified([cur_price]):.1f}"
                print(cut_message)
                send_discord_message(cut_message)
                return sell_order

    # 5분봉 데이터 수집
    df_5m = pyupbit.get_ohlcv(ticker, interval="minute5", count=30)
    time.sleep(0.1)
    if df_5m is None or len(df_5m) < 15:
        print(f"[{ticker}] 5분봉 데이터 부족")
        return None
    
    closes = df_5m['close'].values
    volumes = df_5m['volume'].values
    
    # 현재 RSI
    current_rsi = calculate_rsi_unified(closes)
    
    # ========== 매도 신호 강도 계산 ==========
    signals = []
    sell_strength = 0
    
    # 볼린저밴드 상단 이탈
    sma20 = np.mean(closes[-20:])
    std20 = np.std(closes[-20:])
    bb_upper = sma20 + (2.0 * std20)
    bb_position = (cur_price - sma20) / std20
    
    if bb_position > 2.0 and cur_price < df_5m['high'].iloc[-2]:  # 상단 이탈 후 하락
        signals.append("BB상단급락")
        sell_strength += 3
    
    # RSI 과열 후 하락
    if current_rsi > 75:
        prev_rsi = calculate_rsi_unified(closes[:-1])
        if current_rsi < prev_rsi:
            signals.append("RSI과열하락")
            sell_strength += 2
    
    # 거래량 급증과 함께 20선 이탈
    recent_vol = np.mean(volumes[-3:])
    avg_vol = np.mean(volumes[-10:-3])
    volume_spike = recent_vol / (avg_vol + 1e-8)
    
    if cur_price < sma20 and volume_spike > 1.5:
        signals.append("20선대량이탈")
        sell_strength += 2
    
    # 연속 하락
    consecutive_down = 0
    if len(closes) >= 4:
        for i in range(1, 4):
            if closes[-i] < closes[-i-1]:
                consecutive_down += 1
            else:
                break
    
    if consecutive_down >= 3:
        signals.append(f"연속{consecutive_down}틱하락")
        sell_strength += consecutive_down

    # ========== 매도 요구 점수 설정 (완화) ==========
    if profit_rate >= max_rate:
        required_score = 1  # 목표 달성시 약한 신호로도 매도
    elif profit_rate >= min_rate * 0.7:  # 최소 수익률의 70% 이상
        required_score = 2  # 약간 완화
    else:
        required_score = 3  # 손실 방지

    should_sell_technical = sell_strength >= required_score
    signal_text = " + ".join(signals) + f" (강도:{sell_strength}/{required_score})"
    
    # ========== 매도 실행 루프 ==========
    max_attempts = min(sell_time, 15)  # 최대 15회로 제한
    attempts = 0
    
    while attempts < max_attempts:
        cur_price = pyupbit.get_current_price(ticker)
        profit_rate = (cur_price - avg_buy_price) / avg_buy_price * 100 if avg_buy_price > 0 else 0
        
        # 손절 재확인
        if profit_rate < cut_rate:
            sell_order = upbit.sell_market_order(ticker, buyed_amount)
            cut_message = f"❌ **[손절]**: [{ticker}] 수익률: {profit_rate:.2f}% / 현재가: {cur_price:,.1f}"
            print(cut_message)
            send_discord_message(cut_message)
            return sell_order

        print(f"[{ticker}] 시도 {attempts + 1}/{max_attempts} | 수익률: {profit_rate:.2f}% | 신호강도: {sell_strength}/{required_score}")

        # 매도 조건 충족시
        if profit_rate >= max_rate or should_sell_technical:
            sell_order = upbit.sell_market_order(ticker, buyed_amount)
            
            sell_type = "목표달성" if profit_rate >= max_rate else "기술적매도"
            sellmsg = f"✅ **[{sell_type}]**: [{ticker}] 수익률: {profit_rate:.2f}% / 현재가: {cur_price:,.1f}\n"
            sellmsg += f"신호: {signal_text}"
            
            print(sellmsg)
            send_discord_message(sellmsg)
            return sell_order
        
        time.sleep(second)
        attempts += 1
    
    # 최소 수익률 이상이면 시간 종료 후에도 매도
    if profit_rate >= min_rate * 0.5:  # 최소 수익률의 50% 이상이면 매도 (완화)
        sell_order = upbit.sell_market_order(ticker, buyed_amount)
        final_msg = f"⚠️ **[시간종료매도]**: [{ticker}] 수익률: {profit_rate:.2f}% / 현재가: {cur_price:,.1f}"
        print(final_msg)
        send_discord_message(final_msg)
        return sell_order

    return None

# 누적 자산 기록용 변수
last_total_krw = 0.0
profit_report_running = False

def send_profit_report():
    """개선된 수익률 보고서 - 매시간 정시에 실행"""
    global last_total_krw, profit_report_running
    
    if profit_report_running:
        return
    
    profit_report_running = True
    
    try:
        while True:
            try:
                now = datetime.now()
                
                # 정시까지의 시간 계산
                if now.minute == 0:
                    # 정시라면 즉시 실행
                    pass
                else:
                    # 다음 정시까지 대기
                    next_hour = (now + timedelta(hours=1)).replace(minute=0, second=0, microsecond=0)
                    wait_seconds = (next_hour - now).total_seconds()
                    if wait_seconds > 60:  # 1분 이상이면 대기
                        time.sleep(wait_seconds - 30)  # 30초 전에 준비
                        continue

                # 보고서 생성
                report_message = f"📈 **[{now.strftime('%m/%d %H시')} 정시 보고서]** 📈\n\n"
                
                balances = upbit.get_balances()
                total_krw = 0
                holding_assets = []
                
                if isinstance(balances, list):
                    for b in balances:
                        if not isinstance(b, dict) or 'currency' not in b: 
                            continue
                        
                        currency = b['currency']
                        balance_amount = float(b.get('balance', 0))
                        
                        if currency == "KRW":
                            total_krw += balance_amount
                            continue
                        
                        if balance_amount <= 0:
                            continue
                        
                        ticker = f"KRW-{currency}"
                        try:
                            avg_buy_price = float(b.get('avg_buy_price', 0))
                            cur_price = pyupbit.get_current_price(ticker)
                            time.sleep(0.1)
                            
                            if cur_price is None:
                                continue
                            
                            profit_rate = (cur_price - avg_buy_price) / avg_buy_price * 100 if avg_buy_price > 0 else 0
                            asset_value = balance_amount * cur_price
                            total_krw += asset_value
                            
                            holding_assets.append({
                                "ticker": currency,
                                "profit_rate": profit_rate,
                                "cur_price": cur_price,
                                "avg_buy_price": avg_buy_price,
                                "asset_value": asset_value
                            })
                        except:
                            continue

                # 총 자산 보고
                report_message += f"💰 **총 자산: {total_krw:,.0f}원**\n"
                
                if last_total_krw > 0:
                    krw_change = total_krw - last_total_krw
                    change_rate = (krw_change / last_total_krw) * 100
                    emoji = "📈" if krw_change > 0 else "📉" if krw_change < 0 else "➡️"
                    report_message += f"전시간 대비: {krw_change:+,.0f}원 ({change_rate:+.2f}%) {emoji}\n"
                
                last_total_krw = total_krw
                
                # 목표 달성도
                target_progress = (total_krw / 1_000_000_000) * 100
                report_message += f"🎯 10억 목표 달성도: {target_progress:.4f}%\n\n"
                
                # 보유 자산 상세
                if holding_assets:
                    report_message += "📋 **보유 자산:**\n"
                    for asset in holding_assets[:5]:  # 최대 5개만 표시
                        report_message += f"[{asset['ticker']}] {asset['profit_rate']:+.2f}% | "
                        report_message += f"현재가: {asset['cur_price']:,.0f}원 | "
                        report_message += f"평가액: {asset['asset_value']:,.0f}원\n"
                    
                    if len(holding_assets) > 5:
                        report_message += f"...외 {len(holding_assets)-5}개 더\n"
                else:
                    report_message += "현재 보유 코인 없음 (매수 기회 탐색 중)\n"
                
                send_discord_message(report_message)
                print(f"📊 {now.strftime('%H시')} 정시 보고서 전송 완료")
                
                # 1시간 대기
                time.sleep(3600)
                
            except Exception as e:
                error_msg = f"❌ 수익률 보고 오류: {e}"
                print(error_msg)
                send_discord_message(error_msg)
                time.sleep(300)  # 5분 후 재시도
    
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