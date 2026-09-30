"""Accès OneDrive via Microsoft Graph (jeton de rafraîchissement, droits en lecture seule)."""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass
from datetime import datetime
from urllib.parse import quote

import requests

GRAPH = "https://graph.microsoft.com/v1.0"
TOKEN_URL = "https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token"
SCOPES = "offline_access Files.Read User.Read"
SELECT = "id,name,webUrl,lastModifiedDateTime,file,folder,size"


class GraphAuthError(RuntimeError):
    pass


class GraphError(RuntimeError):
    pass


def refresh_access_token(
    client_id: str, refresh_token: str, tenant: str = "common", session: requests.Session | None = None
) -> tuple[str, str]:
    """Renvoie (access_token, nouveau refresh_token)."""
    session = session or requests.Session()
    resp = session.post(
        TOKEN_URL.format(tenant=tenant),
        data={
            "client_id": client_id,
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "scope": SCOPES,
        },
        timeout=60,
    )
    data = resp.json() if resp.content else {}
    if resp.status_code != 200 or "access_token" not in data:
        raise GraphAuthError(f"jeton refusé ({data.get('error', resp.status_code)})")
    return data["access_token"], data.get("refresh_token", refresh_token)


@dataclass
class DriveItem:
    id: str
    name: str
    web_url: str
    modified: datetime | None
    is_folder: bool
    parents: tuple[str, ...]  # noms des dossiers depuis la racine synchronisée


class GraphClient:
    def __init__(self, access_token: str, session: requests.Session | None = None):
        self.session = session or requests.Session()
        self.session.headers.update({"Authorization": f"Bearer {access_token}"})

    def _get(self, url: str, params: dict | None = None) -> dict:
        for attempt in range(5):
            resp = self.session.get(url, params=params, timeout=60)
            if resp.status_code in (429, 503, 504):
                time.sleep(float(resp.headers.get("Retry-After", 2 ** attempt)))
                continue
            if resp.status_code == 401:
                raise GraphAuthError("accès refusé (401)")
            if resp.status_code >= 400:
                code = (resp.json().get("error") or {}).get("code") if resp.content else ""
                raise GraphError(f"Graph → {resp.status_code} {code}")
            return resp.json()
        raise GraphError("Graph : trop de tentatives")

    def item_by_path(self, path: str) -> dict:
        if not path:
            return self._get(f"{GRAPH}/me/drive/root", {"$select": SELECT})
        return self._get(f"{GRAPH}/me/drive/root:/{quote(path, safe='/')}", {"$select": SELECT})

    def children(self, item_id: str) -> list[dict]:
        items, url, params = [], f"{GRAPH}/me/drive/items/{item_id}/children", {"$select": SELECT, "$top": 200}
        while url:
            data = self._get(url, params)
            items.extend(data.get("value", []))
            url, params = data.get("@odata.nextLink"), None
        return items

    def walk(self, root_path: str, max_depth: int = 8, max_items: int = 5000) -> tuple[DriveItem, list[DriveItem], bool]:
        """Parcours en largeur. Renvoie (racine, éléments, complet)."""
        root = self.item_by_path(root_path)
        found: list[DriveItem] = []
        queue = deque([(root["id"], ())])
        complete = True
        while queue:
            item_id, parents = queue.popleft()
            for raw in self.children(item_id):
                name = raw.get("name", "")
                if name.startswith(("~$", ".")):
                    continue
                item = DriveItem(
                    id=raw["id"],
                    name=name,
                    web_url=raw.get("webUrl", ""),
                    modified=_parse_dt(raw.get("lastModifiedDateTime")),
                    is_folder="folder" in raw,
                    parents=parents,
                )
                found.append(item)
                if len(found) >= max_items:
                    return _to_item(root), found, False
                if item.is_folder:
                    if len(parents) + 1 < max_depth:
                        queue.append((item.id, parents + (name,)))
                    else:
                        complete = False
        return _to_item(root), found, complete


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _to_item(raw: dict) -> DriveItem:
    return DriveItem(
        id=raw["id"],
        name=raw.get("name", ""),
        web_url=raw.get("webUrl", ""),
        modified=_parse_dt(raw.get("lastModifiedDateTime")),
        is_folder=True,
        parents=(),
    )
