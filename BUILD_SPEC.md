# PoolDesk — 빌드 명세서 (Build Specification)
### IMCO Investment Operations 자동화 시뮬레이션 — 포트폴리오 프로젝트

> 버전 1.0 · 작성 2026-05-16 · 대상 면접: IMCO Intern, Investment Operations
> (AI, Data and Process Optimization), R26-82
>
> **이 문서는 다른 AI 모델(또는 개발자)이 처음부터 끝까지 그대로 실행할 수 있도록
> 작성된 단독(self-contained) 명세서다.** 외부 맥락 없이 이 문서만으로 빌드 가능해야 한다.

---

## 0. 실행자(다른 모델/개발자)를 위한 안내

당신은 이 문서 하나만 보고 `PoolDesk`라는 프로젝트를 빌드한다. 규칙:

1. **순서대로** — §11의 Phase 0 → Phase 14를 순서대로 진행한다. 각 Phase는 이전
   Phase의 산출물에 의존한다.
2. **각 Phase 끝에서 검증** — 해당 Phase의 "완료 기준(Acceptance Criteria)"을
   모두 통과해야 다음으로 넘어간다.
3. **재현성 필수** — 모든 무작위성은 `.env`의 `RANDOM_SEED`로 시드 고정. 같은 시드 →
   같은 데이터.
4. **키 없이도 실행 가능해야 함** — `ANTHROPIC_API_KEY`가 placeholder 상태여도
   파이프라인 전체가 끝까지 돈다(Module 6은 rule-based fallback 사용).
   `MARKET_DATA_MODE=synthetic`이면 네트워크도 불필요.
5. **작은 모듈 + 테스트** — 함수는 작게, 핵심 로직(DQ·대사·NAV)은 pytest로 검증.
6. **하드코딩 금지** — 날짜·경로·시드·요율은 모두 `config.py`가 `.env`에서 읽는다.
7. **학습용 시뮬레이션** — 프로덕션 시스템이 아니다. 단순화한 부분은 코드 주석과
   `docs/`에 명시한다. 과장 금지.

빌드 환경: Python 3.11+, 패키지는 `requirements.txt` 참조. `pip install -r requirements.txt`.

---

## 1. 프로젝트 개요

### 1.1 한 줄 정의
PoolDesk는 **기관 자산운용사의 일일 투자운영(Investment Operations) 워크플로를
시뮬레이션**하는 자동화 스위트다. 데이터피드 수집 → 품질검증 → 대사(reconciliation)
→ NAV 산출 → 예외 처리(AI) → 리포팅까지 하나의 파이프라인으로 자동화한다.

### 1.2 모델링 대상 — IMCO 구조 반영
IMCO는 온타리오 공공부문 펀드 자산을 **자산군별 풀(pool)**로 묶어 운용한다. 클라이언트는
풀의 **유닛(unit)**을 보유한다. PoolDesk는 이 구조를 그대로 본떠 **5개 풀**과
**5개 클라이언트(가상)**를 만든다.

### 1.3 공고(R26-82) 대비 — 무엇을 증명하는가
| 공고 책임/요구 항목 | 증명하는 모듈 |
|---|---|
| Develop AI-powered tools and automation solutions | Module 6, 전체 파이프라인 |
| AI-driven operational implementation framework | `docs/ai_ops_framework.md` (Module 12) |
| Thorough documentation of automated processes | `docs/` 일체 (Module 11) |
| Python, SQL, VBA scripts | Module 1–8 (Python), Module 9 (SQL), Module 10 (VBA) |
| Power Automate, SharePoint, Power BI | Module 11(Power BI), Module 12(Power Automate) |
| Monitor and measure data feeds from multiple sources | Module 1, 2 |
| Manage and improve data quality | Module 3 |
| Daily/weekly/monthly reporting and automation | Module 7 |
| Financial and data analysis | Module 4, 5 |
| Pool and transfer agency oversight | Module 5 (NAV·유닛·클라이언트 배분) |
| Document process flows, procedures, controls | `docs/runbook.md`, `docs/control_matrix.md` |

---

## 2. 데이터 전략 — "어떤 티커를 쓰나?" (핵심 설계 결정)

> 이 섹션이 프로젝트 신뢰성의 근간이다. 면접에서 반드시 이 논리로 설명할 것.

### 2.1 문제
실제 투자운영 데이터(운용사 장부, 커스터디언 기록, 클라이언트 보유)는 **기밀**이며
공개 데이터셋이 존재하지 않는다. 그렇다면 시뮬레이션의 "대상"을 무엇으로 할 것인가?

### 2.2 결정 — 3단 하이브리드
1. **증권(Securities) = 실제 티커.** IMCO의 5개 자산군을 대표하는 **실존 종목 34개**를
   바스켓으로 고정한다(§6.1). 캐나다 + 미국 종목 혼합 — IMCO가 온타리오 기반이므로
   캐나다 비중을 의도적으로 포함. → "IMCO 자산군을 본떠 풀을 구성했다"고 말할 근거.
2. **시세(Market prices) = 2-모드.**
   - `synthetic`(기본): 기하 랜덤워크로 가격 생성. 오프라인·재현가능·키 불필요.
   - `live`(옵션): `yfinance`로 실제 시세 수집(키 불필요). → "실시간 데이터피드
     수집도 구현했다"고 말할 근거.
3. **운영 데이터(포지션·거래·커스터디언·클라이언트·현금) = 100% 합성.** 실제 운용
   장부는 공개되지 않으므로 현실적인 합성 데이터를 생성한다. **이것은 약점이 아니라
   투자운영 데이터의 본질이다.**

### 2.3 면접 화법 (그대로 사용)
> *"Investment operations data — the book of records, custodian positions, client
> holdings — is internal and confidential by nature; there's no public dataset.
> So I used real tickers mapped to IMCO's five asset classes for credibility,
> with optionally-live market prices, but I generate the entire operational book
> synthetically with controlled, realistic data issues. Learning that operations
> data is inherently internal was itself part of the point."*

