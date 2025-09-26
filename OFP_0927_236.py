import time
import pyupbit
import numpy as np
from datetime import datetime, timedelta
import os
from dotenv import load_dotenv
import requests
import ta
import pandas as pd
# from concurrent.futures import ThreadPoolExecutor, as_completed, TimeoutError

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
# UpRsiRate = 80

def get_user_input():
    while True:
        try:
            min_rate = float(input("최소 수익률 (예: 0.4): "))
            max_rate = float(input("최대 수익률 (예: 2.1):"))
            sell_time = int(input("매도감시횟수 (예: 10): "))
            rsi_sell_s =int(input("RSI 매도 감시 시작 (예: 65): "))
            rsi_sell_e =int(input("RSI 매도 감시 종료 (예: 80): "))
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

# NOTE: 'upbit' 객체와 'send_discord_message' 함수가 외부에서 정의되었다고 가정합니다.
# from external_modules import upbit, send_discord_message 

# 상위 10개 코인 목록 (거래대금 기준, 수동 지정 또는 별도 API 호출 필요)
# 조회량 기준 상위 10개를 직접 가져오는 API가 없으므로,
# 현재 시장의 대표적인 고유동성 코인 10개를 지정했습니다.
# 실제 운영 시, pyupbit.get_orderbook(tickers=pyupbit.get_tickers(fiat="KRW")) 등을 활용하여
# 실시간 거래대금 상위 10개를 추출하는 로직으로 대체하는 것을 권장합니다.
TOP_10_TICKERS = [
    "KRW-BTC", "KRW-ETH", "KRW-SOL", "KRW-XRP", "KRW-ADA", 
    "KRW-LINK", "KRW-SUI", "KRW-ONDO", "KRW-SEI", "KRW-VIRTUAL"
] 
# 유동성이 높은 코인으로 시스템의 부하를 줄이고 수익률 극대화에 기여

