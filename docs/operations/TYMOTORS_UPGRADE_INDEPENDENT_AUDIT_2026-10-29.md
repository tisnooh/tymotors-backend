# Audit indépendant — préservation lors de l'upgrade commerce

## Décision

APPROVED LOCAL pour le test de régression sur données historiques synthétiques.
Il ne constitue pas une autorisation d'appliquer les migrations en production.
La compatibilité avec le schéma hébergé exact reste NON VÉRIFIÉE par ce test.
Le Chef conserve la décision finale.

## Exécution indépendante

L'auditeur a exécuté, avec Node fourni par Codex :

```text
node tests/commerce_upgrade_preservation.mjs
```

Résultat effectif : PASS, sortie 0.

| Mesure | Résultat observé |
| --- | --- |
| Produits synthétiques préexistants | 40 |
| Commandes historiques synthétiques | 1, déjà payée, mode test |
| Migrations appliquées après le point de séparation | 21 |
| Valeurs de champs préexistants comparées et inchangées | 1 696 |
| Garde finale commerce_live_enabled | false |
| Écritures distantes | 0 |

Le test prend un snapshot avant upgrade sur `products`, `product_images`,
`orders`, `order_items` et `stripe_events`. Après upgrade il compare le nombre
de lignes et toutes les valeurs de colonnes présentes dans chaque snapshot.
Les valeurs des nouvelles colonnes ne sont pas comptées dans les 1 696 valeurs.

Il vérifie également que la commande historique reste sans compte Stripe ni
devis commerce inventés. Les quatre tables `product_variants`, `supplier_offers`,
`commerce_payment_sessions` et `commerce_fulfillment_tasks` restent vides dans
ce scénario ; aucune activation ou association commerciale n'est déduite.

## Contrôle de couverture des migrations

Une vérification indépendante des fichiers, distincte de la regex du test,
compare la liste extraite de `admin_database.mjs` avec tous les fichiers du
répertoire postérieurs à `20261013063630_sandbox_catalog_orders.sql`.

- 45 migrations SQL présentes dans le dépôt au moment du contrôle.
- 34 migrations référencées dans la fixture.
- 13 migrations utilisées pour reconstruire son baseline opérationnel.
- Les 21 suivantes correspondent exactement à tous les fichiers postérieurs
  au point de séparation : aucune migration de ce segment omise, aucun doublon,
  ordre identique à celui des fichiers du dépôt. PASS.
- La version finale du script effectue elle-même ce contrôle de couverture
  par `readdir` avant d'appliquer le segment. L'auditeur l'a relancée : même
  résultat PASS, 21 migrations et 1 696 valeurs conservées, sortie 0.
- Le manifeste `TYMOTORS_PENDING_MIGRATIONS_2026-10-29.json` a été vérifié
  indépendamment : ordre et couverture exacts, 21 empreintes SHA-256 identiques
  aux octets des fichiers SQL présents. PASS. Ce rapprochement local ne compare
  pas le contenu de migrations effectivement exécutées sur le serveur.

Le baseline omet 11 fichiers antérieurs :

- `202608240002_security_and_fk_indexes.sql`.
- `202608240003_clear_broken_vehicle_images.sql`.
- `202608240004_vehicle_image_rights.sql`.
- `202608240005_split_porsche_911_generations.sql`.
- `202608240006_verify_audi_a3_8v_image.sql`.
- `202608240007_split_golf_7_trims.sql`.
- `202608240008_verify_golf_7_gti_image.sql`.
- `202608240009_verify_remaining_vehicle_images.sql`.
- `202608240010_disclose_vehicle_image_crop.sql`.
- `202608250001_vehicle_image_workflow.sql`.
- `202608250002_install_tymotors_vehicle_images.sql`.

La fixture ne reproduit donc pas tous les index, modifications véhicule et
traitements d'images historiques. Cette limitation est acceptable pour ce test
ciblé, mais interdit de le présenter comme un clone complet de la production.

## Limites critiques pour une publication

- Les 40 lignes sont générées avec une même forme de produit ; elles ne
  représentent pas les données réelles des 40 références TYMotors.
- Une seule commande payée de test et un seul événement déjà traité sont
  conservés. Les commandes réelles, retours, remboursements partiels, dossiers
  fournisseurs existants, clients, autorisations et cas multicolis historiques
  ne sont pas reconstruits dans cette fixture.
- Les URL d'images sont conservées en base. Aucun binaire image ni stockage
  distant n'est inspecté ou modifié ; cela ne vérifie pas les droits d'images.
- Le registre distant et ses timestamps différents ne sont pas rapprochés
  automatiquement avec les fichiers locaux. Une vérification du contenu et des
  équivalences de migrations est nécessaire avant tout upgrade hébergé. Ne pas
  rejouer les 13 fichiers du baseline ou réparer le registre sur cette seule base.
- PGlite utilise un moteur local isolé avec Auth simplifié ; ce n'est pas une
  recette PostgreSQL native multi-connexion, de verrouillage concurrent ou de
  bascule Render/Supabase. Le remplacement local de `pgcrypto` est explicite.
- Le test ne démontre ni restauration d'une sauvegarde réelle, ni rollback
  d'un déploiement interrompu, ni réussite du parcours client hébergé après
  publication. Les nouveaux helpers et fonctionnalités ont leurs recettes
  distinctes ; ce test examine principalement la préservation des données.
- Aucun paiement, appel fournisseur, changement de prix public, modification
  visuelle, migration distante ou déploiement effectué par cet audit.

## Suite requise

Conserver ce test dans les recettes locales. Avant toute publication autorisée,
rapprocher le schéma réel et le registre de migrations par contenu, préparer une
sauvegarde restaurable et tester l'upgrade sur un environnement natif isolé
représentatif. Les tarifs, offres et livraisons réels restent des preuves
commerciales distinctes que des données synthétiques ne remplacent pas.

## Empreinte du script exécuté

| Empreinte SHA-256 | Fichier |
| --- | --- |
| A5E6A23DE307E1E989981069A87C1B2AFF0F935944F3F88EA6DDBA5754511CC8 | tests/commerce_upgrade_preservation.mjs |
