"""Reply to BUDGET comments on our recent reels.

Instagram: a threaded reply that @mentions the commenter and points them to their inbox
(Meta Business Suite's "Comment to message" automation sends the DM with the links).
Facebook: a threaded reply with the three links, since Facebook comments make links clickable.

Each comment gets one reply; answered comment ids are kept in automation/replied.json.

    .venv/bin/python automation/comment_responder.py --dry-run
    .venv/bin/python automation/comment_responder.py
"""
import argparse
import json
import os
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
LINKS = json.loads((ROOT / "content" / "links.json").read_text())
STATE = Path(__file__).with_name("replied.json")

load_dotenv(Path(__file__).with_name(".env"))
GRAPH = f"https://graph.facebook.com/{os.environ.get('GRAPH_VERSION') or 'v26.0'}"
KEYWORD = re.compile(r"budget", re.I)
LOOKBACK = timedelta(days=14)
MAX_REPLIES = 25

IG_REPLY = "@{username} Check your inbox! I just sent you the links. If you don't see them, look in your message requests."
FB_REPLY = (
    "Hi {name}! Here are your budget links:\n\n"
    f"Free Paycheck Budget Starter (Google Sheets + Excel): {LINKS['FREE_URL']}\n"
    f"Free 52-Week Savings Challenge printable: {LINKS['FREE52_URL']}\n"
    f"The full Paycheck to Paycheck Budget System: {LINKS['PAID_URL']}\n\n"
    "Save this for your next payday!"
)


def env(key):
    value = os.environ.get(key)
    if not value:
        sys.exit(f"{key} is not set (automation/.env or CI secret).")
    return value


def call(method, path, **params):
    params["access_token"] = env("FB_PAGE_TOKEN")
    r = requests.request(method, f"{GRAPH}/{path}", params=params if method == "GET" else None,
                         data=params if method == "POST" else None, timeout=60)
    data = r.json()
    if "error" in data:
        raise RuntimeError(f"{method} {path}: {data['error'].get('message')}")
    return data


def pages(path, **params):
    """Yield items from every page of a list endpoint."""
    data = call("GET", path, **params)
    while True:
        yield from data.get("data", [])
        nxt = data.get("paging", {}).get("next")
        if not nxt:
            return
        data = requests.get(nxt, timeout=60).json()


def recent(ts):
    return datetime.fromisoformat(ts.replace("+0000", "+00:00")) > datetime.now(timezone.utc) - LOOKBACK


def instagram_targets():
    ig = env("IG_USER_ID")
    me = call("GET", ig, fields="username")["username"]
    for media in pages(f"{ig}/media", fields="id,timestamp,comments_count", limit=25):
        if not recent(media["timestamp"]) or not media.get("comments_count"):
            continue
        for c in pages(f"{media['id']}/comments", fields="id,text,username,replies{username}", limit=50):
            ours = any(r.get("username") == me for r in c.get("replies", {}).get("data", []))
            if c.get("username") != me and KEYWORD.search(c.get("text", "")) and not ours:
                yield c["id"], IG_REPLY.format(username=c["username"]), f"@{c['username']}: {c['text']}"


def facebook_targets():
    page = env("FB_PAGE_ID")
    for reel in pages(f"{page}/video_reels", fields="id,created_time", limit=25):
        if not recent(reel["created_time"]):
            continue
        for c in pages(f"{reel['id']}/comments", fields="id,message,from{id,name},comments{from{id}}",
                       filter="toplevel", limit=50):
            author = c.get("from") or {}
            ours = any((r.get("from") or {}).get("id") == page for r in c.get("comments", {}).get("data", []))
            if author.get("id") != page and KEYWORD.search(c.get("message", "")) and not ours:
                name = (author.get("name") or "").split(" ")[0] or "there"
                yield c["id"], FB_REPLY.format(name=name), f"{author.get('name', '?')}: {c['message']}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="list matching comments, reply to none")
    args = ap.parse_args()

    state = json.loads(STATE.read_text()) if STATE.exists() else {"ig": [], "fb": []}
    sent = 0
    for platform, targets, endpoint in (("ig", instagram_targets, "replies"), ("fb", facebook_targets, "comments")):
        try:
            for comment_id, reply, label in targets():
                if comment_id in state[platform]:
                    continue
                if sent >= MAX_REPLIES:
                    print(f"Reached {MAX_REPLIES} replies this run; the rest wait for the next run.")
                    break
                print(f"[{platform}] {label[:80]}")
                if args.dry_run:
                    continue
                call("POST", f"{comment_id}/{endpoint}", message=reply)
                state[platform].append(comment_id)
                STATE.write_text(json.dumps(state, indent=1))
                sent += 1
                time.sleep(2)
        except RuntimeError as err:
            print(f"[{platform}] skipped: {err}")
    print("Dry run: nothing posted." if args.dry_run else f"Replied to {sent} comment(s).")


if __name__ == "__main__":
    main()
