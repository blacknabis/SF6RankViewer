# SF6Viewer v2 Foundation 구현 설계

- 상태: 승인됨
- 작성일: 2026-07-19
- 상위 설계: `2026-07-19-sf6viewer-v2-master-design.md`
- 구현 단계: 1단계 신뢰 기반
- 품질 기준: fail-closed, migration golden, Windows package smoke

## 1. 목적

Foundation 단계는 완성된 사용자 화면을 만드는 단계가 아니다. 이후 기능 구현이 데이터 손실, 중복 수집, 조용한 scraper 실패, 로컬 API 노출, 패키징 차이를 만들면 자동으로 차단하는 실행 기반을 만든다.

이 단계가 끝나면 다음이 실제 코드와 자동화 검증으로 동작해야 한다.

- Windows 사용자별 단일 앱 인스턴스와 고정 루프백 포트
- 안전한 시작·종료와 복구 가능한 job 수명주기
- raw → normalized/duplicate/quarantine 저장 파이프라인
- 841건 golden을 포함한 v1 무손실 이관
- 하나의 Playwright 작업만 허용하는 collection coordinator
- typed error와 `application/problem+json`
- versioned REST/OpenAPI/SSE 계약
- 최소 상태 UI와 API 보안 session
- Windows x64 onedir package smoke

기존 `main.py`, `database.py`, `scraper.py`, `static/`은 참고 자료로만 사용한다. Foundation 통과 전에는 기존 실행 경로와 `sf6viewer.db`를 삭제하거나 바꾸지 않는다.

## 2. 고정 기술 결정

| 영역 | 결정 |
|---|---|
| OS | Windows 10 22H2 이상, Windows 11, x64 |
| Python | CPython 3.12의 정확한 patch를 `.python-version`과 CI manifest에 고정 |
| Python 의존성 | PEP 621 `pyproject.toml`, `uv.lock`, `uv sync --frozen` |
| Frontend | Node 24 LTS의 정확한 patch를 `.node-version`에 고정, React + TypeScript + Vite |
| Frontend 의존성 | `package-lock.json`, `npm ci` |
| API | FastAPI + Pydantic 2 + Uvicorn |
| DB | SQLite + SQLAlchemy 2 + Alembic |
| Browser 수집 | Playwright Python sync API, 전용 worker thread |
| 데스크톱 | pywebview EdgeChromium/WebView2 |
| Python 검증 | pytest, pytest-cov, Ruff, mypy strict |
| Frontend 검증 | Vitest, React Testing Library, ESLint |
| E2E | Playwright Python과 fixture backend |
| Windows bundle | PyInstaller `onedir`; `onefile`은 사용하지 않음 |
| Installer | Inno Setup은 릴리스 단계에서 추가; Foundation은 unsigned onedir smoke까지 |

lockfile에 들어가는 패키지는 exact version과 hash로 고정한다. 최초 lock 생성 시 선택한 Python·Node patch도 build manifest에 기록한다. lockfile 갱신은 별도 dependency PR로만 수행하고 전체 CI를 다시 통과해야 한다.

시스템 Chrome/Edge를 scraper browser로 사용하지 않는다. lock된 Playwright 버전에 대응하는 Chromium revision을 package에 포함한다. WebView2는 OS의 Evergreen Runtime을 사용하되 bootstrap 전에 존재와 최소 호환성을 검사한다.

## 3. 저장소 구조

```text
sf6viewer/
├─ pyproject.toml
├─ uv.lock
├─ .python-version
├─ .node-version
├─ src/sf6viewer/
│  ├─ __init__.py
│  ├─ __main__.py
│  ├─ bootstrap.py
│  ├─ domain/
│  │  ├─ account.py
│  │  ├─ match.py
│  │  ├─ ingestion.py
│  │  ├─ job.py
│  │  ├─ errors.py
│  │  ├─ events.py
│  │  └─ value_objects.py
│  ├─ application/
│  │  ├─ ports/{auth_store,buckler,clock,event_publisher,repositories,unit_of_work}.py
│  │  ├─ services/{collection,login,migration,normalization,quarantine,query,settings}.py
│  │  └─ dto/
│  ├─ infrastructure/
│  │  ├─ db/{engine,models,repositories,unit_of_work,migrations}/
│  │  ├─ buckler/{adapter,profile_parser,match_parser,selectors,raw_capture}.py
│  │  ├─ storage/{app_paths,dpapi_auth_store,legacy_locator,backup_store,asset_store}.py
│  │  └─ runtime/{single_instance,port_guard,coordinator,scheduler,event_hub,lifecycle}.py
│  └─ presentation/
│     ├─ api/{app,dependencies,problem_details,schemas,routers}/
│     └─ webview/{host,native_bridge,launch_session}.py
├─ frontend/
│  ├─ package.json
│  ├─ package-lock.json
│  ├─ vite.config.ts
│  └─ src/{api,app,components,state,styles,test}/
├─ tests/
│  ├─ unit/{domain,parsers,runtime}/
│  ├─ integration/{api,db,migration,buckler}/
│  ├─ e2e/
│  └─ fixtures/{buckler,v1}/
├─ packaging/{SF6Viewer.spec,build.ps1,smoke.ps1}/
└─ scripts/{check.ps1,make_fixture.ps1}
```

`src/sf6viewer/web/`은 Vite build output을 packaging 때 복사하는 생성물이며 source control에 넣지 않는다.

## 4. Composition root와 의존 규칙

`bootstrap.py`만 concrete adapter를 조립한다.

