#!/usr/bin/env python3
"""온순간 아침 창 (OnMoment Morning)

매일 아침 6시, 또는 컴퓨터에 로그인할 때 실행되어
- Claude Code 대화 기록(~/.claude/projects)과 claude.ai 내보내기(선택)
- context/ 폴더의 온순간 문서들
- 어제의 조언과 어젯밤 Return 기록
을 읽고, 오늘 하루를 위한 5,000자 이상의 조언 대시보드를 만들어 창으로 띄운다.

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
    if not cfg_path.exists():
        shutil.copy(HERE / "config.example.json", cfg_path)
    with open(cfg_path, encoding="utf-8") as f:
        return json.load(f)


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
  "greeting": "범님을 부르는 아침 인사 1~2문장 (요일·날씨 추측 금지, 어제/최근 대화의 구체적 장면 하나를 언급)",
  "one_line": "오늘의 한 문장 — 범님이 오늘 붙잡을 문장 (25자 안팎, 주장보다 고백의 톤)",
  "return_question": "어제의 선택/최근 약속에 대한 Return 질문 1개 (판정 말고 있는 그대로 묻기)",
  "three_lines": {
    "reality": "현재(A) — 대화에서 관찰된 지금의 사실 한 줄",
    "wish": "바람(B) — 범님이 스스로 말한 바라는 장면 한 줄 (범님의 말을 최대한 그대로)",
    "choice": "선택(Bridge) — 오늘 통제 가능한 작은 한 행동 한 줄"
  },
  "day_plan": [
    {"time": "06:00", "end": "06:30", "title": "블록 제목", "detail": "구체적으로 무엇을, 어떤 결과물까지", "tag": "life|build|content|claude|rest"}
  ],
  "build_focus": {"gate": "지금 통과하려는 게이트", "today_task": "오늘 이 게이트를 위해 할 단 하나", "metric": "오늘 끝났다고 말할 수 있는 기준"},
  "content_mission": {
    "question": "오늘 삶에서 품고 다닐 질문 하나 (콘텐츠 기획이 아니라 삶의 방향)",
    "shots": [{"key": "WHERE", "hint": "..."}, {"key": "MOVE", "hint": "..."}, {"key": "DETAIL", "hint": "..."}, {"key": "HUMAN", "hint": "..."}, {"key": "EVIDENCE", "hint": "..."}],
    "voice_memo": ["방금 무슨 일이 있었나?", "예상과 무엇이 달랐나?", "내게 뭐가 걸렸나?"],
    "episode_seed": "이번 주 에피소드 후보 한 줄 (시리즈명 포함)"
  },
  "chapters": [
    {
      "id": "life | build | content | claude | rhythm",
      "kicker": "짧은 머리말 (예: 01 · 온순간을 산다)",
      "title": "장 제목",
      "evidence": "이 조언의 근거가 된 범님의 실제 대화/기록 — 날짜와 함께 짧게 인용",
      "body_md": "본문 (마크다운: 문단, **굵게**, - 목록, > 인용, ### 소제목). 장당 1,100~1,600자",
      "actions": ["오늘 할 수 있는 구체 행동 3개"]
    }
  ],
  "claude_code": [
    {"title": "팁 제목", "why": "범님의 실제 사용 패턴에서 이 팁이 필요한 이유", "how": "적용 방법 2~4문장", "prompt": "그대로 복사해 Claude Code에 붙여넣을 프롬프트 또는 명령"}
  ],
  "watchouts": ["오늘 조심할 패턴 2~3개 (판결 말고 관찰)"],
  "evening": ["밤 3분 질문 3개"],
  "memory_update": ["내일의 나(조언 AI)를 위해 기억할 새 사실 2~5개 — 대화에서 확인된 것만"]
}"""

