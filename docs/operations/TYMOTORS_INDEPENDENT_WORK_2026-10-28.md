# Paiements, cinq pilotes et informations commerciales —28octobre2026

## Périmètre demandé

Avancer tout ce qui ne dépend pas des mails fournisseurs attendus. Conserver
design, photos, prix publics, données et services de production. Pas d'activation
Stripe live, commande réelle, achat, communication externe ou déploiement.
SIRET et statut juridique restent hors de ce lot ; aucune valeur inventée.

## Paiements et fonctionnement

Trois défauts corrigés localement :

1. Expiration Checkout, échec asynchrone ou échec de PaymentIntent : après
   signature et mode test contrôlés, reçu durable minimal dans stripe_events.
   Identité événement/type/objet contrôlée ; doublons et collisions traités,
   concurrence d'insertion relue une seule fois. Une panne de stockage renvoie
   un échec HTTP et n'acquitte pas faussement l'événement. Ni métadonnées brutes,
   données client, email ou erreur fournisseur ne sont conservés dans ce reçu.
   Le reçu ne déclare pas que le paiement est définitivement absent ; réservations,
   finances et tâches restent inchangées jusqu'au rapprochement approprié.
2. Les deux entrées publiques Checkout refusent maintenant la création en
   absence de secret de signature webhook. Aucun appel de création fournisseur
   ne peut alors être effectué. Les gardes live existantes restent fermées.
3. Reprise d'email legacy ambiguë : revue manuelle au lieu d'un renvoi risqué.
   Seule une preuve durable d'échec avant transport reste reprenable, sous
   UPDATE conditionnel atomique. L'API indique le résultat réel. La reprise
   d'un accusé de rétractation avait également un mauvais appel du template :
   corrigé et testé avec texte conservé et HTML échappé.

L'adaptateur chiffré variante/devis et son règlement restent sandbox-only.
Ces corrections ne constituent pas une implémentation Stripe live approuvée.
Le passage live exige encore un lot explicitement revu : déclinaison des
contrats/transactions test vers la production, configuration sécurisée du compte
et du webhook, puis recette hébergée et décision d'activation. Ne jamais retirer
les gardes pour simuler cette préparation.

## Preuves exécutées

- Suite backend finale :2230pytest PASS,22,66s ; avertissement Starlette/httpx
  préexistant. Les tests positifs existants déclarent désormais explicitement
  leur signature synthétique ; le cas signature manquante refuse avant création.
- Recette propriétaire HTTP/SQL :655contrôles du parcours synthétique existant
  PASS, puis42contrôles de reçus négatifs PASS. Signature SDK réelle avec secret
  local synthétique, moteur PostgreSQL/PGlite jetable, transport Stripe FAKE.
  Aucun paiement Stripe réel, nouvel événement de la sandbox distante, achat,
  email SMTP/Brevo ou accès production. Les ports8765/8766 ont été refermés.
- Première tentative de sous-probe rejetée : requête de snapshot SQL de test
  invalide. Helper corrigé vers row_to_json, puis deuxième recette entière PASS.
- Commande de reprise vérifiable :
  `python -m tests.run_commerce_pipeline --node <node-existant> --probe-module tests.commerce_failure_receipt_http_probe`.
  Ne pas relancer l'ancien paiement distant26octobre, déjà remboursé27octobre.

## Cinq pilotes

Fiches et modèles locaux réellement produits dans
backend/data/phoenix-2026-10-28-pilots-prep-v1/. Voir
TYMOTORS_PILOTS_PREP_2026-10-28.md. Les textes déjà prudents ont été conservés.
Références et déclarations Soyin sont des candidats, jamais des correspondances
retenues. Cinq previews VariantInput valides uniquement en draft, stock0,
non vérifiées, sans compatibilités actives. Offres et tarifs volontairement
incomplets, import interdit. Prix et leur date du27octobre conservés.

Audit indépendant terminé :139tests ciblés PASS, cinq identités et sources
concordantes, APPROVED LOCAL pour la préparation. Zéro pilote validé pour vente.

## Informations commerciales

Lot frontend : pages Livraison/FAQ/Contact/CGV/confidentialité/rétractation.
Promesses de frais, gratuité, destinations, délais ou suivi non démontrées
retirées. Contact et mentions partagent la configuration publique autorisée.
Réponse de rétractation validée avant accusé ; double soumission bloquée,
alternative au formulaire expliquée. Aucun titulaire de droit photo sollicité.

Chef : formulation orientée client, sans exposer les détails internes de
simulation ou de connexion logistique. Structure/styles/photographies conservés.
Contrôle AST : mêmes81élémentsJSX et29attributsstyle/classes pour LegalPages,
114/87 pour SupportPages. Sources juridiques et limites détaillées dans le
rapport frontend docs/COMMERCIAL_INFORMATION_2026-10-28.md.

703tests/43suites frontend PASS avant l'allègement final du texte ; après cette
retouche,50tests/4suites concernés PASS, ESLint ciblé et AST PASS. Build optimisé
contrôlé séparément dans le journal de progression.

Hors SIRET/statut, restent notamment à fournir ou décider : coordonnées réelles
du vendeur/SAV, mention TVA, hébergeurs/directeur, médiateur effectivement choisi,
adresse et coûts de retour, conditions d'import/livraison, facturation définitive,
remise durable du contrat et encadré garanties applicable. Les champs inconnus
restent vides ; une conformité globale n'est pas déclarée.

## Statut et reprise

La lecture de la configuration publique du site a confirmé stripe_mode=test et
legal_ready=false, champs d'identité légale vides. Lecture seule, aucun secret.
Le site publié ne contient pas automatiquement ces correctifs locaux.

Les contre-audits ont été interrompus puis repris avec les mêmes agents après
vérification officielle de la disponibilité ordinaire. Aucun nouveau modèle,
compte, reset ou crédit n'a été utilisé pour contourner une limite.

Résultats indépendants finaux : backend177tests ciblés PASS, sources finales
stagées contrôlées et empreintes stables, APPROVED LOCAL ; frontend50tests/
4suites PASS, AST/styles/images identiques à HEAD, APPROVED LOCAL. Les pilotes
avaient déjà été approuvés pour leur préparation seulement. Le Chef accepte
ces trois lots locaux sur ces preuves, sans validation live ou commerciale.
Aucune comparaison pixel mobile ou concurrence hébergée n'est revendiquée.

Avant une publication : audit final, revue des migrations/diff réel sur
l'environnement retenu, validation explicite du propriétaire. Avant vente :
offres/références/livraison et identité commerciale confirmées, recette réelle
pilote sous budget autorisé. Aucune surveillance permanente n'est installée.

## Documentation technique officielle consultée

- [Stripe — webhooks](https://docs.stripe.com/webhooks)
- [Stripe — préparation live](https://docs.stripe.com/get-started/checklist/go-live)
- [Stripe — protection des clés](https://docs.stripe.com/keys-best-practices)

Les anciens liens skill references/payments.md et references/security.md ont
répondu404 ; les pages officielles ci-dessus ont servi de référence effective.
