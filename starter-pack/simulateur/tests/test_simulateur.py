"""Tests du simulateur, écrits contre ses interfaces publiques :
la fonction simuler(), le protocole avec un contrôleur lancé à part, et la ligne de commande.

    python3 -m unittest discover -s starter-pack/simulateur/tests -v
"""
import copy
import csv
import json
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

DOSSIER_SIMULATEUR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(DOSSIER_SIMULATEUR))

import simulate  # noqa: E402
from simulate import ControleurFonction, ControleurProcessus, simuler  # noqa: E402

SIMULATE = str(DOSSIER_SIMULATEUR / "simulate.py")


def scenario(**surcharges):
    """La journée type, avec quelques champs remplacés."""
    brut = copy.deepcopy(simulate._lire_scenario("journee_type"))
    brut.update(surcharges)
    return simulate.preparer_scenario(brut)


def consigne_fixe(consigne, debut=7 * 60, fin=18 * 60):
    return ControleurFonction(lambda etat: {"marche": debut <= etat["minute"] < fin, "consigne": consigne})


def sans_clim():
    return ControleurFonction(lambda etat: {"marche": False})


def reference():
    return ControleurFonction(simulate.thermostat_reference)


def evenement(type_evenement, heure, duree, **params):
    return dict(type=type_evenement, heure=heure, duree=duree, **params)


def ecrire_controleur(dossier, corps):
    """Écrit un contrôleur Python minimal et renvoie la commande qui le lance."""
    chemin = Path(dossier) / "controleur.py"
    chemin.write_text(textwrap.dedent(corps), encoding="utf-8")
    return '"%s" "%s"' % (sys.executable, chemin)


class PhysiqueDeLaPiece(unittest.TestCase):
    def test_sans_clim_la_piece_devient_etouffante_l_apres_midi(self):
        resultat = simuler(scenario(), sans_clim())
        self.assertGreater(resultat["bilan"]["t_max_en_presence"], 30)
        self.assertLess(resultat["bilan"]["t_max_en_presence"], 36)
        self.assertGreater(resultat["bilan"]["minutes_trop_chaud"], 300)
        self.assertEqual(resultat["bilan"]["minutes_trop_froid"], 0)

    def test_la_reference_a_18_degres_sature_et_fait_grelotter(self):
        resultat = simuler(scenario(), reference())
        apres_midi = [ligne for ligne in resultat["lignes"] if 14 * 60 <= ligne["minute"] < 17 * 60]
        self.assertTrue(all(ligne["puissance_froid_w"] >= 3400 for ligne in apres_midi), "la clim doit tourner à fond")
        self.assertTrue(all(ligne["t_reelle"] > 20 for ligne in apres_midi), "elle ne doit pas atteindre 18 °C")
        self.assertGreater(resultat["bilan"]["minutes_trop_froid"], 120)

    def test_une_consigne_raisonnable_bat_la_reference_sur_les_deux_tableaux(self):
        raisonnable = simuler(scenario(), consigne_fixe(25))["bilan"]
        naive = simuler(scenario(), reference())["bilan"]
        self.assertLess(raisonnable["kwh"], 0.7 * naive["kwh"])
        self.assertLessEqual(raisonnable["minutes_personne_inconfort"], 30)

    def test_refroidir_coute_moins_cher_quand_il_fait_frais_dehors(self):
        lignes = simuler(scenario(), reference())["lignes"]
        self.assertGreater(lignes[7 * 60 + 30]["eer"], lignes[15 * 60]["eer"] + 0.5)

    def test_une_fenetre_ouverte_fait_consommer_plus(self):
        ouverte = scenario(evenements=[evenement("fenetre_ouverte", "14:00", 90)])
        self.assertGreater(
            simuler(ouverte, consigne_fixe(25))["bilan"]["kwh"],
            simuler(scenario(), consigne_fixe(25))["bilan"]["kwh"] + 0.2)

    def test_la_meme_journee_donne_toujours_le_meme_resultat(self):
        charge = scenario(evenements=[evenement("panne_sonde", "10:00", 120, mode="derive")])
        premier = simuler(charge, consigne_fixe(25.5))
        second = simuler(charge, consigne_fixe(25.5))
        self.assertEqual(premier["bilan"], second["bilan"])
        for a, b in zip(premier["lignes"], second["lignes"]):
            a.pop("temps_reponse_ms"), b.pop("temps_reponse_ms")
        self.assertEqual(premier["lignes"], second["lignes"])


