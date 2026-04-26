# ═══════════════════════════════════════════════════════════════════════
# AlertManager — Discord 알림 피로 방지 매니저 (v36 패치)
# ═══════════════════════════════════════════════════════════════════════
"""
SRE 모범 사례 기반 Discord 알림 게이트.

[해결 문제]
v36 운영 중 발견된 알림 도배 (10분마다 동일 "현금 부족" 알림 반복).

[설계 원칙 - 출처 표기]

  1. State vs Event 구분
     출처: Google SRE Workbook (https://sre.google/workbook/)
     - State (지속 상태): edge-triggered, 전이 시점만 알림
     - Event (순간 사건): 그대로 알림

  2. Deduplication + Hysteresis
     출처: Prometheus Alertmanager 문서 (https://prometheus.io/docs/alerting/)
            and incident.io 2025 (https://incident.io/blog/alert-fatigue-solutions-for-dev-ops-teams-in-2025)
     - 같은 알림은 기본 침묵
     - N시간 이상 지속 시 에스컬레이션
     - 회복 시 Recovery 알림

  3. Discord Rate Limit 준수
     출처: Discord 공식 문서 (https://docs.discord.com/developers/topics/rate-limits)
     - 웹훅 2초당 5요청
     - Cloudflare 10K req/10min IP ban 위험
"""

import threading
import time
from typing import Optional, Callable
from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class AlertState:
    """단일 알림 키의 상태 추적 데이터"""
    last_sent_ts: float = 0.0           # 마지막 알림 발송 시각
    first_active_ts: float = 0.0        # 처음 활성화된 시각 (state용)
    is_active: bool = False              # 현재 활성 상태 (state용)
    escalation_count: int = 0           # 에스컬레이션 횟수
    occurrences_suppressed: int = 0     # 침묵된 발생 횟수 (event_dedup용)


