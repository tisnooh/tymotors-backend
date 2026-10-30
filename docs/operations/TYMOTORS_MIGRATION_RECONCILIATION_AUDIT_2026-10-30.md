# Audit indépendant — rapprochement des migrations, 30 octobre

## Décision

APPROVED pour le rapprochement documentaire des 24 migrations historiques et
APPROVED LOCAL pour la recette actualisée de préservation. Cela ne valide pas
un upgrade de la production : le schéma courant n'a toujours pas été cloné.

## Vérifications indépendantes

L'auditeur a lu le manifeste du registre et les deux exports SQL privés fournis
par le Chef. Il n'a lancé aucune requête distante, mutation ou réparation de
registre dans ce contrôle.

- 24 versions et 24 fichiers locaux distincts ; couverture exacte des fichiers
  du dépôt jusqu'à `20261013063630_sandbox_catalog_orders.sql`.
- 22 contenus concordants après normalisation CRLF et retrait des espaces aux
  extrémités, avec recalcul indépendant des empreintes locales du manifeste.
- Deux différences relues intégralement puis comparées par jetons, en conservant
  les littéraux SQL :

| Version enregistrée | Fichier local | Résultat |
| --- | --- | --- |
| 20261012164251 | 20261012163951_withdrawal_receipts.sql | 52 jetons identiques ; commentaire de tête retiré et mise en ligne unique |
| 20261012185842 | 20261012184823_enforce_active_auth_session.sql | 103 jetons identiques ; commentaire de tête retiré et mise en ligne unique |

Les valeurs de la contrainte d'emails, la logique de session active, le mode
`SECURITY DEFINER`, le `search_path` vide et les révocations/attributions EXECUTE
concordent dans ces deux contenus. Aucun écart fonctionnel identifié. Le contrôle
des jetons n'est pas présenté comme une preuve générale d'équivalence SQL.
Les empreintes des exports privés concordent aussi avec celles du manifeste.

## Contre-exécution de la recette actualisée

L'auditeur a relu puis exécuté `tests/commerce_upgrade_preservation.mjs` avec
Node fourni par Codex. La nouvelle version reconstruit les 24 fichiers
historiques du dépôt sur une base jetable vide, y compris les 11 fichiers
antérieurement omis de la fixture, puis applique les 21 fichiers suivants.
Résultat : PASS, sortie 0, 1 696 valeurs historiques inchangées, 40 produits
synthétiques et une commande historique de test conservés, garde commerciale
`false`, zéro écriture distante. Cette version remplace la limitation de
couverture à 13 fichiers décrite dans l'audit local du 29 octobre.

## Limites non levées

Le contenu enregistré dans `supabase_migrations.schema_migrations` est un
historique. Sa concordance ne démontre pas que les définitions courantes du
serveur n'ont jamais été modifiées hors migrations. L'auditeur n'a pas réexaminé
toutes les tables, fonctions, politiques et permissions effectives du serveur.

La recette PGlite n'est ni un clone de ce schéma courant, ni une copie des données
réelles, ni un test PostgreSQL natif multi-connexion ou de restauration. Avant
publication, conserver la précondition d'un clone isolé représentatif, d'une
sauvegarde restaurable et d'une approbation du lot exact. Ne pas réparer le
registre ou utiliser `db push --include-all` sur cette seule preuve.

Aucun code métier, SQL existant, photographie, prix ou design modifié par cet
audit ; aucun paiement ni déploiement effectué.

## Empreintes contrôlées

| Empreinte SHA-256 | Fichier |
| --- | --- |
| 4CDC80B9468350ED9978317DA51E350BF859CA41A78F95EFF668042A31349AB5 | docs/operations/TYMOTORS_REMOTE_MIGRATION_HASHES_2026-10-30.json |
| 631F68EAD23F891493870C5033A6144AB6ADE405B0214D439DDE1C91769C22ED | tests/commerce_upgrade_preservation.mjs |
