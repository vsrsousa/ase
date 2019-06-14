import itertools
import numpy as np
from ase.geometry.bravais import (bravais_lattices, UnconventionalLattice,
                                  bravais_names,
                                  get_lattice_from_canonical_cell)
from ase.geometry import Cell

"""This module implements a crude method to recognize most Bravais lattices.

There are probably better methods, and this particularly dreadful one
is an implementation detail.

Suppose we use the ase.geometry.bravais module to generate many
lattices of some particular type, say, BCT(a, c), and then we
Niggli-reduce all of them.  The Niggli-reduced forms are not
immediately recognizable, but we know the mapping from each reduced
form back to the original form.  As it turns out, there are apparently
5 such mappings (the proof is left as an exercise for the reader).

Hence, presumably, every BCT lattice (whether generated by BCT(a, c)
or in some other form) Niggli-reduces to a form which, through the
inverse of one of those five operations, is mapped back to the
recognizable one.  Knowing all five operations (or equivalence
classes), we can characterize any BCT lattice.  Same goes for the
other lattices of sufficiently low dimension, though not for MCL,
MCLC, and TRI.  The set of Niggli-reduced forms of those lattices
appears to be unbounded (the proof is left as an exercise for the
reader).

It may yet be possible to characterize MCL/MCLC/TRI lattices with
reasonably normal parameters this way as well, just not all of
them."""


niggli_op_table = {  # Generated by generate_niggli_op_table()
 'BCC': [(1, 0, 0, 0, 1, 0, 0, 0, 1)],
 'BCT': [(1, 0, 0, 0, 1, 0, 0, 0, 1),
         (0, 1, 0, 0, 0, 1, 1, 0, 0),
         (0, 1, 0, 1, 0, 0, 1, 1, -1),
         (-1, 0, 1, 0, 1, 0, -1, 1, 0),
         (1, 1, 0, 1, 0, 0, 0, 0, -1)],
 'CUB': [(1, 0, 0, 0, 1, 0, 0, 0, 1)],
 'FCC': [(1, 0, 0, 0, 1, 0, 0, 0, 1)],
 'HEX': [(1, 0, 0, 0, 1, 0, 0, 0, 1), (0, 1, 0, 0, 0, 1, 1, 0, 0)],
 'ORC': [(1, 0, 0, 0, 1, 0, 0, 0, 1)],
 'ORCC': [(1, 0, 0, 0, 1, 0, 0, 0, 1),
          (1, 0, -1, 1, 0, 0, 0, -1, 0),
          (-1, 1, 0, -1, 0, 0, 0, 0, 1),
          (0, 1, 0, 0, 0, 1, 1, 0, 0),
          (0, -1, 1, 0, -1, 0, 1, 0, 0)],
 'ORCF': [(0, -1, 0, 0, 1, -1, 1, 0, 0), (-1, 0, 0, 1, 0, 1, 1, 1, 0)],
 'ORCI': [(0, 0, -1, 0, -1, 0, -1, 0, 0),
          (0, 0, 1, -1, 0, 0, -1, -1, 0),
          (0, 1, 0, 1, 0, 0, 1, 1, -1),
          (0, -1, 0, 1, 0, -1, 1, -1, 0)],
 'RHL': [(0, -1, 0, 1, 1, 1, -1, 0, 0),
         (1, 0, 0, 0, 1, 0, 0, 0, 1),
         (1, -1, 0, 1, 0, -1, 1, 0, 0)],
 'TET': [(1, 0, 0, 0, 1, 0, 0, 0, 1), (0, 1, 0, 0, 0, 1, 1, 0, 0)],
 'MCL': [(0, -1, 0, -1, 0, 0, 0, 0, -1),
         (-1, 0, 0, 0, 1, 0, 0, 0, -1),
         (-1, 0, 0, 0, 0, 1, 0, 1, 0),
         (0, 0, -1, 1, 0, 0, 0, -1, 0),
         (1, 0, 0, 0, -1, 0, 0, 0, -1),
         (0, 1, 0, -1, 0, 0, 0, 0, 1),
         (-1, 0, 0, 0, 0, -1, 0, -1, 0),
         (1, 0, 0, 0, 1, 0, 0, 0, 1)],
 'MCLC': [(0, -1, 0, -1, 0, 0, 0, 0, -1),
          (-1, 0, 0, 0, 1, 0, 0, 0, -1),
          (1, 0, 0, 0, -1, 0, 0, 0, -1),
          (-1, 0, 0, 0, -1, 0, 0, 0, 1),
          (0, 1, 0, -1, 0, 0, 0, 0, 1),
          (1, 0, 0, 0, 1, 0, 0, 0, 1),
          (0, -1, 0, -1, 0, -1, 0, 0, -1),
          (-1, 0, -1, 0, 1, 0, 0, 0, -1),
          (0, 1, 0, 1, 0, 0, 0, 0, -1),
          (-1, 0, -1, 0, -1, 0, 0, 0, 1),
          (0, -1, 0, 1, 0, 0, 0, 0, 1),
          (1, 0, 1, 0, -1, 0, 0, 0, -1),
          (0, 0, 1, -1, 0, 0, 0, -1, 0),
          (-1, 0, 0, 0, 1, 1, 0, 0, -1),
          (1, 0, 1, 0, 1, 0, 0, 0, 1)]
}


