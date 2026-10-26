# Pont client — sandbox uniquement

État du25octobre2026 : implémenté localement, pas déployé. Le parcours graphique
client et la vente réelle restent bloqués. Aucun changement de design/photo/prix.

## Contrat

1. `GET /api/products/{product_uuid}/variants` retourne les identités sélectionnables
   actives/vérifiées du produit, sans donnée fournisseur ou preuve privée. Une
   réponse vide ou plusieurs choix ne sélectionnent jamais une finition par défaut.
2. L'ajout existant `POST /api/cart` reçoit le `variant_id` exact et le véhicule
   complet. Le serveur garde l'autorité sur compatibilité, stock, quantité/prix.
3. `POST /api/cart/quote` reçoit une destination exacte, un mode existant et un
   UUID `request_key`. Ni adresse fictive, ni prix/livraison de secours ne sont
   admissibles pour une commande client. Le retour est une projection publique
   immuable, pas une réservation ni une preuve de paiement.
4. `POST /api/cart/quote/{quote_uuid}/checkout` accepte SEULEMENT
   `{"request_key":"UUID"}`. Le propriétaire vient du Bearer authentifié et de sa
   session Auth active, ou de la capacité invité `X-Session-Id`. Une authentification
   invalide ne retombe jamais sur l'invité. Aucun `user_id`/acteur/admin fourni par
   le client n'est accepté.
5. Les nouvelles RPC propriétaires sont réservées au backend `service_role`.
   Session, propriétaire, devis, sources, droits, destination et réservations sont
   revérifiés avant claim. Le verrou commun au panier refuse deux achats en cours
   pour deux devis différents, indépendamment du jeton de retry navigateur.
6. L'appel fournisseur intervient APRÈS persistance de la clé et des paramètres.
   Une reprise liée relit la même session ; création en cours/issue inconnue impose
   inspection et garde les holds. Aucune rotation de clé, annulation aveugle ou
   nouveau paiement pour contourner un timeout.
7. Réponse publique : `order_id`, `order_number`, `quote_id`, `status`, `is_test`, `url` ;
   `session_id` est également présent pour open/awaiting_webhook.
   `open` peut retourner uniquement l'URL HTTPS Stripe de la session test liée.
   `awaiting_webhook` ne fournit pas d'URL : lecture fournisseur payée mais règlement
   local absent. `paid` retourne un reçu sans URL seulement après règlement local.
8. Seul le webhook signé vérifié peut régler le paiement ; le retour navigateur
   et le GET fournisseur ne sont jamais utilisés comme événements financiers.
   Le GET existant `/api/checkout-session/{session_id}` sait lire la liaison
   test avant réception du webhook, après contrôle du propriétaire : il retourne
   alors `paid:false`. Il ne crée, ne récupère chez Stripe ni ne règle rien.
9. Les tâches agents et préparations HyperSKU restent INTERNES et explicitement
   test/simulées. Aucun achat, transmission HyperSKU, frais ou expédition réels.

## Limites connues

- Accord reçu pour le formulaire livraison uniquement. Cart collecte désormais
  l'adresse France en mémoire, sans envoi sur frappe. Le calcul explicite appelle
  `/api/cart/delivery-options` en lecture seule ; seuls les modes passant tous les
  contrôles du moteur existant sont proposés. La confirmation persiste le devis
  exact avant le checkout propriétaire. Aucun tarif ni coût manquant par défaut.
  Recette navigateur et paiement Stripe réseau restent des preuves distinctes.
- Les produits à plusieurs variantes attendent également un choix explicite ;
  aucun sélecteur nouveau n'est ajouté sans accord.
- L'ajout frontend contrôle la variante, les faits véhicule normalisés et une
  quantité couvrant l'incrément par rapport au dernier panier reçu. Une réponse
  incohérente ne déclenche ni succès, ni retry/rollback aveugle. Cela ne constitue
  pas une preuve unique de commit face à des écritures simultanées d'autres onglets.
- Les lignes d'un panier déjà payées ne sont jamais supprimées automatiquement.
  Un nouveau devis contenant encore leurs identifiants est refusé. L'utilisateur
  doit les retirer explicitement avant un nouvel achat ; les nouveaux IDs disjoints
  peuvent être traités. Une situation remboursée/ambiguë reste en revue.
- Les preuves locales PGlite ne démontrent ni concurrence PostgreSQL multiconnexions,
  ni Auth GoTrue/PostgREST réels. Une migration hébergée n'est pas autorisée ici.
- Aucun produit réel n'est validé commercialement par ces tests synthétiques.
- Le live est matériellement refusé. Aucun flag légal ou activation manuelle d'un
  produit ne suffit à ouvrir ce parcours.

## Recette reproductible, sans production

Une publication future exige une approbation distincte et une recette de staging :
migration additive transactionnelle, backend avec les nouveaux endpoints, puis
frontend. Déployer seulement le frontend ferait refuser les ajouts faute de route
variantes ; ce refus doit rester fermé, jamais basculer sur l'ancien checkout.
Le client authentifié doit être testé avec GoTrue/PostgREST réels isolés avant
activation ; les identités de la probe locale sont synthétiques.

Utiliser Python du venv et le Node existant. Exécuter séquentiellement les runners
qui possèdent les ports8765/8766 ; ils refusent un processus déjà présent et ne
terminent que leurs propres enfants.

```powershell
& 'C:/Users/utilisateur/Documents/ChatGPT/TyMotors/backend/.venv/Scripts/python.exe' -m pytest tests/test_commerce_customer_checkout.py tests/test_commerce_customer_checkout_api.py tests/test_commerce_public_variants.py tests/test_quote_checkout_eligibility.py -q
& 'C:/Users/utilisateur/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node.exe' tests/commerce_customer_database.mjs
& 'C:/Users/utilisateur/Documents/ChatGPT/TyMotors/backend/.venv/Scripts/python.exe' -m tests.run_commerce_pipeline --node 'C:/Users/utilisateur/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node.exe' --probe-module tests.commerce_customer_http_probe
```

Le dernier scénario utilise un transport Stripe **FAKE** et un événement synthétique
signé localement. Ce n'est pas un paiement Stripe réseau. Le runner opt-in
`tests.run_stripe_sandbox --customer` peut exercer la vraie sandbox CLI isolée,
avec secrets exclusivement hors dépôt et rapports privés. Il exige un navigateur
fonctionnel, une carte de test et un vrai webhook reçu ; ne jamais présenter un
simple Checkout ouvert comme un test réussi. Il n'est pas lancé si le navigateur
ne permet pas de terminer/contrôler la session.
