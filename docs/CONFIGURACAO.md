# Configuração

Toda a configuração fica em `config.json`, na pasta do painel. O instalador gera esse arquivo a
partir de [`config.example.json`](../config.example.json) e ele já funciona sem mudanças. Edite
com qualquer editor e reinicie o painel (`sudo systemctl restart matrix-dashboard`, ou feche e
abra o `./run.sh`). Parte das opções também muda pelo menu `C`, sem reiniciar.

Para ver o resultado da detecção com a sua configuração: `./run.sh --detect`.

## Detecção automática e o marcador `"auto"`

Listas que contêm `"auto"` são preenchidas pelo [`autodetect.py`](../matrixdash/autodetect.py) a cada
início. Os itens que você escreve ao lado de `"auto"` são mantidos. Assim dá para acrescentar ou
corrigir algo sem perder o resto:

```json
"mounts": ["auto", "/mnt/nas"],
"systemd_units": ["auto", {"name": "MEU APP", "unit": "meu-app"}],
"checks": ["auto", {"name": "SITE", "container": "site", "url": "http://127.0.0.1:8080/health"}]
```

Para desligar a detecção de uma lista, tire o `"auto"` e escreva a lista completa.

| O quê | Como é detectado |
|---|---|
| `mounts` | partições montadas de discos reais com mais de 1 GB; ignora snap, loop, tmpfs, overlay, `/boot` e bind mounts repetidos; `/` vem primeiro; até 6 |
| `network_interface` | a interface com a rota padrão |
| `systemd_units` | catálogo de ~35 serviços comuns (lista em `SERVICE_CATALOG`); entra o que estiver instalado **e** habilitado ou rodando |
| `checks` | refeito ao vivo: para cada container rodando com porta TCP publicada, um teste. Apps conhecidas (`KNOWN_IMAGES`) recebem teste HTTP no caminho de saúde delas; as demais, teste TCP. Containers com `network_mode: host` de apps conhecidas são testados na porta padrão |
| `web.allow` | `127.0.0.1`, `::1`, as faixas do Tailscale (se instalado) e as redes privadas das interfaces físicas |
| `claude: "auto"` | mostra o bloco do Claude Code se o executável `claude` existir |

Serviços detectados: Docker, Podman, SSH, Tailscale, ZeroTier, WireGuard, cloudflared, Nginx,
Apache, Caddy, MySQL, MariaDB, PostgreSQL, Redis, Samba, NFS, Netdata, Cockpit, Webmin,
Prometheus, Node Exporter, Grafana, Plex, Jellyfin, Pi-hole, Unbound, Fail2ban, UFW, K3s,
libvirt, Syncthing, Mosquitto, Home Assistant (core) e cron.

Apps com teste HTTP próprio: Home Assistant, Grafana, Immich, Portainer, Node-RED, EMQX,
File Browser, Jellyfin, Plex, Nextcloud, Vaultwarden, Uptime Kuma, Pi-hole, AdGuard, Frigate,
Nginx Proxy Manager, Prometheus, code-server, Syncthing, qBittorrent, Transmission, Sonarr,
Radarr, Prowlarr, Gitea, n8n e Coolify. Traefik, Mosquitto, PostgreSQL, MariaDB, MySQL, Redis e
MongoDB recebem teste TCP.

## Todas as opções

### Aparência

| Chave | Padrão | Descrição |
|---|---|---|
| `title` | `""` | título do cabeçalho; vazio = `<HOSTNAME> // MATRIX SERVER MONITOR` |
| `operator` | usuário Linux | nome no boot ("WELCOME, …") e no retrato |
| `brand` | `"MATRIX SECURE TERMINAL"` | primeira linha do boot |
| `image` | `"assets/portrait.png"` | foto (`.png`, `.jpg`) convertida em ASCII, ou arte pronta (`.txt`, `.asc`); arquivo inexistente = nome do servidor em letras grandes |
| `fps` | `10` | quadros por segundo (2 a 30); menos = menos CPU |
| `matrix_density` | `0.45` | densidade da chuva (0.05 a 1.0) |
| `boot_animation` | `true` | animação de boot ao abrir |
| `console_palette` | `true` | reprograma as 16 cores do console Linux com tons de verde (só no tty) |
| `screen_off` | `{"enabled": false, "from": "00:00", "to": "07:00"}` | apaga o monitor no horário |

### Monitoramento

