# CJ — envoi d'un brouillon non payé et observation de statut

## Fonctionnement implémenté

Le lot suivant complète la lecture des correspondances par un envoi **explicite par l'administration**, sans achat ni paiement fournisseur. Il ne déclenche pas de traitement à la réception du webhook Stripe : le dossier fournisseur doit d'abord être approuvé sur des informations vérifiées.

1. Une commande TYMotors payée, non test, avec stock appliqué, compatibilité confirmée et dossier fournisseur approuvé existe.
2. `GET /api/admin/orders/{id}/cj-draft` résout les références CJ exactes, vérifie une route et un magasin cohérents, puis produit le payload et son empreinte. Les coûts et approbations financières manquants restent signalés ; ce brouillon n'autorise aucune dépense.
3. `POST /api/admin/orders/{id}/cj-draft` exige `expected_updated_at` du dossier fournisseur, `fingerprint` et `confirm_create_unpaid_draft:true`. Les autres champs sont refusés ; les lignes et l'adresse proviennent du serveur.
4. La RPC `admin_claim_cj_submission` verrouille le dossier, contrôle de nouveau commande/adresse/lignes/preuves et crée une réservation unique **avant** le POST CJ. Une réservation existante n'est jamais reprise pour un second POST.
5. Le client appelle uniquement la création CJ V2 avec `payType:3`, `orderFlow:1`, `isSandbox:0`, `platform:Api`, `shopLogisticsType:2`. Le mode production + Stripe live est requis au niveau de l'orchestrateur. Aucun endpoint de paiement, confirmation, panier ou solde fournisseur n'existe dans ce lot.
6. La référence CJ reçue est conservée et reliée au dossier fournisseur, sans marquer la marchandise commandée, expédiée ou l'agent entièrement connecté.
7. `POST /api/admin/orders/{id}/cj-sync` avec `{}` consulte le détail CJ. L'ID CJ, le magasin et chaque ligne/variante/quantité doivent correspondre. Le statut et le suivi sont conservés comme **observations internes**, sans transformer une absence de suivi en promesse d'expédition client.

