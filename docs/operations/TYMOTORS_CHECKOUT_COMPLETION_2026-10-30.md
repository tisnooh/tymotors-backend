# Livraison technique du 30 octobre 2026

Branche backend et frontend : codex/commerce-workflows.

## Corrections

- Notifications financières raccordées au cycle de vie du serveur, opt-in
  désactivé par défaut et arrêt SQL indépendant conservé.
- File limitée aux reçus pending : blocked/claimed/unknown/sent exclus.
- Réservation SQL dans l'ordre gate -> commande -> reçu, état pending revérifié
  sous verrou ; pas de reprise automatique d'un envoi incertain.
- Événements de remboursement authentifiés et liés au compte, mode et profil,
  projection idempotente, blocage financier conservé et revue administrateur tracée.
- Frontend : URL Checkout liée au mode serveur ; isolation reçu/compte/session ;
  centimes conservés ; accès commandes indépendant des préférences newsletter ;
  ancien traitement admin refusé pour commandes contextuelles.
- Aucun fichier image, CSS, prix public ou mise en page changé.

## Preuves acquises

- Backend global : 3007 pytest PASS, 72,98s, sortie0.
- Frontend global : 724 tests / 47 suites PASS, 110,275s, sortie0.
- Frontend lint et build PASS (GENERATE_SOURCEMAP=false, exécution seule).
- Recette SQL/HTTP : 655 checks socle,252 checks contextuels et96 remboursements
  PASS, transport FAKE_HTTPX_WITH_REAL_SDK ; aucun paiement/remboursement réel.
- Contre-audit indépendant de source frontend et projection remboursement PASS.
- Ancien reçu après remboursement explicitement refusé : aucune réservation
  d'envoi et blocage financier conservé, dans la recette96checks.
- Notifications :655checks socle+95outbox+93réservations système PASS après
  correction de la classification des reçus historiques. Aucun SMTP ni appel
  fournisseur. Blocage automatique conservé et récupération admin explicite testée.
- Manifest23 migrations préparé avec SHA256 ; aucune migration distante appliquée.

Les premiers runs concurrents ont saturé la mémoire (environ101Mo libres sur
3,39Go visibles). Les suites relancées seules passent sans délai augmenté.

## Production et reprise

Stripe relu via le connecteur du compte TYMotors : contexte accessible en test,
charges_enabled=false, payouts_enabled=false, details_submitted=false.
Ce constat ne détermine pas à lui seul quelle pièce d'immatriculation manque.
Le simple retrait des badges test ne rendrait pas les encaissements possibles.

Aucun déploiement production de ce lot, achat ou envoi fournisseur. Les profils
commerciaux sont suivis séparément dans TYMOTORS_ACCOUNTS_2026-10-30.md.
Le push de branche doit être distingué du déploiement et de l'ouverture commerciale.

Frontend poussé : a682e50 ; previewGitREADY dpl_6u3adSqPq7icWcXC6zMttHGcqmic.
Production existante relue parCLIscopé : b5847e590a79b389cd33303e3fc3b2b3c89baa0f,
dpl_FMjsEdJ8oBfBpKfkN5kNTv2kLbt7,READY. Le connecteur listdeployments refusait403 ;
fallbackCLIlecture acquis. Pas de promotion frontend isolée : la branche contient
également les variantes et devis dépendant des migrations et du backend à publier
ensemble, sous peine de casser l'ajout au panier de l'ancien serveur.

Le propriétaire a ensuite autorisé les champs administrateur nécessaires aux
preuves fournisseur et au suivi par colis, avec les styles existants. Ce lot
frontend supplémentaire est en cours et fera l'objet d'une recette séparée.
