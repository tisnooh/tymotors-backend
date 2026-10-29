# Traitement manuel et suivi de plusieurs colis

Lot local, sans déploiement, commande fournisseur, transporteur, paiement,
remboursement ni expédition réelle. Les preuves utilisées par la recette sont
entièrement fictives et ne valident aucune offre commerciale réelle.

Migration : `20261029131412_commerce_context_manual_dispatch.sql`.
Recette : `tests/commerce_context_dispatch_probe.py`.
APPROVED LOCAL : Chef2 881 pytest PASS et recette655+250+216 PASS ; auditeur
146 Python PASS, même contre-recette655+250+216 et15 vérifications ACL PASS.
Les empreintes gelées sont identiques et les ports des fixtures sont fermés.
Rapport : `TYMOTORS_CONTEXT_DISPATCH_INDEPENDENT_AUDIT_2026-10-29.md`.

## Enregistrement des étapes réelles par un administrateur

`commerce_advance_context_task` réutilise les groupes payés et leurs instantanés
fournisseur/agent/variante/tarif. Les étapes sont :

1. `requires_review` → `supplier_confirmed` : référence fournisseur et preuve
   explicite du contrôle de la référence, variante et montage. Cette saisie est
   une attestation humaine, pas une réponse fournisseur automatiquement vérifiée.
2. `supplier_confirmed` → `shipped` : transporteur, numéro de suivi réel, URL HTTPS
   et preuve de l'expédition. Un numéro `SIM-` ne peut pas représenter un envoi.
3. `shipped` → `delivered` : preuve de la livraison physique d'un colis déjà
   expédié. Une annulation ou un examen financier ultérieur ne doit pas empêcher
   l'enregistrement de ce fait ; cela n'autorise aucune nouvelle expédition.

Chaque groupe correspond à un dossier/colis. Plusieurs groupes peuvent avoir des
suivis et des dates distincts. La subdivision d'un même groupe en plusieurs colis
supplémentaires n'est pas implémentée par ce lot.

La mutation utilise la version `updated_at`, conserve les références et les
preuves déjà enregistrées, et rend une répétition identique sans nouvel effet.
Les données historiques du produit, les montants, le fournisseur, l'agent et les
instantanés ne sont pas réécrits. Une preuve contradictoire ou une version
obsolète ne permet pas de remplacer une étape existante.

## Revue, statut global et notifications

Le marqueur de revue de compatibilité n'est levé que lorsque tous les groupes
ont une confirmation technique humaine et une preuve, que leurs instantanés
correspondent aux lignes payées et aux contrôles du devis à la date d'achat,
et qu'aucun incident ne persiste. Une seule confirmation partielle ne suffit pas.
Cette levée est explicitement auditée avec les preuves de chaque groupe.

Le statut global devient `processing`, `shipped` puis `delivered` seulement
lorsque tous les groupes satisfont au niveau correspondant. Les changements
globaux réutilisent l'outbox existante. Un changement d'un seul colis ne crée
pas une seconde notification globale prématurée.

La timeline existante reçoit un événement par colis et étape, avec le
transporteur et le numéro de suivi dans la description publique. Elle n'expose
pas les preuves privées, les coûts ou les références internes du fournisseur.
Pour plusieurs colis, le champ global de suivi ne prétend pas représenter un
colis unique ; les suivis individuels restent dans la timeline et la projection
publique des colis. Aucun composant visuel ni fichier image n'est modifié.

`external_send_allowed` reste faux : enregistrer un accusé fournisseur ne passe
aucune commande, ne paie rien et n'envoie aucun message. Enregistrer une preuve
d'expédition ne génère pas d'étiquette et ne prouve pas une connexion transporteur.

## Incidents financiers

La nouvelle signature à sept paramètres de `commerce_record_context_event`
conserve le PI normalisé d'un événement de remboursement signé. La signature
historique à six paramètres reste un wrapper exact, sans ambiguïté de paramètres
par défaut. Une correspondance exige le même compte, mode, profil et PI.

Un remboursement reçu avant ou après le paiement pose une revue financière
persistante sans inventer de montant remboursé ni modifier la vérité du paiement.
Un remboursement sans PI reste non rapproché et interdit les nouvelles
expéditions pour son compte/mode/profil jusqu'à revue. Il n'est jamais attribué
au hasard à une commande. Les échecs non liés à un remboursement ne créent pas
ce blocage financier supplémentaire.

Une commande annulée, remboursée, en revue financière ou sans stock appliqué ne
peut pas lancer une nouvelle expédition. Les incidents du dossier restent
bloquants. Un colis déjà expédié peut néanmoins être enregistré livré sur preuve,
en préservant les marqueurs financiers, la compatibilité et l'annulation.
Une notification devenue incompatible avec la situation financière est refusée
au claim ; un transport déjà accepté ne peut pas être rappelé.

La projection financière complète des remboursements et la résolution humaine
des reçus non rapprochés restent des fonctions distinctes. Ce lot ne les présente
pas comme terminées.

## Vérifications et limites

Première compilation locale : `66 + 115 + 66` contrôles PASS.
Première recette avant correction de livraison tardive : `655 + 250 + 172`
contrôles PASS, résultat communiqué par le chef. Les nouveaux contre-tests de
livraison après incident et GET → version exacte → mutation nécessitent la
recette finale et l'audit indépendant ; ne pas les compter comme validés avant
leur sortie effective.

Les contre-tests couvrent plusieurs groupes, les permissions, les versions
obsolètes, les répétitions, les preuves contradictoires, les URL non HTTPS,
les numéros simulés, les incidents de stock/adresse/finance, les remboursements
avant/après paiement et l'isolation des comptes. Ils ne constituent pas un envoi
réel de colis ou une validation fournisseur. La concurrence PostgreSQL native
avec plusieurs connexions n'est pas démontrée par PGlite.
