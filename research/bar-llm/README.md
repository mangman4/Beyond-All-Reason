# BAR LLM 비교 실험

Beyond All Reason에서 Cloud GLM 단일 모델과 로컬 모델 또는 역할별 군집이 서로 다른 팀을 제어하는 Windows 연구용 실행 도구입니다. BAR 원본 코드를 유지하고 연구 코드를 이 폴더에 모았습니다.

## 빠른 실행

1. [BAR 공식 런처](https://www.beyondallreason.info/download), Python 3.13, Ollama를 설치합니다. BAR에서 **Red Comet Remake 1.8** 맵을 다운로드하고 일반 경기를 한 번 실행해 엔진과 게임 데이터를 준비합니다.
2. Ollama가 실행된 상태에서 터미널에 `ollama pull qwen2.5:0.5b`를 입력합니다.
3. 이 폴더의 `settings.env.example`을 `settings.env`로 복사합니다. 본인의 Ollama Cloud API 키, 사용 가능한 Cloud 모델 이름, 실제 BAR 런처의 `data` 폴더 경로를 입력합니다. `engine`, `games`, `maps`가 있는 폴더입니다. 환경 변수는 설정 파일보다 우선하며 `--data`는 경로 설정보다 우선합니다.
4. `start-bar-assisted.cmd`를 실행합니다. 처음에는 Python 가상 환경과 고정 버전 의존성을 설치합니다. 게임과 관전 대시보드가 열립니다. 종료는 실행 터미널에서 **Ctrl+C**입니다.

설정 파일과 실행 기록은 Git에서 제외됩니다. API 키를 README나 이슈에 붙여 넣지 마세요. 로컬 모델은 Ollama 기본 주소 `127.0.0.1:11434`, 대시보드는 `127.0.0.1:8766`, 게임 연결은 18765, 엔진은 18452 포트를 사용합니다. 포트가 사용 중이면 이전 실험을 종료합니다.

**실행 버전 주의:** 이 도구는 BAR 런처에 설치된 게임을 기반으로 `data/games/llm-duel.sdd` 연구용 모드를 생성합니다. 이 Git 저장소의 최신 소스를 자동으로 빌드하거나 실행하지 않습니다. 검증한 버전은 [VALIDATION.md](VALIDATION.md)에 기록했습니다. 최신 BAR 버전 호환성은 별도 확인이 필요합니다.

## 실험 모드

| 실행 파일 | 비교 조건 |
|---|---|
| `start-bar-assisted.cmd` | 가능한 행동 중 선택하는 Cloud 단일 vs Local 역할 군집; 기본 시연용 |
| `start-bar-compare.cmd` | 기존 macro 인터페이스, Cloud 단일 vs Local 단일 |
| `start-bar-swarm.cmd` | 기존 macro 인터페이스, Cloud 단일 vs Local 군집 |
| `start-bar-direct.cmd` | 유닛 ID·좌표를 출력하는 직접 제어 실험, Cloud 단일 vs Local 군집 |
| `start-bar-direct-single.cmd` | 직접 제어, Cloud 단일 vs Local 단일 |

군집은 같은 로컬 모델을 경제·생산·전투 역할로 **순차 호출**하고 필요하면 조정 역할을 호출합니다. 서로 다른 모델 세 개를 동시에 메모리에 올리는 구조는 아닙니다.

같은 assisted 조건에서 단일 모델과 군집을 비교하려면 다음 명령을 각각 실행합니다. 작업 폴더는 이 README가 있는 폴더입니다.

```bat
bar_duel\.venv\Scripts\python.exe bar_duel\run.py --control assisted --local-mode single
bar_duel\.venv\Scripts\python.exe bar_duel\run.py --control assisted --local-mode swarm
```

반복 실험은 아래와 같습니다. 기본 한 쌍은 좌우 위치를 바꿔 두 번 실행하며 실행당 현실 시간 600초가 상한입니다.

```bat
bar_duel\.venv\Scripts\python.exe bar_duel\batch.py --control assisted --local-mode swarm --pairs 1 --seconds 600
```

일반 실행 상한은 1,800초이며 `--seconds`로 조절합니다. 판단 횟수 제한은 없습니다. 현재 커맨더 사망 승리 조건을 사용합니다. 시간 상한 종료는 승리나 무승부로 간주하지 않습니다. 결과는 `bar_duel/runs`, 반복 실험은 `bar_duel/batches`에 JSON·CSV·HTML로 기록됩니다. 서로 다른 제어 인터페이스나 모델 조건의 승률은 합산하지 마세요.

## 항공 전력 지원 (2026-10-07)

assisted와 macro에서 1단계 항공 공장, 정찰기, 전투기, 폭격기, 건설기를 선택할 수 있습니다. 대공 포탑과 대공 차량 생산도 제공합니다. 양 팀에 같은 후보 생성 규칙을 적용하며, 실제 후보는 완성된 생산 시설·유휴 상태·건설 가능 위치에 따라 달라집니다. 항공 생산을 강제하지 않으며 자원과 생산 시간이 필요합니다.

기존 공격·후퇴·정찰·지역 방어 명령은 지상군에 적용됩니다. 항공 정찰, 전투기 요격·기지 방어, 폭격기 지상 공격, 항공대 복귀는 별도 명령입니다. 항공대 복귀는 건설기의 작업을 중단시키지 않습니다. 요격·폭격 후보는 현재 보이는 해당 종류의 적이 있을 때만 제공됩니다. 고급 항공기·수송 작전은 아직 별도 후보가 없습니다.

실행 중인 경기를 종료한 뒤 기존 실행기를 다시 실행하면 적용됩니다. 인터페이스 버전은 `assisted-v2-air` / `macro-v3-air`이며 이전 지상군 전용 결과와 승률을 합산하지 마세요.

## 현재 범위와 다음 과제

게임 진행과 LLM 요청은 분리되어 있습니다. 두 팀 관측은 현재 시야와 제한된 최근 관측에 기반합니다. 대시보드에 팀별 판단 기록, 지연, 사용 토큰과 군집 역할 진행을 표시합니다. 요청 실패는 자동 전략으로 대체하지 않습니다.

현재는 연구용 프로토타입입니다. assisted 모드는 엔진이 실행 가능한 행동 후보와 유닛·건설 위치를 제공하므로 자유로운 전체 게임 제어와 구분해야 합니다. 영구 메모리, 별도 스크래치패드, MCP 서버, 강화학습은 아직 구현하지 않았습니다. 향후 기억 유무 비교, 다수 경기 통계, 실행 환경·모델 버전 고정이 필요합니다.

구조: [ARCHITECTURE.md](ARCHITECTURE.md) · 검증: [VALIDATION.md](VALIDATION.md)

## 라이선스와 작성 이력

상위 저장소의 [라이선스 안내](../../LICENSE.md)와 각 파일의 고지를 따릅니다. 이 폴더의 새 연구 코드에는 GPL-2.0-or-later를 적용합니다. BAR 게임 자산·엔진 바이너리·모델 가중치는 이 폴더에 포함하지 않습니다.

OpenAI Codex가 Python/Lua/UI/테스트/문서 작성 및 수정에 광범위하게 사용됐습니다. 자동 검증과 사람의 코드 검토는 별개이며, 팀 검토를 위한 Draft PR로 제출합니다. 상위 [AI 정책](../../AI_POLICY.md)을 참고하세요.

## 경기 중 배속 조절

대시보드 상단의 **1배 / 2배 / 4배** 버튼으로 진행 속도를 바꿉니다. 새 경기는 1배로 시작합니다. 설치 후 첫 적용은 기존 경기를 종료하고 실행기를 다시 실행하세요. 이후 경기 중에는 재시작 없이 조절됩니다.

설정 배속과 최근 약 1초 동안의 실제 프레임 진행 배속을 따로 표시합니다. 컴퓨터가 처리하지 못하면 실제 배속은 설정값보다 낮습니다. 로딩·종료·적용 확인 중에는 버튼을 비활성화하며 적용 확인 실패는 화면에 표시합니다.

LLM 판단 시간과 현실 시간 기준 경기 제한은 배속과 별개입니다. 높은 배속에서는 판단하는 동안 더 많은 게임 시간이 지나갑니다. 양 팀에 동일하게 적용되며, 변경 이력은 manifest.json의 speed_schedule과 events.jsonl에 저장합니다. 다른 배속 이력의 경기는 통합 집계하지 않습니다.
