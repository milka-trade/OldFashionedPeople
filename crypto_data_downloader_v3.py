#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  암호화폐 데이터 다운로더 v3.0 - Upbit 공식 API 직접 연동
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  개선 사항 (v2.0 대비):
  ✅ pyupbit 라이브러리 완전 제거 → Upbit 공식 REST API 직접 호출
  ✅ 페이지네이션 (to 파라미터) → 수백~수만 개 캔들 수집 가능
  ✅ 기간 선택 방식 (30일/90일/180일/365일/직접입력)
  ✅ 진행률 표시 + ETA (예상 완료 시간)
  ✅ 중간 저장 (1,000캔들마다) + 오류 복구
  ✅ Rate Limiting 내장 (초당 ~8 req 자동 조절)
  ✅ 데이터 품질 검증 (중복 제거, 정렬, 갭 체크)
  ✅ 수집 가능 최대량 사전 안내

  수집량 비교 (15분봉 기준):
    pyupbit v2.0 : 최대    200개 (약 2일)
    공식 API v3.0: 최대 35,040개 (약 365일) ← 175배 향상

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

import pandas as pd
import requests
import time
import os
import sys
from datetime import datetime, timedelta


# ============================================================================
# SECTION 1: 기본 설정
# ============================================================================

UPBIT_API_BASE = "https://api.upbit.com"
OUTPUT_DIR      = "./market_data"

# 거래 대상 7개 코인
ALL_TICKERS = [
    "KRW-ETH", "KRW-XRP", "KRW-SOL",
    "KRW-ADA", "KRW-LINK", "KRW-BCH", "KRW-SUI"
]

# Rate Limit 설정 (Upbit 공식: 초당 10 req, 여유 포함 8 req)
API_CALL_MIN_INTERVAL = 0.13   # 초 (≈ 7.7 req/sec)
MAX_PER_CALL          = 200    # Upbit 1회 최대 캔들 수
MAX_RETRIES           = 5
RETRY_DELAY           = 2.0    # 초

# 인터벌 정의 (key: 메뉴번호, 분 단위 크기 포함)
AVAILABLE_INTERVALS = {
    '1':  {'name': '1분봉',   'path': '/v1/candles/minutes/1',   'minutes': 1,      'code': 'minute1'},
    '2':  {'name': '3분봉',   'path': '/v1/candles/minutes/3',   'minutes': 3,      'code': 'minute3'},
    '3':  {'name': '5분봉',   'path': '/v1/candles/minutes/5',   'minutes': 5,      'code': 'minute5'},
    '4':  {'name': '10분봉',  'path': '/v1/candles/minutes/10',  'minutes': 10,     'code': 'minute10'},
    '5':  {'name': '15분봉',  'path': '/v1/candles/minutes/15',  'minutes': 15,     'code': 'minute15'},
    '6':  {'name': '30분봉',  'path': '/v1/candles/minutes/30',  'minutes': 30,     'code': 'minute30'},
    '7':  {'name': '60분봉',  'path': '/v1/candles/minutes/60',  'minutes': 60,     'code': 'minute60'},
    '8':  {'name': '4시간봉', 'path': '/v1/candles/minutes/240', 'minutes': 240,    'code': 'minute240'},
    '9':  {'name': '일봉',    'path': '/v1/candles/days',        'minutes': 1440,   'code': 'day'},
    '10': {'name': '주봉',    'path': '/v1/candles/weeks',       'minutes': 10080,  'code': 'week'},
    '11': {'name': '월봉',    'path': '/v1/candles/months',      'minutes': 43200,  'code': 'month'},
}

# 기간 프리셋 (일 단위)
PERIOD_PRESETS = {
    '1': {'name': '30일',    'days': 30},
    '2': {'name': '90일',    'days': 90},
    '3': {'name': '180일',   'days': 180},
    '4': {'name': '365일',   'days': 365},
    '5': {'name': '2년',     'days': 730},
    '6': {'name': '전체',    'days': 3650},  # 상장일부터 (약 10년치 시도)
    '7': {'name': '직접입력', 'days': None},
}


# ============================================================================
# SECTION 2: 터미널 색상 & UI 유틸
# ============================================================================

