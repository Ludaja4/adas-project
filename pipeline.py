"""Lane finding pipeline (ADAS) - svi koraci u jednom fajlu.

Koraci:
  1. kalibracija kamere (sahovska tabla)        -> calibrate()
  2. ispravljanje distorzije                    -> undistort()
  3. binarna slika (boja + gradijent)           -> threshold()
  4. perspektivna transformacija (bird's-eye)   -> warp()
  5. detekcija piksela trake (Hough) + polinom  -> find_lane_points(), fit_lanes()
  6. radijus krivine i pozicija vozila          -> measure()

Pokretanje:
  python pipeline.py                  # sve slike iz img/ (test*.jpg i straight_lines*.jpg)
  python pipeline.py img/test1.jpg    # jedna slika
  python pipeline.py --recalibrate    # ponovo izracunaj img/calib.npz
U prozoru: bilo koji taster = sledeca slika, ESC = izlaz.
"""
import glob
import os
import sys
import numpy as np
import cv2 as cv

# ---------------------------------------------------------------- konstante
# Putanje su vezane za folder u kom je pipeline.py, pa radi iz bilo kog radnog foldera
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
IMG_DIR = os.path.join(BASE_DIR, "img")
CALIB_FILE = os.path.join(IMG_DIR, "calib.npz")
CALIB_IMAGES = os.path.join(IMG_DIR, "calibration*.jpg")

# Dimenzije table = broj UNUTRASNJIH uglova (cols, rows). Neke slike su isecene i nemaju ceo
# obrazac 9x6, pa se redom isprobavaju i manji obrasci.
CHESSBOARD_PATTERNS = [(9, 6), (9, 5), (6, 5), (7, 6), (9, 4), (8, 6), (5, 6)]

# Trapez na putu (SRC) -> pravougaonik u pticijoj perspektivi (DST), za slike 1280x720
SRC = np.float32([[595, 450], [690, 450], [1115, 720], [216, 720]])
DST = np.float32([[300, 0], [980, 0], [980, 720], [300, 720]])

# Delovi warped slike koji se ignorisu pri Hough pretrazi (sum: rub puta, hauba)
LEFT_LIMIT, RIGHT_LIMIT, BOTTOM_LIMIT = 200, 1180, 660

LANE_WIDTH_PX = 680    # 980 - 300 iz DST tacaka
MIN_COVERAGE = 5       # bar 5 od 9 horizontalnih segmenata mora imati duzi trake
YM_PER_PIX = 30 / 720  # oko 30 m puta u vidnom polju (pretpostavka)
XM_PER_PIX = 3.7 / 680  # traka 3.7 m = 680 px (pretpostavka)


def read_image(path):
    """Ucitavanje slike koje radi i sa putanjama sa razmacima i ne-ASCII znacima (Windows).
    cv.imread na Windowsu moze da vrati None za takve putanje; ovde se fajl cita preko numpy-a."""
    try:
        data = np.fromfile(path, dtype=np.uint8)
        return cv.imdecode(data, cv.IMREAD_COLOR) if data.size else None
    except OSError:
        return None


# ---------------------------------------------------------------- 1. kalibracija
def calibrate(pattern_glob=CALIB_IMAGES, out_file=CALIB_FILE, verbose=True):
    criteria = (cv.TERM_CRITERIA_MAX_ITER + cv.TERM_CRITERIA_EPS, 30, 0.001)
    objectPointsArray, imgPointsArray = [], []
    gray = None

    paths = sorted(glob.glob(pattern_glob))
    if not paths:
        raise SystemExit(f"Nema slika za kalibraciju: {pattern_glob}\n"
                         f"Proveri da li je folder img/ pored pipeline.py i da sadrzi calibration*.jpg.")

    for path in paths:
        image = read_image(path)
        if image is None:
            print(path, "- slika se ne moze ucitati")
            continue
        gray = cv.cvtColor(image, cv.COLOR_BGR2GRAY)
        for (cols, rows) in CHESSBOARD_PATTERNS:
            ret, corners = cv.findChessboardCorners(gray, (cols, rows), None)
            if ret:
                break
        if not ret:
            if verbose:
                print(path, "- tabla nije pronadjena")
            continue

        corners = cv.cornerSubPix(gray, corners, (11, 11), (-1, -1), criteria)
        # Objektne tacke: (0,0,0), (1,0,0), ... z=0, jedinica = jedno polje table
        objectPoints = np.zeros((rows * cols, 3), np.float32)
        objectPoints[:, :2] = np.mgrid[0:cols, 0:rows].T.reshape(-1, 2)
        objectPointsArray.append(objectPoints)
        imgPointsArray.append(corners)

    if not objectPointsArray or gray is None:
        raise SystemExit("Sahovska tabla nije pronadjena ni na jednoj slici za kalibraciju.")

    ret, mtx, dist, rvecs, tvecs = cv.calibrateCamera(
        objectPointsArray, imgPointsArray, gray.shape[::-1], None, None)
    np.savez(out_file, mtx=mtx, dist=dist, rvecs=rvecs, tvecs=tvecs)

    if verbose:
        error = 0
        for i in range(len(objectPointsArray)):
            proj, _ = cv.projectPoints(objectPointsArray[i], rvecs[i], tvecs[i], mtx, dist)
            error += cv.norm(imgPointsArray[i], proj, cv.NORM_L2) / len(proj)
        print(f"Kalibracija: {len(objectPointsArray)} slika, RMS = {ret:.3f} px, "
              f"Total error = {error / len(objectPointsArray):.3f}")
    return mtx, dist