class ComportementDeLaClim(unittest.TestCase):
    def test_une_consigne_hors_bornes_est_ramenee_par_la_clim_et_comptee_hors_limites(self):
        resultat = simuler(scenario(), consigne_fixe(10))
        en_marche = [ligne for ligne in resultat["lignes"] if ligne["marche"]]
        self.assertTrue(all(ligne["consigne"] == 16 for ligne in en_marche))
        self.assertEqual(resultat["bilan"]["minutes_hors_limites_client"], len(en_marche))
        self.assertEqual(simuler(scenario(), consigne_fixe(25))["bilan"]["minutes_hors_limites_client"], 0)

    def test_le_compresseur_ne_redemarre_pas_avant_trois_minutes(self):
        hache = ControleurFonction(lambda etat: {"marche": etat["minute"] % 2 == 0, "consigne": 20})
        lignes = simuler(scenario(), hache, jusqu=12 * 60)["lignes"]
        demarrages = [l["minute"] for avant, l in zip(lignes, lignes[1:]) if l["compresseur"] and not avant["compresseur"]]
        arrets = [l["minute"] for avant, l in zip(lignes, lignes[1:]) if avant["compresseur"] and not l["compresseur"]]
        self.assertGreater(len(demarrages), 10)
        for arret, demarrage in zip(arrets, demarrages[1:]):
            self.assertGreaterEqual(demarrage - arret, 3)
        self.assertTrue(any(l["compresseur_bloque"] for l in lignes))

    def test_le_controleur_voit_l_etat_reel_de_la_clim_a_la_minute_suivante(self):
        vus = []

        def decider(etat):
            vus.append(etat["split"])
            return {"marche": True, "consigne": 20, "ventilation": "fort"}

        simuler(scenario(), ControleurFonction(decider), jusqu=10)
        self.assertFalse(vus[0]["marche"])
        self.assertTrue(vus[1]["marche"] and vus[1]["compresseur"])
        self.assertEqual((vus[1]["consigne"], vus[1]["ventilation"]), (20, "fort"))
        self.assertGreater(vus[1]["puissance_w"], 500)

    def test_un_champ_absent_garde_sa_valeur_precedente(self):
        def decider(etat):
            return {"marche": True, "consigne": 24} if etat["minute"] == 0 else {}

        lignes = simuler(scenario(), ControleurFonction(decider), jusqu=30)["lignes"]
        self.assertTrue(all(l["marche"] and l["consigne"] == 24 for l in lignes))


