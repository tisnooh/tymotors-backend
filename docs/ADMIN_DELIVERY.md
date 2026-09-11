# Livraison du back-office TYMotors — 11 septembre 2026

## 1. Architecture trouvée

- Deux dépôts Git imbriqués sur `develop` : `frontend` et `backend`.
- Frontend : React 19, React Router 7, CRACO 7, Tailwind/Radix, JavaScript.
- Backend : FastAPI, Pydantic 2, client PostgREST asynchrone, sans ORM.
- Données et authentification : Supabase Auth + PostgreSQL avec rôle dans `profiles.role`.
- Paiement : Stripe Checkout et webhook signé. Images : Cloudinary.

L'audit technique détaillé est dans `docs/ADMIN_AUDIT.md`.

## 2. Ce qui existait déjà

- Catalogue, catégories, marques, compatibilités véhicule, fournisseurs privés et images.
- Comptes Supabase, profils client, panier, favoris, commandes et lignes de commande.
- Checkout Stripe, webhook, décrément de stock initial et historique `admin_audit`.
- Quelques endpoints admin produits/commandes, mais sans pagination réelle complète, dashboard, retours, promotions, canaux, paramètres ni historique de stock.

## 3. Ce qui a été créé

- Application `/admin/*` séparée de la boutique publique, avec connexion, contrôle du rôle, sidebar/drawer, déconnexion, états chargement/erreur/vide et notifications.
- Dashboard, commandes et détail, produits et formulaire complet, stocks et mouvements, clients et détail, retours, promotions, canaux et paramètres/audit.
- API admin modulaire dans `app/admin.py`, validations strictes, pagination/recherche serveur et transactions PostgreSQL pour toutes les écritures sensibles.
- Tests backend, PostgreSQL et frontend, plus un environnement navigateur local isolé qui n'est jamais importé dans le build de production.

## 4. Routes créées ou renforcées

Frontend : `/admin`, `/admin/orders`, `/admin/orders/:id`, `/admin/products`, `/admin/products/new`, `/admin/products/:id`, `/admin/inventory`, `/admin/customers`, `/admin/customers/:email`, `/admin/returns`, `/admin/promotions`, `/admin/channels`, `/admin/settings`.

API sous `/api/admin` : vérification, dashboard, options catalogue, produits (liste/détail/création/modification/archivage/upload), commandes (liste/détail/modification), stocks et mouvements, clients et détail, retours, promotions, canaux, paramètres et journal d'audit. Toutes les routes métier vérifient le jeton Supabase puis le rôle actuel dans la base.

## 5. Tables et champs ajoutés

Tables : `shop_settings`, `inventory_movements`, `sales_channels`, `product_channels`, `returns`, `promotions`.

Champs : `products.low_stock_threshold`, `products.tags`; `orders.stock_applied_at`, `refunded_amount_cents`, `discount_amount_cents`, `sales_channel`, `delivered_at`, `promotion_id`; `order_items.cost_price_cents`.

Deux vues privées : `admin_inventory`, `admin_customers`. Index ajoutés sur e-mail/date commandes, statuts, paiements, promotions, audit, mouvements, retours et canaux.

## 6. Migrations effectuées

- `admin_backoffice`
- `admin_backoffice_hardening`

Elles sont appliquées au projet Supabase `wpefncureamghsmsnibx`. Elles sont additives et rétrocompatibles. Contrôle après migration : 41 produits, 1 commande, 0 mouvement de stock de test, aucune suppression de donnée de production.

## 7. Fonctionnalités opérationnelles

- Statistiques calculées sur les commandes réelles : CA brut/remboursements/net, périodes Europe/Paris, panier, clients, marge brute connue, top produits, commandes et stocks à traiter.
- CRUD produit atomique, duplication, activation/désactivation, archivage réversible, images, compatibilités détaillées, fournisseur privé, coût et marges.
- Stock optimiste et transactionnel, historique signé par l'acteur, refus du stock négatif.
- Machine d'états des commandes, suivi colis, annulation confirmée, historique avant/après.
- Paiement idempotent même après remboursement ; décrément uniquement après paiement confirmé ; les paiements échoués/expirés ne décrémentent pas.
- Remboursements comptabilisés uniquement lorsqu'ils sont confirmés `succeeded` par Stripe.
- Retours avec quantité contrôlée, workflow et remise en stock explicite et idempotente.
- Promotions `%` ou montant fixe, dates, minimum, limite, produits/catégories, calcul serveur puis coupon Stripe limité à la session.
- Leboncoin en suivi manuel honnête ; site TYMotors dérivé du statut réel du produit.
- Paramètres réellement utilisés par l'admin et journal d'actions paginé.

## 8. Fonctionnalités volontairement non implémentées