```text
presentation → application → domain
infrastructure ────────────┘
```

규칙:

- domain은 표준 라이브러리 외 프레임워크를 import하지 않는다.
- application service는 SQLAlchemy model이나 Playwright object를 받지 않는다.
- infrastructure adapter는 application port를 구현한다.
- API router는 application DTO만 사용한다.
- SQLAlchemy Session과 Playwright page/context/browser는 함수 경계를 넘어 전역에 저장하지 않는다.
- 현재 시각, ULID 생성, sleep/backoff는 port로 주입해 테스트에서 고정한다.

CI의 import rule test가 위반을 검사한다.

## 5. AppData와 파일 원자성

production root는 `%LOCALAPPDATA%\SF6Viewer`다. unit/integration test는 app factory에 `AppPaths`를 주입하고, package smoke는 disposable Windows 사용자 profile에서 실행해 실제 `%LOCALAPPDATA%` 계약을 검증한다.

```text
data\sf6viewer-v2.db
auth\buckler.dpapi
backgrounds\<sha256>.<ext>
legacy\backups\<source-sha256>.db
legacy\reports\<source-sha256>.json
logs\sf6viewer-YYYYMMDD.jsonl
crash\
runtime\instance.json
```

파일 변경은 같은 volume의 임시 파일에 쓴 뒤 flush, `os.fsync`, close, atomic replace 순서로 수행한다. DB 교체 전에는 모든 connection을 닫고 WAL checkpoint를 완료한다. 인증 파일 ACL은 현재 사용자 SID와 SYSTEM만 허용하고 내용은 Windows DPAPI current-user scope로 암호화한다.

로그는 날짜별 JSONL, 파일당 최대 10 MiB, 14일 보존이다. 다음 key는 이름 또는 중첩 위치와 관계없이 redaction한다: cookie, token, authorization, storage_state, password, csrf, nonce. 원시 HTML/JSON은 일반 로그에 넣지 않는다.

## 6. DB schema revision 1

Alembic revision `0001_foundation`이 아래 schema를 만든다. 모든 enum은 DB에는 대문자 TEXT로 저장하고 application에서 허용 집합을 검증한다. 모든 시간은 ISO-8601 UTC 문자열이 아니라 SQLite INTEGER Unix milliseconds로 저장하며 DTO에서 UTC aware datetime으로 변환한다. 원본 시각 문자열은 별도 TEXT로 보존한다.

### 6.1 `schema_meta`

| column | type | 규칙 |
|---|---|---|
| `id` | INTEGER | PK, 항상 1 |
| `schema_version` | INTEGER | NOT NULL, 1 |
| `created_at_ms` | INTEGER | NOT NULL |
| `updated_at_ms` | INTEGER | NOT NULL |

### 6.2 `accounts`

| column | type | 규칙 |
|---|---|---|
| `id` | INTEGER | PK, CHECK `id=1` |
| `user_code` | TEXT | NOT NULL, UNIQUE, 10자리 숫자 canonical |
| `display_name` | TEXT | nullable |
| `main_character` | TEXT | nullable |
| `rank_name` | TEXT | nullable |
| `current_mr` | INTEGER | nullable, CHECK >= 0 |
| `current_lp` | INTEGER | nullable, CHECK >= 0 |
| `auth_state` | TEXT | NOT NULL: `MISSING`, `VALID`, `EXPIRED`, `MISMATCH` |
| `created_at_ms` | INTEGER | NOT NULL |
| `updated_at_ms` | INTEGER | NOT NULL |

알 수 없는 display/rank/rating은 빈 문자열이나 0이 아니라 NULL이다.

### 6.3 `jobs`

| column | type | 규칙 |
|---|---|---|
| `id` | TEXT | ULID PK |
| `type` | TEXT | `LOGIN`, `COLLECT`, `MIGRATE`, `REPROCESS` |
| `reason` | TEXT | `STARTUP`, `MANUAL`, `SCHEDULED`, `RECOVERY` |
| `state` | TEXT | `QUEUED`, `RUNNING`, terminal state |
| `phase` | TEXT | nullable stable phase code |
| `requested_at_ms` | INTEGER | NOT NULL |
| `started_at_ms` | INTEGER | nullable |
| `finished_at_ms` | INTEGER | nullable |
| `progress_current` | INTEGER | nullable |
| `progress_total` | INTEGER | nullable |
| `error_code` | TEXT | nullable typed code |
| `diagnostic_id` | TEXT | nullable ULID |
| `summary_json` | TEXT | validated JSON, no secrets |

terminal state는 `SUCCEEDED`, `SUCCEEDED_WITH_WARNINGS`, `FAILED`, `CANCELLED`, `INTERRUPTED`다.

### 6.4 `ingestion_runs`

| column | type | 규칙 |
|---|---|---|
| `id` | TEXT | ULID PK |
| `job_id` | TEXT | NOT NULL FK jobs, UNIQUE |
| `account_id` | INTEGER | nullable FK accounts |
| `kind` | TEXT | `LIVE`, `LEGACY_IMPORT`, `REPROCESS` |
| `parser_version` | TEXT | NOT NULL git/build version |
| `state` | TEXT | `FETCHING`, `RAW_COMMITTED`, `NORMALIZING`, terminal |
| `started_at_ms` | INTEGER | NOT NULL |
| `finished_at_ms` | INTEGER | nullable |
| `raw_count` | INTEGER | NOT NULL default 0 |
| `normalized_count` | INTEGER | NOT NULL default 0 |
| `duplicate_count` | INTEGER | NOT NULL default 0 |
| `quarantine_count` | INTEGER | NOT NULL default 0 |
| `error_code` | TEXT | nullable |
| `diagnostic_id` | TEXT | nullable |

