"""범님의 실제 하루를 읽는 곳: 구글 캘린더(iCal 주소) · 구글 Keep(Takeout) · 메모 폴더.

표준 라이브러리만 사용한다.

- 구글 캘린더: 캘린더 설정 → '비공개 주소(iCal 형식)'를 config.json 의 calendar.ics_urls 에 붙여 넣는다.
  반복 일정(RRULE), 제외 날짜(EXDATE), 한 번만 바뀐 반복 일정(RECURRENCE-ID)을 처리한다.
  마지막으로 받은 파일을 보관해 두어, 인터넷이 안 되는 아침에도 어제 받은 일정으로 코칭한다.
- 구글 Keep: 개인용 공개 API가 없다. Google Takeout 으로 받은 Keep 폴더(또는 takeout-*.zip)를 읽는다.
- 메모 폴더: .md / .txt (옵시디언 등). 체크 안 된 "- [ ]" 항목을 할 일로 본다.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import re
import zipfile
from pathlib import Path

WEEKDAY_CODES = ["MO", "TU", "WE", "TH", "FR", "SA", "SU"]


# ---------------------------------------------------------------- ICS 읽기

def _unfold(text: str) -> list[str]:
    lines: list[str] = []
    for raw in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if raw.startswith((" ", "\t")) and lines:
            lines[-1] += raw[1:]
        elif raw:
            lines.append(raw)
    return lines


def _unescape(v: str) -> str:
    return v.replace("\\n", " ").replace("\\N", " ").replace("\\,", ",").replace("\\;", ";").replace("\\\\", "\\").strip()


def _split_prop(line: str) -> tuple[str, dict, str]:
    # NAME;PARAM=a;PARAM2="b:c":VALUE  (따옴표 안의 콜론은 값의 시작이 아니다)
    in_q, cut = False, -1
    for i, ch in enumerate(line):
        if ch == '"':
            in_q = not in_q
        elif ch == ":" and not in_q:
            cut = i
            break
    if cut < 0:
        return line.upper(), {}, ""
    head, value = line[:cut], line[cut + 1 :]
    parts = head.split(";")
    params = {}
    for p in parts[1:]:
        if "=" in p:
            k, v = p.split("=", 1)
            params[k.upper()] = v.strip('"')
    return parts[0].upper(), params, value


def _to_local(value: str, params: dict) -> tuple[dt.datetime, bool]:
    """(현지 시각, 종일 여부). 시간대가 있으면 이 컴퓨터의 현지 시각으로 바꾼다."""
    value = value.strip()
    if params.get("VALUE") == "DATE" or re.fullmatch(r"\d{8}", value):
        return dt.datetime.strptime(value[:8], "%Y%m%d"), True
    utc = value.endswith("Z")
    stamp = dt.datetime.strptime(value.rstrip("Z")[:15], "%Y%m%dT%H%M%S")
    if utc:
        return stamp.replace(tzinfo=dt.timezone.utc).astimezone().replace(tzinfo=None), False
    tzid = params.get("TZID")
    if tzid:
        try:
            from zoneinfo import ZoneInfo

            return stamp.replace(tzinfo=ZoneInfo(tzid)).astimezone().replace(tzinfo=None), False
        except Exception:  # Windows에 tzdata가 없으면 적힌 시각을 그대로 쓴다 (한국 일정은 대부분 그대로 맞다)
            pass
    return stamp, False


def _parse_rrule(v: str) -> dict:
    rule = {}
    for part in v.split(";"):
        if "=" in part:
            k, val = part.split("=", 1)
            rule[k.upper()] = val
    return rule


def _byday(rule: dict) -> list[tuple[int | None, int]]:
    out = []
    for tok in filter(None, rule.get("BYDAY", "").split(",")):
        m = re.fullmatch(r"([+-]?\d+)?(MO|TU|WE|TH|FR|SA|SU)", tok.strip().upper())
        if m:
            out.append((int(m.group(1)) if m.group(1) else None, WEEKDAY_CODES.index(m.group(2))))
    return out


def _nth_weekday_match(d: dt.date, n: int, wd: int) -> bool:
    if d.weekday() != wd:
        return False
    if n > 0:
        return (d.day - 1) // 7 + 1 == n
    nxt = (d.replace(day=28) + dt.timedelta(days=4))
    last = nxt - dt.timedelta(days=nxt.day)
    return (last.day - d.day) // 7 + 1 == -n


def _matches(rule: dict, start: dt.date, d: dt.date) -> bool:
    freq = rule.get("FREQ", "")
    interval = max(1, int(rule.get("INTERVAL", "1") or 1))
    byday = _byday(rule)
    bymonth = [int(x) for x in rule.get("BYMONTH", "").split(",") if x.strip().lstrip("-").isdigit()]
    bymday = [int(x) for x in rule.get("BYMONTHDAY", "").split(",") if x.strip().lstrip("-").isdigit()]
    if bymonth and d.month not in bymonth:
        return False
    if freq == "DAILY":
        if (d - start).days % interval:
            return False
        return not byday or d.weekday() in [w for _, w in byday]
    if freq == "WEEKLY":
        week0 = start - dt.timedelta(days=start.weekday())
        if ((d - week0).days // 7) % interval:
            return False
        days = [w for _, w in byday] or [start.weekday()]
        return d.weekday() in days
    if freq == "MONTHLY":
        if ((d.year - start.year) * 12 + d.month - start.month) % interval:
            return False
        if bymday:
            nxt = (d.replace(day=28) + dt.timedelta(days=4))
            last = (nxt - dt.timedelta(days=nxt.day)).day
            return any(d.day == (x if x > 0 else last + 1 + x) for x in bymday)
        if byday:
            return any(_nth_weekday_match(d, n, w) if n else d.weekday() == w for n, w in byday)
        return d.day == start.day
    if freq == "YEARLY":
        if (d.year - start.year) % interval:
            return False
        if byday and bymonth:
            return any(_nth_weekday_match(d, n, w) if n else d.weekday() == w for n, w in byday)
        return (d.month, d.day) == (start.month, start.day)
    return False


def _occurrences(ev: dict, win_start: dt.date, win_end: dt.date) -> list[dt.datetime]:
    start: dt.datetime = ev["start"]
    span = ev["end"] - start
    rule = ev.get("rrule")
    if not rule:
        return [start] if start.date() <= win_end and (start + span).date() >= win_start else []
    until = None
    if rule.get("UNTIL"):
        try:
            until, _ = _to_local(rule["UNTIL"], {})
        except ValueError:
            pass
    count = int(rule["COUNT"]) if rule.get("COUNT", "").isdigit() else None
    # COUNT가 없으면 창 가까이에서부터 센다 (간격 계산은 시작일 기준이라 결과는 같다)
    d = start.date() if count else max(start.date(), win_start - dt.timedelta(days=span.days + 1))
    d = max(d, start.date())
    out, n, guard = [], 0, 0
    while d <= win_end and guard < 40000:
        guard += 1
        if _matches(rule, start.date(), d):
            occ = dt.datetime.combine(d, start.time())
            if until and occ > until + dt.timedelta(days=1 if ev["all_day"] else 0):
                break
            n += 1
            if count and n > count:
                break
            if occ not in ev["exdates"] and occ.date() not in ev["exdays"] and (occ + span).date() >= win_start:
                out.append(occ)
        d += dt.timedelta(days=1)
    return out


def parse_ics(text: str, label: str, win_start: dt.date, win_end: dt.date) -> list[dict]:
    events, overrides, cur = [], [], None
    for line in _unfold(text):
        if line == "BEGIN:VEVENT":
            cur = {"exdates": set(), "exdays": set(), "rrule": None, "title": "", "location": "", "status": ""}
            continue
        if line == "END:VEVENT":
            if cur and "start" in cur and cur.get("status") != "CANCELLED":
                if "end" not in cur:
                    cur["end"] = cur["start"] + (dt.timedelta(days=1) if cur["all_day"] else dt.timedelta(hours=1))
                (overrides if "recurrence_id" in cur else events).append(cur)
            cur = None
            continue
        if cur is None:
            continue
        name, params, value = _split_prop(line)
        try:
            if name == "DTSTART":
                cur["start"], cur["all_day"] = _to_local(value, params)
            elif name == "DTEND":
                cur["end"], _ = _to_local(value, params)
            elif name == "DURATION":
                m = re.fullmatch(r"P(?:(\d+)W)?(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?)?", value.strip())
                if m and "start" in cur:
                    w, d_, h, mi, s = (int(x or 0) for x in m.groups())
                    cur["end"] = cur["start"] + dt.timedelta(weeks=w, days=d_, hours=h, minutes=mi, seconds=s)
            elif name == "SUMMARY":
                cur["title"] = _unescape(value)
            elif name == "LOCATION":
                cur["location"] = _unescape(value)
            elif name == "STATUS":
                cur["status"] = value.strip().upper()
            elif name == "UID":
                cur["uid"] = value.strip()
            elif name == "RRULE":
                cur["rrule"] = _parse_rrule(value)
            elif name == "EXDATE":
                for v in value.split(","):
                    x, all_day = _to_local(v, params)
                    (cur["exdays"].add(x.date()) if all_day else cur["exdates"].add(x))
            elif name == "RECURRENCE-ID":
                cur["recurrence_id"], _ = _to_local(value, params)
        except ValueError:
            continue

    moved = {}
    for o in overrides:
        moved.setdefault(o.get("uid"), set()).add(o["recurrence_id"])
    out = []
    for ev in events + overrides:
        skip = moved.get(ev.get("uid"), set()) if "recurrence_id" not in ev and ev.get("rrule") else set()
        for occ in _occurrences(ev if "recurrence_id" not in ev else {**ev, "rrule": None}, win_start, win_end):
            if occ in skip:
                continue
            end = occ + (ev["end"] - ev["start"])
            out.append(_event_dict(ev, occ, end, label))
    out.sort(key=lambda e: (e["date"], not e["all_day"], e["start"] or ""))
    return out


def _event_dict(ev: dict, occ: dt.datetime, end: dt.datetime, label: str) -> dict:
    if ev["all_day"]:
        last = (end - dt.timedelta(days=1)).date()
        return {"date": occ.date().isoformat(), "last": max(last, occ.date()).isoformat(), "start": None, "end": None,
                "all_day": True, "title": ev["title"] or "(제목 없음)", "location": ev["location"], "calendar": label}
    return {"date": occ.date().isoformat(), "last": end.date().isoformat(), "hours": (end - occ).total_seconds() / 3600,
            "start": occ.strftime("%H:%M"),
            "end": end.strftime("%H:%M"), "all_day": False, "title": ev["title"] or "(제목 없음)",
            "location": ev["location"], "calendar": label}


def collect_calendar(cal_cfg: dict, cache_dir: Path, today: dt.date, log=print) -> dict:
    """{'today': [...], 'background': [...], 'week': [...], 'source': 'live|cache|none', 'note': str}"""
    from urllib.request import Request, urlopen

    days = int(cal_cfg.get("days_ahead", 7))
    win_end = today + dt.timedelta(days=days)
    timeout = int(cal_cfg.get("timeout_sec", 20))
    sources = [s for s in cal_cfg.get("ics_urls") or [] if (s.get("url") if isinstance(s, dict) else s)]
    events, notes, used_cache = [], [], False
    cache_dir.mkdir(parents=True, exist_ok=True)
    for i, src in enumerate(sources):
        url = src["url"] if isinstance(src, dict) else src
        label = (src.get("name") if isinstance(src, dict) else "") or f"캘린더{i + 1}"
        cache = cache_dir / (hashlib.sha1(url.encode()).hexdigest()[:12] + ".ics")
        text = ""
        try:
            if url.startswith(("http://", "https://", "webcal://")):
                req = Request(url.replace("webcal://", "https://", 1), headers={"User-Agent": "onmoment-morning"})
                with urlopen(req, timeout=timeout) as r:
                    text = r.read().decode("utf-8", errors="replace")
                if "BEGIN:VCALENDAR" not in text:
                    raise ValueError("iCal 형식이 아닙니다 (비공개 주소인지 확인)")
                cache.write_text(text, encoding="utf-8")
            else:
                text = Path(os.path.expanduser(url)).read_text(encoding="utf-8", errors="replace")
        except Exception as e:
            if cache.exists():
                text, used_cache = cache.read_text(encoding="utf-8"), True
                notes.append(f"{label}: 새로 받지 못해 지난번 일정 사용 ({type(e).__name__})")
            else:
                notes.append(f"{label}: 읽지 못함 ({e})"[:160])
            log(f"캘린더 '{label}' 읽기 실패: {e}")
        if text:
            try:
                events += parse_ics(text, label, today, win_end)
            except Exception as e:
                notes.append(f"{label}: 해석 실패 ({e})"[:160])
    iso = today.isoformat()
    # 20시간이 넘는 시간 일정(예: 9/21 08:00 ~ 9/30 09:00 프로젝트 기간)은 종일 일정처럼 '배경'으로 본다
    for e in events:
        if not e["all_day"] and e.get("hours", 0) >= 20:
            e["all_day"], e["start"], e["end"] = True, None, None
    todays = [e for e in events if not e["all_day"] and e["date"] <= iso <= e["last"]]
    # 자정을 넘는 일정은 오늘 부분만
    for e in todays:
        if e["date"] < iso:
            e["start"] = "00:00"
        if e["last"] > iso:
            e["end"] = "23:59"
    background = [e for e in events if e["all_day"] and e["date"] <= iso <= e["last"]]
    week = [e for e in events if e["date"] > iso]
    # 매일·매주 반복되는 루틴(새벽 수영 등)은 '앞으로 7일'에서 빼서 큰 일정만 보이게
    counts: dict[str, int] = {}
    for e in events:
        counts[e["title"]] = counts.get(e["title"], 0) + 1
    week = [e for e in week if counts[e["title"]] < 3 or e["all_day"]]
    seen, dedup = set(), []  # 여러 캘린더에 같은 일정이 있을 때 한 번만
    for e in week:
        k = (e["date"], e["start"], e["title"])
        if k not in seen:
            seen.add(k)
            dedup.append(e)
    return {"today": sorted(todays, key=lambda e: e["start"]), "background": background, "week": dedup[:40],
            "source": "none" if not sources else "cache" if used_cache else "live", "note": " / ".join(notes)}


# ---------------------------------------------------------------- 오늘의 흐름 = 리듬 + 캘린더

def _min(t: str | None) -> int | None:
    m = re.match(r"^(\d{1,2}):(\d{2})", t or "")
    return int(m.group(1)) * 60 + int(m.group(2)) if m else None


TAG_WORDS = [
    ("build", ["온순간", "피칭", "베타", "코호트", "데이터", "창업", "미팅", "회의", "포럼", "IR", "멘토", "상담", "특허", "변리"]),
    ("life", ["예배", "성경", "BBB", "기도", "말씀", "수영", "러닝", "운동", "자전거", "등산", "헬스", "가정", "생일", "결혼", "가족"]),
    ("content", ["촬영", "여행", "축제", "박람회", "전시", "투어", "블로그", "유튜브", "글쓰기"]),
    ("claude", ["Claude", "AI", "코딩", "강의", "교육"]),
]


def guess_tag(title: str) -> str:
    for tag, words in TAG_WORDS:
        if any(w.lower() in title.lower() for w in words):
            return tag
    return "rest"


def merge_plan(rhythm: list[dict], todays: list[dict]) -> list[dict]:
    """캘린더 일정이 먼저. 겹치는 리듬 블록은 남겨 두되 무엇과 겹치는지 적는다."""
    plan = [dict(b, source="rhythm") for b in rhythm]
    for e in todays:
        s, en = _min(e["start"]), _min(e["end"])
        clash = [b for b in plan if b["source"] == "rhythm" and s is not None and _min(b["time"]) is not None
                 and s < (_min(b.get("end")) or _min(b["time"]) + 60) and (en or s + 60) > _min(b["time"])]
        for b in clash:
            b["overlap"] = (b.get("overlap", "") + " · " if b.get("overlap") else "") + f"{e['start']} {e['title']}"
        plan.append({"time": e["start"], "end": e["end"], "title": e["title"], "tag": guess_tag(e["title"]),
                     "detail": e["location"], "source": "calendar"})
    plan.sort(key=lambda b: (_min(b["time"]) or 0, b["source"] != "calendar"))
    return plan


def calendar_text(cal: dict, today: dt.date) -> str:
    def when(e):
        d = dt.date.fromisoformat(e["date"])
        day = f"{d.month}/{d.day}({'월화수목금토일'[d.weekday()]})"
        if e["all_day"]:
            return day + (f"~{e['last'][5:].replace('-', '/')}" if e["last"] != e["date"] else "") + " 종일"
        return f"{day} {e['start']}–{e['end']}"

    lines = ["[오늘 시간 일정]"] + [f"- {e['start']}–{e['end']} {e['title']}" + (f" @ {e['location']}" if e["location"] else "")
                                  for e in cal["today"]]
    if not cal["today"]:
        lines.append("- 없음")
    lines.append("[오늘의 배경 — 종일·여러 날 일정]")
    for e in cal["background"]:
        left = (dt.date.fromisoformat(e["last"]) - today).days
        lines.append(f"- {e['title']} ({e['date'][5:]}~{e['last'][5:]}, 남은 {left}일)")
    if not cal["background"]:
        lines.append("- 없음")
    lines.append("[앞으로 7일]")
    lines += [f"- {when(e)} {e['title']}" for e in cal["week"]] or ["- 없음"]
    if cal.get("note"):
        lines.append(f"(참고: {cal['note']})")
    return "\n".join(lines)


# ---------------------------------------------------------------- 구글 Keep · 메모

def _keep_json_notes(items) -> list[dict]:
    notes = []
    for name, raw in items:
        try:
            n = json.loads(raw)
        except (json.JSONDecodeError, UnicodeDecodeError):
            continue
        if not isinstance(n, dict) or n.get("isTrashed") or n.get("isArchived"):
            continue
        if "textContent" not in n and "listContent" not in n:
            continue
        open_items = [x.get("text", "").strip() for x in n.get("listContent") or [] if not x.get("isChecked") and x.get("text")]
        edited = n.get("userEditedTimestampUsec") or n.get("createdTimestampUsec") or 0
        notes.append({
            "title": (n.get("title") or "").strip() or ((n.get("textContent") or "").strip().split("\n")[0][:24]) or Path(name).stem,
            "text": (n.get("textContent") or "").strip(),
            "open_items": open_items,
            "pinned": bool(n.get("isPinned")),
            "labels": [lb.get("name", "") for lb in n.get("labels") or []],
            "edited": dt.datetime.fromtimestamp(int(edited) / 1e6).isoformat(timespec="minutes") if edited else "",
            "source": "keep",
        })
    return notes


def _keep_folders(base: Path) -> list[Path]:
    if base.name.lower() == "keep":
        return [base]
    return [p for p in [base / "Keep", base / "Takeout" / "Keep", *base.glob("*/Takeout/Keep")] if p.is_dir()]


def collect_notes(keep_cfg: dict, log=print) -> list[dict]:
    recent_days = int(keep_cfg.get("recent_days", 45))
    cutoff = (dt.datetime.now() - dt.timedelta(days=recent_days)).isoformat()
    notes: list[dict] = []
    expand = lambda d: Path(os.path.expandvars(os.path.expanduser(d)))  # noqa: E731
    for base in map(expand, keep_cfg.get("dirs") or []):
        if not base.is_dir():
            continue
        try:
            # Takeout 내보내기 중 가장 최근 것 하나: 압축을 푼 Keep 폴더 또는 takeout-*.zip
            found = [(p.stat().st_mtime, p) for p in _keep_folders(base) + list(base.glob("takeout-*.zip"))]
            if found:
                latest = max(found)[1]
                if latest.is_dir():
                    files = list(latest.glob("*.json"))[:5000]
                    notes += _keep_json_notes((p.name, p.read_text(encoding="utf-8", errors="ignore")) for p in files)
                else:
                    with zipfile.ZipFile(latest) as zf:
                        names = [n for n in zf.namelist() if "/Keep/" in n and n.endswith(".json")][:5000]
                        notes += _keep_json_notes((n, zf.read(n).decode("utf-8", errors="ignore")) for n in names)
        except (OSError, zipfile.BadZipFile) as e:
            log(f"Keep 읽기 실패 {base}: {e}")
    # 3) 일반 메모 폴더 (.md/.txt, 옵시디언 등) — 최근 고친 것만
    for base in map(expand, keep_cfg.get("note_dirs") or []):
        if not base.is_dir():
            continue
        try:
            for p in list(base.rglob("*.md"))[:3000] + list(base.rglob("*.txt"))[:1000]:
                if p.name.startswith("onmoment-return-"):
                    continue
                mtime = dt.datetime.fromtimestamp(p.stat().st_mtime)
                if mtime.isoformat() < cutoff:
                    continue
                text = p.read_text(encoding="utf-8", errors="ignore")
                open_items = re.findall(r"^\s*[-*]\s+\[ \]\s+(.+)$", text, flags=re.M)
                notes.append({"title": p.stem, "text": text.strip()[:1500], "open_items": open_items[:15],
                              "pinned": False, "labels": [], "edited": mtime.isoformat(timespec="minutes"), "source": "note"})
        except OSError as e:
            log(f"메모 폴더 읽기 실패 {base}: {e}")
    # 오래된 Keep 메모는 고정된 것만
    notes = [n for n in notes if n["pinned"] or n["edited"] >= cutoff]
    notes.sort(key=lambda n: n["edited"], reverse=True)
    notes.sort(key=lambda n: not n["pinned"])  # 안정 정렬: 고정 먼저, 그 안에서 최근 순
    seen, out = set(), []
    for n in notes:
        k = (n["title"], n["text"][:80])
        if k not in seen:
            seen.add(k)
            out.append(n)
    return out[: int(keep_cfg.get("max_notes", 15))]


def notes_text(notes: list[dict], budget: int = 6000) -> str:
    chunks, used = [], 0
    for n in notes:
        head = f"### {'📌 ' if n['pinned'] else ''}{n['title']} ({n['source']}, {n['edited'][:10]})"
        body = n["text"][:600]
        todo = "\n".join(f"- [ ] {x}" for x in n["open_items"][:10])
        chunk = "\n".join(x for x in (head, body, todo) if x)
        if used + len(chunk) > budget:
            break
        chunks.append(chunk)
        used += len(chunk)
    return "\n\n".join(chunks)
