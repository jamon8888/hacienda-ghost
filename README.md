# Hacienda Ghost

> Recherche dans vos documents, confidentielle, pour avocats, notaires,
> médecins et professions réglementées — directement dans Claude Desktop.

Hacienda Ghost combine un moteur d'anonymisation local (`piighost`) et
un plugin Cowork (`hacienda`) pour que votre travail avec Claude
Desktop ne fasse jamais sortir vos données clients vers le cloud.

---

## Ce que ça fait pour vous

Hacienda Ghost ajoute quatre capacités à Claude Desktop, sans que vos
données quittent votre poste :

- **Recherche dans vos dossiers clients.** Indexation locale d'un
  dossier complet (PDF, Word, Excel, CSV, e-mails, notes). Les
  réponses de Claude citent les fichiers d'origine, sans transmettre
  les noms, IBAN, ou adresses au cloud.
- **Registre RGPD Art. 30 généré en une commande.** Le registre des
  activités de traitement, conforme aux exigences CNIL, prêt à
  signer en PDF.
- **Screening DPIA Art. 35 automatique.** Détecte si une étude
  d'impact complète est requise, et pré-remplit les champs pour
  l'outil officiel CNIL PIA.
- **Vérification de vos citations juridiques.** Articles, lois,
  décrets, jurisprudences contrôlés contre les sources Legifrance
  officielles. Détection des références fausses ou abrogées.

## Garantie de confidentialité

- **Reste sur votre poste :** noms, IBAN, numéros de sécurité sociale,
  adresses, l'intégralité de vos documents. Tout est chiffré sur
  disque.
- **Sort vers Claude :** uniquement les questions anonymisées. Les
  noms deviennent `<<nom_personne:abc123>>`, les emails
  `<<email:def456>>`, etc.
- **Ne sort jamais :** les valeurs originales. Le journal d'audit
  par session enregistre chaque échange et vous permet de vérifier
  ce qui a été envoyé.

Pour la vérification de citations juridiques (optionnelle), seules les
références juridiques anonymisées sont envoyées à Legifrance — jamais
le contenu de vos dossiers.

## Prérequis

- macOS, Windows ou Linux récent
- [Claude Desktop](https://claude.ai/download) installé
- Un terminal ouvert (Terminal sur macOS / Linux, PowerShell sur Windows)

## Installation en 4 étapes

### Étape 1 — Installer `uv`

`uv` est le gestionnaire d'environnement Python qui orchestrera
l'installation. Une seule ligne par système d'exploitation.

**macOS / Linux :**
```
curl -LsSf https://astral.sh/uv/install.sh | sh
```

**Windows (PowerShell) :**
```
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

Vérifiez l'installation :
```
uv --version
```

Vous devez voir une ligne du type :
```
uv 0.10.2
```

Si la commande n'est pas reconnue, fermez et rouvrez votre terminal.

### Étape 2 — Installer le moteur Hacienda Ghost

Dans le terminal, copiez-collez :

```
uvx --from piighost piighost install --mode=mcp-only
```

Un assistant interactif vous pose **quatre questions** :

1. *Mode d'installation* — choisissez `2) MCP-only`.
2. *Clients à enregistrer* — sélectionnez Claude Desktop et/ou Claude
   Code (la coche `[✓]` indique ceux qui sont détectés sur votre
   poste).
3. *Emplacement du coffre-fort* — laissez la valeur par défaut
   (`~/.piighost/`).
4. *Moteur de recherche sémantique* — choisissez `local`.

L'assistant affiche ensuite une revue de l'installation et demande
confirmation. Validez par `y`. L'installation prend 3 à 5 minutes
(téléchargement des modèles inclus).

À la fin, vous voyez :

```
piighost install — terminé.
  ✓ Moteur installé
  ✓ Claude Desktop configuré
  ✓ Modèles téléchargés
```

### Étape 3 — Installer le plugin Cowork

Toujours dans le terminal :

```
claude plugins add jamon8888/hacienda
```

Cette commande fonctionne pour Claude Desktop **et** Claude Code (le
plugin est partagé via `~/.claude/plugins/`). Vous voyez :

```
Plugin 'hacienda' installed (v0.8.0)
```

### Étape 4 — Redémarrer Claude Desktop

Quittez complètement Claude Desktop (sur macOS : `⌘Q`, pas seulement
fermer la fenêtre), puis rouvrez l'application.

**Vérification :** dans la zone de saisie, tapez `/hacienda`. La
liste des commandes Hacienda Ghost doit apparaître :

```
/hacienda:setup
/hacienda:rgpd:registre
/hacienda:rgpd:dpia
/hacienda:rgpd:access
/hacienda:rgpd:forget
/hacienda:legal:setup
/hacienda:legal:verify
/hacienda:search
/hacienda:audit
/hacienda:status
/hacienda:index
```

Si aucune commande n'apparaît, voyez la section *Que faire si…* en
bas de ce document.

## Premier usage en 3 étapes

### Étape A — Configurer votre cabinet

Dans Claude Desktop, lancez :

```
/hacienda:setup
```

Le wizard vous pose 6 questions en 2 minutes :

1. Profession (avocat / notaire / médecin / EC / RH)
2. Identité du cabinet (nom, adresse, pays)
3. Numéro d'inscription ordinale (numéro de barreau, RPPS, etc.)
4. DPO (oui / non / inconnu)
5. Finalités habituelles (pré-remplies par profession, modifiables)
6. Durée de conservation par défaut

À la fin :

```
✅ Profil cabinet enregistré

