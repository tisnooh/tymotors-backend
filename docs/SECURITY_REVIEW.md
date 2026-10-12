# TYMotors — revue de sécurité, 12 octobre 2026

## Portée et limites

Revue du frontend React, FastAPI, client PostgREST/Auth, migrations SQL, scripts,
Docker/Render, Vercel et CI. Architecture réelle : **Supabase PostgreSQL/Auth**, pas
MongoDB. Aucun paiement live, produit activé, changement de photo ou GSAP, ni 2FA
admin ajouté. Les actions admin/fournisseur restent validées manuellement.

Le multipasse Codex Security n'a **pas démarré** : profil filesystem géré absent ;
Daybreak non accordé. Ce document rapporte une revue source, des tests et des
audits exécutés séparément, pas un résultat du plugin ni une certification.
Un test passant et un healthcheck ne prouvent pas l'absence de vulnérabilités.
Les réglages des comptes/infra non accessibles sont identifiés comme à vérifier.

## Constats et corrections

| Référence | Gravité | Constat / preuve | État et traitement |
| --- | --- | --- | --- |
| SEC-01 | élevée | Un JWT Supabase valide peut rester utilisable après sign-out jusqu'à expiration. | Corrigé pour les API TYMotors : Auth vérifie d'abord signature/expiration, puis RPC service-only vérifie `session_id`, propriétaire et `not_after` dans `auth.sessions`. Pas de cache. Migration appliquée/testée staging puis production. Tests session active/révoquée/expirée et privilèges SQL. |
| SEC-02 | moyenne | Auth SPA persiste access/refresh tokens dans le stockage JS. | Risque résiduel : une XSS pourrait les voler. CSP restrictive, aucune insertion HTML non nettoyée relevée, rendu React échappé. Aucun cookie d'auth maison à prétendre HttpOnly. Passer à un BFF avec cookies HttpOnly/Secure/SameSite nécessiterait une évolution d'architecture ; non simulé ici. |
| SEC-03 | élevée | Le login direct Supabase peut contourner les limites de l'API applicative. | API limitée par IP et empreinte d'email, 429/Retry-After et fenêtres temporaires ; aucune désactivation permanente permettant un DoS du compte. Activer/configurer aussi limites Auth, protection mots de passe compromis et paramètres sessions au dashboard. Production signale la protection compromis désactivée. |
| SEC-04 | élevée | Routes admin / autorisations / audit. | Vérifié : toutes les routes admin testées sans token, token expiré et rôle client. Rôle relu dans `profiles`, pas décidé par metadata JWT. RPC mutations service-only + assertion rôle + `admin_audit` + verrou optimiste. Les tests énumèrent OpenAPI résolu, y compris routers FastAPI récents. Pas de 2FA admin ajoutée. |
| SEC-05 | moyenne | Checkout retournait 403 pour une commande existante non possédée, 404 si absente (énumération). | Corrigé : même 404 ; aucun item/événement lu avant contrôle propriétaire. `/me/orders` filtré `user_id`, invité exige capacité panier + session Stripe correspondante. Tests IDOR client/invité et filtre compte. |
| SEC-06 | élevée | Suivi public et collecte formulaires. | Vérifié : email **et** référence nécessaires ; même 404 si l'un est faux. Réponse filtrée sans ID interne/email/adresse/données fournisseur. Limite 10 recherches/5 min/IP ; tests injection objets et limite. Pas de consultation publique par seul ID. |
| SEC-07 | moyenne | Identifiant invité fallback Date/Math.random prévisible et validation trop souple. | Corrigé : Web Crypto UUID ou 192 bits aléatoires ; 16–128 caractères allowlist côté serveur. Valeur locale invalide remplacée. Une capacité persistante ancienne conforme n'est pas une preuve de propriété d'un compte. |
| SEC-08 | élevée | Corps volumineux/stream sans Content-Length et lecture sans borne globale. | Corrigé : ASGI avant parsers, 1 MiB JSON, 9 MiB enveloppe upload (limite fichier existante 8 MiB inchangée), délai lecture total 15 s, query string 8 KiB. Tests taille déclarée/réelle et stream. Réglages proxy complémentaires à vérifier. |
| SEC-09 | moyenne | Réponses Pydantic pouvaient renvoyer la valeur d'entrée, traces SDK et logs d'URL HTTP pouvaient contenir des données privées/tokens newsletter. | Corrigé : réponses validation sans `input`/`ctx`, erreurs inattendues génériques et en-têtes aussi sur erreur ; logs classe/statut/identifiant technique seulement, plus de traceback SDK dans le logger applicatif. Logs bruts Uvicorn désactivés, HTTPX/httpcore limité à WARNING. Tests mot de passe non réémis, panne dépendance et politique logs. Contrôler séparément redaction/rétention des logs du proxy/hébergeur. |
| SEC-10 | élevée | Injections/XSS/uploads. | Vérifié : modèles Pydantic, UUID/allowlists, SQL paramétré et filtres PostgREST construits côté serveur. Pas de moteur MongoDB ni requête `$where` dans l'application ; objets/opérateurs inattendus rejetés avant base. Aucun `dangerouslySetInnerHTML`, eval ou injection innerHTML trouvé dans src. Emails échappés. Upload admin existant : MIME/extension-signature, taille, nom généré Cloudinary, pas de chemin utilisateur/overwrite. Gestion des images conservée. |
| SEC-11 | critique | Paiement manipulé / faux webhook / double débit stock. | Contrôles existants vérifiés : prix entiers base et livraison serveur, panier/compatibilité revérifiés, signature Stripe sur corps brut, mode test, montant/devise/référence attendus ; événements uniques et RPC SQL atomique verrouillé. Tests signature absente/fausse/altérée/expirée sans écritures, rejeu/idempotence/stock. La redirection succès ne marque jamais payé. Checkout crée une commande **impayée**, webhook confirme son paiement. |
| SEC-12 | moyenne | CSP/HSTS/CORS/HTTPS. | Backend CSP API default-none, nosniff, Frame DENY, Referrer/Permissions, no-store privé. Front CSP script-self, frame-ancestors-none, ajout HSTS un an. HTTPS et redirection gérés par Vercel/Render ; ne pas croire les X-Forwarded arbitraires. CORS origines explicites sans wildcard, regex previews optionnelle à restreindre à son équipe (ne pas accepter tous les `.vercel.app`). Vérifier proxy approuvé et HTTP→HTTPS en déploiement. |
| SEC-13 | élevée | Secrets et configuration. | Historiques Git frontend/backend scannés avec Gitleaks 8.24.3 `--all --redact=100` : aucun secret détecté. `.env*` ignorés sauf exemples sans valeurs réelles ; outils/dumps exclus aussi du contexte Docker. Suppression emails personnels/URLs de site de la blueprint : env `EMAIL_FROM`, `SITE_URL`, `CORS_ORIGINS`. Clés service/Stripe/Brevo/Cloudinary restent backend uniquement. |
| SEC-14 | élevée | Un mot de passe d'application SMTP a été exposé dans une capture du chat antérieure. | **Action manuelle : révoquer/régénérer SMTP_PASSWORD** chez Google et dans tout service qui l'utilise. Valeur non reproduite, pas détectée dans Git. Aucun autre secret déclaré compromis sans preuve. Ne pas réécrire l'historique pour masquer une fuite : rotation d'abord. |
| SEC-15 | élevée | Dépendances vulnérables. | FastAPI/Pydantic/Starlette/multipart/dotenv et axios/React Router mis à jour ; corrections transitives compatibles du lock Yarn. Audit Python après correctifs : aucune vulnérabilité connue. Résidus frontend/outillage détaillés ci-dessous ; ne pas utiliser `npm audit fix --force`. |
| SEC-16 | moyenne | Limites process-local et disponibilité. | Stockage limiteur borné à 10k clés, timeout HTTPX (20 s/connect 10 s), request guard, erreurs génériques, `/api/health` retourne uniquement état sans URL/base/env. Limiteurs non distribués : multiworker/autoscaling exige un compteur partagé/WAF. Free Render peut dormir, ce n'est pas corrigé par changer CORS. |
| SEC-17 | élevée | Sauvegardes / restauration / infra. | Guide et scripts dans BACKUPS.md. Backup réel chiffré hors hôte + restauration staging restent à exécuter ; sans credentials/outils pg_dump/mongodump, aucune sauvegarde distante prétendue. Revoir rôles DB, ACL réseau/TLS, secrets dashboards, PITR/rétention suivant plan. |
| SEC-18 | moyenne | RGPD/rétention et documents légaux. | Minimisation publique/track, pas de carte stockée, tokens newsletter hashés, opt-in/refus par défaut. Pas de purge arbitraire des factures/commandes : fixer délais légaux avec responsable et procédure d'accès/suppression/anonymisation, prestataires/DPA et stockage sauvegardes chiffré. Identité/SIRET/TVA/médiateur non inventés ; indispensables avant vente réelle. |