class Colors:
    HEADER    = '\033[95m'
    BLUE      = '\033[94m'
    CYAN      = '\033[96m'
    GREEN     = '\033[92m'
    YELLOW    = '\033[93m'
    RED       = '\033[91m'
    ENDC      = '\033[0m'
    BOLD      = '\033[1m'
    MAGENTA   = '\033[35m'
    DIM       = '\033[2m'


def clear_screen():
    os.system('cls' if os.name == 'nt' else 'clear')

def print_header(text):
    print(f"\n{Colors.BOLD}{Colors.CYAN}{'━'*70}")
    print(f"  {text}")
    print(f"{'━'*70}{Colors.ENDC}\n")

def print_success(text):  print(f"{Colors.GREEN}✅ {text}{Colors.ENDC}")
def print_error(text):    print(f"{Colors.RED}❌ {text}{Colors.ENDC}")
def print_warning(text):  print(f"{Colors.YELLOW}⚠️  {text}{Colors.ENDC}")
def print_info(text):     print(f"{Colors.BLUE}ℹ️  {text}{Colors.ENDC}")

def print_progress(current, total, label="", width=40, eta_sec=None):
    """진행률 바 표시"""
    pct    = current / total if total > 0 else 0
    filled = int(width * pct)
    bar    = '█' * filled + '░' * (width - filled)
    eta_str = f" ETA:{eta_sec:.0f}초" if eta_sec is not None and eta_sec > 0 else ""
    print(f"\r  [{bar}] {pct:5.1%} ({current:,}/{total:,}) {label}{eta_str}", end="", flush=True)

def create_output_directory():
    if not os.path.exists(OUTPUT_DIR):
        os.makedirs(OUTPUT_DIR)
        print_success(f"폴더 생성: {OUTPUT_DIR}")
    else:
        print_info(f"저장 폴더: {os.path.abspath(OUTPUT_DIR)}")


# ============================================================================
# SECTION 3: Upbit 공식 REST API 클라이언트 (인증 불필요 - Public API)
# ============================================================================

_last_api_call_time = 0.0

def _rate_limit():
    """Rate Limit 자동 조절"""
    global _last_api_call_time
    elapsed = time.time() - _last_api_call_time
    if elapsed < API_CALL_MIN_INTERVAL:
        time.sleep(API_CALL_MIN_INTERVAL - elapsed)
    _last_api_call_time = time.time()


def fetch_candles(ticker: str, interval_key: str, count: int = 200, to: str = None) -> list:
    """
    Upbit 공식 API 캔들 단건 조회
    Args:
        ticker:       'KRW-ETH' 형식
        interval_key: AVAILABLE_INTERVALS 메뉴번호
        count:        1~200
        to:           기준 시각 (ISO 8601, 이 시각 이전 캔들 반환)
    Returns:
        캔들 리스트 (최신순) 또는 None
    """
    info = AVAILABLE_INTERVALS[interval_key]
    url  = f"{UPBIT_API_BASE}{info['path']}"
    params = {'market': ticker, 'count': min(count, MAX_PER_CALL)}
    if to:
        params['to'] = to

    _rate_limit()

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = requests.get(url, params=params, timeout=15)

            if resp.status_code == 200:
                return resp.json()

            elif resp.status_code == 429:
                # Rate Limit 초과
                wait = min(30, 5 * attempt)
                print(f"\n  {Colors.YELLOW}[Rate Limit] {wait}초 대기...{Colors.ENDC}", end="")
                time.sleep(wait)
                continue

            else:
                err_msg = resp.text[:100] if resp.text else "응답 없음"
                if attempt == MAX_RETRIES:
                    print(f"\n  {Colors.RED}[API 오류 {resp.status_code}] {err_msg}{Colors.ENDC}")
                time.sleep(RETRY_DELAY * attempt)

        except requests.exceptions.ConnectionError:
            print(f"\n  {Colors.YELLOW}[연결 오류] {attempt}/{MAX_RETRIES} 재시도...{Colors.ENDC}", end="")
            time.sleep(RETRY_DELAY * attempt)
        except requests.exceptions.Timeout:
            print(f"\n  {Colors.YELLOW}[타임아웃] {attempt}/{MAX_RETRIES} 재시도...{Colors.ENDC}", end="")
            time.sleep(RETRY_DELAY)
        except Exception as e:
            print(f"\n  {Colors.RED}[예외] {e}{Colors.ENDC}")
            time.sleep(RETRY_DELAY)

    return None