def greedy_lattice_reduce(cell):
    ndim = len(cell)
    #op = np.eye(ndim, dtype=int)

    if ndim == 1:
        return cell, 0#, op

    i = 0
    while True:
        # Order vectors by norm:
        squared_lengths = (cell**2).sum(axis=1)
        args = np.argsort(squared_lengths)
        cell = cell[args]
        #op = op[args]

        # Recursive ndim - 1 reduction:
        cell[:-1], _ = greedy_lattice_reduce(cell[:-1])
        #op[:-1] = op1 @ op[:, 1]
        i += 1

        assert cell.shape == (ndim, 3)

        H = np.empty((ndim - 1, ndim - 1))
        for i in range(ndim - 1):
            for j in range(ndim - 1):
                H[i, j] = np.vdot(cell[i], cell[j]) / np.vdot(cell[i], cell[i])

        # Compute vector c closest to cell[-1] within the lattice cell[:-1].
        tvec = cell[-1]
        coords = np.empty(ndim - 1)
        for i in range(ndim - 1):
            coords[i] = np.vdot(cell[i], tvec) / np.vdot(cell[i], cell[i])
        yvec = np.linalg.inv(H) @ coords  # XXX transpose H or not?

        lower = np.floor(yvec).astype(int)
        upper = np.ceil(yvec).astype(int)

        closest = None
        mindist = np.inf

        for coefs in itertools.product(*zip(lower, upper)):
            candidate = np.dot(coefs, cell[:-1])
            dist = np.linalg.norm(candidate - cell[-1])
            if dist < mindist:
                mindist = dist
                closest = candidate

        cell[-1] -= closest
        #op[-1, closest] -= 1  # XXX ?

        if np.linalg.norm(cell[-1]) >= np.linalg.norm(cell[-2]):
            return cell, i#, op


def lattice_loop(latcls, length_grid, angle_grid):
    param_grids = []
    for varname in latcls.parameters:
        # Actually we could choose one parameter, a, to always be 1,
        # reducing the dimension of the problem by 1.  The lattice
        # recognition code should do something like that as well, but
        # it doesn't.  This could affect the impact of the eps value
        # on lattice determination, so we just loop over the whole
        # thing in order not to worry.
        if latcls.name in ['MCL', 'MCLC']:
            special_var = 'c'
        else:
            special_var = 'a'
        if varname == special_var:
            values = np.ones(1)
        elif varname in 'abc':
            values = length_grid
        elif varname == 'alpha':
            values = angle_grid
        else:
            raise ValueError(varname)
        param_grids.append(values)

    for latpars in itertools.product(*param_grids):
        kwargs = dict(zip(latcls.parameters, latpars))
        try:
            lat = latcls(**kwargs)
        except UnconventionalLattice:
            pass
        else:
            yield lat


def find_niggli_ops(latcls, length_grid, angle_grid):
    niggli_ops = {}

    for lat in lattice_loop(latcls, length_grid, angle_grid):
        cell = lat.tocell()

        glr_obj = greedy_lattice_reduce(cell)
        gcell = glr_obj[0]
        cell = Cell(gcell)

        rcell, op = cell.niggli_reduce()
        int_op = op.round().astype(int)
        op_integer_err = np.abs(op - int_op).max()
        assert op_integer_err < 1e-12, op_integer_err

        inv_op_float = np.linalg.inv(op)
        inv_op = inv_op_float.round().astype(int)
        inv_op_integer_err = np.abs(inv_op_float - inv_op).max()
        assert inv_op_integer_err < 1e-12, inv_op_integer_err

        op_key = tuple(int_op.flat[:].tolist())
        if op_key in niggli_ops:
            niggli_ops[op_key] += 1
        else:
            niggli_ops[op_key] = 1

        rcell_test = Cell(op.T @ cell)
        rcellpar_test = rcell_test.cellpar()
        rcellpar = rcell.cellpar()
        err = np.abs(rcellpar_test - rcellpar).max()
        assert err < 1e-7, err

    return niggli_ops


