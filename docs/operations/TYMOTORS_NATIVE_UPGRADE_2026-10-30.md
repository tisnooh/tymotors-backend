# Sauvegarde, restauration et mise à niveau PostgreSQL natif

## Résultat exécuté

Le runner tests/run_native_commerce_upgrade.py a exécuté sur PostgreSQL17.11 :
1. Un cluster neuf dans un dossier privé hors dépôt, uniquement127.0.0.1:18877,
   authentification SCRAM et mot de passe éphémère non affiché.
2. Reconstruction des24 migrations historiques, puis40 produits et leurs
   images, une commande payée synthétique, sa ligne et son événement.
3. Sauvegarde pg_dump au format custom, création d'une seconde base et
   restauration pg_restore avec arrêt sur erreur. Historique restauré comparé.
4. Application des21 migrations nouvelles sur la base restaurée et contrôle de
   conservation :1 696 champs inchangés ; garde commerciale false.
5. Arrêt du seul cluster possédé et suppression du fichier de mot de passe.

Résultat Chef :PASS, backup_restore_verified=true, cluster_stopped=true,
production_writes=0, actual_payments=0. Les archives et journaux de test restent
privés hors Git. Aucun service Windows, règle réseau ou configuration distante
n'a été installé ou modifié.

## Origine du moteur

Archive portable officielle EDB postgresql-17.11-5-windows-x64-binaries.zip,
extraite hors dépôt, sans installation globale. La taille téléchargée est
381531864 octets. Empreinte vérifiée avant extraction/exécution :
80379b2c04d51c30225532e0ae04509899141e9957ed096fe749d7fd9df8f82f.

Source officielle :
https://get.enterprisedb.com/postgresql/postgresql-17.11-5-windows-x64-binaries.zip.sha256
La distribution ZIP Windows est référencée par PostgreSQL :
https://www.postgresql.org/download/windows/

## Défauts corrigés pendant l'exécution

- Première tentative : pg_ctl a démarré le serveur mais le sous-processus
  conservait un pipe Windows ouvert, entraînant un timeout. Arrêt explicite
  du cluster possédé effectué ; aucun serveur inconnu arrêté. Les sorties sont
  maintenant capturées dans des fichiers temporaires pour éviter cette attente.
- Tentative suivante : les migrations attendent le rôle postgres ; le cluster
  jetable utilise maintenant ce propriétaire, avec son propre mot de passe
  SCRAM, sans réutiliser un identifiant ou secret distant.
- L'audit a rejeté le tri constant de jsonb_agg et un état PASS possible lors
  d'un échec de nettoyage : tri par id/event_id et résultat FAILED imposé si
  le nettoyage échoue. Une tentative de startup partiellement réussie fait
  aussi vérifier puis arrêter le cluster possédé.

## Limites et reprise

La restauration native est désormais effectivement testée. Elle reconstruit
l'historique versionné, et n'est pas un export/restauration du schéma courant de
production. Les données sont synthétiques ; aucune vente ou livraison réelle.
La recette ne prouve pas encore les courses concurrentes du parcours commande,
le déploiement hébergé ou les dépendances Supabase gérées.

Reste à compléter les métadonnées privées/vues/types et le rapprochement du
schéma courant, puis préparer la version à publier et sa configuration serveur.
Ne pas déduire une autorisation de déploiement de ces tests locaux. Design,
photographies et prix publics inchangés.
