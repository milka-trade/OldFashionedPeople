"""
🏰 Fortress Hunter v3.2 Final - 완전 통합판
100만원 → 10억원 자동매매 시스템

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🎯 핵심 기능:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
1. 3단계 적응형 진입 (GOLD/SILVER/BRONZE)
2. 수익 중 시간 무제한 (목표 달성까지 보유)
3. 백테스팅 기반 최적 손절선 (-0.9/-0.7/-0.5%)
4. 변동성 고려 동적 손절
5. 트레일링 스톡 (수익 보호)
6. 스마트 자산 리포터 (기술적 분석 + 전망)
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
TICKER_ANALYSIS_DELAY = 0.5


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
    
    def __init__(self, filepath='fortress_state_v3.json'):
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
# ⏱️ API 호출 관리
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


api_limiter = APIRateLimiter()
storage = SafeJSONStorage()


# ═══════════════════════════════════════════════════════════
# 📊 일중 고저점 예측 시스템
# ═══════════════════════════════════════════════════════════

class IntradayPatternAnalyzer:
    """일중 고저점 패턴 분석기"""
    
    def __init__(self):
        self.patterns = defaultdict(list)
    
    def is_good_entry_timing(self, ticker, current_price):
        """현재가가 일중 저점 구간인지 판단"""
        try:
            df_today = api_limiter.call_api(
                pyupbit.get_ohlcv,
                ticker,
                interval="day",
                count=1
            )
            
            if df_today is None or len(df_today) == 0:
                return True
            
            today_open = df_today.iloc[0]['open']
            today_high = df_today.iloc[0]['high']
            today_low = df_today.iloc[0]['low']
            
            if today_open > 0:
                position_pct = ((current_price - today_open) / today_open) * 100
                
                if today_high > today_low:
                    intraday_position = (current_price - today_low) / (today_high - today_low)
                else:
                    intraday_position = 0.5
                
                is_good_timing = (
                    -2.0 <= position_pct <= 0.5 and
                    intraday_position <= 0.5
                )
                
                return is_good_timing
            
            return True
            
        except:
            return True


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
                (recent_change < -3.0 and vol_ratio > 2.0) or
                (recent_15min < -5.0)
            )
            
            if is_crash:
                self.crash_detected_until[ticker] = datetime.now() + timedelta(minutes=30)
                return True, f"급락 감지 ({recent_change:.1f}%)"
            
            return False, None
            
        except:
            return False, None
    
    def check_market_crash(self, tickers):
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
        max_daily_loss = max(total_profit * 0.03, self.initial * 0.015)
        
        if self.daily_loss >= max_daily_loss:
            return False, f"일일 손실 한도"
        
        if self.consecutive_loss >= 3:
            return False, f"연속 손실 {self.consecutive_loss}회"
        
        if self.current_asset < self.initial * 0.85:
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
        print(f"🏰 Fortress v3.2")
        print(f"{'='*60}")
        print(f"자산: {self.current_asset:,.0f}원")
        print(f"거래: {self.total_trades}회 | 승률: {win_rate:.1f}%")
        print(f"{'='*60}\n")
    
    def get_position_size_multiplier(self):
        """포지션 배율"""
        profit_rate = (self.current_asset / self.initial - 1) * 100
        
        if profit_rate < 0:
            return 0.7
        elif profit_rate < 30:
            return 1.0
        elif profit_rate < 100:
            return 1.3
        else:
            return 1.5


# ═══════════════════════════════════════════════════════════
# 🎯 3단계 스마트 Hunter
# ═══════════════════════════════════════════════════════════

class SmartThreeStageHunter:
    """3단계 적응형 진입 시스템"""
    
    GRADE_CONFIGS = {
        'GOLD': {
            'min_score': 90,
            'target_profit': 1.2,
            'base_stop_loss': -0.9,
            'trailing_start': 0.6,
            'trailing_gap': 0.4
        },
        'SILVER': {
            'min_score': 70,
            'target_profit': 0.8,
            'base_stop_loss': -0.7,
            'trailing_start': 0.4,
            'trailing_gap': 0.3
        },
        'BRONZE': {
            'min_score': 50,
            'target_profit': 0.5,
            'base_stop_loss': -0.5,
            'trailing_start': 0.3,
            'trailing_gap': 0.2
        }
    }
    
    def __init__(self):
        self.pattern_analyzer = IntradayPatternAnalyzer()
        self.crash_detector = CrashDetector()
    
    def analyze_opportunity(self, ticker):
        """기회 분석"""
        try:
            df = api_limiter.call_api(
                pyupbit.get_ohlcv,
                ticker,
                interval="minute1",
                count=30
            )
            
            if df is None or len(df) < 20:
                return {'valid': False}
            
            closes = df['close'].values
            volumes = df['volume'].values
            highs = df['high'].values
            lows = df['low'].values
            current_price = closes[-1]
            
            bb_lower, bb_mid, bb_upper, bb_pos, bb_width = calculate_bb(closes, 20)
            rsi = calculate_rsi(closes, 14)
            
            recent_avg = np.mean(closes[-3:])
            prev_avg = np.mean(closes[-8:-3])
            momentum = ((recent_avg - prev_avg) / prev_avg) * 100 if prev_avg > 0 else 0
            
            vol_recent = np.mean(volumes[-3:])
            vol_normal = np.mean(volumes[-10:-3])
            vol_ratio = vol_recent / (vol_normal + 1e-8)
            
            recent_range = np.mean(highs[-5:] - lows[-5:])
            volatility_pct = (recent_range / current_price) * 100
            
            return {
                'valid': True,
                'ticker': ticker,
                'current_price': current_price,
                'bb_pos': bb_pos,
                'bb_width': bb_width,
                'rsi': rsi,
                'momentum': momentum,
                'vol_ratio': vol_ratio,
                'volatility_pct': volatility_pct
            }
            
        except:
            return {'valid': False}
    
    def score_opportunity(self, analysis):
        """점수 계산"""
        if not analysis['valid']:
            return 0, 'NONE', []
        
        score = 0
        reasons = []
        
        bb_pos = analysis['bb_pos']
        if bb_pos < 0.10:
            score += 40
            reasons.append("BB극하단")
        elif bb_pos < 0.20:
            score += 30
            reasons.append("BB하단")
        elif bb_pos < 0.30:
            score += 20
        elif bb_pos < 0.40:
            score += 10
        
        rsi = analysis['rsi']
        if rsi < 20:
            score += 30
            reasons.append("RSI극저")
        elif rsi < 30:
            score += 25
            reasons.append("RSI저")
        elif rsi < 40:
            score += 18
        elif rsi < 50:
            score += 10
        
        momentum = analysis['momentum']
        if momentum > 0.15:
            score += 15
            reasons.append("강반등")
        elif momentum > 0:
            score += 10
            reasons.append("약반등")
        elif momentum > -0.15:
            score += 5
        
        vol_ratio = analysis['vol_ratio']
        if vol_ratio > 2.0:
            score += 10
        elif vol_ratio > 1.5:
            score += 7
        elif vol_ratio > 1.2:
            score += 5
        
        if analysis['volatility_pct'] > 1.5:
            score += 5
        elif analysis['volatility_pct'] > 1.0:
            score += 3
        
        if score >= self.GRADE_CONFIGS['GOLD']['min_score']:
            grade = 'GOLD'
        elif score >= self.GRADE_CONFIGS['SILVER']['min_score']:
            grade = 'SILVER'
        elif score >= self.GRADE_CONFIGS['BRONZE']['min_score']:
            grade = 'BRONZE'
        else:
            grade = 'NONE'
        
        return score, grade, reasons
    
    def calculate_dynamic_stop_loss(self, grade, bb_width):
        """변동성 기반 동적 손절선 계산"""
        base_stop = self.GRADE_CONFIGS[grade]['base_stop_loss']
        
        if bb_width < 2.0:
            adjustment = 0.8
        elif bb_width < 3.0:
            adjustment = 1.0
        elif bb_width < 4.0:
            adjustment = 1.15
        elif bb_width < 5.0:
            adjustment = 1.3
        else:
            adjustment = 1.5
        
        dynamic_stop = base_stop * adjustment
        max_stop = -1.5
        dynamic_stop = max(dynamic_stop, max_stop)
        
        return dynamic_stop
    
    def find_best_opportunity(self, tickers):
        """최적 기회 탐색"""
        print(f"\n{'='*60}")
        print(f"🔍 {len(tickers)}개 종목 스캔")
        print(f"{'='*60}")
        
        market_crash, crash_msg = self.crash_detector.check_market_crash(tickers)
        if market_crash:
            print(f"🚨 {crash_msg}")
            return None
        
        candidates = []
        
        for idx, ticker in enumerate(tickers, 1):
            is_crash, crash_msg = self.crash_detector.check_crash(ticker)
            if is_crash:
                print(f"[{idx}/{len(tickers)}] {ticker}: ⚠️ {crash_msg}")
                time.sleep(TICKER_ANALYSIS_DELAY)
                continue
            
            analysis = self.analyze_opportunity(ticker)
            
            if not analysis['valid']:
                print(f"[{idx}/{len(tickers)}] {ticker}: ❌ 데이터 부족")
                time.sleep(TICKER_ANALYSIS_DELAY)
                continue
            
            score, grade, reasons = self.score_opportunity(analysis)
            
            if grade == 'NONE':
                print(f"[{idx}/{len(tickers)}] {ticker}: ⏭️  {score}점")
                time.sleep(TICKER_ANALYSIS_DELAY)
                continue
            
            is_good_timing = self.pattern_analyzer.is_good_entry_timing(
                ticker, analysis['current_price']
            )
            
            if not is_good_timing:
                score -= 15
                if score < self.GRADE_CONFIGS['BRONZE']['min_score']:
                    print(f"[{idx}/{len(tickers)}] {ticker}: ⏰ 타이밍 나쁨")
                    time.sleep(TICKER_ANALYSIS_DELAY)
                    continue
            
            dynamic_stop = self.calculate_dynamic_stop_loss(grade, analysis['bb_width'])
            
            grade_emoji = {'GOLD': '🥇', 'SILVER': '🥈', 'BRONZE': '🥉'}[grade]
            
            print(f"[{idx}/{len(tickers)}] {ticker}: {grade_emoji} {score}점 (손절:{dynamic_stop:.2f}%)")
            
            candidates.append({
                'ticker': ticker,
                'score': score,
                'grade': grade,
                'reasons': reasons,
                'analysis': analysis,
                'good_timing': is_good_timing,
                'dynamic_stop': dynamic_stop
            })
            
            time.sleep(TICKER_ANALYSIS_DELAY)
        
        print(f"{'='*60}")
        
        if not candidates:
            print("⏳ 적합한 기회 없음")
            return None
        
        best = max(candidates, key=lambda x: x['score'])
        
        grade_emoji = {'GOLD': '🥇', 'SILVER': '🥈', 'BRONZE': '🥉'}[best['grade']]
        
        print(f"\n{grade_emoji} 선정: {best['ticker']} [{best['grade']}]")
        print(f"   점수: {best['score']} | 손절: {best['dynamic_stop']:.2f}%")
        
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


def calculate_rsi(closes, period=14):
    """RSI"""
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
        return None
    
    multiplier = fortress.get_position_size_multiplier()
    buy_size = total_asset * 0.25 * multiplier
    max_krw = krw_balance * 0.995
    buy_size = min(buy_size, max_krw)
    
    if buy_size < MIN_ORDER:
        return None
    
    print(f"\n💰 매수 가능: {buy_size:,.0f}원")
    
    opportunity = hunter.find_best_opportunity(tickers)
    
    if opportunity is None:
        return None
    
    ticker = opportunity['ticker']
    grade = opportunity['grade']
    dynamic_stop = opportunity['dynamic_stop']
    
    try:
        current_price = api_limiter.call_api(pyupbit.get_current_price, ticker)
        
        if current_price is None:
            return None
        
        buy_order = upbit.buy_market_order(ticker, buy_size)
        
        print(f"\n✅ 매수: {ticker} | {buy_size:,.0f}원")
        
        grade_emoji = {'GOLD': '🥇', 'SILVER': '🥈', 'BRONZE': '🥉'}[grade]
        msg = f"{grade_emoji} 매수: {ticker} [{grade}]\n{buy_size:,.0f}원\n손절: {dynamic_stop:.2f}%"
        send_discord_message(msg)
        
        return {
            'ticker': ticker,
            'buy_price': current_price,
            'grade': grade,
            'config': hunter.GRADE_CONFIGS[grade],
            'dynamic_stop': dynamic_stop
        }
        
    except Exception as e:
        print(f"❌ 매수 실패: {e}")
        return None


# ═══════════════════════════════════════════════════════════
# 📉 매도 시스템
# ═══════════════════════════════════════════════════════════

def smart_sell_v3(buy_info, fortress):
    """v3.2 최적화된 매도 시스템"""
    
    ticker = buy_info['ticker']
    buy_price = buy_info['buy_price']
    grade = buy_info['grade']
    config = buy_info['config']
    dynamic_stop = buy_info['dynamic_stop']
    
    currency = ticker.split("-")[1]
    
    try:
        buyed_amount = get_balance(currency)
        if buyed_amount <= 0:
            return None
        
        avg_buy_price = upbit.get_avg_buy_price(currency)
    except:
        return None
    
    grade_emoji = {'GOLD': '🥇', 'SILVER': '🥈', 'BRONZE': '🥉'}[grade]
    
    print(f"\n📊 매도 감시: {ticker} [{grade}]")
    print(f"   목표: +{config['target_profit']}%")
    print(f"   🆕 동적 손절: {dynamic_stop:.2f}%")
    
    start_time = time.time()
    max_profit_rate = -999
    trailing_active = False
    
    ABSOLUTE_MAX_TIME = 3600
    check_interval = 1.5
    
    while True:
        try:
            elapsed = time.time() - start_time
            
            if elapsed >= ABSOLUTE_MAX_TIME:
                print(f"\n⏰ 1시간 강제매도")
                
                cur_price = api_limiter.call_api(pyupbit.get_current_price, ticker)
                if cur_price:
                    profit_rate = (cur_price - avg_buy_price) / avg_buy_price * 100
                    profit_krw = (cur_price - avg_buy_price) * buyed_amount
                    
                    sell_order = upbit.sell_market_order(ticker, buyed_amount)
                    fortress.record_trade(profit_krw, profit_rate, grade)
                    
                    msg = f"⏰ {grade_emoji} 1시간 강제매도\n{profit_krw:+,.0f}원"
                    send_discord_message(msg)
                    
                    return sell_order
            
            cur_price = api_limiter.call_api(pyupbit.get_current_price, ticker)
            if cur_price is None:
                time.sleep(2)
                continue
            
            profit_rate = (cur_price - avg_buy_price) / avg_buy_price * 100
            profit_krw = (cur_price - avg_buy_price) * buyed_amount
            
            if profit_rate > max_profit_rate:
                max_profit_rate = profit_rate
            
            minutes = int(elapsed / 60)
            seconds = int(elapsed % 60)
            print(f"[{minutes:02d}:{seconds:02d}] {profit_rate:+.2f}% (최고:{max_profit_rate:+.2f}%)", end="\r")
            
            # 1️⃣ 목표 달성
            if profit_rate >= config['target_profit']:
                sell_order = upbit.sell_market_order(ticker, buyed_amount)
                fortress.record_trade(profit_krw, profit_rate, grade)
                
                msg = f"✅ {grade_emoji} 목표달성!\n{profit_krw:+,.0f}원 ({profit_rate:+.2f}%)"
                print(f"\n{msg}")
                send_discord_message(msg)
                
                return sell_order
            
            # 2️⃣ 트레일링 스톱
            if profit_rate >= config['trailing_start']:
                if not trailing_active:
                    trailing_active = True
                    print(f"\n🛡️ 트레일링 활성화 (+{profit_rate:.2f}%)")
                
                trailing_stop_rate = max_profit_rate - config['trailing_gap']
                
                if profit_rate <= trailing_stop_rate:
                    sell_order = upbit.sell_market_order(ticker, buyed_amount)
                    fortress.record_trade(profit_krw, profit_rate, grade)
                    
                    msg = f"🛡️ {grade_emoji} 트레일링\n{profit_krw:+,.0f}원 ({profit_rate:+.2f}%)"
                    print(f"\n{msg}")
                    send_discord_message(msg)
                    
                    return sell_order
            
            # 3️⃣ 적응형 손절
            if profit_rate < 0:
                
                if elapsed < 300:
                    if profit_rate <= dynamic_stop:
                        sell_order = upbit.sell_market_order(ticker, buyed_amount)
                        fortress.record_trade(profit_krw, profit_rate, grade)
                        
                        msg = f"🚨 {grade_emoji} 손절\n{profit_krw:+,.0f}원 ({profit_rate:+.2f}%)"
                        print(f"\n{msg}")
                        send_discord_message(msg)
                        
                        return sell_order
                
                elif elapsed < 900:
                    relaxed_stop = dynamic_stop * 0.8
                    if profit_rate <= relaxed_stop:
                        sell_order = upbit.sell_market_order(ticker, buyed_amount)
                        fortress.record_trade(profit_krw, profit_rate, grade)
                        
                        msg = f"🚨 {grade_emoji} 손절(중반)\n{profit_krw:+,.0f}원"
                        print(f"\n{msg}")
                        send_discord_message(msg)
                        
                        return sell_order
                
                elif elapsed < 1800:
                    relaxed_stop = dynamic_stop * 0.5
                    if profit_rate <= relaxed_stop:
                        sell_order = upbit.sell_market_order(ticker, buyed_amount)
                        fortress.record_trade(profit_krw, profit_rate, grade)
                        
                        msg = f"🚨 {grade_emoji} 손절(후반)\n{profit_krw:+,.0f}원"
                        print(f"\n{msg}")
                        send_discord_message(msg)
                        
                        return sell_order
                
                elif elapsed < 3600:
                    relaxed_stop = dynamic_stop * 0.3
                    if profit_rate <= relaxed_stop:
                        sell_order = upbit.sell_market_order(ticker, buyed_amount)
                        fortress.record_trade(profit_krw, profit_rate, grade)
                        
                        msg = f"🚨 {grade_emoji} 손절(말기)\n{profit_krw:+,.0f}원"
                        print(f"\n{msg}")
                        send_discord_message(msg)
                        
                        return sell_order
            
            time.sleep(check_interval)
            
        except Exception as e:
            print(f"\n매도 루프 오류: {e}")
            
            if time.time() - start_time >= ABSOLUTE_MAX_TIME:
                try:
                    upbit.sell_market_order(ticker, buyed_amount)
                except:
                    pass
                return None
            
            time.sleep(3)


# ═══════════════════════════════════════════════════════════
# 📊 스마트 자산 리포터
# ═══════════════════════════════════════════════════════════

# 전역 변수 (함수 밖에 선언!)
profit_report_thread = None
profit_report_running = False


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
            print(f"{'='*60}")
            time.sleep(2)
            
            generate_smart_report(
                fortress, hunter, upbit_instance,
                is_startup=True
            )
            
            while profit_report_running:
                try:
                    now = datetime.now()
                    
                    if now.minute == 0 and now.second < 30:
                        print(f"\n[{now.strftime('%H:%M:%S')}] 정시 보고서 생성 중...")
                        
                        generate_smart_report(
                            fortress, hunter, upbit_instance,
                            is_startup=False
                        )
                        
                        time.sleep(3600)
                    else:
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
    print("✅ 스마트 리포터 스레드 시작됨")


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
        
        send_discord_message(msg)
        print(f"[{report_time.strftime('%H:%M:%S')}] 📊 스마트 보고서 전송 완료")
        
    except Exception as e:
        error_msg = f"❌ 스마트 보고서 오류\n{datetime.now().strftime('%H:%M:%S')}\n{str(e)}"
        print(error_msg)
        send_discord_message(error_msg)


def analyze_holding(ticker, current_price, hunter):
    """보유 코인 기술적 분석"""
    try:
        analysis = hunter.analyze_opportunity(ticker)
        
        if not analysis['valid']:
            return {
                'valid': False,
                'message': '데이터 부족'
            }
        
        score, grade, reasons = hunter.score_opportunity(analysis)
        outlook = predict_outlook(analysis, score, grade, current_price)
        dynamic_stop = hunter.calculate_dynamic_stop_loss(grade, analysis['bb_width'])
        
        return {
            'valid': True,
            'bb_pos': analysis['bb_pos'],
            'bb_width': analysis['bb_width'],
            'rsi': analysis['rsi'],
            'momentum': analysis['momentum'],
            'score': score,
            'grade': grade,
            'reasons': reasons,
            'outlook': outlook,
            'dynamic_stop': dynamic_stop
        }
    
    except Exception as e:
        return {
            'valid': False,
            'message': f'분석 실패: {str(e)}'
        }


def predict_outlook(analysis, score, grade, current_price):
    """향후 전망 예측"""
    bb_pos = analysis['bb_pos']
    rsi = analysis['rsi']
    momentum = analysis['momentum']
    bb_width = analysis['bb_width']
    
    # 추세 판단
    if bb_pos < 0.2 and rsi < 30:
        trend = "강한 상승 기대"
        trend_emoji = "🚀"
        confidence = "높음"
    elif bb_pos < 0.3 and rsi < 40:
        trend = "상승 기대"
        trend_emoji = "📈"
        confidence = "중상"
    elif bb_pos < 0.5 and rsi < 50:
        trend = "횡보 예상"
        trend_emoji = "➡️"
        confidence = "중간"
    elif bb_pos < 0.7 and rsi < 60:
        trend = "약세 우려"
        trend_emoji = "📉"
        confidence = "중하"
    else:
        trend = "하락 우려"
        trend_emoji = "🔻"
        confidence = "낮음"
    
    # 목표 수익률
    if grade == 'GOLD':
        base_target = 1.2
    elif grade == 'SILVER':
        base_target = 0.8
    elif grade == 'BRONZE':
        base_target = 0.5
    else:
        base_target = 0.3
    
    if bb_width > 4.0:
        target_rate = base_target * 1.3
    elif bb_width > 3.0:
        target_rate = base_target * 1.1
    else:
        target_rate = base_target
    
    target_price = current_price * (1 + target_rate / 100)
    
    # 추천 액션
    if bb_pos < 0.25 and rsi < 35 and momentum > 0:
        action = "HOLD 🔒"
        action_reason = "매수 적기 - 상승 대기"
    elif bb_pos < 0.4 and rsi < 45:
        action = "HOLD 👀"
        action_reason = "관찰 - 반등 가능"
    elif bb_pos > 0.7 and rsi > 60:
        action = "EXIT 🚪"
        action_reason = "고점 근처 - 매도 고려"
    elif bb_pos > 0.6 and rsi > 55:
        action = "CAUTION ⚠️"
        action_reason = "주의 - 조정 가능"
    else:
        action = "WATCH 👁️"
        action_reason = "중립 - 추세 관찰"
    
    # 변동성
    if bb_width > 5.0:
        volatility = "극심"
    elif bb_width > 4.0:
        volatility = "높음"
    elif bb_width > 3.0:
        volatility = "보통"
    elif bb_width > 2.0:
        volatility = "낮음"
    else:
        volatility = "매우낮음"
    
    return {
        'trend': trend,
        'trend_emoji': trend_emoji,
        'confidence': confidence,
        'target_rate': target_rate,
        'target_price': target_price,
        'action': action,
        'action_reason': action_reason,
        'volatility': volatility
    }


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
        profit_emoji = "🔥" if h['profit_rate'] > 5 else "📈" if h['profit_rate'] > 0 else "📉"
        
        msg += f"\n{i}. {h['name']} {profit_emoji}\n"
        msg += f"   💵 {h['profit_rate']:+6.2f}% | 평가 {h['eval_value']:,.0f}원 | 순익 {h['net_profit']:+,.0f}원\n"
        
        analysis = h['analysis']
        
        if analysis['valid']:
            grade_emoji = {'GOLD': '🥇', 'SILVER': '🥈', 'BRONZE': '🥉', 'NONE': '⚪'}
            grade_icon = grade_emoji.get(analysis['grade'], '⚪')
            
            msg += f"   {grade_icon} {analysis['grade']} {analysis['score']}점"
            msg += f" | BB:{analysis['bb_pos']*100:.0f}% RSI:{analysis['rsi']:.0f}\n"
            
            outlook = analysis['outlook']
            msg += f"   {outlook['trend_emoji']} {outlook['trend']} (신뢰:{outlook['confidence']})\n"
            msg += f"   🎯 목표: +{outlook['target_rate']:.1f}% ({outlook['target_price']:,.0f}원)\n"
            msg += f"   📌 {outlook['action']} - {outlook['action_reason']}\n"
            msg += f"   📊 변동성: {outlook['volatility']} (BB폭:{analysis['bb_width']:.1f}%)\n"
        else:
            msg += f"   ⚠️ 분석 불가: {analysis.get('message', '알 수 없음')}\n"
    
    msg += "\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    
    return msg


# ═══════════════════════════════════════════════════════════
# 🎮 메인 실행
# ═══════════════════════════════════════════════════════════

def main():
    """메인"""
    
    print("="*60)
    print("🏰 Fortress Hunter v3.2 Final 시작")
    print("="*60)
    print("개선: 손절선 최적화 + 스마트 리포터")
    print(f"목표: 100만원 → 10억원")
    print("="*60 + "\n")
    
    fortress = FortressProtection(initial_capital=1_000_000)
    hunter = SmartThreeStageHunter()
    
    # 🆕 스마트 리포터 시작
    start_smart_reporter(fortress, hunter, upbit)
    
    msg = f"🏰 v3.2 시작\n현재: {fortress.current_asset:,.0f}원"
    send_discord_message(msg)
    
    while True:
        try:
            if fortress.current_asset >= 1_000_000_000:
                msg = f"🎉 목표 달성!\n{fortress.current_asset:,.0f}원"
                print(f"\n{'='*60}\n{msg}\n{'='*60}")
                send_discord_message(msg)
                storage.backup_manually()
                break
            
            buy_info = smart_buy(fortress, hunter, STRATEGIC_COINS)
            
            if buy_info:
                time.sleep(2)
                
                smart_sell_v3(buy_info, fortress)
                
                print("\n⏳ 10초 대기...\n")
                time.sleep(10)
            else:
                print("⏳ 20초 대기...\n")
                time.sleep(20)
            
        except KeyboardInterrupt:
            print("\n프로그램 종료...")
            storage.backup_manually()
            break
        
        except Exception as e:
            print(f"메인 루프 오류: {e}")
            send_discord_message(f"❌ 오류: {e}")
            fortress.save_state()
            time.sleep(30)
    
    print("\n🏰 Fortress Hunter 종료")


if __name__ == "__main__":
    main()