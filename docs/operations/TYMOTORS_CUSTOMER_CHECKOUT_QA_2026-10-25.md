# TYMotors — recette du pont client,25octobre2026

## Verdict de lancement : NON VALIDÉ

Le lot backend/client non visuel est testé localement. Il ne rend pas la boutique
commercialement exploitable à lui seul. Aucun paiement Stripe de test achevé,
aucune commande fournisseur, expédition réelle ou transmission HyperSKU dans ce lot.
Les cinq pilotes restent des candidats, pas des produits validés.

Branche des deux dépôts : `codex/commerce-workflows`. Point initial backend
`b627091c219a3d9c5252d1aea137a3cdedf61351`, frontend `c3f06c18`.
Pas de push ni de déploiement du nouveau lot. Les checkouts historiques privés
sont préservés ; tests sur les worktrees `scp-release` et bases jetables uniquement.

## Corrections réellement effectuées

- Découverte publique de variantes actives/vérifiées, identités exactes et aucune
  sélection automatique d'une finition parmi plusieurs choix. Aucun fallback legacy.
- Boutons existants reliés à cette résolution centralisée. Confirmation de réponse
  portant sur variante, véhicule normalisé et quantité couvrant l'incrément connu ;
  aucun succès ni retry/rollback automatique sur réponse incohérente.
- Devis public relié à une demande checkout propriétaire sandbox, six RPC backend
  privées et vérification de session active. Pas d'usurpation d'administrateur.
- Verrou panier partagé entre devis et clé fournisseur persistante avant appel ;
  refus des doubles achats et mise en inspection sur résultat incertain. Holds conservés.
- Relecture du contexte après réseau ; URL HTTPS Stripe correspondant à la session
  exacte ; aucune confirmation financière fondée sur le seul navigateur/GET Stripe.
- Page de confirmation existante alimentée avant arrivée du webhook via liaison
  persistée : `paid:false`, propriétaire contrôlé avant données client. Paiement
  confirmé uniquement à partir du règlement local signé, sans changement du rendu.
- Script de recette sandbox `--customer` préparé : P1 de mauvaise colonne de session
  détecté par l'auditeur, rejeté, corrigé par jointure et retesté.
- Transport de recette FAKE isolé à l'exécution explicite de la fixture ; import par
  la fixture Stripe réelle ne remplace pas son SDK. Secrets/rapports réels hors Git.

## Preuves et portée

| Contrôle | Résultat réellement obtenu | Limite |
|---|---|---|
| Suite backend complète chef |1452 pytest PASS,31,62s,1 avertissement Starlette/httpx préexistant | Local, pas GoTrue/PostgREST hébergés |
| Suite frontend globale chef |583 tests/38 suites PASS,262,887s,exit0 | CI/runInBand/watchAll=false/testTimeout30s/no-cache/forceExit ; pas navigateur, fermeture naturelle des handles non prouvée |
| ESLint sur fichiers frontend modifiés |PASS,exit0 après correction de2 globals de tests | Pas une preuve de rendu navigateur |
| SQL client / administration indépendants |137 +66 contrôles PASS | PGlite sérialisé, pas concurrence PostgreSQL multiconnexions |
| Backend ciblé initial indépendant |148 tests PASS | Recouvrement avec suite globale, ne pas additionner |
| Helper vraie sandbox corrigé |6 contre-tests PASS | Hors réseau, aucune session créée |
| Confirmation pré-webhook |30 tests chef +30 contre-tests indépendants PASS | Aucun SDK/RPC financier ni mutation |
| Parcours public initial indépendant |153 HTTP/SQL PASS,exit0 | Avant ajout de la confirmation pré-webhook ; Stripe FAKE |
| Historique indépendant |557 HTTP/SQL PASS,exit0 | Cinq pilotes SYNTHÉTIQUES, pas commerciaux ; avant dernier helper receipt |
| Parcours public final enrichi chef |173 HTTP/SQL PASS,exit0 | Signature SDK/HMAC local synthétique, Stripe FAKE ;1 create/commande/tâche/colis SIM |
| Contre-exécution enrichie173 |173 PASS,exit0 sur le dernier code | Auditeur indépendant, ports8765/8766 fermés après cleanup ; APPROVED local simulé uniquement |
| Compilation frontend |Compiled successfully,exit0 | CI=true,GENERATE_SOURCEMAP=false,artefact local .browser-test-build,APIloopback ; pas déploiement |
| Design/photos/prix publics |Aucun fichier de rendu/style/image/prix public modifié | Captures comparatives non réalisées, navigateur instable |

