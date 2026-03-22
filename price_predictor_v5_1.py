#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  암호화폐 가격 예측 분석기 v5.1
  ▶ BB Bounce Hunter v33 보조 모듈 (독립 실행 가능)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  [v5.1 핵심 — 3코인 일괄 분석]

  ✅ v5.0 전체 계승: 속도 최적화 + 31 피처 + 2-Phase 그리드
  ✅ 신규: 모드 4 — ETH/XRP/SOL 일괄 백테스트 → 비교 → 예측
  ✅ 신규: 코인별 독립 최적 파라미터 + 3코인 비교 대시보드
  ✅ 신규: 최적/회피 코인 자동 판정 + BB Bounce 연동 권고

  [속도 비교]
  v4.0 올인원: 약 15~30분 → v5.1: 약 3~8분 (단일)
  v5.1 3코인 일괄: 약 5~10분 (3코인 순차)

  [호환성]
  ✅ get_prediction() API: BB Bounce Hunter v33 그대로 연동
  ✅ 캐시 파일 포맷: v4.0/v3.0 호환
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

import os, sys, time, json, pickle, warnings
import requests, numpy as np, pandas as pd
from datetime import datetime, timedelta
from threading import Lock

warnings.filterwarnings('ignore')

try:
    import lightgbm as lgb
    from lightgbm import LGBMClassifier
except ImportError:
    print("lightgbm 미설치: pip install lightgbm")
    sys.exit(1)


# ============================================================================
# SECTION 1: 설정 (Config)
# ============================================================================

VERSION = "5.1"
DEBUG_MODE_PRED = True   # True: get_prediction() 내부 예외 스택트레이스 출력

COINS = {
    1: "KRW-ETH",  2: "KRW-XRP",  3: "KRW-SOL",
    4: "KRW-ADA",  5: "KRW-LINK", 6: "KRW-BCH", 7: "KRW-SUI",
}

# v5.1: 3코인 일괄 분석 대상 (BB Bounce Hunter v33 감시 코인과 동일)
TARGET_COINS = ["KRW-ETH", "KRW-XRP", "KRW-SOL"]
MULTI_S2_TOP_N = 2   # Stage 2는 상위 N개 코인만 실행 (시간 절약)

UPBIT_API_BASE  = "https://api.upbit.com"
API_INTERVAL    = 0.13
MAX_RETRIES     = 3

BB_PERIOD       = 20
BB_STD_DEV      = 2.0
RSI_PERIOD      = 14

DEFAULT_THRESHOLD = 0.15
PREDICT_STEPS     = 5
MIN_CANDLES       = 50
MIN_TRAIN         = 300
DEFAULT_TRAIN     = 1000
DEFAULT_PRED      = 100

MODEL_DIR         = "./predictor_models"
CACHE_DIR         = "./predictor_models"
CACHE_VALID_HOURS = 12
QUICK_VAL_DROP_THRESHOLD = 0.10

# ── LGB 기본 하이퍼파라미터 (최종 학습용) ──
LGB_BASE_PARAMS = {
    'n_estimators':      500,
    'learning_rate':     0.02,
    'max_depth':         4,
    'num_leaves':        15,
    'min_child_samples': 30,
    'subsample':         0.8,
    'colsample_bytree':  0.7,
    'reg_alpha':         0.1,
    'reg_lambda':        0.2,
    'class_weight':      'balanced',
    'random_state':      42,
    'verbose':           -1,
    'n_jobs':            -1,
}

# ── v5.0: 탐색용 경량 LGB 파라미터 (Stage 1/2 그리드 탐색 전용) ──
LGB_SEARCH_PARAMS = {
    'n_estimators':      150,       # v4: 500 → v5: 150 (70% 감소)
    'learning_rate':     0.05,      # 큰 LR로 빠른 수렴
    'max_depth':         4,
    'num_leaves':        15,
    'min_child_samples': 30,
    'subsample':         0.8,
    'colsample_bytree':  0.7,
    'reg_alpha':         0.1,
    'reg_lambda':        0.2,
    'class_weight':      'balanced',
    'random_state':      42,
    'verbose':           -1,
    'n_jobs':            -1,
}
LGB_SEARCH_EARLY_STOP = 10         # v4: 30 → v5: 10

# ── Stage 1 그리드: 데이터 파라미터 ──
S1_TRAIN_COUNTS  = [500, 1000, 2000]
S1_PRED_COUNTS   = [50, 100]
S1_THRESHOLDS    = [0.10, 0.15, 0.20, 0.25]

# v5.0: 2-Phase 그리드 전략
# Phase A (빠른 스크리닝): 3개 offset, slide 8
S1_OFFSETS_QUICK = [96, 480, 864]       # 1/5/9일 (핵심 3시점)
S1_SLIDE_QUICK   = 8

# Phase B (정밀 검증): 상위 조합만 5개 offset, slide 20
S1_OFFSETS_FULL  = [96, 288, 480, 672, 864]  # 전체 5시점
S1_SLIDE_FULL    = 20

S1_PHASE_A_TOP_N = 8                    # Phase A에서 상위 N개만 Phase B로
S1_MIN_PASS_RATE = 0.7

# ── Stage 2 그리드: LGB 하이퍼파라미터 ──
S2_DEPTHS        = [3, 4, 6]
S2_LEAVES        = [10, 15, 25]
S2_LRS           = [0.01, 0.02, 0.05]
S2_OFFSETS       = [96, 288, 480]
S2_SLIDE_N       = 10

# ── Adaptive Threshold 설정 ──
ADAPTIVE_THR_ENABLED  = True
ADAPTIVE_THR_MIN      = 0.08
ADAPTIVE_THR_MAX      = 0.30
ADAPTIVE_THR_BBW_REF  = 3.0

# ── 피처 선택 ──
FEATURE_PRUNE_ENABLED = True
FEATURE_PRUNE_MIN_IMPORTANCE = 0.02

_predict_lock = Lock()
_last_api_t   = 0.0


# ============================================================================
# SECTION 2: 터미널 색상
# ============================================================================

class C:
    BOLD = '\033[1m'; CYAN = '\033[96m'; GREEN = '\033[92m'
    YELLOW = '\033[93m'; RED = '\033[91m'; BLUE = '\033[94m'
    MAGENTA = '\033[35m'; DIM = '\033[2m'; END = '\033[0m'

def ph(t):  print(f"\n{C.BOLD}{C.CYAN}{'━'*62}\n  {t}\n{'━'*62}{C.END}")
def ps(t):  print(f"{C.GREEN}  ✅ {t}{C.END}")
def pe(t):  print(f"{C.RED}  ❌ {t}{C.END}")
def pw(t):  print(f"{C.YELLOW}  ⚠️  {t}{C.END}")
def pi(t):  print(f"{C.BLUE}  ℹ️  {t}{C.END}")


# ============================================================================
# SECTION 3: Upbit REST API (15분봉)
# ============================================================================

def _rate_limit():
    global _last_api_t
    elapsed = time.time() - _last_api_t
    if elapsed < API_INTERVAL:
        time.sleep(API_INTERVAL - elapsed)
    _last_api_t = time.time()


def fetch_candles_15m(ticker: str, count: int, to: str = None):
    """Upbit 15분봉 수집 (페이지네이션)"""
    url = f"{UPBIT_API_BASE}/v1/candles/minutes/15"
    all_c, remaining, cur_to = [], count, to

    while remaining > 0:
        batch = min(remaining, 200)
        params = {'market': ticker, 'count': batch}
        if cur_to:
            params['to'] = cur_to
        _rate_limit()
        fetched = None
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                r = requests.get(url, params=params, timeout=10)
                if r.status_code == 200:
                    fetched = r.json(); break
                elif r.status_code == 429:
                    time.sleep(5 * attempt)
                else:
                    time.sleep(1 * attempt)
            except Exception:
                time.sleep(2 * attempt)
        if not fetched:
            break
        all_c.extend(fetched)
        remaining -= len(fetched)
        if len(fetched) < batch:
            break
        last_dt = fetched[-1].get('candle_date_time_utc', '')
        if not last_dt:
            break
        try:
            dt_obj = datetime.strptime(last_dt, '%Y-%m-%dT%H:%M:%S')
            cur_to = (dt_obj - timedelta(seconds=1)).strftime('%Y-%m-%dT%H:%M:%S')
        except Exception:
            break

    if not all_c:
        return None

    rows = [{
        'datetime': c.get('candle_date_time_kst', ''),
        'open':     c.get('opening_price', 0.0),
        'high':     c.get('high_price', 0.0),
        'low':      c.get('low_price', 0.0),
        'close':    c.get('trade_price', 0.0),
        'volume':   c.get('candle_acc_trade_volume', 0.0),
    } for c in all_c]

    df = pd.DataFrame(rows)
    df['datetime'] = pd.to_datetime(df['datetime'])
    df = df.set_index('datetime').sort_index()
    df = df[~df.index.duplicated(keep='last')]
    df = df[df['close'] > 0]
    return df


def get_anchor_to_str(offset_bars: int) -> str:
    now_utc = datetime.utcnow()
    return (now_utc - timedelta(minutes=15 * offset_bars)).strftime('%Y-%m-%dT%H:%M:%S')


def bars_to_time(bars: int) -> str:
    total_min = bars * 15
    if total_min < 60:
        return f"{total_min}분"
    elif total_min < 1440:
        h, m = total_min // 60, total_min % 60
        return f"{h}시간" + (f" {m}분" if m else "")
    else:
        d, h = total_min // 1440, (total_min % 1440) // 60
        return f"{d}일" + (f" {h}시간" if h else "")


# ============================================================================
# SECTION 4: 기술 지표 (BB Bounce Hunter v33 동일)
# ============================================================================

def _rsi(series, period=RSI_PERIOD):
    d = series.diff()
    g = d.where(d > 0, 0.0)
    l = (-d).where(d < 0, 0.0)
    ag = g.ewm(com=period - 1, min_periods=period).mean()
    al = l.ewm(com=period - 1, min_periods=period).mean()
    return 100 - (100 / (1 + ag / al.replace(0, np.nan)))


def _srsi(series):
    rsi  = _rsi(series)
    rmin = rsi.rolling(14).min()
    rmax = rsi.rolling(14).max()
    stoch = ((rsi - rmin) / (rmax - rmin).replace(0, np.nan) * 100).fillna(50)
    k = stoch.rolling(3).mean().fillna(50)
    d = k.rolling(3).mean().fillna(50)
    return k, d


def _bb(df):
    c   = df['close']
    mid = c.rolling(BB_PERIOD).mean()
    std = c.rolling(BB_PERIOD).std()
    up  = mid + BB_STD_DEV * std
    lo  = mid - BB_STD_DEV * std
    rng = up - lo
    pos = ((c - lo) / rng.replace(0, np.nan) * 100).clip(0, 100).fillna(50)
    wid = (rng / lo.replace(0, np.nan) * 100).fillna(0)
    return mid, up, lo, rng, pos, wid


# ============================================================================
# SECTION 5: 피처 엔지니어링 (v5.0: 31개 = 28 기존 + 3 신규)
# ============================================================================

FEATURE_COLS = [
    # BB (6)
    'bb_pos', 'bb_width', 'bb_slope', 'close_vs_mid', 'bb_lower_dist', 'bb_upper_dist',
    # RSI / StochRSI (7)
    'rsi', 'rsi_d2', 'rsi_d4', 'srsi_k', 'srsi_d', 'srsi_kd', 'rsi_zone',
    # 수익률 (4)
    'r1', 'r3', 'r6', 'r12',
    # 봉 패턴 (4)
    'body', 'wick_lo', 'wick_hi', 'bull',
    # 모멘텀 (3)
    'ema_cross', 'consec_bull', 'price_accel',
    # 거래량 / 변동성 (2)
    'vol_r', 'atr_ratio',
    # 시간 (3)
    'hour', 'is_block', 'bbw_lv',
    # ── v5.0 신규 피처 (3) ──
    'vwap_dist',       # VWAP 대비 현재가 괴리율
    'bbw_change',      # BB Width 3봉 변화율 (변동성 확대/축소 방향)
    'rsi_divergence',  # RSI 다이버전스 신호 (가격↓ RSI↑ = 양, 가격↑ RSI↓ = 음)
]


