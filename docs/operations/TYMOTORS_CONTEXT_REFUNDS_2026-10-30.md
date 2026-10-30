# Projection financière des remboursements par compte/profil

## Périmètre

Le module commerce_context_refunds.py traite uniquement des événements dont la
signature du corps brut a déjà été vérifiée par le receiver existant. Il revérifie
le mode et le compte serveur avant normalisation. Aucun appel Stripe, création
de remboursement, achat, restauration de stock ou envoi de courriel.

La migration20261030151428 ajoute un journal immuable de champs financiers
minimaux. La clé d'événement inclut compte/is_test ; le profil est également
conservé et contrôlé. Aucun payload client ou métadonnée ne choisit une commande.

Le montant cumulé additionne chaque identifiant de remboursement réussi une
seule fois, après corroboration du paiement par commande/devis/tentative/session
et événement payé immuable dans le même compte, profil et mode. Les observations
charge.refunded sont cumulatives et ne sont jamais ajoutées comme des deltas.
Les observations pending/failed/canceled/null ne prouvent pas un remboursement.

Une contradiction de devise, montant, PI, profil ou statut terminal impose la
revue et ne remplace pas un montant financier déjà établi. Les événements reçus
avant le paiement sont conservés puis projetés par le trigger après règlement.
Des verrous advisory non bloquants partagent le périmètre de paiement ; une
course doit réessayer l'événement plutôt que perdre une observation.

## Revue administrative et limites

La route POST /api/admin/commerce/context/orders/{order_id}/refund-review exige
l'administrateur existant, la version updated_at attendue et une référence de
preuve. Elle relance la projection et écrit un audit. Elle ne lève jamais la
quarantaine financière : review_released reste false.

La réception signée seule ne résout pas les cas inconnus, les contradictions ou
les promesses fournisseur. Les reçus requires_reconciliation et le marqueur de
revue restent conservés. Aucun remboursement n'est automatiquement envoyé au
client, aucun montant manquant n'est estimé et aucune expédition n'est débloquée.
La résolution définitive des revues demeure une décision distincte.

## Raccords effectués

- Après vérification HMAC et scope, les quatre événements refund.created,
  refund.updated, refund.failed et charge.refunded sont dirigés vers
  record_signed_context_refund depuis ContextCheckoutPayments.accept_signed_event.
- create_context_refund_router(db, require_admin) est enregistré dans server.py.
- Les anciennes attentes de tests identity-only sont remplacées par un contrôle
  des champs financiers réellement signés, sans donnée client persistée.
- La migration est incluse dans la chaîne de fixture gelée. Le probe dédié
  utilise cette chaîne et ne réapplique plus lui-même la migration.

## Preuves à distinguer

-112 tests Python de normalisation, scope serveur, contrat HTTP admin et service
  contextuel réussis après raccordement (184,62s, sortie0). Aucun appel Stripe réel.
- Sauvegarde/restauration PostgreSQL17.11 et application24+22 migrations réussies,
 1 696 champs historiques conservés et garde commerciale false. Cela vérifie
  l'application de la nouvelle migration sur le moteur natif, pas encore son
  parcours métier complet ni une base distante.
- Deux tentatives du probe SQL/HTTP dédié ont échoué au démarrage des fixtures
  (Disposable fixture readiness timed out), avant le parcours métier. La première
  a atteint la disponibilité SQL ; la seconde n'a pas atteint la disponibilité
  SQL/API dans le budget. L'hôte était sous forte pression mémoire ; cette
  observation ne remplaçait pas une recette réussie.
- Après libération des ressources : recette sortie0 avec655 checks socle,
  252 checks contextuels et96 checks remboursement PASS. Les dix derniers
  vérifient explicitement le refus d'un ancien reçu de paiement après
  remboursement, sans token d'envoi et avec blocage financier conservé.
  TransportStripeFAKE_HTTPX_WITH_REAL_SDK,0paiement/0remboursement réel.
- Contre-audit indépendant de source et des assertions acquis ; ne pas présenter
  cette recette locale comme un encaissement réel ou une preuve de concurrence native.

Aucun déploiement, secret, prix public, photographie ou design modifié.
