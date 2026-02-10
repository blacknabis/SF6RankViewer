# SF6 Viewer for macOS User Guide 🍎

이 가이드는 **SF6 Viewer**를 macOS 환경에서 직접 실행하는 방법을 설명합니다.
Windows용 EXE 파일은 Mac에서 실행되지 않으므로, **Python 소스 코드**를 직접 다운로드하여 실행해야 합니다.

---

## 1. 준비물 (Prerequisites)

### 1-1. Python 3.12 설치
macOS에는 기본적으로 Python이 깔려있지만, 버전이 낮을 수 있습니다. 최신 버전(3.10 이상)을 설치해주세요.
- [Python 공식 다운로드](https://www.python.org/downloads/macos/)
- 터미널에서 확인: `python3 --version`

### 1-2. Chrome 또는 Edge 브라우저
- [Google Chrome](https://www.google.com/chrome/) 또는 Microsoft Edge가 설치되어 있어야 합니다. (Safari는 지원하지 않습니다)

---

## 2. 설치 방법 (Installation)

### 2-1. 소스 코드 다운로드
터미널(Terminal)을 열고 아래 명령어를 입력하여 프로젝트를 다운로드합니다.
(Git이 없다면 [GitHub Desktop](https://desktop.github.com/)을 사용하거나 `brew install git`으로 설치하세요)

```bash
git clone https://github.com/blacknabis/SF6RankViewer.git
cd SF6RankViewer
```

### 2-2. 가상환경 생성 (권장)
Python 패키지가 시스템 전체에 영향을 주지 않도록 가상환경을 만듭니다.

```bash
python3 -m venv venv
source venv/bin/activate
```
*(터미널 프롬프트 앞에 `(venv)`가 생기면 성공입니다)*

### 2-3. 필요한 라이브러리 설치
```bash
pip install -r requirements.txt
playwright install
```
*(Playwright 브라우저 설치 과정이 포함되어 있습니다)*

---

## 3. 실행 방법 (Running)

터미널에서 다음 명령어로 실행합니다.

```bash
python3 main.py
```

잠시 후 브라우저가 자동으로 열리면서 대시보드(`http://localhost:8000`)에 접속됩니다.

---

## 4. 자주 묻는 질문 (FAQ)

**Q. "ModuleNotFoundError" 에러가 떠요.**
A. `source venv/bin/activate` 명령어로 가상환경을 활성화했는지 확인해주세요.

**Q. "Chromium executable doesn't exist" 에러가 떠요.**
A. `playwright install` 명령어를 다시 실행해보세요. 또한 Chrome 브라우저가 "응용 프로그램" 폴더에 정상적으로 설치되어 있는지 확인하세요.

**Q. 실행할 때마다 터미널을 열어야 하나요?**
A. 네, 현재는 그렇습니다. 편의를 위해 바탕화면에 실행 스크립트(`run.sh`)를 만들어두면 더블 클릭으로 실행할 수도 있습니다.

**[작성 예시: run.sh]**
```bash
#!/bin/bash
cd /path/to/SF6RankViewer
source venv/bin/activate
python3 main.py
```
*(작성 후 `chmod +x run.sh`로 실행 권한을 주어야 합니다)*
