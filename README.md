# Temperature Helper

Integrazione personalizzata per Home Assistant, installabile tramite HACS, che crea
**helper nativi** per le zone di riscaldamento e una dashboard pronta.

Gli helper sono identici a quelli creati a mano da
*Impostazioni → Dispositivi e servizi → Helper*: li puoi modificare o rinominare
dall'interfaccia.

## Installazione

1. HACS → menu ⋮ → **Repository personalizzati**
2. URL: `https://github.com/umb-hub/Temperature_Helper`, categoria **Integrazione**
3. Installa **Temperature Helper** e riavvia Home Assistant
4. *Impostazioni → Dispositivi e servizi → Aggiungi integrazione* → **Temperature Helper**:
   un clic, nessuna domanda.
5. Nella pagina dell'integrazione usa **Aggiungi zona** per ogni zona.

Richiede Home Assistant 2025.3 o successivo.

## Cosa crea

**Subito, all'installazione** (una sola volta):

- Helper *Template → Sensore template* **test**: stato
  `{{ (0.00000001 * now().timestamp()) | round(6) }}`, unità `kWh`, classe di stato
  *Misura* (si aggiorna ogni minuto). Alla creazione vengono importate le
  statistiche orarie degli ultimi 7 giorni, così il grafico ha dati da subito.
- Dashboard **Temperature** (`/temperature-helper`, nella barra laterale) con un
  grafico statistico senza titolo in cima: la legenda usa i nomi degli helper,
  quindi rinominandoli cambia anche il grafico.

**Per ogni zona** (es. `Soggiorno`):

| Helper | Entity ID | Default |
|---|---|---|
| Soggiorno Temperatura Comfort | `input_number.soggiorno_temperatura_comfort` | 21 °C |
| Soggiorno Temperatura Eco | `input_number.soggiorno_temperatura_eco` | 18 °C |
| Soggiorno Temperatura Notte | `input_number.soggiorno_temperatura_notte` | 17 °C |
| Soggiorno Temperatura Assenza | `input_number.soggiorno_temperatura_assenza` | 15 °C |
| Soggiorno Temperatura Antigelo | `input_number.soggiorno_temperatura_antigelo` | 7 °C |
| Soggiorno Modalità Manuale | `input_boolean.soggiorno_modalita_manuale` | off |

più una sezione nella dashboard con una tile per helper. Scegli setpoint, min/max e
passo quando aggiungi la zona; li cambi poi con **Riconfigura** sulla zona.

**Temperatura media**: se una zona ha il *sensore di temperatura* (facoltativo),
viene creato un unico helper *Combina lo stato di più sensori* (media) con i
sensori di tutte le zone, mostrato nel grafico.

## Comportamento

- **Niente duplicati**: una zona per nome; riavvii e ricaricamenti non creano copie.
  Un helper che esiste già con lo stesso ID viene **adottato** (e mai eliminato).
- **Riconfigura zona**: i setpoint aggiunti vengono creati, quelli tolti eliminati.
- **Elimina zona**: vengono eliminati i suoi helper, la sua sezione della dashboard
  e il suo sensore dalla media (se la media resta vuota, viene eliminata).
- **Elimina integrazione**: viene eliminato **tutto** ciò che ha creato: helper delle
  zone, helper media e template, dashboard (solo se l'ha creata lei) e stato salvato.
  Fallo *prima* di disinstallare da HACS: la disinstallazione da HACS cancella solo
  i file e non esegue codice.
- **Tue modifiche**: se elimini un helper o una card, non ricompaiono al riavvio.
  *Configura* → **Ricrea helper e card della dashboard che ho eliminato** li rimette.
- **Opzioni**: *Configura* → dashboard sì/no.

## Aggiornamento dalla 1.x

Le vecchie voci (una per zona) vengono unite automaticamente in un'unica voce con
una zona per ciascuna. Gli helper esistenti restano e non vengono duplicati; da
quel momento sono gestiti dall'integrazione (eliminando la zona vengono eliminati).

## Note tecniche

Home Assistant non ha un'API Python pubblica per creare helper e dashboard gestiti
dalla UI. L'integrazione usa le stesse `StorageCollection` dei comandi websocket del
frontend (`input_number/*`, `input_boolean/*`, `lovelace/dashboards/*`) e i config
flow nativi di `template` e `min_max`. Essendo API interne, una futura versione di
Home Assistant potrebbe cambiarle: in quel caso l'integrazione va in "Riprova
configurazione" senza toccare gli helper esistenti.

## Sviluppo

```bash
pip install -r requirements_test.txt
pytest
```