### 2.4 단순화 명시 (정직성)
- **PE / Real Estate / Infrastructure**는 실제로는 비유동·정기평가 자산이다. 본 프로젝트는
  **상장 프록시(BX, KKR, REIT, BIP 등)**로 대체하고 일간 가격을 부여한다. 이 단순화는
  `docs/` 와 `securities_master` 의 코드 주석에 명시한다.
- **클라이언트는 가상**이다. IMCO의 공공부문 클라이언트 구성에서 영감을 받았으나
  실존 기관이 아니다. 데이터에 `# fictional` 주석 명시.

---

## 3. 기술 스택 & 의존성

| 영역 | 사용 |
|---|---|
| 언어 | Python 3.11+ |
| 데이터 처리 | pandas, numpy |
| DB | SQLite (Python 표준 `sqlite3`) |
| Excel 출력 | openpyxl |
| PDF 출력 | fpdf2 (+ matplotlib 차트) |
| LLM | anthropic SDK (Claude Messages API) |
| 실시간 시세(옵션) | yfinance |
| 설정 | python-dotenv |
| 테스트 | pytest |
| VBA | Excel `.xlsm` 매크로 (수동 작성, §Module 10에 코드 제공) |
| Power BI | Power BI Desktop (수동, §Module 11에 단계 제공) |
| Power Automate | 클라우드 플로우 (수동, §Module 12에 단계 제공) |

`requirements.txt`는 프로젝트 루트에 이미 존재. Python 코드 모듈은 이것만으로 동작해야 한다.

---

## 4. 리포지토리 레이아웃

```
pooldesk/
├── README.md                     ← Module 13 산출 (영문, 스크린샷 포함)
├── BUILD_SPEC.md                  ← 이 문서
├── requirements.txt               ← 존재함
├── .env                           ← 존재함 (placeholder, git-ignored)
├── .env.example                   ← 존재함
├── .gitignore                     ← 존재함
├── config.py                      ← Phase 0: .env 로딩, 상수
├── main.py                        ← Phase 8: CLI 오케스트레이터
│
├── pooldesk/                      ← 파이썬 패키지
│   ├── __init__.py
│   ├── reference.py               ← Module 1a: 정적 참조데이터(증권·풀·클라이언트)
│   ├── data_generator.py          ← Module 1b: 일별 합성 데이터 + 이슈 주입
│   ├── market_data.py             ← Module 1c: synthetic/live 시세 소스
│   ├── ingest.py                  ← Module 2: CSV → SQLite 적재
│   ├── data_quality.py            ← Module 3: 품질 검증 엔진
│   ├── reconcile.py               ← Module 4: 대사 엔진
│   ├── nav.py                     ← Module 5: NAV·유닛·클라이언트 배분
│   ├── ai_assistant.py            ← Module 6: AI 예외 어시스턴트 (+fallback)
│   ├── reporting.py               ← Module 7: Excel/PDF 리포트
│   └── db.py                      ← DB 연결·헬퍼
│
├── sql/
│   ├── schema.sql                 ← Module 2: 테이블 DDL
│   └── checks.sql                 ← Module 9: 대사·DQ SQL 쿼리 모음
│
├── excel/
│   └── PoolDesk_Macro.xlsm        ← Module 10: VBA 매크로 워크북
│
├── powerbi/
│   └── PoolDesk.pbix              ← Module 11: 대시보드 (+ powerbi/README.md 빌드법)
│
├── automate/
│   └── flow_spec.md               ← Module 12: Power Automate 플로우 정의서
│
├── docs/
│   ├── process_flow.md            ← Module 11(docs): mermaid 흐름도
│   ├── runbook.md                 ← 운영 절차서
│   ├── control_matrix.md          ← 통제 매트릭스
│   └── ai_ops_framework.md        ← AI 운영 구현 프레임워크
│
├── data/                          ← 생성물 (git-ignored)
│   ├── reference/                 ← securities_master.csv 등 정적
│   └── feeds/                     ← 일별 피드 CSV
│
├── reports/                       ← 생성물 (git-ignored)
│
└── tests/
    ├── test_data_quality.py
    ├── test_reconcile.py
    └── test_nav.py
```

---

## 5. 설정 (`config.py`)

`config.py`는 `.env`를 `python-dotenv`로 로드해 다음을 노출한다:

```python
# config.py — 시그니처 가이드
ANTHROPIC_API_KEY: str        # placeholder면 AI는 fallback 모드
ANTHROPIC_MODEL: str          # 기본 "claude-haiku-4-5-20251001"
MARKET_DATA_MODE: str         # "synthetic" | "live"
ALPHAVANTAGE_API_KEY: str     # 선택, 미사용 가능
BASE_CURRENCY: str            # "CAD"
SIM_START_DATE: date          # 시뮬레이션 시작일
SIM_DAYS: int                 # 영업일 수
RANDOM_SEED: int              # 재현성 시드
DB_PATH: Path
DATA_DIR: Path
REPORTS_DIR: Path

def has_live_ai() -> bool:    # 키가 placeholder가 아니면 True
def business_days(start, n) -> list[date]:   # 주말 제외 영업일 리스트
```

**판정 규칙**: `ANTHROPIC_API_KEY`가 비었거나 `REPLACE_ME`를 포함하면
`has_live_ai() == False` → Module 6은 rule-based fallback.

---

## 6. 데이터 모델 — 전체 파일 & 스키마

### 6.1 증권 마스터 (참조데이터, 정적) — `data/reference/securities_master.csv`

`reference.py`가 1회 생성. 컬럼:

| 컬럼 | 타입 | 설명 |
|---|---|---|
| `security_id` | str | `SEC0001` 형식 |
| `isin` | str | 합성 ISIN(형식만 유효): `CA`/`US` + 10자리 |
| `ticker` | str | **실제 티커** (live 모드에서 사용) |
| `name` | str | 종목명 |
| `asset_class` | str | EQUITY / FIXED_INCOME / PRIVATE_EQUITY / REAL_ESTATE / INFRASTRUCTURE |
| `pool_id` | str | 소속 풀 |
| `currency` | str | USD / CAD |
| `country` | str | US / CA |