class AlertManager:
    """
    Discord 알림의 단일 게이트.
    
    [정책 종류]
    - 'state_edge': 상태 전이 시점만 알림 + 장기 지속 시 에스컬레이션 + 회복 시 알림
    - 'event_dedup': 같은 키의 사건은 dedup_window_sec 동안 침묵
    - 'always': 무조건 발송 (체결, 시작/종료)
    
    [Thread Safety]
    내부 lock으로 모든 메서드 thread-safe.
    
    [사용 예시]
    
        alert_mgr = AlertManager(send_func=send_discord_message)
        
        # 사례 1: 현금 부족 (state)
        alert_mgr.report_state(
            key="no_cash",
            is_active=(krw < MIN_BUY_KRW),
            on_enter_msg="🚫 현금 부족 발생...",
            on_recover_msg="✅ 현금 회복...",
            escalation_hours=24,
            on_escalate_msg="⏰ 현금 부족 24시간 경과...",
        )
        
        # 사례 2: 같은 에러 반복 (event_dedup)
        alert_mgr.send_event_dedup(
            key=f"error:{error_type}",
            message=f"❌ {error_type}: {error_msg}",
            dedup_window_sec=300,
        )
        
        # 사례 3: 매수/매도 체결 (always)
        alert_mgr.send_always(message="📈 매수 완료...")
    """

    def __init__(self, send_func: Callable[[str, bool], bool], debug: bool = False):
        """
        Args:
            send_func: 실제 디스코드 발송 함수 (예: send_discord_message)
                       시그니처: (message: str, is_critical: bool=False) -> bool
            debug: True면 침묵된 알림도 콘솔에 출력
        """
        self._send_func = send_func
        self._states: dict[str, AlertState] = {}
        self._lock = threading.Lock()
        self._debug = debug

        # ── Discord rate limit 준수 (2초당 5요청) ──
        self._send_history: list[float] = []
        self._rate_limit_window = 2.0
        self._rate_limit_max = 5
        # 실제로는 봇 1개 발송 빈도 매우 낮으므로 throttle 발동 거의 없음
        # 하지만 폭주 시나리오를 대비한 안전장치

    # ────────────────────────────────────────────────────────────────
    # 정책 1: state_edge — 지속 상태 알림 (edge-triggered)
    # ────────────────────────────────────────────────────────────────
    def report_state(
        self,
        key: str,
        is_active: bool,
        on_enter_msg: Optional[str] = None,
        on_recover_msg: Optional[str] = None,
        escalation_hours: float = 0,
        on_escalate_msg: Optional[str] = None,
        is_critical: bool = False,
    ) -> bool:
        """
        지속 상태(state) 알림 보고.
        
        [동작 흐름]
          1. is_active=False였다가 True로 전이 → on_enter_msg 알림 1회
          2. is_active=True가 escalation_hours 이상 지속 → on_escalate_msg 1회
             (escalation_hours 마다 반복)
          3. is_active=True였다가 False로 전이 → on_recover_msg 1회
          4. 그 외 (상태 변화 없음) → 침묵
        
        [언제 사용]
          - "현금 부족" (state: 충분/부족)
          - "거래소 API 다운" (state: 정상/장애)
          - "WebSocket 연결 끊김" (state: 연결/끊김)
        
        Returns:
            True if 알림 발송됨, False if 침묵.
        """
        now = time.time()
        sent = False

        with self._lock:
            state = self._states.get(key)
            if state is None:
                state = AlertState()
                self._states[key] = state

            prev_active = state.is_active

            # ── Case 1: 비활성 → 활성 (Enter) ──
            if not prev_active and is_active:
                state.is_active = True
                state.first_active_ts = now
                state.escalation_count = 0
                state.last_sent_ts = now
                if on_enter_msg:
                    msg_to_send = on_enter_msg
                    sent = True

            # ── Case 2: 활성 → 활성 (지속) — 에스컬레이션 검사 ──
            elif prev_active and is_active:
                state.is_active = True   # 갱신
                if escalation_hours > 0 and on_escalate_msg:
                    elapsed_hours = (now - state.first_active_ts) / 3600
                    expected_escalations = int(elapsed_hours / escalation_hours)
                    if expected_escalations > state.escalation_count:
                        state.escalation_count = expected_escalations
                        state.last_sent_ts = now
                        msg_to_send = on_escalate_msg.format(
                            hours=int(elapsed_hours),
                            escalation_count=expected_escalations,
                        )
                        sent = True
                    else:
                        msg_to_send = None
                else:
                    msg_to_send = None

            # ── Case 3: 활성 → 비활성 (Recover) ──
            elif prev_active and not is_active:
                duration_min = int((now - state.first_active_ts) / 60)
                state.is_active = False
                state.escalation_count = 0
                state.last_sent_ts = now
                if on_recover_msg:
                    msg_to_send = on_recover_msg.format(duration_min=duration_min)
                    sent = True
                else:
                    msg_to_send = None

            # ── Case 4: 비활성 → 비활성 (변화 없음) ──
            else:
                msg_to_send = None

        # ── 발송 (lock 밖에서) ──
        if sent and msg_to_send:
            self._do_send(msg_to_send, is_critical)
        elif self._debug and not sent:
            self._dbg(f"[AlertMgr] state '{key}' 변화 없음 — 침묵 (active={is_active})")

        return sent

    # ────────────────────────────────────────────────────────────────
    # 정책 2: event_dedup — 사건이지만 반복되면 침묵
    # ────────────────────────────────────────────────────────────────
    def send_event_dedup(
        self,
        key: str,
        message: str,
        dedup_window_sec: float = 300,
        is_critical: bool = False,
    ) -> bool:
        """
        같은 키의 사건은 dedup_window_sec 동안 침묵.
        
        [언제 사용]
          - 시스템 에러 (같은 에러 메시지가 1초마다 발생할 때)
          - "수동매도 추정" 알림 (같은 코인 반복 감지)
          - 봇 재시작 동기화 보고 (재시작 자주 시)
        
        [동작]
          - 같은 key가 dedup_window_sec 안에 다시 호출되면 침묵 + 카운터 증가
          - 다음 발송 시 "(N회 억제됨)" 부가 정보 포함 가능
        
        Returns:
            True if 발송됨, False if 침묵.
        """
        now = time.time()
        sent = False
        message_to_send = message

        with self._lock:
            state = self._states.get(key)
            if state is None:
                state = AlertState()
                self._states[key] = state

            elapsed = now - state.last_sent_ts

            if elapsed >= dedup_window_sec or state.last_sent_ts == 0:
                # 발송
                if state.occurrences_suppressed > 0:
                    message_to_send = (
                        f"{message}\n_(동일 사건 {state.occurrences_suppressed}회 억제됨)_"
                    )
                state.last_sent_ts = now
                state.occurrences_suppressed = 0
                sent = True
            else:
                # 침묵
                state.occurrences_suppressed += 1

        if sent:
            self._do_send(message_to_send, is_critical)
        elif self._debug:
            self._dbg(f"[AlertMgr] event '{key}' 침묵 (dedup window {dedup_window_sec}s)")

        return sent

    # ────────────────────────────────────────────────────────────────
    # 정책 3: always — 무조건 발송 (rate limit만 적용)
    # ────────────────────────────────────────────────────────────────
    def send_always(self, message: str, is_critical: bool = False) -> bool:
        """
        무조건 발송. Discord 자체 rate limit만 준수.
        
        [언제 사용]
          - 매수/매도 체결 알림 (사건성, 중복 가능성 거의 없음)
          - 봇 시작/종료
          - 정시 보고 (의도된 주기)
        """
        return self._do_send(message, is_critical)

    # ────────────────────────────────────────────────────────────────
    # 내부: 실제 발송 + Discord rate limit 준수
    # ────────────────────────────────────────────────────────────────
    def _do_send(self, message: str, is_critical: bool) -> bool:
        """
        실제 디스코드 발송 + 2초당 5요청 한도 준수.
        
        한도 초과 시 다음 윈도우까지 대기.
        """
        with self._lock:
            now = time.time()
            # 윈도우 안의 발송 기록만 유지
            self._send_history = [
                ts for ts in self._send_history if now - ts < self._rate_limit_window
            ]

            if len(self._send_history) >= self._rate_limit_max:
                oldest = self._send_history[0]
                wait = self._rate_limit_window - (now - oldest) + 0.1
            else:
                wait = 0

        if wait > 0:
            self._dbg(f"[AlertMgr] Discord rate limit 보호 — {wait:.2f}초 대기")
            time.sleep(wait)

        result = self._send_func(message, is_critical)

        with self._lock:
            self._send_history.append(time.time())

        return bool(result)

    # ────────────────────────────────────────────────────────────────
    # 디버깅
    # ────────────────────────────────────────────────────────────────
    def _dbg(self, msg: str):
        if self._debug:
            print(f"  {msg}")

    def get_status(self) -> dict:
        """현재 매니저 상태 진단용 (디스코드 알림 안 옴 등)"""
        with self._lock:
            return {
                "tracked_keys": len(self._states),
                "active_states": [k for k, s in self._states.items() if s.is_active],
                "send_count_2s": len(self._send_history),
            }
