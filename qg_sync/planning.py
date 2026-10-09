"""Salle dans le titre des créneaux « Planning IPSA ».

Notion Calendar n'affiche que le titre d'un événement issu d'une base Notion : la salle
y est donc ajoutée (« Thermodynamique 1 · 📍BC309 »). La propriété Salle reste la source ;
le suffixe est recalculé à chaque passage, sans toucher au reste du titre.
"""

from __future__ import annotations

import re

SUFFIX = " · 📍"
_SUFFIX_RE = re.compile(r"\s*·\s*📍.*$")


def short_room(salle: str) -> str:
    """« BC308 - Bleriot - Salle 308 » → « BC308 » ; plusieurs salles → « BC307/BC501 » ou « 6 salles »."""
    codes = [part.split(" - ")[0].strip() for part in (salle or "").split(",")]
    codes = [c for c in codes if c]
    if len(codes) <= 2:
        return "/".join(codes)
    return f"{len(codes)} salles"


def base_title(title: str) -> str:
    return _SUFFIX_RE.sub("", title or "").strip()


def planning_title(title: str, salle: str) -> str:
    base, room = base_title(title), short_room(salle)
    return f"{base}{SUFFIX}{room}" if room else base