def build_features(df):
    """v5.0: 31개 피처 생성 (v4 28개 + VWAP/BBW변화율/RSI다이버전스)"""
    if df is None or len(df) < 30:
        return None

    c   = df['close']
    mid, up, lo, rng, pos, wid = _bb(df)
    rsi = _rsi(c)
    sk, sd = _srsi(c)
    cr  = (df['high'] - df['low']).replace(0, np.nan)
    bdy = (c - df['open']).abs()
    e9  = c.ewm(span=9,  adjust=False).mean()
    e21 = c.ewm(span=21, adjust=False).mean()
    vma = df['volume'].rolling(20).mean().replace(0, np.nan)

    f = pd.DataFrame(index=df.index)

    # BB (6)
    f['bb_pos']        = pos
    f['bb_width']      = wid
    f['bb_slope']      = mid.pct_change(3).fillna(0) * 100
    f['close_vs_mid']  = ((c - mid) / mid * 100).fillna(0)
    f['bb_lower_dist'] = ((c - lo) / c * 100).fillna(0)
    f['bb_upper_dist'] = ((up - c) / c * 100).fillna(0)

    # RSI / StochRSI (7)
    f['rsi']      = rsi.fillna(50)
    f['rsi_d2']   = rsi.diff(2).fillna(0)
    f['rsi_d4']   = rsi.diff(4).fillna(0)
    f['srsi_k']   = sk
    f['srsi_d']   = sd
    f['srsi_kd']  = sk - sd
    f['rsi_zone'] = pd.cut(f['rsi'], bins=[0, 30, 45, 55, 70, 100],
                           labels=[0, 1, 2, 3, 4]).astype(float).fillna(2)

    # 수익률 (4)
    for n, col in [(1, 'r1'), (3, 'r3'), (6, 'r6'), (12, 'r12')]:
        f[col] = c.pct_change(n).fillna(0) * 100

    # 봉 패턴 (4)
    f['body']    = (bdy / cr).fillna(0).clip(0, 1)
    f['wick_lo'] = ((df[['open', 'close']].min(axis=1) - df['low']) / cr).fillna(0).clip(0, 1)
    f['wick_hi'] = ((df['high'] - df[['open', 'close']].max(axis=1)) / cr).fillna(0).clip(0, 1)
    f['bull']    = (c >= df['open']).astype(int)

    # 모멘텀 (3)
    f['ema_cross']   = ((e9 - e21) / e21 * 100).fillna(0)
    f['consec_bull'] = f['bull'].rolling(3).sum().fillna(0)
    f['price_accel'] = f['r1'].diff(1).fillna(0)

    # 거래량 / 변동성 (2)
    f['vol_r']     = (df['volume'] / vma).fillna(1).clip(0, 10)
    f['atr_ratio'] = (cr / cr.rolling(14).mean().replace(0, np.nan)).fillna(1).clip(0, 5)

    # 시간 (3)
    f['hour']     = df.index.hour
    f['is_block'] = ((df.index.hour == 8) | (df.index.hour == 9)).astype(int)
    f['bbw_lv']   = pd.cut(f['bb_width'], bins=[-np.inf, 2.0, 4.0, np.inf],
                           labels=[0, 1, 2]).astype(float).fillna(1)

    # ── v5.0 신규 피처 3개 ──

    # 1) VWAP 대비 현재가 괴리율 (%)
    #    VWAP = Σ(TP × Vol) / Σ(Vol), TP = (H+L+C)/3
    #    → 기관 매수/매도 압력 신호 (양수=매수우위, 음수=매도우위)
    tp = (df['high'] + df['low'] + df['close']) / 3
    cum_tpv = (tp * df['volume']).rolling(20).sum()
    cum_vol = df['volume'].rolling(20).sum().replace(0, np.nan)
    vwap = cum_tpv / cum_vol
    f['vwap_dist'] = ((c - vwap) / vwap * 100).fillna(0).clip(-10, 10)

    # 2) BB Width 3봉 변화율 (변동성 확대/축소 방향)
    #    양수 = 변동성 확대 중, 음수 = 변동성 축소 중
    f['bbw_change'] = wid.pct_change(3).fillna(0) * 100
    f['bbw_change'] = f['bbw_change'].clip(-50, 50)

    # 3) RSI Divergence (12봉 기준)
    #    가격 12봉 변화율 vs RSI 12봉 변화율의 부호 불일치 감지
    #    가격↓ but RSI↑ → 양의 다이버전스 (반등 신호) = 양수
    #    가격↑ but RSI↓ → 음의 다이버전스 (하락 신호) = 음수
    price_chg_12 = c.pct_change(12).fillna(0) * 100
    rsi_chg_12   = rsi.diff(12).fillna(0)
    # 정규화: 가격변화와 RSI변화의 방향 차이를 연속값으로 표현
    f['rsi_divergence'] = (rsi_chg_12 - price_chg_12 * 2).fillna(0).clip(-50, 50)

    return f[FEATURE_COLS].ffill().fillna(0)


# ============================================================================
# SECTION 6: Adaptive Threshold — BB Width 기반
# ============================================================================

def compute_adaptive_threshold(df, base_threshold=DEFAULT_THRESHOLD):
    """v4.0 계승: 변동성 기반 임계값 자동 조정"""
    if not ADAPTIVE_THR_ENABLED or df is None or len(df) < BB_PERIOD + 5:
        return base_threshold

    _, _, lo, rng, _, wid = _bb(df)
    recent_bbw = float(wid.iloc[-20:].mean())
    ratio = recent_bbw / ADAPTIVE_THR_BBW_REF
    adaptive = base_threshold * ratio
    adaptive = max(ADAPTIVE_THR_MIN, min(ADAPTIVE_THR_MAX, adaptive))
    return round(adaptive, 4)


# ============================================================================
# SECTION 7: 레이블 생성
# ============================================================================

def build_labels(df, threshold=DEFAULT_THRESHOLD):
    """threshold 기반 3분류 레이블 생성"""
    labels = pd.DataFrame(index=df.index)
    base = df['close']
    for n in range(1, PREDICT_STEPS + 1):
        fr = base.shift(-n).sub(base).div(base) * 100
        col = f'label_{n}'
        labels[col] = 0
        labels.loc[fr >  threshold, col] =  1
        labels.loc[fr < -threshold, col] = -1
    return labels


# ============================================================================
# SECTION 8: LGB 파라미터 관리
# ============================================================================

def _merge_lgb_params(overrides: dict = None, search_mode: bool = False) -> dict:
    """
    v5.0: search_mode=True면 탐색용 경량 파라미터 사용
    search_mode=False면 최종 학습용 풀 파라미터 사용
    """
    base = LGB_SEARCH_PARAMS.copy() if search_mode else LGB_BASE_PARAMS.copy()
    if overrides:
        base.update(overrides)
    return base


# ============================================================================
# SECTION 9: 모델 학습 (v5.0: search_mode 지원)
# ============================================================================

def train_models(df, threshold=DEFAULT_THRESHOLD, lgb_overrides=None,
                 verbose=True, feature_cols=None, search_mode=False):
    """
    전체 파이프라인: 피처 생성 → 학습
    v5.0: search_mode=True → 탐색용 경량 학습 (150트리, early_stop=10)
    """
    if verbose:
        pi("피처 엔지니어링 중...")

    feat = build_features(df)
    if feat is None:
        if verbose: pe("피처 생성 실패")
        return None

    return _train_from_features(feat, df, threshold, lgb_overrides,
                                verbose, feature_cols, search_mode)


def _train_from_features(feat, df_raw, threshold=DEFAULT_THRESHOLD,
                         lgb_overrides=None, verbose=False,
                         feature_cols=None, search_mode=False):
    """
    v5.0: search_mode 추가 — 탐색 시 경량 학습으로 40~50% 시간 단축
    """
    # 피처 서브셋 적용
    if feature_cols is not None:
        valid_cols = [c for c in feature_cols if c in feat.columns]
        if len(valid_cols) >= 10:
            feat = feat[valid_cols]

    labels    = build_labels(df_raw, threshold=threshold)
    valid_idx = feat.dropna().index.intersection(labels.dropna().index)
    valid_idx = valid_idx[:-PREDICT_STEPS] if len(valid_idx) > PREDICT_STEPS else valid_idx

    if len(valid_idx) < 60:
        if verbose: pe(f"학습 데이터 부족: {len(valid_idx)}행")
        return None

    X    = feat.loc[valid_idx]
    n_tr = int(len(X) * 0.75)
    X_tr = X.iloc[:n_tr]
    X_val = X.iloc[n_tr:]

    if verbose:
        mode_tag = " [경량]" if search_mode else ""
        pi(f"학습 {n_tr}행 / 검증 {len(X)-n_tr}행  "
           f"(threshold=±{threshold}%){mode_tag}")

    lgb_params = _merge_lgb_params(lgb_overrides, search_mode=search_mode)
    early_stop = LGB_SEARCH_EARLY_STOP if search_mode else 30
    models, scores = [], []

    for n in range(1, PREDICT_STEPS + 1):
        y    = labels.loc[valid_idx, f'label_{n}']
        y_tr = y.iloc[:n_tr]
        y_val = y.iloc[n_tr:]

        dist_info = dict(y_tr.value_counts().sort_index())

        if len(y_tr.unique()) < 2:
            if verbose: pw(f"t+{n}: 단일 클래스")
            models.append(None); scores.append(0.0)
            continue

        m = LGBMClassifier(**lgb_params)
        m.fit(X_tr, y_tr, eval_set=[(X_val, y_val)],
              callbacks=[lgb.early_stopping(early_stop, verbose=False),
                         lgb.log_evaluation(-1)])

        acc = float((m.predict(X_val) == y_val).mean())
        scores.append(acc)
        models.append(m)

        if verbose:
            col = C.GREEN if acc >= 0.55 else C.YELLOW if acc >= 0.48 else C.RED
            bar = f"{col}{'█'*int(acc*20)}{'░'*(20-int(acc*20))}{C.END}"
            print(f"  t+{n} (+{n*15}분): [{bar}] {acc:.1%}  레이블분포:{dist_info}")

    if verbose:
        vs  = [s for s in scores if s > 0]
        avg = np.mean(vs) if vs else 0
        print(f"\n  {C.BOLD}평균 검증 정확도: {avg:.1%}{C.END}")

    return models


# ============================================================================
# SECTION 10: 모델 저장 / 로드
# ============================================================================

def _mpath(coin, step):
    os.makedirs(MODEL_DIR, exist_ok=True)
    return os.path.join(MODEL_DIR, f"{coin}_15m_t{step}.pkl")


def save_models(models, coin, threshold=DEFAULT_THRESHOLD, lgb_overrides=None):
    n = 0
    for i, m in enumerate(models, 1):
        if m is not None:
            with open(_mpath(coin, i), 'wb') as f:
                pickle.dump({
                    'model': m,
                    'saved_at': datetime.now(),
                    'version': VERSION,
                    'threshold': threshold,
                    'lgb_overrides': lgb_overrides,
                }, f)
            n += 1
    ps(f"모델 저장: {n}개 → {MODEL_DIR}/{coin}_15m_t*.pkl")


def load_models(coin):
    """pkl 모델 로드 — version 불일치 시 None (재학습 유도)"""
    models = []
    for i in range(1, PREDICT_STEPS + 1):
        p = _mpath(coin, i)
        if not os.path.exists(p):
            return None
        try:
            with open(p, 'rb') as f:
                obj = pickle.load(f)
            ver = obj.get('version', '?')
            if ver not in (VERSION, '4.0', '3.0'):
                pw(f"모델 버전 불일치 (v{ver}) → 재학습 필요")
                return None
            models.append(obj['model'])
            age_h = (datetime.now() - obj['saved_at']).total_seconds() / 3600
            if age_h > 24:
                pw(f"모델 {age_h:.0f}시간 경과 — 재학습 권장")
        except Exception:
            return None
    return models


def get_or_train_models(df, coin, force=False, threshold=DEFAULT_THRESHOLD,
                        lgb_overrides=None, verbose=True):
    if not force:
        ms = load_models(coin)
        if ms:
            if verbose: ps(f"저장 모델 로드: {coin} (v{VERSION})")
            return ms
    if verbose: pi(f"모델 학습: {coin} ({len(df)}개 캔들, threshold=±{threshold}%)")
    ms = train_models(df, threshold=threshold, lgb_overrides=lgb_overrides,
                      verbose=verbose)
    if ms:
        save_models(ms, coin, threshold=threshold, lgb_overrides=lgb_overrides)
    return ms


# ============================================================================
# SECTION 11: 최적 파라미터 캐시 관리
# ============================================================================

def _cache_path(coin):
    os.makedirs(CACHE_DIR, exist_ok=True)
    return os.path.join(CACHE_DIR, f"{coin}_optimal.json")


def save_optimal_cache(coin, data: dict):
    data['coin'] = coin
    data['version'] = VERSION
    data['calibrated_at'] = datetime.now().isoformat()
    data['cache_valid_hours'] = CACHE_VALID_HOURS

    path = _cache_path(coin)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    ps(f"최적 파라미터 캐시 저장: {path}")


def load_optimal_cache(coin) -> dict | None:
    path = _cache_path(coin)
    if not os.path.exists(path):
        return None
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        ver = data.get('version', '?')
        if ver not in (VERSION, '4.0', '3.0'):
            pw(f"캐시 버전 불일치 (v{ver})")
            return None
        cal_at = datetime.fromisoformat(data['calibrated_at'])
        age_h  = (datetime.now() - cal_at).total_seconds() / 3600
        if age_h > CACHE_VALID_HOURS:
            pw(f"캐시 만료: {age_h:.1f}시간 경과 (유효: {CACHE_VALID_HOURS}시간)")
            return None
        data['_age_hours'] = age_h
        return data
    except Exception as e:
        pw(f"캐시 로드 실패: {e}")
        return None


# ============================================================================
# SECTION 12: 예측 엔진 (v5.0: predict_from_features 신설)
# ============================================================================

