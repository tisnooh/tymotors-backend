# Préparation de la mise à niveau hébergée

## État vérifié et décisions

Lecture seule du registre de `Tymotors Paris` :24 entrées déjà appliquées,
dernière version20261013063630. Le dépôt comporte21 migrations suivantes,
jusqu'à20261029131412. Le manifeste JSON voisin conserve leurs noms ordonnés et
empreintes SHA-256. Aucun fichier SQL existant n'a été modifié dans ce lot.

Les identifiants historiques ne correspondent pas tous aux noms locaux : les
16 premières entrées distantes portent un nom `migrate_<version locale>_<nom>`
et des versions de septembre. Sept autres migrations d'octobre ont également
des timestamps différents, avec le même nom fonctionnel. Seule la dernière
version historique est identique. La similitude du nom ne prouve pas l'identité
du SQL effectivement appliqué.

Ne pas utiliser aveuglément `db push --include-all` ni réparer le registre sur
la seule base des noms. Cela pourrait rejouer des fondations et des migrations
de photographies. Aucune ancienne migration d'images ne fait partie du lot
proposé. Aucun marquage artificiel de migrations comme appliquées.

## Recette de conservation exécutée

`tests/commerce_upgrade_preservation.mjs` reconstruit le socle opérationnel de
la fixture avant les migrations commerce, puis insère40 produits synthétiques,
40 références d'images, une commande historique payée, sa ligne et son événement.
Les21 migrations suivantes sont appliquées dans l'ordre. Résultat :PASS,
1 696 champs historiques comparés inchangés, mêmes nombres de lignes, aucun
produit/variante/offre/traitement inventé et garde commerciale toujours fermée.
La commande ancienne conserve ses références Stripe et n'est pas réattribuée à
un compte ou devis du nouveau système. Le script refuse une chaîne de fixture
qui omettrait une migration nouvelle présente dans le dépôt.

Ce test utilise PGlite et un socle opérationnel partiel reconstruit : ce n'est
pas un clone du schéma ni des données de production. Il n'établit pas l'absence
de dérive distante, les permissions de tous les rôles hébergés ou la concurrence
PostgreSQL native. Les recettes du parcours métier disposent de rapports séparés.

## Ordre de publication à préparer avant approbation

1. Rapprocher les définitions SQL réellement appliquées et le schéma distant
   avec les prérequis locaux ; conserver un export vérifié et un point de retour.
2. Répéter la chaîne complète sur une copie isolée du schéma hébergé. Ne pas
   exporter de données client dans le dépôt ou dans des journaux publics.
3. Examiner le manifeste et les21 migrations, puis obtenir l'approbation du lot
   exact avant toute application distante. Ne pas activer la garde commerciale.
4. Configurer le backend via son coffre : compte historique, profils et secrets
   distincts. Conserver la destination Stripe historique pour ses événements.
5. Déployer le backend compatible, contrôler les droits d'accès et les routes,
   puis vérifier le nouveau receiver signé en sandbox avec un parcours complet.
6. Ouvrir uniquement les références dont les offres et conditions de livraison
   sont réellement exploitables, après décision commerciale distincte.

Aucune migration distante, activation Stripe réelle, commande fournisseur,
publication, image, prix public ou interface modifié par cette préparation.
