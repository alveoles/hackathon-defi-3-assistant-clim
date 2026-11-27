# Comprendre le simulateur

Ce document explique **comment se comporte la pièce simulée** et **pourquoi ton contrôleur obtient tel bilan**. Pas besoin d'être thermicien : si tu sais lire une courbe, tu sais lire ce document.

Le format des messages échangés avec le simulateur est décrit dans `CONTRAT.md`. Ici, on parle de physique, de capteurs et d'arbitrages.

> ℹ️ Les valeurs données ici sont des **ordres de grandeur** pour une journée type. En cas d'écart, c'est le code de `simulate.py` qui fait foi.

---

## 1. Le principe en 30 secondes

Chaque minute, de 00:00 à 23:59, le simulateur :

1. fait évoluer la **température réelle** de la pièce (soleil, occupants, météo, clim) ;
2. envoie à ton contrôleur ce qu'il **peut voir** : les sondes, les occupants détectés, les messages ;
3. attend sa commande (marche, consigne, ventilation) et la transmet à la clim ;
4. compte l'énergie consommée et l'inconfort.

Ton contrôleur ne voit **jamais** la température réelle ni la présence réelle. Il voit des sondes, comme dans un vrai bâtiment. Le bilan, lui, est calculé sur la réalité.

---

## 2. La pièce : deux réservoirs de chaleur

Un bureau partagé d'environ 30 m², en béton, avec une baie vitrée. La pièce stocke la chaleur à deux endroits :

```
            soleil, occupants, ordinateurs, éclairage
                              │
                              ▼
  extérieur  ◄──────►   AIR de la pièce   ◄──────►   MURS + DALLE + MOBILIER
  (fuites, air neuf)    réagit en ~20 min             réagissent en ~10 h
                              ▲
                              │
                         clim (retire la chaleur de l'air)
```

| Réservoir | Analogie dev | Ce que ça implique |
|---|---|---|
| **L'air** | Un cache : petit, rapide | Quand la clim démarre, l'air se refroidit en quelques minutes. Quand elle s'arrête, il remonte aussi vite. |
| **Les murs et la dalle** | Un disque : gros, lent | Ils absorbent la chaleur de la journée et la restituent la nuit et le matin. Une pièce restée chaude la veille met des heures à vraiment refroidir. |

**Conséquence clé** : refroidir l'air ne suffit pas. Si les murs sont chauds, ils réchauffent l'air dès que la clim s'arrête. C'est pour ça que **le moment où tu refroidis compte autant que la consigne**.

Avant la journée simulée, le simulateur joue trois journées ordinaires : à minuit, les murs ont déjà une température réaliste, la même pour toutes les équipes.

---

## 3. Ce qui chauffe la pièce

| Source | Ordre de grandeur | Quand |
|---|---|---|
| Un occupant | ~100 W | Présence réelle |
| Un poste informatique | ~80 W | Quand son occupant est là |
| Éclairage | ~240 W | Dès qu'il y a quelqu'un |
| Soleil sur la baie vitrée | jusqu'à ~0,8 kW | Le matin si la façade est à l'est, l'après-midi si elle est à l'ouest. Moins quand c'est nuageux |
| Chaleur extérieure | dépend de l'écart intérieur / extérieur | Tout le temps : fuites, vitrage, air neuf (plus il y a d'occupants, plus il y a d'air neuf) |
| Fenêtre ouverte | les fuites sont multipliées par ~3,5 | Pendant l'événement `fenetre_ouverte` |

**Repère** : six occupants, le soleil et la chaleur de l'après-midi, c'est environ **3 kW de chaleur** à évacuer, avec des pointes à 3,5 kW. La clim en fournit 3,5 à 3,7 kW au maximum. Il reste donc **très peu de marge**, et plus aucune en canicule ou avec des visiteurs.

En décembre à Saint-Pierre, il fait environ 23 °C dehors à l'aube et 31 °C vers 15h. **Sans clim**, la pièce monte autour de **32 °C en fin d'après-midi** (35 °C en canicule).

