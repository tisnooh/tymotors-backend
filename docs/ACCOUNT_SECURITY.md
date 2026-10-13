# Sécurité des comptes — actions du propriétaire

État vérifié le 13 octobre 2026. Aucun mot de passe, clé, QR TOTP ou code de
récupération à coller dans le chat ou dans Git. Pas de changement de forfait,
d'activation Stripe live ni de 2FA sur l'admin de la boutique.

## 1. Révoquer le mot de passe Gmail exposé — priorité haute

1. Ouvrir [Mots de passe d'application Google](https://myaccount.google.com/apppasswords)
   avec le compte qui a créé le mot de passe TYMotors montré dans l'ancienne capture.
2. **Révoquer/supprimer uniquement cet ancien mot de passe d'application**.
   Ne pas supprimer une entrée d'un autre projet. Masquer la valeur à l'écran.
3. Si TYMotors utilise Brevo (`EMAIL_PROVIDER=brevo`, clé Brevo présente),
   ne pas recréer un mot de passe Gmail inutile : retirer l'ancien SMTP_PASSWORD
   des services TYMotors qui ne l'utilisent plus, dans leurs dashboards privés.
   Préserver BREVO_API_KEY, EMAIL_FROM et l'adresse expéditrice vérifiée.
4. Si un service utilise encore SMTP, créer soi-même un nouveau mot de passe
   dédié et le remplacer **directement dans ses variables privées**, puis
   redéployer et tester un mail vers sa propre adresse. Render Free bloque
   SMTP sortant : conserver Brevo pour ce service, pas de montée de forfait requise.
5. Contrôler sessions/appareils Google inconnus et confirmation de révocation.
   L'ancien mot de passe ne doit plus apparaître dans la liste. Ne pas publier
   le nouveau secret, ne pas réutiliser l'ancien, ne pas coller de capture avec
   sa valeur. La suppression d'une variable seule ne révoque pas le secret Google.

La révocation et le mail après rotation n'ont **pas** été exécutés par l'agent.
Gitleaks clean ne prouve pas qu'un secret partagé dans le chat n'est pas compromis.
[Instructions Google](https://support.google.com/accounts/answer/185833?hl=fr).

## 2. MFA des comptes — à activer soi-même

Utiliser une app d'authentification, une passkey ou une clé matérielle selon le
fournisseur ; conserver la récupération hors chat/Git. Tester une nouvelle
connexion en gardant une session existante ouverte avant de modifier les accès.
Ne pas imposer une politique d'équipe avant d'avoir sécurisé son propre compte.

| Compte | Action / documentation officielle | État réellement constaté |
| --- | --- | --- |
| Google | Sécurité du compte, validation en deux étapes, revue appareils/app passwords. | Un ancien app password existe dans l'historique du chat ; révocation non attestée. |
| GitHub | Settings → Password and authentication → 2FA/passkeys. | API utilisateur : champ MFA non retourné (`null`), état non confirmé. |
| Stripe | Paramètres personnels → sécurité → authentification à deux étapes ; rester dans sandbox. [Guide](https://support.stripe.com/questions/two-step-authentication-requirement). | Enrôlement non vérifié, aucune clé live créée. |
| Vercel | Account Settings → Authentication → 2FA. [Guide](https://vercel.com/changelog/2fa-is-now-available). | Enrôlement non vérifié. |
| Render | Account Settings → Account Security → 2FA. [Guide](https://render.com/docs/login-settings). | Enrôlement non vérifié ; service Free conservé. |
| Supabase | Account Settings → MFA. [Guide](https://supabase.com/docs/guides/platform/multi-factor-authentication). | Enrôlement non vérifié. Supabase n'émet pas de recovery codes : enregistrer un facteur TOTP de secours séparé selon le guide. |
| Brevo | Sécurité du compte et MFA, revue des clés utilisées. | Enrôlement non vérifié ; aucune clé copiée/régénérée ici. |
| MongoDB Atlas | MFA et rôles réseau, seulement si effectivement utilisé. | Non utilisé par le backend actuel (Supabase PostgreSQL), pas d'audit Atlas prétendu. |

## 3. Infrastructure : vérifié / restant

- Supabase Paris, production et staging : RLS activé sur toutes les tables
  publiques ; anon sans SELECT orders/admin_audit ; TLS on, minimum 1.2.
  Tables fournisseurs/événements sans policy client volontairement privées.
  `private.is_admin()` est un helper self-only de RLS, pas une mutation publique.
- Protection mots de passe compromis : désactivée en production d'après advisor,
  pas de même warning staging. Vérifier l'option et le plan ; ne pas acheter un
  plan automatiquement et ne pas ouvrir de policies pour faire disparaître les INFO.
- PostgreSQL 17.6 annoncé sur les deux bases : vérifier la proposition d'upgrade
  au dashboard, après export chiffré + restauration staging. Aucun upgrade lancé.
- Sauvegarde réelle et restauration : **non exécutées**. Suivre BACKUPS.md,
  stockage externe chiffré et credentials opérateur privés. Les tests de script
  avec fixtures ne constituent pas une sauvegarde de la boutique.
- GitHub : protection main(frontend)/develop(backend) absente à l'API. Configurer
  PR/revue + CI requise, sans force-push ni suppression de branche. Actions
  verrouillées sur SHA et token checkout non persisté dans le correctif code.
- Audits : nouveau frontend → 1 avis braces non corrigé ; baseline CI expire
  le 13 novembre 2026. Python → audit strict CI. Ne pas traiter une indisponibilité
  de l'audit comme une réussite, ne pas étendre silencieusement l'exception.
- Hébergement : vérifier domaine/TLS/redirections et secrets privés au dashboard,
  pas de sk_test/service-role/Brevo dans REACT_APP_*. Debug/reload production
  désactivés ; Stripe test uniquement. Un healthcheck ne remplace pas les parcours.

Toutes ces actions de compte restent à compléter par le propriétaire. Ce guide
est une procédure, pas une attestation de MFA, révocation ou sauvegarde réussie.
