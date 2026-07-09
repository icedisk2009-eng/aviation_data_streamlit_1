"""
AI 스마트 항공 관제탑 - 개선된 UI 컴포넌트
기존 대시보드에 아래 함수/블록들을 그대로 이식해서 사용하면 됨.
전제: df에는 callsign, altitude, vertical_rate, vertical_rate_zscore, timestamp 컬럼이 있다고 가정함.

설치 필요: pip install streamlit-autorefresh
→ 10초마다 st_autorefresh가 스크립트 전체를 재실행함.
  실제 데이터 로딩 부분(OpenSky API 호출 등)이 매번 다시 실행되므로,
  API 호출 비용이 부담되면 @st.cache_data(ttl=10) 붙여서 캐싱 권장함.
"""

import streamlit as st
import pandas as pd
from datetime import datetime
from streamlit_autorefresh import st_autorefresh

# ─────────────────────────────────────────────
# 0. 페이지 기본 세팅 (기존 유지, 없으면 추가)
# ─────────────────────────────────────────────
st.set_page_config(page_title="AI 스마트 항공 관제탑", layout="wide")

# 10초마다 자동 새로고침 (count는 새로고침 횟수, 필요시 디버깅용)
refresh_count = st_autorefresh(interval=10 * 1000, key="dashboard_autorefresh")

# 깜빡임 효과용 CSS (한 번만 주입하면 됨)
st.markdown("""
<style>
@keyframes blink-red {
    0%   { opacity: 1; }
    50%  { opacity: 0.3; }
    100% { opacity: 1; }
}
.status-dot {
    display: inline-block;
    width: 12px;
    height: 12px;
    border-radius: 50%;
    margin-right: 8px;
}
.dot-normal  { background-color: #22c55e; }   /* 초록 */
.dot-danger  {
    background-color: #ef4444;                /* 빨강 */
    animation: blink-red 1s infinite;
}
.alert-card {
    padding: 10px 14px;
    border-radius: 8px;
    margin-bottom: 6px;
    background-color: #1e1e2d;
    border-left: 4px solid #ef4444;
}
</style>
""", unsafe_allow_html=True)


# ─────────────────────────────────────────────
# 1. 위험 등급 판정 함수 (z-score 기준 -3.0으로 재설계)
# ─────────────────────────────────────────────
def classify_status(z_score: float, threshold: float = -3.0) -> str:
    """
    z_score 기준 2단계 분류
    - normal : z > threshold   (정상)
    - danger : z <= threshold  (위험, 통계적 이상치)
    """
    return "danger" if z_score <= threshold else "normal"


STATUS_META = {
    "normal": {"label": "정상",         "dot_class": "dot-normal"},
    "danger": {"label": "위험(이상치)",  "dot_class": "dot-danger"},
}


# ─────────────────────────────────────────────
# 2. 사이드바 - 임계값 슬라이더 (기본값 -3.0)
# ─────────────────────────────────────────────
with st.sidebar:
    st.subheader("⚙️ 위험 경보 설정")
    danger_threshold = st.slider(
        "위험 경보 Z-score 기준값",
        min_value=-5.0, max_value=0.0,
        value=-3.0, step=0.1,
        help="통계적으로 -3.0 이하는 이상치(급강하)로 간주함"
    )
    st.caption(f"🔄 자동 새로고침: 10초마다 (누적 {refresh_count}회)")
    st.caption(f"마지막 갱신: {datetime.now().strftime('%H:%M:%S')}")


# ─────────────────────────────────────────────
# 3. 요약 지표 카드 (색상별 카운트 포함)
# ─────────────────────────────────────────────
def render_summary(df: pd.DataFrame, threshold: float = -3.0):
    df = df.copy()
    df["status"] = df["vertical_rate_zscore"].apply(classify_status, threshold=threshold)

    total = len(df)
    n_normal = (df["status"] == "normal").sum()
    n_danger = (df["status"] == "danger").sum()

    c1, c2, c3 = st.columns(3)
    c1.metric("총 탐지된 비행기", f"{total} 대")
    c2.metric("🟢 정상", f"{n_normal} 대")
    c3.metric("🔴 위험", f"{n_danger} 대")
    return df


# ─────────────────────────────────────────────
# 4. 항공기 리스트 - 색상 아이콘 적용
# ─────────────────────────────────────────────
def render_flight_list(df: pd.DataFrame):
    st.markdown("### ✈️ 탐지된 항공기 목록")
    for _, row in df.sort_values("vertical_rate_zscore").iterrows():
        meta = STATUS_META[row["status"]]
        st.markdown(
            f"""
            <div style="display:flex; align-items:center; padding:6px 0;">
                <span class="status-dot {meta['dot_class']}"></span>
                <b>{row['callsign']}</b>&nbsp;&nbsp;
                고도 {row['altitude']:.0f}m &nbsp;|&nbsp;
                수직속도 {row['vertical_rate']:.2f} m/s &nbsp;|&nbsp;
                z-score {row['vertical_rate_zscore']:.2f} &nbsp;|&nbsp;
                <span style="color:#aaa;">{meta['label']}</span>
            </div>
            """,
            unsafe_allow_html=True
        )


# ─────────────────────────────────────────────
# 5. 실시간 알림 패널 (타임라인 스트리밍)
# ─────────────────────────────────────────────
def render_alert_panel(df: pd.DataFrame):
    st.markdown("### 🚨 실시간 알림 (위험 항공기)")

    alerts = df[df["status"] == "danger"].copy()
    alerts = alerts.sort_values("timestamp", ascending=False)  # 최신이 위로

    if alerts.empty:
        st.info("현재 위험 항공기 없음.")
        return

    for _, row in alerts.iterrows():
        ts = pd.to_datetime(row["timestamp"]).strftime("%H:%M:%S")
        st.markdown(
            f"""
            <div class="alert-card">
                🔴 <b>{ts}</b> — 편명 <b>{row['callsign']}</b> |
                고도 {row['altitude']:.0f}m |
                수직속도 <b>{row['vertical_rate']:.2f} m/s</b> |
                z-score {row['vertical_rate_zscore']:.2f}
            </div>
            """,
            unsafe_allow_html=True
        )


# ─────────────────────────────────────────────
# 6. 메인 실행부 예시 (기존 데이터 로딩 로직으로 교체)
# ─────────────────────────────────────────────
if __name__ == "__main__":
    st.title("🛩️ AI 스마트 항공 관제탑 (한반도 상공)")

    # === 여기를 기존 OpenSky 데이터프레임(df)으로 교체 ===
    # @st.cache_data(ttl=10)  # 10초 캐시 → autorefresh 주기와 맞춰서 중복 API 호출 방지
    # def fetch_opensky_data():
    #     ...
    #     return df
    #
    # df = fetch_opensky_data()
    # df["vertical_rate_zscore"] = (df["vertical_rate"] - df["vertical_rate"].mean()) / df["vertical_rate"].std()

    sample = pd.DataFrame({
        "callsign": ["KAL123", "AAR456", "JJA789", "TWB001", "ABL777"],
        "altitude": [10500, 9800, 11200, 3400, 8700],
        "vertical_rate": [1.2, -5.5, 0.3, -8.9, -2.1],
        "vertical_rate_zscore": [-0.4, -2.1, 0.1, -3.6, -1.6],
        "timestamp": [datetime.now()] * 5,
    })

    df_with_status = render_summary(sample, threshold=danger_threshold)
    st.divider()
    col_left, col_right = st.columns([1.2, 1])
    with col_left:
        render_flight_list(df_with_status)
    with col_right:
        render_alert_panel(df_with_status)
