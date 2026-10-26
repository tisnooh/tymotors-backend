# TYMotors — test client réel en sandbox et fournisseur factice

## Demande et limites

Demande du propriétaire : test complet, puis achat fournisseur factice pour
comprendre les étapes et le déclencheur. Aucune dépense réelle, commande fournisseur
réelle, activation commerciale, publication, photographie ou design modifiés.

Scénario : panier du frontend compilé existant → adresse/livraison → devis
propriétaire → Checkout Stripe sandbox → webhook signé → commande unique → tâche
agent → dossier HyperSKU interne → traitement/suivi SIM. Un SKU synthétique,
véhicule BMW/F30 de fixture et coûts synthétiques : pas de produit réel validé.

## Résultat observé

| Étape | Preuve | Portée |
|---|---|---|
| Adresse et livraison dans le vrai Cart |Client Test, adresse fictive Paris75001 ; mode tracked5EUR ; confirmation total35EUR |Navigateur et API loopback, données de test |
| Paiement Stripe |Session réelle cs_test_a1UcSUzodOkUs1taP6vCjbcCzl8CacaMR4umSL0QHLzl2m9pHE9dy8cAjE ; carte officielle4242 ; page marquée sandbox |Réseau Stripe test, zéro argent réel |
| Lecture SDK après paiement |status=complete, payment_status=paid, livemode=false, total3500EURcentimes, métadonnée commande correspondante |Lecture réseau séparée de la notification |
| Notification financière |signed_webhook_verified=true, actual_stripe_test_payment=true dans rapport du runner |Vrai webhook Stripe transmis par CLI officielle ; pas HMAC synthétique fabriqué |
| Commande |TY-20261026-F670E21F ; id d15baf2b-a8ff-46b4-9cb6-b3510e8da4d9 ; paid_order_count=1 |SQL jetable |
| Retour client |Page Paiement confirmé,35EUR, mention aucun débit réel ni expédition |Navigateur, sans changement du composant OrderSuccess |
| Agent |task_count=1 ; agent69b45266-313b-46c0-a0f6-d7e80ee458f5 ; offre/variante/tarif exacts contrôlés |Attribution backend réelle sur données synthétiques |
| Dossier HyperSKU |110b0bfb-98f8-4140-a8e7-6157efc923a4 ; awaiting_human_review ; external_send_allowed=false ; expenses_authorized=false |Préparation interne uniquement, non certifiée pour import fournisseur |
| Achat factice |SOURCE-SANDBOX-SYNTHETIC-bd4314d799, variante Synthetic exact black, quantité1 ; coût10EUR+port2EUR fictifs |Hypothèses de fixture, PAS un devis fournisseur confirmé |
| Logistique factice |received_by_agent → quality_checked → shipped → delivered ; chaque transition rejouée identiquement sans doublon |SIM uniquement ; suivi SIM-SUPPLIER-DRY-d15baf2ba8 |
| Suivi client |Page montre Paiement de test confirmé puis les quatre événements marqués Simulation/aucune expédition réelle |Le statut réel reste requires_review, pas livré |
| Réessai paiement déjà payé |Retour paid, même order_id, url=null ;1commande,1tâche,0supplier_orders |Aucun nouveau paiement fournisseur ou commande dupliquée |

Le dossier privé du run est
`C:/Users/utilisateur/.codex/stripe-phoenix-private/recette-2026-10-26-panier-fournisseur/` :
stripe-sandbox-result.json, disposable-state.json et fournisseur-dry-run.json.
Le dernier JSON est explicitement NON ENVOYÉ et N'EST PAS un modèle d'import
HyperSKU. Aucun secret dans Git, les captures ou ces rapports. Profil CLI dédié
tymotors-phoenix-isolated/compte acct_1UU8fq7oQBUfbTTb, sans clé live, vérifié avant
le run. La vérification sur le fichier config Stripe par défaut était négative ;
le vrai profil était dans le dossier privé documenté, pas supprimé/expiré.

## Ce qui déclenche réellement chaque étape

1. Le client confirme le panier et paie sur Stripe. Le retour navigateur seul
   ne règle pas la commande ; le webhook signé payé déclenche le règlement local
   et la création de la tâche de l'agent.
2. L'agent contrôle référence, variante, compatibilité, prix fournisseur, transport,
   adresse et association HyperSKU. Dans ce test, le runner joue l'action agent
   Préparer HyperSKU via l'endpoint administrateur existant ; ce n'est PAS une
   automatisation permanente ni une transmission fournisseur.
3. Pour une vraie commande, il faudra une correspondance HyperSKU réelle et un
   canal validé : intégration officielle ou import manuel au format du prestataire.
   La connexion au site HyperSKU ne connecte pas à elle seule TYMotors à son API.
4. Écran HyperSKU observé en lecture seule : Order List → Pending payment,
   More → Import File, boutons Sync Orders et Pay Together présents. Résultats
   affichés0 dans les filtres/date de cette vue ; aucune importation ni synchro
   déclenchée. Le menu d'import est identifié, son schéma de fichier n'est pas
   certifié par ce constat. Ne jamais importer notre JSON synthétique comme une
   commande réelle.