**고정 티커 바스켓 (34종목)** — 이 목록을 그대로 사용:

```
POOL_EQ  (Global Equity, EQUITY):
  RY.TO  Royal Bank of Canada      CAD CA
  TD.TO  Toronto-Dominion Bank     CAD CA
  SHOP.TO Shopify Inc              CAD CA
  CNR.TO Canadian National Railway CAD CA
  ENB.TO Enbridge Inc              CAD CA
  AAPL   Apple Inc                 USD US
  MSFT   Microsoft Corp            USD US
  NVDA   NVIDIA Corp               USD US
  JPM    JPMorgan Chase            USD US
  JNJ    Johnson & Johnson         USD US

POOL_FI  (Fixed Income, FIXED_INCOME):
  AGG    iShares Core US Aggregate Bond  USD US
  BND    Vanguard Total Bond Market      USD US
  TLT    iShares 20+ Yr Treasury Bond    USD US
  LQD    iShares iBoxx IG Corp Bond      USD US
  IEF    iShares 7-10 Yr Treasury Bond   USD US
  XBB.TO iShares Core CAD Universe Bond  CAD CA
  ZAG.TO BMO Aggregate Bond Index ETF    CAD CA

POOL_PE  (Private Equity proxy, PRIVATE_EQUITY):   # 상장 프록시 — 단순화 명시
  BX     Blackstone Inc            USD US
  KKR    KKR & Co Inc              USD US
  APO    Apollo Global Management  USD US
  ARES   Ares Management Corp      USD US
  CG     Carlyle Group             USD US
  BAM    Brookfield Asset Mgmt     USD US

POOL_RE  (Real Estate proxy, REAL_ESTATE):         # 상장 REIT 프록시
  PLD       Prologis Inc             USD US
  AMT       American Tower Corp      USD US
  SPG       Simon Property Group     USD US
  O         Realty Income Corp       USD US
  REI-UN.TO RioCan REIT              CAD CA
  CAR-UN.TO Canadian Apartment REIT  CAD CA

POOL_INFRA (Infrastructure proxy, INFRASTRUCTURE):
  BIP     Brookfield Infrastructure  USD US
  AQN.TO  Algonquin Power & Utilities CAD CA
  IGF     iShares Global Infra ETF   USD US
  NEE     NextEra Energy             USD US
  AEP     American Electric Power    USD US
```
> 코드 주석에 명시: *"PE/RE/INFRA pools use listed proxies; real private assets are
> illiquid and valued periodically — simplified here for a daily-pricing demo."*

### 6.2 풀 마스터 — `data/reference/pools.csv`

| 컬럼 | 타입 | 설명 |
|---|---|---|
| `pool_id` | str | POOL_EQ, POOL_FI, POOL_PE, POOL_RE, POOL_INFRA |
| `pool_name` | str | "Global Equity Pool" 등 |
| `asset_class` | str | 위와 동일 |
| `base_currency` | str | CAD |
| `mgmt_fee_bps` | int | 운용보수(bps): EQ 35, FI 20, PE 75, RE 55, INFRA 50 |
| `inception_date` | date | 2026-01-02 |

### 6.3 클라이언트 마스터 (가상) — `data/reference/clients.csv`

> 주석 필수: `# fictional entities, inspired by IMCO's public-sector client mix`

| `client_id` | `client_name` | `client_type` |
|---|---|---|
| CLI01 | Ontario Public Sector Pension Fund | PENSION |
| CLI02 | Provincial Judiciary Retirement Plan | PENSION |
| CLI03 | Workers' Insurance & Benefit Fund | INSURANCE |
| CLI04 | Municipal Transit Employees Pension | PENSION |
| CLI05 | Clean Water Infrastructure Reserve | RESERVE |

### 6.4 클라이언트 배분 (Transfer Agency 레지스터) — `data/reference/client_allocations.csv`

각 클라이언트가 각 풀에 보유한 유닛 수. 초기값 생성, 이후 가입/환매로 변동.

| 컬럼 | 타입 | 설명 |
|---|---|---|
| `client_id` | str | |
| `pool_id` | str | |
| `units_held` | float | 초기 보유 유닛 (클라이언트별·풀별로 상이) |
| `as_of_date` | date | |

규칙: 각 클라이언트는 3~5개 풀에 분산 투자. 초기 유닛 수는 50,000~500,000 범위 무작위.

### 6.5 일별 피드 파일 — `data/feeds/{YYYYMMDD}/`

영업일마다 한 폴더. 파일별 스키마:

**`market_prices.csv`**
| 컬럼 | 타입 | 설명 |
|---|---|---|
| `security_id` | str | |
| `price_date` | date | |
| `price` | float | 종가(현지통화) |
| `currency` | str | |
| `price_timestamp` | datetime | 가격 생성 시각 (스테일 판정용) |
| `source` | str | "SYNTH" 또는 "YFINANCE" |

**`fx_rates.csv`**
| `from_ccy` | `to_ccy` | `rate` | `rate_date` |
|---|---|---|---|
| USD | CAD | ~1.35 | date |
| CAD | CAD | 1.0 | date |

**`internal_positions.csv`** (운용사 장부 = book of record)
| `pool_id` | `security_id` | `quantity` | `cost_basis_local` | `position_date` |

**`custodian_positions.csv`** (커스터디언 기록 — 내부와 의도적 불일치 주입)
| `pool_id` | `security_id` | `quantity` | `position_date` |

**`trades.csv`**
| 컬럼 | 타입 | 설명 |
|---|---|---|
| `trade_id` | str | `TRD{date}{seq}` |
| `trade_date` | date | |
| `pool_id` | str | |
| `security_id` | str | |
| `side` | str | BUY / SELL |
| `quantity` | float | |
| `price` | float | 체결가(현지통화) |
| `settlement_date` | date | trade_date + 2 영업일 (T+2) |
| `status` | str | SETTLED / PENDING / FAILED |