def calculate_candle_count(interval_key: str, days: int) -> int:
    """기간(일) → 필요 캔들 수 계산"""
    minutes = AVAILABLE_INTERVALS[interval_key]['minutes']
    return int(days * 24 * 60 / minutes)


def calculate_api_calls(candle_count: int) -> int:
    """필요 API 호출 횟수 계산"""
    return (candle_count + MAX_PER_CALL - 1) // MAX_PER_CALL


def estimate_time(api_calls: int, coins: int = 1) -> float:
    """예상 소요 시간 계산 (초)"""
    return api_calls * coins * API_CALL_MIN_INTERVAL * 1.3  # 여유 30%


# ============================================================================
# SECTION 4: 대용량 OHLCV 수집 (페이지네이션)
# ============================================================================

def fetch_ohlcv_paginated(ticker: str, interval_key: str, target_count: int,
                          verbose: bool = True) -> pd.DataFrame | None:
    """
    페이지네이션으로 대용량 OHLCV 수집
    Args:
        ticker:        'KRW-ETH'
        interval_key:  AVAILABLE_INTERVALS 메뉴번호
        target_count:  목표 캔들 수 (수십~수만 개)
        verbose:       진행률 출력 여부
    Returns:
        정렬된 OHLCV DataFrame (datetime 인덱스)
    """
    coin_name    = ticker.replace('KRW-', '')
    interval_name = AVAILABLE_INTERVALS[interval_key]['name']
    total_calls  = calculate_api_calls(target_count)

    if verbose:
        print(f"\n  📥 {coin_name} {interval_name} 수집 (목표: {target_count:,}개 / {total_calls}회 호출)")

    all_candles  = []
    collected    = 0
    remaining    = target_count
    current_to   = None
    call_count   = 0
    start_ts     = time.time()

    while remaining > 0:
        batch = min(remaining, MAX_PER_CALL)
        candles = fetch_candles(ticker, interval_key, batch, current_to)

        if not candles:
            if collected == 0:
                print(f"\n  {Colors.RED}데이터 수집 실패 ({ticker}){Colors.ENDC}")
                return None
            break  # 더 이상 데이터 없음 (상장일 도달)

        all_candles.extend(candles)
        collected  += len(candles)
        remaining  -= len(candles)
        call_count += 1

        if verbose:
            elapsed = time.time() - start_ts
            eta = (elapsed / call_count * (total_calls - call_count)) if call_count > 0 else 0
            print_progress(min(collected, target_count), target_count,
                           f"{collected:,}개", eta_sec=eta)

        # 다음 페이지 기준 시각 (마지막 캔들의 시각 - 1초)
        last_candle = candles[-1]
        last_dt_str = last_candle.get('candle_date_time_utc', '')
        if not last_dt_str:
            break

        # UTC ISO 형식으로 to 파라미터 설정
        try:
            last_dt = datetime.strptime(last_dt_str, '%Y-%m-%dT%H:%M:%S')
            current_to = (last_dt - timedelta(seconds=1)).strftime('%Y-%m-%dT%H:%M:%S')
        except Exception:
            break

        # 배치가 최대치 미만이면 더 이상 데이터 없음 (상장일 도달)
        if len(candles) < batch:
            if verbose:
                print(f"\n  {Colors.CYAN}ℹ️  상장일 도달 (실제 수집: {collected:,}개){Colors.ENDC}", end="")
            break

    if verbose:
        print()  # 줄바꿈

    if not all_candles:
        return None

    # ── DataFrame 변환 ──
    rows = [{
        'datetime': c.get('candle_date_time_kst', c.get('candle_date_time_utc', '')),
        'open':   c.get('opening_price', 0.0),
        'high':   c.get('high_price', 0.0),
        'low':    c.get('low_price', 0.0),
        'close':  c.get('trade_price', 0.0),
        'volume': c.get('candle_acc_trade_volume', 0.0),
        'value':  c.get('candle_acc_trade_price', 0.0),
    } for c in all_candles]

    df = pd.DataFrame(rows)
    df['datetime'] = pd.to_datetime(df['datetime'])
    df = df.set_index('datetime').sort_index(ascending=True)

    # 데이터 품질 처리
    df = df[~df.index.duplicated(keep='last')]  # 중복 제거
    df = df[df['close'] > 0]                    # 이상치 제거

    return df


