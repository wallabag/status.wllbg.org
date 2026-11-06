# status.wallabag.it

Tout se fait depuis une issue GitHub, y compris depuis l'app mobile. La page est en ligne une à deux minutes après chaque action.

## Signaler un incident ou une maintenance

1. Ouvrir une nouvelle issue avec le modèle **Status page incident / maintenance**.
2. Compléter le texte pré-rempli (valeurs par défaut : incident `down` sur app.wallabag.it, maintenant) :
   - **Titre de l'issue** : le titre affiché sur la page.
   - **Type** : `Incident` ou `Scheduled maintenance`.
   - **Severity** : `down` (indisponible), `disrupted` (dégradé) ou `notice` (information).
   - **Affected systems** : un ou plusieurs systèmes, séparés par des virgules.
   - **Start (UTC)** : `AAAA-MM-JJ HH:MM`, vide pour maintenant.
   - **Message** : le texte affiché (Markdown). Obligatoire.
   - **Mastodon** : remplacer `[ ]` par `[x]` pour ne pas publier sur Mastodon.
3. Valider. Un commentaire confirme la publication avec le lien de la page. En cas d'erreur, corriger l'issue : elle est publiée dès qu'elle est valide.

## Mettre à jour

Commenter l'issue :

- `/update <message>` : ajoute une mise à jour.
- `/severity down|disrupted|notice [message]` : change la sévérité.
- `/resolved [message]` : marque comme résolu et ferme l'issue.

Fermer l'issue revient à `/resolved`. La rouvrir remet l'incident en cours.

## Bon à savoir

- Une maintenance future s'affiche en `notice`. Commenter `/severity down` quand elle commence.
- L'incident est publié sur Mastodon (@wallabagit@fosstodon.org), et sa résolution en réponse.
- Seuls les membres et collaborateurs du dépôt peuvent publier.
- Les heures sont en UTC.
