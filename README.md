# TYMotors backend — branche de test

API FastAPI/MongoDB pour le catalogue, le panier, l'administration et Stripe Checkout. La branche `develop` est destinée aux tests ; elle ne doit pas recevoir de clés Stripe réelles.

## Démarrage local

1. Copier `.env.example` vers `.env` et utiliser uniquement des valeurs de test.
2. Créer un mot de passe administrateur haché avec bcrypt et le placer dans `ADMIN_PASSWORD_HASH`.
3. Définir un `ADMIN_JWT_SECRET` aléatoire d'au moins 32 caractères.
4. Installer `requirements-dev.txt`, puis lancer `uvicorn server:app --reload`.
5. Exécuter `pytest -q` avant toute publication.

## Flux de paiement attendu

Le serveur relit prix, statut et stock dans MongoDB, crée une commande `pending`, puis ouvre Stripe Checkout. Seul le webhook signé peut passer une commande à `paid` et réduire le stock. La page de succès lit la commande enregistrée et ne valide jamais le paiement.

Événements Stripe de test :

- `checkout.session.completed`
- `payment_intent.succeeded`
- `payment_intent.payment_failed`
- `charge.refunded`

Endpoint webhook : `/api/stripe/webhook`.

## Déploiement de test

- Déployer `develop` vers un service Render de staging séparé.
- Configurer les variables de `.env.example` dans Render, sans ajouter de `.env` au dépôt.
- Utiliser `ENVIRONMENT=test`, une clé `sk_test_...` et le secret du webhook de staging.
- Configurer le frontend Vercel Preview avec l'URL de ce backend de staging.
- Conserver `REACT_APP_SITE_MODE=test` pour maintenir `noindex,nofollow`.

## Migration catalogue

`migrations/001_secure_catalog.py` fonctionne en lecture seule par défaut. Après sauvegarde MongoDB, `--apply` place les produits historiques en brouillon et supprime leurs preuves sociales artificielles. Compléter ensuite les compatibilités, photos, coûts, montage et délai dans l'administration avant de passer un produit à `active`.

## Actions manuelles obligatoires

- Révoquer et recréer les identifiants MongoDB, Stripe et Cloudinary déjà visibles dans des captures ou dans l'historique Git.
- Nettoyer l'ancien `.env` de tout l'historique avec `git filter-repo`, puis forcer la mise à jour uniquement après sauvegarde et coordination.
- Restreindre MongoDB Atlas aux réseaux nécessaires et à un utilisateur aux droits minimaux.
- Créer le webhook Stripe en environnement de test et enregistrer son secret uniquement sur le backend de staging.
- Vérifier le type, les dimensions et les droits d'utilisation de chaque image fournisseur.

Ne jamais recopier un secret dans un ticket, une capture, un log ou un commit.
