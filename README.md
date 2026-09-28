# Supervision du Lab

Tableau de bord des jobs planifiés (crons GitHub, crons Cloudflare, VPS).
Page : https://juliendepelchin.github.io/supervision/

Toutes les 15 min (Worker Cloudflare `lab-crons`, voir plus bas ; cron GitHub toutes les 30 min en secours), le workflow `Supervision` lit l'API GitHub Actions pour chaque job de `jobs.yml`,
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

## Déclencheur Cloudflare commun : `lab-crons`

Tous les crons fréquents du Lab (plus d'une fois par heure, ou à heure précise) sont déclenchés par
un seul Worker Cloudflare, `lab-crons` ([cloudflare/lab-crons.js](cloudflare/lab-crons.js)) :
un seul déclencheur cron (`*/5 * * * *`), un seul jeton (`GITHUB_TOKEN` : Actions en lecture/écriture
sur les dépôts concernés), et un tableau `PLANNING` qui dit quel workflow lancer et quand (heures UTC).

Les crons quotidiens tolérants au retard restent sur le cron GitHub de leur dépôt.

## Ajouter un nouveau cron

### 1. Choisir où il tourne et qui le déclenche

Le code tourne **sur GitHub Actions** par défaut (gratuit pour un dépôt public, journaux conservés,
secrets rangés, vu automatiquement par le superviseur). Reste à choisir qui donne le top départ :

| Besoin | Déclencheur |
|---|---|
| Une fois par jour (ou moins), quelques heures de retard sans gravité | cron GitHub du dépôt (`on: schedule`) |
| Plus d'une fois par heure, ou à heure précise (alerte, poll) | Worker `lab-crons` (une ligne dans `PLANNING`) |
| Fichiers à conserver entre deux passages, traitement très long, site qui bloque GitHub, besoin de Marcel | VPS, tâche Hermes + heartbeat |

Pièges :
- **Fuseau horaire** : cron GitHub et `lab-crons` sont en **UTC** (Paris = UTC+2 l'été, UTC+1 l'hiver) ;
  Hermes est à l'heure de Paris. Pour une heure locale fixe toute l'année, passer par Hermes.
- **Cron GitHub** : retards fréquents (jusqu'à plusieurs heures), passages parfois sautés, et désactivation
  automatique après 60 jours sans activité sur le dépôt.

### 2. Liste de vérifications

**Cron GitHub**
- [ ] `on: schedule` dans le workflow, **et** `workflow_dispatch` (pour le lancer à la main).

**Worker `lab-crons`**
- [ ] Le workflow a `on: workflow_dispatch` (avec ses `inputs` s'il en attend).
- [ ] Une ligne dans `PLANNING` de [cloudflare/lab-crons.js](cloudflare/lab-crons.js), commitée ici,
      **puis** collée dans l'éditeur Cloudflare et déployée (Deploy).
- [ ] Si le dépôt est nouveau : l'ajouter au jeton `cloudflare-lab-crons` (GitHub > Fine-grained tokens >
      le jeton > Repository access). Sinon, les journaux du Worker affichent « ÉCHEC … 403 ».

**VPS (Hermes)**
- [ ] Script dans `~/.hermes/scripts/`, tâche créée avec `hermes cron create`.
- [ ] Fonction `heartbeat` ajoutée au script (section suivante), avec le bon `job`.

**Dans tous les cas**
- [ ] Une entrée dans [jobs.yml](jobs.yml) : `id`, `projet`, `label`, `source`, `repo`/`workflow`
      (ou `source: heartbeat`), `declencheur`, `max_silence`.
      `max_silence` ≈ trois fois l'intervalle normal (10 min → 40m ; 30 min → 90m ; quotidien → 36h).
      Pour un job qui ne tourne pas le week-end, compter le trou du vendredi au lundi.
- [ ] Si le dépôt est privé : l'ajouter au jeton de lecture du superviseur (`SUPERVISION_TOKEN`).
- [ ] Pousser, puis vérifier sur le tableau, après le premier passage, que le job est « OK ».

### 3. Les jetons en service

| Jeton | Droits | Où il est stocké | Sert à |
|---|---|---|---|
| Lecture du superviseur | Actions : lecture, dépôts surveillés | secret `SUPERVISION_TOKEN` du dépôt `supervision` | lire les runs |
| `cloudflare-lab-crons` | Actions : écriture, dépôts du `PLANNING` | secret `GITHUB_TOKEN` du Worker `lab-crons` | lancer les workflows fréquents |
| `heartbeat-vps` | Actions : écriture, dépôt `supervision` | `~/.config/supervision.env` sur le VPS | signaler les passages des jobs du VPS |

Expiration : un an au plus. Noter les dates ; à l'expiration, les jobs passent « Inconnu » (lecture)
ou « Muet » (écriture) sur le tableau, et Marcel prévient.

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

Tâche Hermes `supervision-alertes` sur le VPS : toutes les 15 min, sans agent (aucun appel au modèle),
elle lance `~/.hermes/scripts/supervision_alertes.py` (copie de référence : [marcel/](marcel/)) et
envoie sa sortie en message privé Slack (`slack:D0C326EDYJE`). Aucune sortie = aucun message.

Le script lit `events.json` et `status.json` via l'API publique de GitHub (aucun jeton) et signale :
- chaque nouveau changement d'état d'un job (mémoire : `~/.hermes/state/supervision_alertes.json`) ;
- un superviseur arrêté (`generated_at` de plus de 90 min), puis son retour ;
- un tableau illisible 6 passages de suite (1 h 30), puis son retour.

Marcel tourne hors de GitHub : il sert donc aussi de filet de sécurité si GitHub Actions ou le superviseur tombent.

Commandes utiles (sur le VPS) : `hermes cron list`, `hermes cron runs`, `hermes cron pause supervision-alertes`.
Après modification du script dans `marcel/`, le recopier : `scp marcel/supervision_alertes.py hermes:.hermes/scripts/`.
