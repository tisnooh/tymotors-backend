# Rapprochement des migrations —30octobre

Lecture seule du registre de production Tymotors Paris :24 entrées. Le fichier
REMOTE_MIGRATION_HASHES_2026-10-30.json associe chaque version réellement
enregistrée au fichier local correspondant, avec empreintes MD5 comparatives
après retrait des CR et des blancs externes (pas de normalisation du SQL).

Résultat :22 textes concordent ; deux diffèrent seulement par présentation et
commentaires après comparaison directe des statements enregistrés :
- withdrawal_receipts : même remplacement de contrainte email_type et mêmes
 13 valeurs autorisées, dont withdrawal_received.
- enforce_active_auth_session : même fonction SQL stable security definer,
  search_path vide, contrôle session/utilisateur/expiration, mêmes REVOKE/GRANT.

Contrôle supplémentaire du schéma actuel par requête de métadonnées : définition
is_auth_session_active conforme, EXECUTE service_role vrai, anon et authenticated
faux ; contrainte email_type contient effectivement withdrawal_received.

Ce rapprochement explique les différences de numéros sans réparer le registre
ni rejouer du SQL. Il ne constitue pas une preuve d'absence de toute dérive du
schéma actuel, ni une sauvegarde/restauration de production. Les empreintes MD5
servent à la comparaison, pas à une attestation cryptographique de provenance.
Les deux textes distants utilisés pour revue restent dans le dossier opérateur
privé hors dépôt ; aucune donnée client n'a été exportée.

## Recette améliorée

Le test commerce_upgrade_preservation reconstruit désormais les24 migrations
historiques locales avant insertion des données synthétiques, puis applique les
21 nouvelles migrations. Les11 anciennes migrations auparavant omises sont donc
couvertes : elles s'exécutent uniquement dans la base jetable, jamais sur le site.
Résultat Chef :PASS24+21,1 696 champs inchangés,40 produits et une commande
historique conservés, garde commerciale false, aucune écriture distante.

Le constat de baseline partiel du rapport du29octobre décrit l'ancienne version
du test. La nouvelle version couvre toute la chaîne des migrations du dépôt,
mais ne reproduit toujours pas les changements distants hors migrations, les
extensions et données réelles ni les courses PostgreSQL multi-connexion.

Reprise : exporter et comparer le schéma courant sans données client, vérifier
un point de restauration, répéter sur une copie isolée appropriée, puis soumettre
le lot exact pour publication. Aucun prix, image ou design modifié.
