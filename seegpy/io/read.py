"""Reading functinons."""
import logging

import numpy as np
import pandas as pd

import os
import os.path as op

from seegpy.contacts.utils import detect_seeg_contacts

logger = logging.getLogger('seegpy')


def read_trm(path, as_transform=True, inverse=False):
    """Read a transformation file.

    Parameters
    ----------
    path : string
        Path to the trm file
    as_transform : bool
        Get either the array as a usable (4, 4) array (True) or just simply
        or just the array contained in the file (False)
    inverse : bool | False
        Whether to inverse the transformation or not

    Returns
    -------
    tr : array_like
        Transformation array
    """
    tr = np.genfromtxt(path)
    if as_transform:
        tr = np.vstack((np.c_[tr[1::, :], tr[0, :]], np.array([0, 0, 0, 1])))
    if inverse:
        tr = np.linalg.inv(tr)
    return tr


def read_contacts_trc(path):
    """Read the channels that are contained inside a TRC file.

    This function uses the neo python package.

    Parameters
    ----------
    path : string
        Path to the trc file

    Returns
    -------
    all_chan : list
        List of contacts
    units : list
        List of units per channels
    """
    import neo

    # -------------------------------------------------------------------------
    # read the channels
    micro = neo.MicromedIO(filename=path)
    seg = micro.read_segment(signal_group_mode='split-all', lazy=True)
    all_chan = [sig.name.replace(' ', '').strip().upper()
                for sig in seg.analogsignals]
    units = [str(sig.units) for sig in seg.analogsignals]

    return all_chan, units


def read_3dslicer_fiducial(path):
    """Read coordinates in a fiducial fcsv file.

    Parameters
    ----------
    path : string
        Path to the fcsv file

    Returns
    -------
    df : DataFrame
        DataFrame with the columns label, x, y and z
    """
    return pd.read_csv(path, skiprows=[0, 1])[['label', 'x', 'y', 'z']]


def read_trc(bloc):
    """Read a TRC file.

    Parameters
    ----------
    bloc : str
        Path to the bloc to read

    Returns
    -------
    sf : float
        The sampling frequency
    raw : array_like
        Array of raw data of shape (n_seeg_chan, n_times)
    seeg_chan : array_like
        Array of sEEG channels names
    trig_event : array_like
        Events in the trigger channel of length (n_events,)
    trig_time : array_like
        Time associated to each event of length (n_events,)
    """
    assert op.isfile(bloc)

    # -------------------------------------------------------------------------
    # SAMPLING FREQUENCY
    # -------------------------------------------------------------------------
    import neo
    micro = neo.MicromedIO(filename=bloc)
    seg = micro.read_segment(signal_group_mode='split-all', lazy=True)
    sf = float(seg.analogsignals[0].sampling_rate)

    # -------------------------------------------------------------------------
    # CHANNELS
    # -------------------------------------------------------------------------
    # read again the channels in first bloc
    ch_names, ch_units = read_contacts_trc(bloc)
    # detect seeg / non-seeg channels
    is_seeg = detect_seeg_contacts(ch_names, ch_units=ch_units, seeg_unit='uV')
    seeg_chan = np.array(ch_names)[is_seeg]
    seeg_nb = np.arange(len(ch_names))[is_seeg]

    # -------------------------------------------------------------------------
    # TRIGGERS AND RAW
    # -------------------------------------------------------------------------
    # load the bloc
    micro = neo.MicromedIO(filename=bloc)
    seg = micro.read_segment(signal_group_mode='split-all', lazy=False)
    # read the trigger
    _event = seg.events[0]
    trig_event = np.array(_event.labels).astype(int)
    trig_time = np.array(_event.times)
    # read the raw data
    raw = []
    for c in seeg_nb:
        raw += [seg.analogsignals[c].squeeze()]
    raw = np.stack(raw)

    return sf, raw, seeg_chan.tolist(), trig_event, trig_time