PROMPT = """당신은 김범(범님)의 아침 동반자다. 범님은 온순간(OnMoment)의 창업자이자 첫 번째 Storydoer다.
매일 아침 6시(또는 컴퓨터를 켤 때) 이 조언이 창으로 뜬다. 범님이 "진정 매순간 온순간을 살고 싶다"고 해서 만든 창이다.

오늘: {today} ({weekday}요일)

# 당신이 지켜야 할 온순간의 규칙 (범님이 직접 정한 것)
- AI is not the author of meaning. AI is the architect of attention. 의미와 선택은 범님이 한다.
- Concrete before abstract. Observation before interpretation. 판결·진단·"당신은 이런 사람" 금지.
- 가능성은 가설로, 최대 2개. 한 번에 하나의 tension만 전면에.
- Small controllable action. Reality before positivity. 억지 교훈·억지 긍정 금지.
- User words before AI words: 범님이 대화에서 쓴 표현을 최대한 그대로 되비춘다.
- 매일 콘텐츠를 만들지 않는다. 매일 온순간을 살고 증거만 남긴다. 생산량 압박 금지.
- 1인 창업자의 소진을 경계한다. 쉼·가족·신앙도 계획의 정식 블록이다.

# 입력 1 — 범님에 대한 문서 (프로필, North Star, 모두의창업, Creator OS)
{context}

# 입력 2 — 일정 게이트 (config.json, D-day는 오늘 기준)
{milestones}

# 입력 3 — 조언 AI의 누적 기억 (지난 아침들이 남긴 것)
{memory}

# 입력 4 — 어제의 조언에서 범님이 고른 선택 / 어젯밤 Return 기록
어제 조언의 선택: {yesterday_choice}
{returns}

# 입력 5 — Claude Code 사용 통계 (최근 {stats_days}일)
{stats}

# 입력 6 — 범님이 최근 Claude와 나눈 대화 (범님이 쓴 메시지만, 시간순)
{history}

# 과제
위 입력을 근거로, 오늘 하루를 위한 조언 대시보드 데이터를 만든다.
- chapters는 정확히 5개, 이 순서: life(온순간을 산다 — 자기·관계·신앙), build(온순간 비즈니스 빌드업 — 모두의창업 게이트), content(온순간 콘텐츠 실행 — Creator OS), claude(Claude Code를 더 잘 쓰는 법), rhythm(오늘의 리듬 — 에너지·쉼·가족).
- 5개 장의 body_md 합계는 반드시 한국어 6,000자 이상. 일반론 금지, 최근 대화에서 나온 구체적 장면·결정·고민을 짚을 것.
- 각 장의 evidence에는 실제 대화 근거를 날짜와 함께 인용. 근거가 없으면 "최근 대화에는 이 주제가 없었습니다"라고 솔직히 쓰고 문서 기반으로 조언.
- day_plan은 06:00부터 22:30까지 7~10개 블록. 깊은 일 블록(90분)은 오전에, 가족·쉼·밤 3분 Return 포함.
- claude_code는 4개. 통계(도구 사용·세션 길이·프로젝트)와 대화 내용에서 보이는 실제 병목에 맞춘 팁. 슬래시 명령, CLAUDE.md, 서브에이전트, plan mode, hooks, skills, headless(claude -p), worktree 등에서 지금 범님에게 가장 효과 큰 것.
- build_focus는 모두의창업 게이트 중 지금 가장 중요한 것 하나.
- memory_update에는 오늘 대화에서 새로 확인된 사실만 (추측 금지).

반드시 아래 스키마의 JSON 객체 하나만 출력한다. 코드블록·설명·머리말 없이 {{ 로 시작해 }} 로 끝낸다.
{schema}
"""


def build_prompt(cfg: dict, today: dt.date, context: str, milestones: list[dict], memory: str,
                 yesterday_choice: str, returns: str, stats: dict, history: str) -> str:
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
    )


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


def run_claude_cli(prompt: str, model: str) -> str:
    exe = find_claude()
    if not exe:
        raise RuntimeError("claude CLI를 찾지 못했습니다")
    cmd = [exe, "-p", "--output-format", "text"]
    if model:
        cmd += ["--model", model]
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)  # Windows에서 콘솔 창이 번쩍이지 않게
    proc = subprocess.run(cmd, input=prompt, capture_output=True, text=True, encoding="utf-8",
                          timeout=1200, cwd=str(HERE), creationflags=flags)
    if proc.returncode != 0 or not proc.stdout.strip():
        raise RuntimeError(f"claude CLI 실패: {proc.stderr.strip()[:300]}")
    return proc.stdout


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


def parse_brief(raw: str) -> dict:
    start, end = raw.find("{"), raw.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("JSON을 찾지 못했습니다")
    brief = json.loads(raw[start : end + 1])
    for key in ("one_line", "three_lines", "day_plan", "chapters"):
        if key not in brief:
            raise ValueError(f"'{key}' 항목이 없습니다")
    return brief


