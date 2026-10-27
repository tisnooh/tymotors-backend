# Recette des remboursements — 27 octobre 2026

État final : **recette réseau sandbox réussie, artefacts APPROVED par l'auditeur
indépendant puis acceptés par le Chef dans ce périmètre**. Aucun déploiement, modification du design,
photographie, prix public, achat, nouvelle charge ou nouvelle session Stripe.

## Preuves distinctes

| Contrôle | Résultat et limites |
|---|---|
| Préflight Stripe avant remboursement | Antérieur à l'unique write de la recette : compte isolé accessible, clé live absente du profil. Checkout et PaymentIntent originaux complete/paid/succeeded, livemode=false,3500centimesEUR ; métadonnées, expiration, destination et montants contrôlés par le validateur commun. Aucun remboursement existant à ce moment. Cette lecture ne faisait aucun write ; l'état après exécution figure séparément ci-dessous. |
| Archive du paiement du26octobre | Six lignes liées par identifiants d'origine, validées sans inventer de nouvel événement financier. La restauration n'authentifie pas à nouveau l'ancienne signature. |
| Unités Chef |2003pytest PASS,20,71s sur version finale ; dont217nouveaux tests d'archive/fixture/lanceur. Un avertissement Starlette/httpx existant, sans mise à jour de dépendance dans ce lot. |
| HTTP/SQL Chef |31contrôles PASS sur base PGlite possédée et jetable. Événements et signatures **synthétiques locaux**, zéro appel Stripe. |
| SQL habituel Chef |66admin +115dispatch +65outbox PASS, mode archive désactivé. |
| Contre-audit |217unités finales et31contrôles HTTP/SQL indépendants PASS ; APPROVED LOCAL avant réseau puis APPROVED artefacts après réseau, sans appel API par l'auditeur. Lecture Stripe distincte effectuée par le Chef. |
| Webhook refund venant de Stripe | **EXÉCUTÉ avec succès**, runner exit0, vrai événement signé journalisé et projeté. Contrôle SDK séparé : un seul refund existant, succeeded,3500centimesEUR, PI concordant. Aucun write dans cette seconde lecture. |
| HyperSKU / produits commerciaux | Aucune nouvelle preuve ni transmission. Les40dossiers disponibles restent bloqués commercialement ; aucun pilote approuvé. |

## Corrections et refus

Le premier import local a été refusé parce que la fixture SQL habituelle crée un
devis lors de ses tests dispatch. Aucune donnée n'a été effacée pour contourner
le contrôle. L'option explicite `--serve --refund-archive` charge les mêmes
migrations et fixtures admin, puis omet seulement les scénarios dispatch/outbox
qui créent l'historique financier. Sans cette option, les suites restent entières.

L'auditeur a ensuite rejeté deux insuffisances du lanceur avant toute écriture
réseau : sortie privée insuffisamment bornée et identité du listener non vérifiée.
Corrections : archives et rapports doivent être strictement sous la racine dédiée
`.codex/stripe-phoenix-private` après résolution des chemins, sans chevauchement.
Le secret du banner Ready! doit être unique et égal au secret de réception en
mémoire ; absence, différence et plusieurs secrets sont refusés avant l'appel
refund. Une deuxième revue a relevé le cas de deux bannières sur des lignes
distinctes : toute bannière supplémentaire invalide maintenant définitivement
l'identité, protégée par verrou et recontrôlée après le dernier await. Les tests
couvrent le changement pendant ce dernier préflight et le format ANSI. Aucune exception
gitleaks n'a été ajoutée ; contrôle staged final sans fuite à ce point.

La contre-recette Chef vérifie une archive au hash de paramètres volontairement
corrompu : refus, rollback intégral, compteurs et triggers/RLS inchangés. L'import
valide restaure exactement six lignes et conserve les défauts du schéma récent.
Seuls deux triggers d'insertion historiques sont désactivés dans la transaction
de restauration locale, puis réactivés avant commit ; aucune FK, permission ou
RLS n'est désactivée. Un second import est refusé sans changement.

La réception utilise la fonction webhook applicative originale. La fixture n'a
ni client API Stripe ni route de création de paiement. Avant toute lecture SQL,
elle impose signature brute valide, mode test et PaymentIntent attendu. Un succès
synthétique puis son doublon et un état pending tardif ne doublent pas le montant.
Le hold financier reste actif ; aucun nouvel email, produit ou achat n'apparaît.
Cette fixture ne restaure pas de tâche active : elle ne prouve pas à elle seule
l'arrêt d'une tâche HyperSKU active ou une concurrence PostgreSQL hébergée.

