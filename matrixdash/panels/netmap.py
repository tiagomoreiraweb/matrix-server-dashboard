"""Network map: LAN devices, Tailscale peers and container networks, with live traffic."""

from __future__ import annotations

import time

from ..fmt import ago, rate_short
from ..models import Snapshot
from ..render.canvas import Canvas
from ..render.charts import heat_strip
from ..render.widgets import section
from ..theme import AMBER, CYAN, G0, G1, G2, G3, G4, G5, G6, RED, SPINNER, TEXT, WHITE
from .base import Panel


class NetMapPanel(Panel):
    LINK_LABELS = {"cabo": ("CABO", G5), "wifi": ("WI-FI", CYAN), "gw": ("ROUTER", AMBER), "?": ("?", G2)}

    def put_rate(self, c: Canvas, x: int, y: int, rx: float, tx: float, width: int = 13, dim: bool = False):
        """'▼rx ▲tx' from the device's point of view; idle traffic is drawn dim."""
        if width <= 0:
            return
        down, up = rate_short(rx), rate_short(tx)
        c.put(x, y, ("▼" + down)[:width], G1 if dim or rx < 1 else G6 if rx > 1e6 else G5)
        xx = x + len(down) + 2
        if xx < x + width:
            c.put(xx, y, ("▲" + up)[: x + width - xx], G1 if dim or tx < 1 else G4 if tx > 1e6 else G3)

    def draw(self, c: Canvas, s: Snapshot, x: int, y: int, w: int, h: int, t: float):
        nm = s.netmap or {}
        tr = s.nettraffic or {}
        tpeers = tr.get("peers") or {}
        lan = nm.get("lan") or {}
        devices = lan.get("devices") or []
        peers = nm.get("tailscale") or []
        nets = nm.get("docker") or []
        scanned = f"varredura há {time.time() - nm['at']:.0f}s" if nm.get("at") else "varrendo..."
        ix, iw, bottom = self.frame(c, x, y, w, h, "▸ NETWORK MAP // DISPOSITIVOS · TRÁFEGO", f"W fecha · {scanned}", t * 18 + 30)
        if not nm:
            spin = SPINNER[int(t * 8) % 4]
            c.put(ix, y + 2, f"{spin} varrendo {s.iface}, tailscale e docker...", G4)
            return

        def traffic_of(ips) -> tuple[float, float, list[float], list[str]]:
            rx = tx = 0.0
            hist: list[float] = []
            svc: list[str] = []
            for ip in ips:
                p = tpeers.get(ip)
                if not p:
                    continue
                rx += p["rx"]
                tx += p["tx"]
                ph = p.get("hist") or []
                hist = [a + b for a, b in zip(hist, ph)] if len(hist) == len(ph) else (hist or ph)
                svc += [x_ for x_ in p.get("svc", []) if x_ not in svc]
            return rx, tx, hist, svc

        # Peers that are neither LAN devices nor Tailscale: the server's own internet traffic.
        local_ips = {d["ip"] for d in devices} | {ip for d in devices for ip in d.get("ip6s", [])}
        ts_ips = {p["ip"] for p in peers}
        inet_rx = sum(p["rx"] for ip, p in tpeers.items() if ip not in local_ips and ip not in ts_ips
                      and not ip.startswith(("100.", "fd7a:")))
        inet_tx = sum(p["tx"] for ip, p in tpeers.items() if ip not in local_ips and ip not in ts_ips
                      and not ip.startswith(("100.", "fd7a:")))

        online = [d for d in devices if d["online"]]
        counts = {k: sum(1 for d in online if d["link"] == k) for k in ("cabo", "wifi", "?")}
        ts_on = sum(1 for p in peers if p["online"])
        n_cont = sum(len(n["members"]) for n in nets)
        ifs = tr.get("ifaces") or {}

        # Topology strip: internet -> router -> lan -> this server, with live interface rates.
        row = y + 1
        router = next((d for d in devices if d["role"] == "router"), None)
        me = next((d for d in devices if d["role"] == "server"), None)
        net_ok = s.net4 or bool(s.net6)
        lan_if = ifs.get(s.iface) or {}
        ts_if = ifs.get("tailscale0") or {}
        parts = [("INTERNET", G5 if net_ok else RED), (" ══ ", G2),
                 (f"ROUTER {router['ip'] if router else lan.get('gateway', '?')}", AMBER), (" ══ ", G2),
                 (f"LAN {lan.get('subnet', '')}", TEXT), (" ══ ", G2),
                 (f"{(me or {}).get('name', s.hostname)} {(me or {}).get('ip', s.ip)}", G6),
                 (f" ({(me or {}).get('link', 'cabo')})", G3)]
        if lan_if:
            parts += [(f"  {s.iface} ", G2), (f"▼{rate_short(lan_if['rx'])} ▲{rate_short(lan_if['tx'])}", G5)]
        if s.tailscale and s.tailscale.get("ip"):
            parts += [(" ┄┄ ", G2), (f"TAILSCALE {s.tailscale['ip']}", CYAN)]
            if ts_if:
                parts += [(f" ▼{rate_short(ts_if['rx'])} ▲{rate_short(ts_if['tx'])}", CYAN)]
        xx = ix
        for text, style in parts:
            c.put(xx, row, text[: max(0, ix + iw - xx)], style)
            xx += len(text)
        row += 1
        stats = [("●", G5, f"{len(online)} online"), ("", G5, f"cabo {counts['cabo']}"),
                 ("", CYAN, f"wi-fi {counts['wifi']}"), ("", G2, f"? {counts['?']}"),
                 ("", G1, f"offline {len(devices) - len(online)}"),
                 ("", CYAN, f"tailscale {ts_on}/{len(peers)}"), ("", G4, f"docker {n_cont} em {len(nets)} redes"),
                 ("", G3, f"internet do servidor ▼{rate_short(inet_tx)} ▲{rate_short(inet_rx)}")]
        xx = ix
        for dot, style, text in stats:
            if dot:
                c.put(xx, row, dot, style)
                xx += 2
            c.put(xx, row, text[: max(0, ix + iw - xx)], style if style not in (G1, G2) else G3)
            xx += len(text) + 3
        row += 2

        wide = iw >= 150
        lan_w = iw * 2 // 3 if wide else iw
        side_x = ix + lan_w + 3 if wide else ix
        side_w = iw - lan_w - 3 if wide else iw

        # --- LAN table
        section(c, ix, row, lan_w, "LAN // CABO · WI-FI", f"{len(online)}/{len(devices)}")
        row += 1
        show_vendor = lan_w >= 100
        show_hist = lan_w >= 88
        cols = [("NOME", 20), ("IP", 15)]
        if show_vendor:
            cols.append(("FABRICANTE", 14))
        cols += [("LINK", 7), ("PING", 6), ("TRÁFEGO", 13)]
        if show_hist:
            cols.append(("ATIVIDADE", 10))
        used = 2 + sum(cw + 1 for _, cw in cols)
        cols.append(("CONEXÕES COM O SERVIDOR", max(0, lan_w - used)))
        xx = ix + 2
        for label, cw in cols:
            c.put(xx, row, label[:cw], G2)
            xx += cw + 1
        row += 1
        lan_bottom = bottom - 2 if wide else min(bottom - 2, row + max(3, (bottom - row) // 2))
        blink = int(t * 2) % 2 == 0
        shown = 0
        for d in devices:
            if row >= lan_bottom:
                break
            on = d["online"]
            new = on and bool(d.get("new"))
            rx_srv, tx_srv, hist, svc = traffic_of([d["ip"], *d.get("ip6s", [])]) if d["role"] != "server" else (0, 0, [], [])
            busy = on and (rx_srv + tx_srv) > 10_000
            c.put(ix, row, "●", (AMBER if blink else G6) if new else (G6 if busy and blink else G5) if on else G1)
            name = d["name"] or ("ROUTER" if d["role"] == "router" else "-")
            xx = ix + 2
            for label, cw in cols:
                if label == "NOME":
                    c.put(xx, row, name[:cw], WHITE if d["role"] == "server" else TEXT if on else G2)
                elif label == "IP":
                    c.put(xx, row, (d["ip"] or "-")[:cw], G4 if on else G2)
                elif label == "FABRICANTE":
                    c.put(xx, row, (d["vendor"] or "-")[:cw], G3 if on else G1)
                elif label == "LINK":
                    link, lstyle = self.LINK_LABELS.get(d["link"], ("?", G2))
                    if d.get("est") and d["link"] != "?":
                        link += "~"
                    c.put(xx, row, link[:cw], lstyle if on else G2)
                elif label == "PING":
                    ms = d.get("ms")
                    if on:
                        c.put(xx, row, f"{ms:.0f}ms" if ms is not None else "-", AMBER if ms and ms > 80 else G4)
                    else:
                        c.put(xx, row, ago(d.get("last", 0))[:cw], G2)
                elif label == "TRÁFEGO":
                    if d["role"] == "server":
                        c.put(xx, row, "(este)", G2)
                    elif on:
                        self.put_rate(c, xx, row, rx_srv, tx_srv, cw)
                    else:
                        c.put(xx, row, "offline", G1)
                elif label == "ATIVIDADE":
                    if on and hist and d["role"] != "server":
                        c.put(xx, row, heat_strip(hist, cw, max(max(hist), 50_000.0)), G4)
                    elif on:
                        c.put(xx, row, "·" * cw, G0)
                elif cw > 0:
                    if d["role"] == "server":
                        text, st = "este servidor", G2
                    elif d["role"] == "router":
                        text, st = (" ".join(svc) or "gateway da internet"), G3
                    else:
                        text, st = (" ".join(svc) if svc else "-" if on else ""), G4 if svc else G1
                    c.put(xx, row, text[:cw], st)
                xx += cw + 1
            row += 1
            shown += 1
        if shown < len(devices) and row < bottom:
            c.put(ix + 2, row, f"+{len(devices) - shown} dispositivos não cabem na tela", G2)
        note = ("tráfego = só o que passa pelo servidor (▼ o aparelho recebe · ▲ envia); "
                "a internet dos outros aparelhos vai direto ao router · ~ wi-fi estimado")
        c.put(ix, bottom - 1, note[:iw], G1)

        # --- Tailscale and Docker (right column, or below the LAN table)
        row = y + 4 if wide else lan_bottom + 1
        if row < bottom - 1:
            section(c, side_x, row, side_w, "TAILSCALE // VPN", f"{ts_on}/{len(peers)} online", CYAN)
            row += 1
            for p in peers:
                if row >= bottom - 1:
                    break
                on = p["online"]
                rx_p, tx_p, _, _ = traffic_of([p["ip"]])
                c.put(side_x, row, "●", CYAN if on else G1)
                c.put(side_x + 2, row, p["name"][:18], TEXT if on else G2)
                c.put(side_x + 21, row, p["ip"][:15], G4 if on else G2)
                if on:
                    self.put_rate(c, side_x + 37, row, rx_p, tx_p, 13)
                    info = ("exit · " if p.get("exit") else "") + (p["path"] or p["os"])
                else:
                    c.put(side_x + 37, row, f"visto {ago(p['last'])}", G2)
                    info = p["os"]
                c.put(side_x + 51, row, info[: max(0, side_w - 51)], G3 if on else G1)
                row += 1
            row += 1
        row = self.draw_wireguard(c, s, side_x, row, side_w, bottom)
        conts = tr.get("containers") or {}
        if row < bottom - 1:
            total_rx = sum(v["rx"] for v in conts.values())
            total_tx = sum(v["tx"] for v in conts.values())
            section(c, side_x, row, side_w, "DOCKER // CONTAINERS",
                    f"▼{rate_short(total_rx)} ▲{rate_short(total_tx)}", G4)
            row += 1
            net_of = {m[0]: n["name"] for n in nets for m in n["members"]}
            names = sorted({m[0] for n in nets for m in n["members"]},
                           key=lambda nm_: (-(conts.get(nm_, {}).get("rx", 0) + conts.get(nm_, {}).get("tx", 0)), nm_))
            for name in names:
                if row >= bottom - 1:
                    break
                cs = conts.get(name)
                busy = cs and cs["rx"] + cs["tx"] > 10_000
                c.put(side_x, row, "●", G6 if busy else G5)
                c.put(side_x + 2, row, name[:22], TEXT)
                c.put(side_x + 25, row, net_of.get(name, "")[:16], G2)
                if cs:
                    # Container counters are its own eth0: rx = what the container receives.
                    self.put_rate(c, side_x + 42, row, cs["rx"], cs["tx"], max(0, min(13, side_w - 42)))
                else:
                    c.put(side_x + 42, row, "rede do host"[: max(0, side_w - 42)], G2)
                row += 1
            empty = [n["name"] for n in nets if not n["members"]]
            if empty and row < bottom - 1:
                c.put(side_x, row, ("redes vazias: " + " ".join(empty))[:side_w], G1)

    def draw_wireguard(self, c: Canvas, s: Snapshot, x: int, row: int, w: int, bottom: int) -> int:
        """WireGuard interfaces of this server and their peers; returns the next free row."""
        wg = s.wireguard or {}
        for iface in wg.get("ifaces") or []:
            if row >= bottom - 1:
                break
            peers = iface["peers"]
            online = sum(1 for p in peers if p["online"])
            right = f"{online}/{len(peers)} online" if wg.get("peers_known") else "peers: sudo ./system/wireguard-sudo.sh"
            section(c, x, row, w, f"WIREGUARD // {iface['name']} {iface['address']}", right, CYAN)
            row += 1
            for p in peers:
                if row >= bottom - 1:
                    break
                on = p["online"]
                c.put(x, row, "●", CYAN if on else (RED if p["keepalive"] else G1))
                c.put(x + 2, row, p["name"][:18], TEXT if on else G2)
                c.put(x + 21, row, ",".join(a.split("/")[0] for a in p["allowed"])[:15], G4 if on else G2)
                if on:
                    # The peer receives what we send: ▼ is our tx.
                    self.put_rate(c, x + 37, row, p["tx_rate"], p["rx_rate"], 13)
                    info = f"{p['endpoint'] or '-'} · handshake {ago(p['handshake'])}"
                else:
                    c.put(x + 37, row, f"visto {ago(p['handshake'])}" if p["handshake"] else "nunca conectou", G2)
                    info = "keepalive: devia estar on-line" if p["keepalive"] else (p["endpoint"] or "")
                c.put(x + 51, row, info[: max(0, w - 51)], G3 if on else (AMBER if p["keepalive"] else G1))
                row += 1
            row += 1
        return row