def get_best_ticker():
    """
    🎯 10만원→10억 반등 포착 통합 시스템
    
    핵심 로직: 볼린저밴드 하단 + RSI 과매도 반등 패턴을 정확히 포착
    - 1차: 5분봉으로 빠른 반등 신호 감지 (ATR 기반 모멘텀 강화)
    - 2차: 1시간봉으로 정밀 확신도 검증 (MACD 다이버전스 기반 '진짜 반등' 확신)
    - 최종: 가장 확실한 반등 기회 1개 선택
    """
    
    # ========== STEP 1: 기본 설정 및 보유 코인 제외 (분석 대상 TOP 10으로 한정) ==========
    try:
        # 보유 코인 목록 추출
        balances = upbit.get_balances()
        held_coins = {f"KRW-{b['currency']}" for b in balances if float(b.get('balance', 0)) > 0}
        
        # TOP 10 코인 중 보유 코인 제외
        all_tickers = [t for t in TOP_10_TICKERS if t not in held_coins]
        
        print(f"🎯 반등 포착 통합 시스템 시작 - 분석 대상 (TOP 10): {len(all_tickers)}개")
        
    except Exception as e:
        print(f"❌ 초기화 실패 (보유 코인 및 TOP 10 필터링): {e}")
        return None
    
    # 예외 상황 처리 (TOP 10 코인을 모두 보유하고 있을 경우)
    if not all_tickers:
        print("💡 TOP 10 코인 모두 보유 중이거나 분석 대상이 없습니다.")
        return None
        
    # ========== STEP 2: 1차 스크리닝 - 5분봉 빠른 반등 신호 감지 (ATR 모멘텀 추가) ==========
    print("🔍 1차 스크리닝: 5분봉 반등 신호 감지 중...")
    
    primary_candidates = []
    
    for ticker in all_tickers:
        try:
            # 5분봉 40개 = 3시간 20분 데이터
            df_5m = pyupbit.get_ohlcv(ticker, interval="minute5", count=40)
            current_price = pyupbit.get_current_price(ticker)
            
            if df_5m is None or len(df_5m) < 30 or current_price is None:
                time.sleep(0.1) # 데이터 부족/오류 발생 시에도 API 부하 방지
                continue
            
            closes = df_5m['close'].values
            volumes = df_5m['volume'].values
            
            # === 지표 계산을 위한 헬퍼 함수 ===
            def calculate_rsi(prices, period=14):
                # (기존 RSI 계산 로직 유지)
                deltas = np.diff(prices)
                gains = np.where(deltas > 0, deltas, 0)
                losses = np.where(deltas < 0, -deltas, 0)
                
                # Simple Moving Average for initial RSI
                if len(gains) < period: return 50.0 # Not enough data
                avg_gain = np.mean(gains[:period])
                avg_loss = np.mean(losses[:period])
                
                # Exponentially Smoothed RSI (for the most recent value)
                for i in range(period, len(prices)-1):
                    avg_gain = (avg_gain * (period - 1) + gains[i]) / period
                    avg_loss = (avg_loss * (period - 1) + losses[i]) / period

                rs = avg_gain / (avg_loss + 1e-8)
                rsi = 100 - (100 / (1 + rs))
                return rsi

            def calculate_atr(df, period=14):
                # True Range (TR)
                high_low = df['high'] - df['low']
                high_prev_close = np.abs(df['high'] - df['close'].shift(1))
                low_prev_close = np.abs(df['low'] - df['close'].shift(1))
                tr = pd.concat([high_low, high_prev_close, low_prev_close], axis=1).max(axis=1)
                
                # Average True Range (ATR)
                return tr.rolling(period).mean().iloc[-1]
                
            # === 볼린저밴드 반등 패턴 감지 ===
            bb_period = 20
            sma20 = np.mean(closes[-bb_period:])
            std20 = np.std(closes[-bb_period:])
            bb_lower = sma20 - (2.0 * std20)
            
            # 하단 돌파 후 복귀 패턴 확인 (최근 5봉)
            bb_breakthrough = False
            bb_recovery = False
            recent_closes = closes[-5:]
            for price in recent_closes:
                if price < bb_lower:
                    bb_breakthrough = True
                if bb_breakthrough and current_price > bb_lower:
                    bb_recovery = True
                    break
            
            # === RSI 과매도 반등 감지 ===
            current_rsi = calculate_rsi(closes)
            
            # RSI 상승 전환 확인
            rsi_uptrend = False
            if len(closes) >= 17: # 14+1+2
                prev_rsi = calculate_rsi(closes[:-2])
                rsi_uptrend = current_rsi > prev_rsi
            
            # === 거래량 급증 확인 (기존 로직 유지) ===
            recent_volume = np.mean(volumes[-3:])
            avg_volume = np.mean(volumes[-15:-3])
            volume_surge = recent_volume / (avg_volume + 1e-8)
            
            # === ⚡ 수익률 극대화 로직 추가: ATR 기반 반전 모멘텀 감지 (5분봉) ===
            try:
                import pandas as pd # pandas import를 함수 내에서 처리 (get_ohlcv 사용을 위해 이미 pyupbit에 의해 로드되었을 가능성이 높지만 안전하게 처리)
                df_5m_pd = pyupbit.get_ohlcv(ticker, interval="minute5", count=40)
                current_atr = calculate_atr(df_5m_pd, period=14)
            except:
                 current_atr = 0.001 # 안전 장치
                 
            # 최근 캔들의 크기 (종가 - 시가)
            last_candle_size = abs(closes[-1] - df_5m['open'].iloc[-1])
            # 캔들 크기가 ATR의 50% 이상 (강한 변동성) + 시가 대비 종가가 상승 (반전)
            atr_momentum = (last_candle_size >= current_atr * 0.5) and (closes[-1] > df_5m['open'].iloc[-1])
            
            # === 1차 통과 조건 ===
            bb_signal = bb_recovery or (current_price < bb_lower * 1.01)
            rsi_signal = current_rsi <= 35 and (rsi_uptrend or current_rsi <= 25)
            volume_signal = volume_surge >= 1.3
            # ATR 모멘텀 신호는 필수 조건은 아니지만, 통과 기준에 포함하여 변동성 기반 수익 극대화에 활용
            
            # 기본 필터
            price_valid = 100 <= current_price <= 100000
            
            # 급등 제외 (기존 로직 유지)
            df_1d = pyupbit.get_ohlcv(ticker, interval="day", count=1)
            daily_change = 0
            if df_1d is not None and not df_1d.empty:
                daily_open = df_1d['open'].iloc[-1]
                daily_change = (current_price - daily_open) / daily_open * 100
            not_surged = daily_change < 8.0 # 당일 8% 이상 급등한 종목은 제외
            
            # 1차 통과 (4개 조건 중 2개 이상 + 기본 조건)
            signal_count = sum([bb_signal, rsi_signal, volume_signal, atr_momentum]) # ATR 모멘텀 추가
            
            if signal_count >= 2 and price_valid and not_surged:
                primary_candidates.append({
                    'ticker': ticker,
                    'current_rsi': current_rsi,
                    'volume_surge': volume_surge,
                    'daily_change': daily_change,
                    'current_price': current_price,
                    'bb_signal': bb_signal,
                    'rsi_signal': rsi_signal,
                    'volume_signal': volume_signal,
                    'atr_momentum': atr_momentum # ATR 모멘텀 추가
                })
                
                print(f"✅ 1차 통과: {ticker} (RSI:{current_rsi:.1f}, 거래량:{volume_surge:.1f}x, ATR모멘텀:{'ON' if atr_momentum else 'OFF'})")
            
            time.sleep(0.1) # ⚡ API 부하 방지 및 안정적인 데이터 요청을 위해 딜레이 조정 (0.03초 -> 0.1초)
            
        except Exception as e:
            # print(f"❌ 1차 스크리닝 오류 ({ticker}): {e}") # 디버깅 시 주석 해제
            continue
    
    print(f"🔍 1차 결과: {len(TOP_10_TICKERS)}개 → {len(primary_candidates)}개 선별")
    
    if not primary_candidates:
        print("💡 1차 스크리닝에서 반등 신호가 감지되지 않았습니다.")
        return None
    
    # ========== STEP 3: 2차 정밀 분석 - 1시간봉 확신도 검증 (MACD 다이버전스 추가) ==========
    print("🎯 2차 정밀 분석: 1시간봉 확신도 검증 중...")
    
    final_candidates = []
    
    for candidate in primary_candidates:
        try:
            ticker = candidate['ticker']
            
            # 1시간봉 24개 = 24시간 데이터로 정밀 분석
            df_1h = pyupbit.get_ohlcv(ticker, interval="minute60", count=34) # MACD 계산을 위해 데이터 개수 증가 (12, 26, 9)
            
            if df_1h is None or len(df_1h) < 30:
                time.sleep(0.1)
                continue
            
            closes = df_1h['close'].values
            volumes = df_1h['volume'].values
            current_price = candidate['current_price']
            
            # === 고급 볼린저밴드 분석 (기존 로직 유지) ===
            bb_period = 20
            sma20 = np.mean(closes[-bb_period:])
            std20 = np.std(closes[-bb_period:])
            bb_upper = sma20 + (2.0 * std20)
            bb_lower = sma20 - (2.0 * std20)
            
            bb_position = (current_price - bb_lower) / (bb_upper - bb_lower) * 100
            
            # 하단 접촉 분석
            lower_touches = 0
            recovery_strength = 0
            
            for i in range(5):  # 최근 5시간
                if closes[-1-i] <= bb_lower * 1.02:
                    lower_touches += 1
                    
                # 반등 강도
                if i > 0 and closes[-1-i] < bb_lower and closes[-1-i+1] > bb_lower:
                    recovery_strength = (current_price - closes[-1-i]) / closes[-1-i] * 100
            
            # === 고급 RSI 분석 (기존 로직 유지) ===
            def advanced_rsi(prices, period=14):
                 # (기존 EMA 기반 RSI 계산 로직 유지)
                deltas = np.diff(prices)
                gains = np.where(deltas > 0, deltas, 0)
                losses = np.where(deltas < 0, -deltas, 0)
                
                alpha = 2.0 / (period + 1)
                
                # Initial SMA for the first 'period' values
                if len(gains) < period: return 50.0
                avg_gain = np.mean(gains[:period])
                avg_loss = np.mean(losses[:period])
                
                # Apply EMA from period+1 onwards
                for i in range(period, len(prices)-1):
                    avg_gain = alpha * gains[i] + (1 - alpha) * avg_gain
                    avg_loss = alpha * losses[i] + (1 - alpha) * avg_loss
                
                rs = avg_gain / (avg_loss + 1e-8)
                rsi = 100 - (100 / (1 + rs))
                return rsi
            
            current_rsi = advanced_rsi(closes)
            
            # RSI 반등 패턴
            rsi_reversal = False
            if len(closes) >= 17:
                rsi_3h_ago = advanced_rsi(closes[:-3])
                rsi_1h_ago = advanced_rsi(closes[:-1])
                
                if rsi_3h_ago <= 30 and current_rsi > rsi_1h_ago and current_rsi > rsi_3h_ago:
                    rsi_reversal = True
            
            # === 거래량 패턴 분석 (기존 로직 유지) ===
            recent_vol = np.mean(volumes[-3:])
            normal_vol = np.mean(volumes[-12:-3])
            volume_expansion = recent_vol / (normal_vol + 1e-8)
            
            # === 💎 수익률 극대화 로직 추가: MACD 상승 다이버전스 감지 (1시간봉) ===
            
            def calculate_macd(prices, fast_period=12, slow_period=26, signal_period=9):
                # MACD 계산 (EMA 기반)
                exp1 = pd.Series(prices).ewm(span=fast_period, adjust=False).mean()
                exp2 = pd.Series(prices).ewm(span=slow_period, adjust=False).mean()
                macd_line = exp1 - exp2
                signal_line = macd_line.ewm(span=signal_period, adjust=False).mean()
                histogram = macd_line - signal_line
                return macd_line.iloc[-1], signal_line.iloc[-1], histogram.iloc[-1], macd_line.values
            
            try:
                import pandas as pd
                df_1h_pd = pyupbit.get_ohlcv(ticker, interval="minute60", count=60) # 충분한 MACD 계산 데이터 확보
                macd_val, signal_val, hist_val, macd_series = calculate_macd(df_1h_pd['close'].values)

                # MACD 다이버전스 검증: 가격은 저점 낮아짐, MACD는 저점 높아짐
                macd_divergence = False
                
                # 최근 10봉 이내의 저점 확인
                recent_low_price_idx = df_1h_pd['low'].iloc[-10:].idxmin()
                
                # 1. 가격 저점은 이전 저점보다 낮거나 비슷
                if df_1h_pd['low'].iloc[-1] <= df_1h_pd['low'].loc[recent_low_price_idx] * 1.005: # 현재 저점
                    # 2. MACD는 이전 저점보다 높아짐 (divergence)
                    # 이전 MACD 저점 확인 (가격 저점 인근 10봉 이내)
                    low_macd_val = macd_series[-10:][::-1][(df_1h_pd['low'].iloc[-10:]).argmin()] # 대략적인 가격 저점 시점의 MACD
                    current_macd_val = macd_series[-1]
                    
                    if low_macd_val < 0 and current_macd_val < 0 and current_macd_val > low_macd_val * 1.05: # 음수 영역에서 MACD 저점이 높아짐
                        macd_divergence = True
                        
            except:
                macd_divergence = False
                
            # === 최종 확신도 계산 (0-100점) ===
            confidence = 0
            signals = []
            
            # 볼린저밴드 점수 (40점 만점)
            if lower_touches >= 2 and recovery_strength > 2:
                confidence += 40
                signals.append(f"BB완벽반등({lower_touches}회접촉)")
            elif lower_touches >= 1 and bb_position < 25:
                confidence += 30
                signals.append(f"BB하단반등")
            elif bb_position < 35:
                confidence += 20
                signals.append(f"BB하단권({bb_position:.0f}%)")
            
            # RSI 점수 (35점 만점)
            if current_rsi <= 25 and rsi_reversal:
                confidence += 35
                signals.append(f"RSI강력반전({current_rsi:.1f})")
            elif current_rsi <= 30 and rsi_reversal:
                confidence += 28
                signals.append(f"RSI반전({current_rsi:.1f})")
            elif current_rsi <= 35:
                confidence += 18
                signals.append(f"RSI과매도({current_rsi:.1f})")
            
            # 거래량 점수 (25점 만점)
            if volume_expansion >= 2.5:
                confidence += 25
                signals.append(f"거래량폭발({volume_expansion:.1f}x)")
            elif volume_expansion >= 2.0:
                confidence += 20
                signals.append(f"거래량급증({volume_expansion:.1f}x)")
            elif volume_expansion >= 1.5:
                confidence += 15
                signals.append(f"거래량증가({volume_expansion:.1f}x)")
                
            # 💎 MACD 다이버전스 가점 (최고 수익률을 위한 폭발적 반등 신호, 10점 추가)
            if macd_divergence:
                confidence += 10
                signals.append("MACD강력다이버전스")
            
            # ⚡ 5분봉 ATR 모멘텀 가점 (빠른 반전을 위한 모멘텀, 5점 추가)
            if candidate['atr_momentum']:
                confidence += 5
                signals.append("5분ATR반전모멘텀")
            
            # === 최종 확신도 75점 이상만 통과 ===
            if confidence >= 75:
                final_candidates.append({
                    'ticker': ticker,
                    'confidence': confidence,
                    'current_rsi': current_rsi,
                    'bb_position': bb_position,
                    'volume_expansion': volume_expansion,
                    'recovery_strength': recovery_strength,
                    'signals': signals,
                    'current_price': current_price,
                    'daily_change': candidate['daily_change']
                })
                
                grade = "🚀 PERFECT" if confidence >= 90 else "⭐ EXCELLENT" if confidence >= 85 else "✅ STRONG"
                print(f"{grade}: {ticker} (확신도:{confidence}점)")
                print(f"  └ {', '.join(signals[:2])}")
            
            time.sleep(0.1) # ⚡ 2차 분석 간에도 딜레이 적용
            
        except Exception as e:
            # print(f"❌ 2차 정밀 분석 오류 ({ticker}): {e}") # 디버깅 시 주석 해제
            continue
    
    print(f"🎯 2차 결과: {len(primary_candidates)}개 → {len(final_candidates)}개 최종 선별")
    
    # ========== STEP 4: 최고 확신도 종목 선택 ==========
    if not final_candidates:
        print("💡 확신도 75점 이상의 반등 기회가 없습니다. 대기 중...")
        return None
    
    # 확신도 기준 정렬
    final_candidates.sort(key=lambda x: x['confidence'], reverse=True)
    best = final_candidates[0]
    
    # 결과 출력
    confidence_level = "🚀 완벽한 반등" if best['confidence'] >= 90 else "⭐ 강력한 반등" if best['confidence'] >= 85 else "✅ 확실한 반등"
    
    print("=" * 80)
    print(f"🎯 **반등 포착 완료**: {best['ticker']}")
    print(f"📊 **확신도**: {best['confidence']}점 ({confidence_level})")
    print(f"📈 **지표**: RSI {best['current_rsi']:.1f} | BB위치 {best['bb_position']:.0f}% | 거래량 {best['volume_expansion']:.1f}배")
    print(f"🔥 **신호**: {', '.join(best['signals'])}")
    print(f"💰 **가격**: {best['current_price']:,}원 (당일 {best['daily_change']:+.1f}%)")
    print("=" * 80)
    
    # 디스코드 알림
    try:
        filtered_time = datetime.now().strftime('%m/%d %H:%M:%S')
        discord_msg = f"🎯 {filtered_time} {confidence_level}!\n"
        discord_msg += f"{best['ticker']} (확신도 {best['confidence']}점)\n"
        discord_msg += f"RSI:{best['current_rsi']:.1f} | BB:{best['bb_position']:.0f}% | 거래량:{best['volume_expansion']:.1f}x\n"
        discord_msg += f"{best['signals'][0] if best['signals'] else '반등신호'}"
        
        send_discord_message(discord_msg)
        print("📱 반등 알림 전송 완료")
        
    except Exception as e:
        print(f"📱 알림 전송 실패: {e}")
    
    print(f"🚀 **최종 선택**: {best['ticker']} - {best['confidence']}점 확신도로 반등 기회 포착!")
    
    return best['ticker']


