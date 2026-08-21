# TopScorers Dashboard

Dashboard TopScorers déployé sur k3s avec Helm, Traefik et Argo CD.

## Publication sans ouvrir de port sur la box

L'ancienne publication utilisait une redirection NAT `50080 -> 80`. La configuration
actuelle utilise un Ingress Traefik sans nom d'hôte imposé afin de pouvoir être publié
avec [Tailscale Funnel](https://tailscale.com/docs/features/tailscale-funnel).

Le routage est le suivant :

- `/api/*` vers le service backend ;
- toutes les autres routes vers le frontend.

### Installation sur le NUC

Installer Tailscale, puis connecter le NUC au compte Tailscale :

```bash
curl -fsSL https://tailscale.com/install.sh | sh
sudo tailscale up
```

Vérifier que Traefik répond localement :

```bash
curl -I http://127.0.0.1/
```

Publier ensuite le port HTTP local de Traefik :

```bash
sudo tailscale funnel --bg 80
tailscale funnel status
```

La première activation ouvre une page Tailscale afin d'autoriser Funnel. La commande
affiche ensuite une URL publique HTTPS stable de la forme
`https://nom-du-nuc.nom-du-tailnet.ts.net`. Aucun port entrant et aucun nom de domaine
personnel ne sont nécessaires.

Pour arrêter la publication :

```bash
sudo tailscale funnel reset
```

## Vérification Kubernetes

```bash
kubectl -n topscorers get pods,svc,ingress
kubectl -n topscorers describe ingress
curl -I http://127.0.0.1/api/dashboard
```
