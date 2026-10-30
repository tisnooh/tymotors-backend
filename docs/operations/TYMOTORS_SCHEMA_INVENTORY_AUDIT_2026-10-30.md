# Audit indépendant — inventaire du schéma courant, 30 octobre

## Décision

APPROVED pour la description des écarts de l'inventaire public et APPROVED LOCAL
pour sa reconstruction et la contre-recette. Aucun constat ne vaut validation
du clone réel, de la publication ou d'une modification des permissions distantes.

## Vérifications exécutées

L'auditeur a relu la requête SELECT `tests/commerce_schema_inventory.sql`, les
trois fichiers privés fournis par le Chef et le script d'upgrade. Aucun SQL
distant n'a été exécuté par l'auditeur.

Contre-run avec Node fourni par Codex et l'option `--inventory-before-upgrade`,
vers un nouveau fichier privé unique : PASS, sortie 0. Reconstruction de 24
migrations historiques, export avant insertion des données synthétiques, puis
21 migrations nouvelles et 1 696 valeurs préexistantes conservées. La garde
commerciale finale reste `false`, zéro écriture distante.

Le nouvel export indépendant est identique au fichier de reconstruction du
Chef. Les identités sont uniques dans les deux inventaires. Le recalcul par
paire `(kind, identity)` confirme :

| Mesure | Valeur |
| --- | --- |
| Entrées locales | 1 418 |
| Entrées distantes fournies | 1 181 |
| Entrées identiques | 1 138 |
| Entrées différentes ou absentes d'un côté | 307 |

Les catégories tables (35), colonnes (415), index (109), politiques (64) et
triggers non internes (21) concordent entièrement pour les attributs interrogés.
Ces nombres comptent des entrées de métadonnées, pas des lignes de clients.

## Qualification indépendante des 307 différences

- **264 contraintes NOT NULL locales supplémentaires.** Toutes correspondent
  à une colonne dont l'attribut `not_null` est vrai et identique dans les deux
  inventaires. L'écart de représentation du catalogue ne démontre donc pas un
  manque de nullabilité distant. Aucune contrainte à supprimer ou ajouter n'est
  déduite de ce seul résultat.
- **16 entrées de fonctions différentes.** Douze définitions deviennent
  strictement identiques après conversion CRLF en LF. Pour la treizième,
  `is_auth_session_active(uuid,uuid)`, le corps est mis en ligne unique ; relecture
  et comparaison des jetons, littéraux conservés, concordent. Trois autres
  fonctions trigger (`handle_new_user`, `set_updated_at`,
  `validate_product_publication`) ont le même SQL mais EXECUTE pour `service_role`
  vrai côté distant et faux localement. Leurs accès anon/authenticated concordent.
- **27 grants supplémentaires distants.** Tous concernent `service_role`, sans
  option de délégation (`is_grantable = NO`). Ils portent sur des tables et les
  vues `admin_customers` et `admin_inventory`. Aucun élargissement d'accès à anon
  ou authenticated n'est observé dans ces 27 entrées. Leur nécessité et leur
  provenance restent à qualifier ; ne pas les retirer automatiquement.

Le total brut de 307 ne représente pas 307 défauts de production. Il ne doit pas
être résumé comme une identité complète du schéma non plus.

## Limites critiques conservées

La requête examine une sélection d'attributs de `public`. Elle n'inventorie pas
les définitions/options de vues, schémas `private` et `auth`, enums et autres
types, séquences, extensions, propriétaires, ACL de schémas et privilèges par
défaut. Les grants de vues sont présents, mais leurs définitions ne sont pas
comparées. Tous les attributs possibles des colonnes et contraintes ne sont
pas couverts. L'instantané fourni n'établit pas l'état du serveur après sa date
de capture ; l'auditeur n'a pas fait de nouvelle extraction distante.

La reconstruction PGlite reste un schéma reconstruit à partir du dépôt, avec
Auth simplifié et données de test. Ce n'est ni un clone actuel natif restauré,
ni un test de concurrence PostgreSQL multi-connexion, de reprise après panne
ou de restauration d'une sauvegarde hébergée. Aucune donnée commerciale réelle
n'est validée par ce parcours.

Avant publication, compléter les dépendances privées, vues, types et ACL,
préparer une copie isolée représentative et une sauvegarde restaurable, puis
exécuter la mise à niveau et la recette métier sur cet environnement. Aucune
réparation de registre ou modification de grants n'est approuvée ici.

Aucun code métier, SQL existant, prix, photographie ou design modifié par cet
audit ; aucun paiement ou déploiement.

## Preuves privées et empreintes

Export indépendant :
`C:/Users/utilisateur/.codex/tymotors-upgrade-2026-10-30/independent-reconstructed-schema-1fbbb52d65e349e19890281d495861d7.json`.
Les corps SQL et instantanés bruts restent hors dépôt.

| Empreinte SHA-256 | Fichier |
| --- | --- |
| 97E422FCE9189D6EBD9388BF8BF9185AD3A8A8B6D0DD95753EE7E8C9584DEFB9 | tests/commerce_schema_inventory.sql |
| 14759F3EB7968304C069115E1DAB57E623493820C7E03F51A3E278399DCDF582 | tests/commerce_upgrade_preservation.mjs |
| 969DF3B099A5F09DDCDA432FD4F331D2E6FB75C92E7E54B2C2F9A157CCDAD797 | current-schema.json, privé |
| A34FE4A6DFB0AD50120265B66E83D36FD31E56171AE1B20350B56A030CD16251 | reconstruction Chef et export indépendant, privés |
| 4103FE01673EE5B5D7F96BEA84B96D2345B7268598670BF62F96DAD7ECFABE6A | schema-differences.json, privé |