DIR_ICON = {1: '🟢', -1: '🔴', 0: '⚪'}
DIR_KOR  = {1: '상승', -1: '하락', 0: '중립'}
DIR_ENG  = {1: 'UP',  -1: 'DOWN',  0: 'NEUTRAL'}


def predict_from_features(feat_row, models):
    """
    v5.0 신규: 사전계산된 피처 1행으로 직접 예측 (build_features 호출 없음)
    - 백테스트 내부에서 사용 → 핵심 속도 개선점
    - feat_row: DataFrame (1행) 또는 Series
    """
    if feat_row is None:
        return None

    if isinstance(feat_row, pd.Series):
        X = feat_row.to_frame().T
    elif isinstance(feat_row, pd.DataFrame):
        X = feat_row.iloc[[-1]] if len(feat_row) > 1 else feat_row
    else:
        return None

    results = []
    for i, m in enumerate(models, 1):
        if m is None:
            results.append({'step': i, 'label': 0, 'prob_up': 0.33,
                            'prob_neu': 0.34, 'prob_dn': 0.33,
                            'max_prob': 0.34, 'conf': '낮음'})
            continue

        # 모델 피처 정렬
        model_features = m.feature_name_
        X_aligned = X.reindex(columns=model_features, fill_value=0)

        proba   = m.predict_proba(X_aligned)[0]
        classes = list(m.classes_)
        pd_     = dict(zip([int(c) for c in classes], proba.tolist()))
        label   = int(classes[np.argmax(proba)])
        maxp    = float(np.max(proba))
        conf    = '높음' if maxp >= 0.55 else '중간' if maxp >= 0.45 else '낮음'
        results.append({
            'step': i, 'label': label,
            'prob_up':  pd_.get( 1, 0.0),
            'prob_neu': pd_.get( 0, 0.0),
            'prob_dn':  pd_.get(-1, 0.0),
            'max_prob': maxp, 'conf': conf,
        })

    return results


def predict_single(df, models):
    """기존 API 호환: df에서 피처 생성 후 마지막 행 예측"""
    feat = build_features(df)
    if feat is None or len(feat) == 0:
        return None
    return predict_from_features(feat.iloc[[-1]], models)


def compute_signal(results):
    """t+1~t+3 기반 종합 신호"""
    votes  = [r['label'] for r in results[:3]]
    avg_up = np.mean([r['prob_up'] for r in results[:3]])
    avg_dn = np.mean([r['prob_dn'] for r in results[:3]])
    up_v   = votes.count(1)
    dn_v   = votes.count(-1)
    if up_v >= 2 and avg_up > avg_dn:
        return f"🟢 단기 매수  (UP {up_v}/3)", "BUY"
    elif dn_v >= 2 and avg_dn > avg_up:
        return f"🔴 단기 매도  (DOWN {dn_v}/3)", "SELL"
    else:
        return "⚪ 관망  (신호 불명확)", "NEUTRAL"


# ============================================================================
# SECTION 13: 백테스트 엔진 (v5.0: 풀 피처 사전계산 방식)
# ============================================================================

def _bt_single_from_pool_v5(pool_feat, pool_df, offset_idx, pred_count,
                             models, threshold):
    """
    v5.0 핵심 개선: 사전계산된 피처풀에서 직접 슬라이싱
    - build_features() 호출 0회 (v4: 매 호출마다 1회)
    - pool_feat: 전체 데이터풀의 사전계산 피처 DataFrame
    - pool_df: 전체 데이터풀 원본 (미래 가격 확인용)
    """
    start_idx = offset_idx - pred_count
    if start_idx < 0 or offset_idx > len(pool_feat):
        return None

    # 예측 시점의 피처 (마지막 행)
    feat_idx = offset_idx - 1  # 0-based
    if feat_idx < 0 or feat_idx >= len(pool_feat):
        return None

    feat_row = pool_feat.iloc[[feat_idx]]

    preds = predict_from_features(feat_row, models)
    if preds is None:
        return None

    base_price = float(pool_df['close'].iloc[feat_idx])
    last_dt    = pool_df.index[feat_idx]

    # 미래 캔들
    future_start = offset_idx
    future_end   = min(offset_idx + PREDICT_STEPS, len(pool_df))
    if future_end - future_start < PREDICT_STEPS:
        return None

    actuals, matches, act_rets = [], [], []
    for n in range(PREDICT_STEPS):
        actual_close = float(pool_df['close'].iloc[future_start + n])
        actual_ret   = (actual_close - base_price) / base_price * 100
        act_rets.append(round(actual_ret, 4))
        al = 1 if actual_ret > threshold else -1 if actual_ret < -threshold else 0
        actuals.append(al)
        matches.append(preds[n]['label'] == al)

    return {
        'predictions': preds, 'actuals': actuals,
        'matches': matches, 'actual_returns': act_rets,
        'base_price': base_price, 'anchor_dt': last_dt,
    }


def _bt_sliding_from_pool_v5(pool_feat, pool_df, base_idx, pred_count,
                              slide_n, models, threshold):
    """v5.0: 사전계산 피처풀 기반 슬라이딩 백테스트 (build_features 0회)"""
    all_results = []
    for i in range(slide_n):
        r = _bt_single_from_pool_v5(pool_feat, pool_df,
                                     base_idx - i, pred_count,
                                     models, threshold)
        if r:
            all_results.append(r)

    if not all_results:
        return None

    n_ok = len(all_results)
    step_matches = [[] for _ in range(PREDICT_STEPS)]
    all_pred_labels, all_actual_labels = [], []
    virt_profits = []
    all_actual_rets = [[] for _ in range(PREDICT_STEPS)]

    for r in all_results:
        for s in range(PREDICT_STEPS):
            step_matches[s].append(r['matches'][s])
            all_pred_labels.append(r['predictions'][s]['label'])
            all_actual_labels.append(r['actuals'][s])
            all_actual_rets[s].append(r['actual_returns'][s])
        # 가상 매매 (t+1 기준)
        t1_pred = r['predictions'][0]['label']
        t1_ret  = r['actual_returns'][0]
        if t1_pred == 1:
            virt_profits.append(t1_ret)
        elif t1_pred == -1:
            virt_profits.append(-t1_ret)

    def precision(pred_list, actual_list, cls):
        pa, aa = np.array(pred_list), np.array(actual_list)
        tp = np.sum((pa == cls) & (aa == cls))
        fp = np.sum((pa == cls) & (aa != cls))
        return tp / (tp + fp) if (tp + fp) > 0 else 0.0

    ret_stats = {}
    for s in range(PREDICT_STEPS):
        rets = np.array(all_actual_rets[s])
        ret_stats[s + 1] = {
            'mean':   float(np.mean(rets)),
            'std':    float(np.std(rets)),
            'q25':    float(np.percentile(rets, 25)),
            'median': float(np.median(rets)),
            'q75':    float(np.percentile(rets, 75)),
            'pos_r':  float((rets > 0).mean()),
        }

    return {
        'n_ok': n_ok, 'sliding_n': slide_n,
        'step_accs':     [np.mean(step_matches[s]) for s in range(PREDICT_STEPS)],
        'total_acc':     np.mean([m for ms in step_matches for m in ms]),
        'prec_up':       precision(all_pred_labels, all_actual_labels, 1),
        'prec_down':     precision(all_pred_labels, all_actual_labels, -1),
        'prec_neu':      precision(all_pred_labels, all_actual_labels, 0),
        'virt_total':    sum(virt_profits) if virt_profits else 0.0,
        'virt_count':    len(virt_profits),
        'virt_win_rate': float(np.mean([p > 0 for p in virt_profits])) if virt_profits else 0.0,
        'ret_stats':     ret_stats,
        'all_results':   all_results,
    }


# ============================================================================
# SECTION 14: EV-aware 종합 점수 계산 (v4.0 동일)
# ============================================================================

def _score_combo(avg_acc, std_acc, avg_virt, virt_win):
    """
    v4.0 계승: EV(기대값) 직접 반영
    적중률 35% + 안정성 15% + 가상수익(EV proxy) 25% + 승률 25%
    EV 음수 시 추가 페널티: 점수 최대 40% 삭감
    """
    acc_score  = min(avg_acc * 100, 100) * 0.35
    std_score  = max(0, (1 - std_acc * 5) * 100) * 0.15
    virt_score = min(max(avg_virt * 20 + 50, 0), 100) * 0.25
    win_score  = min(virt_win * 100, 100) * 0.25

    base_score = acc_score + std_score + virt_score + win_score

    if avg_virt < 0:
        penalty_rate = min(abs(avg_virt) * 0.5, 0.40)
        base_score *= (1.0 - penalty_rate)

    return round(base_score, 1)


# ============================================================================
# SECTION 15: 통계 집계 (Stage 1, Stage 2 공용)
# ============================================================================

def _aggregate_combo_results(combo_stats):
    """조합별 통계 집계"""
    if not combo_stats:
        return None

    accs      = [s['total_acc']     for s in combo_stats]
    virts     = [s['virt_total']    for s in combo_stats]
    virt_wins = [s['virt_win_rate'] for s in combo_stats]
    step_accs_all = list(zip(*[s['step_accs'] for s in combo_stats]))

    avg_acc  = float(np.mean(accs))
    std_acc  = float(np.std(accs))
    avg_virt = float(np.mean(virts))
    avg_vwin = float(np.mean(virt_wins))
    step_avgs = [float(np.mean(s)) for s in step_accs_all]

    # 수익률 분포
    all_rets = {n: [] for n in range(1, PREDICT_STEPS + 1)}
    hit_rets, miss_rets = [], []
    for s in combo_stats:
        for r in s['all_results']:
            for n in range(PREDICT_STEPS):
                all_rets[n + 1].append(r['actual_returns'][n])
                ret = r['actual_returns'][n]
                if r['matches'][n]:
                    hit_rets.append(ret)
                else:
                    miss_rets.append(ret)

    ret_dist = {}
    for n in range(1, PREDICT_STEPS + 1):
        rets = np.array(all_rets[n])
        ret_dist[n] = {
            'mean':  float(np.mean(rets)),
            'std':   float(np.std(rets)),
            'pos_r': float((rets > 0).mean()),
            'q25':   float(np.percentile(rets, 25)),
            'q75':   float(np.percentile(rets, 75)),
        }

    # 시간대별 적중률
    hour_hits = {}
    for s in combo_stats:
        for r in s['all_results']:
            h = r['anchor_dt'].hour
            zone = ('새벽(0-6)'   if 0  <= h < 6  else
                    '오전(6-12)'  if 6  <= h < 12 else
                    '오후(12-18)' if 12 <= h < 18 else '야간(18-24)')
            hour_hits.setdefault(zone, []).append(np.mean(r['matches']))
    hour_acc = {z: float(np.mean(v)) for z, v in hour_hits.items() if v}

    score = _score_combo(avg_acc, std_acc, avg_virt, avg_vwin)

    return {
        'avg_acc':   avg_acc,
        'std_acc':   std_acc,
        'avg_virt':  avg_virt,
        'avg_vwin':  avg_vwin,
        'step_avgs': step_avgs,
        'ret_dist':  ret_dist,
        'hour_acc':  hour_acc,
        'hit_avg':   float(np.mean(hit_rets))  if hit_rets  else 0.0,
        'miss_avg':  float(np.mean(miss_rets)) if miss_rets else 0.0,
        'score':     score,
        'n_combos':  len(combo_stats),
    }


# ============================================================================
# SECTION 16: Stage 1 — 2-Phase 그리드 탐색 (v5.0 핵심 개선)
# ============================================================================

