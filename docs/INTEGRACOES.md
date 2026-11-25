# Integrações

Todas são opcionais. Quando não estão configuradas, as partes da tela, as teclas e as seções do
menu correspondentes não aparecem.

## Alertas (Telegram, Discord, ntfy, webhook)

Os mesmos alertas do letreiro vermelho do cabeçalho viram mensagens: CPU, RAM, disco,
temperatura, internet, container ou workload com problema, serviço do systemd parado, app do
Argo CD Degraded ou com sync que falhou, túnel WireGuard/Tailscale caído e limite do Claude.

- Um problema só é avisado se **durar** `delay` minutos (padrão 2): o que pisca e volta não avisa.
- Enquanto durar, um **lembrete** a cada `repeat` minutos (padrão 60; `0` = só uma vez).
- Quando acaba, chega **✅ resolvido** com quanto tempo durou.
- O que aparece junto vai numa mensagem só.
- **Horário de silêncio** e **silenciar por 1 hora** seguram os avisos; o que ainda estiver
  ativo é enviado quando o silêncio acaba.

Configure pelo próprio painel: **`C` → ALERTAS**, uma seção por canal. Pelo SSH dá para colar
o token ou a URL (colar no terminal é o mesmo que digitar). Segredos aparecem como `******abcd`,
também enquanto você digita, porque a tela vai para a página web; Enter vazio mantém o valor e
`-` apaga. No Telegram, mande um oi para o bot e use **Descobrir chat ID**; no ntfy, **Gerar
tópico aleatório** cria um nome difícil de adivinhar. **Enviar mensagem de teste** mostra no
menu o que chegou e o que falhou.

O mesmo fica na chave `alerts` do `config.json`, se preferir editar o arquivo:

```json
"alerts": {
  "telegram": {"token": "123456:ABC-seu-token", "chat_id": "123456789"},
  "discord":  {"webhook": "https://discord.com/api/webhooks/..."},
  "ntfy":     {"topic": "um-nome-dificil-de-adivinhar", "server": "https://ntfy.sh", "token": ""},
  "webhook":  {"url": "https://n8n.exemplo/webhook/servidor", "headers": {"X-Token": "..."}}
}
```

| Canal | Como conseguir |
|---|---|
| Telegram | Fale com o **@BotFather**, `/newbot`, copie o token. Mande uma mensagem para o seu bot e abra `https://api.telegram.org/bot<TOKEN>/getUpdates`: o `chat.id` é o `chat_id` (grupos têm id negativo). |
| Discord | No canal: Editar canal → Integrações → Webhooks → Novo webhook → Copiar URL. |
| ntfy | Instale o app **ntfy** no celular e assine um tópico. No ntfy.sh público qualquer um que souber o nome do tópico lê as mensagens: use um nome difícil, ou um servidor próprio com `token`. |
| Webhook | Qualquer URL que aceite `POST` com JSON: `{"host", "kind", "title", "text", "alerts": [{"text", "state", "since"}]}`. `kind` é `problem`, `reminder`, `resolved` ou `test`. |

O `config.json` passa a ter segredos: deixe só o seu usuário ler (`chmod 600 config.json`). O
painel mantém essa permissão quando grava o arquivo.

## WireGuard

Detectado sozinho quando existe uma interface WireGuard (`wg0`...). Sem permissão extra, o
painel mostra o endereço da interface e o tráfego. Para ver os **peers**, que só o root lê,
libere a leitura:

```bash
sudo ./system/wireguard-sudo.sh        # regra em /etc/sudoers.d/matrix-dashboard-wireguard
```

A regra permite apenas `wg show all` com `allowed-ips`, `endpoints`, `latest-handshakes`,
`transfer` e `persistent-keepalive`, que não mostram chave privada. Os peers são lidos a cada
60 s (`"wireguard": {"peers_every": 60}`), e essas 5 leituras não vão para o log do sudo
(`!syslog`, `!pam_session`), para não encher o journal; o resto do sudo continua registrado.

- **Serviços**: a linha `wg-quick@wg0` vira `ONLINE 10.8.0.1/24 1/2 peers`.
- **Mapa da rede (`W`)**: seção `WIREGUARD // wg0` com cada peer: IPs permitidos, tráfego ao
  vivo, endpoint e último handshake.
- **Alertas**: interface fora do ar, ou peer com `PersistentKeepalive` (túnel site a site,
  que deveria estar sempre ligado) sem handshake há mais de 3 minutos. Peers sem keepalive
  (celular, notebook) só aparecem como offline, sem alerta.
- **Console**: peer conectou / ficou offline, interface caiu / voltou.

O WireGuard não guarda nomes; os peers aparecem pelo primeiro IP permitido. Para dar nomes:

```json
"wireguard": {"names": {"10.8.0.2": "casa", "10.8.0.3": "notebook"}}
```

## k3s / Kubernetes

Com `"runtimes": ["auto"]` (padrão), o painel mostra os workloads do k3s junto com os containers
do Docker quando existe `kubectl` e um kubeconfig legível. Cada Deployment, StatefulSet e
DaemonSet vira uma linha: prontos/desejados, CPU e memória somadas dos pods (pelo
metrics-server) e há quanto tempo o pod mais novo subiu. Pods com `ImagePullBackOff`,
`CrashLoopBackOff` e afins sobem para o topo e viram alerta no cabeçalho.

O kubeconfig do k3s (`/etc/rancher/k3s/k3s.yaml`) só pode ser lido pelo root. Em vez de abrir
esse arquivo, crie uma conta só para o painel:

```bash
sudo ./system/k8s/make-kubeconfig.sh          # aplica o RBAC e grava ~/.kube/matrix-dashboard.yaml
```

