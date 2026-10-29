# Contrat structurel mode et compte Checkout — fermé par défaut

Statut : préparation locale, NOT_READY_FOR_LIVE. Aucun appel Stripe, paiement,
changement SQL, modèle public, interface, clé, déploiement ou activation.
Base de travail : commit 2c22ec6 et plan TYMOTORS_LIVE_PAYMENT_HANDOFF_2026-10-28.md.

## Contrat et frontières de confiance

`app/commerce_checkout_mode.py` définit `CheckoutServerContext`, dataclass gelée
contenant `mode` (`sandbox` ou `production`) et `stripe_account_id` attendu.
Ce contexte doit être construit par le serveur. Une dict de requête n'est pas
acceptée comme contexte. Cela ne constitue toutefois pas une frontière de
sécurité : tout code Python de confiance peut construire ce type.

Sous contexte explicite, les snapshots commande ET tentative doivent contenir
`stripe_account_id`, identique au compte attendu, ainsi qu'un booléen `is_test`
cohérent avec le mode. Il s'agit d'un contrat d'entrée proposé : ce lot n'ajoute
aucune colonne aux tables existantes ni aucune persistance de cette identité.
Le futur lot SQL devra figer cette identité, son mode et leurs relations.

`build_checkout_params` accepte le contexte en argument keyword-only. Il réutilise
les contrôles existants : identités, montants TTC, articles, image exacte,
expiration, destination, devise EUR, absence de promotions et de taxation
automatique. Le contexte n'est ajouté ni aux métadonnées ni au payload Stripe.
En production structurelle, les origines doivent être HTTPS avec une autorité
publique plausible ; localhost, loopback, IP non globale et domaines locaux ou
réservés .test/.invalid sont refusés. Aucun DNS n'est effectué : ce n'est pas
une preuve d'existence ou de propriété du domaine.

`validate_checkout_session` exige, sous contexte explicite, `provider_account_id`
en argument séparé. Cette identité doit être établie par le futur adaptateur ou
la configuration vérifiée du webhook. Aucune valeur `account` ou métadonnée de
session ne peut remplacer cet argument. Le mode `livemode` de la SESSION et son
préfixe cs_test_/cs_live_ doivent correspondre. Les liens commande/devis/tentative,
session et PI déjà liés, montants, devise et destination restent contrôlés.
Sous contexte explicite, le PI non nul doit aussi respecter le format pi_.

Ce lot ne reçoit pas un objet Stripe Account et n'exige aucun champ
Account.livemode. Il ne prétend ni authentifier un compte ni vérifier ses
capacités. L'égalité d'identifiants purement fournis ne démontre pas leur origine.
L'événement doit encore être authentifié en amont ; une lecture de session ne
remplace pas le règlement par webhook.

## Compatibilité historique et absence d'activation

Sans contexte, le comportement historique reste sandbox strict pour les
snapshots existants dont le compte est absent ou nul sur chaque ligne. Cela
permet la future colonne SQL nullable sans backfill ni validation fictive des
comptes historiques. Un compte non nul, même partiel ou mal formé, reste refusé.
Les codes d'erreur historiques de mode
sont conservés. Une identité de compte ajoutée dans un snapshot sans contexte
est refusée pour éviter de l'ignorer silencieusement. Fournir uniquement une
identité fournisseur sans contexte est également refusé.

Les points d'entrée HTTP, TestStripeGateway, services de tentative, RPC,
CHECK(is_test), journaux et traitement fournisseur restent test-only, inchangés.
Aucun de ces appels existants ne fournit le nouveau contexte. Une session ou un
PI utilisés par une autre commande nécessitent toujours les contraintes SQL :
le validator pur ne consulte aucun registre global et ne déduplique rien.

## Vérification et limites

Tests synthétiques purs, sans SDK, base, réseau, compte réel ou secrets :
contrats croisés de modes, booléens stricts, compte manquant/malformé/divergent,
contexte dict refusé, métadonnées incapables de remplacer le compte serveur,
préfixes de session, PI lié différent, commande/montants/devise, articles,
origines production et stabilité exacte des paramètres sandbox.

Commande locale : pytest sur test_commerce_checkout_mode,
test_commerce_checkout_params, test_commerce_checkout_events,
test_commerce_attempt_service, test_commerce_payment_service,
test_commerce_customer_checkout et test_commerce_payment_observation.
Résultat après corrections de contre-audit : 814 PASS en 18,38 s ; un
avertissement préexistant Starlette/httpx.
`git diff --check` réussi. Les services consommateurs testés conservent leurs
gardes sandbox. Les transports y sont simulés, aucun appel Stripe n'est exécuté.

Cette preuve reste distincte de toute preuve externe. Ce lot ne valide ni un paiement réel, ni un compte actif, ni la
persistance immuable SQL, ni une concurrence réelle, ni une livraison.
Prochain lot : persistance et règlement production audités, gestion des
réservations, réconciliation/remboursements, notifications financières durables.
L'identité réelle, les conditions commerciales et l'autorisation d'ouverture
restent nécessaires avant toute activation.

## Corrections demandées par l'auditeur

Le premier lot rejetait une clé de compte présente mais nulle. Le contrat
accepte maintenant absent/null dans les deux snapshots uniquement comme héritage
sandbox non lié. Il refuse tout compte non nul sans contexte, les valeurs
ambiguës et is_test=false ; ce n'est pas un compte historique validé.

Le premier contrôle d'origine traitait certaines syntaxes IPv4 de navigateur
comme des domaines publics. Toute autorité non reconnue par ip_address et dont
le dernier composant est numérique ou hexadécimal est maintenant refusée, dans
tous les modes. Les cas 127.1, 127.0.1, 0177.0.0.1, 0x7f.0.0.1, 192.168.1,
0300.0250.0.1, entier IPv4 et hôte terminé par un nombre ont leurs contre-tests.
Les IP publiques canoniques, domaines publics ordinaires et localhost sandbox
restent couverts. Aucun navigateur, réseau ou DNS n'est utilisé par le contrôle.

Le contre-audit a ensuite identifié le composant hexadécimal vide 0x/0X,
interprété comme zéro par WHATWG. Il est également refusé. Des contre-tests
supplémentaires couvrent 127.0.0.0x, 127.0.0x, 0x7f.0.0.0x et leurs variantes
majuscules, composants vides, points finaux simples et doubles dans les trois
modes. Les points finaux sont déjà refusés par le contrôle strict des labels.
