# Recette Stripe — TEST uniquement

Objectif : panier → Checkout sandbox → webhook signé → commande payée unique
→ admin → suivi public. Ne jamais utiliser une carte réelle, clé live ou commande
fournisseur. Une commande impayée est créée **avant** Checkout ; le webhook la
confirme, sans créer une seconde commande. `/order-success` est seulement une lecture.

## 1. Smoke test automatisé sans secrets

Depuis backend, Python du projet et Node installé :

```powershell
.venv/Scripts/python.exe -m pip install -r requirements-dev.txt
# Runtime PostgreSQL jetable, hors dépendances de production/Git/Docker :
npm.cmd install --prefix .admin-test-runtime --no-save --package-lock=false @electric-sql/pglite@0.5.8
.venv/Scripts/python.exe scripts/smoke_stripe.py
.venv/Scripts/python.exe -m pytest -q
```

Le smoke appelle les **vraies routes et le SDK Stripe** via TestClient avec base
et transport Checkout en mémoire explicitement simulés. Signature éphémère
générée, requête non signée rejetée, prix/livraison contrôlés côté serveur,
signature acceptée, rejeu dédupliqué, une commande/un effet/événement, lecture
succès et suivi, IDOR rejeté. Puis il exécute `tests/admin_database.mjs` dans
**PostgreSQL/PGlite réel jetable** : migrations, transaction paid/stock une fois,
protection admin et sessions. Pas de réseau fournisseur ni donnée hébergée.
Un test SQL absent/échoué est un échec, pas une réussite masquée.

Cela valide les frontières locales séparément ; cela ne teste **pas** Checkout
hébergé, les clés Render ou la livraison réelle d'un email. Aucun paiement réalisé.

## 2. Préparer le sandbox et la base staging

- Utiliser le sandbox TYMotors, **pas live**. Clé `sk_test_` ou `rk_test_`
  conservée uniquement dans `STRIPE_SECRET_KEY` du backend/coffre privé.
- `ENVIRONMENT=test`, `STRIPE_MODE=test`, `EMAIL_ENABLED=false` pour la recette
  locale, `SITE_URL=http://localhost:3000`, `CORS_ORIGINS=http://localhost:3000`.
- `SUPABASE_*` de **staging isolé**, migrations appliquées ; compte client et
  compte admin de test avec leurs vrais rôles. Aucun secret service dans le navigateur.
- Un produit test de staging seulement : stock/prix/compatibilité/fournisseur
  contrôlés. Aucun brouillon de production activé pour contourner le blocage métier.
- `SHIPPING_COUNTRIES=FR`, `SHIPPING_RATE_CENTS=1500`,
  `FREE_SHIPPING_THRESHOLD_CENTS=35000`, `STRIPE_AUTOMATIC_TAX=false` tant que
  la situation fiscale n'est pas validée.
- Front : `REACT_APP_SITE_MODE=test`, URLs localhost et clés **publishable**
  Supabase staging. Le site n'a pas besoin de clé Stripe frontend pour Checkout.

## 3. Installer Stripe CLI et écouter

