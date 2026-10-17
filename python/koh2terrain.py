"""The europe campaign terrain of Knights of Honor II, for tools that build a new one or patch it.

Constants of the terrain the game ships (europe map) and helpers to read a NetCDF DEM (ETOPO1 subsets
from NOAA ERDDAP: `latitude`, `longitude`, `altitude` in metres) and to roughen heights with noise.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
from scipy import ndimage
from scipy.io import netcdf_file

# world units, heightmap samples, alphamap texels and splat layers of the europe terrain
SIZE_X, SIZE_Z = 3750.0, 2625.0
HEIGHTMAP_RES = 4097
ALPHAMAP_RES = 2048
LAYERS = 24
WATER = 10.0
MAX_HEIGHT = 32.0


def load_dem(path: Path):
    f = netcdf_file(str(path), "r", mmap=False)
    lat = f.variables["latitude"][:].astype(np.float64)
    lon = f.variables["longitude"][:].astype(np.float64)
    alt = f.variables["altitude"][:].astype(np.float32)
    f.close()
    return lat, lon, alt


def fractal_noise(shape, seed, scales=(64, 24, 8), weights=(0.6, 0.3, 0.1)):
    rng = np.random.default_rng(seed)
    total = np.zeros(shape, np.float32)
    for s, w in zip(scales, weights):
        n = ndimage.gaussian_filter(rng.standard_normal(shape).astype(np.float32), s / 3)
        total += w * n / (n.std() + 1e-9)
    return total
