# TYMotors — infrastructure commerciale, travail en cours

Objectif de référence : `goal-objective.md`, pièce jointe dfd4ec4e-fd5d-4b48-ad5c-dcf11380f77e, lu intégralement le 23 octobre 2026.

## Périmètre et garde-fous

- Branche dédiée `codex/commerce-workflows` dans les deux dépôts de release.
- Base backend `d391128f9d275f67977458b630c4970c9ec05042`, frontend `b5847e590a79b389cd33303e3fc3b2b3c89baa0f`.
- Checkouts originaux sales préservés. Aucun déploiement, achat, envoi fournisseur ni changement de prix public autorisé par ce chantier.
- Design, composants graphiques, CSS, animations, cadrages, photographies et galeries inchangés. Les besoins de nouveaux contrôles d'interface restent soumis à autorisation.
- Aucune preuve fournisseur manquante ne devient un fait confirmé. Les 40 dossiers restent non validés commercialement.
- Référence visuelle initiale : sources frontend au commit ci-dessus, notamment pages Home/Catalog/ProductDetail/Cart/OrderSuccess/compte et admin existante, styles et public/images. Aucune comparaison navigateur réussie revendiquée à ce stade.

## Phases et critères de preuve

| Phase | Travail requis | Preuve attendue | État |
| --- | --- | --- | --- |
| 1 | Audit existant | Contrats API, migrations, panier, paiement et suivi inspectés | En cours |
| 2 | Données des 40 articles | Suivi unique, origine des affirmations, lacunes explicites | Dossiers audités ; validations fournisseurs manquantes |
| 3 | Fournisseurs et variantes | Plusieurs offres vérifiables par variante, principale/alternatives, contraintes relationnelles | Fondations DB/API locales et tests SQL ; aucun vrai SKU importé ou validé |
| 4 | Compatibilité | Génération/phase/version/équipements, preuve par règle, aucune extension implicite | Socle publié ; rattachement variantes à compléter |
| 5 | Titres et descriptions | Copie reliée aux preuves sans modifier les photos | 9 corrections publiées ; validation commerciale incomplète |
| 6 | Prix et livraison | Centimes entiers, devise/FX/taxes explicites, tarif réel par offre/quantité/destination/mode, refus si incomplet | Devis administratif local testé ; raccordement checkout et tarifs réels manquants |
| 7 | Agents | Sourcing/catalogue/prix/commandes/superviseur, permissions et journal, attribution réelle | Responsables et rôles persistés ; moteur de tâches/attribution commande à développer |
| 8 | Panier et paiement | Variante conservée, prix serveur, commande atomique/idempotente, webhooks signés | Panier variant/véhicule branché et testé localement ; checkout variantes bloqué explicitement en attente de devis/snapshots |
| 9 | Commandes fournisseurs | SKU/variante/conditions figés à la commande, allocation et demande préparée, achat humain | À développer |
| 10 | Synchronisation et suivi | Journal durable, reprise sans doublons, historique immuable, incidents/retours | Socle existant à compléter |
| 11 | Recette complète | Tests 1–9 ci-dessous, DB réelle isolée puis Stripe sandbox autorisé | À faire |
| 12 | Protection visuelle | Aucun changement assets/styles/rendu ; comparaisons mêmes données/états/largeurs si navigateur disponible | À faire |

## Dix tests imposés — aucun succès présumé

1. Un produit, plusieurs variantes, associations fournisseurs exactes.
2. Sélection véhicule : seules compatibilités vérifiées cohérentes.
3. Mise à jour prix fournisseur : coûts et marges recalculés, historique commandes intact.
4. Panier : bonne variante, quantité, prix et véhicule.
5. Paiement de test : commande unique, répétitions/concurrence/échecs sûrs.
6. Attribution : bonne référence fournisseur et conditions immuables.
7. Responsable : tâche accessible à l'agent autorisé, non aux autres.
8. Expédition confirmée : rattachement commande/colis/suivi exact.
9. Indisponibilité ou preuve/tarif expiré : aucune fausse promesse d'achat possible.
10. Design et photographies identiques ; aucun nouveau composant sans accord.

## État de reprise

Le dernier tour était un contrôle de lancement : les réponses API ont confirmé 40 brouillons, 0 actif, 0 vérifié, aucun stock positif, Stripe test et identité légale vide. Ce contrôle apporte des preuves mais n'implémente pas les connexions manquantes.

Lacunes initiales examinées : panier indexé seulement par produit ; tarifs globaux ; rattachement fournisseur au paiement depuis les données courantes ; absence de modèle d'offres/variantes/tâches agents. Les deux premiers lots ci-dessous corrigent une partie de ces lacunes, sans constituer la chaîne complète.

## Checkpoint local — 24 octobre 2026

### Développé

