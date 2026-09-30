"""Orchestration : lit Moodle et OneDrive, puis crée ou met à jour les pages Notion."""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Callable, Iterable
from zoneinfo import ZoneInfo

import requests

from . import github_secrets
from .config import DATA_SOURCES, Config, OneDriveAccount
from .matching import Course, CourseIndex
from .moodle import (
    SKIPPED_MODULES,
    Deadline,
    MoodleAuthError,
    MoodleClient,
    MoodleError,
    deadline_from_action_event,
    deadlines_from_ics,
    html_to_text,
    module_modified,
    module_type,
    type_from_filename,
)
from .notion import (
    NotionClient,
    p_checkbox,
    p_date,
    p_number,
    p_relation,
    p_select,
    p_text,
    p_title,
    p_url,
    read_plain,
    read_value,
    same_props,
)
from .onedrive import DriveItem, GraphAuthError, GraphClient, GraphError, refresh_access_token

PARIS = ZoneInfo("Europe/Paris")


@dataclass
class Record:
    source_id: str
    props: dict  # resynchronisées à chaque passage
    create_props: dict = field(default_factory=dict)  # posées uniquement à la création


def course_props(course: Course | None) -> dict:
    return {"Matière": p_relation([course.page_id])} if course else {}


def _local(value: datetime | date | None) -> datetime | date | None:
    if isinstance(value, datetime):
        return value.astimezone(PARIS)
    return value


# --- Construction des enregistrements (fonctions pures, testées) ------------


def deadline_records(deadlines: Iterable[Deadline], courses: CourseIndex) -> list[Record]:
    records = []
    for d in deadlines:
        course = courses.match(*d.course_texts, moodle_id=d.course_id)
        title = d.name if course or not d.course_texts else f"{d.name} · {d.course_texts[0]}"
        props = {
            "Tâche": p_title(title),
            "Échéance": p_date(_local(d.due)),
            "Lien": p_url(d.url),
            "Source": p_select("Moodle"),
        }
        if course:
            props["Cours"] = p_relation([course.page_id])
        records.append(
            Record(
                source_id=f"moodle:event:{d.event_id}",
                props=props,
                create_props={"Statut": p_select("À faire"), "Type": p_select("Devoir")},
            )
        )
    return records


def moodle_resource_records(
    base_url: str, moodle_course: dict, sections: list[dict], course: Course | None
) -> list[Record]:
    records = []
    for section in sections:
        for module in section.get("modules", []):
            if module.get("modname") in SKIPPED_MODULES:
                continue
            if module.get("uservisible") is False or module.get("visible", 1) == 0:
                continue
            cmid = module["id"]
            url = module.get("url") or f"{base_url}/mod/{module.get('modname')}/view.php?id={cmid}"
            props = {
                "Nom": p_title(module.get("name", "")),
                "Source": p_select("Moodle"),
                "Type": p_select(module_type(module)),
                "Section": p_text(section.get("name", "")),
                "Lien": p_url(url),
                "Modifié le": p_date(_local(module_modified(module))),
                "Cours source": p_text(moodle_course.get("fullname", "")),
                **course_props(course),
            }
            records.append(Record(f"moodle:cm:{moodle_course['id']}:{cmid}", props))
    return records


def announcement_records(
    base_url: str, pairs: list[tuple[dict, dict]], courses_by_id: dict[int, tuple[dict, Course | None]], since: datetime
) -> list[Record]:
    records = []
    for forum, disc in pairs:
        stamp = disc.get("timemodified") or disc.get("modified") or disc.get("created")
        when = datetime.fromtimestamp(stamp, tz=timezone.utc) if stamp else None
        if when and when < since:
            continue
        moodle_course, course = courses_by_id.get(forum.get("course"), ({}, None))
        disc_id = disc.get("discussion") or disc.get("id")
        props = {
            "Titre": p_title(disc.get("name") or disc.get("subject") or "Annonce"),
            "Date": p_date(_local(when)),
            "Auteur": p_text(disc.get("userfullname", "")),
            "Extrait": p_text(html_to_text(disc.get("message", ""))),
            "Lien": p_url(f"{base_url}/mod/forum/discuss.php?d={disc_id}"),
            "Cours source": p_text(moodle_course.get("fullname", "")),
            **course_props(course),
        }
        records.append(Record(f"moodle:disc:{disc_id}", props, {"Lue": p_checkbox(False)}))
    return records


