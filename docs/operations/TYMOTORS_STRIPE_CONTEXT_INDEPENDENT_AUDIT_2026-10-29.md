# Audit indépendant — contexte de compte Stripe signé

## Décision

APPROVED LOCAL pour le correctif de validation du contexte direct, après revue
du code et contre-tests indépendants. Le Chef conserve la décision finale.
Cette validation ne vaut ni déploiement, ni activation des encaissements, ni
confirmation d'un achat fournisseur ou d'une expédition.

## Problème examiné

Le contrôle historique assimilait toute présence de `Event.context` à une
délégation Connect. Un contexte de compte direct correspondant exactement au
compte serveur épinglé était donc refusé. Le correctif conserve l'interdiction
de Connect et compare le contexte présent au compte prévu côté serveur.

Une observation via l'API des événements ne prouve pas que le corps exact d'une
ancienne livraison webhook contenait ce champ. Les contre-tests ci-dessous
utilisent des événements synthétiques signés localement, pas des livraisons
Stripe rejouées ni des clés d'un compte réel.

## Contrôles exécutés

- 66 contre-tests indépendants ajoutés dans
  `tests/test_independent_stripe_context.py`.
- 226 tests Python réussis lors de la recette indépendante combinée : ce fichier,
  `test_commerce_webhook_profiles.py`, `test_commerce_context_payments.py` et
  `test_independent_context_audit.py`. Durée affichée : 6,90 secondes, sortie 0.
- Signature HMAC vérifiée par le vrai SDK sur les véritables routes HTTP locales.
  Les accès base sont des mocks enregistrants, sans appel réseau.
- Contexte exact accepté ; contexte absent conservé pour les snapshots anciens.
  Le dossier est enregistré uniquement sous le compte et le profil serveur.
- Contextes étrangers, organisation, chemin de comptes, espaces, casse modifiée,
  valeur nulle, booléen, nombre, liste et objet refusés avant tout accès base.
- Présence de `account` refusée même si sa valeur est égale au compte configuré
  ou nulle. Aucune activation implicite de Connect.
- Signature erronée, modification du corps et mode contradictoire refusés.
- Un événement du premier profil ne traverse pas le second, même signé avec le
  secret du second : le compte doit aussi correspondre.
- Le service métier réapplique la même garde avant accès base.
- Le receiver legacy conserve son compte et son mode d'origine lorsque le
  checkout courant est en mode live. Un compte legacy vide ne s'infère jamais
  depuis un événement signé, des métadonnées ou la clé du checkout courant.
- La configuration explicite refuse notamment `None`, `False`, `0`, liste et
  objet. Le premier garde-fou fondé sur la vérité de la valeur a été corrigé.
- `git diff --check` réussi. Aucun fichier image ou composant visuel modifié
  dans le diff examiné.

## Contre-exécution du parcours HTTP et SQL

L'auditeur a relancé `tests.run_commerce_pipeline` avec le probe
`tests.commerce_context_dispatch_probe`, après vérification des ports libres :

- 655 contrôles historiques réussis.
- 252 contrôles du moteur par compte/profil réussis.
- 216 contrôles du traitement manuel et du suivi multicolis réussis.
- Parcours HTTP avec vrai SDK et transport HTTPX factice : une seule création
  Checkout factice, reçu payé, aucun effet de paiement en double.
- L'événement signé qui traverse la route HTTP puis le règlement SQL contient
  désormais le contexte exact du compte. Le contexte étranger et la mauvaise
  signature sont refusés avant le règlement.
- Garde de nouvelle vente finale `false`, aucun appel fournisseur/transporteur,
  paiement réel, remboursement réel ou expédition réelle. Sortie du runner : 0.

Le runner a ensuite été corrigé par le Chef pour supprimer l'héritage éventuel
de `STRIPE_LEGACY_ACCOUNT_ID`. Un contrôle indépendant supplémentaire a injecté
`org_should_not_leak` dans l'environnement parent et capturé, avec Popen et
socket mockés, les deux environnements enfants : valeur vide dans les deux,
PASS. Ce second contrôle ne lance ni processus enfant ni appel réseau ; il ne
prétend pas remplacer une nouvelle recette complète. Aucun code métier n'a été
modifié entre la recette complète et cette correction du runner.

Après nettoyage du runner, une dernière vérification ne trouve aucun listener
sur 8765/8766. Des états TCP transitoires ont été observés pendant le nettoyage ;
aucun processus inconnu n'a été arrêté par l'auditeur.

## Limites et suite

Le receiver legacy accepte un snapshot contenant `context` seulement après
configuration explicite de `STRIPE_LEGACY_ACCOUNT_ID`. La valeur par défaut vide
conserve le refus. Le correctif ne change aucune configuration distante.

L'audit n'a exécuté aucun paiement, remboursement, création de clé, replay Stripe,
migration distante ou déploiement. La chaîne SQL complète n'est pas démontrée par
ces seuls tests Python ; la contre-recette isolée HTTP/SQL ci-dessus étend la
vérification locale. PGlite ne constitue pas une preuve de concurrence native
entre connexions PostgreSQL. Le fonctionnement du webhook hébergé avec cette nouvelle version
reste à vérifier après publication autorisée.

## Empreintes du code examiné

| Empreinte SHA-256 | Fichier |
| --- | --- |
| 1FB1DB0AFDCDCF38B30366742ACA7B558449A127F7297220CFA0AE863DF2467C | app/commerce_webhook_profiles.py |
| 895D2B23F8CEDC2C21E554393862DCAA732F5F5097D67702E6203EC35E4BD506 | app/commerce_context_payments.py |
| 268F79A0B1614A55878CD91FB07C04247C1A6597E2298823AD3015166A95E2A1 | app/config.py |
| 3D27E4E308381F031CA4A4868A68340D6681CFC9C03833B1B9D26E328FE3ADF9 | server.py |
| 1ABB518C0604AB4DF310A546F6EA31877D7C89BF2651E3D31D74B6EA973E16C1 | tests/test_independent_stripe_context.py |
| 6DEBF01626330EE720517BC3A8C92AE1C370E93F37DB27F8D0C9D640CEDBABBC | tests/commerce_context_http_journey.py |
| 8CF28C2E75EF9759C3EDB61EDF9560BD9C7B758D6C289CBCC5F17870CF296A87 | tests/run_commerce_pipeline.py |