- Cinq tables privées : agents, variantes, offres, tarifs de transport, liens de compatibilité. Administration API protégée, écriture atomique/version optimiste, preuves explicites, journal d'audit, aucune reprise automatique des 40 produits.
- Devis administratif multi-offres : montants entiers, coût rendu, devise/change vérifié et expirant, TVA récupérable non comptée deux fois, taxes de vente distinctes par destination pour marchandise/port, coût de ligne transport une fois, responsable et délais nécessaires. Zéro explicite distinct d'inconnu ; marge avant frais de paiement/exploitation, pas une marge nette.
- Refus des tarifs régionaux cassés/ambigus, des réponses PostgREST tronquées, des preuves expirées, coûts manquants et marges négatives. Comptages exacts et bornes explicites.
- Lignes panier identifiées par produit+variante+véhicule complet ; RPC d'ajout/modification/fusion atomiques, vérification propriétaire, somme de stock entre véhicules, refus de plafonnement silencieux et de suppression ambiguë. Archivage conserve la ligne supprimable et le prix de variante ; jamais substitution au produit de base.
- Panier frontend raccordé aux identifiants de lignes, paramètres de variantes et valeurs serveur. Port inconnu « À calculer », total « À confirmer », bouton existant désactivé si paiement non autorisé. Aucun élément/classe/photo ajouté/remplacé.
- Persistance véhicule : phase, carrosserie, finition, booléens false/null, châssis distinct de la génération. Pas de nouveau sélecteur visuel.
- Édition produit : compatibilités stables, anciennes requêtes sans ID rapprochées seulement si contenu strictement identique et unique, aucune réassociation arbitraire. Suppression liée/ID étranger/déclassement invalide refusés avec rollback.
- Harness SQL reproductible versionné (PGlite0.5.8 verrouillé), installation locale vérifiée par npm ci sans scripts, job CI ajouté mais NON exécuté sur GitHub. Adaptateur local upsert corrigé ; tests SQL ne dépendent plus uniquement d'un runtime ignoré de l'ancien checkout.

### Preuves exécutées

- Suite complète backend finale : 515 tests réussis, une dépréciation préexistante Starlette/httpx. Dernier test ajouté : limites sandbox par ligne cohérentes avec SQL, sans modification du stock réel.
- Suite complète frontend : 35 suites, 534 tests réussis. Build frontend réussi (warning DEP0176 non bloquant), lint ciblé réussi.
- PostgreSQL/PGlite local, runtime verrouillé : 197 contrôles fondations, 42 contrôles panier, 26 contrôles sauvegarde stable ; 66 contrôles SQL historiques réussis avec les trois migrations. Suites partiellement recoupées, ne pas additionner en nombre de cas uniques.
- `tests/commerce_http_probe.py` : 49 assertions réussies sur HTTP → application réelle → pont SQL loopback → PostgreSQL/PGlite. Mise à jour coût, refus version périmée, lignes/variantes distinctes, stock cumulé, ciblage suppression, propriétaire, double claim et archivage vérifiés. Prix du produit de base et nombre de commandes inchangés.
- Authentification du probe : identités synthétiques du serveur de test ; pas de GoTrue ni PostgREST hébergé. Aucun paiement Stripe réel ou de sandbox hébergé exécuté ; le probe vérifie le refus avant création de commande. Pas une preuve de checkout complet ni de concurrence multiconnexion.
- Revue indépendante : défauts index STABLE, cumul stock, règle régionale cachée, code postal vide, troncature et archivage détectés puis corrigés ; approbation du lot pour checkpoint local seulement. 86 tests ciblés et 42 contrôles SQL rejoués par le reviewer, recoupant les suites ci-dessus.
- Comparaisons AST frontend : ProductDetail/ProjectBuilder inchangés en JSX pour le lot véhicule ; Cart/AppContext conservent éléments et classes, hors données/keys/handlers/disabled/textes autorisés. Aucun diff CSS, public/images ou données de substitution photo. Capture de référence de l'accueil public inspectée ; pas de comparaison visuelle complète huit pages/mêmes données revendiquée.

### Reprise exacte — ne pas confondre fondations et livraison finale

1. Persister un devis vérifié/versionné pour une destination confirmée ; recalculer/réserver sous transaction, lier ligne panier et commande aux mêmes variantes/offres/conditions.
2. Remplacer le gate actuel du checkout variantes par la chaîne testée : création atomique/idempotente de commande, instantanés immuables, vérification paiement et destination, conservation historique, allocation fournisseur exacte et tâches au responsable. Le gate doit rester jusqu'à cette preuve.
3. Brancher groupes fournisseurs, demandes de traitement préparées, expéditions confirmées, incidents, retours et journal de synchronisation/retry. Aucun achat/envoi automatique.
4. Identifier les contrôles existants permettant choix de variante et confirmation de destination. Le configurateur n'a pas de contrôle de phase dédié ; aucune phase ne peut être inventée. Tout nouvel écran/contrôle nécessite autorisation visuelle préalable.
5. Recette réelle Stripe sandbox isolée, comparaison visuelle mobile/ordinateur sur les huit pages et vérification GoTrue/PostgREST isolés. Aucun push, migration distante ou publication autorisé dans ce lot.
6. Obtenir les preuves fournisseurs et légales manquantes. Le code ne rend aucun des 40 articles commercialement validé.

