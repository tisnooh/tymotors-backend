# Stripe — recette isolée et connexion sécurisée

## État constaté le 24 octobre 2026

Le connecteur Stripe installé ne fournissait pas de compte utilisable (`link_id`
manquant). Une alternative **officielle** a été utilisée : la CLI Stripe1.55.1,
`sandbox create --help`, puis création anonyme sous profil dédié. Documentation :
[sandboxes](https://docs.stripe.com/sandboxes), [clés](https://docs.stripe.com/keys),
[webhooks](https://docs.stripe.com/webhooks),
[fulfillment Checkout](https://docs.stripe.com/checkout/fulfillment).

Compte de test : `acct_1UU8fq7oQBUfbTTb`. Profil :
`tymotors-phoenix-isolated`. `stripe whoami --format json` confirme le profil ;
une vraie requête SDK16.0.0 de lecture Checkout réussit. Le solde n'est pas
accessible selon les permissions actuelles ; cela ne nécessite pas d'élargir
les permissions pour la recette Checkout. Aucun compte live n'a été configuré.

La CLI conserve ses clés dans son dossier privé, **hors dépôt**. Ne jamais
afficher ce fichier, exécuter `config --list`, copier une clé dans le chat,
un argument de commande, une capture ou un rapport. Ne pas utiliser le connecteur
MCP avec cette sandbox anonyme avant revendication officielle.

## Ce qui doit rester distinct

- Les557 assertions du runner local utilisent Stripe **FAKE**.
- Une réponse API Checkout réelle prouve une création, pas un paiement.
- Seul Checkout de test terminé, webhook authentique signé, journal SQL,
  commande unique et tâche attribuée permettent de valider cette recette.
- HyperSKU reste une **préparation interne synthétique**, pas une connexion
  externe, une transmission, un devis confirmé ou une autorisation de dépense.
- Aucun test ne valide les40 produits réels, leurs droits, compatibilités ou coûts.

## Défaut réellement découvert pendant la première tentative

Une session Stripe de test a été créée mais la conversion SDK utilisait
`to_dict_recursive`, absent des ressources SDK16 actuelles. Le service l'a
refusée et a conservé le statut inconnu plutôt que de recréer un paiement.
Correction : `to_dict()` récursif par défaut, avec test sur une vraie classe
SDK, et compatibilité ancienne méthode seulement en secours.

Session concernée : `cs_test_a1id6mEaNZq8ONxb3LJllJOoexSsODYosUunPDvjzYdzLSqOHHM7v24XaA`.
Vérification réseau avant nettoyage : `livemode=false`, `open`, `unpaid`,
metadata de la tentative synthétique attendue. Expiration explicite de cette
seule session appartenant à la recette : résultat `expired/unpaid` confirmé.
Aucune carte soumise, aucun paiement réel ou de test accompli par cette tentative.
L'échec reste documenté, non transformé en réussite.

## Exécution opt-in

`tests/run_stripe_sandbox.py --help` décrit les paramètres non secrets :
exécutables Node/CLI, fichier de configuration privé, profil et compte précis,
dossier privé **nouveau** de rapport et `--accept-sandbox-test-only` obligatoire.
Le runner refuse les ports8765/8766 occupés, le mélange d'une clé live, un compte
différent et l'écrasement d'un rapport existant. Une clé test ne prouve pas à elle
seule qu'un compte est isolé : utiliser uniquement le profil dédié vérifié.

Le runner récupère le secret webhook par `stripe listen --print-secret` en
mémoire, démarre son propre PostgreSQL/PGlite jetable, serveur loopback et
listener officiel. Les secrets ne sont transmis qu'au processus backend.
Le flux autorisé emploie un seul SKU `SANDBOX-SYNTHETIC-*`, un véhicule de fixture,
un tarif et un mapping marqués synthétiques. Il ne touche ni les fichiers photos,
ni les données hébergées, ni les prix publics. Les emails et routes legacy de
paiement sont interdits dans cette fixture. La carte employée doit être
strictement une carte de test documentée par Stripe, sur `checkout.stripe.com`.

Le délai configuré de60à1800secondes borne l'attente Checkout, en plus des
délais bornés de démarrage/préparation. Le fichier `STOP` dans le dossier de
rapport empêche la création initiale ou arrête l'attente. Interruption connue,
échec et délai expiré ne sont jamais un succès ; les processus possédés sont
arrêtés. L'état SQL synthétique est sauvegardé dans `disposable-state.json`
avant nettoyage pour rapprochement ; ne jamais recréer aveuglément une
tentative distante ambiguë. Ces fichiers privés ne contiennent aucune clé.

## Connexion durable si nécessaire

Pour conserver une sandbox anonyme après son expiration, le propriétaire peut
utiliser la procédure officielle `stripe sandbox claim`, puis `stripe login`
sur le profil dédié. Ces commandes ouvrent un parcours Stripe officiel ;
connexion, CAPTCHA et accord utilisateur restent humains. Vérifier ensuite
`stripe whoami --format json`, le compte visé et l'absence de clé live dans ce
profil. Ne jamais réutiliser par défaut le profil d'un autre projet.

Pour une sandbox durable d'équipe, créer/sélectionner une sandbox séparée dans
le Dashboard et une clé restreinte aux opérations réellement nécessaires.
Installer exclusivement côté serveur isolé, via gestionnaire de secrets ou
saisie locale masquée : `STRIPE_MODE=test`, `STRIPE_SECRET_KEY` de test,
`STRIPE_WEBHOOK_SECRET` propre à la destination test. Aucun `REACT_APP_*` ou
secret frontend. Ne jamais activer production, prix live ou paiements réels
pour débloquer une recette.

État paiement de bout en bout : **EN COURS / NON APPROUVÉ tant que le rapport
réel n'atteste pas la signature, le journal, l'unicité et l'attribution**.

## Point de reprise25octobre

La création réelle, le binding SQL et la récupération de Checkout sont prouvés.
Le deuxième essai s'est arrêté sur import tardif de helper dans l'orchestrateur ;
ce chargement a été avancé avant toute opération distante et le lancement module
est recommandé. La deuxième session a également été vérifiée impayée et expirée.

Troisième essai : vraie page Checkout ouverte, bannière « environnement de test,
aucun paiement réel », total35EUR fictifs. Le navigateur n'a plus répondu avant
saisie carte. Runner arrêté viaSTOP, processus possédés nettoyés et snapshot SQL
conservé. Session `cs_test_a1m4GM8XMeuaNqPJFBYEl4aOaJqNEuMZWrrunqnXtoXjeQh8uxGu8Ag1TW`
relue par SDK puis expirée : `livemode=false`, `unpaid`, `expired` confirmés.

Les trois sessions synthétiques sont closes sans paiement. Les rapports privés
recette-2026-10-24, suffixes-b/-c ne doivent pas être écrasés. Toute nouvelle
recette exige navigateur rétabli, nouveau dossier, vérification préalable du
profil/test et des sessions précédentes. Aucun paiement sandbox accompli n'est
revendiqué ; aucun vrai webhook de paiement réussi n'est encore attesté.

## Inspection privée d'une session déjà liée

`GET /api/admin/commerce/checkout-attempts/{attempt_id}/provider-observation`
exige l'administrateur, le mode test et une clé de test exclusivement côté serveur.
L'identifiant de session est lu dans `commerce_test_sessions`, jamais fourni par
le navigateur. Sans liaison : recherche fournisseur manuelle requise et aucun
appel Stripe. Lecture fournisseur selon l'API officielle
[Retrieve a Checkout Session](https://docs.stripe.com/api/checkout/sessions/retrieve?lang=python),
vérifiée le25octobre2026 après indisponibilité du connecteur documentaire sans link_id.

La réponse privée distingue le paiement enregistré localement, le paiement
observé en attente d'événement signé, l'impayé ouvert/expiré, les divergences et
les remboursements à vérifier séparément. Aucun montant ou état Checkout ne
prouve à lui seul le remboursement. La lecture n'écrit aucune donnée, ne crée
pas d'événement, ne recrée pas de paiement et ne libère aucune réservation.
Deux lectures du contexte encadrent l'appel fournisseur ; un changement impose
une nouvelle revue. Données privées expurgées et réponse no-store.

Délais séparés : appel applicatif25s, transport20s, tentative de nettoyage3s.
Un échec de fermeture produit une alerte fixe sans secrets ; la fermeture
physique ne peut pas être garantie si elle échoue. Tests de cette route avec
transports simulés uniquement : ne pas les confondre avec une nouvelle recette
réseau authentifiée ou un rapprochement financier complet.
