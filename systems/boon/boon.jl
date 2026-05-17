function boon(; np = AbstractAlgebra, k = np.QQ, internal_ordering = :degrevlex)
    (_, (s1, g1, s2, g2, C1, C2)) = np.polynomial_ring(k, ["s1", "g1", "s2", "g2", "C1", "C2"], internal_ordering = internal_ordering)
    eqs = [(s1 ^ 2 + g1 ^ 2) - 1, (s2 ^ 2 + g2 ^ 2) - 1, (C1 * g1 ^ 3 + C2 * g2 ^ 3) - k(12) // 10, (C1 * s1 ^ 3 + C2 * s2 ^ 3) - k(12) // 10, (C1 * g1 ^ 2 * s1 + C2 * g2 ^ 2 * s2) - k(7) // 10, (C1 * g1 * s1 ^ 2 + C2 * g2 * s2 ^ 2) - k(7) // 10]
    eqs
end
