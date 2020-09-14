from ase.data import covalent_radii
from ase.neighborlist import NeighborList


def split_bond(atoms, index1, index2):
    """Split atoms by a bond specified by indices"""
    assert index1 != index2
    if index2 > index1:
        shift = 0, 1
    else:
        shift = 1, 0
        
    atoms_copy = atoms.copy()
    del atoms_copy[index2]
    atoms1 = connected_atoms(atoms_copy, index1 - shift[0])
    
    atoms_copy = atoms.copy()
    del atoms_copy[index1]
    atoms2 = connected_atoms(atoms_copy, index2 - shift[1])
    
    return atoms1, atoms2


def connected_atoms(atoms, index, dmax=None, scale=1.5):
    """Find atoms connected to self[index] and return them."""
    return atoms[connected_indices(atoms, index, dmax, scale)]


def connected_indices(atoms, index, dmax=None, scale=1.5):
    """Find atoms connected to self[index] and return their indices.

    If dmax is not None:
    Atoms are defined to be connected if they are nearer than dmax
    to each other.

    If dmax is None:
    Atoms are defined to be connected if they are nearer than the
    sum of their covalent radii * scale to each other.

    """
    if index < 0:
        index = len(atoms) + index

    # set neighbor lists
    if dmax is None:
        # define neighbors according to covalent radii
        radii = scale * covalent_radii[atoms.get_atomic_numbers()]
    else:
        # define neighbors according to distance
        radii = [0.5 * dmax] * len(atoms)
    nl = NeighborList(radii, skin=0, self_interaction=False, bothways=True)
    nl.update(atoms)

    connected = [index] + list(nl.get_neighbors(index)[0])
    isolated = False
    while not isolated:
        isolated = True
        for i in connected:
            for j in nl.get_neighbors(i)[0]:
                if j in connected:
                    pass
                else:
                    connected.append(j)
                    isolated = False

    return connected
