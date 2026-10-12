# Stripe — TYMotors en test uniquement

Le paiement utilise Checkout hébergé, sans transmission de données de carte au serveur TYMotors. Ne pas activer le mode réel ni acheter des produits fournisseurs pendant ces tests.

## Compte et secrets

Le 12 octobre 2026, le sandbox TYMotors a été vérifié dans le navigateur connecté. Le plugin Stripe demande encore une réauthentification : ne pas confondre son accès avec celui du navigateur.

Configurer dans le coffre de secrets / les variables privées Render du backend européen :

- `STRIPE_SECRET_KEY` : clé **de test**, de préférence restreinte `rk_test_` avec Checkout Sessions en lecture/écriture ; Coupons en écriture si les promotions sont utilisées. Vérifier les permissions dépendantes indiquées par Stripe lors de la création. `sk_test_` reste compatible. Jamais de clé `live`.
- `STRIPE_WEBHOOK_SECRET` : secret de signature de la destination **test** ci-dessous, jamais celui du mode réel.
- `STRIPE_AUTOMATIC_TAX=false` tant que les inscriptions fiscales ne sont pas validées.

Ne pas coller les clés dans le chat, Git, le frontend ou des captures d'écran. La création/entrée d'une nouvelle clé doit être effectuée par le propriétaire dans Stripe puis Render.

Destination webhook test : `https://tymotors-backend-eu.onrender.com/api/stripe/webhook`.

Événements : `checkout.session.completed`, `checkout.session.async_payment_succeeded`, `checkout.session.async_payment_failed`, `checkout.session.expired`, `payment_intent.payment_failed`, `charge.refunded`, `refund.created`, `refund.updated`, `refund.failed`.

## Validation de bout en bout

1. Utiliser un produit test actif, avec prix, stock, image, fournisseur et compatibilité vérifiés.
2. Créer une session depuis un panier du site. Vérifier que Stripe affiche son mode test et les montants EUR corrects.
3. Finaliser avec un moyen de paiement test officiel Stripe ; aucune carte réelle.
4. Vérifier le webhook signé, le paiement `paid`, une seule diminution de stock et un seul dossier fournisseur `pending_validation`.
5. Rejouer l'événement : aucune seconde diminution de stock, aucun double email.
6. Tester l'échec, l'expiration et le remboursement de test.
7. Vérifier le suivi client et l'admin. La validation fournisseur reste manuelle, sans commande Alibaba/HyperSKU automatique.

Le code accepte les clés restreintes de test et refuse les événements Stripe réels dans un checkout configuré avec une clé de test. Les tests locaux ne remplacent pas cette validation réelle dans le sandbox connecté.

## Résultat vérifié le 12 octobre 2026

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