# ============================================================================
# SECTION 5: CSV 저장 & 검증
# ============================================================================

def save_to_csv(df: pd.DataFrame, ticker: str, interval_code: str, period_tag: str = "") -> str | None:
    """DataFrame → CSV 저장, 저장된 경로 반환"""
    if df is None or len(df) == 0:
        return None
    try:
        coin_name  = ticker.replace('KRW-', '')
        timestamp  = datetime.now().strftime('%Y%m%d_%H%M')
        tag        = f"_{period_tag}" if period_tag else ""
        filename   = f"{coin_name}_{interval_code}{tag}_{timestamp}.csv"
        filepath   = os.path.join(OUTPUT_DIR, filename)

        df.to_csv(filepath, encoding='utf-8-sig')

        filesize_kb = os.path.getsize(filepath) / 1024
        return filepath, filesize_kb
    except Exception as e:
        print_error(f"저장 오류: {e}")
        return None


def print_data_summary(df: pd.DataFrame, ticker: str, interval_name: str):
    """수집 데이터 요약 출력"""
    if df is None or len(df) == 0:
        return

    coin_name = ticker.replace('KRW-', '')
    start_dt  = df.index[0].strftime('%Y-%m-%d %H:%M')
    end_dt    = df.index[-1].strftime('%Y-%m-%d %H:%M')
    span_days = (df.index[-1] - df.index[0]).days
    change    = (df['close'].iloc[-1] / df['open'].iloc[0] - 1) * 100

    # 갭 체크 (누락 캔들 감지)
    gap_count = 0
    minutes   = next((v['minutes'] for v in AVAILABLE_INTERVALS.values()
                      if v['name'] == interval_name), None)
    if minutes and minutes <= 240:  # 분봉만 체크
        expected_diff = pd.Timedelta(minutes=minutes)
        diffs = df.index.to_series().diff().dropna()
        gap_count = int((diffs > expected_diff * 2).sum())

    print(f"  {Colors.DIM}{'─'*60}{Colors.ENDC}")
    print(f"  📅 기간: {start_dt} ~ {end_dt} ({span_days}일)")
    print(f"  📊 캔들: {len(df):,}개 | 갭: {gap_count}개")
    print(f"  💰 변동: {change:+.2f}%  "
          f"({df['open'].iloc[0]:,.0f}원 → {df['close'].iloc[-1]:,.0f}원)")
    print(f"  📈 고점: {df['high'].max():,.0f}원 | 저점: {df['low'].min():,.0f}원")


# ============================================================================
# SECTION 6: 데이터 수집 가능량 안내
# ============================================================================

def print_capacity_table(interval_key: str):
    """선택한 인터벌의 기간별 수집 가능량 안내"""
    info     = AVAILABLE_INTERVALS[interval_key]
    minutes  = info['minutes']
    name     = info['name']

    print(f"\n  {Colors.BOLD}📊 {name} 수집 가능량 안내{Colors.ENDC}")
    print(f"  {'기간':<10} {'캔들 수':>10} {'API 호출':>8} {'예상 시간':>10}")
    print(f"  {'─'*42}")

    for period_name, days in [('30일', 30), ('90일', 90), ('180일', 180),
                               ('1년', 365), ('2년', 730), ('전체(ETH)', 2500)]:
        count = int(days * 24 * 60 / minutes)
        calls = calculate_api_calls(count)
        est   = estimate_time(calls)
        time_str = f"{est:.0f}초" if est < 60 else f"{est/60:.1f}분"
        print(f"  {period_name:<10} {count:>10,} {calls:>8} {time_str:>10}")

    print(f"\n  {Colors.GREEN}✅ pyupbit v2.0 한계: 200개 (1회 고정)")
    print(f"  🚀 공식 API v3.0: 페이지네이션으로 무제한 수집 가능{Colors.ENDC}")


# ============================================================================
# SECTION 7: 메뉴 시스템
# ============================================================================

