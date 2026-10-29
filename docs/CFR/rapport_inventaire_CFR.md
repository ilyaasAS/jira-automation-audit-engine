# Inventaire des automations Jira — space CFR

21 octobre 2026 · Ilyaas ABDOUL AZIS

## En bref

Le space CFR ne contient qu'une seule automatisation, Auto-assign. Elle fonctionne et sert vraiment : 22 tickets créés, 22 exécutions, 0 erreur. Il n'y a rien à corriger sur ce space.

## Ce qui a été fait

Le space CFR a été analysé avec le même outil d'inventaire que CFIT, sans rien modifier dans Jira. Aucune automatisation n'a été créée ou changée : l'outil fait l'état des lieux de ce qui existe.

1. Ajout du space CFR (identifiant 10099) dans la configuration de l'outil.
2. Lancement de l'inventaire : `python main.py --project CFR`, en moins d'une minute.
3. Vérification des chiffres en comptant directement les tickets CFR.

L'outil est en lecture seule : le code bloque toute création, modification ou suppression. Il utilise mes droits d'admin du space, sans compte admin Jira global.

## La règle Auto-assign

Dès qu'un ticket est créé dans CFR, la règle l'assigne automatiquement à Julien Cabanès.

| Élément | Valeur |
| --- | --- |
| Nom | Auto-assign |
| État | Activée |
| Déclencheur | Un ticket est créé dans CFR |
| Action | Assigner le ticket à Julien Cabanès |
| Créée par / propriétaire | Julien Cabanès |
| Créée le | 25/09/2026, jamais modifiée depuis |
| Portée | Space CFR uniquement |
| Verdict | Active (prouvée) |

## Preuves

Les deux sources indépendantes concordent : chaque ticket créé depuis le 25/09 a déclenché la règle une fois.

| Source | Constat |
| --- | --- |
| Journal d'audit Jira | 22 exécutions avec action, 0 erreur, dernière le 20/10/2026 |
| Tickets CFR créés depuis le 25/09 | 22 tickets, dont 21 encore assignés à Julien Cabanès |
| Exemples vérifiables à la main | CFR-494, CFR-503, CFR-507 |

Le 22e ticket a été réassigné à la main à Fred Regoli après le passage de la règle, ce qui est normal. Le journal contient 23 lignes : la ligne en plus correspond à la création de la règle, pas à une exécution.

## Points d'attention et suite

Aucune action n'est nécessaire sur CFR ; deux remarques mineures seulement.

- La règle n'a pas de description. On pourrait en ajouter une pour expliquer son rôle.
- Tous les tickets vont à une seule personne. Si Julien Cabanès est absent, ils lui restent assignés quand même. Une question à lui poser si besoin.

Prochaine étape : le space CFS, avec la même méthode.
