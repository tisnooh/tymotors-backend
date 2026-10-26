# TYMotors — fournisseurs et décision avant ouverture

## Autorisation et résultat de ce cycle

Le propriétaire a demandé de traiter les étapes « fournisseurs » et « avant
l'ouverture ». Cela permet la qualification et les demandes de confirmation sans
engagement. Ce n'est pas une autorisation d'inventer un devis, d'accepter un
contrat, d'acheter, de changer les prix/photos ou de mettre en service une chaîne
encore non validée.

**Décision du Chef : BLOCKED pour l'ouverture commerciale des cinq pilotes.**
Leur examen a été réalisé, mais aucun ne satisfait les critères d'approbation.
Le mandat du propriétaire ne remplace pas les preuves externes manquantes.

## Contrôle actuel du catalogue

Le générateur existant `scripts.build_commercial_dossiers --live` a effectué
une seule lecture de l'API publique le **26 octobre à20:28:25 UTC**. Aucune
écriture de catalogue ou base, image téléchargée/modifiée, migration ou commande.

-40 articles observés,40 en `draft` ; cinq pilotes toujours `is_verified=false`.
- Prix actuels des cinq relus ci-dessous, inchangés par rapport au25 octobre.
- Les permissions, montages et conditions fournisseurs conservent leurs dates
  historiques : relire un prix ne transforme pas ces éléments en preuve récente.
- Sur les preuves disponibles :0 pilote approuvé,0 marge pilote calculable,
  aucun fournisseur/variante retenu confirmé et aucun mapping HyperSKU confirmé.

Dossier privé neuf, sans écraser le précédent :
`C:/Users/utilisateur/Documents/ChatGPT/TyMotors/backend/data/phoenix-2026-10-26-prelaunch/`.
Il contient `dossiers-40.json`, `DOSSIERS.md` et `prelaunch-review.json`.
SHA-256 du `dossiers-40.json` :
`565FD7D753EF460317041F4E6E796776468F78506C99FFB2B97C6A74F0F2FE31`.
SHA-256 du manifeste `prelaunch-review.json` :
`5EE7E3F454E69078D8D8FD17E09E58DB63B43D3BD1729771C7333F0E0F1AFE8B`.

## Décision par pilote

Les références Soyin restent des **propositions non retenues**. Les prix ci-dessous
sont des prix boutique observés, pas des prix d'achat ni des marges approuvées.

| Pilote | Prix boutique observé | Proposition Soyin | Restriction à résoudre | Coût rendu / marge | Décision |
|---|---:|---|---|---|---|
| Spoiler F30 |129€|EXBWB3022, ligne9|2013–2018 proposé contre2013–2019 archivé ; coffre, finition PSM/noir/carbone et fixations ; pas de F31 par extension|Inconnus|BLOCKED|
| Coques F30/F32 |69€|MR3BF2021, ligne8|Châssis/années différenciés, forme/options du rétroviseur, paire, remplacement ou surcoque|Inconnus|BLOCKED|
| Spoiler G20 |149€|EXBWB2021, ligne12|G20/G28 Sport2019+ proposé contre2019–2021 archivé ; lien produit absent de cette ligne ; coffre/fixation, pas de G21|Inconnus|BLOCKED|
| Coques W205 |79€|MR3AW20507, ligne16|2015–2018 proposé contre source Redzini2014–2021 ; équivalence et équipements inconnus ; pas d'extension W213/W222/GLC|Inconnus|BLOCKED|
| Coques Golf7 |69€|MR3DGF703, ligne30|«14–16 Molk7 Lamando» ambigu contre source Mk7/Mk7.5 2013–2019 ; ne pas normaliser sans réponse ; construction/équipements|Inconnus|BLOCKED|

Identifiants stables et sources ligne/cellule conservés dans le JSON privé.
Pièce jointe Soyin reçue23octobre09:00:54UTC, message `1a167fe0fcb52ea0`,
SHA-256 `ac70277b31bf826e3e04bea04a29bf6581612225101000c003c0e459a2df198a`.
Les déclarations PP/ABS et modèles du classeur ne prouvent pas l'identité des
pièces actuellement présentées. Une variante Shopify n'est pas un SKU fabricant.

## Fournisseurs : quatre relances réellement envoyées

Avant envoi : recherche Gmail incluant les spams, vérification des fils et des
derniers sortants. Les demandes à ces quatre interlocuteurs dataient du23octobre ;
aucune nouvelle réponse de qualification dans les fils relus. Les quatre relances
sont ciblées sur les cinq pilotes, pas une nouvelle campagne vers les40 articles.

