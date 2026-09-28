"""Superviseur des jobs planifiés du Lab.

Lit jobs.yml, interroge l'API GitHub Actions (et les heartbeats reçus),
calcule l'état de chaque job et écrit dans docs/data/ :
  - status.json : état courant de chaque job (lu par la page et par Marcel)
  - runs.json   : historique des runs sur HISTORY_DAYS jours
  - events.json : journal des changements d'état (alertes)

Usage :
  python supervise.py                       # vérification complète
  python supervise.py --heartbeat '<json>'  # enregistre un heartbeat puis vérifie
Variable d'environnement : GH_TOKEN (jeton en lecture sur Actions).
"""
import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml

ROOT = Path(__file__).parent
DATA = ROOT / "docs" / "data"
HISTORY_DAYS = 7
MAX_EVENTS = 300
API = "https://api.github.com"
# Conclusions ignorées pour juger de l'échec (annulations dues à la concurrence, etc.)
NEUTRAL = {"cancelled", "skipped", "neutral", "stale"}


def now():
    return datetime.now(timezone.utc)


def iso(dt):
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_iso(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def parse_duration(s):
    m = re.fullmatch(r"(\d+)\s*([mhd])", str(s).strip())
    if not m:
        raise ValueError(f"Durée invalide : {s!r} (attendu : 40m, 3h, 8d)")
    n, unit = int(m.group(1)), m.group(2)
    return timedelta(**{{"m": "minutes", "h": "hours", "d": "days"}[unit]: n})


def load_json(name, default):
    p = DATA / name
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else default


def save_json(name, obj, compact=False):
    DATA.mkdir(parents=True, exist_ok=True)
    txt = json.dumps(obj, ensure_ascii=False, **({"separators": (",", ":")} if compact else {"indent": 1}))
    (DATA / name).write_text(txt, encoding="utf-8")


def gh(path):
    req = urllib.request.Request(API + path, headers={
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "lab-supervision",
    })
    token = os.environ.get("GH_TOKEN")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def fetch_github(owner, job):
    """Renvoie (runs, workflow_state) pour un job GitHub."""
    repo = f"/repos/{owner}/{job['repo']}"
    wf = job.get("workflow")
    if wf:
        state = gh(f"{repo}/actions/workflows/{wf}")["state"]
        data = gh(f"{repo}/actions/workflows/{wf}/runs?per_page=100")
    else:
        wfs = gh(f"{repo}/actions/workflows")["workflows"]
        state = "active" if any(w["state"] == "active" for w in wfs) else (wfs[0]["state"] if wfs else "absent")
        data = gh(f"{repo}/actions/runs?per_page=100")
    runs = []
    for r in data["workflow_runs"]:
        start = r.get("run_started_at") or r["created_at"]
        dur = None
        if r["status"] == "completed":
            dur = round((parse_iso(r["updated_at"]) - parse_iso(start)).total_seconds())
        runs.append({
            "id": r["id"],
            "start": start,
            "dur": dur,
            "status": r["status"],
            "conclusion": r["conclusion"],
            "event": r["event"],
            "url": r["html_url"],
        })
    return runs, state


def merge_runs(old, new, cutoff):
    by_id = {r["id"]: r for r in old}
    by_id.update({r["id"]: r for r in new})
    kept = [r for r in by_id.values() if parse_iso(r["start"]) >= cutoff]
    return sorted(kept, key=lambda r: r["start"], reverse=True)


def evaluate(job, runs, wf_state, t):
    """Calcule l'état : ok, echec, muet, desactive, inconnu."""
    last = runs[0] if runs else None
    last_done = next((r for r in runs if r["status"] == "completed"
                      and r["conclusion"] not in NEUTRAL), None)
    silence = parse_duration(job["max_silence"])
    info = {
        "dernier_run": last["start"] if last else None,
        "derniere_conclusion": last_done["conclusion"] if last_done else None,
        "dernier_url": (last_done or last or {}).get("url"),
    }
    if wf_state and wf_state != "active":
        return "desactive", f"Workflow {wf_state}", info
    if last is None:
        return "muet", "Aucun run dans l'historique", info
    age = t - parse_iso(last["start"])
    if age > silence:
        h = age.total_seconds() / 3600
        return "muet", f"Aucun run depuis {h:.1f} h (seuil {job['max_silence']})", info
    if last_done and last_done["conclusion"] != "success":
        return "echec", f"Dernier run : {last_done['conclusion']}", info
    return "ok", "", info


def record_heartbeat(payload, runs_by_job, jobs):
    hb = json.loads(payload) if isinstance(payload, str) else payload
    job_id = hb["job"]
    if job_id not in {j["id"] for j in jobs}:
        sys.exit(f"Heartbeat pour un job inconnu : {job_id}")
    t = now()
    start = hb.get("start") or iso(t)
    run = {
        "id": f"hb-{start}",
        "start": start,
        "dur": hb.get("duration"),
        "status": "completed",
        "conclusion": "success" if hb.get("status", "success") == "success" else "failure",
        "event": "heartbeat",
        "url": hb.get("url"),
        "message": (hb.get("message") or "")[:300],
    }
    runs_by_job.setdefault(job_id, []).insert(0, run)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--heartbeat", help="JSON {job, status, duration?, message?, start?}")
    args = ap.parse_args()

    cfg = yaml.safe_load((ROOT / "jobs.yml").read_text(encoding="utf-8"))
    jobs, owner = cfg["jobs"], cfg["owner"]
    t = now()
    cutoff = t - timedelta(days=HISTORY_DAYS)

    runs_by_job = load_json("runs.json", {})
    prev_status = {j["id"]: j for j in load_json("status.json", {}).get("jobs", [])}
    events = load_json("events.json", {"seq": 0, "events": []})

    if args.heartbeat:
        record_heartbeat(args.heartbeat, runs_by_job, jobs)

    out = []
    for job in jobs:
        jid = job["id"]
        old = runs_by_job.get(jid, [])
        wf_state = None
        try:
            if job["source"] == "github":
                new, wf_state = fetch_github(owner, job)
                runs = merge_runs(old, new, cutoff)
            else:
                runs = merge_runs(old, [], cutoff)
            state, detail, info = evaluate(job, runs, wf_state, t)
        except (urllib.error.URLError, KeyError, ValueError) as e:
            runs = old
            state, detail, info = "inconnu", f"Lecture impossible : {e}", {}
        runs_by_job[jid] = runs

        prev = prev_status.get(jid, {}).get("etat")
        if prev is not None and prev != state:
            events["seq"] += 1
            events["events"].insert(0, {
                "seq": events["seq"], "at": iso(t), "job": jid, "label": job["label"],
                "de": prev, "vers": state, "detail": detail, "url": info.get("dernier_url"),
            })

        out.append({
            "id": jid, "projet": job["projet"], "label": job["label"],
            "source": job["source"], "declencheur": job.get("declencheur", ""),
            "repo": f"{owner}/{job['repo']}" if job.get("repo") else None,
            "max_silence": job["max_silence"], "etat": state, "detail": detail,
            "depuis": prev_status.get(jid, {}).get("depuis") if prev == state else iso(t),
            **info,
        })

    events["events"] = events["events"][:MAX_EVENTS]
    runs_by_job = {k: v for k, v in runs_by_job.items() if k in {j["id"] for j in jobs}}
    save_json("runs.json", runs_by_job, compact=True)
    save_json("events.json", events)
    save_json("status.json", {"generated_at": iso(t), "jobs": out})

    for j in out:
        print(f"{j['etat']:10} {j['id']:28} {j['detail']}")


if __name__ == "__main__":
    main()
