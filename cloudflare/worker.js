// Worker Cloudflare « supervision-cron » : déclenche le superviseur toutes les 15 min.
// Copie de référence ; le code en service est dans Cloudflare (Workers & Pages > supervision-cron).
// Secret : GITHUB_TOKEN (fine-grained, dépôt supervision uniquement, Actions : Read and write).
// Déclencheur : cron « */15 * * * * ». Le cron GitHub du workflow reste actif en secours.
export default {
  async scheduled(event, env, ctx) {
    ctx.waitUntil(declencher(env));
  },
};

async function declencher(env) {
  const r = await fetch(
    "https://api.github.com/repos/JulienDepelchin/supervision/actions/workflows/supervision.yml/dispatches",
    {
      method: "POST",
      headers: {
        Accept: "application/vnd.github+json",
        Authorization: `Bearer ${env.GITHUB_TOKEN}`,
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "supervision-cron",
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ ref: "main" }),
    }
  );
  console.log(`GitHub a répondu ${r.status}`); // 204 = OK
  // Une erreur fait apparaître l'exécution en échec dans les journaux Cloudflare.
  if (r.status !== 204) throw new Error(`Déclenchement refusé : ${r.status} ${await r.text()}`);
}
