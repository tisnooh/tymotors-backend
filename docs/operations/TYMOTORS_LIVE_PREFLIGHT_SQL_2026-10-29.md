# Préflight persistant du lancement : préparation fermée

Date : 29 octobre 2026. Développement SQL local uniquement.

## Périmètre

La migration `20261029012943_commerce_live_checkout_preflight.sql` ajoute des déclarations privées au singleton `shop_settings` existant. Elle ne modifie aucun CHECK sandbox, commande, tentative, réservation, journal financier ou droit client. Elle ne crée aucun endpoint d'activation et ne réalise aucun backfill d'approbation.

Le verrou `commerce_live_enabled` vaut false par défaut. Le statut `commerce_launch_registration_status` vaut pending par défaut ; declared_registered est uniquement une déclaration saisie par le service, sans vérification d'un registre officiel. Les champs optionnels sont une référence d'approbation, ses dates de début/expiration, une empreinte légale SHA256, le compte Stripe attendu et une référence opaque de profil d'exécution.

Ces champs n'authentifient ni un compte Stripe ni une identité légale. Leur présence ne certifie pas les offres fournisseurs, les compatibilités, les coûts, la livraison ou la capacité de fulfillment. L'immatriculation signalée en cours reste un blocage du lancement.

## RPC et confidentialité

`commerce_live_checkout_preflight(p_legal_fingerprint text, p_stripe_account_id text, p_profile_ref text) RETURNS jsonb` est réservé à service_role, SECURITY INVOKER, avec search_path vide. Les arguments doivent provenir du contexte serveur ; ils ne sont jamais une autorisation fournie par le client.

Le résultat contient uniquement allowed, live_checkout_implemented, configured, enabled et une liste de codes fixes blockers. Aucune identité de société, référence d'approbation, empreinte, compte, secret ou donnée client n'est renvoyé. La lecture de paramètres absents ou sans permission échoue fermée.

Les blocages sont indépendants : ouverture désactivée, immatriculation en attente, approbation absente/future/expirée, empreinte non confirmée/invalide/différente, compte non confirmé/invalide/différent et profil non confirmé/invalide/différent. L'horloge utilisée est celle de la base ; aucune date d'évaluation injectable n'est acceptée.

`live_checkout_not_implemented` est ajouté sans condition. Même des déclarations de test entièrement cohérentes produisent allowed=false et live_checkout_implemented=false. Aucun résultat de cette lecture ne peut autoriser une mutation future ; celle-ci devra vérifier sa politique dans sa propre transaction.

## Vérification

- Migration générée par la CLI Supabase locale, sans accès à une base hébergée.
- Compilation Python de `tests/commerce_launch_policy_http_probe.py` : PASS.
- Première recette du responsable : 655 contrôles pipeline et 233 contrôles préflight SQL PASS ; suite Python globale 2616 PASS. Ces chiffres précèdent le correctif de dates finies ci-dessous.
- Audit indépendant initial : REJECTED pour les dates PostgreSQL infinity/-infinity, qui pouvaient être déclarées comme une approbation temporellement valide. Le résultat demeurait pourtant allowed=false grâce au verrou d'implémentation ; le diagnostic temporel était insuffisant.
- Correction ciblée : CHECK isfinite sur chacune des deux dates, NULL autorisé ; quatre contre-tests SQL refusent infinity et -infinity sur chaque colonne. Aucun changement de sémantique RPC, de borne métier ni d'ouverture. Compilation Python après correction : PASS.
- Nouvelle recette indépendante :655 parcours +249 préflight PASS, sortie0.
  APPROVED LOCAL après contrôle index/worktree, empreintes et ports fermés.
  Chef accepte uniquement le diagnostic local ; aucun lancement réel autorisé.

La probe reprend la régression pipeline puis contrôle : valeurs fermées initiales, contexte absent/invalide, privilèges, exécution dans une transaction read-only, singleton absent, lecture refusée, déclarations complètes toujours bloquées, révocation, futur, expiration, divergences indépendantes d'empreinte/compte/profil, contraintes de stockage et absence de mutation des données de commande/journaux. Les déclarations true sont exclusivement des fixtures dans une transaction annulée.

## Limites et suite

État : PREPARED, aucune activation autorisée. Aucun appel Stripe, paiement, email, fournisseur, clé réelle, déploiement, changement visuel ou de prix. L'API settings existante ne peut pas écrire ces nouveaux champs grâce à ses champs explicites et à son schéma extra=forbid ; aucune bascule UI n'est ajoutée.

Le parcours réel reste à développer : création quoted liée au compte, tentatives/réservations, gateway vérifiée, associations de sessions, réception webhook contextuelle et journal financier. Le mode ENV courant ne devra pas requalifier les historiques sandbox. Les contraintes strictes existantes sont conservées dans ce lot ; aucune simulation n'est présentée comme une commande réelle exploitable.
