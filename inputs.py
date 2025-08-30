"""
Input validation and unit conversion functions
"""

from config import *

# Arabic/English notes:
# - هذا الملف يتحقق من صحة المدخلات قبل تشغيل النموذج.
# - يتم فرض الحدود التشغيلية الافتراضية من `config.py` ويمكن تخصيصها عبر `allowed_ranges` القادمة من presets.
# - الوحدات المتوقعة:
#   L[km], W[m], h[m], rho_m[ton/m³], Pb/Pp/Pr[proportion], T[°C], A[million ESALs/year]

def validate_inputs(L: float, W: float, h: float, rho_m: float, Pb: float,
                   Pp: float, Pr: float, T: float, A: float, allowed_ranges: dict | None = None):
    """
    Validate inputs against operational limits.
    If allowed_ranges is provided, enforce those bounds where available.
    """
    warnings = []  # مخصّص لتحذيرات مستقبلية إن أردنا إرجاعها مع التحقق
    # تحقق من نسب البيتومين/المعدّلات ضمن الحدود العامة من `config.py`
    if not (0 < Pb <= MAX_Pb):
        raise ValueError(f"Pb must be between {MIN_Pb} and {MAX_Pb}")
    if Pp < 0 or Pp > MAX_Pp:
        raise ValueError(f"Pp must be between 0 and {MAX_Pp}")
    if Pr < 0 or Pr > MAX_Pr:
        raise ValueError(f"Pr must be between 0 and {MAX_Pr}")
    if Pp + Pr > MAX_P_MODIFIERS:
        raise ValueError(f"Pp + Pr cannot exceed {MAX_P_MODIFIERS}")
    # هندسياً: يجب أن تكون السماكة موجبة ومعقولة، وكذلك A (الأحمال السنوية)
    if h <= 0:
        raise ValueError("Layer thickness must be positive")
    if A <= 0:
        raise ValueError("Annual ESALs must be positive")
    if T < 0 or T > 70:
        raise ValueError("Temperature must be between 0 and 70 °C")
    if h < 0.03:
        raise ValueError("Layer thickness must be at least 0.03 m")
    
    # Apply preset-specific ranges if provided
    # تطبيق حدود خاصة بالـ preset (عند توفرها). كل مفتاح يقابل اسم/نطاق في standards.json.
    if allowed_ranges:
        def chk(name, val):
            rng = allowed_ranges.get(name)
            if rng and (val < rng[0] or val > rng[1]):
                raise ValueError(f"{name} must be between {rng[0]} and {rng[1]}")
        chk("layer_thickness_m", h)
        chk("mixture_density_ton_per_m3", rho_m)
        chk("bitumen_content_prop", Pb)
        chk("plastic_of_bitumen_prop", Pp)
        chk("rubber_of_bitumen_prop", Pr)
        chk("temperature_C", T)
        chk("annual_ESALs_million", A)

    # Warnings for high modifiers
    # تحذيرات إرشادية عند نسب معدّلات مرتفعة توصي بإجراء اختبارات معملية.
    if Pp > 0.08:
        warnings.append("Warning: High plastic content — requires lab testing")
    if Pr > 0.12:
        warnings.append("Warning: High rubber content — requires lab testing")
    
    # Additional validation logic will be added later
    return True
