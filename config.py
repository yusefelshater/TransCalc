"""
Default constants and operating ranges for the pavement model
"""

# Default calibration parameters
E0 = 3500.0  # MPa  | معامل المرونة المرجعي قبل عوامل الحرارة/المعدّلات
b = 0.025    # legacy name for temperature coefficient | الاسم القديم لمعامل حساسية الحرارة
k_temp = b   # preferred name used by presets/standards | الاسم المفضّل في المعايير
T0_C = 25.0  # reference temperature (°C) | درجة الحرارة المرجعية
p = 1.8      # تأثير البلاستيك على الصلابة (نِسبي)
r = 0.8      # تأثير المطاط على الصلابة (نِسبي)
# Strain constants
k_epsilon_t = 0.028  # Updated based on corrected formula | ثابت الشد
k_epsilon_c = 0.005  # Updated based on corrected formula | ثابت الضغط
k_f = 1.0e-3         # ثابت التعب (fatigue)
m_f = 4.0            # أس التعب
k_r = 5.0e-4         # ثابت التخدد (rutting)
m_r = 4.0            # أس التخدد

# Operating limits
MIN_Pb = 0.05     # حد أدنى لمحتوى البيتومين
MAX_Pb = 0.055    # حد أقصى لمحتوى البيتومين
MAX_Pp = 0.08     # حد أقصى لنسبة البلاستيك من البيتومين
MAX_Pr = 0.12     # حد أقصى لنسبة المطاط من البيتومين
MAX_P_MODIFIERS = 0.3  # حد أقصى لمجموع (Pp + Pr)
MIN_E = 500       # MPa | حد أدنى واقعي لمعامل المرونة
MAX_E = 15000     # MPa | حد أقصى واقعي لمعامل المرونة
