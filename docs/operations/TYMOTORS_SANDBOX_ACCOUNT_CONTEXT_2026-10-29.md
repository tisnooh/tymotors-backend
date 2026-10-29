# Contexte de compte persistant — préparation sandbox fermée

Ce lot prépare un contexte explicite sur des brouillons internes. Il n'authentifie
aucun compte et n'autorise ni appel Stripe, paiement, règlement live, fournisseur,
email, publication ou déploiement. Aucun design, fichier image ou prix public
n'est modifié.

## Modèle et invariants

- Ajout de `stripe_account_id` nullable à `orders` et
  `commerce_checkout_attempts`, sans valeur par défaut et sans backfill.
- Les anciennes lignes gardent NULL : absence de compte attesté, jamais le compte
  courant supposé. Aucun changement de paramètres, empreinte, clé d'idempotence,
  session ou montant historique.
- Le mode reste `is_test`, déjà immuable pour les commandes quoted. Aucun second
  indicateur de mode contradictoire n'est ajouté ; les CHECK sandbox existants
  sont conservés.
- Un compte renseigné exige un identifiant de forme `acct_…`, une commande quoted
  test et une tentative de même mode. La forme d'un identifiant et l'égalité de
  chaînes ne prouvent ni propriété ni permission chez Stripe.
- Le compte est écrit lors de l'INSERT de la commande, puis copié lors de
  l'INSERT de la tentative. Une tentative explicitement incohérente est refusée.
  Toute réattribution, suppression du compte ou conversion d'une ligne historique
  NULL vers un compte est interdite en UPDATE.

## Réutilisation du parcours existant

La migration CLI `20261028134228_commerce_sandbox_account_context.sql` étend
l'implémentation réellement installée de
`private.commerce_order_from_quote_core` avec un dernier argument compte. Les
anciennes signatures délèguent au même noyau avec NULL : pas de second moteur de
commande ni de copie parallèle des règles de compatibilité, droits, coûts ou
livraison. Les ancres de transformation sont comptées ; une dérive des corps SQL
fait échouer la migration transactionnelle.

Le nouveau RPC
`commerce_prepare_account_bound_test_checkout(actor, quote, account, origin, user, guest)`
est réservé au service et exige un acteur administrateur. Il compose les noyaux
existants : validation du propriétaire, verrou panier → devis → commande,
revalidation des sources, réservation et création de tentative. Les identifiants
client/propriétaire ne sont pas inférés du compte Stripe.

Même compte et même origine peuvent rejouer un brouillon non réclamé sans changer
ses paramètres. Un compte différent, une commande historique non attribuée,
une commande payée ou une tentative déjà réclamée ne sont pas requalifiés.

Les nouvelles tentatives liées restent volontairement **non réclamables** : leur
transition vers `creating`, `unknown`, ou un `first_requested_at` renseigné est
refusée par trigger. Ainsi l'ancien gateway sans contrat de compte explicite ne
peut pas les utiliser pour une création réseau. Les brouillons peuvent conserver
des paramètres prêts ou être annulés avant claim. Un futur gateway account-aware
et les reçus associés nécessitent un lot séparé et audité.

Le RPC indique explicitement `account_authenticated=false`,
`provider_creation_authorized=false` et `publication_authorized=false`. Aucun
accès EXECUTE n'est accordé à PUBLIC, anon ou authenticated. Les ACL historiques,
RLS et autres triggers ne sont ni désactivés ni remplacés.

## Contre-tests et preuves disponibles

`tests/commerce_account_context_http_probe.py` est fourni pour le runner existant,
que le Chef câble et exécute séparément. Il utilise seulement ses deux fixtures
loopback jetables et des identifiants `acct_Synthetic…` : aucun compte réel.

Il reprend d'abord le parcours sandbox historique puis contrôle :