terminal ingestion state는 `COMPLETED`, `COMPLETED_WITH_WARNINGS`, `FAILED`, `INTERRUPTED`다.

### 6.5 `raw_records`

| column | type | 규칙 |
|---|---|---|
| `id` | TEXT | ULID PK |
| `ingestion_id` | TEXT | NOT NULL FK ingestion_runs |
| `ordinal` | INTEGER | NOT NULL, >= 0 |
| `record_type` | TEXT | `PROFILE`, `MATCH`, `LEGACY_PLAYER`, `LEGACY_MATCH` |
| `source_key` | TEXT | nullable |
| `payload_json` | BLOB | NOT NULL, UTF-8 canonical JSON zlib 압축 |
| `payload_sha256` | TEXT | NOT NULL lowercase hex |
| `fetched_at_ms` | INTEGER | NOT NULL |
| `disposition` | TEXT | `PENDING`, `NORMALIZED`, `DUPLICATE`, `QUARANTINED` |
| `disposed_at_ms` | INTEGER | nullable |

`UNIQUE(ingestion_id, ordinal)`와 `CHECK((disposition='PENDING' AND disposed_at_ms IS NULL) OR (disposition!='PENDING' AND disposed_at_ms IS NOT NULL))`를 둔다. raw payload는 update하지 않고 disposition만 한 번 바꿀 수 있다. repository와 DB trigger가 두 번째 disposition 변경을 거부한다.

### 6.6 `profile_snapshots`

| column | type | 규칙 |
|---|---|---|
| `id` | TEXT | ULID PK |
| `account_id` | INTEGER | NOT NULL FK accounts, CHECK 1 |
| `ingestion_id` | TEXT | NOT NULL FK ingestion_runs |
| `raw_record_id` | TEXT | NOT NULL FK raw_records, UNIQUE |
| `display_name` | TEXT | nullable |
| `character` | TEXT | nullable |
| `rank_name` | TEXT | nullable |
| `mr` | INTEGER | nullable, >= 0 |
| `lp` | INTEGER | nullable, >= 0 |
| `observed_at_ms` | INTEGER | NOT NULL |

### 6.7 `matches`

| column | type | 규칙 |
|---|---|---|
| `id` | TEXT | ULID PK |
| `account_id` | INTEGER | NOT NULL FK accounts, CHECK 1 |
| `identity_key` | TEXT | NOT NULL |
| `identity_kind` | TEXT | `SOURCE_ID`, `HYDRATION_KEY`, `FALLBACK_V1` |
| `occurred_at_ms` | INTEGER | NOT NULL |
| `occurred_at_source` | TEXT | NOT NULL 원본 문자열 |
| `my_character` | TEXT | NOT NULL |
| `my_mr` | INTEGER | nullable, >= 0 |
| `my_lp` | INTEGER | nullable, >= 0 |
| `opponent_name` | TEXT | NOT NULL |
| `opponent_character` | TEXT | NOT NULL |
| `opponent_mr` | INTEGER | nullable, >= 0 |
| `opponent_lp` | INTEGER | nullable, >= 0 |
| `result` | TEXT | `WIN`, `LOSE`, `DRAW` |
| `created_at_ms` | INTEGER | NOT NULL |

`UNIQUE(account_id, identity_key)`를 둔다. normalized match row는 insert-only다.

### 6.8 `match_observations`

| column | type | 규칙 |
|---|---|---|
| `id` | TEXT | ULID PK |
| `match_id` | TEXT | NOT NULL FK matches |
| `raw_record_id` | TEXT | NOT NULL FK raw_records, UNIQUE |
| `ingestion_id` | TEXT | NOT NULL FK ingestion_runs |
| `observed_at_ms` | INTEGER | NOT NULL |

하나의 match가 여러 live 수집 또는 legacy 행에서 관측돼도 원본 multiplicity를 잃지 않는다.

### 6.9 `quarantine_records`

| column | type | 규칙 |
|---|---|---|
| `id` | TEXT | ULID PK |
| `raw_record_id` | TEXT | NOT NULL FK raw_records, UNIQUE |
| `account_id` | INTEGER | nullable FK accounts |
| `reason_code` | TEXT | NOT NULL typed code |
| `field_errors_json` | TEXT | validated JSON, 민감값 없음 |
| `status` | TEXT | `OPEN`, `RESOLVED`, `IGNORED` |
| `created_at_ms` | INTEGER | NOT NULL |
| `resolved_at_ms` | INTEGER | nullable |
| `resolution_match_id` | TEXT | nullable FK matches |

### 6.10 `legacy_sources`와 `legacy_rows`

`legacy_sources`:

- `id` ULID PK
- `source_sha256` UNIQUE NOT NULL
- `source_schema_signature` NOT NULL
- `source_path_hint`에는 basename만 저장하고 전체 로컬 경로는 저장하지 않음
- `backup_relpath` NOT NULL
- `backup_sha256` NOT NULL
- `state`: `DISCOVERED`, `BACKED_UP`, `IMPORTING`, `VERIFIED`, `COMPLETED`, `FAILED`
- `started_at_ms`, `finished_at_ms`, `error_code`, `diagnostic_id`
- `report_json`: count/hash 결과만 저장, 실제 이름 없음

`legacy_rows`:

