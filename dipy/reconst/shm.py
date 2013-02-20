""" Tools for using spherical harmonic models to fit diffusion data

References
----------
Aganj, I., et. al. 2009. ODF Reconstruction in Q-Ball Imaging With Solid
    Angle Consideration.
Descoteaux, M., et. al. 2007. Regularized, fast, and robust analytical
    Q-ball imaging.
Tristan-Vega, A., et. al. 2010. A new methodology for estimation of fiber
    populations in white matter of the brain with Funk-Radon transform.
Tristan-Vega, A., et. al. 2009. Estimation of fiber orientation probability
    density functions in high angular resolution diffusion imaging.

"""
"""
Note about the Transpose:
In the literature the matrix representation of these methods is often written
as Y = Bx where B is some design matrix and Y and x are column vectors. In our
case the input data, a dwi stored as a nifti file for example, is stored as row
vectors (ndarrays) of the form (x, y, z, n), where n is the number of diffusion
directions. We could transpose and reshape the data to be (n, x*y*z), so that
we could directly plug it into the above equation. However, I have chosen to
keep the data as is and implement the relevant equations rewritten in the
following form: Y.T = x.T B.T, or in python syntax data = np.dot(sh_coef, B.T)
where data is Y.T and sh_coef is x.T.
"""
import numpy as np
from numpy import (atleast_1d, concatenate, diag, diff, dot, empty, eye, sqrt,
                   unique, dot)
from numpy.linalg import pinv, svd
from numpy.random import randint
from dipy.reconst.odf import OdfModel, OdfFit
from scipy.special import sph_harm, lpn
from dipy.core.geometry import cart2sphere
from dipy.reconst.cache import Cache
from dipy.core.ndindex import ndindex


def _copydoc(obj):
    def bandit(f):
        f.__doc__ = obj.__doc__
        return f
    return bandit


def real_sph_harm(m, n, theta, phi):
    """
    Compute real spherical harmonics, where the real harmonic $Y^m_n$ is
    defined to be:
        Real($Y^m_n$) * sqrt(2) if m > 0
        $Y^m_n$                 if m == 0
        Imag($Y^m_n$) * sqrt(2) if m < 0

    This may take scalar or array arguments. The inputs will be broadcasted
    against each other.

    Parameters
    -----------
      - `m` : int |m| <= n
        The order of the harmonic.
      - `n` : int >= 0
        The degree of the harmonic.
      - `theta` : float [0, 2*pi]
        The azimuthal (longitudinal) coordinate.
      - `phi` : float [0, pi]
        The polar (colatitudinal) coordinate.

    Returns
    --------
      - `y_mn` : real float
        The real harmonic $Y^m_n$ sampled at `theta` and `phi`.

    :See also:
        scipy.special.sph_harm
    """
    m = atleast_1d(m)
    # find where m is =,< or > 0 and broadcasts to the size of the output
    m_eq0, _, _, _ = np.broadcast_arrays(m == 0, n, theta, phi)
    m_gt0, _, _, _ = np.broadcast_arrays(m > 0, n, theta, phi)
    m_lt0, _, _, _ = np.broadcast_arrays(m < 0, n, theta, phi)

    sh = sph_harm(m, n, theta, phi)
    real_sh = empty(sh.shape, 'double')
    real_sh[m_eq0] = sh[m_eq0].real
    real_sh[m_gt0] = sh[m_gt0].real * sqrt(2)
    real_sh[m_lt0] = sh[m_lt0].imag * sqrt(2)
    return real_sh


def real_sph_harm_mrtrix(m, n, theta, phi):
    """
    Compute real spherical harmonics as in mrtrix, where the real harmonic $Y^m_n$ is
    defined to be:
        Real($Y^m_n$)            if m > 0
        $Y^m_n$                  if m == 0
        (-1)^{m+1}Imag($Y^m_n$)  if m < 0

    This may take scalar or array arguments. The inputs will be broadcasted
    against each other.

    Parameters
    -----------
      - `m` : int |m| <= n
        The order of the harmonic.
      - `n` : int >= 0
        The degree of the harmonic.
      - `theta` : float [0, 2*pi]
        The azimuthal (longitudinal) coordinate.
      - `phi` : float [0, pi]
        The polar (colatitudinal) coordinate.

    Returns
    --------
      - `y_mn` : real float
        The real harmonic $Y^m_n$ sampled at `theta` and `phi` as implemented in mrtrix.
        Warning: the basis is Tournier et al 2004 and 2007 is slightly different.
    """
    m = atleast_1d(m)
    # find where m is =,< or > 0 and broadcasts to the size of the output
    m_eq0, _, _, _ = np.broadcast_arrays(m == 0, n, theta, phi)
    m_gt0, _, _, _ = np.broadcast_arrays(m > 0, n, theta, phi)
    m_lt0, _, _, _ = np.broadcast_arrays(m < 0, n, theta, phi)

    sh = sph_harm(m, n, theta, phi)
    real_sh = empty(sh.shape, 'double')
    neg_ones = -1*np.ones(sh.shape)**(m+1)

    real_sh[m_eq0] = sh[m_eq0].real
    real_sh[m_gt0] = sh[m_gt0].real 
    real_sh[m_lt0] = neg_ones[m_lt0] * sh[m_lt0].imag
    
    return real_sh


