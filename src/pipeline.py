"""Lane finding pipeline - koraci 1-3: undistort, binarizacija, perspektiva."""
import glob
import os
import cv2 as cv
import numpy as np

ROOT = os.path.join(os.path.dirname(__file__), '..')
CAL_FILE = os.path.join(ROOT, 'output', 'calibration.npz')
IN_DIR = os.path.join(ROOT, 'test_images')
OUT_DIR = os.path.join(ROOT, 'output_images')

# Trapez na slici puta (src) -> pravougaonik u ptici perspektivi (dst), za 1280x720
SRC = np.float32([[595, 450], [690, 450], [1115, 720], [216, 720]])
DST = np.float32([[300, 0], [980, 0], [980, 720], [300, 720]])


def load_calibration():
    data = np.load(CAL_FILE)
    return data['mtx'], data['dist']


def undistort(img, mtx, dist):
    """Korak 1: ispravljanje distorzije (cv.undistort sa parametrima iz kalibracije)."""
    return cv.undistort(img, mtx, dist, None, mtx)


def threshold(img, s_thresh=(170, 255), sx_thresh=(20, 100), l_min=120):
    """Korak 2: kombinovana binarna slika (S kanal HLS + Sobel X po L kanalu)."""
    hls = cv.cvtColor(img, cv.COLOR_BGR2HLS)
    l_ch, s_ch = hls[:, :, 1], hls[:, :, 2]

    # Gradijent po x (vertikalne ivice = trake), skaliran na 0-255
    sobelx = np.absolute(cv.Sobel(l_ch, cv.CV_64F, 1, 0, ksize=3))
    scaled = np.uint8(255 * sobelx / np.max(sobelx))
    sx_bin = (scaled >= sx_thresh[0]) & (scaled <= sx_thresh[1])

    # Boja: S kanal dobro hvata zute i bele trake i otporan je na senke
    s_bin = (s_ch >= s_thresh[0]) & (s_ch <= s_thresh[1])

    # Tamni delovi (senke) ne mogu biti traka -> odseci po svetlini
    bright = l_ch >= l_min
    return np.uint8((sx_bin | s_bin) & bright)


def warp(binary, src=SRC, dst=DST):
    """Korak 3: perspektivna transformacija u pticiju perspektivu."""
    M = cv.getPerspectiveTransform(src, dst)
    Minv = cv.getPerspectiveTransform(dst, src)
    size = (binary.shape[1], binary.shape[0])
    return cv.warpPerspective(binary, M, size, flags=cv.INTER_LINEAR), M, Minv


def draw_src(img):
    out = img.copy()
    cv.polylines(out, [SRC.astype(np.int32)], True, (0, 0, 255), 3)
    return out


if __name__ == '__main__':
    os.makedirs(OUT_DIR, exist_ok=True)
    mtx, dist = load_calibration()
    for path in sorted(glob.glob(os.path.join(IN_DIR, '*.jpg'))):
        name = os.path.splitext(os.path.basename(path))[0]
        img = cv.imread(path)
        und = undistort(img, mtx, dist)
        binary = threshold(und)
        warped, M, Minv = warp(binary)

        cv.imwrite(f'{OUT_DIR}/{name}_1_undistorted.jpg', np.hstack([img, und]))
        cv.imwrite(f'{OUT_DIR}/{name}_2_binary.png', binary * 255)
        cv.imwrite(f'{OUT_DIR}/{name}_3_warped.png', warped * 255)
        cv.imwrite(f'{OUT_DIR}/{name}_3_src_points.jpg',
                   np.hstack([draw_src(und), cv.cvtColor(cv.warpPerspective(und, M, (1280, 720)), cv.COLOR_BGR2RGB)[:, :, ::-1]]))
        print('obradjeno:', name)
