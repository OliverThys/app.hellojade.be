# HelloJADE — VPS OVH (app.hellojadeapp.be)

## Contexte de ce serveur

Ce VPS OVH est le serveur de production **version démo** (non affiliée Epicura).
URL publique : https://app.hellojadeapp.be (Cloudflare Tunnel → nginx:8080)

## Architecture locale

```
/root/hellojade/
├── docker-compose.ovh.yml     ← Stack Docker principale
├── .env                       ← Variables d'environnement (secrets)
├── backend/app/               ← Code FastAPI (injecté via docker cp)
├── temp/tts/cache/            ← Fichiers WAV Azure TTS (partagés avec Asterisk)
├── reports/                   ← Rapports PDF générés
└── ...

/etc/asterisk/                 ← Config Asterisk (natif, pas Docker)
├── pjsip.conf                 ← Trunk OVH SIP (external_media_address = 51.68.224.55)
├── extensions.conf            ← Dialplan AMD → MixMonitor → Stasis
├── ari.conf                   ← ARI user: hellojadeapp / hellojadeari2024
└── http.conf                  ← ARI HTTP sur 0.0.0.0:8088

/var/lib/asterisk/sounds/custom → /root/hellojade/temp/tts  (symlink critique)
/var/spool/asterisk/recording/  ← Enregistrements WAV des appels
```

## Commandes courantes

```bash
# État des services Docker
docker ps

# Logs backend en temps réel
docker logs -f hellojadeapp-backend

# Redéployer le backend (sans rebuild)
docker cp /root/hellojade/backend/app/. hellojadeapp-backend:/app/app/
docker restart hellojadeapp-backend hellojadeapp-celery hellojadeapp-celery-beat

# Asterisk
systemctl status asterisk
asterisk -rx 'pjsip show registrations'
asterisk -rx 'core show channels'
asterisk -rvvv   # console verbose

# Base de données
docker exec hellojadeapp-postgres psql -U hellojade -d hellojade_db

# Logs Asterisk verbose
tail -f /var/log/asterisk/full
```

## Stack technique

| Composant | Détail |
|-----------|--------|
| Backend | FastAPI (Python), container hellojadeapp-backend |
| TTS/STT | Azure Cognitive Services (fr-BE-CharlineNeural, westeurope) |
| LLM | Mistral API (mistral-small-latest) |
| Téléphonie | Asterisk 20.19.0 natif + OVH SIP trunk |
| ARI | WebSocket ws://localhost:8088, app=hellojadeapp |
| Auth | Keycloak 24 (realm epicura, SAML2) |
| DB | PostgreSQL 16 (container hellojadeapp-postgres) |
| Cache | Redis (container hellojadeapp-redis) |
| Proxy | Nginx (container hellojadeapp-nginx, port 8080) |
| Tunnel | Cloudflare hellojadedemo → app.hellojadeapp.be |

## Points critiques à ne pas casser

- **Symlink TTS** : `/var/lib/asterisk/sounds/custom` doit pointer vers `/root/hellojade/temp/tts`
- **iptables** : règles RTP (UDP 16000-16999) et SIP (5060) persistées via iptables-save
- **saml_service.py** : après docker compose --force-recreate, re-injecter (perd validate_schema=False)
- **Asterisk non-dockerisé** : ne jamais tenter de le mettre en Docker (RTP/NAT)
- **HELLOJADE_APP** dans extensions.conf : toujours via variable, jamais hardcodé

## Déploiement backend

```bash
# Mettre à jour un fichier Python sans rebuild
docker cp /root/hellojade/backend/app/. hellojadeapp-backend:/app/app/
docker restart hellojadeapp-backend

# ATTENTION : force-recreate efface les fichiers copiés → re-injecter après
```

## Accès Keycloak admin

```bash
docker exec -it hellojadeapp-keycloak /bin/bash
# puis naviguer vers http://keycloak:8080/auth (depuis l'intérieur)
# admin / admin123
```
