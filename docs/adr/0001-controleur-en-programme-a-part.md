# Le contrôleur est un programme à part qui échange des lignes JSON

Le simulateur lance le contrôleur de l'équipe comme un sous-processus et lui parle par lignes JSON sur l'entrée et la sortie standard, une ligne par minute simulée. Nous avons écarté le module Python importé (`decider(etat)` appelé directement), plus simple à écrire, pour deux raisons : les équipes choisissent leur langage, et un contrôleur importé partagerait la mémoire du simulateur, donc la température réelle et la suite du scénario.

## Conséquences

- La sortie standard du contrôleur est réservée au protocole : un `print()` de debug casse l'échange. `protocole.py` redirige les `print()` vers la sortie d'erreur pour les équipes en Python.
- Le simulateur attend la réponse avant d'avancer : un appel lent à un modèle de langage ralentit la journée, mais ne change pas son résultat.
- Pendant la simulation, `direct.csv` ne contient que ce que voit le contrôleur. La vérité n'est écrite qu'à la fin, dans `journee.csv`.