| Fournisseur | Pilotes couverts | ID envoyé | Heure UTC26octobre | Fil existant |
|---|---|---|---|---|
| Soyin / Nicy |Les cinq|`1a179e352659c92b`|20:25:03|`1a1621f1af2501cc`|
| GZTM / Jade |Les trois BMW|`1a179e35f2dc1d2b`|20:25:06|`1a167d80286bd1a3`|
| Redzini |Coques W205|`1a179e371859b9b6`|20:25:10|`1a1626de129ceb32`|
| JL Styling |Coques Golf7|`1a179e37bb11a899`|20:25:13|`1a1639c9a5fc93b4`|

Chaque message a été relu individuellement : label SENT, destinataire, fil,
In-Reply-To et contenu intégral correspondent au message préparé. Cela prouve
l'envoi Gmail, **pas la livraison, la lecture ou l'accord du fournisseur**.
Quatre messages couvrent cinq articles et dix couples candidat/article ; ce ne
sont pas dix produits validés. Aucun total historique «37+4» n'est présumé.

Demandes : SKU/variante exacts et identité par rapport à la source, montage et
exclusions, droits précis des fichiers, prix/devise/MOQ/stock/validité, poids/colis,
transport et termes de taxes/douane, délais/suivi, garantie et retours. Scénario
de devis **hypothétique d'une unité de vente complète, zone75001 France**, pas
un achat, une quantité promise ni un tarif validé pour toute la France.

Les droits éventuellement accordés sur de nouvelles photos du fournisseur ne
licencient pas implicitement les images actuelles ou celles d'un autre vendeur.
Aucune modification ou substitution de photographie n'est autorisée par ce lot.
Le refus SCP est respecté, aucune nouvelle sollicitation SCP. VEVOR n'est pas
relancé sur sa référence arrêtée ; son rappel automatique n'est pas une preuve
de disponibilité. HyperSKU n'a pas été relancé une deuxième fois aujourd'hui :
message08:31 déjà envoyé, aucune réponse technique reçue dans le fil relu.

## Conditions de passage avant ouverture

| Contrôle | Responsable | État / preuve attendue |
|---|---|---|
| Fournisseur/variante/montage |Fournisseur + Chef|Réponse par SKU, options/exclusions et preuves, puis rapprochement exact ; aucun substitut accepté|
| Images actuelles |Titulaire des droits + Chef|Autorisation écrite liée aux fichiers et dérivés réellement présents ; droits des logos distincts|
| Coût/marge |Fournisseur/HyperSKU + administrateur|Devis daté, port et taxes/frais complets, régime fiscal et critère de marge ; inconnu ≠ zéro|
| Stock/garantie/retours |Fournisseur + administrateur|Conditions applicables à la variante et au canal France, coûts et gestion des incidents|
| Agent/HyperSKU |Administrateur + HyperSKU|Responsable réel et canal/mapping confirmés ; pas de fausse commande pour le prouver|
| Paiement/commande |Codex|Rapprochement/remboursements quoted et recette hébergée restant à traiter ; le test sandbox positif ne valide pas tous les cas|
| Publication |Administrateur + Chef|Références et marge approuvables sur preuves, contrôles critiques passés, validation de mise en service ; aucun déploiement dans ce cycle|

La vérification a donc abouti à une **non-approbation motivée**, pas à une
activation prématurée. Aucun paiement live, achat fournisseur ou engagement.

## Contrôle indépendant et reprise

**APPROVED — examen et traçabilité uniquement**, après contrôle indépendant.
L'ouverture des cinq pilotes reste **BLOCKED**. Le Chef accepte la qualité du
contrôle, pas une commercialisation sans preuves.

-40 dossiers et cinq correspondances exactes ID/slug/SKU/prix/proposition Soyin.
- Coûts/marges à `null` (inconnus), aucun fournisseur retenu ni droit/mapping validé.
- Quatre messages relus indépendamment dans Gmail : SENT, destinataires, fils,
  horaires et In-Reply-To comparés aux quatre parents réels ; aucune incohérence.
- Scénario75001 et unité de devis hypothétiques, aucun client/achat/engagement.
- SHA-256 du JSON source vérifié, modifications du checkout limitées aux documents.
- **66 tests dossiers/pricing PASS**,4,83s ; contrôle direct du manifeste PASS :
  cinq identités/prix, quatre contacts vérifiés, dix couples et refus d'approbation
  non justifiée. Diffcheck sans erreur. Aucun nouveau test Stripe réel dans ce cycle.

La revue a demandé une précision rédactionnelle : « coûts nuls » pouvait signifier
zéro. Corrigé ci-dessous ; les JSON conservaient déjà `null`, jamais un coût gratuit.

À la reprise : lire les quatre fils avant toute relance ; traiter seulement les
réponses nouvelles, joindre chaque preuve au bon article/variante, laisser les
champs de coûts manquants à `null` (inconnus, jamais zéro) et calculer les marges
uniquement une fois leur base confirmée.
Pas de surveillance en arrière-plan ou nouvel envoi permanent installé.
