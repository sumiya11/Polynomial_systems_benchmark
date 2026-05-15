using AbstractAlgebra

for (root, dirs, files) in walkdir((@__DIR__) * "/../systems")
    for file in files
        if endswith(file, ".jl")
            filepath = root * "/" * file
            @info "Reading $filepath"
            func = include(filepath)
            sys = nothing
            try
                sys = func()
            catch e
                if isa(e, MethodError)
                    try
                        sys = func(2)
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