- héritage NULL et conservation des anciennes lignes/params/hash/key/session ;
- RPC service-only, refus d'un acteur non administrateur et d'un autre propriétaire ;
- compte absent/mal formé, origine invalide, tentative de réattribution ;
- copie ordre → tentative, replay même compte, refus d'un autre compte ;
- paramètres produits par le builder avec contexte explicite, aucun provider ;
- claim ancien interdit pour un nouveau brouillon lié ; compte/mode immuables ;
- INSERT de tentative avec compte ou mode incohérent, rollback du devis, de
  la commande et des audits ;
- sources modifiées et création non-test refusées ; aucune session, tâche ou
  commande fournisseur créée pour le nouveau brouillon.

Un premier bootstrap SQL du Chef a échoué avec SQL42703 : un test AND d'un trigger
commun référait à `first_requested_at` sur une commande. Corrigé par un IF imbriqué
par table avant toute référence aux champs de tentative. Cet échec reste enregistré
et ne vaut pas validation de la version corrigée.

Le passage suivant du Chef a exécuté les **655 contrôles historiques avec succès**,
puis le nouveau probe s'est arrêté sur un libellé de test trop court : `owner`
ne correspondait pas à l'erreur existante `Cart not found or not owned`.
L'attendu est corrigé sans changement métier ; un prochain mismatch conservera
le diagnostic de la fixture SQL synthétique. Les cas ultérieurs n'ont pas été
présumés exécutés sur la base de ce passage interrompu.

Préparation exécutée par le développeur : compilation Python du probe réussie et
**619 tests purs mode/paramètres/événements PASS en 2,43 s**. Ces unités vérifient
les contrats Python préexistants du lot parallèle ; elles ne testent pas la
migration ni la concurrence SQL. Aucun serveur ou port n'a été utilisé par le
développeur de ce lot.

Recette corrigée du Chef : **exit 0, 655 contrôles du pipeline historique puis
150 contrôles du contexte de compte PASS**, sur fixtures possédées HTTP/PGlite.
Les annulations drafting/ready, libération des réservations, refus du replay
annulé, identité du propriétaire après replay et INSERT de tentative sur compte
hérité NULL sont effectivement inclus. Le compte synthétique ne déclenche aucun
appel fournisseur ni nouvelle session pour ces préparations ; le pipeline de
régression utilise uniquement son transport Stripe FAKE préexistant.

Versions de cette recette : migration SHA-256
`972507E92B677CC1ADFFC5E07B22EB7619826350C82D32305A096DB0C7BD15B5` ;
probe `EF9A37EF29C6F717EE97E1AC20DEFF4343C5A3796413166BA4564A29C0BD9789`.
Contrôle gitleaks staged du Chef : PASS. Ces résultats sont ceux du Chef,
pas une exécution indépendante du développeur.

**Contre-audit indépendant : en cours, non anticipé.** Ne pas présenter le
fichier écrit, les unités Python ou cette recette locale comme un compte Stripe
connecté, une création réseau autorisée ou une commande opérationnelle.

## Limites et reprise

Contre-audit exécuté par catalogue_director_audit : APPROVED LOCAL,655+150
contrôles compte PASS puis655+137 remboursement PASS, sorties0 et empreintes
inchangées. Ports8765/8766 fermés. Chef accepte uniquement la préparation locale,
sans authentification de compte ni autorisation de création réseau/live.

Pas de psql/PostgreSQL multi-connexion disponible constaté dans ce cycle ; PGlite
constitue uniquement une preuve locale lorsqu'il est effectivement exécuté. Les
preuves hébergées, l'authentification Stripe et l'approbation live restent distinctes.

Avant un futur appel réseau, le serveur doit établir son identité fournisseur,
la rapprocher de ce contexte immuable, vérifier les gardes commerciales et une
autorisation d'activation auditée. Un booléen d'environnement ne peut suffire.
Ne pas lever la garde de claim de cette migration pour contourner ce travail.

Aucune migration distante n'a été appliquée. Avant commit SQL, une erreur annule
la transaction. Après création de brouillons liés, conserver leurs colonnes et
historique : un retour applicatif en arrière n'autorise pas un DROP destructif,
un backfill ou une suppression des preuves.