def find_all_niggli_ops(length_grid, angle_grid, lattices=None):
    all_niggli_ops = {}
    if lattices is None:
        lattices = [name for name in bravais_names
                    if name not in ['MCL', 'MCLC', 'TRI']]

    for latname in lattices:
        latcls = bravais_lattices[latname]
        if latcls.ndim < 3:
            continue

        print('Working on {}...'.format(latname))
        niggli_ops = find_niggli_ops(latcls, length_grid, angle_grid)
        print('Found {} ops for {}'.format(len(niggli_ops), latname))
        for key, count in niggli_ops.items():
            print('  {:>40}: {}'.format(str(np.array(key)), count))
        print()
        all_niggli_ops[latname] = niggli_ops
    return all_niggli_ops


def check_type(rcell, name, eps):
    niggli_ops = niggli_op_table[name]
    results = []

    for op in niggli_ops:
        op = np.array(op, int).reshape(3, 3)
        candidate = Cell(np.linalg.inv(op.T) @ rcell)
        # XXX Think about what errors and why
        try:
            lat = get_lattice_from_canonical_cell(candidate, eps)
        except (AssertionError, UnconventionalLattice, RuntimeError):
            continue
        if lat.name in ['TRI']:
            continue
        results.append((lat, op))

    return results



def identify_lattice(cell, eps):
    cell = Cell.ascell(cell)
    rcell, op = cell.niggli_reduce()
    for testlat in bravais_names:
        if testlat in ['TRI']:
            continue
        if bravais_lattices[testlat].ndim < 3:
            continue

        results = check_type(rcell, testlat, eps)

        for name in bravais_names:
            for lat, std_op in results:
                if lat.name == name:
                    return lat, std_op @ np.linalg.inv(op)

    raise RuntimeError('Cannot recognize cell: {}'.format(cell.cellpar()))



def generate_niggli_op_table(lattices=None,
                             length_grid=None,
                             angle_grid=None):

    if length_grid is None:
        length_grid = np.logspace(-0.5, 1.5, 50).round(3)
    if angle_grid is None:
        angle_grid = np.linspace(10, 179, 50).round()
    all_niggli_ops_and_counts = find_all_niggli_ops(length_grid, angle_grid,
                                                    lattices=lattices)

    niggli_op_table = {}
    for latname, ops in all_niggli_ops_and_counts.items():
        niggli_op_table[latname] = list(ops)

    import pprint
    print(pprint.pformat(niggli_op_table))
    return niggli_op_table

def test():
    length_grid = np.logspace(-0.5, 1.5, 11).round(3)
    angle_grid = np.linspace(10, 179, 11).round()
    #all_ops = find_all_niggli_ops(length_grid, angle_grid)
    #niggli_op_table.clear()
    #niggli_op_table.update(all_ops)

    for latname in bravais_names:
        if latname in ['MCL', 'MCLC', 'TRI']:
            continue
        latcls = bravais_lattices[latname]
        if latcls.ndim != 3:
            continue

        print('Check', latname)
        maxerr = 0.0

        for lat in lattice_loop(latcls, length_grid, angle_grid):
            cell = lat.tocell()
            out_lat, op = identify_lattice(cell, eps=2e-4)

            # Some lattices represent simpler lattices,
            # e.g. TET(a, a) is cubic.  What we need to check is that
            # the cell parameters are the same.
            cellpar = cell.cellpar()
            outcellpar = out_lat.tocell().cellpar()
            err = np.abs(outcellpar - cellpar).max()
            maxerr = max(err, maxerr)
            if lat.name != out_lat.name:
                print(repr(lat), '-->', repr(out_lat))
            assert err < 1e-8, (err, repr(lat), repr(out_lat))

        print('    OK.  Maxerr={}'.format(maxerr))

if __name__ == '__main__':
    import sys
    lattices = sys.argv[1:]
    if not lattices:
        lattices = None
    length_grid = np.logspace(-2, 2, 100).round(3)
    angle_grid = np.linspace(1, 90, 90) #np.arange(5, 90)
    table = generate_niggli_op_table(lattices=lattices,
                                     angle_grid=angle_grid,
                                     length_grid=length_grid)
    for key in table:
        print('{}: {}'.format(key, len(table[key])))
