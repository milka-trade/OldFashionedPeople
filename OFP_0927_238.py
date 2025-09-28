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
    """
    스캘핑 거래를 위한 최적화된 종목 선정
    - 누적 거래대금 기반 안정적인 메이저 코인 우선
    - 변동성과 유동성의 균형점을 고려한 종목 선별
    - 승률 80% 이상을 목표로 한 보수적 접근
    """
    try:
        # 메이저 코인 우선순위 리스트 (안정성 + 유동성 기준)
        major_coins_priority = [
            "KRW-BTC",   # 비트코인 - 최고 안정성
            "KRW-ETH",   # 이더리움 - 높은 유동성
            "KRW-XRP",   # 리플 - 안정적 거래패턴
            "KRW-ADA",   # 카르다노 - 중간 변동성
            "KRW-LINK",  # 체인링크 - 꾸준한 거래량
            "KRW-DOT",   # 폴카닷 - 안정적 메이저코인
            "KRW-AVAX",  # 아발란체 - 적당한 변동성
            "KRW-MATIC", # 폴리곤 - 꾸준한 거래
            "KRW-ATOM",  # 코스모스 - 안정적 패턴
            "KRW-LTC"    # 라이트코인 - 낮은 변동성
        ]
        
        tickers = pyupbit.get_tickers(fiat="KRW")
        ticker_scores = []
        
        for ticker in tickers:
            try:
                # 30일 데이터로 안정성 평가
                ticker_data = pyupbit.get_ohlcv(ticker, interval="day", count=30)
                if ticker_data is None or len(ticker_data) < 30:
                    continue
                
                # 최근 7일과 30일 평균 거래대금 계산
                recent_7d = ticker_data[-7:]
                all_30d = ticker_data
                
                volume_7d_avg = (recent_7d['volume'] * recent_7d['close']).mean()
                volume_30d_avg = (all_30d['volume'] * all_30d['close']).mean()
                
                # 변동성 계산 (30일 기준 일일 변동률의 표준편차)
                daily_changes = ((ticker_data['close'] - ticker_data['close'].shift(1)) / ticker_data['close'].shift(1)).dropna()
                volatility = daily_changes.std()
                
                # 스코어링 시스템
                score = 0
                
                # 1. 메이저 코인 보너스 (최대 1000점)
                if ticker in major_coins_priority:
                    priority_bonus = 1000 - (major_coins_priority.index(ticker) * 100)
                    score += priority_bonus
                
                # 2. 거래대금 점수 (30일 평균 기준, 최대 500점)
                # 100억원 이상이면 만점, 그 이하는 비례점수
                volume_score = min(500, (volume_30d_avg / 10000000000) * 500)
                score += volume_score
                
                # 3. 안정성 점수 (변동성 역산, 최대 300점)
                # 변동성이 낮을수록 높은 점수 (0.05 기준)
                stability_score = max(0, 300 - (volatility * 6000))
                score += stability_score
                
                # 4. 거래 일관성 점수 (최대 200점)
                # 7일 평균과 30일 평균의 차이가 적을수록 높은 점수
                consistency_ratio = min(volume_7d_avg, volume_30d_avg) / max(volume_7d_avg, volume_30d_avg)
                consistency_score = consistency_ratio * 200
                score += consistency_score
                
                # 5. 최소 거래대금 필터 (일 10억원 이상)
                if volume_30d_avg < 1000000000:
                    continue
                
                # 6. 최대 변동성 필터 (일 변동성 10% 이상은 제외)
                if volatility > 0.10:
                    continue
                
                ticker_scores.append({
                    'ticker': ticker,
                    'score': score,
                    'volume_30d': volume_30d_avg,
                    'volatility': volatility,
                    'is_major': ticker in major_coins_priority
                })
                
                time.sleep(0.01)
                
            except Exception as e:
                continue
        
        # 스코어 기준으로 정렬하여 상위 10개 선택
        ticker_scores.sort(key=lambda x: x['score'], reverse=True)
        selected_tickers = [item['ticker'] for item in ticker_scores[:10]]
        
        # 결과 출력 (디버깅용)
        print("=== 선정된 스캘핑 최적화 종목 ===")
        for i, item in enumerate(ticker_scores[:10], 1):
            major_mark = "★" if item['is_major'] else " "
            print(f"{i:2d}. {major_mark} {item['ticker']:10} | "
                  f"점수: {item['score']:6.0f} | "
                  f"30일평균거래대금: {item['volume_30d']/100000000:6.0f}억 | "
                  f"변동성: {item['volatility']*100:4.1f}%")
        
        return selected_tickers
        
    except Exception as e:
        print(f"최적화된 티커 추출 실패: {e}")
        # 실패시 검증된 안정적인 메이저 코인 반환
        return [
            "KRW-BTC", "KRW-ETH", "KRW-XRP", "KRW-ADA", "KRW-LINK",
            "KRW-DOT", "KRW-AVAX", "KRW-MATIC", "KRW-ATOM", "KRW-LTC"
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