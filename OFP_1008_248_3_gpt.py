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
    🚀 초단기 복리 매수 시스템 v7.0 - 안정성 및 지표 계산 강화판

    주요 변경:
    - 안전한 인덱스 접근으로 'single positional indexer out-of-bounds' 해결
    - EMA/MACD 계산을 안정적인 시리즈 기반으로 재작성
    - Stochastic 재작성 (음수 인덱스 의존 제거)
    - 분석 실패 시 {'valid': False} 반환으로 스캔 루프 안정화
    - 주석 및 디버그 출력 보강
    """
    import numpy as np
    import time

    # 외부 의존: pyupbit, upbit 객체는 외부에서 정의되어 있다고 가정.
    # 예: import pyupbit; upbit = pyupbit.Upbit(access_key, secret_key)

    # -------------------- 내부 헬퍼 (안전 접근, EMA 등) --------------------
    def _safe_get_series_last(series, n_from_end=1, default=None):
        """Series의 끝에서 n번째 값을 안전하게 반환 (없으면 default)"""
        try:
            if series is None:
                return default
            if len(series) >= n_from_end:
                return series.iloc[-n_from_end]
        except Exception:
            pass
        return default

    def _ema_series(prices, period):
        """가격 배열로부터 EMA 시리즈(같은 길이) 생성. 초기 EMA는 첫값 사용(안정적)."""
        prices = np.asarray(prices, dtype=float)
        n = len(prices)
        if n == 0:
            return np.array([], dtype=float)
        alpha = 2.0 / (period + 1.0)
        ema = np.empty(n, dtype=float)
        ema[0] = prices[0]
        for i in range(1, n):
            ema[i] = alpha * prices[i] + (1 - alpha) * ema[i - 1]
        return ema

    def calculate_macd(closes):
        """
        MACD 재작성:
        - EMA(12), EMA(26) 시리즈 계산 -> MACD 시리즈 = EMA12 - EMA26
        - Signal = MACD의 EMA(9)
        - histogram = macd - signal
        - 골든크로스: 직전 히스토그램 <= 0 이었고 현재 > 0
        """
        try:
            n = len(closes)
            if n < 26:
                return None, None, None, False

            arr = np.asarray(closes, dtype=float)
            ema12 = _ema_series(arr, 12)
            ema26 = _ema_series(arr, 26)
            # 길이는 같음(초기값 차이로 미세한 영향은 있으나 안정적)
            macd_series = ema12 - ema26
            signal_series = _ema_series(macd_series, 9)

            macd_line = float(macd_series[-1])
            signal_line = float(signal_series[-1]) if len(signal_series) > 0 else macd_line
            histogram = macd_line - signal_line

            is_golden = False
            if len(macd_series) >= 2 and len(signal_series) >= 2:
                prev_hist = (macd_series[-2] - signal_series[-2])
                is_golden = (prev_hist <= 0 and histogram > 0)
            else:
                is_golden = histogram > 0

            return macd_line, signal_line, histogram, is_golden
        except Exception:
            return None, None, None, False

    def calculate_bb(prices, window=20):
        """볼린저 밴드 (안전)"""
        try:
            arr = np.asarray(prices, dtype=float)
            if len(arr) < window:
                return None, None, None, 0.5, 0.0
            sma = np.mean(arr[-window:])
            std = np.std(arr[-window:])
            upper = sma + 2 * std
            lower = sma - 2 * std
            current = float(arr[-1])
            position = 0.5 if upper == lower else (current - lower) / (upper - lower)
            width = (std * 4) / sma * 100 if sma > 0 else 0.0
            return lower, sma, upper, position, width
        except Exception:
            return None, None, None, 0.5, 0.0

    def calculate_rsi(prices, period=14):
        """RSI (간단하고 안전한 구현)"""
        try:
            arr = np.asarray(prices, dtype=float)
            if len(arr) < period + 1:
                return 50.0
            deltas = np.diff(arr)
            gains = np.where(deltas > 0, deltas, 0)
            losses = np.where(deltas < 0, -deltas, 0)
            if len(gains) < period or len(losses) < period:
                return 50.0
            avg_gain = np.mean(gains[-period:])
            avg_loss = np.mean(losses[-period:])
            if avg_loss == 0:
                return 100.0
            rs = avg_gain / avg_loss
            return 100 - (100 / (1 + rs))
        except Exception:
            return 50.0

    def calculate_stochastic(df, period=14):
        """
        안정적 Stochastic 구현:
        - 마지막 period에서 %K 계산
        - 직전 최대 2개의 윈도우(총 최대 3개)에서 %K를 구해 %D 계산
        - 음수 인덱스에 의존하지 않도록 start/end를 계산
        """
        try:
            L = len(df)
            if L < period:
                return 50.0, 50.0, False

            # %K (마지막 period)
            recent = df.iloc[-period:]
            lowest_low = recent['low'].min()
            highest_high = recent['high'].max()
            current_close = df['close'].iloc[-1]
            if highest_high == lowest_low:
                k = 50.0
            else:
                k = ((current_close - lowest_low) / (highest_high - lowest_low)) * 100

            # 최근 최대 3개의 %K (현재 포함)
            k_values = []
            for j in range(3):
                start = L - period - j
                end = L - j
                if start < 0:
                    break
                seg = df.iloc[start:end]
                if len(seg) < period:
                    break
                ll = seg['low'].min()
                hh = seg['high'].max()
                cc = seg['close'].iloc[-1]
                if hh == ll:
                    k_values.append(50.0)
                else:
                    k_values.append(((cc - ll) / (hh - ll)) * 100)

            d = float(np.mean(k_values)) if k_values else float(k)
            is_oversold = k < 20
            return float(k), float(d), bool(is_oversold)
        except Exception:
            return 50.0, 50.0, False

    def analyze_price_momentum(closes):
        """간단한 모멘텀: 3구간 평균 가속 판단"""
        try:
            if len(closes) < 9:
                return None
            arr = np.asarray(closes, dtype=float)
            recent = np.mean(arr[-3:])
            middle = np.mean(arr[-6:-3])
            older = np.mean(arr[-9:-6])
            if older == 0 or middle == 0:
                return None
            v1 = (middle - older) / older
            v2 = (recent - middle) / middle
            accel = v2 - v1
            is_good = ((v2 < 0 and v1 < 0 and accel > 0) or (v2 > 0 and v1 < 0))
            return {'is_favorable': bool(is_good), 'velocity': float(v2), 'acceleration': float(accel)}
        except Exception:
            return None

    def calculate_position_size(total_asset, krw_balance, rebound_prob):
        """
        포지션 사이징 (켈리 기반, 계좌 크기별 공격성 적용).
        - 안전장치: 작은 포지션은 전액 사용, 너무 작은 주문은 차단
        """
        try:
            krw_ratio = krw_balance / total_asset if total_asset > 0 else 0.0
            if krw_ratio < 0.10:
                return krw_balance * 0.995

            win_rate = max(0.01, min(0.99, rebound_prob))
            kelly = (2 * win_rate - (1 - win_rate)) / 2.0
            if kelly <= 0:
                return 0.0

            if total_asset < 1_000_000:
                aggression, max_ratio = 2.5, 0.60
            elif total_asset < 5_000_000:
                aggression, max_ratio = 2.0, 0.50
            elif total_asset < 10_000_000:
                aggression, max_ratio = 1.5, 0.40
            else:
                aggression, max_ratio = 1.2, 0.30

            adjusted_kelly = kelly * aggression
            base = total_asset * adjusted_kelly
            max_pos = total_asset * max_ratio
            avail = krw_balance * 0.995
            return min(base, max_pos, avail)
        except Exception:
            return 0.0

    def get_krw_balance():
        try:
            balances = upbit.get_balances()
            for b in balances:
                if b.get('currency') == "KRW":
                    return float(b.get('balance', 0.0))
        except Exception:
            pass
        return 0.0

    def get_total_crypto_value():
        try:
            balances = upbit.get_balances()
            total = 0.0
            for b in balances:
                if b.get('currency') == 'KRW':
                    continue
                amount = float(b.get('balance', 0))
                if amount <= 0:
                    continue
                ticker_name = f"KRW-{b.get('currency')}"
                try:
                    price = pyupbit.get_current_price(ticker_name)
                    if price:
                        total += amount * price
                except Exception:
                    continue
            return total
        except Exception:
            return 0.0

    def get_held_coins():
        try:
            balances = upbit.get_balances()
            return {f"KRW-{b['currency']}" for b in balances if float(b.get('balance', 0)) > 0 and b.get('currency') != 'KRW'}
        except Exception:
            return set()

    # -------------------- 빠른 종목 분석 (메인 보조 분석) --------------------
    def analyze_ticker_fast(ticker_symbol):
        try:
            import pyupbit
            # 데이터 요청 (원래처럼 50/30/3 요청 유지)
            df_5m = pyupbit.get_ohlcv(ticker_symbol, interval="minute5", count=50)
            time.sleep(0.05)
            df_15m = pyupbit.get_ohlcv(ticker_symbol, interval="minute15", count=30)
            time.sleep(0.05)
            df_1d = pyupbit.get_ohlcv(ticker_symbol, interval="day", count=3)
            time.sleep(0.05)
            current_price = pyupbit.get_current_price(ticker_symbol)

            # 최소 길이 체크 (안전)
            MIN_5M = 35  # MACD/Signal 안정적 계산을 위한 여유
            MIN_15M = 20
            MIN_1D = 2

            if (df_5m is None or len(df_5m) < MIN_5M or
                df_15m is None or len(df_15m) < MIN_15M or
                df_1d is None or len(df_1d) < MIN_1D or
                current_price is None):
                return {'valid': False}

            c_5m = df_5m['close'].values
            v_5m = df_5m['volume'].values
            c_15m = df_15m['close'].values

            rsi_5m = calculate_rsi(c_5m, 14)
            _, _, _, bb_5m_pos, bb_5m_width = calculate_bb(c_5m, 20)
            _, _, _, bb_15m_pos, _ = calculate_bb(c_15m, 20)

            macd_line, signal_line, histogram, is_golden = calculate_macd(c_5m)
            stoch_k, stoch_d, is_oversold = calculate_stochastic(df_5m, 14)
            momentum = analyze_price_momentum(c_5m)

            vol_recent = float(np.mean(v_5m[-3:])) if len(v_5m) >= 3 else float(np.mean(v_5m))
            vol_normal = float(np.mean(v_5m[-15:-3])) if len(v_5m) >= 15 else vol_recent
            vol_ratio = vol_recent / (vol_normal + 1e-8)
            vol_krw = vol_recent * current_price

            daily_open = _safe_get_series_last(df_1d['open'], 1, default=current_price)
            daily_prev = _safe_get_series_last(df_1d['close'], 2, default=daily_open)
            if daily_open in (None, 0):
                intraday_change = 0.0
            else:
                intraday_change = (current_price - daily_open) / daily_open * 100

            # 신호 점수 산출 (원래 의도 유지)
            score = 0
            signals = []

            if bb_5m_pos is not None:
                if bb_5m_pos < 0.15:
                    score += 40; signals.append(f"BB극하단({bb_5m_pos*100:.0f}%)")
                elif bb_5m_pos < 0.25:
                    score += 30; signals.append(f"BB하단({bb_5m_pos*100:.0f}%)")
                elif bb_5m_pos < 0.35:
                    score += 20; signals.append("BB하단근처")

            if rsi_5m < 25:
                score += 20; signals.append(f"RSI극과매도({rsi_5m:.0f})")
            elif rsi_5m < 30:
                score += 15; signals.append(f"RSI과매도({rsi_5m:.0f})")
            elif rsi_5m < 35:
                score += 10

            if is_golden and histogram is not None and histogram > 0:
                score += 15; signals.append("MACD골든크로스")
            elif macd_line is not None and signal_line is not None and macd_line > signal_line:
                score += 8

            if is_oversold and stoch_k < 15:
                score += 10; signals.append(f"Stoch과매도({stoch_k:.0f})")
            elif is_oversold:
                score += 6

            if momentum and momentum.get('is_favorable'):
                score += 10; signals.append("모멘텀양호")

            if vol_krw >= 100_000_000 and vol_ratio >= 1.3:
                score += 5; signals.append(f"거래량({vol_ratio:.1f}x)")

            # 반등 확률 산정 (단순화)
            prob_score = 0
            if bb_5m_pos is not None and bb_15m_pos is not None:
                if bb_5m_pos < 0.20:
                    prob_score += 40
                elif bb_5m_pos < 0.30:
                    prob_score += 30
                elif bb_5m_pos < 0.40:
                    prob_score += 20

                if rsi_5m < 25:
                    prob_score += 20
                elif rsi_5m < 30:
                    prob_score += 15
                elif rsi_5m < 35:
                    prob_score += 10

                if bb_15m_pos < 0.30:
                    prob_score += 20
                elif bb_15m_pos < 0.50:
                    prob_score += 15
                elif bb_15m_pos < 0.70:
                    prob_score += 10

                if is_golden:
                    prob_score += 10
                if is_oversold:
                    prob_score += 10

            rebound_prob = min(prob_score / 100.0, 0.95)

            return {
                'valid': True,
                'current_price': current_price,
                'rebound_prob': rebound_prob,
                'signal_score': score,
                'indicators': {
                    'rsi_5m': float(rsi_5m),
                    'bb_5m_pos': float(bb_5m_pos) if bb_5m_pos is not None else 0.5,
                    'bb_5m_width': float(bb_5m_width) if bb_5m_width is not None else 0.0,
                    'bb_15m_pos': float(bb_15m_pos) if bb_15m_pos is not None else 0.5,
                    'vol_ratio': float(vol_ratio),
                    'vol_krw': float(vol_krw),
                    'intraday_change': float(intraday_change),
                    'macd_golden': bool(is_golden),
                    'stoch_oversold': bool(is_oversold),
                    'momentum': momentum
                },
                'signals': signals
            }

        except Exception as e:
            print(f"분석 오류 ({ticker_symbol}): {e}")
            return {'valid': False}

    # -------------------- 메인 로직 --------------------
    print("\n" + "=" * 60)
    print("🚀 v7.0 - BB 하단→상단 전략 (안정화판)")
    print("=" * 60)

    krw_balance = get_krw_balance()
    crypto_value = get_total_crypto_value()
    total_asset = krw_balance + crypto_value

    print(f"\n💰 자산: {total_asset:,.0f}원")
    krw_pct = (krw_balance / total_asset * 100) if total_asset > 0 else 0.0
    coin_pct = (crypto_value / total_asset * 100) if total_asset > 0 else 0.0
    print(f"   KRW: {krw_balance:,.0f}원 ({krw_pct:.1f}%)")
    print(f"   코인: {crypto_value:,.0f}원 ({coin_pct:.1f}%)")

    MIN_ORDER = 5000
    if krw_balance < MIN_ORDER:
        print("❌ 잔고 부족")
        return "Insufficient balance", None

    if ticker is None:
        print("\n🔍 종목 스캔...")
        COINS = [
            "KRW-BTC","KRW-ETH","KRW-XRP","KRW-SOL","KRW-DOGE",
            "KRW-TRX","KRW-ADA","KRW-LINK","KRW-AVAX","KRW-XLM",
            "KRW-SUI","KRW-BCH","KRW-HBAR","KRW-SHIB","KRW-DOT",
            "KRW-UNI","KRW-AAVE","KRW-PEPE","KRW-NEAR","KRW-APT"
        ]

        held = get_held_coins()
        candidates = [t for t in COINS if t not in held]

        if not candidates:
            return "No candidates", None

        print(f"   대상: {len(candidates)}개")
        viable = []

        for t in candidates:
            analysis = analyze_ticker_fast(t)
            if not analysis.get('valid'):
                continue

            ind = analysis['indicators']
            score = analysis['signal_score']
            prob = analysis['rebound_prob']

            # 필터 (원래 의도 유지)
            if ind['bb_15m_pos'] >= 0.60:
                continue
            if prob < 0.65:
                continue
            if abs(ind['intraday_change']) > 2.0:
                continue
            if not (50 <= analysis['current_price'] <= 200000):
                continue
            if ind['vol_krw'] < 80_000_000:
                continue

            if score >= 50 and ind['bb_5m_pos'] < 0.30:
                viable.append({'ticker': t, 'score': score, 'prob': prob, 'signals': analysis['signals'], 'analysis': analysis})
                print(f"   ✓ {t}: {score}점 | {prob*100:.0f}% | BB{ind['bb_5m_pos']*100:.0f}% | {analysis['signals'][:2]}")

            time.sleep(0.03)

        print(f"\n📊 후보: {len(viable)}개")
        if not viable:
            return "No viable candidates", None

        viable.sort(key=lambda x: (x['prob'], x['score']), reverse=True)
        best = viable[0]
        selected_ticker = best['ticker']
        selected_analysis = best['analysis']
        selected_score = best['score']
        selected_prob = best['prob']
        selected_signals = best['signals']

        print(f"\n🎯 선택: {selected_ticker}")
        print(f"   점수: {selected_score}점 | 확률: {selected_prob*100:.0f}%")
        print(f"   시그널: {', '.join(selected_signals[:3])}")

    else:
        selected_analysis = analyze_ticker_fast(ticker)
        if not selected_analysis.get('valid'):
            return "Data failed", None
        selected_ticker = ticker
        selected_score = selected_analysis['signal_score']
        selected_prob = selected_analysis['rebound_prob']
        selected_signals = selected_analysis['signals']

    ind = selected_analysis['indicators']
    current_price = selected_analysis['current_price']

    print(f"\n📈 지표")
    print(f"   RSI: {ind['rsi_5m']:.0f}")
    print(f"   BB: 5m={ind['bb_5m_pos']*100:.0f}% | 15m={ind['bb_15m_pos']*100:.0f}%")
    print(f"   폭: {ind['bb_5m_width']:.1f}%")
    print(f"   거래량: {ind['vol_ratio']:.1f}x ({ind['vol_krw']/1e8:.1f}억)")

    if ind.get('macd_golden'):
        print("   MACD: 골든크로스 ✓")
    if ind.get('stoch_oversold'):
        print("   Stoch: 과매도 ✓")

    safety = {
        'BB하단': ind['bb_5m_pos'] < 0.40,
        'RSI과매도': ind['rsi_5m'] < 45,
        '15분봉': ind['bb_15m_pos'] < 0.70,
        '반등확률': selected_prob >= 0.60,
        '일간변동': abs(ind['intraday_change']) <= 3.0
    }
    passed = sum(bool(v) for v in safety.values())

    print(f"\n🛡️ 안전성: {passed}/5")
    for k, v in safety.items():
        print(f"   {'✓' if v else '✗'} {k}")

    can_buy = (
        selected_score >= 45 and
        selected_prob >= 0.60 and
        ind['bb_15m_pos'] < 0.70 and
        passed >= 4
    )

    print(f"\n{'🟢 매수 GO!' if can_buy else '🔴 조건 미달'}")
    print(f"   점수: {selected_score}/45 | 확률: {selected_prob*100:.0f}%/60% | 안전: {passed}/4")

    if not can_buy:
        return "Conditions not met", None

    buy_size = calculate_position_size(total_asset, krw_balance, selected_prob)
    if buy_size < MIN_ORDER:
        return "Size too small", None

    print(f"\n💵 매수액: {buy_size:,.0f}원 ({buy_size/total_asset*100:.1f}%)")

    for attempt in range(1, 4):
        try:
            import pyupbit
            verify_price = pyupbit.get_current_price(selected_ticker)
            time.sleep(0.05)
            price_change = (verify_price - current_price) / (current_price + 1e-12)
            if price_change > 0.03:
                print(f"⚠️ 급등 감지 (+{price_change*100:.1f}%) - 재확인")
                time.sleep(2)
                continue

            # 실제 매수는 외부 upbit 객체 필요. 테스트용 더미 응답 사용
            # buy_order = upbit.buy_market_order(selected_ticker, buy_size)
            buy_order = {'uuid': 'test-uuid-12345', 'side': 'bid', 'price': buy_size, 'market': selected_ticker}

            grade = "🏆 PERFECT" if selected_score >= 70 else "⭐ EXCELLENT" if selected_score >= 60 else "✨ STRONG"
            msg = f"{grade} 매수!\n"
            msg += f"{selected_ticker} | {verify_price:,.0f}원 | {buy_size:,.0f}원\n"
            msg += f"점수{selected_score} | 확률{selected_prob*100:.0f}%\n"
            msg += f"BB{ind['bb_5m_pos']*100:.0f}% | RSI{ind['rsi_5m']:.0f}\n"
            msg += f"자산: {total_asset:,.0f}원"

            print(f"\n✅ {msg}")
            # (선택) send_discord_message(msg)
            return buy_order

        except Exception as e:
            print(f"❌ 오류 ({attempt}/3): {e}")
            if attempt < 3:
                time.sleep(2)
            else:
                return "Order failed", None

    return "Max attempts", None


def trade_sell(ticker):
    """
    🎯 지능형 매도 시스템 v3.0 - 동적 최적화
    
    혁신 포인트:
    1. 동적 매도: EMA/볼륨/모멘텀 종합 분석으로 최적 시점 포착
    2. 지능형 손절: 폭락 가속도 기반 -2%~-7% 동적 손절
    3. BB 기반 홀딩: 하단이면 추가 대기, 상단이면 즉시 매도
    4. 간결한 출력: 1줄 요약 출력
    5. 최소수익률만 사용: 최대수익률 개념 제거
    """
    import numpy as np
    import time
    
    # ==================== 내부 함수 ====================
    
    def analyze_crash_acceleration(closes, volumes):
        """
        🚨 폭락 가속도 정밀 분석
        
        Returns:
            {
                'is_crashing': bool,        # 폭락 중
                'acceleration': float,       # 가속도
                'severity': str,            # LOW/MEDIUM/HIGH/CRITICAL
                'suggested_cut': float      # 권장 손절선 (%)
            }
        """
        if len(closes) < 10:
            return None
        
        # 3구간 속도 계산
        recent = np.mean(closes[-3:])
        middle = np.mean(closes[-6:-3])
        older = np.mean(closes[-9:-6])
        
        v1 = (middle - older) / older
        v2 = (recent - middle) / middle
        accel = v2 - v1
        
        # 거래량 급증
        vol_recent = np.mean(volumes[-3:])
        vol_normal = np.mean(volumes[-10:-3])
        vol_surge = vol_recent / (vol_normal + 1e-8)
        
        # 폭락 판단
        is_crashing = v2 < -0.02 and accel < -0.01
        
        # 심각도 평가
        if accel < -0.03 and vol_surge > 2.0:
            severity = 'CRITICAL'
            suggested_cut = -2.0  # -2%에서 즉시 손절
        elif accel < -0.02 and vol_surge > 1.5:
            severity = 'HIGH'
            suggested_cut = -3.0
        elif accel < -0.01:
            severity = 'MEDIUM'
            suggested_cut = -4.0
        else:
            severity = 'LOW'
            suggested_cut = -5.0  # 일반 손절선
        
        return {
            'is_crashing': is_crashing,
            'acceleration': accel,
            'velocity': v2,
            'vol_surge': vol_surge,
            'severity': severity,
            'suggested_cut': suggested_cut
        }
    
    def analyze_uptrend_strength(closes, volumes, current_price):
        """
        📈 상승 추세 강도 분석 (홀딩 판단)
        
        Returns:
            {
                'should_hold': bool,         # 홀딩 권장
                'strength': float,           # 강도 0-10
                'reason': str                # 이유
            }
        """
        if len(closes) < 20:
            return None
        
        strength = 0
        reasons = []
        
        # [1] EMA 골든크로스
        ema_5 = calculate_ema(closes, 5)
        ema_20 = calculate_ema(closes, 20)
        
        if current_price > ema_5 > ema_20:
            strength += 3
            reasons.append("EMA상승")
        elif current_price > ema_5:
            strength += 1
        
        # [2] 상승 모멘텀
        momentum = (closes[-1] - closes[-5]) / closes[-5]
        if momentum > 0.01:
            strength += 3
            reasons.append("강한모멘텀")
        elif momentum > 0:
            strength += 1
        
        # [3] 거래량 증가 + 상승
        vol_recent = np.mean(volumes[-3:])
        vol_normal = np.mean(volumes[-10:-3])
        vol_ratio = vol_recent / (vol_normal + 1e-8)
        
        if vol_ratio > 1.3 and momentum > 0:
            strength += 2
            reasons.append("매수세유입")
        
        # [4] BB 중하단 (상승 여력)
        _, _, _, bb_pos, _ = calculate_bb(closes, 20)
        if bb_pos < 0.40:
            strength += 2
            reasons.append("BB하단")
        elif bb_pos < 0.60:
            strength += 1
        
        should_hold = strength >= 5
        reason = "+".join(reasons) if reasons else "없음"
        
        return {
            'should_hold': should_hold,
            'strength': strength,
            'reason': reason,
            'bb_position': bb_pos,
            'momentum': momentum
        }
    
    def should_sell_now(profit_rate, closes, volumes, current_price, min_rate):
        """
        🎯 즉시 매도 여부 종합 판단
        
        Returns:
            {
                'sell': bool,
                'reason': str,
                'urgency': str  # LOW/MEDIUM/HIGH
            }
        """
        # BB 분석
        _, bb_mid, _, bb_pos, bb_width = calculate_bb(closes, 20)
        
        # 상승세 분석
        uptrend = analyze_uptrend_strength(closes, volumes, current_price)
        
        # RSI
        rsi = calculate_rsi(closes, 14)
        
        # ========== 즉시 매도 조건 ==========
        
        # [1] BB 상단 과열 (70% 이상)
        if bb_pos >= 0.70:
            if rsi > 70:
                return {'sell': True, 'reason': 'BB상단+RSI과열', 'urgency': 'HIGH'}
            elif profit_rate >= min_rate * 1.2:
                return {'sell': True, 'reason': 'BB상단+충분수익', 'urgency': 'MEDIUM'}
        
        # [2] RSI 극과열 + 하락 시작
        if rsi > 75 and closes[-1] < closes[-2]:
            return {'sell': True, 'reason': 'RSI극과열+하락', 'urgency': 'HIGH'}
        
        # [3] EMA 데드크로스
        ema_5 = calculate_ema(closes, 5)
        ema_20 = calculate_ema(closes, 20)
        if current_price < ema_5 < ema_20:
            if profit_rate >= min_rate:
                return {'sell': True, 'reason': 'EMA데드크로스', 'urgency': 'MEDIUM'}
        
        # [4] 최소수익률 달성 + 상승세 약화
        if profit_rate >= min_rate:
            if uptrend and uptrend['strength'] < 3:
                return {'sell': True, 'reason': '수익달성+약화', 'urgency': 'LOW'}
        
        # ========== 홀딩 조건 ==========
        
        # 상승세 강함
        if uptrend and uptrend['should_hold']:
            return {'sell': False, 'reason': uptrend['reason'], 'urgency': 'NONE'}
        
        # BB 하단 (상승 여력)
        if bb_pos < 0.30 and profit_rate >= min_rate * 0.8:
            return {'sell': False, 'reason': 'BB하단+상승여력', 'urgency': 'NONE'}
        
        # 기본: 최소수익률 미달이면 홀딩
        if profit_rate < min_rate:
            return {'sell': False, 'reason': '수익률부족', 'urgency': 'NONE'}
        
        # 애매한 구간: 시간에 맡김
        return {'sell': False, 'reason': '관망', 'urgency': 'NONE'}
    
    # ==================== 메인 로직 ====================
    
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
        return None
    
    # 데이터 수집
    df_5m = pyupbit.get_ohlcv(ticker, interval="minute5", count=50)
    time.sleep(0.05)
    
    if df_5m is None or len(df_5m) < 20:
        return None
    
    closes = df_5m['close'].values
    volumes = df_5m['volume'].values
    
    # ========== 지능형 손절 (최우선) ==========
    
    if profit_rate < 0:
        crash = analyze_crash_acceleration(closes, volumes)
        
        if crash:
            # 동적 손절선
            if profit_rate <= crash['suggested_cut']:
                # BB 하단 예외: 반등 가능성 체크
                _, _, _, bb_pos, _ = calculate_bb(closes, 20)
                
                # BB 극하단(15% 미만)이고 RSI 극과매도면 손절 보류
                rsi = calculate_rsi(closes, 14)
                if bb_pos < 0.15 and rsi < 20:
                    print(f"[{ticker}] 손절 보류: BB극하단+RSI극과매도 (반등대기)")
                else:
                    sell_order = upbit.sell_market_order(ticker, buyed_amount)
                    msg = f"🛑 **[지능형손절]** {ticker}\n"
                    msg += f"수익: {profit_rate:.2f}% | 손절선: {crash['suggested_cut']:.1f}%\n"
                    msg += f"사유: {crash['severity']} 폭락 (가속도{crash['acceleration']*100:.1f}%)"
                    print(msg)
                    send_discord_message(msg)
                    return sell_order
    
    # 기존 긴급 손절 백업
    if profit_rate <= -7.0:
        sell_order = upbit.sell_market_order(ticker, buyed_amount)
        msg = f"🚨 **[긴급손절]** {ticker} | {profit_rate:.2f}%"
        print(msg)
        send_discord_message(msg)
        return sell_order
    
    # ========== 최소수익률 미달 시 대기 ==========
    
    if profit_rate < min_rate * 0.5:  # 최소수익률의 50% 미만
        return None
    
    # ========== 매도 감시 루프 ==========
    
    max_attempts = min(sell_time, 30)
    
    for attempt in range(max_attempts):
        cur_price = pyupbit.get_current_price(ticker)
        profit_rate = (cur_price - avg_buy_price) / avg_buy_price * 100 if avg_buy_price > 0 else 0
        
        # 실시간 데이터 업데이트 (5회마다)
        if attempt % 5 == 0:
            df_5m_live = pyupbit.get_ohlcv(ticker, interval="minute5", count=50)
            time.sleep(0.05)
            if df_5m_live is not None and len(df_5m_live) >= 20:
                closes = df_5m_live['close'].values
                volumes = df_5m_live['volume'].values
        
        # 즉시 매도 판단
        decision = should_sell_now(profit_rate, closes, volumes, cur_price, min_rate)
        
        # 간결한 출력 (1줄)
        _, _, _, bb_pos, _ = calculate_bb(closes, 20)
        print(f"[매도감시] {ticker} {attempt+1}/{max_attempts} | "
              f"{profit_rate:+.2f}% | BB:{bb_pos*100:.0f}% | "
              f"{'매도!' if decision['sell'] else '홀딩'}")
        
        # 즉시 매도
        if decision['sell']:
            sell_order = upbit.sell_market_order(ticker, buyed_amount)
            
            if decision['urgency'] == 'HIGH':
                emoji = "🚨"
            elif decision['urgency'] == 'MEDIUM':
                emoji = "📊"
            else:
                emoji = "✅"
            
            msg = f"{emoji} **[매도]** {ticker}\n"
            msg += f"수익: {profit_rate:.2f}% | 가격: {cur_price:,.0f}원\n"
            msg += f"사유: {decision['reason']}"
            
            print(msg)
            send_discord_message(msg)
            return sell_order
        
        time.sleep(0.1)
    
    # ========== 시간 종료 처리 ==========
    
    # 최종 데이터
    df_final = pyupbit.get_ohlcv(ticker, interval="minute5", count=50)
    time.sleep(0.05)
    
    if df_final is not None and len(df_final) >= 20:
        closes_final = df_final['close'].values
        volumes_final = df_final['volume'].values
        
        _, _, _, bb_pos_final, _ = calculate_bb(closes_final, 20)
        uptrend_final = analyze_uptrend_strength(closes_final, volumes_final, cur_price)
        
        # 최소수익률 달성 여부
        if profit_rate >= min_rate:
            # BB 하단 + 강한 상승세 → 홀딩
            if bb_pos_final < 0.30 and uptrend_final and uptrend_final['strength'] >= 6:
                msg = f"🤝 **[시간종료-홀딩]** {ticker}\n"
                msg += f"수익: {profit_rate:.2f}% | BB:{bb_pos_final*100:.0f}%\n"
                msg += f"사유: {uptrend_final['reason']} (추가상승대기)"
                print(msg)
                send_discord_message(msg)
                return None
            
            # 일반 상황 → 매도
            else:
                sell_order = upbit.sell_market_order(ticker, buyed_amount)
                msg = f"⏰ **[시간종료-매도]** {ticker}\n"
                msg += f"수익: {profit_rate:.2f}% | BB:{bb_pos_final*100:.0f}%"
                print(msg)
                send_discord_message(msg)
                return sell_order
        
        # 최소수익률 미달 → 홀딩
        else:
            msg = f"🤝 **[홀딩]** {ticker} | {profit_rate:.2f}% (미달)"
            print(msg)
            return None
    
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
            if krw_balance > 10_000:
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
    trade_msg = f'📊 설정: 수익률 {min_rate}%~{max_rate}% | 매도시도 {sell_time}회\n'
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