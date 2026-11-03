# TYMotors — fonctionnement réel et corrections du 3 novembre 2026

## Constat initial en production, avant le diagnostic intégré

Sources de ce premier constat : lecture SQL du projet Supabase `dzdcaloewimekvddvdlo`, API publique, connecteur Stripe du compte `acct_1Tc9tvJB6441TWWo`, déploiement Vercel `dpl_EJZ5DqiZjXMYVxtg6Qq3kT8wv82g` (READY, main `d05d68f`). L'état ultérieur, les déploiements et la commande diagnostique gratuite réellement confirmée sont documentés dans `ZERO_CHECKOUT_LIVE_RESULT_2026-11-03.md`.

| Fonction | Résultat constaté | Limite |
| --- | --- | --- |
| Hébergement et API | Frontend READY ; backend health et configuration répondent. | Un appel initial a expiré à 15 secondes avant de réussir au contrôle suivant ; cause non établie. |
| Catalogue | 40 articles commerciaux visibles, tous en brouillon. | 0 actif, 0 vérifié, 0 stock positif, 0 vendable. Une 41e ligne est une ancienne fixture de test archivée. |
| Fournisseurs | 8 articles ont une association GZTM/Leju non vérifiée ; 32 n'ont pas de nom fournisseur dans le champ opérationnel. | Aucune offre commerciale vérifiée. L'unique offre marquée vérifiée est la fixture archivée STAGING-ONLY, exclue du bilan commercial. |
| Compatibilités pilotes | Règles enregistrées pour trois pilotes. | 0 règle vérifiée sur les cinq pilotes ; W205 et Golf 7 n'ont pas de règle associée. |
| Images | 39 articles ont des images exposées. | `bmw-logo-door-projectors` n'en expose aucune ; aucune photo modifiée pendant ce lot. |
| Stripe | Configuration serveur live ; webhook live activé vers `/api/stripe/webhook`. Un essai gratuit réel a ensuite confirmé sa signature et son traitement (preuve ci-dessous). | Aucun encaissement bancaire ni parcours panier → commande commerciale validé par cet essai. |
| Commandes | 14 commandes conservées, toutes `is_test=true` (7 paid, 7 failed). | 0 commande client réelle. Un dossier fournisseur existe et est annulé ; 0 dossier agent connecté. |
| CJ | Authentification et lecture des connexions prévues par le code ; flux externe à l'unité confirmé par support. | Aucun produit pilote approuvé/mappé et chiffré. Le code CJ actuel n'inscrit ni Service Product ni commande. |
| Informations commerciales | `legal_ready=false` ; champs légaux publics vides. | Identité du vendeur, coordonnées, retours et médiation ne peuvent pas être inventés. |

## Corrections techniques du lot

1. **Montant Stripe / taxes** : empêcher `STRIPE_AUTOMATIC_TAX=true`, car les taxes ajoutées par Stripe n'étaient pas enregistrées dans le total de commande attendu par le webhook. Le serveur refuse cette configuration avant de prendre des paiements incohérents. Garder la variable à `false` avant déploiement. Le calcul fiscal complet reste hors validation.
2. **Confirmation de commande** : distinguer paiement échoué, paiement en attente et remboursement ; ne pas laisser croire qu'un paiement échoué attend seulement Stripe.
3. **Panier** : signaler les échecs de changement de quantité et de suppression ; rafraîchir les données après erreur sans laisser une promesse rejetée sans traitement.
4. **Disponibilité** : remplacer les libellés ambigus des brouillons par « En cours de vérification » et « Indisponible » ; réserver « Simulation de commande » aux essais explicitement identifiés.

Les changements restent sur branches de travail. Aucun design, fichier image ou prix public modifié. Aucun paiement réel, achat fournisseur ou déploiement de ce lot.

## Vérifications et décision

