# Sauvegardes et restauration

**TYMotors utilise Supabase PostgreSQL, pas MongoDB Atlas.** Le script
`scripts/backup_database.py` prend PostgreSQL par défaut ; son mode MongoDB est
optionnel, sans changement de l'application. Aucun export réel n'a été réalisé
sans identifiants DB/opérateur et outils d'export. Les tests utilisent un faux
exécutable d'export et vérifient atomicité, échecs, confidentialité et rétention.

## Préparation

Utiliser un compte opérateur dédié, stockage disque chiffré et ACL privées, hors
webroot/Git/Docker. Copier aussi les archives dans un stockage chiffré hors hôte.
Ne pas confondre SHA256 (intégrité) avec chiffrement. Objectif proposé pour une
boutique débutante : export quotidien, rétention 14 jours, test mensuel de
restauration ; ajuster RPO/RTO et obligations RGPD aux commandes réelles.

Installer les outils officiels : client PostgreSQL de version au moins égale à
celle du serveur, ou MongoDB Database Tools >=100.3 pour le mode optionnel.
Renseigner dans le coffre d'un ordonnanceur/session protégée, jamais dans Git :

| Variable | Usage |
| --- | --- |
| BACKUP_DIRECTORY | Répertoire dédié ; défaut backend/backups ignoré de Git/Docker. |
| BACKUP_RETENTION_DAYS | 14 ; 0 désactive suppression. |
| BACKUP_TIMEOUT_SECONDS | 1800, timeout export. |
| PG_DUMP_PATH | Exécutable pg_dump, sinon PATH. |
| PGHOST, PGPORT, PGDATABASE, PGUSER | Connexion dédiée ; pas une clé REST Supabase. |
| PGPASSFILE | Fichier pgpass protégé, recommandé ; PGPASSWORD injecté est une alternative. |
| PGSSLMODE, PGSSLROOTCERT | verify-full par défaut ; CA adaptée au fournisseur, jamais sslmode=disable en distant. |
| BACKUP_PG_SCHEMAS | public,auth par défaut, liste explicite. Ajouter storage si nécessaire. |
| MONGODUMP_PATH | Exécutable optionnel mongodump. |
| MONGODB_URI, MONGODB_DATABASE | Mode Mongo uniquement, compte backup limité à la base. |

Pour Supabase, récupérer la connexion directe ou pooler **session** (pas pooler
transaction) au dashboard. Vérifier privilèges de lecture des schémas demandés.
Le dump inclut comptes/hashes Auth : données très sensibles à chiffrer. Les objets
Cloudinary/Supabase Storage ne sont pas les octets du dump : sauvegarde distincte
des fichiers/configurations nécessaire. La restauration native/PITR Supabase
dépend du plan ; [documentation officielle](https://supabase.com/docs/guides/platform/backups).

## Export depuis backend, PowerShell

Après injection sécurisée des variables (ne pas copier de password dans l'historique) :

```powershell
.venv/Scripts/python.exe scripts/backup_database.py --engine postgres
# Rétention explicite : supprime uniquement les anciennes archives de cet outil,
# dans ce répertoire, après un nouvel export réussi.
.venv/Scripts/python.exe scripts/backup_database.py --engine postgres --prune
# Seulement si une base MongoDB existe réellement :
.venv/Scripts/python.exe scripts/backup_database.py --engine mongodb --prune
```

Nom UTC daté + suffixe unique, archive .dump / .archive.gz et manifeste .json
(taille/hash/engine). Aucun secret dans args, logs ou manifeste. Config Mongo
temporaire protégée avant écriture puis supprimée ; sur Windows icacls doit
réussir. Échec/timeout/archive vide = code 1, aucun effacement de backup précédent.
Suppression jamais récursive, limitée aux noms générés et pas de liens suivis.
Ne pas programmer l'opération dans le serveur web ; utiliser un ordonnanceur
avec compte de sauvegarde et alertes d'échec, sans commande shell contenant une URI.

## Restauration (action opérateur, jamais automatique en production)

1. Choisir un **serveur/base jetable ou staging vide distinct de production**,
   confirmer sa destination ; ne pas réutiliser les PG* / URI de production.
2. Recalculer SHA256 et comparer au manifeste. Inspecter le catalogue du dump :

```powershell
Get-FileHash -Algorithm SHA256 -LiteralPath $env:RESTORE_ARCHIVE
pg_restore --list $env:RESTORE_ARCHIVE
```

3. Dans une base PostgreSQL jetable compatible, avec les rôles/extensions requis :

```powershell
# PG* doivent maintenant pointer vers la cible de restauration NON production.
pg_restore --exit-on-error --single-transaction --no-owner --no-privileges --dbname $env:PGDATABASE $env:RESTORE_ARCHIVE
```

Pas de `--clean` / `--drop` automatique. Sur un **Supabase géré**, les schémas Auth
sont préexistants et ne doivent pas être recréés aveuglément : préparer la liste
TOC/restauration des données avec la procédure officielle ou restaurer via
backup/PITR du fournisseur. Un dump de public seul n'est pas un backup des comptes
Auth. Garder les identifiants Auth associés aux profiles/commandes ; ne pas
inventer une migration d'utilisateurs/hashes. Vérifier migrations, RLS et grants
après restauration, puis invalider les sessions restaurées suivant la procédure
fournisseur avant réouverture. Les fichiers médias doivent être disponibles séparément.

Mode Mongo : créer soi-même un fichier YAML de destination `uri:` protégé ACL,
sans le versionner ; RESTORE_CONFIG_FILE le désigne, sans secret en argv :

```powershell
mongorestore --config $env:RESTORE_CONFIG_FILE --archive=$env:RESTORE_ARCHIVE --gzip --nsInclude "$($env:MONGODB_DATABASE).*"
```

Sans `--drop`, sur une cible vide seulement. Exports Mongo par DB sans oplog :
pour une cohérence multi-collections sous écritures, mettre en pause les écritures
ou utiliser les snapshots cohérents du fournisseur ; pas de promesse PITR.
[mongodump officiel](https://www.mongodb.com/docs/database-tools/mongodump/),
[pg_dump officiel](https://www.postgresql.org/docs/current/app-pgdump.html).

4. Comparer nombre commandes/items/produits et échantillon non-PII, totaux,
   indexes/RLS, clés étrangères, puis démarrer le backend de recette avec emails
   désactivés et Stripe test. Rejouer tests et parcours admin/tracking/checkout.
5. Consigner date, cible anonymisée, checksum, durée, résultat et erreurs sans PII.
   Seule une restauration exécutée constitue une preuve de reprise.