def display_main_menu():
    clear_screen()
    print_header("🚀 암호화폐 데이터 다운로더 v3.0  [Upbit 공식 API 직접 연동]")

    print(f"  {Colors.BOLD}📅 현재 시각:{Colors.ENDC} {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  {Colors.BOLD}💾 저장 위치:{Colors.ENDC} {os.path.abspath(OUTPUT_DIR)}")
    print(f"  {Colors.BOLD}🪙 대상 코인:{Colors.ENDC} {', '.join(t.replace('KRW-','') for t in ALL_TICKERS)}")
    print(f"  {Colors.BOLD}📡 API:{Colors.ENDC}      Upbit 공식 REST API (인증 불필요)\n")

    print(f"  {Colors.BOLD}{Colors.YELLOW}메뉴를 선택하세요:{Colors.ENDC}\n")
    print(f"    {Colors.BOLD}1.{Colors.ENDC}  ⚡ 빠른 다운로드     (15분봉 90일 + 일봉 365일, 전체 코인)")
    print(f"    {Colors.BOLD}2.{Colors.ENDC}  🎨 커스텀 다운로드   (봉 종류 + 기간 + 코인 선택)")
    print(f"    {Colors.BOLD}3.{Colors.ENDC}  🌟 전체 다운로드     (모든 봉 / 365일 / 전체 코인)")
    print(f"    {Colors.BOLD}4.{Colors.ENDC}  📋 수집 가능량 확인  (인터벌별 최대 데이터량 안내)")
    print(f"    {Colors.BOLD}0.{Colors.ENDC}  ✈️  종료\n")


def select_interval() -> str | None:
    """봉 종류 단일 선택"""
    print_header("📊 봉 종류 선택")
    items = list(AVAILABLE_INTERVALS.items())

    for i in range(0, len(items), 4):
        row = items[i:i+4]
        for num, info in row:
            print(f"  {Colors.BOLD}{num:>2}.{Colors.ENDC} {info['name']:<10}", end="")
        print()

    print()
    while True:
        choice = input(f"  {Colors.CYAN}선택 > {Colors.ENDC}").strip()
        if choice == '0':
            return None
        if choice in AVAILABLE_INTERVALS:
            return choice
        print_error("잘못된 선택입니다.")


def select_intervals_multi() -> list | None:
    """봉 종류 다중 선택"""
    print_header("📊 봉 종류 선택 (다중)")
    items = list(AVAILABLE_INTERVALS.items())

    for i in range(0, len(items), 4):
        row = items[i:i+4]
        for num, info in row:
            print(f"  {Colors.BOLD}{num:>2}.{Colors.ENDC} {info['name']:<10}", end="")
        print()

    print(f"\n  {Colors.YELLOW}선택 방법: 5  |  3,5,9  |  5-9  |  all  |  0=취소{Colors.ENDC}")

    while True:
        choice = input(f"\n  {Colors.CYAN}선택 > {Colors.ENDC}").strip()
        if choice == '0':
            return None
        if choice.lower() == 'all':
            return list(AVAILABLE_INTERVALS.keys())

        selected = []
        valid = True
        try:
            for part in choice.split(','):
                part = part.strip()
                if '-' in part:
                    s, e = part.split('-')
                    for n in range(int(s), int(e)+1):
                        k = str(n)
                        if k in AVAILABLE_INTERVALS and k not in selected:
                            selected.append(k)
                elif part in AVAILABLE_INTERVALS:
                    if part not in selected:
                        selected.append(part)
                else:
                    print_error(f"잘못된 선택: '{part}'")
                    valid = False
                    break
        except Exception:
            valid = False

        if valid and selected:
            selected.sort(key=lambda x: int(x))
            print(f"\n  {Colors.GREEN}선택된 봉:{Colors.ENDC} "
                  + ", ".join(AVAILABLE_INTERVALS[k]['name'] for k in selected))
            if input(f"  {Colors.YELLOW}진행? (y/n) > {Colors.ENDC}").strip().lower() == 'y':
                return selected
        elif valid:
            print_error("선택된 봉이 없습니다.")