**`cash_ledger.csv`**
| `pool_id` | `cash_date` | `opening_cash` | `subscriptions` | `redemptions` | `trade_settlement` | `fees` | `closing_cash` |

규칙: `closing_cash = opening_cash + subscriptions − redemptions + trade_settlement − fees`.
다음 영업일 `opening_cash` = 전일 `closing_cash`.

---

## 7. 주입할 데이터 품질 이슈 (재현성 — 시드 고정)

`data_generator.py`가 의도적으로 결함을 심는다. 비율은 `config`/상수로 조정 가능.

| 이슈 | 위치 | 기본 비율 | 검출 모듈 |
|---|---|---|---|
| 결측 가격 (행 누락) | market_prices | 3% | DQ: completeness |
| 스테일 가격 (timestamp 과거) | market_prices | 5% | DQ: staleness |
| 이상치 (price ≤ 0 또는 일간 ±25%↑) | market_prices | 2% | DQ: outlier |
| 중복 행 (security_id 중복) | market_prices | 1% | DQ: duplicate |
| 수량 불일치 (internal ≠ custodian) | custodian_positions | 4% | Recon: QUANTITY_MISMATCH |
| 커스터디언 누락 (internal에만 존재) | custodian_positions | 2% | Recon: MISSING_IN_CUSTODIAN |
| 커스터디언 초과 (custodian에만 존재) | custodian_positions | 1% | Recon: MISSING_IN_INTERNAL |
| FX 누락 | fx_rates | 가끔 | DQ: fx completeness |
| 미결제 거래 (settlement_date 지났는데 PENDING) | trades | 5% | Recon: 현금 불일치 원인 |
| 실패 거래 | trades | 2% | 리포트에 표시 |

> 핵심: 같은 `RANDOM_SEED` → 항상 같은 결함 집합. 테스트가 이를 검증.

---

## 8. SQLite 데이터베이스 스키마 (`sql/schema.sql`)

차원/팩트 분리(스타 스키마 지향). `ingest.py`가 이 DDL을 실행.

**차원 테이블**
- `dim_security` (security_id PK, isin, ticker, name, asset_class, pool_id, currency, country)
- `dim_pool` (pool_id PK, pool_name, asset_class, base_currency, mgmt_fee_bps, inception_date)
- `dim_client` (client_id PK, client_name, client_type)
- `dim_date` (date_id PK, date, year, month, day, is_business_day)

**팩트 테이블**
- `fact_price` (price_date, security_id, price, currency, price_timestamp, source) — PK(price_date, security_id)
- `fact_fx` (rate_date, from_ccy, to_ccy, rate)
- `fact_position_internal` (position_date, pool_id, security_id, quantity, cost_basis_local)
- `fact_position_custodian` (position_date, pool_id, security_id, quantity)
- `fact_trade` (trade_id PK, trade_date, pool_id, security_id, side, quantity, price, settlement_date, status)
- `fact_cash` (cash_date, pool_id, opening_cash, subscriptions, redemptions, trade_settlement, fees, closing_cash)
- `fact_nav` (nav_date, pool_id, gross_asset_value_cad, liabilities_cad, nav_cad, units_outstanding, unit_price)
- `fact_client_holding` (holding_date, client_id, pool_id, units_held, holding_value_cad)

**운영 테이블**
- `dq_result` (run_date, check_name, severity, records_checked, records_failed, pass_rate, detail)
- `recon_exception` (break_id PK, run_date, pool_id, security_id, break_type, internal_qty, custodian_qty, qty_diff, mv_impact_cad, severity, ai_root_cause, ai_resolution_note, ai_owner_team, ai_priority, status)

모든 팩트 테이블은 적절한 인덱스(날짜·키)를 가진다. 적재는 멱등(idempotent) —
같은 날짜 재적재 시 `INSERT OR REPLACE`.

---

## 9. 모듈 상세 명세 (Module 1–12)

각 모듈: **목적 / 입력 / 출력 / 핵심 로직 / 함수 시그니처 / 완료 기준**.

---

### Module 1 — 데이터 기반 (참조데이터 + 합성 생성기 + 시세)

#### 1a. `reference.py` — 정적 참조데이터
- **목적**: §6.1–6.4의 4개 참조 CSV 생성.
- **출력**: `data/reference/{securities_master,pools,clients,client_allocations}.csv`
- **함수**:
  ```python
  def build_securities_master() -> pd.DataFrame
  def build_pools() -> pd.DataFrame
  def build_clients() -> pd.DataFrame
  def build_client_allocations(seed: int) -> pd.DataFrame
  def write_reference_data() -> None   # 위 4개 호출 후 CSV 저장
  ```
- **완료 기준**: 4개 CSV 존재, securities_master 34행, 모든 security의 pool_id가
  pools에 존재(참조무결성).

#### 1b. `data_generator.py` — 일별 합성 피드
- **목적**: 영업일별로 §6.5의 6개 피드 파일 생성 + §7 결함 주입.
- **입력**: 참조데이터, 날짜, 전일 상태(가격·현금 연속성), seed.
- **핵심 로직**:
  - 가격: `market_data.py`에서 받음.
  - 포지션: 전일 포지션 + 당일 거래 반영. 첫날은 초기 포지션 생성.
  - 커스터디언 포지션: 내부 포지션 복제 후 §7 비율로 결함 주입.
  - 거래: 풀별 0~5건 무작위 생성, T+2 결제, status 분포 주입.
  - 현금: §6.5 항등식 유지.
- **함수**:
  ```python
  def generate_day(date, prev_state, seed) -> DayState
  def generate_history(start, n_days, seed) -> None   # SIM_DAYS만큼 반복
  def inject_price_issues(df, seed) -> pd.DataFrame
  def inject_custodian_breaks(internal_df, seed) -> pd.DataFrame
  ```
- **완료 기준**: `SIM_DAYS`개 폴더 생성, 현금 항등식 성립, 같은 seed로 2회 실행 시
  파일 바이트 동일.