def real_sph_harm_fibernav(m, n, theta, phi):
    """
    Compute real spherical harmonics as in fibernavigator, where the real harmonic $Y^m_n$ is
    defined to be:
        sqrt(2)*Imag($Y^m_n$)    if m > 0
        $Y^m_n$                  if m == 0
        sqrt(2)*Real($Y^|m|_n$)  if m < 0

    This may take scalar or array arguments. The inputs will be broadcasted
    against each other.

    Parameters
    -----------
      - `m` : int |m| <= n
        The order of the harmonic.
      - `n` : int >= 0
        The degree of the harmonic.
      - `theta` : float [0, 2*pi]
        The azimuthal (longitudinal) coordinate.
      - `phi` : float [0, pi]
        The polar (colatitudinal) coordinate.

    Returns
    --------
      - `y_mn` : real float
        The real harmonic $Y^m_n$ sampled at `theta` and `phi` as
        implemented in the FiberNavigator.
        http://code.google.com/p/fibernavigator/
        
    """
    m = atleast_1d(m)
    # find where m is =,< or > 0 and broadcasts to the size of the output
    m_eq0, _, _, _ = np.broadcast_arrays(m == 0, n, theta, phi)
    m_gt0, _, _, _ = np.broadcast_arrays(m > 0, n, theta, phi)
    m_lt0, _, _, _ = np.broadcast_arrays(m < 0, n, theta, phi)

    sh  = sph_harm(m, n, theta, phi)
    sh2 = sph_harm(abs(m), n, theta, phi)

    real_sh = empty(sh.shape, 'double')
    real_sh[m_eq0] = sh[m_eq0].real
    real_sh[m_gt0] = sh[m_gt0].imag  * sqrt(2)
    real_sh[m_lt0] = sh2[m_lt0].real * sqrt(2)
    
    return real_sh


sph_harm_lookup = {None:real_sph_harm, "mrtrix":real_sph_harm_mrtrix, "fibernav":real_sph_harm_fibernav}

def sph_harm_ind_list(sh_order):
    """
    Returns the degree (n) and order (m) of all the symmetric spherical
    harmonics of degree less then or equal it sh_order. The results, m_list
    and n_list are kx1 arrays, where k depends on sh_order. They can be
    passed to real_sph_harm.

    Parameters
    ----------
    sh_order : int
        even int > 0, max degree to return

    Returns
    -------
    m_list : array
        orders of even spherical harmonics
    n_list : array
        degrees of even spherical hormonics

    See also
    --------
    real_sph_harm
    """
    if sh_order % 2 != 0:
        raise ValueError('sh_order must be an even integer >= 0')

    n_range = np.arange(0, sh_order+1, 2, dtype='int')
    n_list = np.repeat(n_range, n_range*2+1)

    ncoef = (sh_order + 2)*(sh_order + 1)/2
    offset = 0
    m_list = empty(ncoef, 'int')
    for ii in n_range:
        m_list[offset:offset+2*ii+1] = np.arange(-ii, ii+1)
        offset = offset + 2*ii + 1

    # makes the arrays ncoef by 1, allows for easy broadcasting later in code
    return (m_list, n_list)


def smooth_pinv(B, L):
    """Regularized psudo-inverse

    Computes a regularized least square inverse of B

    Parameters
    ----------
    B : array_like (n, m)
        Matrix to be inverted
    L : array_like (n,)

    Returns
    -------
    inv : ndarray (m, n)
        regularized least square inverse of B

    Notes
    -----
    In the literature this inverse is often written $(B^{T}B+L^{2})^{-1}B^{T}$.
    However here this inverse is implemented using the psudo-inverse because it
    is more numerically stable than the direct implementation of the matrix
    product.

    """
    L = diag(L)
    inv = pinv(concatenate((B, L)))
    return inv[:, :len(B)]


