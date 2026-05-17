function kinema(; np = AbstractAlgebra, k = np.QQ, internal_ordering = :degrevlex)
    (_, (z1, z2, z3, z4, z5, z6, z7, z8, z9)) = np.polynomial_ring(k, ["z$(i)" for i = 1:9], internal_ordering = internal_ordering)
    [((z1 ^ 2 + z2 ^ 2 + z3 ^ 2) - 12z1) - 68; ((z4 ^ 2 + z5 ^ 2 + z6 ^ 2) - 12z5) - 68; (((z7 ^ 2 + z8 ^ 2 + z9 ^ 2) - 24z8) - 12z9) + 100; (((z1 * z4 + z2 * z5 + z3 * z6) - 6z1) - 6z5) - 52; ((((z1 * z7 + z2 * z8 + z3 * z9) - 6z1) - 12z8) - 6z9) + 64; ((((z4 * z7 + z5 * z8 + z6 * z9) - 6z5) - 12z8) - 6z9) + 32; ((((((2z2 + 2z3) - z4) - z5) - 2z6) - z7) - z9) + 18; ((((z1 + z2 + 2z3 + 2z4 + 2z6) - 2z7) + z8) - z9) - 38; ((((((z1 + z3) - 2z4) + z5) - z6) + 2z7) - 2z8) + 8]
end
