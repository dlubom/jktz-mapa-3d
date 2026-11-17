# Teren mapy 3D

Build pobiera przypięty zasób `terrain-v2.zip` z wydania `terrain-v2`.
[Manifest terenu](../data/terrain.json) podaje URL, rozmiar i SHA-256 ZIP-a
oraz każdego pliku po rozpakowaniu. Współrzędne XY są w EPSG:2180 (easting,
northing), a wysokości terenu w PL-EVRF2007-NH. Poligony zachowują źródłowe Z.

## Warstwy

| Warstwa | Dane | Punkty | Pokrycie stacji JKTZ v2.0.1 |
| --- | --- | ---: | ---: |
| `nmt2019` | NMT ze zdjęć lotniczych, natywna siatka 5 m | 4 745 903 | 18 323 / 18 541 (98,8%) |
| `regional` | NMT z ALS 2025, węzły z siatki 1 m wybrane co 4 m | 3 860 578 | 6 545 / 18 541 (35,3%) |
| `kozia` | ALS 2025, punkty gruntu klasy 2 bez punktów withheld, z RGB | 8 820 406 | Lokalny szczegół Koziej |

Widok całego JKTZ i wybór jaskiń poza Kozią używają NMT 2019. Selektor
pozwala porównać warstwy bez łączenia powierzchni z różnych kampanii. Kolor
punktów NMT koduje wysokość. Obie chmury ALS 2025 mają te same sumy SHA-256
co w [pierwszym wydaniu danych](https://github.com/dlubom/jktz-mapa-3d/releases/tag/terrain-2025-v1).

## Źródła i pokrycie

NMT 2019 pochodzi z 40 arkuszy GUGiK projektu `DFT.7201.003.2019`, w formacie
ARC/INFO ASCII GRID, z datami aktualności 4 lipca lub 1 września 2019 r.
[Manifest źródeł](../data/nmt2019-sources.json) przypina arkusze i odpowiedź
skorowidza WFS. Mozaika zachowuje środki komórek i wysokości. Odrzucono
NoData oraz cztery próbki 0,165 m w arkuszu `M-34-100-B-d-1-3`. Ich
współrzędne zawiera `nmt2019-provenance.json`. Ważne komórki zajmują
118,647575 km². Pełny odczyt Potree potwierdził zgodność XYZ i RGB z wejściem
LAS po kwantyzacji Potree na siatce 1 mm.

NMT 2019 dodaje pokrycie 11 778 stacji względem regionalnego NMT z ALS 2025.
W arkuszach granicznych pola pod grupami `NovaKresanica` (155 stacji)
i `ObcasnaVyv` (63 stacje) mają NoData. Słowacki DMR 5.0 obejmuje obie
grupy w pobranych wycinkach z elipsoidalnymi wysokościami GRS80. GKÚ udostępnia
model quasi-geoidy DMQSK2014-E do przeliczenia ich na EVRF2007. Przed użyciem
trzeba zweryfikować transformację i zgodność na styku z polskim NMT.
[Dane DMR 5.0](https://www.gku.sk/geoportal/zbgis/zbgis/udaje-zbgis/)
· [Instrukcja transformacji GKÚ, §7](https://www.gku.sk/files/gku/produkty-sluzby/na-stiahnutie/navod-dmr-qgis.pdf).

`terrain-mask.json` opisuje natywną siatkę 5 m. `terrain-mask-als2025.json`
zachowuje opis maski 1 m z poprzedniej paczki. Każda maska używa jednego bitu
na komórkę, zapisywanego od najstarszego bitu bajtu, wierszami od północy.
`terrain.py coverage` liczy ważną komórkę pod XY każdego rekordu stacji,
również gdy jego współrzędne się powtarzają. Północna i zachodnia krawędź
należą do komórki. Stacje poza zasięgiem lub w NoData to braki. `coverage.json`
raportuje pokrycie, a nie dokładność pionową. Dane źródłowe ALS 2025 i
przeliczenie krok po kroku opisuje `terrain-provenance.json` z archiwum.

## Odtworzenie

Do zwykłej budowy witryny wystarcza procedura z [README](../README.md).
Przygotowanie nowej paczki wymaga GDAL z Pythonem, NumPy, laspy, pyproj i
PotreeConverter 2.1.5, commit `c2cb61843bf2b901e8e257874b1a6dcf67792fb2`.
Paczka zawiera licencję i poprawkę kompilacji konwertera na macOS.
Generator pobiera arkusze według manifestu i sprawdza ich sumy przed użyciem.

```sh
mkdir -p .build
git show terrain-2025-v1:data/terrain.json > .build/terrain-2025-v1.json
python scripts/terrain.py fetch --manifest .build/terrain-2025-v1.json \
  --cache .build/als2025 --output .build/als2025
python scripts/prepare_nmt2019.py --source-dir .build/nmt2019-sources \
  --output .build/nmt2019-rebuild/data --converter /ścieżka/do/PotreeConverter
python scripts/pack_terrain.py --base .build/als2025 \
  --base-manifest .build/terrain-2025-v1.json --nmt .build/nmt2019-rebuild/data \
  --sources data/nmt2019-sources.json --index dist/data/provenance/nmt2019-index.gml \
  --output .build/nmt2019-rebuild/release
```

Argument `--index` wskazuje zachowaną odpowiedź WFS z gotowej paczki.
Pakowanie wytwarza ZIP i odpowiadający mu manifest. Przed zmianą manifestu
wydania sprawdź sumy rozpakowanych plików, pokrycie bieżącego katastru,
budżet rozmiaru Pages i oba widoki w Chrome z WebGPU.

Teren to **GUGiK / Państwowy Zasób Geodezyjny i Kartograficzny**.
GUGiK udostępnia dane bezpłatnie do dowolnego wykorzystania.
[Warunki NMT](https://www.geoportal.gov.pl/pl/dane/numeryczny-model-terenu-nmt/)
· [Warunki LAS/LAZ](https://www.geoportal.gov.pl/pl/dane/dane-pomiarowe-lidar-lidar/).
