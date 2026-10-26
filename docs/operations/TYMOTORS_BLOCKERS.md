# PHOENIX — blocages explicites

| ID | Statut | Responsable | Preuve / impact | Action attendue |
|---|---|---|---|---|
| IMG_POSITIVE_GATE | APPROVED local | Codex / auditeur | Correction positive par fichier + SQL98, HTTP557 ; refus/révocation/territoire/expiration vérifiés ; aucune photo modifiée | Ne pas confondre contrôle technique avec obtention des permissions des 40 produits |
| STRIPE_ACCESS | En test isolé, paiement BLOCKED jusqu'à preuve | Codex / administrateur | Connecteur sans link_id ; alternative officielle CLI a créé sandbox anonyme, auth et lecture réseau Checkout SDK réussies. Pas de clé live ; solde inaccessible selon permissions | Terminer vrai Checkout test/webhook. Profil temporaire hors dépôt ; revendication humaine pour persistance si nécessaire, aucune clé en conversation |
| HYPERSKU_API | BLOCKED | HyperSKU / administrateur | OpenAPIannoncée mais contrat endpoints/auth/payload/notifications/sandbox/éligibilité absent ducode ; loginhistorique12/10 ne prouve pas accèsactuel | Obtenir documentation/accèsautorisés ; préparationmanuellelocaleenattendant, aucunenvoi |
| COMMERCIAL_5 | BLOCKED | Fournisseurs |5propositionsSoyinnonretenues, 0devis/portFrance/droits/fitmentconfirmé | RéponsesdatéesSKUfinition/montage/photo/devise/MOQ/port/Incoterm/garantie ; pasnouvelenvoisansautorisation |
| OWNER_TERMS | BLOCKED | Administrateur | Agent réel, fiscalité, marge minimale, légal/conditions nonconfirmés | Désigner/valider ; aucunprixpublicmodifié |
| PAYMENT_RECONCILE | PARTIEL — lot financier restant | Codex | Inspection privée test APPROVED local après145 contre-tests indépendants ; aucun rapprochement financier automatique, remboursements quoted toujours refusés. Les réservations held sont une protection intentionnelle | Implémenter journal durable/transaction de rapprochement et remboursements quoted dans un lot séparé ; aucun retry aveugle, faux événement ou libération présumée |
| HOSTED_CONCURRENCY | BLOCKED | Environnementisolé / Codex | PGlitesinglesession, pasPostgreSQLmulticonnexion/GoTrue/PostgRESTréel | Recetteisoléeautorisée, pasmigrationproduction |
| SIM_AGGREGATE_MULTIPARCEL | APPROVED local SIM uniquement | Codex / auditeur | Chef et auditeur : 91 assertions HTTP chacun, deux fournisseurs/agents/colis synthétiques ; régression557 PASS ; statut réel requires_review conservé | Pas de preuve d'expédition réelle ni de condition commerciale déduite |
| SANDBOX_BROWSER | BLOCKED | Accès navigateur | Checkout réel de test créé/bindé ; page test35EUR visible, puis trois opérations CUA sans réponse avant carte ; pas de paiement achevé | Rétablir navigateur intégré puis inspecter état existant/rapport privé avant reprise ; pas de nouvelle charge aveugle |
| QA_RESUMPTION | RESOLVED pour ce lot | Auditeur | Reprise exécutée :35 tests ciblés et91 assertions HTTP indépendants PASS ; guard live45 tests et smoke1 PASS | Ne pas en déduire une disponibilité permanente du service ni une validation commerciale |
| LIVE_LEGACY_GATE | APPROVED local | Codex / auditeur | Checkout legacy live interdit avant panier/RPC/provider ; aucune activation par un produit active/verified ni un simple flag légal. Testmode conservé, contre-audit45 tests et smoke FAKE1 PASS | Activer la vente réelle exigera un futur lot revu et les preuves commerciales, pas un contournement de ce verrou |

Les blocages d'un article sont cumulatifs et distincts de sa publication. Aucun fournisseur ni compte ne doit être sollicité ou modifié pour les masquer.

### Complément reprise du25octobre

| ID | Statut | Responsable | Preuve / impact | Action attendue |
|---|---|---|---|---|
| CUSTOMER_UI_DESTINATION | Implémenté/testé local, revue finale en attente | Codex / auditeur | Formulaire France et devis propriétaire ;103 ciblés,669 frontend globaux,1493 backend,209 HTTP/SQL FAKE,build et navigateur final PASS. A→B→A/quantité invalident bien le devis | Dernière correction A→B→A à contre-auditer après disponibilité du service ; aucun sélecteur de variante ou déploiement autorisé par cet accord |
| CUSTOMER_CHECKOUT_BRIDGE | APPROVED local simulé, UI BLOCKED | Codex / auditeur |1452 pytest et583 frontend chef PASS,buildCI/lintPASS ;173 HTTP/SQL finaux chef ET indépendants PASS ;137 SQL clients/66admin PASS. Pont propriétaire, verrou panier inter-devis et receipt pré-webhook | Collecte adresse/mode/choix de variante après accord ; Stripe réel/GoTrue/PostgREST/concurrence PostgreSQL restent non prouvés |
| SANDBOX_BROWSER | PARTIEL, accès à reconfirmer avant paiement | Codex | Inventaire et DOM ancien Checkout répondent à la reprise ; les3 anciennes sessions sont expired/unpaid selon lecture fournisseur précédente | Ne pas payer une session expirée. Nouvelle recette uniquement sur SQL jetable/session test identifiée, après libération des ports |

Dernier constat navigateur : DOM ponctuel puis reload/focus CDP/onglet neuf en
échec. **BLOCKED pour interaction Checkout**, pas partiellement validé pour un
paiement. Aucun nouveau Checkout ni carte soumis dans ce lot. Les recettes locales
sont terminées et leurs processus/ports sont fermés, pas de surveillance en cours.

### Actualisation du26octobre

Le navigateur intégré fonctionne pour le nouveau panier local : calcul, devis,
invalidation et captures contrôlés sur build final. L'ancien blocage navigateur
est donc historique, pas une preuve d'échec actuel. Aucun nouveau Checkout Stripe
réseau n'a encore été créé/payé : la recette réelle reste à reprendre séparément
avec son profil sandbox et son listener signés, sans confondre la probeFAKE avec
un paiement. Dernière contre-revue du correctif A→B→A non effectuée : le sous-agent
auditeur a atteint sa limite de service ; aucun contournement ni automatisation.
Voir TYMOTORS_DELIVERY_FORM_QA_2026-10-26.md pour l'état final et la reprise.
