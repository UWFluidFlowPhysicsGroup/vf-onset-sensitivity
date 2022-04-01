"""
Testing code for finding hopf bifurcations of coupled FE VF models
"""
# import sys
from os import path
from petsc4py import PETSc
from slepc4py import SLEPc
import numpy as np

from femvf.dynamicalmodels import solid as sldm, fluid as fldm
from femvf.load import load_dynamical_fsi_model
from femvf.meshutils import process_celllabel_to_dofs_from_forms

import nonlineq as nleq

import blocktensor.subops as gops
from blocktensor import vec as bvec

from libhopf import make_hopf_system, normalize_eigenvector_by_hopf_condition
import libhopf

# pylint: disable=redefined-outer-name
# pylint: disable=no-member

TEST_FP = True
TEST_MODAL = True
TEST_HOPF_BIFURCATION = True

EBODY = 5e3 * 10
ECOV = 5e3 * 10
PSUB = 450 * 10

def setup_models():
    """
    Return residual + linear residual needed to model the Hopf system
    """
    # mesh_name = 'BC-dcov5.00e-02-coarse'
    mesh_name = 'BC-dcov5.00e-02-cl2.00'
    # mesh_name = 'vf-square'
    mesh_path = path.join('./mesh', mesh_name+'.xml')

    res = load_dynamical_fsi_model(
        mesh_path, None, SolidType = sldm.KelvinVoigt,
        FluidType = fldm.Bernoulli1DDynamicalSystem,
        fsi_facet_labels=('pressure',), fixed_facet_labels=('fixed',))

    dres = load_dynamical_fsi_model(
        mesh_path, None, SolidType = sldm.LinearizedKelvinVoigt,
        FluidType = fldm.LinearizedBernoulli1DDynamicalSystem,
        fsi_facet_labels=('pressure',), fixed_facet_labels=('fixed',))

    return res, dres

def set_properties(props, region_to_dofs, res):
    """
    Set the model properties
    """
    # VF material props
    gops.set_vec(props['emod'], ECOV)
    gops.set_vec(props['emod'], EBODY)
    gops.set_vec(props['eta'], 5.0)
    gops.set_vec(props['rho'], 1.0)
    gops.set_vec(props['nu'], 0.45)

    # Fluid separation smoothing props
    gops.set_vec(props['zeta_min'], 1.0e-4)
    gops.set_vec(props['zeta_sep'], 1.0e-4)

    # Contact and midline symmetry properties
    # y_gap = 0.5 / 10 # Set y gap to 0.5 mm
    # y_gap = 1.0
    y_gap = 0.01
    y_contact_offset = 1/10*y_gap
    y_max = res.solid.forms['mesh.mesh'].coordinates()[:, 1].max()
    y_mid = y_max + y_gap
    y_contact = y_mid - y_contact_offset
    gops.set_vec(props['ycontact'], y_contact)
    gops.set_vec(props['kcontact'], 1e16)
    gops.set_vec(props['ymid'], y_mid)

    return props


if __name__ == '__main__':
    ## Load the models
    res, dres = setup_models()

    ## Set model properties
    region_to_dofs = process_celllabel_to_dofs_from_forms(
        res.solid.forms, res.solid.forms['fspace.scalar'])

    props = res.properties.copy()
    props = set_properties(props, region_to_dofs, res)

    ## Initialize the Hopf system
    # This vector normalizes the real/imag components of the unstable eigenvector
    EREF = res.state.copy()
    EREF['q'].set(1.0)
    EREF.set(1.0)
    (
        xhopf, hopf_res, hopf_jac,
        apply_dirichlet_vec, apply_dirichlet_mat,
        labels, info) = make_hopf_system(res, dres, props, EREF)
    (
        state_labels, mode_real_labels, mode_imag_labels,
        psub_labels, omega_labels) = labels

    IDX_DIRICHLET = info['dirichlet_dofs']

    ## Test solving for fixed-points
    _control = res.control.copy()
    _control['psub'] = PSUB
    res.set_control(_control)

    if TEST_FP:
        print("\n-- Test solution of fixed-points --")
        newton_params = {
            'maximum_iterations': 20
        }
        xfp_0 = res.state.copy()
        xfp_n, info = libhopf.solve_fixed_point(res, xfp_0, newton_params=newton_params)
        print(info)

    ## Test solving for stabilty (modal analysis of the jacobian)
    _XHOPF = xhopf.copy()
    _XHOPF[state_labels] = xfp_n
    _XHOPF['psub'].array[:] = PSUB
    _XHOPF['omega'].array[:] = 1.0 # have to set omega=1 to get correct jacobian

    if TEST_MODAL:
        print("\n-- Test modal analysis of system linearized dynamics --")
        # Here we solve the eigenvalue problem
        # omega df/dxt ex = df/dx ex
        # in the transformed form
        # df/dxt ex = lambda df/dx ex
        # where lambda=1/omega, and ex is a generalized eigenvector
        omegas, eigvecs_real, eigvecs_imag = libhopf.solve_ls(res, xfp_n)
        print(omegas)

    idx_hopf = 3
    omega_hopf = abs(omegas[idx_hopf].imag)
    mode_real_hopf = eigvecs_real[idx_hopf]
    mode_imag_hopf = eigvecs_imag[idx_hopf]

    ## Test solving the Hopf system for the Hopf bifurcation
    # set the initial guess based on the stability analysis and fixed-point solution
    xhopf_0 = xhopf.copy()
    xhopf_0[state_labels] = xfp_n
    xhopf_0['psub'].array[:] = PSUB
    xhopf_0['omega'].array[:] = -omega_hopf

    xmode_real, xmode_imag = normalize_eigenvector_by_hopf_condition(mode_real_hopf, mode_imag_hopf, EREF)
    xhopf_0[mode_real_labels] = xmode_real
    xhopf_0[mode_imag_labels] = xmode_imag

    def linear_subproblem_hopf(xhopf_n):
        """Linear subproblem of a Newton solver"""
        res_n = hopf_res(xhopf_n)
        jac_n = hopf_jac(xhopf_n)
        apply_dirichlet_vec(res_n)
        apply_dirichlet_mat(jac_n)

        def assem_res():
            """Return residual"""
            return res_n

        def solve(rhs_n):
            """Return jac^-1 res"""
            _rhs_n = rhs_n.to_petsc()
            _jac_n = jac_n.to_petsc()
            _dx_n = _jac_n.getVecRight()

            ksp = PETSc.KSP().create()
            ksp.setType(ksp.Type.PREONLY)
            ksp.setOperators(_jac_n)

            pc = ksp.getPC()
            pc.setType(pc.Type.LU)

            pc.setUp()
            ksp.setUp()
            ksp.solve(_rhs_n, _dx_n)

            dx_n = xhopf_n.copy()
            dx_n.set_vec(_dx_n)
            return dx_n
        return assem_res, solve

    if TEST_HOPF_BIFURCATION:
        print("\n-- Test solution of Hopf system for Hopf bifurcation point --")

        newton_params = {
            'maximum_iterations': 20
        }
        xhopf_n, info = nleq.newton_solve(xhopf_0, linear_subproblem_hopf, norm=bvec.norm, params=newton_params)
        print(xhopf_n.norm())
        print(info)
        # breakpoint()
