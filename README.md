# Temperature Helper

Integrazione personalizzata per Home Assistant, installabile tramite HACS, che crea
**helper nativi** (`input_number`, `input_boolean`) per ogni zona di riscaldamento.

Gli helper creati sono identici a quelli creati a mano da
*Impostazioni → Dispositivi e servizi → Helper*: puoi modificarli, rinominarli o
eliminarli dall'interfaccia e restano anche se rimuovi l'integrazione.

## Cosa crea

Per ogni zona configurata (es. `Soggiorno`):

| Helper | Entity ID | Default |
|---|---|---|
| Soggiorno Temperatura Comfort | `input_number.soggiorno_temperatura_comfort` | 21 °C |
| Soggiorno Temperatura Eco | `input_number.soggiorno_temperatura_eco` | 18 °C |
| Soggiorno Temperatura Notte | `input_number.soggiorno_temperatura_notte` | 17 °C |
| Soggiorno Temperatura Assenza | `input_number.soggiorno_temperatura_assenza` | 15 °C |
| Soggiorno Temperatura Antigelo | `input_number.soggiorno_temperatura_antigelo` | 7 °C |
| Soggiorno Modalità Manuale | `input_boolean.soggiorno_modalita_manuale` | off |

Scegli quali setpoint creare, min/max e passo durante la configurazione.

## Dashboard

Se l'opzione **Aggiungi gli helper alla dashboard 'Temperature'** è attiva (default),
l'integrazione crea una dashboard nativa **Temperature** (`/temperature-helper`, nella
barra laterale) con una sezione per zona: titolo della zona + una tile per ogni helper
(pulsanti −/+ per i setpoint, tocco per la modalità manuale).

- **Temperatura media**: se una zona ha un sensore di temperatura (campo facoltativo
  in configurazione/opzioni), l'integrazione crea un unico helper nativo
  *Combina lo stato di più sensori* (`min_max`, tipo media) con i sensori di tutte
  le zone. È un helper normale: **rinominalo** da *Impostazioni → Helper* come vuoi.
- In cima alla dashboard c'è un grafico statistico **senza titolo** che mostra
  quell'helper: la legenda usa il suo nome, quindi rinominandolo cambia anche il grafico.
- L'helper resta anche rimuovendo l'integrazione; se lo elimini non viene ricreato
  (salvo l'opzione *Ricrea*).
- È una normale dashboard: la modifichi da *Modifica dashboard* come vuoi.
- Ogni helper viene aggiunto **una sola volta**: se togli una card o l'intera
  dashboard, non riappare al riavvio. Usa *Ricrea helper e card della dashboard
  che ho eliminato* nelle opzioni per rimetterle.
- Nuovi setpoint aggiunti dalle opzioni vengono accodati alla sezione della zona
  (riconosciuta dal titolo).
- Rimuovendo l'integrazione la dashboard **resta**.

## Installazione (HACS)

1. HACS → menu ⋮ → **Repository personalizzati**
2. URL: `https://github.com/umb-hub/Temperature_Helper`, categoria **Integrazione**
3. Installa **Temperature Helper** e riavvia Home Assistant
4. *Impostazioni → Dispositivi e servizi → Aggiungi integrazione* → **Temperature Helper**

Aggiungi l'integrazione una volta per ogni zona.

## Comportamento

- **Niente duplicati**: una sola voce per zona (stessa zona → "già configurata").
  Se esiste già un helper con lo stesso ID viene adottato, non ricreato.
- **Persistenza**: gli helper sono salvati in `.storage/input_number` e
  `.storage/input_boolean`, come quelli creati dalla UI. Riavvii e ricaricamenti
  non creano copie.
- **Rimozione**: eliminando l'integrazione gli helper **non** vengono eliminati.
- **Eliminazione manuale**: se elimini un helper, non viene ricreato al riavvio.
  Per ricrearlo: *Configura* sull'integrazione → spunta **Ricrea gli helper che ho eliminato**.
- **Opzioni**: aggiungere setpoint dalle opzioni crea i nuovi helper.
  Gli helper esistenti non vengono modificati (min/max/passo si cambiano dalla pagina Helper).

## Note tecniche

Home Assistant non ha un'API Python pubblica per creare helper gestiti dalla UI.
L'integrazione usa la stessa `StorageCollection` usata dai comandi websocket
`input_number/create` e `input_boolean/create` del frontend, quindi il risultato è
un helper nativo a tutti gli effetti. Essendo un'API interna, una futura versione di
Home Assistant potrebbe cambiarla: in quel caso l'integrazione va in "Riprova
configurazione" senza toccare gli helper esistenti.

## Sviluppo

```bash
pip install -r requirements_test.txt
pytest
```