- Backend : 448 tests Python réussis ; 95 contrôles de base isolée réussis.
- Catalogue : 4 suites frontend ciblées, 152 tests réussis.
- Panier/confirmation : 14 tests ciblés réussis et compilation de production réussie ; après revue, priorité donnée aux statuts échoué/remboursé même si la réponse contient un champ `paid` incohérent, et erreurs de rafraîchissement panier également traitées.
- Contrôle conjoint final : 4 suites, 122 tests réussis (Cart, OrderSuccess, ProductCard, ProductDetail).
- Audit indépendant : aucune régression bloquante détectée ; ses réserves de documentation Stripe Tax ont été corrigées. Les nouveaux libellés de disponibilité sont également rendus en anglais en mode EN. Aucun CSS, fichier photo ou prix modifié.

Le fonctionnement commercial de bout en bout reste **BLOCKED**. Les tests internes démontrent des traitements et des protections, pas une commande réellement reçue par un fournisseur.

## Déblocage concret

| Responsable | Action attendue |
| --- | --- |
| Fournisseur | Confirmer pour au moins un pilote la variante exacte, la compatibilité et ses restrictions, le stock, le prix unitaire, le colis et le transport fournisseur → CJ. Réponses déjà demandées ; ne pas déduire ces données d'une autre annonce. |
| CJ | Approuver le Service Product exact, fournir la variante CJ, le magasin cible et un devis complet France à l'unité ; confirmer les frais et les étapes de traitement. |
| TYMotors / administrateur | Renseigner les informations commerciales réelles et le cadre fiscal applicable. |
| Codex après réception des données | Enregistrer et vérifier l'offre, relier la variante, calculer le coût complet, tester le checkout dans un sandbox isolé puis vérifier la chaîne commande → agent → expédition simulée. Une commande fournisseur payante exige l'autorisation prévue. |

Aucun pilote ne peut être activé automatiquement avec les preuves actuelles : **0/5 validé**, **40/40 articles commerciaux non vendables**.

## Essai Stripe réel gratuit demandé par le propriétaire

Création d'un produit inline intitulé `[DIAGNOSTIC] TYMotors — essai gratuit sans expédition`, prix 0 EUR, sans moyen de paiement ni expédition. Session créée directement via l'API Stripe, puis finalisée dans Checkout : `cs_live_a1Pdfj14cR01LRMv9MaL5uAD3RSLXKKpCDD8FLU8sHtuOdq4hNcxJRrpBK`, `livemode=true`, `status=complete`, `payment_status=paid`, `amount_total=0`, `payment_intent=null`.

Preuve croisée : l'événement Stripe `evt_1UXak1JB6441TWWoQ88fMnXx` est bien `checkout.session.completed`, live, lié à cette session, avec `pending_webhooks=0`. La même référence figure dans `public.stripe_events` en production, statut `completed`, créée le 3 novembre à 05:59:04 UTC et terminée sans erreur. Cela confirme la réception du webhook signé réel et son traitement.

Limite volontaire : aucune métadonnée `order_id` de commande commerciale n'a été utilisée ; cet essai ne crée donc pas de commande boutique, de dossier fournisseur ou d'achat. Il ne prouve ni l'encaissement d'une carte, ni la disponibilité d'un article, ni une liaison CJ. Les garde-fous du checkout public n'ont pas été contournés.

Les PR brouillon [backend #7](https://github.com/tisnooh/tymotors-backend/pull/7) et [frontend #7](https://github.com/tisnooh/tymotors-frontend/pull/7) sont préparées sans fusion. Le premier scan Gitleaks échouait faute de GITHUB_TOKEN ; le jeton éphémère en lecture et la lecture des PR ont été déclarés, les commentaires désactivés. Après correction, scans secrets, tests Python 3.11/3.12, dépendances, build frontend et preview Vercel ont tous réussi. Aucun déploiement de production de ces branches.

Accès CJ : le propriétaire confirme sa connexion, mais la lecture de l'onglet par l'outil renvoie `browser.user is unavailable` ; l'essai dans un onglet neuf expire. Aucun nouveau mapping ni Service Product ne peut être certifié à partir de cet accès indisponible. Les e-mails ne comportent aucune nouvelle réponse fournisseur depuis celles déjà consignées.