def trade_buy(ticker):
    """
    개선된 매수 로직 - 리스크 관리와 최적 타이밍 포함
    
    🎯 10만원→10억 목표를 위한 공격적 소액 투자 및 V자 반등 초입 매매 전략 강화.
    - 모든 로직을 함수 내부에 통합.
    - 초기 소액 시드머니 성장을 위한 '잔고 전액 공격적 매수' 전략 적용.
    - 볼린저밴드 하단 + 꼬리 패턴 기반 V자 반등 매매 필터 강화.
    """

    # ========== 함수 내 TA 및 헬퍼 로직 통합 ==========

    def calculate_rsi(closes, period=14):
        # TA-Lib 없이 numpy로 RSI 계산
        deltas = np.diff(closes)
        gains = np.where(deltas > 0, deltas, 0)
        losses = np.where(deltas < 0, -deltas, 0)
        
        avg_gain = np.mean(gains[:period])
        avg_loss = np.mean(losses[:period])
        
        # EMA 평활화 (RMA 또는 WMA 근사)
        for i in range(period, len(closes)-1):
            avg_gain = (avg_gain * (period - 1) + gains[i-1]) / period
            avg_loss = (avg_loss * (period - 1) + losses[i-1]) / period
        
        rs = avg_gain / (avg_loss + 1e-8)
        rsi = 100 - (100 / (1 + rs))
        return rsi

    def calculate_ema(closes, period=12):
        # TA-Lib 없이 numpy로 EMA 계산
        ema = [closes[0]]
        alpha = 2 / (period + 1)
        for close in closes[1:]:
            ema.append(alpha * close + (1 - alpha) * ema[-1])
        return ema[-1]

    def calculate_bb(closes, window=20, std_dev=2.0):
        # TA-Lib 없이 numpy로 볼린저 밴드 계산
        sma = np.mean(closes[-window:])
        std = np.std(closes[-window:])
        lower_band = sma - (std * std_dev)
        upper_band = sma + (std * std_dev)
        return lower_band, upper_band

    def get_krw_balance():
        # 잔고 조회 로직 통합
        try:
            balances = upbit.get_balances()
            for b in balances:
                if b['currency'] == "KRW":
                    return float(b['balance'])
            return 0.0
        except Exception:
            return 0.0
            
    # ========== 1. 잔고 및 자산 분석 ==========
    
    krw = get_krw_balance()
    print(f"💰 보유 원화: {krw:,.0f}원")

    balances = upbit.get_balances()
    significant_assets_count = 0
    total_asset_value = krw # 원화 잔고부터 시작
    excluded_coins = {"KRW", "QI", "ONX", "ETHF", "ETHW", "PURSE"}
    
    print("📊 보유 자산 분석 시작...")
    for b in balances:
        currency = b['currency']
        balance = float(b['balance'])
        
        if currency in excluded_coins or balance <= 0:
            continue
        
        try:
            asset_ticker = f"KRW-{currency}"
            current_price = pyupbit.get_current_price(asset_ticker)
            time.sleep(0.05) # API 부하 방지
            
            if current_price is None or current_price <= 0:
                continue
                
            asset_value = balance * current_price
            total_asset_value += asset_value
            
            # print(f"📈 {currency}: 평가금액 {asset_value:,.0f}원") # 너무 상세한 로그 생략
            
            if asset_value >= 10000:
                significant_assets_count += 1
                
        except Exception:
            continue

    print(f"📋 분석 완료: 총 {significant_assets_count}개 자산이 1만원 이상, 총 평가금액 {total_asset_value:,.0f}원")

    # === 2. 매수 금액 결정 (10만원->10억 목표를 위한 공격적 전략) ===
    buy_size = 0
    MIN_ORDER_AMOUNT = 5000 # min_krw 대신 상수 5000원 사용 (외부 변수 제거)
    STANDARD_BUY_AMOUNT = 100000  # 표준 매수 금액 (10만원)

    print(f"\n🎯 매수 전략 결정 중...")

    # 잔고가 최소 주문 금액 미만인 경우
    if krw < MIN_ORDER_AMOUNT:
        print(f"❌ 원화 잔고가 최소 주문 금액({MIN_ORDER_AMOUNT:,}원) 미만입니다.")
        buy_size = 0
    
    # ⭐ 천재적 발상 1: 시드머니 성장을 위한 공격적 매수 (10만원 미만 전액)
    elif krw < STANDARD_BUY_AMOUNT * 0.99: # 10만원에 근접해도 전액 매수 시도
        buy_size = krw * 0.9995  # 수수료 고려하여 99.95% 매수
        print(f"💡 원화 잔고가 10만원 미만 → **공격적 전액 매수** 전략 적용")
        print(f"💵 전액 매수 금액: {buy_size:,.0f}원 (원화의 99.95%)")
        
        if buy_size < MIN_ORDER_AMOUNT:
            buy_size = 0
            print(f"⚠️ 수수료 제외 후 금액이 최소 주문 금액({MIN_ORDER_AMOUNT:,}원) 미만입니다.")

    # 잔고가 10만원 이상인 경우 → 표준 매수 금액
    else:
        # 분산 투자/리스크 관리 차원에서 10만원만 매수
        buy_size = STANDARD_BUY_AMOUNT 
        print(f"🚀 10만원 단위 DCA 매수 전략 적용")
        print(f"💵 표준 매수 금액: {buy_size:,.0f}원")
        print(f"💰 매수 후 잔여 원화: {krw - buy_size:,.0f}원")

    print(f"🔥 최종 매수 예정 금액: {buy_size:,.0f}원")

    if buy_size <= MIN_ORDER_AMOUNT:
        if krw > 0:
            print(f"\n❌ 매수 조건을 만족하지 않습니다. 잔고: {krw:,.0f}원.")
        return "Buy size too small or insufficient balance", None

    # === 3. 기술적 분석 및 매수 실행 로직 ===
    max_retries = 5
    attempt = 0
    
    # 5분봉 데이터 가져오기 (50개봉)
    df = pyupbit.get_ohlcv(ticker, interval="minute5", count=50)
    time.sleep(0.3)
    if df is None or len(df) < 30:
        send_discord_message(f"[매수실패] {ticker} 데이터 부족/가져오기 실패")
        return "Data fetch failed", None
    
    cur_price = pyupbit.get_current_price(ticker)
    time.sleep(0.1) # 가격 재확인
    df_close = df['close'].values
    df_high = df['high'].values
    df_low = df['low'].values
    df_open = df['open'].values
    df_volume = df['volume'].values
    
    # === TA 지표 계산 (함수 내 통합) ===
    rsi = calculate_rsi(df_close, period=14)
    last_ema = calculate_ema(df_close, period=12)
    lower_band, upper_band = calculate_bb(df_close, window=30, std_dev=2.2)
    
    bb_position = (cur_price - lower_band) / (upper_band - lower_band)
    price_ma20 = df_close[-20:].mean()
    volume_ma5 = df_volume[-5:].mean()
    volume_ma20 = df_volume[-20:].mean()
    recent_drop = (df_close[-1] - df_close[-5]) / df_close[-5]
    
    # RSI 배열의 마지막 값만 필요 (단일 값으로 가정)
    current_rsi = rsi 
    
    # ⭐ 천재적 발상 2: V자 반등 초입 포착 (꼬리 길이 및 매물대 지지)
    
    # a) 꼬리 길이 확인 (Strong Hammer / Pin Bar)
    last_candle_open = df_open[-1]
    last_candle_low = df_low[-1]
    last_candle_close = df_close[-1]
    
    # 꼬리 길이 (최저가 - 시가/종가 중 낮은 값)
    tail_length = abs(min(last_candle_open, last_candle_close) - last_candle_low)
    # 캔들 본통 길이 (시가 - 종가)
    body_length = abs(last_candle_open - last_candle_close)
    # 전체 캔들 길이 (고가 - 저가)
    full_length = df_high[-1] - last_candle_low

    # 꼬리가 본통의 2배 이상 + 캔들 전체 길이의 50% 이상 (강력한 매수 압력)
    strong_tail_buy = (full_length > 0) and (tail_length >= body_length * 2) and (tail_length / full_length > 0.5)

    # b) 하락 후 회복 강도 (Low-to-Close Recovery)
    # 저점에서 종가까지 회복률
    recovery_rate = (last_candle_close - last_candle_low) / (full_length + 1e-8) if full_length > 0 else 0
    strong_recovery = recovery_rate > 0.6 # 60% 이상 회복
    
    # c) 매물대 지지 여부 확인 (25봉 이내 최저가 대비)
    price_low_25 = np.min(df_low[-25:-1])
    is_at_support = (cur_price > price_low_25 * 0.995) and (cur_price < price_low_25 * 1.005) # 최근 저점 부근 지지

    # 최종 매수 시도 루프
    if krw >= MIN_ORDER_AMOUNT:
        while attempt < max_retries:
            attempt += 1
            cur_price = pyupbit.get_current_price(ticker)  # 매번 최신 가격 업데이트
            time.sleep(0.1)
            
            print(f"[매수 조건 확인]: {ticker} 현재가: {cur_price:,.2f} / 시도: {attempt}/{max_retries}")
            
            # === 핵심 매수 조건 체크 ===
            
            # 기본 조건: V자 반등 초입 (BB 하단 + RSI 상승 전환)
            basic_condition = (
                cur_price < last_ema and # EMA 아래에서 매수
                current_rsi > rsi_buy_s and current_rsi < rsi_buy_e and # RSI 과매도 구간 (ex: 25 < RSI < 40)
                current_rsi > calculate_rsi(df_close[:-1], period=14) # RSI 상승 전환
            )
            
            # 안전 및 수익 극대화 조건들 (6개 안전조건 중 4개 이상 충족 -> 7개 중 5개로 강화)
            safety_conditions = [
                bb_position < 0.35,              # 1. 볼린저 밴드 하위 35% 구간 (더 깊은 과매도)
                strong_tail_buy or strong_recovery, # 2. (NEW) 강력한 꼬리 패턴 또는 급속 회복 (V자 반등)
                volume_ma5 > volume_ma20 * 1.1,  # 3. (강화) 거래량 10% 이상 증가 (매수세 유입 확인)
                recent_drop > -0.05,             # 4. 최근 5% 이상 급락 아님 (점진적 하락)
                cur_price > price_ma20 * 0.90,   # 5. 20일 이평선 대비 10% 이상 하락 아님
                is_at_support,                   # 6. (NEW) 최근 매물대 지지 확인
                abs(recent_drop) < 0.15          # 7. 극단적 변동 아님 (±15%)
            ]
            
            safety_score = sum(safety_conditions)
            
            # 매수 실행 조건
            if basic_condition and safety_score >= 5:  # 7개 조건 중 5개 이상 충족 (강화된 확신)
                
                # === 스마트 매수 실행 (거래 안정성 강화) ===
                buy_attempts = 3
                for i in range(buy_attempts):
                    try:
                        # ⚡ 거래 안정성 강화: 매수 직전 1분 변동성 확인
                        df_last_1m = pyupbit.get_ohlcv(ticker, interval="minute1", count=2)
                        time.sleep(0.05)
                        if df_last_1m is not None and len(df_last_1m) == 2:
                             last_1m_change = abs(df_last_1m['close'].iloc[-1] - df_last_1m['open'].iloc[-1]) / df_last_1m['open'].iloc[-1]
                             if last_1m_change > 0.01: # 1분만에 1% 이상 변동시 매수 취소
                                 send_discord_message(f"[매수취소] {ticker} 1분봉 급변동 감지: {last_1m_change:.2%}")
                                 return "Price volatility too high (1M check)", None
                                 
                        final_price = pyupbit.get_current_price(ticker) # 최종 가격 재확인
                        
                        # 시장가 매수
                        buy_order = upbit.buy_market_order(ticker, buy_size)
                        
                        # 매수 성공 메시지
                        buyedmsg = f"✅ ★★매수 성공★★: {ticker} (🎯 10만->10억 전략)\n"
                        buyedmsg += f"💰 매수가: {final_price:,.2f} | 금액: {buy_size:,.0f}원\n"
                        buyedmsg += f"📊 RSI: {current_rsi:,.1f} | BB위치: {bb_position:.1%}\n"
                        buyedmsg += f"📈 안전점수: {safety_score}/7 | 꼬리강도: {'ON' if strong_tail_buy else 'OFF'}"
                        
                        print(buyedmsg)
                        send_discord_message(buyedmsg)
                        return buy_order

                    except Exception as e:
                        error_msg = f"매수 주문 실행 중 오류: {e}, 재시도 중...({i+1}/{buy_attempts})"
                        print(error_msg)
                        send_discord_message(error_msg)
                        time.sleep(5 * (i + 1))
                
                return "Buy order failed after retries", None
            
            else:
                # 조건 미충족 상세 로그
                condition_msg = f"[매수 대기]: {ticker} ({attempt}/{max_retries})\n"
                condition_msg += f"현재가: {cur_price:,.2f} | EMA: {last_ema:,.2f} ({((cur_price/last_ema-1)*100):+.2f}%)\n"
                condition_msg += f"RSI: {current_rsi:,.1f} | BB위치: {bb_position:.1%} | 안전점수: {safety_score}/7 | 기본조건: {basic_condition}"
                
                print(condition_msg)
                if attempt == max_retries:
                    send_discord_message(condition_msg)
                
                time.sleep(10)  # 10초 대기 후 재시도
        
        # 최대 시도 횟수 초과
        final_fail_msg = f"❌ **매수 실패**: {ticker} (최대 시도 초과)\n"
        final_fail_msg += f"최종가: {cur_price:,.2f} | RSI: {current_rsi:,.1f} | BB위치: {bb_position:.1%}\n"
        final_fail_msg += f"사유: {max_retries}회 시도 후 조건 미충족 (점수: {safety_score}/7)"
        
        print(final_fail_msg)
        send_discord_message(final_fail_msg)
        return "Max attempts exceeded", None
    
    else:
        # 잔고 부족 시
        insufficient_msg = f"💸 **잔고 부족**: 현재 {krw:,.0f}원 < 최소 {MIN_ORDER_AMOUNT:,.0f}원"
        print(insufficient_msg)
        send_discord_message(insufficient_msg)
        return "Insufficient balance", None
    
