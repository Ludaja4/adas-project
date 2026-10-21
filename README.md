# Lane Finding Project (ADAS)

This project finds lane lines in road images and estimates how sharply the road curves and where the car sits in its lane. It is written in Python with OpenCV, and the whole thing lives in a single file, `pipeline.py`. Each step is a small function, and `process()` simply calls them one after another. Results are shown with `cv.imshow`, and all images are kept in `img/`.

Roughly, the pipeline does this:

* Calibrate the camera from chessboard photos.
* Undistort the road images.
* Turn each image into a black-and-white mask of likely lane pixels, using color and edge information.
* Warp the mask to a bird's-eye view.
* Find the lanes with a Hough transform and fit a curve to each one.
* Work out the curvature of the road and the car's offset from the lane center.
* Draw the detected lane back onto the original image. *(TODO)*
* Run everything on a video. *(TODO)*

## Project structure

```
adas-project/
├── pipeline.py        # the whole pipeline
├── requirements.txt   # opencv-python, numpy
├── img/               # 20 chessboard photos, road test images, calib.npz
├── examples/          # pictures used in this README
└── README.md
```

## Running it

```bash
pip install -r requirements.txt     # installs opencv-python and numpy
python pipeline.py                  # runs every test image in img/
python pipeline.py img/test1.jpg    # runs a single image
python pipeline.py --recalibrate    # redoes the calibration (img/calib.npz)
```

If `img/calib.npz` does not exisst yet, the script calibrates the camera first, using the chessboard photos in `img/`. For every road image it then opens six widnows in a 3x2 grid: the original, the undistorted image with the source trapezoid, the binary mask, the bird's-eye view, the Hough segments, and the final polynomial fit with the radius and offset written on it. Press any key to move to the next image, or ESC to quit. The console also prints a small table with the radius, offset and lane width for each image.

A few practical notes. Because the script uses `imshow`, it needs a machine with a display. File paths are resolved relative to `pipeline.py`, so you can start it from any folder. Images that aren't 1280x720 get resized, since the calibration and the perspective points were set up for that size.

| Function in `pipeline.py` | What it does |
|---|---|
| `calibrate()` | camera calibration from the 20 chessboard images |
| `undistort()` | removes lens distortion |
| `threshold()` | builds the binary mask (S channel + Sobel) |
| `warp()` | perspective transform to the bird's-eye view |
| `find_lane_points()` | finds Hough segments and splits them into left and right |
| `fit_lanes()` | fits one polynomial shape to both lanes |
| `measure()` | curvature radius and vehicle offset |
| `process()` | runs all of the above on one image |

## Camera Calibration

#### 1. How the camera matrix and distortion coefficients were computed

The code is in `calibrate()`, and it follows the same recipe as `09_01_calibration.py` from the course repo. For each of the 20 chessboard photos in `img/calibration*.jpg`, the inner corners are located with `cv.findChessboardCorners` and then refined to sub-pixel accuracy with `cv.cornerSubPix`. Each corner also gets a matching 3D point: its grid position on the board, measured in squares, with `z = 0` because the board is flat. All the 2D/3D pairs are passed to `cv.calibrateCamera`, and the result is saved to `img/calib.npz`.

One thing worth knowing: images 1, 4 and 5 are cropped, so the full 9x6 pattern doesn't fit in them. When 9x6 isn't found, the code falls back to smaller patterns (9x5, 6x5, 7x6), and that is what allows all 20 images to be used.

| Quantity | Value |
|---|---|
| RMS error | 0.996 px |
| "Total error" (same formula as in `09_01`) | 0.124 |
| fx, fy | 1161.3, 1158.5 px |
| cx, cy | 666.7, 389.6 px |
| [k1, k2, p1, p2, k3] | -0.258, 0.062, -0.0002, -0.0001, -0.148 |

Original on the left, undistorted on the right:

![Undistorted](./examples/undistort_calibration.jpg)

## Pipeline (single images)

#### 1. Distortion-corrected image

`undistort()` applies `cv.undistort` with the parameters stored in `calib.npz`. The effect is subtle on the road, but you can see it near the edges of the frame and around the car hood (original on the left, corrected on the right):

![Road Transformed](./examples/undistort_road.jpg)

#### 2. Binary image (color + gradient)

`threshold()` builds the mask from two sources and combines them with a logical OR:

* **The S channel of the HLS color space** (170-255). Yellow and white paint both stand out here, and it holds up well when the lighting changes.
* **A Sobel filter in the x direction on the L channel** (20-100). It reacts to near-vertical edges, which is exactly what lane lines look like from a driver's seat.

On top of that, any pixel with lightness L below 120 is thrown away. Shadows can have a high S value too, but a lane marking is never dark, so this simple rule removes most of the false hits from tree shadows.

![Binary Example](./examples/binary.jpg)

#### 3. Perspective transform

