function rur_rand_3_3()
    _,(x,y,z)=AbstractAlgebra.polynomial_ring(AbstractAlgebra.QQ, ["x","y","z"], internal_ordering=:degrevlex)
    sys=[-27*x^3-79*x^2*y-22*x^2*z+16*x*y^2-85*x*y*z-31*x*z^2-58*y^3+49*y^2*z-95*y*z^2-14*z^3-51*x^2-44*x*y+45*x*z+y^2+86*y*z+83*z^2+49*x-97*y-96*z-8, -54*x^3+62*x^2*y+96*x^2*z+89*x*y^2+14*x*y*z-58*x*z^2-2*y^3+86*y^2*z-35*y*z^2+63*z^3-51*x^2-79*x*y-95*x*z+57*y^2+57*y*z+21*z^2+61*x+28*y-71*z-66, -34*x^3+72*x^2*y-40*x^2*z-15*x*y^2-32*x*y*z+87*x*z^2-61*y^3+45*y^2*z-22*y*z^2+46*z^3-68*x^2+17*x*y-60*x*z-50*y^2+48*y*z-49*z^2+7*x-82*y-66*z+18]
    sys
end
