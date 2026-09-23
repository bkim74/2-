# 온순간 아침 창 (OnMoment Morning)

> 매일 콘텐츠를 만들지 않는다. 매일 온순간을 살고 증거만 남긴다.

매일 **아침 6시**, 그리고 **컴퓨터에 로그인할 때마다** 창이 하나 열립니다.
이 창은 범님이 Claude와 나눈 대화, 온순간 문서, 어젯밤의 Return 기록을 읽고
오늘 하루를 위한 **5,000자 이상의 조언 대시보드**를 보여줍니다.

화면은 위에서 아래로 여섯 칸입니다.

| 칸 | 내용 |
|---|---|
| 1. 오늘의 한 문장 | 지금 시각의 해 위치와 오늘 일정 눈금 |
| 2. 오늘 | 3줄(현재·바람·선택, 직접 고쳐 쓰기) · 어제로부터의 질문 · **오늘 꼭 할 3가지** |
| 3. 흐름 · 게이트 | 범님이 엑셀에 설계한 **요일별 리듬** 위에 오늘 할 일 · 모두의창업/Creator OS D-day |
| 4. 레이더 | 매일 아침 **웹 검색**: 정부지원사업(마감 D-day) · AI 교육 · 2주 안의 국내 일정 |
| 5. 조언 | 탭 5개 — 온순간을 산다 / 비즈니스 / 콘텐츠(촬영 미션) / Claude Code(복사용 프롬프트) / 리듬 |
| 6. 밤 3분 Return | 저장하면 다음 날 아침 조언이 읽어 갑니다 |

미리보기: [`preview/sample.html`](preview/sample.html)을 브라우저로 여세요 (2026-09-23 샘플, 레이더는 실제 검색 결과).

---

## 설치 (5분)

