# Paiement et traitement manuel — contrat d'exploitation

## Accès effectivement vérifiés le29octobre

- Les deux connexions Stripe proposées par le connecteur répondent UNAUTHORIZED
  et demandent une réauthentification. Aucun compte marchand n'a été identifié
  ou sélectionné sur cette base, aucune permission n'a été changée.
- Le profil CLI sandbox historique est présent. Vérification en lecture seule
  avec le nouvel adaptateur puis diagnostic limité : `GET /v1/account` refusé
  par Stripe en403 PermissionError. Ni clé ni réponse privée n'ont été affichées.
  Cela ne prouve pas une expiration, une immatriculation refusée ou une panne
  de Checkout ; cette clé temporaire n'autorise pas la lecture nécessaire ici.
- Aucun nouveau paiement, remboursement, compte, clé ou achat n'a été créé.
- Action d'accès : reconnecter Stripe dans Codex avec le compte TYMotors et
  fournir la configuration de backend par son coffre de secrets, jamais au chat.
  Cela ne constitue pas une nouvelle demande d'autorisation pour les travaux
  techniques qui continuent ; c'est l'authentification réelle manquante.

Le checkout par compte/profil a été poussé dans `4b04154`. Le traitement manuel
des dossiers est APPROVED LOCAL après ses propres tests et contre-audit :
2 881 pytest,655+250+216 SQL/HTTP ; auditeur146 Python et15 ACL supplémentaires.
Aucun déploiement,
paiement réel, achat, acceptation fournisseur ou expédition réelle n'est déduit
des recettes locales. Aucune photographie, présentation ou tarification publique
n'est modifiée. L'immatriculation en cours ne bloque pas ce développement.

## Configurer les accès sans exposer de secret

Les valeurs Stripe appartiennent uniquement au coffre de secrets du backend.
Ne pas les mettre dans Git, le frontend, une capture, un journal ou le chat.

- `STRIPE_SECRET_KEY` : clé restreinte du marchand pour le mode choisi, avec les
  accès nécessaires à la lecture de son compte et aux sessions Checkout.
- `STRIPE_WEBHOOK_PROFILES_JSON` : liste privée suivant le schéma de `.env.example`.
  Chaque entrée fixe une référence, un mode sandbox/production, un compte attendu
  et un secret de signature distinct. Les profils historiques doivent rester
  disponibles pour leurs notifications tardives.
- `STRIPE_CHECKOUT_PROFILE` : référence serveur utilisée pour les nouvelles
  commandes. Le client ne choisit jamais le compte ou le mode.
- `STRIPE_LEGACY_WEBHOOK_MODE` : conserve le mode du receiver historique même
  après bascule du nouveau checkout. Actuellement l'historique est en test.
- Chaque destination Stripe correspond à `/api/stripe/webhook/{reference}`.
  La clé de test et le secret d'un autre endpoint ne conviennent pas au réel.

L'adaptateur vérifie le compte avec le même SDK/identifiant que celui utilisé
pour créer la session. Le droit de nouvelles créations dépend également de la
garde datée en base et des offres, compatibilités et ports réellement exploitables.
Une chaîne de caractères configurée ne constitue pas une preuve commerciale.
Les clés seules ne déploient ni les migrations ni l'application.

## Dossier fournisseur et confirmation humaine

Administration authentifiée seulement :

1. `GET /api/admin/commerce/context/orders/{order_id}/tasks` : dossiers des groupes
   payés, fournisseur, référence exacte et agent figés. Recharger leur version.
2. `GET /api/admin/commerce/context/tasks/{task_id}/supplier-draft` : brouillon
   privé audité, explicitement non transmis. Les coordonnées client restent
   protégées par l'autorisation administrateur.
3. `POST /api/admin/commerce/context/tasks/{task_id}/advance` vers
   `supplier_confirmed` : fournir la référence obtenue et la preuve du contrôle
   de la référence, variante et montage. Ce geste administratif atteste une
   vérification humaine ; le logiciel n'invente pas une réponse du vendeur.
4. Tous les groupes doivent être contrôlés avant levée du marqueur de revue de
   compatibilité et passage global en préparation. Les incidents bloquent les
   nouvelles expéditions.

Chaque mutation exige `expected_updated_at`, `next`, `evidence_ref` et, à la
confirmation fournisseur, `supplier_order_ref`. Les preuves et associations déjà
enregistrées sont immuables. Une répétition identique ne crée pas une seconde
opération ; un autre contenu exige une revue, pas un écrasement silencieux.

Ces endpoints ne transmettent aucun message, ne paient rien et ne commandent
aucune pièce. Une référence renseignée par l'administrateur doit venir d'un
échange ou d'une opération réelle effectuée séparément avec les autorisations
nécessaires. HyperSKU ayant refusé les pièces, ne pas le présenter comme actif.

## Colis, suivi client et incidents

Le passage `supplier_confirmed → shipped` exige transporteur, numéro et URL de
suivi HTTPS, plus une preuve d'expédition. `shipped → delivered` exige une preuve
de livraison. Les références du colis expédié ne peuvent pas être remplacées.
Le marqueur `external_send_allowed` reste faux : il n'autorise aucun appel externe.

Un groupe correspond à un colis enregistré. Le statut global expédié/livré
n'est atteint qu'après progression de tous les groupes. Le client reçoit des
numéros et transporteurs dans la timeline existante, ainsi qu'une projection
`parcels` sans données fournisseur/coûts/preuves. Le bouton existant convient au
cas à un seul colis ; aucun nouveau bouton par colis ou écran n'a été ajouté.

Un incident financier après départ ne doit pas empêcher d'enregistrer l'arrivée
physique d'un colis déjà expédié. Cette preuve ne débloque ni le reste des colis,
ni les remboursements, ni une dépense, ni une notification financière en revue.

Les remboursements signés sont rapprochés du compte/profil/PI exact quand il est
présent et placent le dossier en revue, y compris s'ils arrivent avant le paiement.
Une identité de remboursement inconnue impose un rapprochement sur le profil
concerné. Aucun montant remboursé ni statut définitif n'est deviné. La projection
financière cumulative des nouveaux remboursements et la levée documentée de ces
revues restent un travail distinct : les reçus ne prouvent pas un SAV automatisé.

## Limites à ne pas masquer

Les recettes utilisent une base jetable, des offres/adresses/coûts synthétiques et
un transport fournisseur factice avec le vrai SDK Stripe. Elles ne prouvent pas
un accès marchand réel, une commande vendeur, une livraison, un envoi d'email ou
une concurrence PostgreSQL native multi-connexion. Aucun produit commercial réel
n'est approuvé par ces fixtures. L'ouverture nécessite les accès effectifs, les
offres réelles, un mode de livraison accepté et une validation de la version à
déployer. Le SIRET n'est pas utilisé comme prétexte pour suspendre ces travaux.
