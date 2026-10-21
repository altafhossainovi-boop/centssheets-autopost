"""Post one day's reel from content/calendar.json to Instagram and the Facebook Page.

The video file is uploaded straight to Meta (resumable upload), so no public
video host is needed.

    .venv/bin/python automation/post_reel.py --day 1 --dry-run
    .venv/bin/python automation/post_reel.py --day 1 --only ig
    .venv/bin/python automation/post_reel.py            # today's day, from REELS_START_DATE

Already-posted days are recorded in automation/posted.json and skipped.
"""
import argparse
import json
import os
import sys
import time
from datetime import date, datetime, timezone
from pathlib import Path

import requests
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
CALENDAR = ROOT / "content" / "calendar.json"
RENDERS = ROOT / "content" / "reels" / "renders"
POSTED = Path(__file__).with_name("posted.json")

load_dotenv(Path(__file__).with_name(".env"))
VERSION = os.environ.get("GRAPH_VERSION") or "v26.0"
GRAPH = f"https://graph.facebook.com/{VERSION}"


def env(key):
    value = os.environ.get(key)
    if not value:
        sys.exit(f"{key} is not set (automation/.env or CI secret).")
    return value


def check(r):
    try:
        data = r.json()
    except ValueError:
        sys.exit(f"Meta returned {r.status_code}: {r.text[:300]}")
    if r.status_code >= 400 or "error" in data:
        err = data.get("error", data)
        sys.exit(f"Meta error ({r.status_code}): {err.get('message', err)}")
    return data


def rupload(url, token, video):
    with open(video, "rb") as f:
        r = requests.post(
            url,
            headers={
                "Authorization": f"OAuth {token}",
                "offset": "0",
                "file_size": str(video.stat().st_size),
            },
            data=f.read(),
            timeout=600,
        )
    return check(r)


def instagram_container(video, caption, token, attempts=3):
    """Create a resumable Reels container and upload the video, retrying with a fresh container."""
    ig = env("IG_USER_ID")
    for attempt in range(1, attempts + 1):
        container = check(requests.post(f"{GRAPH}/{ig}/media", data={
            "media_type": "REELS",
            "upload_type": "resumable",
            "caption": caption,
            "share_to_feed": "true",
            "access_token": token,
        }, timeout=60))
        with open(video, "rb") as f:
            r = requests.post(container["uri"], headers={
                "Authorization": f"OAuth {token}",
                "offset": "0",
                "file_size": str(video.stat().st_size),
            }, data=f.read(), timeout=600)
        if r.ok and '"success":true' in r.text.replace(" ", ""):
            return container
        print(f"Instagram upload attempt {attempt} failed ({r.status_code}): {r.text[:300]}")
        time.sleep(20 * attempt)
    sys.exit("Instagram upload failed after retries.")


def post_instagram(video, caption, token, publish=True):
    ig = env("IG_USER_ID")
    container = instagram_container(video, caption, token)

    for _ in range(60):
        status = check(requests.get(f"{GRAPH}/{container['id']}", params={
            "fields": "status_code,status", "access_token": token}, timeout=30))
        if status.get("status_code") == "FINISHED":
            break
        if status.get("status_code") in ("ERROR", "EXPIRED"):
            sys.exit(f"Instagram could not process the video: {status.get('status')}")
        time.sleep(10)
    else:
        sys.exit("Instagram processing timed out after 10 minutes.")
    if not publish:
        return {"id": container["id"], "url": "(upload test, not published)"}

    media = check(requests.post(f"{GRAPH}/{ig}/media_publish", data={
        "creation_id": container["id"], "access_token": token}, timeout=60))
    link = check(requests.get(f"{GRAPH}/{media['id']}", params={
        "fields": "permalink", "access_token": token}, timeout=30))
    return {"id": media["id"], "url": link.get("permalink")}


def post_facebook(video, caption, token):
    page = env("FB_PAGE_ID")
    start = check(requests.post(f"{GRAPH}/{page}/video_reels", data={
        "upload_phase": "start", "access_token": token}, timeout=60))
    rupload(start["upload_url"], token, video)
    check(requests.post(f"{GRAPH}/{page}/video_reels", data={
        "upload_phase": "finish",
        "video_id": start["video_id"],
        "video_state": "PUBLISHED",
        "description": caption,
        "access_token": token,
    }, timeout=60))
    return {"id": start["video_id"], "url": f"https://www.facebook.com/reel/{start['video_id']}"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--day", type=int, help="calendar day (default: the earliest unposted day up to today)")
    ap.add_argument("--only", choices=["ig", "fb"], help="post to one platform only")
    ap.add_argument("--dry-run", action="store_true", help="show what would be posted, post nothing")
    ap.add_argument("--upload-test", action="store_true",
                    help="upload to Instagram and wait for processing, but do not publish")
    args = ap.parse_args()

    days = {d["day"]: d for d in json.loads(CALENDAR.read_text())["days"]}
    posted = json.loads(POSTED.read_text()) if POSTED.exists() else {}
    wanted = [args.only] if args.only else ["ig", "fb"]

    def missing(day):
        return [t for t in wanted if t not in posted.get(days[day]["reel"]["id"], {})]

    day = args.day
    if day is None:
        start = date.fromisoformat(env("REELS_START_DATE"))
        today = (datetime.now(timezone.utc).date() - start).days + 1
        # A day that failed earlier is posted first, one reel per run.
        day = next((d for d in sorted(days) if d <= today and missing(d)), today)
    if day not in days:
        print(f"Day {day} is outside the calendar (1–{max(days)}). Nothing to post.")
        return

    reel = days[day]["reel"]
    video = RENDERS / f"{reel['id']}.mp4"
    if not video.exists():
        sys.exit(f"Video not rendered yet: {video.relative_to(ROOT)}")

    print(f"Day {day} · {reel['id']} · {video.name} ({video.stat().st_size / 1e6:.1f} MB)")
    print("Caption:", reel["caption"].splitlines()[0], "…")
    token = env("FB_PAGE_TOKEN")
    if args.upload_test:
        print("Upload test:", post_instagram(video, reel["caption"], token, publish=False)["url"])
        return

    targets = missing(day)
    if not targets:
        print("Already posted to every target. Skipping.")
        return
    print("Targets:", ", ".join(targets))
    if args.dry_run:
        print("Dry run: nothing posted.")
        return

    done = posted.setdefault(reel["id"], {})
    for target in targets:
        result = (post_instagram if target == "ig" else post_facebook)(video, reel["caption"], token)
        done[target] = {**result, "at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
        POSTED.write_text(json.dumps(posted, indent=1))
        print(f"Posted to {target}: {result['url']}")


if __name__ == "__main__":
    main()
