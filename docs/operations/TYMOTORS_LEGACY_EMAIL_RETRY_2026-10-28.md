# Notifications legacy : reprise prudente — 28 octobre 2026

Périmètre local uniquement : service email existant, endpoint administratif de
reprise et tests dédiés. Aucun SMTP/Brevo réel, serveur, paiement, fournisseur,
déploiement, migration, photographie, prix ou changement de design.

## Défaut corrigé

Le transport pouvait accepter le message, puis l'enregistrement `sent` échouer.
Le journal devenait `failed` et une reprise pouvait renvoyer le même message.
Un ancien `queued` n'est pas davantage une preuve d'absence d'envoi.

## Règles

- Une notification legacy est reprenable uniquement si `event_snapshot` est nul,
  son statut est `failed` et son erreur vaut exactement
  `Email delivery is not configured`. Cette issue est enregistrée avant toute
  entrée dans le transport. Un message fournisseur ou une ancienneté ne sont
  jamais utilisés comme preuve de non-envoi.
- La prise est un UPDATE conditionnel atomique : même identifiant, destinataire,
  statut et erreur. Elle passe à `queued` et efface la preuve avant le transport.
  Une réponse de prise perdue n'autorise aucun transport ni nouvelle tentative.
- Une exception après entrée dans le transport ou une confirmation DB absente
  donne `unknown`. Si possible, le journal garde une erreur fixe exigeant une
  revue fournisseur manuelle. Un `sent` déjà committé ne peut pas être rétrogradé
  par l'enregistrement d'une erreur tardive.
- Un `queued`, même ancien, ou un échec ambigu exige une revue manuelle. Aucun
  historique n'est converti en outbox. Les notifications fulfillment gérées
  conservent leur chemin existant ; leurs anciennes lignes restent bloquées.
- L'API de reprise ne renvoie `accepted=true` que si le résultat contient
  explicitement `sent=true`, et non simplement parce qu'un dictionnaire existe.

## Vérifications et limites

Dernier passage local ciblé : **98 tests PASS en 8,00 s**, couvrant
`test_legacy_email_retry`, `test_email_system`, `test_order_notification_outbox`
et `test_order_dispatch_api`. Avertissement Starlette/httpx préexistant.
Pas de recette SMTP/Brevo ni de déploiement ; contre-audit encore requis.

Tests dédiés : configuration désactivée puis rétablie, acceptation du transport
puis panne DB, réponse DB perdue après commit, timeout fournisseur, impossibilité
de journaliser l'incertitude, reprises concurrentes, claim perdu, destinataire
divergent, anciennes lignes `queued`, autorisations et réponse HTTP.

Les transports sont injectés localement et le client HTTP reste en mémoire,
sans lifespan ni accès extérieur. Le double de base vérifie les filtres et
l'exclusion atomique dans la boucle d'événements ; il ne démontre pas une
concurrence native PostgreSQL/PostgREST multi-connexion.

Restriction assumée : certains envois réellement non effectués mais sans preuve
durable suffisante restent bloqués. Aucun renvoi forcé, worker automatique,
rapprochement fournisseur ou garantie d'envoi exactement une fois n'est ajouté.
Ce lot ne rend pas durables les créations de notifications financières dans la
transaction de paiement ; cette limite antérieure est distincte de la reprise.