class SondesEtPannes(unittest.TestCase):
    def lignes_avec_panne(self, controleur=None, **panne):
        charge = scenario(evenements=[evenement("panne_sonde", "10:00", 120, **panne)])
        return simuler(charge, controleur or consigne_fixe(25))["lignes"]

    def test_le_controleur_ne_recoit_jamais_la_verite(self):
        etats = []
        simuler(scenario(), ControleurFonction(lambda etat: etats.append(etat) or {}), jusqu=5)
        for cle in simulate.COLONNES_VERITE:
            self.assertNotIn(cle, etats[0])
        self.assertEqual(
            set(etats[0]),
            {"type", "minute", "heure", "t_piece", "t_reprise", "t_ext", "humidite", "occupants_detectes",
             "messages", "split"})

    def test_la_sonde_de_reprise_lit_un_peu_plus_chaud_que_la_piece(self):
        lignes = simuler(scenario(), consigne_fixe(25))["lignes"]
        ecarts = [l["t_reprise"] - l["t_piece"] for l in lignes]
        self.assertAlmostEqual(sum(ecarts) / len(ecarts), 0.7, delta=0.1)

    def test_sonde_figee_affiche_la_meme_valeur_pendant_que_la_piece_bouge(self):
        lignes = self.lignes_avec_panne(mode="figee", controleur=sans_clim())
        pendant = lignes[10 * 60:12 * 60]
        self.assertEqual(len({l["t_piece"] for l in pendant}), 1)
        self.assertGreater(pendant[-1]["t_reelle"] - pendant[0]["t_reelle"], 0.5)
        self.assertGreater(len({l["t_piece"] for l in lignes[12 * 60:13 * 60]}), 1, "la sonde repart après la panne")

    def test_sonde_absente_vaut_null_et_la_clim_continue_sur_sa_sonde_de_reprise(self):
        lignes = self.lignes_avec_panne(mode="absente")
        pendant = lignes[10 * 60:12 * 60]
        self.assertTrue(all(l["t_piece"] is None for l in pendant))
        self.assertTrue(all(22 < l["t_reelle"] < 26 for l in pendant), "la pièce reste régulée")

    def test_pic_aberrant_affiche_une_valeur_impossible(self):
        charge = scenario(evenements=[evenement("panne_sonde", "10:00", 1, mode="pic")])
        lignes = simuler(charge, consigne_fixe(25))["lignes"]
        self.assertEqual(lignes[10 * 60]["t_piece"], 85.0)
        self.assertLess(lignes[10 * 60 + 1]["t_piece"], 30)

    def test_sonde_qui_derive_fait_trop_refroidir_la_piece(self):
        saine = simuler(scenario(), consigne_fixe(25))["lignes"]
        derive = self.lignes_avec_panne(mode="derive", amplitude=2.0)
        fin = 12 * 60 - 1
        self.assertAlmostEqual(derive[fin]["t_piece"] - derive[fin]["t_reelle"], 2.0, delta=0.4)
        self.assertLess(derive[fin]["t_reelle"], saine[fin]["t_reelle"] - 1.2, "la clim régule sur la sonde qui ment")

    def test_sonde_au_soleil_lit_plusieurs_degres_de_trop(self):
        lignes = self.lignes_avec_panne(mode="soleil", controleur=sans_clim())
        milieu = lignes[11 * 60]
        self.assertAlmostEqual(milieu["t_piece"] - milieu["t_reelle"], 4.0, delta=0.4)
        self.assertAlmostEqual(milieu["t_reprise"] - milieu["t_reelle"], 0.7, delta=0.3)

    def test_une_panne_peut_viser_la_sonde_de_reprise(self):
        lignes = self.lignes_avec_panne(mode="absente", sonde="reprise")
        self.assertIsNone(lignes[11 * 60]["t_reprise"])
        self.assertIsNotNone(lignes[11 * 60]["t_piece"])


