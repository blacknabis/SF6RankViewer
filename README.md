# SF6Viewer V2.4.2

Street Fighter 6의 Buckler 프로필과 최근 대전 기록을 로컬에 수집하고, 방송 중 OBS에 실시간 전적을 표시하는 Windows 데스크톱 앱입니다.

V2는 안정성과 데이터 정확성을 우선하여 새 구조로 마이그레이션했습니다. 원본 응답을 먼저 보존한 뒤 검증된 데이터만 화면에 반영하며, 로그인 정보와 전적 데이터는 사용자 PC에만 저장합니다.

현재 버전은 SF6Viewer v2.4.2입니다.

## 주요 기능

- **마지막 플레이 캐릭터 기준 전적/MR 그래프 자동 분리**: 방송 중 캐릭터를 변경하면 해당 캐릭터의 전체 승률, 최근 100게임 전적, MR 변동 그래프가 자동으로 전환되어 표시
- Buckler 로그인 세션을 Windows DPAPI로 암호화해 저장
- 로그인과 수집에 설치된 Chrome 또는 Edge를 사용해 EXE에서도 로그인 창을 안정적으로 실행
- 앱 전용 로그인 브라우저 프로필을 사용해 반복되는 봇 확인을 줄이고 재인증 상태 유지
- 앱 창 제목과 대시보드에서 현재 실행 중인 버전을 확인 가능
- 로그인한 Buckler 프로필에서 사용자 코드를 자동 확인
- 랭크 게임 중에만 켜는 전적 수집 시작·중지 기능(마지막 상태를 앱 재시작 뒤에도 유지)
- 자동 수집을 시작한 뒤 최근 대전을 30초마다 수집하며, 프로필은 필요할 때만 확인
- 마지막 대전 수집 성공 시각과 수집 실패·지연 상태를 화면에 표시하고, 실패 원인을 로컬 진단 로그에 기록
- 수집용 브라우저가 닫힌 경우 다음 수집 때 자동 복구
- 원본 응답 보존, 중복 방지, 검증 실패 데이터 격리
- 야스민 등 랭크 미배치 캐릭터의 미확정 LP를 정상 처리
- 원본을 보존하면서 표시 전적을 초기화
- 앱 안에서 프로필, 승률, 세션 MR 증감, MR 차트, 대전 피드와 캐릭터별 상성을 확인하는 **실시간 뷰어** 탭
- 기존 로그인·수집·초기화·OBS 연결 기능을 모은 **수집/연결 관리** 탭
- V1 형태의 OBS 전적 오버레이 제공
- OBS 서버 포트 `8000` 고정

## 빠른 실행

