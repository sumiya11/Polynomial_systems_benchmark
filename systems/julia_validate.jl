using AbstractAlgebra

systems_root = normpath((@__DIR__) * "/../systems")
skip = Set(["siwr"])

for (root, dirs, files) in walkdir(systems_root)
    if normpath(root) == systems_root
        continue
    end
    for file in files
        if endswith(file, ".jl")
            if chopsuffix(file, ".jl") in skip
                continue
            end
            filepath = root * "/" * file
            @info "Reading $filepath"
            func = include(filepath)
            sys = nothing
            try
                sys = Base.invokelatest(func)
            catch e
                if isa(e, MethodError)
                    try
                        sys = Base.invokelatest(func, 2)
                    catch e
                        @error "Failed (1): $filepath"
                    end
                else
                    @error "Failed (2): $filepath"
                end
            end
            if !(sys === nothing)
                try
                    @assert base_ring(parent(sys[1])) isa AbstractAlgebra.Field
                catch e
                    @error "Failed (3): $filepath"
                end
            end
        end
    end
end