- `id` ULID PK
- `source_id` FK legacy_sources
- `table_name`: `players` 또는 `matches`
- `legacy_pk` TEXT
- `ordinal` INTEGER
- `raw_payload` BLOB canonical JSON zlib
- `canonical_sha256` TEXT
- `disposition`: `ACTIVE_ACCOUNT`, `NORMALIZED`, `DUPLICATE`, `QUARANTINED`, `PROVENANCE_ONLY`
- `raw_record_id` nullable FK raw_records
- `match_id` nullable FK matches
- `quarantine_id` nullable FK quarantine_records
- `UNIQUE(source_id, table_name, legacy_pk, ordinal)`

### 6.11 `settings`

singleton `id=1`:

- `auto_collect_enabled` BOOLEAN default true
- `collection_interval_seconds` INTEGER default 60, CHECK 30~900
- `collection_limit` INTEGER default 20, CHECK 1~100
- `last_window_json` validated JSON
- `onboarding_step` TEXT
- `updated_at_ms` INTEGER

## 7. SQLite engine 정책

모든 connection에 다음 pragma를 적용하고 integration test가 실제 값을 검사한다.

```sql
PRAGMA foreign_keys = ON;
PRAGMA journal_mode = WAL;
PRAGMA synchronous = FULL;
PRAGMA busy_timeout = 5000;
PRAGMA temp_store = MEMORY;
```

- network/Playwright 호출 중 transaction 금지
- request/job마다 새 Session
- writer는 하나의 `threading.Lock`을 거친 짧은 unit of work
- read는 별도 Session이며 writer lock을 획득하지 않음
- `expire_on_commit=False`, implicit autoflush 금지
- 모든 repository write는 명시적 transaction context 안에서만 가능
- commit 후에만 domain event를 event hub에 publish
- 시작 시 `PRAGMA quick_check`와 `foreign_key_check` 실패하면 readiness 503, write 금지
- DB trigger가 `raw_records`의 payload/identity field 변경, terminal raw disposition 재변경, `matches`와 `legacy_rows`의 update/delete를 `RAISE(ABORT)`로 차단

## 8. Error 계약

domain/application 오류는 아래 안정적인 code 중 하나다. 예상하지 못한 예외만 `INTERNAL.UNEXPECTED`로 변환한다.

| code | HTTP | retryable | scheduler | 기본 사용자 행동 |
|---|---:|---:|---|---|
| `VALIDATION.USER_CODE` | 422 | false | 유지 | 입력 수정 |
| `VALIDATION.LIMIT` | 422 | false | 유지 | 입력 수정 |
| `SESSION.MISSING` | 401 | false | pause | 로그인 |
| `SESSION.EXPIRED` | 401 | false | pause | 다시 로그인 |
| `SESSION.ACCOUNT_MISMATCH` | 409 | false | pause | 올바른 계정 로그인 |
| `UPSTREAM.TIMEOUT` | 503 | true | 최대 2회 retry | 재시도 |
| `UPSTREAM.UNAVAILABLE` | 503 | true | 최대 2회 retry | 재시도 |
| `UPSTREAM.RATE_LIMITED` | 429 | true | pause 5분 | 나중에 재시도 |
| `UPSTREAM.CONTRACT_CHANGED` | 502 | false | pause | 진단 복사·업데이트 |
| `STORAGE.LOCKED` | 503 | true | pause | 앱 재시작 |
| `STORAGE.FULL` | 507 | false | pause | 공간 확보 |
| `STORAGE.CORRUPT` | 500 | false | pause/write 차단 | 복구 안내 |
| `MIGRATION.UNSUPPORTED_SCHEMA` | 422 | false | 해당 없음 | 원본 유지·보고 |
| `MIGRATION.BACKUP_FAILED` | 500 | true | 해당 없음 | 권한/공간 확인 |
| `MIGRATION.INVARIANT_FAILED` | 409 | false | 해당 없음 | 이관 중단·보고 |
| `JOB.CONFLICT` | 409 | true | 해당 없음 | 현재 작업 완료 대기 |
| `JOB.QUEUE_FULL` | 429 | true | 해당 없음 | 현재 작업 완료 대기 |
| `INTERNAL.UNEXPECTED` | 500 | false | pause | 진단 ID 전달 |

오류 응답:

```json
{
  "type": "urn:sf6viewer:error:upstream.contract_changed",
  "title": "수집 형식이 변경되었습니다",
  "status": 502,
  "detail": "정확성을 위해 새 데이터 저장을 중단했습니다.",
  "code": "UPSTREAM.CONTRACT_CHANGED",
  "retryable": false,
  "action": "COPY_DIAGNOSTICS",
  "diagnostic_id": "01J..."
}
```

raw exception text, selector, cookie, token, 전체 로컬 경로, SQL은 response에 넣지 않는다. UI는 `code`를 한국어 message catalog로 매핑하며 `detail`만으로 분기하지 않는다.

## 9. Single-instance와 고정 포트

### 9.1 단일 인스턴스

- mutex: `Local\SF6Viewer.v2.<SHA256(UserSid) 앞 16자>`
- activation pipe: `\\.\pipe\SF6Viewer.v2.<같은 hash>`
- 첫 인스턴스가 pipe에서 `ACTIVATE`를 수신하면 창을 restore하고 foreground 요청
- 두 번째 인스턴스는 mutex 실패 시 runtime PID/EXE path를 확인하고 pipe에 `ACTIVATE`를 보낸 뒤 exit 0
- mutex는 있지만 pipe가 1초 안에 응답하지 않으면 `기존 SF6Viewer가 응답하지 않습니다`를 표시하고 종료
- PID 이름으로 기존 프로세스를 kill하지 않음

