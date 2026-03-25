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
    X = features[f