## Lanceur réseau contrôlé et exécuté

`tests/run_stripe_refund_sandbox.py` exige deux opt-ins explicites et le profil
isolé déjà utilisé. Rapports hors dépôt dans un nouveau dossier distinct, archive
originale préservée ; ports occupés refusés. Les processus sont possédés, bornés et
fermés dans finally. La clé API n'atteint pas le processus de réception ; le
secret webhook éphémère n'est ni affiché ni enregistré dans Git ou les rapports.

Avant l'unique write envisagé : double lecture de l'ancien paiement, zéro refund
existant, base restaurée, réception prête et secret du listener officiel vérifié.
Une nouvelle
vérification STOP/processus a lieu après la dernière lecture réseau. Le refund
envisagé porte uniquement sur les3500centimes du PI test archivé, avec clé
d'idempotence stable et `max_network_retries=0`. Aucun autre paiement n'est créé.

Le checkpoint avant l'appel marque l'issue fournisseur inconnue. Si la réponse
est perdue, `actual_stripe_test_refund_created=null`, pas false ; aucun réessai
automatique. Après un échec ou une interruption, lire Stripe avant toute décision.
Ne pas lancer un deuxième runner en parallèle et ne pas recréer de paiement pour
obtenir une preuve plus facile.

L'exécution réseau a reçu un vrai événement signé, créé le journal SQL associé,
projeté3500centimes remboursés, conservé la revue financière et vérifié le hold
ainsi que les autres tables intactes. Aucun nouveau paiement, session, commande
fournisseur, email ou changement catalogue n'a été créé par le refund. Les
rapports distinguent ancien paiement archivé, refund réseau, fulfillment simulé
et HyperSKU réel. L'ancien paiement reste une preuve historique ; il ne faut
plus tenter de rembourser ce cas une deuxième fois.

Les preuves privées sont dans `refund-2026-10-27-existing-payment-1` sous la racine
privée dédiée : résultat, snapshot SQL final et confirmation SDK séparée datée
13:45:48UTC. Le runner est sorti0 ; ports8765/8766 fermés. Pas de processus,
automatisation ou listener supposé actif après cette sortie.

L'auditeur a rapproché la commande parmi les sept anciennes lignes de l'archive :
mêmes IDs, destinataire, devis, montants et PI. Le snapshot final contient
`refund.created succeeded3500` et `charge.refunded` cumulatif3500, sans double
comptage. Le blocage financier est persisté ; le retour de la fonction hold a été
exigé par le runner audité avant succès, sans export séparé de cette fonction.
Empreintes privées confirmées indépendamment :

- Résultat : `12EDB9C8381C96DF6B206C71014195DB4083E28FC94079F5030DFC5B08E4D7D9`.
- Snapshot : `948EA1788E088E03FE9F276EE744EB1FA5E449943A2E11AC3A253F8D54B33780`.

**Décision Chef : APPROVED pour cette recette de remboursement sandbox**.
HyperSKU, tâche active, expédition réelle, cinq pilotes, publication et vente
réelle restent BLOCKED ou hors périmètre, sans validation déduite de ces tests.

## Reprise

1. Lire ce rapport, PROGRESS et le résultat de l'auditeur ; corriger tout rejet.
2. **Ne pas relancer ce cas** : son unique remboursement succeeded est confirmé
   chez Stripe. Ne pas créer une nouvelle charge pour répéter la démonstration.
3. Continuer les dépendances commerciales/HyperSKU et le rapprochement des
   tentatives ambiguës ; le parcours local ne remplace pas ces preuves.
4. Toute nouvelle recette financière exige son périmètre isolé, ses opt-ins et
   sa revue. En cas d'issue inconnue, préserver le rapport et lire le fournisseur
   avant toute décision ; aucun retry aveugle.

Les clarifications Noeifevo et Ikon sont SENT et relues, respectivement09:05:05
et09:05:30UTC. Ne pas les renvoyer. Le contrôle mail après reprise n'a pas trouvé
de nouvelle réponse technique dans la recherche fournisseurs depuis ces envois.
