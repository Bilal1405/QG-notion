"""Accès Moodle : web services REST (jeton de l'appli mobile) et export calendrier iCal."""

from __future__ import annotations

import html
import re
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any

import requests
from icalendar import Calendar


class MoodleAuthError(RuntimeError):
    pass


class MoodleError(RuntimeError):
    pass


AUTH_ERRORS = {"invalidtoken", "accessexception", "servicenotavailable", "usernotfullysetup", "invalidlogin"}


class MoodleClient:
    def __init__(self, base_url: str, token: str, session: requests.Session | None = None):
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.session = session or requests.Session()

    def call(self, function: str, **params: Any) -> Any:
        data = {"wstoken": self.token, "wsfunction": function, "moodlewsrestformat": "json"}
        data.update(_flatten(params))
        for attempt in range(3):
            try:
                resp = self.session.post(f"{self.base_url}/webservice/rest/server.php", data=data, timeout=60)
            except requests.RequestException as exc:
                if attempt == 2:
                    raise MoodleError(f"{function} : réseau ({type(exc).__name__})") from exc
                time.sleep(2 ** attempt)
                continue
            if resp.status_code >= 500 and attempt < 2:
                time.sleep(2 ** attempt)
                continue
            break
        if resp.status_code >= 400:
            raise MoodleError(f"{function} → HTTP {resp.status_code}")
        payload = resp.json()
        if isinstance(payload, dict) and payload.get("exception"):
            code = payload.get("errorcode", "")
            if code in AUTH_ERRORS:
                raise MoodleAuthError(f"{function} → {code}")
            raise MoodleError(f"{function} → {code}")
        return payload

    def site_info(self) -> dict:
        return self.call("core_webservice_get_site_info")

    def courses(self, userid: int) -> list[dict]:
        return self.call("core_enrol_get_users_courses", userid=userid)

    def contents(self, courseid: int) -> list[dict]:
        return self.call("core_course_get_contents", courseid=courseid)

    def action_events(self, since: datetime) -> list[dict]:
        data = self.call(
            "core_calendar_get_action_events_by_timesort",
            timesortfrom=int(since.timestamp()),
            limitnum=50,
        )
        return data.get("events", [])

    def news_discussions(self, courseids: list[int], per_forum: int = 15) -> list[tuple[dict, dict]]:
        forums = self.call("mod_forum_get_forums_by_courses", courseids=courseids)
        result = []
        for forum in forums:
            if forum.get("type") != "news":
                continue
            try:
                data = self.call(
                    "mod_forum_get_forum_discussions", forumid=forum["id"], sortorder=-1, page=0, perpage=per_forum
                )
            except MoodleError:
                data = self.call(
                    "mod_forum_get_forum_discussions_paginated", forumid=forum["id"], page=0, perpage=per_forum
                )
            for disc in data.get("discussions", []):
                result.append((forum, disc))
        return result

    def grade_items(self, courseid: int, userid: int) -> list[dict]:
        data = self.call("gradereport_user_get_grade_items", courseid=courseid, userid=userid)
        usergrades = data.get("usergrades") or [{}]
        return usergrades[0].get("gradeitems", [])


def _flatten(params: dict, prefix: str = "") -> dict:
    """Aplatit les listes/dicts au format attendu par Moodle : courseids[0]=12."""
    flat = {}
    for key, value in params.items():
        name = f"{prefix}[{key}]" if prefix else key
        if isinstance(value, dict):
            flat.update(_flatten(value, name))
        elif isinstance(value, (list, tuple)):
            for i, item in enumerate(value):
                if isinstance(item, dict):
                    flat.update(_flatten(item, f"{name}[{i}]"))
                else:
                    flat[f"{name}[{i}]"] = item
        else:
            flat[name] = value
    return flat


# --- Conversion des données Moodle ------------------------------------------