def offline_brief(today: dt.date) -> dict:
    """LLM 없이도 창이 비지 않도록, 내장 조언을 날짜별로 회전시킨다."""
    with open(FALLBACK, encoding="utf-8") as f:
        brief = json.load(f)
    rotation = brief.pop("rotation", {})
    i = today.toordinal()
    for key, pool in rotation.items():
        if pool:
            pick = pool[i % len(pool)]
            if key == "choice":
                brief["three_lines"]["choice"] = pick
            else:
                brief[key] = pick
    return brief


def chapter_chars(brief: dict) -> int:
    return sum(len(c.get("body_md", "")) for c in brief.get("chapters", []))


# ---------------------------------------------------------------- render & open

LOADING_HTML = """<!doctype html><html lang="ko"><head><meta charset="utf-8">
<meta http-equiv="refresh" content="6"><title>온순간 아침</title>
<style>body{{margin:0;height:100vh;display:grid;place-items:center;color:#1c2330;
background:linear-gradient(180deg,rgba(130,140,210,.22),rgba(240,160,95,.30)),#eef0ec;
font-family:"Apple SD Gothic Neo","Malgun Gothic",system-ui,sans-serif}}
@media (prefers-color-scheme:dark){{body{{color:#e8eaee;background:linear-gradient(180deg,rgba(70,80,160,.30),rgba(150,110,170,.18)),#0f131a}}}}
.sun{{width:72px;height:72px;border-radius:50%;margin:0 auto 28px;background:#e0892f;
animation:rise 3s ease-in-out infinite alternate}}@keyframes rise{{from{{transform:translateY(10px);opacity:.6}}to{{transform:none;opacity:1}}}}
p{{text-align:center;line-height:1.9;font-size:18px}}small{{opacity:.6;font-size:13px}}</style></head>
<body><div><div class="sun"></div><p>{name}님, 좋은 아침입니다.<br>어제까지의 대화를 읽으며 오늘의 창을 여는 중입니다.<br>
<small>숨 한 번 고르고 기다려 주세요 · 1~3분</small></p></div></body></html>"""


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

def acquire_lock(lock: Path) -> bool:
    if lock.exists() and time.time() - lock.stat().st_mtime < 1800:
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
    for k, v in rows:
        print(f"{k:<18} {v}")
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

    def finish(brief: dict, source: str, target: Path) -> None:
        brief.setdefault("meta", {})
        brief["meta"].update({"source": source, "generated_at": dt.datetime.now().isoformat(timespec="minutes"),
                              "chapter_chars": chapter_chars(brief)})
        brief.update({"date": today.isoformat(), "weekday": WEEKDAYS[today.weekday()], "name": cfg.get("name", "범"),
                      "stats": stats, "milestones": milestones})
        render(brief, target)

    if args.render:
        with open(args.render, encoding="utf-8") as f:
            brief = json.load(f)
        brief.pop("rotation", None)
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

    lock = data_dir / ".lock"
    if not acquire_lock(lock):
        log(data_dir, "다른 생성 작업이 진행 중입니다")
        if not args.no_open and window.exists():
            open_window(window, mode)
        return 0

    try:
        if not args.no_open:
            window.write_text(LOADING_HTML.format(name=cfg.get("name", "범")), encoding="utf-8")
            open_window(window, mode)

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
        )

        engine = "offline" if args.offline else cfg.get("engine", "auto")
        order = ["claude-cli", "api", "offline"] if engine == "auto" else [engine, "offline"]
        brief, source = None, "offline"
        for name in order:
            try:
                if name == "claude-cli":
                    brief = parse_brief(run_claude_cli(prompt, cfg.get("claude_cli_model", "")))
                elif name == "api":
                    brief = parse_brief(run_api(prompt, cfg.get("api_model", "claude-opus-5")))
                else:
                    brief = offline_brief(today)
                source = name
                break
            except Exception as e:  # 다음 엔진으로 넘어간다
                log(data_dir, f"{name} 엔진 실패: {e}")

        finish(brief, source, today_html)
        today_json.write_text(json.dumps(brief, ensure_ascii=False, indent=2), encoding="utf-8")
        shutil.copy(today_html, window)
        log(data_dir, f"생성 완료 ({source}, 본문 {chapter_chars(brief):,}자)")

        if brief.get("memory_update") and source != "offline":
            with open(memory_path, "a", encoding="utf-8") as f:
                f.write(f"\n## {today.isoformat()}\n" + "\n".join(f"- {m}" for m in brief["memory_update"]) + "\n")

        if args.no_open:
            print(today_html)
        return 0
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
