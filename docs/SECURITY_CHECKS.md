# Contrôles ciblés avant mise en vente

Ce travail est un durcissement ciblé, pas un audit exhaustif ni une certification.

- Connexion client/admin via `/api/auth/login` : 5 requêtes/minute/IP, 8/15 minutes/identité ; clé publique Supabase uniquement, mot de passe non stocké, erreurs non énumérantes.
- Checkout : limites par IP et par identité/panier ; newsletter, récupération de compte, contact et suivi sont également limités. Réponse 429 avec Retry-After.
- Ne jamais interpréter X-Forwarded-For dans le code. Sur Render, vérifier les proxys réellement approuvés dans Uvicorn (`FORWARDED_ALLOW_IPS`), jamais `*` sans isolation réseau démontrée. Sinon la limite par IP peut agréger tous les utilisateurs derrière un proxy.
- Les limites sont en mémoire, par processus, et disparaissent au redémarrage : un stockage partagé/WAF est nécessaire pour une garantie multi-instance.
- Supabase Auth reste accessible directement aux clients : configurer ses propres limites, CAPTCHA et MFA admin. La limite API ne remplace pas cette protection fournisseur.
- Rôles admin vérifiés côté serveur dans `profiles`, tables privées en RLS, secrets réservés au backend, écritures privilégiées auditées. Les clés service contournent RLS : ne jamais les exposer au frontend.
- Origines CORS explicites via variables, sans wildcard ; origine HTTPS stricte, credentials interdits dans les URLs. Test Stripe par défaut, live refusé si identité légale absente.
- API privée : no-store ; nosniff, anti-frame, CSP, permissions et HSTS HTTPS. Frontend : CSP Vercel existante conservée, polices sans script inline bloqué.
- Les nouveaux domaines API doivent être ajoutés à l'allowlist CSP `frontend/vercel.json` avant déploiement ; conserver l'URL Render actuelle évite cette modification. Tester les redirections Auth sur le nouveau domaine.

Restants avant production : audit dépendances et mises à jour compatibles, rotation des secrets déjà partagés ailleurs, MFA, sauvegarde/restauration testée, revue des accès opérateurs, logs sans données personnelles superflues, purge/rétention effective. Prévoir un audit indépendant et une surveillance, pas seulement un build réussi.

Supabase advisors, 12/10/2026 : cinq informations RLS sans policy sur des tables volontairement privées sur chaque base. Production signale aussi la protection contre mots de passe compromis désactivée ; [option disponible à partir du plan Pro](https://supabase.com/docs/guides/auth/password-security). Aucun achat ni changement de plan effectué. Activer si le plan le permet ; sinon renforcer politique de mots de passe et MFA. `npm audit` ne peut pas auditer ce dépôt Yarn sans lockfile npm ; ne pas créer un second lockfile contradictoire. Vérification de dépendances à faire avec l'outil adapté au lockfile Yarn avant ouverture.
