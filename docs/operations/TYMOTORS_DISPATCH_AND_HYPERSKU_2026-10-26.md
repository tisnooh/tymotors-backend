# Suite commande et HyperSKU — 26 octobre 2026

## Décision et périmètre

**APPROVED LOCAL : sécurisation de l’expédition manuelle historique.**
**BLOCKED : transmission HyperSKU réelle, qualification commerciale et livraison réelle.**

Aucun changement frontend, design, photographie ou prix public. Aucune migration
distante, publication, connexion de boutique, commande fournisseur, transmission
de données client ou dépense. Le vrai paiement Stripe sandbox précédent reste
acquis ; aucun nouveau paiement créé pour ce lot.

## Correctif exécuté

L’endpoint existant `PUT /api/admin/orders/{id}` ne fait plus une RPC de statut
puis un UPDATE séparé du transporteur/URL. Une seule transaction verrouille la
commande et enregistre statut, numéro, transporteur, URL, dates, audit et événement.
La version attendue est un horodatage avec fuseau. Le rôle admin est revérifié
après le verrou ; l’ancien RPC délègue au même noyau sans contournement.

- Refus de préparation/expédition/livraison réelles pour une commande sandbox,
  impayée, annulée, remboursée ou en revue de compatibilité.
- Refus du chemin historique mono-colis pour les commandes avec devis commerce :
  il ne doit pas contourner le futur fulfillment vérifié par ligne et colis.
- Expédition : numéro et transporteur obligatoires, numéro `SIM-` interdit.
- Suivi figé après expédition ; des champs omis à la livraison conservent le suivi.
- Répétition identique : aucune nouvelle mutation, événement ou demande d’email.
  Une mutation avec version périmée est refusée.
- La livraison est explicitement confirmée manuellement par TYMotors ; aucune
  fausse affirmation de notification automatique du transporteur.

Migration créée avec la CLI : `20261026081655_atomic_manual_order_dispatch.sql`,
appliquée seulement au PostgreSQL/PGlite jetable. Aucun enregistrement réel modifié.

## Résultats exécutés

| Contrôle | Résultat |
|---|---|
| API ciblée + administration | 227 pytest PASS |
| Backend global final | 1523 PASS, 18,03 s ; dépréciation Starlette/httpx préexistante |
| SQL/PGlite | 66 contrôles historiques + 115 nouveaux contrôles expédition PASS |
| HTTP local réel → SQL → suivi client public | 25 assertions PASS ; aucun transport fournisseur |
| Audit indépendant | 22 tests API PASS exécutés par l’auditeur en 4,86 s ; migration/wrapper et tests SQL relus |
| Inspection XLSX + API ciblée finale | 26 pytest PASS, 5,88 s ; original XLSX relu, hash inchangé |
| Frontend / photos | Aucun fichier changé dans ce lot |

Les tests forcent une erreur après l’UPDATE pour prouver le rollback des dates,
statuts, transporteur et événements. Ils couvrent rôles, SIM, impayés/remboursements,
compatibilité, devis, ancien RPC sans transporteur, suivi verrouillé, fermeture,
rejeu et version périmée. Le suivi public n’expose pas les métadonnées privées.
Les contacts et références sont synthétiques ; emails et transport réseau désactivés.

Échecs de développement non masqués : la fixture du cas devis a successivement
utilisé des colonnes absentes, un contexte panier incomplet puis une réaffectation
interdite de devis. Corrigé d’après les migrations, sans affaiblir leurs protections.
Le probe public utilisait d’abord `example.test`, rejeté par EmailStr ; corrigé en
`example.com` synthétique. Le filtre des événements utilise les titres publics,
pas un champ interne absent. Les dernières recettes SQL/HTTP ci-dessus passent.

## HyperSKU : éléments obtenus aujourd’hui

Compte authentifié relu dans le navigateur. Pending payment : 0 avec les filtres
actuels ; Drafts : 0. Cela ne prouve pas l’absence de toute commande historique.

Modèle téléchargé depuis `Orders → Import File → Upload File… → Template / Download` :

