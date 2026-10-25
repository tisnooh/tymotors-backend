# PHOENIX — contrat de calcul financier privé

## Périmètre et niveau de preuve

`app/commerce_finance.py` est un module pur : aucune requête réseau, base de
données, écriture de prix, commande, accès à Stripe ou publication. Il ne change
ni interface, ni photographie. Il complète les évaluations EUR de
`commerce_pricing.quote_offer`, consommées une fois par groupe de
`commerce_quote_engine`. Il ne constitue ni une authentification de documents,
ni un avis fiscal, ni une autorisation commerciale.

Les tests sont synthétiques. Aucun résultat de ces fixtures ne valide les coûts
des 40 références réelles. Tant que le fournisseur, les coûts, les transports ou
les bases fiscales ne sont pas prouvés, ces informations restent inconnues.

Chaque montant ou taux complémentaire comporte `value`, `provenance` et
`reference`. Provenances : `CONFIRMED`, `ASSUMPTION`, `UNKNOWN`. Une valeur
confirmée ou supposée exige une référence ; une valeur inconnue ne contient ni
montant prétendu ni référence présentée comme preuve. La provenance est une
déclaration du service appelant ; ce module ne peut vérifier une facture.

Les valeurs absentes ne valent jamais zéro. Un zéro est une valeur explicite
documentée. Toutes les entrées sont strictes, bornées, sans champs inattendus.
Les montants sont des centimes entiers (0 à 2 milliards par champ), les taux
des points de base (0 à 10 000) ; booléens, nombres flottants et chaînes ne
sont pas acceptés comme montants. Les nombres signés ne sont autorisés que
pour les contributions et les évolutions de coûts de scénarios.

## Reprise des évaluations sans double comptabilisation

`group_from_evaluation(group_id, evaluation, provenance=...)` extrait seulement
les champs financiers documentés d'une évaluation. `group_id`, variante, offre
et tarif logistique sont requis. Les groupes et triplets
variante/offre/tarif sont uniques. Un groupe couvre toute sa quantité, de 1 à
2 000 unités. La limite est de 100 groupes.

Une évaluation source doit être `ready`, sans motifs de blocage, et les champs
monétaires doivent être présents. Une source bloquée/inconnue ne devient pas
commercialisable parce qu'un calcul arithmétique serait possible. Le service
appelant doit vérifier la fraîcheur des preuves et la validité du devis ;
l'analyse peut aussi servir à examiner un historique sans le réévaluer.

Les montants reçus ont déjà été convertis en EUR par le moteur de devis, avec
ses preuves de change. Le module refuse toute autre devise ; aucune conversion
implicite ni deuxième conversion n'est effectuée.

Définitions sources :

- `supplier_gross_cents` : décaissement fournisseur, taxe fournisseur comprise.
- `acquisition_net_cents` : coût fournisseur moins taxe récupérable confirmée.
- `shipping_net_cents` : coût du transport du groupe moins taxe récupérable.
- `additional_costs_cents` : frais agent, droits, taxes non récupérables et
  autres frais déjà inclus dans le tarif de ce groupe.
- `landed_cost_cents` : somme des trois composants nets précédents.
- `customer_total_cents` : montant TTC payé, articles et livraison compris.
- `revenue_net_cents` : revenu hors taxes de vente, avec les bases distinctes
  articles/livraison déjà utilisées par le moteur de devis.
- `sales_tax_cents` : différence TTC moins revenu net.
- `contribution_margin_cents` source : revenu net moins coût rendu, **avant**
  frais de paiement et autres dépenses d'exploitation.

Le module vérifie ces égalités et les incohérences net/brut. Il ne remultiplie
pas les frais de transport, d'agent ou d'importation par la quantité. Il ne
rajoute pas une taxe fournisseur déjà comprise dans le prix brut.

## Frais de commande et retours

Le paiement est calculé **une seule fois par commande** :

`frais_bruts = fixe_brut + arrondi(base × taux_bps / 10 000)`.

