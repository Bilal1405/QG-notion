"""Récupère le jeton web service Moodle quand la connexion se fait par compte Microsoft (SSO).

1. Connecte-toi normalement sur Moodle dans ton navigateur (bouton Microsoft IPSA).
2. Ouvre l'outil de développement (F12) → onglet Console.
3. Dans le même onglet, va sur :
   https://moodle.ipsa.fr/admin/tool/mobile/launch.php?service=moodle_mobile_app&passport=424242&urlscheme=moodlemobile
4. La console affiche une erreur « Failed to launch 'moodlemobile://token=…' ».
   Copie l'adresse complète moodlemobile://token=… (clic droit → Copy link address, ou sélection).
5. Lance :  python tools/moodle_token.py "moodlemobile://token=…"

Le jeton affiché est à coller dans le secret GitHub MOODLE_TOKEN. Ne le partage pas.
"""

from __future__ import annotations

import base64
import hashlib
import sys

PASSPORT = "424242"


def decode(launch_url: str, site_url: str = "https://moodle.ipsa.fr") -> tuple[str, bool]:
    """Renvoie (jeton, signature_valide)."""
    payload = launch_url.split("token=", 1)[-1].strip().strip("'\"")
    payload += "=" * (-len(payload) % 4)
    parts = base64.b64decode(payload).decode().split(":::")
    if len(parts) < 2:
        raise ValueError("format inattendu : ce n'est pas une adresse moodlemobile://token=…")
    signature, token = parts[0], parts[1]
    expected = hashlib.md5((site_url.rstrip("/") + PASSPORT).encode()).hexdigest()
    return token, signature == expected


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 1
    site = sys.argv[2] if len(sys.argv) > 2 else "https://moodle.ipsa.fr"
    token, valid = decode(sys.argv[1], site)
    if not valid:
        print("Attention : signature inattendue (adresse du site différente ?). Jeton quand même extrait.")
    print(f"MOODLE_TOKEN = {token}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
