# TYMotors — checklist de lancement

État vérifié le **4 novembre 2026 au soir (Paris)**. Remplace la photographie du 12 octobre ; l'historique reste dans [le journal](operations/TYMOTORS_PROGRESS.md).

**Stripe est en mode réel. Aucun produit commercial n'a encore toutes les données nécessaires à son activation. La réception d'une commande TYMotors par CJ n'est pas démontrée.**

## Terminé et vérifié

- [x] Derniers correctifs CJ publiés : backend `0ba3cb6` sur Render et administration `3adcb85` sur Vercel.
- [x] Configuration publique HTTP 200 : `stripe_mode=live`, `test_catalog_available=false`.
- [x] Diagnostic Stripe réel à 0 € enregistré jusqu'à la commande interne `TY-DIAG-A19A1078153E4695`, avec webhook reçu. Sans stock commercial, achat ou expédition. Ne pas le confondre avec une vente physique.
- [x] Authentification CJ contrôlée, agent Wazza identifié. Cela ne prouve pas le mapping ni le traitement d'une commande.
- [x] Brouillons CJ protégés par réservation durable et confirmation humaine ; pas de paiement, pas de renvoi automatique d'un résultat incertain. Migration publiée.
- [x] Dernier lot technique : 529 tests backend locaux, contrôles SQL/CI et 512 tests frontend CI réussis. Aucune livraison réelle déduite de ces tests.
- [x] Demandes consolidées auprès de Soyintech et CJ, sans achat. Complément technique envoyé ce soir au support CJ : Gmail `1a1a87a9054a7be4`.
- [x] Design, photographies et prix publics conservés dans ce cycle.

## Mesures en production

Contrôle SQL en lecture seule, hors archives et fixtures :

| Indicateur | Valeur | Limite |
| --- | ---: | --- |
| Articles commerciaux | 40 | 42 lignes avec deux archives internes |
| Articles actifs | 0/40 | Aucun ouvert à la vente |
| Stock positif | 0/40 | Aucun stock à inventer |
| Articles vérifiés | 0/40 | Aucune validation commerciale complète |
| Compatibilités commerciales vérifiées | 0 | La seule règle globale vérifiée appartient à une fixture staging archivée |
| Offres fournisseur vérifiées | 0 | Réponse partielle différente d'une offre complète |
| Prix d'achat renseignés en base | 0 | Le devis mail USD n'est pas encore un coût complet EUR |
| Prix de livraison renseignés en base | 0 | Aucun tarif unitaire client confirmé |
| Marges commerciales calculables | 0 | Coûts incomplets |
| Liens produit–fournisseur | 8 | Huit associations, pas huit fournisseurs |
| Commandes commerciales | 0 | 15 tests/diagnostics internes exclus |
| Soumissions CJ enregistrées | 0 | Aucune réception CJ prouvée |

## À faire, dans l'ordre

| Fait | Tâche | Responsable | Prochaine preuve/action |
| --- | --- | --- | --- |
| [ ] | Lire la dernière réponse CJ | CODEX / accès navigateur | Ticket `T202610311023101331` : notification reçue, contenu non lu. Contrôleurs navigateur et secours Windows sans réponse ce soir ; reprendre ce ticket après rétablissement. |
| [ ] | Résoudre le 429 CJ sur la lecture des boutiques | CJ puis CODEX | Support saisi avec deux request IDs. Obtenir diagnostic compte/IP/endpoint et cadence/cooldown avant un nouvel essai ; pas de boucle. |
| [ ] | Compléter la variante pilote | Soyintech | Pour `MR3BF2021` : ABS noir brillant de remplacement, exclusions rétroviseurs d'origine, stock/départ, dimensions et poids brut emballés, traitement des défauts. Clarification déjà envoyée. |
| [ ] | Enregistrer le mapping exact | CJ / CODEX | Produit de service, variante, SKU, véritable ID boutique et correspondance avec le produit TYMotors. Création gratuite annoncée mais IDs non reçus dans les réponses lues. |
| [ ] | Chiffrer une commande unitaire France | Soyintech / CJ | Port Chine, réception, QC, emballage, transport France, devise, validité, délais, suivi et retours. Les 138 USD historiques portent sur cinq pièces groupées. |
| [ ] | Calculer coût complet et marge | CODEX | Conserver preuve/date/devise ; ne pas saisir le montant USD dans un champ EUR. Conversion et hypothèses explicites, prix public inchangé. |
| [ ] | Compléter les informations vendeur | ADMINISTRATEUR / CODEX | Champs réellement vides ci-dessous. Ne pas inventer une identité, un numéro ou un médiateur. |
| [ ] | Créer un brouillon CJ non payé et vérifier sa présence | CODEX après données exactes | Une réservation, confirmation humaine, ID distant et présence chez CJ. Aucun paiement ni achat fournisseur. |
| [ ] | Recetter le parcours complet du premier produit | CODEX / fournisseur-CJ | Véhicules compatible/incompatible, variante, stock, devis, total, paiement contrôlé, webhook unique, commande, agent, CJ, puis suivi. Distinguer simulation et expédition réelle. |
| [ ] | Valider cinq pilotes puis étendre aux autres | CODEX / audit indépendant | Aucun blocage essentiel ; offre, compatibilité, coût rendu et livraison prouvés pour chaque produit. |
| [ ] | Autoriser l'achat fournisseur et l'ouverture effective | ADMINISTRATEUR | Décision après recette ; aucun engagement financier automatique. |