- Original hors Git : `C:/Users/utilisateur/Downloads/HyperskuExcelOrderTemplate.xlsx`.
- SHA-256 : `c3fc64e82777c17b0882971138a1560fe7e5c1b690a398f11a513a093e63ad4b`.
- Feuille `SheetJS`, uniquement les en-têtes ; aucune commande ni donnée client.
- Colonnes : SKU Code, Store ID, Order Number, Hypersku Quantity, First Name,
  Last Name, Address1, Address2, City, Province, Country, Zip, Phone Number,
  Email, POD Text, POD Image.
- Inspection en lecture seule via `tools/inspect_hypersku_template.py` ; aucune
  formule exécutée ni import testé/certifié. Aucun export arbitraire créé.

Guide officiel du modèle et SKU exact par variante :
https://support.hypersku.com/en/articles/3297862-import-orders-manually-by-uploading-excels

Store Settings ne présente pas de boutique liée dans l’écran consulté. Add Store
propose des plateformes standard, sans connexion React/Python ni contrat API
exploitable identifié dans cette fenêtre. Fermée sans Save. L’Open API reste
annoncée officiellement, pas démontrée accessible pour notre compte :
https://support.hypersku.com/en/articles/2941652-what-s-hypersku-how-to-sign-up-and-get-started

Aucune app, clé, permission, Upload, Submit, synchronisation ou achat effectués.
Le modèle nécessite de clarifier notamment Store ID/SKU réels, prénom/nom,
province et téléphone. Ne pas les inventer ni les déduire arbitrairement.
Les paquets internes gelés restent non certifiés pour import.

## Relance autorisée et réellement envoyée

Avant envoi : recherche Gmail depuis le 12 octobre sur les domaines officiels,
hors messages de nous-mêmes, promotions et corbeille. Seul onboarding du 16 octobre
dans ce périmètre. Fil d’origine relu : demandes des 22/23 octobre, sans réponse
dans ce fil. Ce contrôle n’exclut pas un échange par chat ou hors filtre.

Après autorisation explicite du propriétaire, une relance sans engagement a été
envoyée à `support@etailerhub.com` le **26 octobre 2026 à 08:31:28 UTC**.

- Message Gmail : `1a1775604c6d3c4e` ; fil existant `1a1624419984de5e`.
- Envoi puis relecture : **SENT**, destinataire, sujet et In-Reply-To vérifiés.
  Cela prouve l’envoi, pas la lecture par HyperSKU ni une réponse.
- Demandé : API/auth/idempotence/webhooks/sandbox, Store ID et boutique personnalisée,
  effets Upload/Submit, correspondances des trois références GZTM historiques,
  devis détaillés France actualisés après les changements de tarifs du 24 octobre.
- Pas de secrets demandés par email, données client, commande, service payant,
  achat, substitution ou choix de variante commerciale autorisés.

## Blocages et reprise

| Responsable | Action attendue |
|---|---|
| HyperSKU | Contrat API/canal autorisé, Store ID, SKU et variantes authentiques, devis France et effets d’import confirmés |
| Fournisseurs / HyperSKU | Équivalence, compatibilités et restrictions, disponibilité, droits, coûts et port des pilotes ; aucun pilote validé par ce lot |
| Codex | Adaptateur sur contrat reçu, idempotence et reprises ; suivi sourcé et multi-colis réels, recette isolée |
| Codex | Emails encore best-effort après commit : sans outbox transactionnelle, un crash avant l’email peut perdre cette notification ; aucune reprise garantie annoncée |
| Administrateur | Accords distincts pour données client, budget d’essai fournisseur et publication ; ni relance ni sandbox ne les autorisent |

À la reprise : relire les réponses du fil et du chat existants avant tout autre
contact. Aucun nouvel envoi ni surveillance permanente implicitement autorisés.
Runner jetable fermé ; ports 8765/8766 vérifiés libres après la recette finale.
La concurrence multi-session PostgreSQL hébergée et la réception HyperSKU réelle
ne sont pas démontrées par ces tests locaux.
