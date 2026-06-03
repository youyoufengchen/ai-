"""Minimal chumpy compatibility module for loading SMPL .pkl files."""
import numpy as np

class ch(np.ndarray):
    """Minimal chumpy 'ch' array stub."""
    def __new__(cls, *args, **kwargs):
        # Handle both: ch(array) and ch(shape, dtype) from numpy _reconstruct
        if len(args) == 1 and hasattr(args[0], '__len__') and not isinstance(args[0], (int, np.integer)):
            obj = np.asarray(args[0]).view(cls)
            return obj
        # numpy _reconstruct passes (shape, dtype) or (shape, dtype, buffer)
        if len(args) >= 2:
            shape = args[0]
            dtype = args[1]
            obj = np.ndarray.__new__(cls, shape, dtype)
            return obj
        obj = np.ndarray.__new__(cls, (0,), float)
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
        return np.asarray(self).__reduce__()[2]

    def __setstate__(self, state):
        np.ndarray.__setstate__(self, state)

    def __reduce__(self):
        return (ch, (np.asarray(self),))


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
        print(f'[Ch.__setstate__] state type={type(state)}, len={len(state) if hasattr(state, \"__len__\") else \"N/A\"}')
        if isinstance(state, dict):
            self._val = state.get('_val', np.array(0.0))
        elif isinstance(state, (np.ndarray, list, tuple)):
            self._val = np.asarray(state)
        elif state is None:
            self._val = np.array(0.0)
        else:
            print(f'[Ch.__setstate__] unknown state: {state}')
            self._val = np.array(0.0)

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

# linalg stubs
class SvdD(Ch):
    pass
class SvdVC(Ch):
    pass
class SvdVH(Ch):
    pass

# depends_on decorator stub
def depends_on(*args, **kwargs):
    def decorator(func):
        return func
    return decorator
