import os
import json
import time
import re
import requests

from playwright.sync_api import sync_playwright

# =========================
# PATH SETUP
# =========================

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

DATA_DIR = os.path.join(BASE_DIR, "data")

HOTSTAR_FILE = os.path.join(DATA_DIR, "hotstar.json")
ZEE5_FILE = os.path.join(DATA_DIR, "zee5.json")

LOG_FILE = os.path.join(DATA_DIR, "log.txt")

os.makedirs(DATA_DIR, exist_ok=True)

# =========================
# INIT FILES
# =========================

def ensure_files():

    for f in [HOTSTAR_FILE, ZEE5_FILE]:

        if not os.path.exists(f):

            with open(f, "w") as fp:

                json.dump(
                    {"serials": []},
                    fp,
                    indent=2
                )

ensure_files()

# =========================
# LOG
# =========================

def log(msg):

    ts = time.strftime("%Y-%m-%d %H:%M:%S")

    line = f"[{ts}] {msg}"

    print(line)

    with open(LOG_FILE, "a") as f:

        f.write(line + "\n")

# =========================
# LOAD / SAVE
# =========================

def load_serial_data():

    data = {"serials": []}

    for f in [HOTSTAR_FILE, ZEE5_FILE]:

        try:

            with open(f) as fp:

                d = json.load(fp)

                data["serials"].extend(
                    d.get("serials", [])
                )

        except Exception as e:

            log(f"LOAD ERROR: {e}")

    return data

def save_data(data):

    hotstar = {"serials": []}

    zee5 = {"serials": []}

    for s in data["serials"]:

        if s.get("ott") == "zee5":

            zee5["serials"].append(s)

        else:

            hotstar["serials"].append(s)

    with open(HOTSTAR_FILE, "w") as f:

        json.dump(hotstar, f, indent=2)

    with open(ZEE5_FILE, "w") as f:

        json.dump(zee5, f, indent=2)

# =========================
# HOTSTAR
# =========================

def fetch_hotstar_episodes(show_id):

    url = f"https://www.hotstar.com/in/shows/{show_id}/{show_id}"

    log(f"[HOTSTAR] URL: {url}")

    episodes = []

    try:

        with sync_playwright() as p:

            browser = p.chromium.launch(
                headless=True,
                args=[
                    "--no-sandbox",
                    "--disable-dev-shm-usage"
                ]
            )

            context = browser.new_context(
                user_agent=(
                    "Mozilla/5.0 "
                    "(X11; Linux x86_64) "
                    "AppleWebKit/537.36 "
                    "(KHTML, like Gecko) "
                    "Chrome/124 Safari/537.36"
                )
            )

            page = context.new_page()

            page.set_viewport_size({
                "width": 1920,
                "height": 1080
            })

            page.goto(
                url,
                timeout=90000,
                wait_until="domcontentloaded"
            )

            log("[HOTSTAR] PAGE LOADED")

            # =========================
            # SCROLL
            # =========================

            for i in range(15):

                page.mouse.wheel(0, 8000)

                page.wait_for_timeout(1500)

                log(f"[HOTSTAR] SCROLL {i+1}")

            page.wait_for_timeout(5000)

            # =========================
            # EXTRACT LINKS
            # =========================

            links = page.eval_on_selector_all(
                "a[href]",
                "els => els.map(e => e.href)"
            )

            log(f"[HOTSTAR] TOTAL LINKS: {len(links)}")

            matched = 0

            for l in links:

                if "/watch/" not in l:
                    continue

                if f"/{show_id}/" not in l:
                    continue

                try:

                    parts = l.split("/")

                    idx = parts.index(show_id)

                    title_slug = parts[idx + 1]

                    episode_id = parts[idx + 2]

                    if episode_id.isdigit():

                        matched += 1

                        title = (
                            title_slug
                            .replace("-", " ")
                            .title()
                        )

                        ep = {
                            "episode_id": episode_id,
                            "title": title
                        }

                        episodes.append(ep)

                        log(
                            f"[HOTSTAR] FOUND "
                            f"{episode_id}"
                        )

                except Exception as ex:

                    log(
                        f"[HOTSTAR] "
                        f"PARSE FAIL: {ex}"
                    )

            log(f"[HOTSTAR] MATCHED: {matched}")

            browser.close()

    except Exception as e:

        log(f"[HOTSTAR] ERROR: {e}")

        return []

    # =========================
    # REMOVE DUPLICATES
    # =========================

    unique = {}

    for ep in episodes:

        unique[ep["episode_id"]] = ep

    final = sorted(
        unique.values(),
        key=lambda x: x["episode_id"],
        reverse=True
    )[:5]

    log(f"[HOTSTAR] FINAL: {final}")

    return final

# =========================
# ZEE5
# =========================

ZEE_TOKEN = "YOUR_TOKEN"

def slugify(title):

    title = title.lower()

    title = re.sub(
        r"[^\w\s-]",
        "",
        title
    )

    title = re.sub(
        r"\s+",
        "-",
        title
    )

    return title.strip("-")