def run_stage1_grid(ticker: str) -> dict | None:
    """
    v5.0 핵심: 2-Phase 그리드 탐색
    Phase A: 빠른 스크리닝 (3 offset, slide 8, 경량 LGB)
    Phase B: 상위 N개 조합만 정밀 검증 (5 offset, slide 20, 경량 LGB)
    → 전체 학습/백테스트 횟수 70~80% 감소
    """
    coin = ticker.replace('KRW-', '')
    max_train = max(S1_TRAIN_COUNTS)
    max_pred  = max(S1_PRED_COUNTS)
    n_data_combos = len(S1_TRAIN_COUNTS) * len(S1_PRED_COUNTS) * len(S1_THRESHOLDS)
    total_a = n_data_combos * len(S1_OFFSETS_QUICK)

    ph(f"🔬 Stage 1: 2-Phase 데이터 파라미터 탐색  [{coin}]")
    print(f"  {C.DIM}train {S1_TRAIN_COUNTS} × pred {S1_PRED_COUNTS} "
          f"× threshold {S1_THRESHOLDS}{C.END}")
    print(f"  {C.GREEN}★ v5.0: Phase A 빠른 스크리닝 → Phase B 정밀 검증{C.END}")
    print(f"  {C.GREEN}★ 풀 피처 사전계산 + 탐색용 경량 LGB{C.END}")
    print(f"  {C.DIM}Phase A: {len(S1_OFFSETS_QUICK)}시점 × slide {S1_SLIDE_QUICK}  |  "
          f"Phase B: 상위{S1_PHASE_A_TOP_N}개 → {len(S1_OFFSETS_FULL)}시점 × "
          f"slide {S1_SLIDE_FULL}{C.END}\n")

    start_t = time.time()

    # ━━━ Phase A: 빠른 스크리닝 ━━━
    pi("Phase A: 데이터 사전수집 (핵심 시점)...")
    need_candles = max_train + max_pred + S1_SLIDE_FULL + PREDICT_STEPS + 50
    offset_data = {}       # {offset: DataFrame}
    offset_feat = {}       # {offset: {train_c: feat_DataFrame}}  ← v5.0 핵심

    for off in S1_OFFSETS_QUICK:
        future_to = get_anchor_to_str(max(0, off - max_pred - PREDICT_STEPS - 10))
        df = fetch_candles_15m(ticker, need_candles, to=future_to)
        if df is not None and len(df) >= max_train + max_pred:
            offset_data[off] = df
            # v5.0: 풀 피처 사전계산 (offset × train_c 조합마다 1회)
            offset_feat[off] = {}
            for train_c in S1_TRAIN_COUNTS:
                if len(df) >= train_c:
                    pool_feat = build_features(df)
                    if pool_feat is not None:
                        offset_feat[off][train_c] = pool_feat
            print(f"\r  {C.CYAN}  {bars_to_time(off)}: {len(df)}개 수집 + "
                  f"피처 사전계산{C.END}     ", end='', flush=True)

    elapsed_fetch = time.time() - start_t
    print(f"\r  {C.GREEN}Phase A 수집 완료: {len(offset_data)}/{len(S1_OFFSETS_QUICK)} "
          f"시점  ({elapsed_fetch:.0f}초){C.END}          ")

    if not offset_data:
        pe("데이터 수집 실패")
        return None

    # Phase A 그리드 탐색 (경량 LGB + 사전계산 피처)
    pi("Phase A: 빠른 스크리닝 중...")
    combo_map = {}
    job_no = 0

    for train_c in S1_TRAIN_COUNTS:
        for pred_c in S1_PRED_COUNTS:
            for off in S1_OFFSETS_QUICK:
                if off not in offset_data:
                    job_no += len(S1_THRESHOLDS)
                    continue

                df_full = offset_data[off]
                total_need = train_c + pred_c + S1_SLIDE_QUICK + PREDICT_STEPS
                if len(df_full) < total_need:
                    job_no += len(S1_THRESHOLDS)
                    continue

                df_train_slice = df_full.iloc[:train_c]
                if len(df_train_slice) < MIN_TRAIN:
                    job_no += len(S1_THRESHOLDS)
                    continue

                # v5.0: 사전계산 피처 재사용 (train 영역용)
                feat = offset_feat.get(off, {}).get(train_c)
                if feat is None:
                    feat = build_features(df_train_slice)
                    if feat is None:
                        job_no += len(S1_THRESHOLDS)
                        continue
                else:
                    # train 영역 피처만 추출
                    feat = feat.iloc[:train_c]

                # v5.0: 풀 피처 (백테스트용 — 전체 데이터풀)
                pool_feat = offset_feat.get(off, {}).get(train_c)
                if pool_feat is None:
                    pool_feat = build_features(df_full)

                bt_base_idx = train_c + pred_c

                for threshold in S1_THRESHOLDS:
                    job_no += 1
                    print(f"\r  {C.CYAN}Phase A: {job_no}/{total_a}  "
                          f"[train={train_c} pred={pred_c} thr=±{threshold}% "
                          f"off={bars_to_time(off)}]{C.END}   ",
                          end='', flush=True)

                    # v5.0: 경량 LGB (search_mode=True)
                    models = _train_from_features(feat, df_train_slice,
                                                  threshold=threshold,
                                                  search_mode=True)
                    if not models:
                        continue

                    # v5.0: 사전계산 피처풀 기반 백테스트
                    stats = _bt_sliding_from_pool_v5(
                        pool_feat, df_full, bt_base_idx, pred_c,
                        S1_SLIDE_QUICK, models, threshold
                    )
                    if stats and stats['n_ok'] >= S1_SLIDE_QUICK * S1_MIN_PASS_RATE:
                        key = f"{train_c}_{pred_c}_{threshold}"
                        if key not in combo_map:
                            combo_map[key] = {
                                'train': train_c, 'pred': pred_c,
                                'threshold': threshold, 'stats': []
                            }
                        combo_map[key]['stats'].append(stats)

    # Phase A 결과 집계 + 상위 N개 선별
    phase_a_results = []
    for key, combo in combo_map.items():
        agg = _aggregate_combo_results(combo['stats'])
        if agg:
            agg['train']     = combo['train']
            agg['pred']      = combo['pred']
            agg['threshold'] = combo['threshold']
            agg['_key']      = key
            phase_a_results.append(agg)

    phase_a_results.sort(key=lambda x: x['score'], reverse=True)
    elapsed_a = time.time() - start_t

    print(f"\r  {C.GREEN}Phase A 완료: {job_no}건 탐색, "
          f"{len(phase_a_results)}개 유효  ({elapsed_a:.0f}초){C.END}          ")

    if not phase_a_results:
        pe("Stage 1 Phase A: 유효 결과 없음")
        return None

    # Phase A 상위 결과 요약 출력
    print(f"\n  {C.BOLD}[ Phase A 상위 {min(S1_PHASE_A_TOP_N, len(phase_a_results))}개 "
          f"→ Phase B 정밀 검증 ]{C.END}")
    for rank, r in enumerate(phase_a_results[:S1_PHASE_A_TOP_N], 1):
        ac = C.GREEN if r['avg_acc'] >= 0.55 else C.YELLOW
        print(f"  {rank}위: train={r['train']} pred={r['pred']} "
              f"thr=±{r['threshold']}%  {ac}{r['avg_acc']:.1%}{C.END}  "
              f"점수 {r['score']:.1f}")

    # ━━━ Phase B: 정밀 검증 (상위 N개만) ━━━
    top_combos = phase_a_results[:S1_PHASE_A_TOP_N]

    pi(f"\nPhase B: 상위 {len(top_combos)}개 조합 정밀 검증...")
    pi("추가 시점 데이터 수집 중...")

    # Phase B에 필요한 추가 offset 수집
    need_offsets = [o for o in S1_OFFSETS_FULL if o not in offset_data]
    for off in need_offsets:
        future_to = get_anchor_to_str(max(0, off - max_pred - PREDICT_STEPS - 10))
        df = fetch_candles_15m(ticker, need_candles, to=future_to)
        if df is not None and len(df) >= max_train + max_pred:
            offset_data[off] = df
            offset_feat[off] = {}
            for train_c in S1_TRAIN_COUNTS:
                if len(df) >= train_c:
                    pool_feat_b = build_features(df)
                    if pool_feat_b is not None:
                        offset_feat[off][train_c] = pool_feat_b
            print(f"\r  {C.CYAN}  {bars_to_time(off)}: {len(df)}개 수집{C.END}     ",
                  end='', flush=True)

    ps(f"수집 완료: {len(offset_data)} 시점")

    total_b = len(top_combos) * len(S1_OFFSETS_FULL)
    job_no = 0
    phase_b_results = []

    for combo_agg in top_combos:
        train_c   = combo_agg['train']
        pred_c    = combo_agg['pred']
        threshold = combo_agg['threshold']
        combo_stats = []

        for off in S1_OFFSETS_FULL:
            job_no += 1
            print(f"\r  {C.CYAN}Phase B: {job_no}/{total_b}  "
                  f"[train={train_c} pred={pred_c} thr=±{threshold}% "
                  f"off={bars_to_time(off)}]{C.END}   ",
                  end='', flush=True)

            if off not in offset_data:
                continue

            df_full = offset_data[off]
            total_need = train_c + pred_c + S1_SLIDE_FULL + PREDICT_STEPS
            if len(df_full) < total_need:
                continue

            df_train_slice = df_full.iloc[:train_c]
            if len(df_train_slice) < MIN_TRAIN:
                continue

            feat = offset_feat.get(off, {}).get(train_c)
            if feat is None:
                feat = build_features(df_train_slice)
                if feat is None:
                    continue
            else:
                feat = feat.iloc[:train_c]

            pool_feat_b = offset_feat.get(off, {}).get(train_c)
            if pool_feat_b is None:
                pool_feat_b = build_features(df_full)

            bt_base_idx = train_c + pred_c

            # Phase B도 경량 LGB 사용 (최종 학습에서만 풀 LGB)
            models = _train_from_features(feat, df_train_slice,
                                          threshold=threshold,
                                          search_mode=True)
            if not models:
                continue

            stats = _bt_sliding_from_pool_v5(
                pool_feat_b, df_full, bt_base_idx, pred_c,
                S1_SLIDE_FULL, models, threshold
            )
            if stats and stats['n_ok'] >= S1_SLIDE_FULL * S1_MIN_PASS_RATE:
                combo_stats.append(stats)

        agg = _aggregate_combo_results(combo_stats)
        if agg:
            agg['train']     = train_c
            agg['pred']      = pred_c
            agg['threshold'] = threshold
            phase_b_results.append(agg)

    elapsed = time.time() - start_t
    print(f"\r  {C.GREEN}Stage 1 완료 (Phase A+B): 소요 {elapsed:.0f}초{C.END}          ")

    if not phase_b_results:
        # Phase B 실패 시 Phase A 결과 사용
        pw("Phase B 결과 없음 → Phase A 최적 결과 사용")
        phase_b_results = phase_a_results

    phase_b_results.sort(key=lambda x: x['score'], reverse=True)
    return {
        'ticker':  ticker,
        'results': phase_b_results,
        'best':    phase_b_results[0],
        'elapsed': elapsed,
        'phase_a_count': len(phase_a_results),
        'phase_b_count': len(phase_b_results),
    }


# ============================================================================
# SECTION 17: Stage 2 — LGB 하이퍼파라미터 그리드 탐색
# ============================================================================

def run_stage2_grid(ticker: str, train_c: int, pred_c: int,
                    threshold: float) -> dict | None:
    """
    Stage 2: LGB HP 탐색 (Stage 1 최적 데이터 파라미터 고정)
    v5.0: 사전계산 피처풀 + 경량 LGB
    """
    coin = ticker.replace('KRW-', '')
    combos = [(d, l, lr) for d in S2_DEPTHS for l in S2_LEAVES for lr in S2_LRS]
    total_jobs = len(combos) * len(S2_OFFSETS)

    ph(f"🔬 Stage 2: LGB 하이퍼파라미터 탐색  [{coin}]")
    print(f"  {C.DIM}Stage 1 최적: train={train_c} / pred={pred_c} / "
          f"threshold=±{threshold}% (고정){C.END}")
    print(f"  {C.DIM}depth {S2_DEPTHS} × leaves {S2_LEAVES} × lr {S2_LRS}{C.END}\n")

    start_t = time.time()

    # 데이터 + 피처 사전수집 (v5.0: 풀 피처 1회 계산)
    pi("데이터 + 풀 피처 사전수집...")
    need = train_c + pred_c + S2_SLIDE_N + PREDICT_STEPS + 50
    offset_prepared = {}  # {offset: (df_full, df_train, feat_train, pool_feat)}

    for off in S2_OFFSETS:
        future_to = get_anchor_to_str(max(0, off - pred_c - PREDICT_STEPS - 10))
        df = fetch_candles_15m(ticker, need, to=future_to)
        if df is not None and len(df) >= train_c + pred_c:
            df_train = df.iloc[:train_c]
            feat = build_features(df_train)
            pool_feat = build_features(df)  # v5.0: 풀 피처 (백테스트용)
            if feat is not None and pool_feat is not None:
                offset_prepared[off] = (df, df_train, feat, pool_feat)

    ps(f"수집 완료: {len(offset_prepared)}/{len(S2_OFFSETS)}")
    if not offset_prepared:
        return None

    grid_results = []
    job_no = 0

    for depth, leaves, lr in combos:
        lgb_over = {
            'max_depth': depth,
            'num_leaves': leaves,
            'learning_rate': lr,
        }
        combo_stats = []

        for off in S2_OFFSETS:
            job_no += 1
            print(f"\r  {C.CYAN}탐색: {job_no}/{total_jobs}  "
                  f"[depth={depth} leaves={leaves} lr={lr}]{C.END}   ",
                  end='', flush=True)

            if off not in offset_prepared:
                continue

            df_full, df_train, feat, pool_feat = offset_prepared[off]

            # v5.0: 경량 LGB + HP 오버라이드
            models = _train_from_features(feat, df_train, threshold=threshold,
                                          lgb_overrides=lgb_over,
                                          search_mode=True)
            if not models:
                continue

            # v5.0: 사전계산 피처풀 기반 백테스트
            stats = _bt_sliding_from_pool_v5(
                pool_feat, df_full, train_c + pred_c, pred_c,
                S2_SLIDE_N, models, threshold
            )
            if stats and stats['n_ok'] >= S2_SLIDE_N * S1_MIN_PASS_RATE:
                combo_stats.append(stats)

        agg = _aggregate_combo_results(combo_stats)
        if agg:
            agg['lgb_overrides'] = lgb_over
            grid_results.append(agg)

    elapsed = time.time() - start_t
    print(f"\r  {C.GREEN}Stage 2 완료: {job_no}건 탐색  소요 {elapsed:.0f}초{C.END}          ")

    if not grid_results:
        pw("Stage 2: 유효 결과 없음 — LGB 기본값 유지")
        return None

    grid_results.sort(key=lambda x: x['score'], reverse=True)
    return {
        'ticker':  ticker,
        'results': grid_results,
        'best':    grid_results[0],
        'elapsed': elapsed,
    }


