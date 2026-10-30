# Comparaison du schéma courant —30octobre

Inventaire de métadonnées uniquement : aucune ligne client, adresse, commande
ou clé exportée. La requête SELECT réutilisable est versionnée dans
tests/commerce_schema_inventory.sql. Les résultats bruts restent hors dépôt,
dans le dossier opérateur privé. Aucun DDL, repair, GRANT ou déploiement distant.

Le test de mise à niveau sait maintenant exporter son inventaire avant les
21 migrations nouvelles, après reconstruction des24 anciennes. Le chemin doit
être absolu, hors dépôt, et le fichier ne doit pas déjà exister (écriture wx).
L'export ne met pas fin à la recette : conservation des1 696 champs et garde
commerciale fermée toujours contrôlées, PASS.

## Résultats bruts

Inventaire distant :1 181 objets/entrées ; reconstruction locale :1 418.
Comparaison par catégorie et identité, sans ignorer automatiquement les écarts :
1 138 entrées identiques,307 différences conservées pour revue.

Concordance complète dans le périmètre interrogé :35 tables (RLS/force RLS),
415 colonnes (type/nullabilité/défaut),109 index,64 politiques et21 triggers.

Les307 écarts se répartissent ainsi :
-264 entrées de contraintes NOT NULL présentes seulement dans le catalogue du
  moteur local. La nullabilité est comparée séparément sur toutes les colonnes
  et concorde ; ce constat ne justifie aucune suppression ou nouvelle contrainte.
-16 entrées de fonctions :13 définitions textuellement différentes, dont12
  présentent des CR supplémentaires et une fonction SQL de session déjà examinée
  lors du rapprochement historique ; trois fonctions trigger accordent EXECUTE
  au service_role distant et pas dans la reconstruction. L'accès anon et
  authenticated demeure identique dans ces trois cas.
-27 privilèges de tables/vues supplémentaires pour service_role côté hébergé.
  Ils ne concernent pas un élargissement à anon/authenticated dans cet inventaire.
  Ne pas les retirer automatiquement : examiner les privilèges par défaut de
  l'hébergement et les besoins du backend avant toute décision.

## Limites et prochaine étape

Cet inventaire concerne les tables et objets publics interrogés : il n'exporte
pas le schéma auth, les vues et leurs options, les fonctions private, les enums,
les extensions, propriétaires ou privilèges par défaut. Il n'est donc pas un
dump restaurable ni une preuve d'identité complète du schéma courant.

Le décompte brut de différences ne représente pas307 anomalies de production.
Les écarts de moteur, de fins de lignes et d'environnement doivent être qualifiés
avant toute intervention. Aucun élargissement de permission n'est proposé ici.

Reprise : compléter l'inventaire des dépendances privées/vues/types et la
qualification des ACL ; préparer un export/restauration du schéma complet dans
un PostgreSQL isolé approprié, puis exécuter les21 migrations et la recette
commande. La publication et les encaissements réels restent distincts.
