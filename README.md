# SF6Viewer V2.3.0

Street Fighter 6의 Buckler 프로필과 최근 대전 기록을 로컬에 수집하고, 방송 중 OBS에 실시간 전적을 표시하는 Windows 데스크톱 앱입니다.

V2는 안정성과 데이터 정확성을 우선하여 새 구조로 마이그레이션했습니다. 원본 응답을 먼저 보존한 뒤 검증된 데이터만 화면에 반영하며, 로그인 정보와 전적 데이터는 사용자 PC에만 저장합니다.

현재 정식 버전은 [SF6Viewer v2.3.0](https://github.com/blacknabis/SF6RankViewer/releases/tag/v2.3.0)입니다.

## 주요 기능

- **마지막 플레이 캐릭터 기준 전적/MR 그래프 자동 분리**: 방송 중 캐릭터를 변경하면 해당 캐릭터의 전체 승률, 최근 100게임 전적, MR 변동 그래프가 자동으로 전환되어 표시
- Buckler 로그인 세션을 Windows DPAPI로 암호화해 저장
- 로그인과 수집에 설치된 Chrome 또는 Edge를 사용해 EXE에서도 로그인 창을 안정적으로 실행
- 앱 전용 로그인 브라우저 프로필을 사용해 반복되는 봇 확인을 줄이고 재인증 상태 유지
- 앱 창 제목과 대시보드에서 현재 실행 중인 버전을 확인 가능
- 로그인한 Buckler 프로필에서 사용자 코드를 자동 확인
- 랭크 게임 중에만 켜는 전적 수집 시작·중지 기능(마지막 상태를 앱 재시작 뒤에도 유지)
- 자동 수집을 시작한 뒤 최근 대전을 30초마다 수집하며, 프로필은 필요할 때만 확인
- 수집용 브라우저가 닫힌 경우 다음 수집 때 자동 복구
- 원본 응답 보존, 중복 방지, 검증 실패 데이터 격리
- 야스민 등 랭크 미배치 캐릭터의 미확정 LP를 정상 처리
- 전적 초기화 및 최근 수집 데이터 복구
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
6. 자동 수집이 중지된 상태에서도 **최근 대전 수집**을 눌러 한 번만 수동 확인할 수 있습니다.
7. 앱 창을 닫으면 자동 수집, 수집용 브라우저, 로컬 서버가 함께 종료됩니다.

자동 수집이 켜진 동안 수집용 Chrome 창은 유지해야 합니다. 직접 닫더라도 다음 수집 시 자동으로 다시 열릴 수 있으며, 자동 수집을 중지하면 현재 요청을 마친 뒤 닫힙니다.

## 앱 내 전적 뷰어

앱을 열면 **실시간 뷰어** 탭에서 현재 프로필과 전체/최근 전적, 앱 시작 기준 MR 증감, 연승·연패, 최근 대전 피드 및 캐릭터별 상성을 확인할 수 있습니다. **수집/연결 관리** 탭에는 로그인, 자동·수동 수집, 전적 초기화와 OBS 주소 설정이 있습니다.

실시간 뷰어의 MR 증감 기준은 `앱 세션` 또는 `표시 구간`으로, 차트는 최근 `20`/`50`/`100`전으로 바꿀 수 있습니다. 이 선택은 앱 설정에 저장되어 다음 실행에도 유지됩니다.

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

전적 초기화는 화면에 표시되는 기록을 비우며 원본 수집 데이터는 보존합니다. 필요하면 앱의 복구 기능으로 최근 기록을 다시 구성할 수 있습니다.

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

`dist\SF6Viewer.exe`는 단일 실행 파일이며 Python을 별도로 설치하지 않아도 됩니다. Chrome과 Microsoft Edge WebView2 Runtime은 Windows 환경에 설치되어 있어야 합니다.

## 개발 확인

전체 테스트 대신 변경 범위만 빠르게 확인하려면 다음 명령을 사용할 수 있습니다.

```powershell
uv run ruff check src tests
uv run mypy src
uv run pytest tests/unit -q
```

## 업데이트 내역

### V2.2.2 (2026-08-13)

- 릴리스 EXE에서 재인증할 때 Cloudflare 봇 확인이 반복되던 문제 해결
- 앱 전용 로그인 브라우저 프로필을 유지해 보안 확인과 CAPCOM 로그인 상태 재사용
- Chrome 136 이후 보안 정책에 맞춰 기본 사용자 프로필과 로그인 자동화 프로필 분리

[GitHub 릴리스](https://github.com/blacknabis/SF6RankViewer/releases/tag/v2.2.2)에서 최신 `SF6Viewer.exe`를 받을 수 있습니다.

### V2.2.1 (2026-08-07)

- 신규 캐릭터 야스민의 랭크 미배치 상태에서 Buckler가 반환하는 `league_point: -1`을 미확정 값으로 처리
- 정상 랭크 게임이 `UPSTREAM.CONTRACT_CHANGED`로 격리되던 문제 해결
- 잘못된 평점 형식은 계속 격리해 원본 데이터 검증 유지

[GitHub 릴리스](https://github.com/blacknabis/SF6RankViewer/releases/tag/v2.2.1)에서 최신 `SF6Viewer.exe`를 받을 수 있습니다.

[CHANGELOG.md](CHANGELOG.md)에서 버전별 변경 사항을 확인할 수 있습니다.

## 기술 구성

- Desktop UI: pywebview
- Local API: FastAPI, Uvicorn
- Storage: SQLite, SQLAlchemy, Alembic
- Buckler collection: Playwright
- Packaging: PyInstaller

모든 API와 OBS 화면은 외부에 공개하지 않고 `127.0.0.1:8000`에서만 동작합니다.