---

## 4. La clim : tu donnes une consigne, pas une puissance

La clim est un split inverter de **3,5 kW froid**, comme dans la plupart des bureaux. Elle a **sa propre régulation** :

| Comportement | Ce que ça veut dire pour toi |
|---|---|
| **Tu envoies une consigne**, elle ajuste seule sa puissance | Tu ne pilotes pas « 2 kW », tu demandes « 25 °C ». Plus la pièce est loin de la consigne, plus elle pousse. |
| **La pièce se stabilise un peu au-dessus de la consigne** | Environ +0,2 °C à faible charge, jusqu'à **+0,5 °C quand la clim travaille fort**. Une consigne à 25,5 °C donne 26,0 à 26,2 °C l'après-midi : hors de la plage de confort. |
| **Elle régule sur la sonde de la pièce** | Si la sonde ment, la clim se trompe aussi. Une sonde figée à 22 °C, et la clim croit que tout va bien pendant que la pièce chauffe. Elle lisse ses lectures sur trois minutes : une valeur aberrante isolée ne la trompe pas, une panne qui dure, si. |
| **Sans sonde de pièce, elle se rabat sur sa sonde de reprise** | Quand `t_piece` vaut `null`, la clim régule sur `t_reprise`, qui lit plus chaud : elle refroidit un peu trop. |
| **Puissance entre 30 % et 100 %** | Sous 30 % de besoin, elle ne peut pas moduler plus bas : son compresseur s'arrête et repart de lui-même, autour de la consigne (±0,3 °C). |
| **Anti-court-cycle : 3 minutes** | Après un arrêt, le compresseur ne redémarre pas avant 3 minutes. Ta commande n'est pas refusée, elle est **retardée**. Le retour d'état indique `compresseur_bloque`. |
| **Consigne entre 16 et 30 °C**, par pas de 0,5 °C | Une consigne de 24,3 °C est arrondie à 24,5 °C. Une demande hors bornes est ramenée à la borne. Mais les **limites client** sont plus étroites : c'est à toi de refuser ce qui en sort. |
| **Le rendement baisse quand il fait chaud dehors** | Pour 1 kWh d'électricité, la clim retire environ 4,6 kWh de chaleur à 25 °C dehors, mais seulement environ 3,4 kWh à 35 °C. Le même froid coûte donc environ 20 % de moins à l'aube qu'à 15h. Mais les murs n'en gardent qu'un tiers jusqu'à l'après-midi : **refroidir trop tôt se paie.** |
| **Veille et ventilateur** | 5 W en veille. En marche, le ventilateur consomme 15 W (`faible`), 30 W (`auto`) ou 50 W (`fort`). Une clim allumée pour rien n'est jamais gratuite. |
| **Trois vitesses de ventilation** | `faible` plafonne le froid à 60 % de la puissance. `fort` donne 10 % de froid en plus : c'est la réserve quand la clim sature. |
| **Elle déshumidifie** | Quand elle tourne, l'humidité de la pièce baisse. Utile pour la story bonus sur l'humidité. |

À chaque minute, le simulateur te renvoie l'**état réel de la clim** : marche effective, puissance électrique consommée, consigne appliquée, compresseur bloqué ou non. Vérifie que tes ordres produisent bien l'effet attendu.

---

## 5. Ce que tu vois, et ce qu'on te cache

| Tu reçois | Ce que c'est | Ce qui peut clocher |
|---|---|---|
| `t_piece` | La **sonde de la pièce**, sur laquelle régule la clim | Bruit de ±0,2 °C en permanence. Peut dériver, se figer, décrocher (`null`), afficher un pic aberrant ou prendre le soleil. |
| `t_reprise` | La **sonde de reprise**, dans la clim au plafond | Elle lit en général 0,5 à 1 °C de plus que la pièce. C'est ton deuxième avis pour recouper `t_piece`. |
| `t_ext` | La température extérieure mesurée | Fiable. |
| `occupants_detectes` | Ce que voit le détecteur de présence | Il rate les gens **immobiles** (concentrés, en réunion assise). |
| `messages` | Les phrases des occupants à cette minute | Voir la section 6. |
| `prevision_meteo` (au démarrage) | La météo annoncée heure par heure | Elle se trompe de 0 à 1,5 °C, dans le même sens toute la journée. Parfois beaucoup plus : un orage non prévu. |
| `planning` (au démarrage) | Les réservations prévues de la pièce | La réalité peut différer : absents, réunion imprévue, arrivée anticipée. |

