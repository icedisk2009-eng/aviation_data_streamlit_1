import streamlit as st
import requests
import pandas as pd
import numpy as np
import pydeck as pdk
import time
from datetime import datetime
from streamlit_autorefresh import st_autorefresh

st.set_page_config(page_title="AI 스마트 항공 관제탑", layout="wide")

# ─────────────────────────────────────────────
# 10초마다 전체 스크립트 자동 재실행
# ─────────────────────────────────────────────
refresh_count = st_autorefresh(interval=10 * 1000, key="dashboard_autorefresh")

# ─────────────────────────────────────────────
# 위험 아이콘 깜빡임 효과용 CSS
# ─────────────────────────────────────────────
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
.dot-normal { background-color: #22c55e; }
.dot-danger {
    background-color: #ef4444;
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

TOKEN_URL = "https://auth.opensky-network.org/auth/realms/opensky-network/protocol/openid-connect/token"
STATES_URL = "https://opensky-network.org/api/states/all"


@st.cache_data(ttl=1500)  # 토큰 유효시간(보통 30분)보다 짧게 캐시
def get_access_token():
    """OpenSky OAuth2 client_credentials 방식으로 access token 발급받기"""
    client_id = st.secrets["client_id"]
    client_secret = st.secrets["client_secret"]

    payload = {
        "grant_type": "client_credentials",
        "client_id": client_id,
        "client_secret": client_secret,
    }
    response = requests.post(TOKEN_URL, data=payload, timeout=30)
    response.raise_for_status()
    return response.json()["access_token"]


@st.cache_data(ttl=15)  # OpenSky 인증 사용자 기준 최소 요청 간격은 5초, 여유있게 15초로 설정
def fetch_flight_data(token):
    params = {"lamin": 33.0, "lamax": 39.0, "lomin": 124.0, "lomax": 132.0}
    headers = {"Authorization": f"Bearer {token}"}

    for attempt in range(3):
        try:
            response = requests.get(STATES_URL, params=params, headers=headers, timeout=30)
            response.raise_for_status()
            data = response.json()
            if data.get("states") is not None:
                columns = [
                    "icao24", "callsign", "origin_country", "time_position",
                    "last_contact", "longitude", "latitude", "baro_altitude",
                    "on_ground", "velocity", "true_track", "vertical_rate",
                    "sensors", "geo_altitude", "squawk", "spi", "position_source",
                ]
                df = pd.DataFrame(data["states"], columns=columns)
                df["callsign"] = df["callsign"].str.strip()
                return df
            return pd.DataFrame()
        except Exception as e:
            if attempt == 2:
                st.error(f"API 요청 중 에러: {e}")
                return None
            time.sleep(3)


st.title("🚨 스마트 항공 관제탑 (한반도 상공)")

col_btn, col_info = st.columns([1, 3])
with col_btn:
    if st.button("🔄 수동 새로고침"):
        fetch_flight_data.clear()  # 항공 데이터 캐시만 지움 (토큰 캐시는 그대로 유지)
        st.rerun()
with col_info:
    st.caption(f"자동 새로고침: 10초마다 (누적 {refresh_count}회) · 마지막 갱신: {datetime.now().strftime('%H:%M:%S')}")

try:
    with st.spinner("인증 토큰 발급 중..."):
        token = get_access_token()
except Exception as e:
    st.error(f"OAuth2 인증 실패: {e}")
    st.info("Streamlit Cloud의 App settings → Secrets에 client_id / client_secret이 올바르게 등록되어 있는지 확인해야 함.")
    st.stop()

with st.spinner("실시간 데이터를 불러오는 중..."):
    df = fetch_flight_data(token)

# 토큰이 만료됐거나 거부당한 경우, 토큰만 새로 받아서 한 번 더 시도
if df is None:
    get_access_token.clear()  # 토큰 캐시만 지움
    with st.spinner("토큰 재발급 후 재시도 중..."):
        try:
            token = get_access_token()
            fetch_flight_data.clear()
            df = fetch_flight_data(token)
        except Exception as e:
            st.error(f"재시도 실패: {e}")

if df is not None and not df.empty:
    analysis_df = df.dropna(subset=["latitude", "longitude", "vertical_rate"]).copy()
    vr_mean = analysis_df["vertical_rate"].mean()
    vr_std = analysis_df["vertical_rate"].std()
    analysis_df["z_score"] = 0.0 if pd.isna(vr_std) or vr_std == 0 else (analysis_df["vertical_rate"] - vr_mean) / vr_std

    with st.sidebar:
        st.subheader("⚙️ 위험 경보 설정")
        threshold = st.slider(
            "위험 경보 Z-score 기준값",
            min_value=-5.0, max_value=0.0,
            value=-3.0, step=0.1,
            help="통계적으로 -3.0 이하는 이상치(급강하)로 간주함"
        )

    analysis_df["status"] = np.where(analysis_df["z_score"] <= threshold, "danger", "normal")
    # pydeck 마커 색상: 정상=초록, 위험=빨강 (RGBA)
    analysis_df["color"] = analysis_df["status"].apply(
        lambda s: [239, 68, 68, 200] if s == "danger" else [34, 197, 94, 160]
    )
    danger_count = (analysis_df["status"] == "danger").sum()

    m1, m2, m3 = st.columns(3)
    m1.metric("총 탐지된 비행기", f"{len(analysis_df)} 대")
    m2.metric("🔴 위험(급강하) 비행기", f"{danger_count} 대")
    m3.metric("평균 수직 승강률", f"{vr_mean:.2f} m/s")

    # ─────────────────────────────────────────────
    # 지도: pydeck으로 정상(초록)/위험(빨강) 색상 구분
    # ─────────────────────────────────────────────
    st.markdown("### 🗺️ 실시간 항공기 위치")
    view_state = pdk.ViewState(
        latitude=36.0, longitude=128.0, zoom=5.3, pitch=0
    )
    scatter_layer = pdk.Layer(
        "ScatterplotLayer",
        data=analysis_df,
        get_position=["longitude", "latitude"],
        get_fill_color="color",
        get_radius=4000,
        pickable=True,
    )
    deck = pdk.Deck(
        layers=[scatter_layer],
        initial_view_state=view_state,
        tooltip={"text": "{callsign}\n상태: {status}\nz-score: {z_score}"},
    )
    st.pydeck_chart(deck)

    col_left, col_right = st.columns([1.3, 1])

    with col_left:
        st.markdown("### ✈️ 탐지된 항공기 목록")
        for _, row in analysis_df.sort_values("z_score").iterrows():
            dot_class = "dot-danger" if row["status"] == "danger" else "dot-normal"
            label = "위험(이상치)" if row["status"] == "danger" else "정상"
            st.markdown(
                f"""
                <div style="display:flex; align-items:center; padding:4px 0;">
                    <span class="status-dot {dot_class}"></span>
                    <b>{row['callsign']}</b>&nbsp;&nbsp;
                    수직속도 {row['vertical_rate']:.2f} m/s &nbsp;|&nbsp;
                    z-score {row['z_score']:.2f} &nbsp;|&nbsp;
                    <span style="color:#aaa;">{label}</span>
                </div>
                """,
                unsafe_allow_html=True
            )

    with col_right:
        st.markdown("### 🚨 실시간 알림 (위험 항공기)")
        alerts = analysis_df[analysis_df["status"] == "danger"].sort_values("z_score")
        if alerts.empty:
            st.info("현재 위험 항공기 없음.")
        else:
            now_str = datetime.now().strftime("%H:%M:%S")
            for _, row in alerts.iterrows():
                st.markdown(
                    f"""
                    <div class="alert-card">
                        🔴 <b>{now_str}</b> — 편명 <b>{row['callsign']}</b> |
                        수직속도 <b>{row['vertical_rate']:.2f} m/s</b> |
                        z-score {row['z_score']:.2f}
                    </div>
                    """,
                    unsafe_allow_html=True
                )

    with st.expander("📋 전체 데이터 테이블 보기"):
        st.dataframe(
            analysis_df[["callsign", "status", "z_score", "vertical_rate"]].sort_values(by="z_score")
        )
else:
    st.warning("현재 감지된 비행기가 없거나 API 호출 대기 중입니다.")