A conta (`system/k8s/matrix-dashboard-rbac.yaml`, ServiceAccount `matrix-dashboard` em
`kube-system`) lê pods, nós, workloads, métricas e as Applications do Argo CD, e pode fazer
`rollout restart`. Não lê secrets nem apaga nada. Quem usa GitOps pode levar esse YAML para o
próprio repositório.

O kubeconfig é procurado nesta ordem: chave `kubeconfig`, `$KUBECONFIG`,
`~/.kube/matrix-dashboard.yaml`, `~/.kube/config`, `/etc/rancher/k3s/k3s.yaml`.

No menu `C`, os workloads do k3s só têm a ação **reiniciar** (`kubectl rollout restart`).
Desligar e ligar ficam de fora: com o Argo CD em self-heal, um scale para 0 seria desfeito.

## Argo CD

Com o k3s ligado (seção acima) e o Argo CD instalado no cluster, as Applications aparecem
sozinhas (`"argocd": "auto"`). Não precisa de token da API do Argo CD: as Applications são
recursos do próprio cluster e a conta `matrix-dashboard` tem permissão de leitura nelas.

- **Painel de serviços**: bloco `GITOPS // ARGO CD` com as apps com problema (Degraded,
  OutOfSync, sync que falhou), cada uma com o motivo, e uma linha com as que estão ok.
- **Tecla `A`**: lista completa no lugar dos painéis de sistema e serviços: namespace, sync,
  health, revisão implantada, branch/tag alvo, há quanto tempo foi o último sync e a mensagem.
- **Cabeçalho**: alerta para app Degraded/Missing ou sync que falhou; resumo no letreiro.
- **Console**: eventos de mudança de saúde, de sync, de revisão implantada e de sync com erro.

Quando o Argo CD diz só "Degraded" (versões recentes guardam a saúde dos recursos fora da
Application), o painel mostra o erro dos pods do namespace de destino, como
`api: ImagePullBackOff`. O painel só lê: sync e rollback continuam pelo Argo CD.

## Claude Code

Detectado automaticamente (`"claude": "auto"`) quando o executável `claude` existe.

O painel mostra:

- **Processos**: online/offline, número de sessões, remote-control (nome), versão, CPU,
  memória, há quanto tempo está aberto e se está trabalhando (CPU acima de 4%) ou ocioso, com
  histórico.
- **Uso** (lido de `~/.claude/projects`): tokens e custo estimado de hoje, da semana e das
  últimas 5 h, gráficos por hora e por dia e totais por modelo. O retrato alterna com esse
  relatório; a tecla `U` fixa um dos dois.
- **Limites do plano** (opcional): o Claude Code não expõe os limites por arquivo. Se você usa
  um script de statusline que salva o JSON da statusline, aponte `claude_limits_file` para ele
  (padrão `~/.claude/statusline-last.json`). O painel lê `rate_limits.five_hour` e
  `rate_limits.seven_day` (`used_percentage` e `resets_at`). `claude_plan` é só um rótulo
  (ex.: `"Pro"`).

```json
"claude": "auto",
"claude_plan": "Pro",
"claude_limits_file": "~/.claude/statusline-last.json"
```

Use `"claude": false` para esconder tudo mesmo com o Claude Code instalado.

## Status de um backup externo

O painel pode mostrar o progresso de qualquer script de backup (rclone, restic, rsync…) que
grave um arquivo JSON de estado. Aponte `backup_state` para ele:

```json
"backup_state": "~/backup/state.json"
```

O script deve reescrever o arquivo a cada poucos segundos enquanto roda (se ficar mais de 90 s
sem atualizar durante `running`, o painel mostra `stalled`). Campos lidos:

| Campo | Exemplo | Uso |
|---|---|---|
| `status` | `running`, `idle`, `done`, `paused`, `error`, `not_started` | estado e cor |
| `phase` | `scanning`, `comparing`, `uploading` | fase atual |
| `updated` | `1731672000` | horário (epoch) da última escrita |
| `dest` | `"gdrive:Backup"` | destino exibido |
| `source_bytes` / `uploaded_bytes` | números | progresso da cópia inicial |
| `initial_complete` | `true` | cópia inicial terminada |
| `today` / `run` | objetos com bytes e arquivos | totais do dia e da execução atual |

Com `backup_state` definido, a pasta do arquivo vira a pasta de controle e aparecem as teclas:

| Tecla | Arquivo criado/apagado na pasta | O script deve… |
|---|---|---|
| `B` | `PAUSE` (cria/apaga) | não iniciar enquanto `PAUSE` existir |
| `S` | `RUN_NOW` (cria) | rodar já e apagar o arquivo |
| `V` | `TURBO` (cria/apaga) | ignorar o limite de banda enquanto existir |

Se a pasta tiver um `backup.json` com `bwlimit` (ex.: `"08:00,3M 23:00,8M"`) e `daily_sync_at`
(ex.: `"02:00"`), o menu `C` ganha a seção de backup para editar esses valores.

## iCloud (icloudpd)

Para quem baixa fotos do iCloud com o container
[icloudpd](https://github.com/boredazfcuk/docker-icloudpd):

```json
"icloud": {"container": "icloudpd", "folder": "/srv/fotos/icloud", "limit": "off"}
```

- O painel lê os logs do container e o tamanho da pasta para mostrar status, itens baixados,
  velocidade e total do dia. Avisa quando a Apple pede login de novo.
- Tecla `P` pausa/retoma o container.
- `limit` (`off`, `1M`, `2M`, `3M`, `5M`) limita a banda de download dentro do container. Para
  isso, crie uma vez a imagem auxiliar:
  ```bash
  docker build -t matrix-tc system/tc
  ```
