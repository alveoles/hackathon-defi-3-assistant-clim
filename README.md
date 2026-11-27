# Défi 3 — Assistant domotique pour la climatisation

> Hackathon Alvéoles × Epitech — mercredi 2 décembre, TechSud (Saint-Pierre)

## Le défi

Développer un **assistant domotique** capable de **piloter une climatisation** à partir de **capteurs de température**.

## Objectif

Garder une pièce confortable en consommant le moins d'énergie possible, et permettre de piloter la clim simplement (ex. « j'ai chaud »).

## Livrable attendu

- Un assistant qui lit les capteurs et pilote la clim
- Une démo live
- Un README qui explique comment lancer le projet

## Ressources

| Où | Quoi |
|---|---|
| [`sujet/SUJET.md`](sujet/SUJET.md) | Le sujet complet (aussi en [PDF](sujet/SUJET.pdf)) |
| [`starter-pack/simulateur/`](starter-pack/simulateur/) | Le simulateur de la pièce : `simulate.py` |
| [`starter-pack/simulateur/CONTRAT.md`](starter-pack/simulateur/CONTRAT.md) | Ce que ton contrôleur reçoit et renvoie |
| [`starter-pack/simulateur/COMPORTEMENT.md`](starter-pack/simulateur/COMPORTEMENT.md) | Comment se comporte la pièce, et comment lire le bilan |
| [`starter-pack/scenarios/`](starter-pack/scenarios/) | Les journées à affronter |
| [`starter-pack/controleur_exemple/`](starter-pack/controleur_exemple/) | Le thermostat à 18 °C : la référence à battre |
| [`GLOSSARY.md`](GLOSSARY.md) | Le vocabulaire du défi |
| [`IA_LOCALE.md`](IA_LOCALE.md) | Quelle taille de modèle de langage tourne sur ta machine |

## Démarrer

1. Cliquer sur **Use this template** pour créer le repo de votre équipe
2. Travailler en branches + Pull Requests, rien en direct sur `main`
3. Lancer le simulateur (Python 3.9 ou plus, rien à installer) :

```bash
cd starter-pack
python3 simulateur/simulate.py --verifier    # le simulateur tourne-t-il sur ta machine ?
python3 simulateur/simulate.py               # une journée type avec le thermostat à 18 °C
python3 simulateur/simulate.py --scenario canicule --controleur "python3 ton_dossier/controleur.py"
```
