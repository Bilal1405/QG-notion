from __future__ import annotations

import itertools
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from qg_sync.matching import CourseIndex  # noqa: E402
from qg_sync.notion import read_plain  # noqa: E402


def _page(page_id: str, props: dict) -> dict:
    """Page Notion telle que renvoyée par l'API, à partir de propriétés au format p_*."""
    out = {}
    for name, prop in props.items():
        kind = next(iter(prop))
        value = prop[kind]
        if kind in ("title", "rich_text"):
            value = [{**v, "plain_text": v["text"]["content"]} for v in value]
        out[name] = {"type": kind, kind: value}
    return {"id": page_id, "properties": out}


class FakeNotion:
    def __init__(self, pages: dict[str, list[dict]] | None = None):
        self.pages = pages or {}
        self.ids = (f"page-{i}" for i in itertools.count(1))
        self.created: list[tuple[str, dict]] = []
        self.updated: list[tuple[str, dict | None, bool | None]] = []

    def query_all(self, data_source_id, filter=None):
        pages = [p for p in self.pages.get(data_source_id, []) if not p.get("in_trash")]
        if filter:
            pages = [p for p in pages if read_plain(p["properties"].get(filter["property"]))]
        return pages

    def create_page(self, data_source_id, properties):
        page = _page(next(self.ids), properties)
        self.pages.setdefault(data_source_id, []).append(page)
        self.created.append((data_source_id, properties))
        return page

    def update_page(self, page_id, properties=None, in_trash=None):
        self.updated.append((page_id, properties, in_trash))
        for pages in self.pages.values():
            for page in pages:
                if page["id"] == page_id:
                    if properties:
                        page["properties"].update(_page(page_id, properties)["properties"])
                    if in_trash:
                        page["in_trash"] = True
        return {"id": page_id}


COURSE_PAGES = [
    {
        "id": "c-ma211",
        "properties": {
            "Matière": {"type": "title", "title": [{"plain_text": "Analyse : calcul différentiel"}]},
            "Code": {"type": "rich_text", "rich_text": [{"plain_text": "Ma211"}]},
            "Cours Moodle": {"type": "rich_text", "rich_text": []},
            "Dossier OneDrive": {"type": "url", "url": None},
        },
    },
    {
        "id": "c-ae211",
        "properties": {
            "Matière": {"type": "title", "title": [{"plain_text": "Aéronautique I"}]},
            "Code": {"type": "rich_text", "rich_text": [{"plain_text": "Aé211"}]},
            "Cours Moodle": {"type": "rich_text", "rich_text": [{"plain_text": "4242, AERO-GEN"}]},
            "Dossier OneDrive": {"type": "url", "url": None},
        },
    },
    {
        "id": "c-phs213",
        "properties": {
            "Matière": {"type": "title", "title": [{"plain_text": "Electromagnétisme 1"}]},
            "Code": {"type": "rich_text", "rich_text": [{"plain_text": "Phs213"}]},
            "Cours Moodle": {"type": "rich_text", "rich_text": []},
            "Dossier OneDrive": {"type": "url", "url": "https://old.example/phs213"},
        },
    },
]


@pytest.fixture
def courses() -> CourseIndex:
    return CourseIndex.from_pages(COURSE_PAGES)


@pytest.fixture
def make_page():
    return _page
