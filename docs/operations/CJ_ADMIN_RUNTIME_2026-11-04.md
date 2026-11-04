# Recette administrateur connectée — 4 novembre 2026

Contrôle réalisé après reconnexion du propriétaire dans le navigateur intégré, sur la production publiée. Aucun mot de passe, jeton ou clé lu, copié ou demandé.

## Résultats observés

- Le tableau de bord authentifié s'ouvre. Les commandes historiques de test portent explicitement la mention TEST ; les indicateurs commerciaux restent à zéro.
- Paramètres → « Tester la connexion Stripe » : **Clé Stripe authentifiée sur le compte attendu**, compte `acct_1Tc9tvJB6441TWWo`. Aucun nouveau paiement ni diagnostic gratuit créé pendant ce contrôle.
- Paramètres → « Vérifier les produits CJ » : **Clé CJ authentifiée. Liaison des produits CJ impossible à vérifier pour le moment.** Cette réponse ne prouve ni zéro produit lié ni une correspondance exploitable.
- Côté CJ connecté, API Stores affiche une boutique **Backend TYMotors**, nom interne TYMotors, **Autorisée** et **Activée**. L'identifiant de magasin n'est pas affiché sur cette table ; il ne doit pas être déduit du nom.
- La commande de test existante `TY-20261030-EFFC043A` s'ouvre avec « Commande de test : Paiement sandbox uniquement. Aucun stock réel consommé, aucun dossier fournisseur ni expédition déclenchés. » Le panneau d'envoi CJ n'est pas proposé pour cet essai. Aucune donnée de commande modifiée.

## Anomalie à corriger

Le diagnostic CJ ne distingue pas une erreur HTTP, un refus de l'API magasins et une réponse produits mal formée. Le message actuellement visible est insuffisant pour résoudre la liaison. Correctif ciblé préparé : remonter seulement l'étape, le statut HTTP, le code numérique CJ et l'identifiant de requête filtré ; ne jamais exposer message brut, token, en-tête ou contenu fournisseur. Les libellés de magasin non configuré/non autorisé sont aussi complétés dans le panneau existant.

## Validation et point de reprise

- Branches backend et frontend : `codex/cj-probe-diagnostics`. Aucune migration ni configuration de production modifiée dans ce lot. Versions publiées précédentes : backend `7c2a046`, frontend `646583b`.
- Contrôle local final : **527 tests backend réussis**, dont17 tests de l'adaptateur CJ ; **10 tests Operations frontend réussis**. Lint vérifié par l'agent frontend ; diff sans erreur. La CI et la compilation de la branche sont à vérifier avant publication.
- La revue indépendante initiale a demandé l'alignement du contrat frontend/backend et le filtrage des secrets connus dans les noms/identifiants de boutique. Ces corrections sont appliquées, avec tests supplémentaires. La revue indépendante finale n'a pas pu se terminer : les sous-agents ont rencontré leur limite d'utilisation. Aucune approbation finale indépendante n'est revendiquée et aucune tentative de contournement effectuée.
- **Reprise après disponibilité rétablie : revue indépendante finale APPROVED** sur backend `ef4149c` et frontend `a3be2a1`. L'auditeur a relu les diffs corrigés et exécuté17 tests backend et10 tests frontend. Le diagnostic est approuvé pour publication ; la variante réelle CJ et la livraison ne sont pas validées par cette revue. Backend PR#10 : CI réussie, dont SQL et contrôles des secrets. Frontend PR#9 :512 tests et compilation CI réussis (run41824528402), secrets et préversion Vercel réussis.
- Reprendre par la revue des diffs exacts puis les résultats CI. Après validation du lot, publier backend puis frontend et relancer **une seule fois** le contrôle CJ depuis l'administration connectée. Lire le diagnostic de l'étape `shops` ou `connections`, son statut HTTP, son code CJ et son request ID filtré. La documentation officielle utilise bien GET `/shop/getShops` et GET `/product/conn/connection` ; ne pas inventer un autre endpoint ni un identifiant de magasin.
- Si CJ renvoie un refus ou un incident prestataire, transmettre le diagnostic non secret dans le ticket existant `T202610311023101331`. Ne pas réitérer la demande commerciale déjà envoyée, ni activer un produit ou créer un achat.

## Limites

La référence de variante CJ approuvée et le devis unitaire restent attendus. Le contrôle authentifié ne crée aucune commande CJ et ne remplace pas la recette d'un brouillon réellement reçu chez le prestataire. Design, photographies, prix et statut des produits restent inchangés.
