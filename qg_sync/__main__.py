"""Usage : python -m qg_sync [--dry-run] [--only planning,moodle,onedrive]"""

from __future__ import annotations

import argparse
import sys

from .config import Config
from .notion import NotionClient, NotionError
from .sync import Syncer


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="qg_sync", description="Synchro Planning + Moodle + OneDrive → Notion")
    parser.add_argument("--dry-run", action="store_true", help="calcule sans rien écrire dans Notion")
    parser.add_argument("--only", default="", help="planning, moodle, onedrive (séparés par une virgule)")
    args = parser.parse_args(argv)

    cfg = Config.from_env(dry_run=args.dry_run)
    if not cfg.notion_token:
        print("NOTION_TOKEN manquant.", file=sys.stderr)
        return 2
    only = {s.strip() for s in args.only.split(",") if s.strip()} or None
    if only != {"planning"} and not (cfg.moodle_token or cfg.moodle_ics_url or cfg.onedrive):
        print("Aucune source configurée (MOODLE_TOKEN, MOODLE_ICS_URL ou ONEDRIVE_*) : salles du planning seulement.")
        only = {"planning"}

    syncer = Syncer(cfg, NotionClient(cfg.notion_token))
    try:
        syncer.run(only)
    except NotionError as exc:
        print(syncer.report())
        print(f"Erreur Notion : {exc}", file=sys.stderr)
        return 1
    print(syncer.report())
    return 0


if __name__ == "__main__":
    sys.exit(main())
