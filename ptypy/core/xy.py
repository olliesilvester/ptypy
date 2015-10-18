# -*- coding: utf-8 -*-
"""
This module generates the scan patterns. 

This file is part of the PTYPY package.

    :copyright: Copyright 2014 by the PTYPY team, see AUTHORS.
    :license: GPLv2, see LICENSE for details.
"""
from .. import utils as u
#from ..utils import prop 
from ..utils.verbose import logger
import numpy as np

__all__=['DEFAULT','from_pars','round_scan',\
         'raster_scan','spiral_scan']
         
TEMPLATES = u.Param()

DEFAULT=u.Param(
    #### Paramaters for popular scan methods 
    override = None,
    model = None,                # [None,'round', 'raster', 'spiral' or array-like]
    extent = 15e-6,               # round_roi: Width of ROI 
    spacing = 1.5e-6,               # raster scan: step size (grid spacing)
    steps = 10,
    offset = 0,               # raster scan: step size (grid spacing)
    jitter = None,
    count = None,
)
"""Default pattern parameters. See :py:data:`.scan.xy` and a short listing below"""

def from_pars(xypars=None):
    """
    Creates position array from parameter tree `pars`. See :py:data:`DEFAULT`
    
    :param Param pars: Input parameters
    :returns ndarray pos: A numpy.ndarray of shape ``(N,2)`` for *N* positios
    """
    p = DEFAULT.copy(depth=3)
    model = None
    if hasattr(xypars,'items') or hasattr(xypars,'iteritems'):
        # this is a dict
        p.update(xypars, in_place_depth = 3)    
    elif xypars is None:
        return None
    elif str(xypars)==xypars:
        if xypars in TEMPLATES.keys():
            return from_pars(TEMPLATES[sam])          
        else:
            raise RuntimeError('Template string `%s` for pattern creation is not understood' %sam)
    elif type(xypars) in [np.ndarray,list]:
        return np.array(xypars)
    else:
        ValueError('Input type `%s` for scan pattern creation is not understood' % str(type(xypars)))
    
    if p.override is not None:
        return np.asarray(p.override)
        
    elif p.model is None:
        logger.debug('Scan pattern model `None` is chosen . Will use positions provided by meta information')
        return None
    else:
        if type(p.model) in [np.ndarray, list]:
            pos = np.asarray(p.model)
        elif p.model=='round':
            e,l,s =_complete(p.extent,p.steps,p.spacing)
            pos=round_scan(s[0],l[0]/2)
        elif p.model=='spiral':
            e,l,s =_complete(p.extent,p.steps,p.spacing)
            pos=spiral_scan(s[0],e[0]/2)
        elif p.model=='raster':
            e,l,s =_complete(p.extent,p.steps,p.spacing)
            pos=raster_scan(s[0],s[1],l[0],l[1])
        else:
            raise NameError('Unknown pattern type %s' % str(p.model))
        
        if p.offset is not None:
            pos += u.expect2(p.offset)
        # filter roi
        if p.extent is not None:
            roi = u.expect2(p.extent) /2.
            new = []
            for posi in pos:
                if (posi[0]>-roi[0]) and (posi[0]<roi[0]) and (posi[1]>-roi[1]) and (posi[1]<roi[1]):
                    new.append(posi)
                
            pos = np.array(new)
            
        if p.jitter is not None:
            pos =pos
        
        if p.count is not None and p.count >0:
            pos=pos[:int(p.count)]
            
        logger.info('Prepared %d positions' % len(pos))
        return pos
        
def _complete(extent,steps,spacing):
    a = np.sum([item is None for item in [extent,steps,spacing]])
    if a>=2:
        raise ValueError('Only one of <extent>, <layer> or <spacing> may be None')
    elif steps is None:
        e = u.expect2(extent)
        s = u.expect2(spacing)
        l = (e / s).astype(np.int) 
    elif spacing is None:
        e = u.expect2(extent)
        l = u.expect2(steps)
        s = e / l
    else:
        l = u.expect2(steps)
        s = u.expect2(spacing)
        e = l * s
        
    return e,l,s

