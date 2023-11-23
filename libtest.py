"""
Module with common functionality used for testing
"""

import numpy as np
import blockarray.linalg as bla


def taylor_convergence(x0, dx, res, jac, norm=None):
    """
    Test that the Taylor convergence order is 2
    """
    if norm is None:
        norm = bla.norm

    # Step sizes go from largest to smallest
    alphas = 2**np.arange(4)[::-1]
    res_ns = [res(x0+alpha*dx).copy() for alpha in alphas]
    res_0 = res(x0).copy()

    dres_exacts = [res_n-res_0 for res_n in res_ns]
    dres_linear = jac(x0, dx)

    errs = np.array([
        norm(dres_exact-alpha*dres_linear)
        for dres_exact, alpha in zip(dres_exacts, alphas)
    ])
    magnitudes = np.array([
        1/2*norm(dres_exact+alpha*dres_linear)
        for dres_exact, alpha in zip(dres_exacts, alphas)
    ])
    with np.errstate(invalid='ignore'):
        conv_rates = np.log(errs[:-1]/errs[1:])/np.log(alphas[:-1]/alphas[1:])
        rel_errs = errs/magnitudes

    print(f"||dres_linear||, ||dres_exact|| = {norm(dres_linear)}, {norm(dres_exacts[-1])}")
    print("Relative errors: ", rel_errs)
    print("Convergence rates: ", np.array(conv_rates))
    return alphas, errs, magnitudes, conv_rates