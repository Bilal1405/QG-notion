# QG Notion — synchro Moodle IPSA + OneDrive

Ce script remplit automatiquement le QG Notion (« 🚀 QG Bilal »). Il tourne deux fois par jour, vers 7 h et 19 h, via GitHub Actions.

| Source | Ce qui est récupéré | Base Notion |
|---|---|---|
| Moodle (calendrier + web services) | Devoirs, quiz et dates de rendu | **Tâches** (Source = Moodle) |
| Moodle | Supports de cours : fichiers, liens, pages, devoirs, quiz | **Ressources** |
| Moodle | Forum « Annonces » de chaque cours (120 derniers jours) | **Annonces** |
| Moodle | Carnet de notes (hors totaux) | **Notes Moodle** |
| OneDrive perso / école | Fichiers rangés dans un dossier de matière | **Ressources** + lien « Dossier OneDrive » dans Cours IPSA |
| Planning IPSA (déjà dans Notion) | Salle ajoutée au titre des créneaux à venir (« Thermodynamique 1 · 📍BC309 ») pour qu'elle s'affiche dans Notion Calendar | **Planning IPSA** |

Chaque élément est rattaché à sa matière grâce au **code IPSA** présent dans son nom : Ma211, Aé211, Phs213… Ce code doit apparaître dans le nom du cours Moodle ou du dossier OneDrive. Si la correspondance échoue, renseigne l'ID du cours Moodle dans la colonne « Cours Moodle » de la matière.

Règles de synchro :

- **Rien n'est écrasé côté utilisateur.** Le statut d'une tâche (Fait, En cours…), la priorité et la case « Lue » ne sont jamais modifiés par la synchro.
- **Suppressions** : une ressource qui disparaît de Moodle ou de OneDrive est mise à la corbeille, sauf si elle est « Épinglée ».
- **Tâches, annonces et notes** : jamais supprimées.
- **Accès expiré** : une tâche « 🔑 Renouveler… » apparaît dans le QG. Elle se ferme d'elle-même quand l'accès fonctionne à nouveau.

## Mise en place (une seule fois)

Tous les secrets se saisissent dans GitHub : **Settings → Secrets and variables → Actions → New repository secret**.

### 1. Notion

1. Va sur https://www.notion.so/profile/integrations et clique sur **Nouvelle intégration**.
   - Type : interne.
   - Capacités : lire, mettre à jour et insérer du contenu.
2. Copie le « Secret d'intégration interne » dans le secret **`NOTION_TOKEN`**.
3. Dans Notion, ouvre la page **QG Bilal**, puis **•••** → **Connexions**, et ajoute l'intégration. Toutes les sous-pages et bases en héritent.

### 2. Moodle (connexion par compte Microsoft IPSA)

**a. Calendrier (échéances)** : secret **`MOODLE_ICS_URL`**.

1. Dans Moodle, va dans **Calendrier** → **Exporter le calendrier**.
2. Choisis « Tous les événements » et « Événements récents et des 60 prochains jours ».
3. Clique sur **Obtenir l'URL du calendrier** et copie l'adresse.

Cette adresse contient une clé personnelle : ne la colle nulle part ailleurs.

**b. Jeton web service (supports, annonces, notes)** : secret **`MOODLE_TOKEN`**.

Comme la connexion passe par Microsoft, il n'y a pas de mot de passe Moodle. On récupère donc le jeton de l'appli mobile :

1. Connecte-toi à Moodle dans Chrome ou Edge, puis ouvre la console (F12 → Console).
2. Dans le même onglet, ouvre :
   `https://moodle.ipsa.fr/admin/tool/mobile/launch.php?service=moodle_mobile_app&passport=424242&urlscheme=moodlemobile`
3. La console affiche `Failed to launch 'moodlemobile://token=…'`. Copie l'adresse complète `moodlemobile://token=…`.
   Tu la trouves aussi dans l'onglet Network : c'est l'en-tête `Location` de `launch.php`.
4. Lance `python tools/moodle_token.py "moodlemobile://token=…"` et copie le jeton affiché.

Autre possibilité : dans Moodle, **Préférences → Clés de sécurité**, ligne « Moodle mobile web service ». Ce n'est disponible que si l'IPSA l'affiche.