def read_pramat(mat_root):
    """Read a Pragues file.

    Parameters
    ----------
    mat_root : str
        Path to the root matlab folder

    Returns
    -------
    sf : float
        The sampling frequency
    raw : array_like
        Array of raw data of shape (n_seeg_chan, n_times)
    seeg_chan : array_like
        Array of sEEG channels names
    trig_event : array_like
        Events in the trigger channel of length (n_events,)
    trig_time : array_like
        Time associated to each event of length (n_events,)
    """
    import h5py

    assert op.isdir(mat_root)
    # -------------------------------------------------------------------------
    # BUILD PATH
    # -------------------------------------------------------------------------
    # header file
    path_head = op.join(mat_root, 'alignedData')
    files_head = os.listdir(path_head)
    assert len(files_head) == 1
    path_head = op.join(path_head, files_head[0])
    # raw file
    path_raw = op.join(mat_root, 'rawData', 'amplifierData')
    files_raw = os.listdir(path_raw)
    if len(files_raw) > 1:
        files_raw = ['iEEG.mat']
        logger.error("Multiple matlab files detected. Forcing iEEG.mat")
    assert len(files_raw) == 1
    path_raw = op.join(path_raw, files_raw[0])

    # -------------------------------------------------------------------------
    # CHANNELS
    # -------------------------------------------------------------------------

    cn, ct = [], []

    # +++++++++++++++++++++++++++++++++ HDF5 ++++++++++++++++++++++++++++++++++
    try:
        f = h5py.File(path_head, 'r')['H']
        # read channel names and types
        fc = f['channels']
        cn = [''.join(chr(i) for i in f[k[0]][:]) for k in list(fc['name'])]
        ct = [''.join(chr(i) for i in f[k[0]][:]) for k in list(fc['signalType'])]
    except:
        logger.error("Extraction failed with HDF5. Trying with scipy")

    # +++++++++++++++++++++++++++++++++ SCIPY +++++++++++++++++++++++++++++++++

    if (not len(cn)) and (not len(ct)):
        try:
            from scipy.io import loadmat
            f = loadmat(path_head)['H']
            # read channel names and types
            fc = f['channels']
            cn = [k[0][0] for k in fc[0, 0][0, :]]
            ct = [k[2][0] for k in fc[0, 0][0, :]]
        except:
            logger.error("Extraction failed with scipy. Trying with mat73")

    # +++++++++++++++++++++++++++++++++ MAT73 +++++++++++++++++++++++++++++++++

    if (not len(cn)) and (not len(ct)):
        import mat73
        f = mat73.loadmat(path_head)['H']
        fc = f['channels']
        cn = [k['name'] for k in fc]
        ct = [k['signalType'] for k in fc]

    # get only sEEG channels
    assert len(cn)
    assert len(ct)
    assert len(cn) == len(ct)
    ch_names = np.array([k.upper() for k in cn])
    is_seeg = np.array(ct) == 'SEEG'
    seeg_chan = np.array(ch_names)[is_seeg]

    # -------------------------------------------------------------------------
    # TRIGGER
    # -------------------------------------------------------------------------
    # sampling frequency
    f = h5py.File(path_raw, 'r')
    sf = float(np.array(f['srate'])[0][0])
    # load the time vector
    times = np.array(f['time']).squeeze()
    # load trigger data
    trig_event = np.round(f['raw'][-1, :]).astype(int).squeeze()
    # keep only the first trigger changes (rm duplicates)
    first_only = np.where(trig_event[1::] - trig_event[:-1])[0] + 1
    trig_event = trig_event[first_only]
    times = times[first_only]
    # remove inter zeros
    nnz = trig_event != 0
    trig_event = trig_event[nnz]
    trig_time = times[nnz]
    # now extract the raw data
    raw = np.array(f['raw'][is_seeg, :])

    return sf, raw, seeg_chan.tolist(), trig_event, trig_time


if __name__ == '__main__':

    path_mat = '/home/etienne/DEBUG/PRAGUES_2021_PR7_day1/'

    sf, raw, chan, ev, time = read_pramat(path_mat)
    print(sf)
    print(raw.shape)
    print(chan)
    print(ev)
    print(time)
