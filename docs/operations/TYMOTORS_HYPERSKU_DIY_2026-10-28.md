# HyperSKU — parcours fournisseurs et réponse à Rita

## État réel et périmètre

Le propriétaire a explicitement demandé de poursuivre HyperSKU et de répondre à
Rita sur WhatsApp, dans le fil professionnel montré. L'envoi de cette réponse
non engageante est autorisé ; ne pas demander à nouveau l'accord de rédaction
ou d'envoi. Aucun achat, débit, commande ou transfert de données client autorisé.
Les partenaires restent Tianzhiyu, Soyintech/Soyin et GZTM Auto/Leju. Pas de
nouvelle démarche de certification photo.

**CONNECTED : interface du compte. Module DIY actif. PREPARED : inspection des
modèles. BLOCKED : liaison API/Store ID/SKU et WhatsApp non connecté.** Aucun
import, ordre fournisseur ou expédition réellement exécuté dans ce lot.

## Compte HyperSKU

Le27octobre, Application → DIY Sourced Orders → Add → confirmation a activé le
module interne. L'entrée de menu et la liste `/self/buy/order` sont présentes,
encore vérifiées le28octobre. Le module décrit l'achat par le commerçant auprès
de ses fournisseurs puis la réception de l'inventaire par HyperSKU. Ce n'est ni
un achat effectué ni une confirmation de service/coût par variante.

La liste consultée indique0commande avec son filtre des trois derniers mois.
Import mène à `/orders/draft?goodsType=19`, sans ligne de brouillon. Upload File
ouvre la fenêtre de modèle ; seul Download a été utilisé. **Aucun fichier n'a
été téléversé, aucun Submit, Pay Together, achat ou débit n'a été effectué.**

Les vues My Products et Private Products consultées le27octobre sont vides.
Store Settings ne montre aucune boutique liée dans cette lecture ; Add Store
liste des plateformes standard, sans choix React/Python identifié, et a été
fermé sans Save. Les vues Smart Sourcing Pending/Quote created/Sourcing in
process consultées n'affichent pas de données ; ce relevé n'est pas un inventaire
universel de tous les anciens échanges ou filtres.

Le chat existant est au nom de Chloe ; dernier message visible de Lexi proposant
un accompagnement général, sans devis, Store ID, référence ou documentation API.
Ce fil est distinct de Rita sur WhatsApp. Aucun nouveau message web n'a été
envoyé à la place du WhatsApp demandé.

## Deux modèles distincts, téléchargés uniquement

| Usage | Fichier / en-têtes | Empreinte SHA-256 |
|---|---|---|
| Entrée de stock DIY |HyperskuExcelStockOrderTemplate.xlsx,14641octets,1feuille : SKU Code ; Hypersku Quantity |`8ebd1166dc196462f8025cb742a827e4f30ec2a64254d706565fa82676fbfe78`|
| Commande client |HyperskuExcelOrderTemplate.xlsx,16colonnes incluant Store ID et destinataire, téléchargement26octobre |`c3fc64e82777c17b0882971138a1560fe7e5c1b690a398f11a513a093e63ad4b`|

Les deux fichiers, conservés dans Downloads horsGit, ne contiennent que leurs
en-têtes. Le modèle DIY a été obtenu le28octobre depuis le compte réel et non
reconstruit arbitrairement. Ne pas utiliser un SKU Soyin/Alibaba comme SKU Code
HyperSKU, ni remplacer un Store ID absent par l'identifiant du compte.

Inspection locale reproductible :

```powershell
python tools/inspect_hypersku_template.py C:/Users/utilisateur/Downloads/HyperskuExcelStockOrderTemplate.xlsx --kind inbound-stock
python tools/inspect_hypersku_template.py C:/Users/utilisateur/Downloads/HyperskuExcelOrderTemplate.xlsx
```

L'outil accepte explicitement le contrat2ou16colonnes ; aucun basculement
automatique. Il ne produit que hash, en-têtes fixes et compteurs ; aucune donnée
de commande ou commentaire privé n'est imprimé. Refus des données sur toute la
feuille, feuilles supplémentaires et formules dans les partiesXML concernées.
Aucun workbook modifié, macro/formule exécutée ou fichier d'import créé.

L'auditeur a rejeté un premier contrôle des formules limité aux cellules. Le
contre-exemple de mise en forme conditionnelle a conduit au scan XML global,
avec validation, tables et graphiques. **119tests ciblés indépendants PASS**,
deux modèles officiels acceptés, hashes/octet inchangés ; APPROVED LOCAL pour
l'inspecteur seulement. Cela n'est pas un test d'import HyperSKU.

Suite globale Chef sur le lot final : **2124pytest PASS,22,65s**, un avertissement
Starlette/httpx préexistant. Aucun code applicatif de vente, migration, frontend,
photo ou prix public modifié par ce lot.

## WhatsApp : accès manquant, pas autorisation manquante

WhatsApp Web affiche le QR de connexion, pas les conversations. Aucun message
à Rita n'a été envoyé. Le propriétaire doit lier le navigateur depuis son
téléphone ; l'agent ne peut pas scanner à sa place. La réponse est conservée
dans HYPERSKU_RITA_WHATSAPP_REPLY_2026-10-28.md, explicitement NON ENVOYÉE.

Une fois connecté : lire tout le message récent, vérifier le fil HyperSKU/Rita,
adapter le texte puis l'envoyer sans redemander d'autorisation ordinaire. Vérifier
la bulle sortante et son état avant de déclarer l'envoi ; conserver une preuve
sans données de destinataires clients ou informations d'authentification.

## Suite nécessaire

Demander à Rita le rattachement de boutique personnalisée (Store ID), les SKU
HyperSKU des variantes pilotes et un devis France détaillé, ainsi que le canal
API documenté ou manuel pris en charge. Confirmer les minimums de démarrage,
réception/étiquetage et suivi. Les cinq SKU proposés Soyin restent disponibles
dans la matrice des trois fournisseurs ; aucun achat ne découle de cette demande.

La [présentation officielle](https://support.hypersku.com/en/articles/2941652-what-s-hypersku-how-to-sign-up-and-get-started)
confirme l'Open API pour les boutiques hors plateformes prises en charge. La
[procédure d'import](https://support.hypersku.com/en/articles/3297862-import-orders-manually-by-uploading-excels)
exige le modèle et les SKU propres aux variantes. Ces pages, relues le28octobre,
ne fournissent pas à elles seules les accès ou le contrat d'API TYMotors. Aucun
endpoint privé du dashboard n'a été repris pour simuler une API officielle.

Preuve visuelle locale, horsGit :
backend/data/hypersku-2026-10-28/hypersku-diy-module-active.png. Onglets WhatsApp
et HyperSKU conservés pour reprise, sans surveillance ou exécution en arrière-plan.
