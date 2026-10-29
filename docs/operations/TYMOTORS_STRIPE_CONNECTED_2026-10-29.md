# Stripe connecté — contrôle réel du 29 octobre 2026

## Accès et périmètre

Contrôle effectué vers 20:51 UTC avec le connecteur Stripe authentifié et le
connecteur Supabase, en lecture seule. Le sandbox TYMotors est identifié comme
`acct_1Tc9uQJPkDEK6Dal`, `livemode=false`. Il est distinct du sandbox temporaire
CLI historique `acct_1UU8fq7oQBUfbTTb`. Aucune histoire de paiement n'est déplacée.
Les nouvelles connexions ont remplacé le précédent blocage UNAUTHORIZED pour ce
sandbox. Aucun accès au compte t_fx n'est utilisé pour TYMotors.

## Webhook existant et rapprochement

- Une destination v1 enregistrée, activée, en test :
  `we_1TuRuwJPkDEK6DalaYLsAIQ5`.
- URL : `https://tymotors-backend-eu.onrender.com/api/stripe/webhook`.
- API de la destination : `2026-04-22.dahlia`.
- Les neuf événements enregistrés couvrent les succès Checkout immédiats et
  différés, échecs/expiration, échec de PaymentIntent et notifications de refund.
- Les cinq derniers événements Checkout réussis interrogés sont `paid`, en test,
  avec `pending_webhooks=0`. Les cinq événements existent dans `stripe_events`
  avec `status=completed`, sans erreur. Les cinq commandes associées existent
  dans `orders`, avec `payment_status=paid`, `is_test=true` et
  `fulfillment_status=requires_review`.

| Événement Stripe | Commande TYMotors |
| --- | --- |
| evt_1UUnMAJPkDEK6DalPrLby7vI | TY-20261026-71ACCBC2 |
| evt_1UUnKJJPkDEK6Daljlj7Sx4G | TY-20261026-45003EA5 |
| evt_1UURPZJPkDEK6DalwwkxQzhI | TY-20261025-A9385112 |
| evt_1UTiJnJPkDEK6DalThTVaW9M | TY-20261023-29CEFD0F |
| evt_1UQMgtJPkDEK6DalB6J2crUO | TY-20261014-FDF06769 |

Ce sont cinq commandes historiques, pas cinq références pilotes approuvées.
Aucun nouveau paiement n'a été créé pour produire ce rapprochement.

La recherche des livraisons non réussies pour les huit types Checkout/refund
interrogés renvoie un ancien `checkout.session.expired` :
`evt_1UQ0rDJPkDEK6DaliGwIecnF`, `pending_webhooks=1`, tandis que son journal
TYMotors est déjà `completed` depuis le 13 octobre. Ces deux observations sont
conservées ; aucune nouvelle livraison n'est déclenchée et aucun doublon n'est
créé pour tenter de rendre les compteurs identiques.

## Correctif de compatibilité des événements

Les événements lus par l'API Stripe comportent `context` égal au compte direct.
La documentation officielle définit ce champ comme contexte d'authentification,
distinct du champ `account` d'un compte connecté :
https://docs.stripe.com/api/events/object

Cela ne prouve pas que le corps exact d'une ancienne livraison contenait ce
champ. En revanche, le nouveau validateur local le refusait systématiquement,
comme le service métier et le receiver historique. Correction :

- Profil explicite : accepter un contexte absent ou exactement égal au compte
  serveur attendu, après vérification HMAC du corps brut et du mode.
- Refuser tout champ `account` (Connect hors périmètre), contexte étranger,
  organisation, chemin, valeur nulle ou type incorrect.
- Receiver historique : ajouter `STRIPE_LEGACY_ACCOUNT_ID`, sans inférence depuis
  les métadonnées, une clé courante ou un autre sandbox. La valeur vide conserve
  le refus des événements contenant un contexte.
- Réutiliser la même garde au niveau HTTP et métier. Aucun effet base sur les
  contextes invalides.

Les tests signent des événements synthétiques avec le vrai SDK, sans secret
Stripe réel. Le rapport indépendant séparé compte 66 contre-tests et 226 tests
combinés réussis, APPROVED LOCAL. La recette SQL/HTTP et la suite globale sont
consignées dans PROGRESS après leur exécution par le Chef.

## Écart avec la version hébergée

Lecture du registre de migrations de `Tymotors Paris` : dernière version
`20261013063630` (`sandbox_catalog_orders`). Les migrations du nouveau parcours
par compte/profil du 29 octobre ne sont pas appliquées sur cette base, et ses
tables de paiement/traitement par contexte n'y existent pas. Le paiement
historique testé ne démontre donc pas l'exécution hébergée du nouveau parcours.

Le sandbox retourne `charges_enabled=false`, `payouts_enabled=false`,
`details_submitted=false`. Ces valeurs concernent le sandbox interrogé ; aucune
conclusion automatique sur les droits d'encaissement du compte réel n'en est
déduite. Le formulaire d'activation du compte parent observé précédemment reste
une observation distincte, pas une validation de sa forme juridique.

Lecture supplémentaire du compte parent `acct_1Tc9tvJB6441TWWo` avec sa propre
connexion, qui n'expose ici qu'un contexte de test : mêmes trois indicateurs
`false`, `business_type=null`, capacités vides et motif
`requirements.pending_verification`. Les listes de champs requis retournées sont
vides ; aucune exigence précise (SIRET, document ou autre) n'est inventée à partir
de ce résultat. Aucun accès en mode live n'est listé par ces connexions.

## Actions restant nécessaires

1. Configurer l'identité du receiver historique et les profils du nouveau backend
   dans le coffre prévu, après sélection de l'environnement à déployer ; aucune
   clé dans le chat, Git ou le frontend.
2. Relire et tester le lot de migrations sur un environnement isolé approprié,
   puis publier uniquement avec l'autorisation requise. Ne pas modifier la
   destination historique pour pointer vers un code pas encore disponible.
3. Vérifier une livraison signée réelle pour le nouveau profil une fois celui-ci
   configuré et hébergé ; les tests locaux ne remplacent pas cette étape.
4. Compléter les offres, références exactes et devis de livraison réellement
   acceptés. Les commandes examinées restent en revue fournisseur.

Aucune clé créée, aucun secret révélé, aucun paiement/refund, migration distante,
commande fournisseur, publication, prix public, design ou photographie modifié.
