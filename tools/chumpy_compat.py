"""
Minimal chumpy compatibility shim for loading SMPL .pkl files
without installing the actual chumpy package.
"""
import numpy as np
import sys

class ch(np.ndarray):
    """Minimal chumpy 'ch' array stub."""
    def __new__(cls, input_array):
        obj = np.asarray(input_array).view(cls)
        return obj

    def __array_finalize__(self, obj):
        if obj is None:
            return

    @property
    def r(self):
        return np.asarray(self)

    @property
    def x(self):
        return np.asarray(self)

    @property
    def shape(self):
        return np.asarray(self).shape

    def __getstate__(self):
        return np.asarray(self).__getstate__()

    def __setstate__(self, state):
        np.ndarray.__setstate__(self, state)

class Ch:
    """chumpy.ch.Ch stub"""
    def __init__(self, *args, **kwargs):
        if args:
            self._val = np.asarray(args[0])
        else:
            self._val = np.array(0.0)

    def __getstate__(self):
        return {'_val': self._val}

    def __setstate__(self, state):
        self._val = state.get('_val', np.array(0.0))

    def __getnewargs__(self):
        return (self._val,)

    def __reduce__(self):
        return (Ch, (self._val,))

    @property
    def r(self):
        return self._val
    @property
    def x(self):
        return self._val
    @property
    def shape(self):
        return self._val.shape
    def __array__(self):
        return self._val

# Expose as chumpy.ch
mod = type(sys)('chumpy')
mod.ch = ch
mod.Ch = Ch
sys.modules['chumpy'] = mod
sys.modules['chumpy.ch'] = mod

# Also need chumpy.ch.Ch for some pickles
mod.ch.Ch = Ch

print('[chumpy_compat] stub loaded')