def grade_records(base_url: str, moodle_course: dict, items: list[dict], course: Course | None) -> list[Record]:
    records = []
    for item in items:
        if item.get("itemtype") in ("course", "category") or item.get("graderaw") is None:
            continue
        stamp = item.get("gradedategraded") or item.get("gradedatesubmitted")
        if item.get("cmid") and item.get("itemmodule"):
            url = f"{base_url}/mod/{item['itemmodule']}/view.php?id={item['cmid']}"
        else:
            url = f"{base_url}/grade/report/user/index.php?id={moodle_course['id']}"
        props = {
            "Élément": p_title(item.get("itemname") or "Note"),
            "Note": p_number(round(float(item["graderaw"]), 2)),
            "Sur": p_number(float(item["grademax"]) if item.get("grademax") is not None else None),
            "Date": p_date(_local(datetime.fromtimestamp(stamp, tz=timezone.utc)) if stamp else None),
            "Commentaire": p_text(html_to_text(item.get("feedback", ""), 400)),
            "Lien": p_url(url),
            "Cours source": p_text(moodle_course.get("fullname", "")),
            **course_props(course),
        }
        records.append(Record(f"moodle:grade:{moodle_course['id']}:{item['id']}", props))
    return records


def onedrive_records(
    account: OneDriveAccount, items: list[DriveItem], courses: CourseIndex
) -> tuple[list[Record], dict[str, str]]:
    """Fichiers rangés sous un dossier de matière (nom contenant le code) + lien web de ces dossiers."""
    cache: dict[str, Course | None] = {}

    def match(name: str) -> Course | None:
        if name not in cache:
            cache[name] = courses.match(name)
        return cache[name]

    records, folder_urls = [], {}
    for item in items:
        if item.is_folder:
            course = match(item.name)
            if course and course.page_id not in folder_urls:
                folder_urls[course.page_id] = item.web_url
            continue
        for depth in range(len(item.parents) - 1, -1, -1):
            course = match(item.parents[depth])
            if course:
                break
        else:
            continue  # fichier hors des dossiers de matières : ignoré
        props = {
            "Nom": p_title(item.name),
            "Source": p_select(account.label),
            "Type": p_select(type_from_filename(item.name)),
            "Section": p_text(" / ".join(item.parents[depth + 1 :])),
            "Lien": p_url(item.web_url),
            "Modifié le": p_date(_local(item.modified)),
            "Cours source": p_text(item.parents[depth]),
            **course_props(course),
        }
        records.append(Record(f"onedrive:{account.key}:{item.id}", props))
    return records, folder_urls


# --- Synchroniseur ----------------------------------------------------------


