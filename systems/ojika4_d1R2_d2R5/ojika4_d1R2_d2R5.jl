function ojika4_d1R2_d2R5(; np = AbstractAlgebra, k = np.QQ, internal_ordering = :degrevlex)
    (_, (x1, x2, x3)) = np.polynomial_ring(k, ["x$(i)" for i = 1:3], internal_ordering = internal_ordering)
    [((x1 ^ 3 * x3 + x1 * x3 * x2 ^ 2) - x1 * x3) + x1, ((-2 * x1 ^ 2 * x3 * x2 - x3 * x2 ^ 3) - x3 * x2) + 10x2, (((((-6 * x1 ^ 4 * x3 ^ 2 - 3 * x1 ^ 2 * x3 ^ 2 * x2 ^ 2) - 3 * x3 ^ 2 * x2 ^ 4) - x1 ^ 2 * x3 ^ 2) + 2 * x3 ^ 2 * x2 ^ 2 + 28 * x1 ^ 2 * x3 + 7 * x3 * x2 ^ 2 + x3 ^ 2) - 11x3) + 10]
end
