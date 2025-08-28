@echo off
REM ---------------- [ TwLive3.0 RUNNER ] ----------------
REM 1) mergem în folderul proiectului
cd /d C:\Users\cosmi\Desktop\TwLive3.0

REM 2) creăm/activăm mediul virtual (o singură dată este creat)
if not exist ".venv" (
  python -m venv .venv
)

call .venv\Scripts\activate

REM 3) actualizăm pip + instalăm dependențele din requirements.txt
python -m pip install --upgrade pip
pip install -r requirements.txt

REM 4) rulăm scraper-ul ca să avem date
python scraper\scraper.py

REM 5) pornim serverul Flask (CTRL+C pentru oprire)
python app.py
