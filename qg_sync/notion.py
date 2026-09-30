"""Client minimal de l'API Notion (version data sources) et helpers de propriétés."""

from __future__ import annotations

import time
from datetime import date, datetime
from typing import Any, Iterable

import requests

from .config import NOTION_VERSION

API = "https://api.notion.com/v1"
MAX_TEXT = 2000


class NotionError(RuntimeError):
    pass


class NotionClient:
    def __init__(self, token: str, session: requests.Session | None = None, pause: float = 0.34):
        self.session = session or requests.Session()
        self.session.headers.update(
            {
                "Authorization": f"Bearer {token}",
                "Notion-Version": NOTION_VERSION,
                "Content-Type": "application/json",
            }
        )
        self.pause = pause  # l'API limite à ~3 requêtes/s

    def _request(self, method: str, path: str, body: dict | None = None) -> dict:
        for attempt in range(5):
            resp = self.session.request(method, f"{API}{path}", json=body, timeout=60)
            if resp.status_code == 429 or resp.status_code >= 500:
                time.sleep(float(resp.headers.get("Retry-After", 2 ** attempt)))
                continue
            if resp.status_code >= 400:
                try:
                    err = resp.json()
                    detail = f"{err.get('code')}: {str(err.get('message'))[:200]}"
                except ValueError:
                    detail = resp.text[:200]
                raise NotionError(f"Notion {method} {path.split('/')[1]} → {resp.status_code} {detail}")
            if self.pause:
                time.sleep(self.pause)
            return resp.json()
        raise NotionError(f"Notion {method} {path.split('/')[1]} : trop de tentatives")

    def query_all(self, data_source_id: str, filter: dict | None = None) -> list[dict]:
        pages, cursor = [], None
        while True:
            body: dict[str, Any] = {"page_size": 100}
            if cursor:
                body["start_cursor"] = cursor
            if filter:
                body["filter"] = filter
            data = self._request("POST", f"/data_sources/{data_source_id}/query", body)
            pages.extend(data.get("results", []))
            if not data.get("has_more"):
                return pages
            cursor = data.get("next_cursor")

    def create_page(self, data_source_id: str, properties: dict) -> dict:
        return self._request(
            "POST",
            "/pages",
            {"parent": {"type": "data_source_id", "data_source_id": data_source_id}, "properties": properties},
        )

    def update_page(self, page_id: str, properties: dict | None = None, in_trash: bool | None = None) -> dict:
        body: dict[str, Any] = {}
        if properties:
            body["properties"] = properties
        if in_trash is not None:
            body["in_trash"] = in_trash
        return self._request("PATCH", f"/pages/{page_id}", body)


# --- Écriture de propriétés -------------------------------------------------


def _rich(text: str) -> list[dict]:
    text = (text or "")[:MAX_TEXT]
    return [{"type": "text", "text": {"content": text}}] if text else []


def p_title(text: str) -> dict:
    return {"title": _rich(text or "(sans titre)")}


def p_text(text: str) -> dict:
    return {"rich_text": _rich(text)}


def p_url(url: str | None) -> dict:
    return {"url": url or None}


def p_select(name: str | None) -> dict:
    return {"select": {"name": name} if name else None}


def p_number(value: float | None) -> dict:
    return {"number": value}


def p_checkbox(value: bool) -> dict:
    return {"checkbox": bool(value)}


def p_relation(ids: Iterable[str]) -> dict:
    return {"relation": [{"id": i} for i in ids]}


def p_date(value: date | datetime | None) -> dict:
    if value is None:
        return {"date": None}
    return {"date": {"start": value.isoformat()}}


# --- Lecture de propriétés --------------------------------------------------


def read_plain(prop: dict | None) -> str:
    if not prop:
        return ""
    items = prop.get(prop.get("type", ""), [])
    if isinstance(items, list):
        return "".join(i.get("plain_text") or i.get("text", {}).get("content", "") for i in items)
    return ""


def read_value(prop: dict | None) -> Any:
    """Valeur normalisée d'une propriété Notion, comparable à celle produite par les helpers p_*."""
    if not prop:
        return None
    kind = prop.get("type") or next(iter(prop))
    val = prop.get(kind)
    if kind in ("title", "rich_text"):
        return "".join(i.get("plain_text") or i.get("text", {}).get("content", "") for i in val or [])
    if kind == "select":
        return (val or {}).get("name")
    if kind == "relation":
        return sorted(r["id"].replace("-", "") for r in val or [])
    if kind == "date":
        return _norm_date((val or {}).get("start"))
    if kind in ("url", "number", "checkbox"):
        return val
    return val


def _norm_date(value: str | None) -> Any:
    if not value:
        return None
    if len(value) == 10:
        return value
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return value


def same_props(page: dict, desired: dict) -> bool:
    existing = page.get("properties", {})
    for name, prop in desired.items():
        if read_value(existing.get(name)) != read_value(prop):
            return False
    return True