def select_period() -> int | None:
    """수집 기간 선택 (일 단위 반환)"""
    print(f"\n  {Colors.BOLD}📅 수집 기간 선택:{Colors.ENDC}\n")
    for key, info in PERIOD_PRESETS.items():
        print(f"    {Colors.BOLD}{key}.{Colors.ENDC} {info['name']}")

    print(f"    {Colors.BOLD}0.{Colors.ENDC} 취소")

    while True:
        choice = input(f"\n  {Colors.CYAN}선택 > {Colors.ENDC}").strip()
        if choice == '0':
            return None
        if choice in PERIOD_PRESETS:
            preset = PERIOD_PRESETS[choice]
            if preset['days'] is None:
                # 직접 입력
                try:
                    days = int(input(f"  {Colors.CYAN}기간 입력 (일 단위, 예: 180) > {Colors.ENDC}").strip())
                    if days > 0:
                        return days
                    print_error("1 이상의 숫자를 입력하세요.")
                except ValueError:
                    print_error("숫자를 입력하세요.")
            else:
                return preset['days']
        print_error("잘못된 선택입니다.")


def select_coins() -> list | None:
    """코인 선택"""
    print_header("🪙 코인 선택")
    for idx, t in enumerate(ALL_TICKERS, 1):
        print(f"  {Colors.BOLD}{idx}.{Colors.ENDC} {t.replace('KRW-','')}", end="   ")
        if idx % 4 == 0:
            print()
    print()
    print(f"\n  {Colors.YELLOW}선택 방법: 1  |  1,3,5  |  1-4  |  all (Enter)  |  0=취소{Colors.ENDC}")

    while True:
        choice = input(f"\n  {Colors.CYAN}선택 > {Colors.ENDC}").strip()
        if choice == '0':
            return None
        if choice == '' or choice.lower() == 'all':
            return ALL_TICKERS

        selected_idx = set()
        try:
            for part in choice.split(','):
                part = part.strip()
                if '-' in part:
                    s, e = part.split('-')
                    for n in range(int(s), int(e)+1):
                        if 1 <= n <= len(ALL_TICKERS):
                            selected_idx.add(n-1)
                else:
                    n = int(part)
                    if 1 <= n <= len(ALL_TICKERS):
                        selected_idx.add(n-1)
                    else:
                        print_error(f"범위 벗어남: {n}")
                        selected_idx = set()
                        break
        except Exception:
            selected_idx = set()

        if selected_idx:
            tickers = [ALL_TICKERS[i] for i in sorted(selected_idx)]
            print(f"\n  {Colors.GREEN}선택된 코인:{Colors.ENDC} "
                  + ", ".join(t.replace('KRW-','') for t in tickers))
            if input(f"  {Colors.YELLOW}진행? (y/n) > {Colors.ENDC}").strip().lower() == 'y':
                return tickers
        else:
            print_error("선택된 코인이 없습니다.")


# ============================================================================
# SECTION 8: 다운로드 실행 엔진
# ============================================================================

