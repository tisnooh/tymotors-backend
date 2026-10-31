# TYMotors — point de reprise du 31 octobre 2026

Objectif actif : ouvrir de vraies commandes avec Stripe en mode réel et une offre fournisseur vérifiée. Le design et les photographies ne sont pas modifiés.

## Vérifié en production

- `/api/site-config` : `stripe_mode=test`, `legal_ready=false`, `test_catalog_available=false`.
- Catalogue public : 40 brouillons, zéro stock positif, zéro article achetable.
- Base Supabase « Tymotors Paris » : 41 lignes produit, dont une référence de recette archivée. Aucun article commercial n'est `active`. Sur les 40 articles du catalogue, aucune offre fournisseur n'est marquée vérifiée, aucun prix d'achat ni frais de livraison fournisseur ne sont renseignés.
- Les cinq pilotes F30/G20/W205/Golf 7 sont toujours brouillons. Leurs références fournisseur exactes, prix, livraison et compatibilités restent à confirmer. Trois fiches pointent vers GZTM en base alors que le dossier de recherche propose Soyintech ; cette divergence ne doit pas être tranchée sans preuve.
- Le connecteur Stripe expose deux comptes TYMotors en mode test et aucun contexte `livemode=true` au dernier contrôle.

## Changements publiés et testés

- Les brouillons restent visibles, sans panier ni paiement de démonstration.
- Le checkout public refuse toute tentative tant que Stripe réel n'est pas configuré ; un produit actif sans disponibilité serveur reste non achetable dans l'interface.
- Le checkout réel exige une compatibilité confirmée et une offre fournisseur vérifiée avec référence, coût d'achat et coût de livraison avant de créer une session de paiement.
- Backend : 411 tests réussis pour le dernier correctif. Frontend : tests ciblés réussis et compilation locale réussie. Les derniers contrôles CI frontend échouent à l'audit de dépendances nouvellement signalées ; ne pas déclarer ce contrôle vert.

## CJdropshipping — vérification du 31 octobre 2026

- Compte TYMotors CJ `CJ4321861` : **Wazza Lu** est affiché comme agent personnel actif jusqu'au **30 novembre 2026**. La [commande de service CJ `FF2116477129008095232`](https://www.cjdropshipping.com/mine/agents/serviceOrders) est « en cours », pour **0 $ sur 30 jours**. Ce montant couvre l'affectation de l'agent ; les frais par commande, le transport, les retours et l'éventuelle suite après 30 jours ne sont pas confirmés. Aucun achat de pièce, expédition ou abonnement payant n'a été lancé.
- Le formulaire de détails de ce service a été enregistré le 31 octobre à 13:54, avec les trois fournisseurs Alibaba existants, une demande de traitement à l'unité et l'exigence d'un devis écrit avant toute étape payante.
- Message envoyé à Wazza dans le [chat officiel CJ](https://chat.cjdropshipping.com/?touser=Wazza%20Lou) pour demander la réception à l'unité, le contrôle, les coûts et la procédure de liaison au site. Leah Cheng a répondu que l'équipe vérifierait et répondrait dans le ticket. Le [ticket `T202610311023101331`](https://www.cjdropshipping.com/mine/ticket) reste en attente de réponse au dernier contrôle. Le prénom/nom apparaît aussi comme « Wazza Lou » dans le chat et le courriel CJ ; utiliser l'identifiant de service pour éviter toute ambiguïté.
- Dans le compte CJ, « Produits de la boutique » indique **aucun produit connecté** et « 3PL Fulfillment > Produits » indique **aucun produit de service**. L'agent humain est affecté au compte CJ, mais **aucune commande TYMotors n'est transmise automatiquement à CJ**. Le champ `agent_connection_status` du site doit rester `not_connected` ; ne jamais y copier le numéro de commande du service agent comme s'il s'agissait d'une commande client CJ.
- La [documentation officielle CJ](https://developers.cjdropshipping.com/en/api/start/development.html) prévoit une clé API, un jeton côté serveur, la liaison des variantes et une recette sandbox. Le mode « Store Order Flow » ne rend pas un SKU exploitable sans liaison à un article CJ ; une commande non reliée arrive dans les commandes invalides. Pour les pièces Alibaba existantes, attendre de CJ la confirmation du traitement 3PL, des coûts et des références exactes avant toute commande réelle.
- Correctif local frontend : valeur par défaut du prestataire alignée sur `CJdropshipping` (comme le backend) et lien d'administration vers le vrai espace 3PL CJ. Aucun changement du design ni des images. **Pas encore publié.**
- Suite du 31 octobre : une clé « Backend TYMotors » a été créée et apparaît **activée** dans l'onglet API CJ. L'utilisateur a enregistré `CJ_API_KEY` dans l'environnement Render ; sa présence, son préfixe `CJ4` et sa longueur de 46 caractères ont été vérifiés dans l'interface Render sans afficher la valeur. Le shell Render n'est pas disponible sur l'offre gratuite. Le backend possède localement un contrôle administrateur `GET /admin/integrations/cj/status` : il distingue `not_configured`, `api_authenticated`, `rejected` et `unavailable`, sans renvoyer le jeton. **Ce code n'est pas publié et l'authentification réelle auprès de CJ n'a pas été testée.** La clé enregistrée ne prouve ni son fonctionnement à l'exécution, ni le mapping des SKU, ni la capacité d'expédition.
- Vérification locale du code CJ : **416 tests backend réussis**. Le schéma OpenAPI du backend en ligne ne contient pas `/api/admin/integrations/cj/status` au dernier contrôle ; l'absence de publication est donc confirmée.

## Reprise

1. Après connexion du compte Stripe réel, vérifier `livemode=true` et identifier sans ambiguïté le compte TYMotors ; configurer les clés et le webhook uniquement dans les secrets de l'hébergeur.
2. Obtenir des fournisseurs la variante exacte, les restrictions de montage, le prix, la disponibilité et le devis de livraison France pour au moins un pilote. Ne pas activer un brouillon sans ces preuves.
3. Compléter les informations du vendeur encore vides dans la configuration publique.
4. Activer une référence vérifiée, effectuer un paiement réel contrôlé puis vérifier commande, attribution fournisseur, expédition et suivi. Aucun paiement réel n'a encore été exécuté.
5. Obtenir la réponse écrite de CJ sur l'acceptation des colis Alibaba à l'unité et un devis complet France ; identifier cinq SKU pilotes exacts et leur mapping CJ. La clé API est créée et enregistrée côté Render, mais son authentification doit encore être vérifiée après publication autorisée du contrôle administrateur, suivie d'un test sandbox. Toute transmission payante reste soumise à validation humaine. L'affectation de Wazza seule ne remplace aucune de ces étapes.
