"""
Extract SMPL model data from .pkl to .npz format.
Works around chumpy dependency issues on Windows.
"""
import pickle
import numpy as np
from pathlib import Path


def extract_smpl_from_pkl(pkl_path: Path, out_path: Path = None):
    """
    Extract key SMPL arrays from a .pkl file.
    Handles chumpy objects by trying to convert them to numpy arrays.
    """
    with open(pkl_path, 'rb') as f:
        data = pickle.load(f, encoding='latin1')

    npz_data = {}
    for key in data.keys():
        val = data[key]
        # Try to convert chumpy / unknown objects to numpy
        if hasattr(val, 'r'):
            try:
                arr = np.array(val.r)
                npz_data[key] = arr
                print(f'{key}: converted from chumpy, shape={arr.shape}')
                continue
            except Exception as e:
                print(f'{key}: chumpy convert failed: {e}')
        if hasattr(val, '__array__'):
            try:
                arr = np.array(val)
                npz_data[key] = arr
                print(f'{key}: converted via __array__, shape={arr.shape}')
                continue
            except Exception as e:
                print(f'{key}: __array__ failed: {e}')
        if hasattr(val, 'toarray'):
            try:
                arr = val.toarray()
                npz_data[key] = arr
                print(f'{key}: converted sparse, shape={arr.shape}')
                continue
            except Exception as e:
                print(f'{key}: sparse convert failed: {e}')
        if isinstance(val, np.ndarray):
            npz_data[key] = val
            print(f'{key}: ndarray, shape={val.shape}')
        else:
            print(f'{key}: type={type(val).__name__}, keeping as-is')
            npz_data[key] = val

    if out_path:
        np.savez(out_path, **npz_data)
        print(f'Saved to {out_path}')

    return npz_data


if __name__ == '__main__':
    import sys
    pkl = Path(r'D:\新建文件夹 (2)\data\basicModel_neutral_lbs_10_207_0_v1.0.0.pkl')
    out = pkl.with_suffix('.npz')
    extract_smpl_from_pkl(pkl, out)
