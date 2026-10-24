# Préparation durable des paiements de test

Extension locale suivante : voir `COMMERCE_TEST_PIPELINE.md` pour le service SDK test, le webhook dédié et l'allocation/suivi simulés ajoutés depuis ce checkpoint. Aucun paiement Stripe sandbox réel ni checkout public de variantes n'est validé.

Périmètre local uniquement. Aucun appel Stripe, paiement, débit du stock réel, commande fournisseur ou modification visuelle. La migration et ses limites sont détaillées dans `COMMERCE_ATTEMPTS_SCHEMA.md`.

## Routes administrateur

- `POST /api/admin/commerce/orders/{order_id}/checkout-attempt` : commande test pending/unpaid issue d'un devis figé ; prépare une tentative et ses réservations fictives, construit les paramètres exclusivement côté serveur, puis les enregistre une fois. Limite : 20 préparations par commande et par heure. Disponible uniquement en configuration test.
- `GET /api/admin/commerce/checkout-attempts/{attempt_id}` : retrouve l'état persistant sans exiger que le panier subsiste. Un identifiant absent donne 404.
- `POST /api/admin/commerce/checkout-attempts/{attempt_id}/cancel-draft` : annule uniquement une préparation jamais revendiquée par un worker et libère ses réservations fictives. Disponible uniquement en configuration test.

Les trois routes exigent le contrôle administrateur existant. Les UUID sont validés par FastAPI. Le corps client ne configure ni montant, ni mode, ni expiration, ni origine de redirection. La projection autorisée contient seulement les identifiants tentative/commande, état, mode test, expiration, indicateurs `expired_locally` et `requires_reconciliation`, `payment_available=false` et la portée explicite `durable_test_preparation_not_checkout`. Aucune clé d'idempotence, adresse, référence/coût fournisseur ou paramètre Stripe n'est exposé.

## Reprise et ambiguïtés

Une préparation répétée retrouve la tentative existante : elle ne renouvelle pas sa clé ou son expiration, et ne recalcule pas un prix ancien. Si l'enregistrement des paramètres réussit mais que la réponse réseau se perd, aucun nettoyage automatique n'est tenté : l'appel suivant retrouve l'état enregistré.

Un refus du constructeur avant tout appel fournisseur de paiement tente une annulation sûre. La base refuse cette annulation si un autre worker a déjà revendiqué la tentative. Les états `creating`, `unknown` et le futur `session_created` exigent une réconciliation ; l'expiration locale ne prouve pas l'absence de paiement et ne libère pas leurs réservations.

Le validateur pur `commerce_checkout_events.py` contrôle un objet session contre les instantanés : identifiants, mode, devise, montants, expiration et destination. Il distingue paiement financièrement confirmé et destination divergente, afin qu'un paiement reçu ne soit pas effacé par un refus de livraison. Il ne vérifie PAS une signature webhook et n'enregistre aucun paiement. Ne pas le présenter comme un webhook opérationnel.

## Preuves et limites

Tests dédiés unitaires, SQL/PGlite et probes HTTP utilisent uniquement des données synthétiques et un pont SQL local. La restauration est vérifiée en redémarrant le processus FastAPI tout en conservant le moteur SQL de test : l'état `unknown`, ses réservations et le refus d'annulation subsistent. Cela ne prouve ni reprise d'un fournisseur externe, ni durabilité disque du moteur jetable, ni concurrence multiconnexion, ni fonctionnement GoTrue/PostgREST hébergé.

Avant toute activation : adapter Stripe durable, enregistrement du résultat de session, réconciliation des résultats inconnus, webhook signé avec déduplication et transaction financière dédiée, séparation test/réel, recette sandbox réelle et allocation fournisseur. Ne pas appeler l'ancien `complete_paid_order` pour une commande issue de devis : ses coûts courants, stock produit de base et nettoyage global du panier ne correspondent pas aux instantanés par variante.
