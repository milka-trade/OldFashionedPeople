"""
🏰 Fortress Hunter v2.2 - 100만원 → 10억원 자동매매 시스템

수정사항:
- API 호출 간격 대폭 증가 (안정성 우선)
- 고정 8개 종목 유지
- 상세한 디버그 정보
"""

import time
import pyupbit
import numpy as np
from datetime import datetime, timedelta
import os
from dotenv import load_dotenv
import requests
import json
import shutil
from collections import deque
from threading import Lock
import tempfile

load_dotenv()

# ═══════════════════════════════════════════════════════════
# 🔧 환경 설정
# ═══════════════════════════════════════════════════════════

DISCORD_WEBHOOK_URL = os.getenv("discord_webhhok")
upbit = pyupbit.Upbit(os.getenv("UPBIT_ACCESS"), os.getenv("UPBIT_SECRET"))

# 🎯 고정 종목 (절대 변경 금지!)
STRATEGIC_COINS = [
    "KRW-BTC", "KRW-ETH", "KRW-XRP", "KRW-SOL",
    "KRW-ADA", "KRW-LINK", "KRW-BCH", "KRW-XLM"
]

# API 호출 간격 (초)
API_CALL_DELAY = 0.6  # 각 API 호출 후 0.6초 대기
TICKER_ANALYSIS_DELAY = 1.2  # 각 종목 분석 후 1.2초 대기


# ═══════════════════════════════════════════════════════════
# 📨 디스코드 알림 시스템
# ═══════════════════════════════════════════════════════════

def send_discord_message(msg):
    """디스코드 메시지 전송 (재시도 로직)"""
    if not DISCORD_WEBHOOK_URL:
        return False
    
    for attempt in range(3):
        try:
            message = {"content": msg}
            response = requests.post(
                DISCORD_WEBHOOK_URL,
                data=message,
                timeout=5
            )
            
            if response.status_code == 204:
                return True
                
        except Exception as e:
            if attempt < 2:
                time.sleep(2)
    
    return False


# ═══════════════════════════════════════════════════════════
# 💾 안전한 JSON 저장 시스템
# ═══════════════════════════════════════════════════════════