def trade_sell(ticker):
    """
    [10만원 → 10억] 목표를 위한 '슈퍼-탐욕 보존' 매도 로직 통합 (단일 함수)
    
    모든 기술적 지표 계산, 신호 분석, 매도 실행 로직을 통합합니다.
    """

    # ========== 1. 내부 TA 계산 로직 통합 (MACD, BB, RSI) ==========

    def calculate_macd_bb_volume(df):
        # 1. MACD
        exp1 = df['close'].ewm(span=12, adjust=False).mean()
        exp2 = df['close'].ewm(span=26, adjust=False).mean()
        df['macd'] = exp1 - exp2
        df['macd_signal'] = df['macd'].ewm(span=9, adjust=False).mean()
        
        # 2. 볼린저 밴드 (20, 2.0)
        df['bb_mid'] = df['close'].rolling(window=20).mean()
        df['bb_std'] = df['close'].rolling(window=20).std()
        df['bb_upper'] = df['bb_mid'] + (df['bb_std'] * 2.0)
        df['bb_position'] = (df['close'] - df['bb_mid']) / df['bb_std']
        
        # 3. 거래량 스파이크
        df['volume_avg'] = df['volume'].rolling(window=10).mean()
        df['volume_spike'] = df['volume'] / df['volume_avg']
        
        return df

    def calculate_rsi(closes, period=14):
        # TA-Lib 없이 numpy로 RSI 계산 (단일 값만 반환하도록 단순화)
        diff = np.diff(closes)
        gains = np.where(diff > 0, diff, 0)
        losses = np.where(diff < 0, -diff, 0)
        
        avg_gain = np.mean(gains[:period])
        avg_loss = np.mean(losses[:period])
        
        for i in range(period, len(closes)):
            avg_gain = (avg_gain * (period - 1) + gains[i-1]) / period
            avg_loss = (avg_loss * (period - 1) + losses[i-1]) / period
        
        rs = avg_gain / (avg_loss + 1e-8)
        rsi = 100 - (100 / (1 + rs))
        return rsi

    # ========== 2. 초기 잔고, 수익률, 데이터 확인 ==========
    currency = ticker.split("-")[1]
    
    try:
        buyed_amount = get_balance(currency)
        if buyed_amount <= 0: return None
        
        avg_buy_price = upbit.get_avg_buy_price(currency)
        cur_price = pyupbit.get_current_price(ticker)
        if cur_price is None: return None
        
        profit_rate = (cur_price - avg_buy_price) / avg_buy_price * 100 if avg_buy_price > 0 else 0
        
    except Exception as e:
        print(f"[{ticker}] 초기 정보 조회 오류: {e}")
        return None

    # 5분봉 데이터 수집
    df_5m = pyupbit.get_ohlcv(ticker, interval="minute5", count=50)
    time.sleep(0.3)
    if df_5m is None or len(df_5m) < 30:
        print(f"[{ticker}] 5분봉 데이터 부족")
        return None
    
    df_5m = calculate_macd_bb_volume(df_5m)
    latest = df_5m.iloc[-1]
    prev = df_5m.iloc[-2]
    prev2 = df_5m.iloc[-3]
    
    # RSI 계산 (배열의 마지막 값을 사용)
    current_rsi = calculate_rsi(df_5m['close'].values, period=14)
    rsi_prev = calculate_rsi(df_5m['close'].values[:-1], period=14)
    
    # ========== 3. 손절 로직 (가장 우선) ==========
    
    # 손절 조건 강화 (급락 시 매도)
    if profit_rate < cut_rate:
        # 단기(1분봉) 급락을 추가로 확인하여, 단순 노이즈가 아닌 강력한 하락임을 검증
        df_1m = pyupbit.get_ohlcv(ticker, interval="minute1", count=5)
        time.sleep(0.1)
        if df_1m is not None and len(df_1m) >= 3:
            # 1분봉 3개 동안 2% 이상 하락 시 무조건 손절
            recent_drop_1m = (df_1m['close'].iloc[-1] - df_1m['open'].iloc[-3]) / df_1m['open'].iloc[-3]
            if recent_drop_1m < -0.02: 
                sell_order = upbit.sell_market_order(ticker, buyed_amount)
                cut_message = f"❌ **[긴급 손절]**: [{ticker}] 수익률: {profit_rate:.2f}% / 현재가: {cur_price:,.1f}\n"
                cut_message += f"사유: 1분봉 3개 급락(-2% 이상) 감지! / RSI: {current_rsi:.1f}"
                print(cut_message)
                send_discord_message(cut_message)
                return sell_order
        
        # 일반 손절은 대기
        
    # ========== 4. 매도 신호 강도 계산 및 요구 점수 결정 ==========
    
    signals = []
    sell_strength = 0  # 매도 신호 강도 점수
    required_score = 0
    
    # A. 볼린저 밴드 상단 이탈 후 급락 (최고 강도 3점)
    bb_position = latest['bb_position']
    if prev['bb_position'] > 2.0 and bb_position < prev['bb_position']:
        signals.append("볼밴상단급락")
        sell_strength += 3

    # B. 거래량 동반 20일선 이탈 (강력 추세 반전 3점)
    volume_spike = latest['volume_spike']
    if latest['close'] < latest['bb_mid'] and prev['close'] > prev['bb_mid'] and volume_spike > 1.3:
        signals.append("20일선대량이탈")
        sell_strength += 3

    # C. MACD 하향 크로스 (모멘텀 상실 2점)
    macd_cross_down = (prev['macd'] > prev['macd_signal']) and (latest['macd'] < latest['macd_signal'])
    if macd_cross_down:
        signals.append("MACD하향크로스")
        sell_strength += 2

    # D. RSI 80 이상 과열 후 하락 (과열 해소 2점)
    if current_rsi > 80 and rsi_prev > current_rsi:
        signals.append("RSI극과열하락")
        sell_strength += 2
        
    # E. 연속 3틱 이상 음봉 (단기 모멘텀 붕괴 1~3점)
    consecutive_down = 0
    if len(df_5m) >= 4:
        if df_5m.iloc[-1]['close'] < df_5m.iloc[-2]['close'] < df_5m.iloc[-3]['close']:
            consecutive_down = 3
            if df_5m.iloc[-4]['close'] > df_5m.iloc[-3]['close']:
                 consecutive_down += 1
    
    if consecutive_down >= 3:
        signals.append(f"연속{consecutive_down}틱하락")
        sell_strength += (consecutive_down - 2)

    # 매도 요구 점수 설정 (탐욕 보존 필터)
    if profit_rate >= max_rate: 
        required_score = 1 # 목표 달성: 약한 신호(1점)만으로도 매도
        required_score_text = "목표 달성 (1점)"
    elif profit_rate >= min_rate:
        # 10만원으로 10억 만들려면, 쉽게 팔면 안됨. 최소 4점 이상의 강력한 신호만 매도
        required_score = 4 
        required_score_text = "탐욕 보존 (4점)"
    else: 
        required_score = 5 # 낮은 수익/본전: 강력한 위험 감지 시 매도
        required_score_text = "리스크 헷지 (5점)"
        
    should_sell_technical = sell_strength >= required_score
    signal_text = " + ".join(signals) + f" (강도:{sell_strength}/{required_score_text})"
    
    # ========== 5. 매도 실행 루프 ==========
    
    max_attempts = sell_time
    attempts = 0
    
    while attempts < max_attempts:
        
        # 🔔 가격 및 수익률 재확인
        cur_price = pyupbit.get_current_price(ticker)
        profit_rate = (cur_price - avg_buy_price) / avg_buy_price * 100 if avg_buy_price > 0 else 0
        
        # 손절 재확인 (루프 내에서 항시 체크)
        if profit_rate < cut_rate:
            sell_order = upbit.sell_market_order(ticker, buyed_amount)
            cut_message = f"❌ **[손절]**: [{ticker}] 수익률: {profit_rate:.2f}% / 현재가: {cur_price:,.1f}\n"
            cut_message += f"사유: 잔여 시간 내 최종 손절"
            print(cut_message)
            send_discord_message(cut_message)
            return sell_order

        print(f"[{ticker}] / [시도 {attempts + 1}/{max_attempts}] / 수익률: {profit_rate:.2f}% / 신호 강도: {sell_strength}/{required_score}")

        # 매도 조건 충족 시
        if profit_rate >= max_rate or should_sell_technical: 
            sell_order = upbit.sell_market_order(ticker, buyed_amount)
            
            sell_type = "목표가달성" if profit_rate >= max_rate else "기술적매도"
            sellmsg = f"✅ **[{sell_type}]**: [{ticker}] / 수익률: {profit_rate:.2f}% / 현재가: {cur_price:,.1f}\n"
            sellmsg += f"신호: {signal_text}"
            
            print(sellmsg)
            send_discord_message(sellmsg)
            return sell_order
        
        time.sleep(second)
        attempts += 1
        
    # 루프 종료 후, 최소 수익률 이상이라면 기술적 신호가 있었든 없었든 최종 매도하여 수익을 확보합니다.
    if profit_rate >= min_rate:
        sell_order = upbit.sell_market_order(ticker, buyed_amount)
        final_sell_msg = f"⚠️ **[감시종료후수익확보]**: [{ticker}] / 수익률: {profit_rate:.2f}% / 현재가: {cur_price:,.1f}\n"
        final_sell_msg += f"사유: 매도 대기 시간 종료 후 수익 최소 확보"
        print(final_sell_msg)
        send_discord_message(final_sell_msg)
        return sell_order

    return None