# ============================================================================
# SECTION 18: Quick Validation (캐시 유효성 검증)
# ============================================================================

def quick_validate(ticker: str, cache: dict) -> bool:
    """캐시 파라미터로 최근 데이터 빠른 검증"""
    coin      = ticker.replace('KRW-', '')
    train_c   = cache['optimal_train']
    pred_c    = cache['optimal_pred']
    threshold = cache['optimal_threshold']
    lgb_over  = cache.get('optimal_lgb')
    saved_acc = cache.get('backtest_avg_acc', 0.0)

    pi("Quick Validation 실행 중... (최근 데이터, 슬라이딩 5회)")

    need = train_c + pred_c + 10 + PREDICT_STEPS + 20
    df = fetch_candles_15m(ticker, need)
    if df is None or len(df) < train_c + pred_c:
        pw("Quick Validation: 데이터 부족 → 재탐색 권장")
        return False

    df_train = df.iloc[:train_c]
    models = train_models(df_train, threshold=threshold,
                          lgb_overrides=lgb_over, verbose=False)
    if not models:
        pw("Quick Validation: 모델 학습 실패 → 재탐색 권장")
        return False

    # v5.0: 풀 피처 사전계산 방식 사용
    pool_feat = build_features(df)
    if pool_feat is None:
        pw("Quick Validation: 피처 생성 실패")
        return False

    stats = _bt_sliding_from_pool_v5(pool_feat, df, train_c + pred_c,
                                      pred_c, 5, models, threshold)
    if stats is None or stats['n_ok'] < 3:
        pw("Quick Validation: 백테스트 결과 부족 → 재탐색 권장")
        return False

    current_acc = stats['total_acc']
    drop = saved_acc - current_acc

    if drop > QUICK_VAL_DROP_THRESHOLD:
        pw(f"Quick Validation: 적중률 하락 ({saved_acc:.1%} → {current_acc:.1%}, "
           f"Δ{-drop:+.1%}) → 재탐색 필요")
        return False

    ac = C.GREEN if current_acc >= saved_acc else C.YELLOW
    ps(f"Quick Validation 통과: 적중률 {ac}{current_acc:.1%}{C.END}  "
       f"(저장: {saved_acc:.1%}, Δ{-drop:+.1%})")
    return True


# ============================================================================
# SECTION 19: 결과 출력
# ============================================================================

def _bar(prob, w=12):
    n = int(prob * w)
    return '█' * n + '░' * (w - n)


def print_prediction_result(results, ticker, pred_count, threshold=DEFAULT_THRESHOLD):
    coin = ticker.replace('KRW-', '')
    ph(f"📈 {coin} 15분봉 예측 결과  ({pred_count}개 기준  /  ±{threshold}%)")
    print(f"  기준 시각: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} KST\n")

    print(f"  {'구간':<12} {'예측':^7}  "
          f"{'▲ UP%':^15}  {'━ NEU%':^15}  {'▼ DN%':^15}  신뢰")
    print(f"  {'─'*76}")

    for r in results:
        n     = r['step']
        label = r['label']
        p_up  = r['prob_up']
        p_neu = r['prob_neu']
        p_dn  = r['prob_dn']
        conf  = r['conf']
        max_p = max(p_up, p_neu, p_dn)

        cu = C.GREEN  if p_up  == max_p and label == 1  else (C.GREEN  if p_up  > 0.38 else C.DIM)
        cn = C.YELLOW if p_neu == max_p and label == 0  else (C.YELLOW if p_neu > 0.38 else C.DIM)
        cd = C.RED    if p_dn  == max_p and label == -1 else (C.RED    if p_dn  > 0.38 else C.DIM)
        cc = C.GREEN  if conf == '높음' else C.YELLOW if conf == '중간' else C.DIM

        print(
            f"  t+{n} (+{n*15:<4}분)  "
            f"{DIR_ICON[label]}{DIR_KOR[label]:^5}  "
            f"{cu}{_bar(p_up)} {p_up:.0%}{C.END}  "
            f"{cn}{_bar(p_neu)} {p_neu:.0%}{C.END}  "
            f"{cd}{_bar(p_dn)} {p_dn:.0%}{C.END}  "
            f"{cc}{conf}{C.END}"
        )

    print(f"\n  {'─'*76}")
    sig_str, sig_eng = compute_signal(results)
    print(f"  {C.BOLD}종합 신호: {sig_str}{C.END}")
    hint = ("진입 우선 탐색 권장" if sig_eng == 'BUY'
            else "진입 보류 / 매도 검토" if sig_eng == 'SELL'
            else "추가 신호 확인 후 판단")
    print(f"  BB Bounce 연계: {hint}")


def print_feature_importance(models, top_n=15):
    """v5.0: 상위 15개 표시 (v4: 12개)"""
    m = next((x for x in models if x is not None), None)
    if m is None:
        return
    imp   = m.feature_importances_
    names = m.feature_name_
    total = max(sum(imp), 1)
    ranked = sorted(zip(names, imp), key=lambda x: x[1], reverse=True)[:top_n]
    max_i  = ranked[0][1] if ranked else 1

    ph("🔍 피처 중요도 (t+1 모델 기준)")
    for feat_name, val in ranked:
        bl  = int(val / max_i * 28)
        bar = f"{C.CYAN}{'█'*bl}{'░'*(28-bl)}{C.END}"
        pct = val / total * 100
        # v5.0 신규 피처 표시
        is_new = feat_name in ('vwap_dist', 'bbw_change', 'rsi_divergence')
        new_tag = f" {C.MAGENTA}★NEW{C.END}" if is_new else ""
        marker = f" {C.RED}◀ prune 대상{C.END}" if pct < FEATURE_PRUNE_MIN_IMPORTANCE * 100 else ""
        print(f"  {feat_name:<20}  {bar}  {pct:.1f}%{new_tag}{marker}")


def print_stage1_report(data: dict):
    """Stage 1 보고서 (v5.0: Phase A/B 정보 포함)"""
    ticker  = data['ticker']
    coin    = ticker.replace('KRW-', '')
    results = data['results']
    best    = data['best']
    elapsed = data['elapsed']

    ph(f"📊 Stage 1 분석 보고서  [{coin}]")
    pa_count = data.get('phase_a_count', '?')
    pb_count = data.get('phase_b_count', '?')
    print(f"  Phase A 유효: {pa_count}조합 → Phase B 정밀: {pb_count}조합"
          f"  |  총 소요: {elapsed:.0f}초\n")

    # 랭킹 (상위 10)
    print(f"  {C.BOLD}[ 파라미터 조합별 성능 랭킹 (상위 10) ]{C.END}")
    print(f"  {'순위':<4} {'학습수':>5} {'예측수':>5} {'임계값':>6}  "
          f"{'평균적중':>8} {'안정성':>8} {'가상수익':>8} {'승률':>6} {'종합점수':>8}")
    print(f"  {'─'*72}")

    for rank, r in enumerate(results[:10], 1):
        ac = C.GREEN if r['avg_acc'] >= 0.55 else C.YELLOW if r['avg_acc'] >= 0.48 else C.RED
        sc = C.GREEN if r['avg_virt'] > 0 else C.RED
        wc = C.GREEN if r['avg_vwin'] >= 0.55 else C.YELLOW if r['avg_vwin'] >= 0.45 else C.DIM
        zc = C.GREEN if rank == 1 else C.YELLOW if rank == 2 else C.DIM
        star = f"{C.BOLD}★ {C.END}" if rank == 1 else "  "
        print(
            f"  {star}{C.BOLD}{rank:>2}{C.END}위  "
            f"{r['train']:>5}개  {r['pred']:>5}개  ±{r['threshold']:.2f}%  "
            f"{ac}{r['avg_acc']:>7.1%}{C.END}  "
            f"{C.DIM}±{r['std_acc']:.2f}{C.END}  "
            f"{sc}{r['avg_virt']:>+7.4f}%{C.END}  "
            f"{wc}{r['avg_vwin']:>5.1%}{C.END}  "
            f"{zc}{r['score']:>7.1f}점{C.END}"
        )

    # 최적 상세
    print(f"\n  {C.BOLD}[ ★ 최적 파라미터 상세 ]{C.END}")
    print(f"  학습: {best['train']}개 / 예측기준: {best['pred']}개 / "
          f"임계값: ±{best['threshold']}%  (점수 {best['score']:.1f}점)")

    print(f"\n  구간별 평균 적중률:")
    best_step, best_step_acc = 0, 0.0
    for s, acc in enumerate(best['step_avgs'], 1):
        bc  = C.GREEN if acc >= 0.60 else C.YELLOW if acc >= 0.50 else C.RED
        bar = f"{bc}{'█'*int(acc*30)}{'░'*(30-int(acc*30))}{C.END}"
        icon = "📈" if acc >= 0.60 else "📊" if acc >= 0.50 else "📉"
        print(f"  t+{s} (+{s*15}분) {icon}  {bar}  {bc}{acc:.1%}{C.END}")
        if acc > best_step_acc:
            best_step_acc = acc
            best_step = s

    # 기대값 (EV)
    hit_avg  = best['hit_avg']
    miss_avg = best['miss_avg']
    avg_acc  = best['avg_acc']
    ev = avg_acc * hit_avg + (1 - avg_acc) * miss_avg

    print(f"\n  기대값 (t+1 기반): ", end='')
    ec = C.GREEN if ev > 0 else C.RED
    print(f"{ec}{ev:+.4f}%{C.END}  "
          f"{C.DIM}= {avg_acc:.0%}×({hit_avg:+.4f}%) + {1-avg_acc:.0%}×({miss_avg:+.4f}%){C.END}")

    # 시간대별
    hour_acc = best.get('hour_acc', {})
    if hour_acc:
        print(f"\n  시간대별 예측력:")
        for zone in ['새벽(0-6)', '오전(6-12)', '오후(12-18)', '야간(18-24)']:
            acc = hour_acc.get(zone)
            if acc is None:
                continue
            bc  = C.GREEN if acc >= 0.60 else C.YELLOW if acc >= 0.50 else C.RED
            bar = f"{bc}{'█'*int(acc*20)}{'░'*(20-int(acc*20))}{C.END}"
            print(f"  {zone:<12}  {bar}  {bc}{acc:.1%}{C.END}")

    return best_step, best_step_acc, ev


def print_stage2_report(data: dict):
    """Stage 2 보고서"""
    ticker  = data['ticker']
    coin    = ticker.replace('KRW-', '')
    results = data['results']
    best    = data['best']
    elapsed = data['elapsed']

    ph(f"📊 Stage 2 분석 보고서  [{coin}]")
    n_combos = len(S2_DEPTHS) * len(S2_LEAVES) * len(S2_LRS)
    print(f"  탐색: {n_combos}조합 × {len(S2_OFFSETS)}시점 × {S2_SLIDE_N}슬라이딩"
          f"  |  소요: {elapsed:.0f}초\n")

    print(f"  {C.BOLD}[ LGB 하이퍼파라미터 랭킹 (상위 10) ]{C.END}")
    print(f"  {'순위':<4} {'depth':>5} {'leaves':>6} {'lr':>6}  "
          f"{'평균적중':>8} {'안정성':>8} {'가상수익':>8} {'종합점수':>8}")
    print(f"  {'─'*60}")

    for rank, r in enumerate(results[:10], 1):
        lo = r['lgb_overrides']
        ac = C.GREEN if r['avg_acc'] >= 0.55 else C.YELLOW if r['avg_acc'] >= 0.48 else C.RED
        sc = C.GREEN if r['avg_virt'] > 0 else C.RED
        zc = C.GREEN if rank == 1 else C.YELLOW if rank == 2 else C.DIM
        star = f"{C.BOLD}★ {C.END}" if rank == 1 else "  "
        print(
            f"  {star}{C.BOLD}{rank:>2}{C.END}위  "
            f"{lo['max_depth']:>5}  {lo['num_leaves']:>6}  {lo['learning_rate']:>6.3f}  "
            f"{ac}{r['avg_acc']:>7.1%}{C.END}  "
            f"{C.DIM}±{r['std_acc']:.2f}{C.END}  "
            f"{sc}{r['avg_virt']:>+7.4f}%{C.END}  "
            f"{zc}{r['score']:>7.1f}점{C.END}"
        )

    print(f"\n  {C.BOLD}[ ★ 최적 LGB 파라미터 ]{C.END}")
    lo = best['lgb_overrides']
    print(f"  max_depth={lo['max_depth']} / num_leaves={lo['num_leaves']} / "
          f"learning_rate={lo['learning_rate']}  (점수 {best['score']:.1f}점)")


