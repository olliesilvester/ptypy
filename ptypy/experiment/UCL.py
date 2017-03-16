# -*- coding: utf-8 -*-
"""
Scan loading recipe for the laser imaging setup, UCL.

This file is part of the PTYPY package.

    :copyright: Copyright 2014 by the PTYPY team, see AUTHORS.
    :license: GPLv2, see LICENSE for details.
"""
import numpy as np
import os
from .. import utils as u
from .. import io
from ..core.data import PtyScan
from ..utils.verbose import log
from ..core.paths import Paths
from ..core import DEFAULT_io as IO_par

logger = u.verbose.logger

# Recipe defaults
RECIPE = u.Param()
# Experiment identifier
RECIPE.experimentID = None
# Scan number
RECIPE.scan_number = None
RECIPE.dark_number = None
RECIPE.flat_number = None
RECIPE.energy = None
RECIPE.lam = None
# Distance from object to screen
RECIPE.z = None
# Name of the detector as specified in the nexus file
RECIPE.detector_name = None
# Motor names to determine the sample translation
RECIPE.motors = ['t1_sx', 't1_sy']
# Motor conversion factor to meters
RECIPE.motors_multiplier = 1e-3
RECIPE.base_path = './'
RECIPE.data_file_path = '%(base_path)s' + 'raw/%(scan_number)06d'
RECIPE.dark_file_path = '%(base_path)s' + 'raw/%(dark_number)06d'
RECIPE.flat_file_path = '%(base_path)s' + 'raw/%(flat_number)06d'
RECIPE.mask_file = None  # '%(base_path)s' + 'processing/mask.h5'
# Use flat as Empty Probe (EP) for probe sharing;
# needs to be set to True in the recipe of the scan that will act as EP
RECIPE.use_EP = False
# Apply hot pixel correction
RECIPE.remove_hot_pixels = u.Param(
    # Initiate by setting to True;
    # DEFAULT parameters will be used if not specified otherwise
    apply=False,
    # Size of the window on which the median filter will be applied
    # around every data point
    size=3,
    # Tolerance multiplied with the standard deviation of the data array
    # subtracted by the blurred array (difference array)
    # yields the threshold for cutoff.
    tolerance=10,
    # If True, edges of the array are ignored, which speeds up the code
    ignore_edges=False,
)

# Apply Richardson Lucy deconvolution
RECIPE.rl_deconvolution = u.Param(
    # Initiate by setting to True;
    # DEFAULT parameters will be used if not specified otherwise
    apply=False,
    # Number of iterations
    numiter=5,
    # Provide MTF from file; no loading procedure present for now,
    # loading through recon script required
    dfile=None,
    # Create fake psf as a sum of gaussians if no MTF provided
    gaussians=u.Param(
        # DEFAULT list of gaussians for Richardson Lucy deconvolution
        g1=u.Param(
            # Standard deviation in x direction
            std_x=1.0,
            # Standard deviation in y direction
            std_y=1.0,
            # Offset / shift in x direction
            off_x=0.,
            # Offset / shift in y direction
            off_y=0.,
            )
        ),
)

# Generic defaults
UCLDEFAULT = PtyScan.DEFAULT.copy()
UCLDEFAULT.recipe = RECIPE
UCLDEFAULT.auto_center = False
UCLDEFAULT.orientation = (False, False, False)


