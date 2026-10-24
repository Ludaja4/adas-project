# Lane Finding Project (ADAS)

This is a lane detection project made in Pyhton using OpenCV. The program takes road images and tries to find the left and right lane lines. From the detected lanes it also calculates the approximate road curvature and the position of the car relative to the middle of the lane.

The main code is in `pipeline.py`. The pipeline is split into several functions, so each part can be tested separately.

## What the program does

The main steps are:

- Calibrate the camera using chessboard images.
- Remove lens distortion from the input image.
- Create a binary image using color and gradient information.
- Change the perspective to a bird's-eye view.
- Find lane segments using the Hough transform.
- Fit a polynomial to the detected lane points.
- Calculate the radius of the curve and the car's position in the lane.
- Draw the detected lanes back onto the original image. **(TODO)**
- Process a video. **(TODO)**

## Project structure

```text
adas-project/
├── pipeline.py        # main program
├── requirements.txt   # opencv-python, numpy
├── img/               # calibration and test images
├── examples/          # images used in this README
└── README.md
```

## Running the program

First install the required packages:

```bash
pip install -r requirements.txt
```

Then the program can be started in a few different ways:

```bash
python pipeline.py                  # runs all test images
python pipeline.py img/test1.jpg    # runs one image
python pipeline.py --recalibrate    # calculates the camera calibration again
```

If `img/calib.npz` does not exist, the program automatically runs the calibration using the chessboard images from `img/`.

For every image, six windows are opened:

1. original image
2. undistorted image with the source trapezoid
3. binary image
4. bird's-eye view
5. detected Hough lines
6. final polynomial fit

The windows are arranged in a 3x2 grid. Press any key to move to the next image and press ESC to stop the program. The terminal also prints the calculated radius, offset and lane width.

A few practical things to know:

- The program uses `imshow`, so it needs a computer with a display.
- Paths are based on the location of `pipeline.py`, so the program can also be started from another working directory.
- Images that are not $1280 \times 720$ are resized because the calibration and perspective points were chosen for this resolution.

## Main functions

| Function | What it does |
|---|---|
| `calibrate()` | Calculates the camera calibration from the chessboard images |
| `undistort()` | Removes lens distortion |
| `threshold()` | Creates the binary image using the S channel and Sobel |
| `warp()` | Changes the image to bird's-eye perspective |
| `find_lane_points()` | Finds Hough line segments and separates them into left and right |
| `fit_lanes()` | Fits the polynomial to the lane points |
| `measure()` | Calculates the curve radius and vehicle offset |
| `process()` | Runs all steps for one image |

# Camera Calibration

## 1. Calculating the camera matrix and distortion coefficients

The calibration is done in `calibrate()`. It uses the 20 chessboard images from `img/calibration*.jpg`.

For every image, the program first tries to find the inner chessboard corners with `cv.findChessboardCorners`. The corners are then made more precise with `cv.cornerSubPix`.

For every detected corner there is also a corresponding 3D point. The chessboard is flat, so all these points have $z = 0$. The points from all images are then given to `cv.calibrateCamera()`. The calculated camera matrix and distortion coefficients are saved in `img/calib.npz`.

The calibration code follows the same basic approach as `09_01_calibration.py` from the course repository.

Some of the calibration images are cropped. Because of that, the complete $9 \times 6$ pattern cannot be found in images 1, 4 and 5. The program therefore also tries smaller patterns such as $9 \times 5$, $6 \times 5$ and $7 \times 6$. This makes it possible to use all 20 images.

| Quantity | Value |
|---|---:|
| RMS error | $0.996\text{ px}$ |
| "Total error" (same formula as in `09_01`) | $0.124$ |
| $f_x, f_y$ | $1161.3, 1158.5\text{ px}$ |
| $c_x, c_y$ | $666.7, 389.6\text{ px}$ |
| $[k_1, k_2, p_1, p_2, k_3]$ | $-0.258, 0.062, -0.0002, -0.0001, -0.148$ |