def lazy_index(index):
    """Produces a lazy index

    Returns a slice that can be used for indexing an array, if no slice can be
    made index is returned as is.
    """
    index = np.array(index)
    assert index.ndim == 1
    if index.dtype.kind == 'b':
        index = index.nonzero()[0]
    if len(index) == 1:
        return slice(index[0], index[0] + 1)
    step = unique(diff(index))
    if len(step) != 1 or step[0] == 0:
        return index
    else:
        return slice(index[0], index[-1] + 1, step[0])


class SphHarmModel(OdfModel, Cache):
    """The base class to sub-classed by specific spherical harmonic models of
    diffusion data"""
    def __init__(self, gtab, sh_order, smooth=0, min_signal=1.,
                 assume_normed=False):
        """Creates a model that can be used to fit or sample diffusion data

        Arguments
        ---------
        gtab : GradientTable
            Diffusion gradients used to acquire data
        sh_order : even int >= 0
            the spherical harmonic order of the model
        smoothness : float between 0 and 1
            The regularization parameter of the model
        assume_normed : bool
            If True, data will not be normalized before fitting to the model

        """
        m, n = sph_harm_ind_list(sh_order)
        self._where_b0s = lazy_index(gtab.b0s_mask)
        self._where_dwi = lazy_index(~gtab.b0s_mask)
        self.assume_normed = assume_normed
        self.min_signal = min_signal
        x, y, z = gtab.gradients[self._where_dwi].T
        r, pol, azi = cart2sphere(x, y, z)
        B = real_sph_harm(m, n, azi[:, None], pol[:, None])
        L = -n*(n+1)
        legendre0 = lpn(sh_order, 0)[0]
        F = legendre0[n]
        self.B = B
        self.m = m
        self.n = n
        self._set_fit_matrix(B, L, F, smooth)

    def _set_fit_matrix(self, *args):
        """Should be set in a subclass and is called by __init__"""
        msg = "User must implement this method in a subclass"
        raise NotImplementedError(msg)

    def fit(self, data, mask=None):
        """Fits the model to diffusion data and returns the model fit"""
        # Normalize the data and fit coefficients
        if not self.assume_normed:
            data = normalize_data(data, self._where_b0s, self.min_signal)

        # Compute coefficients using abstract method
        coef = self._get_shm_coef(data)

        # Apply the mask to the coefficients
        if mask is not None:
            mask = np.asarray(mask, dtype=bool)
            coef *= mask[..., None]
        return SphHarmFit(self, coef, mask)


class SphHarmFit(OdfFit):
    """Diffusion data fit to a spherical harmonic model"""

    def __init__(self, model, shm_coef, mask):
        self.model = model
        self._shm_coef = shm_coef
        self.mask = mask

    @property
    def shape(self):
        return self._shm_coef.shape[:-1]

    def __getitem__(self, index):
        """Allowing indexing into fit"""
        # Index shm_coefficients
        if isinstance(index, tuple):
            coef_index = index + (Ellipsis,)
        else:
            coef_index = index
        new_coef = self._shm_coef[coef_index]

        # Index mask
        if self.mask is not None:
            new_mask = self.mask[index]
            assert new_mask.shape == new_coef.shape[:-1]
        else:
            new_mask = None

        return SphHarmFit(self.model, new_coef, new_mask)

    def odf(self, sphere):
        """Samples the odf function on the points of a sphere

        Parameters
        ----------
        sphere : Sphere
            The points on which to sample the odf.

        Returns
        -------
        values : ndarray
            The value of the odf on each point of `sphere`.

        """
        sampling_matrix = self.model.cache_get("sampling_matrix", sphere)
        if sampling_matrix is None:
            phi = sphere.phi.reshape((-1, 1))
            theta = sphere.theta.reshape((-1, 1))
            sampling_matrix = real_sph_harm(self.model.m, self.model.n,
                                            phi, theta)
            self.model.cache_set("sampling_matrix", sphere, sampling_matrix)
        return dot(self._shm_coef, sampling_matrix.T)


class CsaOdfModel(SphHarmModel):
    """Implementation of Constant Solid Angle reconstruction method.

    References
    ----------
    Aganj, I., et. al. 2009. ODF Reconstruction in Q-Ball Imaging With Solid
        Angle Consideration.
    """
    min = .001
    max = .999
    def _set_fit_matrix(self, B, L, F, smooth):
        """The fit matrix, is used by fit_coefficients to return the
        coefficients of the odf"""
        invB = smooth_pinv(B, sqrt(smooth)*L)
        L = L[:, None]
        F = F[:, None]
        self._fit_matrix = F*L*invB

    def _get_shm_coef(self, data, mask=None):
        """Returns the coefficients of the model"""
        data = data[..., self._where_dwi]
        data = data.clip(self.min, self.max)
        loglog_data = np.log(-np.log(data))
        return dot(loglog_data, self._fit_matrix.T)


