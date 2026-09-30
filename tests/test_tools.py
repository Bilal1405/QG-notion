import base64
import hashlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

import moodle_token  # noqa: E402


def test_decode_launch_url():
    signature = hashlib.md5(b"https://moodle.ipsa.fr424242").hexdigest()
    payload = base64.b64encode(f"{signature}:::abc123:::private".encode()).decode().rstrip("=")
    token, valid = moodle_token.decode(f"moodlemobile://token={payload}")
    assert (token, valid) == ("abc123", True)


def test_decode_flags_wrong_site():
    payload = base64.b64encode(b"deadbeef:::abc123").decode()
    assert moodle_token.decode(f"'moodlemobile://token={payload}'") == ("abc123", False)
