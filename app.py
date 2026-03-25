import streamlit as st
import pandas as pd
import numpy as np
from sklearn.ensemble import RandomForestClassifier
from sklearn.preprocessing import LabelEncoder
from itertools import combinations
from collections import defaultdict

st.set_page_config(page_title="이탈 예측 대시보드", layout="wide")
st.title("🐾 동물병원 이탈 예측 대시보드")
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

    ref_date = pd.Timestamp('2026-03-24')

    # ── 피처 생성 ──────────────────────────────
    g = df_d.groupby('거래처명')
    features = pd.DataFrame({
        '첫구매일'   : g['매출일(배송완료일)'].min(),
        '마지막구매일': g['매출일(배송완료일)'].max(),
        '총구매횟수'  : g['매출일(배송완료일)'].count(),
        '구매제품수'  : g['품명요약2'].nunique(),
        '누적매출액'  : g['매출액(vat 제외)'].sum(),
        '담당자'     : g['담당자'].last(),
        '지역'       : g['지역1'].last(),
    }).reset_index()

    features['활동기간_일']  = (features['마지막구매일'] - features['첫구매일']).dt.days.fillna(0)
    features['미구매일수']   = (ref_date - features['마지막구매일']).dt.days.fillna(999)
    features['평균구매주기'] = features['활동기간_일'] / features['총구매횟수'].replace(0, 1)
    features['거래처당매출'] = features['누적매출액'] / features['총구매횟수'].replace(0, 1)
    features['이탈']        = (features['미구매일수'] >= 180).astype(int)

    le_mgr = LabelEncoder()
    le_reg = LabelEncoder()
    features['담당자_enc'] = le_mgr.fit_transform(features['담당자'].fillna('없음'))
    features['지역_enc']   = le_reg.fit_transform(features['지역'].fillna('없음'))

    feature_cols = ['총구매횟수', '구매제품수', '누적매출액', '활동기간_일',
                    '평균구매주기', '거래처당매출', '담당자_enc', '지역_enc']
    X = features[feature_cols].fillna(0)
    y = features['이탈']
    mask = y.notna() & (X.notna().all(axis=1))
    X = X[mask].astype(float)
    y = y[mask].astype(int)

    model = RandomForestClassifier(n_estimators=200, max_depth=6,
                                    random_state=42, class_weight='balanced')
    model.fit(X, y)
    features.loc[mask, '이탈확률'] = model.predict_proba(X)[:, 1]
    features['이탈확률'] = features['이탈확률'].fillna(0.5)
    features['위험등급'] = pd.cut(features['이탈확률'],
        bins=[0, 0.3, 0.5, 0.7, 1.0],
        labels=['🟢 안전', '🟡 주의', '🟠 위험', '🔴 긴급'])

    # ── 소진 분석 ──────────────────────────────
    소진주기 = {prod: 30 for prod in df_d['품명요약2'].dropna().unique()}

    prod_last = df_d.groupby(['거래처명', '품명요약2']).agg(
        마지막구매일=('매출일(배송완료일)', 'max'),
        마지막주문수량=('매출수량', 'last'),
    ).reset_index()

    prod_last['소진일수']   = prod_last['품명요약2'].map(소진주기)
    prod_last['소진예정일'] = (
        prod_last['마지막구매일'] +
        pd.to_timedelta(prod_last['마지막주문수량'] * prod_last['소진일수'], unit='d')
    )
    prod_last['잔여일수'] = (prod_last['소진예정일'] - ref_date).dt.days

    def status(days):
        if days > 60:   return '🟢 안전'
        elif days > 45: return '🟡 유의'
        elif days > 30: return '🟠 위험'
        else:           return '🔴 긴급'

    prod_last['소진상태'] = prod_last['잔여일수'].apply(status)

    urgent_prod = prod_last.sort_values('잔여일수').groupby('거래처명').first().reset_index()
    urgent_prod = urgent_prod[['거래처명', '품명요약2', '잔여일수', '소진상태']]
    urgent_prod.columns = ['거래처명', '재주문필요제품', '잔여일수', '소진상태']

    # ── 교차판매 ───────────────────────────────
    hosp_prods = df_d.groupby('거래처명')['품명요약2'].apply(set)
    prod_count  = defaultdict(int)
    combo_count = defaultdict(int)

    for prods in hosp_prods:
        for p in prods:
            prod_count[p] += 1
        for a, b in combinations(sorted(prods), 2):
            combo_count[(a, b)] += 1

    reco_map = {}
    for prod in prod_count:
        candidates = []
        for (a, b), cnt in combo_count.items():
            if a == prod:
                candidates.append((b, cnt / prod_count[a]))
            elif b == prod:
                candidates.append((a, cnt / prod_count[b]))
        if candidates:
            candidates.sort(key=lambda x: -x[1])
            reco_map[prod] = candidates[0]

    def get_reco(bought_prods):
        recos = []
        for prod in bought_prods:
            if prod in reco_map:
                reco_prod, conf = reco_map[prod]
                if reco_prod not in bought_prods:
                    recos.append((reco_prod, conf, prod))
        if recos:
            recos.sort(key=lambda x: -x[1])
            return recos[0][0], f"{recos[0][2]} 구매처의 {recos[0][1]:.0%}가 함께 구매"
        return None, None

    hosp_prod_set = df_d.groupby('거래처명')['품명요약2'].apply(set).reset_index()
    hosp_prod_set.columns = ['거래처명', '구매제품세트']
    hosp_prod_set['추천제품'], hosp_prod_set['추천근거'] = zip(
        *hosp_prod_set.apply(lambda r: get_reco(r['구매제품세트']), axis=1)
    )

    # ── 최종 합치기 ────────────────────────────
    final = features[['거래처명', '담당자', '지역', '미구매일수',
                       '총구매횟수', '구매제품수', '누적매출액',
                       '이탈확률', '위험등급']].copy()
    final = final.merge(urgent_prod, on='거래처명', how='left')
    final = final.merge(
        hosp_prod_set[['거래처명', '추천제품', '추천근거']],
        on='거래처명', how='left'
    )
    final = final.sort_values('이탈확률', ascending=False)
    final['이탈확률_표시'] = (final['이탈확률'] * 100).round(1).astype(str) + '%'
    final['누적매출액']    = final['누적매출액'].apply(lambda x: f"{x:,.0f}원")

    # ── 요약 지표 ──────────────────────────────
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("전체 거래처",  f"{len(final)}개")
    col2.metric("🔴 긴급",     f"{(final['위험등급']=='🔴 긴급').sum()}개")
    col3.metric("재주문 필요",  f"{final['재주문필요제품'].notna().sum()}개")
    col4.metric("교차판매 기회",f"{final['추천제품'].notna().sum()}개")

    st.divider()

    # ── 필터 ───────────────────────────────────
    col_f1, col_f2 = st.columns(2)
    mgr_list   = ['전체'] + sorted(final['담당자'].dropna().unique().tolist())
    grade_list = ['전체', '🔴 긴급', '🟠 위험', '🟡 주의', '🟢 안전']

    selected_mgr   = col_f1.selectbox("담당자 선택", mgr_list)
    selected_grade = col_f2.selectbox("위험등급 선택", grade_list)

    result = final.copy()
    if selected_mgr != '전체':
        result = result[result['담당자'] == selected_mgr]
    if selected_grade != '전체':
        result = result[result['위험등급'] == selected_grade]

    display_cols = ['거래처명', '담당자', '지역', '위험등급', '이탈확률_표시',
                    '재주문필요제품', '소진상태', '잔여일수',
                    '추천제품', '추천근거', '누적매출액']

    st.subheader(f"거래처 목록 ({len(result)}개)")
    st.dataframe(result[display_cols], use_container_width=True, hide_index=True)
