# Teren ALS 2025

Teren jest osobnym, przypiętym zasobem wydania `terrain-2025-v1`. Nie trafia do
historii Git. Manifest [data/terrain.json](../data/terrain.json) zawiera adres
archiwum, jego rozmiar i SHA-256 oraz rozmiary i SHA-256 wszystkich 13 plików.
Budowa używa dokładnie tego zasobu, a nie automatycznego „latest”.

Archiwum `terrain-als2025-v1.zip` ma **203 513 837 B** i SHA-256:

```text
a87e5cb5c41c59b5087a4476beaa9cdea47785c8d68e9d42357bf0d8a3b8556a
```

ZIP używa DEFLATE na poziomie 6. Po rozpakowaniu pliki Potree mają te same bajty
co zweryfikowany prototyp; kompresja archiwum zmniejsza pobieranie wydania, nie
zmienia punktów ani transferów przeglądarki. Wydanie danych mieści się w limicie
2 GB pojedynczego zasobu GitHub Release. Adres docelowy zasobu jest zapisany
w manifeście; samo przygotowanie manifestu nie publikuje wydania.

## Co zawiera paczka

| Ścieżka | Znaczenie |
| --- | --- |
| `kozia/{metadata.json,hierarchy.bin,octree.bin}` | 8 820 406 oryginalnych punktów gruntu ALS 2025, klasa 2, bez punktów withheld; zachowane XYZ i RGB |
| `regional/{metadata.json,hierarchy.bin,octree.bin}` | 3 860 578 punktów wybranych co 4 m z oficjalnego NMT o siatce 1 m, wyprowadzonego z ALS 2025 |
| `coverage-mask.bin.gz`, `terrain-mask.json` | Dokładna ważność komórek natywnego NMT 1 m i opis georeferencji |
| `terrain-provenance.json` | Adresy i SHA-256 20 źródłowych arkuszy NMT oraz jednego LAZ, metadane, warunki użycia i konwersja |
| `provenance/` | Odczytane indeksy WFS, licencja PotreeConverter i zastosowany patch zgodności z macOS |

Punkty regionalne są pochodną rastra, nie surowymi odbiciami LiDAR. Ich kolor
przedstawia wysokość i nie jest zdjęciem lotniczym. Dane Koziej nie były
interpolowane ani przerzedzane. PotreeConverter tworzy z nich hierarchię LOD,
zachowując wszystkie punkty w całym drzewie. Przeglądarka wybiera potrzebne
węzły tej hierarchii zgodnie z położeniem kamery i budżetem punktów.

Współrzędne danych to **EPSG:2180**, kolejność **easting, northing, wysokość**,
w metrach; układ wysokości źródła to **PL-EVRF2007-NH**. Nie wprowadzono
dopasowanego przesunięcia wysokości. Konwersja do Potree używa skali 0,001 m;
jej błąd kwantyzacji jest ograniczony jednym krokiem 1 mm z zaokrągleniami IEEE.
Nie poprawia to dokładności źródła. Pełny odczyt 12 680 984 rekordów XYZ i RGB
potwierdził zgodność z wejściem po tej jawnej kwantyzacji, wraz z powtórzeniami.

Oficjalne metadane mają daty aktualności 10, 12 i 13 sierpnia 2025 r. Pole
`akt_data` nie zastępuje raportu z nalotu. Deklarowane błędy źródła nie dowodzą
takiej samej dokładności na każdej ścianie skalnej. Nie użyto starszego terenu
do wypełnienia braków ani korekty pionowej dopasowanej do jaskiń.

## Pobieranie i przeliczanie pokrycia

Wystarczy Python 3.9 lub nowszy i jego biblioteka standardowa. Pipeline nie
potrzebuje GDAL, NumPy, źródłowych plików ASC/LAZ ani sąsiedniego repozytorium.

```sh
python scripts/terrain.py fetch \
  --manifest data/terrain.json \
  --cache .build/terrain \
  --output dist/data

python scripts/terrain.py coverage \
  --terrain-dir dist/data \
  --caves .build/caves.json \
  --output dist/data/coverage.json
```