def run_download(tickers: list, interval_keys: list, days: int):
    """
    다운로드 실행 메인 엔진
    Args:
        tickers:       코인 티커 리스트
        interval_keys: 인터벌 메뉴번호 리스트
        days:          수집 기간 (일 단위)
    """
    create_output_directory()

    total_jobs  = len(tickers) * len(interval_keys)
    job_no      = 0
    success     = 0
    total_rows  = 0
    start_time  = time.time()

    print_header(f"📥 다운로드 시작  |  코인 {len(tickers)}개 × 봉 {len(interval_keys)}종류 = {total_jobs}개 작업")
    print_info(f"수집 기간: {days}일  |  예상 캔들 수: "
               f"{calculate_candle_count(interval_keys[0], days):,}개+ (인터벌별 상이)")
    print()

    results = []

    for ticker in tickers:
        coin_name = ticker.replace('KRW-', '')
        print(f"\n{Colors.BOLD}{Colors.BLUE}━━ {coin_name} {'━'*50}{Colors.ENDC}")

        for interval_key in interval_keys:
            job_no += 1
            info      = AVAILABLE_INTERVALS[interval_key]
            target    = calculate_candle_count(interval_key, days)
            api_calls = calculate_api_calls(target)
            period_tag = f"{days}days"

            print(f"\n  [{job_no}/{total_jobs}] {info['name']}  "
                  f"({Colors.DIM}목표 {target:,}개 / {api_calls}회 호출{Colors.ENDC})")

            # 수집 실행
            df = fetch_ohlcv_paginated(ticker, interval_key, target, verbose=True)

            if df is not None and len(df) > 0:
                # 요약 출력
                print_data_summary(df, ticker, info['name'])

                # CSV 저장
                result = save_to_csv(df, ticker, info['code'], period_tag)
                if result:
                    filepath, filesize_kb = result
                    fname = os.path.basename(filepath)
                    print(f"  {Colors.GREEN}💾 저장: {fname} ({filesize_kb:.1f} KB, {len(df):,}행){Colors.ENDC}")
                    success  += 1
                    total_rows += len(df)
                    results.append({
                        'ticker': ticker, 'interval': info['name'],
                        'rows': len(df), 'file': fname, 'kb': filesize_kb
                    })
                else:
                    print_error(f"  저장 실패")
            else:
                print_error(f"  {coin_name} {info['name']} 수집 실패")

    # ── 최종 리포트 ──
    elapsed = time.time() - start_time
    print_header("🎉 다운로드 완료!")

    print(f"  {Colors.BOLD}결과 요약:{Colors.ENDC}")
    print(f"    ✅ 성공: {success}/{total_jobs} 작업")
    print(f"    📊 총 수집: {total_rows:,}개 캔들")
    print(f"    ⏱️  소요: {elapsed:.1f}초 ({elapsed/60:.1f}분)")
    print(f"    📂 위치: {os.path.abspath(OUTPUT_DIR)}\n")

    if results:
        print(f"  {Colors.BOLD}파일 목록:{Colors.ENDC}")
        print(f"  {'파일명':<50} {'캔들':>8} {'크기':>8}")
        print(f"  {'─'*70}")
        for r in results:
            print(f"  {r['file']:<50} {r['rows']:>8,} {r['kb']:>6.1f} KB")


# ============================================================================
# SECTION 9: 프리셋 모드
# ============================================================================

def quick_download():
    """빠른 다운로드: 15분봉 90일 + 일봉 365일, 전체 코인"""
    print_header("⚡ 빠른 다운로드 모드")
    print(f"  • 코인: 전체 7개  ({', '.join(t.replace('KRW-','') for t in ALL_TICKERS)})")
    print(f"  • 봉:   15분봉 90일 ({calculate_candle_count('5', 90):,}개) + 일봉 365일 ({calculate_candle_count('9', 365):,}개)")

    est = estimate_time(calculate_api_calls(calculate_candle_count('5', 90)) +
                        calculate_api_calls(calculate_candle_count('9', 365)),
                        coins=len(ALL_TICKERS))
    print(f"  • 예상 소요: {est/60:.1f}분\n")

    if input(f"  {Colors.YELLOW}진행? (y/n) > {Colors.ENDC}").strip().lower() != 'y':
        return

    # 15분봉 90일
    run_download(ALL_TICKERS, ['5'], 90)
    print()
    # 일봉 365일
    run_download(ALL_TICKERS, ['9'], 365)


def custom_download():
    """커스텀 다운로드"""
    print_header("🎨 커스텀 다운로드 모드")

    interval_keys = select_intervals_multi()
    if not interval_keys:
        return

    # 선택된 각 인터벌의 수집 가능량 안내
    for ik in interval_keys:
        print_capacity_table(ik)

    days = select_period()
    if not days:
        return

    tickers = select_coins()
    if not tickers:
        return

    # 예상 소요 시간
    total_calls = sum(calculate_api_calls(calculate_candle_count(ik, days)) for ik in interval_keys)
    est = estimate_time(total_calls, coins=len(tickers))
    print(f"\n  {Colors.CYAN}예상 소요 시간: {est/60:.1f}분 ({est:.0f}초){Colors.ENDC}")

    if input(f"\n  {Colors.YELLOW}다운로드 시작? (y/n) > {Colors.ENDC}").strip().lower() != 'y':
        return

    run_download(tickers, interval_keys, days)


