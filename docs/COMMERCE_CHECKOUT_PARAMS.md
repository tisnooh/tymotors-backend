# Paramètres Checkout — constructeur pur, non raccordé

`build_checkout_params(order, items, attempt, *, trusted_origin, now)` ne fait aucun accès base, réseau, horloge interne ou tirage aléatoire. Ce module préparatoire n'autorise aucun paiement, ne crée aucune tentative et ne réserve aucun stock. L'ancien checkout variantes reste bloqué.

Les entrées doivent provenir des instantanés serveur, pas d'un JSON client :

- `order` : commande test `pending/unpaid`, son devis, montants et destination figés, enrichie par le futur service de `quote_expires_at` depuis `commerce_quotes.expires_at`.
- `items` : lignes persistées de cette commande, identifiants source uniques, variante, prix et quantité.
- `attempt` : contrat futur avec identifiant, commande/devis, mode test, devise/total, expiration de session absolue en secondes, expiration de devis identique, origine frontend et `integration_identifier` déjà généré/persisté.
- `trusted_origin` : configuration du serveur ; `now` : horodatage injecté par le serveur pour vérifier l'admissibilité, jamais repris d'un formulaire client.

Le constructeur ne prétend pas que ces champs de tentative ou `orders.quote_expires_at` sont déjà en base. Le raccordement devra effectuer la jointure et figer les paramètres complets **et** la clé d'idempotence avant le premier appel Stripe. Après un résultat inconnu, aucune recréation automatique sans réconciliation.

## Refus et invariants

EUR et centimes stricts ; somme des lignes égale au sous-total ; total = sous-total + port ; taxes informatives déjà incluses. Promotions/options susceptibles de modifier ces montants non acceptées. Plage conservatrice prise en charge : 50 à 99 999 999 centimes, sans garantie de disponibilité du compte ou de tous les moyens de paiement.

Maximum 100 lignes, port fixé dans `shipping_options`, moyens de paiement dynamiques, taxes automatiques et conversion adaptative désactivées. Expiration inchangée au retry, entre 30 minutes et 24 heures au moment contrôlé, sans dépasser la fin de validité du devis. Une durée devenue insuffisante provoque un refus, pas un allongement silencieux.

Les photographies sont transmises exactement depuis leur URL figée si elle est HTTPS publique/admissible et non interdite par les règles connues. Sinon refus, sans recadrage, traitement ou substitution. Aucun contrôle DNS ni droit commercial ne peut être déduit de cette vérification syntaxique.

Le pays collecté par Stripe est borné à celui du devis. **Cela ne garantit pas la même adresse complète** : le futur webhook devra comparer la destination et empêcher le fulfillment d'un paiement dont le lieu ne correspond pas aux conditions chiffrées, sans nier un paiement effectivement reçu.

## Preuves et suite

156 tests synthétiques couvrent montants, associations, doublons, stabilité des paramètres, bornes temporelles, origine, options interdites et images. Relus et rejoués par l'auditeur indépendant. Pas d'acceptation de payload par Stripe revendiquée, pas de session créée, pas de test réel de paiement.

Il reste à implémenter la tentative durable, les réservations concurrentes par variante, la liaison atomique aux sessions, la réconciliation, les webhooks signés et la complétion depuis les snapshots. Puis la recette en sandbox isolée, le parcours fournisseur/agent/expéditions et les contrôles visuels avant toute demande de publication.
