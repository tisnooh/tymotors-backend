# Chaîne de commande isolée — périmètre et recette

Branche dédiée `codex/commerce-workflows`. Aucun changement de design, frontend, photo ou prix public. Aucun déploiement, migration hébergée, achat, email ou commande fournisseur réelle.

## Corrections raccordées

La commande préparée depuis un devis possède déjà ses lignes et références figées. Le nouveau service de paiement de test utilise la tentative persistante et sa clé d'idempotence : un seul claim SQL avant appel SDK ; refus des clés live ; aucun nouveau débit après timeout ou résultat inconnu. La récupération active d'une session inconnue reste à implémenter ; il n'y a pas de retry automatique au-delà de la rétention de clé Stripe.

Le webhook existant vérifie la signature sur le corps brut et le mode avant d'aiguiller les événements de devis vers la transaction dédiée. Le validateur pur contrôle session/tentative/commande, montants/devise, expiration, paiement et destination. Les événements completed non payés attendent l'événement async_payment_succeeded ; ni la page de succès ni le navigateur ne déclarent un paiement.

La transaction `commerce_settle_test_checkout` journalise les événements, lie une session à une tentative, sérialise l'identité PaymentIntent et refuse son réemploi sur une autre commande. Deux types d'événements pour le même paiement ne créent pas deux tâches. Le statut financier est enregistré depuis les instantanés, sans catalogue/panier vivant obligatoire. L'adresse divergente conserve le paiement mais n'autorise aucune tâche d'expédition. Le panier n'est pas effacé : une modification ultérieure ne doit pas être perdue.

Les tâches fictives conservent le SKU fournisseur, variante, fournisseur, agent, tarif et conditions historiques. Les identifiants métiers historiques ne sont pas des clés étrangères vers des lignes actuelles supprimables : supprimer un ancien tarif après le départ au paiement ne doit pas faire échouer un paiement reçu. Aucun fournisseur alternatif n'est substitué. Le plan distingue montant d'achat en devise originale et acquisition/logistique converties en EUR telles que figées dans le devis ; il ne reconvertit pas avec un taux actuel.

La table réelle `supplier_orders` reste inaccessible aux commandes test. Les tâches dans `commerce_test_tasks` ne possèdent aucun mécanisme d'envoi externe. La simulation administrative suit prepared → received_by_agent → quality_checked → shipped → delivered, avec identifiant de suivi préfixé `SIM-`, journal unique par étape et contrôle de l'ordre attendu. Une commande annulée, remboursée ou non payée bloque la suite. Les événements visibles portent explicitement la mention Simulation et passent par le suivi client existant, sans nouveau composant graphique.

## Routes privées

- `GET /api/admin/commerce/orders/{id}/fulfillment-plan` : plan exact depuis les snapshots ; coûts privés, administrateur uniquement. Le plan ne prouve pas que la commande est payée et ne donne aucune autorisation d'achat.
- `POST /api/admin/commerce/test-tasks/{id}/simulate` : mode test et administrateur, état attendu, état suivant et suivi SIM facultatif. Aucun transporteur contacté.
- L'adaptateur SDK de création de session n'est pas exposé comme nouveau checkout public. Les variantes restent protégées dans le checkout client tant que le vrai test sandbox et les preuves commerciales ne sont pas terminés.

## Exécution reproductible

```powershell
python -m pytest -q
python -m tests.run_commerce_pipeline --node <chemin-vers-node>
```

Installer explicitement les dépendances verrouillées avant le second test : `npm ci --prefix tools/sql-tests --ignore-scripts --no-audit --no-fund`. Le runner refuse des ports déjà occupés, démarre uniquement ses processus loopback et les arrête dans un finally, même en cas d'erreur. Le job CI ajouté utilise la même recette ; aucun résultat GitHub n'est revendiqué avant publication et exécution effective.

Le test HTTP utilise le vrai backend et PostgreSQL/PGlite jetable, un transport Stripe **FAKE**, et la vraie vérification de signature du SDK avec un secret local synthétique. Il couvre cinq variantes synthétiques distinctes d'un seul produit et un seul fournisseur/agent, pas cinq produits réels ni une chaîne multifournisseur certifiée. Sont aussi testés : paiement différé, replay exact et deux événements du même paiement, montant/source figés après changement de tarif, suppression du tarif et du panier après claim, adresse divergente, annulation avant traitement, réutilisation intercommande d'un PaymentIntent, refus d'étape sautée et suivi client sans coûts privés. Aucun stock réel n'est décrémenté.

Résultats du 24 octobre : **984 tests Python backend PASS** (une dépréciation Starlette/httpx préexistante), **410 assertions du runner PASS** sur une base fraîche et arrêt de ses processus confirmé. Revue indépendante : **37 tests ciblés et 406 assertions du runner PASS**, avant ajout des quatre assertions dédiées aux statuts remboursé et remboursement partiel ; ces quatre assertions supplémentaires passent dans les 410 du contrôle principal. Les 66 assertions historiques de chargement SQL passent aussi. Ces suites se recoupent : ne pas les additionner en cas uniques. Le job GitHub est préparé, pas exécuté à distance.

## Limites bloquantes explicites

- Le connecteur Stripe refuse actuellement l'accès sans liaison de compte exploitable ; aucune clé de test n'a été trouvée aux emplacements de configuration locale prévus. Aucun vrai paiement sandbox exécuté. Connexion d'un environnement isolé demandée à l'administrateur sans partage de clé dans le chat.
- PGlite vérifie les transactions PostgreSQL mais pas la contention multiconnexion, GoTrue/PostgREST hébergés ou la durabilité disque en production.
- Les remboursements de commandes issues de devis sont refusés explicitement et journalisés pour traitement, pas acquittés silencieusement ou transmis au calcul legacy. Le rapprochement/remboursement dédié reste à réaliser ; aucun remboursement externe lancé.
- Les réservations de test restent conservatrices : même après paiement, elles restent held. La transition consumed/released et la réconciliation des paiements inconnus restent nécessaires avant activation ; ne jamais les réutiliser comme stock réel.
- Le suivi SIM n'est pas un transporteur réel. Attribution externe, coûts/logistique réels, droits photo, références/compatibilités et garanties des cinq articles pilotes restent non confirmés.

## Dossiers commerciaux

`python -m scripts.build_commercial_dossiers --source <dossier-audit> --output <nouveau-dossier> --live` reconstruit les 40 dossiers privés sans modifier leurs sources. Une seule lecture de l'API publique fournit les prix datés. Le JSON contient identité/SKU, candidats distincts du fournisseur sélectionné, agent inconnu, variante inconnue, droits, descriptions proposées, coûts/marges nulls lorsque non prouvés, sources et blocages A Codex/B fournisseur/C administrateur. Le script refuse un ensemble partiel ou une dérive d'identité, ne remplace pas un ancien rapport et n'importe aucune proposition Soyin en offre validée.
