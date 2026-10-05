"""Renders the current scan results as a plain-text report."""

import csv
import io
from datetime import datetime

from scanner import PRINTERS, STATE_LOCK, WARN_LEVEL, CRIT_LEVEL


def export_csv():
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Stampante", "IP", "Modello", "Seriale", "Pagine Totali", "Min Livello %",
                     "Fornitura", "Livello %", "Corrente", "Massimo", "Ultima Scansione"])
    with STATE_LOCK:
        printers = list(PRINTERS)
    for p in printers:
        min_pct = f"{p['min_pct']:.1f}" if p.get("min_pct") is not None else "N/D"
        page_count = p["page_count"] if p.get("page_count") is not None else ""
        head = [p["name"], p["ip"], p.get("model") or "", p.get("serial") or "", page_count, min_pct]
        scanned = p.get("scanned_at", "")
        if not p.get("supplies"):
            writer.writerow(head + ["Nessuna fornitura", "", "", "", scanned])
            continue
        for s in p["supplies"]:
            pct = f"{s['percent']:.1f}" if s.get("percent") is not None else "N/D"
            writer.writerow(head + [s["desc"], pct, s["current"], s["maximum"], scanned])
    return output.getvalue()


def export_txt():
    BAR = 22

    def bar(pct):
        if pct is None:
            return "[" + "·" * BAR + "]  N/D"
        f = max(0, min(BAR, int(round(pct / 100 * BAR))))
        w = " ⚠ BASSO" if pct <= WARN_LEVEL else ""
        return f"[{'█' * f}{'░' * (BAR - f)}] {pct:5.1f}%{w}"

    lines = ["═" * 72,
             "  REPORT LIVELLI INCHIOSTRO / TONER",
             f"  Generato: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
             "  Ordine: dal livello MINORE al MAGGIORE",
             "═" * 72, ""]
    with STATE_LOCK:
        printers = list(PRINTERS)
    for rank, p in enumerate(printers, 1):
        ml = f"{p['min_pct']:.1f}%" if p["min_pct"] is not None else "N/D"
        w = "  ← ⚠ CRITICO!" if p["min_pct"] is not None and p["min_pct"] <= CRIT_LEVEL else (
            "  ← ⚠ BASSO" if p["min_pct"] is not None and p["min_pct"] <= WARN_LEVEL else "")
        lines += [f"  [{rank:>2}] {p['name']}",
                  f"        IP: {p['ip']:<20}  Minimo: {ml}{w}", ""]
        for s in sorted(p["supplies"], key=lambda x: (x["percent"] is None, x["percent"] or 999)):
            lines.append(f"        {s['desc']:<34} {bar(s['percent'])}")
        lines += ["", "  " + "─" * 68, ""]
    lines += ["═" * 72,
              f"  Totale stampanti: {len(printers)}",
              f"  Critiche (≤{CRIT_LEVEL:.0f}%): {sum(1 for p in printers if p['min_pct'] is not None and p['min_pct'] <= CRIT_LEVEL)}",
              "═" * 72]
    return "\n".join(lines)