#### 1c. `market_data.py` — 시세 소스 추상화
- **목적**: `synthetic` / `live` 두 모드를 동일 인터페이스로 제공.
- **함수**:
  ```python
  def get_prices(security_ids, tickers, date, mode) -> pd.DataFrame
  def _synthetic_prices(...) -> pd.DataFrame   # 기하 랜덤워크, seed 고정
  def _live_prices(tickers, date) -> pd.DataFrame   # yfinance, 실패 시 synthetic fallback
  ```
- **로직**: `synthetic` = 종목별 시작가 부여 후 일별 `price *= exp(N(μ,σ))`.
  `live` = `yfinance.download`; 네트워크 실패/결측 시 경고 로그 + synthetic으로 대체.
- **완료 기준**: 두 모드 모두 동일 스키마 DataFrame 반환. `synthetic` 모드는
  네트워크 없이 동작.

---

### Module 2 — `ingest.py` (데이터 적재)
- **목적**: CSV → SQLite. "여러 소스에서 들어오는 데이터피드 수집".
- **입력**: `data/reference/`, `data/feeds/`, `sql/schema.sql`.
- **로직**: schema.sql 실행 → 참조데이터 적재 → 날짜별 피드 적재(`INSERT OR REPLACE`)
  → `dim_date` 채움.
- **함수**:
  ```python
  def init_db() -> None                 # schema.sql 실행
  def load_reference() -> None
  def load_feed_day(date) -> int        # 적재 행수 반환
  def load_all() -> None
  ```
- **완료 기준**: DB 파일 생성, 모든 테이블 존재, 행수 > 0, 재실행해도 중복 없음.

---

### Module 3 — `data_quality.py` (데이터 품질 엔진) ★공고 핵심
- **목적**: "데이터 품질 관리 / 데이터피드 모니터링".
- **입력**: 특정 날짜의 적재된 데이터(DB).
- **수행 검사 (각각 결과를 `dq_result`에 기록)**:
  1. `schema_validation` — 필수 컬럼·타입·non-null.
  2. `price_completeness` — 모든 보유 증권에 가격 행이 있는가.
  3. `price_staleness` — `price_timestamp`가 기준(예: 당일) 이전인가.
  4. `price_outlier` — price ≤ 0 또는 전일 대비 ±25% 초과.
  5. `price_duplicate` — (security_id, price_date) 중복.
  6. `referential_integrity` — 포지션의 security_id·pool_id가 마스터에 존재.
  7. `fx_completeness` — 모든 비CAD 통화에 FX 행 존재.
- **출력**: `dq_result` 테이블 + **DQ 스코어카드**(검사별 pass_rate, 종합 점수 0–100).
- **함수**:
  ```python
  def run_all_checks(date) -> pd.DataFrame      # 검사 결과 테이블
  def dq_scorecard(date) -> dict                # {overall_score, by_check, failed_records}
  def check_price_staleness(date) -> CheckResult
  # ... 검사별 함수
  ```
- **완료 기준**: 7개 검사 모두 실행, 주입된 결함 비율(±오차)을 검출,
  스코어카드 점수가 0–100 범위.

---

### Module 4 — `reconcile.py` (대사 엔진) ★공고 핵심
- **목적**: "pool oversight" — 내부 장부 vs 커스터디언 대조.
- **입력**: 특정 날짜의 `fact_position_internal`, `fact_position_custodian`,
  `fact_price`, `fact_fx`, `fact_cash`.
- **로직**:
  - **포지션 대사**: (pool_id, security_id)로 FULL OUTER JOIN.
    - 양쪽 존재 & 수량 차이 → `QUANTITY_MISMATCH`
    - 내부만 → `MISSING_IN_CUSTODIAN`
    - 커스터디언만 → `MISSING_IN_INTERNAL`
  - **MV 영향**: `mv_impact_cad = |qty_diff| × price × fx_to_cad`.
  - **심각도**: HIGH ≥ 1,000,000 CAD / MEDIUM ≥ 100,000 / LOW 그 외.
  - **현금 대사**: 풀별 closing_cash 정합성 점검(거래 결제·수수료 반영).
  - 각 break에 `break_id` 부여, `recon_exception`에 `status='OPEN'`으로 저장.
- **함수**:
  ```python
  def reconcile_positions(date) -> pd.DataFrame   # break 목록
  def reconcile_cash(date) -> pd.DataFrame
  def classify_severity(mv_impact) -> str
  def write_exceptions(date) -> int               # 저장된 break 수
  ```
- **완료 기준**: 주입한 break를 모두 검출·분류, MV·심각도 정확, `recon_exception` 적재.

---

### Module 5 — `nav.py` (NAV·유닛·클라이언트 배분) ★공고 핵심
- **목적**: "financial analysis", "pool and transfer agency oversight".
- **로직 (풀별, 날짜별)**:
  ```
  gross_asset_value_cad = Σ(quantity × price × fx_to_cad) + closing_cash
  liabilities_cad       = 운용보수 발생액
                        = 전일 NAV × (mgmt_fee_bps/10000) × (1/365)  [일할]
  nav_cad               = gross_asset_value_cad − liabilities_cad
  units_outstanding     = Σ(client_allocations.units_held for pool)
  unit_price            = nav_cad / units_outstanding
  ```
  - **클라이언트 보유가치**: `holding_value_cad = units_held × unit_price`.
  - **일일 손익**: `nav_cad(t) − nav_cad(t-1) − 순가입(subscriptions−redemptions)`.
  - 결과를 `fact_nav`, `fact_client_holding`에 저장.
- **엣지케이스**: 가격 결측 시 → 전일 가격 carry-forward + DQ 플래그.
- **함수**:
  ```python
  def compute_nav(date) -> pd.DataFrame              # 풀별 NAV 행
  def compute_client_holdings(date) -> pd.DataFrame
  def daily_pnl(date) -> pd.DataFrame
  ```
- **완료 기준**: 모든 풀 NAV 양수, Σ(클라이언트 보유가치) ≈ NAV(오차 < 0.01%),
  unit_price 연속(점프 없음, 거래 영향 제외).

---