# NOTE: upbit, get_balance, send_discord_message 등은 외부(전역)에서 정의되었다고 가정합니다.

# 누적 자산 기록용 변수 (전역 변수 또는 DB 사용)
last_total_krw = 0.0

def calculate_rsi(closes, period=14):
    """TA-Lib 없이 numpy로 RSI 계산"""
    diff = np.diff(closes)
    gains = np.where(diff > 0, diff, 0)
    losses = np.where(diff < 0, -diff, 0)
    
    avg_gain = np.mean(gains[:period])
    avg_loss = np.mean(losses[:period])
    
    for i in range(period, len(closes)):
        avg_gain = (avg_gain * (period - 1) + gains[i-1]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i-1]) / period
    
    rs = avg_gain / (avg_loss + 1e-8)
    rsi = 100 - (100 / (1 + rs))
    return rsi

def send_profit_report():
    """
    [10만원 → 10억] 목표를 위한 '성장 마인드셋' 수익 보고서 발송 로직
    """
    global last_total_krw
    
    while True:
        try:
            now = datetime.now()
            next_hour = (now + timedelta(hours=1)).replace(minute=0, second=0, microsecond=0)
            time_until_next_hour = (next_hour - now).total_seconds()
            
            # 다음 정시까지 대기
            if time_until_next_hour > 10: # 불필요한 루프 방지
                 time.sleep(time_until_next_hour)
            now = datetime.now() # 재확인
            
            report_message = "📈 **[정시 수익률 보고서]** 📈\n\n"
            balances = upbit.get_balances()
            total_krw = 0
            
            # 보유 자산 목록 및 총 KRW 계산
            holding_assets = []
            if isinstance(balances, list):
                for b in balances:
                    if not isinstance(b, dict) or 'currency' not in b: continue
                    currency = b['currency']
                    balance_amount = float(b['balance'])
                    
                    if currency == "KRW":
                        total_krw += balance_amount
                        continue
                    
                    # KRW-XXXX 티커로 현재가와 매수평단가 조회
                    ticker = f"KRW-{currency}"
                    avg_buy_price = float(b.get('avg_buy_price', 0))
                    cur_price = pyupbit.get_current_price(ticker)
                    
                    if cur_price is None:
                        continue
                    
                    profit_rate = (cur_price - avg_buy_price) / avg_buy_price * 100 if avg_buy_price > 0 else 0
                    total_krw += balance_amount * cur_price
                    
                    # 5분봉 데이터로 RSI 계산
                    df_5m = pyupbit.get_ohlcv(ticker, interval="minute5", count=20)
                    time.sleep(0.1) # API 요청 딜레이
                    current_rsi = "데이터 부족"
                    if df_5m is not None and len(df_5m) >= 14:
                        current_rsi = f"{calculate_rsi(df_5m['close'].values):.2f}"
                    
                    holding_assets.append({
                        "ticker": currency,
                        "profit_rate": profit_rate,
                        "cur_price": cur_price,
                        "avg_buy_price": avg_buy_price,
                        "rsi": current_rsi
                    })
            
            # 총 계좌 가치 보고
            report_message += f"💰 **총 계좌 가치: {total_krw:,.0f} KRW**\n"
            if last_total_krw > 0:
                krw_change = total_krw - last_total_krw
                report_message += f" (이전 대비: {krw_change:,.0f} KRW {'📈 상승' if krw_change > 0 else '📉 하락' if krw_change < 0 else '↔️ 동일'})\n"
            last_total_krw = total_krw
            
            # 심리적 이정표 달성 알림
            milestones = [1_000_000, 10_000_000, 50_000_000, 100_000_000, 1_000_000_000]
            for m in milestones:
                if m > total_krw - 10000 and m < total_krw + 10000: # 근사치로 감지
                    report_message += f"\n🎉 **대박! {m:,.0f} KRW 돌파!** 이 순간을 기억하세요! 🎉\n"

            report_message += "\n📋 **보유 코인 상세 정보**\n"
            if holding_assets:
                for asset in holding_assets:
                    report_message += f"[{asset['ticker']}] 수익률: {asset['profit_rate']:.2f}% / 현재가: {asset['cur_price']:,.2f}\n"
                    report_message += f"평단가: {asset['avg_buy_price']:.2f} / RSI: {asset['rsi']}\n"
            else:
                report_message += "현재 보유 중인 코인이 없습니다."
                
            send_discord_message(report_message)

        except (KeyError, ValueError, IndexError) as e:
            error_message = f"❌ **수익률 보고 중 오류 발생!**\n내용: {e}"
            print(error_message)
            send_discord_message(error_message)
        
        # 정시에 다시 실행
        time.sleep(60) # 1분마다 재확인
            
