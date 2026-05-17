function root(n; np=AbstractAlgebra, k=np.QQ, internal_ordering=:degrevlex)
    ring, xs = np.polynomial_ring(k, ["x$i" for i in 1:n], internal_ordering=internal_ordering)
    elementary = vcat([one(ring)], [zero(ring) for _ in 1:n])
    for variable in xs
        for degree in (n + 1):-1:2
            elementary[degree] += variable * elementary[degree - 1]
        end
    end

    system = [elementary[degree + 1] for degree in 1:n]
    system[end] -= (-1)^(n - 1)
    system
end