class OpdtModel(SphHarmModel):
    """Implementation of Orientation Probability Density Transform
    reconstruction method.

    References
    ----------
    Tristan-Vega, A., et. al. 2010. A new methodology for estimation of fiber
        populations in white matter of the brain with Funk-Radon transform.
    Tristan-Vega, A., et. al. 2009. Estimation of fiber orientation probability
        density functions in high angular resolution diffusion imaging.
    """
    def _set_fit_matrix(self, B, L, F, smooth):
        invB = smooth_pinv(B, sqrt(smooth)*L)
        L = L[:, None]
        F = F[:, None]
        delta_b = F*L*invB
        delta_q = 4*F*invB
        self._fit_matrix = delta_b, delta_q

    def _get_shm_coef(self, data, mask=None):
        """Returns the coefficients of the model"""
        delta_b, delta_q = self._fit_matrix
        return _slowadc_formula(data[..., self._where_dwi], delta_b, delta_q)


def _slowadc_formula(data, delta_b, delta_q):
    """formula used in SlowAdcOpdfModel"""
    logd = -np.log(data)
    return dot(logd*(1.5-logd)*data, delta_q.T) - dot(data, delta_b.T)


class QballModel(SphHarmModel):
    """Implementation of regularized Qball reconstruction method.

    References
    ----------
    Descoteaux, M., et. al. 2007. Regularized, fast, and robust analytical
        Q-ball imaging.
    """

    def _set_fit_matrix(self, B, L, F, smooth):
        invB = smooth_pinv(B, sqrt(smooth)*L)
        F = F[:, None]
        self._fit_matrix = F*invB

    def _get_shm_coef(self, data, mask=None):
        """Returns the coefficients of the model"""
        return dot(data[..., self._where_dwi], self._fit_matrix.T)


def normalize_data(data, where_b0, min_signal=1., out=None):
    """Normalizes the data with respect to the mean b0
    """
    if out is None:
        out = np.array(data, dtype='float32', copy=True)
    else:
        if out.dtype.kind != 'f':
            raise ValueError("out must be floating point")
        out[:] = data

    out.clip(min_signal, out=out)
    b0 = out[..., where_b0].mean(-1)
    out /= b0[..., None]
    return out


def hat(B):
    """Returns the hat matrix for the design matrix B
    """

    U, S, V = svd(B, False)
    H = dot(U, U.T)
    return H

def lcr_matrix(H):
    """Returns a matrix for computing leveraged, centered residuals from data

    if r = (d-Hd), the leveraged centered residuals are lcr = (r/l)-mean(r/l)
    ruturns the matrix R, such lcr = Rd

    """
    if H.ndim != 2 or H.shape[0] != H.shape[1]:
        raise ValueError('H should be a square matrix')

    leverages = sqrt(1-H.diagonal())
    leverages = leverages[:, None]
    R = (eye(len(H)) - H) / leverages
    return R - R.mean(0)

def bootstrap_data_array(data, H, R, permute=None):
    """Applies the Residual Bootstraps to the data given H and R

    data must be normalized, ie 0 < data <= 1

    This function, and the bootstrap_data_voxel function, calculat
    residual-bootsrap samples given a Hat matrix and a Residual matrix. These
    samples can be used for non-parametric statistics or for bootstrap
    probabilistic tractography:

    References:
    -----------
    J. I. Berman, et al., "Probabilistic streamline q-ball tractography using
        the residual bootstrap" 2008
    HA Haroon, et al., "Using the model-based residual bootstrap to quantify
        uncertainty in fiber orientations from Q-ball analysis" 2009
    B. Jeurissen, et al., "Probabilistic Fiber Tracking Using the Residual
        Bootstrap with Constrained Spherical Deconvolution" 2011
    """

    if permute is None:
        permute = randint(data.shape[-1], size=data.shape[-1])
    assert R.shape == H.shape
    assert len(permute) == R.shape[-1]
    R = R[permute]
    data = dot(data, (H+R).T)
    return data

def bootstrap_data_voxel(data, H, R, permute=None):
    """Like bootstrap_data_array but faster when for a single voxel

    data must be 1d and normalized
    """
    if permute is None:
        permute = randint(data.shape[-1], size=data.shape[-1])
    r = dot(data, R.T)
    boot_data = dot(data, H.T)
    boot_data += r[permute]
    return boot_data