def print_final_summary(coin, cache_data):
    """올인원 최종 종합 요약"""
    ph(f"💡 최종 종합 결론  [{coin}]")

    avg_acc = cache_data.get('backtest_avg_acc', 0)
    ev      = cache_data.get('ev', 0)

    if avg_acc >= 0.65 and ev > 0:
        grade = f"{C.GREEN}{C.BOLD}⭐⭐⭐ 우수{C.END}"
        grade_msg = "BB Bounce 보조 신호 즉시 연동 가능"
    elif avg_acc >= 0.58 or (avg_acc >= 0.50 and ev > 0):
        grade = f"{C.YELLOW}{C.BOLD}⭐⭐   양호{C.END}"
        grade_msg = f"t+{cache_data.get('best_step', 1)} 구간 위주 활용 권장"
    elif avg_acc >= 0.50:
        grade = f"{C.YELLOW}{C.BOLD}⭐    보통{C.END}"
        grade_msg = "학습 데이터 증량 또는 다른 코인 시도"
    else:
        grade = f"{C.RED}{C.BOLD}      미흡{C.END}"
        grade_msg = "현재 시장 패턴과 모델 불일치"

    print(f"\n  모델 종합 등급: {grade}  ({grade_msg})")

    print(f"\n  {C.BOLD}최적 파라미터 (캐시 저장됨):{C.END}")
    print(f"  ▸ 학습 캔들: {cache_data['optimal_train']}개")
    print(f"  ▸ 예측 기준: {cache_data['optimal_pred']}개")
    print(f"  ▸ 레이블 임계값: ±{cache_data['optimal_threshold']}%")

    lgb = cache_data.get('optimal_lgb')
    if lgb:
        print(f"  ▸ LGB: depth={lgb['max_depth']} / leaves={lgb['num_leaves']} / "
              f"lr={lgb['learning_rate']}")
    else:
        print(f"  ▸ LGB: 기본값 (Stage 2 미실행 또는 기본값 최적)")

    adaptive_thr = cache_data.get('adaptive_threshold')
    if adaptive_thr and adaptive_thr != cache_data['optimal_threshold']:
        print(f"  ▸ 적응형 임계값: ±{adaptive_thr}% "
              f"(기본 ±{cache_data['optimal_threshold']}% → BBW 기반 조정)")

    print(f"  ▸ 최적 시간대: {cache_data.get('best_hour_zone', 'N/A')}")
    print(f"  ▸ 최적 구간: t+{cache_data.get('best_step', 1)}")

    ec = C.GREEN if ev > 0 else C.RED
    print(f"  ▸ 기대값(EV): {ec}{ev:+.4f}%{C.END}")

    cal = cache_data.get('calibrated_at', '')
    print(f"\n  {C.DIM}캘리브레이션: {cal}")
    print(f"  캐시 유효: {CACHE_VALID_HOURS}시간 → "
          f"다음 재탐색 예정: {cal[:10]} 이후{C.END}")

    # v5.0: 속도 정보
    s1_t = cache_data.get('s1_elapsed', 0)
    s2_t = cache_data.get('s2_elapsed', 0)
    if s1_t > 0:
        print(f"  {C.DIM}Stage 1: {s1_t:.0f}초 / Stage 2: {s2_t:.0f}초 / "
              f"총 {s1_t + s2_t:.0f}초{C.END}")

    print(f"\n  {C.BOLD}모델 개선 방향:{C.END}")
    suggestions = []
    if cache_data.get('backtest_std_acc', 0) > 0.10:
        suggestions.append("안정성 낮음 → 학습 데이터 증량 또는 시점 재조정 권장")
    if avg_acc < 0.55:
        suggestions.append("적중률 개선 필요 → 다른 코인과 비교 분석 권장")
    if ev < 0:
        suggestions.append(f"기대값 음수 ({ev:+.4f}%) → 현재 시장에서 예측 신뢰도 낮음, veto 전용 활용 권장")
    best_step_acc = cache_data.get('best_step_acc', 0)
    if best_step_acc >= 0.65:
        suggestions.append(f"t+{cache_data.get('best_step', 1)} 예측 우수 → BB Bounce 진입 직전 필터 활용")
    if ev > 0.05:
        suggestions.append(f"기대값 양호 ({ev:+.4f}%) → get_prediction() 연동 후 실거래 검증")
    if not suggestions:
        suggestions.append("현재 설정 균형적 → 실거래 데이터 축적 후 재평가 권장")

    for s in suggestions:
        print(f"  {C.CYAN}▶{C.END} {s}")
    print()


# ============================================================================
# SECTION 20: 올인원 파이프라인
# ============================================================================

def run_all_in_one(ticker: str):
    """
    ★ v5.0 올인원 자동 최적화 파이프라인
    Phase 0: 캐시 확인
    Phase 1: Quick Validation (캐시 유효시)
    Phase 2-A: Stage 1 (2-Phase 그리드)
    Phase 2-B: Stage 2 LGB HP 탐색
    Phase 3: 최적 파라미터로 풀 LGB 학습
    Phase 4: 최종 예측 + 종합 보고서
    """
    coin = ticker.replace('KRW-', '')

    # ── Phase 0: 캐시 확인 ──
    ph(f"🚀 올인원 최적화 파이프라인  [{coin}]  v{VERSION}")
    pi("Phase 0: 캐시 확인 중...")

    cache = load_optimal_cache(coin)

    if cache:
        age_h = cache.get('_age_hours', 0)
        ps(f"캐시 발견: {age_h:.1f}시간 전 캘리브레이션  "
           f"(train={cache['optimal_train']}, pred={cache['optimal_pred']}, "
           f"thr=±{cache['optimal_threshold']}%)")

        # ── Phase 1: Quick Validation ──
        pi("Phase 1: Quick Validation...")
        if quick_validate(ticker, cache):
            train_c   = cache['optimal_train']
            pred_c    = cache['optimal_pred']
            threshold = cache['optimal_threshold']
            lgb_over  = cache.get('optimal_lgb')
            ps("캐시 유효 → Stage 1/2 스킵, 바로 재학습+예측")
        else:
            pw("캐시 무효 → 풀 재탐색 시작")
            cache = None

    if cache is None:
        # ── Phase 2-A: Stage 1 (2-Phase 그리드) ──
        confirm = input(
            f"\n  {C.CYAN}2-Phase 그리드 탐색을 시작합니다 (약 3~8분 소요). "
            f"진행? (y/n, 기본 y) > {C.END}"
        ).strip().lower()
        if confirm == 'n':
            print(f"  {C.DIM}취소됨.{C.END}")
            return

        s1_result = run_stage1_grid(ticker)
        if not s1_result:
            pe("Stage 1 실패 — 올인원 중단")
            return

        best_step, best_step_acc, ev = print_stage1_report(s1_result)

        s1_best   = s1_result['best']
        train_c   = s1_best['train']
        pred_c    = s1_best['pred']
        threshold = s1_best['threshold']

        # ── Phase 2-B: Stage 2 ──
        pi("Phase 2-B: Stage 2 시작 (LGB 하이퍼파라미터 탐색)...")
        s2_result = run_stage2_grid(ticker, train_c, pred_c, threshold)

        lgb_over = None
        if s2_result:
            print_stage2_report(s2_result)
            s2_best  = s2_result['best']
            lgb_over = s2_best['lgb_overrides']

            if s2_best['score'] <= s1_best['score']:
                pw("Stage 2 최적이 Stage 1 기본값 이하 → LGB 기본값 유지")
                lgb_over = None
        else:
            pi("Stage 2 유효 결과 없음 → LGB 기본값 유지")

        # Adaptive Threshold 계산
        adaptive_thr = None
        if ADAPTIVE_THR_ENABLED:
            df_recent = fetch_candles_15m(ticker, 100)
            if df_recent is not None and len(df_recent) >= 30:
                adaptive_thr = compute_adaptive_threshold(df_recent, threshold)
                if abs(adaptive_thr - threshold) > 0.02:
                    pi(f"Adaptive Threshold: ±{threshold}% → ±{adaptive_thr}% (BBW 기반)")

        # 캐시 저장
        hour_acc = s1_best.get('hour_acc', {})
        best_zone = max(hour_acc, key=hour_acc.get) if hour_acc else "N/A"

        cache_data = {
            'optimal_train':     train_c,
            'optimal_pred':      pred_c,
            'optimal_threshold': threshold,
            'optimal_lgb':       lgb_over,
            'adaptive_threshold': adaptive_thr,
            'backtest_score':    s1_best['score'],
            'backtest_avg_acc':  s1_best['avg_acc'],
            'backtest_std_acc':  s1_best['std_acc'],
            'best_step':         best_step,
            'best_step_acc':     best_step_acc,
            'best_hour_zone':    best_zone,
            'ev':                ev,
            's1_elapsed':        s1_result['elapsed'],
            's2_elapsed':        s2_result['elapsed'] if s2_result else 0,
            's1_combos_tested':  len(s1_result['results']),
            's2_combos_tested':  len(s2_result['results']) if s2_result else 0,
        }
        save_optimal_cache(coin, cache_data)
    else:
        cache_data = cache

    # ── Phase 3: 최적 파라미터로 풀 LGB 최종 학습 ──
    ph(f"⚡ Phase 3: 최적 파라미터로 모델 학습 (풀 LGB)  [{coin}]")
    print(f"  {C.DIM}train={train_c} / pred={pred_c} / threshold=±{threshold}%{C.END}")
    if lgb_over:
        print(f"  {C.DIM}LGB: depth={lgb_over['max_depth']} / "
              f"leaves={lgb_over['num_leaves']} / lr={lgb_over['learning_rate']}{C.END}")

    total = train_c + pred_c + 30
    pi(f"15분봉 {total}개 수집 중...")
    df_all = fetch_candles_15m(ticker, total)
    if df_all is None or len(df_all) < train_c + pred_c:
        pe("데이터 수집 실패")
        return

    df_train = df_all.iloc[-(train_c + pred_c):-pred_c]
    df_pred  = df_all.iloc[-pred_c:]
    ps(f"학습: {len(df_train)}개  "
       f"({df_train.index[0].strftime('%m/%d %H:%M')} ~ "
       f"{df_train.index[-1].strftime('%m/%d %H:%M')})")
    ps(f"예측: {len(df_pred)}개  "
       f"({df_pred.index[0].strftime('%m/%d %H:%M')} ~ "
       f"{df_pred.index[-1].strftime('%m/%d %H:%M')})")

    # v5.0: 최종 학습에서만 풀 LGB 사용 (search_mode=False)
    models = train_models(df_train, threshold=threshold,
                          lgb_overrides=lgb_over, verbose=True,
                          search_mode=False)
    if not models:
        pe("모델 학습 실패")
        return

    save_models(models, coin, threshold=threshold, lgb_overrides=lgb_over)

    # ── Phase 4: 최종 예측 + 보고서 ──
    results = predict_single(df_pred, models)
    if not results:
        pe("예측 실패")
        return

    print_prediction_result(results, ticker, pred_c, threshold=threshold)
    print_feature_importance(models)
    print_final_summary(coin, cache_data)


# ============================================================================
# SECTION 21: 백테스트 전용 모드
# ============================================================================

def run_backtest_only(ticker: str):
    """모드 2: Stage 1 백테스트만 실행 (보고서 전용)"""
    coin = ticker.replace('KRW-', '')
    ph(f"🔬 백테스트 전용 모드  [{coin}]")
    print(f"  {C.DIM}2-Phase 그리드 탐색 (모델/캐시 저장 없음){C.END}")

    confirm = input(f"  {C.CYAN}시작하시겠습니까? (y/n, 기본 y) > {C.END}").strip().lower()
    if confirm == 'n':
        return

    s1_result = run_stage1_grid(ticker)
    if not s1_result:
        pe("백테스트 실패")
        return

    print_stage1_report(s1_result)

    # 최적 파라미터로 피처 중요도 출력
    best = s1_result['best']
    pi("최적 파라미터로 피처 중요도 계산 중...")
    train_to = get_anchor_to_str(S1_OFFSETS_QUICK[0] + best['pred'] + 5)
    df_tr = fetch_candles_15m(ticker, best['train'] + 30, to=train_to)
    if df_tr is not None and len(df_tr) >= MIN_TRAIN:
        df_tr = df_tr.iloc[-best['train']:]
        models = train_models(df_tr, threshold=best['threshold'], verbose=False)
        if models:
            print_feature_importance(models)


# ============================================================================
# SECTION 22: 예측 전용 모드
# ============================================================================

def run_predict_only(ticker: str):
    """모드 3: 캐시 파라미터로 바로 예측"""
    coin = ticker.replace('KRW-', '')
    ph(f"📈 예측 전용 모드  [{coin}]")

    cache = load_optimal_cache(coin)
    if cache:
        train_c   = cache['optimal_train']
        pred_c    = cache['optimal_pred']
        threshold = cache['optimal_threshold']
        lgb_over  = cache.get('optimal_lgb')
        age_h     = cache.get('_age_hours', 0)
        ps(f"캐시 파라미터 사용 ({age_h:.1f}시간 전): "
           f"train={train_c} / pred={pred_c} / thr=±{threshold}%")
    else:
        pw("캐시 없음 → 기본값 사용 (올인원 모드 실행 권장)")
        train_c   = DEFAULT_TRAIN
        pred_c    = DEFAULT_PRED
        threshold = DEFAULT_THRESHOLD
        lgb_over  = None

    total = train_c + pred_c + 30
    pi(f"15분봉 {total}개 수집 중...")
    df_all = fetch_candles_15m(ticker, total)
    if df_all is None or len(df_all) < train_c + pred_c:
        pe("데이터 수집 실패")
        return

    df_train = df_all.iloc[-(train_c + pred_c):-pred_c]
    df_pred  = df_all.iloc[-pred_c:]
    ps(f"학습: {len(df_train)}개 / 예측: {len(df_pred)}개")

    models = get_or_train_models(df_train, coin, threshold=threshold,
                                 lgb_overrides=lgb_over, verbose=True)
    if not models:
        pe("모델 학습 실패")
        return

    results = predict_single(df_pred, models)
    if not results:
        pe("예측 실패")
        return

    print_prediction_result(results, ticker, pred_c, threshold=threshold)
    print_feature_importance(models)


