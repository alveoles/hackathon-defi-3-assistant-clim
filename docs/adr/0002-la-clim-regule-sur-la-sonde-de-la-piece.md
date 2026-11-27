# La clim régule sur la sonde de la pièce, pas sur la température réelle

La clim simulée ajuste sa puissance d'après la sonde de la pièce, celle que voit aussi le contrôleur, pannes comprises. Si elle régulait sur la température réelle, une équipe qui envoie « consigne 25 » ne serait jamais gênée par une sonde qui ment, et la user story « repérer un capteur incohérent » ne coûterait rien à personne. C'est aussi le montage courant en tertiaire (sonde déportée).

## Conséquences

- Une panne de sonde pénalise tout le monde, y compris la référence à 18 °C. Le contrôleur la compense en décalant sa consigne.
- La sonde de reprise de la clim est fournie au contrôleur comme deuxième avis. Sans elle, une dérive lente serait indétectable.
- Quand la sonde de la pièce ne renvoie plus rien, la clim se rabat sur sa sonde de reprise.
- Le bilan reste calculé sur la température réelle et la présence réelle.