class OccupantsEtMessages(unittest.TestCase):
    def test_detecteur_aveugle_annonce_zero_alors_que_la_piece_est_pleine(self):
        charge = scenario(evenements=[evenement("pir_aveugle", "10:00", 20)])
        ligne = simuler(charge, consigne_fixe(25))["lignes"][10 * 60 + 5]
        self.assertEqual((ligne["occupants_detectes"], ligne["presence_reelle"]), (0, 6))

    def test_absence_presence_et_visiteurs_changent_la_presence_reelle(self):
        charge = scenario(evenements=[
            evenement("absence", "14:00", 60, occupants="tous"),
            evenement("presence", "18:00", 60, occupants=["lea"]),
            evenement("visiteurs", "10:00", 30, nb=4),
        ])
        lignes = simuler(charge, consigne_fixe(25))["lignes"]
        self.assertEqual(lignes[14 * 60 + 30]["presence_reelle"], 0)
        self.assertEqual(lignes[18 * 60 + 30]["presence_reelle"], 1)
        self.assertEqual(lignes[10 * 60 + 10]["presence_reelle"], 10)

    def test_l_inconfort_ne_compte_que_quand_quelqu_un_est_la(self):
        vide = scenario(occupants=[], planning=[])
        bilan = simuler(vide, sans_clim())["bilan"]
        self.assertEqual(bilan["minutes_inconfort"], 0)
        self.assertIsNone(bilan["t_max_en_presence"])

    def test_minutes_personne_comptent_chaque_occupant_present(self):
        bilan = simuler(scenario(), sans_clim(), plaintes_auto=False)["bilan"]
        self.assertEqual(bilan["minutes_personne_inconfort"], 6 * bilan["minutes_inconfort"])
        self.assertFalse(bilan["budget_confort"]["respecte"])

    def test_le_budget_de_confort_depend_du_nombre_d_occupants_prevus(self):
        self.assertEqual(simuler(scenario(), consigne_fixe(25))["bilan"]["budget_confort"],
                         {"limite_minutes_personne": 45, "respecte": True})
        a_huit = scenario(planning=[{"debut": "08:00", "fin": "12:00", "nb": 8}])
        self.assertEqual(simuler(a_huit, sans_clim())["bilan"]["budget_confort"]["limite_minutes_personne"], 60)

    def test_un_pic_de_deux_minutes_sur_la_sonde_ne_fait_pas_perdre_le_budget(self):
        charge = scenario(evenements=[evenement("panne_sonde", "15:00", 2, mode="pic", valeur=-40.0)])
        bilan = simuler(charge, consigne_fixe(25))["bilan"]
        self.assertTrue(bilan["budget_confort"]["respecte"], bilan["minutes_personne_inconfort"])

    def test_le_bruit_des_sondes_ne_se_devine_pas_avec_la_seule_graine(self):
        import random
        alea = random.Random("%s-sondes" % scenario()["graine"])
        devinees = 0
        for ligne in simuler(scenario(), sans_clim(), jusqu=120)["lignes"]:
            bruit_piece, _bruit_reprise = alea.uniform(-0.2, 0.2), alea.uniform(-0.2, 0.2)
            if abs(ligne["t_piece"] - (ligne["t_reelle"] + bruit_piece)) < 0.051:
                devinees += 1
        self.assertLess(devinees, 100, "le bruit ne doit pas se déduire de la graine du scénario")

    def test_une_variation_infime_de_consigne_ne_compte_pas_comme_une_action(self):
        def decider(etat):  # change la consigne commandée de 0,01 °C à chaque message, sans rien faire
            return {"marche": False, "consigne": 26.0 + 0.01 * etat["minute"] % 0.2}

        bilan = simuler(scenario(), ControleurFonction(decider), jusqu=10 * 60)["bilan"]
        self.assertGreater(bilan["plaintes"], 0)
        self.assertEqual(bilan["plaintes_sans_effet"], bilan["plaintes"])
        self.assertEqual(bilan["changements_de_consigne"], 0)

    def test_la_consigne_s_arrondit_au_demi_degre_le_plus_proche(self):
        vus = []
        consignes = iter([24.25, 24.75, 24.2, 24.8])
        simuler(scenario(), ControleurFonction(
            lambda etat: vus.append(etat["split"]["consigne"]) or {"marche": True, "consigne": next(consignes, 24.8)}),
            jusqu=5)
        self.assertEqual(vus[1:], [24.5, 25.0, 24.0, 25.0])

    def test_une_phrase_du_scenario_arrive_a_sa_minute_et_la_reponse_est_enregistree(self):
        charge = scenario(phrases=[{"heure": "10:15", "occupant": "lea", "texte": "on part en réunion jusqu'à 11h"}])
        recus = []

        def decider(etat):
            recus.extend((etat["heure"], m) for m in etat["messages"])
            return {"marche": True, "consigne": 25,
                    "reponses": [{"message": m["id"], "texte": "Bien noté."} for m in etat["messages"]],
                    "journal": {"intention": "absence"} if etat["messages"] else ""}

        resultat = simuler(charge, ControleurFonction(decider))
        self.assertEqual(recus, [("10:15", {"id": "m1", "occupant": "lea", "source": "script",
                                             "texte": "on part en réunion jusqu'à 11h"})])
        ligne = resultat["lignes"][10 * 60 + 15]
        self.assertEqual(ligne["reponses"], [{"message": "m1", "texte": "Bien noté."}])
        self.assertEqual(json.loads(ligne["journal"]), {"intention": "absence"})
        self.assertEqual((resultat["bilan"]["messages"], resultat["bilan"]["messages_sans_reponse"]), (1, 0))

    def test_un_mauvais_controleur_recoit_des_plaintes_et_un_bon_n_en_recoit_pas(self):
        mauvais = simuler(scenario(), sans_clim())
        self.assertGreater(mauvais["bilan"]["plaintes"], 10)
        self.assertEqual(mauvais["bilan"]["plaintes_sans_effet"], mauvais["bilan"]["plaintes"])
        plaintes = [m for l in mauvais["lignes"] for m in l["messages"]]
        self.assertTrue(all(m["source"] == "auto" and m["texte"] in simulate.PHRASES_CHAUD for m in plaintes))
        self.assertGreater(len({m["texte"] for m in plaintes}), 2, "les formulations doivent varier")
        self.assertEqual(simuler(scenario(), consigne_fixe(24.5))["bilan"]["plaintes"], 0)

    def test_un_occupant_ne_se_plaint_pas_plus_d_une_fois_par_demi_heure(self):
        lignes = simuler(scenario(), sans_clim())["lignes"]
        minutes = [l["minute"] for l in lignes for m in l["messages"] if m["occupant"] == "lea"]
        self.assertTrue(all(b - a >= 30 for a, b in zip(minutes, minutes[1:])))

    def test_une_plainte_suivie_d_un_changement_de_consigne_n_est_pas_sans_effet(self):
        def decider(etat):
            if etat["messages"]:
                return {"marche": True, "consigne": 24}
            return {}

        bilan = simuler(scenario(), ControleurFonction(decider), jusqu=10 * 60)["bilan"]
        self.assertGreater(bilan["plaintes"], 0)
        self.assertLess(bilan["plaintes_sans_effet"], bilan["plaintes"])

    def test_une_plainte_a_laquelle_l_assistant_repond_n_est_pas_sans_effet(self):
        def decider(etat):
            return {"reponses": [{"message": m["id"], "texte": "La clim est en panne, désolé."} for m in etat["messages"]]}

        bilan = simuler(scenario(), ControleurFonction(decider), jusqu=10 * 60)["bilan"]
        self.assertGreater(bilan["plaintes"], 0)
        self.assertEqual(bilan["plaintes_sans_effet"], 0)

    def test_changer_la_consigne_dans_le_mauvais_sens_laisse_la_plainte_sans_effet(self):
        etat_interne = {"consigne": 26.0}

        def decider(etat):
            if etat["messages"]:  # ils ont chaud, et on remonte la consigne
                etat_interne["consigne"] += 0.5
            return {"marche": False, "consigne": etat_interne["consigne"]}

        bilan = simuler(scenario(), ControleurFonction(decider), jusqu=10 * 60)["bilan"]
        self.assertGreater(bilan["plaintes"], 0)
        self.assertEqual(bilan["plaintes_sans_effet"], bilan["plaintes"])

    def test_une_reponse_vide_ne_compte_pas_comme_une_reponse(self):
        def decider(etat):
            return {"reponses": [{"message": m["id"], "texte": "  "} for m in etat["messages"]]}

        bilan = simuler(scenario(), ControleurFonction(decider), jusqu=10 * 60)["bilan"]
        self.assertGreater(bilan["messages"], 0)
        self.assertEqual(bilan["messages_sans_reponse"], bilan["messages"])
        self.assertEqual(bilan["plaintes_sans_effet"], bilan["plaintes"])

    def test_sans_plaintes_auto_la_journee_ne_contient_que_les_phrases_du_scenario(self):
        self.assertEqual(simuler(scenario(), sans_clim(), plaintes_auto=False)["bilan"]["messages"], 0)

    def test_au_demarrage_le_controleur_recoit_planning_prevision_et_limites(self):
        recu = {}
        simuler(scenario(), ControleurFonction(lambda etat: {}, initialiser=recu.update), jusqu=1)
        self.assertEqual(recu["type"], "init")
        self.assertEqual(recu["limites"], {"consigne_min": 22, "consigne_max": 27})
        self.assertEqual(recu["planning"][0], {"debut": "08:00", "fin": "12:00", "nb": 6})
        self.assertEqual(len(recu["prevision_meteo"]), 24)
        ecarts = [abs(p["t_ext"] - reel) for p, reel in zip(recu["prevision_meteo"], scenario()["meteo"]["t_ext"])]
        self.assertGreater(max(ecarts), 0, "la prévision n'est jamais exacte")
        self.assertLess(max(ecarts), 2)
        self.assertNotIn("preference", json.dumps(recu))


