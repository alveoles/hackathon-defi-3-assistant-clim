"""Parle au simulateur à ta place : une ligne JSON reçue, une ligne JSON renvoyée.

Copie ce fichier à côté de ton contrôleur, puis :

    from protocole import lancer

    def decider(etat):
        return {"marche": True, "consigne": 25}

    lancer(decider)

Le format des messages est décrit dans simulateur/CONTRAT.md.
"""
import json
import sys


def lancer(decider, initialiser=None):
    """Boucle d'échange avec le simulateur.

    decider(etat) est appelée à chaque minute et renvoie la commande (un dictionnaire).
    initialiser(infos) est appelée une fois au début, avec le planning et la prévision météo.
    """
    for flux in (sys.stdin, sys.stdout, sys.stderr):
        if hasattr(flux, "reconfigure"):
            flux.reconfigure(encoding="utf-8")
    # La sortie standard est réservée au simulateur : tes print() partent sur la sortie d'erreur.
    vers_simulateur = sys.stdout
    sys.stdout = sys.stderr

    for ligne in sys.stdin:
        if not ligne.strip():
            continue
        message = json.loads(ligne)
        if message["type"] == "init":
            if initialiser:
                initialiser(message)
            reponse = {"pret": True}
        elif message["type"] == "pas":
            reponse = decider(message) or {}
        else:  # "fin"
            break
        vers_simulateur.write(json.dumps(reponse, ensure_ascii=False) + "\n")
        vers_simulateur.flush()
