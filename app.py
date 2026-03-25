import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px

st.set_page_config(page_title="거래처 관리 대시보드", layout="wide")
st.title("🐾 거래처 관리 대시보드")
st.caption("경보제약 동물의약품 | 기준일: 2026-03-24")

uploaded = st.file_uploader("Raw 엑셀 파일 업로드", type=["xlsx"])

if uploaded:
    df = pd.read_excel(uploaded, sheet_name="Raw")
    df_d = df[
        (df['거래구분'] == '신규처') &
        (df['거래처명'].notna())
    ].copy()
    df_d['매출일(배송완료일)'] = pd.to_datetime(df_d['매출일(배송완료일)'], errors='coerce')
    df_d = df_d[df_d['매출일(배송완료일)'].notna()]
    df_d = df_d.sort_values(['거래처명', '매출일(배송완료일)'])
    ref_date = pd.Timestamp('2026-03-24')

    g = df_d.groupby('거래처명')
    features = pd.DataFrame({
        '첫구매일'       : g['매출일(배송완료일)'].min(),
        '마지막구매일'   : g['매출일(배송완료일)'].max(),
        '총구매횟수'     : g['매출일(배송완료일)'].count(),
        '구매제품수'     : g['품명요약2'].nunique(),
        '누적매출액'     : g['매출액(vat 제외)'].sum(),
        '담당자'         : g['담당자'].last(),
        '지역'           : g['지역1'].last(),
        '마지막주문수량' : g['매출수량'].last(),
        '평균주문수량'   : g['매출수량'].mean(),
    }).reset_index()

    features['활동기간_일']  = (features['마지막구매일'] - features['첫구매일']).dt.days.fillna(0)
    features['미구매일수']   = (ref_date - features['마지막구매일']).dt.days.fillna(999)
    features['평균구매주기'] = features['활동기간_일'] / features['총구매횟수'].replace(0, 1)
    features['주기배율']     = features['미구매일수'] / features['평균구매주기'].replace(0, 1)

    def top3_products(hosp_name):
        d   = df_d[df_d['거래처명'] == hosp_name]
        top = d.groupby('품명요약2')['매출수량'].sum().sort_values(ascending=False).head(3)
        return ' / '.join([f"{prod} {int(qty)}개" for prod, qty in top.items()])

    with st.spinner("분석 중..."):
        features['주요제품'] = features['거래처명'].apply(top3_products)

    def assign_status(row):
        inactive = row['미구매일수']
        cnt      = row['총구매횟수']
        ratio    = row['주기배율']
        revenue  = row['누적매출액']
        last_qty = row['마지막주문수량']
        avg_qty  = row['평균주문수량']

        # 이탈: 3가지 모두 해당
        if (inactive >= 365 and
            (revenue <= 300000 or cnt <= 2) and
            last_qty <= avg_qty):
            return '🔴 이탈'

        # 관찰중: 1~2회 + 180일 이내
        if cnt <= 2 and inactive <= 180:
            return '⬜ 관찰중'

        # 1~2회인데 180일 초과
        if cnt <= 2 and inactive > 180:
            return '🟡 모니터링'

        # 정상
        if ratio < 1.2:
            return '🟢 정상'

        # 모니터링
        if ratio < 3.0:
            return '🟡 모니터링'

        return '🟡 모니터링'

    features['상태'] = features.apply(assign_status, axis=1)

    top20_threshold        = features['누적매출액'].quantile(0.80)
    features['핵심거래처'] = features['누적매출액'] >= top20_threshold

    # ── 전체 현황 요약 ─────────────────────────────────
    st.subheader("📊 전체 현황")

    total   = len(features)
    normal  = (features['상태'] == '🟢 정상').sum()
    monitor = (features['상태'] == '🟡 모니터링').sum()
    churned = (features['상태'] == '🔴 이탈').sum()
    watch   = (features['상태'] == '⬜ 관찰중').sum()
    core    = features['핵심거래처'].sum()

    c1, c2, c3, c4, c5, c6 = st.columns(6)
    c1.metric("전체",        f"{total}개")
    c2.metric("🟢 정상",     f"{normal}개",  f"{normal/total:.0%}")
    c3.metric("🟡 모니터링", f"{monitor}개", f"{monitor/total:.0%}")
    c4.metric("🔴 이탈",     f"{churned}개", f"{churned/total:.0%}")
    c5.metric("⬜ 관찰중",   f"{watch}개",   f"{watch/total:.0%}")
    c6.metric("⭐ 핵심",     f"{core}개",    f"{core/total:.0%}")

    pie_data = pd.DataFrame({
        '상태': ['🟢 정상', '🟡 모니터링', '🔴 이탈', '⬜ 관찰중'],
        '수':   [normal, monitor, churned, watch]
    })
    fig = px.pie(pie_data, values='수', names='상태',
                 color='상태',
                 color_discrete_map={
                     '🟢 정상':     '#2ecc71',
                     '🟡 모니터링': '#f39c12',
                     '🔴 이탈':     '#e74c3c',
                     '⬜ 관찰중':   '#bdc3c7',
                 })
    fig.update_layout(height=300, margin=dict(t=0, b=0))
    st.plotly_chart(fig, use_container_width=True)

    st.divider()

    # ── 전체 거래처 목록 ───────────────────────────────
    st.subheader("📋 전체 거래처")

    col_f1, col_f2 = st.columns(2)
    mgr_list    = ['전체'] + sorted(features['담당자'].dropna().unique().tolist())
    status_list = ['전체', '🟢 정상', '🟡 모니터링', '🔴 이탈', '⬜ 관찰중']
    selected_mgr    = col_f1.selectbox("담당자", mgr_list)
    selected_status = col_f2.selectbox("상태",   status_list)

    result = features.copy()
    if selected_mgr    != '전체':
        result = result[result['담당자'] == selected_mgr]
    if selected_status != '전체':
        result = result[result['상태']   == selected_status]

    result = result.sort_values('누적매출액', ascending=False)

    # 표시용 변환 (정렬 후)
    display = pd.DataFrame()
    display['거래처명']    = result['거래처명'].values
    display['담당자']      = result['담당자'].values
    display['지역']        = result['지역'].values
    display['상태']        = result['상태'].values
    display['총구매횟수']  = result['총구매횟수'].values
    display['구매제품수']  = result['구매제품수'].values
    display['누적매출액']  = result['누적매출액'].apply(lambda x: f"{x:,.0f}원").values
    display['미구매일수']  = result['미구매일수'].values
    display['평균구매주기']= result['평균구매주기'].apply(lambda x: f"{x:.0f}일").values
    display['주기배율']    = result['주기배율'].apply(lambda x: f"{x:.1f}배").values
    display['주요제품']    = result['주요제품'].values

    st.dataframe(display, use_container_width=True, hide_index=True)
