# Ink Monitor

Web UI per monitorare il livello di inchiostro/toner delle stampanti di rete via SNMP. Server HTTP Python puro (nessuna dipendenza esterna), porta di default 8081.

## Requisiti

- Python 3
- `snmpget` / `snmpwalk` (pacchetto `snmp`)
  - Debian/Ubuntu/Mint: `sudo apt install snmp`
  - Fedora/RHEL: `sudo dnf install net-snmp-utils`
- `nmap` opzionale, per la scansione host più veloce (scan UDP porta 161). Se assente, si usa un ping sweep come fallback.

## Avvio

```bash
python3 main.py
python3 main.py --port 8081
python3 main.py --subnet 10.0.0.0/24 --community public
```

Oppure con lo script incluso (ferma un'istanza già in ascolto su 8081 e riavvia):

```bash
./avvia_ink_monitor.sh
```

Parametri CLI:

| Flag | Default | Descrizione |
|---|---|---|
| `--port` | `8081` | Porta HTTP |
| `--subnet` | subnet locale rilevata automaticamente | Subnet da scansionare (es. `10.0.0.0/24`) |
| `--community` | `public` | Community SNMP v2c |
| `--bind` | `0.0.0.0` | Indirizzo di bind |

Una volta avviato, la UI è su `http://localhost:<porta>`.

## Come funziona

1. **Discovery** (`discovery.py`): trova gli host attivi sulla subnet, via `nmap -sU -p 161` se disponibile, altrimenti ping sweep multithread.
2. **Scan** (`scanner.py`): per ogni host trovato interroga via SNMP (Printer-MIB, RFC 3805) nome dispositivo e livelli delle forniture (toner/inchiostro/tamburo/waste), calcola la percentuale residua e ordina i risultati dal livello più basso al più alto. Scan eseguita in background su thread pool, stato consultabile via API mentre è in corso.
3. **SNMP** (`snmp.py`): wrapper su `snmpget`/`snmpwalk` con decodifica automatica di valori Hex-STRING (usati da alcune stampanti HP per i nomi forniture).
4. **Handlers** (`handlers.py`): server HTTP che serve la UI, gli asset statici e le API JSON.
5. **Export** (`export.py`): genera un report testuale con barre di livello ASCII.

## API

| Endpoint | Metodo | Descrizione |
|---|---|---|
| `/` | GET | UI principale |
| `/api/status` | GET | Stato scansione corrente (`running`, `progress`, `total`, `started`, `finished`, `error`) |
| `/api/printers` | GET | Elenco stampanti con i dati dell'ultima scansione |
| `/api/scan` | POST | Avvia una scansione. Parametri form: `subnet`, `community`, `hosts` (lista IP separati da virgola, opzionale, salta la discovery) |
| `/api/export/txt` | GET | Scarica report testuale |
| `/api/export/json` | GET | Scarica dati grezzi in JSON |

## Soglie di livello

Definite in `scanner.py`:

- `WARN_LEVEL = 15%` — livello basso
- `CRIT_LEVEL = 5%` — livello critico

I valori SNMP speciali `-1`/`-2`/`-3` (sconosciuto/illimitato, es. contenitore toner esausto) sono esclusi dal calcolo del minimo.

## Struttura file

```
main.py          entry point, parsing argomenti, avvio server
config.py        config runtime condivisa (subnet/community di default)
discovery.py     ricerca host attivi sulla rete
scanner.py       probe SNMP delle stampanti, stato scansione, PRINTERS
snmp.py          wrapper snmpget/snmpwalk, OID Printer-MIB, decodifica Hex-STRING
handlers.py      HTTP handler: UI, static, API
export.py        report testuale esportabile
log.py           logging con timestamp
avvia_ink_monitor.sh   script di avvio/riavvio rapido
templates/       HTML della UI
static/          asset statici (CSS/JS)
```
