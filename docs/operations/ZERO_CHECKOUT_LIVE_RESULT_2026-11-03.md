# Article interne gratuit — résultat réel du 3 novembre 2026

## Résultat confirmé

À la demande du propriétaire, création d'un article TYMotors interne à 0 EUR et d'une commande diagnostique en production, puis finalisation de son Checkout Stripe live sans carte, débit, achat fournisseur ni expédition.

| Élément | Preuve |
| --- | --- |
| Article TYMotors | `TY-INTERNAL-ZERO-DIAGNOSTIC`, slug `internal-zero-diagnostic`, prix 0, stock 0, statut archived, non vérifié et absent du catalogue public |
| Commande | `TY-DIAG-A19A1078153E4695`, UUID `d8ae0c51-5274-4878-8e23-3d7f38ac20eb` |
| Session Stripe live | `cs_live_a1l0TUR3lEB6MOhrPz1NGUSb5yXTgxJodnfstI7aoLJIYmL3bW97yBi94o`, complete, paid, amount_total=0, payment_intent=null |
| Webhook signé | `evt_1UXgxLJB6441TWWotlZ1QKAZ`, checkout.session.completed, live, session correspondante, pending_webhooks=0 |
| Traitement backend | stripe_events completed sans erreur ; commande payment_status=paid, status=paid, paid_at=2026-11-03 12:37:25 UTC |
| Isolation | is_test=true, sales_channel=diagnostic, fulfillment_status=requires_review, une ligne, un audit order.paid, aucun dossier supplier_orders, stock inchangé à 0 |

## Méthode et limites

La création de l'article et de la commande a utilisé la RPC atomique `create_admin_zero_diagnostic_order` via le connecteur Supabase autorisé. La session Stripe a été créée via le connecteur Stripe, associée à cette commande et tracée dans admin_audit comme `authorized_connector_diagnostic`. Le formulaire Stripe a ensuite été finalisé dans le navigateur ; le webhook réel a exécuté la confirmation de commande du backend.

Le bouton admin appelle la même RPC via la nouvelle route protégée. Son interface et son endpoint sont testés localement ; la route déployée renvoie bien 401 sans authentification. **Le clic du bouton avec une session admin réelle n'a pas été exécuté**, car l'onglet admin reste sur le formulaire de connexion. Pour cette même raison, la page order-success du diagnostic propriétaire affiche « Confirmation indisponible » dans le navigateur non connecté ; la commande est cependant confirmée en base. Ne pas supprimer le contrôle d'accès pour afficher cette commande.

Ce résultat confirme **article interne → session Stripe live à 0 EUR → webhook signé → commande TYMotors payée**, avec la création de commande amorcée par connecteur. Il ne valide pas le panier public, un encaissement bancaire, la compatibilité d'une pièce ou une transmission CJ. Aucun fournisseur ni agent CJ ne doit être déclaré connecté à partir de ce diagnostic.

## Livraison technique

- Migration appliquée : `20261103072605_admin_zero_checkout_diagnostic` ; RPC refusée à authenticated et autorisée seulement à service_role. Fonction commerciale complete_paid_order comparée au code source avant remplacement : corps identique à la migration de base, MD5 `b0fa7aa75fd6d5231be86cf1502f7477`.
- Backend PR #7 fusionnée : `a437d5280bc0e149cca49b81f39a2705af235f8a`, Render live sur cette référence.
- Frontend PR #7 fusionnée : `36ef097f30413dcba524cf53f6a08b09a0b20429`, Vercel production READY, `dpl_3XxTKgSAGVNtEGenstpvq2bXsCi7`.
- Tests locaux : 461 Python, 111 contrôles SQL isolés, 6 tests du panneau admin ; build/lint et contrôles GitHub réussis. Aucun design, image ou prix commercial modifié.
- Plusieurs anciens processus Jest TYMotors de la veille ont été arrêtés après vérification de leur commande et date pour libérer la mémoire ; aucun runtime Codex ni fichier supprimé.

Prochaine étape de vérification d'interface : connexion au compte admin, Paramètres → diagnostic gratuit, puis consultation du dossier. Le catalogue commercial conserve ses blocages fournisseur et CJ documentés séparément.