def fetch_zee5_episodes(serial):

    if (
        "season_id" not in serial
        or
        "anchor" not in serial
    ):

        return serial.get("episodes", [])

    show_id = serial["show_id"]

    season_id = serial["season_id"]

    anchor = serial["anchor"]

    headers = {
        "User-Agent": "Mozilla/5.0",
        "X-Access-Token": ZEE_TOKEN
    }

    BASE_URL = (
        f"https://www.zee5.com/"
        f"tv-shows/details/"
        f"{serial['name']}/"
        f"{show_id}"
    )

    # =========================
    # FETCH
    # =========================

    def fetch(ep_id, direction):

        try:

            res = requests.get(
                (
                    "https://gwapi.zee5.com/"
                    "content/season/"
                    f"next_previous/{season_id}"
                ),
                headers=headers,
                params={
                    "episode_id": ep_id,
                    "type": direction,
                    "limit": 25,
                    "country": "IN"
                },
                timeout=20
            ).json()

        except Exception as e:

            log(f"[ZEE5] FETCH ERROR: {e}")

            return []

        out = []

        for key in [
            "episodes",
            "items",
            "assets",
            "result"
        ]:

            if (
                isinstance(res, dict)
                and
                key in res
            ):

                for ep in res[key]:

                    eid = ep.get("id")

                    title = (
                        ep.get("title")
                        or
                        ep.get("name")
                        or
                        ""
                    )

                    ep_no = (
                        ep.get("episode_number")
                        or
                        ep.get("episodeNo")
                        or
                        0
                    )

                    if eid:

                        out.append((
                            int(ep_no),
                            eid,
                            title
                        ))

        return out

    prev_eps = fetch(anchor, "previous")

    next_eps = fetch(anchor, "next")

    all_eps = (
        next_eps
        +
        prev_eps
        +
        [(999999, anchor, "ANCHOR")]
    )

    all_eps.sort(
        key=lambda x: x[0],
        reverse=True
    )

    # =========================
    # REMOVE DUPLICATES
    # =========================

    seen = set()

    clean = []

    for _, eid, title in all_eps:

        if eid not in seen:

            clean.append({
                "episode_id": eid,
                "title": title
            })

            seen.add(eid)

    old_n1 = serial.get("N1") or []

    old_ids = [
        x["episode_id"]
        for x in old_n1
    ]

    curr_ids = [
        x["episode_id"]
        for x in clean[:5]
    ]

    new_episode = None

    for eid in curr_ids:

        if eid not in old_ids:

            new_episode = eid

            break

    # =========================
    # FIRST TIME
    # =========================

    if not old_n1:

        final_order = curr_ids

        serial["anchor"] = (
            final_order[0]
            if final_order else None
        )

    else:

        # =========================
        # NEW EPISODE
        # =========================

        if new_episode:

            old_anchor = (
                old_n1[0]["episode_id"]
                if old_n1 else None
            )

            final_order = [new_episode]

            if (
                old_anchor
                and
                old_anchor != new_episode
            ):

                final_order.append(old_anchor)

            for e in old_n1:

                eid = e["episode_id"]

                if eid not in final_order:

                    final_order.append(eid)

            final_order = final_order[:5]

            serial["anchor"] = new_episode

        # =========================
        # NO CHANGE
        # =========================

        else:

            final_order = old_ids[:5]

    title_map = {
        x["episode_id"]: x["title"]
        for x in clean
    }

    final_output = []

    for eid in final_order[:5]:

        title = title_map.get(eid, "")

        url = (
            f"{BASE_URL}/"
            f"{slugify(title)}/"
            f"{eid}"
        )

        final_output.append({
            "episode_id": eid,
            "title": title,
            "url": url
        })

    serial["N"] = old_n1

    serial["N1"] = final_output

    log(
        f"[ZEE5] FINAL: "
        f"{[x['episode_id'] for x in final_output]}"
    )

    return final_output

# =========================
# MAIN
# =========================

def run_update():

    log("🚀 RUN START")

    data = load_serial_data()

    changed = False

    if not data["serials"]:

        log("⚠️ NO SERIALS FOUND")

        return

    for s in data["serials"]:

        name = s.get("name")

        ott = s.get("ott")

        log(f"\n[{ott.upper()}] {name}")

        old_eps = s.get("episodes", [])

        # =========================
        # FETCH
        # =========================

        if ott == "zee5":

            new_eps = fetch_zee5_episodes(s)

        else:

            new_eps = fetch_hotstar_episodes(
                s.get("show_id")
            )

        # =========================
        # FAILED
        # =========================

        if not new_eps:

            log("❌ NO EPISODES FETCHED")

            continue

        new_ids = [
            e["episode_id"]
            for e in new_eps
        ]

        old_ids = [
            e["episode_id"]
            for e in old_eps
        ]

        log(f"📦 OLD: {old_ids}")

        log(f"🆕 NEW: {new_ids}")

        # =========================
        # FIRST TIME
        # =========================

        if not old_eps:

            log("🆕 FIRST TIME LOAD")

            s["episodes"] = new_eps

            changed = True

            continue

        # =========================
        # DETECT CHANGE
        # =========================

        new_found = any(
            eid not in old_ids
            for eid in new_ids
        )

        if not new_found:

            log("⏭️ NO NEW EPISODE")

            continue

        updated = new_eps + old_eps

        seen = set()

        final = []

        for e in updated:

            if e["episode_id"] not in seen:

                final.append(e)

                seen.add(e["episode_id"])

        s["episodes"] = final[:5]

        changed = True

        log(
            f"✅ UPDATED: "
            f"{[e['episode_id'] for e in s['episodes']]}"
        )

    if changed:

        save_data(data)

        log("💾 JSON UPDATED")

    else:

        log("ℹ️ NO CHANGE")

    log("✅ DONE")

# =========================
# ENTRY
# =========================

if __name__ == "__main__":

    run_update()
