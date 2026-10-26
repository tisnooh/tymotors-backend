# Notifications d'expédition — durabilité et contrôle des doublons

## Périmètre et état

Lot local sur `codex/commerce-workflows`, suite au correctif HyperSKU interne
`b306df3`. Ne constitue ni un déploiement, ni une intégration HyperSKU réelle,
ni une validation commerciale d'article. Design, photos et prix publics inchangés.
**APPROVED LOCAL** après tests et contre-recette indépendante. Cette approbation
reste limitée au mécanisme de notification manuelle décrit ci-dessous.

Le changement concerne les quatre notifications du parcours administratif manuel :
préparation, expédition, livraison, annulation. Les confirmations de paiement,
remboursement et commande historiques ne sont pas migrées par ce lot.

## Défaut corrigé

La transition de commande était atomique, mais le mail était créé après son
commit. Un arrêt du serveur entre ces étapes perdait l'intention ; un replay de
la transition n'envoyait plus rien. La nouvelle migration ajoute l'intention dans
la même transaction, dans `email_logs` existant. Un échec d'enqueue annule aussi
la transition, l'audit et le suivi. Aucun second système de commandes ou journal
de mails n'est créé.

Le destinataire et le minimum de données nécessaires au modèle existant sont
figés : commande, sommes historiques, transporteur/suivi et lignes. Aucun nom,
adresse de livraison, secret ou contenu de conversation supplémentaire n'est
copié. Modifier ultérieurement la commande ou ses lignes ne redirige pas le mail.
Les templates existants et les fichiers images ne sont pas modifiés.

## Mécanisme et états

| État interne | Signification | Reprise autorisée |
|---|---|---|
| pending | Intention commitée, transport non réservé | Action explicite d'un administrateur |
| blocked | Configuration/contenu indisponible, aucun transport tenté | Même journal, après correction |
| claimed | Jeton exclusif attribué ; l'issue peut être inconnue après interruption | Pas de renvoi automatique ; contrôler le prestataire |
| sent | Transport accepté et résultat enregistré | Aucun renvoi |
| unknown | Résultat ambigu ou événement devenu obsolète | Revue manuelle, aucun renvoi automatique |

Les valeurs publiques historiques `queued/sent/failed` restent compatibles avec
l'administration existante ; `delivery_state` explique les cas ambigus.
`claimed` et `unknown` ne prouvent jamais que le client n'a rien reçu.

- L'API réserve sous verrou via RPC, avec contrôle du rôle administrateur avant
  et après acquisition. Même jeton rejoué ou autre demande : aucun second droit
  d'appeler le transport. Ordre des verrous : commande puis journal.
- Une exception réseau après l'appel prestataire est ambiguë, pas un échec
  autorisant une nouvelle tentative. Une perte de réponse de réservation ou de
  finalisation ne déclenche pas non plus un nouvel envoi.
- Destinataire, instantané, clé, identifiant, création et jeton figés. Résultats
  terminaux protégés. Suppression des lignes outbox et TRUNCATE refusés pour
  conserver les clés d'idempotence. Toute politique future de rétention/anonymisation
  exige un lot dédié conservant une protection contre les doublons.
- Clé existante conservée : `order:{id}:{kind}:once`. Collision avec un ancien
  journal : ne pas le convertir ni le renvoyer aveuglément. Un ancien mail `sent`
  est déjà traité ; ancien `queued/failed` nécessite une revue prestataire.
- Le retry générique filtre les lignes gérées par outbox. Le retry des quatre
  anciens types manuels ambigus est refusé. Aucune seconde clé pour forcer un envoi.
- Commandes de test exclues. Un événement ne correspondant plus au statut de
  commande est placé en revue, jamais annoncé comme son état courant.
- Les fonctions sont invoker, `search_path=''`, exécutables uniquement par le
  rôle serveur. Les RLS existantes ne sont pas élargies ; client/anon n'accèdent
  ni au destinataire ni à l'instantané privé.
- Une commande impayée, annulée ou remboursée (même partiellement) avant claim
  ne reçoit pas un ancien message de préparation/expédition/livraison. Le mail
  d'annulation reste valide après un remboursement séparé, sans en promettre un.

## Reprise réelle, sans service fictif

Après un arrêt **avant réservation**, l'administrateur peut relancer la ligne
depuis l'endpoint de retry existant. Une configuration absente reste bloquée,
sans appel SMTP/Brevo. Après une réservation abandonnée ou une issue ambiguë,
vérifier l'historique du prestataire avant toute décision ; ce lot ne propose
aucun bouton de contournement. Le code ne garantit pas une livraison client
« exactement une fois » : aucune idempotence du prestataire n'est présumée.

Pas de worker planifié, polling, backfill historique, mail réel, changement de
credentials/permissions, commande fournisseur, paiement ou transmission client.
Aucun mécanisme de surveillance permanente installé.

## Preuves en cours de constitution

- Premier ciblé :54 pytest PASS ; après tests de reprise/API supplémentaires,
  63 pytest ciblés PASS.
