"""Scénario complet hors ligne : faux Moodle + faux Notion."""

from datetime import datetime, timezone

from qg_sync.config import DATA_SOURCES, Config
from qg_sync.notion import read_plain
from qg_sync.sync import Syncer

from conftest import COURSE_PAGES, FakeNotion
from test_moodle import ICS

NOW = datetime(2026, 9, 30, 12, tzinfo=timezone.utc)

WS = {
    "core_webservice_get_site_info": {"userid": 7},
    "core_calendar_get_action_events_by_timesort": {
        "events": [
            {"id": 1201, "name": "Rendu TP3 est à remettre", "activityname": "Rendu TP3", "timesort": 1791849540,
             "course": {"id": 12, "shortname": "MA211-2526", "fullname": "Ma211 Analyse"},
             "url": "https://moodle.ipsa.fr/mod/assign/view.php?id=31"}
        ]
    },
    "core_enrol_get_users_courses": [
        {"id": 12, "shortname": "MA211-2526", "fullname": "Ma211 Analyse"},
        {"id": 99, "shortname": "BDE", "fullname": "Vie étudiante"},
    ],
    "core_course_get_contents": [
        {"name": "Chapitre 1", "modules": [{"id": 31, "modname": "assign", "name": "Rendu TP3"},
                                           {"id": 32, "modname": "resource", "name": "Poly",
                                            "contents": [{"filename": "poly.pdf", "timemodified": 1790000000}]}]}
    ],
    "gradereport_user_get_grade_items": {"usergrades": [{"gradeitems": [
        {"id": 5, "itemtype": "mod", "itemmodule": "quiz", "cmid": 40, "itemname": "Test 1",
         "graderaw": 15, "grademax": 20, "gradedategraded": 1790000000}]}]},
    "mod_forum_get_forums_by_courses": [{"id": 3, "course": 12, "type": "news"}, {"id": 4, "course": 12, "type": "general"}],
    "mod_forum_get_forum_discussions": {"discussions": [
        {"discussion": 50, "name": "Salle changée", "message": "<p>Amphi B</p>", "userfullname": "Prof",
         "timemodified": int(NOW.timestamp()) - 3600}]},
}


class Resp:
    def __init__(self, payload=None, text="", status=200):
        self.payload, self.text, self.status_code = payload, text, status

    def json(self):
        return self.payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(self.status_code)


class FakeHttp:
    def __init__(self, token_ok=True):
        self.token_ok, self.calls = token_ok, []

    def get(self, url, timeout=None):
        return Resp(text=ICS)

    def post(self, url, data=None, timeout=None):
        fn = data["wsfunction"]
        self.calls.append(fn)
        if not self.token_ok:
            return Resp({"exception": "moodle_exception", "errorcode": "invalidtoken"})
        return Resp(WS[fn])


def run(http, notion):
    cfg = Config(notion_token="x", moodle_token="tok", moodle_ics_url="https://moodle.ipsa.fr/calendar/export_execute.php?x")
    syncer = Syncer(cfg, notion, now=NOW, http=http)
    syncer.run()
    return syncer


def titles(notion, key):
    return sorted(
        read_plain(prop)
        for p in notion.pages.get(DATA_SOURCES[key], [])
        if not p.get("in_trash")
        for prop in p["properties"].values()
        if prop["type"] == "title"
    )


def test_full_moodle_run_then_rerun_is_stable():
    notion = FakeNotion({DATA_SOURCES["cours"]: COURSE_PAGES})
    syncer = run(FakeHttp(), notion)

    tasks = notion.pages[DATA_SOURCES["taches"]]
    by_source = {read_plain(t["properties"]["ID source"]): t for t in tasks}
    # l'événement 1201 vient de l'ICS et du web service : une seule tâche, données du web service
    assert set(by_source) == {"moodle:event:1201", "moodle:event:1204"}
    assert read_plain(by_source["moodle:event:1201"]["properties"]["Tâche"]) == "Rendu TP3"
    assert by_source["moodle:event:1201"]["properties"]["Cours"]["relation"] == [{"id": "c-ma211"}]

    assert len(notion.pages[DATA_SOURCES["ressources"]]) == 4  # 2 modules × 2 cours (même contenu simulé)
    assert titles(notion, "notes_moodle") == ["Test 1", "Test 1"]
    assert titles(notion, "annonces") == ["Salle changée"]
    assert syncer.stats["cours Moodle"]["sans matière"] == 1
    assert syncer.warnings == []

    created = len(notion.created)
    notion.updated.clear()
    syncer2 = run(FakeHttp(), notion)
    assert len(notion.created) == created and notion.updated == []
    assert syncer2.stats["ressources"]["inchangés"] == 4


def test_expired_token_raises_alert_and_keeps_ics_deadlines():
    notion = FakeNotion({DATA_SOURCES["cours"]: COURSE_PAGES})
    http = FakeHttp(token_ok=False)
    syncer = run(http, notion)
    assert http.calls == ["core_webservice_get_site_info"]
    task_titles = titles(notion, "taches")
    assert "🔑 Renouveler le jeton Moodle" in task_titles
    assert "Rendu TP3 est à remettre · MA211-2526" not in task_titles  # rattachée au cours par le code
    assert "Rendu TP3 est à remettre" in task_titles
    assert "🔑 Renouveler le jeton Moodle" in syncer.warnings
