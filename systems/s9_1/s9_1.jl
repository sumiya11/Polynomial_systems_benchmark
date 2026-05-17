function s9_1(; np = AbstractAlgebra, k = np.QQ, internal_ordering = :degrevlex)
    (_, (a, b, c, d, e, f, g, h)) = np.polynomial_ring(k, ["x$(i)" for i = 1:8], internal_ordering = internal_ordering)
    [-e * g - 2 * d * h, 9 * e + 4b, (-4 * c * h - 2 * e * f) - 3 * d * g, (-7c + 9a) - 8 * f, ((-4 * d * f - 5 * c * g) - 6h) - 3 * e, ((-5d - 6 * c * f) - 7g) + 9b, (9d + 6a) - 5b, (9c - 7a) + 8]
end
