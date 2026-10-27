# TYMotors — réponses fournisseurs et corrections du 27 octobre

## Décision du Chef

APPROVED LOCAL pour l'analyse sourcée, l'overlay rédactionnel GR86 et le moteur
de suivi des réponses candidates, après correction d'un rejet de chronologie.
L'ouverture commerciale reste BLOCKED : aucune référence n'est activée par ce lot.

Travail sur `codex/commerce-workflows`, sans achat, message fournisseur envoyé,
paiement, migration ou déploiement. Frontend propre, HEAD `6772ba6` ; aucune photo,
galerie, couleur, typographie, mise en page ou prix public modifié.

## Nouvelles réponses réellement traitées

Une recherche Gmail incluant les spams, puis la relecture des fils complets,
ont identifié deux réponses désormais accessibles dans ce cycle. Le constat
historique « aucune nouvelle confirmation visible vers03:10UTC » du lot précédent
n'est pas réutilisé comme état actuel. Les heures ci-dessous sont celles des
messages, pas une hypothèse sur leur date d'indexation dans le connecteur.

| Référence interne | Fournisseur | Message reçu | Date UTC | Décision |
|---|---|---|---|---|
| toyota-gr86-mirror-caps | Ikon |1a17b37757089ac8|27oct02:36:32|Réponse incomplète, restriction GBK consignée|
| carplay-screen-12 | Noeifevo |1a17b15d835fb9cb|27oct01:59:23|Réponse incomplète, manuel inexploitable, prix non chiffré|

Ikon : le nouveau message répond bien à la question ciblée GBK envoyée le26octobre
(`1a1784934d085572`) dans le fil `1a1639a1d0eae4b9`. Rapprochement avec les réponses
du23octobre (`1a166961544fedb9`, livraison) et du26octobre (`1a17601118461fd5`, GBK).
Déclarations retenues **pour le candidat RMC-SBRZ22JDM-GBK seulement** :

- Surcoques ABS, paire gauche/droite, BRZ/GR86 2022-2026 annoncées par le vendeur.
- Conduite à gauche LHD uniquement ; RHD exclu pour ce candidat.
- Pas d'instructions de montage proposées, installation professionnelle recommandée.
- Pas de livraison directe France ; livraison limitée aux48États contigus US.

Ces éléments ne prouvent ni l'équivalence avec les visuels actuels, ni une
sélection d'approvisionnement, ni les fixations/options ou les droits des images.
Ne pas étendre à GT86, CFL/carbone ou autres variantes. Ne pas déduire LHD d'une
adresse en France. Aucun transitaire ni fournisseur alternatif n'a été choisi.

Noeifevo : réponse au message du26octobre (`1a17849379804d85`) dans le fil
`1a1639a21e37d0bb`. Le vendeur indique que les prix du site sont unitaires, port
et autres frais applicables inclus, et demande encore une quantité. C'est une
**déclaration générale**, sans SKU, montant, devise, Incoterm, validité ou détail
France exploitable. Notre hypothèse d'un kit à destination de la France avait
déjà été explicitement fournie, sans quantité d'achat engagée. Aucun coût/marge
ou délai n'est confirmé par ce propos. « Branchement direct » ne prouve pas une
compatibilité universelle. L'ancien lien produit n'a pas fourni de tarif
exploitable à l'outil web (404) ; aucun autre modèle n'a été choisi par défaut.

## Manuel Noeifevo : contrôle réel, pas de validation fictive

Pièce jointe `User Manual GPS Navigation.pdf`, annoncée10616832octets.
Le connecteur marque le MIME PDF supporté mais renvoie INVALID_ARGUMENT sur les
identifiants d'attachement fournis ; les mêmes appels ne sont pas répétés en boucle.
Téléchargement effectué depuis le bouton exact de Gmail, dans le bon fil.

Copie originale préservée hors dépôt :
`backend/data/phoenix-2026-10-27-supplier-replies/User Manual GPS Navigation.pdf`.
Taille10616832octets, hash identique entre téléchargement et copie conservée :
`8A26B413FC9AEBE52AAE9EEC96D45906EFA8EF9F81EFA0EF9EACCD770B837DAC`.

