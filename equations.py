"""
Core equations for the pavement performance model
"""
import math

# Volume and mass calculations
def calculate_volume(L_km: float, W_m: float, h_m: float) -> float:
    """Calculate pavement volume in cubic meters"""
    return (L_km * 1000) * W_m * h_m

def calculate_mass(V_m3: float, rho_m: float) -> float:
    """Calculate total mass of pavement mixture"""
    return V_m3 * rho_m

def calculate_binder_masses(M: float, Pb: float, Pp: float, Pr: float) -> tuple:
    """Calculate masses of components"""
    M_b = M * Pb
    M_p = M_b * Pp
    M_r = M_b * Pr
    M_agg = M - M_b
    M_bit_new = M_b - M_p - M_r
    return M_b, M_p, M_r, M_agg, M_bit_new

def mass_plastic(M_bit: float, Pp: float) -> float:
    """
    حساب كتلة البلاستيك (طن)
    Pp: نسبة البلاستيك من كتلة البيتومين (نسبة البلاستيك من كتلة المادة الرابطة)
    """
    return M_bit * Pp

def mass_rubber(M_bit: float, Pr: float) -> float:
    """
    حساب كتلة المطاط (طن)
    Pr: نسبة المطاط من كتلة البيتومين (نسبة المطاط من كتلة المادة الرابطة)
    """
    return M_bit * Pr

# Temperature factor
def temp_factor(T: float, k_temp: float, T0: float) -> float:
    """
    Calculate temperature factor relative to reference temperature T0
    T: actual temperature (°C)
    k_temp: temperature sensitivity coefficient (1/°C)
    T0: reference temperature (°C)
    """
    return math.exp(-k_temp * (T - T0))

# Modulus calculation
def calculate_modulus(E0: float, p: float, r: float, Pp: float, Pr: float, fT: float) -> float:
    """Calculate effective modulus"""
    return E0 * (1 + p * Pp - r * Pr) * fT

# Strain calculations
def tensile_strain(k_epsilon_t: float, E: float, h: float) -> float:
    """
    حساب إجهاد الشد (ε_t)
    k_epsilon_t: ثابت الإجهاد للشد
    E: معامل المرونة (MPa)
    h: سمك الطبقة (m)
    """
    return k_epsilon_t / (E * h)

def compressive_strain(k_epsilon_c: float, E: float) -> float:
    """
    حساب إجهاد الضغط (ε_c)
    k_epsilon_c: ثابت الإجهاد للضغط
    E: معامل المرونة (MPa)
    """
    return k_epsilon_c / E

# Capacities calculations
def capacities(et: float, ec: float, kf: float, mf: float, kr: float, mr: float) -> dict:
    """Calculate fatigue and rutting capacities"""
    Nf = kf * (1/et) ** mf
    Nr = kr * (1/ec) ** mr
    return {'Nf': Nf, 'Nr': Nr}

# Life in years
def life_years(Nf: float, Nr: float, A_million: float) -> dict:
    """Convert load repetitions to life in years"""
    life_f = Nf / A_million
    life_r = Nr / A_million
    life = min(life_f, life_r)
    return {'fatigue_life': life_f, 'rutting_life': life_r, 'design_life': life}

# Cost calculations
def cost_aggregate(M_agg: float, c_agg: float) -> float:
    """
    حساب تكلفة الركام (جنيه)
    M_agg: كتلة الركام (طن)
    c_agg: تكلفة الطن (جنيه/طن)
    """
    return M_agg * c_agg

def cost_bitumen(M_bit: float, M_pl: float, M_rub: float, c_bit: float) -> float:
    """
    حساب تكلفة البيتومين (جنيه)
    M_bit: كتلة البيتومين الإجمالية (طن)
    M_pl: كتلة البلاستيك (طن)
    M_rub: كتلة المطاط (طن)
    c_bit: تكلفة الطن (جنيه/طن)
    """
    # الكتلة الفعلية للبيتومين (بعد استبدال جزء بالبلاستيك والمطاط)
    M_bit_actual = M_bit - M_pl - M_rub
    return M_bit_actual * c_bit

def cost_plastic(M_pl: float, c_pl: float) -> float:
    """
    حساب تكلفة البلاستيك (جنيه)
    M_pl: كتلة البلاستيك (طن)
    c_pl: تكلفة الطن (جنيه/طن)
    """
    return M_pl * c_pl

def cost_plastik(M_pl: float, c_pl: float) -> float:
    """Alias to handle legacy spelling"""
    return cost_plastic(M_pl, c_pl)

def cost_rubber(M_rub: float, c_rub: float) -> float:
    """
    حساب تكلفة المطاط (جنيه)
    M_rub: كتلة المطاط (طن)
    c_rub: تكلفة الطن (جنيه/طن)
    """
    return M_rub * c_rub

def cost(M_agg: float, M_bit_new: float, M_p: float, M_r: float,
         c_agg: float, c_bit: float, c_pl: float, c_rub: float,
         overhead: float = 0.0) -> dict:
    """Calculate material and total costs"""
    material_cost = cost_aggregate(M_agg, c_agg) + cost_bitumen(M_bit_new + M_p + M_r, M_p, M_r, c_bit) + cost_plastic(M_p, c_pl) + cost_rubber(M_r, c_rub)
    total_cost = material_cost + overhead
    return {'material_cost': material_cost, 'total_cost': total_cost}
