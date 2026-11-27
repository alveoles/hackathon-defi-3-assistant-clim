#!/usr/bin/env python3
"""Simulateur COOL RUNNER : une journée d'un bureau climatisé, minute par minute.

    python3 simulate.py                         journée type, contrôleur exemple
    python3 simulate.py --scenario canicule --controleur "python3 mon_controleur.py"
    python3 simulate.py --aide                  toutes les options

Le protocole d'échange avec le contrôleur est décrit dans CONTRAT.md,
le comportement de la pièce dans COMPORTEMENT.md.
Python 3.9 ou plus, bibliothèque standard uniquement.
"""
import argparse
import copy
import csv
import hashlib
import json
import math
import os
import queue
import random
import shlex
import statistics
import subprocess
import sys
import threading
import time
from pathlib import Path

VERSION = "1.1.0"

DOSSIER_STARTER = Path(__file__).resolve().parent.parent
DOSSIER_SCENARIOS = DOSSIER_STARTER / "scenarios"
CONTROLEUR_EXEMPLE = DOSSIER_STARTER / "controleur_exemple" / "controleur.py"

MINUTES_PAR_JOUR = 1440
PLAGE_CONFORT = (23.0, 26.0)
BUDGET_MINUTES_PAR_OCCUPANT = 7.5  # budget de confort : 45 minutes-personne pour 6 occupants prévus
BUDGET_SANS_PLANNING = 30

# Pièce : deux réservoirs de chaleur (air, masse). Valeurs calées pour un bureau
# de 30 m² en béton : voir COMPORTEMENT.md. Un scénario peut les surcharger dans "piece".
PHYSIQUE = {
    "c_air": 0.8e6,  # J/K, air + mobilier léger
    "c_masse": 12e6,  # J/K, dalle + murs
    "ua_air_masse": 500.0,  # W/K
    "ua_air_ext": 100.0,  # W/K, vitrage + fuites
    "ua_masse_ext": 150.0,  # W/K
    "ua_air_neuf_par_occupant": 8.0,  # W/K
    "ua_fenetre_ouverte": 250.0,  # W/K ajoutés quand une fenêtre est ouverte
    "w_par_occupant": 180.0,  # 100 W la personne + 80 W son poste
    "w_eclairage": 240.0,
    "w_solaire_max": 800.0,
    "part_solaire_masse": 0.3,
}

# Clim : split inverter qui régule seul vers sa consigne, sur la sonde de la pièce.
CLIM_PUISSANCE_FROID_W = 3500.0
CLIM_MODULATION_MIN = 0.30
CLIM_GAIN_W_PAR_K = 7000.0
CLIM_HYSTERESIS = 0.3
CLIM_ANTI_COURT_CYCLE_MIN = 3
CLIM_CONSIGNE_MIN, CLIM_CONSIGNE_MAX = 16.0, 30.0
CLIM_VEILLE_W = 5.0
VENTILATIONS = {  # (plafond de puissance froid, watts du ventilateur)
    "faible": (0.6, 15.0),
    "auto": (1.0, 30.0),
    "fort": (1.1, 50.0),
}

BRUIT_SONDE = 0.2
ECART_REPRISE = 0.7  # la sonde de reprise lit plus chaud : elle est au plafond
PLAINTE_APRES_MIN = 15
PLAINTE_PAUSE_MIN = 30
PLAINTE_EFFET_MIN = 15
TOLERANCE_PAR_DEFAUT = 1.5
PREFERENCE_PAR_DEFAUT = 24.5

PHRASES_CHAUD = [
    "j'ai chaud",
    "il fait trop chaud ici",
    "c'est étouffant",
    "on crève de chaud",
    "on peut rafraîchir un peu ?",
    "je transpire sur mon clavier",
]
PHRASES_FROID = [
    "j'ai froid",
    "il gèle ici",
    "on se croirait dans un frigo",
    "il fait trop froid",
    "on peut monter un peu la température ?",
    "j'ai les doigts gelés",
]

CHAMPS_REPONSE = {"marche", "consigne", "ventilation", "reponses", "journal"}
TYPES_EVENEMENTS = ("panne_sonde", "fenetre_ouverte", "pir_aveugle", "absence", "presence", "visiteurs")
MODES_PANNE = ("derive", "figee", "absente", "pic", "soleil")

COLONNES_DIRECT = [
    "minute", "heure", "t_piece", "t_reprise", "t_ext", "humidite", "occupants_detectes",
    "marche_demandee", "consigne_demandee", "ventilation",
    "marche", "consigne", "puissance_w", "compresseur", "compresseur_bloque", "kwh_cumules",
    "messages", "reponses", "journal", "erreur", "temps_reponse_ms",
]
COLONNES_VERITE = ["t_reelle", "t_masse", "presence_reelle", "puissance_froid_w", "eer", "inconfort", "evenements"]


# Deux bilans ne se comparent que s'ils viennent du même simulateur, à la ligne près.
EMPREINTE_SIMULATEUR = hashlib.sha256(Path(__file__).read_bytes().replace(b"\r\n", b"\n")).hexdigest()[:12]


class ErreurScenario(Exception):
    """Le fichier de scénario est introuvable ou mal écrit."""


class DelaiDepasse(Exception):
    """Le contrôleur n'a pas répondu à temps."""


class ControleurArrete(Exception):
    """Le contrôleur s'est arrêté ou n'a pas pu être lancé."""


# ---------------------------------------------------------------- temps

def minute_de(texte):
    """'08:30' -> 510."""
    heures, minutes = str(texte).split(":")
    valeur = int(heures) * 60 + int(minutes)
    if not 0 <= valeur <= MINUTES_PAR_JOUR or not 0 <= int(minutes) < 60:
        raise ValueError(texte)
    return valeur


