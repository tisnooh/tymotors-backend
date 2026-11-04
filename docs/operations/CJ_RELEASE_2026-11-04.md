# Publication CJ — 4 novembre 2026

## Autorisation et périmètre

Le propriétaire a répondu « Oui, publier ces correctifs CJ » à la demande portant sur backend #8, administration #8 et migration. Aucun achat, paiement fournisseur ni activation de produit n'est inclus.

## Base de production

Projet Supabase `dzdcaloewimekvddvdlo`. Avant application : table CJ absente, fonctions administrateur et trigger existants, zéro produit actif.

Migration `cj_order_submission_reservation` appliquée avec succès. Le service de migration a attribué la version **20261104060209**. Le fichier initial `20261103180202_cj_order_submission_reservation.sql` est renommé vers cette version, sans modification SQL, et le runner SQL utilise le nouveau nom. Ne pas réappliquer cette migration sous son ancien numéro.

Contrôles après application :

- `cj_order_submissions` existe, RLS activée, zéro ligne.
- Aucun accès SELECT pour `anon` ou `authenticated` ; SELECT/INSERT/UPDATE accordés au backend `service_role`.
- Les trois RPC claim/finish/observe sont SECURITY INVOKER avec search_path vide ; EXECUTE refusé aux rôles publics et accordé à `service_role`.
- Advisor : information RLS sans policy sur cette table volontairement réservée au serveur. L'avertissement Auth sur la protection des mots de passe compromis était déjà présent avant le lot ; aucune configuration Auth modifiée.

## Backend

- [PR #8 fusionnée](https://github.com/tisnooh/tymotors-backend/pull/8), commit **c2031d07b395652b0be3fe439a83a87be488fb5f** sur `develop`.
- [CI du commit publié réussie](https://github.com/tisnooh/tymotors-backend/actions/runs/41782918105) : tests Python, SQL, secrets et dépendances.
- Render `tymotors-backend-eu`, service `srv-dajf809594qs73bvpgi0` : **Live**, ce commit affiché comme dernier déploiement réussi, auto-déploiement de 37,2 s.
- `GET /api/health` et `/api/site-config` :200 ; Stripe reste `live`, catalogue de test désactivé, `legal_ready=false` inchangé.
- OpenAPI public : routes de correspondance produit, préparation, consultation/création de brouillon et synchronisation CJ présentes.
- Routes GET produit/cj-connection, commande/cj-readiness et commande/cj-draft :401 sans session. POST cj-draft et cj-sync :401 sans session. Pré-vérification CORS POST depuis `https://tymotors.vercel.app` :200, origine attendue.

## Administration

- [PR #8 fusionnée](https://github.com/tisnooh/tymotors-frontend/pull/8), commit **646583b64b35f69c9c8a483d397b18a1fbe60f01** sur `main`.
- [CI du commit publié réussie](https://github.com/tisnooh/tymotors-frontend/actions/runs/41783133403), compilation et tests.
- Vercel **dpl_6T83x1wTnwdR1tSyJtZEEf21ss1C**, état **READY**, cible **production**, SHA et branche vérifiés par API avec la CLI authentifiée. Alias `tymotors.vercel.app` associé à cette version.
- Le connecteur Vercel a refusé la liste des déploiements avec403 ; vérification obtenue via la CLI autorisée, sur le même projet et la même équipe, sans modifier les permissions.
- `/admin` s'ouvre sur la connexion sécurisée. La session administrateur du navigateur est déconnectée ; aucun clic authentifié sur la nouvelle action n'est revendiqué. Aucun mot de passe demandé ou changé.
- Contrôle des fichiers réellement servis sur l'alias public : le chunk `793.eb4cb8c4.chunk.js` contient les routes `/cj-draft`, `/cj-sync` et la confirmation `confirm_create_unpaid_draft`. Cela vérifie la présence du panneau compilé, sans remplacer un test authentifié dans l'administration.

## Ce que cette publication ne valide pas

Les suites préparatoires totalisent522 tests Python,148 contrôles SQL et508 tests frontend. Elles prouvent les gardes et les scénarios simulés, pas la réception d'une commande réelle chez CJ. Aucun brouillon CJ créé et aucun paiement fournisseur exécuté. Aucune photographie, CSS, page publique ou prix public modifié.

Le premier produit reste en attente de données exactes Soyintech et d'une variante CJ approuvée, du magasin cible confirmé/configuré et d'un devis unitaire. La préparation technique publiée ne remplace pas ces données. Dernier échange CJ et demande sur les frais : `SUPPLIER_MESSAGES_2026-11-04.md`.
