"""
This modules sets up a 'standard' Hopf model to test
"""

import h5py

from femvf.models.transient import solid as tsmd, fluid as tfmd
from femvf.models.dynamical import solid as dsmd, fluid as dfmd
from femvf import load
from femvf.meshutils import process_celllabel_to_dofs_from_forms

import blockarray.subops as gops
from blockarray import h5utils

import libhopf

def transient_fluidtype_from_sep_method(sep_method):
    if sep_method == 'fixed':
        return tfmd.BernoulliFixedSep
    elif sep_method == 'smoothmin':
        return tfmd.BernoulliSmoothMinSep
    else:
        raise ValueError("Something dun goofed")

def dynamical_fluidtype_from_sep_method(sep_method):
    if sep_method == 'fixed':
        return dfmd.BernoulliFixedSep, dfmd.LinearizedBernoulliFixedSep
    elif sep_method == 'smoothmin':
        return dfmd.BernoulliSmoothMinSep, dfmd.LinearizedBernoulliSmoothMinSep
    else:
        raise ValueError("Something dun goofed")

def load_hopf(mesh_path, sep_method='fixed', sep_vert_label='separation'):
    FluidType, LinFluidType = dynamical_fluidtype_from_sep_method(sep_method)

    kwargs = {
        'fsi_facet_labels': ('pressure',),
        'fixed_facet_labels': ('fixed',),
        'separation_vertex_label': sep_vert_label
    }
    res = load.load_dynamical_fsi_model(
        mesh_path,
        None,
        SolidType=dsmd.KelvinVoigt,
        FluidType=FluidType,
        **kwargs
    )

    dres = load.load_dynamical_fsi_model(
        mesh_path,
        None,
        SolidType=dsmd.LinearizedKelvinVoigt,
        FluidType=LinFluidType,
        **kwargs
    )

    _region_to_dofs = process_celllabel_to_dofs_from_forms(
        res.solid.forms, res.solid.forms['fspace.scalar'])
    _props = set_props(res.props.copy(), _region_to_dofs, res)
    res.set_props(_props)
    dres.set_props(_props)

    res_hopf = libhopf.HopfModel(res, dres)
    return res_hopf, res, dres

def load_tran(mesh_path, sep_method='fixed', sep_vert_label='separation'):
    FluidType = transient_fluidtype_from_sep_method(sep_method)

    return load.load_transient_fsi_model(
        mesh_path, None,
        SolidType=tsmd.KelvinVoigt,
        FluidType=FluidType,
        coupling='explicit',
        separation_vertex_label=sep_vert_label
    )


def setup_transient_model(mesh_path):
    model = load.load_transient_fsi_model(
        mesh_path, None,
        SolidType=tsmd.KelvinVoigt, FluidType=tfmd.BernoulliSmoothMinSep,
        coupling='explicit'
        )
    return model

def setup_models(mesh_path):
    """
    Return residual + linear residual needed to model the Hopf system
    """
    res = load.load_dynamical_fsi_model(
        mesh_path, None, SolidType = dsmd.KelvinVoigt,
        FluidType = dfmd.BernoulliSmoothMinSep,
        fsi_facet_labels=('pressure',), fixed_facet_labels=('fixed',))

    dres = load.load_dynamical_fsi_model(
        mesh_path, None, SolidType = dsmd.LinearizedKelvinVoigt,
        FluidType = dfmd.LinearizedBernoulliSmoothMinSep,
        fsi_facet_labels=('pressure',), fixed_facet_labels=('fixed',))

    return res, dres

ECOV = 5e3*10
EBODY = 5e3*10
PSUB = 450 * 10

def set_props(props, region_to_dofs, res):
    """
    Set the model properties
    """
    # VF material props
    gops.set_vec(props['emod'], ECOV)
    gops.set_vec(props['emod'], EBODY)

    props = set_constant_props(props, region_to_dofs, res)

    return props

def set_constant_props(props, region_to_dofs, res):
    gops.set_vec(props['eta'], 5.0)
    gops.set_vec(props['rho'], 1.0)
    gops.set_vec(props['nu'], 0.45)

    # Fluid separation smoothing props
    if all(key in props for key in ['zeta_min', 'zeta_sep']):
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

    gops.set_vec(props['rho_air'], 1.293e-3)

    return props

def setup_hopf_state(mesh_path, hopf_state_path=None):
    ## Load the models
    res, dres = setup_models(mesh_path)

    ## Set model properties
    region_to_dofs = process_celllabel_to_dofs_from_forms(
        res.solid.forms, res.solid.forms['fspace.scalar'])

    props = res.props.copy()
    props = set_props(props, region_to_dofs, res)

    ## Initialize the Hopf system
    # This vector normalizes the real/imag components of the unstable eigenvector
    EREF = res.state.copy()
    EREF['q'].set(1.0)
    EREF.set(1.0)
    hopf = libhopf.HopfModel(res, dres, e_mode=EREF)
    hopf.set_props(props)

    (state_labels,
        mode_real_labels,
        mode_imag_labels,
        psub_labels,
        omega_labels) = hopf.labels_hopf_components

    ## Solve for the fixed point
    # this is used to get the initial guess for the Hopf system
    _control = res.control.copy()
    _control['psub'] = PSUB
    res.set_control(_control)
    res.set_props(props)

    newton_params = {
        'maximum_iterations': 20
    }
    xfp_0 = res.state.copy()
    xfp_n, _ = libhopf.solve_fp_newton(res, xfp_0, PSUB, newton_params=newton_params)

    ## Solve for linear stabilty at the fixed point
    # this is used to get the initial guess for the Hopf system
    omegas, eigvecs_real, eigvecs_imag = libhopf.solve_modal(res, xfp_n, PSUB)

    # The unstable mode is apriori known to be the 3rd one for the current test case
    # In the future, you should make this more general/automatic
    idx_hopf = 3
    omega_hopf = abs(omegas[idx_hopf].imag)
    mode_real_hopf = eigvecs_real[idx_hopf]
    mode_imag_hopf = eigvecs_imag[idx_hopf]

    ## Solve the Hopf system for the Hopf bifurcation
    xhopf_0 = hopf.state.copy()
    xhopf_0[state_labels] = xfp_n
    xhopf_0[psub_labels[0]].array[:] = PSUB
    xhopf_0[omega_labels[0]].array[:] = omega_hopf

    xmode_real, xmode_imag = libhopf.normalize_eigenvector_by_hopf(
        mode_real_hopf, mode_imag_hopf, EREF)
    xhopf_0[mode_real_labels] = xmode_real
    xhopf_0[mode_imag_labels] = xmode_imag

    newton_params = {
        'maximum_iterations': 20
    }
    xhopf_n, info = libhopf.solve_hopf_newton(hopf, xhopf_0)

    if hopf_state_path is not None:
        with h5py.File(hopf_state_path, mode='w') as f:
            h5utils.create_resizable_block_vector_group(
                f, xhopf_n.labels, xhopf_n.bshape)
            h5utils.append_block_vector_to_group(f, xhopf_n)
    return hopf, xhopf_n, props
