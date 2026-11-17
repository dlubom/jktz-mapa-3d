# Teren mapy 3D

Build pobiera przypięty zasób `terrain-v3.zip` z wydania `terrain-v3`.
[Manifest terenu](../data/terrain.json) podaje URL, rozmiar i SHA-256 ZIP-a
oraz każdego pliku po rozpakowaniu. Współrzędne XY są w EPSG:2180 (easting,
northing). Wysokości GUGiK są w PL-EVRF2007-NH, a DMR 5.0 w EVRF2007
(EPSG:5621). Poligony zachowują źródłowe Z.

## Warstwy

| Warstwa | Dane | Punkty | Pokrycie stacji JKTZ v2.0.1 |
| --- | --- | ---: | ---: |
| `tatry` | NMT 2019 ze zdjęć lotniczych (5 m) i DMR 5.0 z ALS w lukach (1 m) | 6 936 620 | 18 541 / 18 541 (100%) |
| `regional` | NMT z ALS 2025, węzły z siatki 1 m wybrane co 4 m | 3 860 578 | 6 545 / 18 541 (35,3%) |
| `kozia` | ALS 2025, punkty gruntu klasy 2 bez punktów withheld, z RGB | 8 820 406 | Lokalny szczegół Koziej |

Domyślnie wszystkie jaskinie i widok całego JKTZ używają modelu regionalnego
z uzupełnieniem DMR. Selektor „Źródło terenu” pozwala wybrać inną warstwę,
w tym lokalny szczegół Koziej. Wybór obowiązuje przy zmianie jaskini i widoku
do następnego wczytania strony. Kolor punktów NMT i DMR koduje wysokość.
Obie chmury ALS 2025 mają te same sumy SHA-256
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

NMT 2019 obejmuje 18 323 stacje. Wycinek DMR 5.0 obejmuje pozostałe 218
stacji w grupach `NovaKresanica` (155) i `ObcasnaVyv` (63). Z natywnego
rastra 1 m EPSG:3046 przeliczono wysokości elipsoidalne ETRS89 według
EPSG:8362. Odjęto biliniowo odczytane odstępy quasi-geoidy DMQSK2014-E.
Korekta w wycinku wynosi od −42,687 do −42,584 m. Porównanie 256 próbek
PROJ z oddzielnym odczytem siatki GTX dało maksymalną różnicę poniżej 1 µm.
[Dane DMR 5.0](https://www.gku.sk/geoportal/zbgis/zbgis/udaje-zbgis/) ·
[Instrukcja transformacji GKÚ, §7](https://www.gku.sk/files/gku/produkty-sluzby/na-stiahnutie/navod-dmr-qgis.pdf).

Na siatce wyjściowej 1 m w EPSG:2180 użyto najbliższej komórki źródłowej DMR.
Zachowano tylko próbki leżące poza ważnymi komórkami polskiego NMT. Chmura
zawiera wszystkie 4 745 903 punkty NMT oraz 2 190 717 punktów DMR. Dane
dodatkowe dotyczą wycinka 2,05 × 1,25 km w EPSG:3046.

### Styk modeli

Porównano DMR minus NMT w środkach ważnych polskich komórek. Wysokość DMR
odczytano biliniowo z czterech ważnych komórek natywnych. Na krawędzi liczono
podzbiór z co najmniej jednym sąsiednim NoData NMT w czterech kierunkach.

| Próbki | Liczba | Mediana | 95. percentyl wartości bezwzględnej | Minimum / maksimum |
| --- | ---: | ---: | ---: | ---: |
| Wspólne pokrycie | 14 735 | −0,30 m | 2,23 m | −24,44 / +39,96 m |
| Krawędź NMT | 488 | −0,52 m | 7,59 m | −10,46 / +14,44 m |

Lokalnie na styku można zobaczyć uskok. Zachowano wysokości obu modeli
bez wyrównywania ani wygładzania. `dmr5-provenance.json` zawiera metodę,
pełne statystyki oraz współrzędne i wysokości skrajnych próbek.

`terrain-mask.json` opisuje natywną siatkę 5 m, `dmr5-mask.json` uzupełnienie
po reprojekcji na siatkę 1 m, a `terrain-mask-als2025.json` maskę ALS 1 m.
Każda maska używa jednego bitu
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
Generator pobiera polskie arkusze według manifestu i sprawdza ich sumy przed
użyciem. Oryginalny wycinek WCS i ZIP quasi-geoidy są w `provenance/dmr5/`
w paczce. [Manifest źródeł DMR](../data/dmr5-sources.json) podaje adresy i sumy.

```sh
mkdir -p .build
git show terrain-v2:data/terrain.json > .build/terrain-v2.json
python scripts/terrain.py fetch --manifest .build/terrain-v2.json \
  --cache .build/terrain-v2 --output .build/terrain-v2
python scripts/prepare_dmr5.py --base .build/terrain-v2 \
  --base-manifest .build/terrain-v2.json --dmr-sources dist/data/provenance/dmr5 \
  --nmt-sources .build/nmt2019-sources --output .build/terrain-v3-rebuild \
  --converter /ścieżka/do/PotreeConverter
```

Pakowanie wytwarza ZIP i odpowiadający mu manifest w podkatalogu `release/`.
Przed zmianą manifestu
wydania sprawdź sumy rozpakowanych plików, pokrycie bieżącego katastru,
budżet rozmiaru Pages i oba widoki w Chrome z WebGPU.

Teren to **GUGiK / Państwowy Zasób Geodezyjny i Kartograficzny**.
GUGiK udostępnia dane bezpłatnie do dowolnego wykorzystania.
[Warunki NMT](https://www.geoportal.gov.pl/pl/dane/numeryczny-model-terenu-nmt/)
· [Warunki LAS/LAZ](https://www.geoportal.gov.pl/pl/dane/dane-pomiarowe-lidar-lidar/).

DMR 5.0 oraz DMQSK2014-E pochodzą od **GKÚ Bratislava**, CC BY 4.0.
[Warunki WCS](https://www.skgeodesy.sk/geoportal/inspire/ukladacie-sluzby/)
· [Quasi-geoida](https://www.gku.sk/gku/produkty-sluzby/na-stiahnutie/geodeticke-zaklady.html).