# ============================================================================
# SECTION 22-A: ★ 모드 4 — 3코인 일괄 분석 (v5.1 신규)
# ============================================================================

def _grade_label(avg_acc, ev):
    """코인별 등급 판정 (비교용 순수 텍스트)"""
    if avg_acc >= 0.65 and ev > 0:
        return '⭐⭐⭐', '우수', 3
    elif avg_acc >= 0.58 or (avg_acc >= 0.50 and ev > 0):
        return '⭐⭐ ', '양호', 2
    elif avg_acc >= 0.50:
        return '⭐  ', '보통', 1
    else:
        return '    ', '미흡', 0


def run_multi_coin_analysis():
    """
    ★ v5.1 핵심 신규: 3코인(ETH/XRP/SOL) 일괄 분석 파이프라인

    Phase 1: 코인별 Stage 1 백테스트 → 최적 파라미터 선정
    Phase 2: 상위 2코인만 Stage 2 (LGB HP 탐색)
    Phase 3: 3코인 비교 랭킹 + 캐시 저장
    Phase 4: 코인별 최종 학습 + 예측
    Phase 5: 종합 대시보드 출력
    """
    coins = TARGET_COINS
    coin_names = [t.replace('KRW-', '') for t in coins]

    ph(f"🎯 3코인 일괄 분석  [{' / '.join(coin_names)}]  v{VERSION}")
    print(f"  {C.GREEN}★ Stage 1 백테스트 → 최적 파라미터 → Stage 2 → 예측 → 비교{C.END}")
    print(f"  {C.DIM}예상 소요: 약 5~10분 (3코인 순차){C.END}\n")

    confirm = input(
        f"  {C.CYAN}3코인 일괄 분석을 시작합니다. 진행? (y/n, 기본 y) > {C.END}"
    ).strip().lower()
    if confirm == 'n':
        print(f"  {C.DIM}취소됨.{C.END}")
        return

    total_start = time.time()

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # Phase 1: 코인별 Stage 1 백테스트
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    ph(f"📊 Phase 1: 코인별 Stage 1 백테스트")

    coin_s1_results = {}    # {coin_name: s1_result}
    coin_best_params = {}   # {coin_name: {train, pred, threshold, score, ...}}

    for idx, ticker in enumerate(coins, 1):
        coin = ticker.replace('KRW-', '')
        pi(f"[{idx}/{len(coins)}] {coin} Stage 1 탐색 시작...")

        s1_result = run_stage1_grid(ticker)
        if s1_result and s1_result['results']:
            coin_s1_results[coin] = s1_result
            best = s1_result['best']

            # Stage 1 보고서 출력 (요약)
            best_step, best_step_acc, ev = print_stage1_report(s1_result)

            coin_best_params[coin] = {
                'ticker':    ticker,
                'train':     best['train'],
                'pred':      best['pred'],
                'threshold': best['threshold'],
                'score':     best['score'],
                'avg_acc':   best['avg_acc'],
                'std_acc':   best['std_acc'],
                'avg_virt':  best.get('avg_virt', 0),
                'avg_vwin':  best.get('avg_vwin', 0),
                'ev':        ev,
                'best_step':      best_step,
                'best_step_acc':  best_step_acc,
                'hour_acc':       best.get('hour_acc', {}),
                's1_elapsed':     s1_result['elapsed'],
            }
            ps(f"{coin} Stage 1 완료: 점수 {best['score']:.1f} / "
               f"적중 {best['avg_acc']:.1%} / EV {ev:+.4f}%")
        else:
            pe(f"{coin} Stage 1 실패 — 건너뜀")

    if not coin_best_params:
        pe("모든 코인 Stage 1 실패 — 중단")
        return

    # Phase 1 요약
    print(f"\n  {C.BOLD}[ Phase 1 결과 요약 ]{C.END}")
    sorted_coins = sorted(coin_best_params.items(),
                          key=lambda x: x[1]['score'], reverse=True)
    for rank, (coin, p) in enumerate(sorted_coins, 1):
        ac = C.GREEN if p['avg_acc'] >= 0.50 else C.YELLOW if p['avg_acc'] >= 0.40 else C.RED
        ec = C.GREEN if p['ev'] > 0 else C.RED
        star = "★" if rank == 1 else " "
        print(f"  {star} {rank}위 {C.BOLD}{coin:<5}{C.END}  "
              f"점수:{p['score']:5.1f}  "
              f"{ac}적중:{p['avg_acc']:.1%}{C.END}  "
              f"{ec}EV:{p['ev']:+.4f}%{C.END}  "
              f"승률:{p['avg_vwin']:.1%}  "
              f"({p['s1_elapsed']:.0f}초)")

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # Phase 2: 상위 N코인만 Stage 2
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    ph(f"📊 Phase 2: 상위 {MULTI_S2_TOP_N}코인 Stage 2 (LGB HP 탐색)")

    coin_lgb_overrides = {}  # {coin_name: lgb_overrides or None}

    for rank, (coin, p) in enumerate(sorted_coins):
        ticker = p['ticker']

        if rank < MULTI_S2_TOP_N:
            pi(f"{coin} Stage 2 시작...")
            s2_result = run_stage2_grid(ticker, p['train'], p['pred'], p['threshold'])

            lgb_over = None
            if s2_result:
                print_stage2_report(s2_result)
                s2_best = s2_result['best']
                if s2_best['score'] > p['score']:
                    lgb_over = s2_best['lgb_overrides']
                    ps(f"{coin} Stage 2: LGB 최적화 적용 "
                       f"(점수 {p['score']:.1f} → {s2_best['score']:.1f})")
                    coin_best_params[coin]['s2_elapsed'] = s2_result['elapsed']
                else:
                    pw(f"{coin} Stage 2: 기본값이 더 우수 → LGB 기본값 유지")
            else:
                pi(f"{coin} Stage 2: 유효 결과 없음 → LGB 기본값")

            coin_lgb_overrides[coin] = lgb_over
        else:
            pi(f"{coin}: Stage 1 하위권 → Stage 2 생략 (LGB 기본값)")
            coin_lgb_overrides[coin] = None

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # Phase 3: 캐시 저장 + Adaptive Threshold
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    ph("💾 Phase 3: 코인별 캐시 저장")

    for coin, p in coin_best_params.items():
        ticker = p['ticker']
        lgb_over = coin_lgb_overrides.get(coin)

        # Adaptive Threshold
        adaptive_thr = None
        if ADAPTIVE_THR_ENABLED:
            df_recent = fetch_candles_15m(ticker, 100)
            if df_recent is not None and len(df_recent) >= 30:
                adaptive_thr = compute_adaptive_threshold(df_recent, p['threshold'])

        hour_acc = p.get('hour_acc', {})
        best_zone = max(hour_acc, key=hour_acc.get) if hour_acc else "N/A"

        cache_data = {
            'optimal_train':     p['train'],
            'optimal_pred':      p['pred'],
            'optimal_threshold': p['threshold'],
            'optimal_lgb':       lgb_over,
            'adaptive_threshold': adaptive_thr,
            'backtest_score':    p['score'],
            'backtest_avg_acc':  p['avg_acc'],
            'backtest_std_acc':  p['std_acc'],
            'best_step':         p['best_step'],
            'best_step_acc':     p['best_step_acc'],
            'best_hour_zone':    best_zone,
            'ev':                p['ev'],
            's1_elapsed':        p.get('s1_elapsed', 0),
            's2_elapsed':        p.get('s2_elapsed', 0),
        }
        save_optimal_cache(coin, cache_data)

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # Phase 4: 코인별 최종 학습 + 예측
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    ph("⚡ Phase 4: 코인별 최종 학습 + 예측 (풀 LGB)")

    coin_predictions = {}  # {coin: {results, signal, confidence, models, cache_data}}

    for coin, p in coin_best_params.items():
        ticker    = p['ticker']
        train_c   = p['train']
        pred_c    = p['pred']
        threshold = p['threshold']
        lgb_over  = coin_lgb_overrides.get(coin)

        pi(f"{coin}: 15분봉 수집 + 풀 LGB 학습...")

        total = train_c + pred_c + 30
        df_all = fetch_candles_15m(ticker, total)
        if df_all is None or len(df_all) < train_c + pred_c:
            pe(f"{coin}: 데이터 수집 실패")
            continue

        df_train = df_all.iloc[-(train_c + pred_c):-pred_c]
        df_pred  = df_all.iloc[-pred_c:]

        models = train_models(df_train, threshold=threshold,
                              lgb_overrides=lgb_over, verbose=True,
                              search_mode=False)
        if not models:
            pe(f"{coin}: 모델 학습 실패")
            continue

        save_models(models, coin, threshold=threshold, lgb_overrides=lgb_over)

        results = predict_single(df_pred, models)
        if not results:
            pe(f"{coin}: 예측 실패")
            continue

        # 예측 결과 출력
        print_prediction_result(results, ticker, pred_c, threshold=threshold)

        # 신호 계산
        sig_str, sig_eng = compute_signal(results)
        avg_max = np.mean([r['max_prob'] for r in results[:3]])
        confidence = 'HIGH' if avg_max >= 0.55 else 'MID' if avg_max >= 0.45 else 'LOW'

        # 학습 정확도 (검증 정확도)
        val_accs = []
        for m in models:
            if m is not None:
                val_accs.append(1.0)  # 학습 시 이미 출력됨
        # (학습 시 verbose=True로 콘솔에 출력됨)

        coin_predictions[coin] = {
            'results': results,
            'signal_str': sig_str,
            'signal_eng': sig_eng,
            'confidence': confidence,
            'models': models,
            'params': p,
        }

        ps(f"{coin}: 예측 완료 → {sig_str}")

    if not coin_predictions:
        pe("모든 코인 예측 실패")
        return

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # Phase 5: 종합 대시보드
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    total_elapsed = time.time() - total_start

    ph(f"🏆 3코인 종합 대시보드  v{VERSION}")
    print(f"  분석 시각: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} KST")
    print(f"  총 소요: {total_elapsed:.0f}초 ({total_elapsed/60:.1f}분)\n")

    # ── 비교 테이블 ──
    print(f"  {C.BOLD}{'═'*72}{C.END}")
    print(f"  {C.BOLD}{'코인':<6} {'점수':>5} {'적중률':>7} {'EV':>9} "
          f"{'승률':>6} {'등급':>8} {'신호':>10} {'최적구간':>8}{C.END}")
    print(f"  {C.BOLD}{'─'*72}{C.END}")

    dashboard_rows = []
    for coin in coin_names:
        if coin not in coin_best_params:
            continue

        p = coin_best_params[coin]
        pred = coin_predictions.get(coin)
        grade_icon, grade_kr, grade_num = _grade_label(p['avg_acc'], p['ev'])

        sig_eng = pred['signal_eng'] if pred else 'N/A'
        sig_icon = {'BUY': '🟢BUY', 'SELL': '🔴SELL', 'NEUTRAL': '⚪관망'}.get(sig_eng, '❓N/A')

        # 색상
        ac = C.GREEN if p['avg_acc'] >= 0.50 else C.YELLOW if p['avg_acc'] >= 0.40 else C.RED
        ec = C.GREEN if p['ev'] > 0 else C.RED
        wc = C.GREEN if p['avg_vwin'] >= 0.55 else C.YELLOW if p['avg_vwin'] >= 0.45 else C.DIM
        gc = C.GREEN if grade_num >= 2 else C.YELLOW if grade_num >= 1 else C.RED

        print(
            f"  {C.BOLD}{coin:<6}{C.END} "
            f"{p['score']:>5.1f} "
            f"{ac}{p['avg_acc']:>7.1%}{C.END} "
            f"{ec}{p['ev']:>+9.4f}%{C.END} "
            f"{wc}{p['avg_vwin']:>6.1%}{C.END} "
            f"{gc}{grade_icon}{C.END} "
            f"{sig_icon:>10} "
            f"t+{p['best_step']:>1}"
        )

        dashboard_rows.append({
            'coin': coin, 'ticker': p['ticker'],
            'score': p['score'], 'avg_acc': p['avg_acc'],
            'ev': p['ev'], 'grade_num': grade_num,
            'signal': sig_eng,
        })

    print(f"  {C.BOLD}{'═'*72}{C.END}")

    # ── 최적 코인 / 회피 코인 판정 ──
    if dashboard_rows:
        # 최적: score 기준 1위 + EV 양수
        best_row = max(dashboard_rows, key=lambda x: x['score'])
        worst_row = min(dashboard_rows, key=lambda x: x['score'])

        print()
        if best_row['ev'] > 0:
            bc = C.GREEN
            print(f"  {bc}{C.BOLD}★ 최적 코인: {best_row['coin']} "
                  f"({best_row['signal']}) — 점수 {best_row['score']:.1f}, "
                  f"EV {best_row['ev']:+.4f}%{C.END}")
        else:
            print(f"  {C.YELLOW}{C.BOLD}★ 상대적 최적: {best_row['coin']} "
                  f"(단, EV 음수 주의){C.END}")

        ev_negative = [r for r in dashboard_rows if r['ev'] < 0]
        if ev_negative:
            worst_ev = min(ev_negative, key=lambda x: x['ev'])
            print(f"  {C.RED}{C.BOLD}⚠ 회피 코인: {worst_ev['coin']} "
                  f"— EV {worst_ev['ev']:+.4f}% (veto 전용 권장){C.END}")

    # ── 코인별 최적 파라미터 요약 ──
    print(f"\n  {C.BOLD}[ 코인별 최적 파라미터 ]{C.END}")
    for coin, p in coin_best_params.items():
        lgb_over = coin_lgb_overrides.get(coin)
        lgb_str = (f"depth={lgb_over['max_depth']}/leaves={lgb_over['num_leaves']}/"
                   f"lr={lgb_over['learning_rate']}" if lgb_over else "기본값")
        print(f"  {C.BOLD}{coin:<5}{C.END}  "
              f"train={p['train']} pred={p['pred']} thr=±{p['threshold']}%  "
              f"LGB: {lgb_str}")

    # ── BB Bounce Hunter 연동 권고 ──
    print(f"\n  {C.BOLD}[ BB Bounce Hunter 연동 권고 ]{C.END}")

    for row in sorted(dashboard_rows, key=lambda x: x['score'], reverse=True):
        coin = row['coin']
        p = coin_best_params[coin]
        sig = row['signal']

        if row['ev'] > 0 and row['avg_acc'] >= 0.50:
            hint = f"✅ 예측 연동 활성화 권장 (t+{p['best_step']} 필터)"
        elif row['ev'] > 0:
            hint = f"⚠️ 제한적 활용 (BUY 신호 시에만 참고)"
        elif row['avg_acc'] >= 0.45:
            hint = f"🛑 veto 전용 (SELL 신호 시 매수 차단)"
        else:
            hint = f"❌ 연동 비권장 (모델 신뢰도 낮음)"

        print(f"  {C.BOLD}{coin:<5}{C.END}  {sig:<8}  {hint}")

    # ── 피처 중요도 (최적 코인) ──
    if dashboard_rows:
        best_coin = best_row['coin']
        if best_coin in coin_predictions:
            print_feature_importance(coin_predictions[best_coin]['models'])

    print(f"\n  {C.DIM}총 소요: {total_elapsed:.0f}초 ({total_elapsed/60:.1f}분)  |  "
          f"분석: {len(coin_predictions)}/{len(coins)}코인 성공{C.END}\n")


