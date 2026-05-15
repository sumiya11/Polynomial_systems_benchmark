function chandran(
    n;
    interface=AbstractAlgebra,
    base_ring=interface.QQ,
    ordering=:degrevlex,
    tol=0,
)
    _, hs = interface.polynomial_ring(
        base_ring,
        ["H$i" for i in 1:n],
        internal_ordering=ordering,
    )

    c = rationalize(BigInt, 0.51234, tol=tol)
    c = base_ring(numerator(c)) // base_ring(denominator(c))

    [
        2 * n * hs[i] -
        c * hs[i] * (1 + sum(base_ring(i) // (j + i) * hs[j] for j in 1:(n - 1))) -
        2 * n
        for i in 1:n
    ]
end
