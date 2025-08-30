"""
Main model implementation
"""
import inputs
import equations
from config import *

# Arabic/English notes about this module:
# - هذا الملف ينفّذ نموذج أداء الرصف: يتحقق من المدخلات، يحسب الحجوم والكتل،
#   يعالج المعاملات الفعّالة (E0, k_temp, T0, p, r, ...)، يحسب الإجهادات والسعات،
#   يقدّر العمر التصميمي والتكاليف، ثم يُرجِع قاموس نتائج شامل.
# - Units/الوحدات:
#   L[km], W[m], h[m], rho_m[ton/m³], Pb/Pp/Pr[fraction], T[°C], A[million ESALs/year]
#   Costs[EGP], Mass[ton], Volume[m³], Modulus[MPa], Strains[dimensionless]

def run_model(L: float, W: float, h: float, rho_m: float, Pb: float,
             Pp: float, Pr: float, T: float, A: float,
             c_agg: float, c_bit: float, c_pl: float, c_rub: float,
             overhead: float = 0.0, target_design_life: float = None, coeffs: dict | None = None,
             allowed_ranges: dict | None = None) -> dict:
    """
    Run full pavement performance model
    
    Returns:
        dict: Dictionary containing all calculated results
    """
    # Validate inputs
    # التحقق من صحة المدخلات ضمن الحدود المسموح بها (قد تأتي من standards.json)
    # Raises ValueError عند وجود قيم خارج النطاق أو غير منطقية.
    inputs.validate_inputs(L, W, h, rho_m, Pb, Pp, Pr, T, A, allowed_ranges)
    
    # Calculate volume and mass
    # حساب الحجم والكتلة الكلية للخليط ثم توزيع كتل المواد الرابطة/المستبدلة:
    # V = L[km]*1000 * W[m] * h[m]  => m³
    # M = V * rho_m                  => ton
    V = equations.calculate_volume(L, W, h)
    M = equations.calculate_mass(V, rho_m)
    M_b, M_p, M_r, M_agg, M_bit_new = equations.calculate_binder_masses(M, Pb, Pp, Pr)
    
    # Check for negative bitumen
    # تحقق أمان: لا يجب أن تصبح كتلة البيتومين الجديدة سالبة بعد الاستبدال بالبلاستيك/الكاوتش.
    if M_bit_new < 0:
        raise ValueError("New bitumen mass cannot be negative")
    
    # Resolve effective coefficients (presets can override defaults)
    # تجميع المعاملات الفعّالة مع السماح للـ presets بتمرير قيم مخصّصة عبر dict `coeffs`.
    # Fallbacks: إن لم تُعرَّف قيم حديثة في config (مثل k_temp/T0_C)، نعود للقديم (مثل b و 25°C).
    if coeffs is None:
        coeffs = {}
    E0_local = coeffs.get("E0_MPa", E0)
    # prefer k_temp/T0_C if provided; fallback to legacy b/25°C
    k_temp_local = coeffs.get("k_temp", k_temp if 'k_temp' in globals() else b)
    T0_local = coeffs.get("T0_C", T0_C if 'T0_C' in globals() else 25.0)
    p_local = coeffs.get("p_plastic", p)
    r_local = coeffs.get("r_rubber", r)
    k_eps_t_local = coeffs.get("k_eps_t", k_epsilon_t)
    k_eps_c_local = coeffs.get("k_eps_c", k_epsilon_c)
    m_f_local = coeffs.get("m_f", m_f)
    m_r_local = coeffs.get("m_r", m_r)
    MIN_E_local = coeffs.get("MIN_E", MIN_E)
    MAX_E_local = coeffs.get("MAX_E", MAX_E)

    # Calculate temperature factor and modulus
    # عامل الحرارة fT يكيّف الصلابة مع T مقارنةً بـ T0 باستخدام k_temp.
    fT = equations.temp_factor(T, k_temp_local, T0_local)
    # Calculate modulus using the safe formula (modifiers act on binder fraction)
    # الصيغة الآمنة: المعدّلات تعمل على نسبة الموثّق (binder fraction) لا على الكتلة الكلية مباشرةً.
    E = E0_local * fT * (1 + p_local * Pp) / (1 + r_local * Pr)
    
    # Clamp E to realistic bounds
    # تثبيت E ضمن حدود واقعية لمنع القيم المتطرفة التي قد تُفسد الحسابات اللاحقة.
    E = max(MIN_E_local, min(E, MAX_E_local))
    
    # Calculate strains
    # حساب إجهادات الشد/الضغط عند أسفل الطبقة. تعتمد على E و h ومعاملات المعايرة.
    epsilon_t = equations.tensile_strain(k_eps_t_local, E, h)
    epsilon_c = equations.compressive_strain(k_eps_c_local, E)
    
    # If target design life is provided, calculate k_f and k_r
    # عند تزويد عمر تصميمي مستهدف: نحسب معاملات التعب/التخدد المطلوبة (k_f, k_r)
    # بحيث تُنتج N_needed على مدى العمر باستخدام الإجهادات الحالية.
    if target_design_life is not None:
        # Calculate required N (million ESALs)
        N_needed = A * target_design_life
        
        # Calculate k_f and k_r
        k_f_val = N_needed * (epsilon_t ** m_f_local)
        k_r_val = N_needed * (epsilon_c ** m_r_local)
    else:
        # Use default values from config
        k_f_val = k_f
        k_r_val = k_r
    
    # Calculate capacities
    # تحويل الإجهادات إلى سعات تحمّل (عدد محاور مكافئة بالملايين) وفق علاقات التعب/التخدد.
    capacities = equations.capacities(epsilon_t, epsilon_c, k_f_val, m_f_local, k_r_val, m_r_local)
    Nf = capacities['Nf']
    Nr = capacities['Nr']
    
    # Calculate life in years
    # تحويل السعات إلى أعمار سنوات بافتراض A مليون محور مكافئ سنوياً.
    life_results = equations.life_years(Nf, Nr, A)
    life_f = life_results['fatigue_life']
    life_r = life_results['rutting_life']
    design_life = life_results['design_life']
    
    # Calculate costs
    # تكاليف المواد: الركام + البيتومين (بعد طرح الاستبدالات) + البلاستيك + الكاوتش.
    # overhead قيمة مُضافة مباشرة بالـ EGP.
    cost_agg = equations.cost_aggregate(M_agg, c_agg)
    # Pass original bitumen mass (before modifiers) so function subtracts replacements once
    cost_bit = equations.cost_bitumen(M_b, M_p, M_r, c_bit)
    cost_pl = equations.cost_plastic(M_p, c_pl)
    cost_rub = equations.cost_rubber(M_r, c_rub)
    material_cost = cost_agg + cost_bit + cost_pl + cost_rub
    # Overhead is an additive EGP amount
    total_cost = material_cost + overhead
    
    # Calculate useful metrics
    # مقاييس إضافية مفيدة للمقارنة:
    # - المساحة m² لتطبيع التكلفة
    # - تكلفة لكل m² ولكل طن
    area = L * 1000 * W  # m²
    cost_per_m2 = total_cost / area
    cost_per_ton = total_cost / M
    
    # Add warnings for outputs
    # تنبيهات للمساعدة في اكتشاف الإدخالات/المعاملات غير الواقعية.
    warnings = []
    if design_life > 100:
        warnings.append("Design life exceeds 100 years — check constants/strains.")
    if epsilon_t < 1e-6 or epsilon_t > 1e-3:
        warnings.append("Tensile strain is outside normal range (1e-6 to 1e-3) — check k_epsilon_t, E, and h.")
    if epsilon_c < 1e-6 or epsilon_c > 1e-3:
        warnings.append("Compressive strain is outside normal range (1e-6 to 1e-3) — check k_epsilon_c and E.")
    if epsilon_t < 1e-6 or epsilon_t > 1e-3 or epsilon_c < 1e-6 or epsilon_c > 1e-3:
        warnings.append("Strains are outside normal range — check k_epsilon_t, k_epsilon_c, E, and h.")
    
    # Create results dictionary
    # القاموس النهائي يتضمن القيم الأساسية، التفاصيل المالية، المقاييس المشتقة،
    # بالإضافة إلى المعاملات الفعّالة المستخدمة لإعادة إنتاج النتيجة.
    results = {
        "volume_m3": V,
        "total_mass_ton": M,
        "modulus_MPa": E,
        "tensile_strain": epsilon_t,
        "compressive_strain": epsilon_c,
        "fatigue_life_years": life_f,
        "rutting_life_years": life_r,
        "design_life_years": design_life,
        "material_cost": material_cost,
        "total_cost": total_cost,
        "costs": {
            "aggregate": cost_agg,
            "bitumen": cost_bit,
            "plastic": cost_pl,
            "rubber": cost_rub,
            "overhead": overhead
        },
        "cost_per_m2": cost_per_m2,
        "cost_per_ton": cost_per_ton,
        "coefficients_effective": {
            "E0_MPa": E0_local,
            "k_temp": k_temp_local,
            "T0_C": T0_local,
            "p_plastic": p_local,
            "r_rubber": r_local,
            "k_eps_t": k_eps_t_local,
            "k_eps_c": k_eps_c_local,
            "m_f": m_f_local,
            "m_r": m_r_local,
            "MIN_E": MIN_E_local,
            "MAX_E": MAX_E_local
        }
    }
    
    # Add warnings to results
    results["warnings"] = warnings
    
    return results
