# TYMotors backend — Supabase staging

API FastAPI du catalogue, des comptes, paniers, commandes, uploads Cloudinary et paiements Stripe Checkout. La branche `develop` reste exclusivement dédiée aux tests.

## Architecture

- PostgreSQL, Auth et RLS : Supabase
- Paiements : Stripe Checkout en environnement test
- Images : Cloudinary
- API : FastAPI, client PostgREST asynchrone

MongoDB et l’ancien mot de passe admin/JWT maison ont été retirés du runtime. L’administration utilise une session Supabase et vérifie `profiles.role = 'admin'` côté serveur.

## Installation locale

1. Copier `.env.example` vers `.env` et renseigner uniquement des identifiants de staging/test.
2. Appliquer, dans l'ordre, tous les fichiers SQL de `supabase/migrations/` au projet Supabase de staging.
3. Installer `requirements-dev.txt`, puis lancer `uvicorn server:app --reload`.
4. Exécuter `pytest -q`.

La clé `SUPABASE_SERVICE_ROLE_KEY` est strictement serveur. Elle ne doit jamais être préfixée par `REACT_APP_`, placée dans Vercel Frontend ou commitée.

## Paiement

Le serveur relit prix, statut et stock dans PostgreSQL, enregistre une commande `pending`, puis crée une session Checkout. Le webhook signé appelle la fonction transactionnelle `complete_paid_order`: stock, commande et panier sont mis à jour atomiquement. La page de succès ne valide jamais elle-même un paiement.

Événements de staging :

- `checkout.session.completed`
- `payment_intent.payment_failed`
- `charge.refunded`
- `refund.created`

Endpoint : `/api/stripe/webhook`.

`STRIPE_AUTOMATIC_TAX` reste désactivé tant que les inscriptions fiscales et paramètres Stripe Tax n’ont pas été validés. Ne pas afficher de TVA calculée si cette configuration n’est pas activée.

## Catalogue

Tous les produits historiques sont importés en `draft`, sans stock, avis, promotion, garantie ni compatibilité inventés. Un trigger PostgreSQL et la validation Pydantic empêchent l’activation d’un produit sans image, compatibilité et fournisseur vérifiés.

Les anciennes catégories API `performance` et `technology` restent acceptées comme alias de transition vers `exterior` et `multimedia-technology`.

## Déploiement Preview

- Render staging : créer le Blueprint depuis `render.yaml`, puis renseigner uniquement des valeurs Supabase staging, Stripe test et Cloudinary.
- Vercel Preview : URL API, URL Supabase et clé Supabase publique uniquement.
- Conserver `ENVIRONMENT=test` et `REACT_APP_SITE_MODE=test`.
- Ne jamais modifier le déploiement Production ni la branche `main` pendant la migration.
