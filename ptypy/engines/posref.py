# -*- coding: utf-8 -*-
"""
Position refinement module.

This file is part of the PTYPY package.

    :copyright: Copyright 2014 by the PTYPY team, see AUTHORS.
    :license: GPLv2, see LICENSE for details.
"""
from ..core import View
from .. import utils as u
from ..utils.verbose import log
import numpy as np
from ..core.classes import DEFAULT_ACCESSRULE

class PositionRefine(object):
    """
    Refines the positions by the following algorithm:
    
    A.M. Maiden, M.J. Humphry, M.C. Sarahan, B. Kraus, J.M. Rodenburg,
    An annealing algorithm to correct positioning errors in ptychography,
    Ultramicroscopy, Volume 120, 2012, Pages 64-72
    """
    def __init__(self, position_refinement_parameters, initial_positions, shape, temp_ob):
        self.p = position_refinement_parameters
        # copy of the original object buffer to give space to play in
        self.temp_ob = temp_ob
        # A dictionary of the initial positions
        self.initial_pos = initial_positions
        # Shape and pixelsize
        self.shape = shape
        self.psize = temp_ob.S.values()[0].psize[0]
        # Maximum shift
        start, end = self.p.start, self.p.stop
        self.max_shift_dist_rule = lambda it: self.p.amplitude * (end - it) / (end - start) + self.psize/2.

        self.ar = DEFAULT_ACCESSRULE.copy()
        self.ar.psize = self.psize
        self.ar.shape = self.shape
        log(3, "Position refinement initialized")


    def fourier_error(self, di_view, obj):
        """
        Calculates the fourier error based on a given diffraction and object.

        :param di_view: View to the diffraction pattern of the given position.
        :param object: Numpy array which contains the needed object.
        :return: Tuple of Fourier Errors
        """
        af2 = np.zeros_like(di_view.data)
        for name, pod in di_view.pods.iteritems():
            af2 += u.abs2(pod.fw(pod.probe*obj))
        af = np.sqrt(af2)
        fmag = np.sqrt(np.abs(di_view.data))
        error = np.sum(di_view.pod.mask * (af - fmag)**2)
        del af2
        del af
        del fmag
        return error


    def single_pos_ref(self, di_view):
        """
        Refines the positions by the following algorithm:

        A.M. Maiden, M.J. Humphry, M.C. Sarahan, B. Kraus, J.M. Rodenburg,
        An annealing algorithm to correct positioning errors in ptychography,
        Ultramicroscopy, Volume 120, 2012, Pages 64-72
    
        Algorithm Description:
        Calculates random shifts around the original position and calculates the fourier error. If the fourier error
        decreased the randomly calculated postion will be used as new position.
    
        :param di_view: Diffraction view for which a better position is searched for.

        :return: If a better coordinate (smaller fourier error) is found for a position, the new coordinate (meters)
        will be returned. Otherwise (0, 0) will be returned.
        """
        dcoords = np.zeros((self.p.nshifts + 1, 2)) - 1.
        delta = np.zeros((self.p.nshifts, 2))               # coordinate shift
        errors = np.zeros(self.p.nshifts)                   # calculated error for the shifted position
        coord = np.copy(di_view.pod.ob_view.coord)
        
        self.ar.coord = coord
        self.ar.storageID = self.temp_ob.storages.values()[0].ID

        # Create temporal object view that can be shifted without reformatting
        ob_view_temp = View(self.temp_ob, accessrule=self.ar)
        dcoords[0, :] = ob_view_temp.dcoord

        # This can be optimized by saving existing iteration fourier error...
        error_inital = self.fourier_error(di_view, ob_view_temp.data)

        for i in range(self.p.nshifts):
            delta_y = np.random.uniform(0, self.max_shift_dist)
            delta_x = np.random.uniform(0, self.max_shift_dist)

            if i % 4 == 1:
                delta_y *= -1
                delta_x *= -1
            elif i % 4 == 2:
                delta_x *= -1
            elif i % 4 == 3:
                delta_y *= -1

            delta[i, 0] = delta_y
            delta[i, 1] = delta_x

            rand_coord = [coord[0] + delta_y, coord[1] + delta_x]
            norm = np.linalg.norm(rand_coord - self.initial_pos[di_view.ID])

            if norm > self.p.max_shift:
                # Positions drifted too far, skip this position
                log(4, "New position is too far away!!!", parallel=True)
                errors[i] = error_inital + 1.
                continue

            self.ar.coord = rand_coord
            ob_view_temp = View(self.temp_ob, accessrule=self.ar)
            dcoord = ob_view_temp.dcoord  # coordinate in pixel

            # check if new coordinate is on a different pixel since there is no subpixel shift, if there is no shift
            # skip the calculation of the fourier error
            if any((dcoord == x).all() for x in dcoords):
                errors[i] = error_inital + 1.
                continue
            dcoords[i + 1, :] = dcoord
            #
            # Check if these are really necessary
            if di_view.pod.ob_view.dlow[0] < 0:
                print("The 0 co-ordinate was less than 0")
                di_view.pod.ob_view.dlow[0] = 0
            if di_view.pod.ob_view.dlow[1] < 0:
                print("The 1 co-ordinate was less than 0")
                di_view.pod.ob_view.dlow[1] = 0

            if not np.allclose(ob_view_temp.data.shape, self.shape):
                print("I went in here tempshape:%s, self.shape:%s, dx:%s, xy:%s, maxdist:%s" % (ob_view_temp.data.shape, self.shape, delta_x, delta_y, self.max_shift_dist))


            errors[i] = self.fourier_error(di_view, ob_view_temp.data)

        if np.min(errors) < error_inital:
            # if a better coordinate is found
            #log(4, "New coordinate with smaller Fourier Error found!", parallel=True)
            arg = np.argmin(errors)
            new_coordinate = np.array([coord[0] + delta[arg, 0], coord[1] + delta[arg, 1]])
        else:
            new_coordinate = (0, 0)

        # Clean up
        del ob_view_temp
        del di_view
        
        return new_coordinate


