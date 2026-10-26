# TYMotors — état de préparation au lancement

## Actualisation locale —26 octobre2026

### Fournisseurs et décision commerciale —20:30UTC

Nouvelle vérification à la demande du propriétaire :40brouillons et cinq pilotes
toujours non vérifiés selon le catalogue relu20:28:25UTC. Quatre relances ciblées
Soyin/GZTM/Redzini/JLStyling envoyées et relues dans les fils existants, sans
engagement ni achat. Les cinq dossiers ont reçu une décision BLOCKED, pas une
approbation sans devis : prix d'achat/port/droits/identité de variante/montage et
conditions encore insuffisamment prouvés ; marges non calculables.
Rapport : `operations/TYMOTORS_PRELAUNCH_REVIEW_2026-10-26.md`.
66tests dossiers/pricing PASS ; aucun nouveau test de paiement ou changement live
dans ce cycle. L'ouverture et les paiements réels restent non activés par ce travail.

**Ouverture aux commandes réelles toujours non validée.** Le tableau du12octobre
ci-dessous est historique : ses hashes, nombres de tests et constats d'accès ne
décrivent pas automatiquement la production actuelle.

- Un vrai parcours positif Stripe sandbox a depuis été effectué depuis le panier
  local :35EUR, événement signé, commande unique, attribution agent et préparation
  interne HyperSKU. Expédition et livraison ensuite **simulées**, aucun achat ni
  envoi fournisseur. Preuve : `operations/TYMOTORS_CLIENT_SUPPLIER_TEST_2026-10-26.md`.
- Préparation HyperSKU revalidée à chaque replay, avec audit indépendant local.
  La connexion fournisseur réelle reste absente : contrat/API, StoreID, références
  des variantes et devis France ne sont pas établis. Preuve et conditions :
  `operations/TYMOTORS_HYPERSKU_CONFIGURATION_2026-10-26.md`.
- Les40 dossiers et cinq candidats ne sont pas commercialement approuvés sur les
  preuves disponibles. Aucune nouvelle offre retenue, permission positive d'image
  ou marge complète n'est déduite d'un test synthétique. Voir
  `operations/TYMOTORS_SUPPLIER_STATUS.md` pour les réponses datées.
- Dernier lot local : notifications administratives persistantes, claims exclusifs,
  refus de renvoi ambigu et garde remboursement.1553pytest globaux et41HTTP PASS ;
  audit indépendant APPROVED LOCAL (41HTTP/65SQLoutbox/63pytest),pas de publication. Rapport :
  `operations/TYMOTORS_NOTIFICATION_OUTBOX_2026-10-26.md`.
- Restent notamment : preuves commerciales des cinq pilotes, canal HyperSKU réel,
  rapprochement financier/remboursements quoted dans un lot dédié, recette isolée
  PostgreSQL multi-connexion/GoTrue/PostgREST, informations administrateur et accord
  explicite de publication/activation commerciale. Aucun accès, coût ou droit
  manquant ne sera inventé pour clôturer ces étapes.

Design, photographies et prix publics inchangés dans ces lots. Les travaux locaux,
leur publication et l'exploitation réelle restent trois validations distinctes.

## Historique vérifié le12octobre2026

Vérifié le 12 octobre 2026. Verdict : vitrine publiée, mais **ouverture aux commandes réelles non validée**. Stripe reste en test et aucun achat fournisseur n'a été effectué.

## Parcours attendu

Un client sélectionne un produit disponible et compatible, paie, reçoit une confirmation, puis TYMotors valide manuellement l'achat fournisseur ; l'agent contrôle et expédie le colis, et le client voit un suivi fiable.

## Éléments vérifiés

| Élément | Preuve | Limite |
| --- | --- | --- |
| Backend européen | Render Frankfurt, service `srv-dajf809594qs73bvpgi0`, correctif `9860d88` Live | Offre gratuite conservée ; les réveils après inactivité restent possibles |
| Base de données | Production `dzdcaloewimekvddvdlo` et staging `enckmnyapgovkkzsnyca`, Paris `eu-west-3` | Ne prouve pas une vente ni une disponibilité fournisseur |
| Origine frontend | `FRONTEND_URL` production enregistré ; contrôle CORS réussi | Aucune clé révélée ou changée |
| Stripe sandbox | Destination active vers le backend européen ; événement signé reçu HTTP 200 et état `completed` en base ; renvoi HTTP 200 avec `duplicate: true`, une seule ligne en base | Événement synthétique sans commande TYMotors, pas une recette panier/paiement complète |
| Administration fournisseur | Liens privés, prestataire éditable, récupération des liens manquants avec confirmation, RPC déployée sur les deux bases | Traitement manuel uniquement ; aucun adaptateur HyperSKU connecté |
| Tests | 168 backend, 17 frontend, lint frontend ; CI backend et frontend réussies | Pas une certification sécurité, juridique ou fournisseur |
| Frontend publié | Commit `61731d2`, Vercel `dpl_7HZRP7sW3Y3oJaRqEtkVBkcWMAde` READY, alias `tymotors.vercel.app` | Seuls le suivi et les promesses livraison/paiement ont été corrigés ; design et animations inchangés |
| Personnalisation véhicule | 14 images récupérées lors de la préparation précédente | Huit droits/licences restent à revoir ; ne pas confondre disponibilité technique et droit d'usage |