Cabinet         : Cabinet Dupont & Associés
Profession      : avocat
N° Numéro de barreau (CNB) : Barreau de Paris #12345
DPO             : Marie Dupont
Finalités       : 3
Conservation    : 5 ans (Art. 2224 Code civil)
```

Le profil est stocké dans `~/.piighost/controller.toml` et vous pouvez
le modifier à tout moment en relançant la commande.

### Étape B — Ouvrir un dossier client dans Cowork

Dans Claude Desktop, ouvrez un dossier client via *File → Open Folder*
(ou glissez-déposez le dossier sur la fenêtre Cowork).

Hacienda Ghost démarre automatiquement l'indexation. Une étiquette
de statut apparaît dans la barre Cowork :

```
Hacienda Ghost · Indexation en cours… (3/14 documents)
```

Quand l'indexation est terminée :

```
Hacienda Ghost · 14 documents indexés · Prêt
```

L'indexation typique d'un dossier de 14 fichiers prend 1 à 2 minutes
(PDF, Word, Excel, CSV, e-mails sont tous supportés).

### Étape C — Générer votre Registre Art. 30

Toujours dans Claude Desktop, lancez :

```
/hacienda:rgpd:registre
```

Hacienda Ghost analyse le contenu indexé, détecte les catégories de
données personnelles, et génère le registre :

```
📋 Registre Art. 30 généré

Cabinet : Cabinet Dupont & Associés
Profession : avocat
Catégories de données : 16
Catégories sensibles (Art. 9) : 1 (condamnation_penale)
Documents inventoriés : 14

À compléter manuellement :
- Coordonnées du DPO : à vérifier
- Liste exhaustive des sous-traitants : à compléter
- Mesures de sécurité spécifiques : à valider

Fichier généré : ~/.piighost/exports/<projet>-registre-<date>.md
```

Le fichier Markdown est lisible directement, ou peut être converti en
PDF via votre éditeur Markdown préféré pour signature.

**Première victoire : votre cabinet a un registre conforme RGPD en
~10 minutes après l'installation.**

## Toutes les commandes

| Commande                  | Quand l'utiliser                              |
|---------------------------|-----------------------------------------------|
| `/hacienda:setup`         | Configurer ou modifier le profil cabinet     |
| `/hacienda:rgpd:registre` | Générer le registre Art. 30                  |
| `/hacienda:rgpd:dpia`     | Screening DPIA Art. 35                       |
| `/hacienda:rgpd:access`   | Réponse à une demande Art. 15                |
| `/hacienda:rgpd:forget`   | Droit à l'oubli Art. 17 (avec aperçu)        |
| `/hacienda:legal:setup`   | Activer la vérification Legifrance           |
| `/hacienda:legal:verify`  | Vérifier les citations juridiques d'un texte |
| `/hacienda:search`        | Recherche fédérée (vos docs + Legifrance)    |
| `/hacienda:audit`         | Journal d'audit de la session                |
| `/hacienda:status`        | État de l'index du dossier ouvert            |
| `/hacienda:index`         | Forcer la ré-indexation du dossier           |

## Que faire si…

**Aucune commande `/hacienda:*` n'apparaît après le redémarrage.**
Vérifiez que le plugin est bien installé : dans le terminal,
`claude plugins list` doit faire apparaître `hacienda` dans la liste.
Si oui, relancez Claude Desktop avec un quit complet (`⌘Q` sur
macOS).

**L'indexation est très lente sur un dossier réseau.**
Les lecteurs réseau (SMB, CIFS) sont scrutés toutes les 10 minutes.
Pour forcer une mise à jour immédiate, utilisez `/hacienda:index`.

**J'ai changé d'avis et je veux désinstaller.**
Dans le terminal :
```
claude plugins remove hacienda
uv tool uninstall piighost
rm -rf ~/.piighost
```

**J'ai un problème avec un dossier en particulier.**
La commande `/hacienda:status` affiche les erreurs d'indexation par
fichier. Si un fichier ne peut pas être indexé (PDF protégé, format
non supporté), il est listé avec la cause.

## Sécurité et confidentialité

- **Coffre-fort local chiffré.** Vos données vivent dans
  `~/.piighost/projects/<dossier>/vault.db`, chiffrées AES-256-GCM.
  La clé est dans `~/.piighost/vault.key`.
- **Profil cabinet en clair.** `~/.piighost/controller.toml` contient
  votre profil cabinet (nom, adresse, profession). Pas de donnée
  client. Lisible.
- **Journal d'audit par session.** Chaque échange avec Claude est
  enregistré dans `~/.piighost/sessions/<id>.audit.jsonl`. Tapez
  `/hacienda:audit` pour le consulter dans Claude Desktop.
- **Aucune donnée envoyée à Anthropic.** Les requêtes vers Claude
  contiennent uniquement les étiquettes anonymisées
  (`<<nom_personne:abc123>>`). Le journal d'audit liste tous les
  appels sortants.
- **Vérification optionnelle Legifrance.** Si activée via
  `/hacienda:legal:setup`, seules les références juridiques
  anonymisées sont envoyées — jamais le contenu de vos dossiers.

## Support

- **Issues GitHub :**
  [github.com/jamon8888/hacienda-ghost/issues](https://github.com/jamon8888/hacienda-ghost/issues)
- **Contrats de support payants :** formation cabinet (demi-journée
  à distance), profils profession spécialisés (notaire, médecin,
  RH), SLA prioritaire. Contact : `support@piighost.example`.
- **Documentation développeur :** voir `docs/` dans le dépôt pour
  les détails techniques (architecture, plans d'évolution, journaux
  de followup).

## Licence

MIT. Voir [LICENSE](LICENSE).
