"""
Forenode — 개발자 데이터 핸드오프 모듈 (dev_handoff.py)

목적
----
고객이 현재 시나리오(입력 변수 + 산출 결과)를 '원클릭'으로 개발자(Forenode)에게
전달할 수 있도록, 한 개의 구조화된 번들(.json)로 묶어 **다운로드**하게 한다.
개발자는 이 파일을 전용 폴더에 넣고 Claude Code로 분석한다(자가 피드백 루프).

전송 방식 (MVP / 서버 0)
-----------------------
다운로드 → 고객이 합의된 안전 채널(이메일 등)로 개발자에게 전달.
앱은 데이터를 외부 제3자에게 **자동 전송하지 않는다**. 번들은 고객 PC에만 저장된다.

보안 원칙
--------
- 입력 변수와 Forenode 자체 산출 근거는 외부에 공개/유출되지 않는다.
- 재학습/분석 활용은 '명시적 동의' 여부를 번들에 기록한다(분석 요청 자체는 동의와 무관).
- Claude Code가 입력 데이터를 보는 것은 개발자만 가능하다(고객은 파일만 넘김).
"""
from __future__ import annotations

import json
import hashlib
from datetime import datetime, timezone, timedelta

import streamlit as st

SCHEMA_VERSION = "1.0"
KST = timezone(timedelta(hours=9))

CONSENT_TEXT = (
    "본 시나리오의 **입력 변수**와 Forenode가 **자체 산출한 분석 근거**를, "
    "서비스 품질 개선 및 모델 재학습 목적으로 Forenode(개발자)가 활용하는 데 동의합니다. "
    "데이터는 외부 제3자에게 공개·유출되지 않으며, 동의는 계약 과정에서 언제든 철회할 수 있습니다."
)


def build_bundle(scenario: dict, *, project_name: str, consent: bool) -> dict:
    """입력+산출+메타+동의여부를 하나의 직렬화 가능한 dict로 묶고 체크섬을 부여."""
    now = datetime.now(KST)
    payload = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now.isoformat(),
        "project_name": project_name or "(미입력)",
        "consent_retrain": bool(consent),
        "consent_text": CONSENT_TEXT if consent else None,
        "inputs": scenario.get("inputs", {}),
        "outputs": scenario.get("outputs", {}),
    }
    # 무결성 체크섬: 전달 중 변조/누락 여부 확인용 (핵심 본문만 해싱)
    body = json.dumps(
        {k: payload[k] for k in ("inputs", "outputs", "consent_retrain")},
        ensure_ascii=False,
        sort_keys=True,
    )
    payload["checksum_sha256"] = hashlib.sha256(body.encode("utf-8")).hexdigest()[:16]
    return payload


def render_handoff_section(scenario: dict, *, project_name: str = "") -> None:
    """KPI 결과 직후에 호출. 고객용 '개발자에게 분석 요청 보내기' 섹션을 렌더."""
    with st.expander("📤 개발자에게 분석 요청 보내기", expanded=False):
        st.caption(
            "현재 **입력값과 산출 결과**를 한 파일로 묶어 내려받은 뒤, 안내받은 채널(이메일 등)로 "
            "Forenode 담당자에게 보내주시면 정밀 분석 결과를 회신드립니다. "
            "이 파일은 **고객님 PC에만 저장**되며, 앱이 외부로 자동 전송하지 않습니다."
        )

        consent = st.checkbox(CONSENT_TEXT, value=False, key="dev_handoff_consent")
        if consent:
            st.caption("✅ 재학습·분석 활용에 **동의**하셨습니다. (번들에 기록됩니다)")
        else:
            st.caption("ℹ️ 미동의 상태로도 1회성 분석 요청은 보낼 수 있습니다. (재학습엔 사용하지 않음)")

        bundle = build_bundle(scenario, project_name=project_name, consent=consent)
        safe_name = (project_name or "untitled").strip().replace(" ", "_") or "untitled"
        fname = f"forenode_scenario_{safe_name}_{datetime.now(KST).strftime('%Y%m%d_%H%M')}.json"
        data = json.dumps(bundle, ensure_ascii=False, indent=2).encode("utf-8")

        st.download_button(
            "📥 분석 요청 데이터 내려받기 (.json)",
            data=data,
            file_name=fname,
            mime="application/json",
            use_container_width=True,
        )
        st.caption(
            f"무결성 코드 `{bundle['checksum_sha256']}` · 전달 시 함께 알려주시면 변조 여부를 확인합니다."
        )
