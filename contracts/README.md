# Contrats hub-agent PitLane

Ce dossier contient la copie agent des contrats versionnés dont la source canonique est le dossier `contracts/` du hub `pitlane`.

- Une modification incompatible crée une nouvelle version de fichier.
- Le hub compatible est déployé avant l'agent émetteur.
- Les exemples ne contiennent ni secret ni donnée personnelle.
- Les fichiers portant le même nom doivent rester strictement identiques entre les deux dépôts.

`result-artifact-available.v1` définit uniquement la notification légère. Le fichier brut sera transféré séparément par HTTP authentifié et idempotent.