def load_calibration(force=False):
    if force or not os.path.exists(CALIB_FILE):
        return calibrate()
    data = np.load(CALIB_FILE)
    return data["mtx"], data["dist"]


# ---------------------------------------------------------------- 2. undistort
def undistort(img, mtx, dist):
    return cv.undistort(img, mtx, dist, None, mtx)


# ---------------------------------------------------------------- 3. binarna slika
def threshold(img, s_thresh=(170, 255), sx_thresh=(20, 100), l_min=120):
    """S kanal (HLS) + Sobel po x nad L kanalom + maska za senke. Vraca 0/255 sliku."""
    hls = cv.cvtColor(img, cv.COLOR_BGR2HLS)
    l_ch = hls[:, :, 1]
    s_ch = hls[:, :, 2]

    sobelx = np.absolute(cv.Sobel(l_ch, cv.CV_64F, 1, 0, ksize=3))
    scaled = np.uint8(255 * sobelx / max(np.max(sobelx), 1e-6))

    sx_bin = (scaled >= sx_thresh[0]) & (scaled <= sx_thresh[1])
    s_bin = (s_ch >= s_thresh[0]) & (s_ch <= s_thresh[1])
    bright = l_ch >= l_min  # senke su tamne -> nisu traka

    return np.uint8((sx_bin | s_bin) & bright) * 255


# ---------------------------------------------------------------- 4. perspektiva
def warp(img, src=SRC, dst=DST):
    transMat = cv.getPerspectiveTransform(src, dst)
    dimensions = (img.shape[1], img.shape[0])
    return cv.warpPerspective(img, transMat, dimensions, flags=cv.INTER_LINEAR), transMat


# ---------------------------------------------------------------- 5a. Hough
def find_lane_points(warped):
    """HoughLinesP nad warped binarnom slikom. Duzi se dele na levu i desnu traku i
    pretvaraju u tacke (na svakih ~2 px, pa duze duzi imaju veci uticaj na fit)."""
    mask = warped.copy()
    mask[:, :LEFT_LIMIT] = 0
    mask[:, RIGHT_LIMIT:] = 0
    mask[BOTTOM_LIMIT:, :] = 0

    lines = cv.HoughLinesP(mask, rho=1, theta=np.pi / 180, threshold=30,
                           minLineLength=30, maxLineGap=40)

    left_x, left_y, right_x, right_y = [], [], [], []
    seg_left, seg_right = [], []
    if lines is not None:
        for line in lines:
            x1, y1, x2, y2 = np.asarray(line).reshape(-1)[:4]
            # trake su skoro vertikalne: odbaci duzi nagnute vise od ~35 stepeni
            if abs(x2 - x1) > 0.7 * abs(y2 - y1):
                continue
            n = int(np.hypot(x2 - x1, y2 - y1) / 2) + 1
            xs = np.linspace(x1, x2, n)
            ys = np.linspace(y1, y2, n)
            if (x1 + x2) / 2 < warped.shape[1] // 2:
                left_x += list(xs); left_y += list(ys); seg_left.append((x1, y1, x2, y2))
            else:
                right_x += list(xs); right_y += list(ys); seg_right.append((x1, y1, x2, y2))

    view = cv.cvtColor(mask, cv.COLOR_GRAY2BGR)
    for (x1, y1, x2, y2) in seg_left:
        cv.line(view, (x1, y1), (x2, y2), (0, 0, 255), 3)   # crveno = leva
    for (x1, y1, x2, y2) in seg_right:
        cv.line(view, (x1, y1), (x2, y2), (255, 0, 0), 3)   # plavo = desna

    return dict(left_x=np.array(left_x), left_y=np.array(left_y),
                right_x=np.array(right_x), right_y=np.array(right_y), view=view)


