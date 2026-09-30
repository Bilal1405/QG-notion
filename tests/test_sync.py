from datetime import datetime, timezone

from qg_sync.config import DATA_SOURCES, Config
from qg_sync.moodle import Deadline
from qg_sync.notion import p_checkbox, p_select, p_text, p_title, same_props
from qg_sync.sync import (
    Record,
    Syncer,
    announcement_records,
    deadline_records,
    grade_records,
    moodle_resource_records,
)

from conftest import FakeNotion

NOW = datetime(2026, 9, 30, 12, tzinfo=timezone.utc)
BASE = "https://moodle.ipsa.fr"


def make_syncer(pages=None, dry_run=False):
    notion = FakeNotion(pages)
    cfg = Config(notion_token="x", dry_run=dry_run, github_repo="Bilal1405/QG-notion")
    return Syncer(cfg, notion, now=NOW), notion


def test_deadline_records_match_course_or_suffix_title(courses):
    records = deadline_records(
        [
            Deadline("1", "Rendu TP3", datetime(2026, 10, 12, 21, 59, tzinfo=timezone.utc), None, ("MA211-2526",), "u1"),
            Deadline("2", "Quiz BDE", datetime(2026, 10, 13, 8, tzinfo=timezone.utc), None, ("VIE-ETU",), "u2"),
        ],
        courses,
    )
    first, second = records
    assert first.source_id == "moodle:event:1"
    assert first.props["Cours"] == {"relation": [{"id": "c-ma211"}]}
    assert first.props["Échéance"] == {"date": {"start": "2026-10-12T23:59:00+02:00"}}
    assert first.create_props["Statut"] == p_select("À faire")
    assert "Cours" not in second.props
    assert second.props["Tâche"]["title"][0]["text"]["content"] == "Quiz BDE · VIE-ETU"


def test_upsert_creates_then_is_idempotent_and_keeps_user_status():
    syncer, notion = make_syncer()
    rec = Record("moodle:event:1", {"Tâche": p_title("Rendu TP3")}, {"Statut": p_select("À faire")})
    syncer.upsert("taches", [rec, rec])
    assert len(notion.created) == 1
    assert notion.created[0][1]["ID source"] == p_text("moodle:event:1")

    page = notion.pages[DATA_SOURCES["taches"]][0]
    notion.update_page(page["id"], {"Statut": p_select("Fait")})  # l'utilisateur coche « Fait »
    notion.updated.clear()

    syncer2, _ = make_syncer(notion.pages)
    syncer2.notion = notion
    syncer2.upsert("taches", [rec])
    assert notion.updated == []  # rien à changer, statut utilisateur conservé
    assert syncer2.stats["taches"]["inchangés"] == 1

    changed = Record("moodle:event:1", {"Tâche": p_title("Rendu TP3 (report)")})
    syncer2.upsert("taches", [changed])
    assert notion.updated[-1][1] == {"Tâche": p_title("Rendu TP3 (report)")}


def test_upsert_trashes_missing_in_scope_but_keeps_pinned(make_page):
    ds = DATA_SOURCES["ressources"]
    pages = {
        ds: [
            make_page("p1", {"ID source": p_text("onedrive:perso:a"), "Épinglé": p_checkbox(False)}),
            make_page("p2", {"ID source": p_text("onedrive:perso:b"), "Épinglé": p_checkbox(True)}),
            make_page("p3", {"ID source": p_text("moodle:cm:12:5"), "Épinglé": p_checkbox(False)}),
        ]
    }
    syncer, notion = make_syncer(pages)
    syncer.upsert("ressources", [], trash_scope=lambda sid: sid.startswith("onedrive:perso:"))
    assert [(u[0], u[2]) for u in notion.updated] == [("p1", True)]


def test_dry_run_writes_nothing():
    syncer, notion = make_syncer(dry_run=True)
    syncer.upsert("taches", [Record("moodle:event:9", {"Tâche": p_title("X")})])
    assert notion.created == [] and syncer.stats["taches"]["créés"] == 1


def test_max_creates_defers_extra_records():
    syncer, notion = make_syncer()
    syncer.cfg.max_creates = 1
    syncer.upsert("taches", [Record(f"moodle:event:{i}", {"Tâche": p_title(str(i))}) for i in range(3)])
    assert len(notion.created) == 1 and syncer.stats["taches"]["reportés"] == 2


