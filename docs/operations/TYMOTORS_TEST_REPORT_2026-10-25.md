# TYMotors — recette après push

Contrôle du25octobre2026, terminé vers05:45UTC.
Backend testé : `b627091c219a3d9c5252d1aea137a3cdedf61351`, branche
`codex/commerce-workflows`. Frontend : `c3f06c18`, inchangé.
Demande : vérifier si un client peut commander puis recevoir sa commande.

## Verdict

**NON VALIDÉ pour le parcours commercial réel.** Les contrôles backend et la
chaîne synthétique passent, mais l'interface client n'est pas raccordée au
nouveau workflow de variantes/devis/paiement. Aucun paiement Stripe achevé ni
expédition réelle n'est prouvé par cette recette.

## Preuves recueillies pendant cette exécution

| Contrôle | Résultat actuel | Portée |
|---|---|---|
| Suite Python, contre-exécution indépendante |1298 PASS, zéro échec,375,68s ; avertissement Starlette/httpx préexistant | Backend local, transports simulés |
| Parcours HTTP/SQL complet |557 assertions PASS, cinq pilotes synthétiques | Base PGlite et serveur loopback jetables ; Stripe FAKE ; signature par SDK réel et secret local synthétique |
| Paiement redirigé / tâche annulée / paiement réutilisé | Cas bloqués selon le rapport HTTP | Aucune autorisation de débit, achat ou expédition réelle |
| Site public | HTTP200, page d'accueil observée dans le navigateur | Disponibilité seulement, pas un achat terminé |
| API publique | `https://tymotors-backend-eu.onrender.com/api/health` →200 `{"status":"ok"}` | Connexion serveur/base pour cette lecture ; pas toute la vente |
| Bundle réellement servi | `https://tymotors.vercel.app/static/js/main.122b2188.js` contient `/create-checkout-session`, pas `/cart/quote` | Le parcours client servi reste le checkout historique |
| OpenAPI réellement servi | `/api/cart/quote`, provider-observation et simulation-status absents | Le lot de la branche poussée n'est pas exposé sur le serveur public observé |
| Auth sandbox Stripe | CLI whoami : profil `tymotors-phoenix-isolated`, compte `acct_1UU8fq7oQBUfbTTb`, clé test disponible, aucune clé live | Authentification seulement, aucun paiement |
| Navigateur | Inventaire et accueil lisibles, puis ouverture de fiche et récupération d'onglet en timeout | Recette UI/Checkout suspendue ; aucune nouvelle session ou carte soumise |

Le premier lancement du runner HTTP a expiré à l'initialisation des fixtures,
avant les assertions métier. Après la fin de pytest, une seule reprise
séquentielle a réussi557 contrôles. La santé de la fixture a été lue200 en0,58s.
La cause exacte du premier retard n'est pas démontrée ; ne pas le masquer par
le résultat de reprise ni l'attribuer avec certitude à une régression métier.

## Première frontière client cassée

Revue indépendante et lecture chef des sources actuelles :

1. `frontend/src/pages/ProductDetail.jsx:306` et`:323`, ainsi que
   `frontend/src/pages/customize/ProjectBuilder.jsx:103`, ajoutent le produit sans
   identifiant de variante précis. Le plumbing optionnel de variante existe,
   mais les actions client ne l'utilisent pas.
2. Aucun appel au devis `/cart/quote` dans l'interface actuelle.
3. `frontend/src/pages/Cart.jsx:32` appelle Checkout.create ;
   `frontend/src/lib/api.js:102` poste vers le checkout historique.
4. Un panier à variantes conserve livraison/total inconnus et paiement
   indisponible ; Cart.jsx:26 respecte ce refus. Le devis nouveau ne donne pas
   d'autorisation de payer ; préparation de commande/tentative limitée à l'admin.
5. Le lot local verrouille le live ; un push sur la branche de travail n'est
   pas une autorisation de publier ou d'activer les ventes.

Arrêt de la vérification publique à cette frontière : pas de contournement
des refus, pas de paiement réel pour « tester », pas de commande HyperSKU.

## Actions nécessaires

- **Codex** : raccorder les actions existantes à la variante exacte, au devis
  serveur et à un chemin de paiement autorisé et testé, sans changer l'apparence.
  Traiter séparément journal/rapprochement/remboursements quoted et concurrence.
- **Recette** : rétablir le navigateur puis terminer un Checkout isolé avec
  carte Stripe de test, webhook authentique, commande unique et attribution.
  La disponibilité de la clé ne remplace pas cette preuve.
- **Fournisseurs / HyperSKU** : confirmer SKU, compatibilités, droits, prix,
  livraison et mapping ; zéro produit réel validé sur les40 dossiers et zéro
  des cinq pilotes commerciaux approuvé selon le dernier suivi.
- **Publication** : revue et autorisation distinctes avant migrations ou
  déploiement. Aucune production modifiée pendant ces tests.

Ce rapport n'effectue aucune correction de code. Les photographies, prix,
couleurs, mises en page et fonctionnalités publiques sont restés inchangés pendant la
recette. Aucun message fournisseur, achat, paiement réel ou déploiement.
