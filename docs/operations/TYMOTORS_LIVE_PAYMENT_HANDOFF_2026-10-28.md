# Passage du paiement à devis vers la production — état vérifié

Statut : NOT_READY_FOR_LIVE. Ce document ne constitue ni une activation ni une
preuve de paiement réel. Le lot de correctifs locaux a été testé et audité ;
la généralisation du parcours sandbox vers la production reste un lot distinct.

## Frontières existantes à préserver

| Couche | Implémentation actuelle | Condition du futur lot production |
|---|---|---|
| API client | commerce_customer_checkout_api refuse le live | Autorisation de mise en service côté serveur, propriété panier/devis et idempotence maintenues |
| Adaptateur | TestStripeGateway accepte seulement des clés et sessions test | Mode et identité du compte authentifié vérifiés, aucun mélange entre comptes ou environnements |
| Paramètres/session | Défaut sandbox conservé ; contexte serveur explicite mode/compte ajouté et contre-audité (510a69a) | Fournir des snapshots persistés et une identité fournisseur authentifiée ; le contrat pur ne constitue pas cette preuve |
| Commande SQL | order_from_quote refuse p_is_test=false | Transactions production et permissions revues sans réutiliser les garde-fous test comme autorisation live |
| Réservations/tentatives | Contraintes CHECK(is_test), historique sandbox conservé | Consommation/libération transactionnelles justifiées, concurrence et crash testés |
| Encaissement | commerce_settle_test_checkout et registres test | Règlement production unique par session/PI/commande, erreurs et événements hors ordre maîtrisés |
| Remboursement | commerce_record_test_refund exclusivement test | Journal signé production et blocage opérationnel cohérents, sans double compte |
| Notifications | Reprise legacy sécurisée ; envoi financier initial best-effort | Outbox financière transactionnelle avec issue ambiguë tracée et reprise prudente |

La source de vérité devra rester la commande figée et le webhook authentifié,
jamais la page de succès, une métadonnée client ou la présence d'une clé live.
Une signature valide ne justifie ni un autre compte, ni une autre variante,
ni un montant ou un transport différent du dossier payé.

## Contrat préparé, intégration transactionnelle encore à réaliser

Le contrat pur de paramètres/validation est implémenté et audité. Les comptes
NULL hérités sont préservés ; un compte renseigné exige un contexte explicite.
Les origines numériques ambiguës sont refusées. Aucun consommateur HTTP/gateway
n'a été ouvert au live. La persistance du compte est un lot sandbox séparé en
recette locale ; elle n'authentifie pas le compte et n'autorise pas sa création
de session. Les modes/comptes attendus doivent toujours provenir du serveur et
de preuves fournisseur authentifiées, jamais de champs de formulaire.

Contre-tests d'acceptation :

- Source test vers contrat live et inverse refusées ; mode absent/ambigu refusé.
- Mauvais compte, mauvaise session, PI réutilisé, montant/devise/variante changés
  refusés ; identité historique conservée à chaque étape.
- Idempotence et reprise après timeout sans deuxième tentative de débit.
- Historique sandbox et gardes HTTP existantes inchangés.
- Ensuite seulement : règlement SQL, cycle des réservations, remboursements et
  notifications durables avec tests HTTP/SQL et concurrence appropriés.

Ne pas retirer simplement les CHECK ou les conditions test-only. Ne pas ajouter
une seconde chaîne de commandes sans justification. Les migrations locales
nécessaires devront être contrôlées avant toute application hébergée.

## Éléments d'activation qui ne peuvent pas être inventés

Identité commerciale réelle, compte Stripe live opérationnel et autorisé,
contexte fiscal, secret webhook associé au bon compte, configuration sécurisée,
catalogue/offres/livraison réellement approuvés, puis autorisation de publication
et recette sur l'environnement retenu. Aucun de ces éléments n'est validé par
un paiement synthétique ou par les correctifs de ce lot.

SIRET/statut restent hors du lot demandé. Les coordonnées, médiation, retours,
facturation et remise durable des conditions figurent aussi dans le rapport
frontend. Aucun secret ne doit être transmis dans le chat ou conservé au dépôt.

## Preuves de la présente analyse

Lecture du code actuel par le Chef et l'agent de revue, sans écriture de ce
dernier, sans API live ni paiement. Points observés : API customer checkout,
commerce_customer_checkout.start, TestStripeGateway, commerce_checkout_params,
commerce_checkout_events, migrations commerce_order_from_quote / attempts /
settlement / refund ledger. Les numéros de lignes peuvent évoluer avec le lot ;
utiliser les symboles et les commits de livraison pour la reprise.

Cette frontière est une information de lancement essentielle : la généralisation
production n'est pas simplement une attente de réponse par mail.
