# IA en local : quelle machine, quels modèles ?

> Mémo Code Runners · 5 minutes de lecture. Choisis ton modèle **avant** d'installer, et télécharge-le **avant** le jour J : le Wi-Fi est partagé par 50 personnes.

## 1. Identifie ta machine (30 s)

| OS | Commande | Ce que tu cherches |
|---|---|---|
| macOS | `system_profiler SPHardwareDataType \| grep -E "Chip\|Memory"` | puce (M1, M2…) et mémoire |
| Linux | `free -h` puis `nvidia-smi --query-gpu=name,memory.total --format=csv` | RAM, et VRAM si GPU NVIDIA |
| Windows | `nvidia-smi` (PowerShell) ; RAM dans *Gestionnaire des tâches › Performances* | VRAM, RAM |

Le chiffre qui compte, c'est **ta mémoire utilisable par le GPU** :

- **Mac Apple Silicon** : la mémoire est unifiée. Compte environ **70 % de la RAM** pour les modèles.
- **PC avec GPU NVIDIA** : c'est la **VRAM** qui compte. Si le modèle déborde sur la RAM, il tourne, mais 5 à 10 fois plus lentement.
- **PC sans GPU dédié** : seul le processeur travaille. Ça marche pour les petits modèles, lentement.

## 2. La règle de calcul

```
mémoire ≈ milliards de paramètres × 0,6 Go   (quantifié en 4 bits, format par défaut d'Ollama)
        + 1 à 2 Go de marge (contexte)
```

Exemple : un modèle 7B demande environ 7 × 0,6 + 1,5 ≈ **6 Go**.

## 3. Ta catégorie

| Ta machine | LLM texte | LLM vision (lit une image) | Génération d'images |
|---|---|---|---|
| **8 Go** (Mac 8 Go, PC sans GPU) | 1 à 4B : `qwen2.5:3b`, `llama3.2:3b`, `gemma3:4b` | `qwen2.5vl:3b` | à éviter |
| **16 Go Mac** / **GPU 6-8 Go** | 7-8B : `qwen2.5:7b`, `llama3.1:8b` | `qwen2.5vl:7b` ✅ | SD 1.5 + LCM ✅ (≈ 8 s par image) |
| **24-32 Go Mac** / **GPU 12-16 Go** | 12-14B : `gemma3:12b`, `qwen2.5:14b` | `gemma3:12b` | SDXL |
| **64 Go+ Mac** / **GPU 24 Go** | 27-32B : `gemma3:27b`, `qwen2.5:32b` | `qwen2.5vl:32b` | SDXL, Flux |

✅ = testé sur un MacBook M1 Pro 16 Go, la machine de référence du hackathon. SDXL n'y était **pas** viable.

> Plus gros ne veut pas dire meilleur pour ton défi. Un 7B qui répond en 2 secondes vaut mieux qu'un 14B qui en met 30 pendant la démo.

## 4. Installe et vérifie

```bash
# Installer Ollama : https://ollama.com/download  (macOS : brew install ollama)
ollama pull qwen2.5:7b        # à faire AVANT le jour J
ollama run qwen2.5:7b "Bonjour"
ollama ps                     # la colonne PROCESSOR doit afficher « 100% GPU »
```

`ollama ps` affiche un partage du genre `40%/60% CPU/GPU` ? Le modèle ne tient pas dans ta mémoire. **Descends d'une taille.**

## 5. Les pièges

- **Un modèle à la fois.** Sur 16 Go, enchaîne les modèles, ne les empile pas. `ollama stop <modèle>` libère la mémoire.
- Un contexte long consomme de la mémoire. Ne monte pas `num_ctx` sans en avoir besoin.
- Ferme Chrome et Docker : sur une machine de 8 à 16 Go, ils mangent plusieurs Go.

## Par défi

| Défi | Ce dont tu as vraiment besoin |
|---|---|
| 01 Sketch2CNC | un LLM vision pour lire les cotes, plus un modèle d'image (voir `INSTALL.md`) |
| 02 Biodiversité | souvent **pas de LLM du tout** : un modèle d'embeddings d'images (CLIP, SigLIP, < 1 Go) tourne sur toutes les machines |
| 03 Assistant clim | un LLM texte de 3 à 8B qui sait appeler des outils (tool calling), par exemple `qwen2.5`, `llama3.1` |