**준비물:** Python 3.9 이상, 그리고 [Claude Code](https://code.claude.com)
(이미 쓰고 계신 구독으로 조언을 생성합니다. API 키는 필요 없습니다.)

1. 이 폴더(`onmoment-morning`)를 컴퓨터의 원하는 위치에 둡니다. 예: `C:\OnMoment\onmoment-morning`, `~/OnMoment/onmoment-morning`
2. 설치합니다.

**Windows** — 폴더 안의 **`설치하기.bat`을 더블클릭**하세요. (`onmoment_morning.py`와 같은 폴더에 있습니다)

설치 과정이 창에 단계별로 표시됩니다. Python이 없으면 winget으로 자동 설치하고, 첫 조언 창을 한 번 연 뒤,
매일 06:00 작업 스케줄러와 로그인 시 시작프로그램에 등록합니다. 관리자 권한은 필요 없습니다.

| 파일 | 하는 일 |
|---|---|
| `설치하기.bat` | 설치 (다시 실행해도 안전) |
| `지금열기.bat` | 오늘의 창 열기 |
| `다시만들기.bat` | 오늘 조언을 새로 생성 |
| `점검하기.bat` | 무엇이 문제인지 점검 (결과를 Claude에게 보여주세요) |
| `제거하기.bat` | 자동 실행 해제 |

**macOS** (터미널)
```bash
bash install/install_macos.sh
```

**Linux**
```bash
bash install/install_linux.sh
```

설치가 끝나면 창이 한 번 바로 열립니다. 첫 생성은 1~3분 걸리고, 그동안 해가 뜨는 대기 화면이 보입니다.

- 6시에 컴퓨터가 꺼져 있었다면 켜진 직후에 실행됩니다.
- 로그인할 때 이미 오늘 조언이 있다면 **다시 생성하지 않고 창만 엽니다.**
- 창은 Edge/Chrome의 앱 창(주소창 없는 독립 창)으로 열립니다. `config.json`의 `window_mode`를 `browser`로 바꾸면 일반 탭으로 열립니다.
- 제거: Windows는 `제거하기.bat`, macOS/Linux는 설치 스크립트에 `--uninstall`을 붙여 실행합니다.
- 설치 기록: `~/OnMoment/morning/install.log`, 실행 기록: `~/OnMoment/morning/morning.log`

## 손으로 실행하기

```bash
python onmoment_morning.py            # 오늘 조언 열기 (없으면 생성)
python onmoment_morning.py --force    # 오늘 조언 다시 생성
python onmoment_morning.py --offline  # 인터넷 없이 내장 조언으로
python onmoment_morning.py --diagnose # 설치 상태 점검
```

---

## 무엇을 읽나요

| 출처 | 위치 | 비고 |
|---|---|---|
| Claude Code 대화 | `~/.claude/projects/**/*.jsonl` | 자동. 범님이 쓴 메시지와 도구 사용 통계 (최근 7일 본문, 30일 통계) |
| claude.ai 웹/앱 대화 | `config.json` → `history.claude_ai_export` | claude.ai → Settings → Privacy → **Export data**로 받은 zip의 `conversations.json` 경로를 적으면 함께 읽습니다 |
| 온순간 문서 | `context/` 폴더 | `.md`, `.txt`, `.docx`를 넣으면 반영됩니다 (파일당 12,000자). 기본으로 프로필 · North Star · 모두의창업 · Creator OS · 2nd Life 요약이 들어 있습니다 |
| 어젯밤 Return | `~/Downloads`, `~/OnMoment/morning/returns` | 대시보드에서 저장한 `onmoment-return-날짜.md` |
| 누적 기억 | `~/OnMoment/morning/memory.md` | 매일 조언이 "내일 기억할 사실"을 덧붙입니다. 직접 고치거나 지워도 됩니다 |

모든 기록은 범님의 컴퓨터에만 저장됩니다. 조언을 만들 때 Claude Code(또는 설정한 경우 Anthropic API)로 위 내용이 전송됩니다.
이 도구 폴더에서 `claude -p`로 실행된 기록은 다음 날 다시 읽지 않도록 제외합니다.

## 레이더 (웹 검색)

조언을 쓰는 것과 **동시에** Claude가 웹을 검색합니다. 별도 API 키는 필요 없습니다. (`claude -p` + WebSearch)

- **정부지원사업**: 온순간(AI 자기코칭 · B2B2C · 소셜벤처 · 콘텐츠)에 맞는 공고. 접수 중이거나 30일 안에 열리는 것. 마감이 가까운 순서.
- **AI 교육**: 무료·정부지원 우선. 에이전트 · 바이브코딩 · AI 콘텐츠 제작.
- **국내 일정**: 앞으로 14일 안의 행사·걷기길. 범님이 엑셀에 만든 **월별 국내 여행지 180곳**(`data/places_kr.csv`)에서 먼저 고르고, 날짜는 검색으로 확인합니다.
- 모든 항목에 공고·행사 링크가 붙습니다. 확인하지 못한 날짜는 "확인 필요"로 표시합니다.
- 검색이 안 되는 날은 공식 포털(K-Startup · 기업마당 · 경기콘텐츠진흥원 · K-MOOC · GSEEK · HRD-Net)과 이달의 여행지 목록으로 대신합니다.
- `config.json`의 `radar.region`으로 지역을, `radar.enabled`로 켜고 끄기를 정합니다.

## 요일별 리듬

`config.json`의 `weekly_rhythm`에 요일별 기본 일과가 들어 있습니다. 2nd Life 엑셀의 Bucket lists 시트에서 옮겼습니다.
조언은 이 리듬을 바꾸지 않고, 각 블록에 오늘 할 일만 채웁니다. 리듬을 바꾸고 싶으면 여기를 고치세요.

## 꼭 고쳐 주세요: 일정

`config.json`의 `milestones`에 모두의창업 발표·협약·중간점검, 변리사 상담, 1R 시작일 같은 **실제 날짜**를 적어 주세요.
날짜가 들어간 항목은 D-day로 표시되고, 조언도 그 날짜를 기준으로 우선순위를 잡습니다.
(올려 주신 문서에는 게이트와 조건만 있고 날짜가 없어 지금은 `날짜 미정`으로 두었습니다.)

```json
{ "title": "1R 50명 코호트 시작 (Insight 20% 검증)", "date": "2026-10-20", "status": "next", "track": "build" }
```

`context/00-about-me.md`의 프로필도 범님이 직접 다듬으면 조언이 더 정확해집니다.

## 조언 엔진

`config.json`의 `engine`:

- `auto` (기본): **Claude Code CLI**(`claude -p`, 구독 사용) → **Anthropic API**(`ANTHROPIC_API_KEY` 또는 `ant auth login`, `pip install anthropic` 필요) → **오프라인 내장 조언** 순서로 시도합니다.
- 어떤 경우에도 창은 비지 않습니다. 오프라인 조언은 날짜에 따라 문장과 선택이 바뀝니다.
- 로그: `~/OnMoment/morning/morning.log`

## 파일 구조

```
onmoment-morning/
├── onmoment_morning.py      # 수집 → 프롬프트 → 생성 → 렌더 → 창 띄우기 (표준 라이브러리만 사용)
├── template.html            # 대시보드 디자인 (라이트/다크, 모바일 대응, 체크 상태 자동 저장)
├── config.example.json      # 설정 (첫 실행 시 config.json으로 복사됨)
├── context/                 # 조언이 매일 읽는 온순간 문서
├── data/places_kr.csv       # 월별 국내 여행지 180곳 (2nd Life 엑셀 'on moment' 시트)
├── fallback/brief.json      # 오프라인 조언 + 2026-09-23 샘플
├── install/                 # Windows / macOS / Linux 자동 실행 등록
└── preview/                 # 샘플 데이터(sample_brief.json)와 렌더된 미리보기
```

생성된 조언은 `~/OnMoment/morning/briefs/날짜.html`에 날짜별로 쌓입니다. 나중에 한 달치를 나란히 놓고 보면, 그 자체가 범님의 Storydoing 기록이 됩니다.
