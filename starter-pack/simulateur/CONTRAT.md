# Le contrat entre le simulateur et ton contrôleur

Ton contrôleur est **un programme à part**, dans le langage de ton choix. Le simulateur le lance, lui écrit **une ligne JSON** sur son entrée standard, et attend **une ligne JSON** en réponse sur sa sortie standard. Une ligne par minute simulée.

```
simulateur ──{"type":"init", ...}──►  contrôleur
simulateur ◄──{"pret": true}───────   contrôleur
simulateur ──{"type":"pas", ...}───►  contrôleur      × 1440 (une par minute)
simulateur ◄──{"marche": ...}──────   contrôleur
simulateur ──{"type":"fin"}────────►  contrôleur
```

Ce que signifient les mesures, les pannes et le bilan est expliqué dans `COMPORTEMENT.md`.

---

## 1. Démarrer en deux minutes

Depuis le dossier `starter-pack/` :

```bash
python3 simulateur/simulate.py                 # journée type, contrôleur exemple, bilan affiché
python3 simulateur/simulate.py --verifier      # vérifie que le simulateur tourne sur ta machine
python3 simulateur/simulate.py --liste         # les scénarios disponibles
```

Puis copie `controleur_exemple/` (le thermostat à 18 °C et son fichier `protocole.py`), modifie `decider()`, et lance :

```bash
python3 simulateur/simulate.py --scenario canicule --controleur "python3 mon_equipe/controleur.py"
```

En Python, `protocole.py` s'occupe des lignes JSON pour toi :

```python
from protocole import lancer

def initialiser(infos):        # facultatif : appelé une fois, avant la première minute
    ...

def decider(etat):             # appelé à chaque minute
    return {"marche": True, "consigne": 25}

lancer(decider, initialiser)
```

Dans un autre langage, il suffit de lire l'entrée standard ligne par ligne et de répondre par une ligne JSON.

---

## 2. Les trois règles à ne pas rater

