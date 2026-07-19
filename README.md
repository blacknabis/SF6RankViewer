# SF6Viewer V2

Street Fighter 6의 Buckler 프로필과 최근 대전 기록을 로컬에 수집하고, 방송 중 OBS에 실시간 전적을 표시하는 Windows 데스크톱 앱입니다.

V2는 안정성과 데이터 정확성을 우선하여 새 구조로 마이그레이션했습니다. 원본 응답을 먼저 보존한 뒤 검증된 데이터만 화면에 반영하며, 로그인 정보와 전적 데이터는 사용자 PC에만 저장합니다.

## 주요 기능

- Buckler 로그인 세션을 Windows DPAPI로 암호화해 저장
- 로그인한 Buckler 프로필에서 사용자 코드를 자동 확인
- 로그인 후 프로필을 한 번 수집하고, 최근 대전은 30초마다 자동 수집
- 수집용 브라우저가 닫힌 경우 다음 수집 때 자동 복구
- 원본 응답 보존, 중복 방지, 검증 실패 데이터 격리
- 전적 초기화 및 최근 수집 데이터 복구
- V1 형태의 OBS 전적 오버레이 제공
- OBS 서버 포트 `8000` 고정

## 빠른 실행

Windows에서 [최신 정식 릴리스의 `SF6Viewer.exe`](https://github.com/blacknabis/SF6RankViewer/releases/latest/download/SF6Viewer.exe) 하나만 내려받아 실행하면 됩니다.

1. `SF6Viewer.exe`를 실행합니다.
2. 처음 사용할 때만 **로그인**을 눌러 열린 Buckler 브라우저에서 로그인을 완료합니다.
3. 이후 저장된 로그인 세션을 복원하므로 매번 사용자 코드를 입력할 필요가 없습니다.
4. 앱이 실행되는 동안 최근 대전 기록을 30초마다 자동으로 확인합니다.
5. 앱 창을 닫으면 자동 수집, 수집용 브라우저, 로컬 서버가 함께 종료됩니다.

수집용 Chrome 창은 앱이 실행되는 동안 유지해야 합니다. 직접 닫더라도 다음 수집 시 자동으로 다시 열릴 수 있습니다.

## OBS 브라우저 소스

- URL: [http://127.0.0.1:8000/ui/obs.html](http://127.0.0.1:8000/ui/obs.html)
- 권장 크기: `1400 x 180`

앱을 먼저 실행한 뒤 OBS 브라우저 소스를 사용하세요. 전적이 변경되거나 초기화되어도 오버레이가 자동으로 갱신되므로 OBS에서 수동 새로고침할 필요가 없습니다.

## 데이터 저장 위치

V2 데이터는 다음 위치에 저장됩니다.

```text
%LOCALAPPDATA%\SF6Viewer
├─ auth\buckler.dpapi          # 현재 Windows 사용자만 복호화 가능한 로그인 정보
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
- Google Chrome
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

## 기술 구성

- Desktop UI: pywebview
- Local API: FastAPI, Uvicorn
- Storage: SQLite, SQLAlchemy, Alembic
- Buckler collection: Playwright
- Packaging: PyInstaller

모든 API와 OBS 화면은 외부에 공개하지 않고 `127.0.0.1:8000`에서만 동작합니다.
