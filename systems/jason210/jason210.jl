function jason210(; np = AbstractAlgebra, k = np.QQ, internal_ordering = :degrevlex)
    (R, (x1, x2, x3, x4, x5, x6, x7, x8)) = np.polynomial_ring(k, [:x1, :x2, :x3, :x4, :x5, :x6, :x7, :x8], internal_ordering = internal_ordering)
    sys = [x1 ^ 2 * x3 ^ 4 + x1 * x2 * x3 ^ 2 * x5 ^ 2 + x1 * x2 * x3 * x4 * x5 * x7 + x1 * x2 * x3 * x4 * x6 * x8 + x1 * x2 * x4 ^ 2 * x6 ^ 2 + x2 ^ 2 * x4 ^ 4, x2 ^ 6, x1 ^ 6]
end