Original image on the left and undiistorted image on the right:

![Undistorted](./examples/undistort_calibration.jpg)

# Pipeline (single images)

## 1. Removing distortion

`undistort()` uses `cv.undistort()` with the parameters saved in `calib.npz`.

The difference is not very large in the middle of the image, but it can be noticed more around the edges and near the car hood.

![Road Transformed](./examples/undistort_road.jpg)

## 2. Creating the binary image

The function `threshold()` creates a binary image from color and gradient information.

Two main things are used:

- **S channel from HLS:** pixels with S between $170$ and $255$ are selected. This helps with detecting the lane markings, especially the yellow and white ones.
- **Sobel in the x direction on the L channel:** pixels with a value between $20$ and $100$ are selected. This detects edges that are mostly vertical, which is useful for lane lines.

The two masks are combined with a logical OR.

There is also an extra condition that removes pixels where the lightness is below $120$. This is mainly there to reduce false detections caused by dark shadows.

![Binary Example](./examples/binary.jpg)

## 3. Perspective transform

The `warp()` function changes the road image to a bird's-eye view. This makes the lane lines easier to work with because they become closer to parallel and vertical.

The transformation is done with `cv.getPerspectiveTransform()` and `cv.warpPerspective()`.

The source points were selected manually using `straight_lines1.jpg`. The destination points were selected so that the lanes are approximately vertical in the new image.

| Point | Source | Destination |
|---|---|---|
| top left | $(595, 450)$ | $(300, 0)$ |
| top right | $(690, 450)$ | $(980, 0)$ |
| bottom right | $(1115, 720)$ | $(980, 720)$ |
| bottom left | $(216, 720)$ | $(300, 720)$ |

A straight road image was used as a simple check. After the transformation, the two lane lines should look approximately parallel and vertical.

![Warp Example](./examples/perspective.jpg)

## 4. Finding the lanes and fitting the polynomial

This part is done by `find_lane_points()` and `fit_lanes()`.

### Hough transform vs. Sliding Window approach

While traditional sliding-window or pixel-histogram methods are commonly used for lane tracking, using the Probabilistic Hough Transform (`cv.HoughLinesP`) offers key engineering advantages in this pipeline:
- **Early angular filtering:** It allows filtering out line segments based on their slope right at the start, easily discarding horizontal and steep diagonal artifacts caused by road patches, vehicle shadows, or pavement seams.
- **Global line structure over local noise:** Instead of relying on local pixel intensities that can get pulled off-track by dark spots or temporary lane disruptions, the Hough transform looks for geometric line agreement. This provides a clean, structured set of points that leads to a much more stable input for the subsequent polynomial fit.

### Hough transform implementation

First, `cv.HoughLinesP()` is used on the binary bird's-eye image.

Some parts of the image are ignored because they usually contain unwanted lines. The first $200\text{ pixels}$ on the left, the last $100\text{ pixels}$ on the right and the bottom $60\text{ pixels}$ are removed from the Hough search.

The detected segments are then filtered. Lines that are too horizontal are removed because lane lines should be mostly vertical in this perspective. The remaining segments are split into left and right depending on which side of the image center they are on.

The segments are also converted into points approximately every $2\text{ pixels}$. This means that longer Hough segments contribute more points to the following fit.

### Removing noisy points

A small RANSAC step is then used for each lane. It randomly chooses two points and checks how many other points are close to the line defined by them. This is repeated $300$ times. Points that do not fit the dominant line are treated as noise.

A fixed random seed is used so that the result is repeatable.

### Polynomial fit

The lane is represented with:

$$x = A \cdot y^2 + B \cdot y + C$$

Using $x$ as a function of $y$ makes sense here because the lane lines are almost vertical in the bird's-eye view.

Both lanes are fitted together. The program assumes that the two lanes have approximately the same curvature, so they use the same $A$ and $B$ values. Their horizontal position is different, so they have different $C$ values.