**Ce qu'on ne te donne jamais** : la température réelle et la présence réelle. Pendant la simulation, le CSV ne contient que ce que voit ton contrôleur. Les colonnes de vérité sont écrites **à la fin** du run, pour ton tableau de bord.

### Reconnaître une panne de sonde

Les pannes ne sont pas des bugs du simulateur. Ce sont des **événements volontaires**, écrits dans le scénario (`evenements`), comme une réunion imprévue ou une fenêtre ouverte. Elles reproduisent ce qui arrive aux vraies sondes. Un même scénario déclenche toujours les mêmes pannes aux mêmes minutes, mais **ton contrôleur n'en est pas prévenu** : à lui de les repérer. Seul le bruit de ±0,2 °C est permanent.

| Panne | À quoi elle ressemble | Indice pour la repérer |
|---|---|---|
| **Dérive** | `t_piece` s'écarte lentement de la réalité, jusqu'à ~2 °C en quelques heures | L'écart avec `t_reprise` change alors qu'il était stable |
| **Valeur figée** | Exactement la même valeur pendant longtemps | Une vraie sonde bruitée ne reste jamais identique au dixième près |
| **Décrochage** | `t_piece` vaut `null` | Évident, encore faut-il le gérer sans planter |
| **Pic aberrant** | 85 °C ou -40 °C pendant une minute ou deux | Physiquement impossible : l'air ne bouge pas de 50 °C en une minute |
| **Sonde au soleil** | +3 à +5 °C quand le soleil arrive sur la façade | Le saut coïncide avec l'heure d'ensoleillement, et `t_reprise` ne suit pas |
| **Détecteur aveugle** | 0 occupant détecté alors que la pièce est pleine | Des messages arrivent d'une pièce « vide » |

> ℹ️ La référence, toujours à fond, ne remarque même pas une panne de sonde. Un contrôleur fin y est bien plus exposé : c'est là qu'il faut recouper les deux sondes, puis corriger la consigne pour compenser.

---

## 6. Les occupants

Chaque occupant a une **température préférée** (autour de 24,5 °C, à ±1,5 °C selon la personne) et une **tolérance**. Deux collègues n'ont donc pas toujours le même avis sur la même pièce.

Les messages viennent de deux sources, indiquées dans le champ `source` :

| Source | Ce que c'est |
|---|---|
| `script` | Une phrase écrite dans le scénario, qui arrive toujours à la même minute : « on part en réunion jusqu'à 15h », « mets 10 °C »… |
| `direct` | Une phrase ajoutée pendant une démo avec `--dire`. |
| `auto` | Une **plainte automatique** : un occupant est resté 15 minutes de suite hors de sa température préférée, et il le dit. Au maximum une plainte par occupant toutes les 30 minutes. Les formulations varient. |

**Conséquence** : un contrôleur qui gère mal la pièce reçoit **plus de plaintes**. Deux versions de ton contrôleur ne reçoivent donc pas forcément les mêmes messages sur le même scénario. Le simulateur reste déterministe : même scénario et même contrôleur donnent toujours la même journée.

> ℹ️ Le client peut aussi parler pendant la démo, sous un nom que tu n'as jamais vu. Ton contrôleur doit l'accepter.

---

## 7. Une journée type, en chiffres

Scénario `journee_type` : six occupants de 8h à 12h puis de 13h30 à 17h30, façade ouest, beau temps. Ordres de grandeur :

