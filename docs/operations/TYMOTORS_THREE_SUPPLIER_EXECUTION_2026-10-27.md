# Exécution recentrée sur les trois fournisseurs initiaux

Instruction du propriétaire : écarter l'étape de confirmation/certification photo
et poursuivre les autres travaux. Périmètre : **Tianzhiyu, Soyintech/Soyin,
GZTM Auto/Leju**. HyperSKU est distinct, pour sourcing/fulfillment selon les
services accessibles. Les autres boutiques ne sont pas des fournisseurs choisis.

## Changements exécutés

La génération privée des40dossiers suit désormais cette instruction par défaut :
aucune nouvelle démarche photo, aucun IMAGE_RIGHTS dans la file de travail,
statut DEFERRED_BY_OWNER. Les réponses, références et liens des autres boutiques
sont conservés en historique, séparés des actions d'approvisionnement courantes.
Les fichiers images, prix publics, design, panier, checkout et SQL restent intacts.
Les refus explicites historiques ne sont ni transformés en accords ni annulés.

Les compteurs distinguent maintenant3partenaires initiaux et les rattachements
article/offre restant à confirmer : le chiffre0de ces rattachements ne signifie
pas « aucun fournisseur de départ ». --historical-scope permet seulement de
reproduire l'ancien plan ; il n'est plus le défaut pour les nouvelles exécutions.

## Travail sur les références et les coûts

| Élément | Résultat vérifié dans les preuves disponibles |
|---|---|
| Articles |40identifiants uniques et5pilotes conservés |
| Soyin |18articles avec SKU nommé ;10autres lignes sans SKU ;1article absent de la demande29lignes |
| GZTM/Leju |8anciennes annonces conservées comme références candidates, pas des SKU fabricant confirmés |
| Rapprochement combiné |20articles uniques, dont6communs aux deux ensembles ; les20autres sans référence nommée dans ces preuves |
| Tianzhiyu |Partenaire initial conservé ; identité primaire et rattachements précis non retrouvés dans les fichiers examinés |
| Prix fournisseur / portFrance / marge |Inconnus ; aucun coût de test réutilisé pour une vente réelle |

Matrice de travail effective : `procurement-matrix-40.json`, dans le dossier privé
`backend/data/phoenix-2026-10-27-three-original-suppliers-v2/`. Elle associe chaque
article à ses références Soyin/GZTM disponibles et aux informations manquantes.
Les coûts, devises et marges restent null tant qu'ils ne sont pas connus.

## Cinq références prioritaires

| Article | SKU proposé Soyin | Vérifications suivantes, sans étape photo |
|---|---|---|
| Spoiler F30 |EXBWB3022|Déclaration PP/F30 2013–2018 ; variante/coffre/fixations et écart de plage d'années à résoudre |
| Coques F30/F32 |MR3BF2021|Forme/options, plages selon châssis, remplacement/surcoque, côtés et unité vendue |
| Spoiler G20 |EXBWB2021|Déclaration G20/G28 Sport 2019+ ; variante, coffre, fixations ; ne pas étendre au G21 |
| Coques W205 |MR3AW20507|Déclaration W205 2015–2018 ; phase/options, construction, côtés/unité |
| Coques Golf7 |MR3DGF703|Clarifier le libellé fournisseur «14–16 Molk7 Lamando», phase/options et unité |

Pour ces cinq lignes : compléter prix/devise, unité/MOQ, stock, validité, poids et
dimensions emballés, préparation, portFrance/Incoterm/délai, garantie/retour, puis
référence et coût HyperSKU. Les cinq pièces ne sont pas présentées comme déjà
commercialisables. Un catalogue ou une référence candidate ne confirme pas le
montage de la variante réellement vendue.

## Sources et contrôles

Sources : `continuation/soyin-29-review.json` (classeur reçu23octobre),
`product_supplier_image_manifest.json` (8références GZTM, uniquement ses champs
produit/vendeur/annonce utilisés), dossiers du27octobre et catalogue public lu une
fois pendant ce lot. La génération v2 réutilise exactement les prix et leur date
de cette lecture, sans nouvel appel réseau ; première sortie pré-renommage gardée.

Recherche mail récente sur les trois noms : aucune réponse entrante nouvelle
trouvée depuis09:05UTC. Ce constat ne couvre pas les chats Alibaba. Aucun message
supplémentaire envoyé, vendeur alternatif choisi, devis accepté ou achat engagé.

Contrôles ciblés Chef et indépendant :73tests dossiers PASS. Audit indépendant du
code/projection puis fichiers v2/matrice APPROVED LOCAL. Chef :2009tests backend
PASS en19,77s ; un avertissement Starlette/httpx préexistant, aucune dépendance
changée. Sources historiques de restrictions non assimilées à des confirmations
des trois partenaires.

Empreintes finales contrôlées indépendamment :

- Dossiers JSON : `5FE97435009599986C3F17EB14790D8EF2E4ABF889694A1A34FD270F81A44328`.
- Dossiers Markdown : `4ABA8BC96FCCDFA01A14E71E3555822B37971DD91E55AF9C81462699D1F41A02`.
- Matrice : `56BCEFEE10826FDA64E020AC41D9A1321B4E455C207787F6BD3F6E64C47D11FE`.