The fit is done with `np.linalg.lstsq()`. It is repeated a few times, removing points that are more than $25\text{ pixels}$ away from the current curve.

There is also a check for how much of the image height is covered by detected lane segments. At least $5$ of $9$ horizontal sections have to contain enough points. If one lane is not detected well enough, its position is estimated from the other lane using the assumed lane width of $680\text{ pixels}$.

In the images below, red lines are the left Hough segments, blue lines are the right segments and yellow lines are the fitted curves.

![Hough](./examples/hough_lines.jpg)

![Fit Visual](./examples/polynomial_fit.jpg)

### Why are both lanes fitted together?

I first tried fitting the two lanes separately. The problem was that the Hough segments are relatively short, so fitting a quadratic to only one side can give very different results depending on which part of the lane was detected.

For example, on one image the two separately calculated radii were about $14700\text{ m}$ and $261\text{ m}$. Using the points from both lanes together gives a more stable curve because there are more points over a larger part of the image.

## 5. Curvature and vehicle position

The calculations are done in `measure()`.

### Converting pixels to meters

Two approximate conversion values are used:

- `YM_PER_PIX` = $30 / 720$
- `XM_PER_PIX` = $3.7 / 680$

This assumes that about $30\text{ meters}$ of road are visible in the image and that the lane is $3.7\text{ meters}$ wide. These are assumptions for this project and were not measured directly from the camera.

### Radius

The polynomial is converted from pixels to meters and the radius is calculated at the bottom of the image. The bottom is used because it represents the part of the road closest to the car.

The formula used is:

$$R = \frac{(1 + (2 \cdot A \cdot y + B)^2)^{1.5}}{|2 \cdot A|}$$

Since both lanes use the same $A$ and $B$, they have the same calculated radius.

### Position of the car

The camera is assumed to be in the middle of the vehicle, so the center of the car is taken as $x = 640$.

The center of the lane is calculated from the left and right fitted lines at the bottom of the image. The difference between the car center and lane center gives the offset.

A negative value means that the car is to the left of the lane center.

The lane width printed by the program should ideally be close to $680\text{ pixels}$.

| Image | Radius [m] | Offset [m] | Lane width [px] | Radius from an earlier sliding-window experiment [m] |
|---|---:|---:|---:|---:|
| straight_lines1 | 1879 | 0.11 | 652 | 8015 |
| straight_lines2 | 3310 | 0.05 | 679 | 7647 |
| test1 | 381 | -0.19 | 704 | 425 |
| test2 | 313 | -0.23 | 656 | 373 |
| test3 | 641 | 0.02 | 648 | 476 |
| test4 | 465 | -0.30 | 700 | 752 |
| test5 | 453 | 0.04 | 738 | 464 |
| test6 | 22359 | -0.03 | 660 | 837 |

### Some limitations

There are a few things that should be kept in mind when looking at these results:

- On straight roads the radius is very large, so even small changes in the detected points can change the result a lot.
- The Hough version and the earlier sliding-window experiment give different results on some images, especially `test4` and `test6`. There is no ground truth in this project, so it is difficult to say which result is closer to the real value.
- The detected lane width is sometimes several percent away from $680\text{ pixels}$. This means that the perspective points and the assumed $3.7\text{ m}$ lane width are only approximate.

## 6. Drawing the result back onto the road

TODO

# Pipeline (video)

TODO

# Discussion

TODO

# Tools

## Notes from the author

A few tecchnical notes regarding display and processing challenges during development:
- During GUI testing, `cv.imshow` initially caused display issues depending on system rendering backends. Alternative windowing functions were tested as a fallback, though the original OpenCV GUI functions were ultimately restored once environment display flags were stabilized.
- For video processing, an experimental implementation was creatd; however, frame-to-frame smoothing and temporal tracking are still undergoing refinement to achieve robust performance across consecutive frames. 