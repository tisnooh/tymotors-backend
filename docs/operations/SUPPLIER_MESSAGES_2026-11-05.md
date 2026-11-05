# Réponses fournisseurs — 5 novembre 2026

## Réponse CJ effectivement lue

Gmail `1a1a909928d6dbce`, fil `1a181738767320c7`, support CJ, reçu le 5 novembre à00:08:55 UTC (01:08:55 Paris).

Le support e-mail ne peut pas vérifier les traces internes ni les paramètres propres au compte. Il explique que HTTP429/code1600200 peut correspondre à la limite de requêtes par seconde ou à la règle de trois utilisateurs par IP sortante ; une pause d'une seconde ne résout pas nécessairement une limite d'IP partagée. Ce sont des causes possibles, pas un diagnostic confirmé du compte TYMotors. CJ demande de fournir les deux request IDs, l'IP sortante actuelle et des captures dans le ticket connecté ou le chat support.

Ticket existant : `T202610311023101331`. Request IDs déjà transmis : `deb941dc230640c39d923a085d67fe2e` et `ef187dd20df8440289e112a68690f691`.

La [documentation Render](https://render.com/docs/outbound-ip-addresses) confirme que les plages sortantes sont partagées entre services d'une même région. Le backend est à Frankfurt. **L'IP exacte utilisée pour les deux requêtes n'a pas été relevée** ; ne pas utiliser l'IP du poste Windows ou l'adresse entrante du backend à sa place. Dans Render : service → Connect → Outbound pour les plages ; celles-ci ne prouvent pas à elles seules l'IP exacte de chaque requête.

## Complément de ticket préparé, non envoyé

872 caractères, dans la limite1000 du formulaire CJ observé. Relever l'IP/plages réelles et joindre les diagnostics autorisés dès que le navigateur est réactivé ; conserver le même ticket, sans nouvelle demande de sourcing en double.

> Following your 5 Nov email (00:08 UTC), please ask the API team to investigate CJ4321861. Authentication succeeds, then GET /api2.0/v1/shop/getShops returns HTTP429/code1600200. Request IDs: deb941dc230640c39d923a085d67fe2e and ef187dd20df8440289e112a68690f691. Our backend is on Render Frankfurt, whose outbound IP ranges are shared; the actual IP for these requests still needs verification. We use one account and one process, serial requests, >1s after each response, no automatic retries. Please trace the outbound IP and distinguish QPS from the one-IP/3-users limit; advise a supported resolution under our current plan before any paid option. Please keep the free provisional MR3BF2021 Service Product/France quote preparation separate from this API issue and provide the genuine shop/product/variant IDs when ready. No purchase, shipment or payment is authorised.

## Accès et absence de nouveaux engagements

- Le contrôle du 5 novembre06:40 Paris renvoie explicitement `Local browser use is disabled in Work settings`. Aucun site n'est accessible par ce contrôleur ; demander sa réactivation plutôt que simuler une lecture ou modifier les réglages de l'application par un autre moyen.
- Aucun nouveau message technique Soyintech dans la recherche Gmail ciblée depuis le4novembre ; la réponse du4novembre reste la dernière exploitable trouvée. Ne pas renvoyer la clarification déjà partie.
- Aucun nouvel appel API CJ, achat, envoi de commande ou abonnement payant. L'IP partagée reste une piste à faire confirmer, pas une raison de contourner une limite ou d'acheter une option sans décision.
