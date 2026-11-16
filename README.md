# JKTZ — mapa 3D Tatr

[Otwórz mapę 3D](https://dlubom.github.io/jktz-mapa-3d/) · [Mapa 2D](https://dlubom.github.io/jktz-mapa/) · [Kataster źródłowy](https://github.com/dlubom/Jaskiniowy-Kataster-Tatr-Zachodnich/releases/latest)

Rozwojowa przeglądarka poligonów jaskiń i gruntu ALS 2025 w Potree-Next/WebGPU.
Pozwala oglądać jaskinie z góry i spod powierzchni. Nie przesuwa wysokości
jaskiń ani terenu. Obsługa: lewy przycisk myszy obraca, prawy przesuwa, kółko
przybliża. Domyślny budżet to 1 mln punktów; można wybrać 2 lub 4 mln.

**Wymagana jest przeglądarka z działającym WebGPU.** Sprawdzono Chrome na
Apple M4. Nie ma fallbacku WebGL; fizycznych telefonów nie zakwalifikowano.

## Skąd pochodzą dane

- **Kataster:** najnowszy stabilny GitHub Release JKTZ, rozpoznawany przy każdym
  nowym uruchomieniu publikacji. Build zachowuje ID wydania i zasobu, tag,
  SHA-256 paczki i modelu. Nie czyta modelu z ruchomej witryny Pages.
- **Kozia:** 8 820 406 oryginalnych punktów ALS 2025 GUGiK, klasa gruntu,
  z RGB. Regionalny kontekst: 3 860 578 węzłów NMT 2025 próbkowanych co 4 m.
- **Zasięg:** niepełny. Dla JKTZ v2.0.1 ważny NMT obejmuje 35,3% stacji;
  kolejny build przelicza ten wskaźnik dla aktualnego modelu. Braki pozostają
  puste. Szczegóły i manifest źródeł: [docs/TERRAIN.md](docs/TERRAIN.md).
- XY sceny: EPSG:2180; Z terenu: PL-EVRF2007-NH. Z modelu zachowano ze źródła;
  zgodność datum całego modelu pozostaje niepotwierdzona.

Aktualne przypięcia i SHA kodu: [publication.json](https://dlubom.github.io/jktz-mapa-3d/publication.json).
Jest to chmura punktów gruntu, nie zamknięta bryła terenu ani model ścian jaskiń.

## Lokalnie

Python 3.12+, przypięty `dump3d` z Survex 1.4.24, działające WebGPU.
Ubuntu 24.04: zbuduj przypięty czytnik według
`.github/actions/setup/action.yml`; pakiet `survex` z dystrybucji jest za stary.
macOS: `brew install survex`, następnie sprawdź `dump3d --version`.
Czytnik 1.4.24 jest zapisany w manifeście narzędzia; nie jest potrzebna
kompilacja katastru w Walls.

```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements.txt
python scripts/catalog.py resolve --output .build/inputs.json
python scripts/catalog.py build --inputs .build/inputs.json --cache .build/catalog --output .build/caves.json
python scripts/terrain.py fetch --manifest data/terrain.json --cache .build/terrain --output dist/data
python scripts/terrain.py coverage --terrain-dir dist/data --caves .build/caves.json --output dist/data/coverage.json
python scripts/site.py build
python scripts/serve.py
```

Adres: <http://127.0.0.1:8768/jktz-mapa-3d/>. Pierwsze pobranie obejmuje paczkę
ALS i model katastru. Gotowa witryna zajmuje około 450 MB. `site.py build`
odtwarza aplikację i zachowuje przygotowane chmury. Pliki źródłowe katastru
i chmur pozostają nienaruszone.

Istniejący `.build/inputs.json` zachowuje poprzedni release. Aby świadomie
sprawdzić kolejny latest, użyj innego pliku przez `--output` i następnie
przekaż go do `build --inputs`. Opcjonalny `GH_TOKEN` ogranicza problem limitu
publicznego GitHub API; nie jest zapisywany w artefaktach ani wysyłany z ZIP.

## Testy i praca nad kodem

```sh
python -m unittest discover -s tests
node --experimental-vm-modules --test tests/loader_retry.cjs
python scripts/site.py verify
npm ci
node scripts/browser_smoke.cjs http://127.0.0.1:8768/jktz-mapa-3d/
```

Ostatnie polecenie używa zainstalowanego Google Chrome i rzeczywistego WebGPU.
Zapisuje wyniki i zrzuty w `output/playwright/`. Testy CI obejmują integralność
źródeł, zachowanie geometrii, NoData, artefakt i HTTP Range; nie zastępują testu
GPU. Mały viewport nie jest testem fizycznego telefonu.

Zmiany rozwijamy przez PR. `check` jest wymaganą kontrolą przed scaleniem.
Zachowane poprawki Potree dotyczą budżetu punktów, błędów pobierania,
żądań Range zgodnych z GitHub Pages, ponawiania przerwanych pobrań,
zmniejszania okna i wyłączenia
nieużywanego loadera LAS. Ograniczenie dekodera
do równych skal XYZ i offset=min jest sprawdzane podczas builda.

## Publikacja

Publikacja jest ręczna, z `main`, przez workflow **Pages — mapa 3D**:

```sh
gh workflow run pages.yml -R dlubom/jktz-mapa-3d --ref main
```

Pierwsza próba przypina latest i zachowuje `inputs-<run_id>` przez 90 dni.
Re-run pobiera to samo przypięcie; brak artefaktu kończy się błędem i wymaga
nowego uruchomienia. Teren jest wersjonowany osobno w `data/terrain.json`.
Build weryfikuje źródła i wynik przed wysłaniem artefaktu Pages. Duże pliki
BIN nie trafiają do historii Git. Po wdrożeniu workflow sprawdza publiczny
SHA i wejścia; renderowanie należy dodatkowo odebrać w przeglądarce.

## Licencje

Kod aplikacji i Potree-Next: **AGPL-3.0**, pełne źródła i poprawki są w tym
repozytorium. [LICENSE](LICENSE); biblioteki w upstream mają własne licencje.
Interfejs wskazuje źródła konkretnego opublikowanego SHA.

Poligony: autorzy Jaskiniowego Katastru Tatr Zachodnich, **CC BY-SA 4.0**,
zgodnie z wydaniem źródłowym. Teren: **GUGiK / Państwowy Zasób Geodezyjny
i Kartograficzny — ALS 2025**, warunki i pochodzenie w docs/TERRAIN.md.
Licencja kodu nie zmienia warunków danych.
