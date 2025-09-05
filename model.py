"""
Main model implementation
"""
import os
import inputs
import equations
from config import *

def plastic_feature_enabled() -> bool:
    """Return True unless PLASTIC_ENABLED env is set to a false-y value.
    Accepted true values: 1, true, yes, on. Anything else treated as False if set.
    If not set, defaults to True for backward compatibility.
    """
    try:
        v = os.environ.get("PLASTIC_ENABLED")
        if v is None:
            return True
        return str(v).strip().lower() in ("1", "true", "yes", "on")
    except Exception:
        return True

def calculate_mix(inputs: dict, catalog: dict) -> dict:
    """
    TransCalc main calculation entry.

    inputs: {
      project: {length_km, width_m, thickness_m, density_ton_per_m3},
      mix: { bitumen_prop_of_mix, rubber_prop_of_bitumen,
             aggregates_shares: {coarse, medium, fine},
             aggregates_type_ids: {coarse, medium, fine} },
      overheads: { mode: 'percent'|'per_ton'|'hybrid', components: [{id, percent?, egp_per_ton?}, ...] }
    }
    catalog: loaded costs.json

    returns dict:
      {
        quantities: { volume_m3, mix_total_ton, bitumen_ton, rubber_ton, aggregates_total_ton,
                      aggregates_breakdown: {type_id: {mass_ton, price_per_ton, subtotal}} },
        costs: {aggregates_subtotal, bitumen_subtotal, rubber_subtotal, materials_subtotal, overhead_total, grand_total},
        warnings: [ ... ]
      }
    """
    warnings: list[str] = []

    proj = (inputs or {}).get("project", {}) or {}
    mix = (inputs or {}).get("mix", {}) or {}
    ovh = (inputs or {}).get("overheads", {}) or {}
    # Optional unit-cost overrides coming from GUI (EGP/ton)
    uc = (inputs or {}).get("unit_cost_overrides", {}) or {}

    # Project geometry and density
    L_km = float(proj.get("length_km", 0.0) or 0.0)
    W_m = float(proj.get("width_m", 0.0) or 0.0)
    h_m = float(proj.get("thickness_m", 0.0) or 0.0)
    rho = float(proj.get("density_ton_per_m3", 0.0) or 0.0)

    if L_km < 0 or W_m < 0 or h_m < 0 or rho <= 0:
        warnings.append(
            f"⚠ مدخلات المشروع قد تحتوي قيماً غير صالحة (قيم سالبة أو كثافة ≤ 0). سيتم الحساب بالقيم المُدخلة وقد تكون النتائج غير واقعية. "
            f"[L_km={L_km:.3f}, W_m={W_m:.3f}, h_m={h_m:.3f}, rho={rho:.3f}]"
        )

    volume_m3 = equations.calculate_volume(L_km, W_m, h_m)
    mix_total_ton = equations.convert_m3_to_ton(volume_m3, rho)

    # Mix fractions
    Pb = float(mix.get("bitumen_prop_of_mix", 0.0) or 0.0)
    Rb = float(mix.get("rubber_prop_of_bitumen", 0.0) or 0.0)
    agg_shares = (mix.get("aggregates_shares") or {}) if isinstance(mix.get("aggregates_shares"), dict) else {}
    agg_types = (mix.get("aggregates_type_ids") or {}) if isinstance(mix.get("aggregates_type_ids"), dict) else {}

    # Soft validation via catalog ranges (if provided)
    mix_ranges = (catalog or {}).get("mix_ranges", {}) if isinstance(catalog, dict) else {}
    br = mix_ranges.get("bitumen_prop_of_mix") if isinstance(mix_ranges, dict) else None
    rr = mix_ranges.get("rubber_prop_of_bitumen") if isinstance(mix_ranges, dict) else None
    if isinstance(br, list) and len(br) == 2 and not (br[0] <= Pb <= br[1]):
        warnings.append(
            f"⚠ Bitumen content = {Pb:.3f} خارج النطاق الموصى به [{br[0]:.3f}–{br[1]:.3f}]. "
            "تم إجراء الحسابات على القيمة المُدخلة، وقد تكون النتائج غير واقعية."
        )
    if isinstance(rr, list) and len(rr) == 2 and not (rr[0] <= Rb <= rr[1]):
        warnings.append(
            f"⚠ Rubber content (of bitumen) = {Rb:.3f} خارج النطاق [{rr[0]:.3f}–{rr[1]:.3f}]. "
            "تم إجراء الحسابات على القيمة المُدخلة، وقد تكون النتائج غير واقعية."
        )

    # Normalize aggregates shares to sum = 1 - Pb
    shares_norm, scale = equations.normalize_aggregates_shares(agg_shares, Pb)
    target_sum = max(0.0, 1.0 - Pb)
    s_sum = (agg_shares.get("coarse", 0.0) or 0.0) + (agg_shares.get("medium", 0.0) or 0.0) + (agg_shares.get("fine", 0.0) or 0.0)
    if abs(s_sum - target_sum) > 1e-6:
        warnings.append("تم تطبيع نسب الركام تلقائيًا لتتوافق مع (1 − نسبة البيتومين).")

    # Mass distribution
    bitumen_ton = mix_total_ton * Pb
    rubber_ton = bitumen_ton * Rb
    bitumen_actual_ton = bitumen_ton - rubber_ton
    aggregates_total_ton = mix_total_ton - bitumen_ton
    if aggregates_total_ton < -1e-9:
        warnings.append("⚠ مجموع كتلة الركام أصبح سالبًا — تحقق من النِسَب (قد تكون نسبة البيتومين مرتفعة). تم إجراء الحساب بالقيم المُدخلة.")

    # Build aggregates catalog index
    catalog_items = {item.get("id"): item for item in (catalog.get("aggregates_catalog", []) if isinstance(catalog, dict) else []) if isinstance(item, dict)}

    # Compute per-type breakdown from categories (coarse/medium/fine)
    breakdown: dict = {}
    for cat in ("coarse", "medium", "fine"):
        share = float(shares_norm.get(cat, 0.0) or 0.0)
        mass_i = max(0.0, aggregates_total_ton * share)
        type_id = agg_types.get(cat)
        if not type_id:
            if mass_i > 0:
                warnings.append(f"لا يوجد نوع محدد لفئة الركام '{cat}'. تم احتسابه بدون سعر.")
            # still record mass with unknown price
            if mass_i > 0:
                row = breakdown.get("(unknown)", {"mass_ton": 0.0, "price_per_ton": 0.0, "subtotal": 0.0})
                row["mass_ton"] += mass_i
                breakdown["(unknown)"] = row
            continue
        item = catalog_items.get(type_id)
        price_per_ton = float(item.get("price_per_ton", 0.0) or 0.0) if isinstance(item, dict) else 0.0
        # Aggregate by type_id
        row = breakdown.get(type_id, {"mass_ton": 0.0, "price_per_ton": price_per_ton, "subtotal": 0.0})
        row["mass_ton"] += mass_i
        row["price_per_ton"] = price_per_ton  # ensure latest catalog price is reflected
        row["subtotal"] = row["mass_ton"] * price_per_ton
        breakdown[type_id] = row

    # Aggregates subtotal
    aggregates_subtotal = sum((row.get("subtotal") or 0.0) for row in breakdown.values())

    # Binder costs (allow GUI overrides when provided and positive)
    bitumen_price_override = 0.0
    rubber_price_override = 0.0
    try:
        if isinstance(uc, dict):
            v = uc.get("bitumen_price_per_ton")
            if v is not None:
                bitumen_price_override = float(v) or 0.0
            v2 = uc.get("rubber_price_per_ton")
            if v2 is not None:
                rubber_price_override = float(v2) or 0.0
    except Exception:
        bitumen_price_override = 0.0
        rubber_price_override = 0.0
    bitumen_price_catalog = float(((catalog.get("bitumen") or {}).get("price_per_ton")) or 0.0) if isinstance(catalog, dict) else 0.0
    rubber_price_catalog = float(((catalog.get("rubber") or {}).get("price_per_ton")) or 0.0) if isinstance(catalog, dict) else 0.0
    bitumen_price = bitumen_price_override if bitumen_price_override > 0.0 else bitumen_price_catalog
    rubber_price = rubber_price_override if rubber_price_override > 0.0 else rubber_price_catalog
    bitumen_subtotal = max(0.0, bitumen_actual_ton * bitumen_price)
    rubber_subtotal = max(0.0, rubber_ton * rubber_price)
    materials_subtotal = aggregates_subtotal + bitumen_subtotal + rubber_subtotal

    # Overheads
    overhead_total, total_percent_used, total_per_ton_used = equations.compute_overheads(materials_subtotal, mix_total_ton, ovh)

    # Overheads hints-based soft warnings
    ovh_cfg = catalog.get("overheads") if isinstance(catalog, dict) else None
    if isinstance(ovh_cfg, dict):
        ph = ovh_cfg.get("total_percent_hint")
        if isinstance(ph, list) and len(ph) == 2 and total_percent_used > 0.0 and not (ph[0] <= total_percent_used <= ph[1]):
            warnings.append(f"تحذير: إجمالي نسب الـ Overhead = {total_percent_used:.3f} خارج التلميح [{ph[0]:.3f}–{ph[1]:.3f}].")
        th = ovh_cfg.get("total_per_ton_hint")
        if isinstance(th, list) and len(th) == 2 and total_per_ton_used > 0.0 and not (th[0] <= total_per_ton_used <= th[1]):
            warnings.append(f"تحذير: إجمالي تكلفة الـ Overhead للطن = {total_per_ton_used:.2f} خارج التلميح [{th[0]:.2f}–{th[1]:.2f}] جنيه.")

    grand_total = materials_subtotal + overhead_total

    # Thickness soft warning based on a generic range (if not in catalog, use 0.03–0.20)
    th_min, th_max = 0.03, 0.20
    # Try to read from standards-like ranges if present
    # (kept simple; GUI will handle hard/soft distinction)
    if not (th_min <= h_m <= th_max):
        warnings.append(f"تحذير: السمك {h_m:.3f} م خارج النطاق المتوقع [{th_min:.3f}–{th_max:.3f}] م.")

    results = {
        "quantities": {
            "volume_m3": volume_m3,
            "mix_total_ton": mix_total_ton,
            "bitumen_ton": bitumen_ton,
            "rubber_ton": rubber_ton,
            "aggregates_total_ton": aggregates_total_ton,
            "aggregates_breakdown": breakdown,
        },
        "costs": {
            "aggregates_subtotal": aggregates_subtotal,
            "bitumen_subtotal": bitumen_subtotal,
            "rubber_subtotal": rubber_subtotal,
            "materials_subtotal": materials_subtotal,
            "overhead_total": overhead_total,
            "grand_total": grand_total,
        },
        "warnings": warnings,
    }

    return results

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
    # Soft-validate inputs (never raises)
    validation_warnings = inputs.validate_inputs(L, W, h, rho_m, Pb, Pp, Pr, T, A, allowed_ranges)
    # Respect global plastic disable via environment variable (affects mass, modulus, and costs)
    if not plastic_feature_enabled():
        Pp = 0.0
        c_pl = 0.0
    
    # Calculate volume and mass
    V = equations.calculate_volume(L, W, h)
    M = equations.calculate_mass(V, rho_m)
    M_b, M_p, M_r, M_agg, M_bit_new = equations.calculate_binder_masses(M, Pb, Pp, Pr)
    
    # Soft-check for negative effective bitumen mass
    warn_list: list[str] = []
    if M_bit_new < 0:
        warn_list.append("⚠ الكتلة الفعلية للبيتومين أصبحت سالبة بعد الاستبدالات — الحسابات ستستمر بالقيم المُدخلة وقد تكون النتائج غير واقعية.")
    
    # Resolve effective coefficients (presets can override defaults)
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
    fT = equations.temp_factor(T, k_temp_local, T0_local)
    # Calculate modulus using the safe formula (modifiers act on binder fraction)
    E = E0_local * fT * (1 + p_local * Pp) / (1 + r_local * Pr)
    
    # Clamp E to realistic bounds
    E = max(MIN_E_local, min(E, MAX_E_local))
    
    # Calculate strains
    epsilon_t = equations.tensile_strain(k_eps_t_local, E, h)
    epsilon_c = equations.compressive_strain(k_eps_c_local, E)
    
    # If target design life is provided, calculate k_f and k_r
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
    capacities = equations.capacities(epsilon_t, epsilon_c, k_f_val, m_f_local, k_r_val, m_r_local)
    Nf = capacities['Nf']
    Nr = capacities['Nr']
    
    # Calculate life in years
    life_results = equations.life_years(Nf, Nr, A)
    life_f = life_results['fatigue_life']
    life_r = life_results['rutting_life']
    design_life = life_results['design_life']
    
    # Calculate costs
    cost_agg = equations.cost_aggregate(M_agg, c_agg)
    # Pass original bitumen mass (before modifiers) so function subtracts replacements once
    cost_bit = equations.cost_bitumen(M_b, M_p, M_r, c_bit)
    cost_pl = equations.cost_plastic(M_p, c_pl)
    cost_rub = equations.cost_rubber(M_r, c_rub)
    material_cost = cost_agg + cost_bit + cost_pl + cost_rub
    # Overhead is an additive EGP amount
    total_cost = material_cost + overhead
    
    # Calculate useful metrics
    area = L * 1000 * W  # m²
    # Safe divides to avoid ZeroDivisionError while preserving run continuity
    if area <= 0:
        warn_list.append(f"⚠ المساحة (L*W) ≤ 0 [L={L:.3f} km, W={W:.3f} m]. سيتم عرض التكلفة/م² = 0 مؤقتاً.")
        cost_per_m2 = 0.0
    else:
        cost_per_m2 = total_cost / area
    if M <= 0:
        warn_list.append("⚠ الكتلة الكلية للخلطة ≤ 0 طن. سيتم عرض التكلفة/طن = 0 مؤقتاً.")
        cost_per_ton = 0.0
    else:
        cost_per_ton = total_cost / M
    
    # Add warnings for outputs
    warnings = []
    if design_life > 100:
        warnings.append("Design life exceeds 100 years — check constants/strains.")
    if epsilon_t < 1e-6 or epsilon_t > 1e-3:
        warnings.append("Tensile strain is outside normal range (1e-6 to 1e-3) — check k_epsilon_t, E, and h.")
    if epsilon_c < 1e-6 or epsilon_c > 1e-3:
        warnings.append("Compressive strain is outside normal range (1e-6 to 1e-3) — check k_epsilon_c and E.")
    if epsilon_t < 1e-6 or epsilon_t > 1e-3 or epsilon_c < 1e-6 or epsilon_c > 1e-3:
        warnings.append("Strains are outside normal range — check k_epsilon_t, k_epsilon_c, E, and h.")
    
    # Merge warnings: validation + soft-checks + output behavior
    warnings = (validation_warnings or []) + warn_list + warnings
    
    # Create results dictionary
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