5. Après réception/import autorisé, vérifier la commande dans Pending payment,
   contrôler les références et la livraison. **Pay Together et le paiement
   fournisseur constituent l'étape financière qui déclenche le traitement réel
   chez HyperSKU.** Cette action n'a PAS été exécutée.
6. Récupérer ensuite les véritables statuts et numéros de suivi et les relier à
   la commande TYMotors. Cette liaison externe et l'expédition réelle ne sont pas
   prouvées par les événements SIM de ce test.

Documentation officielle consultée le26octobre :
[HyperSKU — traitement après une vente](https://support.hypersku.com/en/articles/2941706-fulfill-order-once-make-a-sale),
[HyperSKU — démarrage/intégration et import manuel](https://support.hypersku.com/en/articles/2941652-what-s-hypersku-how-to-sign-up-and-get-started),
[Stripe — fulfillment et webhook](https://docs.stripe.com/checkout/fulfillment),
[Stripe — cartes de test](https://docs.stripe.com/testing).
La page de référence Stripe /references/payments a répondu404 ; la référence
officielle fulfillment a été lue via CLI1.55.1, sans suivre ses suggestions de
reconfiguration automatique. Aucune dépendance ni API version mise à niveau.

## Modifications techniques de ce lot

Uniquement le dispositif de recette dans tests/ : mode --customer --browser-cart
prépare un panier sans devis/adresse/paiement ; la vraie UI crée le devis puis
la session. Bootstrap local explicite, chemins assets/receipt/tracking en GET
dans l'allowlist du serveur sandbox. Ces routes de test ne sont pas déployées.
Attente bornée du paiement, capture du binding unique et contrôle montant,
fournisseur/variante/livraison/agent. Le fichier privé REVIEW_DONE termine la revue
après paiement ; tous les enfants possédés sont arrêtés en finally.

75 tests ciblés PASS, dont4nouveaux de garde de harness : préparation sans
paiement, absence de retry, doublons refusés, scope navigateur/loopback et
interdiction legacy/live. Nouveau finish_supplier_dry_run exécuté avec succès
sur le paiement sandbox ci-dessus : transitions SIM seulement,0commande réelle.
Une première requête de diagnostic SQL a échoué à cause de l'interpolation
PowerShell des paramètres$1/$2 ; la vérification a été rejouée avec chaîne littérale
et est passée. Il ne s'agissait pas d'un échec du paiement ou de la commande.

Premier global après la recette :1496PASS/1échec, le nouveau test de scope
importait un deuxième serveur complet dans un sous-processus et dépassait30s sur
ce poste sous pression mémoire. Pas de timeout augmenté : politique de scope
extraite en fonction pure, testée directement sans serveur/environnement modifiés.
Cette extraction test-only est postérieure au paiement réussi ; aucun code
applicatif, transport Stripe ou contrat financier n'a été changé. Revue et suite
globale finale distinctes, ne pas masquer le premier passage échoué.

Snapshot final relu après arrêt :1commande paid/requires_review,1tâche SIM
delivered,1événement de paiement signé,1préparation awaiting_human_review avec
external_send_allowed=false et expenses_authorized=false. Runner sorti0 ; aucun
listener8765/8766 après nettoyage. Pas de tâche permanente en arrière-plan.

Captures hors dépôt : stripe-paiement-confirme-sandbox-2026-10-26.jpg,
stripe-checkout-sandbox-2026-10-26.jpg, suivi-fournisseur-simulation-2026-10-26.jpg,
hypersku-etapes-sans-achat-2026-10-26.jpg, dans le dossier de visualisations du chat.

## Décision

**Prouvé par exécution :** parcours navigateur Cart → Stripe sandbox payé → vrai
webhook → commande unique → agent → préparation interne et suivi SIM.
**NON PROUVÉ / BLOQUÉ :** réception d'une commande par HyperSKU, achat fournisseur,
vraie expédition, offre commerciale,40articles et5pilotes validés, concurrence
PostgreSQL/GoTrue/PostgREST hébergés, revue indépendante finale et production.
L'auditeur est indisponible après limite de service ; aucun nouvel agent créé
pour contourner cette limite. Le succès d'exécution n'est pas une approbation de
mise en production. Aucune modification frontend/design/photos/prix publics,
aucun achat, message fournisseur, import ou paiement HyperSKU.

Dernier global après extraction de la politique pure :**1497PASS**,180,33s,
exit0, un avertissement Starlette/httpx préexistant. Compilation Python des six
scripts du lot et diff --check PASS. Aucun fichier app/, server.py, migration ou
frontend modifié. Ce scénario réseau est positif uniquement ; refus,3DS,
remboursements et incidents fournisseur ne sont pas tous retestés en réseau par
cette exécution. Les tests unitaires/simulés antérieurs restent distincts.
