# Hver er þingmaðurinn?

Lítill Flask-veklingur sem notar SQLite með gögnum frá Althingi til að spyrja: „Hver er þingmaðurinn?“

## Forsendur
- Python 3.10+
- Virtuelt umhverfi mælt með: `python -m venv .venv && source .venv/bin/activate`
- Setja pakka: `pip install -r requirements.txt`

## Hlaða gögnum
```bash
python load_data.py --database data/thingmenn.db
```
Sækir XML lista af þingmönnum, nær í mynd slóð úr lífshlaups-síðunni, vistar í SQLite og bætir nú við
þingsetu-gögnum í töflunni `memberships` (þing, þingflokkur, tímabil).

## Keyra vefforrit
```bash
export FLASK_SECRET_KEY="skipta út fyrir leyniorð"
export THINGMADURINN_DB="data/thingmenn.db"  # sleppt ef sjálfgefinn staður hentar
python app.py
```
Opnaðu síðan `http://localhost:5000`.

## Uppbygging
- `load_data.py` — sækir og skrifar gögnin.
- `app.py` — Flask-bakendi með JSON-vistum fyrir spurningar/agískanir.
- `templates/index.html` — viðmót.
- `static/style.css` & `static/app.js` — stílar og lógík klientsins.

## Ný valmöguleg leikgerð
- Veldu leikgerð: „Hver er þingmaðurinn?“, „Í hvaða þingflokki var þingmaðurinn?“ eða blanda („Þekkir þú þingmennina?“).
- Veldu erfiðleikastig með 2–6 svarmöguleikum. Hver samsetning hefur sitt eigið stigatöfluborð.
