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
                json.dump({"serials": []}, fp, indent=2)

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
                data["serials"].extend(d.get("serials", []))
        except:
            pass
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

    episodes = []
    url = f"https://www.hotstar.com/in/shows/{show_id}/{show_id}"

    log(f"[HOTSTAR] 🌐 {url}")

    try:
        with sync_playwright() as p:

            browser = p.chromium.launch(
                headless=True,
                args=[
                    "--no-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-blink-features=AutomationControlled"
                ]
            )

            context = browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36"
            )

            page = context.new_page()

            page.goto(url, timeout=60000, wait_until="networkidle")

            # scroll to load episodes
            for _ in range(6):
                page.mouse.wheel(0, 4000)
                page.wait_for_timeout(1500)

            page.wait_for_timeout(10000)

            links = page.eval_on_selector_all(
                "a[href]",
                "els => els.map(e => e.href)"
            )

            log(f"[HOTSTAR] 🔗 Total links: {len(links)}")

            for l in links:
                if f"/{show_id}/" in l and "/watch" in l:
                    for p_id in l.split("/"):
                        if p_id.isdigit():
                            episodes.append(p_id)

            browser.close()

    except Exception as e:
        log(f"[HOTSTAR] ❌ ERROR: {e}")
        return []

    unique = sorted(set(episodes), reverse=True)
    final = unique[:5]

    log(f"[HOTSTAR] 🎯 FINAL: {final}")

    return [{"episode_id": e, "title": f"Episode {e}"} for e in final]

# =========================
# ZEE5
# =========================
ZEE_TOKEN = "PASTE_YOUR_TOKEN_HERE"

def slugify(title):
    title = title.lower()
    title = re.sub(r"[^\w\s-]", "", title)
    title = re.sub(r"\s+", "-", title)
    return title.strip("-")

def fetch_zee5_episodes(serial):

    if "season_id" not in serial or "anchor" not in serial:
        return serial.get("episodes", [])

    show_id = serial["show_id"]
    season_id = serial["season_id"]
    anchor = serial["anchor"]

    headers = {
        "User-Agent": "Mozilla/5.0",
        "X-Access-Token": ZEE_TOKEN
    }

    BASE_URL = f"https://www.zee5.com/tv-shows/details/{serial['name']}/{show_id}"

    def fetch(ep_id, direction):
        try:
            res = requests.get(
                f"https://gwapi.zee5.com/content/season/next_previous/{season_id}",
                headers=headers,
                params={
                    "episode_id": ep_id,
                    "type": direction,
                    "limit": 25,
                    "country": "IN"
                },
                timeout=15
            ).json()
        except:
            return []

        out = []
        for key in ["episodes", "items", "assets", "result"]:
            if key in res:
                for ep in res[key]:
                    eid = ep.get("id")
                    title = ep.get("title") or ep.get("name") or ""
                    ep_no = ep.get("episode_number") or 0
                    if eid:
                        out.append((int(ep_no), eid, title))
        return out

    prev_eps = fetch(anchor, "previous")
    next_eps = fetch(anchor, "next")

    all_eps = next_eps + prev_eps + [(999999, anchor, "ANCHOR")]
    all_eps.sort(key=lambda x: x[0], reverse=True)

    seen = set()
    clean = []

    for _, eid, title in all_eps:
        if eid not in seen:
            clean.append({"episode_id": eid, "title": title})
            seen.add(eid)

    old_n1 = serial.get("N1") or []
    old_ids = [x["episode_id"] for x in old_n1]
    curr_ids = [x["episode_id"] for x in clean[:5]]

    new_episode = None
    for eid in curr_ids:
        if eid not in old_ids:
            new_episode = eid
            break

    if not old_n1:
        final_order = curr_ids
        serial["anchor"] = final_order[0] if final_order else None
    else:
        if new_episode:
            old_anchor = old_n1[0]["episode_id"] if old_n1 else None
            final_order = [new_episode]

            if old_anchor and old_anchor != new_episode:
                final_order.append(old_anchor)

            for e in old_n1:
                eid = e["episode_id"]
                if eid not in final_order:
                    final_order.append(eid)

            final_order = final_order[:5]
            serial["anchor"] = new_episode
        else:
            final_order = old_ids[:5]

    title_map = {x["episode_id"]: x["title"] for x in clean}

    final_output = []
    for eid in final_order[:5]:
        title = title_map.get(eid, "")
        url = f"{BASE_URL}/{slugify(title)}/{eid}"

        final_output.append({
            "episode_id": eid,
            "title": title,
            "url": url
        })

    serial["N"] = old_n1
    serial["N1"] = final_output

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

        if ott == "zee5":
            new_eps = fetch_zee5_episodes(s)
        else:
            new_eps = fetch_hotstar_episodes(s.get("show_id"))

        if not new_eps:
            log("❌ NO EPISODES FETCHED")
            continue

        new_ids = [e["episode_id"] for e in new_eps]
        old_ids = [e["episode_id"] for e in old_eps]

        log(f"📦 OLD: {old_ids}")
        log(f"🆕 NEW: {new_ids}")

        # first time
        if not old_eps:
            log("🆕 FIRST TIME LOAD")
            s["episodes"] = new_eps
            changed = True
            continue

        # detect new
        new_found = any(eid not in old_ids for eid in new_ids)

        if not new_found:
            log("⏭️ NO NEW EPISODE")
            continue

        # update list
        updated = new_eps + old_eps

        seen = set()
        final = []

        for e in updated:
            if e["episode_id"] not in seen:
                final.append(e)
                seen.add(e["episode_id"])

        s["episodes"] = final[:5]
        changed = True

        log(f"✅ UPDATED: {[e['episode_id'] for e in s['episodes']]}")

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
