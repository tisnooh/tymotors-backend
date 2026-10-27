# TYMotors — journal des remboursements sandbox

## Périmètre et décision

Suite de « Continue et finis », sur `codex/commerce-workflows`, backend
`scp-release/backend`. Ce lot ferme la perte de preuves des remboursements
signés des commandes à devis. Il ne clôt ni l'ouverture de la boutique, ni
l'ensemble du rapprochement financier.

Décision du Chef : **APPROVED LOCAL pour ce lot**, après contre-recette et
pytest global finaux. Aucun déploiement ni validation commerciale déduits.
Ouverture commerciale : BLOCKED sur les preuves disponibles.

## Corrections exécutées

- Réception après vérification SDK de la signature sur les octets bruts et du
  mode test. Les `refund.created/updated/failed` et `charge.refunded` sont
  normalisés vers dix champs financiers, sans métadonnées ni données client.
- Journal privé append-only, RLS, sans droits anon/authenticated et sans
  UPDATE/DELETE/TRUNCATE, y compris pour service_role. Aucun fichier photo touché.
- Une identité `re_` n'est comptée qu'une fois, malgré plusieurs événements et
  leur ordre d'arrivée. Seuls les montants `succeeded` non contradictoires sont
  projetés ; un montant cumulé de Charge n'est jamais additionné à un Refund.
- Association par PI corroboré avec commande test, devis, tentative, session,
  montant/devise et historique immuable de paiement. Aucune association par
  `metadata.order_id`, ressemblance de référence ou déclaration client.
- Événement reçu avant paiement local conservé ; après règlement signé, son
  rapprochement intervient avant toute création de tâche simulée. Une anomalie
  métier conserve le reçu et exige un contrôle, plutôt que d'effacer la preuve.
- Drapeau financier persistant et garde sur le journal : pending/failed/unknown,
  montant contradictoire ou sur-remboursement restent en revue, même avec zéro
  centime comptabilisé. Les tâches et préparations existantes sont conservées
  mais ne peuvent plus progresser/rejouer leur autorisation.
- Remboursement partiel/total monotone ; aucun ancien succès de paiement ne
  ressuscite une commande remboursée. Pas de libération de réservation, mutation
  de stock, suppression d'historique, email, remboursement émis ni envoi fournisseur.
- Suivi SIM agrégé `held` pendant la revue ; événements historiques conservés,
  drapeau privé retiré de la réponse publique. Aucun composant/design modifié.
- Ancien chemin non-quoted conservé, y compris avec référence PI développée.
  Le nouveau journal ne transforme pas un remboursement test en remboursement live.

Migration additive préparée uniquement :
`20261027031114_commerce_test_refund_ledger.sql`, créée par la CLI Supabase locale.
Aucune migration appliquée à un serveur hébergé.

## Contrôle contradictoire

L'auditeur a rejeté la première livraison pour deux défauts : référence PI
développée transmise brute au chemin historique et projection SIM ignorant un
blocage financier sans montant. Corrigés et contre-testés. La lecture de
métadonnées malformées avant normalisation a également été supprimée.

Le premier global comptait 1701 PASS et un échec : l'ancienne fixture de replay
ne possédait aucun `data.object`. Fixture rendue représentative d'un événement
Stripe ; aucun contrôle de production affaibli pour la faire passer.

Chef : 320 tests ciblés PASS en 8,83 s ; auditeur : mêmes 320 PASS en 10,88 s.
Chef : 655 contrôles pipeline existant + 137 remboursements = **792 HTTP/SQL PASS**,
sur migration finale, signature SDK réelle avec secret HMAC local.
Transport Stripe **FAKE**, zéro remboursement réel et zéro appel fournisseur.

Contre-recette indépendante : **792 HTTP/SQL PASS**, exit 0 ; huit hashes
identiques avant/après, ports 8765/8766 libérés et diff check sans erreur.
Global final Chef : **1726 pytest PASS en 20,59 s**, exit 0 ; seul avertissement
préexistant de dépréciation Starlette/httpx. Gitleaks 8.24.3 sur diff staged :
aucune fuite détectée. Aucun besoin d'élargir une exception de secrets.

