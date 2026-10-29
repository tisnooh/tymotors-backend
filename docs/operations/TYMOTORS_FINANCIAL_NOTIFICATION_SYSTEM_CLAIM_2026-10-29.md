# Préparation des revendications système de notifications financières

Date : 29 octobre 2026. Périmètre local uniquement, activation désactivée.

## Contrat

- Migration : `20261029011039_commerce_financial_notification_system_claim.sql`, générée avec la CLI Supabase locale.
- RPC ajoutée : `commerce_claim_financial_notification(p_id uuid, p_token uuid, p_ready boolean) RETURNS jsonb`.
- RPC administrateur conservée : `admin_claim_order_notification(p_actor uuid, p_id uuid, p_token uuid, p_ready boolean)`.
- Cœur unique : `private.claim_order_notification_core(uuid, uuid, uuid, boolean, text)`. Les seuls principaux sont `admin` et `systemfinancial`. Le premier conserve ses contrôles administrateur ; le second exige un acteur NULL, sans usurpation d'administrateur.
- Nouvelle garde persistante du singleton existant : `shop_settings.financial_notification_auto_enabled boolean NOT NULL DEFAULT false`.
- Aucune seconde file, aucun nouveau mécanisme de complétion, aucune API de bascule, aucune interface, aucun historique reconstruit. L'API settings existante utilise une liste explicite de champs et ne permet pas d'écrire cette colonne.

Le nouveau RPC et le cœur sont exécutables uniquement par `service_role`, avec `SECURITY INVOKER` et chemin de recherche vide. Les permissions du RPC administrateur existant sont préservées.

## Invariants

La garde est contrôlée dans le cœur système, pas uniquement dans son wrapper. Faux, singleton absent ou lecture refusée retournent `{claimed:false,state:"disabled"}` sans modifier de journal. `p_ready=true` ne contourne pas cette garde.

La lecture de garde prend un verrou partagé sur le singleton jusqu'à la fin de transaction ; l'ordre des autres verrous reste commande puis journal. Une désactivation concurrente attend un claim déjà engagé, puis bloque les claims suivants. Elle ne révoque pas rétroactivement une revendication ni un transport éventuellement commencé. Ce comportement ne constitue pas une preuve de concurrence PostgreSQL native : le banc local utilise PGlite.

Le système ne peut revendiquer que `payment_confirmed` ou `refund_confirmed`, avec snapshot financier existant et source `atomic_financial_transition`, lié à une commande non-test. Les journaux legacy, les autres catégories et sources sont refusés sans conversion. Les états claimed, unknown et sent ne sont jamais revendiqués à nouveau.

Le même validateur financier contrôle toujours propriétaire figé, montants, EUR, identifiant de paiement, remboursement cumulatif exact, état financier actuel et absence de revue financière. Un changement de fulfillment seul ne remplace pas la validation financière. Un changement financier invalide le dossier en unknown ; aucune relance aveugle n'est ajoutée. Le destinataire reste celui du snapshot. Le journal d'audit d'un claim système comporte `principal:systemfinancial` et un acteur administrateur NULL.

Les résultats de transport utilisent le RPC de complétion existant et le jeton unique. Couper la garde n'empêche pas d'enregistrer un résultat déjà connu. Aucune revendication ne prouve une acceptation SMTP, une réception client ou une identité Stripe authentifiée.

## Vérifications et état

`py_compile` du nouveau module de recette : PASS. Recette SQL/HTTP et audit indépendant : en attente du câblage et de l'exécution par le responsable du lot. Le fichier est figé pour cette exécution ; aucun port ni serveur n'a été lancé par son développeur.

La recette `tests.commerce_financial_notification_system_http_probe` réexécute la régression financière précédente avant ses cas système : garde false, accès direct au cœur, singleton absent, lecture refusée, permissions, acteur invalide, configuration indisponible, arrêt et reprise, double claim admin/système, états terminaux, exclusions legacy/source/test/fulfillment, propriétaire modifié, état financier modifié et remboursement exact. L'activation temporaire n'existe que dans cette base de test jetable et est remise false dans un `finally`.

## Limites et décision

Statut : **APPROVED LOCAL — préparation inactive**. Chef et auditeur ont exécuté
655+95+90 contrôles HTTP/SQL, sorties0. Python global Chef2 600 PASS et ciblés
indépendants120 PASS. Garde finale false et ports8765/8766 fermés vérifiés.
Un premier probe a révélé une collision de PI fictif avec le scénario précédent ;
UUID unique et diagnostic corrigés sans modifier les règles métier.
Le worker accepte désormais le libellé SQL not_eligible, avec contre-test du lot.
Empreintes SQL36F5B25B…A61F08 et probeDDA8B588…3D87E5 stables après contre-test.
Ce document n'accorde aucune activation. L'éventuelle configuration future exige
une autorisation distincte et une recette du transport adaptée. Aucun déploiement,
paiement live, email, appel fournisseur ou changement design/photo/prix.
La confirmation de commande legacy reste hors de ce lot. PGlite ne prouve pas
la concurrence PostgreSQL native ; aucun SMTP ou email reçu n'est validé.
