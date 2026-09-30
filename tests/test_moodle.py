from datetime import date, datetime, timezone

import pytest

from qg_sync import moodle
from qg_sync.moodle import (
    MoodleAuthError,
    MoodleClient,
    MoodleError,
    _flatten,
    deadline_from_action_event,
    deadlines_from_ics,
    html_to_text,
    module_type,
)

ICS = """BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//Moodle Pty Ltd//NONSGML Moodle Version 2024100700//EN
BEGIN:VEVENT
UID:1201@moodle.ipsa.fr
SUMMARY:Rendu TP3 est à remettre
DESCRIPTION:Déposer le compte rendu
CATEGORIES:MA211-2526
DTSTART:20261012T215900Z
DTEND:20261012T215900Z
END:VEVENT
BEGIN:VEVENT
UID:1202@moodle.ipsa.fr
SUMMARY:Test chapitre 2 s'ouvre
CATEGORIES:MA211-2526
DTSTART:20261010T080000Z
END:VEVENT
BEGIN:VEVENT
UID:1203@moodle.ipsa.fr
SUMMARY:Vieux devoir est à remettre
DTSTART:20250101T080000Z
END:VEVENT
BEGIN:VEVENT
UID:1204@moodle.ipsa.fr
SUMMARY:Journée projet
DTSTART;VALUE=DATE:20261020
END:VEVENT
END:VCALENDAR
"""

NOW = datetime(2026, 9, 30, 12, tzinfo=timezone.utc)


def test_ics_keeps_deadlines_in_window_and_skips_openings():
    result = deadlines_from_ics(ICS.replace("\n", "\r\n"), "https://moodle.ipsa.fr", NOW)
    assert [d.event_id for d in result] == ["1201", "1204"]
    tp3 = result[0]
    assert tp3.name == "Rendu TP3 est à remettre"
    assert tp3.course_texts == ("MA211-2526",)
    assert tp3.due == datetime(2026, 10, 12, 21, 59, tzinfo=timezone.utc)
    assert tp3.url.startswith("https://moodle.ipsa.fr/calendar/view.php")
    assert result[1].due == date(2026, 10, 20)


def test_action_event_mapping():
    d = deadline_from_action_event(
        {
            "id": 77,
            "name": "TP noté est à remettre",
            "activityname": "TP noté",
            "timesort": 1791849540,
            "course": {"id": 12, "shortname": "PHS213", "fullname": "Electromagnétisme 1"},
            "url": "https://moodle.ipsa.fr/mod/assign/view.php?id=5",
        }
    )
    assert (d.event_id, d.name, d.course_id) == ("77", "TP noté", 12)
    assert d.course_texts == ("PHS213", "Electromagnétisme 1")


def test_flatten_arrays():
    assert _flatten({"courseids": [3, 4], "options": [{"name": "x", "value": 1}]}) == {
        "courseids[0]": 3,
        "courseids[1]": 4,
        "options[0][name]": "x",
        "options[0][value]": 1,
    }


@pytest.mark.parametrize(
    "module,expected",
    [
        ({"modname": "resource", "contents": [{"filename": "Cours_ch1.PDF"}]}, "PDF"),
        ({"modname": "resource", "contents": [{"filename": "TD.pptx"}]}, "Présentation"),
        ({"modname": "resource", "contents": []}, "Autre"),
        ({"modname": "assign"}, "Devoir"),
        ({"modname": "h5pactivity"}, "Autre"),
    ],
)
def test_module_type(module, expected):
    assert module_type(module) == expected


def test_html_to_text():
    assert html_to_text("<p>Bonjour&nbsp;à tous</p><p>TP <b>annulé</b></p>") == "Bonjour\xa0à tous\nTP annulé"
    assert html_to_text("x" * 700, limit=10) == "xxxxxxxxx…"


class FakeResponse:
    def __init__(self, payload, status=200):
        self.payload, self.status_code = payload, status

    def json(self):
        return self.payload


class FakeSession:
    def __init__(self, payload):
        self.payload, self.calls = payload, []

    def post(self, url, data, timeout):
        self.calls.append((url, data))
        return FakeResponse(self.payload)


def test_client_auth_error_is_distinguished():
    client = MoodleClient("https://m", "t", FakeSession({"exception": "x", "errorcode": "invalidtoken"}))
    with pytest.raises(MoodleAuthError):
        client.site_info()
    client = MoodleClient("https://m", "t", FakeSession({"exception": "x", "errorcode": "nopermissions"}))
    with pytest.raises(MoodleError):
        client.site_info()


def test_client_posts_to_rest_endpoint():
    session = FakeSession({"userid": 9})
    assert MoodleClient("https://m/", "tok", session).site_info() == {"userid": 9}
    url, data = session.calls[0]
    assert url == "https://m/webservice/rest/server.php"
    assert data["wstoken"] == "tok" and data["wsfunction"] == "core_webservice_get_site_info"


def test_type_from_filename():
    assert moodle.type_from_filename("rapport.docx") == "Document"
    assert moodle.type_from_filename("sans_extension") == "Autre"