Można podać `.build/terrain` jako `--terrain-dir`. `fetch` weryfikuje wszystkie
pliki cache przed ponownym użyciem. Przy pobieraniu sprawdza rozmiar i SHA-256
ZIP-a, listę i rodzaj wpisów, a potem rozmiary i SHA-256 każdego rozpakowanego
pliku. Odrzuca m.in. ścieżki wychodzące z katalogu, dowiązania, duplikaty oraz
nadmiarowe wpisy. Błąd weryfikacji zatrzymuje budowę. Skrypt kopiuje tylko pliki
terenu i zachowuje niezależnie utworzony `caves.json` w katalogu wyjściowym.

Wejściowy model jaskiń musi mieć `crs: "EPSG:2180"` oraz listę `stations`.
Stacja zawiera `name` i bezwzględne `position: [easting, northing, z]`. Pokrycie
liczy każdy rekord stacji, również powtórzenia. Używa komórki natywnego NMT pod
XY stacji, nie odległości do rozrzedzonych punktów 4 m i nie wysokości stacji.
To informacja o dostępności terenu w danym XY, nie test dokładności pionowej.

Maska ma 18 136 × 5 394 komórek. Jej transformacja to
`[558965.5, 1, 0, 156502.5, 0, -1]`. Wiersze biegną z północy na południe,
kolumny z zachodu na wschód. Północna i zachodnia krawędź komórki należą do
niej; południowa i wschodnia należą do następnej komórki. Zewnętrzna południowa
lub wschodnia granica rastra leży poza maską. NoData i położenie poza maską
dają brak pokrycia. Bity są zapisane wierszami, od najstarszego bitu bajtu;
końcowe bity dopełnienia są zerowe. Gzip ma 32 242 B; po dekompresji maska
bitowa zajmuje 12 228 198 B. Nie zawiera wysokości.

Ważne komórki zajmują **61,780556 km²** w stałym zasięgu tej wersji terenu.
Dla modelu użytego przy kwalifikacji było to **6545 z 18 541 stacji (35,3%)**.
Liczba nie jest stałą strony: każde zbudowanie nowego modelu przelicza ją
ponownie. Stacje dodane poza zapisanym zasięgiem pozostają bez pokrycia do
świadomego wydania nowej paczki terenu. Grupy w raporcie pokrycia to pierwsze
prefiksy nazw stacji, nie identyfikatory jaskiń.

`coverage.json` udostępnia dla interfejsu `summary`, `description`,
`stationCount`, `coveredStations` i `percent`, a także szczegóły grup, metodę,
układ odniesienia i SHA-256 bieżącego modelu. Maska pozostaje w `dist/data`,
ale przeglądarka nie musi jej pobierać przy wyświetlaniu mapy.

## Pochodzenie, powtarzalność i aktualizacja

Źródłem danych jest **GUGiK / Państwowy Zasób Geodezyjny i Kartograficzny —
ALS 2025**. Oficjalne strony opisują bezpłatne dane i możliwość dowolnego
wykorzystania: [NMT](https://www.geoportal.gov.pl/pl/dane/numeryczny-model-terenu-nmt/)
oraz [LAS/LAZ](https://www.geoportal.gov.pl/pl/dane/dane-pomiarowe-lidar-lidar/).
Warunki te są odrębne od licencji kodu przeglądarki. Paczka zawiera pełną
atrybucję i datę sprawdzenia warunków, 16 listopada 2026 r.

Konwersję wykonano PotreeConverter 2.1.5, commit
`c2cb61843bf2b901e8e257874b1a6dcf67792fb2`, `--encoding DEFAULT --method poisson`.
Źródło, licencja, SHA-256 i ograniczony do zgodności platformowej patch są
zapisane w paczce. Archiwum nie zawiera prywatnych ścieżek lokalnych.

Pakowanie sortuje nazwy plików, ustawia czas ZIP na `1980-01-01 00:00:00`,
prawa zwykłych plików `0644`, system Unix i DEFLATE6. Dwa pakowania tym samym
środowiskiem dały identyczny SHA-256. Wszystkie 13 plików odczytano ponownie
z finalnego ZIP-a, sprawdzając CRC oraz przypięte SHA-256. Audyt po sklonowaniu
wymaga jedynie manifestu i wydania danych; nie wymaga dostępu do prototypu.

Aktualizacja terenu jest osobnym działaniem: pozyskanie i kwalifikacja nowych
źródeł, nowa maska i konwersja, nowe wydanie, a następnie jawna zmiana
manifestu. Samo odświeżenie modelu jaskiń nie podmienia danych ALS.

Testy uruchamia się lokalnie bez sieci:

```sh
python -m unittest discover -s tests -p 'test_terrain.py' -v
```
