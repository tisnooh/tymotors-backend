# TYMotors — consigne de reprise exécutable

Objectif : rendre la boutique capable de recevoir une vraie commande et de la faire livrer par CJ, sans modifier le design, les photos ou les prix publics. Ne jamais déclarer une intégration terminée sur la seule présence d'une clé API ou d'un bouton.

À chaque reprise :

1. Vérifier l'état du dépôt, les déploiements Render/Vercel et les réponses Soyintech, GZTM et CJ déjà reçues. Éviter les demandes en double.
2. Vérifier sur CJ la boutique autorisée, les produits de service approuvés et les liaisons exactes TYMotors SKU/variante ↔ CJ produit/variante. Sans correspondance vérifiée, conserver le statut non connecté.
3. Pour chaque pilote, exiger variante et compatibilité, disponibilité, prix d'achat, poids emballé, coût de traitement CJ et devis de livraison France à l'unité. Conserver la preuve et sa date. Ne pas convertir le devis groupé Soyintech en tarif unitaire.
4. Préparer l'activation d'une fiche seulement quand les gardes catalogue et les informations vendeur sont satisfaits. Ne pas créer de faux stock, de référence CJ ou de donnée légale.
5. Tester en environnement isolé puis, quand les données et autorisations sont réunies, contrôler le flux réel : paiement Stripe signé → une commande → dossier fournisseur → attribution agent/CJ → expédition → suivi. Aucun achat fournisseur ou paiement réel sans instruction explicite sur son montant.
6. Après chaque modification technique : exécuter les tests pertinents, vérifier le diff et le déploiement séparément, puis inscrire la preuve et le blocage résiduel dans `TYMOTORS_PROGRESS.md`.

État de référence au 2 novembre 2026 : Stripe réel configuré, boutique API CJ autorisée, Wazza affecté et contacté, cinq références Soyintech candidates. Zéro variante CJ liée, zéro offre fournisseur complète, quarante articles en brouillon sans stock et configuration légale encore vide. La vente ne peut pas être ouverte par un simple changement de statut.
