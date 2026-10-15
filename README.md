# Lane Finding Project

Koraci projekta:

* Izračunati matricu kamere i koeficijente distorzije iz slika šahovske table.
* Ispraviti distorziju na sirovim slikama.
* Koristiti prelaze boja i gradijente za binarnu sliku.
* Primeniti perspektivnu transformaciju ("bird's-eye view").
* Detektovati piksele trake i fitovati polinom. *(sledeći korak)*
* Odrediti krivinu trake i poziciju vozila u odnosu na centar. *(sledeći korak)*
* Vratiti detektovanu traku na originalnu sliku. *(sledeći korak)*
* Prikazati rezultat sa numeričkim vrednostima. *(sledeći korak)*

## Pokretanje

```bash
pip install -r requirements.txt
python src/calibrate_camera.py   # kalibracija -> output/calibration.npz
python src/pipeline.py           # koraci 1-3 nad test_images/ -> output_images/
```

## Camera Calibration

#### 1. Kako su izračunati matrica kamere i koeficijenti distorzije

Kod je u `src/calibrate_camera.py`. Za svaku od 20 slika šahovske table u `camera_cal/` pozivam `cv.findChessboardCorners` i preciziram uglove sa `cv.cornerSubPix`. Pripremljene su "objektne tačke" `objp`: 3D koordinate uglova table u jedinicama polja, sa `z = 0` (tabla je ravna). Za svaku uspešno pronađenu tablu dodajem `objp` u `objpoints`, a pronađene uglove u `imgpoints`.

Slike 1, 4 i 5 su isečene i na njima ne postoji ceo obrazac 9x6, pa kod redom isprobava rezervne obrasce (9x5, 6x5, 7x6). Tako je iskorišćeno svih 20 slika.

Zatim `cv.calibrateCamera` daje matricu kamere i distorziju. Rezultati se čuvaju u `output/calibration.npz`.

| Stavka | Vrednost |
|---|---|
| RMS greška | 0.996 px |
| fx, fy | 1161.3, 1158.5 px |
| cx, cy | 666.7, 389.6 px |
| [k1, k2, p1, p2, k3] | -0.258, 0.062, -0.0002, -0.0001, -0.148 |

Primer ispravljene slike (levo original, desno ispravljeno):

![Undistorted](./examples/undistort_output.jpg)

## Pipeline (single images)

#### 1. Primer slike sa ispravljenom distorzijom

Funkcija `undistort()` u `src/pipeline.py` učitava `calibration.npz` i poziva `cv.undistort`. Najviše se vidi na ivicama slike i na haubi automobila (levo original, desno ispravljeno):

![Road Transformed](./examples/road_undistorted.jpg)

#### 2. Binarna slika (boja + gradijent)

Funkcija `threshold()` u `src/pipeline.py` kombinuje dva kriterijuma operatorom OR:

* **S kanal HLS prostora** (prag 170-255): hvata žute i bele trake i dosta je otporan na promene osvetljenja.
* **Sobel po x nad L kanalom** (prag 20-100): hvata skoro vertikalne ivice, odnosno linije trake.

Pored toga, maskiram piksele sa svetlinom L < 120, jer senke imaju visok S kanal, a traka ne može biti tamna. Bez ove maske senke drveća daju mnogo lažnih piksela.

![Binary Example](./examples/binary_combo_example.png)

#### 3. Perspektivna transformacija

Funkcija `warp()` u `src/pipeline.py` koristi `cv.getPerspectiveTransform` i `cv.warpPerspective`. Izvorne tačke sam odabrao ručno na slici `straight_lines1.jpg`, a odredišne tako da trake postanu vertikalne i paralelne:

| Tačka | Izvor (src) | Odredište (dst) |
|---|---|---|
| gore levo | (595, 450) | (300, 0) |
| gore desno | (690, 450) | (980, 0) |
| dole desno | (1115, 720) | (980, 720) |
| dole levo | (216, 720) | (300, 720) |

Provera: na slici sa pravim putem obe trake posle transformacije postaju paralelne vertikalne linije (crveni trapez levo, ptičija perspektiva desno).

![Warp Example](./examples/warped_straight_lines.jpg)

Funkcija `warp()` vraća i inverznu matricu `Minv`, koja će trebati za vraćanje trake na originalnu sliku.

#### 4. Detekcija piksela trake i fit polinoma

TODO

#### 5. Krivina i pozicija vozila

TODO

#### 6. Rezultat ucrtan na put

TODO

## Pipeline (video)

TODO

## Discussion

TODO