class UCLLaserScan(PtyScan):
    """
    Laser imaging setup (UCL) data preparation class.
    """
    DEFAULT = UCLDEFAULT

    def __init__(self, pars=None, **kwargs):
        """
        Initializes parent class.

        :param pars: dict
            - contains parameter tree.
        :param kwargs: key-value pair
            - additional parameters.
        """
        recipe_default = RECIPE.copy()
        recipe_default.update(pars.recipe, in_place_depth=1)
        pars.recipe.update(recipe_default)

        super(UCLLaserScan, self).__init__(pars, **kwargs)

        # Try to extract base_path to access data files
        if self.info.recipe.base_path is None:
            d = os.getcwd()
            base_path = None
            while True:
                if 'raw' in os.listdir(d):
                    base_path = d
                    break
                d, rest = os.path.split(d)
                if not rest:
                    break
            if base_path is None:
                raise RuntimeError('Could not guess base_path.')
            else:
                self.info.recipe.base_path = base_path

        # Construct path names
        self.data_path = self.info.recipe.data_file_path % self.info.recipe
        log(3, 'Will read data from directory %s' % self.data_path)
        if self.info.recipe.dark_number is None:
            self.dark_file = None
            log(3, 'No data for dark')
        else:
            self.dark_path = self.info.recipe.dark_file_path % self.info.recipe
            log(3, 'Will read dark from directory %s' % self.dark_path)
        if self.info.recipe.flat_number is None:
            self.flat_file = None
            log(3, 'No data for flat')
        else:
            self.flat_path = self.info.recipe.flat_file_path % self.info.recipe
            log(3, 'Will read flat from file %s' % self.flat_path)

        # Load data information
        self.instrument = io.h5read(self.data_path + '/%06d_%04d.nxs'
                                    % (self.info.recipe.scan_number, 1),
                                    'entry.instrument')['instrument']

        # Extract detector name if not set or wrong
        if (self.info.recipe.detector_name is None
                or self.info.recipe.detector_name
                not in self.instrument.keys()):
            detector_name = None
            for k in self.instrument.keys():
                if 'data' in self.instrument[k]:
                    detector_name = k
                    break

            if detector_name is None:
                raise RuntimeError(
                    'Not possible to extract detector name. '
                    'Please specify in recipe instead.')
            elif (self.info.recipe.detector_name is not None
                  and detector_name is not self.info.recipe.detector_name):
                u.log(2, 'Detector name changed from %s to %s.'
                      % (self.info.recipe.detector_name, detector_name))
        else:
            detector_name = self.info.recipe.detector_name

        self.info.recipe.detector_name = detector_name

        # Set up dimensions for cropping
        try:
            # Switch for attributes which are set to None
            # Will be removed once None attributes are removed
            center = pars.center
        except AttributeError:
            center = 'unset'

        # Check if dimension tuple is provided
        if type(center) == tuple:
            offset_x = pars.center[0]
            offset_y = pars.center[1]
        # If center unset, extract offset from raw data
        elif center == 'unset':
            raw_shape = self.instrument[
                self.info.recipe.detector_name]['data'].shape
            offset_x = raw_shape[-1] // 2
            offset_y = raw_shape[-2] // 2
        else:
            raise RuntimeError(
                'Center provided is not of type tuple or set to "unset". '
                'Please correct input parameters.')

        xdim = (offset_x - pars.shape // 2, offset_x + pars.shape // 2)
        ydim = (offset_y - pars.shape // 2, offset_y + pars.shape // 2)

        self.info.recipe.array_dim = [xdim, ydim]

        # Create the ptyd file name if not specified
        if self.info.dfile is None:
            home = Paths(IO_par).home
            self.info.dfile = ('%s/prepdata/data_%d.ptyd'
                               % (home, self.info.recipe.scan_number))
            log(3, 'Save file is %s' % self.info.dfile)

        log(4, u.verbose.report(self.info))

    def load_weight(self):
        """
        For now, this function will be used to load the mask.

        Function description see parent class.

        :return: weight2d
            - np.array: Mask or weight if provided from file
        """
        # FIXME: do something better here. (detector-dependent)
        # Load mask as weight
        if self.info.recipe.mask_file is not None:
            return io.h5read(
                self.info.recipe.mask_file, 'mask')['mask'].astype(float)

    def load_positions(self):
        """
        Load the positions and return as an (N,2) array.

        :return: positions
            - np.array: contains scan positions.
        """
        # Load positions from file if possible.
        motor_positions = io.h5read(
            self.info.recipe.base_path + '/raw/%06d/%06d_metadata.h5'
            % (self.info.recipe.scan_number, self.info.recipe.scan_number),
            'positions')['positions']

        # If no positions are found at all, raise error.
        if motor_positions is None:
            raise RuntimeError('Could not find motors.')

        # Apply motor conversion factor and create transposed array.
        mmult = u.expect2(self.info.recipe.motors_multiplier)
        positions = motor_positions * mmult[0]

        return positions

    def load_common(self):
        """
        Load dark and flat.

        :return: common
            - dict: contains averaged dark and flat (np.array).
        """
        common = u.Param()

        # Load dark.
        if self.info.recipe.dark_number is not None:
            dark = [io.h5read(self.dark_path + '/%06d_%04d.nxs'
                              % (self.info.recipe.dark_number, j),
                              'entry.instrument.detector.data')['data'][0][
                    self.info.recipe.array_dim[1][0]:
                    self.info.recipe.array_dim[1][1],
                    self.info.recipe.array_dim[0][0]:
                    self.info.recipe.array_dim[0][1]].astype(np.float32)
                    for j in np.arange(1, len(os.listdir(self.dark_path)))]

            dark = np.array(dark).mean(0)
            common.dark = dark
            log(3, 'Dark loaded successfully.')

        # Load flat.
        if self.info.recipe.flat_number is not None:
            flat = [io.h5read(self.flat_path + '/%06d_%04d.nxs'
                              % (self.info.recipe.flat_number, j),
                              'entry.instrument.detector.data')['data'][0][
                    self.info.recipe.array_dim[1][0]:
                    self.info.recipe.array_dim[1][1],
                    self.info.recipe.array_dim[0][0]:
                    self.info.recipe.array_dim[0][1]].astype(np.float32)
                    for j in np.arange(1, len(os.listdir(self.flat_path)))]

            flat = np.array(flat).mean(0)
            common.flat = flat
            log(3, 'Flat loaded successfully.')

        return common

    def load(self, indices):
        """
        Load frames given by the indices.

        :param indices: list
            Frame indices available per node.
        :return: raw, pos, weight
            - dict: index matched data frames (np.array).
            - dict: new positions.
            - dict: new weights.
        """
        raw = {}
        pos = {}
        weights = {}

        for j in np.arange(1, len(indices) + 1):
            data = io.h5read(self.data_path + '/%06d_%04d.nxs'
                             % (self.info.recipe.scan_number, j),
                             'entry.instrument.detector.data')['data'][0][
                   self.info.recipe.array_dim[1][0]:
                   self.info.recipe.array_dim[1][1],
                   self.info.recipe.array_dim[0][0]:
                   self.info.recipe.array_dim[0][1]].astype(np.float32)
            raw[j - 1] = data
        log(3, 'Data loaded successfully.')

        return raw, pos, weights

    def correct(self, raw, weights, common):
        """
        Apply corrections to frames. See below for possible options.

        Options for corrections:
        - Hot pixel removal:
            Replace outlier pixels in frames by median.
        - Richardson–Lucy deconvolution:
            Deconvolve frames from detector psf.
        - Dark subtraction:
            Subtract dark from frames.
        - Flat division:
            Divide frames by flat.

        :param raw: dict
            - dict containing index matched data frames (np.array).
        :param weights: dict
            - dict containing possible weights.
        :param common: dict
            - dict containing possible dark and flat frames.
        :return: data, weights
            - dict: contains index matched corrected data frames (np.array).
            - dict: contains modified weights.
        """
        # Apply hot pixel removal
        if self.info.recipe.remove_hot_pixels.apply:
            u.log(3, 'Applying hot pixel removal...')
            for j in raw:
                raw[j] = u.remove_hot_pixels(
                    raw[j],
                    self.info.recipe.remove_hot_pixels.size,
                    self.info.recipe.remove_hot_pixels.tolerance,
                    self.info.recipe.remove_hot_pixels.ignore_edges)[0]

            if self.info.recipe.flat_number is not None:
                common.dark = u.remove_hot_pixels(
                    common.dark,
                    self.info.recipe.remove_hot_pixels.size,
                    self.info.recipe.remove_hot_pixels.tolerance,
                    self.info.recipe.remove_hot_pixels.ignore_edges)[0]

            if self.info.recipe.flat_number is not None:
                common.flat = u.remove_hot_pixels(
                    common.flat,
                    self.info.recipe.remove_hot_pixels.size,
                    self.info.recipe.remove_hot_pixels.tolerance,
                    self.info.recipe.remove_hot_pixels.ignore_edges)[0]

            u.log(3, 'Hot pixel removal completed.')

        # Apply deconvolution
        if self.info.recipe.rl_deconvolution.apply:
            u.log(3, 'Applying deconvolution...')

            # Use mtf from a file if provided in recon script
            if self.info.recipe.rl_deconvolution.dfile is not None:
                mtf = self.info.rl_deconvolution.dfile
            # Create fake psf as a sum of gaussians from parameters
            else:
                gau_sum = 0
                for k in (
                        self.info.recipe.rl_deconvolution.gaussians.iteritems()):
                    gau_sum += u.gaussian2D(raw[0].shape[0],
                                            k[1].std_x,
                                            k[1].std_y,
                                            k[1].off_x,
                                            k[1].off_y)

                # Compute mtf
                mtf = np.abs(np.fft.fft2(gau_sum))

            for j in raw:
                raw[j] = u.rl_deconvolution(
                    raw[j],
                    mtf,
                    self.info.recipe.rl_deconvolution.numiter)

            u.log(3, 'Deconvolution completed.')

        # Apply flat and dark, only dark, or no correction
        if (self.info.recipe.flat_number is not None
                and self.info.recipe.dark_number is not None):
            for j in raw:
                raw[j] = (raw[j] - common.dark) / (common.flat - common.dark)
                raw[j][raw[j] < 0] = 0
            data = raw
        elif self.info.recipe.dark_number is not None:
            for j in raw:
                raw[j] = raw[j] - common.dark
                raw[j][raw[j] < 0] = 0
            data = raw
        else:
            data = raw

        # FIXME: this will depend on the detector type used.
        weights = weights

        return data, weights