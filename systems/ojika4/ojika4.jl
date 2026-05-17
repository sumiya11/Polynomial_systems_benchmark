function ojika4(; np = AbstractAlgebra, k = np.QQ, internal_ordering = :degrevlex)
    (_, (x1, x2, x3)) = np.polynomial_ring(k, ["x$(i)" for i = 1:3], internal_ordering = internal_ordering)
    [(x1 + x3 * x1 ^ 3 + x1 * x3 * x2 ^ 2) - x1 * x3, ((10x2 - 2 * x2 * x3 * x1 ^ 2) - x3 * x2 ^ 3) - x2 * x3, ((((((-6 * x3 ^ 2 * x1 ^ 4 - 3 * x1 ^ 2 * x2 ^ 2 * x3 ^ 2) - x3 ^ 2 * x1 ^ 2) + 28 * x3 * x1 ^ 2) - 3 * x3 ^ 2 * x2 ^ 4) + 2 * x3 ^ 2 * x2 ^ 2 + 7 * x3 * x2 ^ 2 + x3 ^ 2) - 11x3) + 10]
end
