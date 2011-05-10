import os
from os.path import join as pjoin
import gzip
import numpy as np
import nibabel as nib
from nibabel.spatialimages import ImageFileError


def _fread3(fobj):
    """Read a 3-byte int from an open binary file object."""
    b1, b2, b3 = np.fromfile(fobj, ">u1", 3)
    return (b1 << 16) + (b2 << 8) + b3


def read_geometry(filepath):
    """Read a triangular format Freesurfer surface mesh.

    Parameters
    ----------
    filepath : str
        Path to surface file

    Returns
    -------
    coords : numpy array
        nvtx x 3 array of vertex (x, y, z) coordinates
    faces : numpy array
        nfaces x 3 array of defining mesh triangles
    """
    with open(filepath, "rb") as fobj:
        magic = _fread3(fobj)
        if magic == 16777215:
            raise NotImplementedError("Quadrangle surface format reading "
                                      "not implemented")
        elif magic != 16777214:
            raise ValueError("File does not appear to be a Freesurfer surface")
        create_stamp = fobj.readline()
        _ = fobj.readline()
        vnum = np.fromfile(fobj, ">i4", 1)[0]
        fnum = np.fromfile(fobj, ">i4", 1)[0]
        coords = np.fromfile(fobj, ">f4", vnum * 3).reshape(vnum, 3)
        faces = np.fromfile(fobj, ">i4", fnum * 3).reshape(fnum, 3)

    coords = coords.astype(np.float)  # XXX: due to mayavi bug on mac 32bits
    return coords, faces


def read_curvature(filepath):
    """Read a Freesurfer curvature file.

    Parameters
    ----------
    filepath : str
        Path to curvature file

    Returns
    -------
    curv : numpy array
        Vector representation of surface curvature values

    """
    with open(filepath, "rb") as fobj:
        magic = _fread3(fobj)
        if magic == 16777215:
            vnum = np.fromfile(fobj, ">i4", 3)[0]
            curv = np.fromfile(fobj, ">f4", vnum)
        else:
            vnum = magic
            _ = _fread3(fobj)
            curv = np.fromfile(fobj, ">i2", vnum) / 100
    return curv


def load_scalar_data(filepath):
    """Load in scalar data from an image."""
    try:
        scalar_data = nib.load(filepath).get_data()
        scalar_data = scalar_data.ravel(order="F")
        return scalar_data

    except ImageFileError:
        ext = os.path.splitext(filepath)[1]
        if ext == ".mgz":
            openfile = gzip.open
        elif ext == ".mgh":
            openfile = open
        else:
            raise ValueError("Scalar file format must be readable "
                             "by Nibabl or .mg{hz} format")

    fobj = openfile(filepath, "rb")
    # We have to use np.fromstring here as gzip fileobjects don't work
    # with np.fromfile; same goes for try/finally instead of with statement
    try:
        v = np.fromstring(fobj.read(4), ">i4")[0]
        if v != 1:
            # I don't actually know what versions this code will read, so to be
            # on the safe side, let's only let version 1 in for now.
            # Scalar data might also be in curv format (e.g. lh.thickness)
            # in which case the first item in the file is a magic number.
            raise NotImplementedError("Scalar data file version not supported")
        ndim1 = np.fromstring(fobj.read(4), ">i4")[0]
        ndim2 = np.fromstring(fobj.read(4), ">i4")[0]
        ndim3 = np.fromstring(fobj.read(4), ">i4")[0]
        nframes = np.fromstring(fobj.read(4), ">i4")[0]
        datatype = np.fromstring(fobj.read(4), ">i4")[0]
        # Set the number of bytes per voxel and numpy data type according to
        # FS codes
        databytes, typecode = {0: (1, ">i1"), 1: (4, ">i4"), 3: (4, ">f4"),
                               4: (2, ">h")}[datatype]
        # Ignore the rest of the header here, just seek to the data
        fobj.seek(284)
        nbytes = ndim1 * ndim2 * ndim3 * nframes * databytes
        # Read in all the data, keep it in flat representation
        # (is this ever a problem?)
        scalar_data = np.fromstring(fobj.read(nbytes), typecode)
    finally:
        fobj.close()