`payment_fee_base` doit être explicite : `GROSS_CHARGED` (TTC encaissé) ou
`NET_REVENUE` (revenu net). Aucun tarif Stripe réel n'est présumé. La taxe
récupérable sur ces frais est un montant séparé documenté et ne peut dépasser
les frais bruts calculés. Les frais nets valent brut moins taxe récupérable.

Les autres frais variables par commande sont des `ExtraCost`, chacun avec un
identifiant unique, sa devise EUR, son montant brut et sa taxe récupérable.
Leur portée doit être `additional_order_cost_not_in_landed` : le déclarant
certifie ainsi qu'ils ne reproduisent pas les frais de sourcing, agent,
préparation ou transport déjà compris dans le coût rendu. Une liste vide ne
veut dire « aucun autre coût » que si son exhaustivité est explicitement
confirmée ou supposée avec une référence. Un libellé ne permet pas au module
de détecter deux factures sémantiquement identiques : l'audit des preuves
reste obligatoire.

Le risque de retour utilise une probabilité par unité et une perte nette
incrémentale par unité retournée :

`perte_attendue = arrondi(quantité_totale × probabilité_bps × perte_unitaire / 10 000)`.

La perte doit inclure la diminution du revenu net remboursé et la logistique
inverse, déduction faite des récupérations documentées. Elle **exclut** le coût
rendu initial déjà intégralement compté. Le comportement de remboursement des
frais de paiement n'est jamais deviné ; les pertes supplémentaires doivent
figurer dans la preuve du coût de retour. Le champ `return_loss_basis` impose
cette convention.

Pour plusieurs groupes/produits, le module refuse une probabilité/perte uniforme
par défaut. `return_profile_scope=UNIFORM_ACROSS_ALL_GROUP_UNITS` exige que les
preuves de probabilité et de perte couvrent explicitement toutes les unités.
Si les profils sont différents, analyser les groupes séparément pour leurs
risques et préparer un contrat de profils distincts avant d'utiliser un total
de commande : ne pas inventer une moyenne homogène.

## Coût et marge

`coût_variable_complet_net = coût_rendu + frais_paiement_nets + autres_frais_nets + perte_retour_attendue`.

`marge_contributive = revenu_net − coût_variable_complet_net`.

`taux_sur_vente_nette_bps = arrondi(marge_contributive × 10 000 / revenu_net)`.

Lorsque le revenu net est nul, ce taux reste `null`. Une marge négative est
conservée, non masquée. Il ne s'agit **jamais d'un bénéfice net** : les frais
fixes, salaires, obligations fiscales, réserves et frais non fournis ne sont
pas inventés. `profitable_before_unmodelled_fixed_costs` décrit seulement le
signe de cette contribution.

La contribution moyenne par unité est explicitement nommée
`average_contribution_per_unit_cents`, avec deux décimales de centime pour ne
pas forcer une allocation incohérente. Elle ne constitue pas la rentabilité
exacte de chacun de plusieurs produits. Le détail des groupes conserve leur
contribution avant frais de commande. Pour un seul groupe, la contribution
après ajustements est attribuable à ce groupe. Pour plusieurs groupes,
`per_product_contribution_after_order_adjustments=null` et un motif explicite
signale l'absence de règle d'allocation ; les frais fixes de paiement ne sont
pas répartis arbitrairement.

Les calculs utilisent `Decimal`, centime arrondi `ROUND_HALF_UP` au stade
documenté : chaque frais proportionnel de commande et perte attendue est
arrondi une fois, non par unité, afin d'éviter les écarts de multiplication.
Les montants historiques fournis ne sont pas modifiés.

## Scénarios explicitement hypothétiques

Trois scénarios distincts sont requis : `PESSIMISTIC`, `REALISTIC`, `OPTIMISTIC`.
Chacun comporte une référence d'hypothèses, une variation du coût rendu, une
variation des autres frais variables, une probabilité de retour et un volume
optionnel sur la période des frais fixes.

Les variations sont des points de base signés, de −10 000 à +100 000. Les
scénarios utilisent le prix public et les taxes du revenu source inchangés ;
ils ne réécrivent pas un prix fournisseur réel. Les frais de paiement restent
ceux de l'entrée de base ; aucun rabais de volume n'est inventé. Tous les
résultats de scénarios portent le statut `HYPOTHETICAL`, y compris le scénario
réaliste lorsque ses hypothèses reprennent la base. Le choix du nom ne prouve
pas que les hypothèses sont économiquement plausibles : le chef doit les
contrôler. Aucun volume ne vaut une prévision confirmée par défaut.