Windows에서 [최신 정식 릴리스의 `SF6Viewer.exe`](https://github.com/blacknabis/SF6RankViewer/releases/latest/download/SF6Viewer.exe) 하나만 내려받아 실행하면 됩니다.
1. `SF6Viewer.exe`를 실행합니다.
2. 처음 사용할 때만 **로그인**을 눌러 열린 Chrome 또는 Edge의 Buckler 브라우저에서 로그인을 완료합니다.
3. 이후 저장된 로그인 세션을 복원하므로 매번 사용자 코드를 입력할 필요가 없습니다.
4. 랭크 게임을 시작할 때 **전적 수집 시작**을 누릅니다. 처음에는 자동 수집이 꺼져 있습니다.
5. 실행 중에는 최근 대전 기록을 30초마다 자동으로 확인합니다. 게임이 끝나면 **전적 수집 중지**를 누르세요.
6. 자동 수집이 중지된 상태에서도 **최근 대전 수집**을 눌러 한 번만 수동 확인할 수 있습니다. 첫 수집에 필요한 프로필이 없으면 먼저 자동으로 확인합니다.
7. 앱 창을 닫으면 자동 수집, 수집용 브라우저, 로컬 서버가 함께 종료됩니다.

자동 수집이 켜진 동안 수집용 Chrome 창은 유지해야 합니다. 직접 닫더라도 다음 수집 시 자동으로 다시 열릴 수 있으며, 자동 수집을 중지하면 현재 요청을 마친 뒤 닫힙니다.

화면의 수집 상태는 자동 수집 설정과 마지막 수집 결과를 함께 반영합니다. 처음 수집하기 전에는 대기 상태이며, 수집 실패나 갱신 지연도 표시됩니다. **로컬 서비스 연결됨**은 앱 내부 서버와의 연결을 뜻합니다. Buckler 수집 상태는 수집 표시와 마지막 성공 시각에서 확인하세요.

수집 도중 앱이 강제 종료되면 다음 실행에서 미완료 작업을 중단 상태로 정리합니다. 다시 수집에 성공하면 마지막 성공 시각과 수집 상태가 갱신됩니다.

## 앱 내 전적 뷰어

앱을 열면 **실시간 뷰어** 탭에서 현재 프로필과 전체/최근 전적, 앱 시작 기준 MR 증감, 연승·연패, 최근 대전 피드 및 캐릭터별 상성을 확인할 수 있습니다. **수집/연결 관리** 탭에는 로그인, 자동·수동 수집, 전적 초기화와 OBS 주소 설정이 있습니다.

실시간 뷰어의 MR 증감 기준은 `앱 세션` 또는 `표시 구간`으로, 차트는 최근 `20`/`50`/`100`전으로 바꿀 수 있습니다. 이 선택은 앱 설정에 저장되어 다음 실행에도 유지됩니다.

최근 대전 피드의 경기별 MR 증감은 같은 캐릭터로 이어진 두 경기의 시작 MR 차이로 계산하며, 수집 기록에서 연속된 경기임을 확인한 경우에만 `추정`으로 표시합니다. 다음 경기의 MR 기록을 기다리는 동안에는 `MR 확인 중`, MR이 없거나 기록이 불완전·상충하여 계산할 수 없으면 `MR 확인 불가`로 표시합니다.

## OBS 브라우저 소스

- URL: [http://127.0.0.1:8000/ui/obs.html](http://127.0.0.1:8000/ui/obs.html)
- 권장 크기: `1400 x 180`

OBS 주소에는 다음 옵션을 사용할 수 있습니다.

- `delta=session`: 앱 시작(또는 전적 초기화) 이후 MR 증감 표시
- `delta=range`: 현재 차트 표시 구간의 MR 증감 표시
- `limit=20`, `limit=50`, `limit=100`: 차트 및 구간 증감에 사용할 최근 대전 수

예: `http://127.0.0.1:8000/ui/obs.html?delta=range&limit=20`

**수집/연결 관리** 탭에서 옵션을 고르면 정확한 OBS 주소를 복사할 수 있습니다. OBS 주소의 쿼리 옵션은 해당 브라우저 소스에만 적용되며, 앱 내 실시간 뷰어에 저장된 선택과는 독립적입니다.

앱을 먼저 실행한 뒤 OBS 브라우저 소스를 사용하세요. 전적이 변경되거나 초기화되어도 오버레이가 자동으로 갱신되므로 OBS에서 수동 새로고침할 필요가 없습니다.

## 데이터 저장 위치

V2 데이터는 다음 위치에 저장됩니다.

```text
%LOCALAPPDATA%\SF6Viewer
├─ auth\buckler.dpapi          # 현재 Windows 사용자만 복호화 가능한 로그인 정보
├─ browser\login\             # Chrome/Edge가 보호하는 앱 전용 로그인 프로필
├─ data\sf6viewer-v2.db        # 프로필, 대전 기록, 수집 상태
├─ legacy\                    # V1 마이그레이션 백업과 보고서
└─ logs\                      # 민감정보가 제거된 진단 로그
```

전적 초기화는 초기화 시각 이전의 기록을 화면과 통계에서 숨기며 원본 수집 데이터는 보존합니다. 현재 앱에는 초기화 취소나 저장 원본 재처리 기능이 없습니다. 같은 경기를 다시 수집해도 초기화 이전 기록은 계속 숨겨지므로, 초기화 전에 표시할 기록인지 확인하세요.

## 소스 코드로 실행

요구 사항:

- Windows 10/11
- Python 3.12.13 이상
- [uv](https://docs.astral.sh/uv/)
- Google Chrome 또는 Microsoft Edge
- Microsoft Edge WebView2 Runtime

```powershell
uv sync --dev
uv run python -m sf6viewer
```

## EXE 빌드

의존성을 설치한 뒤 프로젝트 루트에서 실행합니다.

```powershell
uv sync --dev
.\build_exe.bat
```

결과물은 다음 경로에 생성됩니다.

```text
dist\SF6Viewer.exe
```

`dist\SF6Viewer.exe`는 단일 실행 파일이며 Python을 별도로 설치하지 않아도 됩니다. Google Chrome 또는 Microsoft Edge와 Microsoft Edge WebView2 Runtime은 Windows 환경에 설치되어 있어야 합니다.

## 개발 확인

Python 정적 검사와 테스트, 화면 로직 테스트는 다음 명령으로 확인합니다. 화면 로직 테스트에는 Node.js가 필요합니다.

```powershell
uv run ruff check src tests
uv run mypy src
uv run pytest tests/unit -q
node --test tests/web/viewer-metrics.test.js tests/web/dashboard-viewer.test.js tests/web/dashboard-controller.test.js tests/web/obs.test.js
```

## 업데이트 내역

### V2.4.2 (2026-09-06)

[업데이트 노트](docs/release_notes_v2.4.2.md) · [GitHub 릴리스 및 다운로드](https://github.com/blacknabis/SF6RankViewer/releases/tag/v2.4.2)

- 대전별 MR 증감이 한 경기씩 밀려 표시되던 문제 수정
- 같은 캐릭터의 연속된 경기임을 수집 기록에서 확인한 경우에만 MR 증감을 `추정`으로 표시
- 다음 경기의 기록을 기다리는 `MR 확인 중`과 불완전·상충 기록의 `MR 확인 불가`를 구분
- 기존 전적 데이터와 설정을 유지하며 업데이트 가능

### V2.4.1 (2026-09-06)

[업데이트 노트](docs/release_notes_v2.4.1.md) · [GitHub 릴리스 및 다운로드](https://github.com/blacknabis/SF6RankViewer/releases/tag/v2.4.1)

- 자동 수집 실패·지연 및 마지막 성공 시각 표시와 실패 진단 기록 추가
- 첫 로그인 직후 수동 수집에서도 필요한 프로필을 먼저 확인
- 닉네임 변경 뒤 동일 경기가 충돌로 잘못 격리되는 문제 수정과 기존 기록 호환 처리
- OBS 요청이 응답 없이 대기할 때 제한시간 이후 재시도하도록 개선
- 정적 검사 오류 정리 및 전적 초기화 동작에 맞춘 안내 수정

### V2.2.2 (2026-08-13)

- 릴리스 EXE에서 재인증할 때 Cloudflare 봇 확인이 반복되던 문제 해결
- 앱 전용 로그인 브라우저 프로필을 유지해 보안 확인과 CAPCOM 로그인 상태 재사용
- Chrome 136 이후 보안 정책에 맞춰 기본 사용자 프로필과 로그인 자동화 프로필 분리

[해당 버전의 GitHub 릴리스](https://github.com/blacknabis/SF6RankViewer/releases/tag/v2.2.2)에서 `SF6Viewer.exe`를 받을 수 있습니다.

### V2.2.1 (2026-08-07)

- 신규 캐릭터 야스민의 랭크 미배치 상태에서 Buckler가 반환하는 `league_point: -1`을 미확정 값으로 처리
- 정상 랭크 게임이 `UPSTREAM.CONTRACT_CHANGED`로 격리되던 문제 해결
- 잘못된 평점 형식은 계속 격리해 원본 데이터 검증 유지

[해당 버전의 GitHub 릴리스](https://github.com/blacknabis/SF6RankViewer/releases/tag/v2.2.1)에서 `SF6Viewer.exe`를 받을 수 있습니다.

[CHANGELOG.md](CHANGELOG.md)에서 버전별 변경 사항을 확인할 수 있습니다.

## 기술 구성

- Desktop UI: pywebview
- Local API: FastAPI, Uvicorn
- Storage: SQLite, SQLAlchemy, Alembic
- Buckler collection: Playwright
- Packaging: PyInstaller

모든 API와 OBS 화면은 외부에 공개하지 않고 `127.0.0.1:8000`에서만 동작합니다.