## Blocages avant les vraies ventes

1. **Catalogue vendable :** les deux bases ont 40 brouillons et une fixture archivée, zéro produit actif. Les 40 brouillons ont stock zéro et ne disposent pas de preuves fournisseur, de compatibilité et d'images vérifiées. Les aperçus publics ne sont pas des produits commandables. Ne pas inventer de stock ou publier la fixture test.
2. **Fournisseur et agent :** demande HyperSKU envoyée et assignée à Chloe lors de la préparation. Aucun devis, acceptation des colis à l'unité, délai total France, prix complet, contrôle qualité ou conditions de retour confirmé dans les preuves disponibles. Aucun achat ni solde crédité.
3. **Informations commerciales :** nom légal, SIRET, adresse professionnelle, médiateur, domaine et e-mail public à fournir pour finaliser les pages et l'expéditeur. Confirmer aussi les conditions de livraison/retour annoncées et les droits des visuels.
4. **Recette et paiements réels :** effectuer une commande complète de test sur un environnement isolé avec un produit dûment validé, puis vérifier stock, paiement, dossier fournisseur unique, mails, suivi, expiration et remboursement. Le passage Stripe live n'est pas autorisé par la demande antérieure de test uniquement et doit être préparé séparément avec le propriétaire.

## Corrections apportées

- Normalisation récursive des objets réels du SDK Stripe après contrôle de signature ; correction des remboursements et tests avec signatures HMAC réelles.
- SDK Stripe fixé à la version 16.0.0 pour un déploiement reproductible.
- Statuts du suivi traduits ; une panne réseau n'est plus affichée comme une commande introuvable.
- Suppression des promesses non confirmées d'expédition avant 14 h, de délais express et de paiement fractionné sans frais.
- Aucun changement du Hero, des images publiques, de la navbar ou des animations pendant ces correctifs.

## Informations attendues du propriétaire

- Réponse reçue : aucun devis fournisseur/HyperSKU confirmé ; « TYmotors » est le nom souhaité, mais SIRET et autres informations d'entreprise ne sont pas disponibles. Ne pas déclarer l'entreprise immatriculée ni inventer ces mentions.
- Les premières références à vendre et la confirmation écrite des variantes, disponibilité, compatibilité, coût total et délai France.
- Les informations légales et le domaine/e-mail professionnel choisi, sans transmettre de clé ni document d'identité dans le chat.
- Ensuite, décision explicite sur le passage aux paiements réels et budget éventuel pour des échantillons ; aucun engagement payant n'est pris automatiquement.

## Références

- [CI backend](https://github.com/tisnooh/tymotors-backend/actions/runs/38238416091)
- [CI frontend](https://github.com/tisnooh/tymotors-frontend/actions/runs/38240456974)
- [Site publié](https://tymotors.vercel.app/)
- [Procédure Stripe test](STRIPE_TEST_SETUP.md)
- [Pilote et demande de devis HyperSKU](HYPERSKU_PILOT.md)
- [Checklist Stripe avant le mode réel](https://docs.stripe.com/get-started/checklist/go-live)
- [Règles officielles e-commerce](https://www.economie.gouv.fr/dgccrf/les-fiches-pratiques/e-commerce-les-regles-entre-professionnels-et-consommateurs)
- [Formalités de création d'une micro-entreprise](https://entreprendre.service-public.gouv.fr/vosdroits/F36746)
- [Mentions obligatoires d'un site professionnel](https://entreprendre.service-public.gouv.fr/vosdroits/F31228)

Le nom commercial seul ne remplace pas l'identification du vendeur. Service Public prévoit une demande d'immatriculation au plus tôt un mois avant le début d'activité et au plus tard quinze jours après celui-ci : ne pas assimiler automatiquement un SIRET en cours d'attribution à une interdiction générale, ni afficher cette mention sans démarche réellement engagée. Le lancement reste ici non validé pour l'ensemble des raisons ci-dessus, indépendamment du seul délai d'attribution du numéro.