| Heure | Dehors | Sans clim | Référence (18 °C de 7h à 19h) | Consigne 25 °C de 7h à 18h |
|---|---|---|---|---|
| 05h | 23,5 °C | 25 °C | 25 °C (clim arrêtée) | 25 °C (clim arrêtée) |
| 08h | 26 °C | 25,5 °C | 19 °C (clim à fond) | 25 °C |
| 12h | 30 °C | 29,5 °C | 21,5 °C (clim à fond) | 25,5 °C |
| 15h | 31 °C | 31,5 °C | 22 °C (clim à fond) | 25,5 °C |
| 17h | 30,5 °C | 32,5 °C | 22,5 °C (clim à fond) | 25,5 °C |

| Bilan | Référence à 18 °C | Consigne 25 °C |
|---|---|---|
| Énergie | ~11,5 kWh | ~5,8 kWh, soit environ la moitié |
| Minutes d'inconfort | 480 : **trop froid** toute la journée | 0 |

**Ce qu'il faut retenir** :
- **La référence est saturée** : la clim tourne à 100 % de 7h à 19h sans jamais atteindre 18 °C. Elle consomme le maximum et fait grelotter les occupants toute la journée.
- **Une simple consigne raisonnable fait déjà mieux sur les deux tableaux.** Le palier 1 se gagne là, et c'est normal.
- **Le matin, la pièce est déjà fraîche** (25 °C à 8h sans clim) : sur une journée ordinaire, refroidir avant l'arrivée ne sert à rien. Ce n'est plus vrai en canicule, ni au retour de la pause de midi.
- **Les points se jouent ensuite** sur les journées difficiles : canicule, pannes de sonde, présence imprévue, conflits entre collègues. C'est là que la détection, l'anticipation et le dialogue font la différence.

---

## 8. Lire le bilan

| Indicateur | Définition | Ce qu'il te dit |
|---|---|---|
| **kWh** | Électricité consommée sur 24 h, veille comprise | Ce que paie Alvéoles |
| **Minutes d'inconfort** | Minutes où au moins un occupant est réellement présent et où la température réelle est hors de [23 ; 26] °C | Le chiffre principal de confort. Le bilan sépare « trop chaud » et « trop froid ». |
| **Minutes-personne d'inconfort** | Pour chaque minute d'inconfort, on compte le nombre d'occupants présents, puis on additionne. Exemple : 10 minutes à 27 °C avec 3 occupants = 30 minutes-personne | Une pièce pleine trop chaude pèse plus qu'une pièce avec une seule personne |
| **Degrés-heures** | Somme des écarts hors de [23 ; 26] °C | Distingue 26,2 °C (léger) de 31 °C (étouffant). Laisser filer une pièce « déjà perdue » se voit ici. |
| **Plaintes** | Nombre de plaintes automatiques | Le ressenti des occupants |
| **Démarrages du compresseur** | Nombre de mises en marche | Trop de démarrages usent le matériel : signe d'une régulation qui fait du yo-yo |
| **Changements de consigne** | Nombre de fois où la consigne appliquée a changé | Une vraie clim n'aime pas recevoir un ordre par minute |
| **Minutes hors limites client** | Minutes où la consigne appliquée sort des limites d'Alvéoles | Ton contrôleur a-t-il vraiment refusé « mets 10 °C » ? |
| **Plaintes sans effet** | Plaintes automatiques restées sans réponse de l'assistant **et** sans action dans le bon sens sous 15 minutes (baisser la consigne ou allumer pour « j'ai chaud », l'inverse pour « j'ai froid ») | L'assistant écoute-t-il vraiment ? Expliquer pourquoi on ne change rien compte comme un effet |
| **Messages sans réponse** | Messages auxquels l'assistant n'a jamais répondu (champ `reponses`, texte non vide) | L'assistant répond-il à ceux qui lui parlent ? La qualité des réponses, elle, se juge à la démo |
| **Erreurs du contrôleur** | Réponses invalides et délais dépassés | Ton contrôleur respecte-t-il le contrat ? |
| **Gain face à la référence** | Écart en % sur les kWh | La promesse du sujet |