## Dépendances : reproduction et traitement des résidus

Backend : `requirements.txt` audité avec pip-audit 2.10.1 dans un venv d'outillage
isolé. Avant : 30 enregistrements d'avis (certains doublonnés) sur dotenv,
multipart et Starlette. Après mise à jour : **aucune vulnérabilité connue**.
FastAPI 0.143.0, Pydantic 2.14.1, Starlette 1.7.0, multipart 0.0.32,
dotenv 1.2.2 ; pip check et tests exécutés. CI Python 3.11 (Docker) et 3.12.

Frontend : audit du **lock Yarn**, utilisant les avis npm, via
`node tests/audit_dependencies.cjs`. Son code retour 1 signale des avis restants,
2 un audit indisponible (jamais interprété comme clean). Pas de second lock npm.
Axios 1.20.0, React Router DOM 7.18.4 ; shell-quote, websocket-driver et proxy-addr
corrigés sans passage forcé de react-scripts/webpack-dev-server vers un majeur incompatible.
Résultat consolidé : **24 avis distincts sur 12 paquets**, 0 critique. Le compteur
Yarn de chemins affectés est 3 faibles / 26 moyens / 21 élevés (ce n'est pas
50 vulnérabilités distinctes). Aucun avis axios/React Router ne reste dans ce scan.

