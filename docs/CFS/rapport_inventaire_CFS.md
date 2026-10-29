# Inventaire des automations Jira — space CFS

21 octobre 2026 · Ilyaas ABDOUL AZIS

## En bref

Le space CFS (Cloudi-Fi Support) ne contient aucune automatisation. Il n'y a donc rien à nettoyer. Le space est par ailleurs peu actif : 6 tickets créés en 90 jours, tous sans responsable.

## Ce qui a été fait

Le space CFS a été analysé avec le même outil d'inventaire que CFIT et CFR, sans rien modifier dans Jira. Aucune automatisation n'a été créée ou changée : l'outil fait l'état des lieux de ce qui existe.

1. Ajout du space CFS (identifiant 10034) dans la configuration de l'outil.
2. Lancement de l'inventaire : `python main.py --project CFS`, en moins d'une minute.
3. Vérification que le résultat « 0 règle » est fiable, et pas dû à un problème d'accès.
4. Lecture des tickets CFS récents pour donner le contexte.

L'outil est en lecture seule : le code bloque toute création, modification ou suppression. Il utilise mes droits d'admin du space, sans compte admin Jira global.

## Pourquoi « 0 règle » est fiable

Un résultat vide pourrait venir d'une erreur. Quatre vérifications montrent que ce n'est pas le cas.

| Vérification | Résultat |
| --- | --- |
| Bon space | L'identifiant 10034 correspond bien à CFS « Cloudi-Fi Support » (responsable : Houda Boutahlil) |
| Droits suffisants | J'ai bien les droits d'admin du space CFS |
| Réponse de Jira | La liste des règles du space répond sans erreur, avec un total de 0 |
| Journal d'audit | 0 exécution enregistrée sur les 4 derniers mois |

## Activité du space

| Élément | Valeur |
| --- | --- |
| Tickets créés sur 90 jours | 6 (CFS-917 à CFS-922) |
| Premier / dernier ticket de la période | 01/09/2026 / 18/09/2026 |
| Tickets assignés | 0 sur 6 |
| Statut des tickets | Tous en « Qualification » |
| Dernière mise à jour d'un ticket | 18/09/2026 |

Aucun ticket n'a été créé ni modifié depuis plus d'un mois.

## Points d'attention et suite

Aucune action n'est nécessaire côté automatisations. Une question peut être posée à Houda Boutahlil, responsable du space :

- Les tickets restent sans responsable et en « Qualification ». Une règle d'assignation automatique, comme Auto-assign sur CFR, pourrait aider, si le space est encore utilisé.
- Si le space n'est plus utilisé, il peut être signalé comme tel.

Une limite connue : avec les droits d'admin du space, l'outil voit les règles propres à CFS. Une éventuelle règle globale, gérée par un admin Jira, ne serait pas visible. Le journal d'audit vide indique qu'aucune règle n'a tourné sur CFS ces 4 derniers mois.

Les trois spaces CFIT, CFR et CFS sont maintenant inventoriés.
