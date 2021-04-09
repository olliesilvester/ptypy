from . import load_kernel
from pycuda import gpuarray
import pycuda.driver as cuda
from ptypy.utils import gaussian
import numpy as np

# maps a numpy dtype to the corresponding C type
def map2ctype(dt):
    if dt == np.float32:
        return 'float'
    elif dt == np.float64: 
        return 'double'
    elif dt == np.complex64: 
        return 'complex<float>'
    elif dt == np.complex128: 
        return 'complex<double>'
    elif dt == np.int32:
        return 'int'
    elif dt == np.int64:
        return 'long long'
    else:
        raise ValueError('No mapping for {}'.format(dt))


class ArrayUtilsKernel:
    def __init__(self, acc_dtype=np.float64, queue=None):
        self.queue = queue
        self.acc_dtype = acc_dtype
        self.cdot_cuda = load_kernel("dot", {
            'IN_TYPE': 'complex<float>',
            'ACC_TYPE': 'double' if acc_dtype==np.float64 else 'float'
        })
        self.dot_cuda = load_kernel("dot", {
            'IN_TYPE': 'float',
            'ACC_TYPE': 'double' if acc_dtype==np.float64 else 'float'
        })
        self.full_reduce_cuda = load_kernel("full_reduce", {
            'IN_TYPE': 'double' if acc_dtype==np.float64 else 'float',
            'OUT_TYPE': 'double' if acc_dtype==np.float64 else 'float',
            'ACC_TYPE': 'double' if acc_dtype==np.float64 else 'float',
            'BDIM_X': 1024
        })
        self.Ctmp = None
        
    def dot(self, A, B, out=None):
        assert A.dtype == B.dtype, "Input arrays must be of same data type"
        assert A.size == B.size, "Input arrays must be of the same size"
        
        if out is None:
            out = gpuarray.zeros((1,), dtype=self.acc_dtype)

        block = (1024, 1, 1)
        grid = (int((B.size + 1023) // 1024), 1, 1)
        if self.acc_dtype == np.float32:
            elsize = 4
        elif self.acc_dtype == np.float64:
            elsize = 8
        if self.Ctmp is None or self.Ctmp.size < grid[0]:
            self.Ctmp = gpuarray.zeros((grid[0],), dtype=self.acc_dtype)
        Ctmp = self.Ctmp
        if grid[0] == 1:
            Ctmp = out
        if np.iscomplexobj(B):
            self.cdot_cuda(A, B, np.int32(A.size), Ctmp,
                block=block, grid=grid, 
                shared=1024 * elsize,
                stream=self.queue)
        else:
            self.dot_cuda(A, B, np.int32(A.size), Ctmp,
                block=block, grid=grid,
                shared=1024 * elsize,
                stream=self.queue)
        if grid[0] > 1:
            self.full_reduce_cuda(self.Ctmp, out, np.int32(grid[0]), 
                block=(1024, 1, 1), grid=(1,1,1), shared=elsize*1024,
                stream=self.queue)
        
        return out

    def norm2(self, A, out=None):
        return self.dot(A, A, out)

class TransposeKernel:

    def __init__(self, queue=None):
        self.queue = queue
        self.transpose_cuda = load_kernel("transpose", {
            'DTYPE': 'int',
            'BDIM': 16
        })

    def transpose(self, input, output):
        # only for int at the moment (addr array), and 2D (reshape pls)
        if len(input.shape) != 2:
            raise ValueError("Only 2D tranpose is supported - reshape as desired")
        if input.shape[0] != output.shape[1] or input.shape[1] != output.shape[0]:
            raise ValueError("Input/Output must be of flipped shape")
        if input.dtype != np.int32 or output.dtype != np.int32:
            raise ValueError("Only int types are supported at the moment")
        
        width = input.shape[1]
        height = input.shape[0]
        blk = (16, 16, 1)
        grd = (
            int((input.shape[1] + 15)// 16),
            int((input.shape[0] + 15)// 16),
            1
        )
        self.transpose_cuda(input, output, np.int32(width), np.int32(height),
            block=blk, grid=grd, stream=self.queue)

class MaxAbs2Kernel:

    def __init__(self, queue=None):
        self.queue = queue
        # we lazy-load this depending on the data types we get
        self.max_abs2_cuda = {}

    def max_abs2(self, X, out):
        """ Calculate max(abs(x)**2) across the final 2 dimensions"""
        rows = np.int32(X.shape[-2])
        cols = np.int32(X.shape[-1])
        firstdims = np.int32(np.prod(X.shape[:-2]))
        gy = int(rows)
        # lazy-loading, keeping scratch memory and both kernels in the same dictionary
        bx = int(64)
        version = '{},{},{}'.format(map2ctype(X.dtype), map2ctype(out.dtype), gy)
        if version not in self.max_abs2_cuda:
            step1, step2 = load_kernel(
                    ("max_abs2_step1", "max_abs2_step2"), 
                    {
                        'IN_TYPE': map2ctype(X.dtype),
                        'OUT_TYPE': map2ctype(out.dtype),
                        'BDIM_X': bx,
                    }, "max_abs2.cu")
            self.max_abs2_cuda[version] = {
                'step1': step1,
                'step2': step2,
                'scratchmem': gpuarray.empty((gy,), dtype=out.dtype)
            }

        # if self.max_abs2_cuda[version]['scratchmem'] is None \
        #     or self.max_abs2_cuda[version]['scratchmem'].shape[0] != gy:
        #     self.max_abs2_cuda[version]['scratchmem'] =
        scratch = self.max_abs2_cuda[version]['scratchmem']

        
        self.max_abs2_cuda[version]['step1'](X, firstdims, rows, cols, scratch,
            block=(bx, 1, 1), grid=(1, gy, 1),
            stream=self.queue)
        self.max_abs2_cuda[version]['step2'](scratch, np.int32(gy), out,
            block=(bx, 1, 1), grid=(1, 1, 1),
            stream=self.queue
        )
    

class CropPadKernel:

    def __init__(self, queue=None):
        self.queue = queue
        # we lazy-load this depending on the data types we get
        self.fill3D_cuda = {}

    def fill3D(self, A, B, offset=[0, 0, 0]):
        """
        Fill 3-dimensional array A with B.
        """
        if A.ndim < 3 or B.ndim < 3:
            raise ValueError('Input arrays must each be at least 3D')
        assert A.ndim == B.ndim, "Input and Output must have the same number of dimensions."
        ash = A.shape
        bsh = B.shape
        misfit = np.array(bsh) - np.array(ash)
        assert not misfit[:-3].any(), "Input and Output must have the same shape everywhere but the last three axes."

        Alim = np.array(A.shape[-3:])
        Blim = np.array(B.shape[-3:])
        off = np.array(offset)
        Ao = off.copy()
        Ao[Ao < 0] = 0
        Bo = -off.copy()
        Bo[Bo < 0] = 0
        assert (Bo < Blim).all() and (Ao < Alim).all(), "At least one dimension lacks overlap"
        Ao = Ao.astype(np.int32)
        Bo =     Bo.astype(np.int32)
        lengths = np.array([
            min(off[0] + Blim[0], Alim[0]) - Ao[0],
            min(off[1] + Blim[1], Alim[1]) - Ao[1],
            min(off[2] + Blim[2], Alim[2]) - Ao[2],
        ], dtype=np.int32)
        lengths2 = np.array([
            min(Alim[0] - off[0], Blim[0]) - Bo[0],
            min(Alim[1] - off[1], Blim[1]) - Bo[1],
            min(Alim[2] - off[2], Blim[2]) - Bo[2],
        ], dtype=np.int32)
        assert (lengths == lengths2).all(), "left and right lenghts are not matching"
        batch = int(np.prod(A.shape[:-3]))
        
        # lazy loading depending on data type
        version = '{},{}'.format(map2ctype(B.dtype), map2ctype(A.dtype))
        if version not in self.fill3D_cuda:
            self.fill3D_cuda[version] = load_kernel("fill3D", {
              'IN_TYPE': map2ctype(B.dtype),
              'OUT_TYPE': map2ctype(A.dtype)
            })
        bx = by = 32
        self.fill3D_cuda[version](
            A, B, 
            np.int32(A.shape[-3]), np.int32(A.shape[-2]), np.int32(A.shape[-1]),
            np.int32(B.shape[-3]), np.int32(B.shape[-2]), np.int32(B.shape[-1]),
            Ao[0], Ao[1], Ao[2],
            Bo[0], Bo[1], Bo[2],
            lengths[0], lengths[1], lengths[2],
            block=(int(bx), int(by), int(1)),
            grid=(
                int((lengths[2] + bx - 1)//bx),
                int((lengths[1] + by - 1)//by),
                int(batch)),
            stream=self.queue
        )


    def crop_pad_2d_simple(self, A, B):
        """
        Places B in A centered around the last two axis. A and B must be of the same shape
        anywhere but the last two dims.
        """
        assert A.ndim >= 2, "Arrays must have more than 2 dimensions."
        assert A.ndim == B.ndim, "Input and Output must have the same number of dimensions."
        misfit = np.array(A.shape) - np.array(B.shape)
        assert not misfit[:-2].any(), "Input and Output must have the same shape everywhere but the last two axes."
        if A.ndim == 2:
            A = A.reshape((1,) + A.shape)
        if B.ndim == 2:
            B = B.reshape((1,) + B.shape)
        a1, a2 = A.shape[-2:]
        b1, b2 = B.shape[-2:]
        offset = [0, a1 // 2 - b1 // 2, a2 // 2 - b2 // 2]
        self.fill3D(A, B, offset)


class ResampleKernel:
    def __init__(self, queue=None):
        self.queue = queue
        # we lazy-load this depending on the data types we get
        self.upsample_cuda = {}
        self.downsample_cuda = {}

    def resample(self, A, B):
        assert A.ndim > 2, "Arrays must have at least 2 dimensions"
        assert B.ndim > 2, "Arrays must have at least 2 dimensions"
        assert A.shape[:-2] == B.shape[:-2], "Arrays must have same shape expect along the last 2 dimensions"
        assert A.shape[-2] == A.shape[-1], "Last two dimensions must be of equal length"
        assert B.shape[-2] == B.shape[-2], "Last two dimensions must be of equal length"
        # same sampling, no need to call this function
        assert A.shape != B.shape, "A and B have the same shape, no need to do any resampling"
        assert A.dtype == B.dtype, "A and B must have the same data type"

        def map_type(dt):
            if dt == np.float32:
                return 'float'
            elif dt == np.float64: 
                return 'double'
            elif dt == np.complex64: 
                return 'complex<float>'
            elif dt == np.complex128: 
                return 'complex<double>'
            elif dt == np.int32:
                return 'int'
            elif dt == np.int64:
                return 'long long'
            else:
                raise ValueError('No mapping for {}'.format(dt))
        
        bx = 16
        by = 16
        # upsampling
        if A.shape[-1] > B.shape[-1]:
            resample = A.shape[-1] // B.shape[-1]
            assert resample <= bx, "Upsampling up to factor {} is supported".format(bx)
            
            version = '{}'.format(map_type(A.dtype))
            if version not in self.upsample_cuda:
                self.upsample_cuda[version] = load_kernel('upsample', {
                    'TYPE': map_type(A.dtype)
                })
            self.upsample_cuda[version](A, B, 
                np.int32(A.shape[1]),
                np.int32(A.shape[2]),
                np.int32(resample),
                block=(bx, by, 1),
                grid=(
                    int((A.shape[2] + bx - 1) // bx), 
                    int((A.shape[1] + by - 1) // by), 
                    int(A.shape[0])),
                shared=int(bx*by*A.dtype.itemsize/resample/resample),
                stream=self.queue)
    
        # downsampling
        elif A.shape[-1] < B.shape[-1]:
            resample = B.shape[-1] // A.shape[-1]
            assert resample <= bx, "Downsampling up to factor {} is supported".format(bx)
            
            version = '{}'.format(map_type(A.dtype))
            if version not in self.downsample_cuda:
                self.downsample_cuda[version] = load_kernel('downsample', {
                    'TYPE': map_type(A.dtype)
                })
            self.downsample_cuda[version](A, B, 
                np.int32(B.shape[1]),
                np.int32(B.shape[2]),
                np.int32(resample),
                block=(bx, by, 1),
                grid=(
                    int((B.shape[2] + bx - 1) // bx), 
                    int((B.shape[1] + by - 1) // by), 
                    int(A.shape[0])),
                shared=int(bx*by*A.dtype.itemsize),
                stream=self.queue)

class DerivativesKernel:
    def __init__(self, dtype, queue=None):
        if dtype == np.float32:
            stype = "float"
        elif dtype == np.complex64:
            stype = "complex<float>"
        else:
            raise NotImplementedError(
                "delxf is only implemented for float32 and complex64")

        self.queue = queue
        self.dtype = dtype
        self.last_axis_block = (256, 4, 1)
        self.mid_axis_block = (256, 4, 1)

        self.delxf_last, self.delxf_mid = load_kernel(
            ("delx_last", "delx_mid"), 
            file="delx.cu", 
            subs={
                'IS_FORWARD': 'true',
                'BDIM_X': str(self.last_axis_block[0]),
                'BDIM_Y': str(self.last_axis_block[1]),
                'IN_TYPE': stype,
                'OUT_TYPE': stype
            })
        self.delxb_last, self.delxb_mid  = load_kernel(
            ("delx_last", "delx_mid"), 
            file="delx.cu", 
            subs={
                'IS_FORWARD': 'false',
                'BDIM_X': str(self.last_axis_block[0]),
                'BDIM_Y': str(self.last_axis_block[1]),
                'IN_TYPE': stype,
                'OUT_TYPE': stype
            })
        

    def delxf(self, input, out, axis=-1):
        if input.dtype != self.dtype:
            raise ValueError('Invalid input data type')

        if axis < 0:
            axis = input.ndim + axis
        axis = np.int32(axis)

        if axis == input.ndim - 1:
            flat_dim = np.int32(np.product(input.shape[0:-1]))
            self.delxf_last(input, out, flat_dim, np.int32(input.shape[axis]),
                            block=self.last_axis_block,
                            grid=(
                int((flat_dim +
                     self.last_axis_block[1] - 1) // self.last_axis_block[1]),
                1, 1),
                stream=self.queue
            )
        else:
            lower_dim = np.int32(np.product(input.shape[(axis+1):]))
            higher_dim = np.int32(np.product(input.shape[:axis]))
            gx = int(
                (lower_dim + self.mid_axis_block[0] - 1) // self.mid_axis_block[0])
            gy = 1
            gz = int(higher_dim)
            self.delxf_mid(input, out, lower_dim, higher_dim, np.int32(input.shape[axis]),
                           block=self.mid_axis_block,
                           grid=(gx, gy, gz),
                           stream=self.queue
                           )

    def delxb(self, input, out, axis=-1):
        if input.dtype != self.dtype:
            raise ValueError('Invalid input data type')

        if axis < 0:
            axis = input.ndim + axis
        axis = np.int32(axis)

        if axis == input.ndim - 1:
            flat_dim = np.int32(np.product(input.shape[0:-1]))
            self.delxb_last(input, out, flat_dim, np.int32(input.shape[axis]),
                            block=self.last_axis_block,
                            grid=(
                int((flat_dim +
                     self.last_axis_block[1] - 1) // self.last_axis_block[1]),
                1, 1),
                stream=self.queue
            )
        else:
            lower_dim = np.int32(np.product(input.shape[(axis+1):]))
            higher_dim = np.int32(np.product(input.shape[:axis]))
            gx = int(
                (lower_dim + self.mid_axis_block[0] - 1) // self.mid_axis_block[0])
            gy = 1
            gz = int(higher_dim)
            self.delxb_mid(input, out, lower_dim, higher_dim, np.int32(input.shape[axis]),
                           block=self.mid_axis_block,
                           grid=(gx, gy, gz),
                           stream=self.queue
                           )


class GaussianSmoothingKernel:
    def __init__(self, queue=None, num_stdevs=4, kernel_type='float'):
        if kernel_type not in ['float', 'double']:
            raise ValueError('Invalid data type for kernel')
        self.kernel_type = kernel_type
        self.dtype = np.complex64
        self.stype = "complex<float>"
        self.queue = queue
        self.num_stdevs = num_stdevs
        self.blockdim_x = 4
        self.blockdim_y = 16

        
        # At least 2 blocks per SM
        self.max_shared_per_block = 48 * 1024 // 2 
        self.max_shared_per_block_complex = self.max_shared_per_block / 2 * np.dtype(np.float32).itemsize
        self.max_kernel_radius = int(self.max_shared_per_block_complex / self.blockdim_y)

        self.convolution_row = load_kernel(
            "convolution_row", file="convolution.cu", subs={
                'BDIM_X': self.blockdim_x,
                'BDIM_Y': self.blockdim_y,
                'DTYPE': self.stype,
                'MATH_TYPE': self.kernel_type
        })
        self.convolution_col = load_kernel(
        "convolution_col", file="convolution.cu", subs={
                'BDIM_X': self.blockdim_y,   # NOTE: we swap x and y in this columns
                'BDIM_Y': self.blockdim_x,
                'DTYPE': self.stype,
                'MATH_TYPE': self.kernel_type
        })
        # pre-allocate kernel memory on gpu, with max-radius to accomodate
        dtype=np.float32 if self.kernel_type == 'float' else np.float64
        self.kernel_gpu = gpuarray.empty((self.max_kernel_radius,), dtype=dtype)
        # keep track of previus radius and std to determine if we need to transfer again
        self.r = 0
        self.std = 0

    
    def convolution(self, data, mfs, tmp=None):
        """
        Calculates a stacked 2D convolution for smoothing, with the standard deviations
        given in mfs (stdx, stdy). It works in-place in the data array,
        and tmp is a gpu-allocated array of the same size and type as data,
        used internally for temporary storage
        """
        ndims = data.ndim
        shape = data.shape

        # Create temporary array (if not given)
        if tmp is None:
            tmp = gpuarray.empty(shape, dtype=data.dtype)
        assert shape == tmp.shape and data.dtype == tmp.dtype

        # Check input dimensions        
        if ndims == 3:
            batches,y,x = shape
            stdy, stdx = mfs
        elif ndims == 2:
            batches = 1
            y,x = shape
            stdy, stdx = mfs
        elif ndims == 1:
            batches = 1
            y,x = shape[0],1
            stdy, stdx = mfs[0], 0.0
        else:
            raise NotImplementedError("input needs to be of dimensions 0 < ndims <= 3")

        input = data
        output = tmp

        # Row convolution kernel
        # TODO: is this threshold acceptable in all cases?
        if stdx > 0.1:
            r = int(self.num_stdevs * stdx + 0.5)
            if r > self.max_kernel_radius:
                raise ValueError("Size of Gaussian kernel too large")
            if r != self.r or stdx != self.std:
                # recalculate + transfer
                g = gaussian(np.arange(-r,r+1), stdx)
                g /= g.sum()
                k = np.ascontiguousarray(g[r:].astype(np.float32 if self.kernel_type == 'float' else np.float64))
                self.kernel_gpu[:r+1] = k[:]
                self.r = r
                self.std = stdx

            bx = self.blockdim_x
            by = self.blockdim_y
            
            shared = (bx + 2*r) * by * np.dtype(np.complex64).itemsize
            if shared > self.max_shared_per_block:
                raise MemoryError("Cannot run kernel in shared memory")

            blk = (bx, by, 1)
            grd = (int((y + bx -1)// bx), int((x + by-1)// by), batches)
            self.convolution_row(input, output, np.int32(y), np.int32(x), self.kernel_gpu, np.int32(r), 
                                 block=blk, grid=grd, shared=shared, stream=self.queue)

            input = output
            output = data
        
        # Column convolution kernel
        # TODO: is this threshold acceptable in all cases?
        if stdy > 0.1:
            r = int(self.num_stdevs * stdy + 0.5)
            if r > self.max_kernel_radius:
                raise ValueError("Size of Gaussian kernel too large")
            if r != self.r or stdy != self.std:
                # recalculate + transfer
                g = gaussian(np.arange(-r,r+1), stdy)
                g /= g.sum()
                k = np.ascontiguousarray(g[r:].astype(np.float32 if self.kernel_type == 'float' else np.float64))
                self.kernel_gpu[:r+1] = k[:]
                self.r = r
                self.std = stdy
                

            bx = self.blockdim_y
            by = self.blockdim_x
            
            shared = (by + 2*r) * bx * np.dtype(np.complex64).itemsize
            if shared > self.max_shared_per_block:
                raise MemoryError("Cannot run kernel in shared memory")

            blk = (bx, by, 1)
            grd = (int((y + bx -1)// bx), int((x + by-1)// by), batches)
            self.convolution_col(input, output, np.int32(y), np.int32(x), self.kernel_gpu, np.int32(r), 
                                 block=blk, grid=grd, shared=shared, stream=self.queue)
            
        # TODO: is this threshold acceptable in all cases?
        if (stdx <= 0.1 and stdy <= 0.1):
            return   # nothing to do
        elif (stdx > 0.1 and stdy > 0.1):
            return   # both parts have run, output is back in data
        else:
            data[:] = tmp[:]  # only one of them has run, output is in tmp

class ClipMagnitudesKernel:

    def __init__(self, queue=None):
        self.queue = queue
        self.clip_magnitudes_cuda = load_kernel("clip_magnitudes", {
            'IN_TYPE': 'complex<float>',
        })

    def clip_magnitudes_to_range(self, array, clip_min, clip_max):

        cmin = np.float32(clip_min)
        cmax = np.float32(clip_max)

        npixel = np.int32(np.prod(array.shape))
        bx = 256
        gx = int((npixel + bx - 1) // bx)
        self.clip_magnitudes_cuda(array, cmin, cmax,
                npixel,
                block=(bx, 1, 1),
                grid=(gx, 1, 1),
                stream=self.queue)