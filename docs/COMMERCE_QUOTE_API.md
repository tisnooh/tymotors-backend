# Devis persistants — API locale, sans paiement

Ce lot n'active aucun article réel, ne réserve aucun stock, ne crée aucune session Stripe et n'envoie aucune commande fournisseur. Le gate du checkout variantes reste en place. Les photographies et le frontend ne sont pas modifiés.

## Parcours et frontières

1. `POST /api/cart/quote` reçoit uniquement une clé de demande UUID, une destination complète et un mode. L'identité vient de la session Supabase vérifiée ou de `X-Session-Id`, jamais du JSON client.
2. Le panier existant est recherché sans en créer un vide. Le contexte privé est capturé par RPC : lignes, variantes, compatibilités, offres, tarifs, responsables et fournisseurs.
3. Le calcul Python réutilise le moteur de compatibilité et les termes vérifiés. Chaque ligne conserve son véhicule. Les lignes d'une même variante sont regroupées pour les MOQ, le stock et le port. Plusieurs variantes d'un même fournisseur exigent une politique explicite `independent_parcels` sur chaque tarif retenu ; un regroupement logistique supposé n'est pas autorisé.
4. La sauvegarde SQL recapture les sources dans une transaction courte. Tout changement, y compris une nouvelle règle régionale, refuse la sauvegarde. Les sommes sont vérifiées indépendamment en base. Aucune requête réseau ne s'exécute sous ces verrous.
5. `GET /api/cart/quote/{id}` ne renvoie qu'un devis du panier appartenant à l'appelant. Le rattachement d'un panier invité à un compte ne transfère pas implicitement ses anciens devis : il faut en demander un nouveau sous la nouvelle identité.
6. `POST /api/admin/commerce/quotes/{id}/prepare-test-order` est réservé à un administrateur, uniquement en mode test. Le RPC recontrôle propriétaire, sources et expiration puis crée une commande **pending/unpaid/is_test**, une seule fois par devis. Les associations fournisseur/référence/variante/tarif/responsable sont conservées dans des instantanés privés immuables. Aucun paiement ni mouvement de stock.

## Contrat public

Entrée :

```json
{
  "request_key": "UUID unique pour cette demande",
  "mode": "tracked",
  "destination": {
    "name": "Destinataire",
    "line1": "Adresse",
    "line2": "",
    "city": "Ville",
    "state": "",
    "postal_code": "75001",
    "country": "FR",
    "phone": ""
  }
}
```

L'adresse est validée structurellement seulement : ni géocodage, ni validation de desserte par un transporteur ne sont revendiqués. Le tarif doit déjà couvrir destination, préfixe postal, quantité et mode. Pays non pris en charge, code postal vide ou coûts/taxes inconnus = refus, pas de forfait de secours.

Sortie : identifiant, statut et expiration du devis, monnaie EUR, sous-total/port/taxes incluses/total en centimes, lignes commerciales publiques. `checkout_available` vaut toujours `false` et `requires_revalidation` toujours `true` dans ce lot. `ready` signifie que l'instantané a été accepté et n'est pas expiré/supplanté/consommé, **pas** que le catalogue n'a plus changé ni que le paiement est autorisé.

Les évaluations privées, prix d'achat, marges, références fournisseur, URLs de preuves, responsables et adresse complète ne sont pas renvoyés. La politique existante de refus d'images est réappliquée à la projection d'un ancien instantané sans modifier la photographie source ni l'historique.

## Reprise et refus

- Même clé, même panier, même adresse/mode : restauration du devis d'origine, pas de recalcul silencieux de ses prix. Un instantané expiré ou supplanté reste marqué comme tel.
- Même clé avec adresse ou mode différent : HTTP409 `request_key_conflict`.
- Nouvelle clé : nouvelle évaluation complète ; les anciens devis prêts du panier deviennent supplantés après sauvegarde réussie.
- Sources modifiées pendant le calcul : HTTP409, nouvelle demande explicite nécessaire. Aucune boucle de retry opaque.
- Plafonds : 100 lignes, 20 unités par ligne, 2 000 par groupe de variante ; montants finaux jusqu'à 2 milliards de centimes. Bornes de données exactes côté SQL, jamais de troncature silencieuse.
- Limiteur complémentaire actuel : 20 requêtes par panier/heure, mémoire de processus bornée. Ce n'est pas un limiteur distribué et il ne remplace pas les règles d'accès de la base.
- Historique privé : tables avec RLS et accès service uniquement ; les fonctions ne sont pas exécutables par `anon`/`authenticated`. La préparation test vérifie aussi le rôle administrateur côté SQL.

## Vérifications et limites avant activation

Les suites Python, PostgreSQL jetable et le probe HTTP utilisent exclusivement des produits, preuves et utilisateurs synthétiques. Le probe traverse FastAPI et le pont SQL local ; il ne valide ni GoTrue, ni PostgREST hébergé, ni Stripe sandbox.

La suite finale de paiement doit encore implémenter puis tester : réservation concurrente, paramètres Stripe persistants et idempotents, vérification du montant/de la monnaie/de la destination, webhooks signés et répétés, paiement asynchrone, expiration et reprise, allocation fournisseur et tâches de traitement autorisées. Le test de concurrence PostgreSQL multiconnexion et la recette sandbox réelle restent nécessaires. Aucun de ces prérequis ne peut être remplacé par la réussite de cette suite locale.

Les 40 articles existants restent soumis aux preuves fournisseurs, licences, données légales et conditions logistiques réelles. Ce lot ne leur donne aucune validation commerciale.
