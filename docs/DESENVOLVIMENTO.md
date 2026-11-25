# Desenvolvimento

## Estrutura

```
matrix_dashboard.py        ponto de entrada (run.sh, serviço e instalador chamam este arquivo)
matrixdash/
  cli.py                   argumentos: --config, --once, --at, --detect
  dashboard.py             laço principal, teclado e layout dos painéis
  terminal.py              teclado cru, tela alternativa, paleta do console e shell local
  collector.py             threads de coleta; monta o Snapshot
  models.py                Snapshot, Container, Event...
  config.py                padrões, leitura e gravação do config.json
  autodetect.py            detecção de discos, interface, serviços, testes de containers e redes
  alerts.py                lista de alertas ativos (cabeçalho e notificações)
  notify/                  canais de aviso (channels.py) e quem decide quando avisar (manager.py)
  health.py                limites de CPU/RAM/temperatura/disco (alertas e eventos)
  netmap.py                mapa da rede: vizinhos ARP/IPv6, mDNS/NetBIOS, Tailscale, redes de containers
  settings_menu.py         menu de configurações (tecla C)
  web_view.py              servidor HTTP do espelho (Server-Sent Events) + terminal web opcional
  claude_usage.py          leitura do uso de tokens do Claude Code (~/.claude/projects)
  fmt.py shell.py storage.py sysinfo.py theme.py validators.py   utilitários
  runtime/                 runtimes de containers: base.ContainerRuntime, docker.DockerRuntime, k3s.K3sRuntime
  integrations/            recursos opcionais: base.Integration, claude, backup, icloud, tailscale, wireguard, argocd
  panels/                  blocos da tela: base.Panel e um arquivo por painel
  render/                  Canvas, Screen, gráficos de texto, chuva, retrato e widgets
tests/                     testes (veja abaixo)
web/index.html             página do espelho (xterm.js em web/static/)
system/matrix-netcfg       helper root que aplica IP fixo/DHCP via netplan, com rollback
system/k8s/                ServiceAccount do painel no k3s e o script que gera o kubeconfig dela
system/wireguard-sudo.sh   regra de sudo só para ler os peers do WireGuard
system/tc/Dockerfile       imagem mínima com `tc`, usada para limitar a banda do icloudpd
install.sh                 instalador interativo
install_service.sh         serviço systemd no tty1
install_hotkeys_sudo.sh    regra do sudo para D/R/rede
uninstall.sh               remove o que foi instalado fora da pasta
tools/screenshots.py       gera os prints da documentação com dados de demonstração
config.example.json        modelo de configuração
```

## Como funciona

- **Coleta**: threads em segundo plano. A rápida (1 s) lê CPU, memória, rede, a lista de
  containers e as integrações rápidas e monta um `Snapshot` novo. A lenta lê o uso dos
  containers, `systemctl is-active`, as integrações lentas e faz os testes HTTP/TCP. O desenho
  só lê `collector.snap`, trocado de forma atômica.
- **Desenho**: cada quadro é desenhado num `Canvas` (caracteres + estilos); o `Screen` compara
  com o quadro anterior e envia ao terminal só o que mudou. O espelho web usa o mesmo canvas.
- **Detecção**: `merge_config()` junta o `config.json` com os padrões e chama
  `autodetect.resolve()`, que troca os marcadores `"auto"`. Os testes de containers são
  recalculados a cada ciclo lento por `autodetect.live_checks()`.

## As três interfaces

**`runtime.base.ContainerRuntime`**: tudo o que o painel pede a um runtime de containers
(listar, uso de CPU/memória, estado, logs, ligar/desligar/reiniciar, política de reinício, portas
publicadas, redes, PIDs). Os métodos nunca levantam exceção: falha vira resultado vazio ou
`None` ("não respondeu"). O coletor junta os containers de todos os runtimes da chave
`"runtimes"` do `config.json` (padrão `["docker"]`) e lembra qual runtime é dono de cada
container, então as ações do menu vão para o runtime certo. Para um runtime novo, crie a classe
em `runtime/` e registre em `runtime.RUNTIMES`.

