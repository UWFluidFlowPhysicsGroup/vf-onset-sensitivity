"""
Plot results of a linear stability analysis
"""

import numpy as np
import matplotlib.pyplot as plt
import dolfin as dfn

import libsetup
import libhopf

dfn.set_log_level(50)
if __name__ == '__main__':
    # mesh_name = 'BC-dcov5.00e-02-cl1.00'
    mesh_name = 'M5_CB_GA3'
    mesh_path = f'mesh/{mesh_name}.msh'
    hopf, *_ = libsetup.load_hopf(
        mesh_path,
        sep_method='fixed',
        sep_vert_label='separation-inf'
    )

    props0 = hopf.props.copy()
    libsetup.set_default_props(props0, hopf.res.solid.forms['mesh.mesh'])
    hopf.set_props(props0)
    res = hopf.res

    psubs = np.arange(0, 1500, 100)*10

    least_stable_modes_info = [
        libhopf.solve_least_stable_mode(res, psub)
        for psub in psubs
    ]
    breakpoint()

    omegas = np.array([mode_info[0] for mode_info in least_stable_modes_info])

    fig, axs = plt.subplots(2, 1, sharex=True)

    axs[0].plot(psubs, omegas.real)
    axs[1].plot(psubs, omegas.imag)

    axs[1].set_xlabel("$\omega_{real}$")
    axs[1].set_xlabel("$\omega_{imag}$")
    axs[1].set_xlabel("$p_{sub}$ [Pa]")

    fig.tight_layout()
    fig.savefig('fig/lsa.png')