Les champs et endpoints sont issus de la [documentation officielle des commandes CJ](https://developers.cjdropshipping.com/en/api/api2/api/shopping.html). Le numéro `orderNum` CJ peut être généré par CJ ; il n'est pas supposé égal au numéro TYMotors. Les identifiants magasin et ligne sont utilisés pour le rapprochement.

## Résistance aux interruptions

- `cj_order_submissions.order_id` et l'identifiant CJ sont uniques. Les RPC sont réservées au backend `service_role`, avec contrôle administrateur ; aucun accès direct `anon`/`authenticated` à la table.
- L'empreinte et le payload sont figés. Un changement de dossier avant réservation refuse l'envoi.
- Après timeout, réponse non lisible ou erreur CJ, l'état devient `uncertain`. Après arrêt brutal avant enregistrement du résultat, il reste `reserved`. Dans les deux cas, un nouvel appel retourne le dossier existant et **ne renvoie pas de commande**.
- Un rapprochement manuel avec CJ est alors nécessaire à partir du numéro TYMotors et du request ID disponible. Aucun bouton de réessai automatique ni mécanisme de paiement n'est ajouté.
- Une observation de suivi indisponible ne remplace pas l'état local. Aucun suivi client n'est fabriqué et le statut de paiement client reste distinct de celui du fournisseur.

## Vérifications

- Validation finale backend sur `42c45af` : [CI verte](https://github.com/tisnooh/tymotors-backend/actions/runs/41706456089), **522 tests Python réussis +1 contrôle croisé ignoré** parce que le dépôt frontend n'est pas cloné dans cette CI backend, **37 contrôles SQL CJ +111 contrôles SQL existants**. Les contrôles de secrets et dépendances passent.
- Actions administrateur ajoutées dans la [PR frontend#8](https://github.com/tisnooh/tymotors-frontend/pull/8), commit `686373e` : contrôle manuel, confirmation explicite et récupération d'une tentative existante, aucun renvoi incertain. [CI frontend verte](https://github.com/tisnooh/tymotors-frontend/actions/runs/41707273384) : **508 tests réussis**, compilation réussie et préversion Vercel terminée. Revue indépendante favorable ; aucun CSS, image ou prix public modifié. Les deux PR restent préparées pour revue, sans fusion ni déploiement production.

- Suite Python locale : **521 tests réussis**, dont orchestration simulée avec le véritable adaptateur CJ sur `httpx.MockTransport`, répétition d'envoi, interruption, changement d'empreinte, mauvaise boutique, mode staging/test et conservation du suivi local.
- Revue indépendante favorable pour le backend et la migration du brouillon non payé, après réussite du test SQL CI.
- Le premier essai PostgreSQL embarqué a échoué par manque de mémoire de la machine. Le nouveau job CI isolé, avec PGlite0.5.8 épinglé, a ensuite détecté une collision d'identifiant de paiement dans les fixtures. Les identifiants des fixtures ont été rendus uniques, sans affaiblir les contraintes de production. Sur le commit `fcb8084`, les **37 contrôles SQL CJ et111 contrôles SQL existants passent**, ainsi que les suites Python3.11/3.12, les secrets et les dépendances : [preuve CI](https://github.com/tisnooh/tymotors-backend/actions/runs/41705843185). La migration est validée en base isolée ; elle n'est pas appliquée en production.
- La lecture d'un brouillon existant retourne son état sans exposer le payload d'adresse ni relancer CJ. Deux contrôles API supplémentaires couvrent cette récupération et le refus des paramètres de paiement/absence de confirmation explicite.
- Aucun fichier frontend, design, photographie ou prix public n'est modifié. La migration n'est pas appliquée en production.

## Messages vérifiés

- Nouveau Gmail CJ `1a1a26b7dad986f8`, « Ticket Replied » : notification automatique demandant une réponse, pas une approbation produit.
- Ticket `T202610311023101331` lu : réponse CJ du3 novembre16:01:50 (heure affichée) indiquant qu'il transmet les informations à son équipe. Aucun SKU CJ ni devis dans cette réponse.
- Réponse TYMotors envoyée et vérifiée dans le même ticket, entrée du3 novembre19:02:59 (heure affichée) : transmission des identifiants stables `platformProductId=e46bf5e1-d459-44ca-b28d-70c01c5c14e7`, `platformVariantId=TY-BMW-F30-F32-MIRROR-CAPS` ; demande des IDs CJ produit/variante/SKU et magasin après approbation. Conditionnement et stock Soyintech toujours attendus. Aucun achat ou travail payant autorisé. Ticket repassé en attente CJ ; preuve visuelle dans l'onglet conservé.
- Fil Nicy : dernier message fournisseur reste `1a1a0b3ed9927eb4`, dernière demande TYMotors envoyée `1a1a1c71ffc6b8d2`. Pas de demande identique répétée.
- WhatsApp : aucun nouveau retour fournisseur utile visible ; HyperSKU conserve son dernier message de courtoisie et l'alerte Alibaba concerne des gadgets de cuisine.
- Alibaba Messenger affiche encore « The network connection has been disconnected » ; les messages récents de cette surface ne peuvent pas être certifiés. Aucun envoi tenté à travers une session déconnectée.

## Limites avant exploitation réelle

La référence de service CJ approuvée et le devis unitaire sont toujours manquants. La création et la réception d'un brouillon **réel** chez CJ ne sont donc pas revendiquées. Les observations sont internes ; l'automatisation des événements client et la gestion de plusieurs colis nécessitent des événements CJ vérifiés et un lot distinct. La préparation d'un brouillon n'achète pas la pièce et ne lance pas l'expédition.

Reprise : préparer l'application de la migration après validation de publication du lot ; enregistrer le magasin exact et la variante CJ approuvée ; effectuer ensuite une recette réelle non payée sur une référence autorisée, puis contrôler le résultat chez CJ. Toute dépense et toute publication production restent séparées de cette recette.
