# COOL RUNNER : simulation d'un bureau climatisé

Vocabulaire du défi 03 : une pièce de bureau, une climatisation, une journée simulée, et l'assistant que les équipes construisent pour la piloter.

## La pièce et ses occupants

**Pièce** :
Le bureau partagé simulé, unique pour tout le défi. Sa température évolue selon la météo, le soleil, les occupants et la clim.
_À éviter_ : salle, local, zone

**Occupant** :
Une personne qui travaille dans la pièce, identifiée par un nom court, avec une température préférée et une tolérance.
_À éviter_ : employé, utilisateur, collègue

**Présence réelle** :
Les occupants effectivement dans la pièce à une minute donnée. Elle sert au score et le contrôleur ne la voit jamais.
_À éviter_ : occupation

**Occupants détectés** :
Le nombre d'occupants vu par le détecteur de présence. Il peut différer de la présence réelle, par exemple quand quelqu'un reste immobile.

**Planning** :
Les réservations prévues de la pièce, connues dès le début de la journée. La présence réelle peut s'en écarter.
_À éviter_ : agenda, calendrier

## Mesures

**Sonde de la pièce** :
Le capteur de température que voit le contrôleur et sur lequel la clim régule. Elle peut être bruitée, dériver, se figer ou décrocher.
_À éviter_ : capteur (seul), thermomètre

**Sonde de reprise** :
Le capteur interne de la clim, placé au plafond. Il lit un peu plus chaud que la pièce et sert à recouper la sonde de la pièce.

**Température réelle** :
La vraie température de l'air de la pièce, calculée par le simulateur. Elle sert au score et le contrôleur ne la voit jamais.
_À éviter_ : température vraie, température simulée

**Panne de sonde** :
Un écart volontaire entre ce qu'affiche une sonde et la réalité : dérive, valeur figée, valeur absente, pic aberrant, sonde au soleil.

## Climatisation

**Clim** :
Le split inverter de la pièce. Il régule lui-même sa puissance pour atteindre la consigne.
_À éviter_ : climatiseur, split, PAC

**Consigne** :
La température que la clim cherche à atteindre, envoyée par le contrôleur. La clim la borne entre 16 et 30 °C.
_À éviter_ : cible, température demandée

**Limites client** :
La plage de consigne qu'Alvéoles accepte. Elle est plus étroite que les bornes de la clim, et le contrôleur doit refuser ce qui en sort.
_À éviter_ : limites sûres, bornes

**Court-cycle** :
Le redémarrage trop rapide du compresseur. La clim l'empêche en retardant le redémarrage de quelques minutes.

## Assistant

**Contrôleur** :
Le programme de l'équipe. À chaque minute, il reçoit l'état visible de la pièce et renvoie une commande pour la clim.
_À éviter_ : assistant (pour le programme), régulateur, bot

**Assistant** :
Le produit vu par l'occupant : le contrôleur, plus la compréhension des phrases et les réponses.

**Message** :
Une phrase dite par un occupant à une minute donnée. Elle est soit écrite dans le scénario, soit générée comme plainte automatique.
_À éviter_ : commande vocale, requête

**Plainte automatique** :
Un message généré par le simulateur quand un occupant est resté trop longtemps hors de sa température préférée.

**Intention** :
Ce que le LLM extrait d'un message, sous forme structurée (« plus frais », « pièce vide jusqu'à 15h »). Le contrôleur décide ensuite quoi en faire.

**Journal** :
L'explication que le contrôleur donne de chaque décision, enregistrée minute par minute.
_À éviter_ : log, trace

## Journée et évaluation

**Scénario** :
La description complète d'une journée : météo, prévision, planning, présence réelle, occupants, messages et événements.
_À éviter_ : journée type (pour le fichier), test, niveau

**Événement** :
Une perturbation datée dans un scénario : fenêtre ouverte, panne de sonde, réunion imprévue, détecteur aveugle, absence.

**Prévision météo** :
La météo heure par heure annoncée au contrôleur en début de journée, avec une erreur volontaire par rapport à la météo réelle.

**Référence** :
Le thermostat naïf réglé à 18 °C pendant les heures de bureau, rejoué sur le même scénario. C'est la référence à battre.
_À éviter_ : baseline, témoin

**Minute d'inconfort** :
Une minute où au moins un occupant est réellement présent et où la température réelle est hors de [23 ; 26] °C.

**Degrés-heures** :
La somme des écarts de la température réelle hors de [23 ; 26] °C pendant la présence réelle, exprimée en heures. Elle distingue un léger dépassement d'une pièce étouffante.

**Bilan** :
Le résumé chiffré d'une journée simulée : kWh, minutes d'inconfort, degrés-heures, plaintes, comparaison à la référence.
_À éviter_ : score, rapport, résultat

**Scénario du jury** :
Le scénario secret rejoué par l'organisateur sur le tag de rendu de chaque équipe pour le classement.
_À éviter_ : scénario imposé, scénario final