Le bilan contient aussi la version et l'empreinte du simulateur, la graine et l'empreinte du scénario : deux bilans ne se comparent que s'ils portent sur la même journée, jouée par le même simulateur.

### Comment le jury classe

1. **Budget de confort** : au plus **7,5 minutes d'inconfort par occupant prévu au planning**, soit **45 minutes-personne pour 6 occupants** (60 pour 8, 15 pour 2). Par exemple, 45 minutes trop chaudes pour une seule personne, ou 7 minutes trop chaudes pour 6 personnes. Au-delà, le confort est jugé insuffisant. Le bilan affiche ce budget et s'il est respecté.
2. Parmi les équipes qui respectent ce budget, **la plus économe en kWh gagne**.
3. Une équipe qui dépasse le budget est classée après toutes celles qui le respectent. Entre équipes hors budget, celle qui a le moins de minutes-personne d'inconfort passe devant.
4. Les minutes hors limites client et les plaintes sans effet servent à **départager**.

Le scénario du jury est secret et rejoué par l'organisateur sur ton tag `v1.0-rendu`. Il reste dans ces plages : façade est ou ouest, 2 à 8 occupants, 22 à 34 °C dehors, au moins une panne. Les chiffres affichés pendant la démo live ne comptent pas pour le classement.

---

## 9. Les arbitrages au cœur du défi

| Tension | D'un côté | De l'autre |
|---|---|---|
| **Confort ou énergie** | Une consigne basse rassure tout le monde | Chaque degré de moins coûte cher, surtout l'après-midi |
| **Réagir ou anticiper** | Attendre que la pièce chauffe est simple, et ne gaspille rien | Démarrer juste à temps (avant l'arrivée, avant le retour de pause) évite l'inconfort. Prendre de l'avance les jours où la clim va saturer sauve l'après-midi. Mais trop tôt, le froid se perd dans les murs, et la prévision peut se tromper |
| **Croire la sonde ou s'en méfier** | La sonde est ta seule vue de la pièce | Une sonde qui ment fait mal climatiser, même la meilleure stratégie |
| **Couper la pièce vide ou la garder** | Couper économise | Le détecteur rate les gens immobiles, et une pièce coupée met 10 à 15 minutes à revenir |
| **Écouter ou protéger** | L'occupant sait ce qu'il ressent | Il ne voit ni la facture, ni les autres occupants, ni les limites du matériel |

### Symptômes fréquents

| Tu observes | Cause probable |
|---|---|
| La clim s'allume et s'éteint toutes les minutes | Pas d'hystérésis, ou une consigne qui change à chaque pas |
| La pièce reste 0,5 °C au-dessus de ta consigne | C'est normal sous forte charge : vise un peu plus bas |
| Tes commandes semblent arriver en retard, ou la colonne `erreur` se remplit | Un `print()` de debug part sur la sortie standard (voir `CONTRAT.md`) |
| `compresseur_bloque` souvent à `true` | Ton contrôleur coupe et relance trop vite |
| La pièce chauffe alors que la clim est en marche à 100 % | Elle est saturée : trop de monde, trop de soleil. Il fallait anticiper. |
| Inconfort à 8h alors que tout va bien ensuite | La pièce n'était pas prête à l'arrivée |
| Inconfort « trop froid » | Consigne trop basse, ou clim qui continue de tourner sur une sonde au soleil |
| Clim coupée pendant une réunion | Détecteur aveugle pris pour une pièce vide |
| kWh très bas mais beaucoup d'inconfort | La clim est coupée trop souvent : le budget de confort est dépassé |

---

## 10. Ce que le simulateur ne modélise pas

Un modèle reste un modèle. Le simulateur ne gère pas : plusieurs zones ou plusieurs clims, la sensation thermique fine (vitesse de l'air, vêtements), le givrage, les pannes de la clim elle-même, ni le prix variable de l'électricité.

> ℹ️ Si tu penses qu'un comportement est faux physiquement, viens en parler. Si c'est un bug, il sera corrigé pour tout le monde en même temps, avec une nouvelle version annoncée.
