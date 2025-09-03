"""
Default constants and operating ranges for the pavement model
"""

# Default calibration parameters
E0 = 3500.0  # MPa
b = 0.025  # legacy name for temperature coefficient
k_temp = b   # preferred name used by presets/standards
T0_C = 25.0  # reference temperature (°C)
p = 1.8
r = 0.8
# Strain constants
k_epsilon_t = 0.028  # Updated based on corrected formula
k_epsilon_c = 0.005  # Updated based on corrected formula
k_f = 1.0e-3
m_f = 4.0
k_r = 5.0e-4
m_r = 4.0

# Operating limits
MIN_Pb = 0.05
MAX_Pb = 0.055
MAX_Pp = 0.08
MAX_Pr = 0.12
MAX_P_MODIFIERS = 0.3
MIN_E = 500  # MPa
MAX_E = 15000  # MPa