def augment_to_coordlist(a,Npos):
 
    # force into a 2 column matrix
    # drop element if size is not a modulo of 2
    a = np.asarray(a)
    if a.size == 1:
        a=np.atleast_2d([a,a])
        
    if a.size % 2 != 0:
        a=a.flatten()[:-1]
    
    a=a.reshape(a.size//2,2)
    # append multiples of a until length is greater equal than Npos
    if a.shape[0] < Npos:
        b=np.concatenate((1+Npos//a.shape[0])*[a],axis=0)
    else:
        b=a
    
    return b[:Npos,:2]
    
def raster_scan(ny=10,nx=10,dy=1.5e-6,dx=1.5e-6):
    """
    Generates a raster scan.
    
    Parameters
    ----------
    ny, nx : int
        Number of steps in *y* (vertical) and *x* (horizontal) direction
        *x* is the fast axis
        
    dy, dx : float
        Step size (grid spacinf) in *y* and *x*  
        
    Returns
    -------
    pos : ndarray
        A (N,2)-array of positions. It is ``N = (nx+1)*(nx+1)``
        
        
    Examples
    --------
    >>> from ptypy.core import xy
    >>> from matplotlib import pyplot as plt
    >>> pos = xy.raster_scan()
    >>> plt.plot(pos[:,1],pos[:,0],'o-');plt.show()
    """
    iix, iiy = np.indices((nx+1,ny+1))
    positions = [(dx*i, dy*j) for i,j in zip(iix.ravel(), iiy.ravel())]
    return np.asarray(positions)

def round_scan(dr=1.5e-6, nr=5, nth=5, bullseye=True):
    """
    Generates a round scan
    
    Parameters
    ----------
    nr : int
        Number of radial steps from center, ``nr + 1`` shells will be made
        
    dr : float
        Step size (shell spacing)
        
    nth : int, optional
        Number of points in first shell
        
    Returns
    -------
    pos : ndarray
        A (N,2)-array of positions. 
        
        
    Examples
    --------
    >>> from ptypy.core import xy
    >>> from matplotlib import pyplot as plt
    >>> pos = xy.round_scan()
    >>> plt.plot(pos[:,1],pos[:,0],'o-');plt.show()
    """
    if bullseye:
        positions = [(0.,0.)]
    else:
        positions = []
        
    for ir in range(1,nr+2):
        rr = ir*dr
        dth = 2*np.pi / (nth*ir)
        positions.extend([(rr*np.sin(ith*dth), rr*np.cos(ith*dth)) for ith in range(nth*ir)])
    return np.asarray(positions)

def spiral_scan(dr=1.5e-6, r=7.5e-6,maxpts=None):
    """
    Generates a spiral scan.
    
    Parameters
    ----------
    r : float
        Number of radial steps from center, ``nr + 1`` shells will be made
        
    dr : float
        Step size (shell spacing)
        
    nth : int, optional
        Number of points in first shell
        
    Returns
    -------
    pos : ndarray
        A (N,2)-array of positions. It is 
        
        
    Examples
    --------
    >>> from ptypy.core import xy
    >>> from matplotlib import pyplot as plt
    >>> pos = xy.spiral_scan()
    >>> plt.plot(pos[:,1],pos[:,0],'o-');plt.show()
    """
    alpha = np.sqrt(4*np.pi)
    beta = dr/(2*np.pi)
    
    if maxpts is None:
        maxpts = 100000

    positions = []
    for k in xrange(maxpts):
        theta = alpha*np.sqrt(k)
        rr = beta * theta
        if rr > r: break
        positions.append( (rr*np.sin(theta), rr*np.cos(theta)) )
    return np.asarray(positions)

def raster_scan_legacy(nx,ny,dx,dy):
    """
    Generates a raster scan.
    
    Legacy function. May get deprecated in future.
    """
    iix, iiy = np.indices((nx+1,ny+1))
    positions = [(dx*i, dy*j) for i,j in zip(iix.ravel(), iiy.ravel())]
    return positions

def round_scan_legacy(r_in, r_out, nr, nth):
    """
    Generates a round scan,
    
    Legacy function. May get deprecated in future.
    """
    dr = (r_out - r_in)/ nr
    positions = []
    for ir in range(1,nr+2):
        rr = r_in + ir*dr
        dth = 2*np.pi / (nth*ir)
        positions.extend([(rr*np.sin(ith*dth), rr*np.cos(ith*dth)) for ith in range(nth*ir)])
    return positions

def round_scan_roi_legacy(dr, lx, ly, nth):
    """\
    Round scan positions with ROI, defined as in spec and matlab.
    
    Legacy function. May get deprecated in future.
    """
    rmax = np.sqrt( (lx/2)**2 + (ly/2)**2 )
    nr = np.floor(rmax/dr) + 1
    positions = []
    for ir in range(1,int(nr+2)):
        rr = ir*dr
        dth = 2*np.pi / (nth*ir)
        th = 2*np.pi*np.arange(nth*ir)/(nth*ir)
        x1 = rr*np.sin(th)
        x2 = rr*np.cos(th)
        positions.extend([(xx1,xx2) for xx1,xx2 in zip(x1,x2) if (np.abs(xx1) <= ly/2) and (np.abs(xx2) <= lx/2)])
    return positions


def spiral_scan_legacy(dr,r_out=None,maxpts=None):
    """\
    Spiral scan positions.

    Legacy function. May get deprecated in future.
    """
    alpha = np.sqrt(4*np.pi)
    beta = dr/(2*np.pi)
    
    if maxpts is None:
        assert r_out is not None
        maxpts = 100000000

    if r_out is None:
        r_out = np.inf

    positions = []
    for k in xrange(maxpts):
        theta = alpha*np.sqrt(k)
        r = beta * theta
        if r > r_out: break
        positions.append( (r*np.sin(theta), r*np.cos(theta)) )
    return positions

def spiral_scan_roi_legacy(dr,lx,ly):
    """\
    Spiral scan positions. ROI
    
    Legacy function. May get deprecated in future.
    """
    alpha = np.sqrt(4*np.pi)
    beta = dr/(2*np.pi)
    
    rmax = .5*np.sqrt(lx**2 + ly**2)
    positions = []
    for k in xrange(1000000000):
        theta = alpha*np.sqrt(k)
        r = beta * theta
        if r > rmax: break
        x,y = r*np.sin(theta), r*np.cos(theta)
        if abs(x) > lx/2: continue
        if abs(y) > ly/2: continue
        positions.append( (x,y) )
    return positions