**`integrations.base.Integration`**: um recurso opcional inteiro numa classe só: coleta
(`collect_fast`, `collect_slow`, `prime`), campos do `Snapshot` (`fill`), eventos
(`detect_events`), alertas e itens do letreiro do cabeçalho, linhas do boot, teclas
(`hotkeys`, `handle_key`, `key_label`) e seção do menu (`menu`, `menu_load`). Quando `enabled()`
é falso, nada dela aparece. Para uma integração nova, crie a classe e coloque em
`integrations.ALL`; a ordem da lista é a ordem na tela.

**`panels.base.Panel`**: cada bloco da tela desenha a si mesmo num retângulo
(`draw(c, s, x, y, w, h, t)`) e só lê o `Snapshot` e o estado do painel. O painel de serviços
aceita seções extras (`ServicesSection`), como o bloco do Claude Code.

## Testes

```bash
.venv/bin/python -m unittest discover -s tests                       # roda tudo
UPDATE_GOLDEN=1 .venv/bin/python -m unittest discover -s tests       # aceita telas novas
```

- `test_golden.py`: desenha 19 telas (painel completo, boot, ajuda, menu, compacta, backup,
  iCloud, relatório de uso, mapa da rede, confirmação, cluster k3s, Argo CD...) com dados fixos, relógio e sorteios
  congelados e compara caractere por caractere e cor por cor com `tests/golden/`. Mudou o
  desenho de propósito? Rode com `UPDATE_GOLDEN=1` e confira o `git diff` dos arquivos.
- `test_runtime.py`: leitura da saída do `docker` (capturada de um servidor real) e a junção
  dos containers de vários runtimes.
- `test_behaviour.py`: teclas, ações das integrações, gravação do menu e eventos.
- `test_alerts.py`: quando os avisos saem (espera, lembrete, resolvido, silêncio) e a
  requisição de cada canal.
- `test_web.py`: espelho web de ponta a ponta (servidor e cliente reais).
- `test_wireguard.py`: interfaces e peers a partir da saída de `ip` e `wg show`.
- `test_k3s.py` e `test_argocd.py`: workloads a partir dos pods, métricas, `rollout restart`,
  leitura das Applications, eventos e alertas (com JSON sintético, sem cluster).
- `test_smoke.py`: roda o `matrix_dashboard.py` de verdade com `--detect` e `--once`.

Os testes precisam de Linux (o painel usa `termios`). Fora do Linux, rode num container:

```bash
docker run --rm -v "$PWD:/app" -w /app python:3.10-slim \
  sh -c "pip install -q psutil Pillow && python -m unittest discover -s tests"
```

## Rodar em desenvolvimento

```bash
./install.sh --yes
.venv/bin/python matrix_dashboard.py --config config.json            # painel
.venv/bin/python matrix_dashboard.py --config config.json --once     # um quadro
.venv/bin/python matrix_dashboard.py --config config.json --once --at 2.0   # quadro do boot
.venv/bin/python -m matrixdash.autodetect                            # só a detecção
COLUMNS=90 LINES=26 .venv/bin/python matrix_dashboard.py --once     # testar outro tamanho
```

## Gerar os prints da documentação

```bash
.venv/bin/python tools/screenshots.py            # grava em docs/screenshots/
```

O script desenha o painel com o renderizador real e dados fixos de demonstração (hostname
`matrix-lab`, IPs de exemplo, containers fictícios), então nada do servidor onde ele roda vai
para as imagens. Precisa da fonte DejaVu Sans Mono (`sudo apt install fonts-dejavu-core`).

## Adicionar um serviço ao catálogo

Em `matrixdash/autodetect.py`, acrescente em `SERVICE_CATALOG` o rótulo e as units candidatas (a primeira
instalada vence; `*` aceita instâncias, ex.: `syncthing@*.service`):

```python
("MEU SERVIÇO", ["meu-servico.service", "meu-servico-alt.service"]),
```

## Adicionar uma app com teste HTTP

Em `KNOWN_IMAGES` (`matrixdash/autodetect.py`): trecho do nome da imagem, porta **interna** do container, caminho de saúde
(ou `None` para TCP) e rótulo. A ordem importa: o primeiro trecho que casar vence.

```python
("minha-app", 8080, "/healthz", "MINHA APP"),
```

## Convenções

- Interface em português; código, comentários e nomes em inglês.
- Só caracteres presentes na fonte do console Linux (Uni2-Fixed16) na tela.
- Recursos opcionais não podem aparecer quebrados: sem configuração, ficam escondidos.
- Sem dependências além de `psutil` e `Pillow`.
