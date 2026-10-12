# Stripe — TYMotors en test uniquement

Le paiement utilise Checkout hébergé, sans transmission de données de carte au serveur TYMotors. Ne pas activer le mode réel ni acheter des produits fournisseurs pendant ces tests.

## Compte et secrets

Le 12 octobre 2026, le sandbox TYMotors a été vérifié dans le navigateur connecté. Le plugin Stripe demande encore une réauthentification : ne pas confondre son accès avec celui du navigateur.

Configurer dans le coffre de secrets / les variables privées Render du backend européen :

- `STRIPE_SECRET_KEY` : clé **de test**, de préférence restreinte `rk_test_` avec Checkout Sessions en lecture/écriture ; Coupons en écriture si les promotions sont utilisées. Vérifier les permissions dépendantes indiquées par Stripe lors de la création. `sk_test_` reste compatible. Jamais de clé `live`.
- `STRIPE_WEBHOOK_SECRET` : secret de signature de la destination **test** ci-dessous, jamais celui du mode réel.
- `STRIPE_AUTOMATIC_TAX=false` tant que les inscriptions fiscales ne sont pas validées.

Ne pas coller les clés dans le chat, Git, le frontend ou des captures d'écran. La création/entrée d'une nouvelle clé doit être effectuée par le propriétaire dans Stripe puis Render.

Destination webhook test : `<URL_BACKEND>/api/stripe/webhook` (URL de votre service Render, sans domaine imposé par le code).

Événements : `checkout.session.completed`, `checkout.session.async_payment_succeeded`, `checkout.session.async_payment_failed`, `checkout.session.expired`, `payment_intent.payment_failed`, `charge.refunded`, `refund.created`, `refund.updated`, `refund.failed`.

## Validation de bout en bout

### Recette locale sous PowerShell

Configurer les variables privées du backend : `ENVIRONMENT=test`, `STRIPE_MODE=test`, `SITE_URL=http://localhost:3000`, `CORS_ORIGINS=http://localhost:3000`, une clé Stripe **test**, `SHIPPING_COUNTRIES=FR` et la base staging isolée. `SHIPPING_RATE_CENTS=1500`, `FREE_SHIPPING_THRESHOLD_CENTS=35000` sont des montants en centimes configurables.