def read_annot(filepath):
    """Load in a Freesurfer annotation from a .annot file."""
    # TODO: probably rewrite this, the matlab implementation is a big
    # hassle anyway.  Also figure out if Mayavi allows you to work with
    # a Freesurfer style LUT
    with open(filepath, "rb") as fobj:
        dt = ">i4"
        vnum = np.fromfile(fobj, dt, 1)[0]
        data = np.fromfile(fobj, dt, vnum * 2).reshape(vnum, 2)
        annot = data[:, 1]
        ctab_exists = np.fromfile(fobj, dt, 1)[0]
        if not ctab_exists:
            return
        ctab_version = np.fromfile(fobj, dt, 1)[0]
        if ctab_version != -2:
            return
        n_entries = np.fromfile(fobj, dt, 1)[0]
        ctab = np.zeros((n_entries, 5), np.int)
        length = np.fromfile(fobj, dt, 1)[0]
        _ = np.fromfile(fobj, "|S%d" % length, 1)[0]  # Orig table path
        entries_to_read = np.fromfile(fobj, dt, 1)[0]
        for i in xrange(entries_to_read):
            _ = np.fromfile(fobj, dt, 1)[0]  # Structure
            name_length = np.fromfile(fobj, dt, 1)[0]
            _ = np.fromfile(fobj, "|S%d" % name_length, 1)[0]  # Struct name
            ctab[i, :4] = np.fromfile(fobj, dt, 4)
            ctab[i, 4] = (ctab[i, 0] + ctab[i, 1] * (2 ** 8) +
                            ctab[i, 2] * (2 ** 16) + ctab[i, 3] * (2 ** 24))
    return ctab


def read_label(filepath):
    """Load in a Freesurfer .label file.

    Label files are just text files indicating the vertices included
    in the label. Each Surface instance has a dictionary of labels, keyed
    by the name (which is taken from the file name if not given as an argument.

    """
    label_array = np.loadtxt(filepath, dtype=np.int, skiprows=2, usecols=[0])
    return label_array


class Surface(object):
    """Container for surface object

    Attributes
    ----------
    subject_id : string
        Name of subject
    hemi : {'lh', 'rh'}
        Which hemisphere to load
    surf : string
        Name of the surface to load (eg. inflated, orig ...)
    data_path : string
        Path where to look for data
    x: 1d array
        x coordinates of vertices
    y: 1d array
        y coordinates of vertices
    z: 1d array
        z coordinates of vertices
    coords : 2d array of shape [n_vertices, 3]
        The vertices coordinates
    faces : 2d array
        The faces ie. the triangles
    """

    def __init__(self, subject_id, hemi, surf):
        """Surface

        Parameters
        ----------
        subject_id : string
            Name of subject
        hemi : {'lh', 'rh'}
            Which hemisphere to load
        surf : string
            Name of the surface to load (eg. inflated, orig ...)
        """
        self.subject_id = subject_id
        self.hemi = hemi
        self.surf = surf

        if 'SUBJECTS_DIR' not in os.environ:
            raise ValueError('Test suite relies on the definition of the '
                             'SUBJECTS_DIR environment variable')

        subj_dir = os.environ["SUBJECTS_DIR"]
        self.data_path = pjoin(subj_dir, subject_id)

    def load_geometry(self):
        surf_path = pjoin(self.data_path, "surf",
                          "%s.%s" % (self.hemi, self.surf))
        self.coords, self.faces = read_geometry(surf_path)

    @property
    def x(self):
        return self.coords[:, 0]

    @property
    def y(self):
        return self.coords[:, 1]

    @property
    def z(self):
        return self.coords[:, 2]

    def load_curvature(self):
        """Load in curavature values from the ?h.curv file."""
        curv_path = pjoin(self.data_path, "surf", "%s.curv" % self.hemi)
        self.curv = read_curvature(curv_path)
        self.bin_curv = np.array(self.curv > 0, np.int)

    def load_label(self, name):
        """Load in a Freesurfer .label file.

        Label files are just text files indicating the vertices included
        in the label. Each Surface instance has a dictionary of labels, keyed
        by the name (which is taken from the file name if not given as an
        argument.

        """
        label = read_label(pjoin(self.data_path, 'label',
                                 '%s.%s.label' % (self.hemi, name)))
        label_array = np.zeros(len(self.x), np.int)
        label_array[label] = 1
        try:
            self.labels[name] = label_array
        except AttributeError:
            self.labels = dict(name=label_array)

    def apply_xfm(self, mtx):
        """Apply an affine transformation matrix to the x,y,z vectors.
        TODO: Use Nipy function here"""
        self.coords = np.dot(np.c_[self.coords, np.ones(len(self.coords))],
                                     mtx.T)[:, :3]