class ReponsesInvalides(unittest.TestCase):
    def test_une_reponse_invalide_garde_la_derniere_commande_et_signale_l_erreur(self):
        reponses = iter([{"marche": True, "consigne": 24}, "n'importe quoi", {"consigne": "froid"},
                         {"ventilation": "turbo"}, {"reponses": [{"message": "m99", "texte": "?"}]},
                         {"consinge": 20}])
        resultat = simuler(scenario(), ControleurFonction(lambda etat: next(reponses, {})), jusqu=10)
        lignes = resultat["lignes"]
        self.assertTrue(all(l["marche"] and l["consigne"] == 24 for l in lignes))
        self.assertEqual([bool(l["erreur"]) for l in lignes[:7]], [False, True, True, True, True, True, False])
        self.assertIn("champ inconnu : consinge", lignes[5]["erreur"])
        self.assertEqual(resultat["bilan"]["erreurs_controleur"], 5)


class ScenariosFichiers(unittest.TestCase):
    def test_tous_les_scenarios_fournis_se_chargent_et_tournent(self):
        noms = simulate.scenarios_disponibles()
        self.assertIn("journee_type", noms)
        for nom in noms:
            with self.subTest(scenario=nom):
                charge = simulate.charger_scenario(nom)
                self.assertTrue(charge["description"], "chaque scénario doit avoir une description")
                bilan = simuler(charge, reference())["bilan"]
                self.assertGreater(bilan["kwh"], 3)

    def test_un_scenario_herite_d_un_autre_et_ne_decrit_que_ses_differences(self):
        with tempfile.TemporaryDirectory() as dossier:
            chemin = Path(dossier) / "variante.json"
            chemin.write_text(json.dumps({
                "base": "journee_type", "description": "test", "piece": {"orientation": "est"},
                "evenements": [evenement("fenetre_ouverte", "09:00", 30)]}), encoding="utf-8")
            charge = simulate.charger_scenario(str(chemin))
        self.assertEqual(charge["nom"], "variante")
        self.assertEqual(charge["piece"]["orientation"], "est")
        self.assertEqual(len(charge["occupants"]), 6)
        self.assertNotEqual(simulate.empreinte(charge), simulate.empreinte(scenario()))

    def test_les_erreurs_d_un_scenario_sont_lisibles(self):
        with self.assertRaises(simulate.ErreurScenario) as contexte:
            scenario(
                evenements=[evenement("fenetre_ouvert", "09:00", 30), evenement("panne_sonde", "25:00", 0, mode="cassee")],
                meteo={"t_ext": [25] * 12})
        message = str(contexte.exception)
        self.assertIn("evenements[0] : type inconnu 'fenetre_ouvert'", message)
        self.assertIn("evenements[1].heure", message)
        self.assertIn("evenements[1].mode", message)
        self.assertIn("meteo.t_ext", message)
        with self.assertRaises(simulate.ErreurScenario) as contexte:
            simulate.charger_scenario("inexistant")
        self.assertIn("journee_type", str(contexte.exception))


