"""Mise à jour d'un secret GitHub Actions (pour conserver le jeton OneDrive renouvelé)."""

from __future__ import annotations

from base64 import b64encode

import requests
from nacl import encoding, public


def update_secret(repo: str, name: str, value: str, token: str, session: requests.Session | None = None) -> None:
    session = session or requests.Session()
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"}
    api = f"https://api.github.com/repos/{repo}/actions/secrets"
    key = session.get(f"{api}/public-key", headers=headers, timeout=30)
    key.raise_for_status()
    key_data = key.json()
    box = public.SealedBox(public.PublicKey(key_data["key"].encode(), encoding.Base64Encoder()))
    encrypted = b64encode(box.encrypt(value.encode())).decode()
    resp = session.put(
        f"{api}/{name}",
        headers=headers,
        json={"encrypted_value": encrypted, "key_id": key_data["key_id"]},
        timeout=30,
    )
    resp.raise_for_status()
