from model import run_model

# Smoke test / مثال تشغيل سريع:
# - يشغّل النموذج بقيم افتراضية للتأكد من أن الأنابيب الحسابية تعمل دون أخطاء.
# - الوحدات: L[km], W[m], h[m], rho_m[ton/m³], Pb/Pp/Pr[proportion], T[°C], A[million ESALs/year]

# Example inputs
L = 1.0  # km
W = 3.5  # m
h = 0.05  # m
rho_m = 2.4  # ton/m³
Pb = 0.055  # 5.5%
Pp = 0.05  # 5% of bitumen weight
Pr = 0.08  # 8% of bitumen weight
T = 30.0  # °C
A = 1.0  # million ESALs/year
c_agg = 100.0  # $/ton
c_bit = 500.0  # $/ton
c_pl = 200.0  # $/ton
c_rub = 300.0  # $/ton
overhead = 1000.0  # $

# Run the model
results = run_model(L, W, h, rho_m, Pb, Pp, Pr, T, A, c_agg, c_bit, c_pl, c_rub, overhead)

# Display results
for key, value in results.items():
    print(f"{key}: {value}")
