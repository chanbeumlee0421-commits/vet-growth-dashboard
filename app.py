from itertools import combinations
from collections import defaultdict

# 소진주기 (전부 30일)
소진주기 = {prod: 30 for prod in df_d['품명요약2'].dropna().unique()}

# 거래처 × 제품별 마지막 주문 정보
prod_last = df_d.groupby(['거래처명', '품명요약2']).agg(
    마지막구매일=('매출일(배송완료일)', 'max'),
    마지막주문수량=('매출수량', 'last'),
    총주문수량=('매출수량', 'sum'),
    구매횟수=('매출일(배송완료일)', 'count')
).reset_index()

# 소진 예정일 계산
prod_last['소진일수'] = prod_last['품명요약2'].map(소진주기)
prod_last['소진예정일'] = (
    prod_last['마지막구매일'] +
    pd.to_timedelta(prod_last['마지막주문수량'] * prod_last['소진일수'], unit='d')
)

# 잔여일수
prod_last['잔여일수'] = (prod_last['소진예정일'] - ref_date).dt.days

# 소진 상태 기준
def status(days):
    if days > 60:   return '🟢 안전'
    elif days > 45: return '🟡 유의'
    elif days > 30: return '🟠 위험'
    else:           return '🔴 긴급'

prod_last['소진상태'] = prod_last['잔여일수'].apply(status)

# 교차판매 룰
hosp_prods = df_d.groupby('거래처명')['품명요약2'].apply(set)
prod_count = defaultdict(int)
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
            conf = cnt / prod_count[a]
            candidates.append((b, conf))
        elif b == prod:
            conf = cnt / prod_count[b]
            candidates.append((a, conf))
    if candidates:
        candidates.sort(key=lambda x: -x[1])
        reco_map[prod] = candidates[0]

# 거래처별 추천 제품
def get_reco(hosp_name, bought_prods):
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
    *hosp_prod_set.apply(
        lambda r: get_reco(r['거래처명'], r['구매제품세트']), axis=1)
)

# 소진 위험 제품 (거래처별 가장 급한 것)
urgent_prod = prod_last.sort_values('잔여일수').groupby('거래처명').first().reset_index()
urgent_prod = urgent_prod[['거래처명', '품명요약2', '잔여일수', '소진상태']]
urgent_prod.columns = ['거래처명', '재주문필요제품', '잔여일수', '소진상태']

# 최종 합치기
final = features[['거래처명', '담당자', '지역', '미구매일수',
                   '총구매횟수', '구매제품수', '누적매출액',
                   '이탈확률', '위험등급']].copy()

final = final.merge(urgent_prod, on='거래처명', how='left')
final = final.merge(
    hosp_prod_set[['거래처명', '추천제품', '추천근거']],
    on='거래처명', how='left'
)

final['이탈확률_표시'] = (final['이탈확률'] * 100).round(1).astype(str) + '%'
final['누적매출액_표시'] = final['누적매출액'].apply(lambda x: f"{x:,.0f}원")
final = final.sort_values('이탈확률', ascending=False)

print(f"전체: {len(final)}개 거래처")
print(f"재주문 필요: {final['재주문필요제품'].notna().sum()}개")
print(f"교차판매 기회: {final['추천제품'].notna().sum()}개")
print()
print(final[['거래처명', '담당자', '위험등급', 
             '재주문필요제품', '소진상태', '추천제품']].head(10).to_string())
