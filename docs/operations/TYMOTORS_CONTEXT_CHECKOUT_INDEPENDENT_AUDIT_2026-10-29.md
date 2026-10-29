# Audit indépendant — exécution des paiements par compte et profil

## Périmètre et décision

APPROVED LOCAL pour le premier lot de paiement lié au compte et au profil.
La contre-exécution indépendante du parcours HTTP/SQL complet est réussie.
Aucun compte réel, appel Stripe externe, commande fournisseur ou déploiement
n'est utilisé par cet audit. Aucune validation commerciale de produit.

## Preuves indépendantes exécutées

- Baseline :509 tests Python existants réussis.
- Première recette des nouveaux adaptateur et service :162 tests réussis.
- Recette élargie finale :226 tests réussis,16,94s, comprenant les
  profils, le service, le retour client, le SDK et13 contre-tests indépendants.
  Avertissements : Starlette/httpx et dépréciations du transport SDK de test.
- Nouveau fichier indépendant :tests/test_independent_context_audit.py.
  Ses premières exécutions ont refusé quatre cas de délégation au receiver
  historique. Après correction, les treize cas passent.
- Contre-exécution indépendante avec run_commerce_pipeline :655 contrôles du
  parcours historique puis250 contrôles du nouveau moteur, sortie0.
  http_context_journey PASS : vraie route client, vrai SDK avec MockTransport
  HTTPX fermé, un seul POST synthétique, webhook signé localement, reçu client
  payé, zéro effet de paiement doublé et garde finale false.
- Vérification SQL supplémentaire dans la fixture possédée par l'auditeur :
  treize helpers privés et39 assertions de permissions réussies ; anon et
  authenticated ne peuvent pas exécuter, service_role peut exécuter.
- Frontend propre à90192b25ca317e00bab770baed57702b560844e9 ; aucun changement
  de design ou d'image dans ce lot. git diff --check réussi.

## Défauts identifiés et corrections contrôlées

1. Comparaison d'une commande SQL enrichie par quote_expires_at avec la ligne
   brute orders : remplacée par une projection de l'identité et du snapshot
   financier. Les changements de montant, devise, adresse et promotion restent
   refusés. Un paiement confirmé pendant la lecture fournisseur est reconnu.
2. Échecs historiques liés par metadata.order_id seulement : plus aucune mutation
   orders pour ces événements, reçu conservé pour réconciliation.
3. Réception test dépendante du mode courant de création : mode historique
   séparé ; profils explicites indépendants du mode courant.
4. Délégation account/context acceptée par le receiver historique : refus avant
   la base, y compris si le champ est présent avec une valeur NULL.
5. Retour client ambigu entre plusieurs comptes ou un ancien paiement : refus
   plutôt que choix implicite/fallback ; les autres propriétaires sont exclus.
6. Identifiants financiers globalement uniques : nouveaux index portés par
   compte et mode, unicités NULL conservées pour l'historique. Lookups de
   remboursements historiques isolés sur NULL, y compris dans les RPC SQL.
7. Paiement reçu après disparition du stock : dossier de revue avec l'agent et
   la raison figés, sans achat ni expédition autorisé.
8. Horloge d'approbation calculée avant attente du verrou : recalcul après
   acquisition FOR SHARE, avant comparaison de l'expiration.

Le signalement intermédiaire concernant l'ACL du helper de panier était caduc :
la relecture ciblée et les requêtes SQL confirment les permissions effectives.

## Sources gelées de la contre-recette

- Migration20261029071833 :
  6AB043EA76C79BA19E72F5DFE2D01D5C259A8587DB261A638A82696D1C1DF54C
- commerce_production_http_probe.py :
  CD50FE3E3E5E3CD90FB81CBA592891597A53A5AD7597EC849483525E3BF2485D
- commerce_context_http_journey.py :
  0ED4B0CD74AAB3355A66FBFD7C22690C39630A8C54FADAD67A149E663E000E48

Ces empreintes doivent rester identiques pour appliquer cette approbation.
Une nouvelle migration de traitement logistique manuel est hors du périmètre
de cette décision et nécessite sa propre recette et son propre audit.

## Limites à conserver dans tout rapport de livraison

- Les événements signés utilisent des HMAC synthétiques avec le vrai SDK.
- Le transport HTTPX du fournisseur est FAKE ; aucun marchand authentifié en
  ligne ni webhook enregistré dans un compte Stripe ne sont démontrés.
- PostgreSQL est exécuté par le moteur local PGlite ; ne pas prétendre avoir
  prouvé les courses entre connexions PostgreSQL natives.
- Les remboursements des nouveaux profils ont un reçu de réconciliation ; cela
  ne constitue pas une projection financière complète de remboursement.
- Les dossiers logistiques restent en revue, sans transmission fournisseur.
- Aucune activation réelle ni référence commercialement approuvée ne résulte
  de ces tests. Le design et les photographies ne sont pas modifiés.
