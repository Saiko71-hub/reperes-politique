# Repères

Application pour apprendre la politique française en jouant : quiz du jour, lexique, hémicycle, impôts, institutions.

**En ligne :** https://saiko71-hub.github.io/reperes-politique/

## Données mises à jour automatiquement

Chaque nuit, GitHub Actions lance `update.py`, qui récupère des données officielles brutes et les enregistre dans `data.json` :

| Donnée | Source |
|---|---|
| Composition des groupes de l'Assemblée | Assemblée nationale, open data (députés en exercice) |
| Inflation (IPCH), chômage (BIT), croissance, solde public, dette, coefficient de Gini | Eurostat |
| Taux directeurs | Banque centrale européenne |
| Actualités et textes de loi | vie-publique.fr (DILA, service du Premier ministre) |

Si une source ne répond pas, la valeur précédente est conservée et un avertissement apparaît dans le journal de l'action.

Les questions de la catégorie « Actu chiffrée » sont générées à partir de ces données, sans IA.

## Lancer la mise à jour à la main

Onglet **Actions** → « Mise à jour et publication » → **Run workflow**.

## Note

GitHub peut suspendre les tâches planifiées d'un dépôt resté inactif 60 jours. Si les données ne bougent plus, relance l'action à la main ou réactive-la dans l'onglet Actions.