### Module 6 — `ai_assistant.py` (AI 예외 어시스턴트) ★공고 간판
- **목적**: "Develop AI-powered tools and automation solutions". 대사 break를
  LLM이 분석.
- **입력**: `recon_exception`의 OPEN break + 컨텍스트(해당 증권 최근 거래, 가격,
  기업행동 가능성).
- **LLM 처리 (Claude Messages API)**:
  - 각 break에 대해 다음을 산출 — **구조화 출력(tool use 또는 JSON 강제)**:
    - `root_cause`: UNSETTLED_TRADE / CORPORATE_ACTION / PRICING_ERROR /
      TIMING_DIFFERENCE / DATA_ENTRY_ERROR / FX_MISMATCH / UNKNOWN
    - `resolution_note`: 2~3문장 영문 해소 메모 초안
    - `owner_team`: Trade Settlement / Pricing / Fund Accounting / Custody / Data Mgmt
    - `priority`: P1 / P2 / P3 (심각도 + 원인 긴급성 종합)
  - **프롬프트 캐싱**: 시스템 프롬프트(분류 기준·팀 정의)는 `cache_control`로 캐싱.
  - **모델**: `config.ANTHROPIC_MODEL` (기본 Haiku 4.5 — 분류엔 빠르고 저렴).
  - **배치**: break를 묶어 호출하되 토큰 한도 고려.
- **Fallback (키 없을 때 — 필수 구현)**: rule-based 분류기.
  - 예: 해당 증권에 PENDING 거래 존재 → `UNSETTLED_TRADE`;
    가격 이상치 플래그 → `PRICING_ERROR`; 비CAD인데 FX 결측 → `FX_MISMATCH`;
    그 외 수량차 → `TIMING_DIFFERENCE`; 미분류 → `UNKNOWN`.
- **출력**: `recon_exception`의 `ai_*` 컬럼 갱신.
- **함수**:
  ```python
  def analyze_exceptions(date) -> pd.DataFrame
  def _analyze_with_llm(breaks, context) -> list[dict]      # has_live_ai()=True
  def _analyze_rule_based(breaks, context) -> list[dict]    # fallback
  def build_context(break_row) -> dict
  ```
- **완료 기준**: 키 유무 모두에서 모든 OPEN break에 `ai_*` 채워짐, 결과 스키마
  동일, LLM 실패 시 graceful fallback + 로그.
- **claude-api 참고**: anthropic SDK, `messages.create`, system 프롬프트
  prompt caching, 구조화 출력은 tool use 강제. 재시도(지수 백오프) 포함.

---

### Module 7 — `reporting.py` (리포트 자동화) ★공고 핵심
- **목적**: "daily/weekly/monthly reporting and automation of recurring tasks".
- **출력물**:
  1. **일일 운영팩 (Excel)** — `reports/daily/PoolDesk_Ops_{date}.xlsx`, 탭:
     - `Summary` — 날짜, DQ 점수, break 건수(심각도별), 총 NAV
     - `DQ Scorecard` — 검사별 결과
     - `Reconciliation Exceptions` — break 전체 + AI 분석 (HIGH=빨강 조건부서식)
     - `NAV by Pool` — 풀별 NAV·유닛가격·일손익
     - `Client Holdings` — 클라이언트별 보유가치
     - `Trade Blotter` — 당일 거래 (FAILED=빨강, PENDING=노랑)
  2. **일일 PDF 1-pager** — `reports/daily/PoolDesk_Summary_{date}.pdf`:
     핵심 KPI + NAV 추이 차트(matplotlib) + 상위 5 break.
  3. **주간 롤업** — `reports/weekly/`: DQ 점수 추이, break 추이, NAV 추이.
  4. **월간 롤업** — `reports/monthly/`: 월말 결산형 요약.
- **함수**:
  ```python
  def build_daily_excel(date) -> Path
  def build_daily_pdf(date) -> Path
  def build_weekly_rollup(week_end) -> Path
  def build_monthly_rollup(month) -> Path
  ```
- **완료 기준**: Excel이 openpyxl로 열림, 6개 탭·서식 적용, PDF 생성, 롤업이
  여러 날짜 집계.

---

### Module 8 — `main.py` (오케스트레이션) — §10 참조

---

### Module 9 — `sql/checks.sql` (SQL 쿼리 모음) ★공고: SQL 증명
- **목적**: 대사·DQ 로직을 **순수 SQL로도** 표현 — SQL 역량 증명용.
- **포함 쿼리 (각각 주석으로 설명)**:
  1. 두 포지션 테이블 대사: `FULL OUTER JOIN`(SQLite는 `LEFT JOIN` UNION으로),
     수량차 + 한쪽 누락 검출.
  2. 가격 결측: 보유 증권 중 `fact_price`에 없는 것 — `LEFT JOIN ... IS NULL`.
  3. 가격 중복: `GROUP BY price_date, security_id HAVING COUNT(*) > 1`.
  4. 풀별 NAV 검산: `SUM(quantity*price*fx)` 집계.
  5. 미결제 거래 aging: `settlement_date < run_date AND status='PENDING'`.
  6. 클라이언트별 보유가치 순위: `ROW_NUMBER() OVER (PARTITION BY pool_id ORDER BY ...)`.
  7. break 심각도 분류: `CASE WHEN mv_impact_cad >= 1e6 THEN 'HIGH' ...`.
- **완료 기준**: 7개 쿼리 모두 DB에서 오류 없이 실행, Python 모듈 결과와 일치.

---

### Module 10 — `excel/PoolDesk_Macro.xlsm` (VBA) ★공고: VBA 증명
- **목적**: "VBA scripts" 증명. Excel 매크로 워크북.
- **기능**: 버튼 클릭 시 ——
  1. 일일 예외 CSV(`recon_exception` export)를 워크시트로 임포트.
  2. HIGH 심각도 행 → 빨강, MEDIUM → 노랑 자동 서식.
  3. break_type별 건수 요약 표 생성.
  4. 처리 결과 메시지박스 표시.