# ---------------------------------------------------------------- 5b. polinom
def _coverage(ys, height):
    # broj segmenata visine (po h/9 px) koji imaju bar 15 tacaka (~30 px duzi)
    return int((np.histogram(ys, bins=9, range=(0, height))[0] >= 15).sum())


def _line_inliers(xs, ys, iterations=300, max_dist=40):
    """RANSAC za PRAVU liniju (2 tacke -> stabilno): tacke suma ostaju daleko od nje."""
    rng = np.random.default_rng(0)  # fiksan seed -> isti rezultat pri svakom pokretanju
    best, best_count = np.ones(len(xs), bool), 0
    for _ in range(iterations):
        i, j = rng.choice(len(xs), 2, replace=False)
        if abs(ys[i] - ys[j]) < 50:
            continue
        a = (xs[i] - xs[j]) / (ys[i] - ys[j])
        b = xs[i] - a * ys[i]
        inliers = np.abs(a * ys + b - xs) < max_dist
        if inliers.sum() > best_count:
            best, best_count = inliers, inliers.sum()
    return best


def fit_lanes(points, height):
    """Polinom x = A*y^2 + B*y + C (y je nezavisna jer su trake skoro vertikalne).
    U pticijoj perspektivi su trake paralelne -> dele A i B, razlikuju se samo u C.
    Fit koristi SVE tacke obe trake odjednom (stabilnije nego dva odvojena fita nad
    kratkim Hough duzima). Vraca None ako nijedna traka nije pronadjena."""
    lx, ly = points["left_x"], points["left_y"]
    rx, ry = points["right_x"], points["right_y"]
    ok_left = len(lx) >= 10 and _coverage(ly, height) >= MIN_COVERAGE
    ok_right = len(rx) >= 10 and _coverage(ry, height) >= MIN_COVERAGE
    if not ok_left and not ok_right:
        return None

    # tacke pouzdanih traka (posle izbacivanja suma), sa oznakom kojoj traci pripadaju
    xs, ys, is_left, is_right = [], [], [], []
    for ok, px, py, side in ((ok_left, lx, ly, 0), (ok_right, rx, ry, 1)):
        if not ok:
            continue
        keep = _line_inliers(px, py)
        xs.append(px[keep]); ys.append(py[keep])
        is_left.append(np.full(keep.sum(), side == 0))
        is_right.append(np.full(keep.sum(), side == 1))
    xs, ys = np.concatenate(xs), np.concatenate(ys)
    is_left = np.concatenate(is_left).astype(float)
    is_right = np.concatenate(is_right).astype(float)

    # zajednicki fit: kolone [y^2, y, (1 za levu), (1 za desnu)], samo za trake koje postoje
    cols = [ys ** 2, ys]
    if ok_left:
        cols.append(is_left)
    if ok_right:
        cols.append(is_right)
    design = np.column_stack(cols)

    keep = np.ones(len(xs), bool)
    for _ in range(3):  # fit, pa izbaci tacke dalje od 25 px od krive, pa ponovo
        coef = np.linalg.lstsq(design[keep], xs[keep], rcond=None)[0]
        inliers = np.abs(design @ coef - xs) < 25
        if inliers.sum() >= 10:
            keep = inliers
    A, B = coef[0], coef[1]
    c_values = list(coef[2:])
    c_left = c_values.pop(0) if ok_left else None
    c_right = c_values.pop(0) if ok_right else None

    # ako jedna traka nema dovoljno duzi (npr. isprekidana linija), izvedi je iz druge
    if c_left is None:
        c_left = c_right - LANE_WIDTH_PX
    if c_right is None:
        c_right = c_left + LANE_WIDTH_PX

    ploty = np.linspace(0, height - 1, height)
    return dict(left_fit=np.array([A, B, c_left]), right_fit=np.array([A, B, c_right]),
                ploty=ploty, left_fitx=np.polyval([A, B, c_left], ploty),
                right_fitx=np.polyval([A, B, c_right], ploty),
                ok_left=ok_left, ok_right=ok_right, lane_width_px=c_right - c_left)


# ---------------------------------------------------------------- 6. krivina i pozicija
def measure(fit, img_width):
    """Radijus krivine [m] na dnu slike i pozicija vozila u odnosu na centar trake [m]."""
    ploty = fit["ploty"]
    y_m = ploty * YM_PER_PIX
    left_m = np.polyfit(y_m, fit["left_fitx"] * XM_PER_PIX, 2)
    right_m = np.polyfit(y_m, fit["right_fitx"] * XM_PER_PIX, 2)
    y_eval = (len(ploty) - 1) * YM_PER_PIX  # dno slike = tacka najbliza vozilu

    def radius(c):  # R = (1 + (2Ay + B)^2)^1.5 / |2A|
        return (1 + (2 * c[0] * y_eval + c[1]) ** 2) ** 1.5 / max(abs(2 * c[0]), 1e-9)

    # Kamera je na sredini vozila -> vozilo je na x = sredina slike
    lane_center = (fit["left_fitx"][-1] + fit["right_fitx"][-1]) / 2
    offset = (img_width / 2 - lane_center) * XM_PER_PIX  # < 0: vozilo levo od centra
    return (radius(left_m) + radius(right_m)) / 2, offset


