# TYMotors — tableau de pilotage PHOENIX

Dernier contrôle : 25 octobre 2026. Branche locale `codex/commerce-workflows`.
Ce rapport ne vaut ni publication ni autorisation de vendre.

## Catalogue réel

Source : génération privée `backend/data/phoenix-2026-10-25/dossiers-40.json`
dans le checkout historique, à partir des preuves fournisseur conservées et
d'une nouvelle lecture API du catalogue. Aucun fichier fournisseur privé dans Git.

| Indicateur | Mesure vérifiée |
|---|---:|
| Articles avec dossier individuel et prochaine action | 40/40 |
| Articles entièrement vérifiés / commercialement approuvés | 0/40 |
| Articles commercialement bloqués | 40/40 |
| Publication observée : brouillon | 40/40 |
| Candidats pilotes / pilotes approuvés | 5 / 0 |
| SKU Soyin proposés, sans sélection d'offre validée | 18 |
| Fournisseurs effectivement retenus et confirmés | 0 |
| Compatibilités exactes confirmées pour le SKU approvisionné | 0 |
| Prix d'achat / livraison France confirmés | 0 / 0 |
| Coûts complets et marges calculables | 0 |
| Mappings HyperSKU commerciaux confirmés | 0 |
| Articles avec autorisation positive complète des images | 0 |
| Nouveaux messages fournisseurs envoyés pendant ce lot | 0 |

Les six contrôles restent chacun en attente pour les40 : fournisseur, HyperSKU,
compatibilité, prix, livraison, droits. Une référence proposée ou une restriction
trouvée sur une annonce similaire n'authentifie pas le SKU finalement acheté.
Les chiffres historiques «37 messages /5 formulaires» ne sont pas recomptés ici
comme un état actuel démontré. Deux pièces jointes déjà connues ont été retrouvées,
sans nouvelle confirmation. Aucun contact extérieur autorisé dans ce lot.

## Fonctionnement et limites

| Module | Preuve / état réel |
|---|---|
| Associations produit–variante–offre–agent–devis | Testées sur données synthétiques ; pas d'offre commerciale validée |
| Droits des images | Autorisation positive exigée pour chaque fichier actuel ; refus SCP non contournable ; photos inchangées |
| Tarifs et finance | Calculs privés sur instantanés serveur, données manquantes jamais remplacées par zéro ; prix publics inchangés |
| Commande et attribution | Transaction et idempotence testées avec transport Stripe FAKE |
| Suivi multi-fournisseurs/multi-agents/multi-colis |91 assertions HTTP chef et91 indépendantes PASS, statut réel requires_review conservé |
| Stripe : vrai réseau | Création/binding/lecture Checkout SDK prouvés ; trois sessions de test closes expired/unpaid ; zéro paiement réussi |
| Inspection Stripe privée | Lecture seule d'une session liée côté serveur ; ne règle, rembourse, recrée ni libère rien. Recette réseau propre à cette route non faite |
| HyperSKU | Connexion web observée ; API, devis, tarifs et variantes encore non confirmés. Paquets internes seulement, transmission interdite |
| Paiement live | Verrouillé sans dérogation par un simple flag ou une activation produit |
| Design, frontend, photographies, prix publics | Aucun changement dans ce lot |

Suite Python complète après les corrections d'inspection : **1298 PASS**, un
avertissement Starlette préexistant (31,03s). Recettes SQL devis98 et tentatives111
PASS ; recette HTTP/SQL standard557 de nouveau PASS sur les fichiers finaux.
Contre-audit indépendant de l'inspection :145 tests PASS après correction de
deux P2. Verdict APPROVED lecture locale seulement ; aucun nouveau paiement réussi.
Voir QA_REPORT pour les verdicts indépendants et les reprises après correction.

## Ce qu'il reste effectivement à faire

**A — Codex.** Journal durable et rapprochement financier revus pour les résultats
provider inconnus, transaction dédiée aux remboursements quoted, recette de
concurrence PostgreSQL isolée, puis raccordement des vraies preuves aux variantes.
L'inspection seule ne clôt pas ces travaux. Ne pas libérer les réservations de
test simplement parce que le paiement est enregistré ou la session expirée.

**B — Fournisseurs / HyperSKU.** SKU et variantes exacts, montage/exclusions,
droits sur les fichiers existants et marques, devis datés/devise/MOQ,
port France/délai/conditions/garantie/retour ; accès et contrat HyperSKU officiels.
Préparer les demandes complémentaires, sans les envoyer sans autorisation.

**C — Administrateur / accès.** Rétablir le navigateur intégré pour terminer
le Checkout de test sans carte réelle ; connecter durablement la sandbox par
le parcours sécurisé du runbook si nécessaire. Désigner l'agent humain, valider
les choix d'offre et la fiscalité/conditions légales/marge minimale.
Ne fournir aucune clé secrète dans la conversation.

Après ces dépendances : vrai paiement sandbox → webhook signé → commande unique
→ attribution agent → préparation HyperSKU interne contrôlée, puis validation
des cinq pilotes. Toute dépense, transmission fournisseur et publication reste
soumise à autorisation humaine distincte.

## Dernier jalon — pont client,25octobre2026

| Indicateur | Résultat vérifié |
|---|---|
| Articles / candidats pilotes |40 /5 dans le snapshot privé daté05:41+01 relu ; pas une nouvelle réponse fournisseur |
| Articles / pilotes validés commercialement |0/40 et0/5 |
| Offre sélectionnée, fitment, prix, portFrance, marge ou mappingHyperSKU confirmés |0 par dimension pour les références à commercialiser |
| Backend complet |1452 pytest PASS,1 warning préexistant |
| Frontend complet |583 tests/38 suites PASS,exit0 (forceExit explicite) |
| Build / lint |CompilationCI et lintPASS,artefact local seulement |
| Dernier parcours public isolé |173 HTTP/SQL chef puis173 indépendants PASS,StripeFAKE,1create/commande/tâche |
| SQL propriétaire / admin indépendants |137 /66 PASS,PGlite sérialisé |
| Paiements sandbox achevés / transmissionsHyperSKU réelles |0 /0 |
| Modifications de rendu/photo/prix public / publication |0 pour chacun |

Le pont propriétaire sandbox et la confirmation pré-webhook sont APPROVED
localement, pas le parcours commercial. Cart.jsx reste legacy, collecte adresse/
mode et sélection multivariantes attendent autorisation UI minimale. Navigateur
ne permet pas actuellement de terminer le Checkout ; aucune nouvelle session créée.
La suite173 n'est pas ajoutée aux anciennes153/557 qui se recouvrent. Rapport
détaillé : CUSTOMER_CHECKOUT_QA_2026-10-25. PréparationsHyperSKU et colisSIM ne
prouvent ni connexionAPI, ni tarif, ni expédition. Aucun nouveau message externe.