| Contrôle | Résultat final | Portée |
|---|---|---|
| Pytest global |1726 PASS|Code local, pas une preuve commerciale|
| HTTP/SQL Chef |792 PASS|655 parcours + 137 remboursements, FAKE|
| HTTP/SQL indépendant |792 PASS|Même version figée, aucune écriture de l'auditeur|
| Ciblés indépendants |320 PASS|Normalisation, signature, legacy, observation, SIM|
| Remboursements réseau Stripe |0 exécuté|Non validés par ce lot|
| Produits pilotes approuvés commercialement |0/5|Preuves externes toujours manquantes|
| Modifications design / photos / prix publics |0|Frontend propre, HEAD 6772ba6|
| Migration hébergée / déploiement / achat |0|Interdictions conservées|

Les contrôles couvrent notamment signature/mode invalides sans écriture,
schéma/RLS/immutabilité/RPC privés, replay, doublon par `re_`, désordre,
remboursement avant règlement, devise/identité/total incohérents, états non
réussis non monétaires, référence développée historique, garde avant préparation
et replay, suivi public expurgé et absence d'effets stock/mail/fournisseur.

## État fournisseurs et ouverture

Recherche Gmail actualisée le 27 octobre vers 03:10 UTC, avec spams et messages
depuis le 26 octobre, domaines/interlocuteurs des fournisseurs et HyperSKU.
Pas de page suivante et aucune nouvelle confirmation technique complémentaire.
Les réponses Ikon/Maxton déjà traitées et rappels automatiques ne sont pas de
nouvelles validations. Pas de nouvelle relance quelques heures après les quatre
SENT du 26 octobre à 20:25 UTC.

Dernière lecture catalogue : **26 octobre 20:28:25 UTC**, 40 brouillons.
Le présent lot ne prétend pas à une nouvelle lecture commerciale de l'API.
Les cinq pilotes, leurs divergences et devis attendus restent décrits dans
`TYMOTORS_PRELAUNCH_REVIEW_2026-10-26.md` ; 0 pilote commercial approuvé,
0 marge pilote calculable sur les pièces disponibles. Inconnu reste null, pas 0€.

## Limites et prochaine reprise

1. Remboursements ici simulés avec signature locale ; aucun test de remboursement
   réseau Stripe n'est revendiqué. La recette réelle de paiement du 26 octobre
   reste une preuve séparée, pas une preuve de cette nouvelle transaction.
2. PGlite mono-connexion ne prouve pas la concurrence PostgreSQL hébergée.
   Aucun docker/psql/pg_ctl/postgres accessible via PATH lors du contrôle local ;
   ne pas appliquer cette migration en production pour obtenir un test.
3. Résolution humaine des anomalies, tentatives ambiguës sans paiement lié,
   restitution/consommation de réservations et litiges/reversals restent des
   procédures distinctes à développer et tester. Aucun retry aveugle permis.
4. Réponses fournisseurs : références exactes, montage/droits, coût rendu France,
   disponibilité/garantie/retours. HyperSKU : contrat API/authentification, Store ID,
   vrais SKU/variantes et devis France toujours non établis dans les preuves relues.
5. Fiscalité, seuil de marge, responsable opérationnel et validation légale restent
   des décisions administrateur. Aucun prix public, photo, activation live ou achat.

Références de contrat consultées par la CLI officielle Stripe 1.53.1 :
[objet Refund](https://docs.stripe.com/api/refunds/object),
[webhooks](https://docs.stripe.com/webhooks). Statuts nullable, livraison désordonnée,
références développables et vérification sur corps brut pris en compte.
Consignes Supabase : invoker/search_path vide, RLS et droits service-only ;
aucune documentation ne remplace les tests de cette migration locale.

Reprise : lire ce rapport et les journaux ; vérifier branche/diff et nouvelles
réponses avant de relancer quiconque. Ne pas recréer une charge Stripe ni une
commande fournisseur pour contourner un résultat ambigu. Aucun travail permanent
en arrière-plan ou déploiement n'est promis par cette clôture locale.