def test_alert_created_once_then_closed():
    syncer, notion = make_syncer()
    syncer.alert("moodle", "🔑 Renouveler le jeton Moodle", ok=False)
    syncer.alert("moodle", "🔑 Renouveler le jeton Moodle", ok=False)
    assert len(notion.created) == 1
    props = notion.created[0][1]
    assert props["Source"] == p_select("Système") and props["ID source"] == p_text("system:moodle")
    assert "#renouveler-les-accès" in props["Lien"]["url"]

    syncer.alert("moodle", "🔑 Renouveler le jeton Moodle", ok=True)
    assert notion.updated[-1][1] == {"Statut": p_select("Fait")}


def test_moodle_resource_records_skip_hidden_and_labels(courses):
    mc = {"id": 12, "fullname": "Ma211 - Analyse", "shortname": "MA211"}
    sections = [
        {
            "name": "Chapitre 1",
            "modules": [
                {"id": 1, "modname": "resource", "name": "Poly", "url": f"{BASE}/mod/resource/view.php?id=1",
                 "contents": [{"filename": "poly.pdf", "timemodified": 1790000000}]},
                {"id": 2, "modname": "label", "name": "Texte"},
                {"id": 3, "modname": "quiz", "name": "Test", "uservisible": False},
                {"id": 4, "modname": "url", "name": "Vidéo YouTube"},
            ],
        }
    ]
    records = moodle_resource_records(BASE, mc, sections, courses.match("MA211"))
    assert [r.source_id for r in records] == ["moodle:cm:12:1", "moodle:cm:12:4"]
    assert records[0].props["Type"] == p_select("PDF")
    assert records[1].props["Lien"] == {"url": f"{BASE}/mod/url/view.php?id=4"}
    assert records[0].props["Matière"] == {"relation": [{"id": "c-ma211"}]}


def test_announcements_filtered_by_age(courses):
    mc = {"id": 12, "fullname": "Ma211 - Analyse"}
    pairs = [
        ({"course": 12}, {"discussion": 50, "name": "Salle changée", "message": "<p>Amphi B</p>",
                          "userfullname": "Prof", "timemodified": int(NOW.timestamp()) - 3600}),
        ({"course": 12}, {"discussion": 51, "name": "Vieux", "message": "", "timemodified": 1500000000}),
    ]
    since = datetime(2026, 6, 1, tzinfo=timezone.utc)
    records = announcement_records(BASE, pairs, {12: (mc, courses.match("MA211"))}, since)
    assert [r.source_id for r in records] == ["moodle:disc:50"]
    assert records[0].props["Lien"] == {"url": f"{BASE}/mod/forum/discuss.php?d=50"}
    assert records[0].create_props == {"Lue": p_checkbox(False)}


def test_grade_records_skip_totals_and_empty(courses):
    mc = {"id": 12, "fullname": "Ma211 - Analyse"}
    items = [
        {"id": 1, "itemtype": "mod", "itemmodule": "quiz", "cmid": 9, "itemname": "Test 1",
         "graderaw": 13.456, "grademax": 20, "gradedategraded": 1790000000, "feedback": "<p>Bien</p>"},
        {"id": 2, "itemtype": "mod", "itemname": "Test 2", "graderaw": None, "grademax": 20},
        {"id": 3, "itemtype": "course", "graderaw": 12, "grademax": 20},
    ]
    records = grade_records(BASE, mc, items, courses.match("MA211"))
    assert len(records) == 1
    props = records[0].props
    assert props["Note"] == {"number": 13.46} and props["Sur"] == {"number": 20.0}
    assert props["Lien"] == {"url": f"{BASE}/mod/quiz/view.php?id=9"}


def test_same_props_compares_dates_across_formats(make_page):
    page = make_page("p", {"Échéance": {"date": {"start": "2026-10-12T21:59:00.000+00:00"}}})
    assert same_props(page, {"Échéance": {"date": {"start": "2026-10-12T23:59:00+02:00"}}})
    assert not same_props(page, {"Échéance": {"date": {"start": "2026-10-12T22:00:00+02:00"}}})
