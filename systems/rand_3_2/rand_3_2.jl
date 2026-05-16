function rur_rand_3_2()
    _,(x,y,z)=AbstractAlgebra.polynomial_ring(AbstractAlgebra.QQ, ["x","y","z"], internal_ordering=:degrevlex)
    sys=[61*x^2+83*x*y-83*x*z+53*y^2-6*y*z-14*x, 35*x^2-31*x*y-17*y*z-21*x+28*y+92*z, -56*x*y-45*x*z-15*y^2-67*z^2+58*x-47]
    sys
end
