# Exécution SQL des commandes à contexte Stripe explicite

APPROVED LOCAL, sans migration distante, activation, paiement réel ni transmission
fournisseur. Chef :2 842 pytest PASS et655 historiques +250 contrôles SQL/HTTP PASS.
Auditeur indépendant :226 Python, même recette655+250 et39 ACL privées PASS.
Transport HTTPX factice avec vrai SDK ; un POST factice, aucune création doublée.

## Périmètre

Migration CLI : `20261029071833_commerce_context_checkout_execution.sql`.
Les nouveaux points d'entrée réutilisent les définitions installées des cores
de devis et de tentatives, avec amendements contrôlés. Les anciennes signatures
restent limitées au sandbox ; aucun historique NULL n'est attribué au compte
courant, aucun prix public ou fichier image n'est modifié.

- `commerce_prepare_context_checkout` : contrôle propriétaire, source du devis,
  compte/profil/mode immuables, création commande/lignes et réservations.
- `commerce_store_context_checkout_params` : reconstruction SQL indépendante
  des paramètres exacts, stockage immuable et empreinte.
- `commerce_claim_context_checkout` : un seul claim, conditions revalidées,
  aucune rotation de clé ou reprise aveugle après issue inconnue.
- `commerce_bind_context_session` : identité session portée par compte/mode,
  persistée dans une liaison immuable et visible dans la tentative.
- `commerce_settle_context_checkout` : fonds confirmés une seule fois,
  snapshots fournisseur/variante/agent/tarif conservés et tâches en revue.
- `commerce_record_context_event` : reçu minimal durable des événements à
  rapprocher ; aucun remboursement n'est inféré ou envoyé.
- `commerce_context_checkout_enabled` : lecture fermée par défaut des conditions
  d'initiation ; ce résultat ne remplace pas le contrôle transactionnel du claim.

Tous ces RPC sont réservés à `service_role`. Les tables de liaison, d'événements
et de tâches ont RLS et aucune permission publique/authenticated. Les changements
de références Stripe et de profil/mode sont interdits après insertion.

## Frontières

Une nouvelle création production requiert le flag persistant, une référence
d'approbation et une période valides, et le compte/profil serveur correspondants.
Il n'existe aucune condition universelle « SIRET reçu ». Les informations
commerciales du devis doivent toujours satisfaire aux contrôles de source
existants ; la migration ne crée aucune preuve fournisseur.

La réception d'un paiement déjà initié est indépendante de ce flag : fermer les
nouvelles ventes ne doit pas effacer un paiement tardif. Une adresse divergente,
une commande annulée ou un stock courant insuffisant conserve un dossier
d'incident attribué au responsable du groupe payé, sans autoriser son
expédition ni consommer le stock, tout en conservant la vérité du paiement.
Les raisons de revue distinguent `fulfillment_approval_required`,
`destination_mismatch`, `inventory_unavailable` et `order_cancelled`.
Une issue Stripe inconnue
conserve sa clé et ses réservations.

Les réservations test et production ont des capacités séparées. Un paiement
production consomme le stock de variante une seule fois lorsque le stock est
disponible et la destination correspond ; le sandbox ne réduit pas le stock.
Les tâches préparées restent `requires_review`, `external_send_allowed=false` :
elles ne constituent ni une commande fournisseur ni une expédition.

Les identités de session/PI sur `orders` et les reçus utilisent le namespace
compte/mode. L'unicité des anciens identifiants NULL-account est conservée ;
les helpers de remboursement historiques sont confinés à cet historique pour
éviter tout rapprochement entre comptes sur un PI opaque identique.

Les remboursements du nouveau contexte sont, à ce stade, reçus pour revue
manuelle. Le lot n'implémente pas leur projection financière complète ni une
émission de remboursement. Ne pas déclarer le module SAV/remboursement réel
entièrement opérationnel sur la seule base de ces reçus.

## Vérifications effectuées par l'auteur

- Compilation et contrôles de la base PGlite : `66 + 115 + 66`, PASS.
- Première recette : `655` contrôles historiques + `181` contrôles du nouveau
  moteur, PASS (avant les contre-tests supplémentaires ci-dessous).
- Nouveau probe : `tests/commerce_production_http_probe.py`.
- Contre-tests ajoutés ensuite : helpers de remboursement legacy avec même PI
  dans plusieurs comptes ; isolation d'un hold sandbox et d'un checkout
  production sur le même panier ; parcours HTTP réel vers transport SDK simulé,
  signature webhook, règlement SQL et reçu propriétaire.
- Après revue initiale, attribution d'un dossier également pour chaque groupe
  payé en incident (stock/adresse/annulation), avec raisons explicites et envoi
  interdit ; recette finale655+250 et contre-audit indépendant réussis, approuvés
  localement par le chef. Les dossiers n'autorisent aucun achat ou envoi.

Le chef et l'auditeur ont exécuté la recette finale avec succès.
Les simulations utilisent des produits/offres/coûts/adresses
entièrement fictifs dans une base jetable ; elles ne valident aucun produit réel,
compte marchand, transporteur, délai ou tarif fournisseur.

PGlite prouve ici les transitions et les refus SQL. Une concurrence native avec
plusieurs connexions PostgreSQL indépendantes n'est pas démontrée par ce moteur.
Le préflight historique du lot précédent reste un diagnostic conservateur, pas
une autorisation d'exécution du nouveau moteur.
