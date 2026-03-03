# Guide Citizen Dev — AI Governor

Bienvenue ! Ce guide est fait pour toi si tu utilises des outils IA (Claude, Cursor, GitHub Copilot…) pour développer sur les projets Your Art / ArtMajeur. Pas besoin d'être développeur pour le lire — on a fait simple.

---

## Qu'est-ce que l'AI Governor ?

L'AI Governor est un **assistant bienveillant** qui travaille en arrière-plan sur les repositories GitHub et GitLab de l'organisation.

Son rôle ? **T'aider à avancer plus vite** en te signalant les choses utiles :

- Un module qui existe déjà et qui fait ce que tu essaies de coder
- Un collègue qui travaille sur quelque chose de similaire
- Un problème de sécurité dans ton code (une clé API qui traîne, par exemple)
- Ton budget API qui commence à fondre

Ce n'est pas un surveillant. Il ne juge pas ton code, ne le modifie jamais, et ne bloque rien. Il observe et te fait des suggestions — libre à toi de les suivre ou non.

---

## Ce que l'agent fait pour toi

### Détection de duplications

Tu codes un système de recherche ? L'agent vérifie s'il en existe déjà un dans les repos de l'organisation. Si oui, il te le signale pour t'éviter de réinventer la roue.

### Suggestions de ressources existantes

L'organisation dispose de nombreuses ressources : modules internes, outils MCP (bases SQL, MongoDB, BigQuery, HubSpot), repos GitLab… L'agent connaît ce catalogue et peut te dire "Hé, il y a déjà un outil pour ça".

### Alertes budget

Chaque citizen dev a un budget API mensuel. L'agent te prévient quand tu approches de ta limite, pour que tu ne sois pas coupé en plein travail.

### Détection de credentials en clair

Si tu commites par accident une clé API, un mot de passe ou un token dans ton code, l'agent le détecte et te prévient immédiatement. C'est l'une des protections les plus importantes.

---

## Types de notifications

Tu recevras des notifications sur Google Chat. Voici les types que tu peux rencontrer :

### 🔍 Duplication détectée

> *"Il existe déjà un module similaire dans le repo `artmajeur-search` qui gère la recherche full-text. Tu veux peut-être le réutiliser plutôt que de recoder cette partie."*

### 🤝 Convergence avec un collègue

> *"Ton projet a des similitudes avec ce que Théo développe sur GitLab (`recommendation-engine`). Ça vaudrait le coup d'échanger pour mutualiser vos efforts."*

### 💰 Alerte budget

> *"Tu as consommé 80% de ton budget API mensuel. Il te reste environ 60€ sur les 300€ alloués."*

### 🔑 Credential en clair

> *"Une clé API a été détectée dans ton dernier commit (`config.py`, ligne 42). Merci de la retirer et d'utiliser le vault pour stocker tes secrets."*

---

## Comment réagir

### Duplication ou convergence

- **C'est pertinent** — Regarde la ressource suggérée. Si elle fait ce dont tu as besoin, réutilise-la. Tu gagneras du temps.
- **Ce n'est pas pertinent** — Pas de souci, ignore le message. Si tu veux aider l'agent à s'améliorer, clique sur **"Marquer faux positif"** dans la notification. Ça affine les futures détections.
- **Tu n'es pas sûr** — Demande à ton gouverneur (admin) ou au collègue mentionné. Personne ne t'en voudra de poser la question.

### Alerte budget

- **Réduis ta consommation** si tu peux (moins d'appels API, modèles moins coûteux)
- **Contacte ton gouverneur** si tu as besoin d'un budget supplémentaire pour finir ton projet

### Credential en clair

- **Retire la clé de ton code** dès que possible
- **Utilise le vault** pour gérer tes secrets de manière sécurisée
- Si tu ne sais pas comment faire, demande de l'aide — c'est normal, et c'est important

---

## FAQ

**L'agent peut-il modifier mon code ?**
Non. L'AI Governor ne fait qu'observer et notifier. Il n'a aucun droit d'écriture sur tes repositories. Ton code reste le tien.

**Qui voit mes données ?**
Seuls les gouverneurs (admins de l'organisation) ont accès aux rapports de l'agent. Il ne partage pas ton code avec d'autres citizen devs.

**Comment donner du feedback ?**
Deux options :
- Les **boutons dans les notifications** Google Chat (Faux positif, Utile, etc.)
- La commande `/governor.advisor feedback` si tu utilises Claude Code

Ton feedback est précieux — il aide l'agent à devenir plus pertinent.

**Puis-je désactiver les notifications ?**
Ce n'est pas prévu en self-service pour le moment. Si les notifications te gênent, parles-en à ton gouverneur — on trouvera une solution.

**C'est quoi un "faux positif" ?**
C'est quand l'agent signale une duplication ou un problème qui n'en est pas un. Par exemple, deux modules qui utilisent le même nom de fonction mais font des choses totalement différentes. En signalant les faux positifs, tu aides l'agent à mieux comprendre le contexte.

**L'agent ralentit-il mon travail ?**
Non. Il tourne en arrière-plan et analyse les événements (commits, pull requests) de manière asynchrone. Tu ne remarqueras aucun impact sur tes outils.

**Je ne comprends pas une notification, que faire ?**
Pas de stress. Demande à ton gouverneur ou ignore-la. L'agent ne bloque jamais rien — tu peux toujours continuer à travailler.

---

*Ce guide est maintenu par les gouverneurs de YourArtOfficial. Dernière mise à jour : mars 2026.*