- SQL jetable :66 historiques +115 expédition +60 outbox PASS. Inclut rollback
  d'enqueue, collisions anciennes, jetons concurrents/rejoués, mauvais jeton,
  état inconnu, absence de mail test, détachement FK, RLS, DELETE/TRUNCATE refusés.
- Premier HTTP : échec d'attente du harness (200 au lieu du202 contractuel du
  retry). Attente corrigée, pas le contrat API. Reprise :37 assertions PASS,
  API→SQL→suivi client, zéro transport mail.
- Régression complète :655 assertions HTTP/SQL PASS, Stripe FAKE, cinq pilotes
  synthétiques, zéro article commercial validé et zéro commande fournisseur.
- Revue indépendante a refusé initialement la protection incomplète de
  l'historique DELETE/TRUNCATE. Défaut corrigé ; revue statique actualisée sans
  nouveau contournement concret. Contre-exécution finale encore requise.
- Contrôle complémentaire du Chef effectué : garde financière et contre-tests
  ajoutés. Nouvelle recette finale :41 assertions HTTP PASS, sans mail envoyé.
- Suite backend finale : **1553 pytest PASS**,65,92s, sortie0 ; une dépréciation
  Starlette/httpx préexistante. Aucun échec de test restant dans cette suite.

### Contre-recette indépendante finale

- **41 assertions HTTP PASS**, sortie0, aucun transport mail.
- JSON mesuré SQL : `checks=66`, `dispatchChecks=115`, `outboxChecks=65`,
  moteur PostgreSQL/PGlite, `result=passed`.
- **63 pytest ciblés PASS**,7,02s, sortie0 ; dépréciation Starlette/httpx connue.
- Six hashes de code/test identiques avant/après ; ports8765/8766 sans écoute,
  diffcheck sans erreur. Aucun fichier modifié par l'auditeur.
- Revue finale sans nouveau contournement concret, **APPROVED LOCAL**. Le Chef
  accepte ce périmètre, pas la mission complète ni une activation commerciale.
- Relecture du diff staged et contrôle ciblé des formats de clés/jetons : zéro
  résultat, sans afficher de valeur sensible. Gitleaks n'a pas été retrouvé dans
  le PATH/runtime temporaire de cette exécution et n'a pas été relancé ; ce
  contrôle ciblé n'est pas présenté comme un scan exhaustif de secrets.

Hashes SHA-256 de la version finale :

| Fichier | SHA-256 |
|---|---|
| migration `20261026142428_order_notification_outbox.sql` | `4C99708B160C2B8E0E9D31B20634007A3DDFC4B753EF1F6BBBB0B88D724B6E46` |
| `app/services/order_notification_outbox.py` | `0FC19AE7D775FF5270B7030CDD0C2EA74E5810947F0E311F1165E644F174B75E` |
| `tests/order_outbox_database.mjs` | `56B9DDB0142B9BD0F9AC0F10364C5AAD51BEC31CB0394951708601171FF684D9` |
| `tests/order_dispatch_http_probe.py` | `6B9738DE697961AAA04B37B46FA7050599E91FE737E820C1304E68C491DED6AF` |

Concurrence PostgreSQL multi-connexion/GoTrue/PostgREST hébergés non prouvée par
PGlite ; les tests de claims de ce lot ne doivent pas être présentés comme cette
recette distante.

## Ce qui reste en dehors du lot

- HyperSKU réel : contrat/API/authentification, Store ID, SKU de variantes et
  devis France manquants. Nouvelle recherche Gmail de cette exécution, après le
  25 octobre, domaines officiels HyperSKU/etailerhub : zéro nouveau message,
  pagination complète. Ne pas renvoyer une relance le même jour sans instruction.
- Cinq produits commerciaux : aucune preuve manquante de droits, prix, port ou
  montage n'est fabriquée pour les activer. Pas de nouvelle validation commerciale.
- Rapprochement financier et remboursement des commandes quoted : lot séparé
  toujours nécessaire ; la lecture privée de session ne remplace pas une transaction
  financière durable ni un événement signé. Ne pas libérer les réservations à tort.
- Publication/migration/activation live restent soumises à autorisation humaine.

Le catalogue et la connexion fournisseur ne sont donc pas déclarés « terminés ».

## Point de reprise

1. Ne pas recommencer les tests de ce lot sans changement pertinent ; conserver
   la migration non appliquée aux bases distantes jusqu'à accord de publication.
2. Lire les réponses HyperSKU dans le fil existant avant toute nouvelle action,
   sans supposer qu'un login web ou le modèle import constituent une connexion.
3. Le prochain lot Codex indépendant est le rapprochement financier durable et
   les remboursements quoted, avec contrat et tests dédiés. Les verrous actuels
   restent actifs tant qu'il n'est pas audité. Les confirmations de paiement et
   remboursement ne bénéficient pas automatiquement de cette nouvelle outbox.
4. Recette hébergée isolée après accord/accessibilité de l'environnement ; aucun
   élargissement de permissions ou déploiement production par défaut.
5. Qualification des cinq offres pilotes sur preuves fournisseur, puis canal
   HyperSKU autorisé et recette de réception/suivi avant toute ouverture live.
