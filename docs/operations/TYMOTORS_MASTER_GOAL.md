# PHOENIX — contrat de mission et reprise

Autorité : instructions du propriétaire du24octobre2026, « MAKE TYMOTORS FULLY OPERATIONAL ». Cette mission prolonge `../COMMERCE_WORKFLOWS.md`, elle ne recommence pas le projet.

## Objectif non réduit

Fournisseur d'origine → HyperSKU (prestataire envisagé, services à confirmer) → produit/variante → véhicule compatible → prix et livraison vérifiés → panier → Stripe → commande → agent TYMotors → fulfillment HyperSKU autorisé → expédition multicolis/suivi → incidents/retours/remboursements.

Réussite : cinq articles réellement validés commercialement et un parcours complet prouvé en sandbox réel avant extension progressive aux40. Un simulateur n'est ni une connexion HyperSKU ni un paiement Stripe réel. Un prix non documenté reste inconnu. Aucun objectif intermédiaire de code ou de tests ne clôt cette mission.

## Invariants absolus

- Design définitif : aucun changement de couleurs, typographies, animations, espacements, bordures, effets, images/galeries, composants, responsive, mise en page ou administration. Frontend seulement pour raccorder les données aux contrôles existants ; tout besoin visuel attend un accord.
- Images/fichiers inchangés. Signaler les droits manquants et bloquer la commercialisation, pas remplacer ou supprimer les photos. Refus SCP à respecter sans détour.
- Pas de prix public modifié, publication, déploiement production, achat, paiement réel, commande HyperSKU, engagement financier, message externe ou migration destructive sans autorisation humaine distincte.
- Aucune référence, compatibilité, disponibilité, taxe, coût, livraison, licence, endpoint/auth API ou réponse fournisseur inventé. Conserver source/date/portée et distinguer preuve/hypothèse.
- Ne pas exposer secrets, données client, coûts privés ou service_role. Aucun secret demandé dans le chat. Stripe isolé en test uniquement, signature et idempotence côté serveur.
- Ne pas confondre fournisseur, HyperSKU, vendeur TYMotors et agent responsable. Pas de substitution d'offre sans équivalence prouvée.

## Gouvernance

Le chef attribue des périmètres disjoints ; l'auditeur ne développe pas le lot qu'il contrôle. Ressources réelles :4agents simultanés au total, chef compris ; dix fonctions métier réparties par lots. Aucun agent ne valide seul. Décisions par périmètre : APPROVED (tous critères prouvés), REJECTED (défaut corrigible), BLOCKED (dépendance externe documentée). Une approbation locale n'est pas une autorisation commerciale.

Chaque lot : développer → tester → audit contradictoire → correction → nouveau test → décision du chef → suivi. Préserver les fichiers tiers et les sources historiques. Branche dédiée `codex/commerce-workflows`, backend dans `scp-release/backend`, frontend associé inchangé ; les checkouts originaux contiennent des travaux privés à préserver.

## Acceptation requise

Pour chaque article/SKU : origine et variante exactes, montage (modèle/génération/année/châssis/phase/carrosserie/finition/options/fixations), titre/description fidèles, droits des fichiers/logos, offre datée/devise/MOQ/disponibilité, coût complet, taxes/frais paiement, livraisonFrance/délai/garantie/retour, agent, mappingHyperSKU et preuve. États par dimension simultanés, publication séparée.

Pour chaque commande : même référence/variante à toutes les étapes ; prix/port/taxes/adresse/agent conservés ; montants et références historiques immuables ; doubles paiements/commandes/événements/transmissions empêchés ; perte de réponse/retry/interruption traitées sans nouveau paiement aveugle. Dépenses soumises à validation humaine au lancement.

Tests critiques A–M : véhiculecompatible/incompatible, variantes proches, tarifs modifiés/historique, destinations vérifiées, paiementréussi/refusé/annulé/expiré/replay/désordre, créationunique, attributionoffre/agent, mappingHyperSKU et transmissionsimulée qualifiée, multicolis/suivi, rupturesréférences/stock/adresse/transport/coûts/sync/pertecolis, permissions/secrets/webhooks/idempotence, absence de changementsvisuels/fichiersimages. Vrai sandboxStripe requis ; concurrencePostgreSQL/GoTrue/PostgREST ne sont pas prouvés parPGlite.

## Reprise obligatoire

Lire MASTER_GOAL, PROGRESS, BLOCKERS, QA_REPORT, SUPPLIER_STATUS et contrats de ce dossier ; vérifier git/branche/diff et les preuves réelles ; reprendre la tâche inachevée indiquée, pas le projet entier. Enregistrer étapes/tests/erreurs et prochaine action avant interruption. Ne pas prétendre à un travail permanent ou à une reprise autonome du produit si l'exécution s'arrête. Le statut du goal produit antérieur était usageLimited ; cela ne remplace pas ce contrat ni ne prouve une exécution en arrière-plan.