- Poppler pdfinfo : xref invalide, trailer absent, xref illisible.
- pypdf strict=False : marqueur EOF manquant / fin de flux inattendue.
- pdfplumber/pdfminer : Unexpected EOF.
- Visionneuse Gmail : impossible de prévisualiser le fichier.
- Auditeur indépendant : taille/hash identiques, en-tête PDF présent mais aucun
  `%%EOF`/`startxref` dans les4096derniers octets. Aucun contenu technique inféré.

Classement : **UNREADABLE_INCOMPLETE**. Ni une notice simplement reçue, ni un
en-tête annonçant des pages ne permettent de déclarer le modèle, le câblage,
la diagonale/résolution ou une installation validés. Aucun fichier n'est réparé,
retouché ou publié à la place de l'original.

## Corrections réellement apportées

1. `app/data/supplier_reply_review_20261027.json` : deux dossiers candidats,
   messages/datations/champs factuels bornés, inconnues et prochaines actions.
   Les déclarations génériques du vendeur sont séparées des faits d'un SKU.
2. Overlay existant de description GR86 : restriction LHD/RHD attribuée à GBK,
   sans sélection fournisseur ni validation du produit. UUID+slug+ancien texte
   exact exigés ; une édition ultérieure du propriétaire garde priorité.
3. Moteur `build_dossiers` et CLI `--reply-review` : schéma fermé, identités et
   preuves liées, copie profonde, faits isolés de tous les champs commerciaux.
   Aucun statut, prix, port, droit ou compteur de validation n'est promu.
4. Chronologie : `received_at <= recorded_at <= reply_review_as_of`, horloge
   trusted fournie séparément par le CLI en UTC et incluse dans l'empreinte.
   La date historique des prix n'est pas détournée en horloge de revue.
5. Rapport Markdown : candidats explicitement non retenus, document illisible,
   portée des déclarations et réserves ; texte des réponses échappé.
6. Deux clarifications préparées dans
   `TYMOTORS_SUPPLIER_CLARIFICATIONS_2026-10-27.md`, **non envoyées**.
   Demande d'autorisation précise présentée ; aucun devis ou contrat accepté.

La description locale est préparée, pas publiée sur le site actuel.
Les règles de compatibilité ne reçoivent aucune validation depuis un candidat.
L'interface véhicule ne comporte pas de champ côté du volant : une exclusion
automatique RHD demandera un champ structuré transmis/persisté de bout en bout
si une variante est effectivement retenue. Une note seule impose revue manuelle,
elle ne prouve pas que le système connaît le côté de conduite du client.

## Catalogue actuel et dossiers de reprise

Lecture des deux fiches publiques à07:04:25UTC : les deux UUID/SKU correspondent,
état `draft`, `is_verified=false`, prix publics inchangés : GR8669EUR,
écran multimédia490EUR. Ce ne sont pas des prix d'achat.

Première génération à07:07:35UTC : conservée dans `dossiers/` comme historique
pré-correction du contrôle temporel. **Ne pas utiliser cette génération comme
preuve d'acceptation du moteur final.**

Génération finale neuve à **07:11:55UTC**, un GET public read-only pour cette
exécution, sans écraser l'historique :
`backend/data/phoenix-2026-10-27-supplier-replies/dossiers-v2/`.

| Indicateur final | Valeur | Portée |
|---|---:|---|
| Dossiers / brouillons observés |40 / 40|Snapshot public du27octobre|
| Réponses nouvelles analysées / dossiers concernés |2 / 2|Ikon et Noeifevo, pas les5pilotes|
| Documents illisibles |1|Original conservé, aucun contenu technique validé|
| Produits commercialement validés / pilotes validés |0 / 0|Pas de preuve substituée pour atteindre l'objectif|
| Coûts, portFrance et marges confirmés |0|Inconnus null, jamais zéro inventé|
| Modifications photos / design / prix publics |0|Données rédactionnelles et suivi seulement|
| Messages envoyés / commandes / dépenses |0|Textes préparés distincts de SENT|