Installer la [Stripe CLI officielle](https://docs.stripe.com/stripe-cli), puis dans un terminal privé :

```powershell
stripe login
stripe listen --events checkout.session.completed,checkout.session.async_payment_succeeded,checkout.session.async_payment_failed,checkout.session.expired,payment_intent.payment_failed,charge.refunded,refund.created,refund.updated,refund.failed --forward-to http://127.0.0.1:8000/api/stripe/webhook
```

Enregistrer le secret `whsec_…` annoncé par `listen` dans `STRIPE_WEBHOOK_SECRET` de l'environnement local privé, puis redémarrer le backend. Ne pas copier ce secret dans Git/chat/capture. Ce secret est distinct de celui du webhook Render.

```powershell
.\.venv\Scripts\python.exe -m uvicorn server:app --host 127.0.0.1 --port 8000
```

Depuis le panier d'une **base de test uniquement**, payer avec `4242 4242 4242 4242`, date future, CVC `123`, adresse et téléphone de test. Une fixture isolée est nécessaire tant que les vrais produits ne sont pas validés. La page `/order-success` ne crée aucun paiement et ne confirme pas elle-même la commande : elle lit le résultat du webhook pendant 30 secondes, puis conserve le statut en attente.

Vérifier le téléphone dans l'admin, les deux lignes Stripe (produits/livraison), la concordance des totaux, un seul mouvement de stock et le dossier fournisseur à validation manuelle. Rejouer l'événement signé avec `stripe events resend <EVENT_ID> --webhook-endpoint=<ENDPOINT_ID>` pour une destination distante de test. `stripe trigger checkout.session.completed` seul ne teste **pas** le panier TYMotors (pas de métadonnées de commande).

Sources : [tests et carte 4242](https://docs.stripe.com/testing), [webhooks](https://docs.stripe.com/webhooks), [traitement après paiement](https://docs.stripe.com/checkout/fulfillment).

La CLI Stripe n'est pas installée sur ce poste et le plugin demande une réauthentification. La recette avec un vrai Checkout sandbox reste **bloquée (action manuelle requise)** ; les tests signés du SDK et PostgreSQL restent exécutables sans secret.

1. Utiliser un produit test actif, avec prix, stock, image, fournisseur et compatibilité vérifiés.
2. Créer une session depuis un panier du site. Vérifier que Stripe affiche son mode test et les montants EUR corrects.
3. Finaliser avec un moyen de paiement test officiel Stripe ; aucune carte réelle.
4. Vérifier le webhook signé, le paiement `paid`, une seule diminution de stock et un seul dossier fournisseur `pending_validation`.
5. Rejouer l'événement : aucune seconde diminution de stock, aucun double email.
6. Tester l'échec, l'expiration et le remboursement de test.
7. Vérifier le suivi client et l'admin. La validation fournisseur reste manuelle, sans commande Alibaba/HyperSKU automatique.

Le code accepte les clés restreintes de test et refuse les événements Stripe réels dans un checkout configuré avec une clé de test. Les tests locaux ne remplacent pas cette validation réelle dans le sandbox connecté.

## Résultat antérieur conservé — non revalidé après les commits de cette session

Ce relevé décrit la précédente vérification distante du 12 octobre. Les nouveaux commits applicatifs de préparation ci-dessus restent locaux ; ils ne sont pas encore déployés. Ne pas présenter ce relevé comme une preuve du Checkout TYMotors après ces modifications.

- Backend européen `tymotors-backend-eu`, Render Frankfurt, commit correctif `9860d88` déployé et état Live vérifié.
- `FRONTEND_URL=https://tymotors.vercel.app` enregistré ; CORS autorise cette origine. `ENVIRONMENT=test` conservé.
- Destination sandbox existante `we_1TuRuwJPkDEK6DalaYLsAIQ5` active, pointant vers le backend européen, avec les neuf événements listés ci-dessus. Secret de signature conservé, jamais exposé ni régénéré.
- L'événement signé `evt_1UPgcnJPkDEK6DalCw7FaQDj`, créé par le générateur officiel Stripe, a obtenu HTTP 200 et a été enregistré `completed` dans `stripe_events`.
- Son renvoi a également obtenu HTTP 200 avec `{"received":true,"duplicate":true}`. La base contient toujours une seule ligne pour cet événement et une seule commande TYMotors. Capture : `assets/stripe-test-webhook-200-duplicate.png` à la racine du workspace.
- Ce générateur crée une session synthétique sans `order_id` TYMotors. Il valide la signature et la livraison du webhook, PAS une commande du panier TYMotors. Le nombre de commandes TYMotors est resté à une.
- Les erreurs HTTP 500 initiales provenaient d'un appel `.get` sur un objet du SDK Stripe. Les objets sont désormais convertis récursivement avec `to_dict()` après vérification de la signature ; les remboursements utilisent également cette conversion.
- SDK verrouillé sur `stripe==16.0.0` ; son API par défaut est `2026-09-30.endive`. La version de la destination existante, `2026-04-22.dahlia`, a été conservée.
- 168 tests backend réussis, dont des événements réellement signés, la détection des signatures invalides, le refus des événements live et la normalisation des ressources Stripe. CI backend réussie.

La validation complète des étapes 1 à 7 reste ouverte : aucun produit actuellement actif et vérifié n'est disponible pour créer une commande du site. Ne pas réactiver la fixture archivée en production, inventer du stock ou déclarer un produit vérifié pour contourner ce blocage.

Le passage au mode réel nécessite une décision distincte, la configuration live et une recette complète. Il n'a pas été effectué.
