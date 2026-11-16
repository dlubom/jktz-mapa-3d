# JKTZ mapa 3D — publikacja prototypu

> **For agentic workers:** Wykonuj niezależne części równolegle, a następnie zweryfikuj cały zbudowany pakiet i publiczny rezultat.

**Goal:** Osobne publiczne repozytorium dlubom/jktz-mapa-3d i działające GitHub Pages z najnowszym stabilnym release JKTZ.

**Architecture:** Statyczny Potree-Next z zaakceptowanego lokalnego prototypu. Build przypina raz latest JKTZ; ALS pozostaje przypiętym, sprawdzonym zasobem wydania terrain-2025-v1. Pages dostaje gotowy katalog przez artefakt Actions. Nowa publikacja jest ręczna, przyszłe zmiany kodu przechodzą PR i CI.

**Tech Stack:** JavaScript modules/WebGPU; Python 3.12+, pyproj, dump3d; GitHub Actions/Pages.

**Spec:** Polecenie użytkownika po odbiorze prototypu: osobne repo jak jktz-mapa, opublikuj, kataster z latest release. Istniejący RAPORT prototypu określa renderowanie, dane i ograniczenia.

## Global Constraints

- Zachowaj XYZ źródeł; tylko udokumentowana reprojekcja XY, bez dopasowania Z.
- Wszystkie grupy i odcinki modelu release; liczby nie są stałymi kontraktowymi.
- Pełne źródła aplikacji i patch Potree publiczne; duże binaria poza historią Git.
- Brak pokrycia ALS 2025 pozostaje jawny; jego procent liczony względem aktualnego modelu.
- Publikacja jest już autoryzowana w tej sesji. Stare ograniczenie „bez publikacji” dotyczyło poprzedniego prototypu i zostało zastąpione.

## Review Focus

- Ruchomy latest między etapami: jeden inputs.json na run, rerun używa zachowanych pinów.
- Uszkodzony ZIP lub niejednoznaczne modele: odmowa builda, zachowana produkcja.
- Zmiana liczby jaskiń/stacji: dynamiczne grupy i pokrycie, brak przycięcia do starego modelu.
- Brak WebGPU / Range / NoData: czytelny komunikat, bez fikcyjnego terenu.
- Zielony deploy bez widocznego terenu: publiczny readback manifestu i test realnej przeglądarki.

## Zadania

- [x] scripts/catalog.py + tests: resolve/fetch/model z najnowszego release, testy integralności i geometrii.
- [x] scripts/terrain.py + data/terrain.json + tests: trwały ZIP ALS, mapa ważności i dynamiczne pokrycie.
- [x] app/, scripts/site.py, scripts/serve.py: przeniesienie sprawdzonego podglądu, provenance, względne ścieżki, test lokalny.
- [x] README, AGENTS, LICENSE, workflows: samodzielne repo, CI i ręczny Pages, zachowanie pinów.
- [ ] Lokalny build/test/review; dopiero potem utworzenie repo, commit/push, zasób ALS i deploy.
- [ ] Zielone CI dla dokładnego SHA, publiczny manifest i renderowanie; lokalny checkout w ~/proj/jktz-mapa-3d.

Nazwę repo i oszczędne ustawienie startu 1 mln punktów dobrał wykonawca zgodnie z wcześniejszą rekomendacją. Nie wdrażamy nowych warstw mapy 2D ani pełnego ALS całych Tatr.
