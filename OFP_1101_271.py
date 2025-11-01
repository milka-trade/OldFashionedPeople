"""
🏰 Fortress Hunter v5.0 - 완전 수정판
100만원 → 10억원 자동매매 시스템

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🎯 v5.0 수정 사항:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
1. ✅ 시작 시점 자산 리포트 출력 보장
2. ✅ 보유종목 완전 제외 (스캔 종목 수 정확 표시)
3. ✅ 멀티 타임프레임 통합 분석
4. ✅ 예측 기반 스마트 매도
5. ✅ 정시마다 자동 보고서
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

import time
import pyupbit
import numpy as np
from datetime import datetime, timedelta
from collections import deque, defaultdict
from threading import Lock, Thread
import os
import json
import shutil
import tempfile
import requests
from dotenv import load_dotenv

load_dotenv()

# ═══════════════════════════════════════════════════════════
# 🔧 환경 설정
# ═══════════════════════════════════════════════════════════

DISCORD_WEBHOOK_URL = os.getenv("discord_webhhok")
upbit = pyupbit.Upbit(os.getenv("UPBIT_ACCESS"), os.getenv("UPBIT_SECRET"))

STRATEGIC_COINS = [
    "KRW-BTC", "KRW-ETH", "KRW-XRP", "KRW-SOL",
    "KRW-ADA", "KRW-LINK", "KRW-BCH", "KRW-XLM"
]

API_CALL_DELAY = 0.3
SCAN_INTERVAL = 30  # 30초마다 전체 스캔


# ═══════════════════════════════════════════════════════════
# 📨 디스코드 알림
# ═══════════════════════════════════════════════════════════

def send_discord_message(msg):
    """디스코드 메시지 전송"""
    if not DISCORD_WEBHOOK_URL:
        return False
    
    for attempt in range(2):
        try:
            response = requests.post(
                DISCORD_WEBHOOK_URL,
                data={"content": msg},
                timeout=3
            )
            if response.status_code == 204:
                return True
        except:
            if attempt < 1:
                time.sleep(1)
    return False


# ═══════════════════════════════════════════════════════════
# 💾 안전한 JSON 저장 시스템
# ═══════════════════════════════════════════════════════════

class SafeJSONStorage:
    """안전한 JSON 저장 시스템"""
    
    def __init__(self, filepath='fortress_state_v5.json'):
        self.filepath = filepath
        self.backup_path = filepath + '.backup'
        self.lock = Lock()
    
    def save(self, data):
        """안전한 저장"""
        with self.lock:
            try:
                temp_fd, temp_path = tempfile.mkstemp(
                    suffix='.json',
                    prefix='fortress_',
                    dir=os.path.dirname(self.filepath) or '.'
                )
                
                try:
                    with os.fdopen(temp_fd, 'w', encoding='utf-8') as f:
                        json.dump(data, f, indent=2, ensure_ascii=False)
                        f.flush()
                        os.fsync(f.fileno())
                    
                    with open(temp_path, 'r', encoding='utf-8') as f:
                        verify_data = json.load(f)
                    
                    required_fields = ['initial', 'current_asset', 'total_trades']
                    for field in required_fields:
                        if field not in verify_data:
                            raise ValueError(f"필수 필드 누락: {field}")
                    
                    if os.path.exists(self.filepath):
                        shutil.copy2(self.filepath, self.backup_path)
                    
                    if os.name == 'nt':
                        if os.path.exists(self.filepath):
                            os.remove(self.filepath)
                        shutil.move(temp_path, self.filepath)
                    else:
                        os.replace(temp_path, self.filepath)
                    
                    return True
                    
                except Exception as e:
                    if os.path.exists(temp_path):
                        os.remove(temp_path)
                    raise e
                    
            except Exception as e:
                print(f"❌ JSON 저장 실패: {e}")
                return False
    
    def load(self):
        """안전한 로드"""
        with self.lock:
            if os.path.exists(self.filepath):
                try:
                    with open(self.filepath, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                    if self._validate(data):
                        return data
                except Exception as e:
                    print(f"⚠️ 메인 파일 로드 실패: {e}")
            
            if os.path.exists(self.backup_path):
                try:
                    with open(self.backup_path, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                    if self._validate(data):
                        print("✅ 백업 파일에서 복구")
                        shutil.copy2(self.backup_path, self.filepath)
                        return data
                except:
                    pass
            
            return None
    
    def _validate(self, data):
        """데이터 유효성 검증"""
        if not isinstance(data, dict):
            return False
        required = ['initial', 'current_asset', 'peak_asset', 'total_trades', 'win_trades']
        return all(field in data for field in required)


# ═══════════════════════════════════════════════════════════
# ⏱️ API 호출 관리 + 캐싱
# ═══════════════════════════════════════════════════════════

class APIRateLimiter:
    """API 호출 관리"""
    
    def __init__(self, max_per_second=8, max_per_minute=80):
        self.max_per_second = max_per_second
        self.max_per_minute = max_per_minute
        self.calls = deque()
        self.lock = Lock()
    
    def wait_if_needed(self):
        """필요 시 대기"""
        with self.lock:
            now = time.time()
            
            while self.calls and now - self.calls[0] > 60:
                self.calls.popleft()
            
            recent_calls = [t for t in self.calls if now - t < 1.0]
            if len(recent_calls) >= self.max_per_second:
                wait_time = 1.0 - (now - recent_calls[0]) + 0.1
                if wait_time > 0:
                    time.sleep(wait_time)
                    now = time.time()
            
            if len(self.calls) >= self.max_per_minute:
                wait_time = 60 - (now - self.calls[0]) + 0.5
                if wait_time > 0:
                    time.sleep(wait_time)
                    now = time.time()
            
            self.calls.append(now)
    
    def call_api(self, func, *args, max_retries=2, **kwargs):
        """안전한 API 호출"""
        for attempt in range(max_retries):
            try:
                self.wait_if_needed()
                time.sleep(API_CALL_DELAY)
                result = func(*args, **kwargs)
                return result
            except Exception as e:
                if "not found" in str(e).lower():
                    return None
                if attempt < max_retries - 1:
                    time.sleep(1)
                else:
                    return None
        return None


class DataCache:
    """데이터 캐싱 시스템"""
    
    def __init__(self, ttl=10):
        self.cache = {}
        self.ttl = ttl
        self.lock = Lock()
    
    def get(self, key):
        """캐시 조회"""
        with self.lock:
            if key in self.cache:
                data, timestamp = self.cache[key]
                if time.time() - timestamp < self.ttl:
                    return data
                else:
                    del self.cache[key]
            return None
    
    def set(self, key, data):
        """캐시 저장"""
        with self.lock:
            self.cache[key] = (data, time.time())
    
    def clear_old(self):
        """오래된 캐시 삭제"""
        with self.lock:
            now = time.time()
            to_delete = [k for k, (_, t) in self.cache.items() if now - t >= self.ttl]
            for k in to_delete:
                del self.cache[k]


api_limiter = APIRateLimiter()
data_cache = DataCache(ttl=10)
storage = SafeJSONStorage()


# ═══════════════════════════════════════════════════════════
# 📈 고급 지표 계산
# ═══════════════════════════════════════════════════════════

def calculate_rsi(closes, period=14):
    """RSI 계산"""
    if len(closes) < period + 1:
        return 50.0
    
    deltas = np.diff(closes)
    gains = np.where(deltas > 0, deltas, 0)
    losses = np.where(deltas < 0, -deltas, 0)
    
    avg_gain = np.mean(gains[:period])
    avg_loss = np.mean(losses[:period])
    
    for i in range(period, len(deltas)):
        avg_gain = (avg_gain * (period-1) + gains[i]) / period
        avg_loss = (avg_loss * (period-1) + losses[i]) / period
    
    rs = avg_gain / (avg_loss + 1e-8)
    return 100 - (100 / (1 + rs))


def calculate_stochastic_rsi(closes, period=14, smooth_k=3, smooth_d=3):
    """Stochastic RSI 계산"""
    if len(closes) < period + smooth_k + smooth_d:
        return 50.0, 50.0
    
    # RSI 계산
    rsi_values = []
    for i in range(period, len(closes) + 1):
        rsi = calculate_rsi(closes[:i], period)
        rsi_values.append(rsi)
    
    if len(rsi_values) < period:
        return 50.0, 50.0
    
    # Stochastic 계산
    stoch_rsi = []
    for i in range(period - 1, len(rsi_values)):
        window = rsi_values[i - period + 1:i + 1]
        min_rsi = min(window)
        max_rsi = max(window)
        
        if max_rsi - min_rsi == 0:
            stoch_rsi.append(50.0)
        else:
            stoch_rsi.append(100 * (rsi_values[i] - min_rsi) / (max_rsi - min_rsi))
    
    if len(stoch_rsi) < smooth_k:
        return 50.0, 50.0
    
    # %K (smoothed)
    k_values = []
    for i in range(smooth_k - 1, len(stoch_rsi)):
        k_values.append(np.mean(stoch_rsi[i - smooth_k + 1:i + 1]))
    
    if len(k_values) < smooth_d:
        return k_values[-1] if k_values else 50.0, 50.0
    
    # %D (smoothed %K)
    d_value = np.mean(k_values[-smooth_d:])
    
    return k_values[-1], d_value


def calculate_macd(closes, fast=12, slow=26, signal=9):
    """MACD 계산"""
    if len(closes) < slow + signal:
        return 0, 0, 0
    
    # EMA 계산
    def ema(data, period):
        weights = np.exp(np.linspace(-1., 0., period))
        weights /= weights.sum()
        
        ema_values = []
        for i in range(period - 1, len(data)):
            window = data[i - period + 1:i + 1]
            ema_values.append(np.sum(weights * window))
        return ema_values
    
    fast_ema = ema(closes, fast)
    slow_ema = ema(closes, slow)
    
    # MACD 라인
    min_len = min(len(fast_ema), len(slow_ema))
    macd_line = np.array(fast_ema[-min_len:]) - np.array(slow_ema[-min_len:])
    
    if len(macd_line) < signal:
        return 0, 0, 0
    
    # 시그널 라인
    signal_line = ema(macd_line.tolist(), signal)
    
    if len(signal_line) == 0:
        return macd_line[-1], 0, 0
    
    # 히스토그램
    histogram = macd_line[-1] - signal_line[-1]
    
    return macd_line[-1], signal_line[-1], histogram


def calculate_bb(closes, window=20, std_dev=2.0):
    """볼린저 밴드"""
    if len(closes) < window:
        window = len(closes)
    
    sma = np.mean(closes[-window:])
    std = np.std(closes[-window:])
    
    lower = sma - (std * std_dev)
    upper = sma + (std * std_dev)
    
    position = (closes[-1] - lower) / (upper - lower + 1e-8)
    width = (upper - lower) / sma * 100
    
    return lower, sma, upper, max(0, min(1, position)), width


def calculate_volume_trend(volumes, window=10):
    """거래량 추세"""
    if len(volumes) < window:
        return 1.0
    
    recent_vol = np.mean(volumes[-3:])
    avg_vol = np.mean(volumes[-window:-3])
    
    if avg_vol == 0:
        return 1.0
    
    return recent_vol / avg_vol


# ═══════════════════════════════════════════════════════════
# 🎯 멀티 타임프레임 분석 엔진
# ═══════════════════════════════════════════════════════════

class MultiTimeframeAnalyzer:
    """멀티 타임프레임 통합 분석"""
    
    TIMEFRAMES = {
        'minute1': {'count': 60, 'weight': 1.0},    # 진입 타이밍
        'minute3': {'count': 40, 'weight': 1.5},    # 단기 추세
        'minute5': {'count': 30, 'weight': 2.0},    # 중기 추세
        'minute15': {'count': 20, 'weight': 2.5}    # 전체 흐름
    }
    
    def __init__(self):
        self.cache = DataCache(ttl=15)
    
    def analyze_ticker(self, ticker):
        """종합 분석"""
        cache_key = f"mtf_{ticker}"
        cached = self.cache.get(cache_key)
        if cached:
            return cached
        
        timeframe_data = {}
        
        for tf_name, tf_config in self.TIMEFRAMES.items():
            df = api_limiter.call_api(
                pyupbit.get_ohlcv,
                ticker,
                interval=tf_name,
                count=tf_config['count']
            )
            
            if df is None or len(df) < 20:
                return {'valid': False, 'reason': f'{tf_name} 데이터 부족'}
            
            closes = df['close'].values
            volumes = df['volume'].values
            highs = df['high'].values
            lows = df['low'].values
            
            # 지표 계산
            bb_lower, bb_mid, bb_upper, bb_pos, bb_width = calculate_bb(closes, 20)
            rsi = calculate_rsi(closes, 14)
            stoch_k, stoch_d = calculate_stochastic_rsi(closes, 14)
            macd, signal, histogram = calculate_macd(closes)
            vol_trend = calculate_volume_trend(volumes)
            
            # 추세 판단
            sma_short = np.mean(closes[-5:])
            sma_long = np.mean(closes[-15:]) if len(closes) >= 15 else sma_short
            trend_direction = 1 if sma_short > sma_long else -1
            
            # 모멘텀
            momentum = ((closes[-1] - closes[-5]) / closes[-5]) * 100 if len(closes) >= 5 else 0
            
            timeframe_data[tf_name] = {
                'weight': tf_config['weight'],
                'current_price': closes[-1],
                'bb_pos': bb_pos,
                'bb_width': bb_width,
                'rsi': rsi,
                'stoch_k': stoch_k,
                'stoch_d': stoch_d,
                'macd': macd,
                'macd_signal': signal,
                'macd_histogram': histogram,
                'vol_trend': vol_trend,
                'trend_direction': trend_direction,
                'momentum': momentum,
                'volatility': (np.max(highs[-5:]) - np.min(lows[-5:])) / closes[-1] * 100
            }
            
            time.sleep(0.2)  # API 보호
        
        result = {
            'valid': True,
            'ticker': ticker,
            'timeframes': timeframe_data,
            'current_price': timeframe_data['minute1']['current_price']
        }
        
        self.cache.set(cache_key, result)
        return result
    
    def score_opportunity(self, analysis):
        """기회 점수 계산"""
        if not analysis['valid']:
            return 0, 'NONE', []
        
        total_score = 0
        weighted_sum = 0
        reasons = []
        
        for tf_name, tf_data in analysis['timeframes'].items():
            tf_score = 0
            weight = tf_data['weight']
            
            # BB 포지션 (하단일수록 좋음)
            bb_pos = tf_data['bb_pos']
            if bb_pos < 0.05:
                tf_score += 25
                if tf_name == 'minute1':
                    reasons.append(f"BB극하단({tf_name})")
            elif bb_pos < 0.15:
                tf_score += 20
            elif bb_pos < 0.25:
                tf_score += 15
            elif bb_pos < 0.35:
                tf_score += 10
            
            # RSI (저평가일수록 좋음)
            rsi = tf_data['rsi']
            if rsi < 20:
                tf_score += 20
                if tf_name == 'minute1':
                    reasons.append(f"RSI극저({rsi:.0f})")
            elif rsi < 30:
                tf_score += 15
            elif rsi < 40:
                tf_score += 10
            elif rsi < 50:
                tf_score += 5
            
            # Stochastic RSI (과매도 확인)
            stoch_k = tf_data['stoch_k']
            if stoch_k < 10:
                tf_score += 15
                if tf_name == 'minute1':
                    reasons.append(f"StochRSI극저({stoch_k:.0f})")
            elif stoch_k < 20:
                tf_score += 10
            elif stoch_k < 30:
                tf_score += 5
            
            # MACD (골든크로스 감지)
            if tf_data['macd_histogram'] > 0 and tf_data['macd'] > tf_data['macd_signal']:
                tf_score += 10
                if tf_name in ['minute1', 'minute3']:
                    reasons.append(f"MACD상승({tf_name})")
            
            # 거래량 증가
            vol_trend = tf_data['vol_trend']
            if vol_trend > 2.0:
                tf_score += 8
            elif vol_trend > 1.5:
                tf_score += 5
            elif vol_trend > 1.2:
                tf_score += 3
            
            # 모멘텀 (반등 확인)
            momentum = tf_data['momentum']
            if momentum > 0.2:
                tf_score += 8
            elif momentum > 0:
                tf_score += 5
            
            # 추세 방향 (상승 추세 선호)
            if tf_data['trend_direction'] > 0:
                tf_score += 5
            
            # 가중 점수 합산
            total_score += tf_score * weight
            weighted_sum += weight
        
        # 정규화
        final_score = (total_score / weighted_sum) if weighted_sum > 0 else 0
        
        # 등급 결정 (더 엄격하게)
        if final_score >= 75 and len(reasons) >= 3:
            grade = 'GOLD'
        elif final_score >= 60 and len(reasons) >= 2:
            grade = 'SILVER'
        elif final_score >= 45 and len(reasons) >= 1:
            grade = 'BRONZE'
        else:
            grade = 'NONE'
        
        return final_score, grade, reasons
    
    def check_multi_timeframe_alignment(self, analysis):
        """타임프레임 정렬 확인"""
        if not analysis['valid']:
            return False
        
        alignment_score = 0
        
        for tf_name, tf_data in analysis['timeframes'].items():
            # 모든 타임프레임이 매수 신호를 보내는지 확인
            is_bullish = (
                tf_data['bb_pos'] < 0.4 and
                tf_data['rsi'] < 55 and
                tf_data['stoch_k'] < 60 and
                tf_data['trend_direction'] >= 0
            )
            
            if is_bullish:
                alignment_score += tf_data['weight']
        
        # 50% 이상 정렬되어야 함
        total_weight = sum(tf['weight'] for tf in analysis['timeframes'].values())
        return (alignment_score / total_weight) >= 0.5


# ═══════════════════════════════════════════════════════════
# 🛡️ 급락 감지 시스템
# ═══════════════════════════════════════════════════════════

class CrashDetector:
    """급락 감지 및 회피 시스템"""
    
    def __init__(self):
        self.crash_detected_until = {}
        self.market_crash_until = None
    
    def check_crash(self, ticker):
        """급락 여부 확인"""
        try:
            if ticker in self.crash_detected_until:
                if datetime.now() < self.crash_detected_until[ticker]:
                    return True, "급락 회피 중"
                else:
                    del self.crash_detected_until[ticker]
            
            df = api_limiter.call_api(
                pyupbit.get_ohlcv,
                ticker,
                interval="minute5",
                count=6
            )
            
            if df is None or len(df) < 3:
                return False, None
            
            recent_change = ((df.iloc[-1]['close'] - df.iloc[-2]['close']) / df.iloc[-2]['close']) * 100
            recent_15min = ((df.iloc[-1]['close'] - df.iloc[-4]['close']) / df.iloc[-4]['close']) * 100
            
            recent_vol = df.iloc[-1]['volume']
            avg_vol = np.mean(df['volume'].values[:-1])
            vol_ratio = recent_vol / (avg_vol + 1e-8)
            
            is_crash = (
                (recent_change < -4.0 and vol_ratio > 2.5) or
                (recent_15min < -7.0)
            )
            
            if is_crash:
                self.crash_detected_until[ticker] = datetime.now() + timedelta(minutes=30)
                return True, f"급락 감지 ({recent_change:.1f}%)"
            
            return False, None
            
        except:
            return False, None
    
    def check_market_crash(self):
        """전체 시장 급락 확인"""
        try:
            if self.market_crash_until and datetime.now() < self.market_crash_until:
                return True, "시장 급락 회피 중"
            
            is_btc_crash, _ = self.check_crash("KRW-BTC")
            
            if is_btc_crash:
                self.market_crash_until = datetime.now() + timedelta(hours=1)
                return True, "BTC 급락"
            
            return False, None
            
        except:
            return False, None


# ═══════════════════════════════════════════════════════════
# 🏰 Fortress Protection
# ═══════════════════════════════════════════════════════════

class FortressProtection:
    """요새 보호 시스템"""
    
    def __init__(self, initial_capital=1_000_000):
        self.initial = initial_capital
        
        saved_state = storage.load()
        
        if saved_state:
            self.current_asset = saved_state['current_asset']
            self.peak_asset = saved_state['peak_asset']
            self.daily_loss = saved_state['daily_loss']
            self.daily_profit = saved_state['daily_profit']
            self.consecutive_loss = saved_state['consecutive_loss']
            self.last_trade_date = datetime.fromisoformat(saved_state['last_trade_date']).date()
            self.total_trades = saved_state['total_trades']
            self.win_trades = saved_state['win_trades']
            self.total_profit = saved_state['total_profit']
            self.grade_stats = saved_state.get('grade_stats', {'GOLD': 0, 'SILVER': 0, 'BRONZE': 0})
            
            print("✅ 이전 상태 복구")
            self.print_status()
        else:
            self.current_asset = initial_capital
            self.peak_asset = initial_capital
            self.daily_loss = 0
            self.daily_profit = 0
            self.consecutive_loss = 0
            self.last_trade_date = datetime.now().date()
            self.total_trades = 0
            self.win_trades = 0
            self.total_profit = 0
            self.grade_stats = {'GOLD': 0, 'SILVER': 0, 'BRONZE': 0}
            
            self.save_state()
    
    def save_state(self):
        """상태 저장"""
        state = {
            'initial': self.initial,
            'current_asset': self.current_asset,
            'peak_asset': self.peak_asset,
            'daily_loss': self.daily_loss,
            'daily_profit': self.daily_profit,
            'consecutive_loss': self.consecutive_loss,
            'last_trade_date': self.last_trade_date.isoformat(),
            'total_trades': self.total_trades,
            'win_trades': self.win_trades,
            'total_profit': self.total_profit,
            'grade_stats': self.grade_stats,
            'updated_at': datetime.now().isoformat()
        }
        return storage.save(state)
    
    def update_daily_reset(self):
        """일일 초기화"""
        today = datetime.now().date()
        if today != self.last_trade_date:
            self.daily_loss = 0
            self.daily_profit = 0
            self.last_trade_date = today
            print(f"\n📅 일일 통계 초기화: {today}")
            self.save_state()
    
    def can_trade(self):
        """거래 가능 여부"""
        self.update_daily_reset()
        
        total_profit = self.current_asset - self.initial
        max_daily_loss = max(total_profit * 0.03, self.initial * 0.02)
        
        if self.daily_loss >= max_daily_loss:
            return False, f"일일 손실 한도"
        
        if self.consecutive_loss >= 4:
            return False, f"연속 손실 {self.consecutive_loss}회"
        
        if self.current_asset < self.initial * 0.80:
            return False, f"자산 하락 한계"
        
        return True, "OK"
    
    def record_trade(self, profit_krw, profit_rate, grade='SILVER'):
        """거래 결과 기록"""
        self.update_daily_reset()
        
        self.total_trades += 1
        self.grade_stats[grade] = self.grade_stats.get(grade, 0) + 1
        
        if profit_krw > 0:
            self.win_trades += 1
            self.daily_profit += profit_krw
            self.consecutive_loss = 0
            
            if self.current_asset > self.peak_asset:
                self.peak_asset = self.current_asset
        else:
            self.daily_loss += abs(profit_krw)
            self.consecutive_loss += 1
        
        self.total_profit += profit_krw
        self.save_state()
        self.print_trade_result(profit_krw, profit_rate, grade)
    
    def print_trade_result(self, profit_krw, profit_rate, grade):
        """거래 결과 출력"""
        win_rate = (self.win_trades / self.total_trades * 100) if self.total_trades > 0 else 0
        
        grade_emoji = {'GOLD': '🥇', 'SILVER': '🥈', 'BRONZE': '🥉'}.get(grade, '⚪')
        
        print(f"\n{'='*60}")
        print(f"{grade_emoji} 거래 #{self.total_trades} [{grade}]")
        print(f"{'='*60}")
        print(f"손익: {profit_krw:+,.0f}원 ({profit_rate:+.2f}%)")
        print(f"현재: {self.current_asset:,.0f}원 | 누적: {self.total_profit:+,.0f}원")
        print(f"승률: {win_rate:.1f}%")
        print(f"{'='*60}\n")
        
        msg = f"{grade_emoji} [{grade}] {profit_krw:+,.0f}원 ({profit_rate:+.2f}%)\n승률: {win_rate:.1f}%"
        send_discord_message(msg)
    
    def print_status(self):
        """상태 출력"""
        win_rate = (self.win_trades / self.total_trades * 100) if self.total_trades > 0 else 0
        
        print(f"\n{'='*60}")
        print(f"🏰 Fortress v5.0")
        print(f"{'='*60}")
        print(f"자산: {self.current_asset:,.0f}원 ({self.total_profit:+,.0f}원)")
        print(f"거래: {self.total_trades}회 | 승률: {win_rate:.1f}%")
        print(f"{'='*60}\n")
    
    def get_position_size_multiplier(self):
        """포지션 배율"""
        profit_rate = (self.current_asset / self.initial - 1) * 100
        
        if profit_rate < 0:
            return 0.6
        elif profit_rate < 30:
            return 0.9
        elif profit_rate < 100:
            return 1.2
        else:
            return 1.5


# ═══════════════════════════════════════════════════════════
# 🎯 스마트 Hunter v5
# ═══════════════════════════════════════════════════════════

class SmartHunterV5:
    """v5.0 스마트 헌터"""
    
    GRADE_CONFIGS = {
        'GOLD': {
            'target_profit': 1.5,
            'min_profit': 1.0,
            'trailing_start': 0.8,
            'trailing_gap': 0.4
        },
        'SILVER': {
            'target_profit': 1.2,
            'min_profit': 0.8,
            'trailing_start': 0.6,
            'trailing_gap': 0.3
        },
        'BRONZE': {
            'target_profit': 0.8,
            'min_profit': 0.5,
            'trailing_start': 0.4,
            'trailing_gap': 0.2
        }
    }
    
    def __init__(self):
        self.mtf_analyzer = MultiTimeframeAnalyzer()
        self.crash_detector = CrashDetector()
    
    def find_best_opportunity(self, tickers):
        """최적 기회 탐색"""
        print(f"\n{'='*60}")
        print(f"🔍 멀티 타임프레임 스캔 ({len(tickers)}개 종목)")
        print(f"{'='*60}")
        
        market_crash, crash_msg = self.crash_detector.check_market_crash()
        if market_crash:
            print(f"🚨 {crash_msg}")
            return None
        
        candidates = []
        
        for idx, ticker in enumerate(tickers, 1):
            is_crash, crash_msg = self.crash_detector.check_crash(ticker)
            if is_crash:
                print(f"[{idx}/{len(tickers)}] {ticker}: ⚠️ {crash_msg}")
                continue
            
            analysis = self.mtf_analyzer.analyze_ticker(ticker)
            
            if not analysis['valid']:
                print(f"[{idx}/{len(tickers)}] {ticker}: ❌ {analysis.get('reason', '데이터 부족')}")
                continue
            
            score, grade, reasons = self.mtf_analyzer.score_opportunity(analysis)
            
            if grade == 'NONE':
                print(f"[{idx}/{len(tickers)}] {ticker}: ⏭️ {score:.1f}점")
                continue
            
            # 타임프레임 정렬 확인
            is_aligned = self.mtf_analyzer.check_multi_timeframe_alignment(analysis)
            
            if not is_aligned:
                print(f"[{idx}/{len(tickers)}] {ticker}: ⚠️ 타임프레임 불일치")
                continue
            
            grade_emoji = {'GOLD': '🥇', 'SILVER': '🥈', 'BRONZE': '🥉'}[grade]
            
            print(f"[{idx}/{len(tickers)}] {ticker}: {grade_emoji} {score:.1f}점 [{grade}]")
            
            candidates.append({
                'ticker': ticker,
                'score': score,
                'grade': grade,
                'reasons': reasons,
                'analysis': analysis
            })
        
        print(f"{'='*60}")
        
        if not candidates:
            print("⏳ 적합한 기회 없음")
            return None
        
        best = max(candidates, key=lambda x: x['score'])
        
        grade_emoji = {'GOLD': '🥇', 'SILVER': '🥈', 'BRONZE': '🥉'}[best['grade']]
        
        print(f"\n{grade_emoji} 선정: {best['ticker']} [{best['grade']}] {best['score']:.1f}점")
        print(f"   이유: {', '.join(best['reasons'][:3])}")
        
        return best


# ═══════════════════════════════════════════════════════════
# 💰 유틸리티 함수
# ═══════════════════════════════════════════════════════════

def get_krw_balance(upbit):
    """KRW 잔고"""
    for _ in range(2):
        try:
            balances = upbit.get_balances()
            for b in balances:
                if b['currency'] == "KRW":
                    return float(b['balance'])
        except:
            time.sleep(1)
    return 0.0


def get_balance(ticker):
    """코인 잔고"""
    for _ in range(2):
        try:
            balances = upbit.get_balances()
            for b in balances:
                if b['currency'] == ticker:
                    return float(b['balance']) if b['balance'] is not None else 0
        except:
            time.sleep(1)
    return 0


def get_total_crypto_value(upbit):
    """암호화폐 평가액"""
    try:
        balances = upbit.get_balances()
        total = 0.0
        
        for balance in balances:
            if balance['currency'] == 'KRW':
                continue
            
            amount = float(balance['balance'])
            if amount > 0:
                ticker_name = f"KRW-{balance['currency']}"
                price = api_limiter.call_api(pyupbit.get_current_price, ticker_name)
                if price:
                    total += amount * price
        
        return total
    except:
        return 0.0


def get_holding_tickers(upbit):
    """현재 보유 중인 코인 목록 조회"""
    try:
        balances = upbit.get_balances()
        holdings = []
        
        for b in balances:
            if b['currency'] == 'KRW':
                continue
            
            amount = float(b.get('balance', 0)) + float(b.get('locked', 0))
            if amount > 0:
                ticker = f"KRW-{b['currency']}"
                holdings.append(ticker)
        
        return holdings
    except Exception as e:
        print(f"⚠️ 보유 종목 조회 오류: {e}")
        return []


# ═══════════════════════════════════════════════════════════
# 📊 스마트 자산 리포터
# ═══════════════════════════════════════════════════════════

# 전역 변수
profit_report_thread = None
profit_report_running = False


def analyze_holding(ticker, current_price, hunter):
    """보유 코인 분석"""
    try:
        analysis = hunter.mtf_analyzer.analyze_ticker(ticker)
        
        if not analysis['valid']:
            return {
                'valid': False,
                'message': '데이터 부족'
            }
        
        score, grade, reasons = hunter.mtf_analyzer.score_opportunity(analysis)
        
        # 1분봉 데이터 기준 예측
        tf_minute1 = analysis['timeframes']['minute1']
        tf_minute5 = analysis['timeframes']['minute5']
        
        # 추세 예측
        if tf_minute1['bb_pos'] < 0.3 and tf_minute1['rsi'] < 40:
            trend = "상승 기대"
            trend_emoji = "🚀"
        elif tf_minute1['bb_pos'] < 0.5 and tf_minute1['rsi'] < 55:
            trend = "횡보 예상"
            trend_emoji = "➡️"
        elif tf_minute1['bb_pos'] > 0.7 or tf_minute1['rsi'] > 65:
            trend = "조정 우려"
            trend_emoji = "📉"
        else:
            trend = "중립"
            trend_emoji = "⚖️"
        
        # 액션 추천
        if tf_minute1['stoch_k'] < 20 and tf_minute5['stoch_k'] < 30:
            action = "HOLD 🔒"
            action_reason = "반등 대기"
        elif tf_minute1['stoch_k'] > 80 and tf_minute5['stoch_k'] > 75:
            action = "EXIT 🚪"
            action_reason = "고점 - 익절 고려"
        elif tf_minute1['macd_histogram'] < 0 and tf_minute5['macd_histogram'] < 0:
            action = "CAUTION ⚠️"
            action_reason = "하락 신호"
        else:
            action = "WATCH 👁️"
            action_reason = "관찰"
        
        return {
            'valid': True,
            'score': score,
            'grade': grade,
            'reasons': reasons,
            'trend': trend,
            'trend_emoji': trend_emoji,
            'action': action,
            'action_reason': action_reason,
            'rsi': tf_minute1['rsi'],
            'stoch_k': tf_minute1['stoch_k'],
            'bb_pos': tf_minute1['bb_pos'],
            'macd_histogram': tf_minute1['macd_histogram']
        }
    
    except Exception as e:
        return {
            'valid': False,
            'message': f'분석 실패: {str(e)}'
        }


def generate_smart_report(fortress, hunter, upbit_instance, is_startup=False):
    """스마트 자산 보고서 생성"""
    try:
        report_time = datetime.now()
        
        balances = upbit_instance.get_balances()
        if not balances:
            raise Exception("잔고 조회 실패")
        
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
            
            ticker = f"KRW-{currency}"
            
            try:
                current_price = api_limiter.call_api(
                    pyupbit.get_current_price, ticker
                )
                
                if not current_price:
                    continue
                
                avg_buy = float(b.get('avg_buy_price', 0))
                eval_value = balance * current_price
                profit_rate = ((current_price - avg_buy) / avg_buy * 100) if avg_buy > 0 else 0
                net_profit = eval_value - (balance * avg_buy)
                
                crypto_value += eval_value
                total_value += eval_value
                
                analysis = analyze_holding(ticker, current_price, hunter)
                
                holdings.append({
                    'ticker': ticker,
                    'name': currency,
                    'balance': balance,
                    'current_price': current_price,
                    'avg_buy': avg_buy,
                    'eval_value': eval_value,
                    'profit_rate': profit_rate,
                    'net_profit': net_profit,
                    'analysis': analysis
                })
                
                time.sleep(0.3)
            
            except Exception as e:
                print(f"⚠️ {ticker} 분석 실패: {e}")
                continue
        
        holdings.sort(key=lambda x: x['eval_value'], reverse=True)
        
        msg = format_smart_report(
            report_time, is_startup,
            total_value, krw_balance, crypto_value,
            holdings, fortress
        )
        
        print(f"\n{msg}\n")
        send_discord_message(msg)
        
        return True
        
    except Exception as e:
        error_msg = f"❌ 보고서 오류\n{datetime.now().strftime('%H:%M:%S')}\n{str(e)}"
        print(error_msg)
        send_discord_message(error_msg)
        return False


def format_smart_report(report_time, is_startup, total_value, krw_balance, 
                       crypto_value, holdings, fortress):
    """스마트 보고서 포맷팅"""
    
    if is_startup:
        header = f"🏰 [{report_time.strftime('%m/%d %H:%M')}] 시작 보고서"
    else:
        header = f"📊 [{report_time.strftime('%m/%d %H시')}] 정시 보고서"
    
    msg = f"{header}\n"
    msg += "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
    
    initial = fortress.initial
    profit_total = total_value - initial
    profit_rate = (profit_total / initial) * 100
    
    msg += f"💰 총자산: {total_value:,.0f}원\n"
    msg += f"   초기: {initial:,.0f}원 | 누적: {profit_total:+,.0f}원 ({profit_rate:+.2f}%)\n"
    msg += f"   KRW: {krw_balance:,.0f}원 | 코인: {crypto_value:,.0f}원\n"
    
    win_rate = (fortress.win_trades / fortress.total_trades * 100) if fortress.total_trades > 0 else 0
    msg += f"   거래: {fortress.total_trades}회 | 승률: {win_rate:.1f}%\n"
    
    msg += "\n"
    
    if not holdings:
        msg += "📭 보유 코인 없음\n"
        msg += "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
        return msg
    
    msg += f"🪙 보유 코인 ({len(holdings)}개)\n"
    msg += "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
    
    for i, h in enumerate(holdings, 1):
        profit_emoji = "🔥" if h['profit_rate'] > 2 else "📈" if h['profit_rate'] > 0 else "📉"
        
        msg += f"\n{i}. {h['name']} {profit_emoji}\n"
        msg += f"   💵 {h['profit_rate']:+6.2f}% | {h['eval_value']:,.0f}원 | {h['net_profit']:+,.0f}원\n"
        
        analysis = h['analysis']
        
        if analysis['valid']:
            grade_emoji = {'GOLD': '🥇', 'SILVER': '🥈', 'BRONZE': '🥉', 'NONE': '⚪'}
            grade_icon = grade_emoji.get(analysis['grade'], '⚪')
            
            msg += f"   {grade_icon} {analysis['grade']} {analysis['score']:.0f}점"
            msg += f" | RSI:{analysis['rsi']:.0f} StochK:{analysis['stoch_k']:.0f}\n"
            msg += f"   {analysis['trend_emoji']} {analysis['trend']}\n"
            msg += f"   📌 {analysis['action']} - {analysis['action_reason']}\n"
        else:
            msg += f"   ⚠️ {analysis.get('message', '분석 불가')}\n"
    
    msg += "\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    
    return msg


def start_smart_reporter(fortress, hunter, upbit_instance):
    """스마트 리포터 시작"""
    global profit_report_thread, profit_report_running
    
    if profit_report_running:
        print("⚠️ 리포터 이미 실행 중")
        return
    
    profit_report_running = True
    
    def report_loop():
        """리포트 루프"""
        global profit_report_running
        
        try:
            print(f"\n{'='*60}")
            print(f"📊 스마트 자산 리포터 시작")
            print(f"{'='*60}\n")
            
            # 🆕 초기화 완료 대기
            time.sleep(1)
            
            # 시작 시 보고서
            print("📝 시작 보고서 생성 중...")
            generate_smart_report(
                fortress, hunter, upbit_instance,
                is_startup=True
            )
            
            while profit_report_running:
                try:
                    now = datetime.now()
                    
                    # 정시마다 보고서 생성
                    if now.minute == 0 and now.second < 30:
                        print(f"\n[{now.strftime('%H:%M:%S')}] 📝 정시 보고서 생성 중...")
                        
                        generate_smart_report(
                            fortress, hunter, upbit_instance,
                            is_startup=False
                        )
                        
                        # 다음 정시까지 대기
                        time.sleep(3600)
                    else:
                        # 정시까지 남은 시간 계산
                        next_hour = (now + timedelta(hours=1)).replace(
                            minute=0, second=0, microsecond=0
                        )
                        wait_seconds = (next_hour - now).total_seconds()
                        time.sleep(min(wait_seconds, 60))
                
                except Exception as e:
                    print(f"⚠️ 리포트 루프 오류: {e}")
                    time.sleep(300)
        
        except Exception as e:
            print(f"❌ 리포터 치명적 오류: {e}")
        
        finally:
            profit_report_running = False
    
    profit_report_thread = Thread(target=report_loop, daemon=True)
    profit_report_thread.start()
    print("✅ 스마트 리포터 스레드 시작\n")


# ═══════════════════════════════════════════════════════════
# 🚀 매수 시스템
# ═══════════════════════════════════════════════════════════

def smart_buy(fortress, hunter, tickers):
    """스마트 매수"""
    
    can_trade, reason = fortress.can_trade()
    if not can_trade:
        print(f"❌ 거래 불가: {reason}")
        return None
    
    krw_balance = get_krw_balance(upbit)
    crypto_value = get_total_crypto_value(upbit)
    total_asset = krw_balance + crypto_value
    
    fortress.current_asset = total_asset
    
    MIN_ORDER = 5000
    if krw_balance < MIN_ORDER:
        print(f"⏳ KRW 잔고 부족 ({krw_balance:,.0f}원)")
        return None
    
    # 🆕 보유 중인 코인 확인 및 제외
    holding_tickers = get_holding_tickers(upbit)
    
    if holding_tickers:
        holding_names = [t.split('-')[1] for t in holding_tickers]
        print(f"\n📦 보유 중: {', '.join(holding_names)} ({len(holding_tickers)}개)")
        
        # 보유 종목 제외
        available_tickers = [t for t in tickers if t not in holding_tickers]
        
        if not available_tickers:
            print(f"⏳ 모든 대상 코인 보유 중 - 매도 대기")
            return None
        
        print(f"✅ 매수 대상: {len(available_tickers)}개 종목 (보유 제외)")
    else:
        available_tickers = tickers
        print(f"✅ 매수 대상: {len(available_tickers)}개 종목 (전체)")
    
    multiplier = fortress.get_position_size_multiplier()
    buy_size = total_asset * 0.20 * multiplier
    max_krw = krw_balance * 0.995
    buy_size = min(buy_size, max_krw)
    
    if buy_size < MIN_ORDER:
        return None
    
    print(f"💰 매수 가능 금액: {buy_size:,.0f}원")
    
    # 🆕 available_tickers를 전달 (보유 제외된 목록)
    opportunity = hunter.find_best_opportunity(available_tickers)
    
    if opportunity is None:
        return None
    
    ticker = opportunity['ticker']
    grade = opportunity['grade']
    
    try:
        current_price = api_limiter.call_api(pyupbit.get_current_price, ticker)
        
        if current_price is None:
            return None
        
        buy_order = upbit.buy_market_order(ticker, buy_size)
        
        print(f"\n✅ 매수 완료: {ticker} [{grade}] {buy_size:,.0f}원")
        
        grade_emoji = {'GOLD': '🥇', 'SILVER': '🥈', 'BRONZE': '🥉'}[grade]
        msg = f"{grade_emoji} 매수\n{ticker} [{grade}]\n{buy_size:,.0f}원\n목표: +{hunter.GRADE_CONFIGS[grade]['target_profit']}%"
        send_discord_message(msg)
        
        return {
            'ticker': ticker,
            'buy_price': current_price,
            'grade': grade,
            'config': hunter.GRADE_CONFIGS[grade],
            'analysis': opportunity['analysis']
        }
        
    except Exception as e:
        print(f"❌ 매수 실패: {e}")
        return None


# ═══════════════════════════════════════════════════════════
# 📉 예측 기반 스마트 매도 v5
# ═══════════════════════════════════════════════════════════

def predictive_sell_v5(buy_info, fortress, hunter):
    """v5.0 예측 기반 매도 시스템"""
    
    ticker = buy_info['ticker']
    buy_price = buy_info['buy_price']
    grade = buy_info['grade']
    config = buy_info['config']
    
    currency = ticker.split("-")[1]
    
    try:
        buyed_amount = get_balance(currency)
        if buyed_amount <= 0:
            return None
        
        avg_buy_price = upbit.get_avg_buy_price(currency)
    except:
        return None
    
    grade_emoji = {'GOLD': '🥇', 'SILVER': '🥈', 'BRONZE': '🥉'}[grade]
    
    print(f"\n📊 [{ticker}] 예측 매도 감시 시작")
    print(f"   등급: {grade_emoji} {grade}")
    print(f"   목표: +{config['target_profit']}% | 최소: +{config['min_profit']}%")
    
    start_time = time.time()
    max_profit_rate = -999
    trailing_active = False
    check_count = 0
    
    while True:
        try:
            elapsed = time.time() - start_time
            check_count += 1
            
            # 현재가 조회
            cur_price = api_limiter.call_api(pyupbit.get_current_price, ticker)
            if cur_price is None:
                time.sleep(2)
                continue
            
            profit_rate = (cur_price - avg_buy_price) / avg_buy_price * 100
            profit_krw = (cur_price - avg_buy_price) * buyed_amount
            
            if profit_rate > max_profit_rate:
                max_profit_rate = profit_rate
            
            # 콘솔 출력 (간결하게)
            minutes = int(elapsed / 60)
            seconds = int(elapsed % 60)
            print(f"[{minutes:02d}:{seconds:02d}] {profit_rate:+.2f}% (최고: {max_profit_rate:+.2f}%)", end="\r")
            
            # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
            # 🎯 매도 조건 체크 (우선순위 순)
            # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
            
            # 1️⃣ 목표 수익 달성 → 즉시 매도
            if profit_rate >= config['target_profit']:
                print(f"\n✅ 목표 달성! {profit_rate:+.2f}%")
                
                sell_order = upbit.sell_market_order(ticker, buyed_amount)
                fortress.record_trade(profit_krw, profit_rate, grade)
                
                msg = f"✅ {grade_emoji} 목표달성\n{ticker}\n{profit_krw:+,.0f}원 ({profit_rate:+.2f}%)"
                send_discord_message(msg)
                
                return sell_order
            
            # 2️⃣ 트레일링 스톱 (수익 보호)
            if profit_rate >= config['trailing_start']:
                if not trailing_active:
                    trailing_active = True
                    print(f"\n🛡️ 트레일링 활성화 (+{profit_rate:.2f}%)")
                
                trailing_stop_rate = max_profit_rate - config['trailing_gap']
                
                if profit_rate <= trailing_stop_rate:
                    print(f"\n🛡️ 트레일링 매도 (최고: {max_profit_rate:.2f}% → 현재: {profit_rate:.2f}%)")
                    
                    sell_order = upbit.sell_market_order(ticker, buyed_amount)
                    fortress.record_trade(profit_krw, profit_rate, grade)
                    
                    msg = f"🛡️ {grade_emoji} 트레일링\n{ticker}\n{profit_krw:+,.0f}원 ({profit_rate:+.2f}%)"
                    send_discord_message(msg)
                    
                    return sell_order
            
            # 3️⃣ 예측 기반 손절 (10분마다 심층 분석)
            if check_count % 20 == 0 or elapsed > 600:
                try:
                    analysis = hunter.mtf_analyzer.analyze_ticker(ticker)
                    
                    if analysis['valid']:
                        tf_minute1 = analysis['timeframes']['minute1']
                        tf_minute5 = analysis['timeframes']['minute5']
                        
                        # 🚨 폭락 징후 감지
                        is_crashing = (
                            (tf_minute1['stoch_k'] < 10 and tf_minute5['stoch_k'] < 15) and
                            (tf_minute1['macd_histogram'] < 0 and tf_minute5['macd_histogram'] < 0) and
                            (tf_minute1['vol_trend'] > 2.0) and
                            (tf_minute1['momentum'] < -0.5 and tf_minute5['momentum'] < -0.8)
                        )
                        
                        if is_crashing and profit_rate < config['min_profit']:
                            print(f"\n🚨 폭락 징후 → 긴급 매도")
                            
                            sell_order = upbit.sell_market_order(ticker, buyed_amount)
                            fortress.record_trade(profit_krw, profit_rate, grade)
                            
                            msg = f"🚨 {grade_emoji} 폭락 손절\n{ticker}\n{profit_krw:+,.0f}원 ({profit_rate:+.2f}%)"
                            send_discord_message(msg)
                            
                            return sell_order
                        
                        # 📈 반등 신호 확인
                        if profit_rate < 0:
                            is_reversing = (
                                (tf_minute1['stoch_k'] > 20 and tf_minute1['stoch_k'] > tf_minute1['stoch_d']) and
                                (tf_minute1['macd_histogram'] > -0.5) and
                                (tf_minute1['momentum'] > -0.3)
                            )
                            
                            if is_reversing:
                                print(f"\n📈 반등 신호 → 홀딩 ({profit_rate:+.2f}%)")
                            else:
                                if profit_rate < -1.5:
                                    print(f"\n🚨 반등 실패 → 손절")
                                    
                                    sell_order = upbit.sell_market_order(ticker, buyed_amount)
                                    fortress.record_trade(profit_krw, profit_rate, grade)
                                    
                                    msg = f"🚨 {grade_emoji} 반등실패\n{ticker}\n{profit_krw:+,.0f}원 ({profit_rate:+.2f}%)"
                                    send_discord_message(msg)
                                    
                                    return sell_order
                
                except Exception as e:
                    print(f"\n⚠️ 분석 오류: {e}")
            
            # 4️⃣ 최대 보유 시간 (2시간)
            if elapsed >= 7200:
                print(f"\n⏰ 최대 시간 → 강제 매도")
                
                sell_order = upbit.sell_market_order(ticker, buyed_amount)
                fortress.record_trade(profit_krw, profit_rate, grade)
                
                msg = f"⏰ {grade_emoji} 시간초과\n{ticker}\n{profit_krw:+,.0f}원 ({profit_rate:+.2f}%)"
                send_discord_message(msg)
                
                return sell_order
            
            time.sleep(5)
            
        except KeyboardInterrupt:
            print("\n❌ 매도 중단")
            return None
        
        except Exception as e:
            print(f"\n⚠️ 매도 오류: {e}")
            time.sleep(5)


# ═══════════════════════════════════════════════════════════
# 🎮 메인 실행
# ═══════════════════════════════════════════════════════════

def main():
    """메인"""
    
    print("="*60)
    print("🏰 Fortress Hunter v5.0 시작")
    print("="*60)
    print("✅ 시작 리포트 출력 보장")
    print("✅ 보유종목 완전 제외")
    print("✅ 멀티 타임프레임 + 예측 매도")
    print("="*60 + "\n")
    
    fortress = FortressProtection(initial_capital=1_000_000)
    hunter = SmartHunterV5()
    
    # 🆕 리포터 시작 (초기화 완료 후)
    start_smart_reporter(fortress, hunter, upbit)
    
    # 리포터 초기화 대기
    time.sleep(3)
    
    msg = f"🏰 v5.0 시작\n현재: {fortress.current_asset:,.0f}원"
    send_discord_message(msg)
    
    last_scan_time = 0
    
    while True:
        try:
            if fortress.current_asset >= 1_000_000_000:
                msg = f"🎉 목표 달성!\n{fortress.current_asset:,.0f}원"
                print(f"\n{'='*60}\n{msg}\n{'='*60}")
                send_discord_message(msg)
                break
            
            current_time = time.time()
            
            # 30초마다 스캔
            if current_time - last_scan_time >= SCAN_INTERVAL:
                buy_info = smart_buy(fortress, hunter, STRATEGIC_COINS)
                last_scan_time = current_time
                
                if buy_info:
                    time.sleep(3)
                    
                    predictive_sell_v5(buy_info, fortress, hunter)
                    
                    print("\n⏳ 10초 대기...\n")
                    time.sleep(10)
                    last_scan_time = 0  # 즉시 다음 스캔
                else:
                    print(f"⏳ 다음 스캔: {SCAN_INTERVAL}초 후")
            else:
                wait_time = SCAN_INTERVAL - (current_time - last_scan_time)
                time.sleep(min(wait_time, 5))
            
        except KeyboardInterrupt:
            print("\n프로그램 종료...")
            fortress.save_state()
            break
        
        except Exception as e:
            print(f"❌ 메인 루프 오류: {e}")
            send_discord_message(f"❌ 오류: {e}")
            fortress.save_state()
            time.sleep(30)
    
    print("\n🏰 Fortress Hunter 종료")


if __name__ == "__main__":
    main()