class ControleurLanceAPart(unittest.TestCase):
    def setUp(self):
        self._dossier = tempfile.TemporaryDirectory()
        self.dossier = self._dossier.name
        self.addCleanup(self._dossier.cleanup)

    def test_le_controleur_exemple_donne_exactement_le_bilan_de_la_reference(self):
        commande = '"%s" "%s"' % (sys.executable, simulate.CONTROLEUR_EXEMPLE)
        par_processus = simuler(scenario(), ControleurProcessus(commande))["bilan"]
        self.assertEqual(par_processus, simuler(scenario(), reference())["bilan"])

    def test_les_print_du_controleur_ne_cassent_pas_l_echange_avec_l_aide_fournie(self):
        commande = ecrire_controleur(self.dossier, """
            import sys
            sys.path.insert(0, %r)
            from protocole import lancer

            def decider(etat):
                print("debug : je réfléchis")
                return {"marche": True, "consigne": 25}

            lancer(decider)
        """ % str(simulate.CONTROLEUR_EXEMPLE.parent))
        bilan = simuler(scenario(), ControleurProcessus(commande), jusqu=3)["bilan"]
        self.assertEqual(bilan["erreurs_controleur"], 0)

    def test_un_print_de_debug_sur_la_sortie_standard_est_signale_sans_decaler_les_commandes(self):
        commande = ecrire_controleur(self.dossier, """
            import json, sys
            for ligne in sys.stdin:
                message = json.loads(ligne)
                if message["type"] == "fin":
                    break
                print("debug : je reçois", message["type"])
                reponse = {"pret": True}
                if message["type"] == "pas":
                    reponse = {"marche": True, "consigne": 20 + message["minute"]}
                print(json.dumps(reponse), flush=True)
        """)
        resultat = simuler(scenario(), ControleurProcessus(commande), jusqu=6)
        self.assertEqual([l["consigne_demandee"] for l in resultat["lignes"]], [20, 21, 22, 23, 24, 25])
        self.assertIn("ligne ignorée", resultat["lignes"][0]["erreur"])
        self.assertIn("debug : je reçois", resultat["lignes"][0]["erreur"])
        self.assertEqual(resultat["bilan"]["erreurs_controleur"], 6)

    def test_un_controleur_trop_lent_garde_sa_derniere_commande_sans_decaler_la_suite(self):
        commande = ecrire_controleur(self.dossier, """
            import json, sys, time
            for ligne in sys.stdin:
                message = json.loads(ligne)
                if message["type"] == "fin":
                    break
                reponse = {}
                if message["type"] == "pas":
                    if message["minute"] == 3:
                        time.sleep(1.5)
                    reponse = {"marche": True, "consigne": 20 + message["minute"]}
                print(json.dumps(reponse), flush=True)
        """)
        resultat = simuler(scenario(), ControleurProcessus(commande, delai_pas=1.0), jusqu=8)
        consignes = [l["consigne_demandee"] for l in resultat["lignes"]]
        self.assertEqual(consignes, [20, 21, 22, 22, 24, 25, 26, 27])
        self.assertIn("délai dépassé", resultat["lignes"][3]["erreur"])
        self.assertEqual(resultat["bilan"]["delais_depasses"], 1)

    def test_un_controleur_qui_plante_arrete_la_simulation_avec_un_message_clair(self):
        commande = ecrire_controleur(self.dossier, """
            import json, sys
            for ligne in sys.stdin:
                if json.loads(ligne).get("minute") == 5:
                    sys.exit(3)
                print("{}", flush=True)
        """)
        with self.assertRaises(simulate.ControleurArrete) as contexte:
            simuler(scenario(), ControleurProcessus(commande), jusqu=20)
        self.assertIn("s'est arrêté", str(contexte.exception))
        self.assertIn('"minute": 5', str(contexte.exception))

    def test_une_commande_introuvable_est_signalee_clairement(self):
        with self.assertRaises(simulate.ControleurArrete) as contexte:
            ControleurProcessus("programme_qui_n_existe_pas_du_tout")
        self.assertIn("impossible de lancer", str(contexte.exception))


