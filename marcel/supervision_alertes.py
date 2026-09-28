"""Alertes Slack du tableau de supervision du Lab (tâche Hermes sans agent).

Copie de référence : sur le VPS, le script vit dans ~/.hermes/scripts/supervision_alertes.py
et tourne via la tâche Hermes « supervision-alertes » (toutes les 15 min, --no-agent).

Lit l'état publié par le dépôt JulienDepelchin/supervision et affiche :
  - les nouveaux changements d'état (events.json, au-delà du dernier seq vu) ;
  - une alerte si le superviseur lui-même n'a pas tourné depuis STALE_MIN minutes ;
  - une alerte si GitHub reste illisible MAX_ECHECS passages de suite.
Rien à signaler = aucune sortie = aucun message.
"""
import json
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

API = "https://api.github.com/repos/JulienDepelchin/supervision/contents/docs/data/"
PAGE = "https://juliendepelchin.github.io/supervision/"
STATE = Path.home() / ".hermes/state/supervision_alertes.json"
STALE_MIN = 90
MAX_ECHECS = 6  # passages toutes les 15 min -> 1 h 30
ICONES = {"ok": "🟢 OK", "echec": "🔴 En échec", "muet": "🟠 Muet",
          "desactive": "⚫ Désactivé", "inconnu": "⚪ Inconnu"}


def lire(nom):
    req = urllib.request.Request(API + nom, headers={
        "Accept": "application/vnd.github.raw+json", "User-Agent": "marcel-supervision"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.load(r)


def main():
    etat = json.loads(STATE.read_text()) if STATE.exists() else None
    lignes = []
    try:
        events, status = lire("events.json"), lire("status.json")
    except Exception as e:
        events, status, erreur = None, None, str(e)

    if etat is None:
        # Premier passage : on part du seq courant sans rejouer l'historique.
        etat = {"seq": events["seq"] if events else 0}
    etat.setdefault("stale_alerte", False)
    etat.setdefault("echecs_lecture", 0)

    if events is None:
        etat["echecs_lecture"] += 1
        if etat["echecs_lecture"] == MAX_ECHECS:
            lignes.append(f"• ⚠️ *Tableau de supervision illisible* depuis {MAX_ECHECS} passages : {erreur}")
    else:
        if etat["echecs_lecture"] >= MAX_ECHECS:
            lignes.append("• ✅ Le tableau de supervision est de nouveau lisible.")
        etat["echecs_lecture"] = 0
        nouveaux = [e for e in events["events"] if e["seq"] > etat["seq"]]
        for e in sorted(nouveaux, key=lambda e: e["seq"]):
            ligne = f"• *{e['label']}* : {ICONES.get(e['de'], e['de'])} → {ICONES.get(e['vers'], e['vers'])}"
            if e.get("detail"):
                ligne += f" — {e['detail']}"
            if e.get("url") and e["vers"] != "ok":
                ligne += f" (<{e['url']}|dernier run>)"
            lignes.append(ligne)
        etat["seq"] = max([etat["seq"]] + [e["seq"] for e in events["events"]])

        age = (datetime.now(timezone.utc)
               - datetime.fromisoformat(status["generated_at"].replace("Z", "+00:00"))).total_seconds() / 60
        if age > STALE_MIN and not etat["stale_alerte"]:
            lignes.append(f"• ⚠️ *Le superviseur ne tourne plus* : dernière vérification il y a {age / 60:.1f} h.")
            etat["stale_alerte"] = True
        elif age <= STALE_MIN and etat["stale_alerte"]:
            lignes.append("• ✅ Le superviseur tourne de nouveau.")
            etat["stale_alerte"] = False

    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(etat))
    if lignes:
        print("*Supervision du Lab*\n" + "\n".join(lignes) + f"\n<{PAGE}|Voir le tableau>")


if __name__ == "__main__":
    main()
