"""Configuration : identifiants des bases Notion et lecture des variables d'environnement."""

from __future__ import annotations

import os
from dataclasses import dataclass, field

NOTION_VERSION = "2025-09-03"

# Data sources Notion du QG (identifiants non secrets : inutiles sans le jeton d'intégration).
DATA_SOURCES = {
    "cours": "7830f406-2a6a-4137-8a98-6decf2b78c9e",
    "taches": "92fdca93-3ed9-4717-a0a5-1a9ee52791be",
    "ressources": "e7508ffa-de3d-40d1-8697-4bb740d1bcec",
    "annonces": "8cb421da-8a9c-474d-a3bc-2adccbbd086d",
    "notes_moodle": "7d87b2f5-592d-47a0-bf0f-b978e471e234",
    "planning": "4ac769b1-4051-427c-ad57-572f15daca72",
}


@dataclass
class OneDriveAccount:
    key: str  # "perso" ou "ecole"
    label: str  # valeur du select « Source » dans Ressources
    refresh_token: str
    root: str
    tenant: str
    secret_name: str  # nom du secret GitHub à mettre à jour après rotation


@dataclass
class Config:
    notion_token: str
    moodle_url: str = "https://moodle.ipsa.fr"
    moodle_token: str = ""
    moodle_ics_url: str = ""
    ms_client_id: str = ""
    onedrive: list[OneDriveAccount] = field(default_factory=list)
    github_repo: str = ""
    github_secrets_token: str = ""
    dry_run: bool = False
    max_creates: int = 600
    announcements_days: int = 120

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None, dry_run: bool = False) -> "Config":
        env = dict(os.environ if env is None else env)

        def get(name: str, default: str = "") -> str:
            return (env.get(name) or default).strip()

        accounts = []
        for key, label, default_root in (
            ("PERSO", "OneDrive perso", "IPSA/IPSA_Année_2"),
            ("ECOLE", "OneDrive école", ""),
        ):
            token = get(f"ONEDRIVE_{key}_REFRESH_TOKEN")
            if token:
                accounts.append(
                    OneDriveAccount(
                        key=key.lower(),
                        label=label,
                        refresh_token=token,
                        root=get(f"ONEDRIVE_{key}_ROOT", default_root).strip("/"),
                        tenant=get(f"ONEDRIVE_{key}_TENANT", "common"),
                        secret_name=f"ONEDRIVE_{key}_REFRESH_TOKEN",
                    )
                )

        return cls(
            notion_token=get("NOTION_TOKEN"),
            moodle_url=get("MOODLE_URL", "https://moodle.ipsa.fr").rstrip("/"),
            moodle_token=get("MOODLE_TOKEN"),
            moodle_ics_url=get("MOODLE_ICS_URL"),
            ms_client_id=get("MS_CLIENT_ID"),
            onedrive=accounts,
            github_repo=get("GITHUB_REPOSITORY"),
            github_secrets_token=get("GH_SECRETS_TOKEN"),
            dry_run=dry_run,
            max_creates=int(get("MAX_CREATES", "600")),
        )
