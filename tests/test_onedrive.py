from datetime import datetime, timezone

from qg_sync.config import OneDriveAccount
from qg_sync.onedrive import DriveItem, GraphClient
from qg_sync.sync import onedrive_records

ACCOUNT = OneDriveAccount("perso", "OneDrive perso", "rt", "IPSA/IPSA_Année_2", "common", "ONEDRIVE_PERSO_REFRESH_TOKEN")
T = datetime(2026, 9, 28, 10, tzinfo=timezone.utc)


def item(id, name, parents, folder=False):
    return DriveItem(id, name, f"https://onedrive.live.com/{id}", T, folder, tuple(parents))


def test_records_only_for_files_under_course_folders(courses):
    items = [
        item("f1", "Semestre_S1", [], folder=True),
        item("x", "notes_perso.txt", []),
        item("f2", "Ma211 - Analyse - calcul différentiel", ["Semestre_S1"], folder=True),
        item("f3", "TD", ["Semestre_S1", "Ma211 - Analyse - calcul différentiel"], folder=True),
        item("a", "Cours ch1.pdf", ["Semestre_S1", "Ma211 - Analyse - calcul différentiel"]),
        item("b", "TD2 corrigé.docx", ["Semestre_S1", "Ma211 - Analyse - calcul différentiel", "TD"]),
        item("d", "planning.xlsx", ["Semestre_S1"]),
    ]
    records, folders = onedrive_records(ACCOUNT, items, courses)
    by_id = {r.source_id: r.props for r in records}
    assert set(by_id) == {"onedrive:perso:a", "onedrive:perso:b"}
    b = by_id["onedrive:perso:b"]
    assert b["Section"]["rich_text"][0]["text"]["content"] == "TD"
    assert b["Type"]["select"]["name"] == "Document"
    assert b["Matière"] == {"relation": [{"id": "c-ma211"}]}
    assert b["Source"]["select"]["name"] == "OneDrive perso"
    assert folders == {"c-ma211": "https://onedrive.live.com/f2"}


class FakeGraphSession:
    def __init__(self, tree):
        self.tree, self.headers = tree, {}

    def get(self, url, params=None, timeout=None):
        class R:
            status_code = 200
            headers = {}
            content = b"x"

            def __init__(self, payload):
                self.payload = payload

            def json(self):
                return self.payload

        if "/root:/" in url or url.endswith("/root"):
            return R({"id": "root", "name": "IPSA_Année_2"})
        item_id = url.split("/items/")[1].split("/")[0]
        return R({"value": self.tree.get(item_id, [])})


def test_walk_breadth_first_and_skips_temp_files():
    tree = {
        "root": [{"id": "s1", "name": "Semestre_S1", "folder": {}}, {"id": "t", "name": "~$tmp.docx", "file": {}}],
        "s1": [
            {"id": "m", "name": "Ma211 - Analyse", "folder": {}},
            {"id": "p", "name": "planning.pdf", "file": {}, "lastModifiedDateTime": "2026-09-01T08:00:00Z"},
        ],
        "m": [{"id": "f", "name": "cours.pdf", "file": {}}],
    }
    client = GraphClient("token", FakeGraphSession(tree))
    root, items, complete = client.walk("IPSA/IPSA_Année_2")
    assert complete and root.id == "root"
    assert [i.id for i in items] == ["s1", "m", "p", "f"]
    assert items[3].parents == ("Semestre_S1", "Ma211 - Analyse")
    assert items[2].modified == datetime(2026, 9, 1, 8, tzinfo=timezone.utc)


def test_walk_reports_truncation():
    tree = {"root": [{"id": "a", "name": "A", "folder": {}}], "a": [{"id": "b", "name": "B", "folder": {}}]}
    _, items, complete = GraphClient("token", FakeGraphSession(tree)).walk("", max_depth=1)
    assert [i.id for i in items] == ["a"] and not complete
