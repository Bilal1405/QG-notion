"""Association d'un cours Moodle ou d'un dossier OneDrive à une matière de « Cours IPSA ».

Règle principale : le code matière IPSA (Ma211, Aé211, Phs213…) présent dans le nom.
Repli : identifiants saisis dans la colonne « Cours Moodle », puis nom de matière identique.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from .notion import read_plain

CODE_RE = re.compile(r"(?<![a-z0-9])([a-z]{2,3}\d{3})(?![0-9])")


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFKD", text or "")
    text = "".join(c for c in text if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", text.lower()).strip()


def extract_codes(text: str) -> list[str]:
    return CODE_RE.findall(normalize(text))


@dataclass
class Course:
    page_id: str
    name: str
    code: str
    moodle_keys: set[str]
    onedrive_url: str


class CourseIndex:
    def __init__(self, courses: list[Course]):
        self.courses = courses
        self.by_code = {normalize(c.code): c for c in courses if c.code}
        self.by_key = {k: c for c in courses for k in c.moodle_keys}
        self.by_name = {normalize(c.name): c for c in courses if len(c.name) >= 6}

    @classmethod
    def from_pages(cls, pages: list[dict]) -> "CourseIndex":
        courses = []
        for page in pages:
            props = page.get("properties", {})
            keys = {normalize(k) for k in read_plain(props.get("Cours Moodle")).split(",") if k.strip()}
            courses.append(
                Course(
                    page_id=page["id"],
                    name=read_plain(props.get("Matière")),
                    code=read_plain(props.get("Code")),
                    moodle_keys=keys,
                    onedrive_url=(props.get("Dossier OneDrive") or {}).get("url") or "",
                )
            )
        return cls(courses)

    def match(self, *texts: str, moodle_id: int | str | None = None) -> Course | None:
        if moodle_id is not None and str(moodle_id) in self.by_key:
            return self.by_key[str(moodle_id)]
        for text in texts:
            if normalize(text) in self.by_key:
                return self.by_key[normalize(text)]
        for text in texts:
            for code in extract_codes(text):
                if code in self.by_code:
                    return self.by_code[code]
        for text in texts:
            if normalize(text) in self.by_name:
                return self.by_name[normalize(text)]
        return None
