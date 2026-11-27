"""Le thermostat naïf : 18 °C de 7h à 19h, que la pièce soit pleine ou vide.

C'est la référence à battre. Lance-le avec :

    python3 simulateur/simulate.py --controleur "python3 controleur_exemple/controleur.py"
"""
from protocole import lancer


def decider(etat):
    en_marche = 7 * 60 <= etat["minute"] < 19 * 60
    return {"marche": en_marche, "consigne": 18, "ventilation": "auto"}


if __name__ == "__main__":
    lancer(decider)
