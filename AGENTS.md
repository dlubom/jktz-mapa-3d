# JKTZ mapa 3D

Osobna statyczna strona GitHub Pages. W `app/` jest interfejs Potree-Next,
w `scripts/` przygotowanie danych i witryny. Kataster pozostaje źródłem
zewnętrznym: build pobiera jego wydanie, nigdy nie wymaga sąsiedniego checkoutu.

## Dane i geometria

- `scripts/catalog.py resolve` przypina najnowszy stabilny release JKTZ raz
  do `.build/inputs.json`; istniejący plik jest odczytywany ponownie bez zmiany
  wydania. Nowe wejścia przygotuj w nowym katalogu/pliku.
- Zachowuj wszystkie odcinki, flagi, grupy i źródłowe Z. Scena używa EPSG:2180
  w kolejności easting/northing. Origin `[566000,153000,0]` służy precyzji
  renderowania. Nie dopasowuj terenu do otworów przesunięciem wysokości.
- ALS 2025 ma niepełny zasięg. `scripts/terrain.py coverage` liczy rzeczywiste
  pokrycie stacji z maski ważnych komórek 1 m. Szczegół ALS i regionalny NMT
  są oddzielnymi produktami. Zmiany źródeł i odtworzenie: `docs/TERRAIN.md`.
- Duże chmury są zasobem wydania wskazanym w `data/terrain.json`; w Git są
  kod, manifest i przypięty mały ZIP upstream. `dist/`, `.build/` i `output/`
  są generowane. Nie commituj ich.

## Praca i sprawdzenia

Po inicjalizacji repozytorium zmiany rozwijaj na gałęzi i w PR; przed scaleniem
wymagany jest zielony `check`. Publikuj na zlecenie użytkownika przez ręczny
workflow `pages.yml` z `main`. Re-run zachowuje wejścia danego uruchomienia.

Polecenia lokalnego builda i testów: `README.md`. Testy danych są w `tests/`.
Sprawdzaj realny widok w Chrome z WebGPU po zmianie renderera, transformacji
lub danych. CI testuje kod i transport, nie udaje odbioru na fizycznym GPU.
Po publikacji porównaj publiczne `publication.json` z dokładnym SHA i wejściami
uruchomienia, sprawdź Range 206 oraz widok z góry i pod powierzchnią.

Kod Potree-Next jest przypięty w `vendor/potree-next.json`, poprawki w
`scripts/patch_vendor.py`. Przy zmianie wersji przejrzyj je względem nowego
upstream i zachowaj AGPL oraz odsyłacz do źródeł opublikowanej wersji.
Dokumentacja i komunikaty są po polsku. Commity bez `Co-Authored-By`.
