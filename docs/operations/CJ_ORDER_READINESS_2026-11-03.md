# CJ — correspondances exactes et dossier de préparation

## Périmètre livré

Ce lot ajoute une **lecture des correspondances et une préparation bloquée**, pas une transmission de commande CJ. Aucun endpoint d'achat/paiement n'est appelé, aucun produit n'est activé, aucune donnée commerciale n'est inventée.

- `GET /api/admin/integrations/cj/status` ne compte plus les connexions de tous les magasins comme celles de TYMotors. `CJ_SHOP_ID` identifie le magasin cible. Sans cette configuration, la réponse authentifiée donne les magasins autorisés (id/nom seulement) et indique `shop_not_configured`.
- `GET /api/admin/products/{uuid}/cj-connection` vérifie le produit exact dans ce magasin, puis compare le SKU plateforme au SKU TYMotors. Une correspondance d'identifiants n'est jamais une validation commerciale.
- `GET /api/admin/orders/{uuid}/cj-readiness` lit la commande et son dossier fournisseur existant, rapproche les lignes et fournit les blocages détaillés ainsi qu'une empreinte stable. Aucun nouvel ordre ni dossier fournisseur n'est créé par cette lecture.
- Les commandes internes de test/diagnostic sont exclues des appels CJ. Les contrôles administrateur restent obligatoires sur les trois routes.
- Tous les départs de requêtes CJ réelles sont espacés d'au moins1 seconde, avec un budget global de30 secondes par contrôle. Une réponse429 arrête tout le lot, sans relance ni résultat partiellement validé. Le garde est partagé par processus ; une architecture à plusieurs workers devra disposer d'une limitation distribuée avant activation. Le Procfile actuel utilise un seul worker Uvicorn.
- Une empreinte identique permet de reconnaître un dossier identique ; elle **ne garantit pas l'idempotence d'un futur envoi externe**. Aucun envoi n'est implémenté dans ce lot.

## Contrat de correspondance

Le catalogue actuel représente chaque variante commercialisée par une fiche et un SKU. Pour éviter toute association par similarité :

| Champ CJ | Valeur TYMotors attendue pour le candidat MR3BF2021 |
| --- | --- |
| Magasin | Magasin API existant « Backend TYMotors », nom non public TYMotors ; ID exact à enregistrer depuis le résultat authentifié |
| `platformProductId` | `e46bf5e1-d459-44ca-b28d-70c01c5c14e7` |
| `platformVariantId` | `TY-BMW-F30-F32-MIRROR-CAPS` |
| Référence fournisseur candidate | `MR3BF2021` — Soyintech, 16 USD/paire proposés |
| `cjProductId` / `cjVariantId` / `cjSku` | Non communiqués, à obtenir après approbation CJ du produit de service exact |

Les UUID/SKU ont été lus dans la base de production le 3 novembre. Le produit est brouillon, stock0 et non vérifié. Contrôle global au même instant :40 brouillons,0 actif. Ces identifiants internes ne démontrent pas une compatibilité F30/F32 ni une variante fournisseur équivalente.

Le 3 novembre, le compte CJ connecté affiche le magasin Backend TYMotors autorisé/activé. Le ticket `T202610311023101331` reste en attente de la réponse CJ après notre mise à jour de15:20:19 (heure affichée par CJ). Pas de nouvelle relance identique envoyée pendant ce lot. Recherche Gmail des messages CJ/Soyintech du jour : aucun nouveau message par rapport au suivi déjà consigné.

## Blocages conservés

1. Réponse fournisseur ciblée : finition/paire exacte, montage et exclusions, stock, emballage par paire et envoi à CJ. La demande Nicy déjà envoyée `1a1a1c71ffc6b8d2` reste la référence ; ne pas la répéter sans nouvelle information.
2. Produit de service/variante CJ et liaison exacte au magasin. Une connexion API authentifiée ne remplace pas ces données.
3. Devis France à l'unité et coûts complets. Les138 USD Soyintech concernent les cinq articles groupés.
4. Devise d'achat et conversion : le modèle historique conserve des cents mais aucune devise fournisseur distincte ; ne pas convertir implicitement le prix USD en EUR ni annoncer une marge confirmée.
5. Approbation financière figée sur montant/devise/version du devis, puis transmission persistante et rapprochement après timeout : à implémenter dans le lot de transmission, sans affaiblir le garde fournisseur existant. Aucun renvoi aveugle ne sera acceptable.
6. L'adresse Stripe peut omettre la région française. Le dossier signale `cj_shipping_province_required`, sans inventer de région ; CJ exige actuellement `shippingProvince` dans le contrat de création de commande.

## Références officielles

- [Magasins et connexions produit/variante](https://developers.cjdropshipping.com/en/api/api2/api/shop.html) : seule la lecture des connexions existantes est utilisée.
- [Authentification CJ](https://developers.cjdropshipping.com/en/api/api2/api/auth.html) : clé et jeton côté serveur, quota documenté1 requête/seconde.
- [Création de commande CJ](https://developers.cjdropshipping.com/en/api/api2/api/shopping.html) : `payType=3` crée sans paiement. Cet endpoint n'est pas appelé dans ce lot. Une future création nécessite les identifiants vérifiés et une traçabilité persistante.

## Validation et reprise

Audit indépendant : préparation en lecture seule approuvée, transmission réelle non validée. Aucun changement frontend, CSS, image, prix public ou migration SQL dans ce lot. Les tests utilisent uniquement des fixtures et transports simulés ; ils ne prouvent pas une réception de commande chez CJ.

Validation finale locale : `python -m pytest -q` — **494 tests réussis** ; `git diff --check` sans erreur. L'auditeur indépendant a également exécuté les13 tests spécifiques CJ après correction429. Un avertissement de dépréciation Starlette/httpx subsiste dans l'outillage de test, sans échec. Branche dédiée `codex/cj-order-readiness` ; aucune publication production dans ce lot.

Prochaine étape utile : récupérer les IDs exacts et les données unitaires confirmées, enregistrer `CJ_SHOP_ID`, vérifier le rapprochement sur le produit réel, puis construire la transmission avec approbation et journal d'idempotence. Ne pas réutiliser l'article gratuit interne comme produit fournisseur.
