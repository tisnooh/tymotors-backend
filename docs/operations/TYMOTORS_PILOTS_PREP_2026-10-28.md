# TYMotors — préparation locale des cinq fiches pilotes

## Résultat réel et périmètre

Les cinq fiches pilotes et leurs données d'import **privées** ont été générées dans :

`C:/Users/utilisateur/Documents/ChatGPT/TyMotors/backend/data/phoenix-2026-10-28-pilots-prep-v1/`

- `pilots-5.json` : cinq fiches, textes conservés, preuves candidates, restrictions/inconnues, prévisualisations et gabarits d'import.
- `PILOTS.md` : lecture humaine des cinq fiches et des données restant à renseigner.

Aucun import, message fournisseur, achat, prix public, image, design, DB ou publication modifié. Aucun pilote déclaré commercialement vérifié. L'examen des photos reste différé suivant la consigne du propriétaire, sans autorisation nouvelle déduite.

## Réutilisation de l'existant

La sélection `PILOTS` et les trois partenaires `ORIGINAL_SUPPLIERS` viennent de `app/commerce_dossiers.py`. Les titres, sous-titres et descriptions viennent des copies déjà relues dans les dossiers v4 : **pas de nouvelle réécriture ni de patch éditorial gratuit**. Les prévisualisations utilisent les contrats existants `VariantInput`, `OfferInput` et `ShippingRateInput`, pas une nouvelle structure concurrente d'administration.

Seules les données utiles aux cinq pilotes sont exportées. Aucun nouveau commerçant ou canal d'approvisionnement n'est introduit.

## Cinq préparations, références toujours candidates

| Pilote | SKU Soyin proposé, non retenu | Déclaration de matière du candidat | Cellule de référence |
|---|---|---|---|
| Spoiler de coffre style PSM F30 | EXBWB3022 | PP | Sheet1!D9 |
| Coques F30/F32 | MR3BF2021 | ABS | Sheet1!D8 |
| Spoiler G20 | EXBWB2021 | ABS | Sheet1!D12 |
| Coques W205 | MR3AW20507 | ABS | Sheet1!D16 |
| Coques Golf 7 | MR3DGF703 | ABS | Sheet1!D30 |

Les références retenues, variantes retenues et UUID fournisseurs restent `null`. Les déclarations de matière/montage sont séparées des caractéristiques du produit réellement approvisionné, qui restent non confirmées.

Restrictions/questions séparées : coffre/fixations et années du F30 ; plages distinctes et références/options des miroirs BMW ; limite finale/phase de G20-G28 ; rétroviseurs/phase W205 ; libellé Soyin « 14-16 Molk 7 Lamando » et phase Golf. Une extension non prouvée n'est jamais transformée en incompatibilité certaine. Aucune règle de compatibilité réelle n'est créée.

## Portée exacte des données d'import

### Variante interne — prévisualisation valide en draft seulement

Les cinq objets passent `VariantInput`. Ils conservent l'UUID produit et le SKU interne observés, le texte déjà relu et le montant du prix public **historique** sans le modifier ni le réapprouver. Ils imposent `status=draft`, `is_verified=false`, `is_default=false`, `stock=0`, `compatibility_ids=[]`, attributs vides et aucune preuve technique d'activation.

Ce stock 0 est une protection du brouillon, **pas une observation de disponibilité fournisseur**. Tous les exports ont `import_allowed=false`. Avant un éventuel import ultérieur autorisé, contrôler les variantes/SKU existants pour éviter les doublons ; aucun UUID de variante n'est fabriqué ici.

### Offre et transport — gabarits volontairement incomplets

Les cinq offres et cinq tarifs restent invalides pour leurs contrats tant que les preuves manquent. Le moteur expose les champs réellement manquants plutôt que d'inventer un fournisseur, une variante, un MOQ de 1, une devise, un taux de change, une disponibilité, une zone postale universelle ou un port gratuit.

