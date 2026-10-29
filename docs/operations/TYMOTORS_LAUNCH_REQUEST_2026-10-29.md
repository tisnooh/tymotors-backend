# Demande d'ouverture commerciale —29octobre

Le propriétaire demande de retirer le mode test et lancer le site. Il confirme
ensuite que l'immatriculation est encore en cours. Aucune identité légale ou
information fournisseur n'est créée pour franchir artificiellement les contrôles.

Vérification publique effective, lecture seule :

- /api/site-config : stripe_mode=test, test_catalog_available=true,
  legal_ready=false, aucun des14champs légaux renseigné.
- /api/products?limit=100 :40articles,40draft,40test_purchase=true,
  aucun stock positif. Ce n'est pas un catalogue commercial activé.
- Les badges frontend correspondent actuellement à test_purchase retourné par
  le serveur. Enlever le texte ne rendrait pas les produits commercialisables.

Accès : le connecteur Stripe exige un link_id non disponible dans cette session.
Le navigateur local est explicitement désactivé dans les réglages Work ; aucun
compte réel n'a pu être inspecté. Cela ne prouve pas que le propriétaire n'en
possède pas. Aucune clé secrète demandée dans le chat ou exposée.

Technique restant réellement à construire : commandes/devis, réservations,
session, règlement et remboursements liés à un compte authentifié en production.
Les contraintes SQL et les deux routes checkout restent sandbox-only. Les
préparations et tests précédents ne valident pas ce parcours réel.

Les cinq produits pilotes restent sans approbation commerciale sur les preuves
disponibles. Les références retenues, coûts, disponibilité et livraison doivent
être justifiés pour l'offre réellement vendue ; pas de faux stock ou de port.

Décision de ce contrôle : NOT_READY_FOR_LIVE. Aucun flag changé, produit promu,
paiement déclenché ou déploiement. Design/images/prix conservés. L'ouverture
nécessite les données réelles de l'entreprise, l'accès sécurisé au compte Stripe
réel, les offres exploitables et la recette technique du parcours production.

Source Stripe consultée : https://docs.stripe.com/get-started/checklist/go-live
Les webhooks live doivent être enregistrés et vérifiés séparément du sandbox.