| Paquet restant | Version | Gravité fournisseur | Traitement restant |
| --- | --- | --- | --- |
| postcss-selector-parser | 6.1.4 | moyenne | Correctif 7.1.6, majeur ; migration chaîne CSS. |
| serialize-javascript | 4.0.0 / 6.0.2 | élevée / moyenne | 7.0.5, majeur ; minifiers CRA à migrer. |
| nth-check | 1.0.2 | élevée | 2.0.1 requis par nouvelle chaîne SVGO. |
| webpack-dev-server | 4.15.2 | moyenne | 5.2.6, incompatible avec l'intégration CRA 5 sans migration. |
| postcss | 7.0.39 | élevée / moyenne | Branche 8.5.23 ; branche 8 actuelle rafraîchie, branche 7 héritée reste. |
| @tootallnate/once | 1.1.2 | faible | 2.0.1, majeur, chaîne jsdom/test à migrer. |
| uuid | 8.3.2 | moyenne | 11.1.1, majeur, dev-server SockJS à migrer. |
| svgo | 1.3.2 | élevée / moyenne | 2.8.4, majeur ; plugins SVG CRA à migrer. |
| webpack-dev-middleware | 5.3.4 | élevée | 7.4.6, majeur ; dev-server à migrer. |
| node-forge | 1.4.0 | élevée | Aucun correctif publié annoncé pour GHSA-86w9-cpqp-85rv. |
| braces | 3.0.3 | élevée | Aucun correctif publié annoncé pour GHSA-vfj7-8cjw-p6xm. |
| sprintf-js | 1.0.3 | moyenne | Aucun correctif publié annoncé pour GHSA-hp3w-g68c-fv3c. |

