# Supabase TYMotors

Les migrations de ce dossier sont la source de vérité du schéma PostgreSQL.

- `202608240001_initial_ecommerce.sql` crée le catalogue, l’authentification liée à `auth.users`, les paniers, favoris, commandes, compatibilités, données fournisseur privées et politiques RLS.
- Les écritures invitées et toutes les opérations de paiement passent par FastAPI avec la clé serveur.
- La clé publique Supabase est utilisée dans le navigateur uniquement pour Auth. La clé serveur ne doit jamais être préfixée par `REACT_APP_` ni être commitée.
- Les produits historiques doivent être importés en `draft` et `is_verified = false`.

Après application distante, exécuter les conseillers sécurité et performance Supabase, puis corriger tout avertissement avant la Preview.
