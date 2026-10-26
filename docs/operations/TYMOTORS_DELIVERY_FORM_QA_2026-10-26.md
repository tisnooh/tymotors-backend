# Formulaire livraison — recette locale du26octobre2026

## Autorisation et périmètre

Accord humain : « Oui, ajouter les champs de livraison avec les styles actuels ».
Branche dédiée codex/commerce-workflows dans les deux worktrees scp-release.
Bases backend a17ba1e/frontend cbf30b3. Aucun push, déploiement, tarif public,
photo ou sélecteur de variante autorisé par cet accord.

Ajout limité à Livraison dans Cart : adresse France conservée en mémoire,
calcul explicite des modes vérifiés puis confirmation d'un devis propriétaire.
Le récapitulatif et le bouton existants exploitent ce devis, jamais un tarif
inventé. Le checkout reste sandbox ; un résultat réseau inconnu ne déclenche
aucune nouvelle tentative automatique.

## Preuves et corrections

| Contrôle | Résultat observé |
|---|---|
| Suite backend |1493 PASS, avertissement Starlette/httpx préexistant |
| Contre-tests backend indépendants |41 PASS après rejet/correction authentification et format postal |
| HTTP/SQL invité, données jetables |209 PASS, TVA583 incluse dans3500, livraison500 ; Stripe FAKE |
| Tests frontend ciblés |103 PASS/5suites après correctif A→B→A |
| Suite frontend complète |669 PASS/41suites,63,567s, runInBand/no-cache/testTimeout30000/forceExit |
| Lint fichiers du lot |PASS après remplacement de4globals de test par globalThis |
| CompilationCI |Premier build et rebuild final après correctif A→B→A PASS, exit0 |
| Navigateur sur rebuild final |Calcul5EUR puis devis35EUR, bouton actif ; modification adresse/A→B→A/quantité invalident le devis |
| Variante du panier |Identités exactes et quantité contrôlées ; aucune sélection arbitraire multivariante |
| Images, styles globaux, Navbar |Aucun fichier modifié ; seule nouvelle section livraison et comportements autorisés |

Les1493 backend ont été exécutés avant les derniers changements de harness/docs,
sans nouveau changement de logique backend depuis. Les669 frontend précèdent
uniquement le remplacement équivalent global→globalThis dans deux fichiers tests.
Un dernier ciblé après ce remplacement :31 PASS/2suites,16,649s, exit0.

Rejets non dissimulés :

- Backend : Basic/Authorization vide pouvaient retomber invité ; désormais401
  avant accès au panier sur découverte/create/read. Code postalFR doit comporter
  cinq chiffres ASCII, ce qui ne prouve ni existence ni desserte de l'adresse.
- Frontend : validateur initial ajoutait la TVA au TTC et refusait les underscores
  pourtant permis dans les sessions Stripe. Correctifs revus par l'auditeur,
  cas de TVA non nulle et session avec underscores couverts.
- Navigateur : revenir A→B→A pouvait restaurer une ancienne approbation en mémoire.
  Générations monotones du contexte et du propriétaire ; recalcul efface tout devis
  immédiatement, checkout bloqué pendant requête. Quatre régressions ajoutées.
- Les deux premières tentatives de suite frontend globale ont été interrompues
  sous forte pagination mémoire, dont deux timeouts SearchOverlay30s. Aucun
  résultat global positif déduit de ces passages. La relance finale complète a
  réussi sans changer les timeouts. Aucune fermeture naturelle des handles Jest
  n'est prouvée, car forceExit est utilisé.

## Limites et décision de revue

La dernière revue indépendante a accepté les corrections TTC/session et les
fixtures en lecture statique. L'auditeur a ensuite atteint sa limite de service,
avant contre-exécution209 et avant correctif A→B→A. Aucun autre agent lancé pour
contourner cette limite. **EN ATTENTE DE REVUE INDEPENDANTE FINALE**, pas validation
commerciale ou autorisation de publication.

Les captures à largeur390 testent le formulaire empilé, pas un vrai appareil :
la Navbar existante force le menu bureau d'après l'user-agent même à largeur
étroite sur ordinateur. Aucun correctif de Navbar/design hors périmètre réalisé.
Un contrôle appareil réel reste distinct. La première mesure client/scrollWidth
était380/380, sans débordement horizontal du document.

Le parcours209 utilise la vraie validation de signature SDK sur une clé HMAC
synthétique et des événements locaux : **pas de paiement Stripe réseau**. HyperSKU
reste une préparation interne, sans transmission, dépense ou colis réels. Les
40dossiers/5pilotes restent non validés commercialement selon les preuves connues.

## Reproduction et reprise

Exécuter les gros tests et builds séquentiellement sur ce poste contraint en RAM.
Runner `python -m tests.run_commerce_pipeline --node <Node> --probe-module
tests.commerce_customer_http_probe` : ports8765/8766 propres, enfants possédés et
fermés en finally. Option `--wait-for-browser` uniquement pour cette probe :
panier synthétique supplémentaire et bootstrap http://127.0.0.1:8765/qa-delivery.
Appuyer sur Entrée pour fermer les enfants. Ce bridge n'est pas le serveur déployé.

Build local avec APIloopback, PUBLIC_URL=/qa-assets et BUILD_PATH=.browser-test-build
(ignoré par Git), pas de secret ni variable distante modifiés. Captures privées
dans le dossier de visualisations du chat, hors dépôts. Deuxième probe209 PASS,
recette navigateur finale effectuée : checkout désactivé et notice absente après
A→B→A, puis devis explicite35EUR réobtenu. Quantité2 donne60EUR de sous-total mais
livraison/total à confirmer, paiement bloqué. Aucune navigation vers un faux
Checkout Stripe n'a été tentée pour faire croire à un paiement.

Capture finale ordinateur : cart-delivery-final-desktop-2026-10-26.jpg. Capture
étroite : cart-delivery-final-narrow-2026-10-26.jpg. À390px, conteneur346px et
scrollWidth346px, champs298px : aucun débordement du formulaire. Bandeau bureau
forcé par user-agent existant signalé, pas de validation iPhone/Android.
Viewport réinitialisé, seul onglet de recette créé fermé. Les deux runners
opt-in sont sortis0 après Entrée et aucun listener8765/8766 n'a été retrouvé.
Pas de service ou surveillance restant en arrière-plan.
