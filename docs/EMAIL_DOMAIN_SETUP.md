# Email actuel et futur domaine

## Configuration serveur unique

`EMAIL_FROM` = adresse d'expéditeur déjà vérifiée dans le fournisseur actuel (pas de valeur inventée). `EMAIL_FROM_NAME=TYMotors`. `EMAIL_REPLY_TO` facultatif, sinon utilise EMAIL_FROM. L'ancien `EMAIL_FROM_ADDRESS` reste un fallback pour ne pas casser un Render déjà configuré ; migrer vers EMAIL_FROM puis supprimer l'ancienne variable.

Brevo HTTPS : `EMAIL_ENABLED=true`, `EMAIL_PROVIDER=brevo`, `BREVO_API_KEY`, `EMAIL_TOKEN_SECRET` aléatoire ≥32 caractères. La présence de la clé Brevo donne priorité au transport HTTPS, endpoint fixe ; Render gratuit bloque généralement SMTP. Ni clé ni mot de passe dans le frontend. SMTP est seulement une alternative si l'hébergement permet ce transport : SMTP_HOST/PORT/USERNAME/PASSWORD/USE_TLS.

Test réel Windows, après variables serveur configurées dans le shell ou `.env` ignoré :

```powershell
cd C:\Users\utilisateur\Documents\ChatGPT\TyMotors\backend
.\.venv\Scripts\python.exe scripts\test_email_delivery.py
```

Le script envoie un seul message à l'expéditeur configuré lui-même. Il n'affiche aucune clé et refuse une configuration désactivée/incomplète. Vérifier ensuite réception, spam et événements Brevo : « accepté » n'est pas « reçu ». Si les secrets sont uniquement sur Render, utiliser le shell du service lorsqu'il est disponible ; sinon renseigner temporairement les variables dans un shell local privé, sans les copier dans le chat, Git ou un journal. Les tests automatiques utilisent un transport simulé, ils ne constituent pas une preuve d'envoi réel.

## DNS après achat du domaine

1. Créer l'adresse sur son fournisseur de messagerie, vérifier l'expéditeur dans Brevo, puis authentifier exactement son domaine/sous-domaine. Une adresse Gmail peut servir provisoirement si le fournisseur l'accepte, mais on ne possède pas son domaine : on ne peut pas authentifier gmail.com.
2. Dans Brevo, copier les enregistrements affichés : code de vérification TXT, DKIM (CNAME ou TXT selon la configuration) et, si proposé, sous-domaine branded/return-path. Ne pas inventer sélecteur, clé ni cible DNS.
3. SPF : un seul enregistrement TXT SPF par nom DNS. Fusionner les services réellement émetteurs selon leurs instructions. Brevo mutualisé utilise son infrastructure SPF ; ne pas ajouter automatiquement un `include` générique au domaine principal. Avec IP dédiée/return-path personnalisé, suivre les valeurs exactes données par Brevo. Le fournisseur de boîte mail peut exiger son propre SPF/MX.
4. DMARC : un seul TXT `_dmarc.<domaine>`. Commencer en observation avec le rapport vers une boîte que l'on contrôle, puis renforcer après analyse. Exemple de structure, **pas un enregistrement à copier tel quel** : `v=DMARC1; p=none; rua=mailto:<boite-de-rapports>`. Ne pas remplacer un DMARC existant sans concilier les autres émetteurs.
5. Attendre la propagation, cliquer Vérifier dans Brevo ; passer EMAIL_FROM à l'adresse professionnelle et EMAIL_REPLY_TO au support. Mettre à jour SITE_URL, LEGAL_CONTACT_EMAIL et redéployer. Vérifier un message réel et les résultats SPF/DKIM/DMARC dans ses en-têtes.

## Supabase Auth n'est pas la newsletter backend

Confirmation de compte et récupération de mot de passe restent gérées par Supabase Auth. Régler séparément son SMTP personnalisé : adresse vérifiée, serveur/port/login et **clé SMTP Brevo**, pas la clé REST BREVO_API_KEY. Régler Site URL et Redirect URLs pour `/auth/confirm` et `/reset-password`. Tester inscription, confirmation et récupération avec un compte de test. Changer EMAIL_FROM côté backend ne reconfigure pas automatiquement Supabase Auth.

## Sources fournisseur vérifiées le 12/10/2026

- [Authentification Brevo : code, DKIM, DMARC](https://help.brevo.com/hc/en-us/articles/12163873383186-Authenticate-your-domain-with-Brevo-Brevo-code-DKIM-DMARC)
- [Infrastructure SPF et return-path](https://help.brevo.com/hc/en-us/articles/35852083084178-Domain-setup-for-better-email-deliverability)
- [Exigences des messageries et IP dédiée](https://help.brevo.com/hc/en-us/articles/14925263522578-Comply-with-Gmail-Yahoo-and-Microsoft-s-requirements-for-email-senders)
- [SMTP personnalisé Supabase](https://supabase.com/docs/guides/auth/auth-smtp)