# ---------------------------------------------------------------- ceo pipeline
def process(img, mtx, dist):
    """Jedna slika kroz sve korake. Vraca recnik sa medjukoracima i merenjima."""
    undistorted = undistort(img, mtx, dist)
    binary = threshold(undistorted)
    warped, M = warp(binary)
    points = find_lane_points(warped)
    fit = fit_lanes(points, warped.shape[0])

    result = dict(undistorted=undistorted, binary=binary, warped=warped,
                  warped_color=warp(undistorted)[0], hough_view=points["view"],
                  fit=fit, radius=None, offset=None, fit_view=points["view"].copy())
    if fit is not None:
        result["radius"], result["offset"] = measure(fit, img.shape[1])
        # zuto = fit iz piksela, ljubicasto = traka izvedena iz druge trake
        for fx, ok in ((fit["left_fitx"], fit["ok_left"]), (fit["right_fitx"], fit["ok_right"])):
            pts = np.int32(np.column_stack([fx, fit["ploty"]]))
            cv.polylines(result["fit_view"], [pts], False,
                         (0, 255, 255) if ok else (255, 0, 255), 4)
        cv.putText(result["fit_view"], f"Radius: {result['radius']:.0f} m", (30, 50),
                   cv.FONT_HERSHEY_SIMPLEX, 1.2, (255, 255, 255), 2)
        cv.putText(result["fit_view"], f"Offset: {result['offset']:.2f} m", (30, 100),
                   cv.FONT_HERSHEY_SIMPLEX, 1.2, (255, 255, 255), 2)
    return result


WINDOW_W, WINDOW_H = 520, 292  # velicina jednog prozora (16:9), 3 u redu x 2 reda


def imshow_tile(title, image, index):
    """Prikaz u prozoru fiksne velicine, rasporedjenom u mrezi 3x2."""
    cv.namedWindow(title, cv.WINDOW_NORMAL)
    cv.resizeWindow(title, WINDOW_W, WINDOW_H)
    cv.moveWindow(title, (index % 3) * (WINDOW_W + 10), (index // 3) * (WINDOW_H + 40))
    cv.imshow(title, image)


def show(name, r, src_img):
    road = r["undistorted"].copy()
    cv.polylines(road, [SRC.astype(np.int32)], True, (0, 0, 255), 3)
    imshow_tile("1 Original", src_img, 0)
    imshow_tile("2 Undistorted + src trapezoid", road, 1)
    imshow_tile("3 Binary", r["binary"], 2)
    imshow_tile("4 Birds-eye view", r["warped_color"], 3)
    imshow_tile("5 Hough lines (red = left, blue = right)", r["hough_view"], 4)
    imshow_tile("6 Polynomial fit", r["fit_view"], 5)


def main():
    args = sys.argv[1:]
    mtx, dist = load_calibration(force="--recalibrate" in args)
    paths = [a for a in args if not a.startswith("--")]
    if not paths:
        paths = sorted(glob.glob(os.path.join(IMG_DIR, "test*.jpg")) +
                       glob.glob(os.path.join(IMG_DIR, "straight_lines*.jpg")))
        if not paths:
            raise SystemExit(f"Nema test slika u {IMG_DIR} (test*.jpg, straight_lines*.jpg).")

    print(f"{'slika':28s} {'radijus [m]':>12s} {'pozicija [m]':>13s} {'sirina [px]':>12s}")
    for path in paths:
        name = os.path.basename(path)
        img = read_image(path)
        if img is None:
            print(f"{name:28s} slika se ne moze ucitati (proveri putanju)")
            continue
        if img.shape[:2] != (720, 1280):
            # kalibracija i SRC/DST tacke vaze za 1280x720
            print(f"{name:28s} velicina {img.shape[1]}x{img.shape[0]} -> menjam na 1280x720")
            img = cv.resize(img, (1280, 720))
        r = process(img, mtx, dist)
        if r["fit"] is None:
            print(f"{name:28s} traka nije pronadjena")
        else:
            print(f"{name:28s} {r['radius']:12.0f} {r['offset']:13.2f} {r['fit']['lane_width_px']:12.0f}")
        show(name, r, img)
        if cv.waitKey(0) & 0xff == 27:  # ESC
            break
    cv.destroyAllWindows()


if __name__ == "__main__":
    main()