- **VBA 코드 (그대로 모듈에 삽입)**:
  ```vba
  Sub ImportAndFormatExceptions()
      Dim ws As Worksheet, csvPath As String, lastRow As Long, i As Long
      Set ws = ThisWorkbook.Sheets("Exceptions")
      ws.Cells.Clear
      csvPath = ThisWorkbook.Path & "\exceptions.csv"
      If Dir(csvPath) = "" Then
          MsgBox "exceptions.csv not found next to this workbook.", vbExclamation
          Exit Sub
      End If
      With ws.QueryTables.Add(Connection:="TEXT;" & csvPath, Destination:=ws.Range("A1"))
          .TextFileParseType = xlDelimited
          .TextFileCommaDelimiter = True
          .Refresh BackgroundQuery:=False
      End With
      lastRow = ws.Cells(ws.Rows.Count, "A").End(xlUp).Row
      ' severity 컬럼 인덱스를 헤더에서 탐색했다고 가정 (예: 11열)
      For i = 2 To lastRow
          Select Case UCase(Trim(ws.Cells(i, 11).Value))
              Case "HIGH":   ws.Rows(i).Interior.Color = RGB(255, 199, 206)
              Case "MEDIUM": ws.Rows(i).Interior.Color = RGB(255, 235, 156)
          End Select
      Next i
      MsgBox "Imported " & (lastRow - 1) & " exceptions and applied formatting.", vbInformation
  End Sub
  ```
- **빌드 메모**: 실행자는 `.xlsm`을 직접 생성할 수 없으면 `excel/VBA_Macro.bas`로
  코드를 저장하고, `excel/README.md`에 "Excel에서 Alt+F11 → 모듈 삽입 → 붙여넣기 →
  버튼 연결" 단계를 적는다. severity 컬럼 위치는 실제 CSV 헤더에 맞춰 조정.
- **완료 기준**: 매크로 코드 파일 + 적용 안내 문서 존재.

---

### Module 11 — `powerbi/PoolDesk.pbix` (Power BI 대시보드)
- **목적**: "Power BI" 증명. 운영 컨트롤 대시보드.
- **데이터 소스**: `pooldesk.db`(SQLite ODBC) 또는 `reports/`의 CSV export.
- **페이지/시각화**:
  - **Ops Control**: DQ 종합점수(카드), break 건수 심각도별(도넛),
    break 추이(꺾은선), NAV 총액 추이(꺾은선).
  - **Reconciliation**: break_type별 건수(막대), MV 영향 상위 10(표),
    예외 aging(미해소 일수).
  - **NAV & Clients**: 풀별 NAV(막대), 클라이언트별 보유가치(트리맵),
    유닛가격 추이.
- **DAX 측정값 예시**: `Total NAV = SUM(fact_nav[nav_cad])`,
  `High Severity Breaks = CALCULATE(COUNTROWS(recon_exception), recon_exception[severity]="HIGH")`,
  `DQ Score = AVERAGE(dq_result[pass_rate]) * 100`.
- **빌드 메모**: `.pbix`는 코드 생성 불가 → `powerbi/README.md`에 위 단계를
  스크린샷 가이드로 작성. CSV export 헬퍼(`reporting.py`에 `export_for_powerbi()`)
  추가.
- **완료 기준**: 빌드 가이드 문서 + CSV export 함수 존재. (가능하면 실제 .pbix)

---

### Module 12 — `automate/flow_spec.md` (Power Automate 플로우)
- **목적**: "Power Automate" 증명. 반복 작업 자동 트리거·배포.
- **플로우 설계 (클라우드 플로우)**:
  1. **트리거**: `Recurrence` — 매 영업일 오전 7시.
  2. **액션**: 일일 운영팩 생성(스크립트 호출 또는 OneDrive의 산출 파일 픽업).
  3. **조건**: HIGH break 존재 시 → 운영팀에 별도 경고 메일.
  4. **액션**: 일일 PDF 요약을 팀에 이메일(`Send an email (V2)`) + Teams 채널 게시.
  5. **로깅**: SharePoint 리스트에 실행 기록 추가(상태·break 수·DQ 점수).
- **빌드 메모**: 실제 플로우는 O365 환경 필요 → `flow_spec.md`에 각 단계
  스크린샷용 정의서로 작성. 면접에서 "이렇게 설계했다"고 설명 가능하면 충분.
- **완료 기준**: `flow_spec.md`에 트리거·액션·조건이 단계별로 명세됨.

---

## 10. 오케스트레이션 — `main.py` (CLI)

```
python main.py generate            # 참조데이터 + SIM_DAYS일치 합성 피드 생성
python main.py init-db             # DB 스키마 생성
python main.py run --date YYYY-MM-DD   # 하루 파이프라인 실행
python main.py run-all             # 전체 기간 일괄 실행
python main.py report --date ...   # 특정일 리포트만 재생성
python main.py rollup --week ...   # 주간/월간 롤업
```

**`run` 1일 파이프라인 순서**: ingest → data_quality → reconcile → nav →
ai_assistant → reporting. 각 단계 시작/종료/소요시간/결과요약을 콘솔 + 로그파일
(`reports/pipeline.log`)에 출력 — "모니터링·에러로깅" 어필 포인트.

**완료 기준**: `python main.py generate && python main.py init-db &&
python main.py run-all` 가 키 없이(synthetic + AI fallback) 오류 없이 완주하고
`reports/`에 산출물 생성.

---

## 11. 빌드 단계 (Phase 0 → 14) — 이 순서로 진행