# ============================================================================
# SECTION 23: BB Bounce Hunter v33 통합 공개 API
# ============================================================================

def get_prediction(ticker, pred_count=None, train_count=None):
    """
    BB Bounce Hunter v33 통합 공개 API (스레드 안전, Lock 적용)

    v5.1 개선:
    - Lock 범위 축소: 파라미터 조회/캐시 저장에만 Lock 적용
      → 학습·API 호출은 Lock 밖에서 실행 (교착 위험 제거)
    - 예외 로깅 강화: except Exception에서 실제 오류 출력
    - ok=False 시 실패 원인 코드 포함

    Usage:
        from price_predictor_v5_1 import get_prediction
        pred = get_prediction("KRW-XRP")

    Returns:
        {
          't+1': {'label':1, 'direction':'UP',
                  'prob_up':0.42, 'prob_neu':0.35, 'prob_dn':0.23, 'conf':'중간'},
          ...
          'signal': 'BUY',
          'confidence': 'MID',
          'ok': True,
          'params': {'train': 1000, 'pred': 50, 'threshold': 0.20}
        }
    """
    _FB = {f't+{n}': {'label': 0, 'direction': 'NEUTRAL',
                       'prob_up': 0.33, 'prob_neu': 0.34, 'prob_dn': 0.33,
                       'conf': '낮음'}
           for n in range(1, PREDICT_STEPS + 1)}
    _FB.update({'signal': 'NEUTRAL', 'confidence': 'LOW', 'ok': False,
                'params': {}, 'fail_reason': 'unknown'})

    coin = ticker.replace('KRW-', '')

    # ── Step 1: 파라미터 결정 (Lock 필요 없음, 읽기 전용) ──
    try:
        cache = load_optimal_cache(coin)
        if cache:
            tc  = cache['optimal_train']
            pc  = cache['optimal_pred']
            thr = cache['optimal_threshold']
            lgb_ov = cache.get('optimal_lgb')
            adaptive = cache.get('adaptive_threshold')
            if adaptive:
                thr = adaptive
        else:
            tc  = DEFAULT_TRAIN
            pc  = DEFAULT_PRED
            thr = DEFAULT_THRESHOLD
            lgb_ov = None

        if pred_count  is not None: pc = pred_count
        if train_count is not None: tc = train_count
    except Exception as e:
        print(f"[Predictor] {coin} 파라미터 로드 오류: {e}")
        tc, pc, thr, lgb_ov = DEFAULT_TRAIN, DEFAULT_PRED, DEFAULT_THRESHOLD, None

    # ── Step 2: 모델 로드 또는 학습 (Lock 불필요 — 코인별 독립) ──
    try:
        models = load_models(coin)
        if models:
            # pkl 로드 성공 → 예측용 캔들만 수집
            df_pred = fetch_candles_15m(ticker, pc + 30)
            if df_pred is None or len(df_pred) < MIN_CANDLES:
                fb = dict(_FB); fb['fail_reason'] = f'pred_candle_부족({0 if df_pred is None else len(df_pred)}봉)'
                print(f"[Predictor] {coin} 예측 캔들 부족 → ok=False")
                return fb
        else:
            # pkl 없음 → 신규 학습
            print(f"[Predictor] {coin} pkl 없음 → 신규 학습 시작 (train={tc} pred={pc})")
            total = tc + pc + 30
            df_all = fetch_candles_15m(ticker, total)
            if df_all is None or len(df_all) < tc + pc:
                fb = dict(_FB); fb['fail_reason'] = f'train_candle_부족({0 if df_all is None else len(df_all)}봉/{tc+pc}필요)'
                print(f"[Predictor] {coin} 학습 캔들 부족 → ok=False")
                return fb

            df_train = df_all.iloc[-(tc + pc):-pc]
            df_pred  = df_all.iloc[-pc:]

            models = train_models(df_train, threshold=thr,
                                  lgb_overrides=lgb_ov, verbose=False,
                                  search_mode=False)
            if not models:
                fb = dict(_FB); fb['fail_reason'] = 'train_models_실패'
                print(f"[Predictor] {coin} 모델 학습 실패 → ok=False")
                return fb

            # Lock 안에서만 저장 (파일 쓰기 경합 방지)
            with _predict_lock:
                save_models(models, coin, threshold=thr, lgb_overrides=lgb_ov)
            print(f"[Predictor] {coin} 신규 학습 완료 → pkl 저장")

    except Exception as e:
        import traceback
        fb = dict(_FB); fb['fail_reason'] = f'model_exception:{e}'
        print(f"[Predictor] {coin} 모델 로드/학습 예외: {e}")
        if DEBUG_MODE_PRED:
            traceback.print_exc()
        return fb

    # ── Step 3: 예측 실행 ──
    try:
        results = predict_single(df_pred, models)
        if not results:
            fb = dict(_FB); fb['fail_reason'] = 'predict_single_None'
            print(f"[Predictor] {coin} predict_single 반환 None → ok=False")
            return fb

        out = {}
        for r in results:
            out[f"t+{r['step']}"] = {
                'label':    r['label'],
                'direction': DIR_ENG[r['label']],
                'prob_up':  r['prob_up'],
                'prob_neu': r['prob_neu'],
                'prob_dn':  r['prob_dn'],
                'conf':     r['conf'],
            }

        _, sig_eng = compute_signal(results)
        out['signal']     = sig_eng
        avg_max           = np.mean([r['max_prob'] for r in results[:3]])
        out['confidence'] = 'HIGH' if avg_max >= 0.55 else 'MID' if avg_max >= 0.45 else 'LOW'
        out['ok']         = True
        out['params']     = {'train': tc, 'pred': pc, 'threshold': thr}
        return out

    except Exception as e:
        import traceback
        fb = dict(_FB); fb['fail_reason'] = f'predict_exception:{e}'
        print(f"[Predictor] {coin} 예측 실행 예외: {e}")
        if DEBUG_MODE_PRED:
            traceback.print_exc()
        return fb


# ============================================================================
# SECTION 24: 인터페이스
# ============================================================================

def input_int(prompt, min_v, max_v, default=None):
    while True:
        raw = input(prompt).strip()
        if raw == '' and default is not None:
            return default
        try:
            v = int(raw)
            if min_v <= v <= max_v:
                return v
            print(f"  {C.YELLOW}  → {min_v}~{max_v} 범위 입력{C.END}")
        except ValueError:
            print(f"  {C.YELLOW}  → 숫자를 입력하세요{C.END}")


def select_coin():
    ph("🪙 코인 선택")
    for num, t in COINS.items():
        print(f"    {C.BOLD}{num}.{C.END} {t.replace('KRW-', '')}")
    print()
    num    = input_int(f"  {C.CYAN}선택 (1~7) > {C.END}", 1, 7)
    ticker = COINS[num]
    ps(f"{ticker.replace('KRW-', '')} 선택")
    return num, ticker


def select_mode():
    ph("⚙️  모드 선택")
    print(f"    {C.BOLD}1.{C.END} 🚀 올인원     단일 코인: 백테스트 → 최적화 → 재학습 → 예측")
    print(f"    {C.BOLD}2.{C.END} 🔬 백테스트   단일 코인: 분석/보고서 전용 (2-Phase 탐색)")
    print(f"    {C.BOLD}3.{C.END} 📈 예측       단일 코인: 캐시 파라미터 사용 (빠른 실행)")
    print(f"    {C.BOLD}4.{C.END} 🎯 3코인 일괄 ETH/XRP/SOL 한번에 분석+예측+비교")
    print()
    while True:
        raw = input(f"  {C.CYAN}선택 (1/2/3/4) > {C.END}").strip()
        if raw in ('1', '2', '3', '4'):
            return raw
        print(f"  {C.YELLOW}  → 1, 2, 3, 4 중 하나 입력{C.END}")


# ============================================================================
# SECTION 25: 메인 실행
# ============================================================================

def main():
    print(f"""
{C.BOLD}{C.CYAN}{'═'*62}
  💹 암호화폐 가격 예측 분석기 v{VERSION}
     BB Bounce Hunter 보조 모듈 — 올인원 최적화 파이프라인
  ─────────────────────────────────────────────────────────
  ▶ 15분봉 기반 향후 5캔들 방향 예측
  ▶ 2단계 자동 최적화: 데이터 파라미터 + LGB 하이퍼파라미터
  ▶ ★ v5.1: 3코인 일괄 분석 (ETH/XRP/SOL 비교 대시보드)
  ▶ ★ v5.0: 2-Phase 그리드 탐색 (속도 70~80% 향상)
  ▶ ★ v5.0: 풀 피처 사전계산 + 탐색용 경량 LGB
  ▶ ★ v5.0: 신규 피처 3개 (VWAP, BBW변화율, RSI다이버전스)
  ▶ Adaptive Threshold / EV-aware 점수
  ▶ get_prediction() 모델 pkl 우선 로드 (~1~2초)
  ▶ 최적 파라미터 캐시 ({CACHE_VALID_HOURS}시간 유효)
{'═'*62}{C.END}
""")

    while True:
        try:
            mode = select_mode()

            if mode == '4':
                # 모드 4: 3코인 일괄 — 코인 선택 불필요
                run_multi_coin_analysis()
            else:
                _, ticker = select_coin()
                if mode == '1':
                    run_all_in_one(ticker)
                elif mode == '2':
                    run_backtest_only(ticker)
                else:
                    run_predict_only(ticker)

            print()
            again = input(f"\n  {C.CYAN}다시 실행? (y/n, 기본 y) > {C.END}").strip().lower()
            if again == 'n':
                print(f"\n{C.BOLD}{C.CYAN}  종료합니다. 감사합니다!{C.END}\n")
                break

        except KeyboardInterrupt:
            print(f"\n\n{C.YELLOW}  Ctrl+C 감지 — 종료합니다.{C.END}\n")
            break
        except Exception as e:
            pe(f"예외: {e}")
            import traceback
            traceback.print_exc()
            again = input(f"\n  {C.CYAN}다시 시도? (y/n) > {C.END}").strip().lower()
            if again == 'n':
                break


if __name__ == '__main__':
    main()
