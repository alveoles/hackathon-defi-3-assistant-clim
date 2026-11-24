---
defi: 03
titre: COOL RUNNER
accroche: while (piece.occupee) { confort.garder(); kwh.reduire(); }
sous_titre: Un thermostat obéit. Un assistant comprend.
version: v1
---

## Introduction

Dans un bureau climatisé, la clim tourne souvent trop fort, trop tôt, ou dans une pièce vide. Elle ne sait faire qu'une chose : viser une consigne. Les occupants, eux, ne parlent pas en degrés. Ils disent « j'ai chaud », « on part en réunion », « il gèle ici ».

Ta mission, avec ton équipe : construire un **assistant domotique** (Proof of Concept). Il lit les capteurs de température, pilote la climatisation, et garde la pièce **confortable en consommant le moins possible**. Il comprend aussi des demandes simples, formulées en langage naturel.

L'assistant ne remplace pas l'occupant. Il **l'écoute, décide dans des limites sûres, et explique ce qu'il a fait.**

> ℹ️ **Périmètre de la journée :** **une pièce** (un bureau partagé), **une climatisation**, une journée de travail simulée. Toutes les équipes partent du même simulateur.

Le projet repose sur trois piliers :

- **Mesurer** : lire les capteurs et savoir ce qui se passe dans la pièce
- **Décider** : réguler la clim entre confort et consommation
- **Dialoguer** : comprendre une demande en langage naturel et y répondre

> ℹ️ Aujourd'hui, une clim de bureau vise 18 °C du matin au soir, que la pièce soit pleine ou vide. Ce soir, ton assistant aura prouvé qu'on peut faire aussi confortable, en consommant nettement moins.

## Considérations techniques

Tu es libre sur les technologies, avec une contrainte : **tout tourne en local, sur ton ordinateur, avec des outils gratuits et open source.** Aucune API payante, aucun service en ligne obligatoire. Il te faudra au minimum :

- un **contrôleur** qui reçoit les mesures et renvoie une commande pour la clim, branché sur le simulateur
- un **LLM local** (via Ollama, le modèle de ton choix) qui transforme une phrase en intention structurée
- une **interface** qui produit le **Tableau de bord de la pièce**

> ℹ️ L'open source est ton meilleur allié : régulateurs, outils domotiques et modèles de langage existent déjà. Mais chaque heure passée à installer est une heure en moins pour construire. Choisis vite, et tiens-toi à ton choix.

