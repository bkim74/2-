#!/usr/bin/env python3
"""온순간 아침 창 (OnMoment Morning)

매일 아침 6시, 또는 컴퓨터에 로그인할 때 실행되어
- Claude Code 대화 기록(~/.claude/projects)과 claude.ai 내보내기(선택)
- 구글 캘린더(비공개 iCal 주소)와 구글 Keep(Takeout) · 메모 폴더
- context/ 폴더의 온순간 문서들
- 어제의 조언과 어젯밤 Return 기록
을 읽고, 오늘 하루를 시간 블록마다 코칭하는 개조식 대시보드를 만들어 창으로 띄운다.

표준 라이브러리만으로 동작한다. (Anthropic API 엔진을 쓸 때만 `pip install anthropic`)

사용법:
    python onmoment_morning.py              # 오늘 조언이 있으면 열기, 없으면 생성 후 열기
    python onmoment_morning.py --force      # 오늘 조언을 새로 생성
    python onmoment_morning.py --offline    # LLM 없이 내장 조언으로 생성
    python onmoment_morning.py --no-open    # 생성만 하고 창은 띄우지 않음
    python onmoment_morning.py --render brief.json   # 주어진 JSON으로 대시보드만 렌더
    python onmoment_morning.py --diagnose   # 설치 상태 점검 (문제가 생기면 이 결과를 Claude에게 보여주세요)
"""

from __future__ import annotations

import argparse
import datetime as dt
import glob
import json
import os
import re
import shutil
import subprocess
import sys
import time
import webbrowser
import zipfile
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from life_sources import (calendar_text, collect_calendar, collect_notes, guess_tag,  # noqa: E402
                          merge_plan, notes_text)

HERE = Path(__file__).resolve().parent
TEMPLATE = HERE / "template.html"
FALLBACK = HERE / "fallback" / "brief.json"
WEEKDAYS = "월화수목금토일"


# ---------------------------------------------------------------- config

def expand(p: str) -> Path:
    path = Path(os.path.expandvars(os.path.expanduser(p)))
    return path if path.is_absolute() else (HERE / path).resolve()


def load_config() -> dict:
    cfg_path = HERE / "config.json"
    example = HERE / "config.example.json"
    if not cfg_path.exists():
        shutil.copy(example, cfg_path)
    with open(cfg_path, encoding="utf-8") as f:
        cfg = json.load(f)
    with open(example, encoding="utf-8") as f:
        defaults = json.load(f)
    for key, value in defaults.items():  # 업데이트로 새로 생긴 설정은 기본값으로 채운다
        cfg.setdefault(key, value)
    return cfg