Si l'IPSA a désactivé l'appli mobile, seules les échéances (2a) fonctionneront.

### 3. OneDrive (facultatif)

1. Enregistre une application sur https://entra.microsoft.com → **Applications** → **Inscriptions d'applications** → **Nouvelle inscription** :
   - Comptes pris en charge : « Comptes dans un annuaire organisationnel et comptes Microsoft personnels ».
   - **Authentification** : « Autoriser les flux de clients publics » = **Oui**.
   - **Autorisations d'API** : Microsoft Graph, délégué, `Files.Read`, `User.Read`, `offline_access`.
   - Copie l'« ID d'application (client) » dans le secret **`MS_CLIENT_ID`**.
2. Sur ton PC, lance :
   - `pip install requests`
   - `python tools/onedrive_auth.py <MS_CLIENT_ID> perso` → secret **`ONEDRIVE_PERSO_REFRESH_TOKEN`**
   - `python tools/onedrive_auth.py <MS_CLIENT_ID> ecole` → secret **`ONEDRIVE_ECOLE_REFRESH_TOKEN`**
3. Dossiers à parcourir : **Settings → Secrets and variables → Actions → Variables**.
   - `ONEDRIVE_PERSO_ROOT` vaut par défaut `IPSA/IPSA_Année_2`.
   - `ONEDRIVE_ECOLE_ROOT` vaut par défaut la racine du OneDrive.
4. Facultatif : un jeton GitHub à granularité fine, limité à ce dépôt, avec la permission « Secrets : Read and write ». Mets-le dans le secret **`GH_SECRETS_TOKEN`**. La synchro enregistre alors elle-même le jeton OneDrive renouvelé, et tu n'as plus besoin de reconnecter OneDrive.

Un compte école peut exiger l'accord de l'administrateur de l'IPSA pour autoriser l'application. Dans ce cas, utilise l'aperçu natif de Notion : `/onedrive` dans une page, ou un lien collé « en aperçu ».

### 4. Premier lancement

1. Onglet **Actions** → **Synchro Moodle & OneDrive → Notion** → **Run workflow**.
2. Coche « Simulation » : le journal affiche ce qui serait créé, sans rien écrire.
3. Relance sans cocher.

## Renouveler les accès

| Tâche affichée dans le QG | Action |
|---|---|
| 🔑 Renouveler le jeton Moodle | Refaire l'étape 2b (le jeton de l'appli mobile expire selon la durée fixée par l'IPSA) |
| 🔑 Renouveler l'URL du calendrier Moodle | Refaire l'étape 2a |
| 🔑 Reconnecter OneDrive perso / école | Refaire l'étape 3.2 (inutile si `GH_SECRETS_TOKEN` est configuré, sauf révocation) |

## Confidentialité

- Le dépôt est **public** : n'importe qui peut lire le code et les journaux d'exécution.
  - Le script n'écrit dans les journaux que des compteurs, jamais de noms de cours, de notes ni de contenus.
  - Les jetons restent dans les secrets GitHub, qui sont chiffrés et jamais affichés.
- Recommandé : passer le dépôt en privé (**Settings → General → Change visibility**). La synchro consomme environ 120 minutes d'Actions par mois, dans la limite du quota gratuit.
- Sur un dépôt public, GitHub suspend les tâches planifiées après 60 jours sans activité. Relance-les depuis l'onglet Actions si besoin.

## Développement

```bash
pip install -r requirements.txt pytest
python -m pytest -q
NOTION_TOKEN=… MOODLE_ICS_URL=… python -m qg_sync --dry-run
```

Structure :

- `qg_sync/notion.py` : client de l'API Notion (data sources, version 2025-09-03).
- `qg_sync/moodle.py` : web services Moodle et lecture du calendrier iCal.
- `qg_sync/onedrive.py` : Microsoft Graph (lecture seule).
- `qg_sync/matching.py` : association à une matière par code IPSA.
- `qg_sync/sync.py` : création ou mise à jour idempotente et alertes « 🔑 ».
- `tools/` : récupération des jetons Moodle (SSO) et OneDrive.
