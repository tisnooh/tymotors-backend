# Stripe — TYMotors en test uniquement

Le paiement utilise Checkout hébergé, sans transmission de données de carte au serveur TYMotors. Ne pas activer le mode réel ni acheter des produits fournisseurs pendant ces tests.

## Compte et secrets

Reconnecter le plugin Stripe au compte TYMotors et sélectionner son environnement de test (ou son sandbox). Aucun accès Stripe n'a été confirmé tant que le connecteur demande une réauthentification.

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