### 9.2 port 8000

첫 인스턴스가 `SO_EXCLUSIVEADDRUSE`로 `127.0.0.1:8000` socket을 직접 bind하고 그 socket을 Uvicorn에 전달한다. preflight check 후 재bind하는 TOCTOU 패턴을 사용하지 않는다.

bind 실패 시 300ms timeout으로 `GET /api/v2/system/identity`를 조회한다.

- product ID와 protocol version이 같은 SF6Viewer면 pipe activate 후 종료
- 다른 서비스면 프로세스 조회가 가능한 경우 PID와 process name만 보여주고 `재시도`, `종료` 제공
- 포트 변경, 상대 프로세스 kill, LAN bind는 금지

## 10. 안전한 bootstrap과 API session

앱 시작마다 `secrets.token_urlsafe(32)`로 bootstrap nonce를 만든다. pywebview는 `http://127.0.0.1:8000/?bootstrap=<nonce>`를 한 번 연다.

1. 서버는 constant-time 비교 후 nonce를 즉시 소모한다.
2. 303으로 `/`에 redirect하며 `sf6v_session` HttpOnly, SameSite=Strict cookie를 설정한다.
3. session은 프로세스 수명과 같고 DB/디스크에 저장하지 않는다.
4. `GET /api/v2/session`이 메모리 CSRF token을 반환한다.
5. POST/PATCH/DELETE는 session cookie와 `X-SF6V-CSRF`를 모두 요구한다.
6. nonce 재사용, 유효한 session cookie와 nonce가 모두 없는 dashboard 접근, 다른 Host는 403이다. 유효한 session cookie를 가진 새로고침은 허용한다.

unauthenticated 허용 endpoint는 다음뿐이다.

- `/api/v2/system/identity`
- `/api/v2/health/live`
- `/broadcast`, `/stats`, `/overlay` 정적 renderer
- renderer가 사용하는 `/api/v2/broadcast/state`

broadcast state는 선수·집계·갱신 상태만 포함하는 읽기 전용 projection이며 설정, 경로, job 오류 세부, migration, auth state를 노출하지 않는다. CORS header를 보내지 않아 다른 origin script가 읽을 수 없게 한다. 모든 static asset은 로컬 bundle이다.

release에서는 `/docs`, `/redoc`, `/openapi.json`을 404로 만든다. CI용 OpenAPI snapshot은 app factory의 test mode에서만 생성한다.

## 11. Coordinator와 scheduler

Coordinator는 in-memory queue와 DB job record를 함께 관리한다. 장기 실행 Playwright 작업은 전용 worker thread 하나에서만 수행한다.

### 11.1 상태 전이

```text
QUEUED → RUNNING → SUCCEEDED
                 ├→ SUCCEEDED_WITH_WARNINGS
                 ├→ FAILED
                 ├→ CANCELLED
                 └→ INTERRUPTED
```

허용하지 않은 상태 전이는 domain error다. 시작 시 DB의 `QUEUED`와 `RUNNING`은 모두 `INTERRUPTED`로 바꾸고, `RAW_COMMITTED` 또는 `NORMALIZING` ingestion은 recovery job 하나로 재처리한다.

### 11.2 queue 규칙

- capacity: active 1 + pending 1
- 실행/대기 중인 `COLLECT`가 있으면 모든 새 collect는 동일 job ID와 `coalesced=true`를 반환
- HTTP client disconnect나 waiter task 취소는 공유 job을 취소하지 않음
- 명시적 cancel endpoint 또는 앱 shutdown만 cooperative cancel flag를 설정
- active가 `LOGIN`이면 collect는 `JOB.CONFLICT`
- active가 `MIGRATE` 또는 `REPROCESS`이고 pending이 비어 있으면 manual collect 하나를 대기시킴
- auto tick은 busy 상태에서 queue에 추가하지 않고 job summary metric `COALESCED_BUSY`만 기록
- manual pending은 auto pending보다 우선하지만 실행 중 job을 선점하지 않음

### 11.3 scheduler

- 기본 interval 60초, 설정 범위 30~900초
- 다음 실행은 이전 collect terminal 시각부터 계산
- sleep/resume으로 deadline이 지났으면 한 번만 즉시 실행
- `SESSION.*`, `CONTRACT_CHANGED`, `ACCOUNT_MISMATCH`, `STORAGE.*` 발생 시 pause
- `TIMEOUT`, `UNAVAILABLE`은 1초, 3초 backoff로 총 2회 추가 시도; fake clock/random seed로 테스트
- rate limit은 5분 pause하고 UI에 next retry를 표시
- scheduler는 UI tab 수와 무관하며 브라우저 `setInterval`을 사용하지 않음

## 12. Buckler adapter 계약

Playwright adapter는 HTML 구조를 직접 domain DTO로 숨기지 않고 아래 envelope를 반환한다.

```text
FetchEnvelope<T>
  status: OK_NONEMPTY | OK_EMPTY | SESSION_EXPIRED |
          RATE_LIMITED | NETWORK_ERROR | CONTRACT_CHANGED
  account_user_code: optional canonical UserCode
  fetched_at: UTC datetime
  records: immutable raw records
  evidence: safe contract markers, no secrets
```

`OK_EMPTY`는 다음을 모두 만족할 때만 허용한다.

1. 인증된 사용자 code가 기대 account와 일치한다.
2. battle log container 또는 공식 JSON payload의 schema marker가 존재한다.
3. 명시적 empty-state marker 또는 검증된 total count 0이 존재한다.