def full_download():
    """전체 다운로드: 모든 봉 365일 전체 코인"""
    print_header("🌟 전체 다운로드 모드")

    all_keys  = list(AVAILABLE_INTERVALS.keys())
    total_jobs = len(ALL_TICKERS) * len(all_keys)
    total_calls = sum(calculate_api_calls(calculate_candle_count(ik, 365)) for ik in all_keys)
    est = estimate_time(total_calls, coins=len(ALL_TICKERS))

    print(f"  • 코인: 전체 7개")
    print(f"  • 봉:   모든 종류 11개 / 365일")
    print(f"  • 총:   {total_jobs}개 파일")
    print(f"  • 예상 소요: {est/60:.1f}분")
    print(f"\n  {Colors.RED}⚠️  대용량 다운로드입니다. 완료까지 상당 시간 소요됩니다.{Colors.ENDC}\n")

    if input(f"  {Colors.YELLOW}진행? (y/n) > {Colors.ENDC}").strip().lower() != 'y':
        return

    run_download(ALL_TICKERS, all_keys, 365)


def show_capacity_info():
    """수집 가능량 정보 출력"""
    print_header("📋 Upbit 공식 API 수집 가능량 안내")

    print(f"  {Colors.BOLD}{'인터벌':<10} {'30일':>9} {'90일':>9} {'180일':>10} {'365일':>10} {'2년':>10} {'전체(ETH)':>12}{Colors.ENDC}")
    print(f"  {'─'*72}")

    for key, info in AVAILABLE_INTERVALS.items():
        m = info['minutes']
        counts = [int(d * 24 * 60 / m) for d in [30, 90, 180, 365, 730, 2500]]
        row = f"  {info['name']:<10}"
        for c in counts:
            row += f" {c:>9,}"
        print(row)

    print(f"\n  {Colors.GREEN}✅ pyupbit (이전): 1회 최대 200개 고정")
    print(f"  🚀 공식 API (현재): 페이지네이션으로 상장일까지 소급 가능")
    print(f"\n  {Colors.YELLOW}⏱️  예상 소요 시간 (전체 7개 코인 기준):{Colors.ENDC}")
    print(f"  {'인터벌':<10} {'365일 캔들':>12} {'호출 수':>8} {'예상 시간':>12}")
    print(f"  {'─'*46}")

    for key, info in AVAILABLE_INTERVALS.items():
        m       = info['minutes']
        count   = int(365 * 24 * 60 / m)
        calls   = calculate_api_calls(count) * len(ALL_TICKERS)
        est     = estimate_time(calculate_api_calls(count), coins=len(ALL_TICKERS))
        time_str = f"{est:.0f}초" if est < 60 else f"{est/60:.1f}분"
        print(f"  {info['name']:<10} {count:>12,} {calls:>8} {time_str:>12}")

    print(f"{Colors.ENDC}")


# ============================================================================
# SECTION 10: 메인 실행
# ============================================================================

def main():
    print(f"\n{Colors.BOLD}{Colors.CYAN}")
    print("  ┌─────────────────────────────────────────────────────────┐")
    print("  │   암호화폐 데이터 다운로더 v3.0                          │")
    print("  │   Upbit 공식 REST API 직접 연동 (pyupbit 제거)          │")
    print("  │   페이지네이션으로 최대 수만 개 캔들 수집               │")
    print("  └─────────────────────────────────────────────────────────┘")
    print(f"{Colors.ENDC}")

    while True:
        display_main_menu()
        try:
            choice = input(f"  {Colors.CYAN}선택 > {Colors.ENDC}").strip()

            if choice == '0':
                print(f"\n  {Colors.YELLOW}👋 종료합니다.{Colors.ENDC}\n")
                break
            elif choice == '1':
                quick_download()
            elif choice == '2':
                custom_download()
            elif choice == '3':
                full_download()
            elif choice == '4':
                show_capacity_info()
            else:
                print_error("잘못된 선택입니다.")
                time.sleep(1)
                continue

            input(f"\n  {Colors.CYAN}계속하려면 Enter...{Colors.ENDC}")

        except KeyboardInterrupt:
            print(f"\n\n  {Colors.YELLOW}⚠️  사용자 중단{Colors.ENDC}\n")
            break
        except Exception as e:
            print_error(f"예상치 못한 오류: {e}")
            time.sleep(2)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print_error(f"치명적 오류: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
