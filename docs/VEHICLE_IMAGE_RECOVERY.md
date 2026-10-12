# Visuels de personnalisation — vérification du 12 octobre 2026

Les 14 compositions existantes sont conservées, sans nouvelle génération ni changement du design. Les fichiers originaux se trouvent dans `../assets/vehicle-sources/`, les compositions dans `../assets/vehicle-finals/` depuis la racine du dépôt backend. Leur manifeste est `data/vehicle_image_manifest.json`.

Le site public utilise `https://tymotors-backend-eu.onrender.com`, pas l'ancien service staging suspendu. Son endpoint `/api/compatibility` fournit les 14 images par marque/modèle/génération. Les 14 ressources Cloudinary ont répondu HTTP 200. Le chargement navigateur de la BMW Série 3 G20 a été confirmé (1600 × 900).

| Véhicule | Génération | Fichier de composition | Droits enregistrés |
| --- | --- | --- | --- |
| BMW Série 3 | F30 / F35 | bmw-serie-3-f30-f35-configurator.png | À vérifier |
| BMW Série 3 | G20 | bmw-serie-3-g20-configurator.png | CC BY-SA |
| BMW Série 4 | F32 / F36 | bmw-serie-4-f32-f36-configurator.png | À vérifier |
| Audi A3 | 8V | audi-a3-8v-configurator.png | À vérifier |
| Audi A4 | B9 | audi-a4-b9-configurator.png | À vérifier |
| Mercedes-Benz Classe A | W177 | mercedes-classe-a-w177-configurator.png | Source utilisateur, à vérifier |
| Mercedes-Benz Classe C | W205 | mercedes-classe-c-w205-configurator.png | CC BY-SA |
| Volkswagen Golf 7 | GTI | volkswagen-golf-7-gti-configurator.png | À vérifier |
| Volkswagen Golf 7 | R | volkswagen-golf-7-r-configurator.png | CC BY-SA |
| Porsche 911 | 991 | porsche-911-991-configurator.png | CC BY-SA |
| Porsche 911 | 992 | porsche-911-992-configurator.png | À vérifier |
| Porsche Cayenne | 9YA | porsche-cayenne-9ya-configurator.png | CC BY |
| Toyota GR Supra | A90 | toyota-gr-supra-a90-configurator.png | À vérifier |
| Toyota GR Yaris | XP210 | toyota-gr-yaris-xp210-configurator.png | CC BY-SA |

Les indications de droits sont celles du manifeste et de la base : elles ne constituent pas une nouvelle validation juridique ni une vérification actuelle de l'attribution complète. Les huit visuels `REQUIRES_MANUAL_REVIEW` n'ont pas été requalifiés en `APPROVED`.

Les anciens modèles BMW mal encodés `s-rie-3` et `s-rie-4` sont déjà inactifs et ne sont pas exposés par l'API publique. Aucun enregistrement n'a été supprimé ou réactivé.

Les zones interactives ne sont affichées que lorsqu'un produit actif possède une compatibilité exacte et vérifiée. Une image de véhicule disponible ne suffit pas à autoriser une zone ou une compatibilité ; aucune référence produit n'a été inventée.