def log(data_dir: Path, msg: str) -> None:
    line = f"[{dt.datetime.now():%Y-%m-%d %H:%M:%S}] {msg}"
    print(line)
    try:
        with open(data_dir / "morning.log", "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass


# ---------------------------------------------------------------- history: Claude Code

NOISE_PREFIXES = ("<command-", "<local-command", "<system-reminder", "Caveat:", "[Request interrupted")


def _text_of(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = [b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text"]
        return "\n".join(p for p in parts if p)
    return ""


def _parse_ts(value) -> dt.datetime | None:
    if not value:
        return None
    try:
        return dt.datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone().replace(tzinfo=None)
    except ValueError:
        return None


def collect_claude_code(projects_dir: Path, recent_days: int, stats_days: int) -> tuple[list[dict], dict]:
    """Claude Code 세션 JSONL에서 내가 쓴 메시지와 사용 통계를 모은다."""
    now = dt.datetime.now()
    stats_from = now - dt.timedelta(days=stats_days)
    messages: list[dict] = []
    daily = Counter()
    hours = Counter()
    projects = Counter()
    tools = Counter()
    sessions_recent = set()
    sessions_all = set()

    for path in glob.glob(str(projects_dir / "*" / "*.jsonl")):
        try:
            if dt.datetime.fromtimestamp(os.path.getmtime(path)) < stats_from:
                continue
        except OSError:
            continue
        with open(path, encoding="utf-8", errors="ignore") as f:
            for line in f:
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if rec.get("isSidechain") or rec.get("isMeta"):
                    continue
                ts = _parse_ts(rec.get("timestamp"))
                if not ts or ts < stats_from:
                    continue
                if rec.get("cwd") and Path(rec["cwd"]).resolve() == HERE:
                    continue  # 이 도구가 claude -p로 남긴 자기 자신의 기록은 읽지 않는다
                msg = rec.get("message") or {}
                session = rec.get("sessionId") or path
                project = Path(rec.get("cwd") or Path(path).parent.name).name
                if rec.get("type") == "assistant":
                    for block in msg.get("content") or []:
                        if isinstance(block, dict) and block.get("type") == "tool_use":
                            tools[block.get("name", "?")] += 1
                    continue
                if rec.get("type") != "user":
                    continue
                text = _text_of(msg.get("content")).strip()
                if not text or text.startswith(NOISE_PREFIXES):
                    continue
                sessions_all.add(session)
                daily[ts.date().isoformat()] += 1
                hours[ts.hour] += 1
                projects[project] += 1
                if ts >= now - dt.timedelta(days=recent_days):
                    sessions_recent.add(session)
                    messages.append({"ts": ts, "source": f"Claude Code · {project}", "text": text})

    days = [(now.date() - dt.timedelta(days=i)).isoformat() for i in range(13, -1, -1)]
    stats = {
        "messages_recent": len(messages),
        "sessions_recent": len(sessions_recent),
        "sessions_period": len(sessions_all),
        "active_days_period": len(daily),
        "daily": [{"date": d, "count": daily.get(d, 0)} for d in days],
        "hours": [hours.get(h, 0) for h in range(24)],
        "top_projects": projects.most_common(5),
        "top_tools": tools.most_common(8),
    }
    return messages, stats


# ---------------------------------------------------------------- history: claude.ai export

def collect_claude_ai(export_path: str, recent_days: int) -> list[dict]:
    if not export_path:
        return []
    path = expand(export_path)
    if not path.exists():
        return []
    try:
        with open(path, encoding="utf-8") as f:
            conversations = json.load(f)
    except (OSError, json.JSONDecodeError):
        return []
    since = dt.datetime.now() - dt.timedelta(days=max(recent_days, 30))
    out = []
    for conv in conversations:
        title = conv.get("name") or "대화"
        for m in conv.get("chat_messages") or []:
            if m.get("sender") != "human":
                continue
            ts = _parse_ts(m.get("created_at"))
            text = (m.get("text") or _text_of(m.get("content"))).strip()
            if ts and ts >= since and text:
                out.append({"ts": ts, "source": f"claude.ai · {title}", "text": text})
    return out


def digest_messages(messages: list[dict], budget: int) -> str:
    """최근 메시지일수록 더 많이 남기고, 오래된 것은 앞부분만 남긴다."""
    if not messages:
        return "(최근 대화 기록을 찾지 못했습니다.)"
    messages = sorted(messages, key=lambda m: m["ts"], reverse=True)
    now = dt.datetime.now()
    lines, used = [], 0
    for m in messages:
        age = (now - m["ts"]).days
        cap = 900 if age < 1 else 450 if age < 3 else 220
        text = re.sub(r"\s+", " ", m["text"])[:cap]
        line = f"- [{m['ts']:%m/%d %H:%M}] ({m['source']}) {text}"
        if used + len(line) > budget:
            break
        lines.append(line)
        used += len(line)
    lines.reverse()
    return "\n".join(lines)


# ---------------------------------------------------------------- context documents

def read_docx(path: Path) -> str:
    with zipfile.ZipFile(path) as z:
        xml = z.read("word/document.xml").decode("utf-8", errors="ignore")
    xml = re.sub(r"</w:p>", "\n", xml)
    return re.sub(r"<[^>]+>", "", xml)


def collect_context(dirs: list[str], per_file: int = 12000, total: int = 40000) -> str:
    chunks, used = [], 0
    for d in dirs:
        base = expand(d)
        if not base.exists():
            continue
        for path in sorted(base.iterdir()):
            try:
                if path.suffix.lower() in (".md", ".txt"):
                    text = path.read_text(encoding="utf-8", errors="ignore")
                elif path.suffix.lower() == ".docx":
                    text = read_docx(path)
                else:
                    continue
            except (OSError, zipfile.BadZipFile, KeyError):
                continue
            text = text.strip()[:per_file]
            if used + len(text) > total:
                text = text[: max(0, total - used)]
            if not text:
                break
            chunks.append(f"### {path.name}\n{text}")
            used += len(text)
    return "\n\n".join(chunks)


def collect_returns(dirs: list[str], days: int = 14) -> str:
    since = time.time() - days * 86400
    found = []
    for d in dirs:
        for path in glob.glob(str(expand(d) / "onmoment-return-*.md")):
            if os.path.getmtime(path) >= since:
                found.append(Path(path))
    found = sorted(set(found), key=lambda p: p.name)[-7:]
    return "\n\n".join(f"### {p.name}\n{p.read_text(encoding='utf-8', errors='ignore')[:2500]}" for p in found)


# ---------------------------------------------------------------- milestones

def milestones_with_dday(milestones: list[dict], today: dt.date) -> list[dict]:
    out = []
    for m in milestones:
        m = dict(m)
        if m.get("date"):
            try:
                m["dday"] = (dt.date.fromisoformat(m["date"]) - today).days
            except ValueError:
                m["dday"] = None
        out.append(m)
    return out


# ---------------------------------------------------------------- prompt

SCHEMA = r"""{
  "greeting": "아침 인사 한 줄 (40자 이내, 최근 대화의 구체적 장면 하나)",
  "one_line": "오늘의 한 문장 (25자 안팎, 고백의 톤)",
  "return_question": "어제의 선택/약속에 대한 질문 1개 (한 줄)",
  "briefing": ["오늘의 브리핑 3~5줄 — 캘린더·배경 일정·게이트를 엮은 오늘의 전제와 우선순위. 각 줄 40자 이내, '→'로 판단을 보여줌. 예: '이사준비 D-6 → 저녁 30분 박스 2개만'"],
  "three_lines": {
    "reality": "현재 — 관찰된 사실 한 줄",
    "wish": "바람 — 범님의 말 그대로 한 줄",
    "choice": "선택 — 오늘의 작은 한 행동 한 줄"
  },
  "top3": [
    {"tag": "life|build|content", "text": "오늘 꼭 할 일 (동사로 끝, 30자 안팎)", "why": "왜 오늘 · 어느 블록 (20자 안팎)"}
  ],
  "day_plan": [
    {"time": "06:00", "end": "07:00", "title": "블록 제목", "tag": "life|build|content|claude|rest", "source": "rhythm|calendar",
     "detail": "이 블록의 오늘 할 일 한 줄 (명사형)",
     "coach": ["준비 · ...", "현장 · ...", "후 · ..."]}
  ],
  "keep_picks": [
    {"note": "Keep/메모 제목", "item": "오늘 꺼낼 항목 한 줄", "when": "어느 블록에서 (예: 14:00 온순간 빌드)"}
  ],
  "build_focus": {"gate": "지금 게이트", "today_task": "오늘 단 하나", "metric": "끝났다고 말할 기준"},
  "content_mission": {
    "question": "오늘 품고 다닐 질문 하나",
    "shots": [{"key": "WHERE", "hint": "..."}, {"key": "MOVE", "hint": "..."}, {"key": "DETAIL", "hint": "..."}, {"key": "HUMAN", "hint": "..."}, {"key": "EVIDENCE", "hint": "..."}],
    "voice_memo": ["방금 무슨 일이 있었나?", "예상과 무엇이 달랐나?", "내게 뭐가 걸렸나?"],
    "episode_seed": "이번 주 에피소드 후보 한 줄"
  },
  "chapters": [
    {
      "id": "life | build | content | claude | rhythm",
      "kicker": "짧은 머리말 (예: 01 · 온순간을 산다)",
      "title": "장 제목 (20자 안팎)",
      "evidence": "근거 — 날짜 + 범님의 말 짧은 인용 (한 줄)",
      "body_md": "개조식 본문. '### 소제목' 3~4개, 각 소제목 아래 '- ' 항목 3~5개. 항목은 한 줄(45자 이내), 명사형·'~하기' 종결. 필요하면 '  - ' 하위 항목. 문단 금지. 장당 900~1,300자",
      "actions": ["오늘 할 구체 행동 3개 (각 한 줄)"]
    }
  ],
  "claude_code": [
    {"title": "팁 제목", "why": "범님의 사용 패턴에서 필요한 이유 (한 줄)", "how": ["적용 단계 2~4개, 각 한 줄"], "prompt": "그대로 복사해 붙여넣을 프롬프트 또는 명령"}
  ],
  "watchouts": ["오늘 조심할 패턴 2~3개 (관찰, 한 줄)"],
  "evening": ["밤 3분 질문 3개"],
  "memory_update": ["내일의 조언 AI가 기억할 새 사실 2~5개 — 확인된 것만"]
}"""

PROMPT = """당신은 김범(범님)의 아침 동반자이자 하루 코치다. 범님은 온순간(OnMoment)의 창업자이자 첫 번째 Storydoer다.
매일 아침 6시(또는 컴퓨터를 켤 때) 이 조언이 창으로 뜬다. 범님이 "진정 매순간 온순간을 살고 싶다"고 해서 만든 창이다.

오늘: {today} ({weekday}요일)

# 온순간의 규칙 (범님이 직접 정한 것)
- AI is not the author of meaning. AI is the architect of attention. 의미와 선택은 범님이 한다.
- Concrete before abstract. Observation before interpretation. 판결·진단 금지.
- 가능성은 가설로, 최대 2개. 한 번에 하나의 tension만.
- Small controllable action. Reality before positivity. 억지 교훈·억지 긍정 금지.
- User words before AI words: 범님의 표현을 그대로 되비춘다.
- 매일 콘텐츠를 만들지 않는다. 매일 온순간을 살고 증거만 남긴다.
- 1인 창업자의 소진 경계. 쉼·가족·신앙도 정식 블록이다.

# 문체 — 개조식 (가장 중요)
- 모든 글은 개조식. 문단·설명문 금지. 한 항목 = 한 줄 = 한 가지.
- 종결은 명사형 또는 '~하기' (예: "10분 스트레칭", "3줄만 고쳐 쓰기"). '~합니다/~해요' 금지.
- 숫자·시각·장소·사람(관계로만 표기)을 넣어 구체적으로. 형용사·수식어 최소.
- 판단은 '→'로 짧게 (예: "수영 06:00 → 기도는 수영 후 10분").

# 입력 1 — 범님에 대한 문서 (프로필, North Star, 모두의창업, Creator OS, 2nd Life)
{context}

# 입력 2 — 일정 게이트 (config.json, D-day는 오늘 기준)
{milestones}

# 입력 3 — 구글 캘린더 (범님의 실제 일정)
{calendar}

# 입력 4 — 오늘의 흐름 초안 = 요일별 리듬 + 캘린더 일정 (source=calendar 는 실제 약속)
{plan}

# 입력 5 — 구글 Keep · 메모 (최근/고정 메모와 체크 안 된 항목)
{notes}

# 입력 6 — 조언 AI의 누적 기억
{memory}

# 입력 7 — 어제의 선택 / 어젯밤 Return 기록
어제 조언의 선택: {yesterday_choice}
{returns}

# 입력 8 — Claude Code 사용 통계 (최근 {stats_days}일)
{stats}

# 입력 9 — 범님이 최근 Claude와 나눈 대화 (범님이 쓴 메시지만, 시간순)
{history}

# 과제 — 오늘 하루를 실제로 사는 데 쓰는 코칭 대시보드
- briefing: 입력 3의 오늘 일정·배경 일정(이사 준비 같은 여러 날 일정)·앞으로 7일의 큰 일정·게이트 D-day를 엮어
  오늘의 전제와 우선순위 3~5줄. 에너지가 몰리는 날/비는 날, 준비가 필요한 다가오는 약속(예: 사흘 뒤 포럼)을 짚기.
- day_plan: 입력 4를 기본으로. 캘린더 일정(source=calendar)은 시간·제목 그대로 유지하고 반드시 포함.
  겹친 리듬 블록(overlap 표시)은 옮기거나 줄이고 detail에 '→ 06:50 이후로' 식으로 조정 표시.
  모든 블록에 detail 한 줄 + coach 2~3개 ('준비 · ', '현장 · ', '후 · ' 로 시작, 각 25자 안팎):
  준비물·이동 시간·질문 하나·찍을 장면·끝나고 남길 한 줄 등 그 블록을 온순간으로 사는 구체 코칭.
  source=calendar 블록은 그 약속에 맞춘 코칭 (예: 포럼 → 명함 10장·물을 질문 1개·만날 사람 1명).
- keep_picks: 입력 5에서 오늘 꺼낼 만한 것 최대 3개와 할 블록. 메모가 없으면 빈 배열.
- top3: 정확히 3개(life 1, build 1, content 1). 각각 day_plan의 어느 블록에서 할지 why에 표시.
- chapters: 정확히 5개, 이 순서: life(온순간을 산다 — 자기·관계·신앙), build(비즈니스 빌드업 — 모두의창업 게이트),
  content(콘텐츠 실행 — Creator OS), claude(Claude Code를 더 잘 쓰는 법), rhythm(오늘의 리듬 — 에너지·쉼·가족·이번 주 일정).
  5개 장의 body_md 합계 한국어 5,000자 이상. 일반론 금지, 최근 대화·캘린더·메모의 구체 장면을 짚기.
  evidence에 근거 날짜+인용. 근거가 없으면 "최근 대화엔 이 주제 없음 → 문서 기준"이라고 쓰기.
- claude_code: 4개. 통계와 대화에서 보이는 실제 병목에 맞춘 팁.
- build_focus: 모두의창업 게이트 중 지금 가장 중요한 것 하나.
- memory_update: 오늘 새로 확인된 사실만 (추측 금지).

반드시 아래 스키마의 JSON 객체 하나만 출력한다. 코드블록·설명·머리말 없이 {{ 로 시작해 }} 로 끝낸다.
{schema}
"""


def build_prompt(cfg: dict, today: dt.date, context: str, milestones: list[dict], memory: str,
                 yesterday_choice: str, returns: str, stats: dict, history: str,
                 calendar: str = "", plan: list[dict] | None = None, notes: str = "") -> str:
    ms_lines = []
    for m in milestones:
        when = f"{m['date']} (D{'-' if m.get('dday', 0) >= 0 else '+'}{abs(m['dday'])})" if m.get("dday") is not None else "날짜 미정"
        ms_lines.append(f"- [{m.get('status')}] {m['title']} · {when}")
    stats_text = json.dumps({k: v for k, v in stats.items() if k not in ("daily",)}, ensure_ascii=False)
    return PROMPT.format(
        today=today.isoformat(), weekday=WEEKDAYS[today.weekday()],
        context=context or "(없음)", milestones="\n".join(ms_lines) or "(없음)",
        memory=memory or "(아직 없음 — 첫 아침)", yesterday_choice=yesterday_choice or "(없음)",
        returns=returns or "(어젯밤 Return 기록 없음)", stats_days=cfg["history"]["stats_days"],
        stats=stats_text, history=history, schema=SCHEMA,
        calendar=calendar or "(캘린더 연결 안 됨 — config.json 의 calendar.ics_urls)",
        plan=plan_text(plan if plan is not None else today_rhythm(cfg, today)),
        notes=notes or "(연결된 메모 없음)",
    )


# ---------------------------------------------------------------- weekly rhythm

DAY_KEYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


def today_rhythm(cfg: dict, today: dt.date) -> list[dict]:
    blocks = (cfg.get("weekly_rhythm") or {}).get(DAY_KEYS[today.weekday()]) or []
    return [dict(b) for b in blocks]


def plan_text(blocks: list[dict]) -> str:
    lines = []
    for b in blocks:
        line = f"- {b['time']}~{b.get('end') or ''} [{b.get('tag', '')}] {b['title']} (source={b.get('source', 'rhythm')})"
        if b.get("source") == "calendar" and b.get("detail"):
            line += f" @ {b['detail']}"
        if b.get("overlap"):
            line += f" ※ 겹침: {b['overlap']}"
        lines.append(line)
    return "\n".join(lines) or "(설정 없음)"


# ---------------------------------------------------------------- radar (웹 검색)

RADAR_SCHEMA = r"""{
  "grants": [
    {"title": "사업/공고명", "org": "주관 기관", "deadline": "YYYY-MM-DD 또는 null(상시)", "status": "접수중|접수예정|상시",
     "fit": "온순간에 왜 맞는지 한 줄", "action": "범님이 오늘 할 한 가지", "url": "공고 페이지 URL"}
  ],
  "ai_edu": [
    {"title": "교육명", "org": "기관", "date": "시작일 YYYY-MM-DD 또는 '상시'", "format": "온라인|오프라인(장소)", "cost": "무료|유료(금액)",
     "fit": "범님에게 왜 맞는지 한 줄", "url": "신청 페이지 URL"}
  ],
  "events": [
    {"title": "행사/장소명", "place": "지역", "date_start": "YYYY-MM-DD", "date_end": "YYYY-MM-DD",
     "fit": "온순간 콘텐츠로 어떤 질문을 열 수 있는지 한 줄", "shot": "찍어 올 한 장면", "url": "공식 페이지 URL"}
  ]
}"""

RADAR_PROMPT = """당신은 김범(범님)의 리서치 비서다. 오늘은 {today} ({weekday}요일).
범님은 1인 창업자로 '온순간'을 만든다: AI가 판정하지 않고 가능성을 비추는 자기코칭 커뮤니티
(현재·바람·선택 3줄 카드 → 실제로 살아보기), 부모교육·은퇴교육·리트릿 기관이 비용을 내는 B2B2C,
소셜벤처 지향, 얼굴 없는 여행·사람 이야기 유튜브 채널 준비 중. 거주·활동 지역: {region}.
법인 설립 전(예비창업자) ~ 초기, 모두의창업(경기콘텐츠진흥원) 참여 중.

웹 검색으로 아래 세 가지를 찾아라. 검색 결과에서 실제로 확인한 것만 쓴다.
모든 항목에 실제 공고·신청·행사 페이지 URL을 넣는다. 마감·종료가 지난 것은 뺀다. 날짜를 확인 못 했으면 넣지 않는다.

1. grants (3~5개): 온순간 비즈니스화에 도움이 될 정부·지자체·공공기관 지원사업.
   지금 접수 중이거나 30일 안에 접수가 열리는 것. 예: K-Startup 사업공고, 기업마당, 경기콘텐츠진흥원,
   경기도경제과학진흥원, 창업진흥원, 한국사회적기업진흥원(소셜벤처), 중소벤처기업부, 콘텐츠진흥원, 시니어·평생교육 관련 공모.
   마감이 가까운 순서로.
2. ai_edu (2~4개): 범님이 들을 만한 AI 교육. 무료 또는 정부지원 우선. AI 에이전트·바이브코딩·Claude Code·
   AI 영상/콘텐츠 제작·AI 창업 관련. 30일 안에 시작하거나 상시 모집.
3. events (3~5개): 앞으로 14일 안에 열리는 국내 행사·축제·걷기길 시즌 중
   온순간 콘텐츠(사람·질문·걷기·순례·가족·자연)에 맞는 것. 아래는 범님이 직접 만든 이달의 후보 목록이다.
   이 목록을 우선 검토하고 실제 일정은 검색으로 확인한다. 주말에 갈 만한 것 우선.
{places}

설명·머리말·코드블록 없이 아래 스키마의 JSON 객체 하나만 출력한다.
{schema}
"""

FALLBACK_GRANTS = [
    {"title": "K-Startup 사업공고 (진행 중)", "org": "창업진흥원", "deadline": None, "status": "상시",
     "fit": "예비·초기창업 지원사업이 가장 먼저 올라오는 곳", "action": "'예비창업' · '소셜' · '콘텐츠'로 필터해 보기",
     "url": "https://www.k-startup.go.kr/web/contents/bizpbanc-ongoing.do"},
    {"title": "기업마당 지원사업 공고", "org": "중소벤처기업부", "deadline": None, "status": "상시",
     "fit": "정부·지자체 지원사업을 한곳에서 검색", "action": "지역 '경기'와 분야 '창업'으로 검색",
     "url": "https://www.bizinfo.go.kr"},
    {"title": "경기콘텐츠진흥원 사업공고", "org": "경기콘텐츠진흥원", "deadline": None, "status": "상시",
     "fit": "모두의창업 주관기관. 콘텐츠·창업 후속 지원", "action": "후속 지원·멘토링 공고 확인",
     "url": "https://www.gcon.or.kr"},
]
FALLBACK_AI_EDU = [
    {"title": "K-MOOC 인공지능 강좌", "org": "국가평생교육진흥원", "date": "상시", "format": "온라인", "cost": "무료",
     "fit": "기초부터 활용까지 무료 강좌", "url": "https://www.kmooc.kr"},
    {"title": "지식(GSEEK) 경기도 평생학습", "org": "경기도", "date": "상시", "format": "온라인", "cost": "무료",
     "fit": "경기도민 무료 AI·디지털 강좌", "url": "https://www.gseek.kr"},
    {"title": "HRD-Net 국민내일배움카드 과정", "org": "고용노동부", "date": "상시", "format": "온라인·오프라인", "cost": "지원",
     "fit": "AI·바이브코딩 과정 검색", "url": "https://www.hrd.go.kr"},
]


def load_places(month: int) -> list[str]:
    import csv

    path = HERE / "data" / "places_kr.csv"
    if not path.exists():
        return []
    with open(path, encoding="utf-8") as f:
        return [row["place"] for row in csv.DictReader(f) if str(month) in row["months"].split()]


def fallback_radar(today: dt.date, note: str = "") -> dict:
    """검색을 못 한 날에도 레이더가 비지 않도록: 공식 포털 + 범님의 월별 목록."""
    from urllib.parse import quote

    places = load_places(today.month)
    start = today.toordinal() % max(1, len(places)) if places else 0
    picks = (places[start:] + places[:start])[:5]
    events = [{"title": p.split(":")[0].strip(), "place": "", "date_start": None, "date_end": None,
               "fit": (p.split(":", 1)[1].strip() if ":" in p else "범님의 이달 후보 목록에서"),
               "shot": "", "url": "https://search.naver.com/search.naver?query=" + quote(p.split(":")[0].split("(")[0].strip() + f" {today.year}")}
              for p in picks]
    return {"grants": FALLBACK_GRANTS, "ai_edu": FALLBACK_AI_EDU, "events": events,
            "meta": {"source": "offline", "note": note}}


def run_radar(cfg: dict, today: dt.date) -> dict:
    rc = cfg.get("radar") or {}
    places = load_places(today.month) + [f"(다음 달) {p}" for p in load_places(today.month % 12 + 1)[:15]]
    prompt = RADAR_PROMPT.format(
        today=today.isoformat(), weekday=WEEKDAYS[today.weekday()], region=rc.get("region", "경기도"),
        places="\n".join(f"- {p}" for p in places) or "(목록 없음)", schema=RADAR_SCHEMA)
    raw = run_claude_cli(prompt, cfg.get("claude_cli_model", ""), int(rc.get("timeout_sec", 480)),
                         tools=["WebSearch", "WebFetch"])
    radar = parse_json(raw)
    for key in ("grants", "ai_edu", "events"):
        radar[key] = [x for x in radar.get(key) or [] if isinstance(x, dict) and x.get("title")]
    radar["meta"] = {"source": "web", "searched_at": dt.datetime.now().isoformat(timespec="minutes")}
    return radar


# ---------------------------------------------------------------- engines

def find_claude() -> str | None:
    """PATH에 없더라도 흔한 설치 위치에서 claude CLI를 찾는다."""
    exe = shutil.which("claude")
    if exe:
        return exe
    home = Path.home()
    candidates = [home / ".local" / "bin" / "claude", home / ".claude" / "local" / "claude"]
    if sys.platform.startswith("win"):
        appdata = Path(os.environ.get("APPDATA", home / "AppData" / "Roaming"))
        candidates = [home / ".local" / "bin" / "claude.exe", appdata / "npm" / "claude.cmd",
                      home / ".claude" / "local" / "claude.exe"] + candidates
    else:
        candidates += [Path("/opt/homebrew/bin/claude"), Path("/usr/local/bin/claude")]
    return next((str(c) for c in candidates if c.exists()), None)


def run_claude_cli(prompt: str, model: str, timeout: int, tools: list[str] | None = None) -> str:
    exe = find_claude()
    if not exe:
        raise RuntimeError("claude CLI를 찾지 못했습니다")
    cmd = [exe, "-p", "--output-format", "text"]
    if model:
        cmd += ["--model", model]
    if tools:
        cmd += ["--allowedTools", ",".join(tools)]
    windows = sys.platform.startswith("win")
    proc = subprocess.Popen(
        cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, encoding="utf-8", errors="replace", cwd=str(HERE),
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) if windows else 0,  # 콘솔 창이 번쩍이지 않게
        start_new_session=not windows,
    )
    try:
        out, err = proc.communicate(prompt, timeout=timeout)
    except subprocess.TimeoutExpired:
        # claude.cmd → node 처럼 자식 프로세스까지 통째로 끝내야 파이프가 풀린다
        if windows:
            subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], capture_output=True,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        else:
            import signal
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except OSError:
                proc.kill()
        try:
            proc.communicate(timeout=10)
        except subprocess.TimeoutExpired:
            pass
        raise
    if proc.returncode != 0 or not out.strip():
        detail = (err.strip() or out.strip())[:300]
        raise RuntimeError(f"claude CLI 실패 (코드 {proc.returncode}): {detail}")
    return out


def run_api(prompt: str, model: str) -> str:
    import anthropic  # 선택 의존성

    client = anthropic.Anthropic()
    params = dict(
        model=model,
        max_tokens=32000,
        thinking={"type": "adaptive"},
        output_config={"effort": "high"},
        messages=[{"role": "user", "content": prompt}],
    )
    try:
        with client.beta.messages.stream(
            betas=["server-side-fallback-2026-07-01"], fallbacks="default", **params
        ) as stream:
            message = stream.get_final_message()
    except TypeError:  # fallbacks를 모르는 구버전 SDK
        with client.messages.stream(**params) as stream:
            message = stream.get_final_message()
    if message.stop_reason == "refusal":
        raise RuntimeError("API가 요청을 거절했습니다")
    return "".join(b.text for b in message.content if b.type == "text")


def api_available() -> bool:
    import importlib.util

    return bool(importlib.util.find_spec("anthropic")) and bool(
        os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"))


def parse_json(raw: str) -> dict:
    start, end = raw.find("{"), raw.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("JSON을 찾지 못했습니다")
    return json.loads(raw[start : end + 1])


def parse_brief(raw: str) -> dict:
    brief = parse_json(raw)
    for key in ("one_line", "three_lines", "day_plan", "chapters"):
        if key not in brief:
            raise ValueError(f"'{key}' 항목이 없습니다")
    return brief


def offline_brief(today: dt.date, cfg: dict | None = None, plan: list[dict] | None = None,
                  notes: list[dict] | None = None) -> dict:
    """LLM 없이도 창이 비지 않도록, 내장 조언을 날짜별로 회전시킨다."""
    with open(FALLBACK, encoding="utf-8") as f:
        brief = json.load(f)
    if plan is None:
        plan = [dict(b, source="rhythm") for b in today_rhythm(cfg, today)] if cfg else []
    coach = brief.pop("coach", {})
    i = today.toordinal()
    if plan:  # 범님이 설계한 요일별 리듬 + 캘린더 일정
        blocks = []
        for n, b in enumerate(plan):
            b = dict(b)
            pool = coach.get("calendar" if b.get("source") == "calendar" else b.get("tag", "rest")) or coach.get("rest") or []
            if pool:
                b.setdefault("coach", pool[(i + n) % len(pool)])
            if b.get("overlap"):
                b["detail"] = f"→ 캘린더 일정({b['overlap']})에 맞춰 줄이거나 옮기기"
            blocks.append(b)
        brief["day_plan"] = blocks
    picks = []
    for note in notes or []:
        for item in note.get("open_items", [])[:2]:
            picks.append({"note": note["title"], "item": item, "when": "빈 블록 15분"})
    if picks:
        brief["keep_picks"] = picks[:3]
    rotation = brief.pop("rotation", {})
    for key, pool in rotation.items():
        if pool:
            pick = pool[i % len(pool)]
            if key == "choice":
                brief["three_lines"]["choice"] = pick
            else:
                brief[key] = pick
    return brief


def ensure_calendar_blocks(plan: list[dict], todays: list[dict]) -> list[dict]:
    """모델이 캘린더 약속을 빠뜨려도, 실제 약속은 흐름에서 사라지지 않게."""
    have = {(b.get("time"), (b.get("title") or "")[:6]) for b in plan}
    for e in todays:
        if not any(b.get("time") == e["start"] and b.get("source") == "calendar" for b in plan) and \
                (e["start"], e["title"][:6]) not in have:
            plan.append({"time": e["start"], "end": e["end"], "title": e["title"], "tag": guess_tag(e["title"]),
                         "detail": e["location"], "source": "calendar"})
    return sorted(plan, key=lambda b: (b.get("time") or "99"))


def chapter_chars(brief: dict) -> int:
    return sum(len(c.get("body_md", "")) for c in brief.get("chapters", []))


# ---------------------------------------------------------------- render & open

def render(brief: dict, out_path: Path) -> None:
    html = TEMPLATE.read_text(encoding="utf-8")
    payload = json.dumps(brief, ensure_ascii=False).replace("</", "<\\/")
    html = html.replace('"__BRIEF_DATA__"', payload, 1)
    out_path.write_text(html, encoding="utf-8")


def find_app_browser() -> str | None:
    candidates = []
    if sys.platform.startswith("win"):
        for base in (os.environ.get("PROGRAMFILES(X86)", ""), os.environ.get("PROGRAMFILES", ""), os.environ.get("LOCALAPPDATA", "")):
            candidates += [os.path.join(base, "Microsoft", "Edge", "Application", "msedge.exe"),
                           os.path.join(base, "Google", "Chrome", "Application", "chrome.exe")]
    elif sys.platform == "darwin":
        candidates += ["/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
                       "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge"]
    else:
        candidates += [shutil.which(n) or "" for n in ("google-chrome", "chromium", "chromium-browser", "microsoft-edge")]
    return next((c for c in candidates if c and os.path.exists(c)), None)


def open_window(path: Path, mode: str) -> None:
    url = path.resolve().as_uri()
    if mode == "app":
        exe = find_app_browser()
        if exe:
            subprocess.Popen([exe, f"--app={url}", "--window-size=1280,900"],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return
    webbrowser.open(url)


# ---------------------------------------------------------------- main

def acquire_lock(lock: Path, stale_after: int) -> bool:
    if lock.exists() and time.time() - lock.stat().st_mtime < stale_after:
        return False
    lock.write_text(str(os.getpid()), encoding="utf-8")
    return True


def diagnose(cfg: dict) -> int:
    """설치가 안 될 때 원인을 한눈에 보여준다."""
    hist = cfg["history"]
    projects = expand(hist["claude_code_projects_dir"])
    sessions = glob.glob(str(projects / "*" / "*.jsonl"))
    rows = [
        ("Python", f"{sys.version.split()[0]} · {sys.executable}"),
        ("도구 폴더", str(HERE)),
        ("template.html", "있음" if TEMPLATE.exists() else "없음 — 압축을 다시 풀어 주세요"),
        ("config.json", "있음" if (HERE / "config.json").exists() else "없음"),
        ("claude CLI", find_claude() or "찾지 못함 → 오프라인 조언으로 열립니다"),
        ("ANTHROPIC_API_KEY", "설정됨" if os.environ.get("ANTHROPIC_API_KEY") else "없음"),
        ("Claude Code 기록", f"{projects} · 세션 파일 {len(sessions)}개"),
        ("앱 창 브라우저", find_app_browser() or "찾지 못함 → 기본 브라우저 탭으로 엽니다"),
        ("데이터 폴더", str(expand(cfg.get("data_dir", "~/OnMoment/morning")))),
    ]
    cal_cfg = cfg.get("calendar") or {}
    urls = [u for u in cal_cfg.get("ics_urls") or [] if (u.get("url") if isinstance(u, dict) else u)]
    if urls:
        try:
            cal = collect_calendar(cal_cfg, expand(cfg.get("data_dir", "~/OnMoment/morning")) / "calendar_cache",
                                   dt.date.today(), log=lambda m: None)
            rows.append(("구글 캘린더", f"{len(urls)}개 연결 · 오늘 {len(cal['today'])}건 · 7일 {len(cal['week'])}건"
                                     + (f" · {cal['note']}" if cal["note"] else "")))
        except Exception as e:
            rows.append(("구글 캘린더", f"읽기 실패: {e}"))
    else:
        rows.append(("구글 캘린더", "연결 안 됨 → config.json 의 calendar.ics_urls 에 비공개 iCal 주소"))
    keep_dirs = [d for k in ("dirs", "note_dirs") for d in (cfg.get("keep") or {}).get(k) or []]
    notes = collect_notes(cfg.get("keep") or {}, log=lambda m: None) if keep_dirs else []
    rows.append(("Keep · 메모", f"{len(notes)}개 읽음 ({', '.join(keep_dirs)})" if keep_dirs else "폴더 없음 → config.json 의 keep.dirs"))
    data_dir = expand(cfg.get("data_dir", "~/OnMoment/morning"))
    lock = data_dir / ".lock"
    if lock.exists():
        age = int(time.time() - lock.stat().st_mtime)
        rows.append(("생성 작업", f"진행 중 표시 있음 ({age}초 전 시작). 멈춘 것 같으면 다시만들기.bat"))
    today_html = data_dir / "briefs" / f"{dt.date.today().isoformat()}.html"
    rows.append(("오늘 조언", "완성됨" if today_html.exists() else "아직 없음"))
    for k, v in rows:
        print(f"{k:<18} {v}")
    if find_claude():
        print("claude 응답 시험      (최대 90초)...", flush=True)
        try:
            t = time.time()
            reply = run_claude_cli("다른 말 없이 OK 라고만 답하세요.", cfg.get("claude_cli_model", ""), 90)
            print(f"claude 응답          정상 ({time.time() - t:.0f}초): {reply.strip()[:60]}")
        except subprocess.TimeoutExpired:
            print("claude 응답          90초 안에 답이 없음 → 터미널에서 claude 를 한 번 실행해 로그인/첫 설정을 마쳐 주세요")
        except Exception as e:
            print(f"claude 응답          실패: {e}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="온순간 아침 창")
    ap.add_argument("--diagnose", action="store_true", help="설치 상태 점검")
    ap.add_argument("--force", action="store_true", help="오늘 조언을 새로 생성")
    ap.add_argument("--offline", action="store_true", help="LLM 없이 내장 조언 사용")
    ap.add_argument("--no-open", action="store_true", help="창을 띄우지 않음")
    ap.add_argument("--render", metavar="JSON", help="주어진 brief JSON으로 렌더만")
    ap.add_argument("--out", metavar="HTML", help="--render 출력 경로")
    args = ap.parse_args()

    cfg = load_config()
    if args.diagnose:
        return diagnose(cfg)
    data_dir = expand(cfg.get("data_dir", "~/OnMoment/morning"))
    briefs_dir = data_dir / "briefs"
    (data_dir / "returns").mkdir(parents=True, exist_ok=True)
    briefs_dir.mkdir(parents=True, exist_ok=True)

    today = dt.date.today()
    today_html = briefs_dir / f"{today.isoformat()}.html"
    today_json = briefs_dir / f"{today.isoformat()}.json"
    window = data_dir / "today.html"
    mode = cfg.get("window_mode", "app")
    hist = cfg["history"]

    # 통계는 렌더 전용 모드에서도 실제 기록으로 채운다
    cc_msgs, stats = collect_claude_code(expand(hist["claude_code_projects_dir"]), hist["recent_days"], hist["stats_days"])
    ai_msgs = collect_claude_ai(hist.get("claude_ai_export", ""), hist["recent_days"])
    stats["messages_claude_ai"] = len(ai_msgs)
    milestones = milestones_with_dday(cfg.get("milestones", []), today)
    radar_state = {"radar": fallback_radar(today)}
    life = {"cal": {"today": [], "background": [], "week": [], "source": "none", "note": ""}, "notes": [], "plan": None}

    def load_life() -> None:
        """구글 캘린더 · Keep · 메모를 읽고, 리듬과 캘린더를 합친 오늘의 흐름 초안을 만든다."""
        try:
            life["cal"] = collect_calendar(cfg.get("calendar") or {}, data_dir / "calendar_cache", today,
                                           log=lambda m: log(data_dir, m))
        except Exception as e:
            log(data_dir, f"캘린더 읽기 실패: {e}")
            life["cal"]["note"] = f"캘린더 읽기 실패: {e}"[:200]
        try:
            life["notes"] = collect_notes(cfg.get("keep") or {}, log=lambda m: log(data_dir, m))
        except Exception as e:
            log(data_dir, f"메모 읽기 실패: {e}")
        life["plan"] = merge_plan(today_rhythm(cfg, today), life["cal"]["today"])

    def finish(brief: dict, source: str, target: Path) -> None:
        brief.setdefault("meta", {})
        brief["meta"].update({"source": source, "generated_at": dt.datetime.now().isoformat(timespec="minutes"),
                              "chapter_chars": chapter_chars(brief)})
        brief.update({"date": today.isoformat(), "weekday": WEEKDAYS[today.weekday()], "name": cfg.get("name", "범"),
                      "stats": stats, "milestones": milestones})
        brief.setdefault("radar", radar_state["radar"])
        cal = life["cal"]
        brief.setdefault("calendar", {"background": cal["background"], "week": cal["week"][:12],
                                      "source": cal["source"], "note": cal["note"], "notes_count": len(life["notes"])})
        render(brief, target)

    if args.render:
        with open(args.render, encoding="utf-8") as f:
            brief = json.load(f)
        brief.pop("rotation", None)
        brief.setdefault("day_plan", today_rhythm(cfg, today))
        out = Path(args.out) if args.out else window
        finish(brief, brief.get("meta", {}).get("source", "manual"), out)
        print(f"렌더 완료: {out}")
        if not args.no_open:
            open_window(out, mode)
        return 0

    if today_html.exists() and not args.force:
        shutil.copy(today_html, window)
        if not args.no_open:
            open_window(window, mode)
        log(data_dir, "오늘 조언이 이미 있어 창만 열었습니다")
        return 0

    timeout = int(cfg.get("claude_timeout_sec", 420))
    radar_cfg = cfg.get("radar") or {}
    radar_timeout = int(radar_cfg.get("timeout_sec", 480))
    lock = data_dir / ".lock"
    if not acquire_lock(lock, max(timeout, radar_timeout) + 120):
        log(data_dir, "다른 생성 작업이 진행 중입니다")
        if not args.no_open and window.exists():
            open_window(window, mode)
        return 0

    def show_offline(pending: bool, note: str = "") -> dict:
        """창이 절대 빈 대기 화면에 갇히지 않도록, 내장 조언을 먼저 그려 둔다."""
        brief = offline_brief(today, cfg, life["plan"], life["notes"])
        brief["meta"] = {"pending": pending, "note": note, "timeout": max(timeout, radar_timeout)}
        finish(brief, "offline", window)
        return brief

    brief, source, notes = None, "offline", []
    try:
        load_life()
        if not args.no_open and not args.offline:
            show_offline(pending=True)
            open_window(window, mode)

        # 레이더(웹 검색)는 조언 생성과 동시에 돈다
        import threading

        def radar_job() -> None:
            try:
                radar_state["radar"] = run_radar(cfg, today)
                log(data_dir, "레이더 검색 완료")
            except subprocess.TimeoutExpired:
                radar_state["radar"] = fallback_radar(today, f"검색이 {radar_timeout}초 안에 끝나지 않았습니다")
                log(data_dir, "레이더 검색 시간 초과")
            except Exception as e:
                radar_state["radar"] = fallback_radar(today, f"검색 실패: {e}"[:200])
                log(data_dir, f"레이더 검색 실패: {e}")

        radar_thread = None
        if radar_cfg.get("enabled", True) and not args.offline and find_claude():
            radar_thread = threading.Thread(target=radar_job, daemon=True)
            radar_thread.start()

        memory_path = data_dir / "memory.md"
        memory = memory_path.read_text(encoding="utf-8")[-6000:] if memory_path.exists() else ""
        yesterday = briefs_dir / f"{(today - dt.timedelta(days=1)).isoformat()}.json"
        yesterday_choice = ""
        if yesterday.exists():
            try:
                yesterday_choice = json.loads(yesterday.read_text(encoding="utf-8"))["three_lines"]["choice"]
            except (KeyError, json.JSONDecodeError):
                pass

        prompt = build_prompt(
            cfg, today,
            context=collect_context(cfg.get("context_dirs", ["./context"])),
            milestones=milestones, memory=memory, yesterday_choice=yesterday_choice,
            returns=collect_returns(cfg.get("journal_dirs", [])), stats=stats,
            history=digest_messages(cc_msgs + ai_msgs, hist["max_history_chars"]),
            calendar=calendar_text(life["cal"], today) if life["cal"]["source"] != "none" else "",
            plan=life["plan"], notes=notes_text(life["notes"]),
        )

        engine = "offline" if args.offline else cfg.get("engine", "auto")
        order = ["claude-cli", "api"] if engine == "auto" else [] if engine == "offline" else [engine]
        if engine == "auto" and not api_available():
            order.remove("api")  # API 키나 SDK가 없으면 조용히 건너뛴다
        for name in order:
            try:
                if name == "claude-cli":
                    brief = parse_brief(run_claude_cli(prompt, cfg.get("claude_cli_model", ""), timeout))
                elif name == "api":
                    brief = parse_brief(run_api(prompt, cfg.get("api_model", "claude-opus-5")))
                brief["day_plan"] = ensure_calendar_blocks(list(brief.get("day_plan") or []), life["cal"]["today"])
                source = name
                break
            except subprocess.TimeoutExpired:
                notes.append(f"{name}: {timeout}초 안에 끝나지 않음")
                log(data_dir, f"{name} 엔진 시간 초과 ({timeout}초)")
            except Exception as e:  # 다음 엔진으로 넘어간다
                notes.append(f"{name}: {e}")
                log(data_dir, f"{name} 엔진 실패: {e}")

        if radar_thread is not None:
            radar_thread.join(radar_timeout + 30)
        if brief is None:
            brief = offline_brief(today, cfg, life["plan"], life["notes"])
            brief["meta"] = {"note": " / ".join(notes)[:400] if notes else ""}
        if source == "offline" and not args.offline:
            # Claude 연결이 안 된 날은 '완성본'으로 저장하지 않아, 다음 실행(로그인 등)에서 다시 시도한다
            finish(brief, source, window)
            log(data_dir, "Claude 조언을 받지 못해 내장 조언을 보여주었습니다 (다음 실행 때 다시 시도)")
            return 0
        finish(brief, source, today_html)
        brief["radar"] = radar_state["radar"]
        today_json.write_text(json.dumps(brief, ensure_ascii=False, indent=2), encoding="utf-8")
        shutil.copy(today_html, window)
        log(data_dir, f"생성 완료 ({source}, 본문 {chapter_chars(brief):,}자)")

        if brief.get("memory_update") and source != "offline":
            with open(memory_path, "a", encoding="utf-8") as f:
                f.write(f"\n## {today.isoformat()}\n" + "\n".join(f"- {m}" for m in brief["memory_update"]) + "\n")

        if args.no_open:
            print(today_html)
        return 0
    except BaseException as e:
        # 어떤 이유로든 중단되면 '쓰는 중' 표시를 거두고, 무엇이 문제인지 창에 남긴다
        if brief is None or source == "offline":
            try:
                show_offline(pending=False, note=f"생성 중 오류: {type(e).__name__}: {e}"[:400])
            except Exception:
                pass
        raise
    finally:
        lock.unlink(missing_ok=True)


if __name__ == "__main__":
    for stream in (sys.stdout, sys.stderr):  # Windows 콘솔(cp949)에서도 한글 출력이 깨지지 않게
        if stream is not None and hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    try:
        sys.exit(main())
    except Exception:  # pythonw로 실행되면 에러가 화면에 안 보이므로 로그에 남긴다
        import traceback

        crash_dir = Path.home() / "OnMoment" / "morning"
        crash_dir.mkdir(parents=True, exist_ok=True)
        with open(crash_dir / "morning.log", "a", encoding="utf-8") as f:
            f.write(f"[{dt.datetime.now():%Y-%m-%d %H:%M:%S}] 실행 오류\n{traceback.format_exc()}\n")
        raise