1. **La sortie standard est réservée au protocole.** Un `print()` de debug casse l'échange. Écris tes logs sur la **sortie d'erreur** (elle s'affiche dans ton terminal). Avec `protocole.py`, tes `print()` y sont envoyés automatiquement.
2. **Une ligne reçue, une ligne renvoyée**, et il faut **vider le tampon** après chaque ligne (`flush`). Sinon le simulateur attend pour rien.
3. **Réponds vite.** Tu as 30 secondes par minute simulée (120 secondes pour `init`). Passé ce délai, le simulateur garde ta dernière commande, note l'erreur dans le CSV, et continue. Ta réponse en retard est ignorée.

---

## 3. Le message `init`

Reçu une seule fois, avant la minute 0. C'est le moment de charger ton modèle de langage. Réponds par n'importe quelle ligne JSON, par exemple `{"pret": true}`.

```json
{
  "type": "init",
  "version": "1.0.0",
  "scenario": "journee_type",
  "limites": {"consigne_min": 22, "consigne_max": 27},
  "plage_confort": [23.0, 26.0],
  "occupants": ["lea", "tom", "ines", "noah", "maya", "hugo"],
  "planning": [
    {"debut": "08:00", "fin": "12:00", "nb": 6},
    {"debut": "13:30", "fin": "17:30", "nb": 6}
  ],
  "prevision_meteo": [
    {"heure": "00:00", "t_ext": 24.6, "nebulosite": 0.1},
    {"heure": "01:00", "t_ext": 24.1, "nebulosite": 0.1}
  ]
}
```

| Champ | Ce que c'est |
|---|---|
| `limites` | Les **limites client** : la plage de consigne qu'Alvéoles accepte. Ton contrôleur doit refuser ce qui en sort. |
| `plage_confort` | La plage de température réelle sur laquelle l'inconfort est compté. |
| `occupants` | Les occupants habituels de la pièce. D'autres personnes peuvent parler (un visiteur, le client). |
| `planning` | Les réservations **prévues**. La réalité peut différer. |
| `prevision_meteo` | 24 entrées, une par heure. `nebulosite` va de 0 (ciel clair) à 1 (couvert). La prévision se trompe un peu, parfois beaucoup. |

---

## 4. Le message `pas`

Reçu à chaque minute, de la minute 0 (00:00) à la minute 1439 (23:59).

```json
{
  "type": "pas",
  "minute": 615,
  "heure": "10:15",
  "t_piece": 25.3,
  "t_reprise": 26.1,
  "t_ext": 28.3,
  "humidite": 52,
  "occupants_detectes": 6,
  "messages": [
    {"id": "m3", "occupant": "lea", "texte": "j'ai chaud", "source": "auto"}
  ],
  "split": {
    "marche": true,
    "consigne": 25.0,
    "ventilation": "auto",
    "puissance_w": 412,
    "compresseur": true,
    "compresseur_bloque": false
  }
}
```

| Champ | Ce que c'est | Attention |
|---|---|---|
| `minute`, `heure` | La minute depuis minuit, et la même chose en `"HH:MM"` | |
| `t_piece` | La **sonde de la pièce**, en °C. La clim régule dessus | Peut valoir `null`, ou mentir (voir `COMPORTEMENT.md`) |
| `t_reprise` | La **sonde de reprise** de la clim, en °C | Lit en général 0,5 à 1 °C de plus que la pièce. Peut valoir `null` |
| `t_ext` | La température extérieure mesurée, en °C | |
| `humidite` | L'humidité relative de la pièce, en % | |
| `occupants_detectes` | Le nombre d'occupants vus par le détecteur de présence | Il rate les gens immobiles |
| `messages` | Les phrases dites pendant cette minute | **Toujours une liste**, vide si personne ne parle |
| `messages[].id` | L'identifiant du message, à reprendre dans ta réponse | |
| `messages[].occupant` | Qui parle | Peut être un nom inconnu |
| `messages[].source` | `script` (écrit dans le scénario), `auto` (plainte automatique) ou `direct` (ajouté pendant la démo) | |
| `split` | L'état de la clim **à la fin de la minute précédente** | |
| `split.consigne` | La consigne **appliquée**, après bornage par la clim (16 à 30 °C, par pas de 0,5) | |
| `split.puissance_w` | La puissance **électrique** consommée, en watts | Ce n'est pas la puissance de froid |
| `split.compresseur` | `true` si le compresseur tourne | Une clim en marche peut avoir son compresseur à l'arrêt : la consigne est atteinte |
| `split.compresseur_bloque` | `true` si la clim voulait redémarrer mais attend la fin de ses 3 minutes de protection | |

---

## 5. Ta réponse

```json
{
  "marche": true,
  "consigne": 24.5,
  "ventilation": "auto",
  "reponses": [{"message": "m3", "texte": "Je baisse d'un demi-degré, la pièce est à 25,3 °C."}],
  "journal": "lea a chaud à 25,3 °C : consigne 25 -> 24,5"
}
```

| Champ | Type | Ce que c'est |
|---|---|---|
| `marche` | `true` / `false` | Allume ou éteint la clim |
| `consigne` | nombre | La température visée, en °C |
| `ventilation` | `"auto"`, `"faible"` ou `"fort"` | `faible` plafonne la puissance de froid à 60 %. `fort` l'augmente de 10 % mais le ventilateur consomme plus |
| `reponses` | liste de `{message, texte}` | Ce que l'assistant répond à un message, désigné par son `id` |
| `journal` | texte ou objet JSON | L'explication de ta décision. Elle est enregistrée telle quelle dans le CSV : pratique pour ton tableau de bord |

**Tous les champs sont facultatifs. Un champ absent garde sa valeur précédente.** Répondre `{}` veut dire « je ne change rien ». Au départ, la clim est à l'arrêt, consigne 25 °C, ventilation `auto`.

Si ta réponse n'est pas du JSON valide, ou si un champ a une valeur impossible, le simulateur ignore ce qui est faux, garde le reste, et note l'erreur dans la colonne `erreur` du CSV.

---

## 6. Les fichiers de résultats

Le simulateur écrit dans `resultats/<scenario>/` (change le dossier avec `--sortie`) :

| Fichier | Quand | Contenu |
|---|---|---|
| `direct.csv` | **Pendant** la simulation, une ligne par minute | Seulement ce que voit ton contrôleur, ses commandes et l'état de la clim. Ton tableau de bord peut le lire en direct |
| `journee.csv` | **À la fin** | Les mêmes colonnes, plus la vérité : température réelle, présence réelle, puissance de froid, événements |
| `bilan.json` | **À la fin** | Les chiffres de la journée et ceux de la référence à 18 °C |

Colonnes de `direct.csv` :

| Colonne | Contenu |
|---|---|
| `minute`, `heure` | Le moment |
| `t_piece`, `t_reprise`, `t_ext`, `humidite`, `occupants_detectes` | Ce que ton contrôleur a reçu (vide si `null`) |
| `marche_demandee`, `consigne_demandee`, `ventilation` | Ta commande |
| `marche`, `consigne`, `puissance_w`, `compresseur`, `compresseur_bloque` | Ce que la clim a fait pendant cette minute (`1` ou `0` pour oui ou non) |
| `kwh_cumules` | L'énergie consommée depuis minuit |
| `messages`, `reponses` | Les messages reçus et tes réponses, en JSON |
| `journal` | Ton explication |
| `erreur` | Vide si tout va bien |
| `temps_reponse_ms` | Le temps que ton contrôleur a mis à répondre |

Colonnes ajoutées dans `journee.csv` : `t_reelle`, `t_masse` (température des murs), `presence_reelle`, `puissance_froid_w`, `eer` (rendement de la clim), `inconfort` (`chaud`, `froid` ou vide), `evenements` (les événements du scénario actifs à cette minute).

Le contenu de `bilan.json` est détaillé dans `COMPORTEMENT.md`, section « Lire le bilan ».

---

## 7. Les options utiles

| Option | Effet |
|---|---|
| `--scenario NOM` | Un scénario du dossier `scenarios/`, ou le chemin d'un fichier JSON |
| `--controleur "COMMANDE"` | La commande qui lance ton contrôleur, entre guillemets |
| `--jusqu 10:00` | Arrête la journée à 10h, pour itérer vite |
| `--debug` | Affiche chaque message échangé |
| `--sans-plaintes-auto` | Désactive les plaintes automatiques, pour comparer sur une journée figée |
| `--delai 5` | Change le délai de réponse par minute (30 secondes par défaut) |
| `--valider fichier.json` | Vérifie un scénario que tu as écrit |
| `--live` | Mode démo : la journée défile à l'écran (voir ci-dessous) |
| `--aide` | Toutes les options |

### Mode démo

```bash
# terminal 1 : la journée défile, 0,2 seconde par minute à partir de 7h
python3 simulateur/simulate.py --live --controleur "python3 mon_equipe/controleur.py"

# terminal 2 : quelqu'un parle à l'assistant pendant la démo
python3 simulateur/simulate.py --dire "lea: on part en réunion jusqu'à 15h"
python3 simulateur/simulate.py --dire "mets 10 degrés"          # sans nom : c'est « client » qui parle
```

La phrase arrive à ton contrôleur à la minute en cours, avec `"source": "direct"`. `--vitesse` règle la cadence, `--depuis` l'heure à partir de laquelle la journée ralentit. Les deux terminaux doivent utiliser le même dossier `--sortie`.

---

## 8. Écrire ton propre scénario

Un scénario est un fichier JSON. Avec `"base"`, il part d'un autre scénario et ne décrit que ses différences :

```json
{
  "base": "journee_type",
  "description": "Une réunion imprévue pendant une panne de sonde.",
  "phrases": [
    {"heure": "14:55", "occupant": "lea", "texte": "on sera dix pendant une heure"}
  ],
  "evenements": [
    {"type": "visiteurs", "heure": "15:00", "duree": 60, "nb": 4},
    {"type": "panne_sonde", "heure": "15:10", "duree": 45, "mode": "figee"}
  ]
}
```

| Événement | Champs en plus | Effet |
|---|---|---|
| `panne_sonde` | `mode` : `derive`, `figee`, `absente`, `pic`, `soleil`. En option `sonde` (`piece` ou `reprise`), `amplitude`, `valeur` | La sonde ment pendant `duree` minutes |
| `fenetre_ouverte` | | La chaleur extérieure entre beaucoup plus vite |
| `pir_aveugle` | | Le détecteur annonce 0 occupant |
| `absence` | `occupants` : `"tous"` ou une liste d'id | Ces occupants ne sont pas là, quel que soit leur horaire |
| `presence` | `occupants` : `"tous"` ou une liste d'id | Ces occupants sont là, même hors de leur horaire |
| `visiteurs` | `nb` | Des personnes en plus dans la pièce |

Les heures s'écrivent `"HH:MM"`, les durées en minutes. `journee_type.json` montre tous les autres champs (météo heure par heure, occupants, planning, limites). Vérifie ton fichier avec `--valider`.

---

## 9. Quand ça ne marche pas

| Tu vois | Cause probable |
|---|---|
| `le contrôleur s'est arrêté` | Ton programme a planté. Son message d'erreur est affiché juste au-dessus |
| `n'a pas répondu au message "init"` | Tu ne réponds pas à `init`, ou tu ne vides pas le tampon de sortie |
| La colonne `erreur` contient `réponse invalide` | Un `print()` de debug est parti sur la sortie standard |
| La colonne `erreur` contient `délai dépassé` | Ton contrôleur est trop lent, souvent un appel au modèle de langage à chaque minute |
| Deux lancements ne donnent pas le même bilan | Ton contrôleur n'est pas déterministe (modèle de langage, hasard, heure réelle) |

`--debug` affiche chaque ligne échangée, et `--jusqu 08:30` limite la journée à quelques minutes utiles.