Si le volume et les frais fixes nets sur la même période sont fournis, le
module expose `period_contribution_less_known_fixed_costs_cents`. Ce solde
reste une hypothèse avant coûts non modélisés, pas un bénéfice net.

## Seuil de rentabilité et trésorerie

Le seuil en commandes comparables n'est calculé que si les frais fixes sur une
période sont fournis et la contribution connue et positive :
`ceil(frais_fixes_période / contribution_commande)`. Il s'agit d'un panier-type,
pas d'un seuil global garanti pour un mix de produits différent. Avec frais
fixes positifs et contribution non positive : `null`, motif explicite. Des
frais fixes explicitement nuls donnent zéro commande couvrant ces seuls frais.

Le besoin initial de trésorerie ne se déduit **pas** du coût rendu net : il
nécessite un décaissement brut total documenté et le séquencement de la
disponibilité des fonds clients. `cash_outlay_gross_cents` est le montant
tout compris (fournisseur, logistique, paiement et autres frais), à ne pas
additionner à nouveau aux composants. Un plancher constitué des obligations
brutes/nettes déjà connues rejette une estimation manifestement trop faible ;
ce plancher n'est pas la preuve du véritable coût brut logistique.

Si le décaissement précède les fonds disponibles : pont initial égal au
décaissement. Sinon : `max(décaissement − montant_client_TTC, 0)`.
`cash_timing_reference` et `cash_timing_provenance` sont nécessaires ; un
simple booléen sans preuve/provenance ne rend pas ce calcul confirmé. Les
réserves Stripe, délais de remboursement de TVA, retours tardifs et commandes
simultanées ne sont pas déduits de cette formule simplifiée ; il faut un plan
de flux datés pour un besoin global. Le résultat l'indique dans sa portée.

Les frais fixes ou la trésorerie inconnus ne bloquent pas le calcul connu de
la contribution ; leurs métriques restent `null` avec `optional_unknowns`.

## Statuts et critères de validation

- `BLOCKED` : source bloquée/inconnue, coût essentiel manquant, base de frais ou
  risque de retour non défini, ou liste des coûts non exhaustive. Contribution,
  scénarios, seuil et trésorerie ne sont pas fabriqués.
- `HYPOTHETICAL` : calcul possible mais au moins une entrée repose sur une
  hypothèse, identifiée par champ et référence.
- `CONFIRMED_ANALYSIS` : les entrées nécessaires déclarées et référencées sont
  confirmées ; cette qualification porte sur le calcul fourni, pas sur les
  autres contrôles de commercialisation du produit.

`commercial_approval` reste toujours `false`. Aucun résultat ne lève les
contrôles de compatibilité, droits d'image, livraison, fournisseur, HyperSKU,
agent, devise, validité du devis ou validation humaine des dépenses.

## Tests et limites d'intégration

`tests/test_commerce_finance.py` teste la reprise d'une vraie évaluation
logicielle sur fixture, les quantités groupées, le port non dupliqué, les frais
de paiement uniques, le TTC/net, les retours, les trois scénarios, les inconnus,
les hypothèses, les doublons, les devises interdites, les montants bornés, les
contradictions, la rentabilité négative, les zéros explicites, le seuil, la
trésorerie et la non-mutation des entrées.

Le module pur n'ajoute ni persistance, ni collecte fournisseur, ni connexion
HyperSKU réelle. Le lot PHOENIX l'a raccordé à la route privée
`POST /api/admin/commerce/finance/quotes/{quote_id}/analyze` : groupes extraits
uniquement des instantanés serveur immuables, provenance ASSUMPTION imposée à
cette analyse sandbox, remplacement des groupes par le client refusé422.
Aucun prix public n'est écrit ; approbation commerciale toujours false.
Le module pur et la route ont été contre-audités ; cette approbation technique
ne confirme aucune facture, marge réelle ou référence du catalogue.
