# TYMotors — pilote HyperSKU

Préparé le 12 octobre 2026. Statut : compte HyperSKU connecté ; demande de devis envoyée dans le chat du compte ; conversation assignée à Chloe, sans réponse humaine ni devis confirmé à ce stade ; aucune commande test passée.

Le profil de contact et le questionnaire commercial ont été enregistrés avec les réponses expressément fournies par l'utilisateur : aucune publicité, boutique en démarrage, service de commandes à l'unité. Les coordonnées personnelles ne sont pas copiées dans ce dossier.

## Fonctionnement demandé

Commande client payée → validation manuelle TYMotors → achat auprès du vendeur Alibaba existant → réception chez HyperSKU → contrôle et emballage → expédition vers le client → suivi dans TYMotors.

Le pilote doit confirmer que HyperSKU accepte des arrivages à l'unité liés à une commande client, sans imposer un achat de stock en volume. L'acceptation de marchandises fournisseurs est documentée, mais cette organisation à l'unité reste à confirmer auprès de leur agent.

## Trois références proposées

Liens extraits de `data/product_supplier_image_manifest.json`. Les noms et compatibilités proviennent de cet audit local ; le stock, le MOQ, la matière, la variante, le prix et la disponibilité actuelle ne sont pas confirmés.

| Référence TYMotors | Produit | Lien Alibaba |
| --- | --- | --- |
| bmw-g20-mirror-caps | Paire de coques de rétroviseurs noir brillant, BMW G20/G21 | https://www.alibaba.com/product-detail/2-Pcs-ABS-Glossy-Black-Side_1600727145118.html |
| bmw-g20-gloss-black-grille | Calandre noir brillant, BMW G20 2019–2021 selon l'audit | https://www.alibaba.com/product-detail/ABS-Glossy-Black-Replacement-Grille-Car_1600833728383.html |
| bmw-g20-m-performance-spoiler | Spoiler de coffre noir brillant, BMW G20/G28 2019–2021 selon l'audit | https://www.alibaba.com/product-detail/1-Pcs-ABS-Glossy-Black-Car_1600733329759.html |

Fournisseur enregistré : GZTM Auto / Leju (Guangzhou) Trading Co., Ltd. — https://gztmauto.en.alibaba.com

Une paire de coques doit être traitée comme un ensemble complet gauche/droite. Le spoiler permet de mesurer l'effet du volume du colis sur le prix du transport.

## Demande de devis prête à copier

Destinataire commercial publié par HyperSKU : support@etailerhub.com. Ce texte reste un brouillon d'email ; la demande a été transmise dans le chat du compte, avec les trois liens Alibaba et les conditions ci-dessous. Un quatrième message confirme le démarrage de la boutique, l'absence de publicité et la possibilité de rappeler via les coordonnées du profil. Aucun email séparé n'a été envoyé.

Objet : TYMotors — Alibaba supplier-to-warehouse pilot, France delivery and custom-store API

Hello HyperSKU team,

We operate TYMotors, a custom automotive-accessories online store serving customers in France: https://tymotors.vercel.app/.

We would like to evaluate HyperSKU as our fulfillment partner while keeping our existing Alibaba supplier. Our desired workflow is: customer payment, our manual approval, supplier delivery to your warehouse, inspection and protective packaging, then shipment to the customer with full tracking.

Please confirm whether you can receive individual supplier parcels for customer orders without requiring bulk inventory or a monthly order minimum. We would like a dedicated agent and a written quotation before placing any paid test order.

Please quote three separate pilot shipments to mainland France, one sales unit of each product:

1. BMW G20/G21 gloss-black mirror covers, one complete left/right pair:
https://www.alibaba.com/product-detail/2-Pcs-ABS-Glossy-Black-Side_1600727145118.html

2. BMW G20 gloss-black front grille, one complete sales unit, listed for 2019–2021:
https://www.alibaba.com/product-detail/ABS-Glossy-Black-Replacement-Grille-Car_1600833728383.html

3. BMW G20/G28 gloss-black rear trunk spoiler, one unit, listed for 2019–2021:
https://www.alibaba.com/product-detail/1-Pcs-ABS-Glossy-Black-Car_1600733329759.html

Our recorded supplier is GZTM Auto / Leju (Guangzhou) Trading Co., Ltd.:
https://gztmauto.en.alibaba.com

For each product, please provide:
- Confirmation that the exact supplier product and variant can be received and handled; any MOQ or other restrictions.
- The inbound address, parcel registration process and required SKU/order labels.
- Packed dimensions, actual weight, volumetric weight and chargeable shipping weight.
- Itemized inbound handling, inspection, packaging, storage, outbound handling, international shipping and any mandatory taxes or customs charges. Please distinguish supplier purchase costs from your fulfillment costs.
- Inspection scope and fees for photos confirming the correct part, finish, fitment identifiers, complete contents, mounting accessories and absence of visible damage.
- A protective-packaging proposal for glossy plastic parts and the long spoiler.
- Processing time after warehouse receipt and realistic transit times to France, shown separately from the supplier's delivery time to your warehouse.
- Available France shipping routes and local carriers, full international tracking and last-mile tracking.
- Whether taxes/customs can be prepaid so the recipient has no unexpected collection charges, including the process for shipments above EUR 150. Please explain the setup and pricing applicable to supplier-owned inventory.
- Written loss, damage, wrong-item and return terms specifically applicable to Customer-Direct Orders.

