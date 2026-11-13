# BeautyFlow

## 테스트

Windows / Python 3.11 기준이다. 기존 `.venv`가 없으면 `python -m venv .venv`로 생성한다.

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pytest -m "not integration"
```

테스트는 AI API 응답을 대체해 노드와 LangGraph의 동작을 검사한다. API 키나 `data/`, `output/` 없이 기본 검사를 실행할 수 있다. 노트북의 실행 테스트 셀은 실행하지 않고 이름으로 정의 셀만 읽는다.

기존 LUMIA 영상 결과를 사용하는 실제 FFmpeg QA 검사는 별도로 실행한다.

```powershell
.\.venv\Scripts\python.exe -m pytest -m integration
```

해당 결과 파일이 없으면 통합 검사는 건너뛴다. 전체 영상 생성 및 모델 응답 품질 평가는 위 자동 테스트와 별개다. `requirements-dev.txt`는 자동 검사 의존성이며 전체 노트북 실행 환경을 설치하는 파일은 아니다.

## GitHub Actions

`.github/workflows/ci.yml`이 push, pull request, 수동 실행 시 Windows / Python 3.11에서 기본 pytest 검사를 수행한다. 로컬 영상 결과에 의존하는 integration 검사는 CI에서 제외한다. 배포 및 실제 AI API 호출은 수행하지 않는다.

결과는 Actions 실행 로그와 `pytest-results` 아티팩트의 JUnit XML에서 확인한다. 워크플로와 테스트를 커밋·push한 뒤 GitHub에서 첫 실행 결과를 확인한다.

`.env`, 가상환경, `data/`, `output/`, 테스트 결과·캐시·루트 임시 파일은 Git에서 제외한다. `AI/tests/`와 CI 설정은 포함한다. 노트북 내부의 미디어 출력은 `.gitignore`로 제외할 수 없으므로 커밋 전에 실행 출력을 지운다.
