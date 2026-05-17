using AbstractAlgebra

function coefficient_denominator(coefficient)
    if coefficient isa Rational
        return denominator(coefficient)
    end
    return one(ZZ)
end

function clear_denominators(poly)
    coeffs = collect(coefficients(poly))
    mons = collect(monomials(poly))
    if isempty(coeffs)
        return poly
    end

    common_denominator = foldl(lcm, map(coefficient_denominator, coeffs); init=one(ZZ))
    if common_denominator == one(ZZ)
        return poly
    end

    return sum((common_denominator * coefficient) * monomial for (coefficient, monomial) in zip(coeffs, mons); init=zero(parent(poly)))
end

function normalize_system_for_txt(sys)
    if isempty(sys)
        return sys
    end

    k = base_ring(parent(sys[1]))
    if characteristic(k) != 0
        return sys
    end

    return map(clear_denominators, sys)
end

function julia_to_txt(sys)
    normalized = normalize_system_for_txt(sys)
    R = parent(normalized[1])
    k = base_ring(R)
    char = characteristic(k)
    vars = join(map(string, gens(R)), ", ")
    equations = join(map(string, normalized), ",\n")
    """
    $vars
    $char
    $equations
    """
end

skip = ["siwr"]

ranges = Dict(
    "chandra" => 2:15,
    "katsura" => 2:15,
    "cyclic" => 2:15,
    "noon" => 2:15,
    "eco" => 2:15,
    "root" => 2:15,
    "reimer" => 2:15,
)

function generate_many_txt()
    prefix = (@__DIR__) * "/../systems"
    for dir in readdir(prefix)
        root = prefix * "/" * dir
        if !isdir(root)
            continue
        end
        for file in readdir(prefix * "/" * dir)
            if endswith(file, ".txt")
                # rm(root * "/txt/" * file, recursive=true)
            end
            if endswith(file, ".jl")
                name = chopsuffix(file, ".jl")
                if name in skip
                    continue
                end
                mkpath(root * "/" * "txt")
                filepath = root * "/" * file
                @info "Reading $filepath"
                func = include(filepath)
                needs_n = false
                if haskey(ranges, chopsuffix(file, ".jl"))
                    range = ranges[chopsuffix(file, ".jl")]
                else
                    range = 5:5
                end
                for n in range
                    sys = nothing
                    try
                        sys = Base.invokelatest(func)
                    catch e
                        if isa(e, MethodError)
                            try
                                sys = Base.invokelatest(func, n)
                                needs_n = true
                            catch e
                                @warn "Failed to call $filepath with n=$n: $e"
                            end
                        else
                            @warn "Failed to call $filepath: $e"
                        end
                    end
                    sys === nothing && continue
                    txt = julia_to_txt(sys)
                    if needs_n
                        txt_filepath = root * "/txt/" * chopsuffix(file, ".jl") * "_$n" * ".txt"
                    else
                        txt_filepath = root * "/txt/" * chopsuffix(file, ".jl") * ".txt"
                    end
                    open(txt_filepath, "w") do fout
                        println("  Writing: $txt_filepath")
                        write(fout, txt)
                    end
                    !needs_n && break
                end
                if needs_n
                    print("$name:--------\n")
                    print(join(["[$(name)_$(n).txt](./systems/$(name)/txt/$(name)_$(n).txt)" for n in range], ", "))
                    print("\n--------\n")
                end
            end
        end
    end
end

if abspath(PROGRAM_FILE) == @__FILE__
    generate_many_txt()
end