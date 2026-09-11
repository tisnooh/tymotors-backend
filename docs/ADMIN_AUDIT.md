# Audit préalable — 11 septembre 2026

Deux dépôts imbriqués, `frontend` et `backend`, branche `develop`. La suppression précédente d'AdminPanel est conservée et remplacée par une zone modulaire. Aucun changement graphique de la boutique n'est prévu.

- React 19, React Router 7, CRACO 7, Tailwind et composants Radix ; JavaScript, pas de TypeScript.
- FastAPI, Pydantic 2, client HTTP PostgREST asynchrone ; aucun ORM.
- PostgreSQL/Supabase : profiles, products, product_images, product_compatibilities, product_supplier_data, orders, order_items, carts, cart_items, wishlists, admin_audit, stripe_events et référentiel véhicules.
- Auth Supabase existante. Chaque requête admin vérifie le jeton avec Auth puis lit `profiles.role` côté serveur. Le rôle est interdit dans les modifications de profil client et protégé par les droits de colonnes PostgreSQL.
- Produits : prix en centimes, stock entier, brouillon/actif/archivé, compatibilités détaillées. Publication conditionnée aux données vérifiées, contrôlée aussi par trigger.
- Commandes : statut commercial, paiement et expédition distincts. Instantanés des articles et coordonnées ; suivi existant. Clients inscrits et invités.
- Stripe Checkout signé et vérification serveur des montants. `complete_paid_order` verrouille la commande et décrémente le stock atomiquement. Pas de réservation avant paiement.
- Images Cloudinary ; fichiers JPEG/PNG/WebP/AVIF, limite 8 Mo. URL HTTPS existantes conservées.
- API admin existantes : vérification, liste/écriture/archivage produits, upload, liste/modification commandes. Pas de dashboard, retours, promotions, canaux, paramètres ni historique de stocks.

## Défauts repérés

1. Liste admin produits chargeant tout le catalogue puis tronquant ; total inexact, pas de recherche serveur.
2. Écriture produit en requêtes séparées : risque d'état partiel ; réécriture du stock depuis un formulaire périmé ; perte des métadonnées d'image. Les compatibilités hydratées contiennent `id` que le modèle d'entrée interdit.
3. Annulation/modification de commande sans machine d'états ni historique des valeurs antérieures.
4. `refund.created` marque tout remboursement comme total, même en attente ; un paiement rejoué après remboursement peut décrémenter le stock à nouveau.
5. Upload : signature RIFF trop permissive ; appel Cloudinary synchrone dans une route asynchrone.
6. Paramètres privés/profils : payloads supplémentaires ignorés, ce qui mérite un rejet explicite.
7. API catalogue publique non paginée à la base (hors périmètre de refonte). Boutique présentant toujours Stripe comme test.

## Validation initiale

15 tests backend réussis avant modifications. Aucun secret local backend disponible. L'accès Supabase était initialement bloqué.

## Vérification après reconnexion

Le projet `wpefncureamghsmsnibx` a ensuite été vérifié via le connecteur Supabase. Les deux migrations `admin_backoffice` et `admin_backoffice_hardening` ont été appliquées et les nouvelles fonctions vérifiées. Les 41 produits et la commande existants sont conservés ; aucun mouvement de stock de test n'a été écrit dans cette base. Aucun profil n'a encore le rôle administrateur : attribution en attente de l'adresse choisie par le propriétaire. Les scénarios d'écriture sont exécutés sur une base PostgreSQL locale jetable, jamais sur le catalogue réel.
