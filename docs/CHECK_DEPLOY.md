# Vérifier une publication TYMotors

Une URL qui répond 200 n'est pas une preuve de bonne version. Toujours corréler
**repo/branche/SHA → CI → déploiement READY/Live → navigateur → API → données**.
Stripe reste test même si Vercel appelle l'environnement « Production ».

## 1. Avant push

```powershell
git status --short
git diff --check
# Backend
.venv/Scripts/python.exe -m pytest -q
.venv/Scripts/python.exe -m pip check
.venv/Scripts/python.exe scripts/smoke_stripe.py
# Frontend, dans son dossier
npx.cmd --yes yarn@1.22.22 install --frozen-lockfile
npx.cmd --yes yarn@1.22.22 test:toolchain
npx.cmd --yes yarn@1.22.22 test --watchAll=false --runInBand
npx.cmd --yes yarn@1.22.22 lint
npx.cmd --yes yarn@1.22.22 build
```

Frontend et backend sont deux dépôts : main et develop respectivement. Commit
clair dans chacun, `git push origin main` / `git push origin develop`, jamais
force, pas de réécriture d'historique. Les migrations doivent précéder les routes
qui les utilisent ; RPC `is_auth_session_active` doit être installée sur la base
du backend avant publication de son client. Ne pas ouvrir les tables privées.

## 2. Variables par hébergeur (valeurs dans les coffres uniquement)

| Emplacement | Variables |
| --- | --- |
| Render API | ENVIRONMENT=test, SITE_URL, CORS_ORIGINS ; CORS_ORIGIN_REGEX optionnelle strictement limitée à ses previews. |
| Render DB/Auth | SUPABASE_URL, SUPABASE_PUBLISHABLE_KEY, SUPABASE_SECRET_KEY ou ancien SUPABASE_SERVICE_ROLE_KEY. Jamais côté client. |
| Render Stripe | STRIPE_MODE=test, STRIPE_SECRET_KEY sk_test_/rk_test_, STRIPE_WEBHOOK_SECRET test ; SHIPPING_COUNTRIES, SHIPPING_RATE_CENTS, FREE_SHIPPING_THRESHOLD_CENTS, STRIPE_AUTOMATIC_TAX=false. |
| Render email | EMAIL_ENABLED, EMAIL_PROVIDER, EMAIL_FROM, EMAIL_REPLY_TO, EMAIL_FROM_NAME, EMAIL_TOKEN_SECRET, BREVO_API_KEY ou SMTP_* privés. EMAIL_FROM_ADDRESS alias historique à migrer. |
| Render légal | LEGAL_* réels quand disponibles, jamais faux SIRET/TVA/adresse/médiateur. Voir LEGAL_PREPARATION.md. |
| Render médias existants | CLOUDINARY_URL ou CLOUDINARY_CLOUD_NAME/API_KEY/API_SECRET, serveur seulement ; aucun changement de gestion des images. |
| Vercel config publique | REACT_APP_BACKEND_URL, REACT_APP_SITE_URL, REACT_APP_SITE_MODE=test, REACT_APP_SUPABASE_URL, REACT_APP_SUPABASE_PUBLISHABLE_KEY. |
| Opérateur sauvegarde | PG* / PGPASSFILE, BACKUP_* ou MONGODB_* seulement si utilisé ; pas à injecter dans le frontend/web server. |

Frontend CRA, pas Next.js : **toute variable REACT_APP_* est publique** et incorporée
au build. Aucune sk_/service-role/Brevo/SMTP/Cloudinary secret. Vérifier présence
et scope Production/Preview dans `vercel env ls` sans afficher/lire les secrets.
Changer une env de build exige un nouveau déploiement. Ne pas utiliser `env pull`
pour copier des secrets de production sur ce poste. Render prend les variables
du runtime ; redéploiement après changement. `.env.example` sert de contrat.

Outillage frontend : Node **22 ou 24** (CI 22, projet Vercel 24.x vérifié le
13 octobre), Yarn 1.22.22 et `--frozen-lockfile`. Les résolutions transitives de
sécurité sont testées via `test:toolchain` : ne pas supprimer ces contrôles pour
masquer un avertissement de plage de dépendance. Détail dans SECURITY_REVIEW.md.

Pas de futur domaine dans le code : renseigner URL Vercel actuelle dans SITE_URL,
origines exactes sans chemin et sans trailing wildcard. CORS ≠ authentification.
Le `connect-src` CSP frontend doit inclure l'origine exacte de l'API/Supabase
utilisée : si l'URL API change, ajuster cette allowlist (ne pas remplacer par *).
La blueprint est un exemple **configurable**, pas la preuve des valeurs dashboard.

## 3. Vérifier SHA et état