Ces résidus sont consignés, pas déclarés corrigés. Reproduire l'audit après toute
mise à jour : le catalogue d'avis peut changer. Références :
[node-forge](https://github.com/advisories/GHSA-86w9-cpqp-85rv),
[braces](https://github.com/advisories/GHSA-vfj7-8cjw-p6xm),
[sprintf-js](https://github.com/advisories/GHSA-hp3w-g68c-fv3c).

Les dépendances de serveur de développement, compilation et tests ne sont pas
automatiquement exploitables dans le bundle statique Vercel. Elles restent un
risque de poste/CI : ne pas exposer le dev-server ni exécuter de PR non fiable
avec des secrets. CRA/react-scripts 5 doit faire l'objet d'une migration dédiée
vers un outillage maintenu pour supprimer les incompatibilités restantes.

## Base et déploiement : preuves et réglages manuels

- PostgreSQL production : **0 table public sans RLS** ; fonctions contrôlées
  sans EXECUTE anon/authenticated. RPC nouvelle session : droits clients refusés
  et session inexistante refusée, staging et production. PGlite teste aussi
  rôle/mutations/idempotence/stock et expiration/révocation de session.
- Vérification distante des grants : clients ne peuvent ni modifier leur rôle,
  ni écrire directement orders/products ; anon ne lit pas orders/admin_audit.
- Advisors Supabase : 5 INFO « RLS sans policy » sur tables fournisseur/événements
  **privées volontairement fermées**, pas une raison d'accorder l'accès public.
  [Explication officielle](https://supabase.com/docs/guides/database/database-linter?lint=0008_rls_enabled_no_policy).
- Production : protection mots de passe compromis désactivée, à activer si le
  plan le permet. [Paramètres mots de passe](https://supabase.com/docs/guides/auth/password-security).
- Supabase Auth gère hash/password/JWT ; pas de password maison en base applicative.
  Le fournisseur utilise bcrypt et sel aléatoire ; régler expiration, rotation
  refresh, limites directes Auth et sessions au dashboard.
  Le contrôle nouveau concerne les **API backend** ; l'accès JWT direct PostgREST
  reste soumis à RLS et à l'expiration du JWT. [Sessions](https://supabase.com/docs/guides/auth/sessions).
- Vercel/Render : vérifier provenance Git/branches/SHA, TLS/redirection, secrets
  backend séparés, env test, aucune variable privée `REACT_APP_*`, debug/reload
  désactivés ; Docker non-root. Gitleaks CI full history et tests frontend ajoutés.
- La clé Supabase serveur est privilégiée par conception ; jamais frontend,
  portée opérationnelle minimale, rotation régulière. Si MongoDB est réellement
  ajouté plus tard : Atlas IP allowlist (pas 0.0.0.0/0), TLS, utilisateur DB dédié
  readWrite à la seule base, rôle sauvegarde séparé et logs anonymisés. **Atlas
  n'est pas une dépendance actuelle et ses dashboards n'ont pas été vérifiés.**
- Activer MFA des comptes Stripe/Vercel/Render/GitHub/Supabase/Atlas (si utilisé).
  C'est distinct d'ajouter une 2FA sur la page admin, non demandé.

## Recette et secrets à régénérer

Tests sécurité : toutes routes admin, IDOR, injection objets, tracking non
énumérant/rate, signature webhook invalide, request limits, validation privée,
session révoquée. Aucune donnée réelle ni secret hébergé requis pour ces tests.
Recette locale : **240 tests backend, 40 frontend (12 suites), 58 contrôles
PostgreSQL/PGlite**, lint, pip check et builds production réussis. Le lifespan
réel démarre/s'arrête localement sans secret hébergé. Le changement FastAPI a
nécessité d'adapter l'énumération des routers : aucun test admin n'est omis.
Procédure paiement hébergé **sandbox** : TEST_STRIPE.md ; état publié : CHECK_DEPLOY.md.
Rotation exigée : **SMTP_PASSWORD exposé dans le chat**. Gitleaks clean n'exclut
pas une fuite dans logs, exports, forks ou références Git non disponibles.
Ne publier ni rapports non masqués ni commandes contenant des credentials.

## Contrôle consolidé — 13 octobre 2026

255 tests backend, 53 frontend (13 suites), 58 contrôles PostgreSQL, smoke signé,
lint, pip check, compilation Python et build production réussis. Dernier audit
Python toujours sans avis connu ; Yarn reste à 24 avis/12 paquets, 0 critique.
Les titres de suivi/mentions/rétractation n'indiquent plus « page introuvable » ;
pages privées noindex, canonicals sans token et origine de secours issue du
navigateur, pas d'un domaine écrit en dur. Cela n'est pas un contrôle d'accès.
Les logs d'URL et filtres DB bruts sont désactivés au runtime et dans Docker.
Déploiements et recette navigateur finale détaillés dans PROGRESS.md.
