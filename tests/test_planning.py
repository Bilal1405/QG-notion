from datetime import datetime, timezone

import pytest

from qg_sync.config import DATA_SOURCES, Config
from qg_sync.notion import p_text, p_title, read_value
from qg_sync.planning import base_title, planning_title, short_room
from qg_sync.sync import Syncer

from conftest import FakeNotion, _page

NOW = datetime(2026, 10, 9, 8, tzinfo=timezone.utc)


@pytest.mark.parametrize(
    ("salle", "expected"),
    [
        ("BC308 - Bleriot - Salle 308", "BC308"),
        ("AMPHI-017", "AMPHI-017"),
        ("BC307 - Bleriot - Salle 307, BC501 - Bleriot - Salle 501", "BC307/BC501"),
        ("AMPHI-017, BC307 - Bleriot - Salle 307, BC501 - Bleriot - Salle 501", "3 salles"),
        ("", ""),
        (None, ""),
    ],
)
def test_short_room(salle, expected):
    assert short_room(salle) == expected


def test_planning_title_is_idempotent_and_follows_room_changes():
    first = planning_title("Thermodynamique 1", "BC309 - Bleriot - Salle 309")
    assert first == "Thermodynamique 1 · 📍BC309"
    assert planning_title(first, "BC309 - Bleriot - Salle 309") == first
    assert planning_title(first, "AC008 - Ariane - Salle 008") == "Thermodynamique 1 · 📍AC008"
    assert planning_title(first, "") == "Thermodynamique 1"
    assert base_title(first) == "Thermodynamique 1"


def slot(page_id, title, salle, start):
    return _page(page_id, {"Cours": p_title(title), "Salle": p_text(salle), "Horaire": {"date": {"start": start}}})


def test_sync_planning_updates_upcoming_slots_only():
    notion = FakeNotion({DATA_SOURCES["planning"]: [
        slot("past", "Analyse", "BC606 - Bleriot - Salle 606", "2026-10-01T08:30:00.000+02:00"),
        slot("next", "Analyse", "BC606 - Bleriot - Salle 606", "2026-10-12T08:30:00.000+02:00"),
        slot("done", "Python · 📍AC108", "AC108 - Ariane - Salle 108", "2026-10-12T15:30:00.000+02:00"),
        slot("asso", "ASSOCIATIONS IPSA", "", "2026-10-22T13:30:00.000+02:00"),
        slot("vac", "Vacances", "", "2026-10-26"),
    ]})
    syncer = Syncer(Config(notion_token="x"), notion, now=NOW)
    syncer.run({"planning"})

    assert [(pid, read_value(props["Cours"])) for pid, props, _ in notion.updated] == [("next", "Analyse · 📍BC606")]
    assert syncer.stats["planning"] == {"salle ajoutée": 1, "inchangés": 3}

    notion.updated.clear()
    Syncer(Config(notion_token="x"), notion, now=NOW).run({"planning"})
    assert notion.updated == []


def test_dry_run_writes_nothing():
    notion = FakeNotion({DATA_SOURCES["planning"]: [
        slot("next", "Analyse", "BC606 - Bleriot - Salle 606", "2026-10-12T08:30:00.000+02:00"),
    ]})
    syncer = Syncer(Config(notion_token="x", dry_run=True), notion, now=NOW)
    syncer.run({"planning"})
    assert notion.updated == [] and syncer.stats["planning"]["salle ajoutée"] == 1
