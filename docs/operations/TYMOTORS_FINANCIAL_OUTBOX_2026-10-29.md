# Notifications financières — intentions transactionnelles locales

Périmètre : `payment_confirmed` et `refund_confirmed` dans `email_logs` et
l'outbox existante. Aucun nouveau worker, seconde file, backfill, SMTP, appel
Stripe/fournisseur, compte connecté, mode live ou publication. Les commandes
quoted et les brouillons avec compte lié restent fermés suivant leurs gardes.

## Contrat durable

La migration CLI `20261029001805_commerce_financial_notification_outbox.sql`
étend uniquement les kinds autorisés dans la contrainte de forme de l'outbox.
Les règles de snapshot immuable, destinataire figé, suppression interdite,
claim exclusif, token de complétion et issue inconnue sont réutilisées.

Un trigger sur les transitions d'une commande non-test enregistre l'intention
dans la même transaction :

- Passage vers `payment_status=paid` depuis un état non payé/non remboursé :
  clé historique `order:{id}:payment_confirmed:once`.
- Augmentation de `refunded_amount_cents` :
  `order:{id}:refund_confirmed:{cumul}`. Un cumul répété ne crée rien.
- Aucun log pour une commande de test, aucune reprise automatique de l'historique
  et aucune notification sur simple INSERT d'une ancienne commande déjà payée.

Une panne d'enqueue fait échouer la transaction financière concernée ; un arrêt
après commit laisse une intention persistée. Cela ne prouve pas l'authenticité
Stripe d'une mise à jour SQL et n'autorise aucun paiement réel.

Une collision avec un ancien journal conserve intégralement ce journal, quel que
soit son statut. Ni conversion en snapshot ni renvoi d'une issue ambiguë. Les
journaux managed restent protégés par leurs tombstones et l'idempotence existante.

## Snapshot version 1

Les champs `version=1`, `order` et `items` sont conservés. Pour les kinds
financiers uniquement, `order` contient aussi `is_test`, `status`,
`owner_user_id`, `refunded_amount_cents`, `stripe_payment_intent_id` et
`financial_review_required`. Aucun bearer ou identifiant de session guest
n'est copié dans le journal.

`financial` contient exactement les valeurs nécessaires au contrat de rendu :

```text
kind
refunded_amount_cents
total_cents
payment_intent_id
occurred_at
```

`occurred_at` est l'instant de capture de la transition **dans la base**, pas
une date d'événement Stripe authentifiée. Le montant de remboursement affiché
est le cumul figé, jamais la somme de journaux successifs ni un delta inventé.

## Claim administrateur

Les RPC existants `admin_claim_order_notification` et
`complete_order_notification` restent utilisés, avec les mêmes ACL. Les
anciennes notifications de fulfillment gardent leur validation distincte.

Avant un claim financier, la base contrôle à nouveau, sous verrou commande puis
journal : identité de la commande/propriétaire, compte client du log, mode
non-test, PI figé, devise EUR, total positif, sous-total + livraison, taxe et
montants figés. Le propriétaire guest est JSON null et comparé explicitement
à JSON null ; aucune inférence d'identité à partir de l'email.

Paiement : payé, cumul nul, commande non annulée/non remboursée et aucune revue
financière. Remboursement : cumul exact positif et inférieur ou égal au total,
aucune revue financière, état partiel `paid` ou intégral `refunded`, cohérents
dans le snapshot et dans la commande. Une commande annulée peut conserver une
notification de remboursement confirmé ; elle ne reçoit pas une confirmation
de paiement devenue trompeuse.

Un simple changement du fulfillment n'invalide pas la vérité financière. Une
incohérence financière/propriétaire devient `unknown`, sans transport. Une
configuration ou un rendu indisponible devient `blocked` avant claim. Un
token déjà réclamé, envoyé ou ambigu n'autorise pas un nouvel envoi.

Le paiement et le remboursement ne sont toujours pas atomiques avec un SMTP
externe. Une évolution postérieure au claim et une réponse fournisseur perdue
restent des limites opérationnelles ; aucune garantie d'envoi exactement une
fois n'est présentée.

## Isolation des remboursements quoted

Le helper legacy `record_order_refund`, fondé sur le seul PaymentIntent, refusait
insuffisamment les commandes quoted. La migration ajoute une garde après
verrouillage et avant toute mutation ou retour de montant : les commandes
quoted, de test ou futures non-test, doivent utiliser leur ledger financier
revu. Le chemin legacy sans devis est conservé. Les anciens règlements sandbox
et leur journal de remboursements ne sont ni promus ni réécrits.

## Tests préparés et état de validation

`tests/commerce_financial_outbox_http_probe.py` reprend le parcours sandbox
synthétique historique puis crée des fixtures SQL legacy explicitement jetables.
Les simulations de complétion ne prouvent aucun envoi réel.

Contre-cas : rollback complet lors d'une panne d'enqueue paiement/remboursement,
crash après commit, snapshot et destinataire immuables, token erroné/replay,
fulfillment modifié, finance/propriétaire modifiés, guest NULL valide, montants
incohérents malgré un snapshot concordant, remboursements partiels/intégraux,
anciens cumuls, revue financière, collisions legacy, commande de test, garde
quoted et permissions.

La revue statique initiale a relevé deux défauts avant recette finale : contrôle
du propriétaire absent et possibilité d'accepter des états partiel/intégral
incohérents. Corrigés dans le helper SQL et couverts par le probe. Aucun défaut
n'a été masqué par une simple réponse `p_ready=true` du client Python.

Compilation du probe Python : PASS. Premier bootstrap du Chef, antérieur aux
derniers durcissements : 66 admin + 115 dispatch + 66 outbox PASS.

Recette finale du Chef : **exit 0, 655 contrôles du pipeline historique puis
95 contrôles de l'outbox financière PASS**. Moteur PGlite jetable et HTTP
loopback ; signatures SDK avec secret synthétique local, Stripe FAKE. Les
complétions du journal et transports injectés sont des simulations, sans
SMTP/Brevo ni preuve d'un email réellement reçu.

Suite Python globale du Chef : **2578 tests PASS en 34,17 secondes**, sur la
version finale du lot et ses correctifs Python associés. Ces résultats ne sont
pas une preuve de concurrence PostgreSQL/PostgREST multi-connexion native et
ne garantissent pas l'envoi exactement une fois chez un prestataire externe.

La politique applicative des notifications financières reste fermée à l'envoi
automatique : intention mise en file puis reprise explicite administrateur
seulement. La confirmation de commande legacy `order_confirmation` est
inchangée et **hors de ce lot** ; aucune durabilité globale de toutes les
notifications n'est déduite de ces deux nouveaux kinds.

**Contre-exécution indépendante : APPROVED LOCAL.** catalogue_director_audit
a confirmé la sortie0 du runner :655+95 contrôles PASS, empreintes inchangées,
ports8765/8766 fermés. Six contre-tests indépendants du helper SQL passent aussi,
dont propriétaire NULL et détachement simultané des FK. Le Chef accepte ce lot
de préparation locale uniquement. Pas d'envoi réel ni d'activation.

Le Chef câble le chargement de migration et l'allowlist du runner existant.
Aucun serveur, port, compte, clé ou service distant n'a été utilisé par le
développeur de la migration. Aucun commit ni déploiement effectué.
