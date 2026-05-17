function reimer(n; np=AbstractAlgebra, k=np.QQ, internal_ordering=:degrevlex)
    _, xs = np.polynomial_ring(k, ["x$i" for i in 1:n], internal_ordering=internal_ordering)
    [sum((-1)^(index + 1) * 2 * xs[index]^degree for index in 1:n) - 1 for degree in 2:(n + 1)]
end