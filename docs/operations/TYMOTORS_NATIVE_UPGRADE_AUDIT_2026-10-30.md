# Audit indépendant — sauvegarde, restauration et upgrade PostgreSQL natif

## Décision

APPROVED LOCAL après corrections et contre-exécution native. Cette recette
vérifie une reconstruction historique peuplée de données synthétiques, une
sauvegarde restaurée et son upgrade. Elle ne valide pas un clone actuel de
production, un déploiement, une vente ou une livraison réelle.

## Rejets et corrections imposées

La première revue a identifié trois défauts du runner :

1. Un timeout de démarrage pouvait sortir avant l'activation du marqueur
   `started`, laissant le nettoyage ignorer un serveur déjà lancé. Le marqueur
   de tentative est maintenant positionné avant `pg_ctl start` ; le nettoyage
   interroge et arrête uniquement le cluster privé possédé.
2. `jsonb_agg(... order by 1)` triait une constante. Les snapshots trient
   désormais sur `t.id`, ou `t.event_id` pour `stripe_events`.
3. Un arrêt échoué pouvait laisser `status = PASS` dans le résultat. Le résultat
   devient maintenant `FAILED`, avec `cleanup_failed` et un type d'erreur.

Les contre-tests isolés ont d'abord confirmé les deux derniers défauts :
3 réussites, 2 échecs. Après correction : **5 tests réussis**, sortie 0.
Ces tests de lifecycle mockent les processus et le réseau ; ils vérifient
timeout de démarrage, erreur de migration, arrêt échoué, refus de port occupé,
tri des snapshots, suppression du fichier de mot de passe et statut final.

Le Chef a aussi remplacé les pipes héritables par des fichiers temporaires pour
la capture des commandes natives sous Windows. Le contre-run ci-dessous couvre
cette version. Le rôle superutilisateur `postgres` existe seulement dans le
cluster de test pour satisfaire les migrations historiques qui le référencent.

## Contre-exécution native effective

Après signal du Chef et vérification du port libre, l'auditeur a exécuté :

```text
python -m tests.run_native_commerce_upgrade --pg-bin C:/Users/utilisateur/.codex/tymotors-postgres-native/pgsql/bin --private-root C:/Users/utilisateur/.codex/tymotors-postgres-native/runs --port 18877
```

| Contrôle | Résultat observé |
| --- | --- |
| Version native | PostgreSQL 17.11 |
| Migrations historiques reconstruites | 24 |
| Migrations nouvelles appliquées après restauration | 21 |
| Données de test | 40 produits, une commande historique, sa ligne et son événement |
| Sauvegarde | pg_dump custom, 237 690 octets |
| Restauration | base distincte `restored_fixture`, snapshots égaux avant upgrade |
| Valeurs historiques conservées après upgrade | 1 696 |
| Garde commerciale finale | false |
| Paiements et écritures de production | 0 |
| Résultat du runner | PASS, sortie 0 |

Dossier privé de la contre-recette :
`C:/Users/utilisateur/.codex/tymotors-postgres-native/runs/native-upgrade-q0bxa82i`.
Le dump et les journaux restent hors dépôt. Après exécution : aucun listener
sur 18877, `cluster_stopped = true`, `postmaster.pid` et `password.txt` absents.

## Sécurité du runner examinée

Les outils sont appelés par chemins absolus dans le répertoire binaire prévu.
Le port occupé est refusé, les variables PG héritées sont supprimées et le
nouveau cluster écoute uniquement `127.0.0.1`. `initdb` impose SCRAM-SHA-256.
Le mot de passe aléatoire passe par fichier privé/environnement, jamais par un
argument contenant sa valeur ; les erreurs sont expurgées et le fichier de mot
de passe est supprimé dans le nettoyage. Aucun service Windows, pare-feu, compte
hébergé ou droit de production n'est modifié. Aucun processus inconnu n'est tué.

L'auditeur a recalculé l'empreinte de l'archive fournie : elle correspond au
checksum éditeur annoncé et vérifié par le Chef. Il n'a pas téléchargé une
seconde archive ni refait lui-même la consultation du checksum éditeur.

## Limites non levées

- Le schéma est reconstruit depuis les migrations locales, avec Auth simplifié ;
  il ne contient pas les éventuelles modifications manuelles du serveur actuel.
- Les données sont synthétiques. Le dump n'est pas une sauvegarde des commandes
  ou clients de production et ne démontre pas leur restauration.
- Le contrôle porte principalement sur cinq tables historiques et la garde de
  lancement. Il ne valide pas les informations fournisseurs ou tous les cas de
  données commerciales existantes.
- Le moteur est maintenant PostgreSQL natif, mais ce runner ne teste pas les
  courses entre plusieurs connexions, un parcours Stripe distant, le transport
  fournisseur, l'envoi de mails ou le déploiement Render/Supabase.
- Une copie isolée du schéma courant et une sauvegarde restaurable réelle
  restent nécessaires avant publication autorisée. Aucun `db push`, repair de
  registre, GRANT distant ou activation commerciale n'est approuvé ici.

## Empreintes des preuves exécutées

| Empreinte SHA-256 | Fichier |
| --- | --- |
| 45730507BB258E44FFE4417934F7B3D1D79B7E432DBA8080011CA7389802E3F3 | tests/run_native_commerce_upgrade.py |
| 4A101B124F2758ECE97B346B222E44FB29D265215B68B13BF7183BF36427AECD | tests/test_native_commerce_upgrade.py |
| 80379B2C04D51C30225532E0AE04509899141E9957ED096FE749D7FD9DF8F82F | postgresql-17.11-5.zip, archive privée |
| 94784DFE9FA0A6BE0270EE753859B98E9309A4D963A06008A686F1BC6BB87A00 | historical.dump, contre-recette privée |
| 02FC9780F582F6EB8DA816466B42215C6367BC70D3F98B77584BBA618835BFA9 | result.json, contre-recette privée |
