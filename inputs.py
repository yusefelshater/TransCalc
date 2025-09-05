"""
Input validation and unit conversion functions
"""

from config import *

def validate_inputs(L: float, W: float, h: float, rho_m: float, Pb: float,
                   Pp: float, Pr: float, T: float, A: float, allowed_ranges: dict | None = None) -> list[str]:
    """
    Soft-validate inputs against operational limits and preset ranges.
    Never raises; returns a list of warning strings while computations proceed
    using the user-entered values as-is.
    """
    warnings: list[str] = []

    # Helper to format a range warning
    def warn_range(label: str, val: float, lo: float, hi: float):
        warnings.append(
            f"⚠ {label} = {val:.4g} خارج النطاق [{lo:.4g}–{hi:.4g}]. "
            f"تم إجراء الحسابات على القيمة المُدخلة، وقد تكون النتائج غير واقعية."
        )

    # Legacy global limits (soft)
    if not (0 < Pb <= MAX_Pb):
        warn_range("Bitumen content (Pb)", Pb, MIN_Pb, MAX_Pb)
    if Pp < 0 or Pp > MAX_Pp:
        warn_range("Plastic of bitumen (Pp)", Pp, 0.0, MAX_Pp)
    if Pr < 0 or Pr > MAX_Pr:
        warn_range("Rubber of bitumen (Pr)", Pr, 0.0, MAX_Pr)
    if Pp + Pr > MAX_P_MODIFIERS:
        warnings.append(
            f"⚠ Pp + Pr = {Pp+Pr:.4g} يتجاوز الحد {MAX_P_MODIFIERS}."
            " تم إجراء الحسابات على القيم المدخلة وقد تكون النتائج غير واقعية."
        )
    if h <= 0:
        warnings.append("⚠ Layer thickness <= 0. الحسابات ستُجرى بالقيمة المُدخلة وقد تكون النتائج غير واقعية.")
    if A <= 0:
        warnings.append("⚠ Annual ESALs <= 0. الحسابات ستُجرى بالقيمة المُدخلة وقد تكون النتائج غير واقعية.")
    if T < 0 or T > 70:
        warn_range("Temperature (°C)", T, 0.0, 70.0)
    if h < 0.03:
        warnings.append("⚠ Layer thickness < 0.03 m. قد تكون النتائج غير واقعية.")

    # Apply preset-specific ranges if provided (soft)
    if allowed_ranges:
        def chk(name, val, label):
            rng = allowed_ranges.get(name)
            if rng and (val < rng[0] or val > rng[1]):
                warn_range(label, val, rng[0], rng[1])
        chk("layer_thickness_m", h, "Layer thickness (m)")
        chk("mixture_density_ton_per_m3", rho_m, "Mixture density (ton/m³)")
        chk("bitumen_content_prop", Pb, "Bitumen content (Pb)")
        chk("plastic_of_bitumen_prop", Pp, "Plastic of bitumen (Pp)")
        chk("rubber_of_bitumen_prop", Pr, "Rubber of bitumen (Pr)")
        chk("temperature_C", T, "Temperature (°C)")
        chk("annual_ESALs_million", A, "Annual ESALs (million)")

    # Hints for high modifiers
    if Pp > 0.08:
        warnings.append("⚠ نسبة البلاستيك مرتفعة — يُنصح باختبارات معملية.")
    if Pr > 0.12:
        warnings.append("⚠ نسبة المطاط مرتفعة — يُنصح باختبارات معملية.")
    
    return warnings
