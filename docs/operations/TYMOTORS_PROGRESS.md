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

## Reprise

1. Après connexion du compte Stripe réel, vérifier `livemode=true` et identifier sans ambiguïté le compte TYMotors ; configurer les clés et le webhook uniquement dans les secrets de l'hébergeur.
2. Obtenir des fournisseurs la variante exacte, les restrictions de montage, le prix, la disponibilité et le devis de livraison France pour au moins un pilote. Ne pas activer un brouillon sans ces preuves.
3. Compléter les informations du vendeur encore vides dans la configuration publique.
4. Activer une référence vérifiée, effectuer un paiement réel contrôlé puis vérifier commande, attribution fournisseur, expédition et suivi. Aucun paiement réel n'a encore été exécuté.