def heure_de(minute):
    """510 -> '08:30'."""
    return "%02d:%02d" % (minute // 60, minute % 60)


def plages_de(horaires):
    """'08:00-12:00,13:30-17:30' -> [(480, 720), (810, 1050)]."""
    plages = []
    for morceau in str(horaires).split(","):
        if not morceau.strip():
            continue
        debut, fin = morceau.strip().split("-")
        plages.append((minute_de(debut), minute_de(fin)))
    return plages


def interpoler(valeurs_horaires, minute):
    """Valeur à une minute donnée, entre deux valeurs horaires (24 valeurs, une par heure)."""
    heure = minute / 60.0
    i = int(heure) % 24
    j = (i + 1) % 24
    part = heure - int(heure)
    return valeurs_horaires[i] * (1 - part) + valeurs_horaires[j] * part


# ---------------------------------------------------------------- scénarios

DEFAUTS_SCENARIO = {
    "description": "",
    "graine": 1,
    "piece": {"orientation": "ouest"},
    "meteo": {"nebulosite": [0.1] * 24, "erreur_prevision": 1.5},
    "limites": {"consigne_min": 22, "consigne_max": 27},
    "occupants": [],
    "planning": [],
    "phrases": [],
    "evenements": [],
}


def _fusionner(base, surcharge):
    """Fusion en profondeur : les dictionnaires se complètent, le reste est remplacé."""
    resultat = copy.deepcopy(base)
    for cle, valeur in surcharge.items():
        if isinstance(valeur, dict) and isinstance(resultat.get(cle), dict):
            resultat[cle] = _fusionner(resultat[cle], valeur)
        else:
            resultat[cle] = copy.deepcopy(valeur)
    return resultat


def scenarios_disponibles():
    return sorted(p.stem for p in DOSSIER_SCENARIOS.glob("*.json"))


def _trouver_scenario(reference, dossier=None):
    candidats = [Path(reference)]
    if dossier is not None:
        candidats += [dossier / reference, dossier / (str(reference) + ".json")]
    candidats += [DOSSIER_SCENARIOS / (str(reference) + ".json")]
    for candidat in candidats:
        if candidat.is_file():
            return candidat
    raise ErreurScenario(
        "scénario introuvable : %s (disponibles : %s)" % (reference, ", ".join(scenarios_disponibles()) or "aucun")
    )


def _lire_scenario(reference, dossier=None, deja_vus=()):
    chemin = _trouver_scenario(reference, dossier)
    if chemin in deja_vus:
        raise ErreurScenario("%s : héritage en boucle via \"base\"" % chemin.name)
    try:
        brut = json.loads(chemin.read_text(encoding="utf-8"))
    except json.JSONDecodeError as erreur:
        raise ErreurScenario("%s : JSON invalide (%s)" % (chemin.name, erreur))
    if not isinstance(brut, dict):
        raise ErreurScenario("%s : le scénario doit être un objet JSON" % chemin.name)
    brut.setdefault("nom", chemin.stem)
    if "base" in brut:
        base = _lire_scenario(brut.pop("base"), chemin.parent, deja_vus + (chemin,))
        base.pop("nom", None)
        base.pop("description", None)
        brut = _fusionner(base, brut)
    return brut


def charger_scenario(reference):
    """Charge un scénario par nom (dossier scenarios/) ou par chemin, héritage "base" compris."""
    return preparer_scenario(_lire_scenario(reference))


def preparer_scenario(brut):
    """Complète un scénario avec les valeurs par défaut et le valide."""
    scenario = _fusionner(DEFAUTS_SCENARIO, brut)
    scenario.setdefault("nom", "sans_nom")
    erreurs = _erreurs_scenario(scenario)
    if erreurs:
        raise ErreurScenario("scénario « %s » invalide :\n  - %s" % (scenario["nom"], "\n  - ".join(erreurs)))
    return scenario


def _est_nombre(valeur):
    return isinstance(valeur, (int, float)) and not isinstance(valeur, bool)


def _erreurs_scenario(scenario):
    erreurs = []

    def heure_valide(valeur, ou):
        try:
            minute_de(valeur)
            return True
        except (ValueError, AttributeError):
            erreurs.append("%s : heure invalide %r (attendu \"HH:MM\")" % (ou, valeur))
            return False

    meteo = scenario["meteo"]
    for cle in ("t_ext", "nebulosite", "prevision_t_ext", "prevision_nebulosite"):
        if cle not in meteo:
            if cle == "t_ext":
                erreurs.append("meteo.t_ext : manquant (24 températures, une par heure)")
            continue
        valeurs = meteo[cle]
        if not (isinstance(valeurs, list) and len(valeurs) == 24 and all(_est_nombre(v) for v in valeurs)):
            erreurs.append("meteo.%s : il faut une liste de 24 nombres, une valeur par heure" % cle)
        elif "nebulosite" in cle and not all(0 <= v <= 1 for v in valeurs):
            erreurs.append("meteo.%s : chaque valeur doit être entre 0 (ciel clair) et 1 (couvert)" % cle)

    piece = scenario["piece"]
    if piece.get("orientation") not in ("est", "ouest"):
        erreurs.append("piece.orientation : %r inconnu (attendu \"est\" ou \"ouest\")" % piece.get("orientation"))
    for cle, valeur in piece.items():
        if cle == "orientation":
            continue
        if cle not in PHYSIQUE:
            erreurs.append("piece.%s : paramètre inconnu (connus : %s)" % (cle, ", ".join(sorted(PHYSIQUE))))
        elif not _est_nombre(valeur):
            erreurs.append("piece.%s : il faut un nombre" % cle)

    limites = scenario["limites"]
    if not (_est_nombre(limites.get("consigne_min")) and _est_nombre(limites.get("consigne_max"))
            and limites["consigne_min"] <= limites["consigne_max"]):
        erreurs.append("limites : consigne_min et consigne_max doivent être deux nombres ordonnés")

    identifiants = set()
    for i, occupant in enumerate(scenario["occupants"]):
        ou = "occupants[%d]" % i
        if not isinstance(occupant, dict) or not isinstance(occupant.get("id"), str):
            erreurs.append("%s : il faut un objet avec un \"id\"" % ou)
            continue
        if occupant["id"] in identifiants:
            erreurs.append("%s : id %r en double" % (ou, occupant["id"]))
        identifiants.add(occupant["id"])
        try:
            plages_de(occupant.get("horaires", ""))
        except ValueError:
            erreurs.append("%s.horaires : %r invalide (attendu \"08:00-12:00,13:30-17:30\")" % (ou, occupant.get("horaires")))
        for cle in ("preference", "tolerance"):
            if cle in occupant and not _est_nombre(occupant[cle]):
                erreurs.append("%s.%s : il faut un nombre" % (ou, cle))

    for i, creneau in enumerate(scenario["planning"]):
        ou = "planning[%d]" % i
        if not isinstance(creneau, dict):
            erreurs.append("%s : il faut un objet {debut, fin, nb}" % ou)
            continue
        heure_valide(creneau.get("debut"), ou + ".debut")
        heure_valide(creneau.get("fin"), ou + ".fin")
        if not isinstance(creneau.get("nb"), int):
            erreurs.append("%s.nb : il faut un nombre entier d'occupants" % ou)

    for i, phrase in enumerate(scenario["phrases"]):
        ou = "phrases[%d]" % i
        if not isinstance(phrase, dict):
            erreurs.append("%s : il faut un objet {heure, occupant, texte}" % ou)
            continue
        heure_valide(phrase.get("heure"), ou + ".heure")
        if not isinstance(phrase.get("occupant"), str) or not isinstance(phrase.get("texte"), str):
            erreurs.append("%s : \"occupant\" et \"texte\" sont obligatoires" % ou)

    for i, evenement in enumerate(scenario["evenements"]):
        ou = "evenements[%d]" % i
        if not isinstance(evenement, dict):
            erreurs.append("%s : il faut un objet {heure, duree, type}" % ou)
            continue
        if evenement.get("type") not in TYPES_EVENEMENTS:
            erreurs.append("%s : type inconnu %r (connus : %s)" % (ou, evenement.get("type"), ", ".join(TYPES_EVENEMENTS)))
            continue
        heure_valide(evenement.get("heure"), ou + ".heure")
        if not (isinstance(evenement.get("duree"), int) and evenement["duree"] > 0):
            erreurs.append("%s.duree : il faut un nombre entier de minutes, supérieur à 0" % ou)
        if evenement["type"] == "panne_sonde":
            if evenement.get("mode") not in MODES_PANNE:
                erreurs.append("%s.mode : %r inconnu (connus : %s)" % (ou, evenement.get("mode"), ", ".join(MODES_PANNE)))
            if evenement.get("sonde", "piece") not in ("piece", "reprise"):
                erreurs.append("%s.sonde : %r inconnue (attendu \"piece\" ou \"reprise\")" % (ou, evenement.get("sonde")))
        if evenement["type"] in ("absence", "presence"):
            cibles = evenement.get("occupants", "tous")
            if cibles != "tous" and not (isinstance(cibles, list) and all(c in identifiants for c in cibles)):
                erreurs.append("%s.occupants : \"tous\" ou une liste d'id connus (%s)" % (ou, ", ".join(sorted(identifiants))))
        if evenement["type"] == "visiteurs" and not (isinstance(evenement.get("nb"), int) and evenement["nb"] > 0):
            erreurs.append("%s.nb : il faut un nombre entier de visiteurs, supérieur à 0" % ou)
    return erreurs


def empreinte(scenario):
    """Identifiant court d'un scénario : deux bilans ne se comparent que s'il est identique."""
    canonique = json.dumps(scenario, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(canonique.encode("utf-8")).hexdigest()[:12]


# ---------------------------------------------------------------- contrôleurs

def thermostat_reference(etat):
    """La référence à battre : 18 °C de 7h à 19h, sans regarder la pièce."""
    return {"marche": 7 * 60 <= etat["minute"] < 19 * 60, "consigne": 18, "ventilation": "auto"}


class ControleurFonction:
    """Contrôleur écrit en Python et appelé directement, sans sous-processus."""

    description = "fonction Python"

    def __init__(self, decider, initialiser=None):
        self._decider = decider
        self._initialiser = initialiser

    def initialiser(self, infos):
        if self._initialiser:
            self._initialiser(infos)

    def decider(self, etat):
        return self._decider(etat)

    def terminer(self):
        pass


class ControleurProcessus:
    """Contrôleur lancé comme un programme à part : une ligne JSON par message (voir CONTRAT.md)."""

    def __init__(self, commande, delai_pas=30.0, delai_init=120.0, debug=False):
        self.description = commande
        self.delai_pas = delai_pas
        self.delai_init = delai_init
        self.debug = debug
        self.derniere_ligne = ""
        self.avertissement = ""
        self._en_retard = 0
        self._lignes = queue.Queue()
        environnement = dict(os.environ, PYTHONUNBUFFERED="1", PYTHONIOENCODING="utf-8", PYTHONUTF8="1")
        try:
            self._processus = subprocess.Popen(
                # Windows découpe lui-même la ligne de commande ; ailleurs, on suit les règles du shell.
                commande if os.name == "nt" else shlex.split(commande),
                stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                encoding="utf-8", bufsize=1, env=environnement,
            )
        except (OSError, ValueError) as erreur:
            raise ControleurArrete("impossible de lancer le contrôleur « %s » : %s" % (commande, erreur))
        threading.Thread(target=self._lire, daemon=True).start()

    def _lire(self):
        try:
            for ligne in self._processus.stdout:
                self._lignes.put(ligne)
        except (OSError, ValueError):
            pass
        self._lignes.put(None)

    def _echanger(self, message, delai):
        """Envoie un message et renvoie la réponse : la première ligne reçue qui est un objet JSON.

        Toute autre ligne (un print() de debug, par exemple) est ignorée et signalée dans
        self.avertissement, pour ne jamais décaler les réponses d'une minute sur la suivante.
        """
        self.avertissement = ""
        self.derniere_ligne = json.dumps(message, ensure_ascii=False)
        if self.debug:
            print("→ " + self.derniere_ligne, file=sys.stderr)
        try:
            self._processus.stdin.write(self.derniere_ligne + "\n")
            self._processus.stdin.flush()
        except (OSError, ValueError):
            raise ControleurArrete(self._diagnostic())
        limite = time.monotonic() + delai
        while True:
            reste = limite - time.monotonic()
            try:
                if reste <= 0:
                    raise queue.Empty
                ligne = self._lignes.get(timeout=reste)
            except queue.Empty:
                self._en_retard += 1  # sa réponse arrivera plus tard : il faudra l'ignorer
                raise DelaiDepasse()
            if ligne is None:
                raise ControleurArrete(self._diagnostic())
            if self.debug:
                print("← " + ligne.rstrip("\n"), file=sys.stderr)
            try:
                reponse = json.loads(ligne)
            except json.JSONDecodeError:
                reponse = None
            if not isinstance(reponse, dict):
                if ligne.strip() and not self.avertissement:
                    self.avertissement = (
                        "ligne ignorée sur la sortie standard, réservée au protocole : %r" % ligne.strip()[:80])
                continue
            if self._en_retard:
                self._en_retard -= 1
                continue
            return reponse

    def _diagnostic(self):
        code = self._processus.poll()
        return (
            "le contrôleur « %s » s'est arrêté%s.\n"
            "  Dernier message envoyé : %s\n"
            "  Son message d'erreur est affiché juste au-dessus (sortie d'erreur)."
            % (self.description, "" if code is None else " (code %s)" % code, self.derniere_ligne[:300])
        )

    def initialiser(self, infos):
        try:
            self._echanger(infos, self.delai_init)
        except DelaiDepasse:
            raise ControleurArrete(
                "le contrôleur « %s » n'a pas répondu au message \"init\" en %d s." % (self.description, self.delai_init)
            )

    def decider(self, etat):
        return self._echanger(etat, self.delai_pas)

    def terminer(self):
        if self._processus.stdin.closed:
            return
        try:
            self._processus.stdin.write(json.dumps({"type": "fin"}) + "\n")
            self._processus.stdin.flush()
        except (OSError, ValueError):
            pass
        try:
            self._processus.stdin.close()
        except OSError:
            pass
        try:
            self._processus.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self._processus.kill()
            self._processus.wait()
        self._processus.stdout.close()


def _lire_reponse(reponse, commande, messages_connus):
    """Applique la réponse du contrôleur à la commande en cours. Un champ absent ne change rien."""
    erreurs = []
    reponses, journal = [], ""
    if not isinstance(reponse, dict):
        return reponses, journal, "réponse invalide : il faut un objet JSON"
    inconnus = sorted(set(reponse) - CHAMPS_REPONSE)
    if inconnus:
        erreurs.append("champ inconnu : %s" % ", ".join(str(c) for c in inconnus))
    if "marche" in reponse:
        if isinstance(reponse["marche"], bool):
            commande["marche"] = reponse["marche"]
        else:
            erreurs.append("marche : il faut true ou false")
    if "consigne" in reponse:
        if _est_nombre(reponse["consigne"]) and math.isfinite(reponse["consigne"]):
            commande["consigne"] = float(reponse["consigne"])
        else:
            erreurs.append("consigne : il faut un nombre")
    if "ventilation" in reponse:
        if reponse["ventilation"] in VENTILATIONS:
            commande["ventilation"] = reponse["ventilation"]
        else:
            erreurs.append("ventilation : attendu auto, faible ou fort")
    if "reponses" in reponse:
        valides = isinstance(reponse["reponses"], list) and all(
            isinstance(r, dict) and isinstance(r.get("texte"), str) for r in reponse["reponses"])
        if valides:
            reponses = [{"message": r.get("message"), "texte": r["texte"]} for r in reponse["reponses"]]
            inconnus = [r["message"] for r in reponses if r["message"] not in messages_connus]
            if inconnus:
                erreurs.append("reponses : message inconnu %s" % ", ".join(str(i) for i in inconnus))
        else:
            erreurs.append("reponses : il faut une liste de {message, texte}")
    if "journal" in reponse:
        journal = reponse["journal"] if isinstance(reponse["journal"], str) else json.dumps(
            reponse["journal"], ensure_ascii=False)
    return reponses, journal, " ; ".join(erreurs)


# ---------------------------------------------------------------- la journée

class Journee:
    """L'état de la pièce, de la clim et des occupants pendant une journée simulée."""

    def __init__(self, scenario):
        self.scenario = scenario
        self.physique = dict(PHYSIQUE)
        self.physique.update({c: v for c, v in scenario["piece"].items() if c in PHYSIQUE})
        self.orientation = scenario["piece"]["orientation"]
        self.meteo = scenario["meteo"]
        self.occupants = [
            {
                "id": o["id"],
                "preference": float(o.get("preference", PREFERENCE_PAR_DEFAUT)),
                "tolerance": float(o.get("tolerance", TOLERANCE_PAR_DEFAUT)),
                "plages": plages_de(o.get("horaires", "")),
            }
            for o in scenario["occupants"]
        ]
        self.evenements = []
        for evenement in scenario["evenements"]:
            debut = minute_de(evenement["heure"])
            self.evenements.append((debut, debut + evenement["duree"], evenement))
        # L'aléa dépend de tout le scénario, pas seulement de sa graine : connaître la graine
        # d'un scénario public ne permet pas de prédire le bruit d'un autre.
        graine = "%s-%s" % (scenario["graine"], empreinte(scenario))
        # Des tirages séparés : les plaintes ne décalent jamais le bruit des sondes.
        self.alea_sondes = random.Random("%s-sondes" % graine)
        self.alea_plaintes = random.Random("%s-plaintes" % graine)
        self.alea_prevision = random.Random("%s-prevision" % graine)

        self.t_air = self.t_masse = 26.0
        self.humidite = 65.0
        self.compresseur = False
        self.bloque_jusqu = 0
        self.demarrages = 0
        self.lectures_split = []
        self.derniere_lecture = {"piece": None, "reprise": None}
        self._prechauffer()

    # ---- météo et soleil

    def t_ext(self, minute):
        return interpoler(self.meteo["t_ext"], minute)

    def soleil(self, minute):
        """Apport solaire par la baie vitrée, en watts."""
        heure = minute / 60.0
        debut, fin = (5.5, 12.5) if self.orientation == "est" else (12.0, 19.0)
        if not debut <= heure <= fin:
            return 0.0
        profil = math.sin((heure - debut) / (fin - debut) * math.pi)
        return self.physique["w_solaire_max"] * profil * (1 - 0.75 * interpoler(self.meteo["nebulosite"], minute))

    def prevision(self):
        """La météo annoncée au contrôleur : proche de la réalité, jamais exacte."""
        erreur = float(self.meteo.get("erreur_prevision", 0))
        biais = self.alea_prevision.uniform(-erreur, erreur)
        annonce = []
        for heure in range(24):
            if "prevision_t_ext" in self.meteo:
                t_ext = self.meteo["prevision_t_ext"][heure]
            else:
                t_ext = self.meteo["t_ext"][heure] + biais + self.alea_prevision.uniform(-0.3, 0.3)
            nebulosite = self.meteo.get("prevision_nebulosite", self.meteo["nebulosite"])[heure]
            annonce.append({"heure": heure_de(heure * 60), "t_ext": round(t_ext, 1), "nebulosite": round(nebulosite, 1)})
        return annonce

    # ---- événements, présence, sondes

    def actifs(self, minute, type_evenement):
        return [e for debut, fin, e in self.evenements if e["type"] == type_evenement and debut <= minute < fin]

    def presents(self, minute):
        """(occupants nommés présents, nombre de visiteurs)."""
        def vise(evenement, occupant):
            cibles = evenement.get("occupants", "tous")
            return cibles == "tous" or occupant["id"] in cibles

        presents = []
        for occupant in self.occupants:
            la = any(debut <= minute < fin for debut, fin in occupant["plages"])
            if any(vise(e, occupant) for e in self.actifs(minute, "absence")):
                la = False
            if any(vise(e, occupant) for e in self.actifs(minute, "presence")):
                la = True
            if la:
                presents.append(occupant)
        visiteurs = sum(e["nb"] for e in self.actifs(minute, "visiteurs"))
        return presents, visiteurs

    def lire_sonde(self, nom, valeur_reelle, minute):
        """Ce qu'affiche une sonde : la réalité, du bruit, et parfois une panne."""
        valeur = valeur_reelle + self.alea_sondes.uniform(-BRUIT_SONDE, BRUIT_SONDE)
        for debut, _fin, evenement in self.evenements:
            if evenement["type"] != "panne_sonde" or evenement.get("sonde", "piece") != nom:
                continue
            if not debut <= minute < debut + evenement["duree"]:
                continue
            mode = evenement["mode"]
            ecoule = minute - debut + 1
            if mode == "absente":
                return None
            if mode == "pic":
                return float(evenement.get("valeur", 85.0))
            if mode == "figee":
                if self.derniere_lecture[nom] is not None:
                    return self.derniere_lecture[nom]
            elif mode == "derive":
                valeur += evenement.get("amplitude", 2.0) * min(1.0, ecoule / evenement["duree"])
            elif mode == "soleil":
                valeur += evenement.get("amplitude", 4.0) * min(1.0, ecoule / 10.0)
        valeur = round(valeur, 1)
        self.derniere_lecture[nom] = valeur
        return valeur

    # ---- clim et physique

    def regler_clim(self, commande, t_piece, t_reprise, minute):
        """La clim décide seule de sa puissance, d'après la consigne et la sonde de la pièce.

        Renvoie l'état de la clim pendant cette minute.
        """
        consigne = min(CLIM_CONSIGNE_MAX, max(CLIM_CONSIGNE_MIN, math.floor(commande["consigne"] * 2 + 0.5) / 2))
        # Sans sonde de pièce, la clim se rabat sur sa sonde de reprise.
        lecture = t_piece if t_piece is not None else t_reprise
        if lecture is not None:
            self.lectures_split = (self.lectures_split + [lecture])[-3:]
        ecart = (statistics.median(self.lectures_split) - consigne) if self.lectures_split else 0.0

        veut = self.compresseur
        if not commande["marche"]:
            veut = False
        elif self.compresseur and ecart < -CLIM_HYSTERESIS:
            veut = False
        elif not self.compresseur and ecart > CLIM_HYSTERESIS:
            veut = True

        bloque = False
        if veut and not self.compresseur:
            if minute < self.bloque_jusqu:
                veut, bloque = False, True
            else:
                self.demarrages += 1
        if self.compresseur and not veut:
            self.bloque_jusqu = minute + 1 + CLIM_ANTI_COURT_CYCLE_MIN
        self.compresseur = veut

        t_ext = self.t_ext(minute)
        plafond, ventilateur_w = VENTILATIONS[commande["ventilation"]]
        capacite = CLIM_PUISSANCE_FROID_W * plafond * min(1.1, max(0.9, 1 - 0.012 * (t_ext - 35)))
        eer = min(5.5, max(2.5, 4.6 - 0.12 * (t_ext - 25)))
        froid_w = 0.0
        if veut:
            froid_w = min(capacite, max(CLIM_MODULATION_MIN * CLIM_PUISSANCE_FROID_W, CLIM_GAIN_W_PAR_K * ecart))
        electrique_w = CLIM_VEILLE_W + froid_w / eer + (ventilateur_w if commande["marche"] else 0.0)
        return {
            "marche": commande["marche"], "consigne": consigne, "ventilation": commande["ventilation"],
            "puissance_w": round(electrique_w), "compresseur": veut, "compresseur_bloque": bloque,
            "froid_w": froid_w, "electrique_w": electrique_w, "eer": eer,
        }

    def avancer(self, minute, nb_presents, froid_w, compresseur):
        """Fait évoluer la pièce d'une minute."""
        p = self.physique
        t_ext = self.t_ext(minute)
        ua_ext = p["ua_air_ext"] + p["ua_air_neuf_par_occupant"] * nb_presents
        if self.actifs(minute, "fenetre_ouverte"):
            ua_ext += p["ua_fenetre_ouverte"]
        apports = nb_presents * p["w_par_occupant"] + (p["w_eclairage"] if nb_presents else 0.0)
        soleil = self.soleil(minute)
        flux_air = (
            ua_ext * (t_ext - self.t_air) + p["ua_air_masse"] * (self.t_masse - self.t_air)
            + apports + soleil * (1 - p["part_solaire_masse"]) - froid_w
        )
        flux_masse = (
            p["ua_air_masse"] * (self.t_air - self.t_masse) + p["ua_masse_ext"] * (t_ext - self.t_masse)
            + soleil * p["part_solaire_masse"]
        )
        self.t_air += 60.0 * flux_air / p["c_air"]
        self.t_masse += 60.0 * flux_masse / p["c_masse"]
        cible_humidite = 50.0 if compresseur else min(85.0, 68.0 + 2.0 * nb_presents)
        self.humidite += (cible_humidite - self.humidite) / 30.0

    def _prechauffer(self):
        """Trois journées ordinaires avant la journée simulée, pour partir de murs réalistes."""
        for _jour in range(3):
            self.bloque_jusqu = 0
            for minute in range(MINUTES_PAR_JOUR):
                nb = sum(1 for o in self.occupants if any(d <= minute < f for d, f in o["plages"]))
                commande = {"marche": 7 * 60 <= minute < 19 * 60, "consigne": 25.0, "ventilation": "auto"}
                clim = self.regler_clim(commande, self.t_air, None, minute)
                self.avancer(minute, nb, clim["froid_w"], clim["compresseur"])
        self.compresseur = False
        self.bloque_jusqu = 0
        self.demarrages = 0
        self.lectures_split = []


def simuler(scenario, controleur, plaintes_auto=True, jusqu=MINUTES_PAR_JOUR, a_chaque_pas=None, messages_live=None):
    """Joue une journée avec un contrôleur. Renvoie {"bilan": ..., "lignes": [...]}.

    a_chaque_pas(ligne) est appelée après chaque minute avec ce que voit le contrôleur.
    messages_live() renvoie les phrases ajoutées en direct : [(occupant, texte), ...].
    """
    try:
        return _simuler(scenario, controleur, plaintes_auto, jusqu, a_chaque_pas, messages_live)
    finally:
        controleur.terminer()


def _simuler(scenario, controleur, plaintes_auto, jusqu, a_chaque_pas, messages_live):
    journee = Journee(scenario)
    limites = scenario["limites"]
    phrases = {}
    for phrase in scenario["phrases"]:
        phrases.setdefault(minute_de(phrase["heure"]), []).append(phrase)

    controleur.initialiser({
        "type": "init",
        "version": VERSION,
        "limites": dict(limites),
        "plage_confort": list(PLAGE_CONFORT),
        "occupants": [o["id"] for o in journee.occupants],
        "planning": copy.deepcopy(scenario["planning"]),
        "prevision_meteo": journee.prevision(),
    })

    commande = {"marche": False, "consigne": 25.0, "ventilation": "auto"}
    etat_clim = {"marche": False, "consigne": 25.0, "ventilation": "auto", "puissance_w": round(CLIM_VEILLE_W),
                 "compresseur": False, "compresseur_bloque": False}
    lignes, commandes = [], []
    gene = {o["id"]: 0 for o in journee.occupants}
    prochaine_plainte = {o["id"]: 0 for o in journee.occupants}
    messages_connus, messages_repondus, plaintes = set(), set(), []
    total = {
        "kwh": 0.0, "inconfort": 0, "chaud": 0, "froid": 0, "minutes_personne": 0, "degres_heures": 0.0,
        "hors_limites": 0, "erreurs": 0, "delais": 0, "messages": 0,
        "t_max": None, "t_min": None, "temps_max_ms": 0.0,
    }

    for minute in range(jusqu):
        presents, visiteurs = journee.presents(minute)
        nb_reel = len(presents) + visiteurs
        t_reelle = journee.t_air
        t_piece = journee.lire_sonde("piece", t_reelle, minute)
        t_reprise = journee.lire_sonde("reprise", t_reelle + ECART_REPRISE, minute)
        detectes = 0 if journee.actifs(minute, "pir_aveugle") else nb_reel

        # Les messages de cette minute : scénario, plaintes automatiques, direct.
        messages = []

        def ajouter(occupant, texte, source):
            total["messages"] += 1
            identifiant = "m%d" % total["messages"]
            messages_connus.add(identifiant)
            messages.append({"id": identifiant, "occupant": occupant, "texte": texte, "source": source})
            return identifiant

        for phrase in phrases.get(minute, []):
            ajouter(phrase["occupant"], phrase["texte"], "script")
        ids_presents = set()
        for occupant in presents:
            ids_presents.add(occupant["id"])
            ecart_perso = t_reelle - occupant["preference"]
            gene[occupant["id"]] = gene[occupant["id"]] + 1 if abs(ecart_perso) > occupant["tolerance"] else 0
            if plaintes_auto and gene[occupant["id"]] >= PLAINTE_APRES_MIN and minute >= prochaine_plainte[occupant["id"]]:
                texte = journee.alea_plaintes.choice(PHRASES_CHAUD if ecart_perso > 0 else PHRASES_FROID)
                plaintes.append((minute, ajouter(occupant["id"], texte, "auto"), ecart_perso > 0))
                prochaine_plainte[occupant["id"]] = minute + PLAINTE_PAUSE_MIN
        for occupant in journee.occupants:
            if occupant["id"] not in ids_presents:
                gene[occupant["id"]] = 0
        if messages_live:
            for occupant, texte in messages_live():
                ajouter(occupant, texte, "direct")

        etat = {
            "type": "pas", "minute": minute, "heure": heure_de(minute),
            "t_piece": t_piece, "t_reprise": t_reprise, "t_ext": round(journee.t_ext(minute), 1),
            "humidite": round(journee.humidite), "occupants_detectes": detectes, "messages": messages,
            "split": {c: etat_clim[c] for c in
                      ("marche", "consigne", "ventilation", "puissance_w", "compresseur", "compresseur_bloque")},
        }

        depart = time.monotonic()
        reponses, journal, erreur = [], "", ""
        try:
            reponses, journal, erreur = _lire_reponse(controleur.decider(etat), commande, messages_connus)
        except DelaiDepasse:
            erreur = "délai dépassé : dernière commande conservée"
            total["delais"] += 1
        avertissement = getattr(controleur, "avertissement", "")
        if avertissement:
            erreur = " ; ".join(e for e in (avertissement, erreur) if e)
        temps_ms = (time.monotonic() - depart) * 1000.0
        total["temps_max_ms"] = max(total["temps_max_ms"], temps_ms)
        if erreur:
            total["erreurs"] += 1
        messages_repondus.update(r["message"] for r in reponses if r["texte"].strip())
        etat_clim = journee.regler_clim(commande, t_piece, t_reprise, minute)
        # On retient la consigne appliquée par la clim : une variation de 0,01 °C n'est pas une action.
        commandes.append((etat_clim["marche"], etat_clim["consigne"]))
        total["kwh"] += etat_clim["electrique_w"] / 60000.0

        inconfort = ""
        if nb_reel:
            total["t_max"] = t_reelle if total["t_max"] is None else max(total["t_max"], t_reelle)
            total["t_min"] = t_reelle if total["t_min"] is None else min(total["t_min"], t_reelle)
            ecart = max(PLAGE_CONFORT[0] - t_reelle, t_reelle - PLAGE_CONFORT[1], 0.0)
            if ecart > 0:
                inconfort = "chaud" if t_reelle > PLAGE_CONFORT[1] else "froid"
                total["inconfort"] += 1
                total[inconfort] += 1
                total["minutes_personne"] += nb_reel
                total["degres_heures"] += ecart / 60.0
        if etat_clim["marche"] and not limites["consigne_min"] <= etat_clim["consigne"] <= limites["consigne_max"]:
            total["hors_limites"] += 1

        ligne = {
            "minute": minute, "heure": heure_de(minute), "t_piece": t_piece, "t_reprise": t_reprise,
            "t_ext": etat["t_ext"], "humidite": etat["humidite"], "occupants_detectes": detectes,
            "marche_demandee": commande["marche"], "consigne_demandee": commande["consigne"],
            "ventilation": commande["ventilation"],
            "marche": etat_clim["marche"], "consigne": etat_clim["consigne"],
            "puissance_w": etat_clim["puissance_w"], "compresseur": etat_clim["compresseur"],
            "compresseur_bloque": etat_clim["compresseur_bloque"], "kwh_cumules": round(total["kwh"], 4),
            "messages": messages, "reponses": reponses, "journal": journal, "erreur": erreur,
            "temps_reponse_ms": round(temps_ms, 1),
            "t_reelle": round(t_reelle, 2), "t_masse": round(journee.t_masse, 2), "presence_reelle": nb_reel,
            "puissance_froid_w": round(etat_clim["froid_w"]), "eer": round(etat_clim["eer"], 2),
            "inconfort": inconfort,
            "evenements": [e["type"] + (":" + e["mode"] if "mode" in e else "")
                           for debut, fin, e in journee.evenements if debut <= minute < fin],
        }
        lignes.append(ligne)
        if a_chaque_pas:
            a_chaque_pas(ligne)
        journee.avancer(minute, nb_reel, etat_clim["froid_w"], etat_clim["compresseur"])

    # Une plainte a un effet si l'assistant y répond, ou s'il agit dans le bon sens sous 15 minutes.
    sans_effet = 0
    for minute, identifiant, trop_chaud in plaintes:
        marche_avant, consigne_avant = commandes[minute - 1] if minute else (False, 25.0)
        if trop_chaud:
            bon_sens = any((marche and not marche_avant) or consigne < consigne_avant
                           for marche, consigne in commandes[minute:minute + PLAINTE_EFFET_MIN + 1])
        else:
            bon_sens = any((marche_avant and not marche) or consigne > consigne_avant
                           for marche, consigne in commandes[minute:minute + PLAINTE_EFFET_MIN + 1])
        if not bon_sens and identifiant not in messages_repondus:
            sans_effet += 1

    prevus = max([creneau["nb"] for creneau in scenario["planning"]] or [0])
    budget = int(BUDGET_MINUTES_PAR_OCCUPANT * prevus + 0.5) if prevus else BUDGET_SANS_PLANNING
    bilan = {
        "simulateur": VERSION,
        "scenario": scenario["nom"],
        "empreinte_scenario": empreinte(scenario),
        "empreinte_simulateur": EMPREINTE_SIMULATEUR,
        "graine": scenario["graine"],
        "jusqu": heure_de(jusqu),
        "kwh": round(total["kwh"], 3),
        "minutes_inconfort": total["inconfort"],
        "minutes_trop_chaud": total["chaud"],
        "minutes_trop_froid": total["froid"],
        "minutes_personne_inconfort": total["minutes_personne"],
        "degres_heures": round(total["degres_heures"], 2),
        "t_max_en_presence": None if total["t_max"] is None else round(total["t_max"], 1),
        "t_min_en_presence": None if total["t_min"] is None else round(total["t_min"], 1),
        "budget_confort": {
            "limite_minutes_personne": budget,
            "respecte": total["minutes_personne"] <= budget,
        },
        "messages": total["messages"],
        "messages_sans_reponse": len(messages_connus - messages_repondus),
        "plaintes": len(plaintes),
        "plaintes_sans_effet": sans_effet,
        "minutes_hors_limites_client": total["hors_limites"],
        "demarrages_compresseur": journee.demarrages,
        "changements_de_consigne": sum(1 for avant, apres in zip(commandes, commandes[1:]) if avant[1] != apres[1]),
        "erreurs_controleur": total["erreurs"],
        "delais_depasses": total["delais"],
    }
    return {"bilan": bilan, "lignes": lignes, "temps_reponse_max_ms": round(total["temps_max_ms"], 1)}


def simuler_avec_reference(scenario, controleur, **options):
    """Joue la journée avec le contrôleur, puis avec la référence à 18 °C, et compare."""
    resultat = simuler(scenario, controleur, **options)
    options.pop("a_chaque_pas", None)
    options.pop("messages_live", None)
    reference = simuler(scenario, ControleurFonction(thermostat_reference), **options)["bilan"]
    bilan = resultat["bilan"]
    cles = ("kwh", "minutes_inconfort", "minutes_trop_chaud", "minutes_trop_froid", "minutes_personne_inconfort",
            "degres_heures", "plaintes", "minutes_hors_limites_client", "demarrages_compresseur")
    bilan["reference"] = {cle: reference[cle] for cle in cles}
    bilan["gain_kwh_pct"] = round(100.0 * (reference["kwh"] - bilan["kwh"]) / reference["kwh"], 1) if reference["kwh"] else 0.0
    return resultat


# ---------------------------------------------------------------- fichiers de résultats

def _cellule(valeur):
    if valeur is None:
        return ""
    if isinstance(valeur, bool):
        return "1" if valeur else "0"
    if isinstance(valeur, (list, dict)):
        return json.dumps(valeur, ensure_ascii=False) if valeur else ""
    return valeur


def ecrire_resultats(dossier, resultat):
    """Écrit journee.csv (toutes les colonnes, vérité comprise) et bilan.json."""
    dossier = Path(dossier)
    dossier.mkdir(parents=True, exist_ok=True)
    colonnes = COLONNES_DIRECT + COLONNES_VERITE
    with open(dossier / "journee.csv", "w", newline="", encoding="utf-8") as fichier:
        ecrivain = csv.writer(fichier)
        ecrivain.writerow(colonnes)
        for ligne in resultat["lignes"]:
            ecrivain.writerow([_cellule(ligne[c]) for c in colonnes])
    with open(dossier / "bilan.json", "w", encoding="utf-8") as fichier:
        json.dump(resultat["bilan"], fichier, ensure_ascii=False, indent=2)
        fichier.write("\n")


class JournalDirect:
    """direct.csv : ce que voit le contrôleur, écrit minute par minute pendant la simulation."""

    def __init__(self, dossier):
        Path(dossier).mkdir(parents=True, exist_ok=True)
        self._fichier = open(Path(dossier) / "direct.csv", "w", newline="", encoding="utf-8")
        self._ecrivain = csv.writer(self._fichier)
        self._ecrivain.writerow(COLONNES_DIRECT)
        self._fichier.flush()

    def ecrire(self, ligne):
        self._ecrivain.writerow([_cellule(ligne[c]) for c in COLONNES_DIRECT])
        self._fichier.flush()

    def fermer(self):
        self._fichier.close()


class FileDirecte:
    """Les phrases ajoutées pendant une démo avec --dire, lues minute par minute."""

    def __init__(self, chemin, vider=False):
        self.chemin = Path(chemin)
        self._position = 0
        if vider:
            self.chemin.parent.mkdir(parents=True, exist_ok=True)
            self.chemin.write_text("", encoding="utf-8")

    def ajouter(self, phrase):
        occupant, separateur, texte = phrase.partition(":")
        if not separateur:
            occupant, texte = "client", phrase
        self.chemin.parent.mkdir(parents=True, exist_ok=True)
        with open(self.chemin, "a", encoding="utf-8") as fichier:
            fichier.write(json.dumps({"occupant": occupant.strip(), "texte": texte.strip()}, ensure_ascii=False) + "\n")

    def nouvelles(self):
        if not self.chemin.is_file():
            return []
        with open(self.chemin, encoding="utf-8") as fichier:
            fichier.seek(self._position)
            lignes = fichier.readlines()
            self._position = fichier.tell()
        phrases = []
        for ligne in lignes:
            try:
                entree = json.loads(ligne)
                phrases.append((str(entree["occupant"]), str(entree["texte"])))
            except (ValueError, KeyError, TypeError):
                continue
        return phrases


# ---------------------------------------------------------------- ligne de commande

def resume(bilan, controleur):
    """Le bilan en quelques lignes lisibles."""
    reference = bilan.get("reference", {})

    def ligne(titre, cle, suffixe=""):
        return "  %-34s %10s %14s%s" % (titre, bilan[cle], reference.get(cle, ""), suffixe)

    budget = bilan["budget_confort"]
    lignes = [
        "COOL RUNNER · simulateur %s (%s)" % (bilan["simulateur"], bilan["empreinte_simulateur"]),
        "Scénario   : %s (empreinte %s)%s" % (
            bilan["scenario"], bilan["empreinte_scenario"],
            "" if bilan["jusqu"] == "24:00" else " · arrêté à %s" % bilan["jusqu"]),
        "Contrôleur : %s" % controleur,
        "",
        "  %-34s %10s %14s" % ("", "Toi", "Référence 18°C"),
        ligne("kWh consommés", "kwh", "   gain %s %%" % bilan.get("gain_kwh_pct", "?")),
        ligne("Minutes d'inconfort", "minutes_inconfort"),
        ligne("  dont trop chaud", "minutes_trop_chaud"),
        ligne("  dont trop froid", "minutes_trop_froid"),
        ligne("Minutes-personne d'inconfort", "minutes_personne_inconfort", "   budget %d : %s" % (
            budget["limite_minutes_personne"], "respecté" if budget["respecte"] else "DÉPASSÉ")),
        ligne("Degrés-heures", "degres_heures"),
        ligne("Plaintes automatiques", "plaintes"),
        "  %-34s %10s" % ("  dont sans effet sous 15 min", bilan["plaintes_sans_effet"]),
        "  %-34s %10s" % ("Messages reçus / sans réponse", "%d / %d" % (bilan["messages"], bilan["messages_sans_reponse"])),
        ligne("Minutes hors limites client", "minutes_hors_limites_client"),
        ligne("Démarrages du compresseur", "demarrages_compresseur"),
        "  %-34s %10s" % ("Changements de consigne", bilan["changements_de_consigne"]),
    ]
    if bilan["erreurs_controleur"]:
        lignes.append("  ⚠ %d réponse(s) du contrôleur en erreur, dont %d délai(s) dépassé(s) : voir la colonne « erreur » du CSV"
                      % (bilan["erreurs_controleur"], bilan["delais_depasses"]))
    return "\n".join(lignes)


def verifier():
    """Vérifie que le simulateur se comporte comme annoncé dans COMPORTEMENT.md."""
    scenario = charger_scenario("journee_type")
    depart = time.monotonic()
    sans_clim = simuler(scenario, ControleurFonction(lambda etat: {"marche": False}), plaintes_auto=False)
    reference = simuler(scenario, ControleurFonction(thermostat_reference))
    encore = simuler(scenario, ControleurFonction(thermostat_reference))
    raisonnable = simuler(scenario, ControleurFonction(
        lambda etat: {"marche": 7 * 60 <= etat["minute"] < 18 * 60, "consigne": 24.5}))
    duree = time.monotonic() - depart
    apres_midi = [l for l in reference["lignes"] if 14 * 60 <= l["minute"] < 17 * 60]
    controles = [
        ("sans clim, la pièce monte entre 30 et 36 °C en présence (%.1f °C)" % sans_clim["bilan"]["t_max_en_presence"],
         30 <= sans_clim["bilan"]["t_max_en_presence"] <= 36),
        ("la référence à 18 °C est saturée l'après-midi",
         sum(1 for l in apres_midi if l["puissance_froid_w"] >= 3400) >= 120),
        ("la référence fait grelotter les occupants (%d min trop froid)" % reference["bilan"]["minutes_trop_froid"],
         reference["bilan"]["minutes_trop_froid"] >= 120),
        ("une consigne raisonnable consomme moins que la référence (%.1f contre %.1f kWh)"
         % (raisonnable["bilan"]["kwh"], reference["bilan"]["kwh"]),
         raisonnable["bilan"]["kwh"] < 0.8 * reference["bilan"]["kwh"]),
        ("une même journée donne toujours le même bilan", reference["bilan"] == encore["bilan"]),
        ("quatre journées simulées en moins de 5 s (%.1f s)" % duree, duree < 5),
    ]
    for texte, ok in controles:
        print("  %s %s" % ("✔" if ok else "✘", texte))
    return all(ok for _texte, ok in controles)


def _analyser(arguments):
    analyseur = argparse.ArgumentParser(
        prog="simulate.py", add_help=False,
        description="Simule une journée d'un bureau climatisé et note ton contrôleur.")
    analyseur.add_argument("--aide", "-h", "--help", action="help", help="affiche cette aide")
    analyseur.add_argument("--scenario", default="journee_type", metavar="NOM",
                           help="nom d'un scénario du dossier scenarios/ ou chemin d'un fichier JSON (défaut : journee_type)")
    analyseur.add_argument("--controleur", metavar="COMMANDE",
                           help="commande qui lance ton contrôleur, entre guillemets (défaut : le contrôleur exemple)")
    analyseur.add_argument("--sortie", default="resultats", metavar="DOSSIER", help="dossier des résultats (défaut : resultats/)")
    analyseur.add_argument("--jusqu", metavar="HH:MM", help="arrête la journée à cette heure, pour itérer vite")
    analyseur.add_argument("--delai", type=float, default=30.0, metavar="S",
                           help="secondes laissées au contrôleur pour répondre à chaque minute (défaut : 30)")
    analyseur.add_argument("--sans-plaintes-auto", action="store_true", help="désactive les plaintes automatiques des occupants")
    analyseur.add_argument("--debug", action="store_true", help="affiche chaque message échangé avec le contrôleur")
    analyseur.add_argument("--live", action="store_true", help="mode démo : la journée défile, et --dire ajoute des phrases")
    analyseur.add_argument("--vitesse", type=float, default=0.2, metavar="S",
                           help="en --live, secondes réelles par minute simulée (défaut : 0.2)")
    analyseur.add_argument("--depuis", default="07:00", metavar="HH:MM",
                           help="en --live, heure à partir de laquelle la journée défile lentement (défaut : 07:00)")
    analyseur.add_argument("--dire", metavar="PHRASE",
                           help="ajoute une phrase à la démo en cours, ex. --dire \"lea: j'ai chaud\"")
    analyseur.add_argument("--liste", action="store_true", help="liste les scénarios disponibles")
    analyseur.add_argument("--valider", metavar="FICHIER", help="vérifie un fichier de scénario et s'arrête")
    analyseur.add_argument("--verifier", action="store_true", help="vérifie que le simulateur fonctionne sur ta machine")
    analyseur.add_argument("--version", action="version", version=VERSION)
    return analyseur.parse_args(arguments)


def main(arguments=None):
    for flux in (sys.stdout, sys.stderr):
        if hasattr(flux, "reconfigure"):  # accents et symboles lisibles partout, affichage immédiat
            flux.reconfigure(encoding="utf-8", line_buffering=True)
    options = _analyser(arguments)
    try:
        if options.liste:
            for nom in scenarios_disponibles():
                print("%-26s %s" % (nom, charger_scenario(nom)["description"]))
            return 0
        if options.valider:
            scenario = charger_scenario(options.valider)
            print("✔ scénario « %s » valide (empreinte %s)" % (scenario["nom"], empreinte(scenario)))
            return 0
        if options.verifier:
            return 0 if verifier() else 1
        if options.dire:
            file_directe = FileDirecte(Path(options.sortie) / "direct.jsonl")
            if not file_directe.chemin.is_file():
                print("✘ aucune démo en cours dans « %s » : lance d'abord simulate.py --live (avec le même --sortie)"
                      % options.sortie, file=sys.stderr)
                return 2
            file_directe.ajouter(options.dire)
            print("phrase ajoutée à la démo en cours")
            return 0

        scenario = charger_scenario(options.scenario)
        jusqu = minute_de(options.jusqu) if options.jusqu else MINUTES_PAR_JOUR
        depuis = minute_de(options.depuis)
        commande = options.controleur or '"%s" "%s"' % (sys.executable, CONTROLEUR_EXEMPLE)
        nom_controleur = options.controleur or "contrôleur exemple (thermostat à 18 °C)"
        dossier = Path(options.sortie) / scenario["nom"]
        for ancien in ("bilan.json", "journee.csv"):  # un run qui échoue ne doit pas laisser l'ancien bilan
            if (dossier / ancien).is_file():
                (dossier / ancien).unlink()
        controleur = ControleurProcessus(commande, delai_pas=options.delai, debug=options.debug)
        direct = JournalDirect(dossier)
        file_directe = FileDirecte(Path(options.sortie) / "direct.jsonl", vider=True) if options.live else None

        def a_chaque_pas(ligne):
            direct.ecrire(ligne)
            if not options.live:
                return
            if ligne["messages"] or ligne["reponses"] or ligne["minute"] % 15 == 0:
                print("%s  pièce %s °C  consigne %s  clim %s  %d W  %d occupant(s)" % (
                    ligne["heure"], ligne["t_piece"], ligne["consigne"], "marche" if ligne["marche"] else "arrêt",
                    ligne["puissance_w"], ligne["occupants_detectes"]))
            for message in ligne["messages"]:
                print("        %s : « %s »" % (message["occupant"], message["texte"]))
            for reponse in ligne["reponses"]:
                print("        assistant : « %s »" % reponse["texte"])
            if ligne["minute"] >= depuis:
                time.sleep(max(0.0, options.vitesse))

        try:
            resultat = simuler_avec_reference(
                scenario, controleur, plaintes_auto=not options.sans_plaintes_auto, jusqu=jusqu,
                a_chaque_pas=a_chaque_pas, messages_live=file_directe.nouvelles if file_directe else None)
        finally:
            direct.fermer()
            if file_directe and file_directe.chemin.is_file():
                file_directe.chemin.unlink()  # la démo est finie : --dire ne doit plus rien accepter
        ecrire_resultats(dossier, resultat)
        print(resume(resultat["bilan"], nom_controleur))
        print("\nRésultats : %s (journee.csv, bilan.json, direct.csv) · réponse la plus lente : %s ms"
              % (dossier, resultat["temps_reponse_max_ms"]))
        return 0
    except (ErreurScenario, ControleurArrete) as erreur:
        print("\n✘ %s" % erreur, file=sys.stderr)
        return 2
    except ValueError as erreur:
        print("\n✘ heure invalide : %s (attendu \"HH:MM\")" % erreur, file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
