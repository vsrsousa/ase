"""Storage and analysis for vibrational data"""

import collections
from math import sin, pi, sqrt
from numbers import Real, Integral
from typing import Any, Dict, Iterator, List, Sequence, Tuple, TypeVar, Union

import numpy as np

from ase.atoms import Atoms
import ase.units as units
import ase.io
from ase.utils import jsonable

from ase.calculators.singlepoint import SinglePointCalculator
from ase.spectrum.dosdata import RawDOSData
from ase.spectrum.doscollection import DOSCollection

RealSequence4D = Sequence[Sequence[Sequence[Sequence[Real]]]]
VD = TypeVar('VD', bound='VibrationsData')


@jsonable('vibrationsdata')
class VibrationsData:
    """Class for storing and analyzing vibrational data (i.e. Atoms + Hessian)

    This class is not responsible for calculating Hessians; the Hessian should
    be computed by a Calculator or some other algorithm. Once the
    VibrationsData has been constructed, this class provides some common
    processing options; frequency calculation, mode animation, DOS etc.

    If the Atoms object is a periodic supercell, VibrationsData may be
    converted to a PhononData using the VibrationsData.to_phonondata() method.
    This provides access to q-point-dependent analyses such as phonon
    dispersion plotting.

    Args:
        atoms:
            Equilibrium geometry of vibrating system. This will be stored as a
            lightweight copy with just positions, masses, unit cell.

        hessian: Second-derivative in energy with respect to
            Cartesian nuclear movements as an (N, 3, N, 3) array.
        indices: indices of atoms which are included
            in Hessian.  Default value (None) includes all atoms.

    """
    def __init__(self,
                 atoms: Atoms,
                 hessian: Union[RealSequence4D, np.ndarray],
                 indices: Union[Sequence[int], np.ndarray] = None,
                 ) -> None:

        if indices is None:
            self._indices = np.array(range(len(atoms)))
        else:
            self._indices = np.array(indices, dtype=int)

        n_atoms = self._check_dimensions(atoms, np.asarray(hessian),
                                         indices=self._indices)
        self._atoms = atoms.copy()

        self._hessian2d = (np.asarray(hessian)
                           .reshape(3 * n_atoms, 3 * n_atoms).copy())

        self._energies = None  # type: Union[np.ndarray, None]
        self._modes = None  # type: Union[np.ndarray, None]

    _setter_error = ("VibrationsData properties cannot be modified: construct "
                     "a new VibrationsData with consistent atoms, Hessian and "
                     "(optionally) indices/mask.")

    @classmethod
    def from_2d(cls, atoms: Atoms,
                hessian_2d: Union[Sequence[Sequence[Real]], np.ndarray],
                indices: Sequence[int] = None) -> 'VibrationsData':
        """Instantiate VibrationsData when the Hessian is in a 3Nx3N format

        Args:
            atoms: Equilibrium geometry of vibrating system

            hessian: Second-derivative in energy with respect to
                Cartesian nuclear movements as a (3N, 3N) array.

            indices: Indices of (non-frozen) atoms included in Hessian

        """
        if indices is None:
            indices = range(len(atoms))
        assert indices is not None  # Show Mypy that indices is now a sequence

        hessian_2d_array = np.asarray(hessian_2d)
        n_atoms = cls._check_dimensions(atoms, hessian_2d_array,
                                        indices=indices, two_d=True)

        return cls(atoms, hessian_2d_array.reshape(n_atoms, 3, n_atoms, 3),
                   indices=indices)

    @staticmethod
    def indices_from_mask(mask: Union[Sequence[bool], np.ndarray]
                          ) -> List[int]:
        """Indices corresponding to boolean mask

        This is provided as a convenience for instantiating VibrationsData with
        a boolean mask. For example, if the Hessian data includes only the H
        atoms in a structure::

          h_mask = atoms.get_chemical_symbols() == 'H'
          vib_data = VibrationsData(atoms, hessian,
                                    VibrationsData.indices_from_mask(h_mask))

        Take care to ensure that the length of the mask corresponds to the full
        number of atoms; this function is only aware of the mask it has been
        given.

        Args:
            mask: a sequence of True, False values

        Returns:
            indices of True elements

        """
        return np.where(mask)[0].tolist()

    @staticmethod
    def _check_dimensions(atoms: Atoms,
                          hessian: np.ndarray,
                          indices: Sequence[int],
                          two_d: bool = False) -> int:
        """Sanity check on array shapes from input data

        Args:
            atoms: Structure
            indices: Indices of atoms used in Hessian
            hessian: Proposed Hessian array

        Returns:
            Number of atoms contributing to Hessian

        Raises:
            ValueError if Hessian dimensions are not (N, 3, N, 3)

        """

        n_atoms = len(atoms[indices])

        if two_d:
            ref_shape = [n_atoms * 3, n_atoms * 3]
            ref_shape_txt = '{n:d}x{n:d}'.format(n=(n_atoms * 3))

        else:
            ref_shape = [n_atoms, 3, n_atoms, 3]
            ref_shape_txt = '{n:d}x3x{n:d}x3'.format(n=n_atoms)

        if (isinstance(hessian, np.ndarray)
            and hessian.shape == tuple(ref_shape)):
            return n_atoms
        else:
            raise ValueError("Hessian for these atoms should be a "
                             "{} numpy array.".format(ref_shape_txt))

    def get_atoms(self) -> Atoms:
        return self._atoms.copy()

    def get_indices(self) -> Union[None, np.ndarray]:
        return np.array(self._indices, dtype=int)

    def get_mask(self) -> np.ndarray:
        """Boolean mask of atoms selected by indices"""
        return self._mask_from_indices(self._atoms, self.get_indices())

    @staticmethod
    def _mask_from_indices(atoms: Atoms,
                           indices: Union[None, Sequence[int], np.ndarray]
                           ) -> np.ndarray:
        """Boolean mask of atoms selected by indices"""
        natoms = len(atoms)

        # Wrap indices to allow negative values
        indices = np.asarray(indices) % natoms

        mask = np.full(natoms, False, dtype=bool)
        mask[indices] = True
        return mask

    def get_hessian(self) -> np.ndarray:
        """The Hessian; second derivative of energy wrt positions

        This format is preferred for iteration over atoms and when
        addressing specific elements of the Hessian.

        Returns:
            array with shape (n_atoms, 3, n_atoms, 3) where
            - the first and third indices identify atoms in self.get_atoms()
            - the second and fourth indices cover the corresponding Cartesian
              movements in x, y, z

            e.g. the element h[0, 2, 1, 0] gives a harmonic force exerted on
            atoms[1] in the x-direction in response to a movement in the
            z-direction of atoms[0]

        """
        n_atoms = int(self._hessian2d.shape[0] / 3)
        return self._hessian2d.reshape(n_atoms, 3, n_atoms, 3).copy()

    def get_hessian_2d(self) -> np.ndarray:
        """Get the Hessian as a 2-D array

        This format may be preferred for use with standard linear algebra
        functions

        Returns:
            array with shape (n_atoms * 3, n_atoms * 3) where the elements are
            ordered by atom and Cartesian direction

            [[at1x_at1x, at1x_at1y, at1x_at1z, at1x_at2x, ...],
             [at1y_at1x, at1y_at1y, at1y_at1z, at1y_at2x, ...],
             [at1z_at1x, at1z_at1y, at1z_at1z, at1z_at2x, ...],
             [at2x_at1x, at2x_at1y, at2x_at1z, at2x_at2x, ...],
             ...]

            e.g. the element h[2, 3] gives a harmonic force exerted on
            atoms[1] in the x-direction in response to a movement in the
            z-direction of atoms[0]

        """
        return self._hessian2d.copy()

    def todict(self) -> Dict[str, Any]:
        if np.allclose(self._indices, range(len(self._atoms))):
            indices = None
        else:
            indices = self.get_indices()

        return {'atoms': self.get_atoms(),
                'hessian': self.get_hessian(),
                'indices': indices}

    @classmethod
    def fromdict(cls, data: Dict[str, Any]) -> 'VibrationsData':
        # mypy is understandably suspicious of data coming from a dict that
        # holds mixed types, but it can see if we sanity-check with 'assert'
        assert isinstance(data['atoms'], Atoms)
        assert isinstance(data['hessian'], (collections.abc.Sequence,
                                            np.ndarray))
        if data['indices'] is not None:
            assert isinstance(data['indices'], (collections.abc.Sequence,
                                                np.ndarray))
            for index in data['indices']:
                assert isinstance(index, Integral)

        return cls(data['atoms'], data['hessian'], indices=data['indices'])

    def _calculate_energies_and_modes(self) -> Tuple[np.ndarray, np.ndarray]:
        """Diagonalise the Hessian to obtain harmonic modes

        This method is an internal implementation of get_energies_and_modes(),
        see the docstring of that method for more information.

        """
        active_atoms = self._atoms[self.get_mask()]
        n_atoms = len(active_atoms)
        masses = active_atoms.get_masses()

        if not np.all(masses):
            raise ValueError('Zero mass encountered in one or more of '
                             'the vibrated atoms. Use Atoms.set_masses()'
                             ' to set all masses to non-zero values.')
        mass_weights = np.repeat(masses**-0.5, 3)

        omega2, vectors = np.linalg.eigh(mass_weights
                                         * self.get_hessian_2d()
                                         * mass_weights[:, np.newaxis])

        unit_conversion = units._hbar * units.m / sqrt(units._e * units._amu)
        energies = unit_conversion * omega2.astype(complex)**0.5

        modes = vectors.T.reshape(n_atoms * 3, n_atoms, 3)
        modes = modes * masses[np.newaxis, :, np.newaxis]**-0.5

        return (energies, modes)

    def get_energies_and_modes(self) -> Tuple[np.ndarray, np.ndarray]:
        """Diagonalise the Hessian to obtain harmonic modes

        Results are cached so diagonalization will only be performed once for
        this object instance.

        Returns:
            tuple (energies, modes)

            Energies are given in units of eV. (To convert these to frequencies
            in cm-1, divide by ase.units.invcm.)

            Modes are given in Cartesian coordinates as a (3N, N, 3) array
            where indices correspond to the (mode_index, atom, direction).

            Note that in this array only the moving atoms are included.

        """
        if self._energies is None or self._modes is None:
            self._energies, self._modes = self._calculate_energies_and_modes()
            return self.get_energies_and_modes()
        else:
            return (self._energies.copy(), self._modes.copy())

    def get_modes(self) -> np.ndarray:
        """Diagonalise the Hessian to obtain harmonic modes

        Results are cached so diagonalization will only be performed once for
        this object instance.

        Returns:
            Modes in Cartesian coordinates as a (3N, N, 3) array where indices
            correspond to the (mode_index, atom, direction).

        """
        return self.get_energies_and_modes()[1]

    def get_energies(self) -> np.ndarray:
        """Diagonalise the Hessian to obtain eigenvalues

        Results are cached so diagonalization will only be performed once for
        this object instance.

        Returns:
            Harmonic mode energies in units of eV

        """
        return self.get_energies_and_modes()[0]

    def get_frequencies(self) -> np.ndarray:
        """Diagonalise the Hessian to obtain frequencies in cm^-1

        Results are cached so diagonalization will only be performed once for
        this object instance.

        Returns:
            Harmonic mode frequencies in units of cm^-1

        """

        return self.get_energies() / units.invcm

    def get_zero_point_energy(self) -> float:
        """Diagonalise the Hessian and sum hw/2 to obtain zero-point energy

        Args:
            energies:
                Pre-computed energy eigenvalues. Use if available to avoid
                re-calculating these from the Hessian.

        Returns:
            zero-point energy in eV
        """
        return self._calculate_zero_point_energy(self.get_energies())

    @staticmethod
    def _calculate_zero_point_energy(energies: Union[Sequence[complex],
                                                     np.ndarray]) -> float:
        return 0.5 * np.asarray(energies).real.sum()

    def tabulate(self, im_tol: float = 1e-8) -> str:
        """Print a summary of the vibrational frequencies.

        Args:
            logfile: if specified, write output to this destination. This can
                be an object with a write() method or the name of a file to
                create. Otherwise, summary is returned as a string.
            im_tol:
                Tolerance for imaginary frequency in eV. If frequency has a
                larger imaginary component than im_tol, the imaginary component
                is shown in the summary table.

        Returns:
            Summary text, if no output was set.
        """

        energies = self.get_energies()

        return ('\n'.join(self._tabulate_from_energies(energies,
                                                       im_tol=im_tol))
                + '\n')

    @classmethod
    def _tabulate_from_energies(cls,
                                energies: Union[Sequence[complex], np.ndarray],
                                im_tol: float = 1e-8) -> List[str]:
        summary_lines = ['---------------------',
                         '  #    meV     cm^-1',
                         '---------------------']

        for n, e in enumerate(energies):
            if abs(e.imag) > im_tol:
                c = 'i'
                e = e.imag
            else:
                c = ''
                e = e.real

            summary_lines.append('{index:3d} {mev:6.1f}{im:1s}  {cm:7.1f}{im}'
                                 .format(index=n, mev=(e * 1e3),
                                         cm=(e / units.invcm), im=c))
        summary_lines.append('---------------------')
        summary_lines.append('Zero-point energy: {:.3f} eV'.format(
            cls._calculate_zero_point_energy(energies=energies)))

        return summary_lines

    def iter_animated_mode(self, mode_index: int,
                           temperature: float = units.kB * 300,
                           frames: int = 30) -> Iterator[Atoms]:
        """Obtain animated mode as a series of Atoms

        Args:
            mode_index: Selection of mode to animate
            temperature: In energy units - use units.kB * T_IN_KELVIN
            frames: number of image frames in animation

        Yields:
            Displaced atoms following vibrational mode

        """

        mode = (self.get_modes()[mode_index]
                * sqrt(temperature / abs(self.get_energies()[mode_index])))

        for phase in np.linspace(0, 2 * pi, frames, endpoint=False):
            atoms = self.get_atoms()
            atoms.positions[self.get_mask()] = (
                atoms.positions[self.get_mask()] + sin(phase) * mode)

            yield atoms

    def show_as_force(self,
                      mode: int,
                      scale: float = 0.2,
                      show: bool = True) -> Atoms:
        """Illustrate mode as "forces" on atoms

        Args:
            mode: mode index
            scale: scale factor
            show: if True, open the ASE GUI and show atoms

        Returns:
            Atoms with scaled forces corresponding to mode eigenvectors (using
            attached SinglePointCalculator).

        """

        atoms = self.get_atoms()
        mode = self.get_modes()[mode] * len(atoms) * 3 * scale
        atoms.calc = SinglePointCalculator(atoms, forces=mode)
        if show:
            atoms.edit()

        return atoms

    def write_jmol(self,
                   filename: str = 'vib.xyz',
                   ir_intensities: Union[Sequence[float], np.ndarray] = None
                   ) -> None:
        """Writes file for viewing of the modes with jmol.

        This is an extended XYZ file with eigenvectors given as extra columns
        and metadata given in the label/comment line for each image. The format
        is not quite human-friendly, but has the advantage that it can be
        imported back into ASE with ase.io.read.

        Args:
            filename: Path for output file
            energies_and_modes: Use pre-computed eigenvalue/eigenvector data if
                available; otherwise it will be recalculated from the Hessian.
            ir_intensities: If available, IR intensities can be included in the
                header lines. This does not affect the visualisation, but may
                be convenient when comparing to experimental data.
        """

        energies_and_modes = self.get_energies_and_modes()

        all_images = []
        for i, (energy, mode) in enumerate(zip(*energies_and_modes)):
            # write imaginary frequencies as negative numbers
            if energy.imag > energy.real:
                energy = float(-energy.imag)
            else:
                energy = energy.real

            image = self.get_atoms()
            image.info.update({'mode#': str(i),
                               'frequency_cm-1': energy / units.invcm,
                               })
            image.arrays['mode'] = np.zeros_like(image.positions)
            image.arrays['mode'][self.get_mask()] = mode

            # Custom masses are quite useful in vibration analysis, but will
            # show up in the xyz file unless we remove them
            if image.has('masses'):
                del image.arrays['masses']

            if ir_intensities is not None:
                image.info['IR_intensity'] = float(ir_intensities[i])

            all_images.append(image)
        ase.io.write(filename, all_images, format='extxyz')

    def get_dos(self) -> RawDOSData:
        """Total phonon DOS"""
        energies = self.get_energies()
        return RawDOSData(energies, np.ones_like(energies))

    def get_pdos(self) -> DOSCollection:
        """Phonon DOS, including atomic contributions"""
        energies = self.get_energies()
        masses = self._atoms[self.get_mask()].get_masses()

        # Get weights as N_moving_atoms x N_modes array
        vectors = self.get_modes() / masses[np.newaxis, :, np.newaxis]**-0.5
        all_weights = (np.linalg.norm(vectors, axis=-1)**2).T

        mask = self.get_mask()
        all_info = [{'index': i, 'symbol': a.symbol}
                    for i, a in enumerate(self._atoms) if mask[i]]

        return DOSCollection([RawDOSData(energies, weights, info=info)
                              for weights, info in zip(all_weights, all_info)])

    def with_new_masses(self: VD, masses: Union[Sequence[float], np.ndarray]
                        ) -> VD:
        """Get a copy of vibrations with modified masses and the same Hessian

        Args:
            masses:
                New sequence of masses corresponding to the atom order in
                self.get_atoms()
        Returns:
            A copy of the data with new masses for the same Hessian
        """

        new_atoms = self.get_atoms()
        new_atoms.set_masses(masses)
        return self.__class__(new_atoms, self.get_hessian(),
                              indices=self.get_indices())