| Chave | Padrão | Descrição |
|---|---|---|
| `mounts` | `["auto"]` | discos exibidos (pontos de montagem) |
| `network_interface` | `"auto"` | interface dos gráficos de rede |
| `systemd_units` | `["auto"]` | serviços do host: `{"name": "RÓTULO", "unit": "nome-da-unit"}` |
| `checks` | `["auto"]` | testes de endpoint, veja abaixo |
| `alerts` | `{"delay": 2, "repeat": 60, ...}` | notificações dos alertas: canais `telegram`, `discord`, `ntfy`, `webhook`, minutos até avisar, lembrete e horário de silêncio ([Integrações](INTEGRACOES.md#alertas-telegram-discord-ntfy-webhook)) |
| `theme` | `"matrix"` | tema de cores: `matrix`, `ambar`, `gelo`, `synthwave`, `mono` (também pelo menu `C`) |
| `theme_colors` | `{}` | troca cores do tema, ex.: `{"accent": "ff00ff"}`; papéis: `g0`…`g6` (do mais escuro ao mais claro), `text`, `accent`, `red`, `amber`, `red_bg`, `white` |
| `hide_containers` | `[]` | nomes de containers que não aparecem |
| `runtimes` | `["auto"]` | de onde vêm os containers: `docker`, `k3s`; `auto` usa os que existirem na máquina |
| `wireguard` | `{}` | `{"names": {"10.8.0.2": "casa"}}` dá nome aos peers; `false` esconde |
| `argocd` | `"auto"` | applications do Argo CD lidas do cluster k3s; `false` esconde |
| `kubeconfig` | `""` | kubeconfig usado para o k3s; vazio = procura (veja [Integrações](INTEGRACOES.md#k3s--kubernetes)) |
| `ping_host` / `ping_host6` | `1.1.1.1` / `2606:4700:4700::1111` | alvo da latência e do teste de internet |
| `thresholds` | `{"cpu": 85, "ram": 85, "disk": 90, "temperature": 80}` | limites de alerta (%, °C) |
| `claude` | `"auto"` | `true`/`false` força mostrar/esconder o Claude Code |

**Formato de um teste (`checks`)**:

```json
{"name": "MEU SITE", "container": "site", "url": "http://127.0.0.1:8080/health"}
{"name": "BANCO", "container": "db", "tcp_host": "127.0.0.1", "tcp_port": 5432}
{"name": "PROXY", "url": "https://127.0.0.1/", "host_header": "app.exemplo.com"}
```

- `url`: teste HTTP; conta como no ar com qualquer resposta abaixo de 500 (inclusive 401/404).
  HTTPS aceita certificado autoassinado.
- `tcp_host` + `tcp_port`: só verifica se a porta aceita conexão.
- `container`: liga o resultado à linha do container. Um teste explícito **substitui** o
  automático do mesmo container. Sem `container`, o teste aparece como linha própria.

### Espelho web

| Chave | Padrão | Descrição |
|---|---|---|
| `web.enabled` | `false` | liga o servidor web do painel |
| `web.port` | `8095` | porta |
| `web.fps` | `5` | quadros por segundo enviados ao navegador |
| `web.control` | `false` | a página pode enviar teclas |
| `web.terminal` | `false` | shell no navegador (exige `control`) — **sem senha** |
| `web.allow` | `["auto"]` | redes (CIDR) que podem acessar; o resto recebe 403 |

### Mapa da rede

| Chave | Padrão | Descrição |
|---|---|---|
| `devices` | `{}` | nome e tipo fixos por MAC |
| `netmap.interval` | `60` | segundos entre varreduras |

```json
"devices": {
  "aa:bb:cc:dd:ee:ff": {"name": "TV SALA", "link": "cabo"},
  "11:22:33:44:55:66": {"name": "CELULAR ANA", "link": "wi-fi"}
}
```

### Integrações opcionais

`backup_state`, `icloud`, `claude_plan` e `claude_limits_file`: veja [Integrações](INTEGRACOES.md).

## Exemplo completo

```json
{
  "title": "LAB // CASA",
  "operator": "Ana",
  "image": "assets/portrait.jpg",
  "fps": 8,
  "mounts": ["auto", "/mnt/nas"],
  "systemd_units": ["auto", {"name": "MINECRAFT", "unit": "minecraft"}],
  "checks": ["auto", {"name": "BLOG", "container": "ghost", "url": "http://127.0.0.1:2368/ghost/"}],
  "hide_containers": ["watchtower", "autoheal"],
  "thresholds": {"cpu": 90, "temperature": 75},
  "screen_off": {"enabled": true, "from": "23:30", "to": "07:00"},
  "web": {"enabled": true, "port": 8095, "control": true, "terminal": false, "allow": ["auto"]},
  "devices": {"aa:bb:cc:dd:ee:ff": {"name": "TV SALA", "link": "cabo"}}
}
```

Chaves que começam com `_` são ignoradas e servem como comentário (`"_nota": "..."`).

## Segurança

- **Página web**: responde só às redes de `web.allow`. Sem `control`, é só visualização. As
  teclas exigem um cabeçalho que formulários de outros sites não conseguem enviar, então uma
  página maliciosa aberta num navegador da rede não aperta teclas no painel.
- **Terminal web**: qualquer pessoa que alcance a página ganha um shell com o usuário do painel.
  Ative só se a porta estiver acessível apenas por você (ex.: só Tailscale:
  `"allow": ["127.0.0.1/32", "100.64.0.0/10"]`).
- **Root**: o painel roda como usuário comum. `install_hotkeys_sudo.sh` libera só
  `systemctl poweroff`, `systemctl reboot` e `/usr/local/sbin/matrix-netcfg` (pertence ao root,
  valida os argumentos e só altera o IPv4 da interface principal no netplan, com backup e
  rollback automático).
- **Docker**: estar no grupo `docker` equivale a ter root no servidor. O painel precisa disso
  para ler os containers; se não quiser, ele funciona sem a parte de containers.