| Phase | 내용 | 산출물 | 완료 기준(DoD) |
|---|---|---|---|
| **0** | 스캐폴딩 | `config.py`, `pooldesk/__init__.py`, `db.py`, 폴더트리 | `python -c "import config"` 성공, `.env` 로딩 |
| **1** | 참조데이터 + 합성 생성기 + 시세 | `reference.py`, `data_generator.py`, `market_data.py` | §6 모든 CSV 생성, 재현성 검증 |
| **2** | 적재 | `sql/schema.sql`, `ingest.py` | DB에 모든 테이블·데이터, 멱등 |
| **3** | 데이터 품질 엔진 | `data_quality.py` | 7개 검사 동작, 결함 검출, 스코어카드 |
| **4** | 대사 엔진 | `reconcile.py` | break 검출·분류·MV·심각도 정확 |
| **5** | NAV·배분 | `nav.py` | NAV 양수, 보유가치 합 = NAV |
| **6** | AI 예외 어시스턴트 | `ai_assistant.py` | LLM + fallback 모두 동작 |
| **7** | 리포팅 | `reporting.py` | Excel 6탭·PDF·롤업 생성 |
| **8** | 오케스트레이션 | `main.py` | `run-all` 키 없이 완주 |
| **9** | SQL 쿼리 모음 | `sql/checks.sql` | 7개 쿼리 실행, Python 결과와 일치 |
| **10** | VBA 매크로 | `excel/VBA_Macro.bas` + `excel/README.md` | 코드 + 적용 안내 |
| **11** | Power BI | `powerbi/README.md` + `export_for_powerbi()` | 빌드 가이드 + export |
| **12** | Power Automate | `automate/flow_spec.md` | 단계별 플로우 정의서 |
| **13** | 문서화 | `docs/*` + `README.md` | §13 전부 |
| **14** | 테스트·정리 | `tests/*` | `pytest` 전부 통과 |

각 Phase는 독립 커밋. Phase 1–9는 자동 검증 가능, 10–12는 문서 산출물.

---

## 12. 테스트 요구사항 (`tests/`, pytest)

- `test_data_quality.py`: 알려진 결함이 심긴 합성 데이터에서 각 검사가
  예상 건수(±오차)를 검출하는지.
- `test_reconcile.py`: 수동 구성한 internal/custodian 쌍에서 break 유형·MV·
  심각도가 정확한지. `classify_severity` 경계값 테스트.
- `test_nav.py`: 손으로 계산한 소형 케이스로 NAV·unit_price 검증.
  Σ(client holding) = NAV 항등.
- **완료 기준**: `pytest -q` 전부 통과. CI 불필요(로컬).

---

## 13. 문서 산출물 (`docs/` + README)

| 파일 | 내용 |
|---|---|
| `docs/process_flow.md` | 일일 운영 워크플로 mermaid 흐름도 (수집→DQ→대사→NAV→AI→리포트) |
| `docs/runbook.md` | 운영 절차서: 매일 실행 단계, 실패 시 대응, 재시도, 연락 체계 |
| `docs/control_matrix.md` | 통제 매트릭스: 리스크 → 통제 → 빈도 → 증빙 (예: 가격결측→DQ검사→일일→dq_result) |
| `docs/ai_ops_framework.md` | "AI-driven operational implementation framework" 1–2p: 자동화 후보 선정 기준, 휴먼인더루프 원칙, LLM 사용 가드레일, 표준 워크플로 |
| `README.md` | 영문. 개요, 아키텍처 다이어그램, 설치(`pip install -r requirements.txt`), `.env` 설정, 실행법, 스크린샷 3–4장, "학습용 시뮬레이션" 명시, 단순화 한계 |

`README.md`는 채용담당자가 30초 안에 "무엇을·왜·어떻게"를 파악하게 쓴다.

---

## 14. 전역 규칙 & 완료 정의 (Definition of Done)

프로젝트 전체가 "완료"되려면:

- [ ] `pip install -r requirements.txt` 후 `python main.py generate && python
      main.py init-db && python main.py run-all`이 **API 키 없이** 오류 없이 완주.
- [ ] `MARKET_DATA_MODE=synthetic`에서 **네트워크 없이** 동작.
- [ ] `ANTHROPIC_API_KEY` 유효 시 Module 6이 LLM 모드, 없으면 fallback — 둘 다 동작.
- [ ] 같은 `RANDOM_SEED` → 동일한 합성 데이터(재현성).
- [ ] `pytest` 전부 통과.
- [ ] `reports/`에 Excel·PDF·롤업 생성.
- [ ] `docs/` 5종 + `README.md` 완성.
- [ ] `.env`는 git에 커밋되지 않음(.gitignore 확인).
- [ ] 모든 단순화·가정이 코드 주석 또는 docs에 명시됨.
- [ ] 비밀키·실제 기관명 오용 없음. 클라이언트는 가상임이 명시됨.

---

## 15. 면접 연결 — 빌드하며 챙길 "말할 거리"

빌드를 맡은 모델은 각 모듈 완료 시 한 줄 메모를 남겨, 지원자가 면접에서 쓸 수 있게 한다:

- **Module 3**: "스테일 가격을 timestamp로 잡았다 — 운영에서 가장 흔한 조용한 오류."
- **Module 4**: "break를 MV 영향으로 심각도화 — 건수가 아니라 금액으로 우선순위."
- **Module 5**: "가격 결측 시 전일가 carry-forward + 플래그 — 멈추지 않되 표시."
- **Module 6**: "LLM은 분류·초안만, 해소 결정은 사람 — human-in-the-loop."
- **Module 9**: "같은 대사 로직을 Python과 SQL 양쪽으로 — 도구가 아니라 논리가 핵심."
- **전체**: "프로덕션이 아니라 도메인을 배우려고 만든 시뮬레이션. 만들면서
  reconciliation break의 원인 유형 체계를 이해했다."

---

## 16. 부록 — 빠른 시작 (실행자용 첫 명령)

```bash
cd pooldesk
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env          # 필요시 ANTHROPIC_API_KEY 입력 (없어도 동작)
# 이제 Phase 0부터 빌드 시작 — config.py 작성 → §11 순서대로
```

빌드 완료 후 데모:
```bash
python main.py generate
python main.py init-db
python main.py run-all
# reports/ 폴더에서 산출물 확인
```

---

*문서 끝. 이 명세서는 IMCO 면접 포트폴리오용 학습 프로젝트를 위한 것이며,
PoolDesk는 실제 IMCO 시스템·데이터와 무관한 독립 시뮬레이션이다.*
