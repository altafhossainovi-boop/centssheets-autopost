"""Ask for the Meta App Secret and the Graph API Explorer user token (hidden
input), save them to automation/.env, then run meta_setup.py.

A value already saved in the right format is not asked again; pass
--new-token to replace the user token.

    .venv/bin/python automation/set_secrets.py
"""
import re
import sys
from getpass import getpass
from pathlib import Path

from dotenv import dotenv_values, set_key

import meta_setup

ENV = Path(__file__).with_name(".env")
SECRET_RE = re.compile(r"[0-9a-f]{32}")


def ask(label, valid, hint):
    while True:
        value = getpass(f"{label} (paste, then Enter — nothing will show): ").strip()
        if valid(value):
            return value
        print(f"That doesn't look right: {hint} Try again.")


if __name__ == "__main__":
    env = dotenv_values(ENV)

    if not SECRET_RE.fullmatch(env.get("META_APP_SECRET") or ""):
        secret = ask(
            "App Secret",
            lambda v: SECRET_RE.fullmatch(v) is not None,
            "the App Secret is 32 characters of 0-9 and a-f (a token starts with EAA).",
        )
        set_key(ENV, "META_APP_SECRET", secret, quote_mode="never")
        print("App Secret saved.")

    if "--new-token" in sys.argv or not (env.get("META_USER_TOKEN") or "").startswith("EAA"):
        token = ask(
            "User access token",
            lambda v: v.startswith("EAA") and len(v) > 50,
            "the token from Graph API Explorer starts with EAA.",
        )
        set_key(ENV, "META_USER_TOKEN", token, quote_mode="never")
        print("User token saved.")

    print("Running meta_setup.py …\n")
    meta_setup.main()
