# HyperSKU — configuration, preuves et dépendances

## Périmètre du 26 octobre

Demande : rendre le chemin HyperSKU fonctionnel. Branche de travail existante
`codex/commerce-workflows`, sans publication, achat, prix public, photographie ou
modification visuelle. Les deux documents du lot courriels déjà modifiés sont
conservés. La configuration d'un transport API ne doit pas être inventée.

## Contrôle réel du compte et de la documentation

- Session web HyperSKU authentifiée, rôle Administrator, relue dans le navigateur.
- Store Settings : aucune boutique liée visible. Pas de Store ID observé.
- Applications : fonctionnalités proposées (Consolidation, DIY Sourced Orders,
  etc.), sans méthode Open API identifiée dans cette page. Aucune application
  ajoutée, aucune clé créée, aucune permission ou condition contractuelle acceptée.
- My Products : « No data ». Cela ne prouve pas l'absence universelle de produits
  dans toutes les autres listes du compte.
- Smart Sourcing : Pending sourcing affiche « No data ». Le passage à Quote
  created n'a pas été confirmé : deux interactions CDP puis une alternative
  souris ont échoué après diagnostic. Ne pas annoncer sa liste vide.
- Chat existant relu : réponse de Lexi, support général et fonctionnalités
  dédiées liées à la croissance du volume. Aucun contrat API, SKU, devis France
  ou accord sur le flux fournisseur externe fourni dans cette réponse. L'heure
  affichée dans le fil ne suffit pas à dater précisément ce message.
- Recherche Gmail `in:anywhere after:2026/10/25 -from:me -in:trash
  {from:hypersku.com from:etailerhub.com}` : zéro résultat, pagination terminée.
  Cela ne prouve pas l'absence de réponse par un autre domaine/canal.
- La relance du 26 octobre à 08:31 UTC est déjà envoyée et vérifiée. Aucun
  second message, demande de sourcing, upload, import, Sync ou Pay Together exécuté.

Sources officielles relues :