목록 selector를 찾지 못하거나 필수 schema marker가 없으면 `CONTRACT_CHANGED`다. empty list로 대체하지 않는다.

한 collect job은 browser/context 하나를 만들고 같은 context에서 profile과 battle log를 읽는다. 모든 navigation과 selector wait에는 timeout이 있다. `finally`에서 page/context/browser를 닫는다. 전역 persistent context는 금지한다.

### 12.1 profile validation

- 필수: canonical 10자리 user code
- 선택: display name, character, rank, MR, LP
- 숫자를 못 읽으면 0이 아니라 NULL과 field warning
- 기대 user code와 다르면 raw 저장 후 `SESSION.ACCOUNT_MISMATCH`, normalized update 없음

### 12.2 match validation

정규화 필수 필드는 원본 날짜, 내 캐릭터, 상대 이름, 상대 캐릭터, 결과다. 결과는 WIN/LOSE/DRAW만 허용한다. MR/LP는 선택이며 0 이상 integer만 허용한다.

날짜 parser는 versioned fixture에 있는 Buckler 형식만 `Asia/Seoul` local time으로 해석한 뒤 UTC로 변환한다. DST가 없는 timezone이라도 timezone을 명시한다. 해석 실패는 현재 시각으로 대체하지 않고 `UPSTREAM.CONTRACT_CHANGED` reason의 quarantine으로 보낸다.

### 12.3 identity

1. 원본 match ID가 있으면 `src:<id>`
2. hydration/link key가 있으면 `hyd:<key>`
3. v1/fallback은 다음 canonical JSON의 SHA-256: account user code, original date string, 양쪽 이름·캐릭터·MR·LP, result, 동일 source page 안의 occurrence index

fallback은 `fb:<sha256>` 형식이다. 문자열은 Unicode NFC, 외곽 공백 제거, 숫자 JSON, 정렬된 key, UTF-8로 canonicalize한다.

## 13. 수집 transaction 순서

```text
1. browser fetch 완료 — DB transaction 없음
2. job + ingestion RUNNING 짧은 commit
3. 모든 raw_records를 한 transaction으로 insert, ingestion RAW_COMMITTED
4. 각 raw를 순수 parser로 분류 — DB transaction 없음
5. 한 normalization transaction:
   account/profile snapshot upsert-or-insert
   matches INSERT ON CONFLICT DO NOTHING
   match_observations insert
   quarantine insert
   raw disposition 변경
   ingestion count와 terminal state 변경
6. commit 성공
7. job terminal commit
8. SSE collection.completed / data.changed 발행
```

단계 3 이후 crash하면 다음 시작에서 pending raw를 새 recovery job으로 단계 4부터 실행한다. 단계 5 transaction이 실패하면 어떤 raw disposition도 부분 변경되지 않는다. 단계 7이 실패해도 ingestion 결과는 남고 startup reconciliation이 job을 결과에 맞춰 고친다.

완료된 ingestion은 `raw_count = normalized_count + duplicate_count + quarantine_count`여야 한다. DB query와 service assertion이 둘 다 검사한다.

## 14. v1 이관 알고리즘

### 14.1 탐색과 사전 검사

- v1 EXE 디렉터리와 현재 작업 디렉터리의 `sf6viewer.db`만 자동 후보
- SQLite URI `mode=ro&immutable=1`로 열고 쓰기 시도 금지
- `PRAGMA quick_check`, 예상 table/column/type signature 검사
- source 전체 SHA-256 계산
- source가 현재 v2 active DB path이면 거부
- 완료된 동일 source hash가 있으면 검증 report를 반환하고 no-op

### 14.2 backup

SQLite backup API로 `legacy/backups/<source-sha256>.db.tmp`에 복사한다. flush/fsync 후 backup SHA-256이 source와 같을 때만 `.db`로 atomic rename한다. 기존 같은 hash backup이 있으면 내용 hash를 검사한 뒤 재사용한다.

### 14.3 staging DB

active v2 DB가 있으면 SQLite backup API로 `sf6viewer-v2.next.db`를 만들고, 없으면 새 DB에 Alembic head를 적용한다. source import와 검증은 next DB에만 수행한다.

모든 v1 `players`와 `matches` 행은 변환 전에 `legacy_rows.raw_payload`와 대응 `raw_records`로 보존한다. 활성 player는 `user_config.json`의 canonical user code와 일치하는 row를 우선하고, 없으면 `last_updated DESC, id DESC` 첫 row다. 그 외 player는 `PROVENANCE_ONLY`와 `LEGACY_NON_ACTIVE_ACCOUNT` quarantine으로 남긴다. v1 평문 인증은 읽거나 활성화하지 않는다.

v1 match mapping:

| v1 | v2 |
|---|---|
| player.user_code | account.user_code |
| player.name | account/display snapshot |
| player.character/rank/lp | profile snapshot |
| match.match_date naive | `Asia/Seoul` 해석 UTC + 원본 문자열 |
| my/opponent character | 동일 필드, Unknown/빈 값은 quarantine |
| my/opponent mr/lp | nullable integer, 0은 원본이 실제 0일 때만 유지 |
| result | WIN/LOSE/DRAW만 정상화 |
| v1 row identity | fallback canonical hash + occurrence index |

### 14.4 검증과 활성화

table별로 다음 식을 검증한다.

```text
v1 players count = active account row + provenance/quarantined player rows
v1 matches count = normalized observations + duplicate observations + quarantined match rows
```

추가 검증:

- 모든 legacy row canonical SHA-256 multiset가 v1 원본과 동일
- v2에서 v1 projection한 canonical hash Counter가 원본 Counter와 동일
- `PRAGMA integrity_check = ok`
- `PRAGMA foreign_key_check` 0행
- orphan raw, observation, quarantine 0행
- 완료 ingestion count invariant 성립
- golden manifest: players 2, matches 841, WIN 433, LOSE 408, null date 0, 날짜 min/max 일치
- source와 backup SHA-256 동일, source의 이관 전후 SHA-256 동일

모두 성공하면 next DB를 checkpoint, fsync, close한다. 기존 active DB가 있으면 timestamp/hash 이름으로 backup하고 같은 volume에서 atomic replace한다. 실패하면 next DB를 `legacy/reports` 밖의 임시 위치에서 제거하고 active/source/backup을 그대로 유지한다. 실패 report에는 count와 hash만 넣고 실제 선수명은 넣지 않는다.

동일 source를 두 번 실행하면 두 번째는 no-op이며 모든 table count가 동일해야 한다. backup/create/import/verify/replace 단계마다 fault injection test를 둔다.

### 14.5 golden fixture

`tests/fixtures/v1/v1_841.sqlite`는 현재 실제 구조와 분포를 보존한 결정론적 비식별 fixture다.

- player/user code/name/opponent name을 stable 가명으로 치환
- 날짜, result, MR/LP null·분포, 중복 multiplicity, FK 구조 유지
- cookie/token/auth 파일은 포함하지 않음
- `manifest.json`에 fixture SHA-256, schema signature, table count, null count, result count, date min/max, canonical multiset digest 저장
- fixture 생성 스크립트는 원본 DB를 read-only로 열고 output을 새 임시 파일에만 작성
- 실제 DB와 생성 중간 파일은 git ignore, fixture만 secret scan 후 commit

## 15. REST 계약

prefix는 `/api/v2`다. request/response field는 snake_case, timestamp는 UTC ISO-8601 `Z`, ID는 ULID string이다.

### 15.1 system

- `GET /system/identity` → product ID, semantic app version, API version 2, PID, instance ID
- `GET /health/live` → process alive
- `GET /health/ready` → 200 READY 또는 503 with blockers
- `GET /system/status` → app, DB, auth, scheduler, active job, last successful ingestion
- `POST /system/shutdown` → 202; pywebview session+CSRF만 허용

### 15.2 jobs

- `POST /jobs/login` body `{}` → 202 JobRef
- `POST /jobs/collections` body `{"reason":"MANUAL","limit":20}` → 202 JobRef
- `GET /jobs/{job_id}` → JobDetail
- `POST /jobs/{job_id}/cancel` → 202 JobDetail
- `GET /jobs?cursor=&limit=` → cursor page

JobRef:

```json
{
  "job": {"id":"01J...","type":"COLLECT","state":"QUEUED"},
  "coalesced": false
}
```

`limit` 기본 20, 허용 1~100이다. DOM click event 같은 object/string은 422 `VALIDATION.LIMIT`이다.

### 15.3 data

- `GET /account`
- `GET /matches?cursor=&limit=&result=&my_character=&opponent_character=&from=&to=`
- `GET /stats/summary?window=100`
- `GET /stats/mr-history?cursor=&limit=100`
- `GET /ingestions/{id}`
- `GET /quarantine?cursor=&limit=&status=`
- `POST /quarantine/{id}/reprocess`

목록 limit 기본 50, 최대 200, 정렬은 `occurred_at_ms DESC, id DESC` keyset cursor다. 통계는 반드시 `account_id=1`로 scope한다. window 표본이 없으면 percentage를 NULL로 반환한다.

### 15.4 settings와 migration

- `GET /settings`
- `PATCH /settings` 허용 field만 적용
- `GET /migration/status`
- `GET /migration/report`
- `POST /migration/retry`

임의 local path를 REST body로 받지 않는다. 수동 source 선택은 pywebview native file dialog가 선택한 handle을 application service에 직접 전달한다.

## 16. SSE 계약

`GET /api/v2/events`는 UI session을 요구한다.

```text
id: 1842
event: job.progress
retry: 3000
data: {"schema":1,"occurred_at":"2026-07-19T12:00:00Z","job_id":"01J...","phase":"FETCH_MATCHES","current":8,"total":20}
```

- event ID는 프로세스 내 단조 증가 integer
- schema version 1
- 15초 heartbeat comment
- 최근 500 event 또는 10분 ring buffer
- `Last-Event-ID` replay
- 범위 밖이면 `stream.reset`; client는 status/job/data REST를 다시 조회
- slow client queue 최대 100; 초과 시 stream을 닫아 재동기화 유도
- event payload에 raw 데이터, exception, 경로, 인증 정보 없음
- SSE 전송 실패는 job이나 transaction 결과를 바꾸지 않음

Foundation event: `app.state`, `job.state`, `job.progress`, `collection.completed`, `data.changed`, `auth.changed`, `migration.progress`, `quarantine.created`, `warning`, `stream.reset`.

## 17. 최소 Foundation UI

완성형 UX 전에 contract를 검증하는 최소 React shell을 만든다.

- readiness와 migration blocking 화면
- 로그인 필요 상태
- 수집 idle/running/coalesced/success/error 상태
- 현재 account와 전체 match count
- 최근 job과 diagnostic ID
- `로그인`, `지금 수집`, `중지`, `재시도` 중 상태별 하나의 주요 버튼

