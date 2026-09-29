// Worker Cloudflare « lab-crons » : déclencheur unique de tous les crons fréquents du Lab.
//
// Code en service : Cloudflare > Workers & Pages > lab-crons (copie de référence ici).
// Déclencheur : un seul cron Cloudflare, « */5 * * * * » (toutes les 5 min).
// Secret : GITHUB_TOKEN (fine-grained, Actions : Read and write, limité aux dépôts du PLANNING).
//
// Ajouter un cron : une ligne dans PLANNING, le dépôt dans le jeton s'il est nouveau,
// et une entrée dans jobs.yml du dépôt supervision.
//
// Heures en UTC (Paris = UTC+2 l'été, UTC+1 l'hiver).
//   toutesLes : intervalle en minutes, multiple de 5 qui divise 1440 (5, 10, 15, 20, 30, 60, 120…)
//   decalage  : minutes de décalage dans l'intervalle (facultatif, multiple de 5)
//   a         : liste d'heures fixes « HH:MM » UTC, à la place de toutesLes (minutes multiples de 5)
//   inputs    : paramètres transmis au workflow (facultatif)

const OWNER = "JulienDepelchin";

const PLANNING = [
  { repo: "supervision", workflow: "supervision.yml", toutesLes: 15 },
  { repo: "veille-carburants", workflow: "alerte-carburants.yml", toutesLes: 30, inputs: { mode: "verification" } },
  { repo: "classement-actifs-lille", workflow: "poll-ter-rt.yml", toutesLes: 10 },
  { repo: "classement-actifs-lille", workflow: "poll-autoroutes.yml", toutesLes: 10 },
  { repo: "classement-actifs-lille", workflow: "poll-dir-nord.yml", toutesLes: 10 },
  { repo: "classement-actifs-lille", workflow: "poll-ilevia-pertu.yml", toutesLes: 10 },
  { repo: "veille-ja", workflow: "veille.yml", a: ["16:00"] },
];

export function aLancer(scheduledTime) {
  const d = new Date(scheduledTime);
  const minute = d.getUTCHours() * 60 + d.getUTCMinutes();
  const hhmm = d.toISOString().slice(11, 16);
  return PLANNING.filter(p =>
    p.a ? p.a.includes(hhmm) : (minute - (p.decalage || 0)) % p.toutesLes === 0);
}

function verifierPlanning() {
  for (const p of PLANNING) {
    const nom = `${p.repo}/${p.workflow}`;
    if (p.a) {
      if (!p.a.every(h => /^\d{2}:\d{2}$/.test(h) && +h.slice(3) % 5 === 0)) throw new Error(`${nom} : heures invalides`);
    } else if (!(p.toutesLes % 5 === 0 && 1440 % p.toutesLes === 0) || (p.decalage || 0) % 5 !== 0) {
      throw new Error(`${nom} : toutesLes/decalage invalides`);
    }
  }
}

async function declencher(p, token) {
  const r = await fetch(
    `https://api.github.com/repos/${OWNER}/${p.repo}/actions/workflows/${p.workflow}/dispatches`,
    {
      method: "POST",
      headers: {
        Accept: "application/vnd.github+json",
        Authorization: `Bearer ${token}`,
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "lab-crons",
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ ref: "main", ...(p.inputs ? { inputs: p.inputs } : {}) }),
    }
  );
  if (r.status !== 204) throw new Error(`${p.repo}/${p.workflow} -> ${r.status} ${await r.text()}`);
  return `${p.repo}/${p.workflow} -> 204`;
}

export default {
  async scheduled(event, env, ctx) {
    verifierPlanning();
    const jobs = aLancer(event.scheduledTime);
    const res = await Promise.allSettled(jobs.map(p => declencher(p, env.GITHUB_TOKEN)));
    res.forEach(r => console.log(r.status === "fulfilled" ? r.value : `ÉCHEC ${r.reason.message}`));
    // Une erreur fait apparaître l'exécution en échec dans les journaux Cloudflare ;
    // les autres déclenchements du même passage ont quand même eu lieu.
    const echecs = res.filter(r => r.status === "rejected");
    if (echecs.length) throw new Error(`${echecs.length} déclenchement(s) refusé(s) sur ${jobs.length}`);
  },
};
