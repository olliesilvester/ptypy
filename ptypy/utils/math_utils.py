# -*- coding: utf-8 -*-
"""
Numerical util functions.

This file is part of the PTYPY package.

    :copyright: Copyright 2014 by the PTYPY team, see AUTHORS.
    :license: GPLv2, see LICENSE for details.
"""


from scipy.special import erf 
import numpy as np
from misc import *
from scipy import ndimage as ndi

__all__ = ['smooth_step','abs2','norm2', 'norm', 'delxb', 'delxc', 'delxf',\
            'ortho','gauss_fwhm','gaussian','gf','cabs2','gf_2d','c_gf']

def cabs2(A):
    """
    Squared absolute value (for complex array `A`)
    """
    return A * A.conj()

def abs2(A):
    """
    Squared absolute value (for real array `A`)
    """
    return np.square(np.abs(A))

    
def norm2(A):
    """
    Squared norm
    """
    return np.sum(abs2(A))
    
def norm(A):
    """
    Norm.
    """
    return np.sqrt(norm2(A))
    
def smooth_step(x,mfs):
    """
    Smoothed step function with fwhm `mfs` 
    Evaluates the error function `scipy.special.erf`.
    """
    return 0.5*erf(x*2.35/mfs) +0.5

def gaussian(x,std=1.0,off=0.):
    """
    Evaluates gaussian standard normal
    
    .. math::
        g(x)=\\frac{1}{\mathrm{std}\sqrt{2\pi}}\,\exp \\left(-\\frac{(x-\mathrm{off})^2}{2 \mathrm{std}^2 }\\right)
    
    Parameters
    ----------
    x : ndarray
        input array
    
    std : float,optional 
        Standard deviation
        
    off : float, optional
        Offset / shift
    
    See also
    --------
    gauss_fwhm
    smooth_step
    """
    return np.exp(-(x-off)**2/(2*std**2)) / (std * np.sqrt(2*np.pi))
    
def gauss_fwhm(x,fwhm=1.0,off=0.):
    """
    Evaluates gaussian with full width half maximum 
    
    Parameters
    ----------
    x : ndarray
        input array
    
    fwhm : float,optional 
        Full width at half maximum
        
    off : float, optional
        Offset / shift
    
    See also
    --------
    gaussian
    
    """
    return gaussian(x,fwhm/2/np.sqrt(2*np.log(2)),off)

def delxf(a, axis = -1, out = None):
    """\
    Forward first order derivative for finite difference calculation.
    
    .. note::
        The last element along the derivative direction is set to 0.\n
        Pixel units are used (:math:`\\Delta x = \\Delta h = 1`).
    
    Parameters
    ----------
    a : ndarray
        Input array.
        
    axis : int, Default=-1, optional
        Which direction used for the derivative.
    
    out : ndarray, Default=None, optional
        Array in wich the resault is written (same size as ``a``).
    
    Returns
    -------
    out : ndarray
        Derived array.
    """
    nd   = len(a.shape)
    axis = range(nd)[axis]
    
    slice1 = [ slice(1,  None) if i == axis else slice(None) for i in range(nd) ]
    slice2 = [ slice(None, -1) if i == axis else slice(None) for i in range(nd) ]
    
    if out == None:  out = np.zeros_like(a)
    
    out[slice2] = a[slice1] - a[slice2]
    
    if out is a:
        # required for in-place operation
        slice3 = [ slice(-2, None) if i == axis else slice(None) for i in range(nd) ]
        out[slice3] = 0.
    
    return out

def delxb(a,axis=-1):
    """\
    Backward first order derivative for finite difference calculation.

    .. note::
        The first element along the derivative direction is set to 0.\n
        Pixel units are used (:math:`\\Delta x = \\Delta h = 1`).
    
    Parameters
    ----------
    a : ndarray
        Input array.
        
    axis : int, Default=-1, optional
        Which direction used for the derivative.
    
    Returns
    -------
    out : ndarray
        Derived array.
    """

    nd = len(a.shape)
    axis = range(nd)[axis]
    slice1 = [slice(1,None) if i==axis else slice(None) for i in range(nd)]
    slice2 = [slice(None,-1) if i==axis else slice(None) for i in range(nd)]
    b = np.zeros_like(a)
    b[slice1] = a[slice1] - a[slice2]
    return b

def delxc(a,axis=-1):
    """\
    Central first order derivative for finite difference calculation.
    
    .. note::
        Forward and backward derivatives are used for first and last 
        elements along the derivative direction.\n
        Pixel units are used (:math:`\\Delta x = \\Delta h = 1`).
    
    Parameters
    ----------
    a : nd-numpy-array
        Input array.
        
    axis : int, Default=-1, optional
        Which direction used for the derivative.
    
    Returns
    -------
    out : nd-numpy-array
        Derived array.
    """
    nd = len(a.shape)
    axis = range(nd)[axis]
    slice_middle = [slice(1,-1) if i==axis else slice(None) for i in range(nd)]
    b = delxf(a,axis) + delxb(a,axis)
    b[slice_middle] *= .5
    return b
            

def ortho(modes):
    """\
    Orthogonalize the given list of modes or ndarray along first axis.
    **specify procedure**
    
    Parameters
    ----------
    modes : array-like or list
        List equally shaped arrays or array of higher dimension
        
    Returns
    -------
    amp : vector
        relative power of each mode
    nplist : list
        List of modes, sorted in descending order
    """
    N = len(modes)
    A = np.array([[np.vdot(p2,p1) for p1 in modes] for p2 in modes])
    e,v = np.linalg.eig(A)
    ei = (-e).argsort()
    nplist = [sum(modes[i] * v[i,j] for i in range(N)) for j in ei]
    amp = np.array([norm2(npi) for npi in nplist])
    amp /= amp.sum()
    return amp, nplist


c_gf= complex_overload(ndi.gaussian_filter)
# ndi.gaussian_filter is a little special in the docstring
c_gf.__doc__='    *complex input*\n\n    '+c_gf.__doc__
    
def gf(c,*arg,**kwargs):
    """
    Wrapper for scipy.ndimage.gaussian_filter, that determines whether
    original or the complex function shall be used.
    
    See also
    --------
    c_gf 
    """
    if np.iscomplexobj(c):
        return c_gf(c,*arg,**kwargs)
    else:
        return ndi.gaussian_filter(c,*arg,**kwargs)

def gf_2d(c,sigma,**kwargs):
    """
    Gaussian filter along the last 2 axes
    
    See also
    --------
    gf
    c_gf
    """
    if c.ndim > 2:
        n=c.ndim
        return gf(c,(0,)*(n-2)+tuple(expect2(sigma)),**kwargs)
    else:
        return gf(c,sigma,**kwargs)