> ℹ️ Le LLM ne pilote jamais la clim directement. Il traduit une phrase en intention (« plus frais », « pièce vide jusqu'à 14h »). Ton contrôleur décide, et refuse ce qui sort des limites sûres.

> ℹ️ Branches, pull requests, commits lisibles. Ton historique git fait partie du rendu.

### Pistes locales

Ces pistes sont des points de départ, pas des obligations. La machine de référence est un MacBook M1 Pro 16 Go. Pour savoir quelle taille de modèle ta machine fait tourner, lis `IA_LOCALE.md` à la racine du repo.

| Brique | Piste | Autres pistes |
|---|---|---|
| Régulation | Seuil avec hystérésis | PID (`simple-pid`), commande prédictive |
| Langage naturel | LLM de 3 à 8 milliards de paramètres via Ollama, avec tool calling | Sortie JSON imposée par un schéma |
| Prévision | Moyenne glissante sur l'historique | Régression linéaire (`scikit-learn`) |
| Interface | Page web qui lit le fichier de résultats | Streamlit, Gradio, Grafana |
| Matériel *(bonus)* | Arduino + BME280, lu en USB série (`pyserial`) | DHT11, VMA320, Raspberry Pi |
| Programmation Arduino *(bonus)* | Arduino IDE | `arduino-cli`, PlatformIO |
| Voix *(bonus)* | `whisper.cpp` | Vosk |

> ℹ️ Le simulateur avance minute par minute. Un LLM appelé à chaque minute transforme une journée de quelques secondes en une heure d'attente. Appelle-le quand un occupant parle, pas à chaque pas.

## Starter Pack

Dans `starter-pack/` :

- `simulateur/simulate.py` : simule une journée de la pièce, minute par minute, en quelques secondes. À chaque pas, il appelle ton contrôleur, puis écrit le résultat dans `resultats/` (un CSV et un bilan).
- `simulateur/CONTRAT.md` : ce que ton contrôleur reçoit (heure, température intérieure et extérieure, occupants, phrases des occupants) et ce qu'il renvoie (marche ou arrêt, consigne, ventilation).
- `scenarios/` : des journées types en JSON (journée chaude, réunion de dernière minute, pièce vide l'après-midi). Chacune décrit la météo, les arrivées et départs, et ce que disent les occupants.
- `controleur_exemple/` : un thermostat naïf, réglé à 18 °C toute la journée. C'est la référence à battre.

Le bilan donne deux chiffres : les **kWh consommés** et les **minutes d'inconfort**. Une même journée donne toujours le même résultat : tu peux comparer deux versions de ton contrôleur.

À la racine : `INSTALL.md` (installation pas à pas) et `check_setup.py` (vérifie que le simulateur et Ollama tournent sur ta machine).

> ℹ️ Ton contrôleur reçoit des mesures sans savoir d'où elles viennent. Le jour où tu branches un vrai capteur, seule la couche qui lit les mesures change. Garde cette frontière propre.

> ℹ️ Un capteur réel ment parfois : il dérive, il décroche, il est posé en plein soleil. Le simulateur aussi, de temps en temps.

## Fonctionnalités

Les fonctionnalités sont formulées en **user stories** et regroupées par **palier**. À l'intérieur d'un palier, **elles ne sont pas triées** : à ton équipe de les prioriser. Elles sont validées par ton Product Owner pour le seul sprint de la journée.

> ℹ️ Un palier stable et démontrable vaut plus que trois paliers commencés. Ne passe au suivant qu'une fois le précédent solide.

> ℹ️ Toutes les user stories sont-elles claires ? Les comprenez-vous tous de la même façon ?

### Palier 1 : la boucle de régulation

- En tant qu'occupant, je veux que la température reste dans une plage de confort sans que j'aie à toucher la clim, afin de travailler sans y penser
- En tant que gestionnaire, je veux visualiser la journée : température, consigne, état de la clim et consommation, afin de comprendre ce que fait l'assistant
- En tant que gestionnaire, je veux que la clim ne refroidisse pas une pièce vide, afin de ne pas payer pour personne
- En tant que gestionnaire, je veux comparer, sur la même journée, mon assistant au thermostat réglé à 18 °C, afin de prouver le gain en kWh

### Palier 2 : l'assistant comprend

- En tant qu'occupant, je veux dire « j'ai chaud » ou « il fait trop froid », afin d'ajuster la pièce sans chercher la télécommande
- En tant qu'occupant, je veux annoncer « on part en réunion jusqu'à 15h », afin que l'assistant adapte la clim à mon absence
- En tant qu'occupant, je veux que l'assistant me réponde ce qu'il a fait et pourquoi, afin de lui faire confiance
- En tant que gestionnaire, je veux que l'assistant refuse ou ramène dans les limites une demande absurde (« mets 10 °C »), afin de protéger le matériel et la facture

> ℹ️ « J'ai chaud » à 9h dans une pièce à 24 °C et « j'ai chaud » à 15h dans une pièce à 29 °C ne demandent pas la même réponse. Le contexte fait partie de l'intention.

### Palier 3 : économiser en anticipant

- En tant qu'occupant, je veux que la pièce soit déjà fraîche à mon arrivée, afin de ne pas subir les premières minutes
- En tant que gestionnaire, je veux que l'assistant tienne compte de la météo et du planning de la pièce, afin de refroidir au bon moment plutôt qu'en continu
- En tant qu'occupant, je veux que l'assistant arbitre entre deux collègues qui n'ont pas la même sensation, afin que personne ne monopolise la clim
- En tant que gestionnaire, je veux que l'assistant repère un capteur incohérent et continue de fonctionner, afin de ne pas refroidir sur une fausse mesure

### Bonus : aller plus loin

- En tant qu'occupant, je veux que l'assistant lise un vrai capteur de température posé sur la table, afin de sortir du simulateur
- En tant qu'occupant, je veux qu'un témoin physique (une LED sur l'Arduino) montre quand la clim tourne, afin de voir la décision sortir de l'écran
- En tant qu'occupant, je veux que l'assistant tienne compte de l'humidité, afin de régler sur la sensation réelle et pas seulement sur le thermomètre
- En tant qu'occupant, je veux parler à l'assistant à voix haute, afin de ne pas taper au clavier

> ℹ️ Matériel prêté pour la journée : des Arduino, des capteurs BME280 (température, humidité, pression), DHT11 (température, humidité) et VMA320 (température), des breadboards et des câbles. L'Arduino se branche en USB sur ton ordinateur. Il n'y a pas d'émetteur infrarouge : la clim reste simulée. Et trois capteurs posés côte à côte ne donnent pas la même température : compare-les avant de leur faire confiance.

### …

Ton client, c'est Alvéoles. Il connaît ses occupants, ses horaires et sa facture d'électricité. Il a ses propres contraintes, et tout n'est pas écrit dans ce sujet.

> ℹ️ À 17h00, ton assistant affrontera une journée qu'il n'a jamais vue. Les scénarios du starter pack ne sont pas les seuls possibles.

> ℹ️ Ton client est dans la salle. Va lui poser tes questions, et sois prêt à formuler de nouvelles user stories.

## Livrable : le Tableau de bord

À **17h00**, démonstration live sur un **scénario imposé**, que tu lances avec le simulateur. Ton **tableau de bord** affiche :

- la **courbe de la journée** : température mesurée, consigne, occupants, état de la clim
- le **bilan** face au thermostat de référence : **kWh consommés** et **minutes d'inconfort**
- le **fil de conversation** avec l'assistant, et chaque décision qu'il a prise (à partir du palier 2)
- *(bonus)* la **mesure d'un vrai capteur** à côté de la mesure simulée

Pendant la démo, ton client ajoutera ses propres phrases à la journée.

Côté repo : un `README` avec les instructions de lancement, des PR fusionnées et un tag **`v1.0-rendu`** avant la démo.
