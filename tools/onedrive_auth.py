"""Autorise la synchro à lire un OneDrive (lecture seule) et affiche le jeton à stocker en secret.

Usage :
    python tools/onedrive_auth.py <MS_CLIENT_ID> perso    # compte Microsoft personnel
    python tools/onedrive_auth.py <MS_CLIENT_ID> ecole    # compte IPSA

Suis le lien affiché, saisis le code, connecte-toi avec le bon compte.
Le jeton affiché va dans le secret ONEDRIVE_PERSO_REFRESH_TOKEN ou ONEDRIVE_ECOLE_REFRESH_TOKEN.
"""

from __future__ import annotations

import sys
import time

import requests

SCOPES = "offline_access Files.Read User.Read"
TENANTS = {"perso": "consumers", "ecole": "organizations"}


def main() -> int:
    if len(sys.argv) < 3 or sys.argv[2] not in TENANTS:
        print(__doc__)
        return 1
    client_id, tenant = sys.argv[1], TENANTS[sys.argv[2]]
    base = f"https://login.microsoftonline.com/{tenant}/oauth2/v2.0"

    flow = requests.post(f"{base}/devicecode", data={"client_id": client_id, "scope": SCOPES}, timeout=30).json()
    if "device_code" not in flow:
        print(f"Erreur : {flow.get('error')} — {flow.get('error_description', '')[:300]}")
        return 1
    print(flow["message"])

    deadline = time.time() + int(flow.get("expires_in", 900))
    while time.time() < deadline:
        time.sleep(int(flow.get("interval", 5)))
        token = requests.post(
            f"{base}/token",
            data={
                "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                "client_id": client_id,
                "device_code": flow["device_code"],
            },
            timeout=30,
        ).json()
        if "refresh_token" in token:
            name = f"ONEDRIVE_{sys.argv[2].upper()}_REFRESH_TOKEN"
            print(f"\nOK. Copie cette valeur dans le secret GitHub {name} :\n\n{token['refresh_token']}\n")
            return 0
        if token.get("error") not in ("authorization_pending", "slow_down"):
            print(f"Erreur : {token.get('error')} — {token.get('error_description', '')[:300]}")
            return 1
    print("Délai dépassé, relance la commande.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