class LigneDeCommande(unittest.TestCase):
    def setUp(self):
        self._dossier = tempfile.TemporaryDirectory()
        self.sortie = Path(self._dossier.name) / "resultats"
        self.addCleanup(self._dossier.cleanup)

    def lancer(self, *arguments):
        return subprocess.run(
            [sys.executable, SIMULATE, "--sortie", str(self.sortie)] + list(arguments),
            capture_output=True, encoding="utf-8", timeout=120)

    def test_sans_argument_la_journee_type_tourne_et_ecrit_ses_resultats(self):
        execution = self.lancer()
        self.assertEqual(execution.returncode, 0, execution.stderr)
        self.assertIn("kWh consommés", execution.stdout)
        self.assertIn("gain 0.0 %", execution.stdout)
        bilan = json.loads((self.sortie / "journee_type" / "bilan.json").read_text(encoding="utf-8"))
        self.assertEqual(bilan["simulateur"], simulate.VERSION)
        self.assertEqual(bilan["reference"]["kwh"], bilan["kwh"])
        with open(self.sortie / "journee_type" / "journee.csv", newline="", encoding="utf-8") as fichier:
            lignes = list(csv.DictReader(fichier))
        self.assertEqual(len(lignes), 1440)
        self.assertIn("t_reelle", lignes[0])

    def test_le_fichier_ecrit_pendant_la_simulation_ne_contient_pas_la_verite(self):
        self.lancer("--jusqu", "09:00")
        with open(self.sortie / "journee_type" / "direct.csv", newline="", encoding="utf-8") as fichier:
            lignes = list(csv.DictReader(fichier))
        self.assertEqual(len(lignes), 9 * 60)
        for colonne in simulate.COLONNES_VERITE:
            self.assertNotIn(colonne, lignes[0])

    def test_verifier_confirme_que_le_simulateur_se_comporte_comme_annonce(self):
        execution = self.lancer("--verifier")
        self.assertEqual(execution.returncode, 0, execution.stdout + execution.stderr)
        self.assertNotIn("✘", execution.stdout)

    def test_un_run_qui_echoue_ne_laisse_pas_l_ancien_bilan_en_place(self):
        self.assertEqual(self.lancer("--jusqu", "01:00").returncode, 0)
        bilan = self.sortie / "journee_type" / "bilan.json"
        self.assertTrue(bilan.is_file())
        commande = ecrire_controleur(self._dossier.name, "raise SystemExit(1)")
        self.assertEqual(self.lancer("--controleur", commande).returncode, 2)
        self.assertFalse(bilan.exists())
        self.assertFalse((self.sortie / "journee_type" / "journee.csv").exists())

    def test_un_scenario_invalide_ou_un_controleur_absent_donne_une_erreur_claire(self):
        execution = self.lancer("--scenario", "inexistant")
        self.assertEqual(execution.returncode, 2)
        self.assertIn("scénario introuvable", execution.stderr)
        execution = self.lancer("--controleur", "programme_qui_n_existe_pas_du_tout")
        self.assertEqual(execution.returncode, 2)
        self.assertIn("impossible de lancer", execution.stderr)

    def test_dire_une_phrase_sans_demo_en_cours_est_refuse(self):
        execution = self.lancer("--dire", "lea: j'ai chaud")
        self.assertEqual(execution.returncode, 2)
        self.assertIn("aucune démo en cours", execution.stderr)

    def test_une_phrase_dite_en_direct_arrive_au_controleur_pendant_la_demo(self):
        recus = Path(self._dossier.name) / "recus.txt"
        commande = ecrire_controleur(self._dossier.name, """
            import json, sys
            for ligne in sys.stdin:
                message = json.loads(ligne)
                if message["type"] == "fin":
                    break
                for m in message.get("messages", []):
                    if m["source"] == "direct":
                        open(%r, "a", encoding="utf-8").write(m["occupant"] + "|" + m["texte"] + "\\n")
                print("{}", flush=True)
        """ % str(recus))
        demo = subprocess.Popen(
            [sys.executable, SIMULATE, "--sortie", str(self.sortie), "--live", "--vitesse", "0.02",
             "--depuis", "00:00", "--jusqu", "06:00", "--controleur", commande],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, encoding="utf-8")
        self.addCleanup(demo.kill)
        self.assertEqual(demo.stdout.readline().split()[0], "00:00", "la démo doit avoir démarré")
        self.assertEqual(self.lancer("--dire", "client: mets 10 degrés").returncode, 0)
        self.assertEqual(self.lancer("--dire", "il fait bon ici").returncode, 0)
        demo.communicate(timeout=60)
        self.assertEqual(demo.returncode, 0)
        self.assertEqual(self.lancer("--dire", "trop tard").returncode, 2, "la démo est terminée")
        self.assertEqual(recus.read_text(encoding="utf-8").splitlines(),
                         ["client|mets 10 degrés", "client|il fait bon ici"])


if __name__ == "__main__":
    unittest.main()