class Syncer:
    def __init__(self, cfg: Config, notion: NotionClient, now: datetime | None = None, http: requests.Session | None = None):
        self.cfg = cfg
        self.notion = notion
        self.now = now or datetime.now(timezone.utc)
        self.http = http or requests.Session()
        self.stats: dict[str, Counter] = defaultdict(Counter)
        self.warnings: list[str] = []
        self.creates = 0
        self._tasks_index: dict[str, dict] | None = None

    # -- Notion --

    def load_index(self, key: str) -> dict[str, dict]:
        pages = self.notion.query_all(
            DATA_SOURCES[key], filter={"property": "ID source", "rich_text": {"is_not_empty": True}}
        )
        return {read_plain(p["properties"].get("ID source")): p for p in pages}

    def upsert(
        self,
        key: str,
        records: list[Record],
        index: dict[str, dict] | None = None,
        trash_scope: Callable[[str], bool] | None = None,
    ) -> None:
        index = self.load_index(key) if index is None else index
        stats, seen = self.stats[key], set()
        for rec in records:
            if rec.source_id in seen:
                continue
            seen.add(rec.source_id)
            page = index.get(rec.source_id)
            if page is None:
                if self.creates >= self.cfg.max_creates:
                    stats["reportés"] += 1
                    continue
                props = {**rec.create_props, **rec.props, "ID source": p_text(rec.source_id)}
                if not self.cfg.dry_run:
                    index[rec.source_id] = self.notion.create_page(DATA_SOURCES[key], props)
                self.creates += 1
                stats["créés"] += 1
            elif not same_props(page, rec.props):
                if not self.cfg.dry_run:
                    self.notion.update_page(page["id"], rec.props)
                stats["mis à jour"] += 1
            else:
                stats["inchangés"] += 1
        if trash_scope is None:
            return
        for source_id, page in index.items():
            if source_id in seen or not trash_scope(source_id):
                continue
            if read_value(page.get("properties", {}).get("Épinglé")):
                continue
            if not self.cfg.dry_run:
                self.notion.update_page(page["id"], in_trash=True)
            stats["supprimés"] += 1

    def alert(self, key: str, title: str, ok: bool) -> None:
        """Tâche « Système » sur le tableau de bord quand un accès expire ; close automatiquement ensuite."""
        if self._tasks_index is None:
            self._tasks_index = self.load_index("taches")
        source_id = f"system:{key}"
        page = self._tasks_index.get(source_id)
        status = read_value(page["properties"].get("Statut")) if page else None
        if ok:
            if page and status != "Fait" and not self.cfg.dry_run:
                self.notion.update_page(page["id"], {"Statut": p_select("Fait")})
            return
        self.warnings.append(title)
        props = {
            "Tâche": p_title(title),
            "Source": p_select("Système"),
            "Priorité": p_select("Haute"),
            "Statut": p_select("À faire"),
            "Échéance": p_date(self.now.astimezone(PARIS).date()),
            "Type": p_select("Admin"),
            "Lien": p_url(f"https://github.com/{self.cfg.github_repo}#renouveler-les-accès" if self.cfg.github_repo else None),
        }
        if self.cfg.dry_run:
            return
        if page is None:
            self._tasks_index[source_id] = self.notion.create_page(
                DATA_SOURCES["taches"], {**props, "ID source": p_text(source_id)}
            )
        elif status == "Fait":
            self.notion.update_page(page["id"], {"Statut": p_select("À faire"), "Échéance": props["Échéance"]})

    # -- Moodle --

    def sync_moodle(self, courses: CourseIndex) -> None:
        cfg = self.cfg
        deadlines: dict[str, Deadline] = {}

        if cfg.moodle_ics_url:
            try:
                resp = self.http.get(cfg.moodle_ics_url, timeout=60)
                resp.raise_for_status()
                for d in deadlines_from_ics(resp.text, cfg.moodle_url, self.now):
                    deadlines[d.event_id] = d
                self.alert("moodle-ics", "🔑 Renouveler l'URL du calendrier Moodle", ok=True)
            except Exception as exc:  # noqa: BLE001 - flux iCal indisponible ou invalide
                self.alert("moodle-ics", "🔑 Renouveler l'URL du calendrier Moodle", ok=False)
                self.warnings.append(f"calendrier Moodle illisible ({type(exc).__name__})")

        client = MoodleClient(cfg.moodle_url, cfg.moodle_token, self.http) if cfg.moodle_token else None
        userid = None
        if client:
            try:
                userid = client.site_info()["userid"]
                self.alert("moodle", "🔑 Renouveler le jeton Moodle", ok=True)
            except MoodleAuthError:
                self.alert("moodle", "🔑 Renouveler le jeton Moodle", ok=False)
                client = None
            except MoodleError as exc:
                self.warnings.append(f"Moodle indisponible ({exc})")
                client = None

        if client:
            try:
                for event in client.action_events(self.now - timedelta(days=7)):
                    d = deadline_from_action_event(event)
                    deadlines[d.event_id] = d
            except MoodleError as exc:
                self.warnings.append(f"échéances Moodle : {exc}")

        if deadlines:
            self.upsert("taches", deadline_records(deadlines.values(), courses))

        if not client:
            return

        try:
            moodle_courses = client.courses(userid)
        except MoodleError as exc:
            self.warnings.append(f"liste des cours Moodle : {exc}")
            return

        courses_by_id: dict[int, tuple[dict, Course | None]] = {}
        resources, grades, covered = [], [], set()
        for mc in moodle_courses:
            course = courses.match(mc.get("shortname", ""), mc.get("fullname", ""), mc.get("idnumber", ""), moodle_id=mc["id"])
            courses_by_id[mc["id"]] = (mc, course)
            if course is None:
                self.stats["cours Moodle"]["sans matière"] += 1
            try:
                resources += moodle_resource_records(cfg.moodle_url, mc, client.contents(mc["id"]), course)
                covered.add(str(mc["id"]))
            except MoodleError as exc:
                self.warnings.append(f"contenu d'un cours Moodle : {exc}")
            try:
                grades += grade_records(cfg.moodle_url, mc, client.grade_items(mc["id"], userid), course)
            except MoodleError:
                self.stats["notes Moodle"]["cours sans carnet"] += 1

        self.upsert(
            "ressources",
            resources,
            trash_scope=lambda sid: sid.startswith("moodle:cm:") and sid.split(":")[2] in covered,
        )
        self.upsert("notes_moodle", grades)

        pairs: list[tuple[dict, dict]] = []
        ids = list(courses_by_id)
        for i in range(0, len(ids), 20):
            try:
                pairs += client.news_discussions(ids[i : i + 20])
            except MoodleError as exc:
                self.warnings.append(f"annonces Moodle : {exc}")
        since = self.now - timedelta(days=cfg.announcements_days)
        self.upsert("annonces", announcement_records(cfg.moodle_url, pairs, courses_by_id, since))

    # -- OneDrive --

    def sync_onedrive(self, courses: CourseIndex) -> None:
        cfg = self.cfg
        if cfg.onedrive and not cfg.ms_client_id:
            self.warnings.append("MS_CLIENT_ID manquant : OneDrive ignoré")
            return
        folder_urls: dict[str, str] = {}
        for account in cfg.onedrive:
            alert_key, alert_title = f"onedrive-{account.key}", f"🔑 Reconnecter {account.label}"
            try:
                access, new_refresh = refresh_access_token(cfg.ms_client_id, account.refresh_token, account.tenant, self.http)
            except GraphAuthError:
                self.alert(alert_key, alert_title, ok=False)
                continue
            self.alert(alert_key, alert_title, ok=True)
            self._persist_refresh_token(account, new_refresh)
            try:
                _, items, complete = GraphClient(access).walk(account.root)
            except (GraphError, GraphAuthError) as exc:
                self.warnings.append(f"{account.label} : {exc}")
                continue
            records, urls = onedrive_records(account, items, courses)
            for page_id, url in urls.items():
                folder_urls.setdefault(page_id, url)
            prefix = f"onedrive:{account.key}:"
            self.upsert("ressources", records, trash_scope=(lambda sid, p=prefix: sid.startswith(p)) if complete else None)

        for course in courses.courses:
            url = folder_urls.get(course.page_id)
            if url and url != course.onedrive_url:
                if not cfg.dry_run:
                    self.notion.update_page(course.page_id, {"Dossier OneDrive": p_url(url)})
                self.stats["cours"]["dossier OneDrive"] += 1

    def _persist_refresh_token(self, account: OneDriveAccount, new_refresh: str) -> None:
        if not new_refresh or new_refresh == account.refresh_token or self.cfg.dry_run:
            return
        if not (self.cfg.github_secrets_token and self.cfg.github_repo):
            return  # l'ancien jeton reste utilisable jusqu'à son expiration
        try:
            github_secrets.update_secret(
                self.cfg.github_repo, account.secret_name, new_refresh, self.cfg.github_secrets_token, self.http
            )
        except requests.RequestException as exc:
            self.warnings.append(f"secret {account.secret_name} non mis à jour ({type(exc).__name__})")

    # -- Point d'entrée --

    def run(self, only: set[str] | None = None) -> None:
        courses = CourseIndex.from_pages(self.notion.query_all(DATA_SOURCES["cours"]))
        if (not only or "moodle" in only) and (self.cfg.moodle_token or self.cfg.moodle_ics_url):
            self.sync_moodle(courses)
        if (not only or "onedrive" in only) and self.cfg.onedrive:
            self.sync_onedrive(courses)

    def report(self) -> str:
        lines = [f"{'[simulation] ' if self.cfg.dry_run else ''}Synchro QG — {self.now:%Y-%m-%d %H:%M} UTC"]
        for key, counter in self.stats.items():
            detail = ", ".join(f"{v} {k}" for k, v in counter.items())
            lines.append(f"  {key} : {detail}")
        for warning in self.warnings:
            lines.append(f"  ⚠ {warning}")
        return "\n".join(lines)