class ResidualBootstrapWrapper(object):
    """Returns a residual bootstrap sample of the signal_object when indexed

    Wraps a signal_object, this signal object can be an interpolator. When
    indexed, the the wrapper indexes the signal_object to get the signal.
    There wrapper than samples the residual boostrap distribution of signal and
    returns that sample.
    """
    def __init__(self, signal_object, B, where_dwi, min_signal=1.):
        """Builds a ResidualBootstrapWapper

        Given some linear model described by B, the design matrix, and a
        signal_object, returns an object which can sample the residual
        bootstrap distribution of the signal. We assume that the signals are
        normalized so we clip the bootsrap samples to be between min_signal and
        1.

        Parameters
        ----------
        signal_object : some object that can be indexed
            This object should return diffusion weighted signals when indexed.
        B : ndarray, ndim=2
            The design matrix of spherical hormonic model usded to fit the
            data. This is the model that will be used to compute the residuals
            and sample the residual bootstrap distribution
        where_dwi :
            indexing object to find diffusion weighted signals from signal
        min_signal : float
            The lowest allowable signal.
        """
        self._signal_object = signal_object
        self._H = hat(B)
        self._R = lcr_matrix(self._H)
        self._min_signal = min_signal
        self._where_dwi = where_dwi

    def __getitem__(self, index):
        """Indexes self._signal_object and bootstraps the result"""
        signal = self._signal_object[index].copy()
        dwi_signal = signal[self._where_dwi]
        boot_signal = bootstrap_data_voxel(dwi_signal, self._H, self._R)
        boot_signal.clip(self._min_signal, 1., out=boot_signal)
        signal[self._where_dwi] = boot_signal
        return signal


def sf_to_sh(sf, sphere, sh_order=4, basis_type=None, smooth=0.0):
    """ Spherical function to spherical harmonics (SH)

    Parameters
    ----------
    sf : ndarray
         ndarray of values representing spherical functions on the 'sphere'
    sphere : Sphere
          The points on which the sf is defined.
    sh_order : int, optional
               Maximum SH order in the SH fit,
               For `sh_order`, there will be
               (`sh_order`+1)(`sh_order`_2)/2 SH coefficients
               (default 4)
    basis_type : {None, 'mrtrix', 'fibernav'}
                 None for the default dipy basis,
                 'mrtrix' for the MRtrix basis, and
                 'fibernav' for the FiberNavigator basis
                 (default None)
   smooth : float, optional
            Lambda-regularization in the SH fit
            (default 0.0)
    
    Returns
    _______
    sh : ndarray
         SH coefficients representing the input `odf`
             
    """
    m, n = sph_harm_ind_list(sh_order)

    pol = sphere.theta
    azi = sphere.phi

    sph_harm_basis = sph_harm_lookup.get(basis_type)
    if not sph_harm_basis:
        raise ValueError(' Wrong basis type name ')
    B = sph_harm_basis(m, n, azi[:, None], pol[:, None])
    
    L = -n * (n + 1)
    invB = smooth_pinv(B, sqrt(smooth)*L)
    R = (sh_order + 1) * (sh_order + 2) / 2
    sh = np.zeros(sf.shape[:-1] + (R,))

    sh = np.dot(sf, invB.T)        

    return sh


def sh_to_sf(sh, sphere, sh_order, basis_type=None):    
    """ Spherical harmonics (SH) to spherical function (SF)

    Parameters
    ----------
    sh : ndarray
         ndarray of SH coefficients representing a spherical function
    sphere : Sphere
             The points on which to sample the sf.
    sh_order : int, optional
               Maximum SH order in the SH fit,
               For `sh_order`, there will be (`sh_order`+1)(`sh_order`_2)/2 SH coefficients
               (default 4)
    basis_type : {None, 'mrtrix', 'fibernav'}
                 None for the default dipy basis,
                 'mrtrix' for the MRtrix basis, and
                 'fibernav' for the FiberNavigator basis
                 (default None)
    
    Returns
    _______
    sf : ndarray
         Spherical function values on the `sphere`
             
    """
    m, n = sph_harm_ind_list(sh_order)

    pol = sphere.theta
    azi = sphere.phi

    sph_harm_basis = sph_harm_lookup.get(basis_type)
    if not sph_harm_basis:
        raise ValueError(' Wrong basis type name ')
    B = sph_harm_basis(m, n, azi[:, None], pol[:, None])
    
    N = sphere.vertices.shape[0]
    sf = np.zeros( sh.shape[:-1] + (N,) )

    sf = np.dot( sh, B.T) 

    return sf



