# Demande d'ouverture commerciale —29octobre

## Avancement technique après ce constat

Le checkout par compte/profil est désormais implémenté et APPROVED LOCAL :
2 842 tests Python,655 historiques +250 contrôles SQL/HTTP, avec contre-exécution
indépendante. Les descriptions « routes uniquement sandbox » ci-dessous décrivent
le constat initial, pas le nouveau code. Aucun déploiement de ce code n'a eu lieu.
Les comptes Stripe, offres et prestations réels ne sont pas validés par ces tests.
La progression logistique manuelle et les remboursements nouveaux sont traités
dans une tranche séparée. Voir les rapports CONTEXT_CHECKOUT_INDEPENDENT_AUDIT
et CONTEXT_SQL_EXECUTION pour le périmètre exact.

## Rectification après retour du propriétaire

L'immatriculation en cours ne doit pas être présentée comme une interdiction
générale de commencer ni comme un blocage du développement ou des tests sans
encaissement. Pour une micro-entreprise ou une entreprise individuelle, Service
Public précise que la demande peut être déposée au plus tard dans les quinze
jours suivant le début d'activité. Un chiffre d'affaires nul ne constitue pas,
à lui seul, une dispense générale de déclaration d'activité.

Source officielle consultée le29octobre2026 :
https://entreprendre.service-public.gouv.fr/vosdroits/F36746
https://entreprendre.service-public.gouv.fr/vosdroits/F36763

Le champ légal manquant est un constat de configuration, pas une preuve que
toute activité avant réception du SIRET serait interdite. Le préflight actuel
est une politique technique conservatrice, pas une détermination juridique.
Continuer les travaux et les tests autorisés sans attendre le SIRET. L'ouverture
effective reste à évaluer selon la forme d'activité réellement choisie, les
exigences du prestataire de paiement et les capacités commerciales disponibles.
Ne pas déduire de cette correction que Stripe réel ou la logistique sont prêts.

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
