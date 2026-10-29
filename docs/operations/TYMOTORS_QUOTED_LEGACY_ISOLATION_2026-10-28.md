# Isolation des commandes à devis et du traitement historique

APPROVED LOCAL, après revue indépendante et recette du Chef. Aucune base hébergée
modifiée, aucun paiement ou achat ; le mode réel reste désactivé.

## Défaut et correction

L'ancien `complete_paid_order` et `ensure_supplier_order` étaient encore capables
de traiter une commande portant `commerce_quote_id`. Le premier pouvait prendre
un raccourci « déjà payé » ; le second reconstruisait les lignes fournisseur depuis
`product_supplier_data`, sans respecter les snapshots variante/offre du devis.

La migration locale `20261028133928_commerce_quoted_legacy_isolation.sql`, créée
avec la CLI Supabase, ajoute deux refus avant effet :

- `complete_paid_order` : après verrouillage et contrôle d'existence, avant le
  retour payé/remboursé et avant stock, panier, ligne ou audit.
- `ensure_supplier_order` : avant création de dossier, lignes et suivi fournisseur.

Le déclencheur de paiement historique n'est ni désactivé ni contourné : un essai
de paiement quoted non-test par cette voie échoue et revient en arrière. Le
parcours sandbox dédié conserve `commerce_settle_test_checkout`. Les commandes
historiques sans devis gardent leur comportement, sans backfill ni réécriture.

## Vérification

Recette du Chef puis même recette indépendante par `commerce_quote_review` :

```powershell
& 'C:/Users/utilisateur/Documents/ChatGPT/TyMotors/backend/.venv/Scripts/python.exe' -m tests.run_commerce_pipeline --node 'C:/Users/utilisateur/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node.exe' --probe-module tests.commerce_legacy_isolation_http_probe
```

- 655 contrôles du parcours synthétique HTTP/SQL passent.
- 30 nouveaux contrôles d'isolation passent : quoted pending/payé, test/non-test,
  refus direct fournisseur, rollback du déclencheur, snapshots protégés identiques,
  absence de commande et permissions/attributs des deux fonctions conservés.
- Les contrôles legacy unquoted test/non-test de la fixture s'exécutent après
  chargement de cette migration et passent aussi.
- Fixtures et sommes fictives, PGlite jetable, transport Stripe FAKE ; signature
  SDK avec secret local synthétique. Aucun encaissement distant ni fournisseur.
- Premier probe refusé par le trigger d'identité du devis : fixture sans panier
  corrigée en ajoutant panier/source cohérents, sans retirer aucun garde-fou.
- Ports8765/8766 libérés après chaque exécution.

La migration reprend les définitions installées, compte exactement les ancres
attendues et échoue en cas de dérive. `CREATE OR REPLACE` conserve identités et
ACL ; les tests vérifient invoker/definer, search_path et absence d'EXECUTE pour
anon/authenticated. Aucune nouvelle fonction ou permission publique ajoutée.

## Limites et suite

Cette isolation empêche un mauvais chemin ; elle ne fournit pas le règlement
production ni le fulfillment variant-aware. Un futur chemin live devra gérer
explicitement le déclencheur historique, les réservations, le compte/mode figés,
la réconciliation, les remboursements et les notifications transactionnelles.

PGlite n'est pas une preuve de concurrence multi-connexion PostgreSQL native.
Pas de comparaison visuelle requise : aucun frontend, CSS, photo ou prix modifié.
La publication de la migration et la recette hébergée restent non effectuées.