[CLI officielle](https://docs.stripe.com/cli/install). Une copie locale d'outillage
1.53.1 est installée hors Git dans `.security-tools/stripe-cli/stripe.exe` sur ce
poste ; sur une nouvelle machine installer la version officielle actuelle.
Si `stripe` n'est pas au PATH, employer ce chemin à la place de `stripe`.

```powershell
stripe version
stripe login
stripe listen --events checkout.session.completed,checkout.session.async_payment_succeeded,checkout.session.async_payment_failed,checkout.session.expired,payment_intent.payment_failed,charge.refunded,refund.created,refund.updated,refund.failed --forward-to http://127.0.0.1:8000/api/stripe/webhook
```

Le propriétaire effectue la connexion. Renseigner le secret `whsec_` du listener
dans `STRIPE_WEBHOOK_SECRET` du **coffre local**, pas dans le chat, Git ou une
commande enregistrée. Le secret CLI est distinct du secret destination Render.
Redémarrer le backend après configuration ; garder le listener ouvert.

```powershell
# Terminal backend
.venv/Scripts/python.exe -m uvicorn server:app --host 127.0.0.1 --port 8000 --no-access-log
# Autre terminal, dossier frontend
npx.cmd --yes yarn@1.22.22 start
```

## 4. Carte 4242 et résultat attendu

1. Choisir produit + véhicule compatible, ajouter au panier, cliquer paiement.
2. Vérifier page Stripe marquée test, devise EUR, prix/quantités et livraison
   séparée. Collecte adresse de facturation, livraison et téléphone.
3. Carte **4242 4242 4242 4242**, date future, CVC **123**, identité/adresse de
   test (pas les coordonnées d'un vrai client). Aucun argent réel débité.
4. Listener : `checkout.session.completed` HTTP 200. Page `/order-success` :
   référence `TY-…`, paid après webhook ; si en attente, examiner la livraison
   de l'événement, ne pas marquer paid manuellement.
5. Admin → Commandes : même référence, montant exact, téléphone/adresse et statut
   payé ; un seul mouvement de stock, dossier fournisseur `pending_validation`.
   **Ne pas approuver/acheter chez Alibaba ou HyperSKU durant le test.**
6. `/support/track` : bon email test + référence → statut et suivi ; email faux
   ou référence fausse → même « introuvable ». Transporteur/numéro ajoutés
   depuis admin doivent apparaître, sans exposer données privées.
7. Rejouer l'événement test : un seul paiement/commande/débit stock/email.
   Pour une destination distante de test :

```powershell
stripe events resend $env:TEST_STRIPE_EVENT_ID --webhook-endpoint=$env:TEST_STRIPE_ENDPOINT_ID
```

Ces IDs ne sont pas des clés mais doivent appartenir au même sandbox. Pour le
listener local, refaire le smoke/rejouer une requête signée de fixture seulement
dans l'adaptateur isolé ; ne pas fabriquer un paiement sur une vraie commande.
`stripe trigger checkout.session.completed` **sans metadata order_id TYMotors**
ne valide pas le panier ni la création d'une commande de ce site.

## 5. Échecs, sécurité et preuve de recette

- Carte refusée officielle **4000 0000 0000 0002** : commande jamais paid.
- Retour panier/cancel ou session expirée : pas de débit stock avant paiement.
- Signature absente/fausse/altérée/ancienne : HTTP 400, aucune mutation.
- Double événement ou sessions concurrentes : tests SQL de transaction/stock,
  pas seulement un cache en mémoire.
- Remboursement **test**, partiel puis total : statuts réconciliés ; aucune
  remise en stock sans réception/inspection admin, aucune double remise.
- Noter date, SHA frontend/backend, sandbox, référence/event de fixture,
  HTTP/statuts/totaux et captures sans secrets/PII. Ne pas déclarer payé à partir
  d'un simple healthcheck ou d'un événement sans commande.

Sources : [webhooks et corps brut](https://docs.stripe.com/webhooks),
[cartes test](https://docs.stripe.com/testing). Passage live hors périmètre :
uniquement après SIRET, conformité légale/produits et recette complète autorisée.

## État externe réexaminé — 13 octobre 2026

Le connecteur Stripe demande une réauthentification. Le dashboard sandbox est
visible : destination test active et ancien événement générique dédupliqué en
HTTP 200. Il ne comporte aucune metadata de commande TYMotors, son retour est
extérieur au site et il ne collecte ni livraison ni téléphone. **Ce n'est pas
la recette 4242 du panier**. Ne pas créer/modifier une vraie commande pour lui
faire correspondre cet événement.

Supabase staging est accessible, eu-west-3 : 40 produits draft, 1 archived,
aucun actif au moment du contrôle. Le code et le smoke local sont vérifiés ;
la recette hébergée reste bloquée (action manuelle requise : réauthentification,
coffre sandbox configuré et référence staging isolée validée). Aucun produit
réel activé ni clé Stripe créée/copiée pour contourner cette limite.