trade_start = datetime.now().strftime('%m/%d %H시%M분%S초')  # 시작시간 기록
trade_msg = f'{trade_start} trading start \n'
trade_msg += f'매도: {min_rate}% ~ {max_rate}% / 시도: {sell_time}회 / RsiBuy: {rsi_buy_s} ~ {rsi_buy_e} / RsiSell: {rsi_sell_s} ~ {rsi_sell_e} / 손절: {cut_rate}% \n'

print(trade_msg)
send_discord_message(trade_msg)

# NOTE: pyupbit, upbit, get_balance, send_discord_message, trade_sell, trade_buy, get_best_ticker
#       등은 외부(전역)에서 정의되었다고 가정합니다.

# 이 코드는 이전의 스레드 코드를 대체합니다.
# 하나의 메인 루프에서 매도와 매수 로직을 순차적으로 실행합니다.

def selling_logic():
    """
    [개선된 매도 로직]
    보유 코인의 매도 신호를 즉시 확인하고 처리합니다.
    (이 함수는 더 이상 자체 루프를 돌지 않습니다. main 루프에서 호출됩니다.)
    """
    
    # 예외 처리: get_balances()가 실패할 경우 안전하게 처리
    try:
        balances = upbit.get_balances()
    except Exception as e:
        print(f"selling_logic / 잔고 조회 에러: {e}")
        send_discord_message(f"selling_logic / 잔고 조회 에러: {e}")
        return False # 보유 코인 없음으로 간주
    
    has_holdings = False
    if isinstance(balances, list):
        for b in balances:
            # 매도 로직에 불필요한 코인 제외
            if b.get('currency') in ["KRW", "QI", "ONX", "ETHF", "ETHW", "PURSE"]:
                continue

            ticker = f"KRW-{b.get('currency')}"
            
            # trade_sell 함수가 매도 로직을 처리 (내부에 별도의 sleep 없음)
            trade_sell(ticker)
            has_holdings = True # 보유 코인이 하나라도 있으면 True
            
    return has_holdings

