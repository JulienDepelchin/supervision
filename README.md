# Supervision du Lab

Tableau de bord des jobs planifiés (crons GitHub, crons Cloudflare, VPS).
Page : https://juliendepelchin.github.io/supervision/

Toutes les 30 min, le workflow `Supervision` lit l'API GitHub Actions pour chaque job de `jobs.yml`,
calcule son état et commite le résultat dans `docs/data/` :

| État | Signification |
|---|---|
| OK | dernier run réussi, dans le délai attendu |
| En échec | le dernier run terminé a échoué |
| Muet | aucun run depuis plus de `max_silence` (cron Cloudflare en panne, VPS arrêté…) |
| Désactivé | workflow désactivé sur GitHub (à la main, ou après 60 jours d'inactivité du dépôt) |
| Inconnu | l'API n'a pas pu être lue (jeton, dépôt renommé…) |

Fichiers publiés : `data/status.json` (état courant), `data/runs.json` (7 jours de runs),
`data/events.json` (changements d'état, numérotés par `seq`).

## Installation

1. Créer le dépôt `JulienDepelchin/supervision` (public) et y pousser ce dossier.
2. **Jeton de lecture** : GitHub > photo de profil > *Settings* > *Developer settings* >
   *Personal access tokens* > *Fine-grained tokens* > *Generate new token*.
   - *Repository access* : *Only select repositories* → les dépôts surveillés (dont `veille_data_gouv`).
   - *Permissions* > *Repository permissions* : **Actions : Read-only** (*Metadata : Read-only* est ajouté d'office).
   - Expiration : 1 an maximum ; noter la date de renouvellement.
3. Dans le dépôt `supervision` : *Settings* > *Secrets and variables* > *Actions* > *New repository secret*,
   nom `SUPERVISION_TOKEN`, valeur = le jeton.
4. *Settings* > *Pages* : *Deploy from a branch*, branche `main`, dossier `/docs`.
5. Onglet *Actions* > *Supervision* > *Run workflow* pour un premier passage.

## Ajouter un job

Ajouter une entrée dans `jobs.yml`. Choisir `max_silence` avec une marge d'environ trois fois
l'intervalle normal : les crons GitHub prennent régulièrement 30 min à plusieurs heures de retard.

## Jobs hors GitHub : heartbeat (ex. veille RAA sur le VPS)

Le job signale chaque passage en lançant le workflow `Supervision` avec un champ `heartbeat`
(`workflow_dispatch`). Il faut un **second jeton** (*fine-grained*, limité au dépôt `supervision`,
**Actions : Read and write** ; inutile de donner l'écriture sur Contents), stocké sur le VPS
dans `~/.config/supervision.env` (`chmod 600`) : `SUPERVISION_PUSH_TOKEN=...`

Fonction à ajouter au script du job (en place dans `~/.hermes/scripts/raa_veille.sh`, qui l'appelle
dans son `trap ERR` et en fin de script ; sauvegarde de l'ancienne version : `raa_veille.sh.bak-avant-heartbeat`) :

```bash
HB_START=$(date -u +%FT%TZ); HB_T0=$(date +%s)
heartbeat() {  # heartbeat success|failure "message" ; n'échoue jamais
  [ -f "$HOME/.config/supervision.env" ] || return 0
  ( source "$HOME/.config/supervision.env"
    python3 -c 'import json,sys; hb={"job":"raa-veille","status":sys.argv[1],"start":sys.argv[2],"duration":int(sys.argv[3]),"message":sys.argv[4][:200]}; print(json.dumps({"ref":"main","inputs":{"heartbeat":json.dumps(hb,ensure_ascii=False)}}))'       "$1" "$HB_START" "$(( $(date +%s) - HB_T0 ))" "$2" |
    curl -s --max-time 10 -o /dev/null -X POST https://api.github.com/repos/JulienDepelchin/supervision/actions/workflows/supervision.yml/dispatches       -H "Authorization: Bearer $SUPERVISION_PUSH_TOKEN" -H "Accept: application/vnd.github+json" -d @- ) || true
}
```

Si le jeton expire ou si le VPS tombe, plus aucun heartbeat n'arrive et le job passe « muet » : la panne reste visible.

## Alertes Slack via Marcel

Marcel interroge la page publique ; aucun secret n'est nécessaire.

Tâche à confier à Marcel (toutes les 15 à 30 min) :

1. Lire `https://juliendepelchin.github.io/supervision/data/events.json`.
   Pour chaque événement dont `seq` est supérieur au dernier `seq` mémorisé, poster sur Slack :
   `<label> : <de> → <vers>. <detail>` (+ lien `url` s'il existe), puis mémoriser le plus grand `seq`.
   Au tout premier passage, mémoriser le `seq` courant sans rien poster.
2. **Surveiller le superviseur** : lire `data/status.json` ; si `generated_at` date de plus de 90 min,
   alerter une seule fois (« Le superviseur ne tourne plus ») jusqu'à ce qu'il redevienne frais.

Marcel tourne hors de GitHub : il sert donc aussi de filet de sécurité si GitHub Actions ou le superviseur tombent.