SHA-256 JSON final : `ED028694347A21FA136B1B12938850F7D332AC8EA73A89F09764AD4AD64EA024`.
SHA-256 Markdown final : `6C473B16C0A219B4813E90F194B1D1266816261C3AAFB75CEB5149B7A51ADC8B`.
Empreinte des sources/horloge :
`414d9101cb5772df23e8c48d05d32ab43d3cf8c5c59f98d245f48f036957942e`.
Les sources copy/fitment/droits historiques restent datées ; cette lecture ne
les transforme pas en une nouvelle certification de montage ou licence d'image.

## Notifications Alibaba vérifiées

Notification Gmail `1a17bdc40ebdc9e9` reçue27octobre05:36UTC : deux non-lus.
Le lien officiel a été suivi en lecture seule. Les deux messages visibles
appartiennent au fil Amy Hong / Shenzhen Harrison, datés du22octobre :
présentation commerciale et image générale de gammes dashcam avec logos de
certification. Aucune référence/SKU réellement retenu, pièce ou certification
applicable n'est confirmée par cette brochure. « Deux non-lus » ne vaut donc pas
deux nouvelles réponses techniques du27octobre. Le bandeau temps réel signale
une déconnexion ; l'historique a néanmoins été rendu et lu après rechargement.
Aucun message, demande de commande ou accord Trade Agent/partage tiers accepté.
Les anciens aperçus Jade/Lauren ne sont pas présentés comme de nouvelles réponses.

## Tests et contrôle indépendant

- Première livraison :50tests dossier PASS, puis66avec copy PASS. Contre-audit
  REJECTED : source2099 acceptée dans une revue2026. Défaut corrigé sans changer
  les preuves réellement reçues, sans écraser la première génération.
- Version finale :67tests dossier +16copy = **83ciblés indépendants PASS**.
  Sourcefuture/revuefuture/clockabsentouinvalide refusés ; offsets équivalents
  acceptés ; prixhistorique avec revue récente accepté sans approbation commerciale.
- Audit preuves : quatre mails sources Ikon23/26/27 et Noe27 relus, UUID et
  restrictions conformes ; PDF hash/taille corroborés ; copy conditionnelle.
- Chef global final : **1786pytest PASS en17,98s**, exit0 ; avertissement
  Starlette/httpx préexistant. Ce ne sont pas1786produits ou tests Stripe réseau.
- Contrôle final indépendant APPROVED LOCAL : hashes JSON/Markdown conformes,
  identités et chronologiev2 vérifiées,40draft/2réponses/1illisible/0validé,
  coûts/port/marges ànull. Première génération conservée, drafts non-SENT.
- Gitleaks staged final : aucune fuite détectée ; diffcheck PASS. Une première
  alerte concernait une ligne de prose où « accessibles » et un identifiant de
  message concaténé avaient déclenché generic-api-key. Texte rendu explicite et
  espacé, sans exception/allowlist ni affaiblissement du scanner. Aucun secret
  réel découvert, aucune URL de session Alibaba ou clé ajoutée aux fichiers.

## Ce qui reste bloqué et prochaine action

- FOURNISSEUR : manuel lisible et modèle exact Noe ; fixations/options GBK,
  droits des fichiers actuels, devis datés, portFrance, garantie/retours.
- HYPERSKU : contrat/API/StoreID/références/devis France toujours absents dans
  les réponses relues. Aucun fournisseur d'origine confondu avec le prestataire.
- ADMINISTRATEUR : approbation des deux clarifications si souhaitées, fiscalité,
  seuil de marge, responsable réel et informations légales.
- CODEX : après nouvelles preuves, raccorder les références choisies aux offres,
  variantes, compatibilités structurées et devis. Ne pas généraliser depuis une
  proposition ni désactiver les blocages ; procédures financières et recette
  hébergée restent des lots séparés, voir les rapports précédents.

Reprise : utiliser `dossiers-v2`, relire ce rapport et les fils avant envoi ;
si une réponse est déjà arrivée, traiter son contenu plutôt que doubler une
relance. Ne pas considérer le commit local comme un déploiement.
