# Audit indépendant — traitement manuel et suivi multi-colis

## Décision

APPROVED LOCAL pour le deuxième lot de traitement manuel. Cette décision ne
valide aucune offre commerciale, expédition réelle ou intégration fournisseur.
Le premier lot de paiement dispose de son rapport indépendant séparé.

## Preuves exécutées par l'auditeur

-146 tests Python réussis,9,53s : API de traitement, consommateur financier,
  retour client et contre-tests indépendants. Avertissement Starlette/httpx connu.
- Contre-exécution du runner isolé :655 contrôles historiques,250 contrôles du
  moteur de paiement et216 contrôles de traitement manuel réussis, sortie0.
- Parcours HTTP/SDK avec transport MockTransport fermé réussi ; un seul POST
  factice, reçu client payé, aucun effet de paiement en double.
-15 assertions SQL supplémentaires réussies sur les cinq nouveaux helpers
  privés : aucun EXECUTE pour anon/authenticated, EXECUTE pour service_role.
- Deux groupes/colis : références fournisseurs, preuves par étape, contrôle de
  version, reprise idempotente, statut global et suivis publics contrôlés.
- Remboursement signalé avant/après paiement : revue maintenue, aucun montant
  remboursé déduit et aucune nouvelle expédition autorisée.
- Livraison d'un colis déjà expédié après incident financier/annulation : preuve
  conservée, aucune remise en circulation financière, aucune permission de
  départ pour l'autre colis, aucune notification invalidée envoyée.
- Garde finale false. Ports8765/8766 fermés après la recette.
- git diff --check réussi. Aucun fichier visuel ou image modifié dans le lot.

## Corrections exigées pendant la revue

- Le validateur de lien de suivi acceptait des écritures navigateur d'adresses
  loopback : réutilisation de la validation d'origine déjà contrôlée ; refus des
  variantes avec point terminal, labels hexadécimaux, labels vides et contrôleDEL.
- La première version empêchait également de constater une livraison physique
  après incident financier : exception strictement limitée au colis déjà
  expédié, avec identité de suivi et preuve immuables. Les tests216 couvrent le
  maintien des autres interdictions.
- La précision microseconde des versions a été préservée dans la fixture REST,
  afin que les versions obtenues par GET restent utilisables lors du POST.

## Empreintes gelées vérifiées

| Empreinte SHA-256 | Fichier |
| --- | --- |
| C1AAC0B99891BF46B71B6EED1CDF5FAA068979D495FAC464EDD748841814EBAB | supabase/migrations/20261029131412_commerce_context_manual_dispatch.sql |
| 045F7BB1F352AE158191D0BBAA22AECEC4E1B615A4A1D2904CAB050D37BAAA3D | tests/commerce_context_dispatch_probe.py |
| C83AC0E4B8B983CB13CA7881B3591FBD9186307E4472E7F292A74F75F234B91F | app/commerce_context_dispatch_api.py |
| AE929E57848ADF7EF12FE3E5259CA597FF845970182C0FF39523BF90F755BC50 | app/commerce_context_payments.py |

## Limites obligatoires de toute présentation

- Les statuts fournisseurs et transporteurs sont enregistrés manuellement avec
  preuve ; aucune commande ni transmission fournisseur n'est déclenchée.
- Les faits de livraison du test sont synthétiques ; aucune livraison réelle.
- Les notifications sont mises dans la file existante et contrôlées ; aucun
  envoi réel de courriel n'est démontré par cette recette.
- Les remboursements des nouveaux profils entraînent une revue ; leur projection
  monétaire cumulative complète et la résolution des reçus sans identité restent
  à traiter manuellement. Une quarantaine ne doit pas être effacée sans preuve.
- Le moteur SQL local est PGlite, pas une preuve de courses entre connexions
  PostgreSQL natives.
- Le frontend existant conserve son bouton de suivi pour un colis. Pour plusieurs
  colis, les numéros figurent dans la chronologie existante et dans l'API parcels ;
  aucun nouveau bouton par colis ni nouvelle interface graphique n'est livré.
- L'accès réel au compte Stripe reste hors de cette approbation. Le Chef a
  signalé un refus403 de lecture du compte avec la clé temporaire existante,
  sans nouveau paiement/remboursement. Cela indique une permission de clé
  insuffisante pour ce contrôle, pas une preuve d'inéligibilité juridique.
- Aucun déploiement ou activation en production n'est approuvé par cet audit.