Restent notamment inconnus : unité commerciale/paire/kit et finition, contenu/fixations, prix/devise/MOQ/paliers/validité/stock, conditionnement, préparation, port et délai direct France, Incoterm, taxes/frais, garantie/retours et responsable opérationnel. Les montants/taxes restent `null`, pas zéro. Aucun coût rendu ni marge n'est calculé.

Le pays FR est un scénario de préparation de livraison directe, **pas une confirmation de desserte ni une commande**. Le fichier exporté n'est ni un import fournisseur/HyperSKU certifié ni un moyen d'envoi automatique.

## Preuves et fraîcheur

- Dossiers source : `backend/data/phoenix-2026-10-28-direct-shipping-v4/dossiers-40.json`, observation du catalogue le 27 octobre, pas une nouvelle lecture de production le 28.
- Réponse Soyin : `backend/data/catalogue-review-2026-10-23/continuation/soyin-29-review.json`, message `1a167fe0fcb52ea0`, reçu le 23 octobre à 09:00:54 UTC.
- Pièce jointe originale : SHA-256 `ac70277b31bf826e3e04bea04a29bf6581612225101000c003c0e459a2df198a`.
- Le JSON exporté conserve dates, cellules D/E/F par article, empreintes canoniques des sources et SHA-256 des fichiers effectivement lus. Ces empreintes prouvent la traçabilité des entrées, pas une approbation commerciale.

Le moteur refuse une sélection dérivée, un UUID/SKU/cellule incohérent, des doublons, un changement du périmètre des trois partenaires, un article déjà approuvé/actif ou l'apparition de coûts confirmés qui nécessiterait une nouvelle revue. Les dates d'observation/réponse ne peuvent être postérieures à la préparation.

## Fichiers de ce lot

- `app/commerce_pilot_preparation.py` : projection pure, contrôlée et sans mutation des entrées.
- `scripts/prepare_commercial_pilots.py` : lecture de fichiers uniquement ; sortie dans un dossier neuf ; pas d'option live/import/envoi.
- `tests/test_commerce_pilot_preparation.py` : 36 nouveaux tests légers.
- Ce rapport ; les deux artefacts privés générés ci-dessus. Aucun autre code applicatif modifié.

## Exécution et vérifications

Commande exécutée depuis `scp-release/backend` :

```powershell
C:/Users/utilisateur/Documents/ChatGPT/TyMotors/backend/.venv/Scripts/python.exe -m scripts.prepare_commercial_pilots --dossiers C:/Users/utilisateur/Documents/ChatGPT/TyMotors/backend/data/phoenix-2026-10-28-direct-shipping-v4/dossiers-40.json --soyin C:/Users/utilisateur/Documents/ChatGPT/TyMotors/backend/data/catalogue-review-2026-10-23/continuation/soyin-29-review.json --output C:/Users/utilisateur/Documents/ChatGPT/TyMotors/backend/data/phoenix-2026-10-28-pilots-prep-v1
```

Résultat : 5 fiches, 5 previews de variantes draft, 5 gabarits d'offres incomplets, 5 gabarits de transport incomplets, **0 import et 0 pilote vérifié**. Le répertoire v1 ne doit pas être réutilisé pour écraser l'historique ; prendre un nouveau nom lors d'une prochaine préparation.

Tests exécutés :

```powershell
C:/Users/utilisateur/Documents/ChatGPT/TyMotors/backend/.venv/Scripts/python.exe -m pytest tests/test_commerce_pilot_preparation.py tests/test_commerce_dossiers.py tests/test_catalogue_copy_policy.py -q -p no:cacheprovider
```

**139 tests réussis en 2,25 secondes**, dont les 36 nouveaux : modèles existants, aucune mutation/prix inventé, indépendance des données candidates, dates/identités/cellules, absence d'extension de compatibilité, coûts inconnus, CLI sans réseau et refus d'écrasement.

Cette préparation est terminée localement. Les réponses commerciales et restrictions exactes manquantes restent à traiter séparément ; aucune validation, dépense ou mise en ligne n'est obtenue par le simple fait que les cinq dossiers sont prêts pour revue.