`warp()` is written in the same style as `translate()` and `rotate()` in `00_02_transformations.py`, but it uses `getPerspectiveTransform` and `warpPerspective` instead of `warpAffine`. An affine transform can't stretch a trapezoid into a rectangle, so it isn't enough here. The source points were picked by hand on `straight_lines1.jpg`, and the destination points are chosen so the lanes end up vertical:

| Point | Source | Destination |
|---|---|---|
| top left | (595, 450) | (300, 0) |
| top right | (690, 450) | (980, 0) |
| bottom right | (1115, 720) | (980, 720) |
| bottom left | (216, 720) | (300, 720) |

The quick sanity check is the straight-road image: after the warp, both lanes should be parallel and vertical, and they are (red trapezoid on the left, bird's-eye view on the right):

![Warp Example](./examples/perspective.jpg)

#### 4. Lane pixels (Hough) and polynomial fit

This part lives in `find_lane_points()` and `fit_lanes()`.

1. **Hough transform.** `cv.HoughLinesP` runs on the binary bird's-eye image. Before that, a few areas are blanked out because they only produce junk segments: the left 200 px (the jagged edge of the road), the right 100 px, and the bottom 60px (noise from the hood).
2. **Filtering the segments.** Anything tilted more than about 35° from vertical is dropped. The rest is assigned to the left or right lane, depending on whether the segment's midpoint is left or right of the image center. Every segment is then turned into points about 2 px apart, so longer segments naturally count for more.
3. **Throwing out noise.** For each lane, a small RANSAC step (2 random points, 300 tries, fixed seed so results are repeatable) looks for the straight line that has the most points within ±40 px. Points far from that line are treated as noise.

4. **Fitting the curve.** The model is `x = A·y² + B·y + C`. It is written as a function of `y` because the lanes run almost vertically in this view. In the bird's-eye view the two lanes are parallel, so they share `A` and `B` and differ only in `C`. The fit uses the points from both lanes at once (`np.linalg.lstsq`), and it is repeated three times, each time dropping points more than 25 px away from the current curve.
5. **A safety net.** A lane is only trusted if its segments cover at least 5 of 9 horizontal bands of the image. If one lane fails this check (for example, a dashed line with long gaps), its `C` is taken from the other lane, shifted by one lane width (680 px).

In the pictures below, red segments belong to the left lane, blue ones to the right lane, and the yellow line is the fitted curve.

![Hough](./examples/hough_lines.jpg)

![Fit Visual](./examples/polynomial_fit.jpg)

Why share one curve between both lanes? Fitting each lane separately gave very different radii for the same road, for example 14700 m and 261 m on a single image. Hough segments are short and only cover part of the image height, so a quadratic fitted to one of them extrapolates badly. Pooling all the points makes the result much more stable.

#### 5. Curvature and vehicle position

This is done in `measure()`.

* **Pixels to meters.** `YM_PER_PIX = 30/720` and `XM_PER_PIX = 3.7/680`. These are common assumptions (about 30 m of road in view, and a 3.7 m wide lane that is 680 px wide after the warp). They are not measured for this particular camera.
* **Radius.** The curve is refitted in meters, and the radius is computed with `R = (1 + (2·A·y + B)²)^1.5 / |2·A|` at the bottom of the image, which is the point closest to the car. Since both lanes share `A` and `B`, they come out with the same radius.
* **Position in the lane.** The camera is assumed to sit in the middle of the car, at `x = 640`. The offset is the distance between that point and the center of the lane at the bottom of the image. A negative value means the car is to the left of the center.
* **A quick check.** The printed lane width should be close to 680 px.

| Image | Radius [m] | Offset [m] | Lane width [px] | Radius from an earlier sliding-window experiment [m] |
|---|---|---|---|---|
| straight_lines1 | 1879 | 0.11 | 652 | 8015 |
| straight_lines2 | 3310 | 0.05 | 679 | 7647 |
| test1 | 381 | -0.19 | 704 | 425 |
| test2 | 313 | -0.23 | 656 | 373 |
| test3 | 641 | 0.02 | 648 | 476 |
| test4 | 465 | -0.30 | 700 | 752 |
| test5 | 453 | 0.04 | 738 | 464 |
| test6 | 22359 | -0.03 | 660 | 837 |

A few honest caveats:

* On straight roads the radius is in the thousands of meters and depends heavily on small amounts of noise, so those numbers are only rough.
* The Hough version and the earlier sliding-window experiment disagree on some images (`test4`, `test6`). That tells us a curvature eestimate from a single image can easily be off by tens of percent, and there is no ground truth here to say which one is closer.
* The measured lane width is up to about 8% away from 680 px, so the source/destination points and the 3.7 m assumption are only approximate.

#### 6. Result drawn back onto the road

TODO

## Pipeline (video)

TODO

## Discussion

TODO

## Tools

Parts of this project (the code and the drafting of this README) were developed with the help of an AI assistant.