## Pilote : preuves reçues et manquantes

`TY-BMW-F30-F32-MIRROR-CAPS`, produit `e46bf5e1-d459-44ca-b28d-70c01c5c14e7` : Soyintech/Nicy, Gmail `1a1a53ecf2cf214d`, 4 novembre 07:28 Paris. Référence `MR3BF2021`, **16 USD la paire gauche/droite**, MOQ une paire ; F30 berline 2013–2018 explicitement cité. Données annoncées par paire : 32 × 22 × 17 cm, 0,6 kg, caractère emballé/brut à confirmer. Livraison à un entrepôt tiers chinois acceptée ; port selon adresse, transit intérieur normalement 1–3 jours ouvrables, distinct du délai client France.

Ne pas généraliser aux F32, carrosseries, années et équipements sur la similarité du titre. Variante exacte et restrictions restent en clarification, Gmail `1a1a6695622def89`. Aucun stock ou poids emballé confirmé à partir de cette réponse.

CJ annonce le 4 novembre à 13:02:56 (heure affichée) préparer un Service Product gratuit et fournir les IDs/devis. Une notification Gmail `1a1a78f5f5189c2a` reçue à 18:15:50 Paris annonce une nouvelle réponse : **son contenu reste à lire**, pas une preuve que les IDs sont arrivés.

## Configuration qui ferme actuellement le checkout

Le contrôle public du soir retourne `legal_ready=false`. `app/site_config.py` et `src/pages/Cart.jsx` conditionnent le panier réel à ce booléen. Les dix champs exigés par le code sont vides :

`LEGAL_COMPANY_NAME`, `LEGAL_SIRET`, `LEGAL_ADDRESS`, `LEGAL_CONTACT_EMAIL`, `LEGAL_CONTACT_PHONE`, `LEGAL_VAT_MENTION`, `LEGAL_MEDIATOR_NAME`, `LEGAL_MEDIATOR_URL`, `LEGAL_HOSTING_DETAILS`, `LEGAL_RETURNS_ADDRESS`.

C'est le comportement mesuré de l'application, pas une conclusion générale sur le démarrage d'une activité avec immatriculation en cours. Toute adaptation doit utiliser les informations réelles du vendeur ; ne pas forcer le booléen ni fabriquer un numéro. Ne transmettre aucune clé secrète dans le chat.

## Vérifications restantes de qualité

- [ ] Vérifier le nouveau libellé de l'administration : `is_test=true` peut désigner un diagnostic gratuit Stripe live et ne prouve pas le mode sandbox. Correction textuelle préparée sur `codex/launch-checklist-label`, revue indépendante APPROVED, 7 tests Commerce et lint réussis ; publication et contrôle visuel non effectués. Aucun changement de logique ni styles.
- [ ] Vérifier visuellement mobile/ordinateur après rétablissement du contrôleur navigateur.
- [ ] Surveiller la latence initiale : `/api/health` 24,05 s au premier contrôle, puis `/api/site-config` 0,34 s. Mesure ponctuelle, cause non établie ; aucun abonnement payant activé.
- [ ] Vérifier confirmations client et suivi multicolis dans la recette du premier produit ; le diagnostic gratuit ne prouve pas la livraison physique.

## Preuves et reprise

- [Contrôle CJ publié](operations/CJ_ADMIN_RUNTIME_2026-11-04.md).
- [Messages fournisseur](operations/SUPPLIER_MESSAGES_2026-11-04.md).
- [Diagnostic gratuit](operations/ZERO_CHECKOUT_LIVE_RESULT_2026-11-03.md).
- [Progression](operations/TYMOTORS_PROGRESS.md).

Reprise : lire le ticket existant, traiter la réponse, relier uniquement des IDs authentiques, compléter variante et devis, tester le brouillon non payé. Conserver les 40 fiches en brouillon tant que leurs preuves manquent, sans stock fictif ni mention de disponibilité trompeuse.