- Pas de remboursement direct depuis TYMotors : l'action financière reste dans Stripe, puis le webhook met la base à jour. Ceci évite tout faux remboursement.
- Pas de synchronisation automatique Leboncoin, faute d'API officielle existante dans le projet.
- Pas de réservation de stock avant paiement : `reserved_stock` vaut explicitement zéro.
- Pas de marge nette inventée, pas de multi-entrepôts, ERP, comptabilité ou CRM avancé.
- Le moyen de paiement précis n'est pas persisté ; l'admin indique Stripe Checkout lorsque c'est la seule information certaine.

## 9. Problèmes découverts dans l'ancien code

- Requêtes admin chargées intégralement puis tronquées ; écritures produit en plusieurs requêtes non atomiques.
- Stock réécrit depuis un formulaire potentiellement périmé ; métadonnées d'image susceptibles d'être perdues.
- Transitions de commande non contraintes.
- Événement `refund.created` traité comme remboursement total même s'il était en attente ou partiel.
- Possibilité de redécrémenter le stock après remboursement lors d'un rejeu de paiement.
- Signature WebP trop permissive et upload Cloudinary bloquant dans une route asynchrone.
- Payloads supplémentaires ignorés, favorisant le mass assignment silencieux.

## 10. Risques de sécurité corrigés

- RBAC contrôlé sur chaque endpoint par Supabase Auth et lecture serveur de `profiles.role`; aucun rôle lu depuis les métadonnées modifiables du compte.
- Nouvelles tables sous RLS, sans accès `anon`/`authenticated`; accès uniquement via le backend `service_role` et fonctions administratives contrôlées.
- Révocation des écritures directes client sur produits et commandes.
- Validation stricte des UUID, montants, dates avec fuseau, transitions, URL HTTPS, MIME/signatures et champs supplémentaires.
- Filtre PostgREST nettoyé, concurrence optimiste, transactions et audit des valeurs avant/après.
- Webhook Stripe signé, idempotence renforcée et remboursements confirmés cumulés de façon monotone.

Point de configuration restant : activer la protection Supabase contre les mots de passe compromis. L'avis officiel se trouve dans la documentation Auth Supabase.

## 11. Variables d'environnement nécessaires

Frontend : `REACT_APP_BACKEND_URL`, `REACT_APP_SUPABASE_URL`, `REACT_APP_SUPABASE_PUBLISHABLE_KEY`, plus les variables publiques déjà utilisées (`REACT_APP_SITE_MODE`, `REACT_APP_SITE_URL`, contact et réseaux).

Backend : `ENVIRONMENT`, `SUPABASE_URL`, `SUPABASE_PUBLISHABLE_KEY`, `SUPABASE_SECRET_KEY` ou `SUPABASE_SERVICE_ROLE_KEY`, `FRONTEND_URL`, `CORS_ORIGINS`, `CORS_ORIGIN_REGEX`, `STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET`, `SHIPPING_RATE_CENTS`, `FREE_SHIPPING_THRESHOLD_CENTS`, et soit `CLOUDINARY_URL`, soit les trois variables Cloudinary séparées. Aucun nouveau secret n'est codé en dur.

## 12. Tests réalisés

- 114 tests Python/FastAPI réussis, incluant le refus de chaque endpoint pour déconnecté, client et jeton expiré.
- 27 contrôles PostgreSQL transactionnels réussis : migrations, rollbacks, RLS/grants, concurrence stock, paiements rejoués, remboursements partiels/complets, transitions, retours et promotions.
- 6 tests frontend réussis.
- Parcours navigateur réels sur l'application locale : connecté/déconnecté/non-admin, création et modification produit, correction stock, rupture, recherche/filtre, promotion, canal manuel, dashboard, commande et détail.
- Responsive vérifié à 375, 390, 430, 768, 1024 et 1440 px sur sidebar, tables, formulaire produit, dashboard et détail commande ; aucun débordement global.
- Console : aucune erreur applicative observée. Uniquement l'avertissement de transform JSX de l'environnement de test isolé.

## 13. Résultat du build

- ESLint : réussi.
- Compilation Python : réussie.
- Build production CRACO : réussi sans avertissement de compilation ; chunk admin chargé à la demande, environ 14,91 kB gzip et CSS admin environ 3,37 kB gzip.
- Le projet est JavaScript, donc aucun typecheck TypeScript n'est applicable.
- Le CSS principal public garde le même hash, confirmant l'absence de modification visuelle globale de la boutique.

## 14. Prochaines étapes recommandées

1. Attribuer `profiles.role = 'admin'` à l'adresse de compte TYMotors choisie ; aucun des deux comptes actuels n'est administrateur.
2. Déployer les deux dépôts ensemble afin que le frontend et l'API utilisent le nouveau contrat.
3. Vérifier sur l'environnement déployé : connexion admin, une modification produit non destructive et un paiement Stripe de test avec webhook.
4. Activer la protection contre les mots de passe compromis dans Supabase Auth.