def buying_logic():
    """
    [개선된 매수 로직 - 메인 루프 역할]
    메인 루프에서 매도 로직을 우선 실행한 후,
    잔고와 시장 상황에 따라 매수 기회를 탐색하고 실행합니다.
    """
    while True:
        try:
            # ========== 1. 매도 로직 우선 실행 (가장 중요한 부분!) ==========
            # 보유 코인이 있는지 확인
            has_holdings = selling_logic()
            
            # 보유 코인이 있으면 짧게 대기하여 다음 매도 신호에 빠르게 반응
            if has_holdings:
                print("보유 코인 존재: 매도 신호 재탐색을 위해 10초 대기...")
                time.sleep(10)
                continue
                
            # ========== 2. 매수 로직 (보유 코인이 없을 때만 실행) ==========
            stopbuy_time = datetime.now()
            restricted_start = stopbuy_time.replace(hour=8, minute=50, second=0, microsecond=0)
            restricted_end = stopbuy_time.replace(hour=9, minute=10, second=0, microsecond=0)
            
            # 매수 제한 시간 체크
            if restricted_start <= stopbuy_time <= restricted_end:
                print("매수 제한 시간 (08:50 ~ 09:10). 대기 중...")
                time.sleep(60) 
                continue
            
            krw_balance = get_balance("KRW")
            
            if krw_balance > min_krw:
                best_ticker = get_best_ticker()
                
                if best_ticker:
                    buy_time = datetime.now().strftime('%m/%d %H시%M분%S초')
                    send_discord_message(f"[{buy_time}] 선정코인: [{best_ticker}]")
                    result = trade_buy(best_ticker)
                    
                    if result:
                        print(f"매수 성공. 다음 매수 기회 탐색까지 60초 대기...")
                        time.sleep(60)
                    else:
                        print(f"매수 실패. 다음 기회 탐색까지 30초 대기...")
                        time.sleep(30)
                else:
                    print("매수할 코인 없음. 다음 기회 탐색까지 30초 대기...")
                    time.sleep(30)
            else:
                print("매수 가능 KRW 부족. 180초 대기...")
                time.sleep(180)

        except Exception as e:
            print(f"buying_logic / 메인 루프 에러 발생: {e}")
            send_discord_message(f"buying_logic / 메인 루프 에러 발생: {e}")
            time.sleep(5)

# --- 메인 실행 루프 ---
# 이전의 threading 코드는 이 함수 호출로 대체됩니다.
# 두 로직이 하나의 흐름에서 안전하고 효율적으로 실행됩니다.
buying_logic()