서버 문자열은 React text node로만 렌더링한다. `dangerouslySetInnerHTML`과 raw `innerHTML`을 금지한다. typed API client가 request schema를 구성하므로 click handler event가 `limit` 값으로 전달되지 않는다. double-click 시 frontend는 같은 pending mutation을 재사용하고 server single-flight가 최종 보장한다.

## 18. 테스트 설계

### 18.1 Unit 약 60%

- UserCode, UTC time, canonical JSON, identity
- 모든 job 상태 전이와 잘못된 전이
- 25/100-way single-flight와 waiter cancel
- parser: 정상, 실제 empty, session expired, rate limit, malformed date, missing selector, unknown result, MR/LP variant
- error mapping과 redaction
- v1 field mapping과 canonical projection
- scheduler fake clock, sleep/resume, backoff, pause

### 18.2 Integration/contract 약 25%

- 임시 SQLite의 repository/UoW, pragma, FK, unique race
- raw commit 후 crash recovery
- normalization rollback과 count invariant
- account mismatch에서 기존 account/match 불변
- 모든 REST success/problem schema
- OpenAPI snapshot과 error catalog snapshot
- nonce exchange, reuse 거부, CSRF, Host, docs 404, no CORS
- SSE replay/reset/slow client
- fixture HTTP server를 사용하는 Playwright adapter
- v1 golden과 모든 fault injection

### 18.3 Frontend 약 10%

- idle/running/coalesced/success/retryable/login-required/fatal migration 렌더링
- 빈 DB, 1건, 841건, 긴 Unicode 이름, NULL rating
- fake 0/player placeholder가 없음
- click event가 API body로 유출되지 않음
- double-click의 의미적 POST 1회
- raw exception 대신 error code message
- 외부 문자열이 HTML sink에 들어가지 않음

### 18.4 E2E/package 약 5%

- fixture backend로 최초 실행, migration 성공/실패, 로그인 필요, 수집 성공/실패/재시도
- 수집 중 앱 종료와 재시작 recovery
- unsigned Windows onedir에서 top-level pywebview window 감지
- listener가 `127.0.0.1:8000` 하나뿐임
- 잘못된/reused nonce 403, docs 404
- bundled Chromium fixture page 수집
- golden 이관 841건 검증
- 두 번째 EXE가 backend/collector를 추가로 시작하지 않음
- 정상 종료 뒤 owned Uvicorn/Chromium child가 남지 않음
- 임시 AppData를 사용하고 install directory에 DB가 생성되지 않음
- bundle에 `.db`, auth, user config, env, debug dump, ZIP이 포함되지 않음
- Windows Defender scan

CI는 Capcom 실서비스나 실제 인증 상태를 사용하지 않는다. 모든 외부 fixture는 비식별이며 cookie/token을 포함하지 않는다. 시간, timezone, locale, random seed를 고정한다.

## 19. 품질 gate

모든 PR 필수 job:

```text
python-quality
python-unit-integration
migration-golden
api-security-contract
frontend-quality-ui
package-smoke-win-x64
secret-dependency-scan
```

통과 기준:

- Ruff/ESLint error·warning 0
- mypy strict; ignore에는 좁은 범위와 이유가 필요
- Python 전체 line 95%, branch 90%
- frontend line/function 90%, branch 85%
- migration, single-flight, error taxonomy, bootstrap security branch 100%
- 변경 line 100%
- flaky retry 금지
- regression test 없는 bug fix merge 금지
- secret scan, `pip-audit`, npm high/critical audit 통과
- GitHub Actions 기본 permission read-only, third-party action commit SHA 고정
- PR CI 목표 12분, Windows packaging은 다른 test와 병렬

실제 사용자 DB는 release candidate 전에 복사본으로 dry-run하되 로그와 report에는 count/hash 결과만 출력한다.

## 20. Foundation 완료 기준

다음 항목이 모두 자동화 evidence와 함께 통과해야 완료다.

1. 새 source tree가 의존 방향 검사와 strict type/lint를 통과한다.
2. 고정 포트·single-instance·bootstrap session이 package에서 동작한다.
3. 100개 동시 collect 요청이 scraper/DB commit 하나를 공유한다.
4. 실제 empty와 contract change fixture가 서로 다른 terminal 결과를 만든다.
5. 날짜/결과/필수 필드 오류가 quarantine되며 fake 값이 생성되지 않는다.
6. raw commit 직후 crash를 재현하고 재시작 후 정확히 한 번 정상화한다.
7. 841 golden 이관이 count, multiset, FK, checksum을 통과한다.
8. 이관 fault injection 모든 단계에서 원본/backup/active DB가 보존된다.
9. 동일 source 두 번째 이관이 no-op이다.
10. API가 raw exception·로컬 경로·인증 정보를 노출하지 않는다.
11. 최소 UI가 loading/empty/stale/error를 가짜 데이터 없이 표현한다.
12. unsigned onedir가 clean Windows runner에서 시작·수집·종료 smoke를 통과한다.

이 gate를 통과하기 전에는 완성형 홈·분석·OBS styling을 병합하지 않는다.

## 21. Foundation 비범위

- 완성형 홈, 경기 표, 분석 chart
- `/broadcast`, `/stats`, `/overlay`의 최종 visual styling
- background upload UI
- Inno Setup과 Authenticode signing
- 자동 업데이트
- macOS binary와 Windows ARM64
- live Capcom CI
- 다중 account와 원격 API

단, 이후 단계가 사용할 REST/SSE/data/error 계약과 local bundled asset 원칙은 Foundation에서 동결한다.