- [Open API et import alternatif](https://support.hypersku.com/en/articles/2941652-what-s-hypersku-how-to-sign-up-and-get-started) : existence d'une Open API pour boutiques personnalisées, sans contrat technique d'authentification/endpoints sur cette page.
- [Import Excel](https://support.hypersku.com/en/articles/3297862-import-orders-manually-by-uploading-excels) : modèle du compte, SKU distinct par variante, province et informations d'adresse. Un fichier ou un SKU interne TYMotors n'est pas une référence d'import certifiée.

## Correction technique locale

Migration créée avec la CLI Supabase installée :
`20261026130757_hypersku_preparation_revalidation.sql`. Elle modifie uniquement la
fonction existante `commerce_prepare_hypersku_task`, avec vérification des ancres
de sa définition pour refuser une dérive non revue. Pas de nouvelle architecture,
table, transport fournisseur ou modification des droits SQL.

Défaut : un appel répété retournait un dossier existant avant de revalider les
autorisations courantes. Son existence ne doit jamais devenir une autorisation
permanente de traitement.

Correction : avant tout retour, y compris répétition, vérifier les éléments
existants (commande test payée/non annulée/non remboursée, mapping exact non expiré,
offre et tarif inchangés, droits images, agent actif et même affectation), puis :

- Disponibilité/quantité fournisseur et validité des conditions/change.
- Variante exacte active/vérifiée, même identité et caractéristiques gelées.
- Revue humaine de compatibilité conservée sur la commande : préparer son dossier
  de revue interne ne lève pas ce verrou et n'autorise aucune transmission.
- Associations et règles véhicule identiques aux preuves gelées du devis.
- Entités marque, modèle et génération également identiques au contexte gelé.
- Mapping d'une préparation existante identique à son instantané immuable.

Une nouvelle valeur de prix public ou de stock retail ne réécrit pas le montant
payé. Les contrôles fournisseur restent distincts. Aucun dossier historique n'est
modifié pour paraître envoyé ou validé. Les booléens `external_send_allowed=false`,
`expenses_authorized=false`, `certified_provider_import=false` sont conservés.

## QA

- Premier passage Chef : 635 assertions HTTP/SQL PASS sur cinq variantes
  synthétiques, transport Stripe FAKE, zéro fournisseur réel, zéro production.
- Contre-audit statique : premier résultat REJECTED, données de taxonomie véhicule
  non comparées. Marque/modèle/génération ajoutés avec contre-tests. Une première
  recette finale a échoué : la garde ajoutée sur requires_compatibility_review
  empêchait même la préparation du dossier de revue, car ce drapeau est vrai par
  construction dans toutes les commandes sandbox. Cette garde supplémentaire
  incorrecte est retirée, pas le verrou métier existant : le drapeau reste vrai,
  le dossier reste en attente humaine et aucune transmission n'est possible.
  Le premier passage ne vaut pas validation de cette version.
- Recette finale corrigée du Chef : **655 assertions HTTP/SQL PASS**, cinq
  variantes synthétiques, Stripe FAKE, zéro commande fournisseur réelle et zéro
  accès production. Le runner possède et nettoie ses deux processus jetables.
- Première exécution indépendante :635 PASS sur la version antérieure, non
  substituable à la recette finale. **Contre-recette indépendante finale :655
  PASS, sortie0**, trois hashes des fichiers migration/probe/bootstrap identiques
  avant/après, aucune écoute8765/8766 restante. Verdict APPROVED LOCAL pour la
  préparation/revalidation interne, pas pour une connexion fournisseur.
- Premier pytest global :1505 PASS /18 erreurs de préparation des tests
  quote_service. La permission photo synthétique héritée de l'horloge fixe du
  moteur expirait le26octobre à12hUTC, tandis que les tests service utilisent
  l'heure réelle. Correction exclusivement dans la fixture service (validités
  relatives et date de vérification cohérente), sans changer le moteur applicatif.
  Nouveau contre-test : une permission expirée doit toujours donner409 et ne
  stocker aucun devis.20 tests ciblés PASS ; correction relue indépendamment.
- **Pytest global final :1524 PASS**,58,76s, sortie0 ; avertissement
  Starlette/httpx préexistant. Compilation Python et diff --check PASS.
- Aucun fichier frontend/image modifié et aucune permission SQL élargie.
- Concurrence PostgreSQL hébergée et véritable requête API/import HyperSKU non
  testés. Le paiement Stripe sandbox positif antérieur reste un test distinct.

## Conditions de déblocage externe

| Condition | Preuve nécessaire | État / action |
|---|---|---|
| Contrat et accès API | Documentation actuelle fournie par HyperSKU, autorisation du compte, authentification et environnement d'essai | BLOCKED ; demande déjà envoyée. Ne jamais transmettre une clé dans le chat ou la committer. |
| Boutique | Store ID réel et méthode applicable à React/Python | BLOCKED ; ne pas choisir Shopify/WooCommerce fictivement. |
| Références | SKU d'import de chaque variante, correspondance exacte et preuve d'équivalence | BLOCKED ; parent produit, référence de variante et SKU d'import restent distincts. |
| Coûts France | Devis daté, validité, prix, préparation, livraison/taxes, poids et restrictions | BLOCKED ; aucun coût synthétique injecté dans le catalogue. |
| Transfert de destinataire | Champs explicites et autorisation du canal ; pas de nom découpé arbitrairement, province ou téléphone inventés | BLOCKED avant tout upload ; aucune donnée client transmise. |
| Déclenchement fournisseur | Validation humaine, réception/import confirmé, puis dépense autorisée séparément | Aucune commande ou dépense autorisée par ce lot. |
| Exploitation | Confirmation technique du canal puis recette bout en bout et revue des produits | Pas de déploiement ni activation commerciale dans ce lot. |

Le dossier interne fonctionne uniquement dans son périmètre sandbox. La connexion
HyperSKU réelle reste BLOCKED. Un login web et des tests locaux ne constituent
ni une connexion API, ni une expédition, ni cinq produits commercialement validés.

## Reprise précise

1. Recette et contre-audit locaux terminés ; ne pas recommencer sans changement
   pertinent. Garder la migration non déployée jusqu'à validation de publication.
2. Les préparations restent des dossiers de revue sans transfert fournisseur.
3. Lire le fil HyperSKU existant avant toute action fournisseur supplémentaire.
4. Quand le contrat et les références sont fournis, implémenter le canal documenté
   et configurer les secrets dans l'environnement isolé, avec accord explicite
   pour toute nouvelle permission ou transmission sensible.
5. Tester d'abord réception/idempotence/erreurs dans l'environnement officiellement
   disponible ; ne pas prétendre disposer d'une sandbox HyperSKU non confirmée.