EXT_TYPES = {
    "PDF": {"pdf"},
    "Document": {"doc", "docx", "odt", "rtf", "txt", "md", "tex"},
    "Présentation": {"ppt", "pptx", "odp", "key"},
    "Tableur": {"xls", "xlsx", "xlsm", "ods", "csv"},
    "Vidéo": {"mp4", "mov", "avi", "mkv", "webm"},
    "Image": {"png", "jpg", "jpeg", "gif", "svg", "bmp", "webp"},
    "Code": {"py", "ipynb", "m", "c", "cpp", "h", "java", "js", "mat", "sldprt", "sldasm", "slddrw", "step", "stp"},
    "Archive": {"zip", "rar", "7z", "tar", "gz"},
}

MODULE_TYPES = {
    "folder": "Dossier",
    "url": "Lien",
    "page": "Page",
    "book": "Page",
    "assign": "Devoir",
    "quiz": "Quiz",
}

SKIPPED_MODULES = {"label", "forum", "attendance", "choicegroup", "qbank"}


def type_from_filename(filename: str) -> str:
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    for kind, exts in EXT_TYPES.items():
        if ext in exts:
            return kind
    return "Autre"


def module_type(module: dict) -> str:
    modname = module.get("modname", "")
    if modname == "resource":
        files = module.get("contents") or []
        return type_from_filename(files[0].get("filename", "")) if files else "Autre"
    return MODULE_TYPES.get(modname, "Autre")


def module_modified(module: dict) -> datetime | None:
    stamps = [c.get("timemodified") for c in module.get("contents") or [] if c.get("timemodified")]
    info = module.get("contentsinfo") or {}
    if info.get("lastmodified"):
        stamps.append(info["lastmodified"])
    return datetime.fromtimestamp(max(stamps), tz=timezone.utc) if stamps else None


@dataclass
class Deadline:
    event_id: str
    name: str
    due: datetime | date
    course_id: int | None
    course_texts: tuple[str, ...]
    url: str


def deadline_from_action_event(event: dict) -> Deadline:
    course = event.get("course") or {}
    return Deadline(
        event_id=str(event["id"]),
        name=event.get("activityname") or event.get("name") or "Échéance Moodle",
        due=datetime.fromtimestamp(event.get("timesort") or event.get("timestart"), tz=timezone.utc),
        course_id=course.get("id"),
        course_texts=tuple(filter(None, (course.get("shortname"), course.get("fullname"), course.get("idnumber")))),
        url=event.get("url") or "",
    )


# Événements « X s'ouvre » / « X opens » : ce ne sont pas des échéances.
OPENING_RE = re.compile(r"(s['’]ouvre|\bopens\b)", re.IGNORECASE)


def deadlines_from_ics(ics_text: str, base_url: str, now: datetime, horizon_days: int = 150) -> list[Deadline]:
    cal = Calendar.from_ical(ics_text)
    start, end = now - timedelta(days=7), now + timedelta(days=horizon_days)
    result = []
    for comp in cal.walk("VEVENT"):
        summary = str(comp.get("SUMMARY") or "").strip()
        if not summary or OPENING_RE.search(summary):
            continue
        due = comp.decoded("DTSTART")
        due_cmp = due if isinstance(due, datetime) else datetime.combine(due, datetime.min.time(), tzinfo=timezone.utc)
        if due_cmp.tzinfo is None:
            due_cmp = due_cmp.replace(tzinfo=timezone.utc)
        if not (start <= due_cmp <= end):
            continue
        uid = str(comp.get("UID") or "")
        event_id = uid.split("@", 1)[0] or uid
        categories = comp.get("CATEGORIES")
        cats: list[str] = []
        for cat in categories if isinstance(categories, list) else [categories] if categories else []:
            cats.extend(str(c) for c in getattr(cat, "cats", [cat]))
        url = str(comp.get("URL") or "") or f"{base_url}/calendar/view.php?view=day&time={int(due_cmp.timestamp())}"
        result.append(
            Deadline(
                event_id=event_id,
                name=summary,
                due=due,
                course_id=None,
                course_texts=tuple(cats),
                url=url,
            )
        )
    return result


def html_to_text(value: str, limit: int = 600) -> str:
    text = re.sub(r"<(br|/p|/div|/li)[^>]*>", "\n", value or "", flags=re.IGNORECASE)
    text = html.unescape(re.sub(r"<[^>]+>", "", text))
    text = re.sub(r"\n\s*\n+", "\n", text).strip()
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"
