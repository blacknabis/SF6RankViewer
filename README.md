# 🥋 SF6 Viewer (Live Match & MR Tracker)

Street Fighter 6 실시간 대전 기록 및 MR 추적 대시보드입니다.  
방송용 오버레이(OBS)와 개인 기록 분석을 위해 제작되었습니다.

## 📥 빠른 실행 (Quick Start)

**Python 설치 없이 바로 실행하고 싶으신가요?**

1. 이 저장소의 **[Releases]** 또는 소스 코드에 포함된 **`SF6ViewerV1_0.zip`** 파일을 다운로드하세요.
2. 압축을 풀고 **`SF6Viewer.exe`**를 실행하면 됩니다.
   - **콘솔 창**이 뜨면서 서버가 시작되고, 잠시 후 **대시보드(브라우저)**가 자동으로 열립니다.
   - 종료하려면 콘솔 창을 닫으시면 됩니다.

---

## ✨ 주요 기능

- **실시간 대전 기록**: 최근 매치 승패 및 캐릭터별 승률 자동 추적
- **MR 히스토리 차트**: MR 변동 추이를 시각적으로 확인 (Area Chart, 모던 디자인)
- **OBS 레이아웃 최적화**: 
  - **1500x200px** 컴팩트 배너 디자인
  - **글래스모피즘(Glassmorphism)** 스타일 (반투명/블러 효과)
  - 배경 투명화 지원 (OBS 브라우저 소스 최적화)
- **자동 갱신**: 30초마다 데이터 자동 동기화 (백그라운드 수집)
- **DB 저장**: SQLite를 사용하여 모든 기록 영구 보관 및 빠른 조회

---

## 🚀 설치 및 실행

### 1. 소스 코드로 실행 (개발용)

**필수 요구사항:**
- Python 3.10 이상
- Google Chrome 브라우저

**설치:**
```bash
# 1. 의존성 패키지 설치
pip install -r requirements.txt

# 2. Playwright 브라우저 설치 (필수)
playwright install chromium
```

**실행:**
```bash
# 서버 실행 (자동으로 대시보드가 열립니다)
run_server.bat
```
- **대시보드**: [http://localhost:8000](http://localhost:8000)
- **오버레이 URL**: [http://localhost:8000/overlay](http://localhost:8000/overlay)

---

### 2. 실행 파일(EXE) 빌드

Python이 없는 환경에서도 실행할 수 있도록 EXE 파일을 만들 수 있습니다.

1. **`build.bat` 실행**: 자동으로 빌드가 진행됩니다.
2. **주의사항 (Windows Defender)**:
   - 빌드 과정에서 Windows Defender가 파일을 차단할 수 있습니다.
   - **프로젝트 폴더를 '제외' 목록에 추가**한 뒤 빌드해야 합니다.
3. **결과물**: `dist/SF6Viewer/SF6Viewer.exe`
   - 이 폴더 전체를 복사해서 사용하면 됩니다.

---

## ⚙️ 초기 설정

1. 프로그램을 처음 실행하면 **설정 페이지**가 나타납니다.
2. 본인의 **User Code** (Buckler 프로필 ID, 숫자 10자리)를 입력하고 저장하세요.
   - 예: `1234567890`
3. 설정 내용은 `config.json` 파일에 저장됩니다.

## 🛠️ 기술 스택

- **Backend**: Python (FastAPI, SQLAlchemy, SQLite)
- **Crawler**: Playwright (Headless Chrome)
- **Frontend**: Vanilla JS, CSS (Chart.js)