Les tests se recouvrent : ne pas présenter la somme de ces lignes comme un nombre
de scénarios indépendants. Les premiers échecs d'initialisation/temps/JSDOM et le
chemin de test ProjectBuilder erroné restent dans le journal ; les runs finaux
réussis ne sont pas une explication prouvée de leur cause.

## Parcours exercé

Véhicule synthétique → variante exacte → panier → destination/devis calculé depuis
offre et tarif synthétiques → checkout public invité → SDK transportFAKE → liaison
SQL → receipt en attente → webhook synthétique signé localement → commande unique
payée en test → fournisseur/agent corrects → préparation HyperSKU INTERNE figée et
non transmissible → expédition/suivi SIM → lookup public expurgé.

Mauvais propriétaire, Bearer invalide, prix/acteur injectés, nouveaux request_key,
deux devis du même panier, webhook invalide/répété et compteurs de création sont
contrôlés. Aucune commande fournisseur ni diminution de stock réel n'en résulte.

## Blocages qui empêchent encore le lancement

**CODEX / INTERFACE.** Cart.jsx conserve le checkout historique. Aucun formulaire
adresse/mode de livraison ni sélecteur nouveau n'est autorisé à ce point. Une
question d'autorisation pour le formulaire minimal est en attente. Il faut relier
ces données aux tarifs réellement disponibles, sans valeur de livraison inventée,
et tester le parcours UI complet. Les produits multivariantes restent refusés en
l'absence de choix explicite. Aucun ajout visuel effectué.

**STRIPE.** Trois anciennes sessions sandbox restent expired/unpaid d'après leur
dernière lecture fournisseur. Aucune nouvelle session créée pendant ce lot. Le DOM
de l'ancienne page a répondu une fois, puis reload/focus/onglet neuf ont échoué.
Inventaire accessible ne vaut pas navigateur fonctionnel. Ne pas contourner par
un endpoint caché ou un faux événement pour fabriquer un succès de paiement.

**FOURNISSEURS / HYPERSKU.** Snapshot privé relu, daté25/10à05:41+01 :40 lignes,
0 entièrement vérifiée,40 bloquées,0 offre sélectionnée/fitment/prix/portFrance/
marge/mapping HyperSKU confirmé. Dix-huit SKU proposés ne sont pas des choix
validés. Contrat/API/conditions HyperSKU, preuves de montage et droits sur les
fichiers existants restent nécessaires. Aucun message externe envoyé.

**ADMINISTRATEUR.** Accord pour le seul ajout UI minimal, choix d'offres/agent humain,
fiscalité/conditions légales/marge minimale et autorisations commerciales. Ne donner
aucune clé secrète dans la conversation. Aucune activation live ni publication sans
autorisation distincte.

**RECETTE / CODE RESTANT.** PostgreSQL multiconnexion et Auth réels isolés, journal
durable/rapprochement des états financiers incertains et remboursements quoted dans
un lot transactionnel distinct. Inspection seule ne permet ni remboursement ni
libération présumée de stock. Aucun exécutable Docker/PostgreSQL trouvé dans le PATH
du poste lors de ce contrôle (cela ne prouve pas une absence sur tout le disque).

## Reprise exacte

Lire PROGRESS, BLOCKERS, QA_REPORT et le contrat CUSTOMER_CHECKOUT. Vérifier HEAD,
diff et processus/ports avant toute recette. Compilation et contre173 sont
terminées, ne pas les recommencer sans nouveau changement pertinent. Après accord UI, raccorder adresse/mode/variante
aux endpoints existants sans refonte. Nouvelle sandbox seulement lorsque le navigateur
peut réellement terminer le Checkout ; exiger le webhook authentique et la commande
unique avant approbation. Ne pas étendre automatiquement les droits ou activer le live.
