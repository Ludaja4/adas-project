"""Kalibracija kamere pomocu sahovske table (OpenCV)."""
import glob
import os
import cv2 as cv
import numpy as np

# Dimenzije table: broj UNUTRASNJIH uglova (ne polja!)
PATTERNS = [(9, 6), (9, 5), (6, 5), (7, 6), (9, 4), (8, 6), (5, 6)]  # fallback za slike koje su isecene
CAL_DIR = os.path.join(os.path.dirname(__file__), '..', 'camera_cal')
OUT_FILE = os.path.join(os.path.dirname(__file__), '..', 'output', 'calibration.npz')


def find_corners(gray):
    """Isprobava glavni obrazac (9x6), pa rezervne ako slika nije cela vidljiva."""
    flags = cv.CALIB_CB_ADAPTIVE_THRESH + cv.CALIB_CB_NORMALIZE_IMAGE
    for pattern in PATTERNS:
        ok, corners = cv.findChessboardCorners(gray, pattern, flags)
        if ok:
            return pattern, corners
    return None, None


def calibrate():
    criteria = (cv.TERM_CRITERIA_EPS + cv.TERM_CRITERIA_MAX_ITER, 30, 0.001)
    objpoints, imgpoints, used = [], [], []
    img_size = None

    for path in sorted(glob.glob(os.path.join(CAL_DIR, 'calibration*.jpg'))):
        img = cv.imread(path)
        gray = cv.cvtColor(img, cv.COLOR_BGR2GRAY)
        img_size = gray.shape[::-1]  # (width, height)

        pattern, corners = find_corners(gray)
        if pattern is None:
            print(f'{os.path.basename(path):20s} NIJE pronadjena tabla')
            continue

        corners = cv.cornerSubPix(gray, corners, (11, 11), (-1, -1), criteria)
        # 3D tacke table u "svetu": (0,0,0), (1,0,0), ... (z = 0, jedinica = jedno polje)
        objp = np.zeros((pattern[0] * pattern[1], 3), np.float32)
        objp[:, :2] = np.mgrid[0:pattern[0], 0:pattern[1]].T.reshape(-1, 2)

        objpoints.append(objp)
        imgpoints.append(corners)
        used.append((os.path.basename(path), pattern))
        print(f'{os.path.basename(path):20s} OK  {pattern}')

    rms, mtx, dist, rvecs, tvecs = cv.calibrateCamera(objpoints, imgpoints, img_size, None, None)

    # Reprojekciona greska (srednja)
    errs = []
    for op, ip, rv, tv in zip(objpoints, imgpoints, rvecs, tvecs):
        proj, _ = cv.projectPoints(op, rv, tv, mtx, dist)
        errs.append(cv.norm(ip, proj, cv.NORM_L2) / len(proj))
    print(f'\nKoriscenih slika: {len(used)}/20')
    print(f'RMS greska: {rms:.4f} px | srednja reprojekciona greska: {np.mean(errs):.4f} px')
    print('Camera matrix:\n', mtx)
    print('Distortion [k1 k2 p1 p2 k3]:\n', dist.ravel())

    np.savez(OUT_FILE, mtx=mtx, dist=dist)
    return mtx, dist


if __name__ == '__main__':
    mtx, dist = calibrate()
    # Demo: ispravljanje distorzije na prvoj slici
    img = cv.imread(os.path.join(CAL_DIR, 'calibration1.jpg'))
    h, w = img.shape[:2]
    newmtx, _ = cv.getOptimalNewCameraMatrix(mtx, dist, (w, h), 1, (w, h))
    und = cv.undistort(img, mtx, dist, None, newmtx)
    cv.imwrite(os.path.join(os.path.dirname(OUT_FILE), 'undistorted_calibration1.jpg'),
               np.hstack([img, und]))