class SafeJSONStorage:
    """안전한 JSON 저장 시스템"""
    
    def __init__(self, filepath='fortress_state.json'):
        self.filepath = filepath
        self.backup_path = filepath + '.backup'
        self.lock = Lock()
    
    def save(self, data):
        """안전한 저장 (원자적 쓰기)"""
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
        """안전한 로드 (손상 시 자동 복구)"""
        with self.lock:
            if os.path.exists(self.filepath):
                try:
                    with open(self.filepath, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                    
                    if self._validate(data):
                        return data
                    else:
                        print("⚠️ 메인 파일 손상 - 백업 시도")
                        
                except Exception as e:
                    print(f"⚠️ 메인 파일 로드 실패: {e}")
            
            if os.path.exists(self.backup_path):
                try:
                    with open(self.backup_path, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                    
                    if self._validate(data):
                        print("✅ 백업 파일에서 복구 성공")
                        shutil.copy2(self.backup_path, self.filepath)
                        return data
                        
                except Exception as e:
                    print(f"⚠️ 백업 파일 로드 실패: {e}")
            
            print("📊 저장된 데이터 없음 - 초기화")
            return None
    
    def _validate(self, data):
        """데이터 유효성 검증"""
        if not isinstance(data, dict):
            return False
        
        required_fields = ['initial', 'current_asset', 'peak_asset', 'total_trades', 'win_trades']
        
        for field in required_fields:
            if field not in data:
                return False
        
        if not isinstance(data['total_trades'], int):
            return False
        
        if not isinstance(data['current_asset'], (int, float)):
            return False
        
        return True
    
    def backup_manually(self, backup_name=None):
        """수동 백업 생성"""
        if not os.path.exists(self.filepath):
            return False
        
        try:
            if backup_name is None:
                timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
                backup_name = f"{self.filepath}.{timestamp}.backup"
            
            shutil.copy2(self.filepath, backup_name)
            print(f"✅ 수동 백업 완료: {backup_name}")
            return True
            
        except Exception as e:
            print(f"❌ 백업 실패: {e}")
            return False


# ═══════════════════════════════════════════════════════════
# ⏱️ 개선된 API 호출 관리 시스템
# ═══════════════════════════════════════════════════════════

class APIRateLimiter:
    """
    개선된 API 호출 제한 관리 시스템
    
    변경사항:
    - 호출 간격 증가
    - 상세한 에러 로그
    - 재시도 로직 강화
    """
    
    def __init__(self, max_per_second=6, max_per_minute=60):
        self.max_per_second = max_per_second  # 초당 6회로 감소
        self.max_per_minute = max_per_minute  # 분당 60회로 감소
        self.calls = deque()
        self.lock = Lock()
    
    def wait_if_needed(self):
        """필요 시 대기 (더 보수적)"""
        with self.lock:
            now = time.time()
            
            # 1분 이상 된 기록 제거
            while self.calls and now - self.calls[0] > 60:
                self.calls.popleft()
            
            # 초당 제한 확인
            recent_calls = [t for t in self.calls if now - t < 1.0]
            
            if len(recent_calls) >= self.max_per_second:
                wait_time = 1.0 - (now - recent_calls[0]) + 0.2  # 여유 0.2초 추가
                if wait_time > 0:
                    time.sleep(wait_time)
                    now = time.time()
            
            # 분당 제한 확인
            if len(self.calls) >= self.max_per_minute:
                wait_time = 60 - (now - self.calls[0]) + 1.0  # 여유 1초 추가
                if wait_time > 0:
                    print(f"⏳ API 분당 제한 대기: {wait_time:.1f}초")
                    time.sleep(wait_time)
                    now = time.time()
            
            # 호출 기록
            self.calls.append(now)
    
    def call_api(self, func, *args, max_retries=3, **kwargs):
        """
        안전한 API 호출 (상세한 디버그)
        """
        func_name = func.__name__
        ticker_info = ""
        
        # 티커 정보 추출 (디버깅용)
        if args:
            if isinstance(args[0], str) and 'KRW' in args[0]:
                ticker_info = f"[{args[0]}]"
        
        for attempt in range(max_retries):
            try:
                # 제한 확인 및 대기
                self.wait_if_needed()
                
                # 추가 안전 대기
                time.sleep(API_CALL_DELAY)
                
                # API 호출
                result = func(*args, **kwargs)
                
                # 성공 로그 (첫 번째 시도만)
                if attempt == 0:
                    print(f"   ✓ {func_name} {ticker_info}")
                
                return result
                
            except Exception as e:
                error_msg = str(e)
                
                # 상세한 에러 로그
                # print(f"   ⚠️ {func_name} {ticker_info} 실패 (시도 {attempt+1}/{max_retries}): {error_msg}")
                
                # Code not found는 재시도 불필요
                if "code not found" in error_msg.lower():
                    # print(f"   ❌ {ticker_info} 존재하지 않는 코인 - 건너뜀")
                    return None
                
                # 재시도
                if attempt < max_retries - 1:
                    wait = (2 ** attempt) + 1  # 지수 백오프 + 여유
                    print(f"   ⏳ {wait}초 후 재시도...")
                    time.sleep(wait)
                else:
                    print(f"   ❌ {func_name} {ticker_info} 최종 실패")
                    return None
        
        return None


# 전역 인스턴스
api_limiter = APIRateLimiter()
storage = SafeJSONStorage()


# ═══════════════════════════════════════════════════════════
# 🏰 Fortress Protection System
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
            
            print("✅ 이전 상태 복구 완료")
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
            'updated_at': datetime.now().isoformat()
        }
        
        return storage.save(state)
    
    def update_daily_reset(self):
        """날짜 변경 시 초기화"""
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
        
        max_daily_loss = max(total_profit * 0.02, self.initial * 0.01)
        
        if self.daily_loss >= max_daily_loss:
            return False, f"일일 손실 한도 ({self.daily_loss:,.0f}원)"
        
        if self.consecutive_loss >= 2:
            return False, f"연속 손실 {self.consecutive_loss}회"
        
        if self.current_asset < self.initial * 0.90:
            return False, f"자산 하락 한계 ({self.current_asset:,.0f}원)"
        
        return True, "OK"
    
    def record_trade(self, profit_krw, profit_rate):
        """거래 결과 기록"""
        self.update_daily_reset()
        
        self.total_trades += 1
        
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
        self.print_trade_result(profit_krw, profit_rate)
    
    def print_trade_result(self, profit_krw, profit_rate):
        """거래 결과 출력"""
        win_rate = (self.win_trades / self.total_trades * 100) if self.total_trades > 0 else 0
        
        print(f"\n{'='*60}")
        print(f"📊 거래 #{self.total_trades}")
        print(f"{'='*60}")
        print(f"손익: {profit_krw:+,.0f}원 ({profit_rate:+.2f}%)")
        print(f"현재 자산: {self.current_asset:,.0f}원")
        print(f"누적 수익: {self.total_profit:+,.0f}원 ({(self.current_asset/self.initial-1)*100:+.2f}%)")
        print(f"승률: {win_rate:.1f}% ({self.win_trades}/{self.total_trades})")
        print(f"오늘 수익: {self.daily_profit:+,.0f}원 | 손실: {self.daily_loss:,.0f}원")
        print(f"연속 손실: {self.consecutive_loss}회")
        print(f"{'='*60}\n")
        
        msg = f"📊 거래 #{self.total_trades}\n"
        msg += f"손익: {profit_krw:+,.0f}원 ({profit_rate:+.2f}%)\n"
        msg += f"자산: {self.current_asset:,.0f}원 (누적: {self.total_profit:+,.0f}원)\n"
        msg += f"승률: {win_rate:.1f}%"
        send_discord_message(msg)
    
    def print_status(self):
        """현재 상태 출력"""
        win_rate = (self.win_trades / self.total_trades * 100) if self.total_trades > 0 else 0
        
        print(f"\n{'='*60}")
        print(f"📊 Fortress 현황")
        print(f"{'='*60}")
        print(f"초기 자본: {self.initial:,.0f}원")
        print(f"현재 자산: {self.current_asset:,.0f}원")
        print(f"누적 수익: {self.total_profit:+,.0f}원 ({(self.current_asset/self.initial-1)*100:+.2f}%)")
        print(f"총 거래: {self.total_trades}회 (승률: {win_rate:.1f}%)")
        print(f"목표까지: {1_000_000_000 - self.current_asset:,.0f}원")
        print(f"{'='*60}\n")
    
    def get_position_size_multiplier(self):
        """포지션 배율"""
        profit_rate = (self.current_asset / self.initial - 1) * 100
        
        if profit_rate < 0:
            return 0.5
        elif profit_rate < 50:
            return 1.0
        elif profit_rate < 200:
            return 1.2
        else:
            return 1.5


# ═══════════════════════════════════════════════════════════
# 🎯 1% Hunter System
# ═══════════════════════════════════════════════════════════

class OnePercentHunter:
    """1% 수익 전문 포착 시스템"""
    
    TARGET_PROFIT = 0.99
    MAX_HOLD_TIME = 300
    
    @staticmethod
    def analyze_1min_momentum(ticker):
        """
        1분봉 분석 (천천히)
        """
        try:
            # print(f"\n   🔍 {ticker} 분석 시작...")
            
            # API 호출
            df = api_limiter.call_api(
                pyupbit.get_ohlcv,
                ticker,
                interval="minute1",
                count=30
            )
            
            if df is None or len(df) < 20:
                print(f"   ❌ {ticker} 데이터 부족")
                return {'valid': False}
            
            closes = df['close'].values
            volumes = df['volume'].values
            highs = df['high'].values
            lows = df['low'].values
            current_price = closes[-1]
            
            # 지표 계산
            bb_lower, bb_mid, bb_upper, bb_pos, bb_width = calculate_bb(closes, 20)
            rsi = calculate_rsi(closes, 14)
            
            recent_avg = np.mean(closes[-3:])
            prev_avg = np.mean(closes[-8:-3])
            momentum = (recent_avg - prev_avg) / prev_avg * 100
            
            vol_recent = np.mean(volumes[-3:])
            vol_normal = np.mean(volumes[-10:-3])
            vol_ratio = vol_recent / (vol_normal + 1e-8)
            
            recent_range = np.mean(highs[-5:] - lows[-5:])
            volatility_pct = (recent_range / current_price) * 100
            
            potential_1pct = bb_width * 0.4
            can_reach_1pct = potential_1pct >= 1.0
            
            # print(f"   ✅ {ticker} 분석 완료 (BB:{bb_pos*100:.0f}% RSI:{rsi:.0f})")
            
            return {
                'valid': True,
                'current_price': current_price,
                'bb_pos': bb_pos,
                'bb_width': bb_width,
                'rsi': rsi,
                'momentum': momentum,
                'vol_ratio': vol_ratio,
                'volatility_pct': volatility_pct,
                'potential_1pct': potential_1pct,
                'can_reach_1pct': can_reach_1pct
            }
            
        except Exception as e:
            print(f"   ❌ {ticker} 분석 실패: {e}")
            return {'valid': False}
    
    @staticmethod
    def is_perfect_entry(analysis):
        """완벽한 진입점 판별"""
        if not analysis['valid']:
            return False, 0, "데이터 없음"
        
        score = 0
        reasons = []
        
        bb_pos = analysis['bb_pos']
        
        if bb_pos < 0.15:
            score += 40
            reasons.append("BB극하단")
        elif bb_pos < 0.25:
            score += 30
            reasons.append("BB하단")
        elif bb_pos < 0.35:
            score += 20
        else:
            return False, score, "BB 높음"
        
        rsi = analysis['rsi']
        
        if rsi < 25:
            score += 30
            reasons.append("RSI극과매도")
        elif rsi < 30:
            score += 24
            reasons.append("RSI과매도")
        elif rsi < 35:
            score += 18
        else:
            return False, score, "RSI 높음"
        
        if analysis['can_reach_1pct']:
            score += 20
            reasons.append("1%도달")
        elif analysis['potential_1pct'] >= 0.7:
            score += 10
        
        momentum = analysis['momentum']
        
        if momentum > 0.1:
            score += 10
            reasons.append("반등")
        elif momentum > 0:
            score += 5
        
        if score < 85:
            return False, score, f"점수 부족 ({score}점)"
        
        reason_str = "+".join(reasons)
        return True, score, reason_str


# ═══════════════════════════════════════════════════════════
# 🛡️ Zero-Cut Zone
# ═══════════════════════════════════════════════════════════

def is_zero_cut_zone(ticker):
    """무손절 구역 판별"""
    try:
        df = api_limiter.call_api(
            pyupbit.get_ohlcv,
            ticker,
            interval="minute5",
            count=50
        )
        
        if df is None or len(df) < 20:
            return False, None
        
        closes = df['close'].values
        
        _, _, _, bb_pos, bb_width = calculate_bb(closes, 20)
        rsi = calculate_rsi(closes, 14)
        
        if bb_pos < 0.15 and rsi < 20 and bb_width > 3.0:
            reason = f"🛡️ 무손절구역 (BB:{bb_pos*100:.0f}% RSI:{rsi:.0f})"
            return True, reason
        
        elif bb_pos < 0.20 and rsi < 25:
            reason = f"⚠️ 손절 주의 (BB:{bb_pos*100:.0f}% RSI:{rsi:.0f})"
            return False, reason
        
        return False, None
        
    except Exception as e:
        return False, None


# ═══════════════════════════════════════════════════════════
# 💰 유틸리티 함수들
# ═══════════════════════════════════════════════════════════

def get_krw_balance(upbit):
    """KRW 잔고 조회"""
    for attempt in range(3):
        try:
            balances = upbit.get_balances()
            for b in balances:
                if b['currency'] == "KRW":
                    return float(b['balance'])
        except Exception as e:
            if attempt < 2:
                time.sleep(2)
    return 0.0


def get_balance(ticker):
    """코인 잔고 조회"""
    for attempt in range(3):
        try:
            balances = upbit.get_balances()
            for b in balances:
                if b['currency'] == ticker:
                    return float(b['balance']) if b['balance'] is not None else 0
        except Exception as e:
            if attempt < 2:
                time.sleep(2)
    return 0


def get_total_crypto_value(upbit):
    """암호화폐 총 평가액"""
    try:
        balances = upbit.get_balances()
        total = 0.0
        
        for balance in balances:
            if balance['currency'] == 'KRW':
                continue
            
            amount = float(balance['balance'])
            if amount > 0:
                ticker_name = f"KRW-{balance['currency']}"
                
                price = api_limiter.call_api(
                    pyupbit.get_current_price,
                    ticker_name
                )
                
                if price:
                    total += amount * price
        
        return total
    except Exception as e:
        print(f"평가액 조회 실패: {e}")
        return 0.0


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
        avg_gain = (avg_gain * (period-1) + gains[i]) / period
        avg_loss = (avg_loss * (period-1) + losses[i]) / period
    
    rs = avg_gain / (avg_loss + 1e-8)
    return 100 - (100 / (1 + rs))


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


# ═══════════════════════════════════════════════════════════
# 🚀 매수 시스템
# ═══════════════════════════════════════════════════════════

def fortress_hunter_buy(fortress, hunter, tickers):
    """
    Fortress Hunter 매수 시스템 (천천히)
    """
    
    can_trade, reason = fortress.can_trade()
    
    if not can_trade:
        print(f"❌ 거래 불가: {reason}")
        return reason, None
    
    krw_balance = get_krw_balance(upbit)
    crypto_value = get_total_crypto_value(upbit)
    total_asset = krw_balance + crypto_value
    
    fortress.current_asset = total_asset
    
    MIN_ORDER = 5000
    
    if krw_balance < MIN_ORDER:
        return "잔고 부족", None
    
    multiplier = fortress.get_position_size_multiplier()
    buy_size = total_asset * 0.25 * multiplier
    max_krw = krw_balance * 0.995
    buy_size = min(buy_size, max_krw)
    
    if buy_size < MIN_ORDER:
        return "매수액 부족", None
    
    print(f"\n💰 매수 가능: {buy_size:,.0f}원 (배율: {multiplier:.1f}x)")
    
    best_candidate = None
    best_score = 0
    
    print(f"\n{'='*60}")
    print(f"🔍 종목 분석 시작 ({len(tickers)}개)")
    print(f"{'='*60}")
    
    for idx, ticker in enumerate(tickers, 1):
        # print(f"\n[{idx}/{len(tickers)}] {ticker} 분석 중...")
        
        # 🆕 각 종목 분석 후 충분한 대기
        analysis = hunter.analyze_1min_momentum(ticker)
        
        if not analysis['valid']:
            print(f"   ⏭️ {ticker} 건너뜀")
            time.sleep(TICKER_ANALYSIS_DELAY)
            continue
        
        is_perfect, score, reason = hunter.is_perfect_entry(analysis)
        
        if is_perfect:
            print(f"   🎯 매수 후보! 점수: {score}점 ({reason})")
            
            if score > best_score:
                best_score = score
                best_candidate = {
                    'ticker': ticker,
                    'score': score,
                    'reason': reason,
                    'analysis': analysis
                }
        else:
            print(f"   ❌ 조건 미충족: {reason}")
        
        # 🆕 각 종목 분석 후 대기
        time.sleep(TICKER_ANALYSIS_DELAY)
    
    print(f"\n{'='*60}")
    
    if best_candidate is None:
        print("⏳ 조건 충족 종목 없음")
        return "조건 충족 없음", None
    
    selected = best_candidate
    ticker = selected['ticker']
    analysis = selected['analysis']
    
    print(f"\n🎯 최종 선정: {ticker} ({selected['score']}점)")
    print(f"   이유: {selected['reason']}")
    print(f"   BB: {analysis['bb_pos']*100:.0f}% | RSI: {analysis['rsi']:.0f}")
    
    try:
        current_price = api_limiter.call_api(
            pyupbit.get_current_price, ticker
        )
        
        if current_price is None:
            return "가격 조회 실패", None
        
        buy_order = upbit.buy_market_order(ticker, buy_size)
        
        print(f"✅ 매수 완료: {ticker} | {buy_size:,.0f}원 @ {current_price:,.0f}원")
        
        msg = f"🎯 매수: {ticker}\n"
        msg += f"금액: {buy_size:,.0f}원 | 가격: {current_price:,.0f}원\n"
        msg += f"점수: {selected['score']}점 | {selected['reason']}"
        send_discord_message(msg)
        
        return buy_order, current_price
        
    except Exception as e:
        print(f"❌ 매수 실패: {e}")
        send_discord_message(f"❌ 매수 실패: {ticker} - {e}")
        return "매수 실행 실패", None


# ═══════════════════════════════════════════════════════════
# 📉 매도 시스템
# ═══════════════════════════════════════════════════════════

def fortress_hunter_sell(ticker, buy_price, fortress, hunter):
    """Fortress Hunter 매도 시스템"""
    
    currency = ticker.split("-")[1]
    
    try:
        buyed_amount = get_balance(currency)
        
        if buyed_amount <= 0:
            return None
        
        avg_buy_price = upbit.get_avg_buy_price(currency)
        
    except Exception as e:
        print(f"매도 준비 실패: {e}")
        return None
    
    print(f"\n📊 매도 감시 시작: {ticker} (매수가: {avg_buy_price:,.0f}원)")
    
    start_time = time.time()
    STAGE_1_TIME = 300
    STAGE_2_TIME = 600
    ABSOLUTE_MAX = 1800
    
    check_interval = 2  # 🆕 체크 간격 2초로 증가
    max_profit = 0
    in_safe_zone_since = None
    
    while True:
        try:
            elapsed = time.time() - start_time
            
            if elapsed >= ABSOLUTE_MAX:
                print(f"\n⏰ 절대 최대 시간 초과 (30분) - 강제 매도")
                
                cur_price = api_limiter.call_api(
                    pyupbit.get_current_price, ticker
                )
                
                if cur_price:
                    profit_rate = (cur_price - avg_buy_price) / avg_buy_price * 100
                    profit_krw = (cur_price - avg_buy_price) * buyed_amount
                    
                    sell_order = upbit.sell_market_order(ticker, buyed_amount)
                    fortress.record_trade(profit_krw, profit_rate)
                    
                    msg = f"🚨 [강제매도] {ticker}\n"
                    msg += f"손익: {profit_krw:+,.0f}원 ({profit_rate:+.2f}%)"
                    
                    print(f"\n{msg}")
                    send_discord_message(msg)
                    
                    return sell_order
            
            cur_price = api_limiter.call_api(
                pyupbit.get_current_price, ticker
            )
            
            if cur_price is None:
                time.sleep(3)
                continue
            
            profit_rate = (cur_price - avg_buy_price) / avg_buy_price * 100
            profit_krw = (cur_price - avg_buy_price) * buyed_amount
            
            if profit_rate > max_profit:
                max_profit = profit_rate
            
            print(f"[{elapsed:.0f}s] {ticker} | {profit_rate:+.2f}% (최고:{max_profit:+.2f}%)", end="\r")
            
            if profit_rate >= hunter.TARGET_PROFIT:
                sell_order = upbit.sell_market_order(ticker, buyed_amount)
                fortress.record_trade(profit_krw, profit_rate)
                
                msg = f"✅ [목표달성] {ticker}\n"
                msg += f"수익: {profit_krw:+,.0f}원 ({profit_rate:+.2f}%)\n"
                msg += f"보유: {elapsed:.0f}초"
                
                print(f"\n{msg}")
                send_discord_message(msg)
                
                return sell_order
            
            if profit_rate < -1.5:
                is_safe_zone, zone_reason = is_zero_cut_zone(ticker)
                
                if elapsed < STAGE_1_TIME:
                    if is_safe_zone:
                        if in_safe_zone_since is None:
                            in_safe_zone_since = time.time()
                        
                        print(f"\n{zone_reason} - 대기 중")
                        time.sleep(5)
                        continue
                    else:
                        sell_order = upbit.sell_market_order(ticker, buyed_amount)
                        fortress.record_trade(profit_krw, profit_rate)
                        
                        msg = f"🚨 [손절] {ticker}\n"
                        msg += f"손실: {profit_krw:+,.0f}원 ({profit_rate:+.2f}%)"
                        
                        print(f"\n{msg}")
                        send_discord_message(msg)
                        
                        return sell_order
                
                elif elapsed < STAGE_2_TIME:
                    if is_safe_zone:
                        if in_safe_zone_since:
                            safe_zone_duration = time.time() - in_safe_zone_since
                            
                            if safe_zone_duration < 600:
                                print(f"\n{zone_reason} - 추가 대기")
                                time.sleep(5)
                                continue
                    
                    sell_order = upbit.sell_market_order(ticker, buyed_amount)
                    fortress.record_trade(profit_krw, profit_rate)
                    
                    msg = f"🚨 [손절-STAGE2] {ticker}\n"
                    msg += f"손실: {profit_krw:+,.0f}원 ({profit_rate:+.2f}%)"
                    
                    print(f"\n{msg}")
                    send_discord_message(msg)
                    
                    return sell_order
                
                else:
                    if profit_rate > -3.0:
                        sell_order = upbit.sell_market_order(ticker, buyed_amount)
                        fortress.record_trade(profit_krw, profit_rate)
                        
                        msg = f"🚨 [손절-STAGE3] {ticker}\n"
                        msg += f"손실: {profit_krw:+,.0f}원 ({profit_rate:+.2f}%)"
                        
                        print(f"\n{msg}")
                        send_discord_message(msg)
                        
                        return sell_order
            
            if elapsed >= STAGE_1_TIME and profit_rate > 0:
                sell_order = upbit.sell_market_order(ticker, buyed_amount)
                fortress.record_trade(profit_krw, profit_rate)
                
                msg = f"⏰ [시간초과] {ticker}\n"
                msg += f"수익: {profit_krw:+,.0f}원 ({profit_rate:+.2f}%)"
                
                print(f"\n{msg}")
                send_discord_message(msg)
                
                return sell_order
            
            time.sleep(check_interval)
            
        except Exception as e:
            print(f"\n매도 루프 오류: {e}")
            
            if time.time() - start_time >= ABSOLUTE_MAX:
                try:
                    upbit.sell_market_order(ticker, buyed_amount)
                except:
                    pass
                return None
            
            time.sleep(5)


# ═══════════════════════════════════════════════════════════
# 🎮 메인 실행
# ═══════════════════════════════════════════════════════════

def main_fortress_hunter():
    """Fortress Hunter 메인 실행"""
    
    print("="*60)
    print("🏰 Fortress Hunter v2.2 시작")
    print("="*60)
    print("목표: 100만원 → 10억원 (697회 1% 복리)")
    print(f"고정 종목: {', '.join(STRATEGIC_COINS)}")
    print(f"API 호출 간격: {API_CALL_DELAY}초")
    print(f"종목 분석 간격: {TICKER_ANALYSIS_DELAY}초")
    print("="*60 + "\n")
    
    fortress = FortressProtection(initial_capital=1_000_000)
    hunter = OnePercentHunter()
    
    msg = f"🏰 Fortress Hunter 시작\n"
    msg += f"목표: 10억원\n"
    msg += f"현재: {fortress.current_asset:,.0f}원\n"
    msg += f"코인: {len(STRATEGIC_COINS)}개"
    send_discord_message(msg)
    
    while True:
        try:
            if fortress.current_asset >= 1_000_000_000:
                msg = f"🎉 목표 달성!\n"
                msg += f"최종: {fortress.current_asset:,.0f}원\n"
                msg += f"거래: {fortress.total_trades}회\n"
                msg += f"승률: {fortress.win_trades/fortress.total_trades*100:.1f}%"
                
                print(f"\n{'='*60}")
                print(msg)
                print("="*60)
                
                send_discord_message(msg)
                storage.backup_manually()
                break
            
            result = fortress_hunter_buy(fortress, hunter, STRATEGIC_COINS)
            
            if result and isinstance(result, tuple):
                buy_order, buy_price = result
                ticker = None
                
                time.sleep(3)
                
                balances = upbit.get_balances()
                for b in balances:
                    if b['currency'] in ['KRW', 'QI', 'ONX', 'ETHF', 'ETHW', 'PURSE']:
                        continue
                    
                    balance = float(b.get('balance', 0))
                    if balance > 0:
                        ticker = f"KRW-{b['currency']}"
                        break
                
                if ticker:
                    fortress_hunter_sell(ticker, buy_price, fortress, hunter)
                    print("\n⏳ 다음 거래까지 15초 대기...\n")
                    time.sleep(15)
                else:
                    print("⚠️ 매수 코인 확인 실패")
                    time.sleep(5)
            
            else:
                reason = result[0] if isinstance(result, tuple) else result
                
                if "조건 충족 없음" in reason:
                    wait_time = 30
                elif "거래 불가" in reason:
                    wait_time = 300
                elif "잔고 부족" in reason:
                    wait_time = 60
                else:
                    wait_time = 20
                
                print(f"⏳ {wait_time}초 대기 후 재시도...\n")
                time.sleep(wait_time)
            
        except KeyboardInterrupt:
            print("\n프로그램 종료 요청...")
            storage.backup_manually()
            break
        
        except Exception as e:
            print(f"메인 루프 오류: {e}")
            send_discord_message(f"❌ 메인 루프 오류: {e}")
            fortress.save_state()
            time.sleep(30)
    
    print("\n🏰 Fortress Hunter 종료")


# ═══════════════════════════════════════════════════════════
# 🚀 프로그램 시작
# ═══════════════════════════════════════════════════════════

if __name__ == "__main__":
    main_fortress_hunter()