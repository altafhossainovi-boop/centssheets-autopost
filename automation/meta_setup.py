"""One-time Meta token setup.

Reads META_APP_ID, META_APP_SECRET and a short-lived META_USER_TOKEN from
automation/.env, then:
  1. exchanges the user token for a long-lived one (~60 days),
  2. reads the "Cents & Sheets" Page token from it (a Page token made from a
     long-lived user token does not expire),
  3. finds the Instagram business account linked to that Page,
  4. writes FB_PAGE_ID, FB_PAGE_TOKEN and IG_USER_ID back into .env.

Tokens are never printed in full.

    .venv/bin/python automation/meta_setup.py
"""
import sys
from pathlib import Path

import requests
from dotenv import dotenv_values, set_key

ENV = Path(__file__).with_name(".env")
PAGE_NAME = "Cents & Sheets"


def mask(token):
    return f"{token[:6]}…{token[-4:]}" if token else "(empty)"


def get(url, **params):
    r = requests.get(url, params=params, timeout=30)
    data = r.json()
    if "error" in data:
        sys.exit(f"Meta error: {data['error'].get('message')}")
    return data


def main():
    if not ENV.exists():
        sys.exit("automation/.env not found. Copy .env.example to .env and fill it first.")
    env = dotenv_values(ENV)
    for key in ("META_APP_ID", "META_APP_SECRET", "META_USER_TOKEN"):
        if not env.get(key):
            sys.exit(f"{key} is empty in automation/.env")
    graph = f"https://graph.facebook.com/{env.get('GRAPH_VERSION') or 'v26.0'}"

    long_user = get(
        f"{graph}/oauth/access_token",
        grant_type="fb_exchange_token",
        client_id=env["META_APP_ID"],
        client_secret=env["META_APP_SECRET"],
        fb_exchange_token=env["META_USER_TOKEN"],
    )["access_token"]
    print("Long-lived user token:", mask(long_user))

    pages = get(
        f"{graph}/me/accounts",
        fields="id,name,access_token,instagram_business_account{id,username}",
        access_token=long_user,
    )["data"]
    print("Pages this token can manage:", ", ".join(p["name"] for p in pages) or "none")
    page = next((p for p in pages if p["name"] == PAGE_NAME), None)
    if not page:
        sys.exit(f'Page "{PAGE_NAME}" not found. Select it when you click Allow in Graph API Explorer.')

    ig = page.get("instagram_business_account")
    if not ig:
        sys.exit("No Instagram business account is linked to the Page (or instagram_basic was not granted).")

    app_token = f"{env['META_APP_ID']}|{env['META_APP_SECRET']}"
    info = get(f"{graph}/debug_token", input_token=page["access_token"], access_token=app_token)["data"]
    expires = "never" if not info.get("expires_at") else info["expires_at"]
    print("Page token scopes:", ", ".join(sorted(info.get("scopes", []))))
    print("Page token expires:", expires)

    set_key(ENV, "FB_PAGE_ID", page["id"], quote_mode="never")
    set_key(ENV, "FB_PAGE_TOKEN", page["access_token"], quote_mode="never")
    set_key(ENV, "IG_USER_ID", ig["id"], quote_mode="never")
    set_key(ENV, "META_USER_TOKEN", "", quote_mode="never")
    print(f"Saved: Page {page['name']} ({page['id']}), Instagram @{ig.get('username')} ({ig['id']}), Page token {mask(page['access_token'])}")


if __name__ == "__main__":
    main()