## Dépendances externes non terminées

- Validation SKU/variante, compatibilités, disponibilité, coûts/logistique et garanties des fournisseurs.
- Droits photos et logos ; refus SCP respecté par les protections déjà publiées, liens CDN directs restant à révoquer selon le dernier contrôle.
- Identité légale, conditions commerciales et facturation réelle.
- Accès à un environnement Stripe isolé pour recette réelle ; aucun paiement réel.
- Connexion d'un prestataire logistique/agent réel et devis acceptables ; aucune dépense autorisée.

Ne pas conclure que TYMotors est opérationnel tant que les tests et ces dépendances critiques ne sont pas vérifiés.

## Deuxième checkpoint local — devis persistants et commande figée

- API propriétaire `POST/GET /api/cart/quote` : destination structurée, montants serveur seulement, restauration idempotente du même instantané, aucune exposition des coûts/références fournisseur. `checkout_available=false` et `requires_revalidation=true` explicites.
- Moteur regroupé par variante (jusqu'à 100 lignes/2 000 unités) : chaque véhicule vérifié, stock/MOQ/port cumulés sans doubler le transport. Plusieurs variantes du même fournisseur exigent `independent_parcels` confirmé sur les tarifs ; inconnue = refus. EUR explicite panier/produit/variante, bornes monétaires et expirations avec fuseau.
- Contexte SQL cohérent recapturé avant sauvegarde. Changement de prix, conditions, panier ou insertion d'une restriction régionale = refus. Les calculs d'acquisition, fiscalité incluse, port, marge contributive et total sont recomputés indépendamment en base.
- Barrière conservatrice `EXCLUSIVE NOWAIT` courte sur les sources, profils compris. Les cycles identifiés avec les modifications produit et les FK sont traités par un refus immédiat, pas par une attente de ligne sous un verrou de table incompatible. La contention/performance multiconnexion reste à vérifier.
- Devis et instantanés privés immuables. Une seule commande administrative **test/pending/unpaid** par devis, lignes publiques sans coûts nouveaux, références fournisseur/variante/tarif/agent figées dans `commerce_order_lines`. Montants, devise et mode test de la commande protégés. Aucun stock réservé ou débité, aucun Stripe, aucun achat/envoi fournisseur.
- 602 tests Python backend réussis avant le lot suivant. 83 contrôles SQL devis réussis, plus régression 197/42/26 et 66 historiques chargés avec la nouvelle migration. 53 assertions HTTP devis et les 49 précédentes rejouées avec la migration finale. Suites partiellement recoupées, ne pas les additionner en cas uniques.
- Revue indépendante : corrections devise, verrouillage et conservation historique demandées puis approuvées pour ce checkpoint uniquement. Le frontend reste au commit `c3f06c1`, propre et inchangé dans ce lot ; aucune photographie modifiée.
- Documentation détaillée : `COMMERCE_QUOTE_API.md` et `COMMERCE_QUOTES_SCHEMA.md`. Nouveau test SQL ajouté au job CI, mais aucun run GitHub ni publication revendiqué.

### Reprise exacte après ce lot

1. Préparer les paramètres Stripe déterministes depuis l'ordre figé, puis persister les tentatives/idempotence/paramètres avant tout appel externe. Ce premier constructeur peut être testé sans réseau ; il ne représente pas un paiement de test.
2. Ajouter les réservations par variante et les transactions de paiement dédiées. **Ne pas utiliser l'ancien `complete_paid_order` tel quel** : il reprend le coût courant, débite le produit de base et efface tout le panier. Les devis exigent leurs propres snapshots, stock par variante et nettoyage ciblé.
3. Vérifier mode/session/tentative/montant/devise/destination par webhooks signés, traiter timeout ambigu, expiration et paiement différé avec reprise durable. Aucun nouveau paiement après résultat inconnu sans réconciliation.
4. Raccorder allocation fournisseur/agent, tâches, envois préparés soumis à autorisation, expédition/suivi/retours et journal de reprise. Le gate variantes reste fermé jusqu'à la preuve complète.
5. Confirmer frais de paiement et politique de marge minimale avant activation : le devis actuel affiche une marge **avant frais de paiement/exploitation**, pas un bénéfice net garanti. Finaliser preuves fournisseurs/légales, concurrence PostgreSQL multiconnexion, GoTrue/PostgREST, sandbox Stripe réelle et recette visuelle complète avant lancement.
