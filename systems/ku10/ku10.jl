function ku10(; np = AbstractAlgebra, k = np.QQ, internal_ordering = :degrevlex)
    (_, (x1, x2, x3, x4, x5, x6, x7, x8, x9, x10)) = np.polynomial_ring(k, ["x$(i)" for i = 1:10], internal_ordering = internal_ordering)
    [5 * x1 * x2 + 5x1 + 3x2 + 55, 7 * x2 * x3 + 9x2 + 9x3 + 19, (3 * x3 * x4 + 6x3 + 5x4) - 4, 6 * x4 * x5 + 6x4 + 7x5 + 118, x5 * x6 + 3x5 + 9x6 + 27, 6 * x6 * x7 + 7x6 + x7 + 72, 9 * x7 * x8 + 7x7 + x8 + 35, 4 * x8 * x9 + 4x8 + 6x9 + 16, (8 * x9 * x10 + 4x9 + 3x10) - 51, (3 * x1 * x10 - 6x1) + x10 + 5]
end