- GitHub Actions des deux repos : tests/build/secrets success sur **le SHA poussé**,
  pas une précédente exécution. CI backend couvre Python 3.11 Docker et 3.12.
- Vercel : projet/équipe exacts, branche main, target Production, état READY et
  alias au déploiement correspondant. Avec accès CLI autorisé :

```powershell
vercel --scope $env:CHECK_VERCEL_TEAM list $env:CHECK_VERCEL_PROJECT --environment production
vercel --scope $env:CHECK_VERCEL_TEAM inspect $env:CHECK_VERCEL_DEPLOYMENT_URL
```

Si MCP refuse l'accès, utiliser seulement le fallback CLI de la même équipe et
du même projet. Ne pas supposer qu'un autre scope/default donne le bon résultat.
Attention aux URL `&` passées aux wrappers .cmd PowerShell : préférer commande
native inspect ou l'entrée Node de la CLI avec les arguments correctement cités.
- Render : service API européen correct, dépôt backend / branche develop, **Live**
  sur le SHA attendu, pas seulement Build/Deploy en cours. Examiner le premier
  échec de build/startup sans recopier de secrets/logs PII ; ne pas changer de plan.
- Logs applicatifs : pas d'access log brut/query token ; HTTPX/httpcore WARNING,
  erreurs structurées sans PII. Contrôler aussi redaction/rétention du proxy/hébergeur,
  qui n'est pas couvert par la configuration du logger Python.
- En rollback, migrations compatibles à conserver ; ne pas restaurer la base
  automatiquement pour rollback un simple frontend. Décision backup séparée.

## 4. Vérifications HTTP non mutantes

Injecter les deux origines choisies (pas une clé, pas une URI DB) puis :

```powershell
.venv/Scripts/python.exe scripts/check_deploy.py
```

Env diagnostique : **SITE_URL** (frontend) et **CHECK_BACKEND_URL** (API). Le script
ne charge pas .env, ne login pas, ne checkout pas, n'envoie aucun email : seulement
GET/OPTIONS. Il vérifie health avec DB, Stripe test public, admin sans auth 401,
CORS origine exacte/refus origine étrangère, CSP/HSTS/nosniff/frame-deny et no-store.
Échec réseau/config = sortie 1, jamais confondu avec clean. Un free Render endormi
peut dépasser 30 s : réveiller/attendre sa disponibilité puis refaire une fois,
consigner le temps réel ; ne pas déclarer un service indisponible instantanément
comme bug de prix/produit. Vérifier aussi HTTP → HTTPS (301/307/308) chez l'hébergeur.

## 5. Navigateur et frontières métier

Sur le **site déployé**, vérifier console/errors réseau et lecture des pages :
accueil/GSAP mobile, catalogue, détail existant, panier, configurateur, suivi,
auth et admin refusé sans session, cookies/légales. Pas de nouveaux visuels ni
de modifications cosmétique hors scope. Retirer les cookies facultatifs puis
vérifier absence de traceurs avant accord. Auth réelle : login/session/expiration
et sign-out, ancien token API refusé ; ne pas écrire de secret dans une capture.

Pour tester création réelle d'une commande utiliser **TEST_STRIPE.md** : carte
4242, sandbox/staging, livraison, adresse/téléphone, webhook signé, commande
unique, fournisseur pending_validation et suivi. Aucun produit actif réel
validé actuellement : ne pas en inventer ou activer une fixture en production.
Réception email/identité/produits/sauvegarde-restauration restent des validations
manuelles. Conserver preuves sans données personnelles ; mise en ligne du code
ne vaut pas autorisation d'ouvrir aux vraies ventes.

## Journal de cette livraison

Résultats et SHA définitifs dans **PROGRESS.md à la racine**. Les anciens relevés
de STRIPE_TEST_SETUP.md sont datés/historiques. Aucune réussite Checkout réel,
email réel, DNS, backup réel ou SIRET affirmée sans preuve correspondante.

Complément sécurité : voir **SECURITY_REVIEW.md** (nouvel audit 1 avis braces,
contre 14 auparavant) et **ACCOUNT_SECURITY.md** (rotation SMTP/MFA/restauration
réelles à effectuer soi-même). La baseline CI est exacte, visible et expirante ;
pas une approbation de sécurité du paquet résiduel. Actions CI verrouillées sur
SHA et audit pip strict, sans activation commerciale.

Le serveur React local écoute maintenant uniquement sur 127.0.0.1 par défaut.
`HOST`, `DEV_ALLOWED_HOSTS` et `DEV_ALLOWED_ORIGINS` sont des options **locales**
pour accès LAN/intégration approuvée, pas des variables Vercel/Render à remplir.
Ne jamais les définir à `all`, `*` ou une origine non fiable. Les hooks
CRA/visual/health et WebSocket restent derrière les contrôles du serveur.