Our store is custom-built with a React frontend and Python backend. Please provide your current Open API documentation, access/eligibility requirements, test environment if available, and tracking/status notification documentation. We need fulfillment submission to happen only after our manual approval; importing a customer order must not automatically trigger procurement or shipping.

At this stage, this is a quotation request only. We are not authorizing purchases, shipments, wallet funding, subscriptions or any paid commitment.

Thank you,
TYMotors

## Déroulement du pilote

1. Connexion effectuée dans le compte HyperSKU ; profil de contact et questionnaire commercial enregistrés.
2. Demande transmise dans le chat du compte et assignée à Chloe. Obtenir une réponse humaine et vérifier que le devis porte bien sur nos produits fournisseurs externes.
3. Obtenir le devis détaillé et les instructions d'arrivée pour les trois références. Demander aussi au vendeur Alibaba son prix unitaire et son coût d'envoi jusqu'à cet entrepôt.
4. Calculer le coût total réel par référence : achat fournisseur + transport intérieur Chine + réception/contrôle/emballage + transport France + taxes/frais applicables.
5. Après choix du budget et de l'adresse par l'utilisateur, commander les échantillons ; enregistrer les dates réelles de chaque étape.
6. Vérifier à réception la bonne référence, l'état des pièces, l'emballage, le suivi transporteur et la facture finale avant de décider de l'intégration.

## Résultats à renseigner après le test

| Référence | Coût total | Arrivée entrepôt | Contrôle et photos | Remise transporteur | Livraison France | État à réception |
| --- | --- | --- | --- | --- | --- | --- |
| bmw-g20-mirror-caps | À confirmer | Non testé | Non testé | Non testé | Non testé | Non testé |
| bmw-g20-gloss-black-grille | À confirmer | Non testé | Non testé | Non testé | Non testé | Non testé |
| bmw-g20-m-performance-spoiler | À confirmer | Non testé | Non testé | Non testé | Non testé | Non testé |

## État technique constaté localement

Le workflow existant gère la validation manuelle et les étapes fournisseur/agent. La migration `20261011221114_supplier_fulfillment_workflow.sql` utilise encore `CJdropshipping` comme fournisseur d'agent par défaut et `not_connected` comme état initial. La sélection commerciale de HyperSKU ne vaut pas connexion technique : ce défaut n'a pas été modifié et aucune migration n'a été appliquée pendant cette préparation.

### Préparation de l'admin le 12 octobre

- Le prestataire logistique est désormais éditable par commande dans le code local ; le lien vers l'espace HyperSKU ou CJ suit le nom renseigné. Les anciens prestataires sont conservés, aucune connexion API n'est simulée.
- Le champ privé `exact_source_url`, déjà accepté par le backend, est exposé dans l'éditeur produit avec validation HTTPS côté serveur.
- Une action explicite récupère uniquement les liens manquants d'une commande depuis les fiches produits. Elle ne modifie ni les liens existants ni les coûts, ne valide pas la commande et ne lance aucun achat.
- La récupération est réservée aux administrateurs, avec contrôle de concurrence, et refusée après validation, achat, expédition, annulation ou remboursement.
- Migration additive locale : `20261012042643_supplier_link_refresh.sql`. Elle doit être publiée avant le backend/frontend utilisant la nouvelle action ; elle n'a pas encore été appliquée aux projets hébergés.
- Contrôles locaux : 153 tests API, 47 contrôles PostgreSQL/PGlite, lint frontend, 6 tests frontend et build de production réussis.
- Navigateur isolé : prestataire HyperSKU et état « Configuration en cours » enregistrés, lien exact enregistré depuis l'éditeur produit. La fenêtre native de confirmation de récupération a bloqué l'onglet d'automatisation ; le parcours complet de ce bouton reste à retester. L'appel HTTP local réel de récupération a ajouté une référence, sans achat, sans validation et sans événement client supplémentaire ; résultat affiché dans une nouvelle vue de l'admin. Preuve : `assets/hypersku-admin-local.png` à la racine du workspace.

Contrôle distant en lecture seule : le catalogue de staging contient 41 produits, dont 8 liens exacts renseignés. Le dossier fournisseur sans lien observé en production correspond à `[TEST STAGING] Validation Stripe`, et non à une référence automobile réelle. Ne pas lui attribuer arbitrairement un lien fournisseur ni effectuer d'achat.

L'accès Open API est annoncé par HyperSKU, mais les URL d'API, les identifiants, les webhooks, le contrat de données et l'éligibilité de notre compte doivent être obtenus avant de programmer l'adaptateur réel.

## Sources officielles consultées le 12 octobre 2026

- Contact commercial : https://www.hypersku.com/contact-us/
- Réception des produits achetés chez ses propres fournisseurs : https://support.hypersku.com/en/customer-direct-order-handling-fee
- Fonctionnement général et Open API : https://support.hypersku.com/en/articles/2941652-what-s-hypersku-how-to-sign-up-and-get-started
- Fulfillment : https://www.hypersku.com/fulfillment/

Le tarif d'entrée publié de 0,15 USD/unité ne représente pas le prix total du service. Le devis doit confirmer son application à chaque référence, notamment aux ensembles de plusieurs pièces.
